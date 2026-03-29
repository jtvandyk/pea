"""
Batch processor for protest event classification.
Handles multiple events with error recovery and progress reporting.
"""

from typing import List
from src.models.schemas import ProtestEventPrediction
from src.models.llm_classifier import LLMClassifier


class BatchProcessor:
    """Process multiple protest event texts through the classifier."""

    def __init__(self, classifier: LLMClassifier, max_batch_size: int = 50):
        self.classifier = classifier
        self.max_batch_size = max_batch_size

    def process_events(
        self,
        texts: List[str],
        method: str = "zero_shot",
    ) -> List[ProtestEventPrediction]:
        """
        Classify a list of texts.

        Args:
            texts: List of event description strings.
            method: One of "zero_shot", "few_shot", "cot".

        Returns:
            List of ProtestEventPrediction, one per input text.
        """
        predictions = []

        for i, text in enumerate(texts):
            try:
                if method == "zero_shot":
                    pred = self.classifier.classify_zero_shot(text)
                elif method == "cot":
                    pred = self.classifier.classify_with_cot(text)
                elif method == "few_shot":
                    # few_shot requires examples; fall back to zero_shot until
                    # examples are wired in by the caller
                    pred = self.classifier.classify_zero_shot(text)
                else:
                    raise ValueError(f"Unknown method: {method}")

                predictions.append(pred)

                if (i + 1) % 10 == 0:
                    print(f"Processed {i + 1}/{len(texts)} events")

            except Exception as e:
                print(f"Error on text {i}: {e}")
                predictions.append(
                    ProtestEventPrediction(
                        event_type="ERROR",
                        confidence_score=0.0,
                        reasoning=str(e),
                        schema_valid=False,
                        key_indicators=[],
                    )
                )

        return predictions

    def to_dataframe(self, predictions: List[ProtestEventPrediction]):
        """Convert predictions to a pandas DataFrame."""
        import pandas as pd

        return pd.DataFrame(
            [
                {
                    "event_type": p.event_type,
                    "confidence": p.confidence_score,
                    "reasoning": p.reasoning,
                    "schema_valid": p.schema_valid,
                    "num_indicators": len(p.key_indicators),
                }
                for p in predictions
            ]
        )
