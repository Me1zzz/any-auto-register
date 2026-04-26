from __future__ import annotations

from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.base import BaseFlowStep
from platforms.chatgpt.codex_gui.steps.common import (
    require_driver,
    resolve_wait_timeout,
    run_named_action,
    set_current_stage,
    verify_success,
)
from platforms.chatgpt.codex_gui.steps.metadata import StepMetadata
from platforms.chatgpt.codex_gui.steps.recovery import retry_step_or_abort


class ClickOfficialSignupFreeSignupStep(BaseFlowStep):
    step_id = "official_signup.click_free_signup"
    stage_name = "官网注册-点击免费注册"
    max_attempts = 2
    metadata = StepMetadata(
        step_id=step_id,
        stage_name=stage_name,
        intent="在 ChatGPT 官网首页点击免费注册，并等待登录或注册弹窗出现",
        legacy_mapping="new official signup: click free signup on chatgpt.com home",
        expected_targets=("official_signup_free_signup_button",),
    )

    def prepare(self, engine, ctx) -> None:
        set_current_stage(ctx, self.stage_name)

    def execute(self, engine, ctx):
        driver = require_driver(engine)
        wait_timeout = resolve_wait_timeout(engine)
        run_named_action(
            engine,
            "[官网注册] 点击免费注册",
            lambda: driver.click_named_target("official_signup_free_signup_button"),
        )
        try:
            matched_url = engine._wait_for_stage_ready("官网注册-登录或注册弹窗", timeout=wait_timeout)
        except RuntimeError as wait_error:
            probe_timeout_ms = engine._stage_dom_probe_timeout_ms()
            try:
                driver.peek_target_with_timeout("official_signup_free_signup_button", probe_timeout_ms)
            except Exception:
                raise wait_error
            run_named_action(
                engine,
                "[官网注册] 重试点击免费注册",
                lambda: driver.click_named_target("official_signup_free_signup_button"),
            )
            matched_url = engine._wait_for_stage_ready("官网注册-登录或注册弹窗", timeout=wait_timeout)
        return FlowStepResult(success=True, stage_name=self.stage_name, matched_url=matched_url)

    def verify(self, engine, ctx, result) -> None:
        verify_success(result, step_id=self.step_id)

    def on_error(self, engine, ctx, error: Exception):
        return retry_step_or_abort(error=error, attempt=ctx.step_attempts.get(self.step_id, 1), max_attempts=self.max_attempts)
