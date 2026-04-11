"""Codex GUI 注册/登录引擎。"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
import ctypes
import random
import json
import socket
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from core.browser_runtime import ensure_browser_display_available
from core.proxy_utils import build_playwright_proxy_config
from core.task_runtime import TaskInterruption
from services.cliproxyapi_sync import get_codex_auth_url
from services.page_clicker.dom import extract_clickable_candidates

from .refresh_token_registration_engine import EmailServiceAdapter, RegistrationResult
from .utils import generate_random_age, generate_random_name, generate_random_password

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CodexGUIIdentity:
    email: str
    password: str
    full_name: str
    age: int
    service_id: str = ""


class CodexGUIDriver:
    def open_url(self, url: str, *, reuse_current: bool = False) -> None:
        raise NotImplementedError

    def click_named_target(self, name: str) -> None:
        raise NotImplementedError

    def input_text(self, name: str, text: str) -> None:
        raise NotImplementedError

    def read_current_url(self) -> str:
        raise NotImplementedError

    def press_keys(self, *keys: str) -> None:
        raise NotImplementedError

    def peek_target(self, name: str) -> tuple[str, str, dict[str, float] | None]:
        raise NotImplementedError

    def wander_while_waiting(self, stage: str) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class PyAutoGUICodexGUIDriver(CodexGUIDriver):
    def __init__(self, *, extra_config: dict[str, Any], logger_fn: Callable[[str], None]):
        self.extra_config = dict(extra_config or {})
        self.logger_fn = logger_fn
        self._type_interval = float(self.extra_config.get("codex_gui_type_interval", 0.02) or 0.02)
        self._browser_settle_seconds = float(
            self.extra_config.get("codex_gui_browser_settle_seconds", 1.5) or 1.5
        )
        self._timeout_ms = int(self.extra_config.get("codex_gui_dom_timeout_ms", 15_000) or 15_000)
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._edge_process: subprocess.Popen[Any] | None = None
        self._edge_user_data_dir: str | None = None
        self._cdp_port: int | None = None

    def _resolve_edge_command(self) -> str:
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
        self.logger_fn(message)

    def _require_page(self):
        if self._page is None:
            raise RuntimeError("Edge DOM 页面未初始化")
        return self._page

    def _import_playwright(self):
        try:
            from playwright.sync_api import sync_playwright
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "未安装 playwright，无法执行 Codex GUI DOM 驱动流程。请先执行 `pip install -r requirements.txt`。"
            ) from exc
        return sync_playwright

    def _import_pyautogui(self):
        try:
            import pyautogui  # type: ignore
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "未安装 pyautogui，无法执行 Codex GUI 流程。请先执行 `pip install pyautogui`。"
            ) from exc
        pyautogui.PAUSE = 0
        return pyautogui

    def _ensure_browser_session(self):
        if self._page is not None:
            return self._page
        attach_mode = str(self.extra_config.get("codex_gui_browser_attach_mode") or "cdp").strip().lower()
        self._log_debug(f"[浏览器] 开始: 初始化 Edge 浏览器会话 attach_mode={attach_mode}")
        ensure_browser_display_available(False)
        sync_playwright = self._import_playwright()
        self._pw = sync_playwright().start()
        if attach_mode == "launch":
            return self._ensure_playwright_launch_session()
        return self._ensure_edge_cdp_session()

    def _get_free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            return int(sock.getsockname()[1])

    def _build_edge_launch_args(self) -> list[str]:
        edge_command = self._resolve_edge_command()
        args = [edge_command]
        cdp_port = self._cdp_port or self._get_free_port()
        self._cdp_port = cdp_port
        user_data_dir = str(
            self.extra_config.get("codex_gui_edge_user_data_dir")
            or tempfile.mkdtemp(prefix="codex-gui-edge-")
        )
        self._edge_user_data_dir = user_data_dir
        args.extend(
            [
                f"--remote-debugging-port={cdp_port}",
                f"--user-data-dir={user_data_dir}",
                "--start-maximized",
                "--no-first-run",
                "--no-default-browser-check",
                "about:blank",
            ]
        )
        proxy_value = str(self.extra_config.get("proxy") or self.extra_config.get("proxy_url") or "").strip()
        if proxy_value:
            args.append(f"--proxy-server={proxy_value}")
        self._log_debug(f"[浏览器] 真实 Edge 启动参数: {args}")
        return args

    def _wait_for_cdp_endpoint(self) -> str:
        if self._cdp_port is None:
            raise RuntimeError("CDP 端口未初始化")
        endpoint = f"http://127.0.0.1:{self._cdp_port}/json/version"
        deadline = time.time() + max(5, self._timeout_ms / 1000)
        last_error: Exception | None = None
        while time.time() <= deadline:
            try:
                with urllib.request.urlopen(endpoint, timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8", errors="replace"))
                ws_url = str(payload.get("webSocketDebuggerUrl") or "").strip()
                if ws_url:
                    self._log_debug(f"[浏览器] CDP 端点就绪: {endpoint} -> {ws_url}")
                    return f"http://127.0.0.1:{self._cdp_port}"
            except Exception as exc:
                last_error = exc
            time.sleep(0.2)
        raise RuntimeError(f"等待 Edge CDP 端点超时: {endpoint} ({last_error})")

    def _pick_cdp_page(self):
        if self._browser is None:
            raise RuntimeError("CDP Browser 未初始化")
        contexts = list(getattr(self._browser, "contexts", []) or [])
        if not contexts:
            raise RuntimeError("CDP 附着后未发现任何浏览器上下文")
        self._context = contexts[0]
        pages = list(getattr(self._context, "pages", []) or [])
        preferred = []
        for page in pages:
            page_url = str(getattr(page, "url", "") or "")
            if not page_url.startswith("edge://") and not page_url.startswith("devtools://"):
                preferred.append(page)
        self._page = preferred[-1] if preferred else (pages[-1] if pages else self._context.new_page())
        self._log_debug(
            f"[浏览器] CDP 页面绑定完成: contexts={len(contexts)}, pages={len(pages)}, current_url={getattr(self._page, 'url', '')}"
        )
        return self._page

    def _ensure_edge_cdp_session(self):
        if self._pw is None:
            raise RuntimeError("Playwright 未初始化，无法通过 CDP 附着 Edge")
        launch_args = self._build_edge_launch_args()
        self._edge_process = subprocess.Popen(launch_args)
        cdp_base_url = self._wait_for_cdp_endpoint()
        pw = self._pw
        self._browser = pw.chromium.connect_over_cdp(cdp_base_url)
        return self._pick_cdp_page()

    def _ensure_playwright_launch_session(self):
        if self._pw is None:
            raise RuntimeError("Playwright 未初始化，无法启动 Edge")
        launch_opts: dict[str, Any] = {
            "headless": False,
            "channel": "msedge",
            "args": ["--start-maximized"],
        }
        proxy_cfg = build_playwright_proxy_config(self.extra_config.get("proxy") or self.extra_config.get("proxy_url"))
        if proxy_cfg:
            launch_opts["proxy"] = proxy_cfg
            self._log_debug(f"[浏览器] 代理配置: {proxy_cfg}")
        edge_command = self._resolve_edge_command()
        if edge_command and os.path.exists(edge_command):
            launch_opts["executable_path"] = edge_command
        self._log_debug(f"[浏览器] 启动 Edge: {edge_command} | options={launch_opts}")
        pw = self._pw
        self._browser = pw.chromium.launch(**launch_opts)
        self._context = self._browser.new_context(no_viewport=True, ignore_https_errors=True)
        self._page = self._context.new_page()
        try:
            self._page.evaluate(
                """
                () => {
                  try {
                    window.moveTo(0, 0);
                    window.resizeTo(screen.availWidth, screen.availHeight);
                  } catch (e) {
                    return String(e);
                  }
                  return 'ok';
                }
                """
            )
        except Exception as exc:
            self._log_debug(f"[浏览器] Edge 最大化脚本执行失败（忽略）: {exc}")
        return self._page

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
        page = self._require_page()
        metrics = page.evaluate(
            """
            () => {
              const vv = window.visualViewport;
              return {
                url: window.location.href,
                title: document.title,
                screenX: window.screenX || 0,
                screenY: window.screenY || 0,
                outerWidth: window.outerWidth || 0,
                outerHeight: window.outerHeight || 0,
                innerWidth: window.innerWidth || 0,
                innerHeight: window.innerHeight || 0,
                devicePixelRatio: window.devicePixelRatio || 1,
                screenWidth: window.screen.width || 0,
                screenHeight: window.screen.height || 0,
                availWidth: window.screen.availWidth || 0,
                availHeight: window.screen.availHeight || 0,
                visualOffsetLeft: vv ? vv.offsetLeft : 0,
                visualOffsetTop: vv ? vv.offsetTop : 0,
                visualWidth: vv ? vv.width : window.innerWidth || 0,
                visualHeight: vv ? vv.height : window.innerHeight || 0,
              };
            }
            """
        )
        self._log_debug(f"[浏览器] 当前几何信息: {metrics}")
        return metrics

    def _fetch_dom_snapshot(self, target_name: str) -> tuple[str, list[dict[str, str]]]:
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
        self._log_debug(
            f"[DOM] 获取完成: len={len(html)}, clickable={len(candidates)}, sample={preview}"
        )
        return html, candidates

    def _configured_dom_target(self, name: str) -> dict[str, Any] | None:
        targets = self.extra_config.get("codex_gui_targets") or self.extra_config.get("codex_gui_step_targets") or {}
        if not isinstance(targets, dict):
            raise RuntimeError("codex_gui_targets 配置格式错误，必须为字典")
        target = targets.get(name)
        return target if isinstance(target, dict) else None

    def _builtin_target_strategies(self, name: str) -> list[tuple[str, str]]:
        mapping = {
            "register_button": [("text", "注册"), ("css", "text=注册")],
            "email_input": [
                ("css", "input[placeholder*='电子邮件地址']"),
                ("css", "input[type='email']"),
            ],
            "continue_button": [("role", "继续"), ("text", "继续")],
            "password_input": [
                ("css", "input[placeholder*='密码']"),
                ("css", "input[type='password']"),
            ],
            "verification_code_input": [
                ("css", "input[placeholder*='验证码']"),
                ("css", "input[inputmode='numeric']"),
            ],
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

    def _locator_from_strategy(self, page, strategy_kind: str, strategy_value: str):
        if strategy_kind == "css":
            return page.locator(strategy_value).first
        if strategy_kind == "text":
            return page.get_by_text(strategy_value, exact=False).first
        if strategy_kind == "role":
            return page.get_by_role("button", name=strategy_value, exact=False).first
        raise RuntimeError(f"不支持的 DOM 定位策略: {strategy_kind}")

    def _resolve_target_locator(self, name: str):
        page = self._require_page()
        self._fetch_dom_snapshot(name)
        configured = self._configured_dom_target(name)
        strategies: list[tuple[str, str]] = []
        if configured:
            kind = str(configured.get("kind") or "").strip().lower()
            value = str(configured.get("value") or configured.get("selector") or configured.get("text") or "").strip()
            if kind in {"css", "text", "role"} and value:
                strategies.append((kind, value))
        strategies.extend(self._builtin_target_strategies(name))
        last_error: Exception | None = None
        for strategy_kind, strategy_value in strategies:
            self._log_debug(
                f"[DOM] 开始定位目标: name={name}, strategy={strategy_kind}, value={strategy_value}"
            )
            locator = self._locator_from_strategy(page, strategy_kind, strategy_value)
            try:
                locator.wait_for(state="visible", timeout=self._timeout_ms)
                box = locator.bounding_box(timeout=self._timeout_ms)
                self._log_debug(
                    f"[DOM] 定位成功: name={name}, strategy={strategy_kind}, value={strategy_value}, box={box}"
                )
                return locator, strategy_kind, strategy_value, box
            except Exception as exc:
                last_error = exc
                self._log_debug(
                    f"[DOM] 定位失败: name={name}, strategy={strategy_kind}, value={strategy_value}, error={exc}"
                )
        raise RuntimeError(f"无法在当前页面 DOM 中定位目标: {name} ({last_error})")

    def peek_target(self, name: str) -> tuple[str, str, dict[str, float] | None]:
        _locator, strategy_kind, strategy_value, box = self._resolve_target_locator(name)
        return strategy_kind, strategy_value, box

    def _screen_point_from_box(self, name: str, box: dict[str, float] | None) -> tuple[int, int]:
        if not box:
            raise RuntimeError(f"无法获取目标 DOM 位置: {name}")
        dom_x = float(box.get("x") or 0) + float(box.get("width") or 0) / 2
        dom_y = float(box.get("y") or 0) + float(box.get("height") or 0) / 2
        return self._screen_point_from_dom_point(name, dom_x, dom_y, box=box)

    def _random_middle80_point_from_box(self, name: str, box: dict[str, float] | None) -> tuple[float, float]:
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

    def _screen_point_from_dom_point(
        self,
        name: str,
        dom_x: float,
        dom_y: float,
        *,
        box: dict[str, float] | None = None,
    ) -> tuple[int, int]:
        pyautogui = self._import_pyautogui()
        screen_width, screen_height = pyautogui.size()
        metrics = self._browser_metrics()
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
        css_x = (
            float(metrics.get("screenX") or 0)
            + border_x
            + float(metrics.get("visualOffsetLeft") or 0)
            + dom_x
        )
        css_y = (
            float(metrics.get("screenY") or 0)
            + top_chrome
            + float(metrics.get("visualOffsetTop") or 0)
            + dom_y
        )
        screen_x = int(round(css_x * scale_x))
        screen_y = int(round(css_y * scale_y))
        self._log_debug(
            "[坐标] 计算完成: "
            f"name={name}, box={box}, dom_point=({dom_x:.2f},{dom_y:.2f}), "
            f"screen_size=({screen_width},{screen_height}), scale=({scale_x:.4f},{scale_y:.4f}), "
            f"css=({css_x:.2f},{css_y:.2f}), screen=({screen_x},{screen_y})"
        )
        return screen_x, screen_y

    def _random_post_action_pause(self, reason: str) -> None:
        delay = random.uniform(3.0, 5.0)
        self._log_debug(f"[节奏] 操作后随机停顿: reason={reason}, delay={delay * 1000:.1f}ms")
        time.sleep(delay)

    def _random_page_hover_point(self) -> tuple[int, int]:
        pyautogui = self._import_pyautogui()
        metrics = self._browser_metrics()
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
        self._log_debug(
            f"[等待] 随机游走点: dom=({dom_x:.2f},{dom_y:.2f}), screen=({screen_x},{screen_y})"
        )
        return screen_x, screen_y

    def wander_while_waiting(self, stage: str) -> None:
        pyautogui = self._import_pyautogui()
        try:
            target_x, target_y = self._random_page_hover_point()
            hover_duration = random.uniform(0.4, 1.2)
            self._log_debug(
                f"[{stage}] 等待中随机 WindMouse 漫游: point=({target_x},{target_y}), duration={hover_duration:.3f}s"
            )
            self._human_move_to(pyautogui, target_x, target_y, hover_duration)
        except Exception as exc:
            self._log_debug(f"[{stage}] 等待中随机移动鼠标失败（忽略）: {exc}")

    def _human_move_to(self, pyautogui, x: int, y: int, duration: float) -> None:
        try:
            start_x, start_y = pyautogui.position()
        except Exception:
            start_x, start_y = x, y
        total_duration = max(duration, 0.05)
        distance = max(((x - start_x) ** 2 + (y - start_y) ** 2) ** 0.5, 1.0)
        gravity = float(self.extra_config.get("codex_gui_windmouse_gravity", 9.0) or 9.0)
        wind = float(self.extra_config.get("codex_gui_windmouse_wind", 3.0) or 3.0)
        max_step = float(self.extra_config.get("codex_gui_windmouse_max_step", 15.0) or 15.0)
        target_area = float(self.extra_config.get("codex_gui_windmouse_target_area", 8.0) or 8.0)
        max_steps = max(10, int(self.extra_config.get("codex_gui_windmouse_max_steps", 80) or 80))
        self._log_debug(
            f"[GUI] WindMouse 移动: start=({start_x},{start_y}), target=({x},{y}), gravity={gravity:.2f}, wind={wind:.2f}, max_step={max_step:.2f}, target_area={target_area:.2f}, max_steps={max_steps}"
        )
        if distance <= 3:
            pyautogui.moveTo(x, y, duration=total_duration)
            return

        current_x = float(start_x)
        current_y = float(start_y)
        velocity_x = 0.0
        velocity_y = 0.0
        wind_x = 0.0
        wind_y = 0.0
        screen_width, screen_height = pyautogui.size()
        path: list[tuple[int, int]] = []

        for _index in range(max_steps):
            remaining_x = x - current_x
            remaining_y = y - current_y
            remaining_distance = (remaining_x * remaining_x + remaining_y * remaining_y) ** 0.5
            if remaining_distance < 1.0:
                break

            local_wind = min(wind, remaining_distance)
            if remaining_distance >= target_area:
                wind_x = wind_x / 1.6 + random.uniform(-local_wind, local_wind) / 3.0
                wind_y = wind_y / 1.6 + random.uniform(-local_wind, local_wind) / 3.0
            else:
                wind_x /= 1.3
                wind_y /= 1.3
                local_max = max(3.0, min(max_step, remaining_distance))
                max_step = max(local_max, 3.0)

            if remaining_distance > 0:
                velocity_x += wind_x + gravity * remaining_x / remaining_distance
                velocity_y += wind_y + gravity * remaining_y / remaining_distance

            velocity_mag = (velocity_x * velocity_x + velocity_y * velocity_y) ** 0.5
            if velocity_mag > max_step:
                clip = max_step / max(velocity_mag, 1e-6)
                velocity_x *= clip
                velocity_y *= clip

            current_x += velocity_x
            current_y += velocity_y
            step_x = int(round(current_x))
            step_y = int(round(current_y))
            step_x = max(1, min(int(screen_width) - 1, step_x))
            step_y = max(1, min(int(screen_height) - 1, step_y))
            if not path or path[-1] != (step_x, step_y):
                path.append((step_x, step_y))

        if not path or path[-1] != (x, y):
            path.append((x, y))

        step_duration = total_duration / max(len(path), 1)
        for index, (step_x, step_y) in enumerate(path, start=1):
            self._log_debug(
                f"[GUI] WindMouse 轨迹点: step={index}/{len(path)}, point=({step_x},{step_y}), duration={step_duration:.3f}s"
            )
            pyautogui.moveTo(step_x, step_y, duration=0)
            time.sleep(step_duration)

    def _type_text_humanized(self, pyautogui, text: str) -> None:
        content = str(text or "")
        for index, char in enumerate(content, start=1):
            delay = random.uniform(0.05, 0.2)
            self._log_debug(
                f"[GUI] 键入字符: index={index}/{len(content)}, char={repr(char)}, delay={delay * 1000:.1f}ms"
            )
            pyautogui.write(char, interval=0)
            time.sleep(delay)
        if content:
            self._random_post_action_pause("type_text")

    def _click_screen_point(self, name: str, x: int, y: int) -> None:
        pyautogui = self._import_pyautogui()
        move_duration = float(self.extra_config.get("codex_gui_move_duration_ms", 200) or 200) / 1000
        pre_click_delay = float(self.extra_config.get("codex_gui_pre_click_delay_ms", 100) or 100) / 1000
        post_click_delay = float(self.extra_config.get("codex_gui_post_click_delay_ms", 150) or 150) / 1000
        self._log_debug(f"[GUI] 移动鼠标: name={name}, to=({x}, {y}), duration={move_duration:.3f}s")
        self._human_move_to(pyautogui, x, y, move_duration)
        time.sleep(max(pre_click_delay, 0))
        self._log_debug(f"[GUI] 点击目标: name={name}, point=({x}, {y})")
        pyautogui.click(x, y)
        time.sleep(max(post_click_delay, 0))
        self._random_post_action_pause(f"click:{name}")

    def _focus_and_clear_input(self, name: str) -> None:
        pyautogui = self._import_pyautogui()
        self._log_debug(f"[GUI] 清空输入框: name={name}")
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")
        self._random_post_action_pause(f"clear:{name}")

    def _switch_to_english_input(self) -> None:
        self._log_debug("[输入法] 开始切换到英文输入模式")
        try:
            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            load_keyboard_layout = getattr(user32, "LoadKeyboardLayoutW", None)
            activate_keyboard_layout = getattr(user32, "ActivateKeyboardLayout", None)
            get_foreground_window = getattr(user32, "GetForegroundWindow", None)
            get_window_thread_process_id = getattr(user32, "GetWindowThreadProcessId", None)
            post_message = getattr(user32, "PostMessageW", None)
            if (
                callable(load_keyboard_layout)
                and callable(activate_keyboard_layout)
                and callable(get_foreground_window)
                and callable(get_window_thread_process_id)
                and callable(post_message)
            ):
                load_keyboard_layout_fn: Any = load_keyboard_layout
                activate_keyboard_layout_fn: Any = activate_keyboard_layout
                get_foreground_window_fn: Any = get_foreground_window
                get_window_thread_process_id_fn: Any = get_window_thread_process_id
                post_message_fn: Any = post_message
                hkl = load_keyboard_layout_fn("00000409", 1)
                if hkl:
                    activate_keyboard_layout_fn(hkl, 0)
                    hwnd = get_foreground_window_fn()
                    if hwnd:
                        get_window_thread_process_id_fn(hwnd, None)
                        wm_inputlangchangerequest = 0x0050
                        post_message_fn(hwnd, wm_inputlangchangerequest, 0, hkl)
                    self._log_debug("[输入法] 已通过 Win32 API 切换到英文键盘布局")
                    return
        except Exception as exc:
            self._log_debug(f"[输入法] Win32 API 切换失败，尝试快捷键回退: {exc}")

        pyautogui = self._import_pyautogui()
        try:
            pyautogui.hotkey("ctrl", "space")
            time.sleep(0.1)
            self._log_debug("[输入法] 已通过 Ctrl+Space 尝试切换到英文输入模式")
        except Exception as exc:
            self._log_debug(f"[输入法] Ctrl+Space 切换失败，尝试 Shift: {exc}")
            pyautogui.press("shift")
            time.sleep(0.1)
            self._log_debug("[输入法] 已通过 Shift 尝试切换到英文输入模式")

    def open_url(self, url: str, *, reuse_current: bool = False) -> None:
        page = self._ensure_browser_session()
        edge_command = self._resolve_edge_command()
        mode = "当前窗口地址替换" if reuse_current else "新建 Edge 最大化窗口"
        self._log_debug(f"[浏览器] 开始打开链接: mode={mode}, edge={edge_command}, url={url}")
        page.goto(str(url or ""), wait_until="domcontentloaded", timeout=self._timeout_ms)
        try:
            page.evaluate(
                """
                () => {
                  try {
                    window.moveTo(0, 0);
                    window.resizeTo(screen.availWidth, screen.availHeight);
                  } catch (e) {
                    return String(e);
                  }
                  return 'ok';
                }
                """
            )
        except Exception as exc:
            self._log_debug(f"[浏览器] Edge 最大化脚本执行失败（忽略）: {exc}")
        try:
            self._log_debug("[浏览器] 尝试将 Edge 窗口前置到最上层")
            page.bring_to_front()
            page.evaluate(
                """
                () => {
                  try {
                    window.focus();
                    return 'ok';
                  } catch (e) {
                    return String(e);
                  }
                }
                """
            )
        except Exception as exc:
            self._log_debug(f"[浏览器] bring_to_front 失败（忽略）: {exc}")
        self._log_debug(f"[浏览器] 打开完成: current_url={page.url}")
        time.sleep(max(0.1, self._browser_settle_seconds))

    def click_named_target(self, name: str) -> None:
        self._log_debug(f"[操作] 开始点击目标: {name}")
        locator, strategy_kind, strategy_value, box = self._resolve_target_locator(name)
        try:
            locator.scroll_into_view_if_needed(timeout=self._timeout_ms)
        except Exception as exc:
            self._log_debug(f"[DOM] scroll_into_view 失败（忽略）: {exc}")
        dom_x, dom_y = self._random_middle80_point_from_box(name, box)
        screen_x, screen_y = self._screen_point_from_dom_point(name, dom_x, dom_y, box=box)
        self._log_debug(
            f"[操作] 点击前确认: name={name}, strategy={strategy_kind}, value={strategy_value}, point=({screen_x}, {screen_y})"
        )
        self._click_screen_point(name, screen_x, screen_y)

    def input_text(self, name: str, text: str) -> None:
        pyautogui = self._import_pyautogui()
        self._log_debug(f"[操作] 开始输入: name={name}, text={text}")
        self.click_named_target(name)
        self._switch_to_english_input()
        self._focus_and_clear_input(name)
        self._log_debug(f"[GUI] 输入文本: name={name}, length={len(str(text or ''))}")
        self._type_text_humanized(pyautogui, str(text or ""))

    def read_current_url(self) -> str:
        page = self._require_page()
        current_url = str(page.url or "").strip()
        self._log_debug(f"[浏览器] 当前 URL: {current_url}")
        return current_url

    def press_keys(self, *keys: str) -> None:
        pyautogui = self._import_pyautogui()
        filtered = [str(key or "").strip() for key in keys if str(key or "").strip()]
        if not filtered:
            return
        if len(filtered) == 1:
            pyautogui.press(filtered[0])
            return
        pyautogui.hotkey(*filtered)

    def close(self) -> None:
        self._log_debug("[浏览器] 开始关闭 Edge/Playwright 会话")
        if self._context is not None:
            try:
                self._context.close()
            except Exception as exc:
                self._log_debug(f"[浏览器] 关闭 context 失败（忽略）: {exc}")
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception as exc:
                self._log_debug(f"[浏览器] 关闭 browser 失败（忽略）: {exc}")
        if self._edge_process is not None:
            try:
                self._edge_process.terminate()
                self._edge_process.wait(timeout=5)
            except Exception:
                try:
                    self._edge_process.kill()
                except Exception as exc:
                    self._log_debug(f"[浏览器] 终止 Edge 进程失败（忽略）: {exc}")
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception as exc:
                self._log_debug(f"[浏览器] 停止 Playwright 失败（忽略）: {exc}")
        if self._edge_user_data_dir and not self.extra_config.get("codex_gui_edge_user_data_dir"):
            try:
                shutil.rmtree(self._edge_user_data_dir, ignore_errors=True)
            except Exception as exc:
                self._log_debug(f"[浏览器] 清理 Edge 用户目录失败（忽略）: {exc}")
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._edge_process = None
        self._edge_user_data_dir = None
        self._cdp_port = None


class CodexGUIRegistrationEngine:
    def __init__(
        self,
        email_service,
        proxy_url: Optional[str] = None,
        browser_mode: str = "headed",
        callback_logger: Optional[Callable[[str], None]] = None,
        task_uuid: Optional[str] = None,
        max_retries: int = 1,
        extra_config: Optional[dict] = None,
    ):
        self.email_service = email_service
        self.proxy_url = proxy_url
        self.browser_mode = browser_mode or "headed"
        self.callback_logger = callback_logger or (lambda msg: logger.info(msg))
        self.task_uuid = task_uuid
        self.max_retries = max(1, int(max_retries or 1))
        self.extra_config = dict(extra_config or {})

        self.email: Optional[str] = None
        self.password: Optional[str] = None
        self.logs: list[str] = []
        self._last_retry_action: Optional[Callable[[], None]] = None
        self._driver: Optional[CodexGUIDriver] = None
        self._oauth_login_completed = False

    def _log(self, message: str, level: str = "info") -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_message = f"[{timestamp}] {message}"
        self.logs.append(log_message)
        if self.callback_logger:
            self.callback_logger(log_message)
        if level == "error":
            logger.error(log_message)
        else:
            logger.info(log_message)

    def _build_driver(self) -> CodexGUIDriver:
        return PyAutoGUICodexGUIDriver(extra_config=self.extra_config, logger_fn=self._log)

    def _log_step(self, stage: str, detail: str) -> None:
        self._log(f"[{stage}] 开始: {detail}")

    def _fetch_auth_payload(self) -> dict[str, Any]:
        self._log_step("准备", "获取 Codex OAuth 授权链接")
        return get_codex_auth_url(
            api_url=self.extra_config.get("cliproxyapi_base_url"),
            api_key=self.extra_config.get("cliproxyapi_management_key"),
            is_webui=True,
        )

    def _create_identity(self) -> CodexGUIIdentity:
        self._log_step("准备", "创建注册身份与邮箱")
        email_info = self.email_service.create_email()
        email = str(self.email or (email_info or {}).get("email") or "").strip()
        if not email:
            raise RuntimeError("Codex GUI 流程创建邮箱失败：未获取到邮箱地址")
        password = str(self.password or generate_random_password(16) or "").strip()
        first_name, last_name = generate_random_name()
        full_name = f"{first_name} {last_name}".strip()
        age = generate_random_age(20, 60)
        service_id = str((email_info or {}).get("service_id") or "").strip()
        self.email = email
        self.password = password
        return CodexGUIIdentity(
            email=email,
            password=password,
            full_name=full_name,
            age=age,
            service_id=service_id,
        )

    def _wait_timeout(self, key: str, default: int) -> int:
        value = self.extra_config.get(key, default)
        try:
            return max(1, int(value or default))
        except Exception:
            return default

    def _expected_dom_targets_for_stage(self, stage: str) -> list[str]:
        mapping = {
            "注册-打开登录页": ["register_button", "continue_button"],
            "注册-创建账户页": ["email_input"],
            "注册-密码页": ["password_input"],
            "注册-验证码页": ["verification_code_input"],
            "注册-about-you": ["fullname_input", "age_input"],
            "注册-终态判断": ["complete_account_button"],
            "登录-打开登录页": ["continue_button"],
            "登录-密码页": ["otp_login_button"],
            "登录-验证码页": ["verification_code_input"],
            "登录-终态判断": ["continue_button"],
        }
        return mapping.get(stage, [])

    def _stage_dom_matched(self, stage: str) -> tuple[bool, str | None]:
        driver = self._driver
        if driver is None or not hasattr(driver, "peek_target"):
            return False, None
        for target_name in self._expected_dom_targets_for_stage(stage):
            try:
                driver.peek_target(target_name)
                return True, target_name
            except Exception as exc:
                self._log(f"[{stage}] DOM 未命中 {target_name}: {exc}")
        return False, None

    def _wait_for_any_url(self, fragments: list[str], *, timeout: int, stage: str) -> str:
        driver = self._driver
        if driver is None:
            raise RuntimeError("Codex GUI 驱动未初始化")
        self._log_step(stage, f"等待页面命中: {', '.join(fragments)}")
        deadline = time.time() + max(1, timeout)
        normalized = [fragment for fragment in fragments if str(fragment or "").strip()]
        while time.time() <= deadline:
            current_url = str(driver.read_current_url() or "").strip()
            for fragment in normalized:
                if fragment in current_url:
                    self._log(f"[{stage}] 已进入页面: {current_url}")
                    return current_url
            dom_matched, matched_target = self._stage_dom_matched(stage)
            if dom_matched:
                self._log(
                    f"[{stage}] 通过 DOM 命中判定页面已切换: target={matched_target}, current_url={current_url}"
                )
                return current_url
            if self._is_retry_page(current_url):
                self._handle_retry_page(stage)
            driver.wander_while_waiting(stage)
            time.sleep(0.25)
        joined = ", ".join(normalized)
        raise RuntimeError(f"[{stage}] 等待页面超时，未进入目标地址片段: {joined}")

    def _wait_for_url(self, fragment: str, *, timeout: int, stage: str) -> str:
        return self._wait_for_any_url([fragment], timeout=timeout, stage=stage)

    def _is_consent_url(self, current_url: str) -> bool:
        return "/sign-in-with-chatgpt/codex/consent" in str(current_url or "")

    def _complete_oauth_if_on_consent(self, stage: str) -> bool:
        driver = self._driver
        if driver is None:
            raise RuntimeError("Codex GUI 驱动未初始化")
        current_url = str(driver.read_current_url() or "").strip()
        if not self._is_consent_url(current_url):
            return False
        self._run_action(
            f"[{stage}] 命中 consent 页面，点击继续完成 OAuth 登录",
            lambda: driver.click_named_target("continue_button"),
        )
        self._oauth_login_completed = True
        self._log(f"[{stage}] 本次 OAuth 登录已成功")
        return True

    def _is_retry_page(self, current_url: str) -> bool:
        configured = self.extra_config.get("codex_gui_error_retry_url_contains")
        if isinstance(configured, str):
            fragments = [item.strip() for item in configured.split(",") if item.strip()]
        elif isinstance(configured, (list, tuple, set)):
            fragments = [str(item or "").strip() for item in configured if str(item or "").strip()]
        else:
            fragments = ["/error", "error"]
        lowered = str(current_url or "").lower()
        return any(fragment.lower() in lowered for fragment in fragments)

    def _handle_retry_page(self, stage: str) -> None:
        if self._driver is None:
            raise RuntimeError("Codex GUI 驱动未初始化")
        retry_target = (self.extra_config.get("codex_gui_retry_target") or "retry_button").strip()
        self._log(f"[{stage}] 命中错误页，尝试点击重试")
        driver = self._driver
        if driver is None:
            raise RuntimeError("Codex GUI 驱动未初始化")
        driver.click_named_target(retry_target)
        if self._last_retry_action is not None:
            self._last_retry_action()

    def _run_action(self, description: str, action: Callable[[], None]) -> None:
        self._log(description)
        self._last_retry_action = action
        action()

    def _collect_verification_code(
        self,
        adapter: EmailServiceAdapter,
        *,
        stage: str,
    ) -> str:
        driver = self._driver
        if driver is None:
            raise RuntimeError("Codex GUI 驱动未初始化")
        resend_timeout = self._wait_timeout("codex_gui_otp_wait_seconds", 55)
        resend_attempts = self._wait_timeout("codex_gui_otp_max_resends", 1)
        otp_sent_at = time.time()
        for attempt in range(resend_attempts + 1):
            exclude_codes = adapter.build_exclude_codes()
            code = adapter.wait_for_verification_code(
                adapter.email,
                timeout=resend_timeout,
                otp_sent_at=otp_sent_at,
                exclude_codes=exclude_codes,
            )
            if code:
                return str(code or "").strip()
            if attempt >= resend_attempts:
                break
            self._log(f"[{stage}] 长时间未收到验证码，尝试点击“重新发送电子邮件”")
            self._run_action(
                f"[{stage}] 点击重新发送邮件",
                lambda: driver.click_named_target(
                    str(self.extra_config.get("codex_gui_resend_target") or "resend_email_button").strip()
                ),
            )
            otp_sent_at = time.time()
        raise RuntimeError(f"[{stage}] 等待验证码失败")

    def _run_registration_flow(self, auth_url: str, identity: CodexGUIIdentity, adapter: EmailServiceAdapter) -> None:
        wait_timeout = self._wait_timeout("codex_gui_wait_timeout_seconds", 30)
        driver = self._driver
        if driver is None:
            raise RuntimeError("Codex GUI 驱动未初始化")
        self._log_step("注册", "使用 Edge 最大化窗口打开 OAuth 授权链接")
        driver.open_url(auth_url, reuse_current=False)
        self._wait_for_url("/log-in", timeout=wait_timeout, stage="注册-打开登录页")
        self._run_action("[注册] 点击注册按钮", lambda: driver.click_named_target("register_button"))
        self._wait_for_url("/create-account", timeout=wait_timeout, stage="注册-创建账户页")
        self._run_action("[注册] 输入邮箱地址", lambda: driver.input_text("email_input", identity.email))
        self._run_action("[注册] 点击继续按钮", lambda: driver.click_named_target("continue_button"))
        self._wait_for_url("/create-account/password", timeout=wait_timeout, stage="注册-密码页")
        self._run_action("[注册] 输入密码", lambda: driver.input_text("password_input", identity.password))
        self._run_action("[注册] 提交密码", lambda: driver.click_named_target("continue_button"))
        self._wait_for_url("/email-verification", timeout=wait_timeout, stage="注册-验证码页")
        register_code = self._collect_verification_code(adapter, stage="注册")
        self._run_action("[注册] 输入邮箱验证码", lambda: driver.input_text("verification_code_input", register_code))
        self._run_action("[注册] 提交验证码", lambda: driver.click_named_target("continue_button"))
        self._wait_for_url("/about-you", timeout=wait_timeout, stage="注册-about-you")
        self._run_action("[注册] 输入全名", lambda: driver.input_text("fullname_input", identity.full_name))
        self._run_action("[注册] 输入年龄", lambda: driver.input_text("age_input", str(identity.age)))
        self._run_action("[注册] 完成帐户创建", lambda: driver.click_named_target("complete_account_button"))
        terminal_url = self._wait_for_any_url(
            ["/add-phone", "/sign-in-with-chatgpt/codex/consent"],
            timeout=wait_timeout,
            stage="注册-终态判断",
        )
        if self._is_consent_url(terminal_url):
            self._complete_oauth_if_on_consent("注册")
            return

    def _run_login_flow(self, auth_url: str, identity: CodexGUIIdentity, adapter: EmailServiceAdapter) -> None:
        wait_timeout = self._wait_timeout("codex_gui_wait_timeout_seconds", 30)
        driver = self._driver
        if driver is None:
            raise RuntimeError("Codex GUI 驱动未初始化")
        self._log_step("登录", "在当前 Edge 窗口中重新打开 OAuth 授权链接")
        driver.open_url(auth_url, reuse_current=True)
        self._wait_for_url("/log-in", timeout=wait_timeout, stage="登录-打开登录页")
        self._run_action("[登录] 输入邮箱地址", lambda: driver.input_text("email_input", identity.email))
        self._run_action("[登录] 点击继续按钮", lambda: driver.click_named_target("continue_button"))
        self._wait_for_url("/log-in/password", timeout=wait_timeout, stage="登录-密码页")
        self._run_action("[登录] 切换到一次性验证码登录", lambda: driver.click_named_target("otp_login_button"))
        self._wait_for_url("/email-verification", timeout=wait_timeout, stage="登录-验证码页")
        login_code = self._collect_verification_code(adapter, stage="登录")
        self._run_action("[登录] 输入邮箱验证码", lambda: driver.input_text("verification_code_input", login_code))
        if self._complete_oauth_if_on_consent("登录-输入验证码后"):
            return
        self._run_action("[登录] 提交验证码", lambda: driver.click_named_target("continue_button"))
        if self._complete_oauth_if_on_consent("登录-提交验证码后"):
            return
        final_url = self._wait_for_any_url(
            ["/sign-in-with-chatgpt/codex/consent", "/add-phone"],
            timeout=wait_timeout,
            stage="登录-终态判断",
        )
        if self._is_consent_url(final_url):
            self._complete_oauth_if_on_consent("登录")
            return
        if "/add-phone" in final_url:
            raise RuntimeError("登录流程进入 add-phone 页面，未进入 Codex consent 页面")

    def run(self) -> RegistrationResult:
        result = RegistrationResult(success=False, logs=self.logs, source="codex_gui")
        try:
            self._log_step("准备", "初始化 Codex GUI 注册/登录流程")
            identity = self._create_identity()
            auth_payload = self._fetch_auth_payload()
            auth_url = str(auth_payload.get("url") or "").strip()
            state = str(auth_payload.get("state") or "").strip()
            self._log_step("准备", "初始化 GUI 驱动")
            self._driver = self._build_driver()
            self._log_step("准备", "初始化邮箱验证码适配器")
            adapter = EmailServiceAdapter(self.email_service, identity.email, self._log)

            self._log("=" * 60)
            self._log("开始 Codex GUI 注册/登录流程")
            self._log(f"邮箱: {identity.email}")
            self._log(f"全名: {identity.full_name}, 年龄: {identity.age}")
            self._log("=" * 60)

            self._oauth_login_completed = False
            self._run_registration_flow(auth_url, identity, adapter)
            if self._oauth_login_completed or self._complete_oauth_if_on_consent("注册阶段结束"):
                self._log("注册阶段完成，OAuth 登录已成功")
            else:
                self._log("注册阶段完成，已到达 add-phone 页面")
            if not self._oauth_login_completed:
                self._run_login_flow(auth_url, identity, adapter)
                if self._oauth_login_completed:
                    self._log("登录阶段完成，OAuth 登录已成功")
                else:
                    raise RuntimeError("登录流程结束后未完成 OAuth 登录")

            result.success = True
            result.email = identity.email
            result.password = identity.password
            result.account_id = identity.service_id or identity.email
            result.metadata = {
                "codex_gui_register_completed": True,
                "codex_gui_login_completed": True,
                "codex_gui_oauth_login_completed": True,
                "codex_gui_auth_state": state,
                "codex_gui_auth_url": auth_url,
                "codex_gui_full_name": identity.full_name,
                "codex_gui_age": identity.age,
            }
            return result
        except TaskInterruption:
            raise
        except Exception as exc:
            self._log(f"Codex GUI 注册/登录流程失败: {exc}", "error")
            result.error_message = str(exc)
            return result
        finally:
            driver = self._driver
            if driver is not None:
                try:
                    # driver.close()
                    pass
                except Exception as exc:
                    self._log(f"关闭 Codex GUI 浏览器会话失败（忽略）: {exc}")
