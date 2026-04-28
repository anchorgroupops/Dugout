"""Tests for tools/deduplicator.py — URL normalization and duplicate detection."""
from __future__ import annotations

import pytest

from tools.deduplicator import deduplicate, extract_youtube_id, normalize


# ---------------------------------------------------------------------------
# extract_youtube_id
# ---------------------------------------------------------------------------

class TestExtractYoutubeId:
    @pytest.mark.parametrize("url,expected", [
        # Standard watch URL
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        # With extra params
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30", "dQw4w9WgXcQ"),
        # Short URL
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        # Short URL with tracking param
        ("https://youtu.be/dQw4w9WgXcQ?si=abc123", "dQw4w9WgXcQ"),
        # Shorts URL
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        # Live URL
        ("https://www.youtube.com/live/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        # Mobile subdomain
        ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ])
    def test_extracts_id(self, url, expected):
        assert extract_youtube_id(url) == expected

    def test_non_youtube_returns_none(self):
        assert extract_youtube_id("https://example.com/video") is None

    def test_youtube_watch_without_v_param_returns_none(self):
        assert extract_youtube_id("https://www.youtube.com/channel/UCxyz") is None

    def test_empty_string_returns_none(self):
        assert extract_youtube_id("") is None


# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_youtube_canonical_form(self):
        url = "https://youtu.be/dQw4w9WgXcQ?si=tracking123"
        assert normalize(url) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_youtube_shorts_canonical(self):
        url = "https://www.youtube.com/shorts/dQw4w9WgXcQ"
        assert normalize(url) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_tracking_params_stripped(self):
        url = "https://example.com/page?utm_source=twitter&utm_medium=social&real_param=1"
        result = normalize(url)
        assert "utm_source" not in result
        assert "utm_medium" not in result
        assert "real_param=1" in result

    def test_trailing_slash_stripped(self):
        url = "https://example.com/page/"
        result = normalize(url)
        assert not result.endswith("/")

    def test_fragment_stripped(self):
        url = "https://example.com/page#section"
        assert "#" not in normalize(url)

    def test_scheme_lowercased(self):
        result = normalize("HTTPS://Example.COM/path")
        assert result.startswith("https://")

    def test_netloc_lowercased(self):
        result = normalize("https://EXAMPLE.COM/path")
        assert "example.com" in result

    def test_non_tracking_params_preserved(self):
        url = "https://example.com/search?q=softball&page=2"
        result = normalize(url)
        assert "q=softball" in result
        assert "page=2" in result

    def test_params_sorted_consistently(self):
        url_a = "https://example.com/?z=last&a=first"
        url_b = "https://example.com/?a=first&z=last"
        assert normalize(url_a) == normalize(url_b)

    def test_idempotent(self):
        url = "https://example.com/page?utm_source=x&keep=1"
        assert normalize(normalize(url)) == normalize(url)

    def test_youtube_idempotent(self):
        url = "https://youtu.be/abc123?si=xyz"
        assert normalize(normalize(url)) == normalize(url)

    def test_fbclid_stripped(self):
        url = "https://example.com/article?fbclid=IwABC123&id=42"
        result = normalize(url)
        assert "fbclid" not in result
        assert "id=42" in result

    def test_ref_param_stripped(self):
        url = "https://example.com/page?ref=homepage&article=5"
        result = normalize(url)
        assert "ref=" not in result


# ---------------------------------------------------------------------------
# deduplicate
# ---------------------------------------------------------------------------

class TestDeduplicate:
    def test_empty_candidates(self):
        result = deduplicate([], existing_urls=set())
        assert result["candidates_in"] == 0
        assert result["duplicates_found"] == 0
        assert result["clean_queue"] == []

    def test_no_duplicates_all_pass_through(self):
        candidates = [
            {"url": "https://example.com/a", "title": "A"},
            {"url": "https://example.com/b", "title": "B"},
        ]
        result = deduplicate(candidates, existing_urls=set())
        assert result["duplicates_found"] == 0
        assert len(result["clean_queue"]) == 2

    def test_duplicate_against_existing(self):
        existing = {"https://www.youtube.com/watch?v=abc123"}
        candidates = [{"url": "https://youtu.be/abc123?si=xyz", "title": "Video"}]
        result = deduplicate(candidates, existing_urls=existing)
        assert result["duplicates_found"] == 1
        assert result["clean_queue"] == []

    def test_within_run_dedup(self):
        candidates = [
            {"url": "https://youtu.be/vid123", "title": "First"},
            {"url": "https://www.youtube.com/watch?v=vid123", "title": "Duplicate"},
        ]
        result = deduplicate(candidates, existing_urls=set())
        assert result["duplicates_found"] == 1
        assert len(result["clean_queue"]) == 1

    def test_normalized_url_stored_in_clean_queue(self):
        candidates = [{"url": "https://youtu.be/abc?si=tracking", "title": "X"}]
        result = deduplicate(candidates, existing_urls=set())
        item = result["clean_queue"][0]
        assert item["url_normalized"] == "https://www.youtube.com/watch?v=abc"

    def test_item_with_no_url_skipped(self):
        candidates = [
            {"url": "", "title": "No URL"},
            {"url": "https://example.com/valid", "title": "Valid"},
        ]
        result = deduplicate(candidates, existing_urls=set())
        assert result["candidates_in"] == 2
        assert len(result["clean_queue"]) == 1

    def test_tracking_params_cause_dedup(self):
        existing = {"https://example.com/page"}
        candidates = [{"url": "https://example.com/page?utm_source=email", "title": "X"}]
        result = deduplicate(candidates, existing_urls=existing)
        assert result["duplicates_found"] == 1

    def test_counts_are_accurate(self):
        existing = {"https://example.com/old"}
        candidates = [
            {"url": "https://example.com/old", "title": "Old"},
            {"url": "https://example.com/new1", "title": "New 1"},
            {"url": "https://example.com/new2", "title": "New 2"},
        ]
        result = deduplicate(candidates, existing_urls=existing)
        assert result["candidates_in"] == 3
        assert result["duplicates_found"] == 1
        assert len(result["clean_queue"]) == 2

    def test_original_fields_preserved_in_clean_queue(self):
        candidates = [{"url": "https://example.com/page", "title": "My Page", "custom": "data"}]
        result = deduplicate(candidates, existing_urls=set())
        item = result["clean_queue"][0]
        assert item["title"] == "My Page"
        assert item["custom"] == "data"

    def test_existing_urls_normalized_before_comparison(self):
        existing = {"https://youtu.be/VIDEO_ID"}
        candidates = [{"url": "https://www.youtube.com/watch?v=VIDEO_ID", "title": "V"}]
        result = deduplicate(candidates, existing_urls=existing)
        assert result["duplicates_found"] == 1


# ---------------------------------------------------------------------------
# Property-based tests (hypothesis)
# ---------------------------------------------------------------------------
from hypothesis import given, settings
from hypothesis import strategies as st

import pytest


@pytest.mark.property
class TestNormalizeProperty:
    _urls = st.one_of(
        st.just("https://example.com/page"),
        st.just("https://youtu.be/dQw4w9WgXcQ"),
        st.just("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        st.just("https://www.youtube.com/shorts/abc123"),
        st.just("https://example.com/page?utm_source=x&keep=1"),
        st.just("https://example.com/page?a=1&z=2"),
    )

    @given(_urls)
    def test_normalize_is_idempotent(self, url):
        assert normalize(normalize(url)) == normalize(url)

    @given(_urls)
    def test_normalize_strips_fragment(self, url):
        url_with_frag = url + "#section"
        assert "#" not in normalize(url_with_frag)

    @given(_urls)
    def test_normalize_returns_string(self, url):
        assert isinstance(normalize(url), str)
