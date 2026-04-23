from __future__ import annotations

from typing import Any

from core.alias_pool.browser_runtime import BrowserRuntimeSessionState, BrowserRuntimeStep
from core.browser_runtime import ensure_browser_display_available, resolve_browser_headless


class BrowserFallbackRuntime:
    def __init__(
        self,
        *,
        page=None,
        context=None,
        browser=None,
        owns_session: bool = True,
        headless: bool = True,
    ):
        self._page = page
        self._context = context
        self._browser = browser
        self._pw = None
        self._owns_session = owns_session
        if self._page is None or self._context is None or self._browser is None:
            from playwright.sync_api import sync_playwright

            resolved_headless, _ = resolve_browser_headless(headless)
            ensure_browser_display_available(resolved_headless)
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=resolved_headless)
            self._context = self._browser.new_context()
            self._page = self._context.new_page()

    def _require_page(self) -> Any:
        if self._page is None:
            raise RuntimeError("playwright page unavailable")
        return self._page

    def _require_context(self) -> Any:
        if self._context is None:
            raise RuntimeError("playwright context unavailable")
        return self._context

    def open(self, url: str) -> BrowserRuntimeStep:
        page = self._require_page()
        page.goto(url, wait_until="domcontentloaded")
        return BrowserRuntimeStep(code="open", label="打开页面", status="completed", detail=url)

    def restore(self, state: BrowserRuntimeSessionState) -> None:
        page = self._require_page()
        context = self._require_context()
        target_url = str(state.current_url or self.current_url() or "about:blank")
        page.goto(target_url, wait_until="domcontentloaded")
        if state.cookies:
            context.add_cookies(list(state.cookies))

    def snapshot(self) -> BrowserRuntimeSessionState:
        return BrowserRuntimeSessionState(
            current_url=self.current_url(),
            cookies=self.snapshot_cookies(),
        )

    def fill(self, selector: str, value: str) -> None:
        self._require_page().locator(selector).fill(value)

    def fill_role(self, role: str, name: str, value: str, *, exact: bool = False) -> None:
        kwargs: dict[str, Any] = {"name": name}
        if exact:
            kwargs["exact"] = True
        self._require_page().get_by_role(role, **kwargs).fill(value)

    def click(self, selector: str) -> None:
        self._require_page().locator(selector).click()

    def click_role(self, role: str, name: str) -> None:
        self._require_page().get_by_role(role, name=name).click()

    def current_url(self) -> str:
        return str(self._require_page().url or "")

    def content(self) -> str:
        return str(self._require_page().content() or "")

    def wait_for_url(self, pattern: str) -> None:
        self._require_page().wait_for_url(pattern)

    def wait_for_text(self, text: str) -> None:
        self._require_page().get_by_text(text).wait_for(state="visible")

    def snapshot_cookies(self) -> list[dict[str, Any]]:
        raw_cookies = self._require_context().cookies()
        if raw_cookies is None:
            return []
        try:
            iterator = iter(raw_cookies)
        except TypeError:
            return []

        cookies: list[dict[str, Any]] = []
        for item in iterator:
            if isinstance(item, dict):
                cookies.append(dict(item))
                continue
            name = str(getattr(item, "name", "") or "")
            value = str(getattr(item, "value", "") or "")
            if name:
                cookies.append({"name": name, "value": value})
        return cookies

    def restore_cookies(self, cookies: list[dict[str, Any]]) -> None:
        if cookies:
            self._require_context().add_cookies(list(cookies))

    def close(self) -> None:
        if self._owns_session and self._browser is not None:
            self._browser.close()
        if self._owns_session and self._pw is not None:
            self._pw.stop()
