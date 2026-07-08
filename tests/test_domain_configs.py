"""Structural tests for domain codebooks, few-shot examples, and registration.

These are the gates the pea-domain-add skill specifies: every codebook YAML
(registered or not) must carry the extractor's required structure, every
registered domain must be fully wired (DOMAIN_CONFIGS + _REQUIRED_CONFIGS +
relevance filter), and the codebook injection must never be silently empty —
the failure mode that shipped the violent_extremism `attack_types` bug.
"""

from pathlib import Path

import pytest
import yaml

from src.acquisition.extractor import _build_codebook_context
from src.acquisition.pipeline import (
    DOMAIN_CONFIGS,
    _REQUIRED_CONFIGS,
    _validate_domains,
)
from src.acquisition.relevance_filter import RelevanceFilter

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS_DIR = REPO_ROOT / "configs"

# Contract from .claude/skills/pea-domain-add: every domain codebook must
# supply these top-level sections.
REQUIRED_CODEBOOK_SECTIONS = [
    "metadata",
    "general_rules",
    "minimum_criteria",
    "event_types",
    "non_events",
    "confidence_guidance",
]

# The only per-type keys _build_codebook_context() injects into the prompt.
REQUIRED_TYPE_KEYS = [
    "definition",
    "positive_examples",
    "negative_examples",
    "decision_rules",
]

REQUIRED_EXAMPLE_KEYS = ["description", "article_snippet", "extracted_events"]


def _codebook_paths():
    return sorted(
        p for p in CONFIGS_DIR.glob("*codebook*.yaml") if "template" not in p.name
    )


def _examples_paths():
    return sorted(
        p
        for p in CONFIGS_DIR.glob("*extraction_examples*.yaml")
        if "template" not in p.name
    )


# ── Domain registration ──────────────────────────────────────────────────────


@pytest.mark.parametrize("domain", sorted(DOMAIN_CONFIGS))
def test_domain_registered(domain):
    """Each registered domain has existing codebook/examples files, a distinct
    GDELT query, and passes _validate_domains."""
    cfg = DOMAIN_CONFIGS[domain]
    assert cfg["codebook"].is_file(), f"{domain}: codebook missing"
    assert cfg["examples"].is_file(), f"{domain}: examples missing"
    assert cfg["query"].strip(), f"{domain}: empty GDELT query"
    _validate_domains([domain])  # must not raise


def test_domain_queries_distinct():
    queries = [cfg["query"] for cfg in DOMAIN_CONFIGS.values()]
    assert len(queries) == len(set(queries)), "domains must not share GDELT queries"


def test_unknown_domain_rejected():
    with pytest.raises(SystemExit):
        _validate_domains(["not_a_domain"])


def test_domain_configs_in_required_configs():
    """Every registered codebook/examples file must be in the startup
    assertion list — losing one silently collapses extraction quality."""
    required = set(_REQUIRED_CONFIGS)
    for domain, cfg in DOMAIN_CONFIGS.items():
        assert (
            cfg["codebook"] in required
        ), f"{domain} codebook not in _REQUIRED_CONFIGS"
        assert (
            cfg["examples"] in required
        ), f"{domain} examples not in _REQUIRED_CONFIGS"


# ── Codebook YAML structure (all codebooks, registered or not) ───────────────


@pytest.mark.parametrize("path", _codebook_paths(), ids=lambda p: p.name)
def test_codebook_structure(path):
    with open(path) as f:
        cb = yaml.safe_load(f)

    missing = [k for k in REQUIRED_CODEBOOK_SECTIONS if k not in cb]
    assert not missing, f"{path.name} missing sections: {missing}"

    assert cb["event_types"], f"{path.name}: event_types is empty"
    assert cb["metadata"].get("version"), f"{path.name}: metadata.version missing"

    for type_key, details in cb["event_types"].items():
        missing_keys = [k for k in REQUIRED_TYPE_KEYS if k not in details]
        assert not missing_keys, (
            f"{path.name} event_types.{type_key} missing {missing_keys} — "
            "these are the only keys the extractor injects into the prompt"
        )
        assert str(
            details["definition"]
        ).strip(), f"{path.name} event_types.{type_key}: empty definition"


# ── Few-shot examples structure ──────────────────────────────────────────────


