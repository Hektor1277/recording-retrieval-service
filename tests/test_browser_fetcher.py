from __future__ import annotations

from pathlib import Path

from app.services.browser_fetcher import PlaywrightBrowserFetcher, should_retry_navigation_error


def test_bilibili_context_options_include_storage_state_when_file_exists(tmp_path: Path) -> None:
    storage_path = tmp_path / "bilibili-state.json"
    storage_path.write_text("{}", encoding="utf-8")
    fetcher = PlaywrightBrowserFetcher(
        bilibili_cookie="SESSDATA=abc",
        bilibili_user_agent="UA/1.0",
        bilibili_storage_state_path=str(storage_path),
    )

    options = fetcher._context_options_for_url("https://search.bilibili.com/all?keyword=test")

    assert options["storage_state"] == str(storage_path)
    assert options["user_agent"] == "UA/1.0"
    assert options["extra_http_headers"]["Cookie"] == "SESSDATA=abc"


def test_bilibili_urls_reuse_shared_context() -> None:
    fetcher = PlaywrightBrowserFetcher()

    assert fetcher._should_reuse_shared_context("https://search.bilibili.com/all?keyword=test") is True
    assert fetcher._should_reuse_shared_context("https://www.bilibili.com/video/BV1abc/") is True
    assert fetcher._should_reuse_shared_context("https://www.youtube.com/results?search_query=test") is False


def test_should_retry_navigation_error_only_for_transient_bilibili_navigation_failures() -> None:
    assert should_retry_navigation_error(
        'net::ERR_ABORTED; maybe frame was detached?',
        "https://search.bilibili.com/all?keyword=test",
    ) is True
    assert should_retry_navigation_error(
        "frame was detached during navigation",
        "https://www.bilibili.com/video/BV1abc/",
    ) is True
    assert should_retry_navigation_error(
        "Target page, context or browser has been closed",
        "https://search.bilibili.com/all?keyword=test",
    ) is False
    assert should_retry_navigation_error(
        "net::ERR_ABORTED",
        "https://www.youtube.com/results?search_query=test",
    ) is False
