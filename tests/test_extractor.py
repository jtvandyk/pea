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
