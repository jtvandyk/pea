"""
LLM Event Extraction Module
=============================
Extracts structured protest event fields from news article text
using Azure AI Foundry as the LLM backend.

Requires:
  AZURE_FOUNDRY_API_KEY  — API key for Azure AI Foundry
  AZURE_OPENAI_ENDPOINT  — endpoint URL for Azure AI Foundry project

Codebook version: 2.3
Follows the meta-codebook schema, extracting:
  - Event identification (date, location, country)
  - Actor information (who organised/participated)
  - Event type (demonstration_march, strike_boycott, riot, occupation_seizure,
    confrontation, petition_signature, vigil, hunger_strike)
  - Claims/grievances (what protesters demanded)
  - Size / participation estimate
  - Duration
  - State response (police, military, arrests)
  - Outcome / escalation
  - Fatalities / injuries
  - Source metadata

Multiple events can be reported in a single article.
The LLM is instructed to return a JSON array of event objects.
"""

import json
import logging
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import yaml

from src.acquisition._rate_limit import SlidingWindowLimiter
from src.acquisition.storage import upload_checkpoint
from src.constants import CONFIGS_DIR

log = logging.getLogger(__name__)

_CODEBOOK_PATH = CONFIGS_DIR / "protest_codebook.yaml"
_EXAMPLES_PATH = CONFIGS_DIR / "extraction_examples.yaml"


def _build_codebook_context(codebook_path: Path) -> str:
    """
    Load the protest codebook YAML and return a formatted string of all event type
    definitions, positive/negative examples, and decision rules for injection into
    the system prompt.  Returns an empty string if the file cannot be loaded.
    """
    try:
        with open(codebook_path) as f:
            cb = yaml.safe_load(f)
    except Exception as e:
        log.warning(f"Could not load codebook for prompt injection: {e}")
        return ""

    event_types = cb.get("event_types", {})
    if not event_types:
        return ""

    version = cb.get("metadata", {}).get("version", "unknown")
    lines = [f"\n\n== FULL EVENT TYPE DEFINITIONS (Codebook v{version}) ==\n"]
    for event_type, details in event_types.items():
        lines.append(f"TYPE: {event_type.upper()}")
        definition = details.get("definition", "").strip()
        lines.append(f"DEFINITION: {definition}")

        pos = details.get("positive_examples", [])
        if pos:
            lines.append("POSITIVE EXAMPLES (these qualify):")
            for ex in pos:
                lines.append(f"  + {ex}")

        neg = details.get("negative_examples", [])
        if neg:
            lines.append("NEGATIVE EXAMPLES (these do NOT qualify as this type):")
            for ex in neg:
                lines.append(f"  - {ex}")

        rules = details.get("decision_rules", [])
        if rules:
            lines.append("DECISION RULES:")
            for rule in rules:
                lines.append(f"  -> {rule}")

        lines.append("")

    return "\n".join(lines)


def _build_few_shot_examples(
    examples_path: Path,
    sample_n: int = 5,
    seed: Optional[int] = None,
) -> str:
    """
    Load the gold-standard extraction examples YAML and return a formatted
    string of demonstrated input/output pairs for injection into the user prompt.

    Selection rules:
      - Entries with ``pinned: true`` are always included (handwritten
        curriculum; never evicted).
      - Remaining slots up to ``sample_n`` total are filled by random sampling
        from the non-pinned pool using ``random.Random(seed)``. With a
        run-stable seed, the sample is identical across all articles in a
        run (preserves Azure prompt caching) but varies across runs
        (exposes the model to rotating promoted examples).
      - If ``sample_n <= len(pinned)``, ``sample_n`` acts as a floor and
        all pinned are still included.

    Returns an empty string if the file cannot be loaded.
    """
    try:
        with open(examples_path) as f:
            data = yaml.safe_load(f)
    except Exception as e:
        log.warning(f"Could not load extraction examples for prompt injection: {e}")
        return ""

    pool = (data or {}).get("examples", []) or []
    if not pool:
        return ""

    pinned = [ex for ex in pool if ex.get("pinned")]
    rotatable = [ex for ex in pool if not ex.get("pinned")]

    remaining = max(0, int(sample_n) - len(pinned))
    if remaining and rotatable:
        rng = random.Random(seed)
        sampled = rng.sample(rotatable, min(remaining, len(rotatable)))
    else:
        sampled = []

    selected = pinned + sampled

    lines = ["== FEW-SHOT EXAMPLES ==", ""]
    lines.append(
        "The following are gold-standard examples of correct extraction. "
        "Study them before processing the real article below.\n"
    )

    for ex in selected:
        lines.append(f"--- Example: {ex.get('description', '')} ---")
        lines.append("ARTICLE TEXT:")
        lines.append(ex.get("article_snippet", "").strip())
        lines.append("")
        lines.append("CORRECT OUTPUT:")
        lines.append(json.dumps(ex.get("extracted_events", []), indent=2))
        lines.append("")

    lines.append("== END OF EXAMPLES -- NOW PROCESS THE REAL ARTICLE BELOW ==")
    lines.append("")
    return "\n".join(lines)


