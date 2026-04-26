"""Codex GUI 注册/登录引擎。"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime
from typing import Any, Callable, Optional, cast

from core.task_runtime import TaskInterruption
from services.cliproxyapi_sync import get_codex_auth_url

from .codex_gui.context import CodexGUIFlowContext
from .codex_gui_driver import CodexGUIDriver, PyAutoGUICodexGUIDriver
from .codex_gui.models import CodexGUIIdentity
from .codex_gui.services.email_code_service import EmailCodeServiceAdapter as EmailServiceAdapter
from .codex_gui.steps.base import StepErrorDecision
from .codex_gui.steps.errors import RegistrationHardFailureError
from .codex_gui.workflows import LoginWorkflow, OfficialSignupWorkflow, RegistrationWorkflow
from .chatgpt_registration_mode_adapter import (
    CODEX_GUI_VARIANT_DEFAULT,
    CODEX_GUI_VARIANT_OFFICIAL_SIGNUP,
    resolve_codex_gui_variant,
)
from .refresh_token_registration_engine import RegistrationResult
from .team_workspace import (
    ChatGPTTeamWorkspaceResult,
    invite_chatgpt_team_member,
    remove_chatgpt_team_member_with_retry,
)
from .utils import generate_random_age, generate_random_name, generate_random_password

logger = logging.getLogger(__name__)


def _parse_bool_config(value: Any, *, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


class CodexGUIRegistrationEngine:
    """驱动 ChatGPT/Codex GUI 注册与登录补偿链路的兼容入口引擎。"""

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
        """保存运行时依赖，并初始化 GUI 工作流所需的状态。"""
        self.email_service = email_service
        self.proxy_url = proxy_url
        self.browser_mode = browser_mode or "headed"
        self.callback_logger = callback_logger or (lambda msg: logger.info(msg))
        self.task_uuid = task_uuid
        self.max_retries = max(1, int(max_retries or 1))
        self.extra_config = dict(extra_config or {})
        if (
            str(self.extra_config.get("cloudmail_team_account_email") or "").strip()
            and not str(self.extra_config.get("codex_gui_target_detector") or "").strip()
        ):
            self.extra_config["codex_gui_target_detector"] = "pywinauto"

        self.email: Optional[str] = None
        self.password: Optional[str] = None
        self.logs: list[str] = []
        self._last_retry_action: Optional[Callable[[], None]] = None
        self._driver: Optional[CodexGUIDriver] = None
        self._oauth_login_completed = False
        self._registration_workflow = RegistrationWorkflow()
        self._login_workflow = LoginWorkflow()
        self._official_signup_workflow = OfficialSignupWorkflow()
        self._variant_resolution = resolve_codex_gui_variant(self.extra_config)
        self._last_flow_context: CodexGUIFlowContext | None = None

    def _log(self, message: str, level: str = "info") -> None:
        """统一写入内存日志、回调日志与模块日志。"""
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
        """构建当前 GUI 链路使用的 driver 实现。"""
        return PyAutoGUICodexGUIDriver(extra_config=self.extra_config, logger_fn=self._log)

    def _log_step(self, stage: str, detail: str) -> None:
        """按阶段输出标准化日志。"""
        self._log(f"[{stage}] 开始: {detail}")

    def _fetch_auth_payload(self) -> dict[str, Any]:
        """通过 cliproxy API 获取 OAuth 授权链接与状态。"""
        self._log_step("准备", "获取 Codex OAuth 授权链接")
        return get_codex_auth_url(
            api_url=self.extra_config.get("cliproxyapi_base_url"),
            api_key=self.extra_config.get("cliproxyapi_management_key"),
            is_webui=True,
        )

    def _create_identity(self) -> CodexGUIIdentity:
        """创建注册所需的邮箱、密码、姓名与年龄。"""
        self._log_step("准备", "创建注册身份与邮箱")
        email_info = self.email_service.create_email()
        email = str(self.email or (email_info or {}).get("email") or "").strip()
        if not email:
            raise RuntimeError("Codex GUI 流程创建邮箱失败：未获取到邮箱地址")
        password = str(self.password or generate_random_password(16) or "").strip()
        first_name, last_name = generate_random_name()
        full_name = random.choice([first_name, last_name,f"{first_name} {last_name}".strip()])
        if random.choice([True, False]):
            full_name = full_name.lower()
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
        """为 workflow 构建共享流程上下文。"""
        ctx = CodexGUIFlowContext(
            identity=identity,
            auth_url=auth_url,
            auth_state="",
            email_adapter=email_adapter,
            logger=self._log,
            extra_config=self.extra_config,
            oauth_login_completed=self._oauth_login_completed,
            gui_variant=self._variant_resolution.effective_variant,
            variant_requested=self._variant_resolution.requested_variant,
            variant_fallback_reason=self._variant_resolution.fallback_reason,
        )
        self._last_flow_context = ctx
        return ctx

    def _log_identity_summary(self, identity: CodexGUIIdentity) -> None:
        """输出本次 GUI 注册/登录使用的身份摘要。"""
        self._log("=" * 60)
        self._log("开始 Codex GUI 注册/登录流程")
        self._log(f"邮箱: {identity.email}")
        self._log(f"全名: {identity.full_name}, 年龄: {identity.age}")
        self._log("=" * 60)

    def _build_abort_decision(self, error: Exception) -> StepErrorDecision:
        """构建立即终止当前流程的恢复决策。"""
        return StepErrorDecision(action="abort_flow", reason=str(error))

    def _initialize_run_result(self) -> RegistrationResult:
        """初始化默认失败态的结果对象。"""
        return RegistrationResult(success=False, logs=self.logs, source="codex_gui")

    def _finalize_success_result(
        self,
        result: RegistrationResult,
        *,
        identity: CodexGUIIdentity,
        auth_state: str,
        auth_url: str,
        ctx: CodexGUIFlowContext | None = None,
    ) -> RegistrationResult:
        """把成功执行后的身份与 OAuth 元信息写回结果对象。"""
        result.success = True
        result.email = identity.email
        result.password = identity.password
        result.account_id = identity.service_id or identity.email
        metadata = {
            "codex_gui_register_completed": True,
            "codex_gui_login_completed": True,
            "codex_gui_oauth_login_completed": True,
            "codex_gui_auth_state": auth_state,
            "codex_gui_auth_url": auth_url,
            "codex_gui_full_name": identity.full_name,
            "codex_gui_age": identity.age,
            "codex_gui_variant_requested": self._variant_resolution.requested_variant,
            "codex_gui_variant": self._variant_resolution.effective_variant,
            "codex_gui_variant_fallback_reason": self._variant_resolution.fallback_reason,
        }
        if ctx is not None:
            metadata.update(self._build_phase_metadata(ctx))
        result.metadata = metadata
        return result

    def _build_phase_metadata(self, ctx: CodexGUIFlowContext) -> dict[str, Any]:
        workspace_enrolled = bool(
            ctx.workspace_enroll_result.get("success")
            or ctx.workspace_enroll_result.get("workspace_enroll_success")
        )
        workspace_cleanup_completed = bool(
            ctx.workspace_cleanup_result.get("success")
            or ctx.workspace_cleanup_result.get("workspace_cleanup_success")
        )
        return {
            "codex_gui_official_signup_completed": bool(ctx.official_signup_completed),
            "codex_gui_register_tail_completed": bool(ctx.register_tail_completed),
            "codex_gui_workspace_enrolled": workspace_enrolled,
            "codex_gui_workspace_enroll_result": dict(ctx.workspace_enroll_result),
            "codex_gui_oauth_login_reuse_completed": bool(ctx.oauth_login_result.get("success")),
            "codex_gui_oauth_login_reuse_result": dict(ctx.oauth_login_result),
            "codex_gui_cleanup_required": bool(ctx.cleanup_required),
            "codex_gui_workspace_cleanup_completed": workspace_cleanup_completed,
            "codex_gui_workspace_cleanup_result": dict(ctx.workspace_cleanup_result),
            "codex_gui_cleanup_retry_count": int(ctx.cleanup_retry_count or 0),
            "codex_gui_cleanup_compensation_context": dict(ctx.cleanup_compensation_context),
        }

    def _build_base_metadata(self, *, auth_state: str = "", auth_url: str = "") -> dict[str, Any]:
        return {
            "codex_gui_variant_requested": self._variant_resolution.requested_variant,
            "codex_gui_variant": self._variant_resolution.effective_variant,
            "codex_gui_variant_fallback_reason": self._variant_resolution.fallback_reason,
            "codex_gui_auth_state": auth_state,
            "codex_gui_auth_url": auth_url,
        }

    def _attach_failure_metadata(
        self,
        result: RegistrationResult,
        *,
        error: Exception,
        auth_state: str = "",
        auth_url: str = "",
    ) -> None:
        metadata = self._build_base_metadata(auth_state=auth_state, auth_url=auth_url)
        ctx = self._last_flow_context
        if ctx is not None:
            metadata.update(self._build_phase_metadata(ctx))
        error_text = str(error)
        if "工作空间清理阶段错误" in error_text:
            failure_stage = "workspace_cleanup"
        elif "工作空间加入阶段错误" in error_text:
            failure_stage = "workspace_enroll"
        elif "登录" in error_text or "oauth" in error_text.lower() or "login" in error_text.lower():
            failure_stage = "oauth_login"
        elif self._variant_resolution.effective_variant == CODEX_GUI_VARIANT_OFFICIAL_SIGNUP and ctx is not None and not ctx.official_signup_completed:
            failure_stage = "official_signup"
        else:
            failure_stage = "registration"
        metadata["codex_gui_failure_stage"] = failure_stage
        metadata["codex_gui_primary_error"] = error_text
        metadata["codex_gui_cleanup_error"] = error_text if failure_stage == "workspace_cleanup" else ""
        result.metadata = metadata

    def _wait_timeout(self, key: str, default: int) -> int:
        """读取并规整等待超时配置。"""
        value = self.extra_config.get(key, default)
        try:
            return max(1, int(value or default))
        except Exception:
            return default

    def _stage_probe_interval_seconds(self) -> float:
        """计算阶段探测之间的休眠时间。"""
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
        """读取单次 DOM 探测的超时阈值。"""
        value = self.extra_config.get("codex_gui_stage_dom_probe_timeout_ms", 1000)
        try:
            return max(100, int(value or 1000))
        except Exception:
            return 1000

    def _expected_dom_targets_for_stage(self, stage: str) -> list[str]:
        """给每个阶段提供一个用于辅助命中的 DOM target 列表。"""
        mapping = {
            "官网注册-首页": ["official_signup_free_signup_button"],
            "注册-打开登录页": ["register_button", "continue_button"],
            "注册-创建账户页": ["email_input"],
            "注册-密码页": ["password_input"],
            "注册-验证码页": ["verification_code_input"],
            "注册-about-you": ["fullname_input", "age_input"],
            "注册-终态判断": ["complete_account_button"],
            "官网注册-登录或注册弹窗": ["official_signup_email_input", "official_signup_continue_button"],
            "登录-打开登录页": ["continue_button"],
            "登录-密码页": ["otp_login_button"],
            "登录-验证码页": ["verification_code_input"],
            "登录-终态判断": ["continue_button"],
        }
        return mapping.get(stage, [])

    def _stage_dom_matched(self, stage: str) -> tuple[bool, str | None]:
        """通过 marker 或预期 target 粗略判断当前阶段是否已经到位。"""
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
                # 优先使用带超时的轻量探测，避免在等待循环里做重型定位。
                if hasattr(driver, "peek_target_with_timeout"):
                    driver.peek_target_with_timeout(target_name, probe_timeout_ms)
                else:
                    driver.peek_target(target_name)
                return True, target_name
            except Exception as exc:
                self._log(f"[{stage}] DOM 未命中 {target_name}: {exc}")
        return False, None

    def _wait_for_any_url(self, fragments: list[str], *, timeout: int, stage: str) -> str:
        """等待命中任一 URL 片段，并在过程中处理 DOM 命中与错误页重试。"""
        driver = self._driver
        if driver is None:
            raise RuntimeError("Codex GUI 驱动未初始化")
        self._log_step(stage, f"等待页面命中: {', '.join(fragments)}")
        deadline = time.time() + max(1, timeout)
        normalized = [fragment for fragment in fragments if str(fragment or "").strip()]
        while time.time() <= deadline:
            # 先检查 URL 是否已经进入目标页面，这是最直接也最可靠的判定。
            current_url = str(driver.read_current_url() or "").strip()
            for fragment in normalized:
                if fragment in current_url:
                    self._log(f"[{stage}] 已进入页面: {current_url}")
                    return current_url
            # 对某些页面切换，URL 可能尚未改变或无法稳定读取，因此用 DOM/marker 作为补充信号。
            dom_matched, matched_target = self._stage_dom_matched(stage)
            if dom_matched:
                self._log(
                    f"[{stage}] 通过 DOM 命中判定页面已切换: target={matched_target}, current_url={current_url}"
                )
                return current_url
            # 某些异常页面会卡住流程，这里在等待循环中顺带做错误页重试。
            if self._is_retry_page(current_url):
                self._handle_retry_page(stage)
            # 在等待期间执行轻量 wander，保持与原 GUI 行为一致。
            driver.wander_while_waiting(stage)
            time.sleep(self._stage_probe_interval_seconds())
        joined = ", ".join(normalized)
        raise RuntimeError(f"[{stage}] 等待页面超时，未进入目标地址片段: {joined}")

    def _wait_for_stage_ready(self, stage: str, *, timeout: int) -> str:
        """等待阶段文本 marker 或目标控件命中，不用 URL 命中提前放行。"""
        driver = self._driver
        if driver is None:
            raise RuntimeError("Codex GUI 驱动未初始化")
        self._log_step(stage, "等待页面阶段就绪")
        started_at = time.perf_counter()
        deadline = time.time() + max(1, timeout)
        while time.time() <= deadline:
            dom_matched, matched_target = self._stage_dom_matched(stage)
            if dom_matched:
                current_url = ""
                if not self._is_pywinauto_mode():
                    current_url = str(driver.read_current_url() or "").strip()
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                self._log(
                    f"[{stage}] 页面阶段就绪: target={matched_target}, current_url={current_url}, elapsed={elapsed_ms:.1f}ms"
                )
                return current_url
            self._retry_page_from_url_after_marker_window(stage, started_at=started_at)
            driver.wander_while_waiting(stage)
            time.sleep(self._stage_probe_interval_seconds())
        raise RuntimeError(f"[{stage}] 等待页面阶段就绪超时")

    def _wait_for_url(self, fragment: str, *, timeout: int, stage: str) -> str:
        """统一等待页面切换；pywinauto 模式使用 marker，Playwright 模式优先 URL。"""
        if str(self.extra_config.get("codex_gui_target_detector") or "").strip().lower() == "pywinauto":
            # 在 pywinauto 模式下 URL 读取不稳定，因此完全退化为 marker 等待。
            self._wait_for_stage_marker(stage, timeout=timeout)
            return str(fragment or "").strip()
        return self._wait_for_any_url([fragment], timeout=timeout, stage=stage)

    def _is_consent_url(self, current_url: str) -> bool:
        """判断当前 URL 是否已经处于 Codex consent 页面。"""
        return "/sign-in-with-chatgpt/codex/consent" in str(current_url or "")

    def _page_marker_match(self, stage: str) -> bool:
        """通过 driver 的 marker 能力判断当前页面文本是否命中指定阶段。"""
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
        """判断当前是否运行在 pywinauto 检测模式。"""
        return str(self.extra_config.get("codex_gui_target_detector") or "").strip().lower() == "pywinauto"

    def _marker_retry_window_seconds(self) -> float:
        """读取 marker 等待期间允许开始检查错误页的时间窗口。"""
        value = self.extra_config.get("codex_gui_stage_marker_retry_window_seconds", 15)
        try:
            return max(0.0, float(value or 15))
        except Exception:
            return 15.0

    def _retry_page_from_url_after_marker_window(self, stage: str, *, started_at: float) -> bool:
        """在 marker 等待期间，基于 URL 兜底检查是否落入错误重试页。"""
        driver = self._driver
        if driver is None:
            raise RuntimeError("Codex GUI 驱动未初始化")
        if self._is_pywinauto_mode():
            elapsed_seconds = time.perf_counter() - started_at
            # pywinauto 模式下先给 marker 一段独占判定窗口，避免过早把正常页误判成错误页。
            if elapsed_seconds < self._marker_retry_window_seconds():
                return False
        current_url = str(driver.read_current_url() or "").strip()
        if self._is_retry_page(current_url):
            self._handle_retry_page(stage)
            return True
        return False

    def _wait_for_stage_marker(self, stage: str, *, timeout: int) -> None:
        """等待页面文本 marker 全部命中。"""
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
            # marker 未命中时继续执行错误页检查与轻量 wander。
            self._retry_page_from_url_after_marker_window(stage, started_at=started_at)
            driver.wander_while_waiting(stage)
            time.sleep(self._stage_probe_interval_seconds())
        raise RuntimeError(f"[{stage}] 等待页面文本命中超时")

    def _wait_for_registration_otp_submit_outcome(self, *, timeout: int) -> str:
        """在 pywinauto 模式下等待注册 OTP 提交后的结果。"""
        wrong_code_stage = "注册-验证码错误"
        success_stage = "注册-about-you"
        driver = self._driver
        if driver is None:
            raise RuntimeError("Codex GUI 驱动未初始化")
        self._log_step("注册-验证码提交后判定", "等待 about-you 或 验证码错误")
        started_at = time.perf_counter()
        deadline = time.time() + max(1, timeout)
        while time.time() <= deadline:
            if self._page_marker_match(wrong_code_stage):
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                self._log(f"[注册-验证码提交后判定] 命中验证码错误: elapsed={elapsed_ms:.1f}ms")
                return "wrong-code"
            if self._page_marker_match(success_stage):
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                self._log(f"[注册-验证码提交后判定] 命中 about-you: elapsed={elapsed_ms:.1f}ms")
                return "success"
            self._retry_page_from_url_after_marker_window("注册-验证码提交后判定", started_at=started_at)
            driver.wander_while_waiting("注册-验证码提交后判定")
            time.sleep(self._stage_probe_interval_seconds())
        raise RuntimeError("[注册-验证码提交后判定] 等待提交结果超时")

    def _wait_for_registration_password_submit_outcome(self, *, timeout: int) -> str:
        """在 pywinauto 模式下等待注册密码提交后的结果。"""
        hard_fail_stage = "注册-密码页-create-failed"
        success_stage = "注册-验证码页"
        driver = self._driver
        if driver is None:
            raise RuntimeError("Codex GUI 驱动未初始化")
        self._log_step("注册-密码提交后判定", "等待验证码页或创建账号失败提示")
        started_at = time.perf_counter()
        deadline = time.time() + max(1, timeout)
        while time.time() <= deadline:
            if self._page_marker_match(hard_fail_stage):
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                self._log(f"[注册-密码提交后判定] create-account-failed 命中: elapsed={elapsed_ms:.1f}ms")
                raise RegistrationHardFailureError("创建帐户失败，请重试")
            if self._page_marker_match(success_stage):
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                self._log(f"[注册-密码提交后判定] 命中验证码页: elapsed={elapsed_ms:.1f}ms")
                return "success"
            self._retry_page_from_url_after_marker_window("注册-密码提交后判定", started_at=started_at)
            driver.wander_while_waiting("注册-密码提交后判定")
            time.sleep(self._stage_probe_interval_seconds())
        raise RuntimeError("[注册-密码提交后判定] 等待提交结果超时")

    def _wait_for_terminal_outcome(self, *, prefix: str, timeout: int) -> str:
        """等待终态，当前只接受 consent 或 add-phone 两种结果。"""
        add_stage = f"{prefix}-终态判断-add/phone"
        consent_stage = f"{prefix}-终态判断-consent"
        driver = self._driver
        if driver is None:
            raise RuntimeError("Codex GUI 驱动未初始化")
        self._log_step(f"{prefix}-终态判断", "等待终态页面命中")
        started_at = time.perf_counter()
        deadline = time.time() + max(1, timeout)
        while time.time() <= deadline:
            # 终态优先看 consent，再看 add-phone，顺序体现了成功优先原则。
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

    def _wait_for_registration_profile_disappear_or_terminal(self, *, timeout: int) -> str:
        """官网注册中，about-you 的年龄提示消失即可视为账号创建完成。"""
        driver = self._driver
        if driver is None:
            raise RuntimeError("Codex GUI 驱动未初始化")
        self._log_step("注册-资料提交后判定", "等待年龄提示消失或终态页面命中")
        started_at = time.perf_counter()
        deadline = time.time() + max(1, timeout)
        while time.time() <= deadline:
            if self._page_marker_match("注册-终态判断-consent"):
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                self._log(f"[注册-资料提交后判定] consent 命中: elapsed={elapsed_ms:.1f}ms")
                return "consent"
            if self._page_marker_match("注册-终态判断-add/phone"):
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                self._log(f"[注册-资料提交后判定] add-phone 命中: elapsed={elapsed_ms:.1f}ms")
                return "add-phone"
            if not self._page_marker_match("注册-about-you"):
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                self._log(f"[注册-资料提交后判定] 年龄提示已消失，账号创建完成: elapsed={elapsed_ms:.1f}ms")
                return "created"
            self._retry_page_from_url_after_marker_window("注册-资料提交后判定", started_at=started_at)
            driver.wander_while_waiting("注册-资料提交后判定")
            time.sleep(self._stage_probe_interval_seconds())
        raise RuntimeError("[注册-资料提交后判定] 等待年龄提示消失超时")

    def _wait_for_oauth_success_page(self, prefix: str, *, timeout: int) -> None:
        """等待 OAuth 成功标志页并标记登录完成。"""
        stage = f"{prefix}-成功标志页"
        self._wait_for_stage_marker(stage, timeout=timeout)
        self._oauth_login_completed = True
        self._log(f"[{prefix}] OAuth 成功标志页已命中")

    def _click_consent_continue(self, *, prefix: str, stage: str) -> None:
        driver = self._driver
        if driver is None:
            raise RuntimeError("Codex GUI 椹卞姩鏈垵濮嬪寲")
        if self._should_select_personal_account_before_consent_continue():
            self._run_action(
                f"[{stage}] consent 页面选择个人帐户",
                lambda: driver.click_named_target("personal_account_option"),
            )
        self._run_action(
            f"[{stage}] 鍛戒腑 consent 椤甸潰锛岀偣鍑荤户缁畬鎴?OAuth 鐧诲綍",
            lambda: driver.click_named_target("continue_button"),
        )

    def _complete_oauth_if_on_consent(self, stage: str) -> bool:
        """如果当前就在 consent 页面，则直接点击继续完成 OAuth。"""
        driver = self._driver
        if driver is None:
            raise RuntimeError("Codex GUI 驱动未初始化")
        current_url = str(driver.read_current_url() or "").strip()
        # 只有真正命中 consent URL 才允许执行继续按钮，避免误点其它页面的 continue。
        if not self._is_consent_url(current_url):
            return False
        if self._should_select_personal_account_before_consent_continue():
            self._run_action(
                f"[{stage}] consent 页面选择个人帐户",
                lambda: driver.click_named_target("personal_account_option"),
            )
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
        """判断当前 URL 是否属于需要点击重试的错误页。"""
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
        """点击错误页上的重试按钮，并在必要时重放上一动作。"""
        if self._driver is None:
            raise RuntimeError("Codex GUI 驱动未初始化")
        retry_target = (self.extra_config.get("codex_gui_retry_target") or "retry_button").strip()
        self._log(f"[{stage}] 命中错误页，尝试点击重试")
        driver = self._driver
        if driver is None:
            raise RuntimeError("Codex GUI 驱动未初始化")
        driver.click_named_target(retry_target)
        # 如果之前记录过可重放动作，这里会在点击重试后继续推进原步骤。
        if self._last_retry_action is not None:
            self._last_retry_action()

    def _run_action(self, description: str, action: Callable[[], None]) -> None:
        """统一执行一个 GUI 动作，并把它登记为可重放动作。"""
        self._log(description)
        self._last_retry_action = action
        action()

    def _collect_verification_code(
        self,
        adapter: EmailServiceAdapter,
        *,
        stage: str,
    ) -> str:
        """拉取验证码；在 pywinauto 模式下采用更积极的重发策略。"""
        driver = self._driver
        if driver is None:
            raise RuntimeError("Codex GUI 驱动未初始化")
        detector_kind = str(self.extra_config.get("codex_gui_target_detector") or "").strip().lower()
        otp_sent_at = time.time()
        if detector_kind == "pywinauto":
            # pywinauto 模式下无法像 DOM 那样快速探测页面状态，因此使用更长的重发与轮询策略。
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
                        otp_sent_at=otp_sent_at,
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
                # 只有在仍有剩余尝试次数时，才触发“重新发送电子邮件”。
                self._log(f"[{stage}] {wait_seconds:.1f}s 内未收到验证码，点击“重新发送电子邮件”")
                self._run_action(
                    f"[{stage}] 点击重新发送邮件",
                    lambda: driver.click_named_target(resend_target),
                )
            raise RuntimeError(f"[{stage}] 多次重发后仍未收到验证码，判定当前 OAuth 失败")
        resend_timeout = self._wait_timeout("codex_gui_otp_wait_seconds", 55)
        resend_attempts = self._wait_timeout("codex_gui_otp_max_resends", 1)
        for attempt in range(resend_attempts + 1):
            # Playwright 路径按统一超时等待 OTP，并在必要时触发一次或多次重发。
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
        raise RuntimeError(f"[{stage}] 等待验证码失败")

    def _run_registration_flow(self, auth_url: str, identity: CodexGUIIdentity, adapter: EmailServiceAdapter) -> None:
        """构建上下文并驱动注册 workflow。"""
        ctx = self._build_flow_context(identity=identity, auth_url=auth_url, email_adapter=adapter)
        result = self._registration_workflow.run(self, ctx)
        self._oauth_login_completed = ctx.oauth_login_completed
        if result.terminal_state:
            self._log(f"[注册] 终态: {result.terminal_state}")

    def _run_login_flow(self, auth_url: str, identity: CodexGUIIdentity, adapter: EmailServiceAdapter) -> None:
        """构建上下文并驱动登录补偿 workflow。"""
        ctx = self._build_flow_context(identity=identity, auth_url=auth_url, email_adapter=adapter)
        result = self._login_workflow.run(self, ctx)
        self._oauth_login_completed = ctx.oauth_login_completed
        if result.terminal_state:
            self._log(f"[登录] 终态: {result.terminal_state}")

    def _run_login_workflow_with_context(self, ctx: CodexGUIFlowContext) -> None:
        result = self._login_workflow.run(self, ctx)
        self._oauth_login_completed = ctx.oauth_login_completed
        terminal_state = getattr(result, "terminal_state", "") or ctx.terminal_state
        if terminal_state:
            self._log(f"[登录] 终态: {terminal_state}")
        ctx.oauth_login_result = {
            "success": bool(self._oauth_login_completed),
            "stage": "oauth_login",
            "terminal_state": terminal_state,
            "detail": "oauth_login_completed" if self._oauth_login_completed else "oauth_login_not_completed",
        }

    def _team_workspace_id(self) -> str:
        return str(
            self.extra_config.get("chatgpt_team_workspace_id")
            or self.extra_config.get("codex_gui_team_workspace_id")
            or self.extra_config.get("team_workspace_id")
            or ""
        ).strip()

    def _team_account_config(self) -> dict[str, Any]:
        configured = self.extra_config.get("chatgpt_team_member_account") or self.extra_config.get(
            "codex_gui_team_member_account"
        )
        if isinstance(configured, dict):
            return dict(configured)
        email = str(
            self.extra_config.get("chatgpt_team_member_email")
            or self.extra_config.get("codex_gui_team_member_email")
            or self.extra_config.get("cloudmail_team_account_email")
            or ""
        ).strip()
        credential = str(
            self.extra_config.get("chatgpt_team_member_credential")
            or self.extra_config.get("codex_gui_team_member_credential")
            or self.extra_config.get("cloudmail_team_account_password")
            or ""
        ).strip()
        return {"email": email, "credential": credential}

    def _team_remove_after_login_enabled(self) -> bool:
        return _parse_bool_config(
            self.extra_config.get(
                "chatgpt_team_remove_after_login",
                self.extra_config.get("codex_gui_team_remove_after_login", True),
            ),
            default=True,
        )

    def _should_select_personal_account_before_consent_continue(self) -> bool:
        team_account = self._team_account_config()
        return self._team_remove_after_login_enabled() and bool(str(team_account.get("email") or "").strip())

    def _cleanup_retry_attempts(self) -> int:
        value = self.extra_config.get("chatgpt_team_cleanup_max_attempts", self.extra_config.get("codex_gui_team_cleanup_max_attempts", 3))
        try:
            return max(1, int(value or 3))
        except Exception:
            return 3

    def _cleanup_retry_delay_seconds(self) -> float:
        value = self.extra_config.get("chatgpt_team_cleanup_retry_delay_seconds", self.extra_config.get("codex_gui_team_cleanup_retry_delay_seconds", 1.0))
        try:
            return max(0.0, float(value or 0.0))
        except Exception:
            return 1.0

    def _enroll_team_workspace(self, ctx: CodexGUIFlowContext) -> ChatGPTTeamWorkspaceResult:
        workspace_id = self._team_workspace_id()
        team_account = self._team_account_config()
        inviter = self.extra_config.get("chatgpt_team_workspace_inviter")
        typed_inviter = cast(Callable[..., ChatGPTTeamWorkspaceResult] | None, inviter if callable(inviter) else None)
        self._log_step("Team 工作空间", "加入新注册账号")
        result = invite_chatgpt_team_member(
            member_email=ctx.identity.email,
            workspace_id=workspace_id,
            team_account=team_account,
            inviter=typed_inviter,
            logger=self._log,
            proxy_url=self.proxy_url,
        )
        ctx.workspace_enroll_result = result.as_metadata("workspace_enroll")
        if result.success and self._team_remove_after_login_enabled():
            ctx.cleanup_required = True
        return result

    def _cleanup_team_workspace_membership(self, ctx: CodexGUIFlowContext) -> ChatGPTTeamWorkspaceResult:
        workspace_id = self._team_workspace_id()
        team_account = self._team_account_config()
        remover = self.extra_config.get("chatgpt_team_workspace_remover")
        typed_remover = cast(Callable[..., ChatGPTTeamWorkspaceResult] | None, remover if callable(remover) else None)
        self._log_step("Team 工作空间", "移除新注册账号")
        result = remove_chatgpt_team_member_with_retry(
            member_email=ctx.identity.email,
            workspace_id=workspace_id,
            team_account=team_account,
            max_attempts=self._cleanup_retry_attempts(),
            retry_delay_seconds=self._cleanup_retry_delay_seconds(),
            remover=typed_remover,
            logger=self._log,
            proxy_url=self.proxy_url,
        )
        ctx.workspace_cleanup_result = result.as_metadata("workspace_cleanup")
        ctx.cleanup_retry_count = result.attempts
        compensation_context = result.payload.get("compensation_context")
        if isinstance(compensation_context, dict):
            ctx.cleanup_compensation_context = dict(compensation_context)
        return result

    def _run_official_signup_flow(self, auth_url: str, identity: CodexGUIIdentity, adapter: EmailServiceAdapter) -> CodexGUIFlowContext:
        ctx = self._build_flow_context(identity=identity, auth_url=auth_url, email_adapter=adapter)
        self._official_signup_workflow.run(self, ctx)
        tail_result = self._registration_workflow.run_tail_after_password(self, ctx)
        self._oauth_login_completed = ctx.oauth_login_completed
        tail_terminal_state = getattr(tail_result, "terminal_state", "") or ctx.terminal_state
        if tail_terminal_state:
            self._log(f"[注册] 终态: {tail_terminal_state}")
        enroll_result = self._enroll_team_workspace(ctx)
        if not enroll_result.success:
            raise RuntimeError(f"工作空间加入阶段错误: {enroll_result.detail}")
        login_error: Exception | None = None
        try:
            if not self._oauth_login_completed:
                self._run_login_workflow_with_context(ctx)
            else:
                ctx.oauth_login_result = {
                    "success": True,
                    "stage": "oauth_login",
                    "terminal_state": ctx.terminal_state,
                    "detail": "completed_during_registration_tail",
                }
            if not self._oauth_login_completed:
                raise RuntimeError("登录流程结束后未完成 OAuth 登录")
        except Exception as exc:
            login_error = exc
            ctx.oauth_login_result = {
                "success": False,
                "stage": "oauth_login",
                "terminal_state": ctx.terminal_state,
                "detail": str(exc),
            }
        if not self._team_remove_after_login_enabled():
            ctx.cleanup_required = False
            ctx.workspace_cleanup_result = {
                "workspace_cleanup_success": False,
                "workspace_cleanup_skipped": True,
                "workspace_cleanup_detail": "team_remove_after_login_disabled",
            }
            if login_error is not None:
                raise login_error
            return ctx
        cleanup_result = self._cleanup_team_workspace_membership(ctx)
        if not cleanup_result.success:
            original_stage = "oauth_login" if login_error is not None else ""
            detail = cleanup_result.detail or "workspace cleanup failed"
            raise RuntimeError(f"工作空间清理阶段错误: {detail}; original_failure_stage={original_stage}")
        if login_error is not None:
            raise login_error
        return ctx

    def run(self) -> RegistrationResult:
        """执行完整 GUI 注册/登录链路，并返回统一结果。"""
        result = self._initialize_run_result()
        auth_url = ""
        state = ""
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

            # 先走注册链路，只有在注册未完成 OAuth 时才进入登录补偿。
            self._oauth_login_completed = False
            ctx: CodexGUIFlowContext | None = None
            if self._variant_resolution.effective_variant == CODEX_GUI_VARIANT_OFFICIAL_SIGNUP:
                ctx = self._run_official_signup_flow(auth_url, identity, adapter)
            else:
                ctx = self._build_flow_context(identity=identity, auth_url=auth_url, email_adapter=adapter)
                if self._variant_resolution.fallback_reason:
                    self._log(
                        f"[Codex GUI] 官网注册变体回退默认 GUI 链路: {self._variant_resolution.fallback_reason}"
                    )
                result_step = self._registration_workflow.run(self, ctx)
                self._oauth_login_completed = ctx.oauth_login_completed
                if result_step.terminal_state:
                    self._log(f"[注册] 终态: {result_step.terminal_state}")
            if self._oauth_login_completed:
                self._log("注册阶段完成，OAuth 登录已成功")
            else:
                self._log("注册阶段完成，已到达 add-phone 页面")
            if not self._oauth_login_completed and self._variant_resolution.effective_variant != CODEX_GUI_VARIANT_OFFICIAL_SIGNUP:
                self._run_login_workflow_with_context(ctx)
                if self._oauth_login_completed:
                    self._log("登录阶段完成，OAuth 登录已成功")
                else:
                    # 登录补偿结束后仍未完成 OAuth，说明当前 GUI 方案整体失败。
                    raise RuntimeError("登录流程结束后未完成 OAuth 登录")

            return self._finalize_success_result(result, identity=identity, auth_state=state, auth_url=auth_url, ctx=ctx)
        except TaskInterruption:
            raise
        except Exception as exc:
            self._log(f"Codex GUI 注册/登录流程失败: {exc}", "error")
            result.error_message = str(exc)
            self._attach_failure_metadata(result, error=exc, auth_state=state, auth_url=auth_url)
            return result
        finally:
            # 无论成功或失败，都尽量关闭 driver，避免遗留浏览器资源。
            driver = self._driver
            if driver is not None:
                try:
                    driver.close()
                except Exception as exc:
                    self._log(f"关闭 Codex GUI 浏览器会话失败（忽略）: {exc}")
