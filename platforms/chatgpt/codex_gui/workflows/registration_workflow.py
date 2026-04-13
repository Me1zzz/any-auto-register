from __future__ import annotations

from platforms.chatgpt.codex_gui.context import CodexGUIFlowContext
from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.registration import (
    ClickRegisterButtonStep,
    CompleteRegistrationConsentStep,
    CompleteRegistrationStep,
    FillRegistrationProfileStep,
    OpenRegistrationAuthUrlStep,
    SubmitRegistrationEmailStep,
    SubmitRegistrationOtpStep,
    SubmitRegistrationPasswordStep,
)


class RegistrationWorkflow:
    """负责按顺序驱动注册链路的步骤编排器。"""

    def run(self, engine, ctx: CodexGUIFlowContext) -> FlowStepResult:
        """依次执行注册步骤，并响应步骤级跳转请求。"""
        steps = [
            OpenRegistrationAuthUrlStep(),
            ClickRegisterButtonStep(),
            SubmitRegistrationEmailStep(),
            SubmitRegistrationPasswordStep(),
            SubmitRegistrationOtpStep(),
            FillRegistrationProfileStep(),
            CompleteRegistrationStep(),
            CompleteRegistrationConsentStep(),
        ]
        step_index = {step.step_id: index for index, step in enumerate(steps)}
        last_result = FlowStepResult(success=True, stage_name="")
        current_index = 0
        while current_index < len(steps):
            # 由步骤自身负责单步生命周期，这里只控制整体顺序和跳转。
            step = steps[current_index]
            result = step.run(engine, ctx)
            if isinstance(result, FlowStepResult):
                last_result = result
            if ctx.pending_step_id:
                # 某些恢复策略会要求跳回某一步，此处统一解析跳转目标。
                current_index = step_index.get(ctx.pending_step_id, current_index + 1)
                ctx.pending_step_id = ""
                continue
            current_index += 1
        return last_result
