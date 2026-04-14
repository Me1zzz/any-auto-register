from __future__ import annotations

from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.base import BaseFlowStep
from platforms.chatgpt.codex_gui.steps.common import require_driver, require_non_empty, resolve_wait_timeout, run_named_action, set_current_stage, verify_success, wait_for_expected_url
from platforms.chatgpt.codex_gui.steps.errors import RegistrationHardFailureError
from platforms.chatgpt.codex_gui.steps.metadata import StepMetadata
from platforms.chatgpt.codex_gui.steps.recovery import retry_last_action_or_abort


class SubmitRegistrationPasswordStep(BaseFlowStep):
    """Original mapping: 输入 password_input、点击 continue_button、等待验证码页。"""

    step_id = "registration.submit_password"
    stage_name = "注册-验证码页"
    max_attempts = 2
    metadata = StepMetadata(
        step_id=step_id,
        stage_name=stage_name,
        intent="输入注册密码并进入验证码页",
        legacy_mapping="旧 engine: input password_input -> click continue_button -> wait /email-verification",
        expected_url_fragment="/email-verification",
        expected_targets=("password_input", "continue_button"),
    )

    def precheck(self, engine, ctx) -> None:
        """确保密码字段存在。"""
        require_driver(engine)
        require_non_empty(ctx.identity.password, field_name="identity.password")

    def prepare(self, engine, ctx) -> None:
        """写入当前阶段。"""
        set_current_stage(ctx, self.stage_name)

    def execute(self, engine, ctx):
        """输入密码并进入验证码页。"""
        driver = require_driver(engine)
        wait_timeout = resolve_wait_timeout(engine)
        run_named_action(engine, "[注册] 输入密码", lambda: driver.input_text("password_input", ctx.identity.password))
        run_named_action(engine, "[注册] 提交密码", lambda: driver.click_named_target("continue_button"))
        if getattr(engine, "_is_pywinauto_mode", lambda: False)():
            engine._wait_for_registration_password_submit_outcome(timeout=wait_timeout)
            matched_url = "/email-verification"
        else:
            matched_url = wait_for_expected_url(engine, "/email-verification", timeout=wait_timeout, stage=self.stage_name)
        return FlowStepResult(success=True, stage_name=self.stage_name, matched_url=matched_url)

    def verify(self, engine, ctx, result) -> None:
        """验证密码提交流程成功。"""
        verify_success(result, step_id=self.step_id)

    def on_error(self, engine, ctx, error: Exception):
        """密码提交失败时优先重放最后动作。"""
        if isinstance(error, RegistrationHardFailureError):
            return engine._build_abort_decision(error)
        return retry_last_action_or_abort(error=error, attempt=ctx.step_attempts.get(self.step_id, 1), max_attempts=self.max_attempts)
