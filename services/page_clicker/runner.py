from __future__ import annotations

from typing import Any

from core.browser_runtime import ensure_browser_display_available

from .models import ClickResult, PageClickConfig


def perform_click_flow(page: Any, config: PageClickConfig) -> ClickResult:
    page.goto(config.url, wait_until="domcontentloaded", timeout=config.timeout_ms)
    if config.wait_for_selector:
        page.wait_for_selector(config.wait_for_selector, timeout=config.timeout_ms)

    locator = page.locator(config.click_selector).first
    clicked_text = None
    try:
        clicked_value = locator.inner_text(timeout=config.timeout_ms).strip()
        clicked_text = clicked_value or None
    except Exception:
        clicked_text = None
    locator.click(timeout=config.timeout_ms)

    if config.screenshot_path:
        config.screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(config.screenshot_path), full_page=True)

    return ClickResult(
        success=True,
        url=config.url,
        click_selector=config.click_selector,
        final_url=page.url,
        title=page.title(),
        clicked_text=clicked_text,
        screenshot_path=config.screenshot_path,
    )


def run_click_flow(config: PageClickConfig) -> ClickResult:
    headless = True if config.headless is None else config.headless
    ensure_browser_display_available(headless)

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            context = browser.new_context()
            page = context.new_page()
            try:
                return perform_click_flow(page, config)
            finally:
                context.close()
                browser.close()
    except Exception as exc:
        error_type = exc.__class__.__name__
        return ClickResult(
            success=False,
            url=config.url,
            click_selector=config.click_selector,
            screenshot_path=config.screenshot_path,
            error=f"{error_type}: {exc}",
        )
