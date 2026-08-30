"""Tests for dissent-repression linked pairs (plan §4 decision 2, NAVCO 3.0)."""

from src.acquisition.dissent_repression import (
    derive_linked_repression_events,
    event_uid,
    link_repression_to_protests,
)


def _protest(**kw):
    event = {
        "event_type": "demonstration_march",
        "event_date": "2026-08-10",
        "country": "Uganda",
        "city": "Kampala",
        "state_response": "teargas",
        "organizer": "NUP",
        "state_actors": ["Uganda Police Force"],
        "arrests": "12",
        "confidence": "high",
        "article_url": "http://x.test/protest",
    }
    event.update(kw)
    return event


def _repression(**kw):
    event = {
        "event_type": "assembly_ban_curfew",
        "event_date": "2026-08-11",
        "country": "Uganda",
        "city": "Kampala",
        "article_url": "http://x.test/ban",
    }
    event.update(kw)
    return event


class TestEventUid:
    def test_deterministic(self):
        a, b = _protest(), _protest()
        assert event_uid(a) == event_uid(b)
        assert a["event_uid"].startswith("evt_")

    def test_existing_uid_kept(self):
        event = _protest(event_uid="evt_custom")
        assert event_uid(event) == "evt_custom"


class TestDerivation:
    def test_teargas_derives_pro_government_violence(self):
        protest = _protest()
        (twin,) = derive_linked_repression_events([protest])
        assert twin["event_type"] == "pro_government_violence"
        assert twin["derived_from_protest"] is True
        assert twin["country"] == "Uganda"
        assert twin["arrests"] == "12"
        assert twin["perpetrator_name"] == "Uganda Police Force"
        assert twin["target_name"] == "NUP"

    def test_pair_id_shared_both_ways(self):
        protest = _protest()
        (twin,) = derive_linked_repression_events([protest])
        assert protest["dissent_repression_pair_id"] == (
            twin["dissent_repression_pair_id"]
        )
        assert twin["event_uid"] in protest["linked_event_ids"]
        assert protest["event_uid"] in twin["linked_event_ids"]

    def test_response_type_mapping(self):
        cases = {
            "arrests": "activist_arrest_prosecution",
            "ban": "assembly_ban_curfew",
            "internet_shutdown": "internet_shutdown",
            "organisational_dissolution": "civil_society_restriction",
        }
        for response, expected in cases.items():
            (twin,) = derive_linked_repression_events(
                [_protest(state_response=response)]
            )
            assert twin["event_type"] == expected, response

    def test_non_repressive_response_derives_nothing(self):
        for response in ("none", "monitoring", "unknown", None, ""):
            assert (
                derive_linked_repression_events([_protest(state_response=response)])
                == []
            )


class TestLinking:
    def test_links_within_window(self):
        protest, rep = _protest(), _repression()
        assert link_repression_to_protests([rep], [protest]) == 1
        assert rep["dissent_repression_pair_id"] == (
            protest["dissent_repression_pair_id"]
        )
        assert protest["event_uid"] in rep["linked_event_ids"]

    def test_window_boundary(self):
        protest = _protest()
        inside = _repression(event_date="2026-08-13")  # +3 days
        outside = _repression(event_date="2026-08-14")  # +4 days
        assert link_repression_to_protests([inside], [protest]) == 1
        assert link_repression_to_protests([outside], [_protest()]) == 0

    def test_different_country_not_linked(self):
        assert (
            link_repression_to_protests([_repression(country="Kenya")], [_protest()])
            == 0
        )

    def test_conflicting_city_not_linked(self):
        assert (
            link_repression_to_protests([_repression(city="Gulu")], [_protest()]) == 0
        )

    def test_null_city_compatible(self):
        assert link_repression_to_protests([_repression(city=None)], [_protest()]) == 1

    def test_closest_protest_wins(self):
        near = _protest(event_date="2026-08-11", article_url="http://x.test/near")
        far = _protest(event_date="2026-08-09", article_url="http://x.test/far")
        rep = _repression()
        link_repression_to_protests([rep], [far, near])
        assert rep["dissent_repression_pair_id"] == near["dissent_repression_pair_id"]
        assert "dissent_repression_pair_id" not in far

    def test_derived_twin_skipped(self):
        protest = _protest()
        (twin,) = derive_linked_repression_events([protest])
        # twin already linked at derivation; linking pass must not re-link
        assert link_repression_to_protests([twin], [protest]) == 0

    def test_unparseable_date_skipped(self):
        assert (
            link_repression_to_protests(
                [_repression(event_date="last week")], [_protest()]
            )
            == 0
        )


class TestPipelineIntegration:
    def test_multi_domain_runs_linking_and_saves_after(self, tmp_path, monkeypatch):
        """Stage 4.8 runs between extraction and storage; derived twins land
        in the saved state_repression output."""
        import src.acquisition.pipeline as pipeline

        class FakeFilter:
            degraded_mode = False

            def __init__(self, **kwargs):
                pass

            def filter(self, articles):
                return articles, []

        def fake_extract(articles, codebook_path=None, **kwargs):
            if "repression" in str(codebook_path):
                return [_repression()], []
            return [_protest()], []

        saved = {}

        def fake_save(events, domain="protest", **kwargs):
            saved[domain] = list(events)
            return tmp_path / domain

        monkeypatch.setattr(pipeline, "scrape_articles", lambda a, **k: a)
        monkeypatch.setattr(pipeline, "RelevanceFilter", FakeFilter)
        monkeypatch.setattr(pipeline, "extract_events", fake_extract)
        monkeypatch.setattr(pipeline, "save_results", fake_save)
        monkeypatch.setattr(
            pipeline,
            "_discover_articles",
            lambda **k: [{"url": "http://x", "title": "t", "text": "w" * 200}],
        )

        pipeline.run_pipeline_multi_codebook(
            domains=["protest", "state_repression"],
            countries=["UG"],
            days=1,
            output_dir=tmp_path,
            translate=False,
            geocode=False,
        )

        rep_events = saved["state_repression"]
        assert any(e.get("derived_from_protest") for e in rep_events)
        extracted = [e for e in rep_events if not e.get("derived_from_protest")]
        assert extracted[0]["dissent_repression_pair_id"]
        assert saved["protest"][0]["dissent_repression_pair_id"]
