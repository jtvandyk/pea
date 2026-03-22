"""Tests for PredictionPoweredInference."""

from src.models.ppi_estimator import PredictionPoweredInference
from src.models.schemas import ProtestEventPrediction


def _make_predictions():
    types = ["demonstration_march", "demonstration_march", "riot", "strike_boycott", "UNCLASSIFIABLE"]
    return [
        ProtestEventPrediction(
            event_type=t,
            confidence_score=0.8,
            reasoning="test",
            schema_valid=True,
            key_indicators=[],
        )
        for t in types
    ]


def test_estimate_prevalence_correct_fraction():
    preds = _make_predictions()
    ppi = PredictionPoweredInference(preds)
    result = ppi.estimate_prevalence("demonstration_march")
    assert result["estimate"] == 0.4  # 2 out of 5
    assert result["n_classified"] == 2
    assert result["total_n"] == 5


def test_estimate_prevalence_ci_bounds():
    preds = _make_predictions()
    ppi = PredictionPoweredInference(preds)
    result = ppi.estimate_prevalence("demonstration_march")
    assert result["ci_lower"] <= result["estimate"] <= result["ci_upper"]


def test_estimate_prevalence_empty():
    ppi = PredictionPoweredInference([])
    result = ppi.estimate_prevalence("demonstration_march")
    assert result["total_n"] == 0


def test_estimate_by_confidence():
    preds = _make_predictions()
    ppi = PredictionPoweredInference(preds)
    result = ppi.estimate_by_confidence()
    assert result["high_confidence"] + result["medium_confidence"] + result["low_confidence"] == 5


def test_estimate_correlation():
    preds = _make_predictions()
    ppi = PredictionPoweredInference(preds)
    external = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = ppi.estimate_correlation(preds, external)
    assert "correlation" in result
    assert "p_value" in result
