"""Tests for BatchProcessor — LLM calls are mocked via classifier."""

from unittest.mock import MagicMock
from src.models.batch_processor import BatchProcessor
from src.models.schemas import ProtestEventPrediction


def _mock_classifier():
    clf = MagicMock()
    clf.classify_zero_shot.return_value = ProtestEventPrediction(
        event_type="demonstration_march",
        confidence_score=0.85,
        reasoning="Mock.",
        schema_valid=True,
        key_indicators=["gathered"],
    )
    clf.classify_with_cot.return_value = clf.classify_zero_shot.return_value
    return clf


def test_process_events_returns_correct_count():
    clf = _mock_classifier()
    processor = BatchProcessor(clf)
    texts = ["text one", "text two", "text three"]
    results = processor.process_events(texts)
    assert len(results) == 3


def test_process_events_zero_shot_calls_classifier():
    clf = _mock_classifier()
    processor = BatchProcessor(clf)
    processor.process_events(["some text"], method="zero_shot")
    clf.classify_zero_shot.assert_called_once_with("some text")


def test_process_events_cot_calls_classifier():
    clf = _mock_classifier()
    processor = BatchProcessor(clf)
    processor.process_events(["some text"], method="cot")
    clf.classify_with_cot.assert_called_once_with("some text")


def test_process_events_error_recovery():
    clf = MagicMock()
    clf.classify_zero_shot.side_effect = RuntimeError("API down")
    processor = BatchProcessor(clf)
    results = processor.process_events(["text"])
    assert results[0].event_type == "ERROR"


def test_to_dataframe_shape():
    clf = _mock_classifier()
    processor = BatchProcessor(clf)
    preds = processor.process_events(["a", "b"])
    df = processor.to_dataframe(preds)
    assert len(df) == 2
    assert "event_type" in df.columns
