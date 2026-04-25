from __future__ import annotations

import os
import random
import shutil
import subprocess
import time
from typing import Any, Callable

from .browser_session import PlaywrightEdgeBrowserSession
from .geometry_helper import CodexGUIGeometryHelper
from .gui_controller import PyAutoGUICodexGUIController
from .target_detector import (
    CodexGUITargetResolution,
    PlaywrightCodexGUITargetDetector,
    PywinautoCodexGUITargetDetector,
)


class CodexGUIDriver:
    """Codex GUI 驱动抽象接口。"""

    def open_new_profile_browser(self) -> None:
        """打开使用 runtime profile 的浏览器会话。"""
        raise NotImplementedError

    def navigate_with_address_bar(self, url: str) -> None:
        """识别地址栏并输入目标地址进行导航。"""
        raise NotImplementedError

    def open_url(self, url: str, *, reuse_current: bool = False) -> None:
        """打开指定 URL。"""
        raise NotImplementedError

    def click_named_target(self, name: str) -> None:
        """点击一个命名 GUI 目标。"""
        raise NotImplementedError

    def input_text(self, name: str, text: str) -> None:
        """向命名输入目标写入文本。"""
        raise NotImplementedError

    def read_current_url(self) -> str:
        """读取当前页面 URL。"""
        raise NotImplementedError

    def press_keys(self, *keys: str) -> None:
        """发送按键序列。"""
        raise NotImplementedError

    def peek_target(self, name: str) -> tuple[str, str, dict[str, float] | None]:
        """轻量探测一个命名目标。"""
        raise NotImplementedError

    def peek_target_with_timeout(self, name: str, timeout_ms: int) -> tuple[str, str, dict[str, float] | None]:
        """带超时的轻量目标探测。"""
        raise NotImplementedError

    def page_marker_matched(self, stage: str) -> tuple[bool, str | None]:
        """检查当前页面是否命中某个阶段 marker。"""
        raise NotImplementedError

    def wander_while_waiting(self, stage: str) -> None:
        """在等待期间执行轻量游走动作。"""
        raise NotImplementedError

    def close(self) -> None:
        """关闭底层浏览器与相关资源。"""
        raise NotImplementedError


