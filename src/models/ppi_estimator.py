"""
Prediction-Powered Inference (PPI) for protest event classification.
Based on Angelopoulos et al. (2023) - accounts for LLM misclassification
when generating statistically valid estimates.
"""

from typing import List, Dict, Any
from src.models.schemas import ProtestEventPrediction


class PredictionPoweredInference:
    """
    Generate valid statistical estimates that account for LLM error rates.

    Reference: Angelopoulos et al. (2023) https://arxiv.org/abs/2309.08574
    """

    def __init__(self, llm_predictions: List[ProtestEventPrediction]):
        self.predictions = llm_predictions

    def estimate_prevalence(
        self,
        event_type: str,
        confidence_level: float = 0.95,
    ) -> Dict[str, float]:
        """
        Estimate prevalence of an event type with binomial confidence intervals.

        Returns dict with keys: estimate, ci_lower, ci_upper, n_classified, total_n.
        """
        from scipy import stats

        n = len(self.predictions)
        if n == 0:
            return {
                "estimate": 0.0,
                "ci_lower": 0.0,
                "ci_upper": 0.0,
                "n_classified": 0,
                "total_n": 0,
            }

        correct = sum(1 for p in self.predictions if p.event_type == event_type)
        prevalence = correct / n

        ci = stats.binom.interval(confidence_level, n, prevalence)

        return {
            "estimate": prevalence,
            "ci_lower": ci[0] / n,
            "ci_upper": ci[1] / n,
            "n_classified": correct,
            "total_n": n,
        }

    def estimate_by_confidence(self) -> Dict[str, Any]:
        """Break down prediction counts by confidence band."""
        high = [p for p in self.predictions if p.confidence_score >= 0.8]
        medium = [p for p in self.predictions if 0.6 <= p.confidence_score < 0.8]
        low = [p for p in self.predictions if p.confidence_score < 0.6]
        n = len(self.predictions)

        return {
            "high_confidence": len(high),
            "medium_confidence": len(medium),
            "low_confidence": len(low),
            "pct_high": len(high) / n if n else 0,
            "pct_medium": len(medium) / n if n else 0,
            "pct_low": len(low) / n if n else 0,
        }

    def estimate_correlation(
        self,
        predictions_var1: List[ProtestEventPrediction],
        external_var: List[float],
    ) -> Dict[str, float]:
        """
        Spearman correlation between classified (1) / unclassifiable (0) and
        an external continuous variable.
        """
        import numpy as np
        from scipy.stats import spearmanr

        coded = np.array(
            [1 if p.event_type != "UNCLASSIFIABLE" else 0 for p in predictions_var1]
        )
        external = np.array(external_var)
        corr, p_value = spearmanr(coded, external)

        return {"correlation": float(corr), "p_value": float(p_value), "n": len(coded)}
