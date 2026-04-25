from __future__ import annotations

import json
import os
import pathlib
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from typing import Any, Callable

from core.browser_runtime import ensure_browser_display_available
from core.proxy_utils import build_playwright_proxy_config


class PlaywrightEdgeBrowserSession:
    def __init__(
        self,
        *,
        extra_config: dict[str, Any],
        logger_fn: Callable[[str], None],
        import_playwright: Callable[[], Any],
        resolve_edge_command: Callable[[], str],
    ) -> None:
        self.extra_config = dict(extra_config or {})
        self.logger_fn = logger_fn
        self._import_playwright = import_playwright
        self._resolve_edge_command = resolve_edge_command
        self._timeout_ms = int(self.extra_config.get("codex_gui_dom_timeout_ms", 15_000) or 15_000)
        self._browser_settle_seconds = float(
            self.extra_config.get("codex_gui_browser_settle_seconds", 1.5) or 1.5
        )
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._edge_process: subprocess.Popen[Any] | None = None
        self._edge_user_data_dir: str | None = None
        self._cdp_port: int | None = None

    def _log_debug(self, message: str) -> None:
        self.logger_fn(message)

    def require_page(self):
        if self._page is None:
            raise RuntimeError("Edge DOM 页面未初始化")
        return self._page

    def ensure_browser_session(self):
        if self._page is not None:
            return self._page
        attach_mode = str(self.extra_config.get("codex_gui_browser_attach_mode") or "cdp").strip().lower()
        self._log_debug(f"[浏览器] 开始: 初始化 Edge 浏览器会话 attach_mode={attach_mode}")
        ensure_browser_display_available(False)
        sync_playwright = self._import_playwright()
        self._pw = sync_playwright().start()
        if attach_mode == "launch":
            return self.ensure_playwright_launch_session()
        return self.ensure_edge_cdp_session()

    def get_free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            return int(sock.getsockname()[1])

    def build_edge_launch_args(self) -> list[str]:
        edge_command = self._resolve_edge_command()
        args = [edge_command]
        cdp_port = self._cdp_port or self.get_free_port()
        self._cdp_port = cdp_port
        configured_user_data_dir = str(self.extra_config.get("codex_gui_edge_user_data_dir") or "").strip()
        user_data_dir = self.prepare_edge_runtime_user_data_dir(configured_user_data_dir)
        self._edge_user_data_dir = user_data_dir
        args.extend(
            [
                f"--remote-debugging-port={cdp_port}",
                f"--user-data-dir={user_data_dir}",
                "--start-maximized",
                "--no-first-run",
                "--no-default-browser-check",
            ]
        )
        profile_directory = str(self.extra_config.get("codex_gui_edge_profile_directory") or "").strip()
        if profile_directory:
            args.append(f"--profile-directory={profile_directory}")
        self._log_debug(
            f"[浏览器] Edge Profile 配置: codex_gui_edge_user_data_dir={user_data_dir}, codex_gui_edge_profile_directory={profile_directory or '(default)'}"
        )
        proxy_value = str(self.extra_config.get("proxy") or self.extra_config.get("proxy_url") or "").strip()
        if proxy_value:
            args.append(f"--proxy-server={proxy_value}")
        startup_url = str(self.extra_config.get("codex_gui_edge_startup_url") or "about:blank").strip() or "about:blank"
        args.append(startup_url)
        self._log_debug(f"[浏览器] 真实 Edge 启动参数: {args}")
        return args

    def build_edge_process_only_args(self) -> list[str]:
        edge_command = self._resolve_edge_command()
        configured_user_data_dir = str(self.extra_config.get("codex_gui_edge_user_data_dir") or "").strip()
        user_data_dir = self.prepare_edge_runtime_user_data_dir(configured_user_data_dir)
        self._edge_user_data_dir = user_data_dir
        args = [
            edge_command,
            f"--user-data-dir={user_data_dir}",
            "--start-maximized",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        profile_directory = str(self.extra_config.get("codex_gui_edge_profile_directory") or "").strip()
        if profile_directory:
            args.append(f"--profile-directory={profile_directory}")
        proxy_value = str(self.extra_config.get("proxy") or self.extra_config.get("proxy_url") or "").strip()
        if proxy_value:
            args.append(f"--proxy-server={proxy_value}")
        startup_url = str(self.extra_config.get("codex_gui_edge_startup_url") or "about:blank").strip() or "about:blank"
        args.append(startup_url)
        self._log_debug(
            f"[浏览器] process-only Edge 启动参数: codex_gui_edge_user_data_dir={user_data_dir}, "
            f"codex_gui_edge_profile_directory={profile_directory or '(default)'}, args={args}"
        )
        return args

    def launch_edge_process_only(self):
        if self._edge_process is not None:
            return self._edge_process
        self._log_debug("[浏览器] 开始: 仅启动 Edge 进程，不初始化 Playwright/CDP")
        ensure_browser_display_available(False)
        launch_args = self.build_edge_process_only_args()
        self._edge_process = subprocess.Popen(launch_args)
        time.sleep(max(0.1, self._browser_settle_seconds))
        return self._edge_process

    def is_real_edge_profile_path(self, path: str) -> bool:
        normalized = str(path or "").strip().lower().replace("/", "\\")
        return "\\microsoft\\edge\\user data" in normalized and normalized.endswith("user data")

    def snapshot_source_profile(self, user_data_dir: str, profile_directory: str) -> str:
        source_root = pathlib.Path(user_data_dir)
        source_profile = source_root / (profile_directory or "Default")
        if not source_profile.exists():
            raise RuntimeError(f"指定的 Edge Profile 不存在: {source_profile}")
        snapshot_root = pathlib.Path(tempfile.mkdtemp(prefix="codex-gui-edge-snapshot-"))
        self._log_debug(f"[浏览器] 开始创建 Edge Profile 快照: source={source_profile}, snapshot={snapshot_root}")
        shutil.copytree(source_profile, snapshot_root / (profile_directory or "Default"), dirs_exist_ok=True)

        root_candidates = ["Local State", "First Run", "Last Version", "Variations"]
        for candidate in root_candidates:
            source_file = source_root / candidate
            target_file = snapshot_root / candidate
            if source_file.exists() and source_file.is_file():
                try:
                    shutil.copy2(source_file, target_file)
                except Exception as exc:
                    self._log_debug(f"[浏览器] 复制 Edge 根文件失败（忽略）: {source_file} -> {exc}")

        return str(snapshot_root)

    def prepare_edge_runtime_user_data_dir(self, configured_user_data_dir: str) -> str:
        profile_directory = str(self.extra_config.get("codex_gui_edge_profile_directory") or "").strip()
        if not configured_user_data_dir:
            return tempfile.mkdtemp(prefix="codex-gui-edge-")
        use_snapshot = bool(self.extra_config.get("codex_gui_edge_snapshot_profile", True))
        if use_snapshot:
            snapshot_root = self.snapshot_source_profile(configured_user_data_dir, profile_directory)
            self._log_debug(
                f"[浏览器] 使用 Edge Profile 快照启动: source_user_data_dir={configured_user_data_dir}, runtime_user_data_dir={snapshot_root}, profile_directory={profile_directory or 'Default'}"
            )
            return snapshot_root
        return configured_user_data_dir

    def profile_lock_exists(self, user_data_dir: str, profile_directory: str) -> bool:
        profile_dir = pathlib.Path(user_data_dir)
        if profile_directory:
            profile_dir = profile_dir / profile_directory
        lock_candidates = [
            pathlib.Path(user_data_dir) / "SingletonLock",
            pathlib.Path(user_data_dir) / "SingletonCookie",
            pathlib.Path(user_data_dir) / "SingletonSocket",
            profile_dir / "LOCK",
        ]
        return any(candidate.exists() for candidate in lock_candidates)

    def validate_profile_for_cdp(self) -> None:
        configured_user_data_dir = str(self.extra_config.get("codex_gui_edge_user_data_dir") or "").strip()
        profile_directory = str(self.extra_config.get("codex_gui_edge_profile_directory") or "").strip()
        use_snapshot = bool(self.extra_config.get("codex_gui_edge_snapshot_profile", True))
        if not configured_user_data_dir:
            return
        if use_snapshot:
            self._log_debug("[浏览器] 已启用 Profile 快照模式，跳过 live profile 锁冲突检查")
            return
        if self.is_real_edge_profile_path(configured_user_data_dir):
            self._log_debug("[浏览器] 检测到正在使用真实 Edge User Data 目录，若该 profile 已在运行，CDP 端口可能无法生效")
        if self.profile_lock_exists(configured_user_data_dir, profile_directory):
            raise RuntimeError(
                "当前 Edge profile 可能正被运行中的浏览器占用，无法可靠启动 CDP。"
                "请先关闭该 profile 对应的 Edge，或改用专用自动化 profile。"
            )

    def wait_for_cdp_endpoint(self) -> str:
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
        configured_user_data_dir = str(self.extra_config.get("codex_gui_edge_user_data_dir") or "").strip()
        profile_directory = str(self.extra_config.get("codex_gui_edge_profile_directory") or "").strip()
        if configured_user_data_dir:
            raise RuntimeError(
                f"等待 Edge CDP 端点超时: {endpoint} ({last_error})。"
                f"当前配置的 profile 可能未真正以调试模式启动：user_data_dir={configured_user_data_dir}, "
                f"profile_directory={profile_directory or '(default)'}。"
                "请先关闭该 profile 对应的 Edge，或改用专用自动化 profile。"
            )
        raise RuntimeError(f"等待 Edge CDP 端点超时: {endpoint} ({last_error})")

    def pick_cdp_page(self):
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

    def ensure_edge_cdp_session(self):
        if self._pw is None:
            raise RuntimeError("Playwright 未初始化，无法通过 CDP 附着 Edge")
        self.validate_profile_for_cdp()
        launch_args = self.build_edge_launch_args()
        self._edge_process = subprocess.Popen(launch_args)
        try:
            cdp_base_url = self.wait_for_cdp_endpoint()
        except Exception:
            process = self._edge_process
            if process is not None:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except Exception:
                    try:
                        process.kill()
                    except Exception as exc:
                        self._log_debug(f"[浏览器] CDP 启动失败后终止 Edge 进程失败（忽略）: {exc}")
            self._edge_process = None
            raise
        pw = self._pw
        self._browser = pw.chromium.connect_over_cdp(cdp_base_url)
        return self.pick_cdp_page()

    def ensure_playwright_launch_session(self):
        if self._pw is None:
            raise RuntimeError("Playwright 未初始化，无法启动 Edge")
        launch_opts: dict[str, Any] = {"headless": False, "channel": "msedge", "args": ["--start-maximized"]}
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

    def browser_metrics(self) -> dict[str, float]:
        page = self.require_page()
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

    def open_url(self, url: str, *, reuse_current: bool = False) -> None:
        page = self.ensure_browser_session()
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

    def read_current_url(self) -> str:
        page = self.require_page()
        current_url = str(page.url or "").strip()
        self._log_debug(f"[浏览器] 当前 URL: {current_url}")
        return current_url

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
        keep_user_data_dir = bool(str(self.extra_config.get("codex_gui_edge_user_data_dir") or "").strip()) and not bool(
            self.extra_config.get("codex_gui_edge_snapshot_profile", True)
        )
        if self._edge_user_data_dir and not keep_user_data_dir:
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
