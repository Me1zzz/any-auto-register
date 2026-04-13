from __future__ import annotations

from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.base import BaseFlowStep
from platforms.chatgpt.codex_gui.steps.common import input_and_click_then_wait, require_driver, require_non_empty, resolve_wait_timeout, set_current_stage, verify_success
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
        require_driver(engine)
        require_non_empty(ctx.identity.password, field_name="identity.password")

    def prepare(self, engine, ctx) -> None:
        set_current_stage(ctx, self.stage_name)

    def execute(self, engine, ctx):
        driver = require_driver(engine)
        wait_timeout = resolve_wait_timeout(engine)
        matched_url = input_and_click_then_wait(
            engine,
            driver,
            input_label="[注册] 输入密码",
            input_target="password_input",
            input_value=ctx.identity.password,
            click_label="[注册] 提交密码",
            click_target="continue_button",
            fragment="/email-verification",
            timeout=wait_timeout,
            stage=self.stage_name,
        )
        return FlowStepResult(success=True, stage_name=self.stage_name, matched_url=matched_url)

    def verify(self, engine, ctx, result) -> None:
        verify_success(result, step_id=self.step_id)

    def on_error(self, engine, ctx, error: Exception):
        return retry_last_action_or_abort(error=error, attempt=ctx.step_attempts.get(self.step_id, 1), max_attempts=self.max_attempts)
