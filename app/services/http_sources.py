from __future__ import annotations

import asyncio
import base64
import contextvars
import html
import json
import re
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote_plus, urljoin, urlparse

import httpx

from app.services.browser_fetcher import BrowserFetchUnavailable, PlaywrightBrowserFetcher
from app.services.platform_clients import BilibiliVideoDetail, PlatformSearchClients
from app.services.platform_search_config import PlatformSearchConfig, load_platform_search_config
from app.services.pipeline import (
    DraftRecordingEntry,
    LOW_CONFIDENCE_THRESHOLD,
    RetrievalProfile,
    build_queries,
    build_work_query,
    contains_cjk,
    has_collaboration_marker,
    looks_latin,
)
from app.services.source_profiles import (
    OrchestraAliasLoader,
    PersonAliasLoader,
    SourceProfileEntry,
    SourceProfileLoader,
    default_orchestra_alias_path,
    default_person_alias_path,
)

DEFAULT_HEADERS = {
    "user-agent": "Mozilla/5.0 (compatible; RecordingRetrievalService/0.1; +https://example.invalid)",
}

HOST_QUERY_DEPTH = 6
ENGINE_RESULT_DEPTH = 6
STREAMING_RESULT_DEPTH = 8
HYDRATE_DEPTH = 12
HOST_SEARCH_DEPTH = 5


class BrowserFetcher(Protocol):
    async def fetch_page(self, url: str, timeout_seconds: float | None = None) -> dict[str, str]: ...

    async def fetch_links(
        self,
        url: str,
        *,
        url_patterns: list[str] | None = None,
        timeout_seconds: float | None = None,
    ) -> list[str]: ...


def compact(value: Any) -> str:
    return str(value or "").strip()


def sanitize_bilibili_metadata_text(value: str) -> str:
    cleaned = compact(value)
    if not cleaned:
        return ""
    markers = [
        "相关视频",
        "作者简介",
        "视频作者",
        "视频播放量",
        "弹幕量",
        "点赞数",
        "投硬币枚数",
        "收藏人数",
        "转发人数",
    ]
    cut_points = [cleaned.find(marker) for marker in markers if marker in cleaned]
    if cut_points:
        cleaned = cleaned[: min(cut_points)]
    cleaned = re.sub(r"©\s*\d+\s*,?\s*$", "", cleaned, flags=re.I)
    return compact(cleaned.strip(" ,;|/-\n"))


def materials_root() -> Path:
    return Path(__file__).resolve().parents[2] / "materials" / "source-profiles"


def build_bilibili_metadata_from_detail(detail: BilibiliVideoDetail) -> dict[str, Any]:
    parts = " ".join(compact(part) for part in detail.page_parts[:4] if compact(part))
    description = compact(detail.description)
    return {
        "title": compact(detail.title),
        "description": description,
        "body_text": compact(" ".join(part for part in [compact(detail.title), compact(detail.uploader), parts] if part)),
        "image_url": compact(detail.image_url),
        "uploader": compact(detail.uploader),
        "bvid": compact(detail.bvid),
        "duration_seconds": int(detail.duration_seconds or 0),
        "view_count": int(detail.view_count or 0),
    }


