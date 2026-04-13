from __future__ import annotations

from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.base import BaseFlowStep
from platforms.chatgpt.codex_gui.steps.common import input_and_click_then_wait, require_driver, require_non_empty, resolve_wait_timeout, set_current_stage, verify_success
from platforms.chatgpt.codex_gui.steps.metadata import StepMetadata
from platforms.chatgpt.codex_gui.steps.recovery import retry_step_or_abort


class SubmitRegistrationEmailStep(BaseFlowStep):
    """Original mapping: 输入 email_input、点击 continue_button、等待密码页。"""

    step_id = "registration.submit_email"
    stage_name = "注册-密码页"
    max_attempts = 2
    metadata = StepMetadata(
        step_id=step_id,
        stage_name=stage_name,
        intent="输入注册邮箱并提交到密码页",
        legacy_mapping="旧 engine: input email_input -> click continue_button -> wait /create-account/password",
        expected_url_fragment="/create-account/password",
        expected_targets=("email_input", "continue_button"),
    )

    def precheck(self, engine, ctx) -> None:
        """确保邮箱字段存在且 driver 可执行输入。"""
        require_driver(engine)
        require_non_empty(ctx.identity.email, field_name="identity.email")

    def prepare(self, engine, ctx) -> None:
        """写入当前阶段。"""
        set_current_stage(ctx, self.stage_name)

    def execute(self, engine, ctx):
        """输入邮箱后点击继续，推进到密码页。"""
        driver = require_driver(engine)
        wait_timeout = resolve_wait_timeout(engine)
        matched_url = input_and_click_then_wait(
            engine,
            driver,
            input_label="[注册] 输入邮箱地址",
            input_target="email_input",
            input_value=ctx.identity.email,
            click_label="[注册] 点击继续按钮",
            click_target="continue_button",
            fragment="/create-account/password",
            timeout=wait_timeout,
            stage=self.stage_name,
        )
        return FlowStepResult(success=True, stage_name=self.stage_name, matched_url=matched_url)

    def verify(self, engine, ctx, result) -> None:
        """验证邮箱提交步骤成功。"""
        verify_success(result, step_id=self.step_id)

    def on_error(self, engine, ctx, error: Exception):
        """邮箱输入/跳转失败时按整步重试处理。"""
        return retry_step_or_abort(error=error, attempt=ctx.step_attempts.get(self.step_id, 1), max_attempts=self.max_attempts)
