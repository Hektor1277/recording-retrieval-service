from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx

from app.services.http_sources import (
    HttpSourceProvider,
    build_work_aliases,
    extract_bing_result_links,
    looks_like_single_movement,
    normalize_host,
    score_recording_match,
)
from app.services.pipeline import DraftRecordingEntry, RetrievalProfile
from app.services.platform_search_config import (
    AppleMusicSearchConfig,
    BilibiliSearchConfig,
    PlatformSearchConfig,
    YouTubeSearchConfig,
)
from app.services.source_profiles import OrchestraAliasLoader, SourceProfileLoader
from app.services.source_profiles import PersonAliasLoader


class SearchTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "bing.com" in url:
            return httpx.Response(
                200,
                request=request,
                text="""
                <html><body>
                  <li class="b_algo"><h2><a href="https://catalog.example/releases/recording-2">hit</a></h2></li>
                </body></html>
                """,
            )
        if "youtube.com/results" in url:
            return httpx.Response(
                200,
                request=request,
                text='{"videoRenderer":{"videoId":"abc123xyz00","title":{"runs":[{"text":"Klemperer LSO Tchaikovsky 5"}]}}}',
            )
        if "catalog.example" in url:
            return httpx.Response(
                200,
                request=request,
                text="""
                <html><head>
                  <title>Tchaikovsky Symphony No. 5 - Klemperer - LSO - 1964</title>
                  <meta property="og:description" content="Recorded live in London. Label: EMI. Release 1965." />
                  <meta property="og:image" content="https://catalog.example/cover.jpg" />
                </head><body>Otto Klemperer London Symphony Orchestra 1964</body></html>
                """,
            )
        if "youtube.com/watch" in url:
            return httpx.Response(
                200,
                request=request,
                text="""
                <html><head>
                  <title>Klemperer LSO Tchaikovsky 5</title>
                  <meta property="og:description" content="London Symphony Orchestra, 1964." />
                </head><body>Otto Klemperer London Symphony Orchestra 1964</body></html>
                """,
            )
        return httpx.Response(404, request=request, text="not found")


class CountingSearchTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.requests: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if "youtube.com/results" in url:
            return httpx.Response(
                200,
                request=request,
                text='{"videoRenderer":{"videoId":"abc123xyz00","title":{"runs":[{"text":"Klemperer LSO Tchaikovsky 5"}]}}}',
            )
        if "youtube.com/watch" in url:
            return httpx.Response(
                200,
                request=request,
                text="""
                <html><head>
                  <title>Klemperer LSO Tchaikovsky 5</title>
                  <meta property="og:description" content="London Symphony Orchestra, 1964." />
                </head><body>Otto Klemperer London Symphony Orchestra 1964</body></html>
                """,
            )
        if "bilibili.com" in url:
            return httpx.Response(500, request=request, text="should not be called")
        return httpx.Response(404, request=request, text="not found")


class MultiQueryYouTubeTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "youtube.com/results" in url:
            if "Otto+Klemperer+1960" in url:
                return httpx.Response(
                    200,
                    request=request,
                    text='{"videoRenderer":{"videoId":"later000001","title":{"runs":[{"text":"Better Klemperer result"}]}}}',
                )
            return httpx.Response(
                200,
                request=request,
                text='{"videoRenderer":{"videoId":"first000001","title":{"runs":[{"text":"Movement only"}]}}}',
            )
        if "youtube.com/watch?v=first000001" in url:
            return httpx.Response(
                200,
                request=request,
                text="""<html><head><title>Symphony No. 5 in C Minor, Op. 67: I. Allegro con brio</title></head><body></body></html>""",
            )
        if "youtube.com/watch?v=later000001" in url:
            return httpx.Response(
                200,
                request=request,
                text="""<html><head><title>Beethoven - Symphony No 5 in C minor, Op 67 - Klemperer</title><meta property="og:description" content="Philharmonia Orchestra 1960." /></head><body>Otto Klemperer Philharmonia Orchestra 1960</body></html>""",
            )
        return httpx.Response(404, request=request, text="not found")


class QueryRecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.urls.append(url)
        if "youtube.com/results" in url or "bilibili.com" in url:
            return httpx.Response(200, request=request, text="")
        return httpx.Response(404, request=request, text="not found")


class LaterQueryYouTubeTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "youtube.com/results" not in url:
            return httpx.Response(404, request=request, text="not found")
        if "query-one" in url:
            text = "".join(
                f'{{"videoRenderer":{{"videoId":"q1{i:02d}","title":{{"runs":[{{"text":"query one {i}"}}]}}}}}}'
                for i in range(4)
            )
            return httpx.Response(200, request=request, text=text)
        if "query-two" in url:
            text = "".join(
                f'{{"videoRenderer":{{"videoId":"q2{i:02d}","title":{{"runs":[{{"text":"query two {i}"}}]}}}}}}'
                for i in range(4)
            )
            return httpx.Response(200, request=request, text=text)
        text = '{"videoRenderer":{"videoId":"later-hit-01","title":{"runs":[{"text":"later hit"}]}}}'
        return httpx.Response(200, request=request, text=text)


class DeepResultYouTubeTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "youtube.com/results" not in url:
            return httpx.Response(404, request=request, text="not found")
        text = "".join(
            f'{{"videoRenderer":{{"videoId":"junk{i:02d}","title":{{"runs":[{{"text":"junk {i}"}}]}}}}}}'
            for i in range(4)
        )
        text += "".join(
            f'{{"videoRenderer":{{"videoId":"deep{i:02d}","title":{{"runs":[{{"text":"deep {i}"}}]}}}}}}'
            for i in range(1, 5)
        )
        return httpx.Response(200, request=request, text=text)


class HostSliceAwareProvider(HttpSourceProvider):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.hydrated_urls: list[str] = []

    async def _search_streaming_host(
        self,
        draft: DraftRecordingEntry,
        profile: RetrievalProfile,
        host,
    ) -> list[dict[str, str]]:
        del draft, profile, host
        return [
            {"url": f"https://stream.example/{index}", "source_label": "Streaming Search", "source_kind": "streaming"}
            for index in range(1, 13)
        ]

    async def _hydrate_results(
        self,
        draft: DraftRecordingEntry,
        rows: list[dict[str, str]],
        source_kind: str,
    ) -> list[dict[str, str]]:
        del draft, source_kind
        self.hydrated_urls = [row["url"] for row in rows]
        return rows


class ParallelHostProvider(HttpSourceProvider):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.host_start_times: dict[str, float] = {}

    async def _search_streaming_host(
        self,
        draft: DraftRecordingEntry,
        profile: RetrievalProfile,
        host,
    ) -> list[dict[str, str]]:
        del draft, profile
        self.host_start_times[host.url] = time.perf_counter()
        await asyncio.sleep(0.12)
        return [
            {
                "url": f"{host.url.rstrip('/')}/video/result",
                "source_label": normalize_host(host.url),
                "source_kind": "streaming",
            }
        ]

    async def _hydrate_results(
        self,
        draft: DraftRecordingEntry,
        rows: list[dict[str, str]],
        source_kind: str,
    ) -> list[dict[str, str]]:
        del draft, source_kind
        return rows


class PriorityCoverageProvider(HttpSourceProvider):
    async def _search_streaming_host(
        self,
        draft: DraftRecordingEntry,
        profile: RetrievalProfile,
        host,
    ) -> list[dict[str, str]]:
        del draft, profile
        normalized = normalize_host(host.url)
        if "youtube.com" in normalized:
            return [
                {
                    "url": f"https://www.youtube.com/watch?v=yt{index:02d}",
                    "source_label": "YouTube Search",
                    "source_kind": "streaming",
                }
                for index in range(12)
            ]
        return [
            {
                "url": "https://www.bilibili.com/video/BV1priorityhit1",
                "source_label": "Bilibili Search",
                "source_kind": "streaming",
            }
        ]

    async def _hydrate_results(
        self,
        draft: DraftRecordingEntry,
        rows: list[dict[str, str]],
        source_kind: str,
    ) -> list[dict[str, str]]:
        del draft, source_kind
        return rows


class MultiHostDeepSliceAwareProvider(HttpSourceProvider):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.hydrated_urls: list[str] = []

    async def _search_streaming_host(
        self,
        draft: DraftRecordingEntry,
        profile: RetrievalProfile,
        host,
    ) -> list[dict[str, str]]:
        del draft, profile
        normalized = normalize_host(host.url)
        if "youtube.com" in normalized:
            return [
                {
                    "url": f"https://www.youtube.com/watch?v=yt{index:02d}",
                    "source_label": "YouTube Search",
                    "source_kind": "streaming",
                }
                for index in range(1, 7)
            ] + [
                {
                    "url": "https://www.youtube.com/watch?v=annie-deep-hit",
                    "source_label": "YouTube Search",
                    "source_kind": "streaming",
                },
                {
                    "url": "https://www.youtube.com/watch?v=yt08",
                    "source_label": "YouTube Search",
                    "source_kind": "streaming",
                },
            ]
        return [
            {
                "url": "https://www.bilibili.com/video/BV1coverage01/",
                "source_label": "Bilibili Search",
                "source_kind": "streaming",
            },
            {
                "url": "https://www.bilibili.com/video/BV1coverage02/",
                "source_label": "Bilibili Search",
                "source_kind": "streaming",
            },
        ]

    async def _hydrate_results(
        self,
        draft: DraftRecordingEntry,
        rows: list[dict[str, str]],
        source_kind: str,
    ) -> list[dict[str, str]]:
        del draft, source_kind
        self.hydrated_urls = [row["url"] for row in rows]
        return rows


class AdaptiveHydrationProvider(HttpSourceProvider):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.hydration_windows: list[list[str]] = []

    async def _search_streaming_host(
        self,
        draft: DraftRecordingEntry,
        profile: RetrievalProfile,
        host,
    ) -> list[dict[str, str]]:
        del draft, profile
        normalized = normalize_host(host.url)
        if "youtube.com" in normalized:
            return [
                {
                    "url": f"https://www.youtube.com/watch?v=yt{index:02d}",
                    "source_label": "YouTube Search",
                    "source_kind": "streaming",
                }
                for index in range(1, 15)
            ]
        return [
            {
                "url": f"https://www.bilibili.com/video/BV1adaptive{index:02d}/",
                "source_label": "Bilibili Search",
                "source_kind": "streaming",
            }
            for index in range(1, 5)
        ]

    async def _hydrate_results(
        self,
        draft: DraftRecordingEntry,
        rows: list[dict[str, str]],
        source_kind: str,
    ) -> list[dict[str, str]]:
        del draft, source_kind
        urls = [row["url"] for row in rows]
        self.hydration_windows.append(urls)
        hydrated: list[dict[str, str]] = []
        for row in rows:
            score = 0.1
            if row["url"] == "https://www.youtube.com/watch?v=yt09":
                score = 0.72
            hydrated.append(
                {
                    **row,
                    "title": row["url"].rsplit("=", 1)[-1],
                    "platform": "youtube" if "youtube.com" in row["url"] else "bilibili",
                    "weight": 0.6,
                    "same_recording_score": score,
                    "fields": {},
                    "images": [],
                }
            )
        return hydrated


class FlakyYouTubeTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.call_count = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.call_count += 1
        url = str(request.url)
        if "youtube.com/results" in url:
            if self.call_count == 1:
                raise httpx.ReadTimeout("timed out", request=request)
            return httpx.Response(
                200,
                request=request,
                text='{"videoRenderer":{"videoId":"abc123xyz00","title":{"runs":[{"text":"Klemperer LSO Tchaikovsky 5"}]}}}',
            )
        if "youtube.com/watch" in url:
            return httpx.Response(
                200,
                request=request,
                text="""
                <html><head><title>Klemperer LSO Tchaikovsky 5</title></head>
                <body>Otto Klemperer London Symphony Orchestra 1964</body></html>
                """,
            )
        return httpx.Response(404, request=request, text="not found")


class EngineRecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.urls.append(url)
        if "bing.com" in url:
            return httpx.Response(
                200,
                request=request,
                text='<li class="b_algo"><h2><a href="https://catalog.example/releases/recording-2">hit</a></h2></li>',
            )
        if "duckduckgo.com" in url:
            return httpx.Response(403, request=request, text="forbidden")
        if "catalog.example" in url:
            return httpx.Response(
                200,
                request=request,
                text="<html><head><title>hit</title></head><body>content</body></html>",
            )
        return httpx.Response(404, request=request, text="not found")


class ApiFirstTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.urls: list[str] = []
        self.headers: dict[str, dict[str, str]] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.urls.append(url)
        self.headers[url] = {key.decode().lower(): value.decode() for key, value in request.headers.raw}
        if "googleapis.com/youtube/v3/search" in url:
            return httpx.Response(
                200,
                request=request,
                json={
                    "items": [
                        {
                            "id": {"videoId": "apiyoutube01"},
                            "snippet": {"title": "Klemperer API result"},
                        }
                    ]
                },
            )
        if "api.music.apple.com/v1/catalog" in url:
            return httpx.Response(
                200,
                request=request,
                json={
                    "results": {
                        "songs": {
                            "data": [
                                {
                                    "attributes": {
                                        "url": "https://music.apple.com/us/album/demo/1?i=1",
                                        "name": "Apple API Result",
                                    }
                                }
                            ]
                        }
                    }
                },
            )
        if url.rstrip("/") == "https://www.bilibili.com":
            return httpx.Response(200, request=request, text="home")
        if "api.bilibili.com/x/web-interface/nav" in url:
            return httpx.Response(
                200,
                request=request,
                json={
                    "code": 0,
                    "data": {
                        "wbi_img": {
                            "img_url": "https://i0.hdslb.com/bfs/wbi/abcdefghijklmnopqrstuvwxyz123456.png",
                            "sub_url": "https://i0.hdslb.com/bfs/wbi/uvwxyzabcdefghijklmnopqrstuvwxyz123456.jpg",
                        }
                    },
                },
            )
        if "api.bilibili.com/x/web-interface/wbi/search/type" in url:
            return httpx.Response(
                200,
                request=request,
                json={
                    "code": 0,
                    "data": {
                        "result": [
                            {"arcurl": "https://www.bilibili.com/video/BV1apiresult1"}
                        ]
                    }
                },
            )
        if "youtube.com/results" in url:
            return httpx.Response(
                200,
                request=request,
                text='{"videoRenderer":{"videoId":"fallback001","title":{"runs":[{"text":"fallback"}]}}}',
            )
        if "music.apple.com/search" in url:
            return httpx.Response(
                200,
                request=request,
                text='"url":"https:\\/\\/music.apple.com\\/us\\/album\\/fallback\\/1?i=1"',
            )
        if "search.bilibili.com/all" in url:
            return httpx.Response(
                200,
                request=request,
                text='"arcurl":"https:\\/\\/www.bilibili.com\\/video\\/BV1fallback1"',
            )
        return httpx.Response(404, request=request, text="not found")


