from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from platforms.chatgpt.codex_gui.steps.metadata import StepMetadata
from platforms.chatgpt.codex_gui.steps.common import append_step_history


@dataclass(slots=True)
class StepErrorDecision:
    """描述步骤失败后应该采取的恢复动作。"""

    action: Literal["retry_step", "retry_last_action", "jump_to_step", "abort_flow", "continue"]
    reason: str
    next_step_id: str | None = None


class BaseFlowStep:
    """所有 GUI 步骤的公共抽象基类。"""

    step_id = ""
    stage_name = ""
    max_attempts = 1
    metadata = StepMetadata(step_id="", stage_name="", intent="", legacy_mapping="")

    def precheck(self, engine, ctx) -> None:
        """在执行步骤前检查前置条件是否满足。"""
        return None

    def prepare(self, engine, ctx) -> None:
        """在真正执行前写入阶段状态或做轻量准备。"""
        return None

    def execute(self, engine, ctx):
        """执行步骤的核心动作，由子类实现。"""
        raise NotImplementedError

    def verify(self, engine, ctx, result) -> None:
        """在步骤执行后验证结果是否符合预期。"""
        return None

    def on_error(self, engine, ctx, error: Exception) -> StepErrorDecision:
        """将异常转换为统一的恢复决策。"""
        return StepErrorDecision(action="abort_flow", reason=str(error))

    def run(self, engine, ctx):
        """按统一生命周期驱动步骤运行，并处理重试/跳转。"""
        attempt = 0
        while attempt < max(1, int(self.max_attempts or 1)):
            try:
                # 记录当前步骤执行次数，供恢复策略判断是否还能继续重试。
                attempt += 1
                ctx.step_attempts[self.step_id] = attempt
                # 每次重新进入步骤前都清空挂起跳转，避免沿用上次失败时的状态。
                ctx.pending_step_id = ""
                self.precheck(engine, ctx)
                self.prepare(engine, ctx)
                # 统一记录步骤历史，便于日志排查与失败回放。
                append_step_history(ctx, self.step_id)
                result = self.execute(engine, ctx)
                self.verify(engine, ctx, result)
                # 步骤成功后清空错误状态，避免污染后续步骤判断。
                ctx.last_error = ""
                ctx.last_error_action = ""
                return result
            except Exception as error:
                # 将原始异常交给子类恢复策略进行语义化决策。
                decision = self.on_error(engine, ctx, error)
                ctx.last_error = str(error)
                ctx.last_error_action = decision.action
                if decision.action == "retry_last_action":
                    # 某些失败适合仅重放最后一个 GUI 动作，而不是重跑整个步骤。
                    retry_action = getattr(engine, "_last_retry_action", None)
                    if callable(retry_action) and attempt < max(1, int(self.max_attempts or 1)):
                        retry_action()
                        continue
                if decision.action == "retry_step" and attempt < max(1, int(self.max_attempts or 1)):
                    # 允许当前步骤在完整生命周期下重新执行一次。
                    continue
                if decision.action == "jump_to_step" and decision.next_step_id:
                    # 将跳转目标写入上下文，由 workflow 在外层驱动切换步骤。
                    ctx.pending_step_id = decision.next_step_id
                    return None
                if decision.action == "continue":
                    # 某些异常被视作可忽略，直接让 workflow 进入下一步。
                    return None
                raise
        raise RuntimeError(f"步骤执行失败: {self.step_id}")
