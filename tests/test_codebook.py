"""Tests for CodebookManager."""

import pytest
from src.utils.codebook_manager import CodebookManager
from src.models.schemas import ProtestEventPrediction


def test_codebook_loads(codebook):
    assert len(codebook.event_definitions) > 0


def test_codebook_has_expected_types(codebook):
    expected = {
        "demonstration_march", "strike_boycott", "riot",
        "occupation_seizure", "confrontation", "petition_signature"
    }
    assert expected.issubset(set(codebook.event_definitions.keys()))


def test_get_prompt_context_contains_definitions(codebook):
    context = codebook.get_prompt_context()
    assert "EVENT TYPE DEFINITIONS" in context
    assert "demonstration_march" in context.lower() or "demonstration" in context.lower()


def test_validate_prediction_valid(codebook):
    pred = ProtestEventPrediction(
        event_type="demonstration_march",
        confidence_score=0.90,
        reasoning="Clear case.",
        schema_valid=True,
        key_indicators=["gathered"],
    )
    assert codebook.validate_prediction(pred) is True


def test_validate_prediction_below_threshold(codebook):
    pred = ProtestEventPrediction(
        event_type="demonstration_march",
        confidence_score=0.10,
        reasoning="Very uncertain.",
        schema_valid=False,
        key_indicators=[],
    )
    assert codebook.validate_prediction(pred) is False


def test_validate_prediction_unknown_type(codebook):
    pred = ProtestEventPrediction(
        event_type="UNKNOWN_TYPE",
        confidence_score=0.99,
        reasoning="Doesn't exist.",
        schema_valid=False,
        key_indicators=[],
    )
    assert codebook.validate_prediction(pred) is False
