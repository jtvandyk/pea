"""Tests for Pydantic schemas."""

import pytest
from pydantic import ValidationError
from src.models.schemas import ProtestEventPrediction, EventDefinition


def test_protest_event_prediction_valid():
    pred = ProtestEventPrediction(
        event_type="demonstration_march",
        confidence_score=0.85,
        reasoning="Clear march with demands.",
        schema_valid=True,
        key_indicators=["marched", "demanded"],
    )
    assert pred.event_type == "demonstration_march"
    assert pred.confidence_score == 0.85


def test_confidence_score_bounds():
    with pytest.raises(ValidationError):
        ProtestEventPrediction(
            event_type="riot",
            confidence_score=1.5,  # out of bounds
            reasoning="x",
            schema_valid=False,
            key_indicators=[],
        )


def test_event_definition_defaults():
    defn = EventDefinition(
        name="test",
        definition="A test definition.",
        positive_examples=[],
        negative_examples=[],
        decision_rules=[],
    )
    assert defn.confidence_threshold == 0.70
