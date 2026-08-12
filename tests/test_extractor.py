"""Unit tests for JSON parsing helpers in src/acquisition/extractor.py.

No API key or network access required — all tests operate on _clean_json
and _parse_events which are pure string/JSON functions.
"""

import pytest
from src.acquisition.extractor import _clean_json, _parse_events


# ── _clean_json ──────────────────────────────────────────────────────────────


class TestCleanJson:
    def test_plain_json_unchanged(self):
        raw = '[{"event_type": "demonstration_march"}]'
        assert _clean_json(raw) == raw

    def test_strips_whitespace(self):
        raw = '  [{"a": 1}]  '
        assert _clean_json(raw) == '[{"a": 1}]'

    def test_removes_markdown_fence(self):
        raw = '```json\n[{"event_type": "riot"}]\n```'
        result = _clean_json(raw)
        assert "```" not in result
        assert "riot" in result

    def test_removes_fence_without_language_tag(self):
        raw = "```\n[{}]\n```"
        result = _clean_json(raw)
        assert "```" not in result

    def test_strips_json_language_prefix(self):
        raw = "```json\n[{}]\n```"
        result = _clean_json(raw)
        assert not result.startswith("json")

    def test_removes_trailing_commas_before_bracket(self):
        raw = '[{"a": 1,}]'
        result = _clean_json(raw)
        assert result == '[{"a": 1}]'

    def test_removes_trailing_commas_before_brace(self):
        raw = '{"a": 1, "b": [1, 2,]}'
        result = _clean_json(raw)
        assert result == '{"a": 1, "b": [1, 2]}'


# ── _parse_events ─────────────────────────────────────────────────────────────


class TestParseEvents:
    def test_clean_json_array(self):
        raw = '[{"event_type": "riot", "country": "Nigeria"}]'
        result = _parse_events(raw)
        assert len(result) == 1
        assert result[0]["event_type"] == "riot"

    def test_empty_array(self):
        assert _parse_events("[]") == []

    def test_fenced_json(self):
        raw = '```json\n[{"event_type": "strike_boycott"}]\n```'
        result = _parse_events(raw)
        assert len(result) == 1
        assert result[0]["event_type"] == "strike_boycott"

    def test_trailing_comma_tolerated(self):
        raw = '[{"event_type": "vigil",}]'
        result = _parse_events(raw)
        assert len(result) == 1

    def test_array_embedded_in_prose(self):
        raw = 'Here are the events:\n[{"event_type": "riot"}]\nEnd.'
        result = _parse_events(raw)
        assert len(result) == 1
        assert result[0]["event_type"] == "riot"

    def test_dict_with_list_value_unwrapped(self):
        raw = '{"events": [{"event_type": "confrontation"}]}'
        result = _parse_events(raw)
        assert len(result) == 1
        assert result[0]["event_type"] == "confrontation"

    def test_multiple_events(self):
        raw = '[{"event_type": "riot"}, {"event_type": "vigil"}]'
        result = _parse_events(raw)
        assert len(result) == 2

    def test_completely_unparseable_returns_empty(self):
        assert _parse_events("No events found in this article.") == []

    def test_content_filter_sentinel_not_parsed(self):
        # __CONTENT_FILTERED__ is handled upstream; _parse_events sees it as garbage
        assert _parse_events("__CONTENT_FILTERED__") == []

    def test_none_equivalent_empty_string(self):
        assert _parse_events("") == []


# ── system prompt parameterization ───────────────────────────────────────────


