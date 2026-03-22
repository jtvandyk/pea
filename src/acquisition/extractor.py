"""
LLM Event Extraction Module
=============================
Extracts structured protest event fields from news article text
using a local Llama model via Ollama (no API key required).

The extractor follows the meta-codebook schema, extracting:
  - Event identification (date, location, country)
  - Actor information (who organised/participated)
  - Event type (protest, strike, riot, etc.)
  - Claims/grievances (what protesters demanded)
  - Size / participation estimate
  - State response (police, military, arrests)
  - Outcome / escalation
  - Fatalities / injuries
  - Source metadata

Multiple events can be reported in a single article.
The LLM is instructed to return a JSON array of event objects.
"""

import json
import logging
import time
from typing import Optional

log = logging.getLogger(__name__)

# Ollama chat endpoint supports system + user roles
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"

SYSTEM_PROMPT = """You are an expert coder for a protest event analysis (PEA) dataset,
specialising in the Global South and non-Western contexts.

Your task is to read a news article and extract structured information about
each distinct protest event described. Follow these rules:

1. Extract ONLY information explicitly stated in the article — do not infer or hallucinate.
2. If a field is not mentioned, use null.
3. One article may contain multiple protest events — return all of them.
4. For location, prefer the most specific level available (city > region > country).
5. For actor names, use the full organisation/group name as given in the article.
6. For event_type, choose the BEST match from: protest, demonstration, march, rally,
   strike, general_strike, sit_in, blockade, riot, uprising, vigil, boycott, other.
7. For state_response, choose from: none, monitoring, dispersal, teargas, water_cannon,
   rubber_bullets, live_ammunition, arrests, ban, curfew, unknown.
8. For outcome, choose from: ongoing, dispersed, arrested, demands_met, partial_concession,
   escalated, unknown.
9. crowd_size should be a numeric estimate if given, or a range string like "hundreds" /
   "thousands" / "tens of thousands" if only approximate language is used.
10. claims should be a brief list of the main demands or grievances.

Return ONLY a valid JSON array. No preamble, no explanation, no markdown fences.
If the article contains no protest events, return an empty array: []

JSON schema for each event:
{
  "event_date": "YYYY-MM-DD or partial date string",
  "country": "country name",
  "city": "city or town name",
  "region": "state/province/region",
  "location_notes": "any additional location context",
  "event_type": "one of the allowed types above",
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
  "confidence": "high / medium / low — your confidence in this extraction"
}"""

USER_PROMPT_TEMPLATE = """Article title: {title}
Article URL: {url}
Article date: {date}
Source country: {source_country}
Original language: {language}

Article text:
{text}

Extract all protest events from this article and return a JSON array."""


def _call_ollama(
    system: str,
    user: str,
    model: str,
    base_url: str,
    timeout: int = 180,
) -> Optional[str]:
    """
    Call local Ollama chat endpoint with system + user messages.
    Returns the assistant response text, or None on failure.
    """
    import requests

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": 0.1},
    }
    try:
        resp = requests.post(
            f"{base_url}/api/chat",
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]
    except Exception as e:
        log.warning(f"Ollama call failed: {e}")
        return None


def _clean_json(text: str) -> str:
    """Remove common LLM JSON formatting issues."""
    import re
    # Strip markdown code fences
    if "```" in text:
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    # Remove trailing commas before ] or } (invalid JSON that llama2 often emits)
    text = re.sub(r",\s*([\]}])", r"\1", text)
    return text.strip()


def _parse_events(raw: str) -> list[dict]:
    """Extract a JSON array of events from the LLM response string."""
    text = _clean_json(raw)

    # Try direct parse
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            # Model wrapped the array: {"events": [...]} or {"data": [...]}
            for val in result.values():
                if isinstance(val, list):
                    return val
        log.warning(f"LLM returned unexpected JSON structure: {type(result)}")
        return []
    except json.JSONDecodeError:
        pass

    # Find the outermost [...] block
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            cleaned = _clean_json(text[start:end + 1])
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

    log.debug(f"Could not parse JSON array from: {text[:200]}")
    return []


