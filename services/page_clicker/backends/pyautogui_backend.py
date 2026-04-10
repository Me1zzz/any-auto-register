from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..models import ClickResult, OptionalDependencyMissingError, PageClickConfig
from .base import PageClickBackend


def _sleep_ms(delay_ms: int) -> None:
    time.sleep(delay_ms / 1000)


def _validate_confidence_dependency(confidence: float | None) -> None:
    if confidence is None:
        return
    try:
        import cv2  # noqa: F401
    except ModuleNotFoundError as exc:
        raise OptionalDependencyMissingError(
            "当前设置了 --locate-confidence，但环境未安装 OpenCV 依赖，无法进行置信度图像匹配。"
        ) from exc


def _resolve_screen_target(pyautogui_module: Any, config: PageClickConfig) -> tuple[int, int]:
    options = config.pyautogui
    target = config.target
    if options is None or target is None:
        raise ValueError("PyAutoGUI 后端配置不完整")

    if options.point is not None:
        return options.point

    if options.image_path is None:
        raise ValueError("PyAutoGUI 后端缺少图像目标")

    _validate_confidence_dependency(options.confidence)
    deadline = time.time() + (config.timeout_ms / 1000)
    while time.time() <= deadline:
        point = pyautogui_module.locateCenterOnScreen(
            str(options.image_path),
            confidence=options.confidence,
            region=options.region,
        )
        if point is not None:
            return int(point.x), int(point.y)
        _sleep_ms(250)
    raise RuntimeError(f"在超时时间内未定位到目标图像: {options.image_path}")


def _capture_screenshot(pyautogui_module: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    screenshot = pyautogui_module.screenshot()
    screenshot.save(path)


class PyAutoGUIPageClickBackend(PageClickBackend):
    name = "pyautogui"

    def run(self, config: PageClickConfig) -> ClickResult:
        options = config.pyautogui
        if options is None:
            raise ValueError("缺少 PyAutoGUI 后端配置")
        if not options.allow_gui_control:
            raise ValueError("未授权 GUI 控制，拒绝执行 PyAutoGUI 点击")

        try:
            import pyautogui
        except ModuleNotFoundError as exc:
            raise OptionalDependencyMissingError(
                "未安装 pyautogui，无法使用桌面自动化后端。请先执行 `pip install pyautogui`。"
            ) from exc

        pyautogui.FAILSAFE = options.failsafe
        pyautogui.PAUSE = 0

        clicked_position = None
        try:
            target_x, target_y = _resolve_screen_target(pyautogui, config)
            pyautogui.moveTo(target_x, target_y, duration=max(options.move_duration_ms, 0) / 1000)
            _sleep_ms(options.pre_click_delay_ms)
            if config.click_mode == "human":
                pyautogui.mouseDown()
                _sleep_ms(max(50, options.pre_click_delay_ms))
                pyautogui.mouseUp()
            else:
                pyautogui.click(target_x, target_y)
            _sleep_ms(options.post_click_delay_ms)
            clicked_position = (target_x, target_y)

            if config.screenshot_path:
                _capture_screenshot(pyautogui, config.screenshot_path)

            return ClickResult(
                success=True,
                backend="pyautogui",
                target_kind=config.target.kind if config.target else None,
                target_value=config.target.value if config.target else None,
                clicked_position=clicked_position,
                screenshot_path=config.screenshot_path,
            )
        except Exception:
            if config.screenshot_path:
                try:
                    _capture_screenshot(pyautogui, config.screenshot_path)
                except Exception:
                    pass
            raise
