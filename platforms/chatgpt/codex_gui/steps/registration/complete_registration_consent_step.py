from __future__ import annotations

from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.base import BaseFlowStep
from platforms.chatgpt.codex_gui.steps.common import require_driver, resolve_wait_timeout, run_named_action, set_current_stage, verify_success
from platforms.chatgpt.codex_gui.steps.metadata import StepMetadata
from platforms.chatgpt.codex_gui.steps.recovery import abort_flow


class CompleteRegistrationConsentStep(BaseFlowStep):
    """Original mapping: 如果注册终态是 consent，则点击继续并等待成功标志页。"""

    step_id = "registration.complete_consent"
    stage_name = "注册-成功标志页"
    metadata = StepMetadata(
        step_id=step_id,
        stage_name=stage_name,
        intent="若终态为 consent，则点击继续完成 OAuth",
        legacy_mapping="旧 engine: consent -> click continue_button -> wait success marker",
        expected_targets=("continue_button",),
    )

    def precheck(self, engine, ctx) -> None:
        require_driver(engine)

    def prepare(self, engine, ctx) -> None:
        set_current_stage(ctx, self.stage_name)

    def execute(self, engine, ctx):
        driver = require_driver(engine)
        wait_timeout = resolve_wait_timeout(engine)
        if ctx.terminal_state != "consent":
            return FlowStepResult(success=True, stage_name=self.stage_name, terminal_state=ctx.terminal_state)
        run_named_action(
            engine,
            "[注册] 命中 consent 页面，点击继续完成 OAuth 登录",
            lambda: driver.click_named_target("continue_button"),
        )
        engine._wait_for_oauth_success_page("注册", timeout=wait_timeout)
        ctx.oauth_login_completed = True
        return FlowStepResult(success=True, stage_name=self.stage_name, terminal_state="consent")

    def verify(self, engine, ctx, result) -> None:
        verify_success(result, step_id=self.step_id)

    def on_error(self, engine, ctx, error: Exception):
        return abort_flow(error)
