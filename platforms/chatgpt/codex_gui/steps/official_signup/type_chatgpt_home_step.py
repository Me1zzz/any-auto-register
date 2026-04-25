from __future__ import annotations

from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.base import BaseFlowStep
from platforms.chatgpt.codex_gui.steps.common import require_driver, resolve_wait_timeout, set_current_stage, verify_success
from platforms.chatgpt.codex_gui.steps.metadata import StepMetadata
from platforms.chatgpt.codex_gui.steps.recovery import retry_step_or_abort


class TypeChatGPTHomeStep(BaseFlowStep):
    step_id = "official_signup.type_chatgpt_home"
    stage_name = "官网注册-地址栏输入 chatgpt.com"
    max_attempts = 2
    metadata = StepMetadata(
        step_id=step_id,
        stage_name=stage_name,
        intent="识别浏览器地址栏并输入 chatgpt.com",
        legacy_mapping="new official signup: type chatgpt.com in isolated browser address bar",
        expected_url_fragment="chatgpt.com",
    )

    def prepare(self, engine, ctx) -> None:
        set_current_stage(ctx, self.stage_name)

    def execute(self, engine, ctx):
        driver = require_driver(engine)
        wait_timeout = resolve_wait_timeout(engine)
        home_url = str(ctx.extra_config.get("codex_gui_official_signup_home_url") or "chatgpt.com").strip()
        engine._log_step("官网注册", f"识别地址栏并输入 {home_url}")
        driver.navigate_with_address_bar(home_url)
        matched_url = engine._wait_for_stage_ready("官网注册-首页", timeout=wait_timeout)
        return FlowStepResult(success=True, stage_name=self.stage_name, matched_url=matched_url)

    def verify(self, engine, ctx, result) -> None:
        verify_success(result, step_id=self.step_id)

    def on_error(self, engine, ctx, error: Exception):
        return retry_step_or_abort(error=error, attempt=ctx.step_attempts.get(self.step_id, 1), max_attempts=self.max_attempts)
