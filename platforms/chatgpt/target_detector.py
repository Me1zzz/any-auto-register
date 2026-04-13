from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
from pathlib import Path
import re
import time
from typing import Any, Callable

from services.page_clicker.dom import extract_clickable_candidates


@dataclass(frozen=True)
class CodexGUITargetResolution:
    locator: Any
    strategy_kind: str
    strategy_value: str
    box: dict[str, float] | None


@dataclass(frozen=True)
class PywinautoTextCandidate:
    text: str
    box: dict[str, float]


@dataclass(frozen=True)
class PywinautoBlankAreaClickConfig:
    enabled: bool
    box: dict[str, float] | None
    click_count_min: int
    click_count_max: int
    interval_seconds_min: float
    interval_seconds_max: float


class NullCodexGUILocator:
    def scroll_into_view_if_needed(self, timeout: int | None = None) -> None:
        return None

    def set_focus(self) -> None:
        return None


class CodexGUITargetDetector(ABC):
    @abstractmethod
    def resolve_target(self, name: str) -> CodexGUITargetResolution:
        raise NotImplementedError

    @abstractmethod
    def peek_target(self, name: str, *, timeout_ms: int | None = None) -> tuple[str, str, dict[str, float] | None]:
        raise NotImplementedError


class PlaywrightCodexGUITargetDetector(CodexGUITargetDetector):
    def __init__(self, *, extra_config: dict[str, Any], logger_fn: Callable[[str], None], browser_session: Any) -> None:
        self.extra_config = dict(extra_config or {})
        self.logger_fn = logger_fn
        self.browser_session = browser_session
        self._timeout_ms = int(self.extra_config.get("codex_gui_dom_timeout_ms", 15_000) or 15_000)

    def _log_debug(self, message: str) -> None:
        self.logger_fn(message)

    def _require_page(self):
        return self.browser_session.require_page()

    def fetch_dom_snapshot(self, target_name: str) -> tuple[str, list[dict[str, str]]]:
        page = self._require_page()
        self._log_debug(f"[DOM] 开始获取当前页面 DOM: target={target_name}")
        html = str(page.content() or "")
        try:
            candidates = extract_clickable_candidates(html)
        except Exception as exc:
            self._log_debug(f"[DOM] 静态候选提取失败（忽略）: {exc}")
            candidates = []
        preview = []
        for item in candidates[:8]:
            text = str(item.get("text") or "").strip()
            selector = str(item.get("selector") or "").strip()
            if text or selector:
                preview.append(f"{item.get('tag')}:{text or selector}")
        self._log_debug(f"[DOM] 获取完成: len={len(html)}, clickable={len(candidates)}, sample={preview}")
        return html, candidates

    def configured_dom_target(self, name: str) -> dict[str, Any] | None:
        targets = self.extra_config.get("codex_gui_targets") or self.extra_config.get("codex_gui_step_targets") or {}
        if not isinstance(targets, dict):
            raise RuntimeError("codex_gui_targets 配置格式错误，必须为字典")
        target = targets.get(name)
        return target if isinstance(target, dict) else None

    def builtin_target_strategies(self, name: str) -> list[tuple[str, str]]:
        mapping = {
            "register_button": [("text", "注册"), ("css", "text=注册")],
            "email_input": [("css", "input[placeholder*='电子邮件地址']"), ("css", "input[type='email']")],
            "continue_button": [("role", "继续"), ("text", "继续")],
            "password_input": [("css", "input[placeholder*='密码']"), ("css", "input[type='password']")],
            "verification_code_input": [("css", "input[placeholder*='验证码']"), ("css", "input[inputmode='numeric']")],
            "fullname_input": [("css", "input[placeholder*='全名']")],
            "age_input": [("css", "input[placeholder*='年龄']"), ("css", "input[inputmode='numeric']")],
            "complete_account_button": [
                ("role", "完成帐户创建"),
                ("text", "完成帐户创建"),
                ("role", "完成帐户创建"),
                ("text", "完成帐户创建"),
            ],
            "otp_login_button": [("text", "使用一次性验证码登录")],
            "resend_email_button": [("text", "重新发送电子邮件")],
            "retry_button": [("text", "重试")],
        }
        strategies = mapping.get(name)
        if not strategies:
            raise RuntimeError(f"缺少 Codex GUI DOM 目标定义: {name}")
        return strategies

    def locator_from_strategy(self, page, strategy_kind: str, strategy_value: str):
        if strategy_kind == "css":
            return page.locator(strategy_value).first
        if strategy_kind == "text":
            return page.get_by_text(strategy_value, exact=False).first
        if strategy_kind == "role":
            return page.get_by_role("button", name=strategy_value, exact=False).first
        raise RuntimeError(f"不支持的 DOM 定位策略: {strategy_kind}")

    def resolve_target(self, name: str, *, timeout_ms: int | None = None) -> CodexGUITargetResolution:
        page = self._require_page()
        self.fetch_dom_snapshot(name)
        configured = self.configured_dom_target(name)
        strategies: list[tuple[str, str]] = []
        if configured:
            kind = str(configured.get("kind") or "").strip().lower()
            value = str(configured.get("value") or configured.get("selector") or configured.get("text") or "").strip()
            if kind in {"css", "text", "role"} and value:
                strategies.append((kind, value))
        strategies.extend(self.builtin_target_strategies(name))
        last_error: Exception | None = None
        for strategy_kind, strategy_value in strategies:
            self._log_debug(f"[DOM] 开始定位目标: name={name}, strategy={strategy_kind}, value={strategy_value}")
            locator = self.locator_from_strategy(page, strategy_kind, strategy_value)
            try:
                effective_timeout_ms = int(timeout_ms if timeout_ms is not None else self._timeout_ms)
                locator.wait_for(state="visible", timeout=effective_timeout_ms)
                box = locator.bounding_box(timeout=effective_timeout_ms)
                self._log_debug(
                    f"[DOM] 定位成功: name={name}, strategy={strategy_kind}, value={strategy_value}, box={box}"
                )
                return CodexGUITargetResolution(
                    locator=locator,
                    strategy_kind=strategy_kind,
                    strategy_value=strategy_value,
                    box=box,
                )
            except Exception as exc:
                last_error = exc
                self._log_debug(
                    f"[DOM] 定位失败: name={name}, strategy={strategy_kind}, value={strategy_value}, error={exc}"
                )
        raise RuntimeError(f"无法在当前页面 DOM 中定位目标: {name} ({last_error})")

    def peek_target(self, name: str, *, timeout_ms: int | None = None) -> tuple[str, str, dict[str, float] | None]:
        resolved = self.resolve_target(name, timeout_ms=timeout_ms)
        return resolved.strategy_kind, resolved.strategy_value, resolved.box


