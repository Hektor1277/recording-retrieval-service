from __future__ import annotations

import atexit
import asyncio
import sys
import weakref
from contextlib import asynccontextmanager
from contextlib import suppress
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class BrowserFetchUnavailable(RuntimeError):
    pass


@dataclass(slots=True)
class BrowserPageSnapshot:
    title: str
    description: str
    body_text: str
    image_url: str
    uploader: str
    bvid: str
    duration_seconds: int
    view_count: int


@dataclass(slots=True)
class _LoopBrowserState:
    browser: Any = None
    playwright: Any = None
    playwright_manager: Any = None
    shared_bilibili_context: Any = None
    browser_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    context_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class PlaywrightBrowserFetcher:
    def __init__(
        self,
        max_concurrency: int = 2,
        *,
        bilibili_cookie: str = "",
        bilibili_user_agent: str = "",
        bilibili_referer: str = "https://www.bilibili.com",
        bilibili_storage_state_path: str = "",
    ) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._bilibili_cookie = bilibili_cookie.strip()
        self._bilibili_user_agent = bilibili_user_agent.strip()
        self._bilibili_referer = bilibili_referer.strip() or "https://www.bilibili.com"
        self._bilibili_storage_state_path = bilibili_storage_state_path.strip()
        self._loop_states: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _LoopBrowserState] = weakref.WeakKeyDictionary()
        self._atexit_registered = False
        atexit.register(self._aclose_sync)
        self._atexit_registered = True

    async def fetch_page(self, url: str, timeout_seconds: float | None = None) -> dict[str, str]:
        async with self._semaphore:
            return await self._run_with_timeout(self._fetch_page_inner(url), timeout_seconds or 8.0)

    async def fetch_links(
        self,
        url: str,
        *,
        url_patterns: list[str] | None = None,
        timeout_seconds: float | None = None,
    ) -> list[str]:
        async with self._semaphore:
            return await self._run_with_timeout(
                self._fetch_links_inner(url, url_patterns or []),
                timeout_seconds or 8.0,
            )

    async def _run_with_timeout(self, coroutine: Any, timeout_seconds: float):
        task = asyncio.create_task(coroutine)
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=timeout_seconds)
        except asyncio.TimeoutError as error:
            task.cancel()
            task.add_done_callback(_silence_task_exception)
            raise TimeoutError("browser fetch timed out") from error

    async def _fetch_page_inner(self, url: str) -> dict[str, str]:
        try:
            from playwright.async_api import Error as PlaywrightError
        except ImportError as error:  # pragma: no cover - environment dependent
            raise BrowserFetchUnavailable("playwright is not installed") from error

        try:
            async with self._open_page(url) as page:
                await self._goto_with_retry(page, url, PlaywrightError)
                await self._wait_for_page_snapshot(page, url)

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
                                    bvid: String(video.bvid || '').trim(),
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
                                  bvid: '',
                                  duration_seconds: 0,
                                  view_count: 0,
                                };
                            }""",
                        )
                    ),
                )
                return {
                    "title": snapshot.title,
                    "description": snapshot.description,
                    "bodyText": snapshot.body_text,
                    "imageUrl": snapshot.image_url,
                    "uploader": snapshot.uploader,
                    "bvid": snapshot.bvid,
                    "durationSeconds": snapshot.duration_seconds,
                    "viewCount": snapshot.view_count,
                }
        except PlaywrightError as error:  # pragma: no cover - environment dependent
            raise BrowserFetchUnavailable(str(error)) from error

    async def _fetch_links_inner(self, url: str, url_patterns: list[str]) -> list[str]:
        try:
            from playwright.async_api import Error as PlaywrightError
        except ImportError as error:  # pragma: no cover - environment dependent
            raise BrowserFetchUnavailable("playwright is not installed") from error

        try:
            async with self._open_page(url) as page:
                await self._goto_with_retry(page, url, PlaywrightError)
                await self._wait_for_link_results(page, url)

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
                return [str(value).strip() for value in links or [] if str(value or "").strip()]
        except PlaywrightError as error:  # pragma: no cover - environment dependent
            raise BrowserFetchUnavailable(str(error)) from error

    async def aclose(self) -> None:
        for state in list(self._loop_states.values()):
            async with state.context_lock:
                await self._safe_close(state.shared_bilibili_context)
                state.shared_bilibili_context = None
            async with state.browser_lock:
                await self._safe_close(state.browser)
                state.browser = None
                with suppress(Exception):
                    if state.playwright is not None:
                        await state.playwright.stop()
                state.playwright_manager = None
                state.playwright = None
        self._loop_states = weakref.WeakKeyDictionary()
        if self._atexit_registered:
            with suppress(Exception):
                atexit.unregister(self._aclose_sync)
            self._atexit_registered = False

    def _aclose_sync(self) -> None:
        if all(
            state.browser is None and state.shared_bilibili_context is None and state.playwright_manager is None
            for state in self._loop_states.values()
        ):
            return
        with suppress(BaseException):
            asyncio.run(self.aclose())

    def _get_loop_state(self) -> _LoopBrowserState:
        loop = asyncio.get_running_loop()
        state = self._loop_states.get(loop)
        if state is None:
            state = _LoopBrowserState()
            self._loop_states[loop] = state
        return state

    async def _get_browser(self) -> Any:
        state = self._get_loop_state()
        if state.browser is not None:
            return state.browser
        async with state.browser_lock:
            if state.browser is not None:
                return state.browser
            try:
                from playwright.async_api import async_playwright
            except ImportError as error:  # pragma: no cover - environment dependent
                raise BrowserFetchUnavailable("playwright is not installed") from error
            state.playwright_manager = async_playwright()
            state.playwright = await state.playwright_manager.start()
            launch_options: dict[str, Any] = {"headless": True}
            if sys.platform == "win32":
                launch_options["channel"] = "msedge"
            state.browser = await state.playwright.chromium.launch(**launch_options)
            return state.browser

    async def _get_context(self, url: str) -> tuple[Any, bool]:
        browser = await self._get_browser()
        if self._should_reuse_shared_context(url):
            state = self._get_loop_state()
            async with state.context_lock:
                if state.shared_bilibili_context is None:
                    state.shared_bilibili_context = await browser.new_context(**self._context_options_for_url(url))
                return state.shared_bilibili_context, True
        return await browser.new_context(**self._context_options_for_url(url)), False

    @asynccontextmanager
    async def _open_page(self, url: str):
        context, shared_context = await self._get_context(url)
        page = None
        try:
            page = await context.new_page()
            yield page
        finally:
            await self._safe_close(page)
            if not shared_context:
                await self._safe_close(context)

    def _context_options_for_url(self, url: str) -> dict[str, Any]:
        host = urlparse(url).netloc.lower()
        options: dict[str, Any] = {
            "viewport": {"width": 1440, "height": 960},
        }
        if "bilibili.com" not in host and "b23.tv" not in host:
            return options

        headers = {
            "Referer": self._bilibili_referer,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        if self._bilibili_cookie:
            headers["Cookie"] = self._bilibili_cookie
        options["extra_http_headers"] = headers
        options["locale"] = "zh-CN"
        if self._bilibili_user_agent:
            options["user_agent"] = self._bilibili_user_agent
        if self._bilibili_storage_state_path:
            storage_state = Path(self._bilibili_storage_state_path)
            if storage_state.is_file():
                options["storage_state"] = str(storage_state)
        return options

    def _should_reuse_shared_context(self, url: str) -> bool:
        host = urlparse(url).netloc.lower()
        return "bilibili.com" in host or "b23.tv" in host

    async def _wait_for_page_snapshot(self, page: Any, url: str) -> None:
        host = urlparse(url).netloc.lower()
        if "bilibili.com" in host:
            with suppress(Exception):
                await page.wait_for_function(
                    "() => Boolean(window.__INITIAL_STATE__ && window.__INITIAL_STATE__.videoData)",
                    timeout=4000,
                )
            await page.wait_for_timeout(800)
            return
        await page.wait_for_timeout(300)

    async def _wait_for_link_results(self, page: Any, url: str) -> None:
        host = urlparse(url).netloc.lower()
        if "search.bilibili.com" in host:
            with suppress(Exception):
                await page.wait_for_function(
                    """() => Array.from(document.querySelectorAll('a[href]')).some((node) => {
                        const href = node?.href || '';
                        return /\\/video\\/(?:BV[0-9A-Za-z]+|av\\d+)/i.test(href);
                    })""",
                    timeout=4500,
                )
            await page.wait_for_timeout(700)
            return
        await page.wait_for_timeout(800)

    async def _goto_with_retry(self, page: Any, url: str, playwright_error: type[Exception]) -> None:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=12000)
            return
        except playwright_error as error:
            if not should_retry_navigation_error(str(error), url):
                raise
        await page.wait_for_timeout(450)
        await page.goto(url, wait_until="domcontentloaded", timeout=12000)

    async def _safe_close(self, handle: Any) -> None:
        with suppress(Exception):
            if handle is not None:
                await handle.close()


def _silence_task_exception(task: asyncio.Task) -> None:
    with suppress(BaseException):
        task.exception()


def should_retry_navigation_error(message: str, url: str) -> bool:
    host = urlparse(url).netloc.lower()
    if "bilibili.com" not in host and "b23.tv" not in host:
        return False
    lowered = (message or "").lower()
    return "err_aborted" in lowered or "frame was detached" in lowered
