from __future__ import annotations

from platforms.chatgpt.codex_gui.steps.base import StepErrorDecision
from platforms.chatgpt.codex_gui.steps.errors import (
    OTPCollectionError,
    StageTransitionTimeoutError,
    StepExecutionError,
    TargetNotFoundError,
    TerminalResolutionError,
)


def abort_flow(error: Exception) -> StepErrorDecision:
    """直接终止整个流程。"""
    return StepErrorDecision(action="abort_flow", reason=str(error))


def retry_step_or_abort(*, error: Exception, attempt: int, max_attempts: int) -> StepErrorDecision:
    """按异常类型决定是否整步重试。"""
    if isinstance(error, (StageTransitionTimeoutError, TargetNotFoundError)) and attempt < max_attempts:
        return StepErrorDecision(action="retry_step", reason=str(error))
    return abort_flow(error)


def retry_last_action_or_abort(*, error: Exception, attempt: int, max_attempts: int) -> StepErrorDecision:
    """按异常类型决定是否仅重放最后一个 GUI 动作。"""
    if isinstance(error, (StageTransitionTimeoutError, TargetNotFoundError, TerminalResolutionError)) and attempt < max_attempts:
        return StepErrorDecision(action="retry_last_action", reason=str(error))
    return abort_flow(error)


def otp_abort(error: Exception) -> StepErrorDecision:
    """OTP 相关错误统一按终止流程处理。"""
    if isinstance(error, OTPCollectionError):
        return StepErrorDecision(action="abort_flow", reason=str(error))
    if isinstance(error, StepExecutionError):
        return StepErrorDecision(action="abort_flow", reason=str(error))
    return abort_flow(error)