_BASE_SYSTEM_PROMPT = """You are an expert coder for a protest event analysis (PEA) dataset,
specialising in the Global South and African contexts.
You follow codebook version 2.3, aligned with Halterman & Keith (2025).

Your task is to read a news article and extract structured information about
each distinct protest event described.

== STEP 1: DISQUALIFY NON-PROTEST ARTICLES FIRST ==

Return an empty array [] immediately if the article is primarily about ANY of:
- Conferences, summits, or official institutional meetings (e.g. SADC summit, AU session, economic forums)
- Phone calls, press conferences, or statements by officials
- Armed conflict, military operations, terrorism, or insurgency
- Natural disasters, accidents, or crashes (e.g. helicopter crash)
- Sports matches, cultural celebrations, or entertainment events
- Trade, economic, or aid activity (exports, imports, investments, donations)
- Diplomatic events or international relations
- Legal proceedings, elections, or parliamentary votes
- War or inter-state conflict reporting
- Analysis or commentary ABOUT protests without reporting a specific event

== STEP 2: APPLY MINIMUM CRITERIA ==

An article ONLY qualifies if ALL of the following are true:
1. >=2 people act together (exception: hunger_strike can be 1 person)
2. In a public setting
3. With explicit political motivation, demand, or grievance
4. Outside normal institutional channels
5. A real physical action occurred (not planned, proposed, or hypothetical)

== STEP 3: EXTRACT EVENTS ==

For qualifying articles, extract each distinct protest event. Follow these rules:
1. Extract ONLY information explicitly stated -- do not infer or hallucinate.
2. If a field is not mentioned, use null.
3. One article may describe multiple distinct events -- return all of them.
4. For location, prefer the most specific level available (city > region > country).
   If the article names a specific venue, landmark, or neighbourhood, extract it into "venue".
5. For actor names, use the full organisation/group name as given in the article.
6. For event_type, use EXACTLY one of these keys:
   - demonstration_march  (peaceful public gathering, rally, march)
   - strike_boycott       (organized work stoppage or consumer boycott)
   - riot                 (violent collective action initiated by protesters)
   - occupation_seizure   (sit-in, encampment, building takeover)
   - confrontation        (non-violent direct action: blocking, picketing, disrupting)
   - petition_signature   (organized petition or letter campaign)
   - vigil                (solemn/commemorative gathering, candlelight assembly)
   - hunger_strike        (publicly declared food refusal as political protest)
7. For state_response, choose the most severe response reported. Allowed values:
   Standard: none, monitoring, dispersal, teargas, water_cannon, rubber_bullets,
             live_ammunition, arrests, ban, curfew
   Extended: legal_criminalisation (charged under novel anti-protest statute),
             anti_terrorism_designation (labelled terrorist/security threat),
             organisational_dissolution (movement legally dissolved),
             non_association_bail (bail bars activists from contacting each other)
   If unclear: unknown.
8. For outcome, choose from: ongoing, dispersed, arrested, demands_met, partial_concession,
   escalated, unknown.
9. crowd_size: numeric estimate if given, or "hundreds" / "thousands" / "tens of thousands".
10. claims: brief list of main demands or grievances stated in the article.
11. duration: how long the event lasted if stated (e.g. "3 hours", "2 days").
12. state_actors: list specific police units, military branches, or security forces named.
13. confidence: "high" (clear, unambiguous protest), "medium" (some ambiguity), "low" (borderline).
    Do NOT use "unknown" -- always choose high, medium, or low.

Return ONLY a valid JSON array. No preamble, no explanation, no markdown fences.
If the article contains no qualifying protest events, return: []

JSON schema for each event:
{
  "event_date": "YYYY-MM-DD or partial date string",
  "country": "country name",
  "city": "city or town name",
  "region": "state/province/region",
  "venue": "specific named venue/landmark within the city (e.g. 'Lekki Toll Gate', 'Parliament Square')",
  "location_notes": "any additional location context",
  "event_type": "one of the 8 allowed keys above",
  "organizer": "organisation or group that called the event",
  "participant_groups": ["list of groups/demographics who participated"],
  "claims": ["list of demands or grievances"],
  "crowd_size": "numeric or descriptive estimate",
  "duration": "how long the event lasted if stated",
  "state_response": "one of the allowed state response types",
  "state_actors": ["police, military units, etc. mentioned"],
  "arrests": "number or description of arrests",
  "fatalities": "number of deaths if any",
  "injuries": "number of injuries if any",
  "outcome": "one of the allowed outcome types",
  "outcome_notes": "any additional outcome context",
  "article_title": "title of the source article",
  "article_url": "URL of the source article",
  "article_date": "publication date of article",
  "source_country": "country of news source",
  "source_language": "language of original article",
  "confidence": "high / medium / low"
}"""

