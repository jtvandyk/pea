"""
Quality control and monitoring for protest event classification.
"""

import datetime
from typing import List, Dict, Any
from src.models.schemas import ProtestEventPrediction


class QualityController:
    """Monitor classification quality and surface issues."""

    def __init__(self, predictions: List[ProtestEventPrediction]):
        self.predictions = predictions

    def schema_validity_report(self) -> Dict[str, Any]:
        valid = sum(1 for p in self.predictions if p.schema_valid)
        total = len(self.predictions)
        return {
            "valid_schemas": valid,
            "invalid_schemas": total - valid,
            "validity_rate": valid / total if total else 0,
            "flag_for_review": (total - valid) > total * 0.1,
        }

    def confidence_distribution(self) -> Dict[str, Any]:
        import numpy as np

        scores = [p.confidence_score for p in self.predictions]
        if not scores:
            return {}
        arr = np.array(scores)
        return {
            "mean_confidence": float(arr.mean()),
            "median_confidence": float(np.median(arr)),
            "std_confidence": float(arr.std()),
            "min_confidence": float(arr.min()),
            "max_confidence": float(arr.max()),
            "percentile_25": float(np.percentile(arr, 25)),
            "percentile_75": float(np.percentile(arr, 75)),
        }

    def generate_quality_report(self) -> Dict[str, Any]:
        return {
            "schema_validity": self.schema_validity_report(),
            "confidence_distribution": self.confidence_distribution(),
            "total_predictions": len(self.predictions),
            "timestamp": datetime.datetime.now().isoformat(),
        }
