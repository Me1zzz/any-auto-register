from __future__ import annotations

from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.base import BaseFlowStep
from platforms.chatgpt.codex_gui.steps.common import require_driver, resolve_wait_timeout, run_named_action, set_current_stage, verify_success, verify_terminal_state, wait_for_terminal
from platforms.chatgpt.codex_gui.steps.metadata import StepMetadata
from platforms.chatgpt.codex_gui.steps.recovery import retry_last_action_or_abort


class CompleteRegistrationStep(BaseFlowStep):
    """Original mapping: 点击 complete_account_button 并解析注册终态。"""

    step_id = "registration.complete_account"
    stage_name = "注册-终态判断"
    max_attempts = 2
    metadata = StepMetadata(
        step_id=step_id,
        stage_name=stage_name,
        intent="提交账户创建并解析注册终态",
        legacy_mapping="旧 engine: click complete_account_button -> wait terminal outcome",
        expected_targets=("complete_account_button",),
    )

    def precheck(self, engine, ctx) -> None:
        require_driver(engine)

    def prepare(self, engine, ctx) -> None:
        set_current_stage(ctx, self.stage_name)

    def execute(self, engine, ctx):
        driver = require_driver(engine)
        wait_timeout = resolve_wait_timeout(engine)
        run_named_action(engine, "[注册] 完成帐户创建", lambda: driver.click_named_target("complete_account_button"))
        terminal_state = wait_for_terminal(engine, prefix="注册", timeout=wait_timeout)
        ctx.terminal_state = terminal_state
        return FlowStepResult(success=True, stage_name=self.stage_name, terminal_state=terminal_state)

    def verify(self, engine, ctx, result) -> None:
        verify_success(result, step_id=self.step_id)
        verify_terminal_state(ctx, {"consent", "add-phone"}, step_id=self.step_id)

    def on_error(self, engine, ctx, error: Exception):
        return retry_last_action_or_abort(error=error, attempt=ctx.step_attempts.get(self.step_id, 1), max_attempts=self.max_attempts)