@pytest.mark.parametrize("path", _examples_paths(), ids=lambda p: p.name)
def test_examples_structure(path):
    with open(path) as f:
        data = yaml.safe_load(f)

    examples = data.get("examples")
    assert examples, f"{path.name}: no examples"

    for ex in examples:
        missing = [k for k in REQUIRED_EXAMPLE_KEYS if k not in ex]
        assert not missing, f"{path.name} example {ex.get('id')}: missing {missing}"
        assert isinstance(ex["extracted_events"], list)

    assert any(ex.get("pinned") for ex in examples), (
        f"{path.name}: at least one example must be pinned so every run "
        "carries a stable anchor regardless of sample rotation"
    )


# ── Codebook injection guard ─────────────────────────────────────────────────


@pytest.mark.parametrize("domain", sorted(DOMAIN_CONFIGS))
def test_codebook_context_nonempty(domain):
    """_build_codebook_context returns '' when the taxonomy key is wrong or the
    file is unreadable — the exact failure that made the pre-remediation VE
    codebook inject zero context. Guard every registered codebook."""
    context = _build_codebook_context(DOMAIN_CONFIGS[domain]["codebook"])
    assert context.strip(), f"{domain}: codebook injected empty context"
    assert "TYPE:" in context
    assert "DECISION RULES:" in context


def test_ve_codebook_taxonomy_key_regression():
    """Regression for the original VE bug: the taxonomy must live under
    `event_types` (the injected key), never `attack_types` (which injected
    zero context). Kept explicit even though VE is now a registered domain."""
    with open(CONFIGS_DIR / "violent_extremism_codebook.yaml") as f:
        cb = yaml.safe_load(f)
    assert "attack_types" not in cb
    context = _build_codebook_context(CONFIGS_DIR / "violent_extremism_codebook.yaml")
    assert "TYPE: ASSASSINATION" in context


# ── Relevance filter wiring ──────────────────────────────────────────────────


@pytest.mark.parametrize("domain", sorted(DOMAIN_CONFIGS))
def test_relevance_filter_constructs(domain):
    """Every registered domain must have a _DOMAIN_CONFIG entry in
    relevance_filter.py — without it the multi-domain run crashes at Stage 2.5.
    An invalid model name forces the cheap keyword-fallback path."""
    filt = RelevanceFilter(
        domain=domain, model_name="nonexistent/model-for-structural-test"
    )
    assert filt.degraded_mode  # keyword fallback, no model download
    assert filt._domain_signals, f"{domain}: no keyword signals loaded"


# ── Pipeline stage-order regression ──────────────────────────────────────────


def test_translation_runs_before_relevance_filter(tmp_path, monkeypatch):
    """Pins the fixed stage order: the NLI relevance filter is English-trained,
    so translation must run first or non-English true positives are silently
    rejected (single-domain path regression guard)."""
    import src.acquisition.pipeline as pipeline

    call_order = []

    def fake_scrape(articles, **kwargs):
        call_order.append("scrape")
        return articles

    def fake_translate(articles, **kwargs):
        call_order.append("translate")
        for a in articles:
            a["text_en"] = a["text"]
            a["text_lang"] = "fr"
        return articles

    class FakeFilter:
        degraded_mode = False

        def __init__(self, **kwargs):
            pass

        def filter(self, articles):
            call_order.append("relevance_filter")
            return articles, []

    def fake_extract(articles, **kwargs):
        call_order.append("extract")
        return [], []

    def fake_save(events, **kwargs):
        return tmp_path / "events.jsonl"

    monkeypatch.setattr(pipeline, "scrape_articles", fake_scrape)
    monkeypatch.setattr(pipeline, "translate_articles", fake_translate)
    monkeypatch.setattr(pipeline, "RelevanceFilter", FakeFilter)
    monkeypatch.setattr(pipeline, "extract_events", fake_extract)
    monkeypatch.setattr(pipeline, "save_results", fake_save)

    pipeline.run_pipeline(
        query="protest",
        countries=["ZA"],
        days=1,
        output_dir=tmp_path,
        geocode=False,
        articles=[{"url": "http://x", "title": "grève", "text": "grève générale"}],
    )

    assert "translate" in call_order and "relevance_filter" in call_order
    assert call_order.index("translate") < call_order.index(
        "relevance_filter"
    ), f"translation must run before the relevance filter; got {call_order}"