SYSTEM_PROMPT = _BASE_SYSTEM_PROMPT + _build_codebook_context(_CODEBOOK_PATH)

_FEW_SHOT_EXAMPLES = _build_few_shot_examples(_EXAMPLES_PATH)

USER_PROMPT_TEMPLATE = """{few_shot_examples}Article title: {title}
Article URL: {url}
Article date: {date}
Source country: {source_country}
Original language: {language}

Article text:
{text}

Extract all protest events from this article and return a JSON array."""


def _call_azure(
    system: str,
    user: str,
    model: str,
    api_key: str,
    timeout: int = 180,
) -> Optional[str]:
    """
    Call Azure AI Foundry via its OpenAI-compatible endpoint.
    The model name is the deployment name in your Foundry project
    (e.g. 'gpt-4o-mini', 'claude-sonnet-4-6', 'gpt-5').
    Reads AZURE_OPENAI_ENDPOINT from the environment.

    Prompt caching is automatic for gpt-4o-mini on Azure OpenAI when the
    prompt prefix exceeds 1024 tokens. The system prompt + codebook injection
    (~29k tokens) is an ideal cache target -- all per-article variation is in
    the user message, leaving the system prefix identical across a run.
    Cached tokens are billed at 50% of the standard input rate.
    Returns the assistant response text, or None on failure.
    """
    try:
        from openai import OpenAI, APIStatusError

        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        if not endpoint:
            raise ValueError("AZURE_OPENAI_ENDPOINT env var is not set")
        client = OpenAI(base_url=endpoint, api_key=api_key, timeout=timeout)
        response = client.chat.completions.create(
            model=model,
            max_tokens=4096,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )

        # Log prompt-caching savings when the API reports them.
        usage = getattr(response, "usage", None)
        if usage:
            details = getattr(usage, "prompt_tokens_details", None)
            cached = getattr(details, "cached_tokens", 0) or 0
            if cached:
                saved_usd = cached * (0.150 / 1_000_000) * 0.50
                log.debug(
                    f"Prompt cache hit: {cached} cached tokens "
                    f"(saved ~${saved_usd:.5f})"
                )

        return response.choices[0].message.content
    except APIStatusError as e:
        log.warning(f"Azure API error {e.status_code}: {e.message}")
        if e.status_code == 400 and "content_filter" in str(e.message):
            return "__CONTENT_FILTERED__"
        return None
    except Exception as e:
        log.warning(f"Azure call failed: {e}")
        return None


def _clean_json(text: str) -> str:
    """Remove common LLM JSON formatting issues."""
    if "```" in text:
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    text = re.sub(r",\s*([\]}])", r"\1", text)
    return text.strip()


def _parse_events(raw: str) -> list:
    """Extract a JSON array of events from the LLM response string."""
    text = _clean_json(raw)

    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for val in result.values():
                if isinstance(val, list):
                    return val
        log.warning(f"LLM returned unexpected JSON structure: {type(result)}")
        return []
    except json.JSONDecodeError:
        pass

    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            cleaned = _clean_json(text[start : end + 1])
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

    log.debug(f"Could not parse JSON array from: {text[:200]}")
    return []


