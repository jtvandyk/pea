"""
Translation Module
==================
Detects article language and translates non-English text to English
for downstream LLM processing.

Strategy (in order of preference):
  1. langdetect for language identification
  2. deep-translator (Google Translate free tier) for translation
  3. Falls back gracefully — untranslated text is still passed to extractor
     with a language tag so the LLM can handle it natively if capable

For Global South sources, this module handles:
  - Arabic, Swahili, Hindi, Urdu, Bengali, Indonesian, Tagalog,
    Portuguese (Brazilian), Spanish, French, and more
"""

import logging
from typing import Optional

log = logging.getLogger(__name__)

# Languages the LLM can handle natively — skip translation for these
# (saves time and avoids translation noise)
NATIVE_LANGUAGES = {
    "en",
    "es",
    "fr",
    "pt",
    "ar",
    "zh",
    "de",
    "it",
    "ru",
    "ja",
    "ko",
    "hi",
    "bn",
    "id",
    "ms",
    "tr",
    "vi",
    "th",
    "tl",
}

# Max characters to translate per article (Google free tier limit awareness)
MAX_CHARS_TO_TRANSLATE = 4000


def detect_language(text: str) -> str:
    """
    Detect the language of a text string.
    Returns ISO 639-1 language code (e.g. 'en', 'ar', 'sw').
    Returns 'unknown' on failure.
    """
    try:
        from langdetect import detect

        # Use first 500 chars for faster detection
        lang = detect(text[:500])
        return lang
    except ImportError:
        log.warning("langdetect not installed — language detection unavailable")
        return "unknown"
    except Exception as e:
        log.debug(f"Language detection failed: {e}")
        return "unknown"


def translate_text(text: str, source_lang: str) -> Optional[str]:
    """
    Translate text to English using deep-translator (Google Translate).

    Args:
        text: text to translate
        source_lang: ISO 639-1 source language code

    Returns:
        translated text or None if translation fails
    """
    try:
        from deep_translator import GoogleTranslator

        # Truncate to avoid rate limits / long processing
        truncated = text[:MAX_CHARS_TO_TRANSLATE]
        if len(text) > MAX_CHARS_TO_TRANSLATE:
            log.debug(
                f"Truncated text from {len(text)} to {MAX_CHARS_TO_TRANSLATE} chars for translation"
            )

        # deep_translator uses language names or codes
        translator = GoogleTranslator(source=source_lang, target="en")
        translated = translator.translate(truncated)
        return translated

    except ImportError:
        log.warning("deep-translator not installed — translation unavailable")
        return None
    except Exception as e:
        log.debug(f"Translation failed ({source_lang} → en): {e}")
        return None


def translate_articles(articles: list[dict]) -> list[dict]:
    """
    Detect language and translate each article's text if needed.
    Adds 'text_lang' and 'text_en' fields to each article dict.

    - 'text_lang': detected ISO language code
    - 'text_en': English text (translated or original if already English)

    Articles without text are skipped.
    """
    translated_count = 0
    native_count = 0
    skipped_count = 0

    for article in articles:
        text = article.get("text")
        if not text:
            article["text_lang"] = None
            article["text_en"] = None
            skipped_count += 1
            continue

        # Detect language
        lang = detect_language(text)
        article["text_lang"] = lang
        log.debug(f"Detected language: {lang} for {article.get('url', '')[:60]}")

        if lang == "en":
            # Already English — no translation needed
            article["text_en"] = text
            native_count += 1

        elif lang in NATIVE_LANGUAGES:
            # Claude can handle this language natively
            # Still provide original, flag as non-English for extractor
            log.info(f"  Language '{lang}' — Claude handles natively, passing as-is")
            article["text_en"] = text  # LLM will handle
            native_count += 1

        else:
            # Translate to English
            log.info(f"  Translating from '{lang}'...")
            translated = translate_text(text, source_lang=lang)
            if translated:
                article["text_en"] = translated
                translated_count += 1
                log.info(f"  ✓ Translated ({lang} → en)")
            else:
                # Translation failed — pass original, note language for LLM
                article["text_en"] = text
                log.info(
                    f"  ✗ Translation failed — passing original '{lang}' text to LLM"
                )

    log.info(
        f"Translation summary: {translated_count} translated, "
        f"{native_count} native/handled, {skipped_count} skipped"
    )
    return articles
