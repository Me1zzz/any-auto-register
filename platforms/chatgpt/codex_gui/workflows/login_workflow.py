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
    """负责按顺序驱动登录补偿链路的步骤编排器。"""

    def run(self, engine, ctx: CodexGUIFlowContext) -> FlowStepResult:
        """依次执行登录步骤，并响应步骤级跳转请求。"""
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
            # 登录 workflow 的职责是排步骤，不直接承载每个步骤的细节实现。
            step = steps[current_index]
            result = step.run(engine, ctx)
            if isinstance(result, FlowStepResult):
                last_result = result
            if ctx.pending_step_id:
                # 若步骤要求跳转到别的登录步骤，在这里统一切换索引。
                current_index = step_index.get(ctx.pending_step_id, current_index + 1)
                ctx.pending_step_id = ""
                continue
            current_index += 1
        return last_result
