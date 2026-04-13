from __future__ import annotations

from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.base import BaseFlowStep
from platforms.chatgpt.codex_gui.steps.common import collect_otp_code, input_and_click_then_wait, require_driver, require_non_empty, resolve_wait_timeout, set_current_stage, verify_success
from platforms.chatgpt.codex_gui.steps.metadata import StepMetadata
from platforms.chatgpt.codex_gui.steps.recovery import otp_abort


class SubmitRegistrationOtpStep(BaseFlowStep):
    """Original mapping: 拉取注册验证码、输入 verification_code_input、点击 continue、等待 about-you。"""

    step_id = "registration.collect_otp"
    stage_name = "注册-about-you"
    metadata = StepMetadata(
        step_id=step_id,
        stage_name=stage_name,
        intent="拉取注册验证码并提交到 about-you 页面",
        legacy_mapping="旧 engine: collect OTP -> input verification_code_input -> click continue_button -> wait /about-you",
        expected_url_fragment="/about-you",
        expected_targets=("verification_code_input", "continue_button"),
    )

    def precheck(self, engine, ctx) -> None:
        require_driver(engine)

    def prepare(self, engine, ctx) -> None:
        set_current_stage(ctx, self.stage_name)

    def execute(self, engine, ctx):
        driver = require_driver(engine)
        wait_timeout = resolve_wait_timeout(engine)
        register_code = collect_otp_code(engine, ctx.email_adapter, stage="注册")
        matched_url = input_and_click_then_wait(
            engine,
            driver,
            input_label="[注册] 输入邮箱验证码",
            input_target="verification_code_input",
            input_value=register_code,
            click_label="[注册] 提交验证码",
            click_target="continue_button",
            fragment="/about-you",
            timeout=wait_timeout,
            stage=self.stage_name,
        )
        return FlowStepResult(success=True, stage_name=self.stage_name, matched_url=matched_url, payload={"otp": register_code})

    def verify(self, engine, ctx, result) -> None:
        verify_success(result, step_id=self.step_id)
        require_non_empty(str(result.payload.get("otp") or ""), field_name="registration_otp")

    def on_error(self, engine, ctx, error: Exception):
        return otp_abort(error)
