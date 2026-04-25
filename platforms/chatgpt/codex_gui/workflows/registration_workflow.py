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

    def _all_steps(self):
        return [
            OpenRegistrationAuthUrlStep(),
            ClickRegisterButtonStep(),
            SubmitRegistrationEmailStep(),
            SubmitRegistrationPasswordStep(),
            SubmitRegistrationOtpStep(),
            FillRegistrationProfileStep(),
            CompleteRegistrationStep(),
            CompleteRegistrationConsentStep(),
        ]

    def _run_steps(self, steps, engine, ctx: CodexGUIFlowContext) -> FlowStepResult:
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

    def run(self, engine, ctx: CodexGUIFlowContext) -> FlowStepResult:
        """依次执行注册步骤，并响应步骤级跳转请求。"""
        return self._run_steps(self._all_steps(), engine, ctx)

    def run_tail_after_password(self, engine, ctx: CodexGUIFlowContext) -> FlowStepResult:
        """复用密码提交后的 OTP、资料补全、终态与 consent 收口。"""
        steps = [
            SubmitRegistrationOtpStep(),
            FillRegistrationProfileStep(),
            CompleteRegistrationStep(),
            CompleteRegistrationConsentStep(),
        ]
        result = self._run_steps(steps, engine, ctx)
        ctx.register_tail_completed = True
        return result
