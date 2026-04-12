from __future__ import annotations

import random
from typing import Any, Callable


class CodexGUIGeometryHelper:
    def __init__(
        self,
        *,
        logger_fn: Callable[[str], None],
        browser_session: Any,
        pyautogui_getter: Callable[[], Any],
    ) -> None:
        self.logger_fn = logger_fn
        self.browser_session = browser_session
        self._pyautogui_getter = pyautogui_getter

    def _log_debug(self, message: str) -> None:
        self.logger_fn(message)

    def screen_point_from_box(self, name: str, box: dict[str, float] | None) -> tuple[int, int]:
        if not box:
            raise RuntimeError(f"无法获取目标 DOM 位置: {name}")
        dom_x = float(box.get("x") or 0) + float(box.get("width") or 0) / 2
        dom_y = float(box.get("y") or 0) + float(box.get("height") or 0) / 2
        return self.screen_point_from_dom_point(name, dom_x, dom_y, box=box)

    def random_middle80_point_from_box(self, name: str, box: dict[str, float] | None) -> tuple[float, float]:
        if not box:
            raise RuntimeError(f"无法获取目标 DOM 位置: {name}")
        x = float(box.get("x") or 0)
        y = float(box.get("y") or 0)
        width = float(box.get("width") or 0)
        height = float(box.get("height") or 0)
        if width <= 0 or height <= 0:
            raise RuntimeError(f"目标 DOM 尺寸无效: {name} -> {box}")
        x_min = x + width * 0.1
        x_max = x + width * 0.9
        y_min = y + height * 0.1
        y_max = y + height * 0.9
        dom_x = random.uniform(x_min, x_max)
        dom_y = random.uniform(y_min, y_max)
        self._log_debug(
            f"[DOM] 随机点击点: name={name}, inner80=(({x_min:.2f},{y_min:.2f})-({x_max:.2f},{y_max:.2f})), chosen=({dom_x:.2f},{dom_y:.2f})"
        )
        return dom_x, dom_y

    def screen_point_from_dom_point(
        self,
        name: str,
        dom_x: float,
        dom_y: float,
        *,
        box: dict[str, float] | None = None,
    ) -> tuple[int, int]:
        pyautogui = self._pyautogui_getter()
        screen_width, screen_height = pyautogui.size()
        metrics = self.browser_session.browser_metrics()
        outer_width = float(metrics.get("outerWidth") or 0)
        outer_height = float(metrics.get("outerHeight") or 0)
        inner_width = float(metrics.get("innerWidth") or 0)
        inner_height = float(metrics.get("innerHeight") or 0)
        border_x = max(0.0, (outer_width - inner_width) / 2)
        top_chrome = max(0.0, outer_height - inner_height - border_x)
        screen_ref_width = float(metrics.get("screenWidth") or screen_width or 1)
        screen_ref_height = float(metrics.get("screenHeight") or screen_height or 1)
        scale_x = float(screen_width or 1) / max(screen_ref_width, 1.0)
        scale_y = float(screen_height or 1) / max(screen_ref_height, 1.0)
        css_x = float(metrics.get("screenX") or 0) + border_x + float(metrics.get("visualOffsetLeft") or 0) + dom_x
        css_y = float(metrics.get("screenY") or 0) + top_chrome + float(metrics.get("visualOffsetTop") or 0) + dom_y
        screen_x = int(round(css_x * scale_x))
        screen_y = int(round(css_y * scale_y))
        self._log_debug(
            "[坐标] 计算完成: "
            f"name={name}, box={box}, dom_point=({dom_x:.2f},{dom_y:.2f}), "
            f"screen_size=({screen_width},{screen_height}), scale=({scale_x:.4f},{scale_y:.4f}), "
            f"css=({css_x:.2f},{css_y:.2f}), screen=({screen_x},{screen_y})"
        )
        return screen_x, screen_y

    def random_page_hover_point(self) -> tuple[int, int]:
        pyautogui = self._pyautogui_getter()
        metrics = self.browser_session.browser_metrics()
        screen_width, screen_height = pyautogui.size()
        screen_ref_width = float(metrics.get("screenWidth") or screen_width or 1)
        screen_ref_height = float(metrics.get("screenHeight") or screen_height or 1)
        scale_x = float(screen_width or 1) / max(screen_ref_width, 1.0)
        scale_y = float(screen_height or 1) / max(screen_ref_height, 1.0)
        inner_width = max(1.0, float(metrics.get("innerWidth") or 0))
        inner_height = max(1.0, float(metrics.get("innerHeight") or 0))
        border_x = max(0.0, (float(metrics.get("outerWidth") or 0) - inner_width) / 2)
        top_chrome = max(0.0, float(metrics.get("outerHeight") or 0) - inner_height - border_x)
        dom_x = random.uniform(inner_width * 0.15, inner_width * 0.85)
        dom_y = random.uniform(inner_height * 0.15, inner_height * 0.85)
        css_x = float(metrics.get("screenX") or 0) + border_x + float(metrics.get("visualOffsetLeft") or 0) + dom_x
        css_y = float(metrics.get("screenY") or 0) + top_chrome + float(metrics.get("visualOffsetTop") or 0) + dom_y
        screen_x = int(round(css_x * scale_x))
        screen_y = int(round(css_y * scale_y))
        self._log_debug(f"[等待] 随机游走点: dom=({dom_x:.2f},{dom_y:.2f}), screen=({screen_x},{screen_y})")
        return screen_x, screen_y
