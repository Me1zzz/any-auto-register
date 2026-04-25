from __future__ import annotations

from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.base import BaseFlowStep
from platforms.chatgpt.codex_gui.steps.common import input_and_click_then_wait, require_driver, require_non_empty, resolve_wait_timeout, run_named_action, set_current_stage, verify_success
from platforms.chatgpt.codex_gui.steps.metadata import StepMetadata
from platforms.chatgpt.codex_gui.steps.recovery import retry_step_or_abort


class SubmitOfficialSignupEmailStep(BaseFlowStep):
    step_id = "official_signup.submit_email"
    stage_name = "官网注册-输入邮箱"
    max_attempts = 2
    metadata = StepMetadata(
        step_id=step_id,
        stage_name=stage_name,
        intent="在官网注册页输入新账号邮箱",
        legacy_mapping="new official signup: input official_signup_email_input -> continue",
        expected_url_fragment="/password",
        expected_targets=("official_signup_email_input", "official_signup_continue_button"),
    )

    def precheck(self, engine, ctx) -> None:
        require_driver(engine)
        require_non_empty(ctx.identity.email, field_name="identity.email")

    def prepare(self, engine, ctx) -> None:
        set_current_stage(ctx, self.stage_name)

    def execute(self, engine, ctx):
        driver = require_driver(engine)
        wait_timeout = resolve_wait_timeout(engine)
        if getattr(engine, "_is_pywinauto_mode", lambda: False)():
            run_named_action(engine, "[官网注册] 输入邮箱地址", lambda: driver.input_text("official_signup_email_input", ctx.identity.email))
            run_named_action(engine, "[官网注册] 提交邮箱", lambda: driver.click_named_target("official_signup_continue_button"))
            engine._wait_for_stage_marker("注册-密码页", timeout=wait_timeout)
            return FlowStepResult(success=True, stage_name=self.stage_name, matched_url="/password")
        matched_url = input_and_click_then_wait(
            engine,
            driver,
            input_label="[官网注册] 输入邮箱地址",
            input_target="official_signup_email_input",
            input_value=ctx.identity.email,
            click_label="[官网注册] 提交邮箱",
            click_target="official_signup_continue_button",
            fragment="/password",
            timeout=wait_timeout,
            stage=self.stage_name,
        )
        return FlowStepResult(success=True, stage_name=self.stage_name, matched_url=matched_url)

    def verify(self, engine, ctx, result) -> None:
        verify_success(result, step_id=self.step_id)

    def on_error(self, engine, ctx, error: Exception):
        return retry_step_or_abort(error=error, attempt=ctx.step_attempts.get(self.step_id, 1), max_attempts=self.max_attempts)
