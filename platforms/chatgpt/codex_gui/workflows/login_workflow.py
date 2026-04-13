from __future__ import annotations

from platforms.chatgpt.codex_gui.context import CodexGUIFlowContext
from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.login import (
    ConfirmLoginOtpStep,
    ReopenLoginAuthUrlStep,
    ResolveLoginTerminalStep,
    SubmitLoginEmailStep,
    SubmitLoginOtpStep,
    SwitchToOtpLoginStep,
)


class LoginWorkflow:
    def run(self, engine, ctx: CodexGUIFlowContext) -> FlowStepResult:
        steps = [
            ReopenLoginAuthUrlStep(),
            SubmitLoginEmailStep(),
            SwitchToOtpLoginStep(),
            SubmitLoginOtpStep(),
            ConfirmLoginOtpStep(),
            ResolveLoginTerminalStep(),
        ]
        step_index = {step.step_id: index for index, step in enumerate(steps)}
        last_result = FlowStepResult(success=True, stage_name="")
        current_index = 0
        while current_index < len(steps):
            step = steps[current_index]
            result = step.run(engine, ctx)
            if isinstance(result, FlowStepResult):
                last_result = result
            if ctx.pending_step_id:
                current_index = step_index.get(ctx.pending_step_id, current_index + 1)
                ctx.pending_step_id = ""
                continue
            current_index += 1
        return last_result
