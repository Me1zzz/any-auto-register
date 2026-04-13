from __future__ import annotations

from typing import Any, Callable

from platforms.chatgpt.codex_gui.detectors.base import (
    CodexGUITargetDetector,
    CodexGUITargetResolution,
    NullCodexGUILocator,
    PywinautoBlankAreaClickConfig,
    PywinautoTextCandidate,
)
from platforms.chatgpt.codex_gui.detectors.config import CodexGUIConfigMixin
from platforms.chatgpt.codex_gui.detectors import uia_runtime
from platforms.chatgpt.codex_gui.targets.catalog import builtin_uia_target_keywords


class PywinautoCodexGUITargetDetector(CodexGUIConfigMixin, CodexGUITargetDetector):
    def __init__(self, *, extra_config: dict[str, Any], logger_fn: Callable[[str], None], browser_session: Any) -> None:
        self.extra_config = dict(extra_config or {})
        self.logger_fn = logger_fn
        self.browser_session = browser_session
        self._locator = NullCodexGUILocator()
        self._codex_gui_config_cache: dict[str, Any] | None = None
        self._address_bar_cache: tuple[Any, dict[str, float]] | None = None

    def _log_debug(self, message: str) -> None:
        self.logger_fn(message)

    def _pywinauto_modules(self):
        try:
            from pywinauto import Application, findwindows
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "未安装 pywinauto，无法执行 Codex GUI pywinauto 检测流程。请先执行 `pip install pywinauto`。"
            ) from exc
        return Application, findwindows

    def configured_uia_target(self, name: str) -> dict[str, Any] | None:
        targets = self.extra_config.get("codex_gui_pywinauto_targets") or {}
        if not isinstance(targets, dict):
            raise RuntimeError("codex_gui_pywinauto_targets 配置格式错误，必须为字典")
        target = targets.get(name)
        return target if isinstance(target, dict) else None

    def blank_area_click_config_for_target(self, name: str) -> PywinautoBlankAreaClickConfig:
        payload = self.blank_area_clicks()
        item_payload = payload.get(name)
        if isinstance(item_payload, dict):
            config_item: dict[str, Any] = item_payload
        else:
            default_payload = payload.get("default")
            config_item = default_payload if isinstance(default_payload, dict) else {}
        enabled = bool(config_item.get("enabled", True))
        raw_box_payload = config_item.get("bbox")
        box_payload = raw_box_payload if isinstance(raw_box_payload, dict) else None
        box = None
        if box_payload:
            box = {
                "x": float(box_payload.get("x") or 0),
                "y": float(box_payload.get("y") or 0),
                "width": float(box_payload.get("width") or 0),
                "height": float(box_payload.get("height") or 0),
            }
        click_count_min = max(1, int(config_item.get("click_count_min", 1) or 1))
        click_count_max = max(click_count_min, int(config_item.get("click_count_max", click_count_min) or click_count_min))
        interval_seconds_min = max(0.0, float(config_item.get("interval_seconds_min", 0.15) or 0.15))
        interval_seconds_max = max(
            interval_seconds_min,
            float(config_item.get("interval_seconds_max", interval_seconds_min) or interval_seconds_min),
        )
        return PywinautoBlankAreaClickConfig(
            enabled=enabled,
            box=box,
            click_count_min=click_count_min,
            click_count_max=click_count_max,
            interval_seconds_min=interval_seconds_min,
            interval_seconds_max=interval_seconds_max,
        )

    def page_text_markers_for_stage(self, stage: str) -> list[str]:
        markers = self.page_markers()
        return list(markers.get(stage, []))

    def builtin_target_keywords(self, name: str) -> list[str]:
        return builtin_uia_target_keywords(name)

    def _find_edge_window(self):
        return uia_runtime.find_edge_window(self)

    @staticmethod
    def _box_from_rect(rect) -> dict[str, float]:
        return uia_runtime.box_from_rect(rect)

    def _validate_address_bar_control(self, control) -> tuple[Any, dict[str, float]] | None:
        return uia_runtime.validate_address_bar_control(control)

    def _get_cached_address_bar(self) -> tuple[Any, dict[str, float]] | None:
        return uia_runtime.get_cached_address_bar(self)

    def _cache_address_bar(self, control) -> tuple[Any, dict[str, float]] | None:
        return uia_runtime.cache_address_bar(self, control)

    def _focused_edit_control(self, window) -> Any | None:
        return uia_runtime.focused_edit_control(self, window)

    def locate_address_bar(self):
        return uia_runtime.locate_address_bar(self)

    def _value_from_control(self, control) -> str:
        return uia_runtime.value_from_control(control)

    def focused_edit_candidate(self) -> PywinautoTextCandidate | None:
        candidate = uia_runtime.focused_edit_candidate(self)
        if candidate is None:
            return None
        return PywinautoTextCandidate(text=str(candidate.get("text") or ""), box=dict(candidate.get("box") or {}))

    @staticmethod
    def boxes_intersect(first: dict[str, float], second: dict[str, float]) -> bool:
        return uia_runtime.boxes_intersect(first, second)

    def text_candidates_in_region(self, region: dict[str, float]) -> list[PywinautoTextCandidate]:
        return [
            PywinautoTextCandidate(text=str(item.get("text") or ""), box=dict(item.get("box") or {}))
            for item in uia_runtime.text_candidates_in_region(self, region)
        ]

    def visible_text_candidates(self) -> list[PywinautoTextCandidate]:
        return [
            PywinautoTextCandidate(text=str(item.get("text") or ""), box=dict(item.get("box") or {}))
            for item in uia_runtime.visible_text_candidates(self)
        ]

    def page_marker_matched(self, stage: str) -> tuple[bool, str | None]:
        return uia_runtime.page_marker_matched(self, stage)

    def iter_visible_controls(self):
        yield from uia_runtime.iter_visible_controls(self)

    def resolve_target(self, name: str) -> CodexGUITargetResolution:
        result = uia_runtime.resolve_uia_target(self, name)
        return CodexGUITargetResolution(
            locator=result.get("locator"),
            strategy_kind=str(result.get("strategy_kind") or ""),
            strategy_value=str(result.get("strategy_value") or ""),
            box=result.get("box"),
        )

    def peek_target(self, name: str, *, timeout_ms: int | None = None) -> tuple[str, str, dict[str, float] | None]:
        resolved = self.resolve_target(name)
        return resolved.strategy_kind, resolved.strategy_value, resolved.box
