from __future__ import annotations

from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.base import BaseFlowStep
from platforms.chatgpt.codex_gui.steps.common import require_driver, resolve_wait_timeout, set_current_stage, verify_success
from platforms.chatgpt.codex_gui.steps.metadata import StepMetadata
from platforms.chatgpt.codex_gui.steps.recovery import retry_step_or_abort


class OpenOfficialSignupEntryStep(BaseFlowStep):
    step_id = "official_signup.open_entry"
    stage_name = "官网注册-打开入口页"
    max_attempts = 2
    metadata = StepMetadata(
        step_id=step_id,
        stage_name=stage_name,
        intent="打开 ChatGPT 官网注册入口页",
        legacy_mapping="new official signup: open configured official signup URL",
        expected_url_fragment="/auth/login",
        expected_targets=("official_signup_continue_button", "official_signup_email_input"),
    )

    def prepare(self, engine, ctx) -> None:
        set_current_stage(ctx, self.stage_name)

    def execute(self, engine, ctx):
        driver = require_driver(engine)
        wait_timeout = resolve_wait_timeout(engine)
        entry_url = str(
            ctx.extra_config.get("codex_gui_official_signup_url")
            or ctx.extra_config.get("chatgpt_official_signup_url")
            or "https://chatgpt.com/auth/login"
        ).strip()
        engine._log_step("官网注册", "打开 ChatGPT 官网注册入口页")
        driver.open_url(entry_url, reuse_current=False)
        matched_url = engine._wait_for_any_url(
            ["/auth/login", "/auth/signup", "/create-account", "chatgpt.com"],
            timeout=wait_timeout,
            stage=self.stage_name,
        )
        return FlowStepResult(success=True, stage_name=self.stage_name, matched_url=matched_url)

    def verify(self, engine, ctx, result) -> None:
        verify_success(result, step_id=self.step_id)

    def on_error(self, engine, ctx, error: Exception):
        return retry_step_or_abort(error=error, attempt=ctx.step_attempts.get(self.step_id, 1), max_attempts=self.max_attempts)
