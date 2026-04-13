from __future__ import annotations

from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.base import BaseFlowStep
from platforms.chatgpt.codex_gui.steps.common import click_and_wait_for_url, require_driver, resolve_wait_timeout, set_current_stage, verify_success
from platforms.chatgpt.codex_gui.steps.metadata import StepMetadata
from platforms.chatgpt.codex_gui.steps.recovery import retry_last_action_or_abort


class SwitchToOtpLoginStep(BaseFlowStep):
    """Original mapping: 点击 otp_login_button，切到 email-verification。"""

    step_id = "login.switch_to_otp"
    stage_name = "登录-验证码页"
    max_attempts = 2
    metadata = StepMetadata(
        step_id=step_id,
        stage_name=stage_name,
        intent="切换到一次性验证码登录",
        legacy_mapping="旧 engine: click otp_login_button -> wait /email-verification",
        expected_url_fragment="/email-verification",
        expected_targets=("otp_login_button",),
    )

    def precheck(self, engine, ctx) -> None:
        require_driver(engine)

    def prepare(self, engine, ctx) -> None:
        set_current_stage(ctx, self.stage_name)

    def execute(self, engine, ctx):
        driver = require_driver(engine)
        wait_timeout = resolve_wait_timeout(engine)
        matched_url = click_and_wait_for_url(
            engine,
            driver,
            click_label="[登录] 切换到一次性验证码登录",
            target_name="otp_login_button",
            fragment="/email-verification",
            timeout=wait_timeout,
            stage=self.stage_name,
        )
        return FlowStepResult(success=True, stage_name=self.stage_name, matched_url=matched_url)

    def verify(self, engine, ctx, result) -> None:
        verify_success(result, step_id=self.step_id)

    def on_error(self, engine, ctx, error: Exception):
        return retry_last_action_or_abort(error=error, attempt=ctx.step_attempts.get(self.step_id, 1), max_attempts=self.max_attempts)
