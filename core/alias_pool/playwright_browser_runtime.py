from __future__ import annotations

import json
from typing import Any, Callable

from core.alias_pool.browser_runtime import BrowserRuntimeSessionState, BrowserRuntimeStep


class PlaywrightAliasBrowserRuntime:
    def __init__(self, *, site_url: str, executor_builder: Callable[[], Any] | None):
        if not callable(executor_builder):
            raise ValueError("executor_builder is required")
        self.site_url = site_url
        self._executor = executor_builder()
        self._page = getattr(self._executor, "page", None) or getattr(self._executor, "_page", None)
        self._context = getattr(self._executor, "context", None) or getattr(self._executor, "_context", None)

    def _require_page(self):
        if self._page is None:
            raise RuntimeError("playwright page unavailable")
        return self._page

    def _require_context(self):
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
        target_url = str(state.current_url or self.site_url or "about:blank")
        page.goto(target_url, wait_until="domcontentloaded")
        if state.cookies:
            context.add_cookies(list(state.cookies))
        if state.local_storage:
            page.evaluate(
                """
                (items) => {
                  Object.entries(items || {}).forEach(([key, value]) => window.localStorage.setItem(key, value));
                }
                """,
                dict(state.local_storage),
            )
        if state.session_storage:
            page.evaluate(
                """
                (items) => {
                  Object.entries(items || {}).forEach(([key, value]) => window.sessionStorage.setItem(key, value));
                }
                """,
                dict(state.session_storage),
            )

    def snapshot(self) -> BrowserRuntimeSessionState:
        page = self._require_page()
        context = self._require_context()
        local_storage = json.loads(page.evaluate("() => JSON.stringify(window.localStorage)"))
        session_storage = json.loads(page.evaluate("() => JSON.stringify(window.sessionStorage)"))
        return BrowserRuntimeSessionState(
            current_url=str(getattr(page, "url", "") or ""),
            cookies=list(context.cookies()),
            local_storage=dict(local_storage or {}),
            session_storage=dict(session_storage or {}),
        )

    def current_url(self) -> str:
        return str(getattr(self._require_page(), "url", "") or "")

    def fill(self, selector: str, value: str) -> None:
        self._require_page().locator(selector).fill(value)

    def click(self, selector: str) -> None:
        self._require_page().locator(selector).click()

    def click_role(self, role: str, name: str) -> None:
        self._require_page().get_by_role(role, name=name).click()

    def select_option(self, selector: str, value: str) -> None:
        self._require_page().locator(selector).select_option(value)

    def wait_for_text(self, text: str) -> None:
        self._require_page().get_by_text(text).wait_for(state="visible")

    def text_content(self, selector: str) -> str:
        first_locator = self._require_page().locator(selector).first
        return str(first_locator.text_content() or "")

    def wait_for_url(self, pattern: str) -> None:
        self._require_page().wait_for_url(pattern, wait_until="commit")

    def wait_for_selector(self, selector: str) -> None:
        self._require_page().wait_for_selector(selector, state="attached")

    def content(self) -> str:
        return str(self._require_page().content() or "")

    def close(self) -> None:
        close = getattr(self._executor, "close", None)
        if callable(close):
            close()
