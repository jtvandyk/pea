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

_KEYWORDS_PATH = Path(__file__).parent.parent.parent / "configs" / "keywords.yaml"

# Per-domain NLI label config.  Each domain maps to a positive hypothesis
# and a rejection label used in the zero-shot classifier.
_DOMAIN_CONFIG: dict = {
    "protest": {
        "positive_labels": ["protest or political unrest event"],
        "rejection_label": "unrelated news or institutional meeting",
        "keyword_key": "protest_signals",
        "keyword_fallback": {
            "protest", "demonstration", "strike", "march", "riot",
            "unrest", "rally", "uprising", "blockade", "clashes",
        },
    },
    "drone": {
        "positive_labels": ["drone or unmanned aerial vehicle (UAV) operation"],
        "rejection_label": "unrelated news with no drone or UAV involvement",
        "keyword_key": "drone_signals",
        "keyword_fallback": {
            "drone", "uav", "unmanned", "quadcopter", "bayraktar", "shahed",
            "reaper", "mq-9", "tb2", "fpv", "loitering munition", "airstrike",
        },
    },
}


def _load_domain_signals(path: Path, domain: str) -> set[str]:
    cfg = _DOMAIN_CONFIG.get(domain, _DOMAIN_CONFIG["protest"])
    try:
        with open(path) as f:
            kw = yaml.safe_load(f) or {}
        signals = set(kw.get(cfg["keyword_key"], []))
        return signals if signals else cfg["keyword_fallback"]
    except Exception:
        return cfg["keyword_fallback"]


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
        domain: str = "protest",
    ):
        """
        Args:
            model_name: HuggingFace model for zero-shot classification.
            threshold:  Articles below this score are rejected.
                        0.30 = conservative (high recall). Raise to 0.50+ after GLOCON validation.
            device:     'cpu' or 'cuda'.
            domain:     'protest' or 'drone' — selects the NLI hypothesis and keyword set.
        """
        if domain not in _DOMAIN_CONFIG:
            raise ValueError(f"Unknown domain '{domain}'. Valid: {list(_DOMAIN_CONFIG)}")
        self.threshold = threshold
        self.model_name = model_name
        self.domain = domain
        self._classifier = None
        self._domain_signals = _load_domain_signals(_KEYWORDS_PATH, domain)
        self._model_available = False
        self._positive_labels = _DOMAIN_CONFIG[domain]["positive_labels"]
        self._rejection_label = _DOMAIN_CONFIG[domain]["rejection_label"]
        self._all_labels = self._positive_labels + [self._rejection_label]

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
        """Return domain relevance score [0, 1] using the NLI classifier."""
        snippet = text[:512]
        try:
            result = self._classifier(snippet, self._all_labels, multi_label=False)
            label_scores = dict(zip(result["labels"], result["scores"]))
            return label_scores.get(self._positive_labels[0], 0.0)
        except Exception as e:
            log.debug(f"Model scoring failed: {e} — using keyword fallback")
            return self._score_with_keywords(text)

    def _score_with_keywords(self, text: str) -> float:
        """
        Keyword-based fallback scorer. Returns 1.0 if any domain signal
        is found in the text, 0.0 otherwise.
        """
        lower = text.lower()
        if any(sig in lower for sig in self._domain_signals):
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
            f"RelevanceFilter (domain={self.domain}, {source}, threshold={self.threshold}): "
            f"kept {len(kept)}, rejected {len(rejected)} "
            f"of {len(articles)} articles"
        )
        return kept, rejected
