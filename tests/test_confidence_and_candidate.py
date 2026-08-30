"""Tests for per-field confidence handling and the candidate-tier convention."""

from src.acquisition.storage import (
    field_confidence_distribution,
    flatten_for_csv,
    save_results,
)
from src.annotation.import_annotations import process_task


def _event(**kw):
    event = {
        "event_type": "riot",
        "country": "Nigeria",
        "confidence": "high",
        "field_confidence": {
            "event_type": "high",
            "actors": "medium",
            "location": "high",
            "date": "low",
            "casualties": "low",
        },
    }
    event.update(kw)
    return event


class TestFieldConfidenceFlattening:
    def test_fc_columns_populated(self):
        row = flatten_for_csv(_event())
        assert row["fc_event_type"] == "high"
        assert row["fc_actors"] == "medium"
        assert row["fc_date"] == "low"

    def test_missing_field_confidence_gives_blanks(self):
        row = flatten_for_csv({"event_type": "riot", "country": "Kenya"})
        assert row["fc_event_type"] == ""
        assert row["fc_casualties"] == ""

    def test_distribution_aggregates(self):
        events = [_event(), _event(), {"event_type": "vigil"}]
        dist = field_confidence_distribution(events)
        assert dist["event_type"] == {"high": 2}
        assert dist["date"] == {"low": 2}

    def test_distribution_tolerates_malformed(self):
        events = [{"field_confidence": "high"}, {"field_confidence": {"date": None}}]
        assert field_confidence_distribution(events) == {}


class TestCandidateTier:
    def test_save_results_stamps_candidate(self, tmp_path):
        events = [_event(), _event(validation_status="reviewed")]
        save_results(events, output_dir=tmp_path, run_id="t1", domain="protest")
        # in-place stamping: unset events become candidate, set ones untouched
        assert events[0]["validation_status"] == "candidate"
        assert events[1]["validation_status"] == "reviewed"

    def test_summary_counts_validation_status(self, tmp_path):
        import json

        events = [_event(), _event()]
        out = save_results(events, output_dir=tmp_path, run_id="t2", domain="protest")
        summary = json.loads((out / "summary_t2.json").read_text())
        assert summary["events_by_validation_status"] == {"candidate": 2}
        assert summary["field_confidence_distribution"]["actors"] == {"medium": 2}

    def test_csv_has_validation_status(self, tmp_path):
        out = save_results(
            [_event()], output_dir=tmp_path, run_id="t3", domain="protest"
        )
        header, row = (out / "events_t3.csv").read_text().splitlines()[:2]
        assert "validation_status" in header
        assert "candidate" in row


def _task(verdict, extra_results=None, source_event=None):
    import json

    results = [
        {
            "from_name": "is_protest",
            "type": "choices",
            "value": {"choices": [verdict]},
        }
    ]
    for name, choices in (extra_results or {}).items():
        results.append(
            {"from_name": name, "type": "choices", "value": {"choices": choices}}
        )
    return {
        "id": 1,
        "data": {"_source_event": json.dumps(source_event or _event())},
        "annotations": [
            {
                "was_cancelled": False,
                "skipped": False,
                "result": results,
                "completed_by": {"id": 7},
            }
        ],
    }


class TestAnnotationPromotion:
    def test_confirmed_event_promoted_to_reviewed(self):
        event = process_task(_task("yes"))
        assert event["validation_status"] == "reviewed"
        assert event["_is_false_positive"] is False

    def test_rejected_event_demoted(self):
        event = process_task(_task("no"))
        assert event["validation_status"] == "rejected"
        assert event["_is_false_positive"] is True


class TestIssueTagsCorrection:
    def test_corrected_tags_applied(self):
        event = process_task(
            _task(
                "yes",
                extra_results={"corrected_issue_tags": ["elections", "land"]},
                source_event=_event(issue_tags=["economy_jobs"]),
            )
        )
        assert event["issue_tags"] == ["elections", "land"]
        assert event["_issue_tags_corrected"] is True

    def test_no_tags_supported_means_empty_list(self):
        event = process_task(
            _task(
                "yes",
                extra_results={"corrected_issue_tags": ["no_tags_supported"]},
                source_event=_event(issue_tags=["economy_jobs"]),
            )
        )
        assert event["issue_tags"] == []
        assert event["_issue_tags_corrected"] is True

    def test_untouched_widget_keeps_llm_tags(self):
        event = process_task(_task("yes", source_event=_event(issue_tags=["land"])))
        assert event["issue_tags"] == ["land"]
        assert "_issue_tags_corrected" not in event


class TestFieldVerdicts:
    def test_flagged_fields_marked_incorrect(self):
        event = process_task(
            _task(
                "yes",
                extra_results={"extraction_errors": ["wrong_date", "wrong_casualties"]},
            )
        )
        verdicts = event["_field_verdicts"]
        assert verdicts["date"] == "incorrect"
        assert verdicts["casualties"] == "incorrect"
        assert verdicts["event_type"] == "correct"

    def test_wrong_organizer_maps_to_actors(self):
        event = process_task(
            _task("yes", extra_results={"extraction_errors": ["wrong_organizer"]})
        )
        assert event["_field_verdicts"]["actors"] == "incorrect"

    def test_no_errors_all_correct(self):
        event = process_task(_task("yes"))
        assert set(event["_field_verdicts"].values()) == {"correct"}
        assert set(event["_field_verdicts"]) == {
            "event_type",
            "actors",
            "location",
            "date",
            "casualties",
        }


class TestAnnotationExportDisplay:
    def test_new_display_fields_present(self):
        from src.annotation.export_for_annotation import _build_task

        task = _build_task(_event(issue_tags=["elections"], _article_text="text " * 50))
        assert task["data"]["issue_tags_display"] == "elections"
        assert task["data"]["field_confidence_display"] == (
            "event_type: high, actors: medium, location: high, "
            "date: low, casualties: low"
        )

    def test_display_defaults(self):
        from src.annotation.export_for_annotation import _build_task

        event = _event(issue_tags=None)
        del event["field_confidence"]
        task = _build_task(event)
        assert task["data"]["issue_tags_display"] == "(none)"
        assert task["data"]["field_confidence_display"] == "(not rated)"
