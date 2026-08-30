"""Tests for the excluded-cases store (plan §1.5, RTV Excluded Cases pattern)."""

import json
import threading

import pytest

from src.acquisition.excluded_store import (
    _TEXT_CAP,
    load_excluded_cases,
    record_excluded_case,
)


def _article(url="http://x.test/a", text_len=500, **kw):
    art = {
        "url": url,
        "title": "Test article",
        "text_en": "w" * text_len,
        "text_lang": "en",
        "sourcecountry": "Nigeria",
        "_relevance_score": 0.61,
    }
    art.update(kw)
    return art


class TestRecordExcludedCase:
    def test_roundtrip(self, tmp_path):
        path = tmp_path / "excluded.jsonl"
        rec = record_excluded_case(path, _article(), domain="drone", run_id="r1")
        assert rec["domain"] == "drone"
        assert rec["run_id"] == "r1"
        assert rec["reason"] == "llm_returned_empty"
        assert rec["relevance_score"] == 0.61
        loaded = load_excluded_cases(path)
        assert len(loaded) == 1
        assert loaded[0]["url"] == "http://x.test/a"
        assert loaded[0]["source_country"] == "Nigeria"

    def test_text_truncated_to_extractor_cap(self, tmp_path):
        path = tmp_path / "excluded.jsonl"
        record_excluded_case(path, _article(text_len=_TEXT_CAP + 5000))
        (rec,) = load_excluded_cases(path)
        assert len(rec["_article_text"]) == _TEXT_CAP

    def test_appends_and_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "sub" / "dir" / "excluded.jsonl"
        record_excluded_case(path, _article(url="http://x.test/1"))
        record_excluded_case(path, _article(url="http://x.test/2"))
        assert [r["url"] for r in load_excluded_cases(path)] == [
            "http://x.test/1",
            "http://x.test/2",
        ]

    def test_concurrent_writes_produce_valid_lines(self, tmp_path):
        path = tmp_path / "excluded.jsonl"
        threads = [
            threading.Thread(
                target=record_excluded_case,
                args=(path, _article(url=f"http://x.test/{i}")),
            )
            for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        loaded = load_excluded_cases(path)
        assert len(loaded) == 20
        # every line individually parseable
        for line in path.read_text().splitlines():
            json.loads(line)


class TestLoadExcludedCases:
    def test_missing_file_returns_empty(self, tmp_path):
        assert load_excluded_cases(tmp_path / "nope.jsonl") == []

    def test_malformed_line_skipped(self, tmp_path):
        path = tmp_path / "excluded.jsonl"
        record_excluded_case(path, _article())
        with open(path, "a") as f:
            f.write("{not json}\n")
        record_excluded_case(path, _article(url="http://x.test/b"))
        assert len(load_excluded_cases(path)) == 2


class TestExtractEventsWiring:
    """extract_events records excluded cases for LLM-empty articles only."""

    @pytest.fixture
    def articles(self):
        return [
            _article(url="http://x.test/has-events"),
            _article(url="http://x.test/empty"),
            _article(url="http://x.test/short", text_len=50),  # scrape-quality skip
            _article(url="http://x.test/fails"),
        ]

    @pytest.fixture
    def fake_extract(self, monkeypatch):
        def _fake(article, **kwargs):
            url = article.get("url", "")
            if url.endswith("has-events"):
                return [{"event_type": "protest", "article_url": url}]
            if url.endswith("fails"):
                return None
            return []  # both 'empty' and 'short' return [] like the real function

        monkeypatch.setattr("src.acquisition.extractor.extract_from_article", _fake)

    @pytest.mark.parametrize("workers", [1, 2])
    def test_only_llm_empty_recorded(self, tmp_path, articles, fake_extract, workers):
        from src.acquisition.extractor import extract_events

        excluded_path = tmp_path / "excluded.jsonl"
        events, failures = extract_events(
            articles,
            api_key="test-key",
            workers=workers,
            rate_limit_delay=0,
            excluded_path=str(excluded_path),
            domain="protest",
            run_id="testrun",
        )
        assert len(events) == 1
        assert len(failures) == 1
        loaded = load_excluded_cases(excluded_path)
        assert [r["url"] for r in loaded] == ["http://x.test/empty"]
        assert loaded[0]["run_id"] == "testrun"

    def test_no_path_no_file(self, tmp_path, articles, fake_extract):
        from src.acquisition.extractor import extract_events

        events, failures = extract_events(
            articles,
            api_key="test-key",
            workers=1,
            rate_limit_delay=0,
        )
        assert len(events) == 1
        assert not list(tmp_path.iterdir())