class PyAutoGUICodexGUIDriver(CodexGUIDriver):
    """基于 Playwright + pyautogui + detector 的 GUI driver 实现。"""

    def __init__(self, *, extra_config: dict[str, Any], logger_fn: Callable[[str], None]):
        """初始化浏览器会话、检测器、几何辅助器和 GUI 控制器。"""
        self.extra_config = dict(extra_config or {})
        self.logger_fn = logger_fn
        self._type_interval = float(self.extra_config.get("codex_gui_type_interval", 0.02) or 0.02)
        self._browser_settle_seconds = float(
            self.extra_config.get("codex_gui_browser_settle_seconds", 1.5) or 1.5
        )
        self._timeout_ms = int(self.extra_config.get("codex_gui_dom_timeout_ms", 15_000) or 15_000)
        self._pywinauto_input_verify_timeout_seconds = float(
            self.extra_config.get("codex_gui_pywinauto_input_verify_timeout_seconds", 5) or 5
        )
        self._pywinauto_input_retry_count = int(self.extra_config.get("codex_gui_pywinauto_input_retry_count", 2) or 2)
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._edge_process: subprocess.Popen[Any] | None = None
        self._edge_user_data_dir: str | None = None
        self._cdp_port: int | None = None
        self._browser_session = PlaywrightEdgeBrowserSession(
            extra_config=self.extra_config,
            logger_fn=self._log_debug,
            import_playwright=self._import_playwright,
            resolve_edge_command=self._resolve_edge_command,
        )
        self._target_detector = self._build_target_detector()
        self._geometry = CodexGUIGeometryHelper(
            logger_fn=self._log_debug,
            browser_session=self._browser_session,
            pyautogui_getter=self._import_pyautogui,
        )
        self._gui_controller = PyAutoGUICodexGUIController(
            extra_config=self.extra_config,
            logger_fn=self._log_debug,
            pyautogui_getter=self._import_pyautogui,
        )
        self._load_codex_gui_config()

    def _resolve_edge_command(self) -> str:
        """解析本机 Edge 可执行文件路径。"""
        configured = str(
            self.extra_config.get("codex_gui_edge_command")
            or self.extra_config.get("codex_gui_browser_command")
            or ""
        ).strip()
        if configured:
            return configured

        candidates = [
            shutil.which("msedge"),
            shutil.which("msedge.exe"),
            shutil.which("microsoft-edge"),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            normalized = str(candidate).strip()
            if normalized and (normalized.lower().endswith("msedge") or os.path.exists(normalized)):
                return normalized
        return "msedge"

    def _log_debug(self, message: str) -> None:
        """输出 driver 级调试日志。"""
        self.logger_fn(message)

    def _refresh_pywinauto_page_state(self, reason: str) -> None:
        if self._detector_kind() != "pywinauto":
            return
        refresher = getattr(self._target_detector, "refresh_page_state", None)
        if not callable(refresher):
            return
        try:
            refresher(reason=reason)
        except Exception as exc:
            if hasattr(self._target_detector, "_visible_controls_snapshot"):
                self._target_detector._visible_controls_snapshot = None
            self._log_debug(f"[UIA] 页面状态刷新失败（忽略）: reason={reason}, error={exc}")

    def _load_codex_gui_config(self) -> None:
        """在 pywinauto 模式下把 waits 配置同步回 driver extra_config。"""
        if not isinstance(self._target_detector, PywinautoCodexGUITargetDetector):
            return
        waits = self._target_detector.waits_config()
        legacy_compat_overrides = {
            "stage_probe_interval_seconds_min": 0.1,
            "pre_click_delay_seconds_min": 0.02,
        }
        for key in (
            "stage_probe_interval_seconds_min",
            "stage_probe_interval_seconds_max",
            "post_action_pause_seconds_min",
            "post_action_pause_seconds_max",
            "pre_click_delay_seconds_min",
            "pre_click_delay_seconds_max",
            "post_click_delay_seconds_min",
            "post_click_delay_seconds_max",
            "typing_paste_settle_seconds_min",
            "typing_paste_settle_seconds_max",
            "ime_switch_wait_seconds_min",
            "ime_switch_wait_seconds_max",
            "pywinauto_input_confirmation_retry_count",
        ):
            if key in waits:
                value = waits[key]
                if key in legacy_compat_overrides:
                    override_value = legacy_compat_overrides[key]
                    try:
                        value = min(float(value), float(override_value))
                    except (TypeError, ValueError):
                        value = override_value
                self.extra_config[f"codex_gui_{key}"] = value
        self._gui_controller.extra_config = dict(self.extra_config)
        self._gui_controller.extra_config = dict(self.extra_config)

    def _pywinauto_input_attempts(self) -> int:
        """计算 pywinauto 输入确认的总尝试次数。"""
        confirmation_retry_count = self.extra_config.get("codex_gui_pywinauto_input_confirmation_retry_count")
        if confirmation_retry_count is not None:
            try:
                parsed_retries = max(0, int(confirmation_retry_count or 0))
            except (TypeError, ValueError):
                parsed_retries = 0
            return parsed_retries + 1

        try:
            legacy_attempts = int(self.extra_config.get("codex_gui_pywinauto_input_retry_count", 2) or 2)
        except (TypeError, ValueError):
            legacy_attempts = 2
        return max(legacy_attempts, 1)

    def _build_target_detector(self):
        """按配置选择 Playwright 或 pywinauto 目标检测器。"""
        detector_kind = str(self.extra_config.get("codex_gui_target_detector") or "playwright").strip().lower()
        detector_cls = PlaywrightCodexGUITargetDetector
        if detector_kind == "pywinauto":
            detector_cls = PywinautoCodexGUITargetDetector
        self._log_debug(f"[检测] 初始化目标检测器: backend={detector_kind}")
        return detector_cls(
            extra_config=self.extra_config,
            logger_fn=self._log_debug,
            browser_session=self._browser_session,
        )

    def _sync_components_from_facade(self) -> None:
        """把 facade 上维护的运行时状态同步到各组件。"""
        self._browser_session._import_playwright = self._import_playwright
        self._browser_session._resolve_edge_command = self._resolve_edge_command
        self._browser_session._pw = self._pw
        self._browser_session._browser = self._browser
        self._browser_session._context = self._context
        self._browser_session._page = self._page
        self._browser_session._edge_process = self._edge_process
        self._browser_session._edge_user_data_dir = self._edge_user_data_dir
        self._browser_session._cdp_port = self._cdp_port
        self._geometry._pyautogui_getter = self._import_pyautogui
        self._gui_controller._pyautogui_getter = self._import_pyautogui

    def _sync_facade_from_components(self) -> None:
        """把组件内部最新状态回写到 facade。"""
        self._pw = self._browser_session._pw
        self._browser = self._browser_session._browser
        self._context = self._browser_session._context
        self._page = self._browser_session._page
        self._edge_process = self._browser_session._edge_process
        self._edge_user_data_dir = self._browser_session._edge_user_data_dir
        self._cdp_port = self._browser_session._cdp_port

    def _require_page(self):
        """确保当前有可用 Playwright page。"""
        self._sync_components_from_facade()
        page = self._browser_session.require_page()
        self._sync_facade_from_components()
        return page

    def _import_playwright(self):
        """懒加载 Playwright 运行时依赖。"""
        try:
            from playwright.sync_api import sync_playwright
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "未安装 playwright，无法执行 Codex GUI DOM 驱动流程。请先执行 `pip install -r requirements.txt`。"
            ) from exc
        return sync_playwright

    def _import_pyautogui(self):
        """懒加载 pyautogui，并设置 pause 参数。"""
        try:
            import pyautogui  # type: ignore
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "未安装 pyautogui，无法执行 Codex GUI 流程。请先执行 `pip install pyautogui`。"
            ) from exc
        pyautogui.PAUSE = float(self.extra_config.get("codex_gui_pyautogui_pause", 0) or 0)
        return pyautogui

    def _detector_kind(self) -> str:
        """返回当前 detector 后端名称。"""
        return str(self.extra_config.get("codex_gui_target_detector") or "playwright").strip().lower()

    @staticmethod
    def _is_input_target(name: str) -> bool:
        """判断目标名是否属于输入类控件。"""
        normalized = str(name or "").strip().lower()
        return normalized in {
            "email_input",
            "password_input",
            "verification_code_input",
            "fullname_input",
            "age_input",
        }

    @staticmethod
    def _normalize_visible_text(text: str) -> str:
        """将可见文本规整为便于比较的形式。"""
        return "".join(str(text or "").strip().lower().split())

    @staticmethod
    def _is_password_target(name: str) -> bool:
        """判断目标是否为密码输入框。"""
        return str(name or "").strip().lower() == "password_input"

    @staticmethod
    def _contains_password_mask(text: str, expected_length: int) -> bool:
        """判断文本是否表现为与目标密码长度一致的纯掩码。"""
        value = str(text or "").strip()
        if expected_length <= 0 or not value:
            return False
        return value == ("•" * expected_length) or value == ("*" * expected_length)

    @staticmethod
    def _expand_box(box: dict[str, float] | None, *, x_scale: float = 1.35, y_scale: float = 1.9) -> dict[str, float] | None:
        """放大一个矩形区域，提升 UIA 输入确认的鲁棒性。"""
        if not box:
            return None
        width = float(box.get("width") or 0)
        height = float(box.get("height") or 0)
        center_x = float(box.get("x") or 0) + width / 2
        center_y = float(box.get("y") or 0) + height / 2
        expanded_width = max(width * x_scale, width + 12)
        expanded_height = max(height * y_scale, height + 16)
        return {
            "x": center_x - expanded_width / 2,
            "y": center_y - expanded_height / 2,
            "width": expanded_width,
            "height": expanded_height,
        }

    @staticmethod
    def _random_inner80_screen_point(box: dict[str, float] | None) -> tuple[int, int]:
        """在目标框的内侧 80% 区域中随机选择点击点。"""
        if not box:
            raise RuntimeError("无法获取 UIA 屏幕位置")
        x = float(box.get("x") or 0)
        y = float(box.get("y") or 0)
        width = float(box.get("width") or 0)
        height = float(box.get("height") or 0)
        if width <= 0 or height <= 0:
            raise RuntimeError(f"UIA 尺寸无效: {box}")
        inner_x = random.uniform(x + width * 0.1, x + width * 0.9)
        inner_y = random.uniform(y + height * 0.1, y + height * 0.9)
        return int(round(inner_x)), int(round(inner_y))

    def _click_pywinauto_box(self, name: str, box: dict[str, float] | None) -> None:
        """在 pywinauto 模式下按目标 box 执行随机点击。"""
        screen_x, screen_y = self._random_inner80_screen_point(box)
        self._log_debug(f"[UIA] 随机点击点: name={name}, box={box}, point=({screen_x}, {screen_y})")
        self._click_screen_point(name, screen_x, screen_y)

    def _pre_click_blank_area_for_input_detection(self, name: str) -> None:
        """在识别输入框前先点击空白区域，降低焦点干扰。"""
        if not isinstance(self._target_detector, PywinautoCodexGUITargetDetector):
            return
        if not self._is_input_target(name):
            return
        config = self._target_detector.blank_area_click_config_for_target(name)
        if not config.enabled or not config.box:
            return
        started_at = time.perf_counter()
        click_count = random.randint(config.click_count_min, config.click_count_max)
        self._log_debug(
            f"[UIA] 输入框识别前点击空白区域: name={name}, count={click_count}, box={config.box}, interval=({config.interval_seconds_min:.2f},{config.interval_seconds_max:.2f})"
        )
        pyautogui = self._import_pyautogui()
        for index in range(click_count):
            # 多次空白点击用于让浏览器或系统焦点回到稳定状态。
            blank_x, blank_y = self._random_inner80_screen_point(config.box)
            self._click_screen_point(f"blank_area:{name}:{index + 1}", blank_x, blank_y)
            if index < click_count - 1:
                time.sleep(random.uniform(config.interval_seconds_min, config.interval_seconds_max))
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        self._log_debug(f"[耗时] 输入框识别前空白区域点击完成: name={name}, elapsed={elapsed_ms:.1f}ms")

    def _verify_pywinauto_input(self, name: str, text: str) -> None:
        """在 pywinauto 模式下确认输入内容已真实进入页面。"""
        if not isinstance(self._target_detector, PywinautoCodexGUITargetDetector):
            return
        target_text = str(text or "").strip()
        normalized_target = self._normalize_visible_text(target_text)
        if not normalized_target:
            if self._is_password_target(name):
                raise RuntimeError(f"[UIA] 输入确认失败: name={name}, text={target_text}")
            return
        self._refresh_pywinauto_page_state(f"before_input_verify:{name}")
        deadline = time.monotonic() + max(self._pywinauto_input_verify_timeout_seconds, 0.5)
        while time.monotonic() <= deadline:
            self._refresh_pywinauto_page_state(f"during_input_verify:{name}")
            # 输入确认只验证输入值本身；不要重新按 placeholder/label 定位目标。
            focused = self._target_detector.focused_edit_candidate()
            if focused:
                focused_text = self._normalize_visible_text(focused.text)
                focused_matches = (
                    focused_text == normalized_target if self._is_password_target(name) else normalized_target in focused_text
                )
                if focused_matches or (
                    self._is_password_target(name) and self._contains_password_mask(focused.text, len(target_text))
                ):
                    self._log_debug(f"[UIA] 输入确认成功(焦点值): name={name}, text={target_text}, box={focused.box}")
                    return
            for candidate in self._target_detector.visible_text_candidates():
                candidate_text = self._normalize_visible_text(candidate.text)
                candidate_matches = (
                    candidate_text == normalized_target if self._is_password_target(name) else normalized_target in candidate_text
                )
                if candidate_matches or (
                    self._is_password_target(name) and self._contains_password_mask(candidate.text, len(target_text))
                ):
                    self._log_debug(f"[UIA] 输入确认成功(可见值): name={name}, text={target_text}, box={candidate.box}")
                    return
            time.sleep(0.25)
        raise RuntimeError(f"[UIA] 输入确认失败: name={name}, text={target_text}")

    def page_marker_matched(self, stage: str) -> tuple[bool, str | None]:
        """委派到底层 detector 执行 marker 匹配，并记录耗时。"""
        if not isinstance(self._target_detector, PywinautoCodexGUITargetDetector):
            return False, None
        self._refresh_pywinauto_page_state(f"before_page_marker:{stage}")
        started_at = time.perf_counter()
        result = self._target_detector.page_marker_matched(stage)
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        self._log_debug(f"[耗时] 页面 marker 检查完成: stage={stage}, elapsed={elapsed_ms:.1f}ms")
        return result

    def _ensure_browser_session(self):
        """按 attach_mode 初始化浏览器会话。"""
        attach_mode = str(self.extra_config.get("codex_gui_browser_attach_mode") or "cdp").strip().lower()
        self._log_debug(f"[浏览器] 开始: 初始化 Edge 浏览器会话 attach_mode={attach_mode}")
        if attach_mode == "launch":
            return self._ensure_playwright_launch_session()
        return self._ensure_edge_cdp_session()

    def _get_free_port(self) -> int:
        self._sync_components_from_facade()
        port = self._browser_session.get_free_port()
        self._sync_facade_from_components()
        return port

    def _build_edge_launch_args(self) -> list[str]:
        self._sync_components_from_facade()
        args = self._browser_session.build_edge_launch_args()
        self._sync_facade_from_components()
        return args

    def _is_real_edge_profile_path(self, path: str) -> bool:
        return self._browser_session.is_real_edge_profile_path(path)

    def _snapshot_source_profile(self, user_data_dir: str, profile_directory: str) -> str:
        self._sync_components_from_facade()
        snapshot = self._browser_session.snapshot_source_profile(user_data_dir, profile_directory)
        self._sync_facade_from_components()
        return snapshot

    def _prepare_edge_runtime_user_data_dir(self, configured_user_data_dir: str) -> str:
        self._sync_components_from_facade()
        runtime_dir = self._browser_session.prepare_edge_runtime_user_data_dir(configured_user_data_dir)
        self._sync_facade_from_components()
        return runtime_dir

    def _profile_lock_exists(self, user_data_dir: str, profile_directory: str) -> bool:
        return self._browser_session.profile_lock_exists(user_data_dir, profile_directory)

    def _validate_profile_for_cdp(self) -> None:
        self._sync_components_from_facade()
        self._browser_session.validate_profile_for_cdp()
        self._sync_facade_from_components()

    def _wait_for_cdp_endpoint(self) -> str:
        self._sync_components_from_facade()
        base_url = self._browser_session.wait_for_cdp_endpoint()
        self._sync_facade_from_components()
        return base_url

    def _pick_cdp_page(self):
        self._sync_components_from_facade()
        page = self._browser_session.pick_cdp_page()
        self._sync_facade_from_components()
        return page

    def _ensure_edge_cdp_session(self):
        self._sync_components_from_facade()
        page = self._browser_session.ensure_edge_cdp_session()
        self._sync_facade_from_components()
        return page

    def _ensure_playwright_launch_session(self):
        self._sync_components_from_facade()
        page = self._browser_session.ensure_playwright_launch_session()
        self._sync_facade_from_components()
        return page

    def _clipboard_text(self) -> str:
        try:
            import tkinter

            root = tkinter.Tk()
            root.withdraw()
            value = root.clipboard_get()
            root.destroy()
            return str(value or "").strip()
        except Exception:
            pass

        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
            return str(completed.stdout or "").strip()
        except Exception:
            return ""

    def _browser_metrics(self) -> dict[str, float]:
        self._sync_components_from_facade()
        metrics = self._browser_session.browser_metrics()
        self._sync_facade_from_components()
        return metrics

    def _resolve_target_locator(self, name: str) -> CodexGUITargetResolution:
        started_at = time.perf_counter()
        if self._detector_kind() == "pywinauto":
            self._pre_click_blank_area_for_input_detection(name)
            self._refresh_pywinauto_page_state(f"before_resolve_target:{name}")
        self._sync_components_from_facade()
        resolved = self._target_detector.resolve_target(name)
        self._sync_facade_from_components()
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        self._log_debug(f"[耗时] 目标识别完成: name={name}, elapsed={elapsed_ms:.1f}ms")
        return resolved

    def peek_target(self, name: str) -> tuple[str, str, dict[str, float] | None]:
        self._refresh_pywinauto_page_state(f"before_peek_target:{name}")
        return self._target_detector.peek_target(name)

    def peek_target_with_timeout(self, name: str, timeout_ms: int) -> tuple[str, str, dict[str, float] | None]:
        self._refresh_pywinauto_page_state(f"before_peek_target:{name}")
        return self._target_detector.peek_target(name, timeout_ms=timeout_ms)

    def _screen_point_from_box(self, name: str, box: dict[str, float] | None) -> tuple[int, int]:
        self._sync_components_from_facade()
        point = self._geometry.screen_point_from_box(name, box)
        self._sync_facade_from_components()
        return point

    def _random_middle80_point_from_box(self, name: str, box: dict[str, float] | None) -> tuple[float, float]:
        self._sync_components_from_facade()
        point = self._geometry.random_middle80_point_from_box(name, box)
        self._sync_facade_from_components()
        return point

    def _screen_point_from_dom_point(
        self,
        name: str,
        dom_x: float,
        dom_y: float,
        *,
        box: dict[str, float] | None = None,
    ) -> tuple[int, int]:
        self._sync_components_from_facade()
        point = self._geometry.screen_point_from_dom_point(name, dom_x, dom_y, box=box)
        self._sync_facade_from_components()
        return point

    def _random_post_action_pause(self, reason: str) -> None:
        self._sync_components_from_facade()
        self._gui_controller.random_post_action_pause(reason)
        self._sync_facade_from_components()

    def _navigate_with_address_bar(self, url: str) -> None:
        if not isinstance(self._target_detector, PywinautoCodexGUITargetDetector):
            raise RuntimeError("当前检测器不支持 pywinauto 地址栏导航")
        pyautogui = self._import_pyautogui()
        started_at = time.perf_counter()
        self._refresh_pywinauto_page_state("before_address_bar_navigation")
        locate_started_at = time.perf_counter()
        control, box = self._target_detector.locate_address_bar()
        locate_elapsed_ms = (time.perf_counter() - locate_started_at) * 1000
        self._log_debug(f"[耗时] 地址栏定位完成: elapsed={locate_elapsed_ms:.1f}ms")
        try:
            control.set_focus()
        except Exception:
            pass
        address_x, address_y = self._random_inner80_screen_point(box)
        self._log_debug(f"[浏览器] 通过 pywinauto 地址栏导航: point=({address_x},{address_y}), url={url}")
        self._click_screen_point("browser_address_bar", address_x, address_y)
        try:
            pyautogui.hotkey("ctrl", "l")
        except Exception:
            pass
        self._gui_controller.navigate_with_address_bar(pyautogui, url)
        current_value = ""
        try:
            current_value = str(control.window_text() or "").strip()
        except Exception:
            current_value = ""
        target_url = str(url or "").strip()
        if target_url and current_value and current_value != target_url:
            self._log_debug(
                f"[浏览器] 地址栏快速输入疑似被截断，尝试剪贴板兜底: current_length={len(current_value)}, target_length={len(target_url)}"
            )
            pyautogui.hotkey("ctrl", "l")
            pyautogui.hotkey("ctrl", "a")
            self._gui_controller.paste_text(pyautogui, target_url, reason="address_bar_fallback")
            pyautogui.press("enter")
        time.sleep(max(0.1, self._browser_settle_seconds))
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        self._log_debug(f"[耗时] 地址栏导航完成: elapsed={elapsed_ms:.1f}ms")

    @staticmethod
    def _url_for_playwright_navigation(url: str) -> str:
        target = str(url or "").strip()
        if not target:
            raise RuntimeError("缺少要打开的 URL")
        if "://" in target:
            return target
        return f"https://{target}"

    def _random_page_hover_point(self) -> tuple[int, int]:
        if self._detector_kind() == "pywinauto":
            pyautogui = self._import_pyautogui()
            screen_width, screen_height = pyautogui.size()
            point = (
                int(random.uniform(screen_width * 0.15, screen_width * 0.85)),
                int(random.uniform(screen_height * 0.15, screen_height * 0.85)),
            )
            self._log_debug(f"[等待] pywinauto 模式随机游走点: screen={point}")
            return point
        self._sync_components_from_facade()
        point = self._geometry.random_page_hover_point()
        self._sync_facade_from_components()
        return point

    def wander_while_waiting(self, stage: str) -> None:
        try:
            target_x, target_y = self._random_page_hover_point()
            hover_duration = random.uniform(0.4, 1.2)
            self._log_debug(
                f"[{stage}] 等待中随机 WindMouse 漫游: point=({target_x},{target_y}), duration={hover_duration:.3f}s"
            )
            self._human_move_to(self._import_pyautogui(), target_x, target_y, hover_duration)
        except Exception as exc:
            self._log_debug(f"[{stage}] 等待中随机移动鼠标失败（忽略）: {exc}")

    def _human_move_to(self, pyautogui, x: int, y: int, duration: float) -> None:
        self._sync_components_from_facade()
        self._gui_controller.human_move_to(pyautogui, x, y, duration)
        self._sync_facade_from_components()

    def _type_text_humanized(self, pyautogui, text: str) -> None:
        self._sync_components_from_facade()
        self._gui_controller.type_text_humanized(pyautogui, text)
        self._sync_facade_from_components()

    def _click_screen_point(self, name: str, x: int, y: int) -> None:
        self._sync_components_from_facade()
        self._gui_controller.click_screen_point(name, x, y)
        self._sync_facade_from_components()

    def _focus_and_clear_input(self, name: str) -> None:
        self._sync_components_from_facade()
        self._gui_controller.focus_and_clear_input(name)
        self._sync_facade_from_components()

    def _switch_to_english_input(self) -> None:
        self._sync_components_from_facade()
        self._gui_controller.switch_to_english_input()
        self._sync_facade_from_components()

    def open_url(self, url: str, *, reuse_current: bool = False) -> None:
        if self._detector_kind() == "pywinauto":
            self._navigate_with_address_bar(url)
            return
        self._sync_components_from_facade()
        self._browser_session.open_url(url, reuse_current=reuse_current)
        self._sync_facade_from_components()

    def open_new_profile_browser(self) -> None:
        self._log_debug("[浏览器] 开始打开 runtime profile 浏览器")
        self._sync_components_from_facade()
        if self._detector_kind() == "pywinauto":
            self._browser_session.launch_edge_process_only()
        else:
            self._browser_session.ensure_browser_session()
        self._sync_facade_from_components()

    def navigate_with_address_bar(self, url: str) -> None:
        if self._detector_kind() == "pywinauto":
            self._navigate_with_address_bar(url)
            return
        self._sync_components_from_facade()
        self._browser_session.open_url(self._url_for_playwright_navigation(url), reuse_current=True)
        self._sync_facade_from_components()

    def click_named_target(self, name: str) -> None:
        self._log_debug(f"[操作] 开始点击目标: {name}")
        resolved = self._resolve_target_locator(name)
        locator = resolved.locator
        strategy_kind = resolved.strategy_kind
        strategy_value = resolved.strategy_value
        box = resolved.box
        try:
            locator.scroll_into_view_if_needed(timeout=self._timeout_ms)
        except Exception as exc:
            self._log_debug(f"[DOM] scroll_into_view 失败（忽略）: {exc}")
        if strategy_kind.startswith("uia_"):
            self._click_pywinauto_box(name, box)
            return
        else:
            dom_x, dom_y = self._random_middle80_point_from_box(name, box)
            screen_x, screen_y = self._screen_point_from_dom_point(name, dom_x, dom_y, box=box)
        self._log_debug(
            f"[操作] 点击前确认: name={name}, strategy={strategy_kind}, value={strategy_value}, point=({screen_x}, {screen_y})"
        )
        self._click_screen_point(name, screen_x, screen_y)

    def input_text(self, name: str, text: str) -> None:
        pyautogui = self._import_pyautogui()
        target_text = str(text or "")
        self._log_debug(f"[操作] 开始输入: name={name}, text={target_text}")
        attempts = self._pywinauto_input_attempts() if self._detector_kind() == "pywinauto" else 1
        last_error: Exception | None = None
        for attempt in range(1, max(attempts, 1) + 1):
            started_at = time.perf_counter()
            self.click_named_target(name)
            self._switch_to_english_input()
            self._focus_and_clear_input(name)
            self._log_debug(f"[GUI] 输入文本: name={name}, length={len(target_text)}, attempt={attempt}")
            self._type_text_humanized(pyautogui, target_text)
            if self._detector_kind() != "pywinauto":
                return
            try:
                self._verify_pywinauto_input(name, target_text)
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                self._log_debug(f"[耗时] 输入流程完成: name={name}, attempt={attempt}, elapsed={elapsed_ms:.1f}ms")
                return
            except Exception as exc:
                last_error = exc
                self._log_debug(f"[UIA] 输入确认未通过，准备重试: name={name}, attempt={attempt}, error={exc}")
                if attempt >= max(attempts, 1):
                    raise
        if last_error is not None:
            raise last_error

    def read_current_url(self) -> str:
        if self._detector_kind() == "pywinauto":
            if not isinstance(self._target_detector, PywinautoCodexGUITargetDetector):
                raise RuntimeError("当前检测器不支持 pywinauto 地址栏读取")
            self._refresh_pywinauto_page_state("before_read_current_url")
            locate_started_at = time.perf_counter()
            control, _box = self._target_detector.locate_address_bar()
            locate_elapsed_ms = (time.perf_counter() - locate_started_at) * 1000
            try:
                value = str(control.window_text() or "").strip()
            except Exception as exc:
                raise RuntimeError(f"读取浏览器地址栏失败: {exc}") from exc
            self._log_debug(f"[耗时] 地址栏读取完成: locate_elapsed={locate_elapsed_ms:.1f}ms")
            self._log_debug(f"[浏览器] 当前地址栏 URL: {value}")
            return value
        self._sync_components_from_facade()
        current_url = self._browser_session.read_current_url()
        self._sync_facade_from_components()
        return current_url

    def press_keys(self, *keys: str) -> None:
        self._sync_components_from_facade()
        self._gui_controller.press_keys(*keys)
        self._sync_facade_from_components()

    def close(self) -> None:
        self._sync_components_from_facade()
        self._browser_session.close()
        self._sync_facade_from_components()