def extract_from_article(
    article: dict,
    model: str,
    base_url: str,
    max_retries: int = 2,
) -> list[dict]:
    """
    Run LLM extraction on a single article.
    Returns list of extracted event dicts.
    """
    text = article.get("text_en") or article.get("text") or ""
    lang = article.get("text_lang", "unknown")

    # Skip articles in languages llama2 cannot reliably process.
    # These are articles where translation failed and the language isn't
    # in the set that llama2 handles natively — sending them causes timeouts.
    PROCESSABLE = {
        "en", "es", "fr", "pt", "ar", "de", "it", "ru",
        "hi", "id", "ms", "tr", "unknown",
    }
    if lang not in PROCESSABLE:
        log.info(f"  Skipping untranslatable article (lang={lang}): {article.get('url','')[:60]}")
        return []

    if not text or len(text) < 100:
        log.debug(f"Skipping article with insufficient text: {article.get('url', '')[:60]}")
        return []

    # Truncate to avoid context limits on smaller models
    truncated_text = text[:6000]

    prompt = USER_PROMPT_TEMPLATE.format(
        title=article.get("title", "Unknown"),
        url=article.get("url", ""),
        date=article.get("seendate", "Unknown"),
        source_country=article.get("sourcecountry", "Unknown"),
        language=article.get("text_lang", "unknown"),
        text=truncated_text,
    )

    for attempt in range(max_retries + 1):
        raw = _call_ollama(
            system=SYSTEM_PROMPT,
            user=prompt,
            model=model,
            base_url=base_url,
        )

        if raw is None:
            log.warning(f"Ollama returned nothing (attempt {attempt + 1})")
            if attempt < max_retries:
                time.sleep(2 ** attempt)
            continue

        events = _parse_events(raw)

        if events is not None:  # empty list is valid (no events in article)
            # Discard any non-dict items (llama2 occasionally returns strings)
            events = [e for e in events if isinstance(e, dict)]
            # Backfill metadata fields the LLM may have omitted
            for event in events:
                event.setdefault("article_url", article.get("url", ""))
                event.setdefault("article_title", article.get("title", ""))
                event.setdefault("article_date", article.get("seendate", ""))
                event.setdefault("source_country", article.get("sourcecountry", ""))
                event.setdefault("source_language", article.get("text_lang", "unknown"))
            return events

        log.warning(f"Parse failed (attempt {attempt + 1}), retrying...")
        if attempt < max_retries:
            time.sleep(1)

    return []


def extract_events(
    articles: list[dict],
    model: str = "llama2",
    base_url: str = "http://localhost:11434",
    rate_limit_delay: float = 0.5,
) -> list[dict]:
    """
    Run LLM extraction across all scraped articles.

    Args:
        articles: list of article dicts with 'text_en' field
        model: Ollama model name (default: llama2)
        base_url: Ollama server base URL
        rate_limit_delay: seconds between requests (polite pacing)

    Returns:
        flat list of all extracted event dicts
    """
    all_events = []
    processed = 0
    skipped = 0

    for i, article in enumerate(articles):
        url = article.get("url", "")[:70]
        log.info(f"[{i+1}/{len(articles)}] Extracting from: {url}...")

        events = extract_from_article(article, model=model, base_url=base_url)

        if events:
            log.info(f"  ✓ Found {len(events)} event(s)")
            all_events.extend(events)
            processed += 1
        else:
            log.info(f"  — No events found or extraction failed")
            skipped += 1

        if i < len(articles) - 1:
            time.sleep(rate_limit_delay)

    log.info(
        f"Extraction complete: {len(all_events)} events from "
        f"{processed} articles ({skipped} with no events)"
    )
    return all_events
