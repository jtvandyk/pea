"""
ConfliBERT Relevance Filter
============================
Stage 0 filter — runs before translation and LLM extraction.
Scores each scraped article for protest relevance using a zero-shot
NLI classifier backed by a conflict-domain model, rejecting clear
non-protest articles before any API call is made.

Default model: cross-encoder/nli-deberta-v3-small
  - 184 MB, CPU-only inference, ~200 articles/min on a single core
  - Swap for snowood1/ConfliBERT-large-uncased once a classification
    head has been fine-tuned on labelled PEA data (see active learning).

Why this saves money: the system prompt + codebook injection is ~29k
tokens. With gpt-4o-mini at $0.00616/article, every article rejected
before the LLM saves that full amount. At a typical 40–60% GDELT noise
rate this roughly halves API spend on large runs.

Graceful degradation: if the model cannot be loaded (e.g. no internet
access in a container with no model cache) the filter falls back to the
keyword scorer already used in gdelt_discovery.filter_protest_relevant,
so the pipeline continues without interruption.
"""

import logging
from pathlib import Path
from typing import Optional

import yaml

log = logging.getLogger(__name__)

# Labels used for zero-shot classification.
# The "protest" score is compared against _REJECTION_LABEL.
_PROTEST_LABELS = ["protest or political unrest event"]
_REJECTION_LABEL = "unrelated news or institutional meeting"
_ALL_LABELS = _PROTEST_LABELS + [_REJECTION_LABEL]

_KEYWORDS_PATH = Path(__file__).parent.parent.parent / "configs" / "keywords.yaml"


def _load_protest_signals(path: Path) -> set[str]:
    try:
        with open(path) as f:
            kw = yaml.safe_load(f) or {}
        return set(kw.get("protest_signals", []))
    except Exception:
        return {
            "protest", "demonstration", "strike", "march", "riot",
            "unrest", "rally", "uprising", "blockade", "clashes",
        }


class RelevanceFilter:
    """
    Scores articles for protest relevance.

    Usage:
        filt = RelevanceFilter()
        kept, rejected = filt.filter(articles)

    The filter attaches a '_relevance_score' float (0–1) and
    '_relevance_source' ('model' or 'keyword') to each article dict.
    """

    def __init__(
        self,
        model_name: str = "cross-encoder/nli-deberta-v3-small",
        threshold: float = 0.30,
        device: str = "cpu",
    ):
        """
        Args:
            model_name: HuggingFace model for zero-shot classification.
                        To use ConfliBERT once a classification head is
                        trained, swap this to the fine-tuned model path.
            threshold:  Articles with protest score below this are rejected.
                        0.30 is conservative (high recall, some noise passes).
                        Raise to 0.50+ once GLOCON validation confirms accuracy.
            device:     'cpu' (default) or 'cuda' if GPU available.
        """
        self.threshold = threshold
        self.model_name = model_name
        self._classifier = None
        self._protest_signals = _load_protest_signals(_KEYWORDS_PATH)
        self._model_available = False

        self._try_load_model(model_name, device)

    def _try_load_model(self, model_name: str, device: str) -> None:
        try:
            from transformers import pipeline as hf_pipeline

            self._classifier = hf_pipeline(
                "zero-shot-classification",
                model=model_name,
                device=device,
                # Don't download the full tokenizer vocab on first call
                tokenizer=model_name,
            )
            self._model_available = True
            log.info(f"RelevanceFilter: loaded '{model_name}' on {device}")
        except Exception as e:
            log.warning(
                f"RelevanceFilter: could not load '{model_name}': {e}. "
                "Falling back to keyword scoring."
            )

    def _score_with_model(self, text: str) -> float:
        """Return protest relevance score [0, 1] using the NLI classifier."""
        # Truncate to 512 chars — sufficient for title + first paragraph
        snippet = text[:512]
        try:
            result = self._classifier(snippet, _ALL_LABELS, multi_label=False)
            label_scores = dict(zip(result["labels"], result["scores"]))
            return label_scores.get(_PROTEST_LABELS[0], 0.0)
        except Exception as e:
            log.debug(f"Model scoring failed: {e} — using keyword fallback")
            return self._score_with_keywords(text)

    def _score_with_keywords(self, text: str) -> float:
        """
        Keyword-based fallback scorer. Returns 1.0 if any protest signal
        is found in the text, 0.0 otherwise. Intentionally binary so that
        the threshold comparison below still makes sense.
        """
        lower = text.lower()
        if any(sig in lower for sig in self._protest_signals):
            return 1.0
        return 0.0

    def score_article(self, article: dict) -> float:
        """Score a single article. Uses title + first 200 chars of text."""
        title = article.get("title") or ""
        text_snippet = (article.get("text_en") or article.get("text") or "")[:200]
        combined = f"{title}. {text_snippet}".strip()

        if self._model_available:
            score = self._score_with_model(combined)
            source = "model"
        else:
            score = self._score_with_keywords(combined)
            source = "keyword"

        article["_relevance_score"] = round(score, 4)
        article["_relevance_source"] = source
        return score

    def filter(
        self,
        articles: list[dict],
    ) -> tuple[list[dict], list[dict]]:
        """
        Score and partition articles.

        Returns:
            (kept, rejected) — articles above and below threshold.
            Both lists have '_relevance_score' and '_relevance_source' set.
        """
        kept, rejected = [], []
        for article in articles:
            score = self.score_article(article)
            if score >= self.threshold:
                kept.append(article)
            else:
                rejected.append(article)

        source = "model" if self._model_available else "keyword fallback"
        log.info(
            f"RelevanceFilter ({source}, threshold={self.threshold}): "
            f"kept {len(kept)}, rejected {len(rejected)} "
            f"of {len(articles)} articles"
        )
        return kept, rejected
