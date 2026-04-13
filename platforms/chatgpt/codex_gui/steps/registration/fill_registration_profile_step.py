from __future__ import annotations

from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.base import BaseFlowStep
from platforms.chatgpt.codex_gui.steps.common import require_driver, require_non_empty, run_named_action, set_current_stage, verify_success
from platforms.chatgpt.codex_gui.steps.metadata import StepMetadata
from platforms.chatgpt.codex_gui.steps.recovery import retry_step_or_abort


class FillRegistrationProfileStep(BaseFlowStep):
    """Original mapping: 输入 fullname_input 与 age_input。"""

    step_id = "registration.fill_profile"
    stage_name = "注册-about-you"
    max_attempts = 2
    metadata = StepMetadata(
        step_id=step_id,
        stage_name=stage_name,
        intent="填写全名与年龄",
        legacy_mapping="旧 engine: input fullname_input + age_input",
        expected_targets=("fullname_input", "age_input"),
    )

    def precheck(self, engine, ctx) -> None:
        require_driver(engine)
        require_non_empty(ctx.identity.full_name, field_name="identity.full_name")

    def prepare(self, engine, ctx) -> None:
        set_current_stage(ctx, self.stage_name)

    def execute(self, engine, ctx):
        driver = require_driver(engine)
        run_named_action(engine, "[注册] 输入全名", lambda: driver.input_text("fullname_input", ctx.identity.full_name))
        run_named_action(engine, "[注册] 输入年龄", lambda: driver.input_text("age_input", str(ctx.identity.age)))
        return FlowStepResult(success=True, stage_name=self.stage_name)

    def verify(self, engine, ctx, result) -> None:
        verify_success(result, step_id=self.step_id)

    def on_error(self, engine, ctx, error: Exception):
        return retry_step_or_abort(error=error, attempt=ctx.step_attempts.get(self.step_id, 1), max_attempts=self.max_attempts)