class TestBuildSystemPrompt:
    """The extraction_prompt YAML section drives the rendered base prompt
    (verified byte-identical to the legacy _BASE_SYSTEM_PROMPT at the v2.4
    refactor, before v3.0 additions), and codebooks without the section must
    fall back to the legacy prompt byte-identically."""

    def test_protest_prompt_structure(self):
        """The rendered protest prompt carries the full STEP 1/2/3 scaffolding,
        the current metadata.version, every taxonomy key, the issue_tags field,
        and the injected event-type definitions."""
        import yaml
        from src.acquisition.extractor import _CODEBOOK_PATH, _build_system_prompt

        with open(_CODEBOOK_PATH) as f:
            cb = yaml.safe_load(f)
        rendered = _build_system_prompt(_CODEBOOK_PATH)

        version = cb["metadata"]["version"]
        assert f"codebook version {version}" in rendered
        assert "== STEP 1: DISQUALIFY NON-PROTEST ARTICLES FIRST ==" in rendered
        assert "== STEP 2: APPLY MINIMUM CRITERIA ==" in rendered
        assert "== STEP 3: EXTRACT EVENTS ==" in rendered
        assert '"issue_tags":' in rendered  # v3.0 output schema field
        for key in cb["event_types"]:
            assert f"- {key}" in rendered  # generated valid-key list
            assert f"TYPE: {key.upper()}" in rendered  # injected definitions
        assert "== FULL EVENT TYPE DEFINITIONS" in rendered

    def test_issue_taxonomy_keys_in_prompt(self):
        """Every closed issue_taxonomy key must appear in the rendered prompt's
        issue_tags rule, so the LLM sees the full closed vocabulary."""
        import yaml
        from src.acquisition.extractor import _CODEBOOK_PATH, _build_system_prompt

        with open(_CODEBOOK_PATH) as f:
            cb = yaml.safe_load(f)
        rendered = _build_system_prompt(_CODEBOOK_PATH)
        for tag in cb["issue_taxonomy"]:
            assert tag in rendered, f"issue tag '{tag}' missing from prompt"

    def test_fallback_without_extraction_prompt(self, tmp_path):
        """A codebook lacking extraction_prompt gets the legacy base prompt."""
        import yaml
        from src.acquisition.extractor import (
            _BASE_SYSTEM_PROMPT,
            _CODEBOOK_PATH,
            _build_system_prompt,
        )

        with open(_CODEBOOK_PATH) as f:
            cb = yaml.safe_load(f)
        cb.pop("extraction_prompt")
        stripped = tmp_path / "no_prompt_codebook.yaml"
        stripped.write_text(yaml.safe_dump(cb, allow_unicode=True))

        rendered = _build_system_prompt(stripped)
        assert rendered.startswith(_BASE_SYSTEM_PROMPT)

    def test_unreadable_codebook_falls_back_to_base(self, tmp_path):
        from src.acquisition.extractor import _BASE_SYSTEM_PROMPT, _build_system_prompt

        rendered = _build_system_prompt(tmp_path / "does_not_exist.yaml")
        assert rendered == _BASE_SYSTEM_PROMPT

    def test_event_type_keys_generated_from_taxonomy(self):
        """The STEP 3 valid-key list is generated from event_types, so adding
        or renaming a type can never desync the prompt from the taxonomy."""
        import yaml
        from src.acquisition.extractor import _CODEBOOK_PATH, _render_extraction_prompt

        with open(_CODEBOOK_PATH) as f:
            cb = yaml.safe_load(f)
        rendered = _render_extraction_prompt(cb)
        for key in cb["event_types"]:
            assert f"- {key}" in rendered

    def test_renamed_type_flows_into_prompt(self):
        import copy
        import yaml
        from src.acquisition.extractor import _CODEBOOK_PATH, _render_extraction_prompt

        with open(_CODEBOOK_PATH) as f:
            cb = yaml.safe_load(f)
        mutated = copy.deepcopy(cb)
        mutated["event_types"]["totally_new_type"] = mutated["event_types"].pop("vigil")
        rendered = _render_extraction_prompt(mutated)
        assert "- totally_new_type" in rendered

    def test_version_templated_from_metadata(self):
        import copy
        import yaml
        from src.acquisition.extractor import _CODEBOOK_PATH, _render_extraction_prompt

        with open(_CODEBOOK_PATH) as f:
            cb = yaml.safe_load(f)
        mutated = copy.deepcopy(cb)
        mutated["metadata"]["version"] = "99.9"
        assert "codebook version 99.9" in _render_extraction_prompt(mutated)
