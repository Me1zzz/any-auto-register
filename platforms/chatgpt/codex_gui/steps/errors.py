from __future__ import annotations


class StepExecutionError(RuntimeError):
    """Base class for step execution failures."""


class StepPrecheckError(StepExecutionError):
    """Required preconditions are missing before a step runs."""


class TargetNotFoundError(StepExecutionError):
    """A required GUI target could not be located."""


class StageTransitionTimeoutError(StepExecutionError):
    """The expected page or marker transition did not happen in time."""


class OTPCollectionError(StepExecutionError):
    """An OTP could not be collected or verified."""


class TerminalResolutionError(StepExecutionError):
    """The terminal outcome of a flow could not be determined or was invalid."""
