from __future__ import annotations

from platforms.chatgpt.codex_gui.context import CodexGUIFlowContext
from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.official_signup import (
    ClickOfficialSignupFreeSignupStep,
    OpenOfficialSignupRuntimeProfileStep,
    SubmitOfficialSignupEmailStep,
)
from platforms.chatgpt.codex_gui.steps.registration.submit_registration_password_step import SubmitRegistrationPasswordStep


class OfficialSignupWorkflow:
    """负责官网注册密码提交前半段的步骤编排器。"""

    def __init__(self, steps=None):
        self._steps = list(steps) if steps is not None else [
            OpenOfficialSignupRuntimeProfileStep(),
            ClickOfficialSignupFreeSignupStep(),
            SubmitOfficialSignupEmailStep(),
            SubmitRegistrationPasswordStep(),
        ]

    def run(self, engine, ctx: CodexGUIFlowContext) -> FlowStepResult:
        step_index = {step.step_id: index for index, step in enumerate(self._steps)}
        last_result = FlowStepResult(success=True, stage_name="")
        current_index = 0
        while current_index < len(self._steps):
            step = self._steps[current_index]
            result = step.run(engine, ctx)
            if isinstance(result, FlowStepResult):
                last_result = result
            if ctx.pending_step_id:
                current_index = step_index.get(ctx.pending_step_id, current_index + 1)
                ctx.pending_step_id = ""
                continue
            current_index += 1
        ctx.official_signup_completed = True
        return last_result
