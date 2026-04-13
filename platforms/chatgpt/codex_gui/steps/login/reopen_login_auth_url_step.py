from __future__ import annotations

from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.base import BaseFlowStep
from platforms.chatgpt.codex_gui.steps.common import require_driver, require_non_empty, resolve_wait_timeout, set_current_stage, wait_for_expected_url, verify_success
from platforms.chatgpt.codex_gui.steps.metadata import StepMetadata
from platforms.chatgpt.codex_gui.steps.recovery import retry_step_or_abort


class ReopenLoginAuthUrlStep(BaseFlowStep):
    """Original mapping: 登录补偿阶段重新打开 OAuth 链接并等待 /log-in。"""

    step_id = "login.reopen_auth_url"
    stage_name = "登录-打开登录页"
    max_attempts = 2
    metadata = StepMetadata(
        step_id=step_id,
        stage_name=stage_name,
        intent="重新打开 OAuth 链接进入登录页",
        legacy_mapping="旧 engine: reopen auth_url -> wait /log-in",
        expected_url_fragment="/log-in",
        expected_targets=("continue_button",),
    )

    def precheck(self, engine, ctx) -> None:
        """确保重新打开授权页前 driver 与 auth_url 已准备好。"""
        require_driver(engine)
        require_non_empty(ctx.auth_url, field_name="auth_url")

    def prepare(self, engine, ctx) -> None:
        """写入当前阶段。"""
        set_current_stage(ctx, self.stage_name)

    def execute(self, engine, ctx):
        """在现有窗口中重新打开授权页，进入登录补偿流程。"""
        driver = require_driver(engine)
        wait_timeout = resolve_wait_timeout(engine)
        engine._log_step("登录", "在当前 Edge 窗口中重新打开 OAuth 授权链接")
        driver.open_url(ctx.auth_url, reuse_current=True)
        matched_url = wait_for_expected_url(engine, "/log-in", timeout=wait_timeout, stage=self.stage_name)
        return FlowStepResult(success=True, stage_name=self.stage_name, matched_url=matched_url)

    def verify(self, engine, ctx, result) -> None:
        """验证登录入口页已打开。"""
        verify_success(result, step_id=self.step_id)

    def on_error(self, engine, ctx, error: Exception):
        """重新打开授权页失败时按整步重试。"""
        return retry_step_or_abort(error=error, attempt=ctx.step_attempts.get(self.step_id, 1), max_attempts=self.max_attempts)
