from __future__ import annotations

from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.base import BaseFlowStep
from platforms.chatgpt.codex_gui.steps.common import require_driver, set_current_stage, verify_success
from platforms.chatgpt.codex_gui.steps.metadata import StepMetadata
from platforms.chatgpt.codex_gui.steps.recovery import retry_step_or_abort


def _snapshot_profile_enabled(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"0", "false", "no", "off"}:
            return False
        if normalized in {"1", "true", "yes", "on"}:
            return True
    return bool(value)


class OpenOfficialSignupRuntimeProfileStep(BaseFlowStep):
    step_id = "official_signup.open_runtime_profile"
    stage_name = "官网注册-打开 runtime profile 浏览器"
    max_attempts = 2
    metadata = StepMetadata(
        step_id=step_id,
        stage_name=stage_name,
        intent="使用一次性的 runtime Edge Profile 打开新的浏览器会话",
        legacy_mapping="new official signup: initialize isolated runtime edge profile",
    )

    def precheck(self, engine, ctx) -> None:
        configured_user_data_dir = str(ctx.extra_config.get("codex_gui_edge_user_data_dir") or "").strip()
        if configured_user_data_dir and not _snapshot_profile_enabled(ctx.extra_config.get("codex_gui_edge_snapshot_profile", True)):
            raise RuntimeError("官网注册变体不允许直接复用真实 Edge Profile，请启用 codex_gui_edge_snapshot_profile")

    def prepare(self, engine, ctx) -> None:
        set_current_stage(ctx, self.stage_name)

    def execute(self, engine, ctx):
        driver = require_driver(engine)
        engine._log_step("官网注册", "打开一次性 runtime profile 的 Edge 浏览器")
        driver.open_new_profile_browser()
        runtime_user_data_dir = str(getattr(driver, "_edge_user_data_dir", "") or "").strip()
        return FlowStepResult(
            success=True,
            stage_name=self.stage_name,
            payload={"runtime_user_data_dir": runtime_user_data_dir},
        )

    def verify(self, engine, ctx, result) -> None:
        verify_success(result, step_id=self.step_id)

    def on_error(self, engine, ctx, error: Exception):
        return retry_step_or_abort(error=error, attempt=ctx.step_attempts.get(self.step_id, 1), max_attempts=self.max_attempts)
