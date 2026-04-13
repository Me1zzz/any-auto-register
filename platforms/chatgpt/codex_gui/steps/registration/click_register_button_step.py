from __future__ import annotations

from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.base import BaseFlowStep
from platforms.chatgpt.codex_gui.steps.common import click_and_wait_for_url, require_driver, resolve_wait_timeout, set_current_stage, verify_success
from platforms.chatgpt.codex_gui.steps.metadata import StepMetadata
from platforms.chatgpt.codex_gui.steps.recovery import retry_last_action_or_abort


class ClickRegisterButtonStep(BaseFlowStep):
    """Original mapping: 点击 register_button 并等待创建账户页。"""

    step_id = "registration.click_register"
    stage_name = "注册-创建账户页"
    max_attempts = 2
    metadata = StepMetadata(
        step_id=step_id,
        stage_name=stage_name,
        intent="点击注册按钮进入创建账户页",
        legacy_mapping="旧 engine: click register_button -> wait /create-account",
        expected_url_fragment="/create-account",
        expected_targets=("register_button",),
    )

    def precheck(self, engine, ctx) -> None:
        """确保点击注册按钮前 driver 已可用。"""
        require_driver(engine)

    def prepare(self, engine, ctx) -> None:
        """写入当前阶段。"""
        set_current_stage(ctx, self.stage_name)

    def execute(self, engine, ctx):
        """点击注册按钮并等待进入创建账号页。"""
        driver = require_driver(engine)
        wait_timeout = resolve_wait_timeout(engine)
        matched_url = click_and_wait_for_url(
            engine,
            driver,
            click_label="[注册] 点击注册按钮",
            target_name="register_button",
            fragment="/create-account",
            timeout=wait_timeout,
            stage=self.stage_name,
        )
        return FlowStepResult(success=True, stage_name=self.stage_name, matched_url=matched_url)

    def verify(self, engine, ctx, result) -> None:
        """验证点击与跳转结果成功。"""
        verify_success(result, step_id=self.step_id)

    def on_error(self, engine, ctx, error: Exception):
        """点击类错误优先尝试重放最后动作。"""
        return retry_last_action_or_abort(error=error, attempt=ctx.step_attempts.get(self.step_id, 1), max_attempts=self.max_attempts)