class FallbackApiTransport(ApiFirstTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "googleapis.com/youtube/v3/search" in url:
            self.urls.append(url)
            return httpx.Response(403, request=request, json={"error": {"message": "quota exceeded"}})
        return await super().handle_async_request(request)


class HtmlEndpointFallbackTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.urls: list[str] = []
        self.headers: dict[str, dict[str, str]] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.urls.append(url)
        self.headers[url] = {key.decode().lower(): value.decode() for key, value in request.headers.raw}
        if "classical.music.apple.com/search" in url:
            return httpx.Response(200, request=request, text="")
        if "music.apple.com/search" in url:
            return httpx.Response(
                200,
                request=request,
                text='"url":"https:\\/\\/music.apple.com\\/us\\/album\\/fallback\\/1?i=1"',
            )
        if "search.bilibili.com/all" in url:
            return httpx.Response(200, request=request, text="")
        if "search.bilibili.com/video" in url:
            return httpx.Response(
                200,
                request=request,
                text='"arcurl":"https:\\/\\/www.bilibili.com\\/video\\/BV1fallbackvideo1"',
            )
        return httpx.Response(404, request=request, text="not found")


class PlatformEngineFallbackTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.urls.append(url)
        if "search.bilibili.com" in url or "classical.music.apple.com/search" in url or "music.apple.com/search" in url:
            return httpx.Response(200, request=request, text="")
        if "bing.com" in url and "site%3Awww.bilibili.com" in url:
            return httpx.Response(
                200,
                request=request,
                text='<li class="b_algo"><h2><a href="https://www.bilibili.com/video/BV1enginefallback1">hit</a></h2></li>',
            )
        if "bing.com" in url and "site%3Amusic.apple.com" in url:
            return httpx.Response(
                200,
                request=request,
                text='<li class="b_algo"><h2><a href="https://music.apple.com/us/album/engine-fallback/1?i=1">hit</a></h2></li>',
            )
        return httpx.Response(404, request=request, text="not found")


class YouTubeEngineMergeTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.urls.append(url)
        if "youtube.com/results" in url:
            return httpx.Response(
                200,
                request=request,
                text='{"videoRenderer":{"videoId":"native001","title":{"runs":[{"text":"native"}]}}}',
            )
        if "bing.com" in url and "site%3Awww.youtube.com" in url:
            return httpx.Response(
                200,
                request=request,
                text='<li class="b_algo"><h2><a href="https://www.youtube.com/watch?v=engine002">hit</a></h2></li>',
            )
        return httpx.Response(404, request=request, text="not found")


class BrowserResultFetcher:
    def __init__(self, links_by_url: dict[str, list[str]]) -> None:
        self.links_by_url = links_by_url
        self.page_calls: list[str] = []
        self.link_calls: list[str] = []

    async def fetch_page(self, url: str, timeout_seconds: float | None = None) -> dict[str, str]:
        del timeout_seconds
        self.page_calls.append(url)
        return {}

    async def fetch_links(
        self,
        url: str,
        *,
        url_patterns: list[str] | None = None,
        timeout_seconds: float | None = None,
    ) -> list[str]:
        del url_patterns, timeout_seconds
        self.link_calls.append(url)
        return list(self.links_by_url.get(url, []))


class StructuredBrowserFetcher(BrowserResultFetcher):
    def __init__(
        self,
        links_by_url: dict[str, list[str]],
        page_payloads: dict[str, dict[str, str | int]],
    ) -> None:
        super().__init__(links_by_url)
        self.page_payloads = page_payloads

    async def fetch_page(self, url: str, timeout_seconds: float | None = None) -> dict[str, str | int]:
        del timeout_seconds
        self.page_calls.append(url)
        return dict(self.page_payloads.get(url, {}))


def build_draft() -> DraftRecordingEntry:
    return DraftRecordingEntry(
        item_id="recording-1",
        title="Klemperer LSO 1964",
        composer_name="柴可夫斯基",
        composer_name_latin="Pyotr Ilyich Tchaikovsky",
        work_title="第五交响曲",
        work_title_latin="Symphony No. 5 in E Minor",
        catalogue="Op.64",
        performance_date_text="1964",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="Otto Klemperer | London Symphony Orchestra | 1964",
        raw_text="Otto Klemperer | London Symphony Orchestra | 1964",
        existing_links=[],
        lead_names=["Otto Klemperer"],
        ensemble_names=["London Symphony Orchestra"],
    )


def build_profile() -> RetrievalProfile:
    return RetrievalProfile(
        category="orchestral",
        tags=[],
        queries=["Symphony No. 5 in E Minor Op.64 Otto Klemperer London Symphony Orchestra 1964"],
    )


def test_extract_bing_result_links_reads_direct_result_url() -> None:
    html = '<li class="b_algo"><h2><a href="https://catalog.example/releases/recording-2">hit</a></h2></li>'

    assert extract_bing_result_links(html) == ["https://catalog.example/releases/recording-2"]


def test_extract_bing_result_links_decodes_redirect_url() -> None:
    html = (
        '<li class="b_algo"><h2><a href="https://www.bing.com/ck/a?u=a1'
        'aHR0cHM6Ly9jYXRhbG9nLmV4YW1wbGUvcmVsZWFzZXMvcmVjb3JkaW5nLTM&ntb=1">hit</a></h2></li>'
    )

    assert extract_bing_result_links(html) == ["https://catalog.example/releases/recording-3"]


def test_provider_uses_bing_for_high_quality_search_engine(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://www.youtube.com\n", encoding="utf-8")
    transport = EngineRecordingTransport()
    client = httpx.AsyncClient(transport=transport, follow_redirects=True)
    provider = HttpSourceProvider(profile_loader=SourceProfileLoader(root), client=client)

    results = asyncio.run(provider.search_high_quality(build_draft(), build_profile()))

    assert results
    assert results[0]["url"] == "https://catalog.example/releases/recording-2"
    assert any("bing.com" in url for url in transport.urls)
    assert not any("duckduckgo.com" in url for url in transport.urls)


def test_provider_can_search_youtube_directly_without_external_search_engine(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://www.youtube.com\n", encoding="utf-8")
    client = httpx.AsyncClient(transport=SearchTransport(), follow_redirects=True)
    provider = HttpSourceProvider(profile_loader=SourceProfileLoader(root), client=client)

    results = asyncio.run(provider.search_streaming(build_draft(), build_profile()))

    assert results
    assert any(row["url"] == "https://www.youtube.com/watch?v=abc123xyz00" for row in results)


def test_provider_merges_youtube_native_results_with_search_engine_recall(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://www.youtube.com\n", encoding="utf-8")
    transport = YouTubeEngineMergeTransport()
    client = httpx.AsyncClient(transport=transport, follow_redirects=True)
    provider = HttpSourceProvider(
        profile_loader=SourceProfileLoader(root),
        client=client,
        browser_fetcher=BrowserResultFetcher({}),
        platform_search_config=PlatformSearchConfig(
            youtube=YouTubeSearchConfig(enabled=False),
        ),
    )

    rows = asyncio.run(provider._search_youtube(["schumann annie fischer"]))

    assert any(row["url"] == "https://www.youtube.com/watch?v=native001" for row in rows)
    assert any(row["url"] == "https://www.youtube.com/watch?v=engine002" for row in rows)
    assert any("bing.com" in url and "site%3Awww.youtube.com" in url for url in transport.urls)


def test_provider_keeps_streaming_host_scan_for_deeper_candidates(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://www.youtube.com\nhttps://www.bilibili.com\n", encoding="utf-8")
    transport = CountingSearchTransport()
    client = httpx.AsyncClient(transport=transport, follow_redirects=True)
    provider = HttpSourceProvider(
        profile_loader=SourceProfileLoader(root),
        client=client,
        browser_fetcher=BrowserResultFetcher({}),
    )

    results = asyncio.run(provider.search_streaming(build_draft(), build_profile()))

    assert results
    assert any("youtube.com/results" in url for url in transport.requests)
    assert any("bilibili.com" in url for url in transport.requests)


def test_provider_can_be_reused_across_multiple_asyncio_runs(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://www.youtube.com\n", encoding="utf-8")
    client = httpx.AsyncClient(transport=SearchTransport(), follow_redirects=True)
    provider = HttpSourceProvider(profile_loader=SourceProfileLoader(root), client=client)

    first = asyncio.run(provider.search_streaming(build_draft(), build_profile()))
    second = asyncio.run(provider.search_streaming(build_draft(), build_profile()))

    assert first
    assert second


def test_provider_aggregates_multiple_queries_within_same_streaming_host(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://www.youtube.com\n", encoding="utf-8")
    client = httpx.AsyncClient(transport=MultiQueryYouTubeTransport(), follow_redirects=True)
    provider = HttpSourceProvider(profile_loader=SourceProfileLoader(root), client=client)
    profile = RetrievalProfile(
        category="orchestral",
        tags=[],
        queries=["first query", "Otto Klemperer 1960"],
    )

    results = asyncio.run(provider.search_streaming(build_draft(), profile))

    assert any(row["url"] == "https://www.youtube.com/watch?v=first000001" for row in results)
    assert any(row["url"] == "https://www.youtube.com/watch?v=later000001" for row in results)


def test_youtube_search_keeps_later_queries_even_after_two_queries_fill_initial_budget(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://www.youtube.com\n", encoding="utf-8")
    client = httpx.AsyncClient(transport=LaterQueryYouTubeTransport(), follow_redirects=True)
    provider = HttpSourceProvider(profile_loader=SourceProfileLoader(root), client=client)

    rows = asyncio.run(provider._search_youtube(["query one", "query two", "query three"]))

    assert any(row["url"] == "https://www.youtube.com/watch?v=later-hit-01" for row in rows)


def test_youtube_search_reads_deeper_results_beyond_first_four_links_per_query(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://www.youtube.com\n", encoding="utf-8")
    client = httpx.AsyncClient(transport=DeepResultYouTubeTransport(), follow_redirects=True)
    provider = HttpSourceProvider(profile_loader=SourceProfileLoader(root), client=client)

    rows = asyncio.run(provider._search_youtube(["deep query"]))

    assert any(row["url"] == "https://www.youtube.com/watch?v=deep04" for row in rows)


def test_search_streaming_hydrates_more_than_first_four_rows_from_successful_host(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://www.youtube.com\n", encoding="utf-8")
    provider = HostSliceAwareProvider(profile_loader=SourceProfileLoader(root))

    results = asyncio.run(provider.search_streaming(build_draft(), build_profile()))

    assert any(row["url"] == "https://stream.example/12" for row in results)
    assert "https://stream.example/12" in provider.hydrated_urls


def test_provider_collects_access_telemetry_and_host_summary(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://www.youtube.com\n", encoding="utf-8")
    client = httpx.AsyncClient(transport=SearchTransport(), follow_redirects=True)
    provider = HttpSourceProvider(profile_loader=SourceProfileLoader(root), client=client)

    results = asyncio.run(provider.search_streaming(build_draft(), build_profile()))
    events = provider.consume_access_events()
    summary = provider.get_access_summary()

    assert results
    assert any(event["host"] == "www.youtube.com" for event in events)
    assert any(event["operation"] == "streaming-search" for event in events)
    assert summary["hosts"]["www.youtube.com"]["requests"] >= 2
    assert summary["hosts"]["www.youtube.com"]["avgLatencyMs"] >= 0


def test_provider_access_summary_marks_unstable_host_and_recommends_higher_timeout(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://www.youtube.com\n", encoding="utf-8")
    client = httpx.AsyncClient(transport=FlakyYouTubeTransport(), follow_redirects=True)
    provider = HttpSourceProvider(
        profile_loader=SourceProfileLoader(root),
        client=client,
        platform_search_config=PlatformSearchConfig(youtube=YouTubeSearchConfig(enabled=False, api_key="")),
    )

    asyncio.run(provider.search_streaming(build_draft(), build_profile()))
    asyncio.run(provider.search_streaming(build_draft(), build_profile()))
    summary = provider.get_access_summary()

    assert summary["hosts"]["www.youtube.com"]["failures"] >= 1
    assert summary["hosts"]["www.youtube.com"]["recommendedTimeoutSeconds"] > 6.0
    assert summary["hosts"]["www.youtube.com"]["status"] == "degraded"


def test_provider_skips_duckduckgo_after_repeated_failures(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://www.youtube.com\n", encoding="utf-8")
    transport = EngineRecordingTransport()
    client = httpx.AsyncClient(transport=transport, follow_redirects=True)
    provider = HttpSourceProvider(profile_loader=SourceProfileLoader(root), client=client)

    for _ in range(3):
        provider._record_access_event(
            url="https://html.duckduckgo.com/html/?q=test",
            operation="search-engine",
            ok=False,
            duration_ms=7000,
            source_kind="search",
            source_label="Web Search",
            error="403",
        )

    rows = asyncio.run(provider._search_query_via_engines(query="test query", source_label="Web Search", source_kind="search"))

    assert rows
    assert any("bing.com" in url for url in transport.urls)
    assert not any("duckduckgo.com" in url for url in transport.urls)


class ExactLinkTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "youtube.com/watch?v=shortclip001" in url:
            return httpx.Response(
                200,
                request=request,
                text="""
                <html><head>
                  <title>Annie Fischer - Schumann / Piano Concerto in A Minor / A-moll zongoraverseny</title>
                  <meta property="og:description" content="Annie Fischer (1914 -- 1995) Schumann - Piano Concerto in A Minor&#10;vezényel: Paul Kletzki" />
                  <meta property="og:image" content="https://img.youtube.com/vi/shortclip001/hqdefault.jpg" />
                  <script>var ytInitialPlayerResponse = {"videoDetails":{"lengthSeconds":"225","author":"MaldororArt","shortDescription":"Annie Fischer (1914 -- 1995) Schumann - Piano Concerto in A Minor\\nvezényel: Paul Kletzki","title":"Annie Fischer - Schumann / Piano Concerto in A Minor / A-moll zongoraverseny","viewCount":"5506"}};</script>
                </head><body>Annie Fischer Paul Kletzki</body></html>
                """,
            )
        if "youtube.com/watch?v=fullclip001" in url:
            return httpx.Response(
                200,
                request=request,
                text="""
                <html><head>
                  <title>Annie Fischer plays Schumann: Klavierkonzert a-minor  video! full!</title>
                  <meta property="og:description" content="Full performance" />
                  <meta property="og:image" content="https://img.youtube.com/vi/fullclip001/hqdefault.jpg" />
                  <script>var ytInitialPlayerResponse = {"videoDetails":{"lengthSeconds":"2016","author":"Katalin Sin","shortDescription":"Full performance","title":"Annie Fischer plays Schumann: Klavierkonzert a-minor  video! full!","viewCount":"88772"}};</script>
                </head><body>Annie Fischer Klavierkonzert a-minor full performance</body></html>
                """,
            )
        return httpx.Response(404, request=request, text="not found")


def build_annie_draft() -> DraftRecordingEntry:
    return DraftRecordingEntry(
        item_id="recording-annie",
        title="Annie Fischer & Kletzki",
        composer_name="罗伯特·舒曼",
        composer_name_latin="Robert Schumann",
        work_title="a小调钢琴协奏曲",
        work_title_latin="Piano Concerto in A Minor, Op.54",
        catalogue="Op.54",
        performance_date_text="",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="Robert Schumann | Piano Concerto in A Minor, Op.54 | Annie Fischer | Kletzki | -",
        raw_text="Robert Schumann | Piano Concerto in A Minor, Op.54 | Annie Fischer | Kletzki | -",
        existing_links=[],
        primary_names=["Annie Fischer"],
        primary_names_latin=["Annie Fischer"],
        secondary_names=["Kletzki"],
        secondary_names_latin=["Kletzki"],
        lead_names=["Annie Fischer", "Kletzki"],
        lead_names_latin=["Annie Fischer", "Kletzki"],
        query_lead_names=["Annie Fischer", "Kletzki"],
        query_lead_names_latin=["Annie Fischer", "Kletzki"],
    )


def test_provider_penalizes_short_excerpt_against_full_length_upload(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://www.youtube.com\n", encoding="utf-8")
    client = httpx.AsyncClient(transport=ExactLinkTransport(), follow_redirects=True)
    provider = HttpSourceProvider(profile_loader=SourceProfileLoader(root), client=client)

    rows = asyncio.run(
        provider._hydrate_results(
            build_annie_draft(),
            [
                {"url": "https://www.youtube.com/watch?v=shortclip001", "source_label": "YouTube Search", "source_kind": "streaming"},
                {"url": "https://www.youtube.com/watch?v=fullclip001", "source_label": "YouTube Search", "source_kind": "streaming"},
            ],
            "streaming",
        )
    )
    score_by_url = {row["url"]: row["same_recording_score"] for row in rows}

    assert score_by_url["https://www.youtube.com/watch?v=fullclip001"] > score_by_url["https://www.youtube.com/watch?v=shortclip001"]
    assert score_by_url["https://www.youtube.com/watch?v=shortclip001"] < 0.75


def test_build_work_aliases_infers_violin_concerto_from_chinese_title() -> None:
    aliases = build_work_aliases("D大调小提琴协奏曲")

    assert "violin concerto d major" in aliases
    assert "violin concerto in d major" in aliases


def test_provider_prefers_youtube_api_when_configured(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://www.youtube.com\n", encoding="utf-8")
    transport = ApiFirstTransport()
    client = httpx.AsyncClient(transport=transport, follow_redirects=True)
    provider = HttpSourceProvider(
        profile_loader=SourceProfileLoader(root),
        client=client,
        platform_search_config=PlatformSearchConfig(
            youtube=YouTubeSearchConfig(api_key="yt-key"),
        ),
    )

    rows = asyncio.run(provider._search_youtube(["klemperer query"]))

    assert any(row["url"] == "https://www.youtube.com/watch?v=apiyoutube01" for row in rows)
    assert any("googleapis.com/youtube/v3/search" in url for url in transport.urls)
    assert not any("youtube.com/results" in url for url in transport.urls)


def test_provider_falls_back_to_youtube_html_when_api_fails(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://www.youtube.com\n", encoding="utf-8")
    transport = FallbackApiTransport()
    client = httpx.AsyncClient(transport=transport, follow_redirects=True)
    provider = HttpSourceProvider(
        profile_loader=SourceProfileLoader(root),
        client=client,
        platform_search_config=PlatformSearchConfig(
            youtube=YouTubeSearchConfig(api_key="yt-key"),
        ),
    )

    rows = asyncio.run(provider._search_youtube(["klemperer query"]))

    assert any(row["url"] == "https://www.youtube.com/watch?v=fallback001" for row in rows)
    assert any("googleapis.com/youtube/v3/search" in url for url in transport.urls)
    assert any("youtube.com/results" in url for url in transport.urls)


def test_provider_disables_youtube_api_after_quota_error_in_same_run(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://www.youtube.com\n", encoding="utf-8")
    transport = FallbackApiTransport()
    client = httpx.AsyncClient(transport=transport, follow_redirects=True)
    provider = HttpSourceProvider(
        profile_loader=SourceProfileLoader(root),
        client=client,
        platform_search_config=PlatformSearchConfig(
            youtube=YouTubeSearchConfig(api_key="yt-key"),
        ),
    )

    rows = asyncio.run(provider._search_youtube(["query-one", "query-two"]))

    assert any(row["url"] == "https://www.youtube.com/watch?v=fallback001" for row in rows)
    assert sum("googleapis.com/youtube/v3/search" in url for url in transport.urls) == 1
    assert sum("youtube.com/results" in url for url in transport.urls) >= 2


def test_provider_expands_title_inferred_chinese_collaborator_into_latin_youtube_queries(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://www.youtube.com\n", encoding="utf-8")
    person_alias_path = tmp_path / "person-name-aliases.txt"
    person_alias_path.write_text(
        "#global\n托斯卡尼尼 = Arturo Toscanini\n亚莎·海菲兹 = Jascha Heifetz\n",
        encoding="utf-8",
    )
    provider = HttpSourceProvider(
        profile_loader=SourceProfileLoader(root),
        person_alias_loader=PersonAliasLoader(person_alias_path),
    )
    draft = DraftRecordingEntry(
        item_id="recording-yt-query-1",
        title="托斯卡尼尼 - 海菲兹 - NBC Symphony Orchestra - March 11, 1940",
        composer_name="贝多芬",
        composer_name_latin="Ludwig van Beethoven",
        work_title="D大调小提琴协奏曲",
        work_title_latin="Violin Concerto in D major, Op.61",
        catalogue="Op.61",
        performance_date_text="March 11, 1940",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="",
        raw_text="",
        existing_links=[],
        query_lead_names=["亚莎·海菲兹", "托斯卡尼尼"],
        query_lead_names_latin=["Jascha Heifetz"],
        ensemble_names=["NBC Symphony Orchestra"],
        ensemble_names_latin=["NBC Symphony Orchestra"],
    )
    profile = RetrievalProfile(category="concerto", tags=[], queries=[], latin_queries=[], zh_queries=[], mixed_queries=[])
    host = provider._profile_loader.load(category="concerto", tags=[]).streaming[0]

    queries = provider._queries_for_host(draft, profile, host)

    assert any("Arturo Toscanini" in query for query in queries)


def test_queries_for_host_keep_soloist_only_work_query_for_concerto_full_draft() -> None:
    provider = HttpSourceProvider()
    draft = DraftRecordingEntry(
        item_id="recording-annie-query-1",
        title="Annie Fischer & Kletzki",
        composer_name="舒曼",
        composer_name_latin="Robert Schumann",
        work_title="a小调钢琴协奏曲",
        work_title_latin="Piano Concerto, Op.54",
        catalogue="Op.54",
        performance_date_text="",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="Robert Schumann | Piano Concerto in A Minor, Op.54 | Annie Fischer | Kletzki | Budapest Philharmonic Orchestra | -",
        raw_text="Robert Schumann | Piano Concerto in A Minor, Op.54 | Annie Fischer | Kletzki | Budapest Philharmonic Orchestra | -",
        existing_links=[],
        primary_names=["Annie Fischer"],
        primary_names_latin=["Annie Fischer"],
        secondary_names=["Kletzki"],
        secondary_names_latin=["Kletzki"],
        query_lead_names=["Annie Fischer", "Kletzki"],
        query_lead_names_latin=["Annie Fischer", "Kletzki"],
        lead_names=["Annie Fischer", "Kletzki"],
        lead_names_latin=["Annie Fischer", "Kletzki"],
        ensemble_names=["Budapest Philharmonic Orchestra"],
        ensemble_names_latin=["Budapest Philharmonic Orchestra"],
    )
    profile = RetrievalProfile(category="concerto", tags=[], queries=[], latin_queries=[], zh_queries=[], mixed_queries=[])
    host = next(host for host in provider._profile_loader.load(category="concerto", tags=[]).streaming if "youtube.com" in host.url)

    queries = provider._queries_for_host(draft, profile, host)

    assert "Piano Concerto, Op.54 Annie Fischer" in queries
    assert any("Annie Fischer" in query and "klavierkonzert" in query.lower() for query in queries)


def test_provider_prefers_apple_music_api_when_configured(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://music.apple.com\n", encoding="utf-8")
    transport = ApiFirstTransport()
    client = httpx.AsyncClient(transport=transport, follow_redirects=True)
    provider = HttpSourceProvider(
        profile_loader=SourceProfileLoader(root),
        client=client,
        platform_search_config=PlatformSearchConfig(
            apple_music=AppleMusicSearchConfig(developer_token="apple-token", storefront="us"),
        ),
    )

    rows = asyncio.run(provider._search_apple_music(["schumann query"]))

    assert any("music.apple.com/us/album/demo/1" in row["url"] for row in rows)
    assert any("api.music.apple.com/v1/catalog/us/search" in url for url in transport.urls)
    assert not any("music.apple.com/search" in url for url in transport.urls)


def test_provider_prefers_bilibili_api_when_cookie_configured(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\n[zh] https://www.bilibili.com\n", encoding="utf-8")
    transport = ApiFirstTransport()
    client = httpx.AsyncClient(transport=transport, follow_redirects=True)
    provider = HttpSourceProvider(
        profile_loader=SourceProfileLoader(root),
        client=client,
        browser_fetcher=BrowserResultFetcher({}),
        platform_search_config=PlatformSearchConfig(
            bilibili=BilibiliSearchConfig(cookie="SESSDATA=abc", user_agent="UA/1.0"),
        ),
    )

    rows = asyncio.run(provider._search_bilibili(["布鲁克纳 伯姆"]))

    assert any(row["url"] == "https://www.bilibili.com/video/BV1apiresult1" for row in rows)
    bilibili_api_url = next(url for url in transport.urls if "api.bilibili.com/x/web-interface/wbi/search/type" in url)
    assert transport.headers[bilibili_api_url]["cookie"] == "SESSDATA=abc"
    assert transport.headers[bilibili_api_url]["referer"] == "https://www.bilibili.com"
    assert "w_rid=" in bilibili_api_url
    assert "wts=" in bilibili_api_url
    assert any(url.rstrip("/") == "https://www.bilibili.com" for url in transport.urls)
    assert any("api.bilibili.com/x/web-interface/nav" in url for url in transport.urls)


def test_provider_uses_bilibili_public_wbi_search_without_cookie(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\n[zh] https://www.bilibili.com\n", encoding="utf-8")
    transport = ApiFirstTransport()
    client = httpx.AsyncClient(transport=transport, follow_redirects=True)
    provider = HttpSourceProvider(
        profile_loader=SourceProfileLoader(root),
        client=client,
        browser_fetcher=BrowserResultFetcher({}),
        platform_search_config=PlatformSearchConfig(
            bilibili=BilibiliSearchConfig(enabled=True, user_agent="UA/1.0"),
        ),
    )

    rows = asyncio.run(provider._search_bilibili(["海菲兹 托斯卡尼尼 1940"]))

    assert any(row["url"] == "https://www.bilibili.com/video/BV1apiresult1" for row in rows)
    bilibili_api_url = next(url for url in transport.urls if "api.bilibili.com/x/web-interface/wbi/search/type" in url)
    assert transport.headers[bilibili_api_url]["user-agent"] == "UA/1.0"
    assert transport.headers[bilibili_api_url]["referer"] == "https://www.bilibili.com"
    assert not any("search.bilibili.com/all" in url for url in transport.urls)


def test_provider_tries_multiple_apple_music_html_endpoints_without_api(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://classical.music.apple.com\nhttps://music.apple.com\n", encoding="utf-8")
    transport = HtmlEndpointFallbackTransport()
    client = httpx.AsyncClient(transport=transport, follow_redirects=True)
    provider = HttpSourceProvider(
        profile_loader=SourceProfileLoader(root),
        client=client,
        platform_search_config=PlatformSearchConfig(
            apple_music=AppleMusicSearchConfig(enabled=False, use_itunes_fallback=False),
        ),
    )

    rows = asyncio.run(provider._search_apple_music(["schumann query"]))

    assert any("music.apple.com/us/album/fallback/1" in row["url"] for row in rows)
    assert any("classical.music.apple.com/search" in url for url in transport.urls)
    assert any("music.apple.com/search" in url for url in transport.urls)


def test_provider_tries_multiple_bilibili_html_endpoints_without_api(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\n[zh] https://www.bilibili.com\n", encoding="utf-8")
    transport = HtmlEndpointFallbackTransport()
    client = httpx.AsyncClient(transport=transport, follow_redirects=True)
    provider = HttpSourceProvider(
        profile_loader=SourceProfileLoader(root),
        client=client,
        browser_fetcher=BrowserResultFetcher({}),
        platform_search_config=PlatformSearchConfig(
            bilibili=BilibiliSearchConfig(enabled=False),
        ),
    )

    rows = asyncio.run(provider._search_bilibili(["布鲁克纳 伯姆"]))

    assert any(row["url"] == "https://www.bilibili.com/video/BV1fallbackvideo1" for row in rows)
    assert any("search.bilibili.com/all" in url for url in transport.urls)
    assert any("search.bilibili.com/video" in url for url in transport.urls)


def test_provider_sends_bilibili_headers_for_html_search_when_configured(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\n[zh] https://www.bilibili.com\n", encoding="utf-8")
    transport = HtmlEndpointFallbackTransport()
    client = httpx.AsyncClient(transport=transport, follow_redirects=True)
    provider = HttpSourceProvider(
        profile_loader=SourceProfileLoader(root),
        client=client,
        browser_fetcher=BrowserResultFetcher({}),
        platform_search_config=PlatformSearchConfig(
            bilibili=BilibiliSearchConfig(
                enabled=False,
                cookie="SESSDATA=abc; buvid3=def",
                user_agent="TestAgent/1.0",
                referer="https://www.bilibili.com",
            ),
        ),
    )

    asyncio.run(provider._search_bilibili(["布鲁克纳 伯姆"]))

    bilibili_search_url = next(url for url in transport.urls if "search.bilibili.com/all" in url)
    assert transport.headers[bilibili_search_url]["cookie"] == "SESSDATA=abc; buvid3=def"
    assert transport.headers[bilibili_search_url]["referer"] == "https://www.bilibili.com"
    assert transport.headers[bilibili_search_url]["user-agent"] == "TestAgent/1.0"


def test_provider_falls_back_to_search_engine_when_bilibili_html_is_empty(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\n[zh] https://www.bilibili.com\n", encoding="utf-8")
    transport = PlatformEngineFallbackTransport()
    client = httpx.AsyncClient(transport=transport, follow_redirects=True)
    provider = HttpSourceProvider(
        profile_loader=SourceProfileLoader(root),
        client=client,
        browser_fetcher=BrowserResultFetcher({}),
        platform_search_config=PlatformSearchConfig(
            bilibili=BilibiliSearchConfig(enabled=False),
        ),
    )

    rows = asyncio.run(provider._search_bilibili(["布鲁克纳 伯姆"]))

    assert any(row["url"] == "https://www.bilibili.com/video/BV1enginefallback1" for row in rows)
    assert any("search.bilibili.com/all" in url for url in transport.urls)
    assert any("bing.com" in url and "site%3Awww.bilibili.com" in url for url in transport.urls)


def test_provider_uses_browser_rendered_bilibili_results_before_search_engine_fallback(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\n[zh] https://www.bilibili.com\n", encoding="utf-8")
    transport = PlatformEngineFallbackTransport()
    client = httpx.AsyncClient(transport=transport, follow_redirects=True)
    browser_fetcher = BrowserResultFetcher(
        {
            "https://search.bilibili.com/all?keyword=%E6%B5%B7%E8%8F%B2%E5%85%B9+%E6%89%98%E6%96%AF%E5%8D%A1%E5%B0%BC%E5%B0%BC+1940": [
                "https://www.bilibili.com/video/BV1browserhit1/",
                "https://www.bilibili.com/video/BV1browserhit2/",
            ]
        }
    )
    provider = HttpSourceProvider(
        profile_loader=SourceProfileLoader(root),
        client=client,
        browser_fetcher=browser_fetcher,
        platform_search_config=PlatformSearchConfig(
            bilibili=BilibiliSearchConfig(enabled=False),
        ),
    )

    rows = asyncio.run(provider._search_bilibili(["海菲兹 托斯卡尼尼 1940"]))

    assert [row["url"] for row in rows[:2]] == [
        "https://www.bilibili.com/video/BV1browserhit1/",
        "https://www.bilibili.com/video/BV1browserhit2/",
    ]
    assert any("search.bilibili.com/all" in url for url in browser_fetcher.link_calls)
    assert any("bing.com" in url and "site%3Awww.bilibili.com" in url for url in transport.urls)
    assert any(row["url"] == "https://www.bilibili.com/video/BV1enginefallback1" for row in rows)


def test_provider_accepts_browser_rendered_bilibili_av_links(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\n[zh] https://www.bilibili.com\n", encoding="utf-8")
    transport = PlatformEngineFallbackTransport()
    client = httpx.AsyncClient(transport=transport, follow_redirects=True)
    browser_fetcher = BrowserResultFetcher(
        {
            "https://search.bilibili.com/all?keyword=%E4%BC%AF%E6%81%A9%E6%96%AF%E5%9D%A6+1977": [
                "https://www.bilibili.com/video/av317938669",
            ]
        }
    )
    provider = HttpSourceProvider(
        profile_loader=SourceProfileLoader(root),
        client=client,
        browser_fetcher=browser_fetcher,
        platform_search_config=PlatformSearchConfig(
            bilibili=BilibiliSearchConfig(enabled=False),
        ),
    )

    rows = asyncio.run(provider._search_bilibili(["伯恩斯坦 1977"]))

    assert any(row["url"] == "https://www.bilibili.com/video/av317938669" for row in rows)


def test_provider_uses_browser_metadata_to_enrich_bilibili_video_pages(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\n[zh] https://www.bilibili.com\n", encoding="utf-8")

    class MinimalBilibiliTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if "www.bilibili.com/video/BV1TE411f7uh" in str(request.url):
                return httpx.Response(
                    200,
                    request=request,
                    text=(
                        "<html><head><title>"
                        "【安妮·费舍尔】舒曼钢协现场视频 Annie Fischer plays Schumann Piano Concerto Op. 54_哔哩哔哩_bilibili"
                        "</title></head><body></body></html>"
                    ),
                )
            return httpx.Response(404, request=request, text="not found")

    browser_fetcher = StructuredBrowserFetcher(
        {},
        {
            "https://www.bilibili.com/video/BV1TE411f7uh/": {
                "title": "【安妮·费舍尔】舒曼钢协现场视频 Annie Fischer plays Schumann Piano Concerto Op. 54",
                "description": "https://www.youtube.com/watch?v=wkMQ1q4V4Vs",
                "bodyText": "Annie Fischer Schumann Piano Concerto Op.54",
                "imageUrl": "",
                "uploader": "艾斯跳票",
                "durationSeconds": 2017,
                "viewCount": 1748,
            }
        },
    )
    provider = HttpSourceProvider(
        profile_loader=SourceProfileLoader(root),
        client=httpx.AsyncClient(transport=MinimalBilibiliTransport(), follow_redirects=True),
        browser_fetcher=browser_fetcher,
    )
    draft = DraftRecordingEntry(
        item_id="annie-metadata",
        title="Annie Fischer & Kletzki",
        composer_name="鑸掓浖",
        composer_name_latin="Robert Schumann",
        work_title="a小调钢琴协奏曲",
        work_title_latin="Piano Concerto, Op.54",
        catalogue="Op.54",
        performance_date_text="",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="Robert Schumann | Piano Concerto in A Minor, Op.54 | Annie Fischer | Kletzki | Budapest Philharmonic Orchestra | -",
        raw_text="Robert Schumann | Piano Concerto in A Minor, Op.54 | Annie Fischer | Kletzki | Budapest Philharmonic Orchestra | -",
        existing_links=[],
        primary_names=["Annie Fischer"],
        primary_names_latin=["Annie Fischer"],
        secondary_names=["Kletzki"],
        secondary_names_latin=["Kletzki"],
        lead_names=["Annie Fischer", "Kletzki"],
        lead_names_latin=["Annie Fischer", "Kletzki"],
        ensemble_names=["Budapest Philharmonic Orchestra"],
        ensemble_names_latin=["Budapest Philharmonic Orchestra"],
    )

    row = asyncio.run(
        provider._fetch_page_record(
            "https://www.bilibili.com/video/BV1TE411f7uh/",
            "Bilibili Search Browser Search",
            "streaming",
            draft,
            asyncio.Semaphore(1),
        )
    )

    assert row is not None
    assert row["uploader"] == "艾斯跳票"
    assert row["duration_seconds"] == 2017
    assert row["view_count"] == 1748
    assert row["same_recording_score"] >= 0.6


def test_provider_canonicalizes_bilibili_av_url_to_bv_when_metadata_exposes_bvid(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\n[zh] https://www.bilibili.com\n", encoding="utf-8")

    class CanonicalBilibiliTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if "www.bilibili.com/video/av317938669" in str(request.url):
                return httpx.Response(
                    200,
                    request=request,
                    text=(
                        '<html><script>window.__INITIAL_STATE__={"videoData":{"title":"Bernstein Fantastique",'
                        '"bvid":"BV16P411Y7J1","owner":{"name":"uploader"},"stat":{"view":1024},"duration":3010}};</script></html>'
                    ),
                )
            return httpx.Response(404, request=request, text="not found")

    provider = HttpSourceProvider(
        profile_loader=SourceProfileLoader(root),
        client=httpx.AsyncClient(transport=CanonicalBilibiliTransport(), follow_redirects=True),
        browser_fetcher=BrowserResultFetcher({}),
    )
    draft = DraftRecordingEntry(
        item_id="bernstein-bvid",
        title="Bernstein Fantastique",
        composer_name="柏辽兹",
        composer_name_latin="Hector Berlioz",
        work_title="幻想交响曲",
        work_title_latin="Symphonie Fantastique",
        catalogue="",
        performance_date_text="1977",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="Berlioz | Symphonie Fantastique | Leonard Bernstein | 1977",
        raw_text="Berlioz | Symphonie Fantastique | Leonard Bernstein | 1977",
        existing_links=[],
        primary_names=["Leonard Bernstein"],
        primary_names_latin=["Leonard Bernstein"],
        lead_names=["Leonard Bernstein"],
        lead_names_latin=["Leonard Bernstein"],
    )

    row = asyncio.run(
        provider._fetch_page_record(
            "https://www.bilibili.com/video/av317938669",
            "Bilibili Search",
            "streaming",
            draft,
            asyncio.Semaphore(1),
        )
    )

    assert row is not None
    assert row["url"] == "https://www.bilibili.com/video/BV16P411Y7J1/"


def test_provider_ignores_related_video_year_noise_in_bilibili_metadata(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\n[zh] https://www.bilibili.com\n", encoding="utf-8")

    class NoisyBilibiliTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if "www.bilibili.com/video/BV16P411Y7J1" in str(request.url):
                return httpx.Response(
                    200,
                    request=request,
                    text=(
                        '<html><script>window.__INITIAL_STATE__={"videoData":{'
                        '"title":"伯恩斯坦《柏辽兹：幻想交响曲》法国国家管弦乐团「BD」",'
                        '"desc":"Blu-ray Disc（蓝光碟） - 1080i片源'
                        ' Hector Louis Berlioz (1803—1869)'
                        ' Symphonie fantastique, Op. 14'
                        ' Orchestre National de France'
                        ' Leonard Bernstein, conductor'
                        ' 相关视频：卡拉扬《贝多芬：第五交响曲“命运”》柏林爱乐1982「欧盟版」",'
                        '"bvid":"BV16P411Y7J1",'
                        '"owner":{"name":"Rigel口袋音乐"},'
                        '"stat":{"view":6655},'
                        '"duration":3340'
                        '}};</script></html>'
                    ),
                )
            return httpx.Response(404, request=request, text="not found")

    provider = HttpSourceProvider(
        profile_loader=SourceProfileLoader(root),
        client=httpx.AsyncClient(transport=NoisyBilibiliTransport(), follow_redirects=True),
        browser_fetcher=BrowserResultFetcher({}),
    )
    draft = DraftRecordingEntry(
        item_id="bernstein-noisy-bvid",
        title="Bernstein Fantastique 1977",
        composer_name="柏辽兹",
        composer_name_latin="Hector Berlioz",
        work_title="幻想交响曲",
        work_title_latin="Symphonie Fantastique",
        catalogue="Op. 14",
        performance_date_text="",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="Berlioz | Symphonie Fantastique | Leonard Bernstein | -",
        raw_text="Berlioz | Symphonie Fantastique | Leonard Bernstein | -",
        existing_links=[],
        primary_names=["Leonard Bernstein"],
        primary_names_latin=["Leonard Bernstein"],
        lead_names=["Leonard Bernstein"],
        lead_names_latin=["Leonard Bernstein"],
    )

    row = asyncio.run(
        provider._fetch_page_record(
            "https://www.bilibili.com/video/BV16P411Y7J1/",
            "Bilibili Search",
            "streaming",
            draft,
            asyncio.Semaphore(1),
        )
    )

    assert row is not None
    assert row["same_recording_score"] >= 0.9
    assert row["fields"]["releaseDate"] == ""


def test_provider_falls_back_to_search_engine_when_apple_html_is_empty(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://classical.music.apple.com\nhttps://music.apple.com\n", encoding="utf-8")
    transport = PlatformEngineFallbackTransport()
    client = httpx.AsyncClient(transport=transport, follow_redirects=True)
    provider = HttpSourceProvider(
        profile_loader=SourceProfileLoader(root),
        client=client,
        platform_search_config=PlatformSearchConfig(
            apple_music=AppleMusicSearchConfig(enabled=False, use_itunes_fallback=False),
        ),
    )

    rows = asyncio.run(provider._search_apple_music(["schumann query"]))

    assert any("music.apple.com/us/album/engine-fallback/1" in row["url"] for row in rows)
    assert any("classical.music.apple.com/search" in url for url in transport.urls)
    assert any("bing.com" in url and "site%3Amusic.apple.com" in url for url in transport.urls)


def test_search_streaming_does_not_let_first_host_starve_youtube_follow_up(tmp_path: Path) -> None:
    class NoHydrateProvider(HttpSourceProvider):
        async def _hydrate_results(self, draft, rows, source_kind):
            del draft, source_kind
            return rows

    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\n[zh] https://www.bilibili.com\nhttps://www.youtube.com\n", encoding="utf-8")
    transport = ApiFirstTransport()
    client = httpx.AsyncClient(transport=transport, follow_redirects=True)
    provider = NoHydrateProvider(
        profile_loader=SourceProfileLoader(root),
        client=client,
        browser_fetcher=BrowserResultFetcher({}),
        platform_search_config=PlatformSearchConfig(
            youtube=YouTubeSearchConfig(api_key="yt-key"),
            bilibili=BilibiliSearchConfig(cookie="SESSDATA=abc", user_agent="UA/1.0"),
        ),
    )

    rows = asyncio.run(provider.search_streaming(build_draft(), build_profile()))

    assert rows
    assert any("googleapis.com/youtube/v3/search" in url for url in transport.urls)
    assert any("api.bilibili.com/x/web-interface/wbi/search/type" in url for url in transport.urls)


def test_search_streaming_queries_priority_hosts_in_parallel(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://www.youtube.com\n[zh] https://www.bilibili.com\n", encoding="utf-8")
    provider = ParallelHostProvider(profile_loader=SourceProfileLoader(root))

    started = time.perf_counter()
    rows = asyncio.run(provider.search_streaming(build_draft(), build_profile()))
    elapsed = time.perf_counter() - started

    assert len(rows) == 2
    assert elapsed < 0.2
    assert len(provider.host_start_times) == 2
    start_times = sorted(provider.host_start_times.values())
    assert start_times[-1] - start_times[0] < 0.08


def test_search_streaming_keeps_bilibili_coverage_even_when_youtube_fills_budget(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://www.youtube.com\n[zh] https://www.bilibili.com\n", encoding="utf-8")
    provider = PriorityCoverageProvider(profile_loader=SourceProfileLoader(root))

    rows = asyncio.run(provider.search_streaming(build_draft(), build_profile()))

    urls = [row["url"] for row in rows]
    assert any("youtube.com/watch" in url for url in urls)
    assert any("bilibili.com/video/BV1priorityhit1" in url for url in urls)


def test_search_streaming_keeps_deeper_youtube_hit_when_multiple_priority_hosts_share_budget(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://www.youtube.com\n[zh] https://www.bilibili.com\n", encoding="utf-8")
    provider = MultiHostDeepSliceAwareProvider(profile_loader=SourceProfileLoader(root))

    rows = asyncio.run(provider.search_streaming(build_draft(), build_profile()))

    urls = [row["url"] for row in rows]
    assert "https://www.youtube.com/watch?v=annie-deep-hit" in urls
    assert "https://www.youtube.com/watch?v=annie-deep-hit" in provider.hydrated_urls
    assert any("bilibili.com/video/BV1coverage01/" in url for url in urls)


def test_search_streaming_expands_hydration_window_when_initial_slice_has_no_promising_hits(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://www.youtube.com\n[zh] https://www.bilibili.com\n", encoding="utf-8")
    provider = AdaptiveHydrationProvider(profile_loader=SourceProfileLoader(root))

    rows = asyncio.run(provider.search_streaming(build_draft(), build_profile()))

    urls = [row["url"] for row in rows]
    assert "https://www.youtube.com/watch?v=yt09" in urls
    assert len(provider.hydration_windows) >= 2
    assert len(provider.hydration_windows[0]) == 12
    assert len(provider.hydration_windows[-1]) > 12


def test_looks_like_single_movement_ignores_complete_tracklist_descriptions() -> None:
    text = (
        'Jean Fournier & Ginette Doyen play Beethoven "Spring" Sonata '
        'Violin Sonata No. 5 in F major Opus 24, "Frühlingssonate"'
        '1. Allegro2. Adagio molto espressivo (7:27)3. Scherzo: Allegro molto '
        '(14:22)4. Rondo: Allegro ma non...'
    )

    assert looks_like_single_movement(text) is False


def test_provider_uses_chinese_queries_only_for_chinese_platforms_and_expands_abbreviations(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text(
        "#global\n[zh] https://www.bilibili.com\nhttps://www.youtube.com\n",
        encoding="utf-8",
    )
    alias_path = tmp_path / "orchestra-abbreviations.txt"
    alias_path.write_text("BSO = Boston Symphony Orchestra\n", encoding="utf-8")
    transport = QueryRecordingTransport()
    client = httpx.AsyncClient(transport=transport, follow_redirects=True)
    provider = HttpSourceProvider(
        profile_loader=SourceProfileLoader(root),
        client=client,
        orchestra_alias_loader=OrchestraAliasLoader(alias_path),
        browser_fetcher=BrowserResultFetcher({}),
    )
    draft = DraftRecordingEntry(
        item_id="recording-8",
        title="蒙都 - BSO - 第五交响曲 op.64",
        composer_name="柴可夫斯基",
        composer_name_latin="Tchaikovsky",
        work_title="第五交响曲",
        work_title_latin="Symphony No. 5 in E minor, Op. 64",
        catalogue="Op.64",
        performance_date_text="",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="柴可夫斯基 | 第五交响曲 | 蒙都 | BSO | -",
        raw_text="柴可夫斯基 | 第五交响曲 | 蒙都 | BSO | -",
        existing_links=[],
        lead_names=["蒙都"],
        lead_names_latin=["Monteux"],
        ensemble_names=["BSO"],
        ensemble_names_latin=["BSO"],
    )
    profile = RetrievalProfile(
        category="orchestral",
        tags=[],
        queries=["placeholder"],
        latin_queries=["Tchaikovsky Symphony No. 5 in E minor, Op. 64 Monteux BSO", "Tchaikovsky Symphony No. 5 in E minor, Op. 64 Monteux Boston Symphony Orchestra"],
        zh_queries=["柴可夫斯基 第五交响曲 蒙都 BSO"],
        mixed_queries=["Tchaikovsky 第五交响曲 Monteux BSO"],
    )

    asyncio.run(provider.search_streaming(draft, profile))

    bilibili_urls = [url for url in transport.urls if "bilibili.com" in url]
    youtube_urls = [url for url in transport.urls if "youtube.com/results" in url]
    assert any("%E6%9F%B4%E5%8F%AF%E5%A4%AB%E6%96%AF%E5%9F%BA" in url for url in bilibili_urls)
    assert any("Boston+Symphony+Orchestra" in url for url in youtube_urls)
    assert not any("%E6%9F%B4%E5%8F%AF%E5%A4%AB%E6%96%AF%E5%9F%BA" in url for url in youtube_urls)


def test_non_chinese_platform_queries_promote_named_concerto_aliases_into_executed_budget(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://www.youtube.com\n", encoding="utf-8")
    provider = HttpSourceProvider(profile_loader=SourceProfileLoader(root))
    draft = build_annie_draft()
    item_profile = RetrievalProfile(
        category="concerto",
        tags=[],
        queries=[
            "Robert Schumann Piano Concerto, Op.54 Annie Fischer",
            "Piano Concerto, Op.54 Annie Fischer",
            "Robert Schumann piano concerto Annie Fischer",
            "Robert Schumann concerto a minor Annie Fischer",
            "Piano Concerto, Op.54 Annie Fischer Kletzki Budapest Philharmonic Orchestra",
            "Piano Concerto, Op.54 Annie Fischer / Kletzki Budapest Philharmonic Orchestra",
        ],
        latin_queries=[
            "Robert Schumann Piano Concerto, Op.54 Annie Fischer",
            "Piano Concerto, Op.54 Annie Fischer",
            "Robert Schumann piano concerto Annie Fischer",
            "Robert Schumann concerto a minor Annie Fischer",
        ],
    )
    youtube_host = SourceProfileLoader(root).load(category="concerto", tags=[]).streaming[0]

    queries = provider._queries_for_host(draft, item_profile, youtube_host)

    assert any("klavierkonzert" in query.lower() for query in queries[:8])


def test_non_chinese_platform_queries_include_named_work_aliases_for_solo_repertoire(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    root.mkdir(parents=True)
    (root / "high-quality.txt").write_text("#global\nhttps://catalog.example\n", encoding="utf-8")
    (root / "streaming.txt").write_text("#global\nhttps://www.youtube.com\n", encoding="utf-8")
    provider = HttpSourceProvider(profile_loader=SourceProfileLoader(root))
    draft = DraftRecordingEntry(
        item_id="recording-9",
        title="Claudio Arrau 1970",
        composer_name="路德维希·凡·贝多芬",
        composer_name_latin="Ludwig van Beethoven",
        work_title="第二十三号奏鸣曲，热情",
        work_title_latin="Piano Sonata No.23, Op.57",
        catalogue="Op.57",
        performance_date_text="Beethovenfest Bonn 1970",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="",
        raw_text="",
        existing_links=[],
        lead_names=["Claudio Arrau"],
        lead_names_latin=["Claudio Arrau"],
        ensemble_names=[],
        ensemble_names_latin=[],
    )
    profile = RetrievalProfile(category="chamber_solo", tags=["piano"], queries=[], latin_queries=[], zh_queries=[], mixed_queries=[])
    host = provider._profile_loader.load(category="chamber_solo", tags=["piano"]).streaming[0]

    queries = provider._queries_for_host(draft, profile, host)

    assert any("appassionata" in query.lower() for query in queries)


def test_score_recording_match_accepts_group_acronym_and_year_when_latin_fields_missing() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-2",
        title="Rudolf Kempe - London Symphony Orchestra - 第五交响曲 - 1964",
        composer_name="柴可夫斯基",
        composer_name_latin="",
        work_title="第五交响曲",
        work_title_latin="",
        catalogue="",
        performance_date_text="1964",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="柴可夫斯基 | 第五交响曲 | Rudolf Kempe | London Symphony Orchestra | 1964",
        raw_text="柴可夫斯基 | 第五交响曲 | Rudolf Kempe | London Symphony Orchestra | 1964",
        existing_links=[],
        lead_names=["Rudolf Kempe"],
        ensemble_names=["London Symphony Orchestra"],
    )

    score = score_recording_match(
        "Tchaikovsky : Symphony No.5 R.Kempe /LSO 1964 Proms live",
        "https://www.youtube.com/watch?v=demo",
        draft,
    )

    assert score >= 0.45


def test_score_recording_match_accepts_sparse_ui_input_with_abbreviation_and_surname_only() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-2b",
        title="monteux - BSO - 第五交响曲",
        composer_name="柴可夫斯基",
        composer_name_latin="",
        work_title="第五交响曲",
        work_title_latin="",
        catalogue="op.64",
        performance_date_text="",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="柴可夫斯基 | 第五交响曲 op.64 | monteux | BSO | -",
        raw_text="柴可夫斯基 | 第五交响曲 op.64 | monteux | BSO | -",
        existing_links=[],
        lead_names=["monteux"],
        lead_names_latin=["monteux"],
        ensemble_names=["BSO"],
        ensemble_names_latin=["BSO"],
    )

    score = score_recording_match(
        "Tchaikovsky - Symphony No. 5 in E minor, Op. 64 - Boston Symphony Orchestra - Pierre Monteux (1958)",
        "https://www.youtube.com/watch?v=F70Ofs15dEQ",
        draft,
    )

    assert score >= 0.75


def test_score_recording_match_accepts_exact_chamber_recording_even_when_title_omits_catalogue() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-2c",
        title="亚历山大·莫吉列夫斯基 & 列奥尼德·克鲁策",
        composer_name="路德维希·凡·贝多芬",
        composer_name_latin="Ludwig van Beethoven",
        work_title="第5号小提琴奏鸣曲, “春天”",
        work_title_latin="Violin Sonata No.5, Op.24",
        catalogue="",
        performance_date_text="1931",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="",
        raw_text="",
        existing_links=[],
        lead_names=["Alexander Yakovlevich Mogilevsky", "Leonid Kreutzer"],
        lead_names_latin=["Alexander Yakovlevich Mogilevsky", "Leonid Kreutzer"],
        ensemble_names=[],
        ensemble_names_latin=[],
    )

    score = score_recording_match(
        "Alexandre Moguilewsky & Leonid Kreutzer: Beethoven: Violin Sonata No. 5 (R. ca 1931)",
        "https://www.youtube.com/watch?v=vCC5o4A3HMY",
        draft,
    )

    assert score >= 0.45


def test_score_recording_match_accepts_concerto_resource_when_title_uses_klavierkonzert_and_only_soloist_is_visible() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-concerto-1",
        title="Annie Fischer & Kletzki",
        composer_name="罗伯特·舒曼",
        composer_name_latin="Robert Schumann",
        work_title="a小调钢琴协奏曲",
        work_title_latin="Piano Concerto, Op.54",
        catalogue="Op.54",
        performance_date_text="",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="",
        raw_text="",
        existing_links=[],
        lead_names=["Annie Fischer", "Paul Kletzki"],
        lead_names_latin=["Annie Fischer", "Paul Kletzki"],
        ensemble_names=["Budapest Philharmonic Orchestra"],
        ensemble_names_latin=["Budapest Philharmonic Orchestra"],
    )

    score = score_recording_match(
        "Annie Fischer plays Schumann: Klavierkonzert a-minor video! full!",
        "https://www.youtube.com/watch?v=wkMQ1q4V4Vs",
        draft,
    )

    assert score >= 0.58


def test_score_recording_match_penalizes_alternative_collaborator_when_second_required_lead_is_missing() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-concerto-2",
        title="Annie Fischer & Kletzki",
        composer_name="罗伯特·舒曼",
        composer_name_latin="Robert Schumann",
        work_title="a小调钢琴协奏曲",
        work_title_latin="Piano Concerto, Op.54",
        catalogue="Op.54",
        performance_date_text="",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="",
        raw_text="",
        existing_links=[],
        lead_names=["Annie Fischer", "Paul Kletzki"],
        lead_names_latin=["Annie Fischer", "Paul Kletzki"],
        ensemble_names=["Budapest Philharmonic Orchestra"],
        ensemble_names_latin=["Budapest Philharmonic Orchestra"],
    )

    exact_like = score_recording_match(
        "Annie Fischer plays Schumann: Klavierkonzert a-minor video! full!",
        "https://www.youtube.com/watch?v=wkMQ1q4V4Vs",
        draft,
    )
    wrong_collaborator = score_recording_match(
        "Schumann, Piano Concerto in A Minor, Op.54 / Fischer & Giulini",
        "https://www.youtube.com/watch?v=R4YZRoHbrCw",
        draft,
    )

    assert exact_like > wrong_collaborator
    assert exact_like >= 0.4


def test_score_recording_match_accepts_german_keyed_concerto_alias_from_clean_chinese_work_title() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-concerto-2b",
        title="Annie Fischer & Kletzki",
        composer_name="舒曼",
        composer_name_latin="Robert Schumann",
        work_title="a小调钢琴协奏曲",
        work_title_latin="Piano Concerto, Op.54",
        catalogue="Op.54",
        performance_date_text="",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="",
        raw_text="",
        existing_links=[],
        lead_names=["Annie Fischer", "Paul Kletzki"],
        lead_names_latin=["Annie Fischer", "Paul Kletzki"],
        ensemble_names=["Budapest Philharmonic Orchestra"],
        ensemble_names_latin=["Budapest Philharmonic Orchestra"],
    )

    exact_like = score_recording_match(
        "Annie Fischer plays Schumann: Klavierkonzert a-minor video! full!",
        "https://www.youtube.com/watch?v=wkMQ1q4V4Vs",
        draft,
    )
    wrong_collaborator = score_recording_match(
        "Schumann, Piano Concerto in A Minor, Op.54 / Fischer & Giulini",
        "https://www.youtube.com/watch?v=R4YZRoHbrCw",
        draft,
    )

    assert exact_like > wrong_collaborator
    assert exact_like >= 0.4


def test_score_recording_match_accepts_violin_concerto_alias_when_only_soloist_is_visible() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-concerto-2c",
        title="Heifetz 1940",
        composer_name="贝多芬",
        composer_name_latin="Ludwig van Beethoven",
        work_title="D大调小提琴协奏曲",
        work_title_latin="",
        catalogue="Op.61",
        performance_date_text="",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="",
        raw_text="",
        existing_links=[],
        primary_names=["亚莎·海菲兹"],
        primary_names_latin=["Jascha Heifetz"],
        secondary_names=["阿图罗·托斯卡尼尼"],
        secondary_names_latin=["Arturo Toscanini"],
        query_lead_names=["亚莎·海菲兹"],
        query_lead_names_latin=["Jascha Heifetz"],
        lead_names=["亚莎·海菲兹", "阿图罗·托斯卡尼尼"],
        lead_names_latin=["Jascha Heifetz", "Arturo Toscanini"],
        ensemble_names=[],
        ensemble_names_latin=[],
    )

    exact_like = score_recording_match(
        "Beethoven: Violin Concerto (1940) Heifetz/Toscanini",
        "https://www.youtube.com/watch?v=9YWr1UcbZE8",
        draft,
        duration_seconds=2315,
        uploader="Private Reserve",
    )
    wrong_work = score_recording_match(
        "Tchaikovsky: Violin Concerto in D Major, Op. 35 (reference rec.: Jascha Heifetz / 2023 Remastered)",
        "https://www.youtube.com/watch?v=qhSxS6UnXBo",
        draft,
        duration_seconds=1773,
        uploader="Classical Music Reference Recording",
    )

    assert exact_like >= 0.45
    assert exact_like > wrong_work


def test_score_recording_match_uses_title_year_hint_to_prefer_target_upload_cluster() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-concerto-2d",
        title="海菲兹&托斯卡尼尼 1940",
        composer_name="贝多芬",
        composer_name_latin="Ludwig van Beethoven",
        work_title="D大调小提琴协奏曲",
        work_title_latin="",
        catalogue="Op.61",
        performance_date_text="",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="路德维希·凡·贝多芬 | D大调小提琴协奏曲 | Jascha Heifetz | -",
        raw_text="路德维希·凡·贝多芬 | D大调小提琴协奏曲 | Jascha Heifetz | - | 海菲兹&托斯卡尼尼 1940",
        existing_links=[],
        primary_names=["亚莎·海菲兹"],
        primary_names_latin=["Jascha Heifetz"],
        query_lead_names=["亚莎·海菲兹"],
        query_lead_names_latin=["Jascha Heifetz"],
        lead_names=["亚莎·海菲兹"],
        lead_names_latin=["Jascha Heifetz"],
        ensemble_names=[],
        ensemble_names_latin=[],
    )

    exact_like = score_recording_match(
        "Beethoven: Violin Concerto (1940) Heifetz/Toscanini",
        "https://www.youtube.com/watch?v=9YWr1UcbZE8",
        draft,
        duration_seconds=2315,
        uploader="Private Reserve",
    )
    wrong_upload = score_recording_match(
        "Jascha Heifetz - Beethoven : Violin Concerto Op.61 (1955)",
        "https://www.youtube.com/watch?v=4hEgZXlYOVY",
        draft,
        duration_seconds=2295,
        uploader="uchukyoku1",
    )

    assert exact_like > wrong_upload


def test_score_recording_match_accepts_appassionata_nickname_for_exact_solo_piano_recording() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-solo-1",
        title="Claudio Arrau 1970",
        composer_name="路德维希·凡·贝多芬",
        composer_name_latin="Ludwig van Beethoven",
        work_title="第二十三号奏鸣曲，热情",
        work_title_latin="Piano Sonata No.23, Op.57",
        catalogue="Op.57",
        performance_date_text="Beethovenfest Bonn 1970",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="",
        raw_text="",
        existing_links=[],
        lead_names=["Claudio Arrau"],
        lead_names_latin=["Claudio Arrau"],
        ensemble_names=[],
        ensemble_names_latin=[],
    )

    exact_like = score_recording_match(
        'Claudio Arrau Beethoven "Appassionata" (Full)',
        "https://www.youtube.com/watch?v=Tdg-DT8rTUQ",
        draft,
    )
    wrong_pianist = score_recording_match(
        "Anna Fedorova - Ludwig van Beethoven - Appassionata - Piano Sonata No. 23 in F minor, Op. 57",
        "https://www.youtube.com/watch?v=9uj9g-eH0uw",
        draft,
    )

    assert exact_like > wrong_pianist


def test_score_recording_match_does_not_mistake_complete_multi_movement_listing_for_single_movement() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-solo-1b",
        title="Claudio Arrau 1970",
        composer_name="路德维希·凡·贝多芬",
        composer_name_latin="Ludwig van Beethoven",
        work_title="第二十三号奏鸣曲，热情",
        work_title_latin="Piano Sonata No.23 in F minor, Op.57 Appassionata",
        catalogue="Op.57",
        performance_date_text="Beethovenfest Bonn 1970",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="",
        raw_text="",
        existing_links=[],
        lead_names=["Claudio Arrau"],
        lead_names_latin=["Claudio Arrau"],
        ensemble_names=[],
        ensemble_names_latin=[],
    )

    complete_listing = score_recording_match(
        'Claudio Arrau Beethoven "Appassionata" (Full) Piano Sonata No. 23 in F minor, Op. 57 '
        '"Appassionata" I. Allegro assai II. Andante con moto III. Allegro ma non troppo Beethovenfest Bonn 1970',
        "https://www.youtube.com/watch?v=Tdg-DT8rTUQ",
        draft,
    )
    movement_only = score_recording_match(
        "Piano Sonata No. 23 in F Minor, Op. 57, \"Appassionata\": II. Andante con moto (Live at...)",
        "https://www.youtube.com/watch?v=movement-only",
        draft,
    )

    assert complete_listing > movement_only
    assert complete_listing >= 0.8


def test_score_recording_match_does_not_mistake_arabic_numbered_tracklist_for_single_movement() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-orchestral-1a",
        title="Karl Bohm 1976",
        composer_name="安东·布鲁克纳",
        composer_name_latin="Anton Bruckner",
        work_title="第七交响曲",
        work_title_latin="Symphony No.7 in E major, WAB 107",
        catalogue="WAB 107",
        performance_date_text="February 2-5 1976",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="",
        raw_text="",
        existing_links=[],
        lead_names=["Karl Böhm", "Karl Bohm"],
        lead_names_latin=["Karl Böhm", "Karl Bohm"],
        ensemble_names=["Wiener Philharmoniker"],
        ensemble_names_latin=["Wiener Philharmoniker"],
    )

    complete_tracklist = score_recording_match(
        "[High quality] Anton Bruckner - Symphony No. 7 in E major / Karl Böhm & Wiener Philharmoniker "
        "Anton Bruckner Symphony No. 7 in E major, WAB 107 (00:00) - 1. Allegro moderato "
        "(19:38) - 2. Adagio: Sehr feierlich und sehr langsam",
        "https://www.youtube.com/watch?v=jCkO-GbPLnk",
        draft,
    )
    movement_only = score_recording_match(
        "Symphony No. 7 in E Major, WAB 107: I. Allegro Moderato (Live)",
        "https://www.youtube.com/watch?v=Mr5VNv6jgSU",
        draft,
    )

    assert complete_tracklist > movement_only
    assert complete_tracklist >= 0.75


def test_score_recording_match_rewards_non_year_performance_context_for_exact_recording() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-solo-1c",
        title="Claudio Arrau 1970",
        composer_name="路德维希·凡·贝多芬",
        composer_name_latin="Ludwig van Beethoven",
        work_title="第二十三号奏鸣曲，热情",
        work_title_latin="Piano Sonata No.23 in F minor, Op.57 Appassionata",
        catalogue="Op.57",
        performance_date_text="Beethovenfest Bonn 1970",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="",
        raw_text="",
        existing_links=[],
        lead_names=["Claudio Arrau"],
        lead_names_latin=["Claudio Arrau"],
        ensemble_names=[],
        ensemble_names_latin=[],
    )

    with_context = score_recording_match(
        'Claudio Arrau Beethoven "Appassionata" (Full) Piano Sonata No. 23 in F minor, Op. 57 '
        '"Appassionata" Beethovenfest Bonn 1970',
        "https://www.youtube.com/watch?v=Tdg-DT8rTUQ",
        draft,
    )
    without_context = score_recording_match(
        '1970 Beethoven Piano Sonata No 23 F minor Op 57 Appassionata Claudio Arrau',
        "https://www.youtube.com/watch?v=dmF2fryWk8A",
        draft,
    )

    assert with_context > without_context


def test_score_recording_match_penalizes_wrong_soloist_even_when_work_and_year_match() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-solo-1d",
        title="Claudio Arrau 1970",
        composer_name="路德维希·凡·贝多芬",
        composer_name_latin="Ludwig van Beethoven",
        work_title="第二十三号奏鸣曲，热情",
        work_title_latin="Piano Sonata No.23 in F minor, Op.57 Appassionata",
        catalogue="Op.57",
        performance_date_text="1970",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="",
        raw_text="",
        existing_links=[],
        lead_names=["Claudio Arrau"],
        lead_names_latin=["Claudio Arrau"],
        ensemble_names=[],
        ensemble_names_latin=[],
    )

    exact_like = score_recording_match(
        '1970 Beethoven Piano Sonata No 23 F minor Op 57 Appassionata Claudio Arrau',
        "https://www.youtube.com/watch?v=dmF2fryWk8A",
        draft,
    )
    wrong_soloist = score_recording_match(
        "Gould/Beethoven Sonata No.23 in F minor, op.57 'Appassionata'",
        "https://www.youtube.com/watch?v=T1Kljp4_60U",
        draft,
    )

    assert exact_like > wrong_soloist
    assert wrong_soloist < 0.75


def test_score_recording_match_uses_chinese_work_title_aliases_to_separate_true_and_false_hits() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-3",
        title="Albert Coates - 第五交响曲 - 1922",
        composer_name="柴可夫斯基",
        composer_name_latin="",
        work_title="第五交响曲",
        work_title_latin="",
        catalogue="",
        performance_date_text="1922",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="柴可夫斯基 | 第五交响曲 | Albert Coates | - | 1922",
        raw_text="",
        existing_links=[],
        lead_names=["Albert Coates"],
        ensemble_names=[],
    )

    true_hit = score_recording_match(
        "Albert Coates and The Symphony Orchestra - Symphony No. 5 in E minor, Op. 64 (Tchaikovsky) (1922)",
        "https://www.youtube.com/watch?v=true",
        draft,
    )
    false_hit = score_recording_match(
        "Albert Coates (1882-1953): Wagner with Davis, Radford & Whitehill  (London 1922-26)",
        "https://www.youtube.com/watch?v=false",
        draft,
    )

    assert true_hit >= 0.45
    assert false_hit < true_hit


def test_score_recording_match_penalizes_wrong_year_and_multi_work_compilations() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-4",
        title="Otto Klemperer - Philharmonia Orchestra - Symphony No. 5 - 1960",
        composer_name="贝多芬",
        composer_name_latin="Ludwig van Beethoven",
        work_title="第五交响曲",
        work_title_latin="Symphony No. 5 in C minor",
        catalogue="Op.67",
        performance_date_text="1960",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="贝多芬 | 第五交响曲 | Otto Klemperer | Philharmonia Orchestra | 1960",
        raw_text="",
        existing_links=[],
        lead_names=["Otto Klemperer"],
        ensemble_names=["Philharmonia Orchestra"],
    )

    exact_hit = score_recording_match(
        "Beethoven - Symphony No 5 in C minor, Op 67 - Klemperer Philharmonia Orchestra 1960",
        "https://www.youtube.com/watch?v=exact",
        draft,
    )
    wrong_year = score_recording_match(
        "Symphonies Nos. 5 and 7 [Philharmonia Orchestra / Otto Klemperer, 1955 Recorded]",
        "https://www.youtube.com/watch?v=wrong-year",
        draft,
    )

    assert exact_hit > wrong_year


def test_score_recording_match_penalizes_chamber_multi_sonata_compilations() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-spring-compile",
        title='Jean Fournier & Ginette Doyen - Spring Sonata',
        composer_name="贝多芬",
        composer_name_latin="Ludwig van Beethoven",
        work_title='第5号小提琴奏鸣曲“春天”',
        work_title_latin='Violin Sonata No.5, Op.24 "Spring"',
        catalogue="Op.24",
        performance_date_text="early '50s",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="贝多芬 | 第5号小提琴奏鸣曲“春天” | Jean Fournier | Ginette Doyen | early '50s",
        raw_text="",
        existing_links=[],
        primary_names=["让·富尼埃"],
        primary_names_latin=["Jean Fournier"],
        secondary_names=["吉内特·多延"],
        secondary_names_latin=["Ginette Doyen"],
        lead_names=["让·富尼埃", "吉内特·多延"],
        lead_names_latin=["Jean Fournier", "Ginette Doyen"],
    )

    exact_hit = score_recording_match(
        'Jean Fournier & Ginette Doyen play Beethoven "Spring" Sonata',
        "https://www.youtube.com/watch?v=exact-spring",
        draft,
    )
    compilation_hit = score_recording_match(
        "Beethoven Sonatas Violin & Piano Jean Fournier & Ginette Doyen Westminster WL-5176",
        "https://www.youtube.com/watch?v=compilation",
        draft,
    )
    multi_number_hit = score_recording_match(
        "Beethoven, Violin Sonata No 3,5, Fournier,Doyen",
        "https://www.youtube.com/watch?v=multi-number",
        draft,
    )

    assert exact_hit > compilation_hit
    assert exact_hit > multi_number_hit


def test_score_recording_match_penalizes_wrong_composer_when_other_signals_match() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-4b",
        title="Karl Bohm - VPO - Symphony No.7",
        composer_name="安东·布鲁克纳",
        composer_name_latin="Anton Bruckner",
        work_title="第七交响曲",
        work_title_latin="Symphony No.7 in E major, WAB 107",
        catalogue="WAB 107",
        performance_date_text="",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="安东·布鲁克纳 | 第七交响曲 | Karl Bohm | Vienna Philharmonic Orchestra | -",
        raw_text="",
        existing_links=[],
        lead_names=["Karl Böhm", "Karl Bohm"],
        lead_names_latin=["Karl Böhm", "Karl Bohm"],
        ensemble_names=["Vienna Philharmonic Orchestra", "Wiener Philharmoniker", "VPO"],
        ensemble_names_latin=["Vienna Philharmonic Orchestra", "Wiener Philharmoniker", "VPO"],
    )

    exact_hit = score_recording_match(
        "[High quality] Anton Bruckner - Symphony No. 7 in E major / Karl Böhm & Wiener Philharmoniker",
        "https://www.youtube.com/watch?v=jCkO-GbPLnk",
        draft,
    )
    wrong_composer = score_recording_match(
        "贝姆排练贝多芬第七交响曲 A rehearsal : Beethoven Symphony No.7",
        "https://www.youtube.com/watch?v=1MmYV8m6ZIQ",
        draft,
    )

    assert exact_hit > wrong_composer
    assert wrong_composer < 0.5


def test_score_recording_match_heavily_penalizes_real_world_wrong_composer_false_positive() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-4c",
        title="Karl Bohm - VPO - Symphony No.7",
        composer_name="安东·布鲁克纳",
        composer_name_latin="Anton Bruckner",
        work_title="第七交响曲",
        work_title_latin="Symphony No.7 in E major, WAB 107",
        catalogue="WAB 107",
        performance_date_text="",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="安东·布鲁克纳 | 第七交响曲 | Karl Bohm | Vienna Philharmonic Orchestra | -",
        raw_text="",
        existing_links=[],
        lead_names=["Karl Böhm", "Karl Bohm"],
        lead_names_latin=["Karl Böhm", "Karl Bohm"],
        ensemble_names=["Vienna Philharmonic Orchestra", "Wiener Philharmoniker", "VPO"],
        ensemble_names_latin=["Vienna Philharmonic Orchestra", "Wiener Philharmoniker", "VPO"],
    )

    exact_hit = score_recording_match(
        "[High quality] Anton Bruckner - Symphony No. 7 in E major / Karl Böhm & Wiener Philharmoniker",
        "https://www.youtube.com/watch?v=jCkO-GbPLnk",
        draft,
    )
    wrong_composer = score_recording_match(
        "贝姆排练贝多芬第七交响曲   A rehearsal : Beethoven Symphony No.7",
        "https://www.youtube.com/watch?v=1MmYV8m6ZIQ",
        draft,
    )

    assert exact_hit > wrong_composer
    assert wrong_composer <= 0.55


def test_score_recording_match_penalizes_single_movement_track() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-5",
        title="Otto Klemperer - Philharmonia Orchestra - Symphony No. 5 - 1960",
        composer_name="贝多芬",
        composer_name_latin="Ludwig van Beethoven",
        work_title="第五交响曲",
        work_title_latin="Symphony No. 5 in C minor",
        catalogue="Op.67",
        performance_date_text="1960",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="贝多芬 | 第五交响曲 | Otto Klemperer | Philharmonia Orchestra | 1960",
        raw_text="",
        existing_links=[],
        lead_names=["Otto Klemperer"],
        ensemble_names=["Philharmonia Orchestra"],
    )

    full_recording = score_recording_match(
        "Beethoven - Symphony No 5 in C minor, Op 67 - Klemperer",
        "https://www.youtube.com/watch?v=full",
        draft,
    )
    movement_only = score_recording_match(
        "Symphony No. 5 in C Minor, Op. 67: I. Allegro con brio (1960)",
        "https://www.youtube.com/watch?v=movement",
        draft,
    )

    assert full_recording > movement_only


def test_score_recording_match_penalizes_aria_extract_for_goldberg_variations() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-6",
        title="Glenn Gould - Goldberg Variations - 1955",
        composer_name="巴赫",
        composer_name_latin="Bach",
        work_title="哥德堡变奏曲",
        work_title_latin="Goldberg Variations",
        catalogue="BWV988",
        performance_date_text="1955",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="Goldberg Variations | Glenn Gould | - | 1955",
        raw_text="",
        existing_links=[],
        lead_names=["Glenn Gould"],
        ensemble_names=[],
    )

    full_recording = score_recording_match(
        "Glenn Gould plays BACH : The Goldberg Variations (1955)",
        "https://www.youtube.com/watch?v=full",
        draft,
    )
    aria_extract = score_recording_match(
        "Goldberg Variations, BWV 988: Aria",
        "https://www.youtube.com/watch?v=aria",
        draft,
    )

    assert full_recording > aria_extract


def test_score_recording_match_treats_bilingual_people_as_same_role_slots() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-role-aware",
        title="Annie Fischer & Kletzki",
        composer_name="舒曼",
        composer_name_latin="Robert Schumann",
        work_title="a小调钢琴协奏曲",
        work_title_latin="Piano Concerto, Op.54",
        catalogue="Op.54",
        performance_date_text="",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="舒曼 | a小调钢琴协奏曲 | Annie Fischer | Kletzki | Budapest Philharmonic Orchestra | -",
        raw_text="",
        existing_links=[],
        primary_names=["安妮·费舍尔"],
        primary_names_latin=["Annie Fischer"],
        secondary_names=["保罗·克列茨基"],
        secondary_names_latin=["Kletzki"],
        lead_names=["安妮·费舍尔", "保罗·克列茨基"],
        lead_names_latin=["Annie Fischer", "Kletzki"],
        ensemble_names=["布达佩斯爱乐乐团"],
        ensemble_names_latin=["Budapest Philharmonic Orchestra"],
    )

    exact_like = score_recording_match(
        "Schumann Piano Concerto Op.54 Annie Fischer Kletzki Budapest Philharmonic Orchestra",
        "https://www.youtube.com/watch?v=exact-like",
        draft,
    )
    wrong_collaborator = score_recording_match(
        "Schumann Piano Concerto Op.54 Annie Fischer & Giulini Budapest Philharmonic Orchestra",
        "https://www.youtube.com/watch?v=wrong-collaborator",
        draft,
    )

    assert exact_like > wrong_collaborator


def test_score_recording_match_keeps_exact_annie_schumann_above_wrong_concerto_version() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-annie-version-guard",
        title="Annie Fischer & Kletzki",
        composer_name="鑸掓浖",
        composer_name_latin="Robert Schumann",
        work_title="a小调钢琴协奏曲",
        work_title_latin="Piano Concerto, Op.54",
        catalogue="Op.54",
        performance_date_text="",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="Robert Schumann | Piano Concerto in A Minor, Op.54 | Annie Fischer | Kletzki | Budapest Philharmonic Orchestra | -",
        raw_text="Robert Schumann | Piano Concerto in A Minor, Op.54 | Annie Fischer | Kletzki | Budapest Philharmonic Orchestra | -",
        existing_links=[],
        primary_names=["Annie Fischer"],
        primary_names_latin=["Annie Fischer"],
        secondary_names=["Kletzki"],
        secondary_names_latin=["Kletzki"],
        lead_names=["Annie Fischer", "Kletzki"],
        lead_names_latin=["Annie Fischer", "Kletzki"],
        ensemble_names=["Budapest Philharmonic Orchestra"],
        ensemble_names_latin=["Budapest Philharmonic Orchestra"],
    )

    exact_like = score_recording_match(
        "Annie Fischer plays Schumann Piano Concerto Op.54 full performance",
        "https://www.bilibili.com/video/BV1TE411f7uh/",
        draft,
        duration_seconds=2017,
        uploader="艾斯跳票",
    )
    wrong_work = score_recording_match(
        "Beethoven c minor third piano concerto Annie Fischer Dorati",
        "https://www.bilibili.com/video/BV1ht411X7rC/",
        draft,
        duration_seconds=2140,
        uploader="古典搬运",
    )

    assert exact_like >= 0.6
    assert exact_like > wrong_work


def test_score_recording_match_prefers_complete_chamber_collaboration_over_single_name_hit() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-spring-role-aware",
        title="Jean Fournier & Ginette Doyen",
        composer_name="贝多芬",
        composer_name_latin="Ludwig van Beethoven",
        work_title="第5号小提琴奏鸣曲“春天”",
        work_title_latin="Violin Sonata No.5, Op.24",
        catalogue="Op.24",
        performance_date_text="",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="贝多芬 | 第5号小提琴奏鸣曲“春天” | Jean Fournier | Ginette Doyen | -",
        raw_text="",
        existing_links=[],
        primary_names=["让·富尼埃"],
        primary_names_latin=["Jean Fournier"],
        secondary_names=["吉内特·多延"],
        secondary_names_latin=["Ginette Doyen"],
        lead_names=["让·富尼埃", "吉内特·多延"],
        lead_names_latin=["Jean Fournier", "Ginette Doyen"],
        ensemble_names=[],
        ensemble_names_latin=[],
    )

    complete_duo = score_recording_match(
        'Jean Fournier & Ginette Doyen play Beethoven "Spring" Sonata',
        "https://www.youtube.com/watch?v=complete",
        draft,
    )
    single_name = score_recording_match(
        "Beethoven, Violin Sonata No 5, Jean Fournier",
        "https://www.youtube.com/watch?v=single",
        draft,
    )

    assert complete_duo > single_name


def test_score_recording_match_treats_complete_sonata_tracklist_as_full_work() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-spring-tracklist",
        title="让·富尼埃&吉内特·多延",
        composer_name="贝多芬",
        composer_name_latin="Ludwig van Beethoven",
        work_title="第5号小提琴奏鸣曲, “春天”",
        work_title_latin='Violin Sonata No.5, Op.24 "Spring"',
        catalogue="Op.24",
        performance_date_text="",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="",
        raw_text="",
        existing_links=[],
        primary_names=["让·富尼埃"],
        primary_names_latin=["Jean Fournier"],
        secondary_names=["吉内特·多延"],
        secondary_names_latin=[],
        lead_names=["让·富尼埃", "吉内特·多延"],
        lead_names_latin=["Jean Fournier"],
        ensemble_names=[],
        ensemble_names_latin=[],
    )

    tracklisted_full = score_recording_match(
        'Jean Fournier & Ginette Doyen play Beethoven "Spring" Sonata '
        'Violin Sonata No. 5 in F major Opus 24, "Frühlingssonate"'
        '1. Allegro2. Adagio molto espressivo (7:27)3. Scherzo: Allegro molto '
        '(14:22)4. Rondo: Allegro ma non...',
        "https://www.youtube.com/watch?v=n0bji6PXYso",
        draft,
    )
    single_name = score_recording_match(
        "Beethoven, Violin Sonata No 5, Jean Fournier YouTube でお気に入りの動画や音楽を楽しみ、"
        "オリジナルのコンテンツをアップロードして友だちや家族、世界中の人たちと共有しましょう。",
        "https://www.youtube.com/watch?v=puC1aT9nRzI",
        draft,
    )

    assert tracklisted_full > single_name


def test_score_recording_match_keeps_sparse_cjk_duo_tracklist_above_final_threshold() -> None:
    draft = DraftRecordingEntry(
        item_id="recording-spring-sparse-duo",
        title="让·富尼埃 - 吉内特·多延 - early '50s",
        composer_name="路德维希·凡·贝多芬",
        composer_name_latin="Ludwig van Beethoven",
        work_title="第5号小提琴奏鸣曲, “春天”",
        work_title_latin='Violin Sonata No.5, Op.24 "Spring"',
        catalogue="Op.24",
        performance_date_text="early '50s",
        venue_text="",
        album_title="",
        label="",
        release_date="",
        notes="",
        source_line="路德维希·凡·贝多芬 | 第5号小提琴奏鸣曲, “春天” | Jean Fournier | -",
        raw_text="路德维希·凡·贝多芬 | 第5号小提琴奏鸣曲, “春天” | Jean Fournier | - | 让·富尼埃 - 吉内特·多延 - early '50s",
        existing_links=[],
        primary_names=["让·富尼埃"],
        primary_names_latin=["Jean Fournier"],
        secondary_names=["吉内特·多延"],
        secondary_names_latin=[],
        lead_names=["让·富尼埃", "吉内特·多延"],
        lead_names_latin=["Jean Fournier"],
        ensemble_names=[],
        ensemble_names_latin=[],
    )

    tracklisted_full = score_recording_match(
        'Jean Fournier & Ginette Doyen play Beethoven "Spring" Sonata '
        'Violin Sonata No. 5 in F major Opus 24, "Frühlingssonate"'
        '1. Allegro2. Adagio molto espressivo (7:27)3. Scherzo: Allegro molto '
        '(14:22)4. Rondo: Allegro ma non...',
        "https://www.youtube.com/watch?v=n0bji6PXYso",
        draft,
    )
    single_name = score_recording_match(
        "Beethoven, Violin Sonata No 5, Jean Fournier",
        "https://www.youtube.com/watch?v=puC1aT9nRzI",
        draft,
    )

    assert tracklisted_full >= 0.65
    assert tracklisted_full > single_name
