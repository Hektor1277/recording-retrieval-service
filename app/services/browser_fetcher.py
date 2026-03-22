from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from typing import Any


class BrowserFetchUnavailable(RuntimeError):
    pass


@dataclass(slots=True)
class BrowserPageSnapshot:
    title: str
    description: str
    body_text: str
    image_url: str
    uploader: str
    duration_seconds: int
    view_count: int


class PlaywrightBrowserFetcher:
    def __init__(self, max_concurrency: int = 2) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def fetch_page(self, url: str, timeout_seconds: float | None = None) -> dict[str, str]:
        async with self._semaphore:
            return await asyncio.wait_for(self._fetch_page_inner(url), timeout=timeout_seconds or 8.0)

    async def fetch_links(
        self,
        url: str,
        *,
        url_patterns: list[str] | None = None,
        timeout_seconds: float | None = None,
    ) -> list[str]:
        async with self._semaphore:
            return await asyncio.wait_for(
                self._fetch_links_inner(url, url_patterns or []),
                timeout=timeout_seconds or 8.0,
            )

    async def _fetch_page_inner(self, url: str) -> dict[str, str]:
        try:
            from playwright.async_api import Error as PlaywrightError
            from playwright.async_api import async_playwright
        except ImportError as error:  # pragma: no cover - environment dependent
            raise BrowserFetchUnavailable("playwright is not installed") from error

        try:
            async with async_playwright() as playwright:
                launch_options: dict[str, Any] = {"headless": True}
                if sys.platform == "win32":
                    launch_options["channel"] = "msedge"
                browser = await playwright.chromium.launch(**launch_options)
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=8000)
                await page.wait_for_timeout(300)

                snapshot = BrowserPageSnapshot(
                    **(
                        await page.evaluate(
                            """() => {
                                const host = window.location.hostname || '';
                                const fromMeta = () => (
                                  document.querySelector('meta[property="og:description"]')?.content
                                  || document.querySelector('meta[name="description"]')?.content
                                  || ''
                                ).trim();
                                const imageFromMeta = () => {
                                  const fromMeta = document.querySelector('meta[property="og:image"]')?.content
                                    || document.querySelector('meta[name="twitter:image"]')?.content;
                                  if (fromMeta) {
                                    return fromMeta.trim();
                                  }
                                  const image = Array.from(document.images || [])
                                    .find((node) => node?.src && node.width >= 240 && node.height >= 240);
                                  return image?.src?.trim() || '';
                                };
                                if (host.includes('bilibili.com')) {
                                  const video = window.__INITIAL_STATE__?.videoData || {};
                                  const owner = video.owner?.name || '';
                                  const description = (video.desc || fromMeta()).trim();
                                  const bodyParts = [
                                    video.title || document.title || '',
                                    description,
                                    owner,
                                    Array.isArray(video.pages) ? video.pages.map((item) => item?.part || '').join(' ') : '',
                                  ];
                                  return {
                                    title: String(video.title || document.title || '').trim(),
                                    description,
                                    body_text: bodyParts.filter(Boolean).join(' ').slice(0, 4000).trim(),
                                    image_url: String(video.pic || imageFromMeta()).trim(),
                                    uploader: String(owner || '').trim(),
                                    duration_seconds: Number(video.duration || 0) || 0,
                                    view_count: Number(video.stat?.view || 0) || 0,
                                  };
                                }
                                const text = document.body?.innerText || '';
                                return {
                                  title: String(document.title || '').trim(),
                                  description: fromMeta(),
                                  body_text: text.slice(0, 4000).trim(),
                                  image_url: imageFromMeta(),
                                  uploader: '',
                                  duration_seconds: 0,
                                  view_count: 0,
                                };
                            }""",
                        )
                    ),
                )
                await browser.close()
                return {
                    "title": snapshot.title,
                    "description": snapshot.description,
                    "bodyText": snapshot.body_text,
                    "imageUrl": snapshot.image_url,
                    "uploader": snapshot.uploader,
                    "durationSeconds": snapshot.duration_seconds,
                    "viewCount": snapshot.view_count,
                }
        except PlaywrightError as error:  # pragma: no cover - environment dependent
            raise BrowserFetchUnavailable(str(error)) from error

    async def _fetch_links_inner(self, url: str, url_patterns: list[str]) -> list[str]:
        try:
            from playwright.async_api import Error as PlaywrightError
            from playwright.async_api import async_playwright
        except ImportError as error:  # pragma: no cover - environment dependent
            raise BrowserFetchUnavailable("playwright is not installed") from error

        try:
            async with async_playwright() as playwright:
                launch_options: dict[str, Any] = {"headless": True}
                if sys.platform == "win32":
                    launch_options["channel"] = "msedge"
                browser = await playwright.chromium.launch(**launch_options)
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=8000)
                await page.wait_for_timeout(800)

                links = await page.evaluate(
                    """(patterns) => {
                        const regexes = (patterns || []).map((pattern) => new RegExp(pattern, 'i'));
                        const values = Array.from(document.querySelectorAll('a[href]'))
                          .map((node) => {
                            try {
                              return new URL(node.getAttribute('href') || '', window.location.href).href;
                            } catch (error) {
                              return '';
                            }
                          })
                          .filter((href) => /^https?:/i.test(href));
                        const filtered = regexes.length
                          ? values.filter((href) => regexes.some((pattern) => pattern.test(href)))
                          : values;
                        return Array.from(new Set(filtered));
                    }""",
                    url_patterns,
                )
                await browser.close()
                return [str(value).strip() for value in links or [] if str(value or "").strip()]
        except PlaywrightError as error:  # pragma: no cover - environment dependent
            raise BrowserFetchUnavailable(str(error)) from error
