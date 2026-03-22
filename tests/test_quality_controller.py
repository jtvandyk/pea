"""Tests for QualityController."""

from src.models.quality_controller import QualityController
from src.models.schemas import ProtestEventPrediction


def _make_predictions(valid_count, invalid_count):
    preds = []
    for _ in range(valid_count):
        preds.append(ProtestEventPrediction(
            event_type="demonstration_march",
            confidence_score=0.9,
            reasoning="valid",
            schema_valid=True,
            key_indicators=["gathered"],
        ))
    for _ in range(invalid_count):
        preds.append(ProtestEventPrediction(
            event_type="UNCLASSIFIABLE",
            confidence_score=0.1,
            reasoning="invalid",
            schema_valid=False,
            key_indicators=[],
        ))
    return preds


def test_schema_validity_report_counts():
    preds = _make_predictions(valid_count=8, invalid_count=2)
    qc = QualityController(preds)
    report = qc.schema_validity_report()
    assert report["valid_schemas"] == 8
    assert report["invalid_schemas"] == 2
    assert report["validity_rate"] == 0.8


def test_schema_validity_flag_triggered():
    preds = _make_predictions(valid_count=5, invalid_count=6)
    qc = QualityController(preds)
    report = qc.schema_validity_report()
    assert report["flag_for_review"] is True


def test_confidence_distribution_keys():
    preds = _make_predictions(valid_count=5, invalid_count=5)
    qc = QualityController(preds)
    dist = qc.confidence_distribution()
    for key in ("mean_confidence", "median_confidence", "std_confidence"):
        assert key in dist


def test_generate_quality_report_structure():
    preds = _make_predictions(valid_count=3, invalid_count=1)
    qc = QualityController(preds)
    report = qc.generate_quality_report()
    assert "schema_validity" in report
    assert "confidence_distribution" in report
    assert "total_predictions" in report
    assert report["total_predictions"] == 4