def extract_from_article(
    article: dict,
    model: str,
    api_key: str,
    provider: str = "azure",
    max_retries: int = 2,
    system_prompt: Optional[str] = None,
    few_shot_examples: Optional[str] = None,
    limiter: Optional[SlidingWindowLimiter] = None,
) -> Optional[list]:
    """
    Run LLM extraction on a single article.
    Returns list of extracted event dicts, or None on total failure.

    system_prompt: override the default SYSTEM_PROMPT (built from protest codebook).
    few_shot_examples: override the default _FEW_SHOT_EXAMPLES string.
    limiter: shared rate limiter -- acquired before every Azure call, including
        retries, so retry storms cannot burst past the RPM ceiling.
    """
    resolved_system = system_prompt if system_prompt is not None else SYSTEM_PROMPT
    resolved_examples = (
        few_shot_examples if few_shot_examples is not None else _FEW_SHOT_EXAMPLES
    )

    text = article.get("text_en") or article.get("text") or ""

    if not text or len(text) < 100:
        log.debug(
            f"Skipping article with insufficient text: {article.get('url', '')[:60]}"
        )
        return []

    truncated_text = text[:12000]

    prompt = USER_PROMPT_TEMPLATE.format(
        few_shot_examples=resolved_examples,
        title=article.get("title", "Unknown"),
        url=article.get("url", ""),
        date=article.get("seendate", "Unknown"),
        source_country=article.get("sourcecountry", "Unknown"),
        language=article.get("text_lang", "unknown"),
        text=truncated_text,
    )

    for attempt in range(max_retries + 1):
        if limiter is not None:
            limiter.acquire()
        raw = _call_azure(
            system=resolved_system,
            user=prompt,
            model=model,
            api_key=api_key,
        )

        if raw == "__CONTENT_FILTERED__":
            log.warning(
                "Content filtered by Azure policy (violence:medium) -- skipping retries"
            )
            return None

        if raw is None:
            log.warning(f"LLM returned nothing (attempt {attempt + 1})")
            if attempt < max_retries:
                time.sleep(2**attempt)
            continue

        events = _parse_events(raw)

        if events is not None:
            events = [e for e in events if isinstance(e, dict)]
            for event in events:
                event.setdefault("article_url", article.get("url", ""))
                event.setdefault("article_title", article.get("title", ""))
                event.setdefault("article_date", article.get("seendate", ""))
                event.setdefault("source_country", article.get("sourcecountry", ""))
                event.setdefault("source_language", article.get("text_lang", "unknown"))
                # Store source text for annotation training pairs.
                # Truncated to 12k chars (same as extraction limit) so JSONL
                # files don't balloon. Prefixed with _ so it's stripped from
                # the final CSV output and public-facing datasets.
                event["_article_text"] = truncated_text
            return events

        log.warning(f"Parse failed (attempt {attempt + 1}), retrying...")
        if attempt < max_retries:
            time.sleep(1)

    return None


_PROVIDER_ENV_VARS = {
    "azure": "AZURE_FOUNDRY_API_KEY",
}

_PROVIDER_DEFAULT_MODELS = {
    "azure": "gpt-4.1",
}


