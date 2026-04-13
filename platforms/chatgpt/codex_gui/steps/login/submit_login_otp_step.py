from __future__ import annotations

from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.base import BaseFlowStep
from platforms.chatgpt.codex_gui.steps.common import collect_otp_code, require_driver, require_non_empty, run_named_action, set_current_stage, verify_success
from platforms.chatgpt.codex_gui.steps.metadata import StepMetadata
from platforms.chatgpt.codex_gui.steps.recovery import otp_abort


class SubmitLoginOtpStep(BaseFlowStep):
    """Original mapping: 拉取登录 OTP，输入 verification_code_input，并尝试直接命中 consent。"""

    step_id = "login.collect_otp"
    stage_name = "登录-输入验证码后"
    metadata = StepMetadata(
        step_id=step_id,
        stage_name=stage_name,
        intent="拉取登录 OTP 并尝试直接命中 consent",
        legacy_mapping="旧 engine: collect login OTP -> input verification_code_input -> check consent",
        expected_targets=("verification_code_input",),
    )

    def precheck(self, engine, ctx) -> None:
        require_driver(engine)

    def prepare(self, engine, ctx) -> None:
        set_current_stage(ctx, self.stage_name)

    def execute(self, engine, ctx):
        driver = require_driver(engine)
        login_code = collect_otp_code(engine, ctx.email_adapter, stage="登录")
        run_named_action(engine, "[登录] 输入邮箱验证码", lambda: driver.input_text("verification_code_input", login_code))
        if engine._complete_oauth_if_on_consent(self.stage_name):
            ctx.oauth_login_completed = True
            ctx.terminal_state = "consent"
        return FlowStepResult(success=True, stage_name=self.stage_name, terminal_state=ctx.terminal_state, payload={"otp": login_code})

    def verify(self, engine, ctx, result) -> None:
        verify_success(result, step_id=self.step_id)
        require_non_empty(str(result.payload.get("otp") or ""), field_name="login_otp")

    def on_error(self, engine, ctx, error: Exception):
        return otp_abort(error)
