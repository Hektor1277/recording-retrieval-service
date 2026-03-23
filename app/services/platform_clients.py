from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from app.services.platform_search_config import PlatformSearchConfig


@dataclass(slots=True)
class ApiSearchResult:
    endpoint_url: str
    links: list[str]


WBI_MIXIN_KEY_INDEX = [
    46,
    47,
    18,
    2,
    53,
    8,
    23,
    32,
    15,
    50,
    10,
    31,
    58,
    3,
    45,
    35,
    27,
    43,
    5,
    49,
    33,
    9,
    42,
    19,
    29,
    28,
    14,
    39,
    12,
    38,
    41,
    13,
    37,
    48,
    7,
    16,
    24,
    55,
    40,
    61,
    26,
    17,
    0,
    1,
    60,
    51,
    30,
    4,
    22,
    25,
    54,
    21,
    56,
    59,
    6,
    63,
    57,
    62,
    11,
    36,
    20,
    34,
    44,
    52,
]


class PlatformSearchClients:
    def __init__(self, config: PlatformSearchConfig, client: httpx.AsyncClient) -> None:
        self._config = config
        self._client = client
        self._bilibili_wbi_keys: tuple[str, str] | None = None
        self._bilibili_wbi_key_time = 0.0
        self._bilibili_seeded = False

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
        await self._seed_bilibili_session()
        endpoint = "https://api.bilibili.com/x/web-interface/wbi/search/type"
        img_key, sub_key = await self._load_bilibili_wbi_keys()
        mixin_key = self._derive_bilibili_mixin_key(img_key, sub_key)
        params = self._sign_bilibili_wbi_params(
            {
                "search_type": "video",
                "keyword": query,
                "page": 1,
                "page_size": min(max(1, result_limit), 20),
                "order": "totalrank",
            },
            mixin_key,
        )
        response = await self._client.get(
            endpoint,
            params=params,
            headers=self._bilibili_headers(),
        )
        response.raise_for_status()
        payload = response.json()
        code = int(payload.get("code") or 0)
        if code != 0:
            message = str(payload.get("message") or payload.get("msg") or "unknown error").strip()
            raise RuntimeError(f"Bilibili WBI search failed with code {code}: {message}")
        links = []
        for item in (((payload.get("data") or {}).get("result") or [])[:result_limit]):
            url = str(item.get("arcurl") or "").strip()
            if url:
                links.append(url)
        return ApiSearchResult(endpoint_url=str(response.request.url), links=links)

    def _bilibili_headers(self) -> dict[str, str]:
        headers = {
            "referer": self._config.bilibili.referer or "https://www.bilibili.com",
            "user-agent": self._config.bilibili.user_agent or "Mozilla/5.0",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        if self._config.bilibili.cookie:
            headers["cookie"] = self._config.bilibili.cookie
        return headers

    async def _seed_bilibili_session(self) -> None:
        if self._bilibili_seeded:
            return
        self._bilibili_seeded = True
        response = await self._client.get("https://www.bilibili.com", headers=self._bilibili_headers())
        response.raise_for_status()

    async def _load_bilibili_wbi_keys(self) -> tuple[str, str]:
        if self._bilibili_wbi_keys and time.time() - self._bilibili_wbi_key_time < 600:
            return self._bilibili_wbi_keys
        response = await self._client.get(
            "https://api.bilibili.com/x/web-interface/nav",
            headers=self._bilibili_headers(),
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") or {}
        wbi_img = data.get("wbi_img") or {}
        img_url = str(wbi_img.get("img_url") or "").strip()
        sub_url = str(wbi_img.get("sub_url") or "").strip()
        img_key = self._extract_bilibili_wbi_key(img_url)
        sub_key = self._extract_bilibili_wbi_key(sub_url)
        if not img_key or not sub_key:
            raise RuntimeError("Bilibili nav response missing wbi keys")
        self._bilibili_wbi_keys = (img_key, sub_key)
        self._bilibili_wbi_key_time = time.time()
        return self._bilibili_wbi_keys

    @staticmethod
    def _extract_bilibili_wbi_key(url: str) -> str:
        match = re.search(r"/([^/]+)\.[a-zA-Z0-9]+(?:\?|$)", url)
        return match.group(1) if match else ""

    @staticmethod
    def _derive_bilibili_mixin_key(img_key: str, sub_key: str) -> str:
        joined = img_key + sub_key
        return "".join(joined[index] for index in WBI_MIXIN_KEY_INDEX if index < len(joined))[:32]

    @staticmethod
    def _sign_bilibili_wbi_params(params: dict[str, object], mixin_key: str) -> dict[str, object]:
        signed: dict[str, object] = {
            key: re.sub(r"[!'()*]", "", str(value))
            for key, value in params.items()
            if value is not None
        }
        signed["wts"] = int(time.time())
        canonical = "&".join(
            f"{quote(str(key), safe='-_.~')}={quote(str(signed[key]), safe='-_.~')}"
            for key in sorted(signed)
        )
        signed["w_rid"] = hashlib.md5(f"{canonical}{mixin_key}".encode("utf-8")).hexdigest()
        return signed
