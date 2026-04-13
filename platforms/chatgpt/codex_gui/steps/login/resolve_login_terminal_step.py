from __future__ import annotations

from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.base import BaseFlowStep
from platforms.chatgpt.codex_gui.steps.common import require_driver, resolve_wait_timeout, run_named_action, set_current_stage, verify_success, verify_terminal_state, wait_for_terminal
from platforms.chatgpt.codex_gui.steps.metadata import StepMetadata
from platforms.chatgpt.codex_gui.steps.recovery import abort_flow


class ResolveLoginTerminalStep(BaseFlowStep):
    """Original mapping: 等待登录终态；若命中 consent，点击继续完成 OAuth。"""

    step_id = "login.resolve_terminal"
    stage_name = "登录-终态判断"
    max_attempts = 2
    metadata = StepMetadata(
        step_id=step_id,
        stage_name=stage_name,
        intent="等待登录终态并在 consent 时完成 OAuth",
        legacy_mapping="旧 engine: wait terminal outcome -> consent click continue -> wait success marker",
        expected_targets=("continue_button",),
    )

    def precheck(self, engine, ctx) -> None:
        require_driver(engine)

    def prepare(self, engine, ctx) -> None:
        set_current_stage(ctx, self.stage_name)

    def execute(self, engine, ctx):
        driver = require_driver(engine)
        wait_timeout = resolve_wait_timeout(engine)
        if ctx.oauth_login_completed:
            return FlowStepResult(success=True, stage_name=self.stage_name, terminal_state=ctx.terminal_state)
        terminal_state = wait_for_terminal(engine, prefix="登录", timeout=wait_timeout)
        ctx.terminal_state = terminal_state
        if terminal_state == "consent":
            run_named_action(
                engine,
                "[登录] 命中 consent 页面，点击继续完成 OAuth 登录",
                lambda: driver.click_named_target("continue_button"),
            )
            engine._wait_for_oauth_success_page("登录", timeout=wait_timeout)
            ctx.oauth_login_completed = True
            return FlowStepResult(success=True, stage_name=self.stage_name, terminal_state=terminal_state)
        if terminal_state == "add-phone":
            raise RuntimeError("登录流程进入 add-phone 页面，未进入 Codex consent 页面")
        return FlowStepResult(success=True, stage_name=self.stage_name, terminal_state=terminal_state)

    def verify(self, engine, ctx, result) -> None:
        verify_success(result, step_id=self.step_id)
        if not ctx.oauth_login_completed:
            verify_terminal_state(ctx, {"consent", "add-phone", ""}, step_id=self.step_id)

    def on_error(self, engine, ctx, error: Exception):
        return abort_flow(error)
