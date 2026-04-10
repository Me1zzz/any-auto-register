from __future__ import annotations

import random
import time
from typing import Any

from core.browser_runtime import ensure_browser_display_available

from ..models import ClickResult, OptionalDependencyMissingError, PageClickConfig, TargetSpec
from .base import PageClickBackend


def _sleep_ms(delay_ms: int) -> None:
    time.sleep(delay_ms / 1000)


def _random_delay_ms(lower: int, upper: int) -> int:
    return random.randint(lower, upper)


def _resolve_locator(page: Any, target: TargetSpec) -> Any:
    if target.kind == "css":
        return page.locator(target.value).first
    if target.kind == "text":
        return page.get_by_text(target.value).first
    raise ValueError(f"Playwright 后端不支持目标类型: {target.kind}")


def _wait_for_target(page: Any, target: TargetSpec, timeout_ms: int) -> None:
    locator = _resolve_locator(page, target)
    locator.wait_for(state="visible", timeout=timeout_ms)


def _perform_human_like_click(page: Any, locator: Any, timeout_ms: int) -> tuple[int, int] | None:
    locator.hover(timeout=timeout_ms)
    _sleep_ms(_random_delay_ms(40, 120))

    box = locator.bounding_box(timeout=timeout_ms)
    if box is None:
        raise RuntimeError("无法获取目标元素的可点击区域")

    target_x = box["x"] + box["width"] * random.uniform(0.35, 0.65)
    target_y = box["y"] + box["height"] * random.uniform(0.35, 0.65)
    page.mouse.move(target_x, target_y, steps=random.randint(8, 20))
    _sleep_ms(_random_delay_ms(20, 90))
    page.mouse.down()
    _sleep_ms(_random_delay_ms(50, 130))
    page.mouse.up()
    return int(target_x), int(target_y)


def perform_playwright_click_flow(page: Any, config: PageClickConfig) -> ClickResult:
    playwright_options = config.playwright
    if playwright_options is None or playwright_options.url is None or config.target is None:
        raise ValueError("Playwright 后端配置不完整")

    page.goto(playwright_options.url, wait_until="domcontentloaded", timeout=config.timeout_ms)
    if playwright_options.wait_target is not None:
        _wait_for_target(page, playwright_options.wait_target, config.timeout_ms)

    locator = _resolve_locator(page, config.target)
    clicked_text = None
    clicked_position = None
    try:
        clicked_value = locator.inner_text(timeout=config.timeout_ms).strip()
        clicked_text = clicked_value or None
    except Exception:
        clicked_text = None

    if config.click_mode == "human":
        clicked_position = _perform_human_like_click(page, locator, config.timeout_ms)
    else:
        locator.click(timeout=config.timeout_ms)

    if config.screenshot_path:
        config.screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(config.screenshot_path), full_page=True)

    return ClickResult(
        success=True,
        backend="playwright",
        url=playwright_options.url,
        target_kind=config.target.kind,
        target_value=config.target.value,
        final_url=page.url,
        title=page.title(),
        clicked_text=clicked_text,
        clicked_position=clicked_position,
        screenshot_path=config.screenshot_path,
    )


class PlaywrightPageClickBackend(PageClickBackend):
    name = "playwright"

    def run(self, config: PageClickConfig) -> ClickResult:
        playwright_options = config.playwright
        if playwright_options is None:
            raise ValueError("缺少 Playwright 后端配置")

        headless = True if playwright_options.headless is None else playwright_options.headless
        ensure_browser_display_available(headless)

        try:
            from playwright.sync_api import sync_playwright
        except ModuleNotFoundError as exc:
            raise OptionalDependencyMissingError(
                "未安装 playwright，无法使用 Playwright 后端。请先执行 `pip install -r requirements.txt`。"
            ) from exc

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            context = browser.new_context()
            page = context.new_page()
            try:
                return perform_playwright_click_flow(page, config)
            finally:
                context.close()
                browser.close()
