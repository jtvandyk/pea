"""Tests for LLMClassifier — all LLM calls are mocked."""

from unittest.mock import patch, MagicMock
from src.models.llm_classifier import LLMClassifier
from tests.conftest import MOCK_LLM_JSON


def _make_classifier(codebook):
    clf = LLMClassifier.__new__(LLMClassifier)
    clf.model_name = "llama"
    clf.codebook = codebook
    from src.utils.prompt_builder import ProtestEventPrompter
    clf.prompter = ProtestEventPrompter(codebook)
    clf.api_keys = {}
    clf.ollama_model = "llama3"
    clf.ollama_base_url = "http://localhost:11434"
    clf.llm = lambda prompt: MOCK_LLM_JSON
    return clf


def test_zero_shot_returns_prediction(codebook):
    clf = _make_classifier(codebook)
    pred = clf.classify_zero_shot("Workers gathered outside factory.")
    assert pred.event_type == "demonstration_march"
    assert pred.confidence_score == 0.88


def test_zero_shot_invalid_json_returns_unclassifiable(codebook):
    clf = _make_classifier(codebook)
    clf.llm = lambda prompt: "not json at all"
    pred = clf.classify_zero_shot("Some text.")
    assert pred.event_type == "UNCLASSIFIABLE"
    assert pred.confidence_score == 0.0


def test_cot_returns_prediction(codebook):
    clf = _make_classifier(codebook)
    pred = clf.classify_with_cot("Students sat in at university building.")
    assert pred.event_type == "demonstration_march"


def test_unknown_model_raises(codebook):
    import pytest
    with pytest.raises(ValueError, match="Unknown model"):
        LLMClassifier("gpt-999", codebook)
