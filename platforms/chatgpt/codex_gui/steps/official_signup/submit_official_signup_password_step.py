from __future__ import annotations

from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.base import BaseFlowStep
from platforms.chatgpt.codex_gui.steps.common import require_driver, require_non_empty, resolve_wait_timeout, run_named_action, set_current_stage, verify_success, wait_for_expected_url
from platforms.chatgpt.codex_gui.steps.errors import RegistrationHardFailureError
from platforms.chatgpt.codex_gui.steps.metadata import StepMetadata
from platforms.chatgpt.codex_gui.steps.recovery import retry_last_action_or_abort


class SubmitOfficialSignupPasswordStep(BaseFlowStep):
    step_id = "official_signup.submit_password"
    stage_name = "官网注册-进入验证码页"
    max_attempts = 2
    metadata = StepMetadata(
        step_id=step_id,
        stage_name=stage_name,
        intent="在官网注册页输入密码并进入验证码页",
        legacy_mapping="new official signup: input official_signup_password_input -> continue -> email verification",
        expected_url_fragment="/email-verification",
        expected_targets=("official_signup_password_input", "official_signup_continue_button"),
    )

    def precheck(self, engine, ctx) -> None:
        require_driver(engine)
        require_non_empty(ctx.identity.password, field_name="identity.password")

    def prepare(self, engine, ctx) -> None:
        set_current_stage(ctx, self.stage_name)

    def execute(self, engine, ctx):
        driver = require_driver(engine)
        wait_timeout = resolve_wait_timeout(engine)
        run_named_action(engine, "[官网注册] 输入密码", lambda: driver.input_text("official_signup_password_input", ctx.identity.password))
        run_named_action(engine, "[官网注册] 提交密码", lambda: driver.click_named_target("official_signup_continue_button"))
        if getattr(engine, "_is_pywinauto_mode", lambda: False)():
            engine._wait_for_registration_password_submit_outcome(timeout=wait_timeout)
            matched_url = "/email-verification"
        else:
            matched_url = wait_for_expected_url(engine, "/email-verification", timeout=wait_timeout, stage=self.stage_name)
        return FlowStepResult(success=True, stage_name=self.stage_name, matched_url=matched_url)

    def verify(self, engine, ctx, result) -> None:
        verify_success(result, step_id=self.step_id)

    def on_error(self, engine, ctx, error: Exception):
        if isinstance(error, RegistrationHardFailureError):
            return engine._build_abort_decision(error)
        return retry_last_action_or_abort(error=error, attempt=ctx.step_attempts.get(self.step_id, 1), max_attempts=self.max_attempts)
