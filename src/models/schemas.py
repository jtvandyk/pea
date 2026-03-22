"""
Pydantic schemas for protest event classification.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class EventDefinition(BaseModel):
    """Event type definition with examples."""
    name: str
    definition: str
    positive_examples: List[str]
    negative_examples: List[str]
    decision_rules: List[str]
    confidence_threshold: float = 0.70


class ProtestEventPrediction(BaseModel):
    """LLM prediction for a single protest event."""
    event_type: str = Field(description="Classified event type")
    confidence_score: float = Field(description="LLM confidence (0-1)", ge=0, le=1)
    reasoning: str = Field(description="Why this classification")
    schema_valid: bool = Field(default=False, description="Matches codebook schema")
    key_indicators: List[str] = Field(description="Text spans supporting classification")
    alternative_types: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Other possible classifications with scores"
    )


class ProtestEventBatch(BaseModel):
    """Batch of predictions."""
    predictions: List[ProtestEventPrediction]
    batch_id: str
    model_used: str
    timestamp: str
