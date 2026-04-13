"""Codex GUI 注册/登录引擎。"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime
from typing import Any, Callable, Optional

from core.task_runtime import TaskInterruption
from services.cliproxyapi_sync import get_codex_auth_url

from .codex_gui.context import CodexGUIFlowContext
from .codex_gui_driver import CodexGUIDriver, PyAutoGUICodexGUIDriver
from .codex_gui.models import CodexGUIIdentity
from .codex_gui.services.email_code_service import EmailCodeServiceAdapter as EmailServiceAdapter
from .codex_gui.workflows import LoginWorkflow, RegistrationWorkflow
from .refresh_token_registration_engine import RegistrationResult
from .utils import generate_random_age, generate_random_name, generate_random_password

logger = logging.getLogger(__name__)

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
        self._registration_workflow = RegistrationWorkflow()
        self._login_workflow = LoginWorkflow()

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

    def _build_flow_context(self, *, identity: CodexGUIIdentity, auth_url: str, email_adapter) -> CodexGUIFlowContext:
        return CodexGUIFlowContext(
            identity=identity,
            auth_url=auth_url,
            auth_state="",
            email_adapter=email_adapter,
            logger=self._log,
            extra_config=self.extra_config,
            oauth_login_completed=self._oauth_login_completed,
        )

    def _log_identity_summary(self, identity: CodexGUIIdentity) -> None:
        self._log("=" * 60)
        self._log("开始 Codex GUI 注册/登录流程")
        self._log(f"邮箱: {identity.email}")
        self._log(f"全名: {identity.full_name}, 年龄: {identity.age}")
        self._log("=" * 60)

    def _initialize_run_result(self) -> RegistrationResult:
        return RegistrationResult(success=False, logs=self.logs, source="codex_gui")

    def _finalize_success_result(
        self,
        result: RegistrationResult,
        *,
        identity: CodexGUIIdentity,
        auth_state: str,
        auth_url: str,
    ) -> RegistrationResult:
        result.success = True
        result.email = identity.email
        result.password = identity.password
        result.account_id = identity.service_id or identity.email
        result.metadata = {
            "codex_gui_register_completed": True,
            "codex_gui_login_completed": True,
            "codex_gui_oauth_login_completed": True,
            "codex_gui_auth_state": auth_state,
            "codex_gui_auth_url": auth_url,
            "codex_gui_full_name": identity.full_name,
            "codex_gui_age": identity.age,
        }
        return result

    def _wait_timeout(self, key: str, default: int) -> int:
        value = self.extra_config.get(key, default)
        try:
            return max(1, int(value or default))
        except Exception:
            return default

    def _stage_probe_interval_seconds(self) -> float:
        value = self.extra_config.get("codex_gui_stage_probe_interval_seconds")
        if value is not None:
            try:
                return max(0.1, float(value or 1))
            except Exception:
                return 1.0
        min_value = self.extra_config.get("codex_gui_stage_probe_interval_seconds_min", 0.8)
        max_value = self.extra_config.get("codex_gui_stage_probe_interval_seconds_max", 1.5)
        try:
            parsed_min = max(0.1, float(min_value or 0.8))
        except Exception:
            parsed_min = 0.8
        try:
            parsed_max = max(parsed_min, float(max_value or 1.5))
        except Exception:
            parsed_max = max(parsed_min, 1.5)
        return random.uniform(parsed_min, parsed_max)

    def _stage_dom_probe_timeout_ms(self) -> int:
        value = self.extra_config.get("codex_gui_stage_dom_probe_timeout_ms", 1000)
        try:
            return max(100, int(value or 1000))
        except Exception:
            return 1000

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
        if hasattr(driver, "page_marker_matched"):
            try:
                page_text_matched, marker = driver.page_marker_matched(stage)
                if page_text_matched:
                    return True, marker
            except Exception as exc:
                self._log(f"[{stage}] 页面文本未命中: {exc}")
        probe_timeout_ms = self._stage_dom_probe_timeout_ms()
        for target_name in self._expected_dom_targets_for_stage(stage):
            try:
                if hasattr(driver, "peek_target_with_timeout"):
                    driver.peek_target_with_timeout(target_name, probe_timeout_ms)
                else:
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
            time.sleep(self._stage_probe_interval_seconds())
        joined = ", ".join(normalized)
        raise RuntimeError(f"[{stage}] 等待页面超时，未进入目标地址片段: {joined}")

    def _wait_for_url(self, fragment: str, *, timeout: int, stage: str) -> str:
        if str(self.extra_config.get("codex_gui_target_detector") or "").strip().lower() == "pywinauto":
            self._wait_for_stage_marker(stage, timeout=timeout)
            return str(fragment or "").strip()
        return self._wait_for_any_url([fragment], timeout=timeout, stage=stage)

    def _is_consent_url(self, current_url: str) -> bool:
        return "/sign-in-with-chatgpt/codex/consent" in str(current_url or "")

    def _page_marker_match(self, stage: str) -> bool:
        driver = self._driver
        if driver is None or not hasattr(driver, "page_marker_matched"):
            return False
        try:
            matched, marker = driver.page_marker_matched(stage)
        except Exception as exc:
            self._log(f"[{stage}] 页面文本命中检查失败: {exc}")
            return False
        if matched:
            self._log(f"[{stage}] 页面文本命中成功: marker={marker}")
        return matched

    def _is_pywinauto_mode(self) -> bool:
        return str(self.extra_config.get("codex_gui_target_detector") or "").strip().lower() == "pywinauto"

    def _marker_retry_window_seconds(self) -> float:
        value = self.extra_config.get("codex_gui_stage_marker_retry_window_seconds", 15)
        try:
            return max(0.0, float(value or 15))
        except Exception:
            return 15.0

    def _retry_page_from_url_after_marker_window(self, stage: str, *, started_at: float) -> bool:
        driver = self._driver
        if driver is None:
            raise RuntimeError("Codex GUI 驱动未初始化")
        if self._is_pywinauto_mode():
            elapsed_seconds = time.perf_counter() - started_at
            if elapsed_seconds < self._marker_retry_window_seconds():
                return False
        current_url = str(driver.read_current_url() or "").strip()
        if self._is_retry_page(current_url):
            self._handle_retry_page(stage)
            return True
        return False

    def _wait_for_stage_marker(self, stage: str, *, timeout: int) -> None:
        driver = self._driver
        if driver is None:
            raise RuntimeError("Codex GUI 驱动未初始化")
        self._log_step(stage, "等待页面文本全部命中")
        started_at = time.perf_counter()
        deadline = time.time() + max(1, timeout)
        while time.time() <= deadline:
            if self._page_marker_match(stage):
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                self._log(f"[{stage}] 页面文本等待完成: elapsed={elapsed_ms:.1f}ms")
                return
            self._retry_page_from_url_after_marker_window(stage, started_at=started_at)
            driver.wander_while_waiting(stage)
            time.sleep(self._stage_probe_interval_seconds())
        raise RuntimeError(f"[{stage}] 等待页面文本命中超时")

    def _wait_for_terminal_outcome(self, *, prefix: str, timeout: int) -> str:
        add_stage = f"{prefix}-终态判断-add/phone"
        consent_stage = f"{prefix}-终态判断-consent"
        driver = self._driver
        if driver is None:
            raise RuntimeError("Codex GUI 驱动未初始化")
        self._log_step(f"{prefix}-终态判断", "等待终态页面命中")
        started_at = time.perf_counter()
        deadline = time.time() + max(1, timeout)
        while time.time() <= deadline:
            if self._page_marker_match(consent_stage):
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                self._log(f"[{prefix}-终态判断] consent 命中: elapsed={elapsed_ms:.1f}ms")
                return "consent"
            if self._page_marker_match(add_stage):
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                self._log(f"[{prefix}-终态判断] add-phone 命中: elapsed={elapsed_ms:.1f}ms")
                return "add-phone"
            self._retry_page_from_url_after_marker_window(f"{prefix}-终态判断", started_at=started_at)
            driver.wander_while_waiting(f"{prefix}-终态判断")
            time.sleep(self._stage_probe_interval_seconds())
        raise RuntimeError(f"[{prefix}-终态判断] 等待终态页面超时")

    def _wait_for_oauth_success_page(self, prefix: str, *, timeout: int) -> None:
        stage = f"{prefix}-成功标志页"
        self._wait_for_stage_marker(stage, timeout=timeout)
        self._oauth_login_completed = True
        self._log(f"[{prefix}] OAuth 成功标志页已命中")

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
        prefix = "注册" if stage.startswith("注册") else "登录"
        wait_timeout = self._wait_timeout("codex_gui_wait_timeout_seconds", 60)
        self._wait_for_oauth_success_page(prefix, timeout=wait_timeout)
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
        detector_kind = str(self.extra_config.get("codex_gui_target_detector") or "").strip().lower()
        if detector_kind == "pywinauto":
            resend_wait_min = float(self.extra_config.get("codex_gui_otp_resend_wait_seconds_min", 5) or 5)
            resend_wait_max = float(self.extra_config.get("codex_gui_otp_resend_wait_seconds_max", 8) or 8)
            resend_attempts_min = int(self.extra_config.get("codex_gui_otp_max_resends_min", 8) or 8)
            resend_attempts_max = int(self.extra_config.get("codex_gui_otp_max_resends_max", 10) or 10)
            resend_attempts = max(resend_attempts_min, resend_attempts_max)
            resend_target = str(self.extra_config.get("codex_gui_resend_target") or "resend_email_button").strip()
            for attempt in range(1, resend_attempts + 1):
                wait_seconds = random.uniform(resend_wait_min, resend_wait_max)
                self._log(f"[{stage}] 第 {attempt}/{resend_attempts} 次等待验证码，等待 {wait_seconds:.1f}s")
                exclude_codes = adapter.build_exclude_codes()
                try:
                    code = adapter.wait_for_verification_code(
                        adapter.email,
                        timeout=max(1, int(round(wait_seconds))),
                        otp_sent_at=time.time(),
                        exclude_codes=exclude_codes,
                    )
                except TimeoutError as exc:
                    self._log(
                        f"[{stage}] 本次等待验证码超时: {exc}；按未收到验证码处理，准备进入重发分支"
                    )
                    code = None
                if code:
                    return str(code or "").strip()
                if attempt >= resend_attempts:
                    break
                self._log(f"[{stage}] {wait_seconds:.1f}s 内未收到验证码，点击“重新发送电子邮件”")
                self._run_action(
                    f"[{stage}] 点击重新发送邮件",
                    lambda: driver.click_named_target(resend_target),
                )
            raise RuntimeError(f"[{stage}] 多次重发后仍未收到验证码，判定当前 OAuth 失败")
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
        ctx = self._build_flow_context(identity=identity, auth_url=auth_url, email_adapter=adapter)
        result = self._registration_workflow.run(self, ctx)
        self._oauth_login_completed = ctx.oauth_login_completed
        if result.terminal_state:
            self._log(f"[注册] 终态: {result.terminal_state}")

    def _run_login_flow(self, auth_url: str, identity: CodexGUIIdentity, adapter: EmailServiceAdapter) -> None:
        ctx = self._build_flow_context(identity=identity, auth_url=auth_url, email_adapter=adapter)
        result = self._login_workflow.run(self, ctx)
        self._oauth_login_completed = ctx.oauth_login_completed
        if result.terminal_state:
            self._log(f"[登录] 终态: {result.terminal_state}")

    def run(self) -> RegistrationResult:
        result = self._initialize_run_result()
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

            self._log_identity_summary(identity)

            self._oauth_login_completed = False
            self._run_registration_flow(auth_url, identity, adapter)
            if self._oauth_login_completed:
                self._log("注册阶段完成，OAuth 登录已成功")
            else:
                self._log("注册阶段完成，已到达 add-phone 页面")
            if not self._oauth_login_completed:
                self._run_login_flow(auth_url, identity, adapter)
                if self._oauth_login_completed:
                    self._log("登录阶段完成，OAuth 登录已成功")
                else:
                    raise RuntimeError("登录流程结束后未完成 OAuth 登录")

            return self._finalize_success_result(result, identity=identity, auth_state=state, auth_url=auth_url)
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
                    driver.close()
                except Exception as exc:
                    self._log(f"关闭 Codex GUI 浏览器会话失败（忽略）: {exc}")
