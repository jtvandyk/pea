"""
Shared pytest fixtures for protest event classification tests.
All LLM calls are mocked — no real API or Ollama connection required.
"""

import pytest
from unittest.mock import MagicMock, patch
from src.models.schemas import ProtestEventPrediction
from src.utils.codebook_manager import CodebookManager
from src.utils.prompt_builder import ProtestEventPrompter


CODEBOOK_PATH = "configs/protest_codebook.yaml"


@pytest.fixture
def codebook():
    return CodebookManager(CODEBOOK_PATH)


@pytest.fixture
def prompter(codebook):
    return ProtestEventPrompter(codebook)


@pytest.fixture
def sample_prediction():
    return ProtestEventPrediction(
        event_type="demonstration_march",
        confidence_score=0.92,
        reasoning="Workers gathered peacefully with signs and chants.",
        schema_valid=True,
        key_indicators=["gathered", "demanding", "peaceful"],
    )


@pytest.fixture
def low_confidence_prediction():
    return ProtestEventPrediction(
        event_type="riot",
        confidence_score=0.45,
        reasoning="Ambiguous description.",
        schema_valid=False,
        key_indicators=[],
    )


@pytest.fixture
def sample_predictions(sample_prediction, low_confidence_prediction):
    return [sample_prediction, low_confidence_prediction]


MOCK_LLM_JSON = """{
  "event_type": "demonstration_march",
  "confidence_score": 0.88,
  "reasoning": "Workers gathered peacefully outside factory.",
  "schema_valid": true,
  "key_indicators": ["gathered", "workers", "peacefully"]
}"""
