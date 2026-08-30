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


class TestAnnotationPromotion:
    def _task(self, verdict):
        import json

        return {
            "id": 1,
            "data": {"_source_event": json.dumps(_event())},
            "annotations": [
                {
                    "was_cancelled": False,
                    "skipped": False,
                    "result": [
                        {
                            "from_name": "is_protest",
                            "type": "choices",
                            "value": {"choices": [verdict]},
                        }
                    ],
                    "completed_by": {"id": 7},
                }
            ],
        }

    def test_confirmed_event_promoted_to_reviewed(self):
        event = process_task(self._task("yes"))
        assert event["validation_status"] == "reviewed"
        assert event["_is_false_positive"] is False

    def test_rejected_event_demoted(self):
        event = process_task(self._task("no"))
        assert event["validation_status"] == "rejected"
        assert event["_is_false_positive"] is True
