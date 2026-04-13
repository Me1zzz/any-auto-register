from __future__ import annotations

from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.base import BaseFlowStep
from platforms.chatgpt.codex_gui.steps.common import require_driver, require_non_empty, resolve_wait_timeout, set_current_stage, wait_for_expected_url, verify_success
from platforms.chatgpt.codex_gui.steps.metadata import StepMetadata
from platforms.chatgpt.codex_gui.steps.recovery import retry_step_or_abort


class OpenRegistrationAuthUrlStep(BaseFlowStep):
    """Original mapping: 注册阶段打开 OAuth 链接并等待进入 /log-in。"""

    step_id = "registration.open_auth_url"
    stage_name = "注册-打开登录页"
    max_attempts = 2
    metadata = StepMetadata(
        step_id=step_id,
        stage_name=stage_name,
        intent="打开 OAuth 授权链接并进入登录页",
        legacy_mapping="旧 engine: 打开 auth_url -> 等待 /log-in",
        expected_url_fragment="/log-in",
        expected_targets=("register_button", "continue_button"),
    )

    def precheck(self, engine, ctx) -> None:
        """确保授权链接与 driver 已就绪。"""
        require_driver(engine)
        require_non_empty(ctx.auth_url, field_name="auth_url")

    def prepare(self, engine, ctx) -> None:
        """把当前阶段写入上下文，便于日志与恢复判断。"""
        set_current_stage(ctx, self.stage_name)

    def execute(self, engine, ctx):
        """打开 OAuth 链接并等待登录页出现。"""
        driver = require_driver(engine)
        wait_timeout = resolve_wait_timeout(engine)
        # 记录步骤日志，帮助区分注册链路中的每个导航动作。
        engine._log_step("注册", "使用 Edge 最大化窗口打开 OAuth 授权链接")
        # 在注册链路中第一次打开授权地址，总是使用新导航而不是复用当前页面。
        driver.open_url(ctx.auth_url, reuse_current=False)
        # 只有命中 /log-in，后续步骤才能假设页面处于登录入口态。
        matched_url = wait_for_expected_url(engine, "/log-in", timeout=wait_timeout, stage=self.stage_name)
        return FlowStepResult(success=True, stage_name=self.stage_name, matched_url=matched_url)

    def verify(self, engine, ctx, result) -> None:
        """验证跳转结果存在且步骤成功。"""
        verify_success(result, step_id=self.step_id)
        require_non_empty(result.matched_url, field_name="matched_url")

    def on_error(self, engine, ctx, error: Exception):
        """打开授权页失败时按整步重试策略处理。"""
        return retry_step_or_abort(error=error, attempt=ctx.step_attempts.get(self.step_id, 1), max_attempts=self.max_attempts)
