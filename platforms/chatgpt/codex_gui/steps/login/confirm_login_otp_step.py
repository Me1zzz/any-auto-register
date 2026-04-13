from __future__ import annotations

from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.base import BaseFlowStep
from platforms.chatgpt.codex_gui.steps.common import require_driver, run_named_action, set_current_stage, verify_success
from platforms.chatgpt.codex_gui.steps.metadata import StepMetadata
from platforms.chatgpt.codex_gui.steps.recovery import retry_last_action_or_abort


class ConfirmLoginOtpStep(BaseFlowStep):
    """Original mapping: 若未直接命中 consent，则点击 continue_button 提交验证码。"""

    step_id = "login.submit_otp"
    stage_name = "登录-提交验证码后"
    max_attempts = 2
    metadata = StepMetadata(
        step_id=step_id,
        stage_name=stage_name,
        intent="若未直接命中 consent，则提交验证码",
        legacy_mapping="旧 engine: click continue_button after login OTP",
        expected_targets=("continue_button",),
    )

    def precheck(self, engine, ctx) -> None:
        """确保提交 OTP 前 driver 已可用。"""
        require_driver(engine)

    def prepare(self, engine, ctx) -> None:
        """写入当前阶段。"""
        set_current_stage(ctx, self.stage_name)

    def execute(self, engine, ctx):
        """当输入 OTP 后未直接进入 consent 时，显式点击继续提交。"""
        driver = require_driver(engine)
        if ctx.oauth_login_completed:
            # 若上一步已经直接命中 consent，这里不再重复点击，保持幂等。
            return FlowStepResult(success=True, stage_name=self.stage_name, terminal_state=ctx.terminal_state)
        run_named_action(engine, "[登录] 提交验证码", lambda: driver.click_named_target("continue_button"))
        if engine._complete_oauth_if_on_consent(self.stage_name):
            ctx.oauth_login_completed = True
            ctx.terminal_state = "consent"
        return FlowStepResult(success=True, stage_name=self.stage_name, terminal_state=ctx.terminal_state)

    def verify(self, engine, ctx, result) -> None:
        """验证 OTP 提交步骤成功。"""
        verify_success(result, step_id=self.step_id)

    def on_error(self, engine, ctx, error: Exception):
        """提交 OTP 失败时优先重放最后动作。"""
        return retry_last_action_or_abort(error=error, attempt=ctx.step_attempts.get(self.step_id, 1), max_attempts=self.max_attempts)