def extract_events(
    articles: list,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    provider: str = "azure",
    rate_limit_delay: float = 1.5,
    checkpoint_path: Optional[str] = None,
    upload_to: Optional[str] = None,
    codebook_path: Optional[Path] = None,
    examples_path: Optional[Path] = None,
    workers: int = 4,
    rpm_limit: int = 450,
    examples_sample_n: int = 5,
    examples_seed: Optional[int] = None,
) -> tuple:
    """
    Run LLM extraction across all scraped articles via Azure AI Foundry.

    Args:
        articles: list of article dicts with 'text_en' field
        model: deployment name in your Azure AI Foundry project (e.g. 'gpt-4.1')
        api_key: API key -- defaults to AZURE_FOUNDRY_API_KEY env var
        provider: always 'azure' (kept for interface compatibility)
        rate_limit_delay: seconds between requests (sequential mode only; ignored when workers>1)
        checkpoint_path: path to checkpoint file; processed URLs are skipped on resume
        codebook_path: override the default protest codebook YAML path
        examples_path: override the default extraction examples YAML path
        workers: number of concurrent extraction threads (default 4). Pass 1 for
                 sequential mode. All workers use the same system prompt so Azure
                 prompt caching is maximised, and share one sliding-window rate
                 limiter so retry storms cannot burst past the RPM ceiling.
        rpm_limit: Azure OpenAI RPM ceiling for the rate limiter (default 450 = 10%
                   headroom under the 500 RPM gpt-4o-mini limit).

    Returns:
        (events, failures) -- flat list of extracted event dicts, and list of
        articles that failed extraction after all retries.
    """
    if provider != "azure":
        raise ValueError(
            f"Provider '{provider}' is not supported. This pipeline uses Azure AI Foundry only."
        )

    resolved_model = model or _PROVIDER_DEFAULT_MODELS[provider]
    env_var = _PROVIDER_ENV_VARS[provider]
    resolved_key = api_key or os.environ.get(env_var, "")
    if not resolved_key:
        raise ValueError(
            f"No API key for provider '{provider}'. "
            f"Set {env_var} env var or pass api_key=."
        )

    log.info(f"LLM provider: {provider} | model: {resolved_model}")

    # Build system prompt ONCE before the article loop so all workers share the
    # identical byte sequence -- prerequisite for Azure prompt cache hits.
    if codebook_path is not None:
        run_system = _BASE_SYSTEM_PROMPT + _build_codebook_context(codebook_path)
        log.info(f"Using custom codebook: {codebook_path}")
    else:
        run_system = SYSTEM_PROMPT

    # Rebuild few-shot examples for this run with a run-stable seed.
    resolved_seed = examples_seed if examples_seed is not None else time.time_ns()
    resolved_examples_path = (
        examples_path if examples_path is not None else _EXAMPLES_PATH
    )
    run_examples = _build_few_shot_examples(
        resolved_examples_path,
        sample_n=examples_sample_n,
        seed=resolved_seed,
    )
    if examples_path is not None:
        log.info(f"Using custom examples: {examples_path}")

    # Load already-processed URLs if resuming
    done_urls: set = set()
    if checkpoint_path:
        cp = Path(checkpoint_path)
        if cp.exists():
            done_urls = set(cp.read_text().splitlines())
            log.info(f"Checkpoint: skipping {len(done_urls)} already-processed URLs")

    todo_articles = [a for a in articles if a.get("url", "") not in done_urls]
    log.info(
        f"Articles to process: {len(todo_articles)} "
        f"(skipping {len(articles) - len(todo_articles)} checkpointed)"
    )

    all_events: list = []
    failures: list = []
    _checkpoint_lock = threading.Lock()

    def _write_checkpoint(url: str) -> None:
        if not checkpoint_path:
            return
        with _checkpoint_lock:
            with open(checkpoint_path, "a") as f:
                f.write(url + "\n")

    def _process_one(
        article: dict,
        limiter: Optional[SlidingWindowLimiter] = None,
    ) -> tuple:
        url = article.get("url", "")
        events = extract_from_article(
            article,
            model=resolved_model,
            api_key=resolved_key,
            provider=provider,
            system_prompt=run_system,
            few_shot_examples=run_examples,
            limiter=limiter,
        )
        if events is not None:
            _write_checkpoint(url)
        return url, events

    if workers > 1:
        log.info(f"Concurrent extraction: {workers} workers, rpm_limit={rpm_limit}")

        _limiter = SlidingWindowLimiter(max_requests=rpm_limit, window_seconds=60.0)

        results: list = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_process_one, a, _limiter): a for a in todo_articles}
            for i, future in enumerate(as_completed(futures)):
                url, events = future.result()
                results.append((url, events))
                if upload_to and checkpoint_path and (i + 1) % 10 == 0:
                    upload_checkpoint(upload_to, Path(checkpoint_path).parent)

        for url, events in results:
            if events:
                all_events.extend(events)
            elif events is None:
                article = next((a for a in todo_articles if a.get("url") == url), {})
                failures.append(
                    {
                        "url": url,
                        "title": article.get("title", ""),
                        "reason": "extraction_failed",
                        "lang": article.get("text_lang", "unknown"),
                    }
                )
    else:
        for i, article in enumerate(todo_articles):
            url = article.get("url", "")
            url_display = url[:70]
            log.info(f"[{i+1}/{len(todo_articles)}] Extracting from: {url_display}...")

            url, events = _process_one(article)

            if events:
                log.info(f"  [OK] Found {len(events)} event(s)")
                all_events.extend(events)
            elif events is not None and len(events) == 0:
                log.info("  [--] No events found")
            else:
                log.warning(f"  [FAIL] Extraction failed: {url_display}")
                failures.append(
                    {
                        "url": url,
                        "title": article.get("title", ""),
                        "reason": "extraction_failed",
                        "lang": article.get("text_lang", "unknown"),
                    }
                )

            if upload_to and checkpoint_path and (i + 1) % 10 == 0:
                upload_checkpoint(upload_to, Path(checkpoint_path).parent)

            if i < len(todo_articles) - 1:
                time.sleep(rate_limit_delay)

    n_succeeded = len(todo_articles) - len(failures)
    log.info(
        f"Extraction complete: {len(all_events)} events from "
        f"{n_succeeded} articles ({len(failures)} failures)"
    )
    return all_events, failures