# ── Multilingual keyword fallback (pan-Africa coverage) ──────────────────────


@pytest.fixture(scope="module")
def protest_keyword_filter():
    """One shared degraded-mode filter — constructing RelevanceFilter attempts
    a model load (network) per call, so per-test construction is slow."""
    return RelevanceFilter(
        domain="protest", model_name="nonexistent/model-for-structural-test"
    )


@pytest.mark.parametrize(
    "headline",
    [
        # Portuguese (Mozambique/Angola)
        "Manifestação em Maputo termina em confrontos com a polícia",
        "Greve dos taxistas paralisa Luanda pelo segundo dia",
        "Paralisação nacional convocada pela oposição",
        # Amharic (Ethiopia)
        "በአዲስ አበባ ተቃውሞ ሰልፍ ተካሄደ",
        "የገበያ አድማ በኦሮሚያ ከተሞች",
        # Hausa (Northern Nigeria/Niger)
        "An gudanar da zanga-zangar kin jinin tsadar rayuwa a Kano",
        "Ma'aikata sun shiga yajin aiki a Abuja",
        # Somali
        "Banaanbax ka dhacay Muqdisho oo lagu diidan yahay",
        "Mudaaharaad ballaaran oo Hargeysa ka dhacay",
        # French (regression — pre-existing coverage)
        "Grève générale à Dakar contre la vie chère",
        # Arabic (regression — pre-existing coverage)
        "احتجاجات في الجزائر العاصمة",
    ],
    ids=[
        "pt-manifestacao",
        "pt-greve",
        "pt-paralisacao",
        "am-teqawmo-self",
        "am-adma",
        "ha-zanga-zanga",
        "ha-yajin-aiki",
        "so-banaanbax",
        "so-mudaaharaad",
        "fr-greve",
        "ar-ihtijajat",
    ],
)
def test_keyword_fallback_matches_african_language_headlines(
    protest_keyword_filter, headline
):
    """The keyword fallback must fire on protest headlines in every language
    the pipeline claims to cover — Portuguese, Amharic, Hausa, and Somali were
    added for pan-Africa coverage (the NLI model path handles translated text;
    this fallback is what runs in degraded mode)."""
    assert protest_keyword_filter._score_with_keywords(headline) == 1.0, headline


# ── Turmoil derivation covers repression-domain vocabulary ───────────────────


def test_internet_shutdown_derives_medium_turmoil():
    """The state_repression domain emits state_response: internet_shutdown;
    storage.py's turmoil sets must know it (codebook<->storage sync rule)."""
    from src.acquisition.storage import _derive_turmoil_level

    event = {"state_response": "internet_shutdown"}
    assert _derive_turmoil_level(event) == "medium"


def test_repression_vocabulary_covered_by_turmoil_sets():
    """Every state_response value the repression codebook instructs the LLM to
    emit must be classifiable by _derive_turmoil_level's severity sets (or be
    an explicitly-low value), so no repression event silently defaults."""
    from src.acquisition.storage import (
        _HIGH_TURMOIL_RESPONSES,
        _MEDIUM_TURMOIL_RESPONSES,
    )

    known = (
        _HIGH_TURMOIL_RESPONSES
        | _MEDIUM_TURMOIL_RESPONSES
        | {"none", "monitoring", "unknown"}
    )
    # The vocabulary the repression extraction_prompt tells the model to use:
    with open(CONFIGS_DIR / "state_repression_codebook.yaml") as f:
        cb = yaml.safe_load(f)
    rules = "\n".join(cb["extraction_prompt"]["extraction_rules"])
    vocab_rule = next(r for r in rules.split("\n\n") if "shared" in r)
    import re

    listed = set(re.findall(r"[a-z_]{4,}", vocab_rule.split(":", 1)[1]))
    listed &= {
        "arrests",
        "ban",
        "curfew",
        "legal_criminalisation",
        "anti_terrorism_designation",
        "organisational_dissolution",
        "non_association_bail",
        "internet_shutdown",
        "live_ammunition",
        "rubber_bullets",
        "teargas",
        "dispersal",
        "unknown",
    }
    missing = listed - known
    assert not missing, f"repression vocabulary not covered by turmoil sets: {missing}"