class HttpSourceProvider:
    def __init__(
        self,
        profile_loader: SourceProfileLoader | None = None,
        client: httpx.AsyncClient | None = None,
        browser_fetcher: BrowserFetcher | None = None,
        orchestra_alias_loader: OrchestraAliasLoader | None = None,
        person_alias_loader: PersonAliasLoader | None = None,
        platform_search_config: PlatformSearchConfig | None = None,
    ) -> None:
        self._profile_loader = profile_loader or SourceProfileLoader(materials_root())
        self._client = client
        self._orchestra_alias_loader = orchestra_alias_loader or OrchestraAliasLoader(default_orchestra_alias_path())
        self._person_alias_loader = person_alias_loader or PersonAliasLoader(default_person_alias_path())
        self._platform_search_config = platform_search_config or load_platform_search_config()
        self._browser_fetcher = browser_fetcher or PlaywrightBrowserFetcher(
            bilibili_cookie=self._platform_search_config.bilibili.cookie,
            bilibili_user_agent=self._platform_search_config.bilibili.user_agent,
            bilibili_referer=self._platform_search_config.bilibili.referer,
            bilibili_storage_state_path=self._platform_search_config.bilibili.storage_state_path,
        )
        self._disabled_platform_apis: set[str] = set()
        self._text_cache: dict[str, str] = {}
        self._thread_local = threading.local()
        self._warning_state: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar("http_source_warnings", default=None)
        self._request_access_state: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar(
            "http_source_access_events",
            default=None,
        )
        self._access_events: list[dict[str, Any]] = []
        self._host_stats: dict[str, dict[str, float]] = {}
        self._state_lock = threading.RLock()

    async def aclose(self) -> None:
        browser_fetcher = getattr(self._browser_fetcher, "aclose", None)
        if callable(browser_fetcher):
            await browser_fetcher()
        client = self._client
        if client is not None:
            with suppress(Exception):
                await client.aclose()
        thread_client = getattr(self._thread_local, "client", None)
        if thread_client is not None and thread_client is not client:
            with suppress(Exception):
                await thread_client.aclose()
        self._thread_local.client = None
        self._thread_local.client_loop = None

    def start_request_scope(self) -> None:
        self._warning_state.set([])
        self._request_access_state.set([])

    def consume_warnings(self) -> list[str]:
        warnings = self._warning_state.get() or []
        self._warning_state.set([])
        return dedupe_text(warnings)

    def consume_access_events(self) -> list[dict[str, Any]]:
        request_events = self._request_access_state.get()
        if request_events is not None:
            events = list(request_events)
            self._request_access_state.set([])
            return events
        with self._state_lock:
            events = list(self._access_events)
            self._access_events.clear()
        return events

    def get_access_summary(self) -> dict[str, Any]:
        hosts: dict[str, Any] = {}
        with self._state_lock:
            host_items = list(self._host_stats.items())
            fallback_event_count = len(self._access_events)
        for host, stats in host_items:
            requests = int(stats.get("requests", 0))
            successes = int(stats.get("successes", 0))
            failures = int(stats.get("failures", 0))
            total_latency = float(stats.get("totalLatencyMs", 0.0))
            total_results = float(stats.get("totalResults", 0.0))
            cache_hits = int(stats.get("cacheHits", 0))
            failure_rate = failures / requests if requests else 0.0
            avg_latency = total_latency / requests if requests else 0.0
            avg_results = total_results / requests if requests else 0.0
            hosts[host] = {
                "requests": requests,
                "successes": successes,
                "failures": failures,
                "cacheHits": cache_hits,
                "avgLatencyMs": round(avg_latency, 2),
                "avgResultCount": round(avg_results, 2),
                "failureRate": round(failure_rate, 3),
                "recommendedTimeoutSeconds": self._recommended_timeout_seconds(host, 6.0),
                "recommendedQueryDepth": self._recommended_query_depth(host, HOST_QUERY_DEPTH),
                "recommendedResultDepth": self._recommended_result_depth(host, STREAMING_RESULT_DEPTH),
                "status": self._host_health_status(host),
            }
        request_event_count = len(self._request_access_state.get() or [])
        return {"hosts": hosts, "eventCount": request_event_count or fallback_event_count}

    def _reset_warnings(self) -> None:
        self._warning_state.set([])

    def _warn(self, message: str) -> None:
        warnings = list(self._warning_state.get() or [])
        warnings.append(message)
        self._warning_state.set(warnings)

    def _record_access_event(
        self,
        *,
        url: str,
        operation: str,
        ok: bool,
        duration_ms: float,
        source_kind: str = "",
        source_label: str = "",
        query: str = "",
        result_count: int = 0,
        status_code: int | None = None,
        error: str = "",
        cache_hit: bool = False,
        timeout_seconds: float | None = None,
    ) -> None:
        host = urlparse(url).netloc.lower() or normalize_host(url)
        event = {
            "host": host,
            "url": url,
            "operation": operation,
            "sourceKind": source_kind,
            "sourceLabel": source_label,
            "query": query,
            "ok": ok,
            "durationMs": round(duration_ms, 2),
            "statusCode": status_code,
            "error": error,
            "cacheHit": cache_hit,
            "resultCount": result_count,
            "timeoutSeconds": timeout_seconds,
        }
        request_events = self._request_access_state.get()
        if request_events is not None:
            request_events.append(event)
        else:
            with self._state_lock:
                self._access_events.append(event)

        with self._state_lock:
            stats = self._host_stats.setdefault(
                host,
                {
                    "requests": 0.0,
                    "successes": 0.0,
                    "failures": 0.0,
                    "totalLatencyMs": 0.0,
                    "totalResults": 0.0,
                    "cacheHits": 0.0,
                },
            )
            stats["requests"] += 1
            stats["successes"] += 1 if ok else 0
            stats["failures"] += 0 if ok else 1
            stats["totalLatencyMs"] += max(0.0, duration_ms)
            stats["totalResults"] += max(0, result_count)
            stats["cacheHits"] += 1 if cache_hit else 0

    def _host_health_status(self, host: str) -> str:
        with self._state_lock:
            stats = dict(self._host_stats.get(host, {}))
        requests = float(stats.get("requests", 0.0))
        failures = float(stats.get("failures", 0.0))
        avg_latency = float(stats.get("totalLatencyMs", 0.0)) / requests if requests else 0.0
        if requests >= 2 and (failures >= 1 or failures / requests >= 0.25 or avg_latency >= 2500):
            return "degraded"
        if requests >= 2 and failures == 0 and avg_latency <= 1000:
            return "healthy"
        return "observing"

    def _recommended_timeout_seconds(self, host: str, base_timeout: float) -> float:
        with self._state_lock:
            stats = dict(self._host_stats.get(host, {}))
        requests = float(stats.get("requests", 0.0))
        failures = float(stats.get("failures", 0.0))
        avg_latency = float(stats.get("totalLatencyMs", 0.0)) / requests if requests else 0.0
        timeout = base_timeout
        if requests >= 2 and failures >= 1:
            timeout *= 1.2
        if requests >= 2 and (failures / requests >= 0.25 or avg_latency >= 2500):
            timeout *= 1.7
        elif requests >= 2 and failures == 0 and avg_latency <= 800:
            timeout *= 0.9
        return round(max(4.0, min(14.0, timeout)), 1)

    def _recommended_query_depth(self, host: str, base_depth: int) -> int:
        with self._state_lock:
            stats = dict(self._host_stats.get(host, {}))
        requests = float(stats.get("requests", 0.0))
        failures = float(stats.get("failures", 0.0))
        avg_results = float(stats.get("totalResults", 0.0)) / requests if requests else 0.0
        depth = base_depth
        if requests >= 2 and failures / requests >= 0.4:
            depth -= 2
        elif requests >= 2 and failures == 0 and avg_results >= 2.0:
            depth += 1
        elif requests >= 3 and avg_results < 0.5:
            depth -= 1
        return max(2, min(10, depth))

    def _recommended_result_depth(self, host: str, base_depth: int) -> int:
        with self._state_lock:
            stats = dict(self._host_stats.get(host, {}))
        requests = float(stats.get("requests", 0.0))
        avg_results = float(stats.get("totalResults", 0.0)) / requests if requests else 0.0
        if requests >= 2 and avg_results >= 4.0:
            return min(base_depth + 2, 12)
        if requests >= 3 and avg_results < 1.0:
            return max(base_depth - 2, 4)
        return base_depth

    def _should_skip_host(self, host: str, *, min_requests: int = 3) -> bool:
        with self._state_lock:
            stats = dict(self._host_stats.get(host, {}))
        requests = int(stats.get("requests", 0.0))
        successes = int(stats.get("successes", 0.0))
        failures = int(stats.get("failures", 0.0))
        if requests < min_requests:
            return False
        if successes == 0 and failures >= min_requests:
            return True
        return failures / max(1, requests) >= 0.85

    def _get_http_client(self) -> httpx.AsyncClient:
        client = self._client
        if client is not None:
            return client
        current_loop = asyncio.get_running_loop()
        client = getattr(self._thread_local, "client", None)
        client_loop = getattr(self._thread_local, "client_loop", None)
        if client is None or client_loop is not current_loop:
            client = httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=6.0)
            self._thread_local.client = client
            self._thread_local.client_loop = current_loop
        return client

    def _platform_clients(self) -> PlatformSearchClients:
        return PlatformSearchClients(self._platform_search_config, self._get_http_client())

    def _request_headers_for_url(self, url: str) -> dict[str, str] | None:
        host = urlparse(url).netloc.lower()
        if "bilibili.com" not in host and "b23.tv" not in host:
            return None
        headers = {
            "referer": self._platform_search_config.bilibili.referer or "https://www.bilibili.com",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        if compact(self._platform_search_config.bilibili.user_agent):
            headers["user-agent"] = self._platform_search_config.bilibili.user_agent
        if compact(self._platform_search_config.bilibili.cookie):
            headers["cookie"] = self._platform_search_config.bilibili.cookie
        return headers

    def _is_platform_api_disabled(self, api_label: str) -> bool:
        with self._state_lock:
            return compact(api_label).lower() in self._disabled_platform_apis

    def _disable_platform_api(self, api_label: str) -> None:
        normalized = compact(api_label).lower()
        if normalized:
            with self._state_lock:
                self._disabled_platform_apis.add(normalized)

    def _can_use_youtube_api(self) -> bool:
        return bool(
            self._platform_search_config.enabled
            and self._platform_search_config.youtube.enabled
            and compact(self._platform_search_config.youtube.api_key)
        )

    def _can_use_apple_music_api(self) -> bool:
        return bool(
            self._platform_search_config.enabled
            and self._platform_search_config.apple_music.enabled
            and compact(self._platform_search_config.apple_music.developer_token)
        )

    def _can_use_apple_music_public_api(self) -> bool:
        return bool(
            self._platform_search_config.enabled
            and self._platform_search_config.apple_music.enabled
            and self._platform_search_config.apple_music.use_itunes_fallback
        )

    def _can_use_bilibili_api(self) -> bool:
        return bool(
            self._platform_search_config.enabled
            and self._platform_search_config.bilibili.enabled
            and (
                compact(self._platform_search_config.bilibili.cookie)
                or compact(self._platform_search_config.bilibili.user_agent)
                or compact(self._platform_search_config.bilibili.storage_state_path)
            )
        )

    async def inspect_existing_links(self, draft: DraftRecordingEntry, profile: RetrievalProfile) -> list[dict[str, Any]]:
        del profile
        self._reset_warnings()
        semaphore = asyncio.Semaphore(4)
        tasks = [
            self._fetch_page_record(link["url"], "Existing Link", "existing-link", draft, semaphore)
            for link in draft.existing_links[:3]
        ]
        return [item for item in await asyncio.gather(*tasks, return_exceptions=False) if item]

    async def search_high_quality(self, draft: DraftRecordingEntry, profile: RetrievalProfile) -> list[dict[str, Any]]:
        self._reset_warnings()
        profiles = self._profile_loader.load(category=profile.category, tags=profile.tags)
        return await self._search_hosts(draft, profile, profiles.high_quality[:HOST_SEARCH_DEPTH], source_kind="high-quality")

    async def search_streaming(self, draft: DraftRecordingEntry, profile: RetrievalProfile) -> list[dict[str, Any]]:
        self._reset_warnings()
        self._thread_local.current_draft = draft
        profiles = self._profile_loader.load(category=profile.category, tags=profile.tags)
        streaming_hosts = sorted(profiles.streaming[:HOST_SEARCH_DEPTH], key=lambda host: streaming_host_priority(host.url))

        async def run_host(host: SourceProfileEntry) -> tuple[SourceProfileEntry, list[dict[str, str]]]:
            normalized_host = normalize_host(host.url)
            if self._should_skip_host(normalized_host, min_requests=2):
                self._warn(f"{normalized_host} 连续失败，当前请求暂时跳过。")
                return host, []
            timeout_seconds = self._streaming_host_timeout_seconds(draft, profile, host)
            try:
                host_rows = await asyncio.wait_for(self._search_streaming_host(draft, profile, host), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                self._warn(f"{normalized_host} 资源平台搜索超时。")
                self._record_access_event(
                    url=host.url,
                    operation="streaming-host",
                    ok=False,
                    duration_ms=timeout_seconds * 1000,
                    source_kind="streaming",
                    source_label=normalized_host,
                    error="timeout",
                    timeout_seconds=timeout_seconds,
                )
                return host, []
            return host, host_rows

        primary_hosts = [host for host in streaming_hosts if streaming_host_priority(host.url)[0] == 0]
        auxiliary_hosts = [host for host in streaming_hosts if streaming_host_priority(host.url)[0] != 0]

        primary_results = await asyncio.gather(*(run_host(host) for host in primary_hosts), return_exceptions=False)
        host_results = list(primary_results)
        if should_search_auxiliary_streaming_hosts(primary_results):
            auxiliary_results = await asyncio.gather(*(run_host(host) for host in auxiliary_hosts), return_exceptions=False)
            host_results.extend(auxiliary_results)

        rows = merge_streaming_host_rows(host_results)
        initial_depth = HYDRATE_DEPTH
        if should_expand_initial_streaming_window(host_results):
            initial_depth = min(len(rows), HYDRATE_DEPTH + 4)
        hydrated_rows = await self._hydrate_results(draft, rows[:initial_depth], "streaming")
        if len(rows) > initial_depth and not any(
            float(row.get("same_recording_score", 0.0) or 0.0) >= LOW_CONFIDENCE_THRESHOLD for row in hydrated_rows
        ):
            extended_depth = min(len(rows), initial_depth + 6)
            hydrated_rows = await self._hydrate_results(draft, rows[:extended_depth], "streaming")
        return hydrated_rows

    def _streaming_host_timeout_seconds(
        self,
        draft: DraftRecordingEntry,
        profile: RetrievalProfile,
        host: SourceProfileEntry,
    ) -> float:
        normalized_host = normalize_host(host.url)
        base_timeout = self._recommended_timeout_seconds(normalized_host, 10.0)
        query_count = len(self._queries_for_host(draft, profile, host))
        query_depth = min(query_count, self._recommended_query_depth(normalized_host, HOST_QUERY_DEPTH))
        timeout_scale = 1.0 + max(0, query_depth - 1) * 0.28
        return round(min(30.0, max(10.0, base_timeout * timeout_scale)), 1)

    async def search_fallback(self, draft: DraftRecordingEntry, profile: RetrievalProfile) -> list[dict[str, Any]]:
        self._reset_warnings()
        tasks = [
            self._search_query_via_engines(
                query=query,
                source_label="Web Search",
                source_kind="search",
            )
            for query in profile.queries[:HOST_QUERY_DEPTH]
        ]
        rows: list[dict[str, str]] = []
        for group in await asyncio.gather(*tasks, return_exceptions=False):
            rows.extend(group)
            rows = dedupe_rows(rows)
            if len(rows) >= HYDRATE_DEPTH:
                break
        return await self._hydrate_results(draft, rows[:HYDRATE_DEPTH], "search")

    async def _search_hosts(
        self,
        draft: DraftRecordingEntry,
        profile: RetrievalProfile,
        hosts: list[SourceProfileEntry],
        source_kind: str,
    ) -> list[dict[str, Any]]:
        tasks = []
        for host in hosts:
            normalized_host = normalize_host(host.url)
            if self._should_skip_host(normalized_host, min_requests=2):
                self._warn(f"{normalized_host} 已因连续失败暂时跳过。")
                continue
            query_depth = self._recommended_query_depth(normalized_host, HOST_QUERY_DEPTH)
            for query in self._queries_for_host(draft, profile, host)[:query_depth]:
                tasks.append(
                    self._search_query_via_engines(
                        query=f"site:{normalized_host} {query}",
                        source_label=f"Site Search {normalized_host}",
                        source_kind=source_kind,
                    )
                )
        rows: list[dict[str, str]] = []
        for group in await asyncio.gather(*tasks, return_exceptions=False):
            rows.extend(group)
        return await self._hydrate_results(draft, rows[:HYDRATE_DEPTH], source_kind)

    async def _search_streaming_host(
        self,
        draft: DraftRecordingEntry,
        profile: RetrievalProfile,
        host: SourceProfileEntry,
    ) -> list[dict[str, str]]:
        normalized_host = normalize_host(host.url)
        queries = self._queries_for_host(draft, profile, host)
        if "youtube.com" in normalized_host or "youtu.be" in normalized_host:
            return await self._search_youtube(queries)
        if "bilibili.com" in normalized_host:
            return await self._search_bilibili(queries)
        if "apple.com" in normalized_host:
            return await self._search_apple_music(queries)
        return await self._search_hosts(draft, profile, [host], source_kind="streaming")

    async def _search_query_via_engines(self, *, query: str, source_label: str, source_kind: str) -> list[dict[str, str]]:
        engines = [
            ("bing", f"https://www.bing.com/search?q={quote_plus(query)}", extract_bing_result_links),
        ]
        active_engines = []
        for engine_name, engine_url, parser in engines:
            if self._should_skip_host(urlparse(engine_url).netloc.lower(), min_requests=3):
                continue
            active_engines.append((engine_name, engine_url, parser))
        if not active_engines:
            active_engines.append(("bing", f"https://www.bing.com/search?q={quote_plus(query)}", extract_bing_result_links))

        async def run_engine(engine_name: str, url: str, parser) -> list[dict[str, str]]:
            started = time.perf_counter()
            try:
                html_text = await self._fetch_text(
                    url,
                    operation="search-engine",
                    query=query,
                    source_kind=source_kind,
                    source_label=source_label,
                    timeout_seconds=self._recommended_timeout_seconds(urlparse(url).netloc.lower(), 6.0),
                )
            except Exception as error:
                self._warn(f"{source_label} 在 {engine_name} 检索失败：{error}")
                self._record_access_event(
                    url=url,
                    operation="search-engine",
                    ok=False,
                    duration_ms=(time.perf_counter() - started) * 1000,
                    source_kind=source_kind,
                    source_label=source_label,
                    query=query,
                    error=str(error),
                )
                return []
            links = parser(html_text)
            self._record_access_event(
                url=url,
                operation="search-engine",
                ok=True,
                duration_ms=(time.perf_counter() - started) * 1000,
                source_kind=source_kind,
                source_label=source_label,
                query=query,
                result_count=len(links[:ENGINE_RESULT_DEPTH]),
            )
            return [
                {"url": link, "source_label": f"{source_label} via {engine_name}", "source_kind": source_kind}
                for link in links[:ENGINE_RESULT_DEPTH]
            ]

        rows: list[dict[str, str]] = []
        for group in await asyncio.gather(
            *(run_engine(engine_name, engine_url, parser) for engine_name, engine_url, parser in active_engines),
            return_exceptions=False,
        ):
            rows.extend(group)
        return dedupe_rows(rows)

    async def _search_youtube(self, queries: list[str]) -> list[dict[str, str]]:
        html_query_depth = min(len(queries), self._recommended_query_depth("www.youtube.com", HOST_QUERY_DEPTH) + 1)
        rows = await self._search_streaming_platform(
            queries=queries[:html_query_depth],
            url_builders=[
                lambda query: f"https://www.youtube.com/results?search_query={quote_plus(query)}",
                lambda query: f"https://www.youtube.com/results?sp=EgIQAQ%253D%253D&search_query={quote_plus(query)}",
            ],
            parser=extract_youtube_result_links,
            source_label="YouTube Search",
            api_search=self._run_youtube_api_search if self._can_use_youtube_api() else None,
            api_source_label="YouTube API Search",
        )
        if self._can_use_youtube_api() and not self._is_platform_api_disabled("YouTube API Search"):
            return rows
        engine_rows = await self._search_platform_via_site_engines(
            queries[: max(4, html_query_depth)],
            site_hosts=["www.youtube.com", "youtu.be"],
            source_label="YouTube Search",
        )
        return dedupe_rows([*rows, *engine_rows])[:HYDRATE_DEPTH]

    async def _search_bilibili(self, queries: list[str]) -> list[dict[str, str]]:
        prioritized_queries = queries
        html_query_depth = min(len(prioritized_queries), self._recommended_query_depth("search.bilibili.com", HOST_QUERY_DEPTH) + 1)
        builders = [
            lambda query: f"https://search.bilibili.com/all?keyword={quote_plus(query)}",
            lambda query: f"https://search.bilibili.com/video?keyword={quote_plus(query)}",
        ]
        browser_queries = select_bilibili_browser_queries(prioritized_queries)
        rows = await self._search_streaming_platform(
            queries=prioritized_queries[:html_query_depth],
            url_builders=builders,
            parser=extract_bilibili_result_links,
            source_label="Bilibili Search",
            api_search=self._run_bilibili_api_search if self._can_use_bilibili_api() else None,
            api_source_label="Bilibili API Search",
        )
        browser_rows = await self._search_platform_via_browser_pages(
            queries=browser_queries,
            url_builders=builders,
            source_label="Bilibili Search",
            url_patterns=[r"https://www\.bilibili\.com/video/(?:BV[0-9A-Za-z]+|av\d+)/?"],
        )
        engine_rows = await self._search_platform_via_site_engines(
            prioritized_queries[: max(4, html_query_depth)],
            site_hosts=["www.bilibili.com", "m.bilibili.com", "b23.tv"],
            source_label="Bilibili Search",
        )
        return merge_bilibili_search_rows(rows, browser_rows, engine_rows)

    async def _search_apple_music(self, queries: list[str]) -> list[dict[str, str]]:
        rows = await self._search_streaming_platform(
            queries=queries,
            url_builders=[
                lambda query: f"https://classical.music.apple.com/search?term={quote_plus(query)}",
                lambda query: f"https://music.apple.com/search?term={quote_plus(query)}",
            ],
            parser=extract_apple_music_result_links,
            source_label="Apple Music Search",
            api_search=self._run_apple_music_api_search
            if self._can_use_apple_music_api() or self._can_use_apple_music_public_api()
            else None,
            api_source_label="Apple Music API Search",
        )
        if rows:
            return rows
        return await self._search_platform_via_site_engines(
            queries,
            site_hosts=["classical.music.apple.com", "music.apple.com"],
            source_label="Apple Music Search",
        )

    async def _search_streaming_platform(
        self,
        *,
        queries: list[str],
        url_builder=None,
        url_builders=None,
        parser,
        source_label: str,
        api_search=None,
        api_source_label: str = "",
    ) -> list[dict[str, str]]:
        builders = list(url_builders or ([] if url_builder is None else [url_builder]))
        if not builders:
            return []
        sample_url = builders[0](queries[0]) if queries else ""
        host = urlparse(sample_url).netloc.lower()
        query_depth = self._recommended_query_depth(host, HOST_QUERY_DEPTH)
        result_depth = self._recommended_result_depth(host, STREAMING_RESULT_DEPTH)
        if api_search is None or self._is_platform_api_disabled(api_source_label or source_label):
            query_boost, result_boost = self._html_budget_boost(source_label)
            query_depth = min(10, query_depth + query_boost)
            result_depth = min(12, result_depth + result_boost)

        async def run_query(query: str) -> list[dict[str, str]]:
            if api_search is not None and not self._is_platform_api_disabled(api_source_label or source_label):
                api_started = time.perf_counter()
                try:
                    api_result = await api_search(query, result_depth)
                except Exception as error:
                    api_url = self._platform_api_marker_url(api_source_label or source_label)
                    if should_disable_platform_api(error):
                        self._disable_platform_api(api_source_label or source_label)
                    self._warn(f"{api_source_label or source_label} API 搜索失败：{error}")
                    self._record_access_event(
                        url=api_url,
                        operation="streaming-api-search",
                        ok=False,
                        duration_ms=(time.perf_counter() - api_started) * 1000,
                        source_kind="streaming",
                        source_label=api_source_label or source_label,
                        query=query,
                        error=str(error),
                    )
                else:
                    self._record_access_event(
                        url=api_result.endpoint_url,
                        operation="streaming-api-search",
                        ok=True,
                        duration_ms=(time.perf_counter() - api_started) * 1000,
                        source_kind="streaming",
                        source_label=api_source_label or source_label,
                        query=query,
                        result_count=len(api_result.links[:result_depth]),
                    )
                    if api_result.links:
                        return [
                            {
                                "url": link,
                                "source_label": api_source_label or source_label,
                                "source_kind": "streaming",
                            }
                            for link in api_result.links[:result_depth]
                        ]

            rows: list[dict[str, str]] = []
            for build_url in builders:
                request_url = build_url(query)
                started = time.perf_counter()
                try:
                    html_text = await self._fetch_text(
                        request_url,
                        operation="streaming-search",
                        query=query,
                        source_kind="streaming",
                        source_label=source_label,
                        timeout_seconds=self._recommended_timeout_seconds(urlparse(request_url).netloc.lower(), 6.0),
                    )
                except Exception as error:
                    self._warn(f"{source_label} 搜索失败：{error}")
                    self._record_access_event(
                        url=request_url,
                        operation="streaming-search",
                        ok=False,
                        duration_ms=(time.perf_counter() - started) * 1000,
                        source_kind="streaming",
                        source_label=source_label,
                        query=query,
                        error=str(error),
                    )
                    continue
                links = parser(html_text)[:result_depth]
                self._record_access_event(
                    url=request_url,
                    operation="streaming-search",
                    ok=True,
                    duration_ms=(time.perf_counter() - started) * 1000,
                    source_kind="streaming",
                    source_label=source_label,
                    query=query,
                    result_count=len(links),
                )
                rows.extend(
                    {
                        "url": link,
                        "source_label": source_label,
                        "source_kind": "streaming",
                    }
                    for link in links
                )
                rows = dedupe_rows(rows)
                if links or len(rows) >= result_depth:
                    break
            return rows[:result_depth]
        groups = await asyncio.gather(*(run_query(query) for query in queries[:query_depth]), return_exceptions=False)
        if should_merge_streaming_query_coverage(source_label):
            return merge_streaming_query_groups(groups, limit=HYDRATE_DEPTH)
        rows: list[dict[str, str]] = []
        for group in groups:
            rows.extend(group)
            rows = dedupe_rows(rows)
            if len(rows) >= HYDRATE_DEPTH:
                break
        return rows

    def _platform_api_marker_url(self, source_label: str) -> str:
        lowered = compact(source_label).lower()
        if "youtube" in lowered:
            return "https://www.googleapis.com/youtube/v3/search"
        if "apple" in lowered:
            return f"https://api.music.apple.com/v1/catalog/{self._platform_search_config.apple_music.storefront}/search"
        if "bilibili" in lowered:
            return "https://api.bilibili.com/x/web-interface/wbi/search/type"
        return "https://api.example.invalid/search"

    def _html_budget_boost(self, source_label: str) -> tuple[int, int]:
        lowered = compact(source_label).lower()
        if "youtube" in lowered:
            return 2, 2
        if "bilibili" in lowered:
            return 1, 2
        if "apple" in lowered:
            return 1, 1
        return 0, 0

    async def _search_platform_via_site_engines(
        self,
        queries: list[str],
        *,
        site_hosts: list[str],
        source_label: str,
    ) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for query in queries[: min(len(queries), HOST_QUERY_DEPTH)]:
            for host in site_hosts:
                engine_rows = await self._search_query_via_engines(
                    query=f"site:{host} {query}",
                    source_label=f"{source_label} Engine Fallback",
                    source_kind="streaming",
                )
                filtered = [
                    row
                    for row in engine_rows
                    if any(site_host in urlparse(row.get("url", "")).netloc.lower() for site_host in site_hosts)
                ]
                rows.extend(filtered)
                rows = dedupe_rows(rows)
                if len(rows) >= HYDRATE_DEPTH:
                    return rows[:HYDRATE_DEPTH]
        return rows[:HYDRATE_DEPTH]

    async def _search_platform_via_browser_pages(
        self,
        *,
        queries: list[str],
        url_builders: list,
        source_label: str,
        url_patterns: list[str],
    ) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        if not queries or not url_builders:
            return rows

        sample_url = url_builders[0](queries[0])
        host = urlparse(sample_url).netloc.lower()
        lowered_label = compact(source_label).lower()
        bilibili_search = "bilibili" in lowered_label
        query_depth = len(queries) if bilibili_search else 1
        result_depth = min(HYDRATE_DEPTH, self._recommended_result_depth(host, STREAMING_RESULT_DEPTH) + 2)
        if bilibili_search:
            query_rows_list: list[list[dict[str, str]]] = []
            for query in queries[:query_depth]:
                query_rows: list[dict[str, str]] = []
                for build_url in url_builders[:2]:
                    search_url = build_url(query)
                    started = time.perf_counter()
                    try:
                        links = await self._browser_fetcher.fetch_links(
                            search_url,
                            url_patterns=url_patterns,
                            timeout_seconds=min(
                                4.0,
                                self._recommended_timeout_seconds(urlparse(search_url).netloc.lower(), 4.0),
                            ),
                        )
                    except (AttributeError, BrowserFetchUnavailable, RuntimeError, TimeoutError) as error:
                        self._warn(f"{source_label} 浏览器搜索回退失败: {error}")
                        self._record_access_event(
                            url=search_url,
                            operation="browser-search",
                            ok=False,
                            duration_ms=(time.perf_counter() - started) * 1000,
                            source_kind="streaming",
                            source_label=f"{source_label} Browser Search",
                            query=query,
                            error=str(error),
                        )
                        continue
                    self._record_access_event(
                        url=search_url,
                        operation="browser-search",
                        ok=True,
                        duration_ms=(time.perf_counter() - started) * 1000,
                        source_kind="streaming",
                        source_label=f"{source_label} Browser Search",
                        query=query,
                        result_count=len(links[:result_depth]),
                    )
                    query_rows.extend(
                        {
                            "url": link,
                            "source_label": f"{source_label} Browser Search",
                            "source_kind": "streaming",
                        }
                        for link in links[:result_depth]
                    )
                    query_rows = dedupe_rows(query_rows)
                    if links:
                        break
                if query_rows:
                    query_rows_list.append(query_rows[:result_depth])
            return merge_bilibili_browser_query_rows(query_rows_list, result_depth=result_depth)

        for query in queries[:query_depth]:
            builders_to_use = url_builders[:1]
            for build_url in builders_to_use:
                search_url = build_url(query)
                started = time.perf_counter()
                try:
                    links = await self._browser_fetcher.fetch_links(
                        search_url,
                        url_patterns=url_patterns,
                        timeout_seconds=min(
                            4.0,
                            self._recommended_timeout_seconds(urlparse(search_url).netloc.lower(), 4.0),
                        ),
                    )
                except (AttributeError, BrowserFetchUnavailable, RuntimeError, TimeoutError) as error:
                    self._warn(f"{source_label} 浏览器搜索回退失败：{error}")
                    self._record_access_event(
                        url=search_url,
                        operation="browser-search",
                        ok=False,
                        duration_ms=(time.perf_counter() - started) * 1000,
                        source_kind="streaming",
                        source_label=f"{source_label} Browser Search",
                        query=query,
                        error=str(error),
                    )
                    continue
                self._record_access_event(
                    url=search_url,
                    operation="browser-search",
                    ok=True,
                    duration_ms=(time.perf_counter() - started) * 1000,
                    source_kind="streaming",
                    source_label=f"{source_label} Browser Search",
                    query=query,
                    result_count=len(links[:result_depth]),
                )
                rows.extend(
                    {
                        "url": link,
                        "source_label": f"{source_label} Browser Search",
                        "source_kind": "streaming",
                    }
                    for link in links[:result_depth]
                )
                rows = dedupe_rows(rows)
                if len(rows) >= result_depth:
                    return rows[:result_depth]
                if links:
                    break
        return rows[:result_depth]

    async def _run_youtube_api_search(self, query: str, result_depth: int):
        return await self._platform_clients().search_youtube(query, result_limit=result_depth)

    async def _run_apple_music_api_search(self, query: str, result_depth: int):
        clients = self._platform_clients()
        if self._can_use_apple_music_api():
            try:
                return await clients.search_apple_music(query, result_limit=result_depth)
            except Exception:
                if not self._can_use_apple_music_public_api():
                    raise
        return await clients.search_apple_music_public(query, result_limit=result_depth)

    async def _run_bilibili_api_search(self, query: str, result_depth: int):
        return await self._platform_clients().search_bilibili(query, result_limit=result_depth)

    async def _hydrate_results(
        self,
        draft: DraftRecordingEntry,
        rows: list[dict[str, str]],
        source_kind: str,
    ) -> list[dict[str, Any]]:
        semaphore = asyncio.Semaphore(4)
        tasks = [
            self._fetch_page_record(item["url"], item["source_label"], source_kind, draft, semaphore)
            for item in dedupe_rows(rows)
        ]
        return [item for item in await asyncio.gather(*tasks, return_exceptions=False) if item]

    def _queries_for_host(
        self,
        draft: DraftRecordingEntry,
        profile: RetrievalProfile,
        host: SourceProfileEntry,
    ) -> list[str]:
        latin_lead_pool = self._expand_person_terms(
            dedupe_text([*draft.query_lead_names_latin, *draft.query_lead_names]),
            prefer_latin=True,
        )
        latin_leads = dedupe_text([*[value for value in latin_lead_pool if looks_latin(value)], *latin_lead_pool])
        latin_ensembles = self._expand_ensemble_terms(
            draft.ensemble_names_latin or [value for value in draft.ensemble_names if looks_latin(value)],
            prefer_full_names=not host.is_chinese,
        )
        zh_leads = self._expand_person_terms(
            [value for value in draft.query_lead_names if contains_cjk(value)],
            prefer_latin=False,
        )
        zh_ensembles = dedupe_text([value for value in draft.ensemble_names if contains_cjk(value)])

        latin_queries = build_queries(
            work_query=build_work_query(draft, prefer_latin=True),
            composer_query=compact(draft.composer_name_latin),
            lead_terms=latin_leads,
            ensemble_terms=latin_ensembles,
            title=draft.title,
            performance_date_text=draft.performance_date_text,
        )
        if not latin_queries:
            latin_queries = profile.latin_queries or profile.queries

        if host.is_chinese:
            primary_only_queries = self._primary_only_queries_for_host(
                draft,
                host,
                composer_query=compact(draft.composer_name),
            )
            zh_queries = build_queries(
                work_query=build_work_query(draft, prefer_latin=False),
                composer_query=compact(draft.composer_name),
                lead_terms=zh_leads,
                ensemble_terms=zh_ensembles,
                title=draft.title,
                performance_date_text=draft.performance_date_text,
            )
            mixed_queries = build_queries(
                work_query=build_work_query(draft, prefer_latin=False) or build_work_query(draft, prefer_latin=True),
                composer_query=compact(draft.composer_name_latin or draft.composer_name),
                lead_terms=dedupe_text([*zh_leads, *latin_leads]),
                ensemble_terms=dedupe_text([*zh_ensembles, *latin_ensembles]),
                title=draft.title,
                performance_date_text=draft.performance_date_text,
            )
            generated_queries = prioritize_platform_queries(
                [
                    *primary_only_queries[:4],
                    *zh_queries[:3],
                    *latin_queries[:3],
                    *profile.mixed_queries[:1],
                    *mixed_queries[:2],
                    *self._alias_queries_for_host(
                        draft,
                        host,
                        lead_terms=dedupe_text([*zh_leads, *latin_leads]),
                        ensemble_terms=dedupe_text([*zh_ensembles, *latin_ensembles]),
                    )[:2],
                ],
                draft=draft,
                prefer_cjk=True,
            )
            return dedupe_text([
                *primary_only_queries[:4],
                *profile.zh_queries[:2],
                *profile.latin_queries[:2],
                *generated_queries,
            ])[:8]

        primary_only_queries = self._primary_only_queries_for_host(
            draft,
            host,
            composer_query=compact(draft.composer_name_latin),
        )
        alias_queries = self._alias_queries_for_host(
            draft,
            host,
            lead_terms=latin_leads,
            ensemble_terms=latin_ensembles,
        )
        generated_queries = prioritize_platform_queries(
            [
                *primary_only_queries[:4],
                *alias_queries[:4],
                *latin_queries[:4],
            ],
            draft=draft,
            prefer_cjk=False,
        )
        return dedupe_text([
            *primary_only_queries[:4],
            *alias_queries[:1],
            *profile.queries[:2],
            *profile.latin_queries[:2],
            *generated_queries,
        ])[:10]

    def _primary_only_queries_for_host(
        self,
        draft: DraftRecordingEntry,
        host: SourceProfileEntry,
        *,
        composer_query: str,
    ) -> list[str]:
        work_query = build_work_query(draft, prefer_latin=not host.is_chinese)
        normalized_work = compact(work_query).lower()
        if not normalized_work:
            return []
        if "concerto" not in normalized_work and "协奏曲" not in work_query:
            return []
        if host.is_chinese:
            primary_terms = dedupe_text([*getattr(draft, "primary_names", []), *getattr(draft, "primary_names_latin", [])])
        else:
            primary_terms = dedupe_text([*getattr(draft, "primary_names_latin", []), *getattr(draft, "primary_names", [])])
        if not primary_terms:
            return []
        queries = build_queries(
            work_query=work_query,
            composer_query=composer_query,
            lead_terms=primary_terms[:1],
            ensemble_terms=[],
            title=draft.title,
            performance_date_text=draft.performance_date_text,
        )
        alias_values = build_work_aliases(draft.work_title_latin)
        alias_values.update(build_work_aliases(draft.work_title))
        for alias in sorted(alias_values):
            normalized_alias = compact(alias)
            if not normalized_alias or normalized_alias.lower() == normalized_work:
                continue
            if host.is_chinese and not contains_cjk(normalized_alias):
                continue
            if not host.is_chinese and not looks_latin(normalized_alias):
                continue
            queries.extend(
                build_queries(
                    work_query=normalized_alias,
                    composer_query=composer_query,
                    lead_terms=primary_terms[:1],
                    ensemble_terms=[],
                    title=draft.title,
                    performance_date_text=draft.performance_date_text,
                )[:2]
            )
        filtered_queries = []
        required_lead = compact(primary_terms[0]).lower()
        catalogue = compact(draft.catalogue).lower()
        for query in dedupe_text(queries):
            lowered = compact(query).lower()
            if required_lead and required_lead not in lowered:
                continue
            if catalogue and catalogue not in lowered and "concerto" not in lowered and "协奏曲" not in query and "klavierkonzert" not in lowered:
                continue
            filtered_queries.append(query)
        return prioritize_platform_queries(filtered_queries, draft=draft, prefer_cjk=host.is_chinese)

    def _alias_queries_for_host(
        self,
        draft: DraftRecordingEntry,
        host: SourceProfileEntry,
        *,
        lead_terms: list[str],
        ensemble_terms: list[str],
    ) -> list[str]:
        aliases = build_work_aliases(draft.work_title_latin)
        aliases.update(build_work_aliases(draft.work_title))
        if host.is_chinese:
            work_aliases = [alias for alias in aliases if contains_cjk(alias)]
            composer_query = compact(draft.composer_name)
        else:
            work_aliases = [alias for alias in aliases if looks_latin(alias)]
            composer_query = compact(draft.composer_name_latin)
        queries: list[str] = []
        base_queries = {
            compact(build_work_query(draft, prefer_latin=not host.is_chinese)),
            compact(build_work_query(draft, prefer_latin=host.is_chinese)),
        }
        ordered_aliases = sorted(
            work_aliases,
            key=lambda alias: (
                any(word in alias.lower() for word in ("sonata", "concerto", "symphony")),
                len(alias),
            ),
        )
        for alias in ordered_aliases:
            normalized_alias = compact(alias)
            if not normalized_alias or normalized_alias in base_queries:
                continue
            queries.extend(
                build_queries(
                    work_query=normalized_alias,
                    composer_query=composer_query,
                    lead_terms=lead_terms,
                    ensemble_terms=ensemble_terms,
                    title=draft.title,
                    performance_date_text=draft.performance_date_text,
                )[:4]
            )
        return dedupe_text(queries)

    def _expand_ensemble_terms(self, values: list[str], *, prefer_full_names: bool) -> list[str]:
        expanded: list[str] = []
        for value in values:
            expansions = self._orchestra_alias_loader.expand(value)
            if prefer_full_names:
                expansions = sorted(expansions, key=lambda item: (is_probable_abbreviation(item), len(item)))
            expanded.extend(expansions)
        return dedupe_text(expanded)

    def _expand_person_terms(self, values: list[str], *, prefer_latin: bool) -> list[str]:
        expanded: list[str] = []
        for value in values:
            expansions = self._person_alias_loader.expand(value)
            if prefer_latin:
                expansions = sorted(expansions, key=lambda item: (contains_cjk(item), len(item)))
            else:
                expansions = sorted(expansions, key=lambda item: (not contains_cjk(item), len(item)))
            expanded.extend(expansions)
        return dedupe_text(expanded)

    async def _fetch_page_record(
        self,
        url: str,
        source_label: str,
        source_kind: str,
        draft: DraftRecordingEntry,
        semaphore: asyncio.Semaphore,
    ) -> dict[str, Any] | None:
        async with semaphore:
            platform = detect_platform(url)
            html_text = ""
            bilibili_metadata: dict[str, Any] = {}
            duration_seconds = 0
            uploader = ""
            view_count = 0
            fetch_timeout = self._recommended_timeout_seconds(urlparse(url).netloc.lower(), 6.0)
            if platform == "bilibili" and self._can_use_bilibili_api() and not self._is_platform_api_disabled("Bilibili Detail API"):
                detail_started = time.perf_counter()
                try:
                    detail = await self._platform_clients().fetch_bilibili_video_detail(url)
                except Exception as error:
                    if should_disable_platform_api(error):
                        self._disable_platform_api("Bilibili Detail API")
                    self._warn(f"Bilibili Detail API 获取失败：{error}")
                    self._record_access_event(
                        url=url,
                        operation="detail-api-fetch",
                        ok=False,
                        duration_ms=(time.perf_counter() - detail_started) * 1000,
                        source_kind=source_kind,
                        source_label="Bilibili Detail API",
                        error=str(error),
                    )
                else:
                    if detail is not None:
                        bilibili_metadata = build_bilibili_metadata_from_detail(detail)
                    self._record_access_event(
                        url=detail.endpoint_url if detail is not None else url,
                        operation="detail-api-fetch",
                        ok=True,
                        duration_ms=(time.perf_counter() - detail_started) * 1000,
                        source_kind=source_kind,
                        source_label="Bilibili Detail API",
                    )

            detail_ready = platform == "bilibili" and not metadata_is_insufficient(
                compact(bilibili_metadata.get("title")),
                compact(bilibili_metadata.get("description")),
                compact(bilibili_metadata.get("body_text")),
            ) and int(bilibili_metadata.get("duration_seconds", 0) or 0) > 0 and int(
                bilibili_metadata.get("view_count", 0) or 0
            ) > 0 and compact(bilibili_metadata.get("uploader"))

            if not detail_ready:
                started = time.perf_counter()
                try:
                    html_text = await self._fetch_text(
                        url,
                        operation="fetch-page",
                        source_kind=source_kind,
                        source_label=source_label,
                        timeout_seconds=fetch_timeout,
                    )
                except Exception as error:
                    self._warn(f"{normalize_host(url)} 访问失败：{error}")
                    self._record_access_event(
                        url=url,
                        operation="fetch-page",
                        ok=False,
                        duration_ms=(time.perf_counter() - started) * 1000,
                        source_kind=source_kind,
                        source_label=source_label,
                        error=str(error),
                        timeout_seconds=fetch_timeout,
                    )
                    html_text = ""

                if platform == "bilibili" and html_text:
                    html_bilibili_metadata = extract_bilibili_structured_metadata(html_text)
                    for key, value in html_bilibili_metadata.items():
                        if not compact(bilibili_metadata.get(key)):
                            bilibili_metadata[key] = value
            title = strip_html(
                extract_meta_content(html_text, "og:title")
                or compact(bilibili_metadata.get("title"))
                or extract_title(html_text)
            )
            description = strip_html(
                extract_meta_content(html_text, "og:description")
                or extract_meta_content(html_text, "description", attr="name")
                or compact(bilibili_metadata.get("description"))
            )
            body_text = compact(bilibili_metadata.get("body_text")) or (strip_html(html_text)[:4000] if html_text else "")
            if platform == "bilibili":
                description = sanitize_bilibili_metadata_text(description)
                body_text = sanitize_bilibili_metadata_text(body_text)
            image_url = resolve_image_url(
                url,
                extract_meta_content(html_text, "og:image")
                or extract_meta_content(html_text, "twitter:image", attr="name")
                or compact(bilibili_metadata.get("image_url"))
                or extract_first_image_src(html_text, url),
            )
            canonical_url = canonicalize_bilibili_video_url(url, compact(bilibili_metadata.get("bvid")))
            duration_seconds = extract_duration_seconds(html_text) or int(bilibili_metadata.get("duration_seconds", 0) or 0)
            uploader = extract_uploader_name(html_text) or compact(bilibili_metadata.get("uploader"))
            view_count = extract_view_count(html_text) or int(bilibili_metadata.get("view_count", 0) or 0)

            browser_metadata_needed = metadata_is_insufficient(title, description, body_text) or (
                platform == "bilibili" and (duration_seconds <= 0 or view_count <= 0 or not compact(uploader))
            )
            if browser_metadata_needed:
                browser_started = time.perf_counter()
                try:
                    browser_timeout = self._recommended_timeout_seconds(urlparse(url).netloc.lower(), 6.0)
                    browser_payload = await self._browser_fetcher.fetch_page(url, timeout_seconds=browser_timeout)
                    self._record_access_event(
                        url=url,
                        operation="browser-fallback",
                        ok=True,
                        duration_ms=(time.perf_counter() - browser_started) * 1000,
                        source_kind=source_kind,
                        source_label=source_label,
                        timeout_seconds=browser_timeout,
                    )
                    title = compact(browser_payload.get("title")) or title
                    description = compact(browser_payload.get("description")) or description
                    body_text = compact(browser_payload.get("bodyText")) or body_text
                    if platform == "bilibili":
                        description = sanitize_bilibili_metadata_text(description)
                        body_text = sanitize_bilibili_metadata_text(body_text)
                    image_url = resolve_image_url(url, browser_payload.get("imageUrl") or image_url)
                    uploader = compact(browser_payload.get("uploader")) or uploader
                    canonical_url = canonicalize_bilibili_video_url(
                        canonical_url,
                        compact(browser_payload.get("bvid")),
                    )
                    duration_seconds = max(
                        duration_seconds,
                        int(browser_payload.get("durationSeconds", browser_payload.get("duration_seconds", 0)) or 0),
                    )
                    view_count = max(
                        view_count,
                        int(browser_payload.get("viewCount", browser_payload.get("view_count", 0)) or 0),
                    )
                except (BrowserFetchUnavailable, RuntimeError, TimeoutError) as error:
                    self._warn(f"{normalize_host(url)} 浏览器回退失败：{error}")
                    self._record_access_event(
                        url=url,
                        operation="browser-fallback",
                        ok=False,
                        duration_ms=(time.perf_counter() - browser_started) * 1000,
                        source_kind=source_kind,
                        source_label=source_label,
                        error=str(error),
                    )

        summary_text = " ".join(part for part in [title, description] if part)
        combined = " ".join(part for part in [summary_text, body_text] if part)
        match_score = score_recording_match(
            summary_text or combined,
            url,
            draft,
            duration_seconds=duration_seconds,
            uploader=uploader,
        )
        source_images = []
        if image_url:
            source_images.append(
                {
                    "src": image_url,
                    "title": title or draft.title,
                    "sourceUrl": url,
                    "sourceKind": source_kind,
                    "attribution": source_label,
                }
            )

        return {
            "url": canonical_url,
            "source_label": source_label,
            "source_kind": source_kind,
            "title": title,
            "description": description,
            "platform": platform,
            "weight": 0.9 if source_kind in {"existing-link", "high-quality"} else 0.68,
            "same_recording_score": match_score,
            "duration_seconds": duration_seconds,
            "uploader": uploader,
            "view_count": view_count,
            "fields": {
                "performanceDateText": extract_year(summary_text) or extract_year(combined) or draft.performance_date_text,
                "venueText": extract_venue(combined),
                "albumTitle": title if title and not title.startswith("http") else "",
                "label": extract_label(summary_text or combined),
                "releaseDate": extract_release_date(summary_text or combined),
            },
            "images": source_images,
        }

    async def _fetch_text(
        self,
        url: str,
        *,
        operation: str = "fetch-page",
        query: str = "",
        source_kind: str = "",
        source_label: str = "",
        timeout_seconds: float | None = None,
    ) -> str:
        normalized_url = compact(url)
        with self._state_lock:
            cached = self._text_cache.get(normalized_url)
        if cached is not None:
            if operation == "fetch-page":
                self._record_access_event(
                    url=url,
                    operation=operation,
                    ok=True,
                    duration_ms=0.0,
                    source_kind=source_kind,
                    source_label=source_label,
                    query=query,
                    result_count=0,
                    cache_hit=True,
                    timeout_seconds=timeout_seconds,
                )
            return cached
        client = self._get_http_client()
        started = time.perf_counter()
        response = await client.get(url, timeout=timeout_seconds, headers=self._request_headers_for_url(url))
        response.raise_for_status()
        with self._state_lock:
            self._text_cache[normalized_url] = response.text
        if operation == "fetch-page":
            self._record_access_event(
                url=url,
                operation=operation,
                ok=True,
                duration_ms=(time.perf_counter() - started) * 1000,
                source_kind=source_kind,
                source_label=source_label,
                query=query,
                status_code=response.status_code,
                timeout_seconds=timeout_seconds,
            )
        return response.text


def metadata_is_insufficient(title: str, description: str, body_text: str) -> bool:
    return not compact(title) and not compact(description) and len(compact(body_text)) < 80


def should_disable_platform_api(error: Exception) -> bool:
    if isinstance(error, httpx.HTTPStatusError):
        status_code = error.response.status_code
        body = ""
        try:
            body = error.response.text.lower()
        except Exception:
            body = ""
        if status_code in {401, 403, 412, 429}:
            return True
        if "quota" in body or "rate" in body:
            return True
    message = compact(error).lower()
    return any(token in message for token in ("quota", "rate limit", "403", "412", "429"))


def normalize_host(value: str) -> str:
    return compact(value).replace("https://", "").replace("http://", "").strip("/")


def canonicalize_bilibili_video_url(url: str, bvid: str = "") -> str:
    normalized_url = compact(url)
    normalized_bvid = compact(bvid)
    host = urlparse(normalized_url).netloc.lower()
    if "bilibili.com" not in host or not normalized_bvid:
        return normalized_url
    return f"https://www.bilibili.com/video/{normalized_bvid}/"


def streaming_host_priority(value: str) -> tuple[int, str]:
    normalized = normalize_host(value).lower()
    if "youtube.com" in normalized or "youtu.be" in normalized:
        return (0, normalized)
    if "bilibili.com" in normalized or "b23.tv" in normalized:
        return (0, normalized)
    if "apple.com" in normalized:
        return (1, normalized)
    return (2, normalized)


def merge_streaming_host_rows(
    host_results: list[tuple[SourceProfileEntry, list[dict[str, str]]]],
) -> list[dict[str, str]]:
    coverage_rows: list[dict[str, str]] = []
    all_rows: list[dict[str, str]] = []
    priority_hosts = {host.url for host, _ in host_results if streaming_host_priority(host.url)[0] == 0}
    for host, rows in host_results:
        if host.url in priority_hosts:
            coverage_rows.extend(rows[:2])
    coverage_rows = dedupe_rows(coverage_rows)

    multiple_hosts = len(host_results) > 1
    for host, rows in host_results:
        normalized_host = normalize_host(host.url)
        if not multiple_hosts:
            per_host_cap = HYDRATE_DEPTH
        elif "youtube.com" in normalized_host or "youtu.be" in normalized_host:
            per_host_cap = 10
        elif "bilibili.com" in normalized_host or "b23.tv" in normalized_host:
            per_host_cap = 10
        else:
            per_host_cap = 4
        all_rows.extend(rows[:per_host_cap])
    return dedupe_rows([*coverage_rows, *all_rows])


def merge_bilibili_search_rows(
    api_rows: list[dict[str, str]],
    browser_rows: list[dict[str, str]],
    engine_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    return dedupe_rows([*browser_rows, *api_rows, *engine_rows])[:HYDRATE_DEPTH]


def merge_bilibili_browser_query_rows(
    query_rows_list: list[list[dict[str, str]]],
    *,
    result_depth: int,
) -> list[dict[str, str]]:
    coverage_rows: list[dict[str, str]] = []
    all_rows: list[dict[str, str]] = []
    for rows in query_rows_list:
        coverage_rows.extend(rows[:3])
        all_rows.extend(rows)
    return dedupe_rows([*coverage_rows, *all_rows])[:result_depth]


def merge_streaming_query_groups(
    groups: list[list[dict[str, str]]],
    *,
    limit: int,
    coverage_per_query: int = 2,
) -> list[dict[str, str]]:
    coverage_rows: list[dict[str, str]] = []
    all_rows: list[dict[str, str]] = []
    for group in groups:
        coverage_rows.extend(group[:coverage_per_query])
        all_rows.extend(group)
    return dedupe_rows([*coverage_rows, *all_rows])[:limit]


def should_merge_streaming_query_coverage(source_label: str) -> bool:
    lowered = compact(source_label).lower()
    return "youtube" in lowered


def bilibili_query_specificity(query: str) -> tuple[int, int, int]:
    normalized = compact(query)
    return (
        sum(character.isdigit() for character in normalized),
        len(normalized.split()),
        len(normalized),
    )


def select_bilibili_browser_queries(queries: list[str], *, max_queries: int = 6) -> list[str]:
    candidates = dedupe_text([compact(query) for query in queries if compact(query)])
    if len(candidates) <= max_queries:
        return candidates
    if max_queries <= 0:
        return []

    head_count = min(2, len(candidates), max_queries)
    selected_indices: set[int] = set(range(head_count))

    tail_capacity = max_queries - len(selected_indices)
    tail_count = min(2, tail_capacity, max(0, len(candidates) - head_count))
    if tail_count:
        selected_indices.update(range(len(candidates) - tail_count, len(candidates)))

    remaining_slots = max_queries - len(selected_indices)
    if remaining_slots > 0:
        middle_indices = [index for index in range(head_count, len(candidates) - tail_count) if index not in selected_indices]
        ranked_middle = sorted(
            middle_indices,
            key=lambda index: (bilibili_query_specificity(candidates[index]), -index),
            reverse=True,
        )
        selected_indices.update(ranked_middle[:remaining_slots])

    return [candidates[index] for index in sorted(selected_indices)]


def should_search_auxiliary_streaming_hosts(
    host_results: list[tuple[SourceProfileEntry, list[dict[str, str]]]],
) -> bool:
    non_empty = [(host, rows) for host, rows in host_results if rows]
    if len(non_empty) < 2:
        return True
    merged = merge_streaming_host_rows(non_empty)
    return len(merged) < 4


def should_expand_initial_streaming_window(
    host_results: list[tuple[SourceProfileEntry, list[dict[str, str]]]],
) -> bool:
    priority_non_empty = [
        (host, rows)
        for host, rows in host_results
        if rows and streaming_host_priority(host.url)[0] == 0
    ]
    if len(priority_non_empty) < 2:
        return False
    for host, rows in priority_non_empty:
        normalized_host = normalize_host(host.url)
        if ("bilibili.com" in normalized_host or "b23.tv" in normalized_host) and len(rows) >= 9:
            return True
    return False


def prioritize_platform_queries(values: list[str], *, draft: DraftRecordingEntry, prefer_cjk: bool) -> list[str]:
    catalogue = compact(draft.catalogue).lower()
    work_title = compact(draft.work_title_latin or draft.work_title).lower()
    composer = compact(draft.composer_name_latin or draft.composer_name).lower()

    def sort_key(query: str) -> tuple[int, int, int, int, int]:
        lowered = compact(query).lower()
        return (
            0 if contains_cjk(lowered) == prefer_cjk else 1,
            0 if catalogue and catalogue in lowered else 1,
            0 if work_title and work_title in lowered else 1,
            0 if composer and composer in lowered else 1,
            len(lowered),
        )

    return sorted(dedupe_text(values), key=sort_key)


def dedupe_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for row in rows:
        url = compact(row.get("url"))
        if not url:
            continue
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def dedupe_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for value in values:
        normalized = compact(value)
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(normalized)
    return items


def is_probable_abbreviation(value: str) -> bool:
    normalized = compact(value)
    return bool(normalized) and normalized.upper() == normalized and len(normalized) <= 6 and " " not in normalized


def strip_html(value: str) -> str:
    cleaned = re.sub(r"<script[\s\S]*?</script>", " ", value or "", flags=re.I)
    cleaned = re.sub(r"<style[\s\S]*?</style>", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    return html.unescape(cleaned).replace("\n", " ").strip()


def extract_meta_content(html_text: str, key: str, attr: str = "property") -> str:
    patterns = [
        re.compile(rf'<meta[^>]+{attr}=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']', re.I),
        re.compile(rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+{attr}=["\']{re.escape(key)}["\']', re.I),
    ]
    for pattern in patterns:
        match = pattern.search(html_text or "")
        if match:
            return html.unescape(match.group(1))
    return ""


def extract_title(html_text: str) -> str:
    match = re.search(r"<title>([^<]+)</title>", html_text or "", re.I)
    return html.unescape(match.group(1).strip()) if match else ""


def extract_first_image_src(html_text: str, base_url: str) -> str:
    for match in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html_text or "", re.I):
        src = resolve_image_url(base_url, match.group(1))
        if src:
            return src
    return ""


def resolve_image_url(base_url: str, value: str | None) -> str:
    src = compact(value)
    if not src or src.startswith("data:"):
        return ""
    return urljoin(base_url, src)


def extract_duration_seconds(html_text: str) -> int:
    patterns = [
        r'"lengthSeconds":"(\d+)"',
        r'"durationSeconds":"(\d+)"',
        r'"duration":"PT(?:(\d+)M)?(?:(\d+)S)?"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text or "", re.I)
        if not match:
            continue
        if len(match.groups()) == 1:
            return int(match.group(1))
        minutes = int(match.group(1) or 0)
        seconds = int(match.group(2) or 0)
        total = minutes * 60 + seconds
        if total:
            return total
    return 0


def extract_json_object_after_marker(html_text: str, marker: str) -> dict[str, Any]:
    index = html_text.find(marker)
    if index < 0:
        return {}
    start = index + len(marker)
    while start < len(html_text) and html_text[start].isspace():
        start += 1
    if start >= len(html_text) or html_text[start] != "{":
        return {}

    depth = 0
    in_string = False
    escaped = False
    for end in range(start, len(html_text)):
        char = html_text[end]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                payload = html_text[start : end + 1]
                try:
                    parsed = json.loads(payload)
                except json.JSONDecodeError:
                    return {}
                return parsed if isinstance(parsed, dict) else {}
    return {}


def extract_bilibili_structured_metadata(html_text: str) -> dict[str, Any]:
    state = extract_json_object_after_marker(html_text, "window.__INITIAL_STATE__=")
    video_data = state.get("videoData") if isinstance(state, dict) else {}
    if not isinstance(video_data, dict):
        return {}
    owner = video_data.get("owner") if isinstance(video_data.get("owner"), dict) else {}
    stats = video_data.get("stat") if isinstance(video_data.get("stat"), dict) else {}
    pages = video_data.get("pages") if isinstance(video_data.get("pages"), list) else []
    parts = " ".join(compact(item.get("part")) for item in pages[:4] if isinstance(item, dict))
    description = compact(video_data.get("desc"))
    return {
        "title": compact(video_data.get("title")),
        "description": description,
        "body_text": compact(" ".join(part for part in [compact(video_data.get("title")), description, compact(owner.get("name")), parts] if part)),
        "image_url": compact(video_data.get("pic")),
        "uploader": compact(owner.get("name")),
        "bvid": compact(video_data.get("bvid")),
        "duration_seconds": int(video_data.get("duration") or 0),
        "view_count": int(stats.get("view") or 0),
    }


def extract_uploader_name(html_text: str) -> str:
    for pattern in (r'"ownerChannelName":"([^"]+)"', r'"author":"([^"]+)"'):
        match = re.search(pattern, html_text or "", re.I)
        if match:
            return html.unescape(match.group(1))
    return ""


def extract_view_count(html_text: str) -> int:
    match = re.search(r'"viewCount":"(\d+)"', html_text or "", re.I)
    if not match:
        return 0
    try:
        return int(match.group(1))
    except ValueError:
        return 0


def extract_duckduckgo_result_links(html_text: str) -> list[str]:
    matches = re.finditer(r'result__a[^>]+href="([^"]+)"', html_text or "", re.I)
    return [html.unescape(match.group(1)) for match in matches if compact(match.group(1)).startswith("http")]


def extract_bing_result_links(html_text: str) -> list[str]:
    matches = re.finditer(r'<li class="b_algo"[\s\S]{0,1200}?<a href="([^"]+)"', html_text or "", re.I)
    links: list[str] = []
    for match in matches:
        link = html.unescape(match.group(1))
        decoded = decode_bing_redirect(link)
        if compact(decoded).startswith("http"):
            links.append(decoded)
    return links


def extract_youtube_result_links(html_text: str) -> list[str]:
    video_ids = re.findall(r'"videoRenderer"[\s\S]{0,600}?"videoId":"([^"]+)"', html_text or "")
    return [f"https://www.youtube.com/watch?v={video_id}" for video_id in video_ids]


def extract_bilibili_result_links(html_text: str) -> list[str]:
    urls = []
    for match in re.finditer(r'"arcurl":"([^"]+)"', html_text or ""):
        encoded = match.group(1)
        try:
            urls.append(json.loads(f'"{encoded}"'))
        except json.JSONDecodeError:
            continue
    return urls


def extract_apple_music_result_links(html_text: str) -> list[str]:
    links: list[str] = []
    for match in re.finditer(r'"url":"(https:\\/\\/(?:classical\.)?music\.apple\.com[^"]+)"', html_text or ""):
        try:
            link = json.loads(f'"{match.group(1)}"')
        except json.JSONDecodeError:
            continue
        if "/album/" in link or "/song/" in link or "/playlist/" in link:
            links.append(link)
    return links


def decode_bing_redirect(url: str) -> str:
    target = compact(url)
    if "bing.com/ck/a" not in target:
        return target
    match = re.search(r"[?&]u=([^&]+)", target)
    if not match:
        return target
    encoded = match.group(1)
    if encoded.startswith("a1"):
        encoded = encoded[2:]
    padding = "=" * ((4 - len(encoded) % 4) % 4)
    try:
        decoded = base64.b64decode(encoded + padding).decode("utf-8")
    except Exception:
        return target
    return decoded if decoded.startswith("http") else target


def detect_platform(url: str) -> str:
    normalized = url.lower()
    if "youtube.com" in normalized or "youtu.be" in normalized:
        return "youtube"
    if "bilibili.com" in normalized:
        return "bilibili"
    if "apple.com" in normalized:
        return "apple_music"
    if "spotify.com" in normalized:
        return "spotify"
    if "qobuz.com" in normalized:
        return "qobuz"
    return "other"


def score_recording_match(
    text: str,
    url: str,
    draft: DraftRecordingEntry,
    *,
    duration_seconds: int = 0,
    uploader: str = "",
) -> float:
    haystack = normalize_text(f"{text} {url} {uploader}")
    score = 0.2
    years_in_text = extract_year_mentions(haystack)

    work_text = draft.work_title_latin or draft.work_title
    work_tokens = tokenize(work_text)
    work_core_tokens = tokenize(strip_catalogue_text(work_text))
    work_aliases = build_work_aliases(draft.work_title_latin)
    work_aliases.update(build_work_aliases(draft.work_title))
    named_work_aliases = build_named_work_aliases(draft.work_title_latin)
    named_work_aliases.update(build_named_work_aliases(draft.work_title))
    work_matched = False
    if work_tokens and contains_tokens(haystack, work_tokens):
        work_matched = True
    elif work_core_tokens and contains_tokens(haystack, work_core_tokens):
        work_matched = True
    elif work_aliases and any(alias in haystack for alias in work_aliases):
        work_matched = True
    if work_matched:
        score += 0.25

    catalogue_tokens = tokenize(draft.catalogue)
    if catalogue_tokens and contains_tokens(haystack, catalogue_tokens):
        score += 0.12

    composer_value = draft.composer_name_latin or draft.composer_name
    composer_tokens = tokenize(composer_value)
    composer_matched = False
    if composer_tokens and (contains_tokens(haystack, composer_tokens) or name_matches(haystack, composer_value)):
        composer_matched = True
        score += 0.08
    elif composer_tokens and work_matched and (looks_latin(composer_value) or compact(draft.composer_name_latin)):
        score -= 0.24

    lead_slots = build_lead_slots(draft)
    sparse_collaboration_hint = has_sparse_collaboration_hint(draft, lead_slots)
    lead_hits = 0
    for slot in lead_slots:
        if any(name_matches(haystack, lead) for lead in slot):
            lead_hits += 1
    if lead_hits:
        score += 0.18 + 0.08 * max(0, lead_hits - 1)
    if len(lead_slots) >= 2 and lead_hits < len(lead_slots):
        collaboration_separators = [" / ", "&", " and ", " with "]
        if any(separator in haystack for separator in collaboration_separators):
            penalty = 0.24 * (len(lead_slots) - lead_hits)
            if sparse_collaboration_hint and has_collaboration_marker(text) and work_matched and lead_hits >= 1:
                penalty *= 0.15
            score -= penalty
        elif has_explicit_collaborator_marker(text):
            score -= 0.18 * (len(lead_slots) - lead_hits)
    if len(lead_slots) >= 2 and not draft.ensemble_names and not draft.ensemble_names_latin:
        if lead_hits == len(lead_slots):
            score += 0.18
        elif lead_hits == 1:
            if sparse_collaboration_hint and has_collaboration_marker(text) and work_matched:
                score += 0.08
                if has_complete_work_tracklist(haystack):
                    score += 0.18
                elif named_work_aliases and any(alias in haystack for alias in named_work_aliases):
                    score += 0.08
            else:
                score -= 0.1
    elif has_collaboration_marker(draft.title) and not draft.ensemble_names and not draft.ensemble_names_latin:
        if has_collaboration_marker(text) and lead_hits >= 1 and work_matched:
            score += 0.18
            if named_work_aliases and any(alias in haystack for alias in named_work_aliases):
                score += 0.06
        elif lead_hits >= 1 and not has_collaboration_marker(text):
            score -= 0.12

    group_hits = 0
    for group in dedupe_text([*draft.ensemble_names[:2], *draft.ensemble_names_latin[:2]])[:4]:
        if ensemble_matches(haystack, group):
            group_hits += 1
    if group_hits:
        score += 0.15
    if work_matched and lead_hits and group_hits:
        score += 0.06

    year = infer_reference_year(draft)
    if year and year in haystack:
        score += 0.08
    if year and years_in_text and year not in years_in_text:
        score -= 0.32
    performance_context_tokens = extract_performance_context_tokens(draft.performance_date_text)
    if performance_context_tokens and contains_tokens(haystack, performance_context_tokens):
        score += 0.1
    score += score_catalogue_fit(draft, haystack)

    if looks_like_single_movement(haystack):
        score -= 0.34
    if looks_like_multi_work_compilation(haystack):
        score -= 0.34
    if "provided to youtube by" in haystack:
        score -= 0.1
    score += score_duration_fit(draft, haystack, duration_seconds)

    negative_patterns = [
        "biography",
        "discography of",
        "born ",
        "composer profile",
        "work details",
        "人物简介",
        "生平",
        "作品介绍",
    ]
    if any(pattern in haystack for pattern in negative_patterns):
        score -= 0.28

    if (work_tokens or work_aliases) and not work_matched:
        score -= 0.22
    if lead_slots and lead_hits == 0:
        score -= 0.1
    if draft.ensemble_names and group_hits == 0:
        score -= 0.08

    return max(0.0, min(0.97, score))


def score_duration_fit(draft: DraftRecordingEntry, haystack: str, duration_seconds: int) -> float:
    minimum = estimate_full_work_min_duration_seconds(draft)
    if duration_seconds <= 0 or minimum <= 0:
        return 0.0
    if duration_seconds >= int(minimum * 0.85):
        return 0.05 if "full" in haystack or "complete" in haystack else 0.02
    if duration_seconds < max(240, int(minimum * 0.35)):
        return -0.38
    if duration_seconds < int(minimum * 0.6):
        return -0.18
    return 0.0


def score_catalogue_fit(draft: DraftRecordingEntry, haystack: str) -> float:
    catalogue = normalize_text(draft.catalogue)
    if not catalogue:
        return 0.0
    if catalogue in haystack:
        return 0.06
    requested_numbers = extract_catalogue_markers(catalogue)
    if not requested_numbers:
        return 0.0
    seen_numbers = extract_catalogue_markers(haystack)
    if seen_numbers and requested_numbers.isdisjoint(seen_numbers):
        return -0.2
    return 0.0


def has_complete_work_tracklist(haystack: str) -> bool:
    numbered_sections = len(re.findall(r"(?:^|\D)([1-6])\.", haystack))
    movement_terms = sum(
        1
        for token in ("allegro", "adagio", "andante", "scherzo", "rondo", "presto", "larghetto", "largo")
        if token in haystack
    )
    if numbered_sections >= 3 and movement_terms >= 2:
        return True
    return movement_terms >= 3


def infer_reference_year(draft: DraftRecordingEntry) -> str:
    return (
        extract_year(draft.performance_date_text)
        or extract_year(draft.title)
        or extract_year(draft.raw_text)
    )


def estimate_full_work_min_duration_seconds(draft: DraftRecordingEntry) -> int:
    work_text = normalize_text(f"{draft.work_title_latin} {draft.work_title}")
    if any(token in work_text for token in ("symphony", "交响曲", "concerto", "协奏曲", "variations", "变奏曲")):
        return 900
    if any(token in work_text for token in ("sonata", "奏鸣曲", "quartet", "四重奏", "trio", "三重奏")):
        return 720
    if any(token in work_text for token in ("mass", "requiem", "opera", "suite", "组曲")):
        return 900
    return 0


def name_matches(haystack: str, value: str) -> bool:
    tokens = tokenize(value)
    if not tokens:
        return False
    if contains_tokens(haystack, tokens):
        return True
    surname = tokens[-1]
    if len(surname) >= 4 and surname in haystack:
        return True
    initials = "".join(token[0] for token in tokens if token)
    if len(initials) >= 2:
        initials_pattern = r"\b" + r"[\.\s]+".join(re.escape(char.lower()) for char in initials) + r"\.?\b"
        if re.search(initials_pattern, haystack, re.I):
            return True
    return False


def ensemble_matches(haystack: str, value: str) -> bool:
    tokens = tokenize(value)
    if not tokens:
        return False
    if contains_tokens(haystack, tokens):
        return True
    acronym = build_acronym(tokens)
    compact_haystack = haystack.replace(".", "").replace(" ", "")
    if acronym and acronym.lower() in compact_haystack:
        return True
    if is_compact_acronym(value) and acronym_sequence_matches(haystack, value):
        return True
    significant = [token for token in tokens if token not in {"orchestra", "philharmonic", "symphony", "ensemble", "choir"}]
    return bool(significant) and all(token in haystack for token in significant)


def build_lead_slots(draft: DraftRecordingEntry) -> list[list[str]]:
    slots: list[list[str]] = []
    primary = dedupe_text([*getattr(draft, "primary_names", []), *getattr(draft, "primary_names_latin", [])])
    secondary = dedupe_text([*getattr(draft, "secondary_names", []), *getattr(draft, "secondary_names_latin", [])])
    if primary:
        slots.append(primary)
    if secondary:
        slots.append(secondary)
    if not slots:
        lead_names = draft.lead_names[:2]
        lead_names_latin = draft.lead_names_latin[:2]
        count = max(len(lead_names), len(lead_names_latin))
        for index in range(count):
            slot = dedupe_text(
                [
                    lead_names[index] if index < len(lead_names) else "",
                    lead_names_latin[index] if index < len(lead_names_latin) else "",
                ]
            )
            if slot:
                slots.append(slot)
    return slots


def has_sparse_collaboration_hint(draft: DraftRecordingEntry, lead_slots: list[list[str]]) -> bool:
    title_hint = has_collaboration_marker(draft.title) or has_sparse_title_duo_separator(draft.title)
    if not title_hint or len(lead_slots) < 2:
        return False
    for slot in lead_slots[1:]:
        if any(looks_latin(value) for value in slot):
            continue
        if any(contains_cjk(value) for value in slot):
            return True
    return False


def has_sparse_title_duo_separator(value: str) -> bool:
    normalized = compact(value)
    if " - " not in normalized:
        return False
    segments = [segment.strip() for segment in normalized.split(" - ") if compact(segment)]
    return len(segments) >= 2


def has_explicit_collaborator_marker(value: str) -> bool:
    normalized = compact(value).lower()
    return has_collaboration_marker(normalized) or " - " in normalized or ", " in normalized


def build_acronym(tokens: list[str]) -> str:
    significant = [token for token in tokens if len(token) >= 2]
    if len(significant) < 2:
        return ""
    return "".join(token[0] for token in significant)


def is_compact_acronym(value: str) -> bool:
    normalized = compact(value).replace(".", "").replace(" ", "")
    return 2 <= len(normalized) <= 6 and normalized.isalpha() and normalized.upper() == normalized


def acronym_sequence_matches(haystack: str, value: str) -> bool:
    acronym = compact(value).replace(".", "").replace(" ", "").lower()
    if len(acronym) < 2:
        return False
    words = [token for token in tokenize(haystack) if len(token) >= 2]
    if len(words) < len(acronym):
        return False
    target = list(acronym)
    for index in range(len(words) - len(target) + 1):
        window = words[index : index + len(target)]
        initials = "".join(word[0] for word in window)
        if initials == acronym:
            return True
    return False


def build_work_aliases(value: str) -> set[str]:
    text = compact(value)
    aliases: set[str] = set()
    normalized = normalize_text(text)
    if normalized:
        aliases.add(normalized)
    stripped = normalize_text(strip_catalogue_text(text))
    if stripped:
        aliases.add(stripped)
    aliases.update(build_keyed_work_aliases(text))
    aliases.update(build_named_work_aliases(text))

    arabic_match = re.search(r"\u7b2c?\s*(\d+)\s*(\u4ea4\u54cd\u66f2|\u534f\u594f\u66f2|\u594f\u9e23\u66f2)", text)
    chinese_match = re.search(
        r"\u7b2c?\s*([\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u4e24]+)\s*(\u4ea4\u54cd\u66f2|\u534f\u594f\u66f2|\u594f\u9e23\u66f2)",
        text,
    )
    number = ""
    form = ""
    if arabic_match:
        number = arabic_match.group(1)
        form = arabic_match.group(2)
    elif chinese_match:
        number = str(chinese_number_to_int(chinese_match.group(1)))
        form = chinese_match.group(2)

    if not number or not form:
        return aliases

    english_form = {
        "\u4ea4\u54cd\u66f2": "symphony",
        "\u534f\u594f\u66f2": "concerto",
        "\u594f\u9e23\u66f2": "sonata",
    }.get(form, "")
    if not english_form:
        return aliases

    aliases.add(f"{english_form} no {number}")
    aliases.add(f"{english_form} no. {number}")
    aliases.add(f"{english_form} no.{number}")
    aliases.add(f"{english_form} n {number}")
    aliases.add(f"{english_form} {number}")
    if english_form == "symphony":
        aliases.add(f"sym {number}")
        aliases.add(f"sym{number}")
    return aliases


def build_keyed_work_aliases(value: str) -> set[str]:
    text = compact(value)
    if not text:
        return set()
    normalized = normalize_text(text)
    aliases: set[str] = set()
    is_concerto = "concerto" in normalized or "协奏曲" in text
    is_sonata = "sonata" in normalized or "奏鸣曲" in text
    is_symphony = "symphony" in normalized or "交响曲" in text

    if "协奏曲" in text:
        is_concerto = True
    if "奏鸣曲" in text:
        is_sonata = True
    if "交响曲" in text:
        is_symphony = True

    key_names = extract_key_aliases(text)
    if not key_names:
        return aliases

    for key_name in key_names:
        if is_concerto:
            concerto_instruments = infer_concerto_instruments(text, normalized)
            for instrument in concerto_instruments:
                aliases.add(f"{instrument} concerto")
                aliases.add(f"{instrument} concerto {key_name}")
                aliases.add(f"{instrument} concerto in {key_name}")
            aliases.add(f"concerto {key_name}")
            if "piano" in concerto_instruments:
                aliases.add(f"klavierkonzert {key_name}")
        if is_sonata:
            aliases.add(f"sonata {key_name}")
            aliases.add(f"sonata in {key_name}")
        if is_symphony:
            aliases.add(f"symphony {key_name}")
            aliases.add(f"symphony in {key_name}")
    return {normalize_text(alias) for alias in aliases if compact(alias)}


def infer_concerto_instruments(text: str, normalized: str) -> list[str]:
    instrument_map = [
        ("violin", ("小提琴", "violin")),
        ("piano", ("钢琴", "鋼琴", "piano", "klavier")),
        ("cello", ("大提琴", "cello")),
        ("flute", ("长笛", "flute")),
    ]
    return [
        label
        for label, markers in instrument_map
        if any(marker in text or marker in normalized for marker in markers)
    ]


def build_named_work_aliases(value: str) -> set[str]:
    text = compact(value)
    normalized = normalize_text(text)
    aliases: set[str] = set()
    nickname_map = {
        "appassionata": ["appassionata", "热情"],
        "spring": ["spring", "春天"],
    }
    for alias, markers in nickname_map.items():
        if any(marker in normalized or marker in text for marker in markers):
            aliases.add(alias)
    if "piano sonata no 23" in normalized or "op.57" in normalized or "op57" in normalized:
        aliases.add("appassionata")
    if "violin sonata no 5" in normalized or "op.24" in normalized or "op24" in normalized:
        aliases.add("spring")
    return aliases


def extract_key_aliases(value: str) -> set[str]:
    text = compact(value)
    aliases: set[str] = set()
    latin_match = re.search(r"\b([a-g])\s*(?:-| )?(major|minor|maj|min)\b", text, flags=re.I)
    if latin_match:
        note = latin_match.group(1).lower()
        mode = latin_match.group(2).lower()
        if mode == "maj":
            mode = "major"
        elif mode == "min":
            mode = "minor"
        aliases.add(f"{note} {mode}")
        aliases.add(f"{note}-{mode}")

    cn_match = re.search(r"([A-Ga-g])\s*(大调|小调)", text)
    if cn_match:
        note = cn_match.group(1).lower()
        mode = "major" if cn_match.group(2) == "大调" else "minor"
        aliases.add(f"{note} {mode}")
        aliases.add(f"{note}-{mode}")

    return aliases


def extract_catalogue_markers(value: str) -> set[str]:
    text = normalize_text(value)
    markers: set[str] = set()
    for prefix in ("op", "kv", "k", "bwv", "hob", "d", "wab", "sz", "rv"):
        for number in re.findall(rf"\b{prefix}\s*\.?\s*(\d+[a-z]?)\b", text):
            markers.add(f"{prefix}{number}")
    return markers


def chinese_number_to_int(value: str) -> int:
    digits = {
        "\u96f6": 0,
        "\u4e00": 1,
        "\u4e8c": 2,
        "\u4e24": 2,
        "\u4e09": 3,
        "\u56db": 4,
        "\u4e94": 5,
        "\u516d": 6,
        "\u4e03": 7,
        "\u516b": 8,
        "\u4e5d": 9,
    }
    units = {"\u5341": 10, "\u767e": 100}
    total = 0
    current = 0
    for char in value:
        if char in digits:
            current = digits[char]
        elif char in units:
            unit = units[char]
            total += (current or 1) * unit
            current = 0
    return total + current


def strip_catalogue_text(value: str) -> str:
    return re.sub(r"\b(?:op|k|bwv|hob|d|wab)\.?\s*\d+[a-z]?\b", "", compact(value), flags=re.I).strip(" ,.;:-")


def normalize_text(value: str) -> str:
    normalized = compact(value).lower()
    normalized = re.sub(r"№\s*(\d+)", r" no \1", normalized)
    normalized = re.sub(r"\bn\s*[°º]\s*(\d+)", r" no \1", normalized)
    normalized = re.sub(r"\bno\.?\s*(\d+)", r" no \1", normalized)
    normalized = re.sub(r"\bsym\s*\.?\s*(\d+)", r" sym \1", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def tokenize(value: str) -> list[str]:
    return [
        token
        for token in re.split(r"[^a-z0-9\u4e00-\u9fff]+", normalize_text(value))
        if len(token) >= 2 or token.isdigit()
    ]


def contains_tokens(haystack: str, tokens: list[str]) -> bool:
    return bool(tokens) and all(token in haystack for token in tokens)


def extract_year(value: str) -> str:
    match = re.search(r"(19\d{2}|20\d{2})", value or "")
    return match.group(1) if match else ""


def extract_year_mentions(value: str) -> set[str]:
    return {match.group(1) for match in re.finditer(r"(19\d{2}|20\d{2})", value or "")}


def extract_performance_context_tokens(value: str) -> list[str]:
    normalized = re.sub(r"(19\d{2}|20\d{2})", " ", value or "")
    tokens = tokenize(normalized)
    stopwords = {
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "live",
        "recorded",
        "recording",
    }
    return [token for token in tokens if token not in stopwords and not token.isdigit()]


def extract_release_date(value: str) -> str:
    match = re.search(r"((?:19|20)\d{2}(?:[-/.]\d{2}){0,2})", value or "")
    return match.group(1) if match else ""


def extract_label(value: str) -> str:
    patterns = [
        re.compile(r"label[:：]?\s*([^|,/.]+)", re.I),
        re.compile(r"厂牌[:：]?\s*([^|,/.]+)", re.I),
        re.compile(r"发行商[:：]?\s*([^|,/.]+)", re.I),
    ]
    for pattern in patterns:
        match = pattern.search(value or "")
        if match:
            return match.group(1).strip()
    return ""


def extract_venue(value: str) -> str:
    patterns = [
        re.compile(r"(?:venue|location|live at)[:：]?\s*([^|,/]+)", re.I),
        re.compile(r"(?:地点|现场|录于)[:：]?\s*([^|,/]+)", re.I),
    ]
    for pattern in patterns:
        match = pattern.search(value or "")
        if match:
            return match.group(1).strip()
    return ""


def looks_like_single_movement(value: str) -> bool:
    lowered = value or ""
    roman_markers = {
        marker.lower()
        for marker in re.findall(r"(?:^|[^a-z])(i{1,3}|iv|v)\.\s", lowered, re.I)
    }
    arabic_markers = {
        marker
        for marker in re.findall(r"(?:^|[\s(:\-–—])([1-9])\.\s", lowered, re.I)
    }
    numbered_markers = {
        marker
        for marker in re.findall(r"\b([1-9][0-9]{0,1})(?:st|nd|rd|th)\s+movement\b", lowered, re.I)
    }
    movement_heading_count = len(roman_markers) + len(arabic_markers) + len(numbered_markers)
    movement_terms = [
        "allegro",
        "adagio",
        "andante",
        "scherzo",
        "rondo",
        "presto",
        "largo",
    ]
    distinct_movement_terms = sum(1 for term in movement_terms if re.search(rf"\b{term}\b", lowered, re.I))
    if distinct_movement_terms >= 3:
        return False
    if movement_heading_count >= 2:
        return False
    if movement_heading_count >= 1 and re.search(r"\b(full|complete)\b", lowered, re.I):
        return False
    if movement_heading_count >= 1 and distinct_movement_terms >= 1:
        return True

    patterns = [
        r":\s*i\.\s",
        r":\s*ii\.\s",
        r":\s*iii\.\s",
        r":\s*iv\.\s",
        r":\s*v\.\s",
        r"1st movement",
        r"2nd movement",
        r"3rd movement",
        r"4th movement",
        r"\bgoldberg variations\b.*:\s*aria\b",
        r"allegro con brio",
        r"andante",
        r"adagio",
        r"scherzo",
        r"\baria\b",
    ]
    return any(re.search(pattern, value, re.I) for pattern in patterns)


def looks_like_multi_work_compilation(value: str) -> bool:
    patterns = [
        r"nos?\.\s*\d+\s*(?:and|&)\s*\d+",
        r"\bnos?\s*\d+\s*,\s*\d+",
        r"\bnos?\s*\d+\s*/\s*\d+",
        r"symphonies\s+nos?\.",
        r"\bsonatas\b",
        r" overture",
        r" overtures",
        r" works /",
        r" works by",
    ]
    return any(re.search(pattern, value, re.I) for pattern in patterns)
