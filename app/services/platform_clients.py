from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.services.platform_search_config import PlatformSearchConfig


@dataclass(slots=True)
class ApiSearchResult:
    endpoint_url: str
    links: list[str]


class PlatformSearchClients:
    def __init__(self, config: PlatformSearchConfig, client: httpx.AsyncClient) -> None:
        self._config = config
        self._client = client

    async def search_youtube(self, query: str, *, result_limit: int) -> ApiSearchResult:
        endpoint = "https://www.googleapis.com/youtube/v3/search"
        response = await self._client.get(
            endpoint,
            params={
                "part": "snippet",
                "type": "video",
                "q": query,
                "key": self._config.youtube.api_key,
                "maxResults": min(max(1, result_limit), self._config.youtube.max_results),
                "regionCode": self._config.youtube.region_code,
            },
        )
        response.raise_for_status()
        payload = response.json()
        links = []
        for item in payload.get("items", []):
            video_id = str(((item.get("id") or {}).get("videoId") or "")).strip()
            if video_id:
                links.append(f"https://www.youtube.com/watch?v={video_id}")
        return ApiSearchResult(endpoint_url=str(response.request.url), links=links)

    async def search_apple_music(self, query: str, *, result_limit: int) -> ApiSearchResult:
        endpoint = f"https://api.music.apple.com/v1/catalog/{self._config.apple_music.storefront}/search"
        response = await self._client.get(
            endpoint,
            params={
                "term": query,
                "types": "songs,albums",
                "limit": min(max(1, result_limit), 25),
            },
            headers={
                "authorization": f"Bearer {self._config.apple_music.developer_token}",
                "origin": "https://music.apple.com",
            },
        )
        response.raise_for_status()
        payload = response.json()
        links: list[str] = []
        for bucket_name in ("songs", "albums", "playlists"):
            bucket = (((payload.get("results") or {}).get(bucket_name) or {}).get("data") or [])
            for item in bucket:
                url = str(((item.get("attributes") or {}).get("url") or "")).strip()
                if url:
                    links.append(url)
        return ApiSearchResult(endpoint_url=str(response.request.url), links=links)

    async def search_apple_music_public(self, query: str, *, result_limit: int) -> ApiSearchResult:
        endpoint = "https://itunes.apple.com/search"
        response = await self._client.get(
            endpoint,
            params={
                "term": query,
                "media": "music",
                "limit": min(max(1, result_limit), 25),
            },
        )
        response.raise_for_status()
        payload = response.json()
        links: list[str] = []
        for item in payload.get("results", []):
            for key in ("trackViewUrl", "collectionViewUrl", "artistViewUrl"):
                url = str(item.get(key) or "").strip()
                if url:
                    links.append(url)
                    break
        return ApiSearchResult(endpoint_url=str(response.request.url), links=links)

    async def search_bilibili(self, query: str, *, result_limit: int) -> ApiSearchResult:
        endpoint = "https://api.bilibili.com/x/web-interface/search/type"
        headers = {
            "referer": self._config.bilibili.referer or "https://www.bilibili.com",
        }
        if self._config.bilibili.cookie:
            headers["cookie"] = self._config.bilibili.cookie
        headers["user-agent"] = self._config.bilibili.user_agent or "Mozilla/5.0"
        response = await self._client.get(
            endpoint,
            params={
                "search_type": "video",
                "keyword": query,
                "page": 1,
            },
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json()
        links = []
        for item in (((payload.get("data") or {}).get("result") or [])[:result_limit]):
            url = str(item.get("arcurl") or "").strip()
            if url:
                links.append(url)
        return ApiSearchResult(endpoint_url=str(response.request.url), links=links)
