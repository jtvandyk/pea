"""
Post-deploy smoke test for the Azure AI Foundry extraction path.

Sends one canned protest article through `extract_from_article` and
asserts the live deployment responded with parseable JSON. Catches the
deploy-day failure modes the unit tests can't:

  * AZURE_OPENAI_ENDPOINT typo / missing /openai/v1 suffix
  * AZURE_FOUNDRY_API_KEY rotated or pasted with whitespace
  * Deployment name (--model) doesn't exist in the Foundry project
  * Foundry API version drift breaks the response shape

Exits 0 on success, 1 on any failure. Run from repo root:

    python -m scripts.smoke_extract
    python -m scripts.smoke_extract --model gpt-5.4
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional


# Canned, paraphrased protest scenario. Not a real news article — written here
# specifically so the smoke test has no copyright dependency on a live source.
# Designed to be unambiguous: a peaceful demonstration with a clear demand.
_CANNED_ARTICLE: dict = {
    "url": "https://example.invalid/smoke-test-article",
    "title": "Hundreds rally in Lagos demanding electricity tariff rollback",
    "seendate": "2026-05-06",
    "sourcecountry": "NG",
    "text_lang": "en",
    "text": (
        "Lagos, Nigeria — An estimated 400 residents gathered outside the "
        "Ministry of Power offices in Ikeja on Tuesday afternoon to protest "
        "against a recently announced 35 percent increase in electricity "
        "tariffs. Carrying placards reading 'Power for the people' and "
        "'Roll back the hike', demonstrators marched from Allen Avenue to "
        "the ministry compound, where organisers from the Nigerian Consumer "
        "Forum delivered a petition signed by more than 12,000 residents. "
        "The protest was peaceful and dispersed by 5pm. No arrests were "
        "reported. A ministry spokesperson said the demands would be "
        "'reviewed in due course'. Organisers said they would return next "
        "week if the tariff increase is not suspended."
    ),
}


def _resolve_endpoint() -> Optional[str]:
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
    if not endpoint:
        return None
    return endpoint


def _resolve_key() -> Optional[str]:
    key = os.environ.get("AZURE_FOUNDRY_API_KEY", "").strip()
    if not key:
        return None
    return key


def _print_summary(events: list) -> None:
    print(f"  Parsed {len(events)} event(s) from response.")
    for i, ev in enumerate(events[:3]):
        if not isinstance(ev, dict):
            continue
        et = ev.get("event_type", "?")
        country = ev.get("country") or ev.get("source_country", "?")
        conf = ev.get("confidence", "?")
        print(f"    [{i + 1}] event_type={et}  country={country}  confidence={conf}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test the live Azure AI Foundry extraction endpoint."
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("PEA_SMOKE_MODEL", "gpt-5.4"),
        help="Deployment name in Azure AI Foundry (default: gpt-5.4, "
        "or PEA_SMOKE_MODEL env var)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=1,
        help="Retries on transient failure (default: 1 — keep tight for CI)",
    )
    args = parser.parse_args()

    endpoint = _resolve_endpoint()
    if not endpoint:
        print("FAIL: AZURE_OPENAI_ENDPOINT is empty or unset.", file=sys.stderr)
        return 1

    key = _resolve_key()
    if not key:
        print("FAIL: AZURE_FOUNDRY_API_KEY is empty or unset.", file=sys.stderr)
        return 1

    print("=== PEA extraction smoke test ===")
    print(f"  endpoint     : {endpoint[:60]}{'…' if len(endpoint) > 60 else ''}")
    print(f"  model/deploy : {args.model}")
    print(f"  article      : {_CANNED_ARTICLE['title']}")

    # Import lazily so missing-dependency errors are reported by the smoke test
    # itself (which is the whole point of this script) rather than ImportError
    # at module load.
    try:
        from src.acquisition.extractor import extract_from_article
    except Exception as exc:
        print(f"FAIL: could not import extractor — {exc!r}", file=sys.stderr)
        return 1

    try:
        events = extract_from_article(
            article=_CANNED_ARTICLE,
            model=args.model,
            api_key=key,
            provider="azure",
            max_retries=args.max_retries,
        )
    except Exception as exc:
        print(f"FAIL: extract_from_article raised — {exc!r}", file=sys.stderr)
        return 1

    if events is None:
        print(
            "FAIL: extractor returned None — the live endpoint is reachable "
            "but the model did not return parseable JSON. Likely causes: "
            "wrong deployment name, content filter, or model schema drift.",
            file=sys.stderr,
        )
        return 1

    if not isinstance(events, list):
        print(f"FAIL: expected list, got {type(events).__name__}", file=sys.stderr)
        return 1

    # An empty list is a valid response ("not a protest event"), but for this
    # canned, unambiguous protest article it's a strong signal that few-shot
    # examples or codebook injection isn't reaching the model. Warn loudly
    # but still exit 0 — the auth/endpoint path is verified, which is the
    # smoke test's primary job.
    if len(events) == 0:
        print(
            "WARN: extraction returned [] for an unambiguous protest article. "
            "Auth + endpoint OK, but verify codebook + few-shot examples are "
            "loaded in the running container."
        )
    else:
        _print_summary(events)
        # Cheap schema sanity check
        first = events[0]
        if isinstance(first, dict) and not first.get("event_type"):
            print(
                "WARN: first event has no event_type field — JSON shape may "
                "have drifted from the codebook spec.",
                file=sys.stderr,
            )

    print("PASS: live Azure Foundry endpoint is reachable and returning JSON.")
    print(json.dumps({"smoke_test": "ok", "events_returned": len(events)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