class PywinautoCodexGUITargetDetector(CodexGUITargetDetector):
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

    def _config_file_path(self) -> Path:
        configured = str(
            self.extra_config.get("codex_gui_config_file")
            or self.extra_config.get("codex_gui_page_markers_file")
            or self.extra_config.get("codex_gui_blank_area_clicks_file")
            or ""
        ).strip()
        if configured:
            return Path(configured)
        return Path(__file__).with_name("codex_gui_config.json")

    def codex_gui_config(self) -> dict[str, Any]:
        if self._codex_gui_config_cache is not None:
            return self._codex_gui_config_cache
        path = self._config_file_path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._codex_gui_config_cache = {}
            return self._codex_gui_config_cache
        if not isinstance(payload, dict):
            raise RuntimeError(f"Codex GUI 配置格式错误: {path}")
        self._codex_gui_config_cache = payload
        return payload

    def page_markers(self) -> dict[str, list[str]]:
        payload = self.codex_gui_config().get("page_markers")
        if not isinstance(payload, dict):
            return {}
        markers: dict[str, list[str]] = {}
        for stage, values in payload.items():
            if not isinstance(values, list):
                continue
            markers[str(stage)] = [str(item or "").strip() for item in values if str(item or "").strip()]
        return markers

    def blank_area_clicks(self) -> dict[str, Any]:
        payload = self.codex_gui_config().get("blank_area_clicks")
        return payload if isinstance(payload, dict) else {}

    def waits_config(self) -> dict[str, Any]:
        payload = self.codex_gui_config().get("waits")
        return payload if isinstance(payload, dict) else {}

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
        mapping = {
            "register_button": ["注册"],
            "email_input": ["电子邮件地址", "邮箱", "email"],
            "continue_button": ["继续"],
            "password_input": ["密码", "password"],
            "verification_code_input": ["验证码", "code"],
            "fullname_input": ["全名", "name"],
            "age_input": ["年龄", "age"],
            "complete_account_button": ["完成帐户创建", "完成账户创建"],
            "otp_login_button": ["使用一次性验证码登录"],
            "resend_email_button": ["重新发送电子邮件", "重新发送邮件"],
            "retry_button": ["重试"],
        }
        keywords = mapping.get(name)
        if not keywords:
            raise RuntimeError(f"缺少 Codex GUI pywinauto 目标定义: {name}")
        return keywords

    def _find_edge_window(self):
        Application, findwindows = self._pywinauto_modules()
        title_keyword = str(self.extra_config.get("codex_gui_pywinauto_window_title_keyword") or "Edge").strip() or "Edge"
        title_pattern = rf".*{re.escape(title_keyword)}.*"
        handles = list(findwindows.find_windows(title_re=title_pattern))
        if not handles:
            raise RuntimeError(f"没有找到标题包含 {title_keyword!r} 的已打开浏览器窗口")
        app = Application(backend="uia").connect(handle=handles[0])
        return app.window(handle=handles[0])

    @staticmethod
    def _box_from_rect(rect) -> dict[str, float]:
        return {
            "x": float(int(rect.left)),
            "y": float(int(rect.top)),
            "width": float(int(rect.width())),
            "height": float(int(rect.height())),
        }

    def _validate_address_bar_control(self, control) -> tuple[Any, dict[str, float]] | None:
        rect_getter = getattr(control, "rectangle", None)
        if not callable(rect_getter):
            return None
        try:
            rect = rect_getter()
            width_getter = getattr(rect, "width", None)
            height_getter = getattr(rect, "height", None)
            top_value = getattr(rect, "top", None)
            if not callable(width_getter) or not callable(height_getter) or top_value is None:
                return None
            width = int(float(str(width_getter())))
            height = int(float(str(height_getter())))
            top = int(float(str(top_value)))
        except Exception:
            return None
        if width <= 0 or height <= 0 or top < 0:
            return None
        return control, self._box_from_rect(rect)

    def _get_cached_address_bar(self) -> tuple[Any, dict[str, float]] | None:
        cached = self._address_bar_cache
        if cached is None:
            return None
        control, _box = cached
        validated = self._validate_address_bar_control(control)
        if validated is None:
            self._address_bar_cache = None
            return None
        self._address_bar_cache = validated
        self._log_debug("[UIA] 复用已缓存地址栏控件")
        return validated

    def _cache_address_bar(self, control) -> tuple[Any, dict[str, float]] | None:
        validated = self._validate_address_bar_control(control)
        if validated is None:
            self._address_bar_cache = None
            return None
        self._address_bar_cache = validated
        return validated

    def _focused_edit_control(self, window) -> Any | None:
        for attr_name in ("get_focus", "get_active"):
            getter = getattr(window, attr_name, None)
            if not callable(getter):
                continue
            try:
                focused = getter()
            except Exception:
                continue
            if focused is None:
                continue
            candidates: list[Any] = []
            wrapper_getter = getattr(focused, "wrapper_object", None)
            if callable(wrapper_getter):
                try:
                    candidates.append(wrapper_getter())
                except Exception:
                    pass
            candidates.append(focused)
            for candidate in candidates:
                validated = self._validate_address_bar_control(candidate)
                if validated is not None:
                    return candidate
        return None

    def locate_address_bar(self):
        started_at = time.perf_counter()
        cached = self._get_cached_address_bar()
        if cached is not None:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            self._log_debug(f"[耗时] 地址栏定位(cache)完成: elapsed={elapsed_ms:.1f}ms")
            return cached
        window = self._find_edge_window()
        title_hints = [
            str(item or "").strip()
            for item in (
                self.extra_config.get("codex_gui_pywinauto_address_bar_title"),
                "Address and search bar",
                "地址和搜索栏",
            )
            if str(item or "").strip()
        ]
        controls_to_try = []
        for title_hint in title_hints:
            controls_to_try.append({"title": title_hint, "control_type": "Edit"})
        controls_to_try.extend(
            [
                {"auto_id": "view_0", "control_type": "Edit"},
                {"control_type": "Edit"},
            ]
        )
        last_error: Exception | None = None
        for criteria in controls_to_try:

            try:
                control = window.child_window(**criteria).wrapper_object()
                rect = control.rectangle()
                validated = self._cache_address_bar(control)
                if validated is None:
                    continue
                self._log_debug(f"[UIA] 地址栏定位成功: criteria={criteria}, rect={rect}")
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                self._log_debug(f"[耗时] 地址栏定位(primary)完成: elapsed={elapsed_ms:.1f}ms")
                return validated
            except Exception as exc:
                last_error = exc
        focused_control = self._focused_edit_control(window)
        if focused_control is not None:
            validated = self._cache_address_bar(focused_control)
            if validated is not None:
                self._log_debug(f"[UIA] 地址栏通过焦点 Edit 快速定位成功: control={focused_control}")
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                self._log_debug(f"[耗时] 地址栏定位(focused)完成: elapsed={elapsed_ms:.1f}ms")
                return validated
        try:
            descendants = window.descendants(control_type="Edit")
        except Exception as exc:
            last_error = exc
            descendants = []
        for control in descendants:
            try:
                rect = control.rectangle()
                validated = self._cache_address_bar(control)
                if validated is None:
                    continue
                self._log_debug(f"[UIA] 地址栏通过 Edit 回退定位成功: rect={rect}")
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                self._log_debug(f"[耗时] 地址栏定位(fallback)完成: elapsed={elapsed_ms:.1f}ms")
                return validated
            except Exception as exc:
                last_error = exc

        raise RuntimeError(f"无法在当前浏览器窗口中定位地址栏 ({last_error})")

    def _value_from_control(self, control) -> str:
        wrapper = control
        for method_name in ("get_value", "window_text"):
            method = getattr(wrapper, method_name, None)
            if callable(method):
                try:
                    value = str(method() or "").strip()
                except Exception:
                    value = ""
                if value:
                    return value
        return ""

    def focused_edit_candidate(self) -> PywinautoTextCandidate | None:
        window = self._find_edge_window()
        for attr_name in ("get_focus", "get_active"):
            getter = getattr(window, attr_name, None)
            if not callable(getter):
                continue
            try:
                focused = getter()
            except Exception:
                continue
            if focused is None:
                continue
            wrapper_getter = getattr(focused, "wrapper_object", None)
            if callable(wrapper_getter):
                try:
                    wrapper = wrapper_getter()
                except Exception:
                    wrapper = focused
            else:
                wrapper = focused
            value = self._value_from_control(focused)
            rect_getter = getattr(wrapper, "rectangle", None)
            if not callable(rect_getter):
                continue
            try:
                rect = rect_getter()
            except Exception:
                continue
            width_getter = getattr(rect, "width", None)
            height_getter = getattr(rect, "height", None)
            left = getattr(rect, "left", None)
            top = getattr(rect, "top", None)
            if not callable(width_getter) or not callable(height_getter):
                continue
            try:
                width = int(float(str(width_getter())))
                height = int(float(str(height_getter())))
                if left is None or top is None:
                    continue
                left_value = float(str(left))
                top_value = float(str(top))
            except Exception:
                continue
            if width <= 0 or height <= 0:
                continue
            return PywinautoTextCandidate(
                text=value,
                box={
                    "x": left_value,
                    "y": top_value,
                    "width": float(width),
                    "height": float(height),
                },
            )
        return None

    @staticmethod
    def boxes_intersect(first: dict[str, float], second: dict[str, float]) -> bool:
        ax1 = float(first.get("x") or 0)
        ay1 = float(first.get("y") or 0)
        ax2 = ax1 + float(first.get("width") or 0)
        ay2 = ay1 + float(first.get("height") or 0)
        bx1 = float(second.get("x") or 0)
        by1 = float(second.get("y") or 0)
        bx2 = bx1 + float(second.get("width") or 0)
        by2 = by1 + float(second.get("height") or 0)
        return ax1 < bx2 and ax2 > bx1 and ay1 < by2 and ay2 > by1

    def text_candidates_in_region(self, region: dict[str, float]) -> list[PywinautoTextCandidate]:
        candidates: list[PywinautoTextCandidate] = []
        for control, text, box in self.iter_visible_controls():
            if not self.boxes_intersect(box, region):
                continue
            value = self._value_from_control(control)
            candidate_text = value or str(text or "").strip()
            if not candidate_text:
                continue
            candidates.append(PywinautoTextCandidate(text=candidate_text, box={**box}))
        return candidates

    def visible_text_candidates(self) -> list[PywinautoTextCandidate]:
        started_at = time.perf_counter()
        candidates: list[PywinautoTextCandidate] = []
        for control, text, box in self.iter_visible_controls():
            value = self._value_from_control(control)
            candidate_text = value or str(text or "").strip()
            if not candidate_text:
                continue
            candidates.append(PywinautoTextCandidate(text=candidate_text, box={**box}))
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        self._log_debug(f"[耗时] 可见文本候选收集完成: count={len(candidates)}, elapsed={elapsed_ms:.1f}ms")
        return candidates

    def page_marker_matched(self, stage: str) -> tuple[bool, str | None]:
        started_at = time.perf_counter()
        markers = self.page_text_markers_for_stage(stage)
        if not markers:
            return False, None
        normalized_markers = {marker: "".join(marker.lower().split()) for marker in markers}
        matched_markers: dict[str, dict[str, float]] = {}
        for candidate in self.visible_text_candidates():
            normalized_candidate = "".join(candidate.text.lower().split())
            for marker, normalized_marker in normalized_markers.items():
                if marker in matched_markers:
                    continue
                if normalized_marker and normalized_marker in normalized_candidate:
                    matched_markers[marker] = candidate.box
        missing_markers = [marker for marker in markers if marker not in matched_markers]
        if missing_markers:
            self._log_debug(f"[UIA] 页面文本未全部命中: stage={stage}, missing={missing_markers}")
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            self._log_debug(f"[耗时] 页面文本匹配完成(未命中): stage={stage}, elapsed={elapsed_ms:.1f}ms")
            return False, ", ".join(missing_markers)
        self._log_debug(f"[UIA] 页面文本全部命中: stage={stage}, markers={markers}")
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        self._log_debug(f"[耗时] 页面文本匹配完成(命中): stage={stage}, elapsed={elapsed_ms:.1f}ms")
        if markers:
            return True, markers[0]
        return False, None

    def iter_visible_controls(self):
        started_at = time.perf_counter()
        window = self._find_edge_window()
        try:
            descendants = window.iter_descendants()
        except AttributeError:
            descendants = window.descendants()
        setup_elapsed_ms = (time.perf_counter() - started_at) * 1000
        self._log_debug(f"[耗时] 可见控件枚举准备完成: elapsed={setup_elapsed_ms:.1f}ms")
        for control in descendants:
            try:
                text = str(control.window_text() or "").strip()
            except Exception:
                text = ""
            try:
                rect = control.rectangle()
            except Exception:
                continue
            width = int(rect.width())
            height = int(rect.height())
            if width <= 0 or height <= 0:
                continue
            yield control, text, {
                "x": float(int(rect.left)),
                "y": float(int(rect.top)),
                "width": float(width),
                "height": float(height),
            }

    def resolve_target(self, name: str) -> CodexGUITargetResolution:
        started_at = time.perf_counter()
        configured = self.configured_uia_target(name)
        keywords: list[str] = []
        if configured:
            configured_keywords = configured.get("keywords")
            if isinstance(configured_keywords, (list, tuple, set)):
                keywords.extend(str(item or "").strip() for item in configured_keywords if str(item or "").strip())
            else:
                value = str(
                    configured.get("value") or configured.get("text") or configured.get("keyword") or ""
                ).strip()
                if value:
                    keywords.append(value)
        keywords.extend(self.builtin_target_keywords(name))
        keywords = list(dict.fromkeys(keywords))
        if not keywords:
            raise RuntimeError(f"缺少 Codex GUI pywinauto 关键词定义: {name}")

        candidates: list[tuple[int, str, dict[str, float]]] = []
        for _control, text, box in self.iter_visible_controls():
            if not text:
                continue
            lowered_text = text.lower()
            for keyword in keywords:
                lowered_keyword = keyword.lower()
                if lowered_keyword and lowered_keyword in lowered_text:
                    score = 0 if text == keyword else abs(len(text) - len(keyword)) + max(len(text.splitlines()) - 1, 0)
                    candidates.append((score, keyword, {**box}))
                    break

        if not candidates:
            raise RuntimeError(f"无法在当前 Edge UIA 树中定位目标: {name} (keywords={keywords})")

        score, matched_keyword, box = sorted(candidates, key=lambda item: (item[0], item[2]["y"], item[2]["x"]))[0]
        self._log_debug(
            f"[UIA] 定位成功: name={name}, keyword={matched_keyword}, score={score}, box={box}"
        )
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        self._log_debug(f"[耗时] UIA 目标匹配完成: name={name}, candidates={len(candidates)}, elapsed={elapsed_ms:.1f}ms")
        return CodexGUITargetResolution(
            locator=self._locator,
            strategy_kind="uia_text",
            strategy_value=matched_keyword,
            box=box,
        )

    def peek_target(self, name: str, *, timeout_ms: int | None = None) -> tuple[str, str, dict[str, float] | None]:
        resolved = self.resolve_target(name)
        return resolved.strategy_kind, resolved.strategy_value, resolved.box
