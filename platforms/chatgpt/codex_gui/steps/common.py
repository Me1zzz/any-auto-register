from __future__ import annotations

from platforms.chatgpt.codex_gui.context import CodexGUIFlowContext
from platforms.chatgpt.codex_gui.models import FlowStepResult
from platforms.chatgpt.codex_gui.steps.errors import (
    OTPCollectionError,
    StageTransitionTimeoutError,
    StepPrecheckError,
    TargetNotFoundError,
    TerminalResolutionError,
)


def append_step_history(ctx: CodexGUIFlowContext, step_id: str) -> None:
    """将步骤 ID 追加到执行历史中。"""
    ctx.step_history.append(step_id)


def require_driver(engine):
    """确保当前 engine 已经完成 GUI driver 初始化。"""
    driver = getattr(engine, "_driver", None)
    if driver is None:
        raise RuntimeError("Codex GUI 驱动未初始化")
    return driver


def resolve_wait_timeout(engine, key: str = "codex_gui_wait_timeout_seconds", default: int = 60) -> int:
    """统一读取等待超时配置，避免步骤自己解析配置。"""
    return engine._wait_timeout(key, default)


def require_non_empty(value: str, *, field_name: str) -> str:
    """确保关键字符串字段非空，否则抛出前置检查异常。"""
    normalized = str(value or "").strip()
    if not normalized:
        raise StepPrecheckError(f"缺少必要字段: {field_name}")
    return normalized


def set_current_stage(ctx: CodexGUIFlowContext, stage_name: str) -> None:
    """在上下文中记录当前执行阶段名称。"""
    ctx.current_stage = str(stage_name or "").strip()


def verify_success(result: FlowStepResult, *, step_id: str) -> None:
    """验证步骤结果对象标记为成功。"""
    if not result.success:
        raise StepPrecheckError(f"步骤执行失败: {step_id}")


def verify_terminal_state(ctx: CodexGUIFlowContext, allowed: set[str], *, step_id: str) -> None:
    """验证终态是否落在允许集合中。"""
    if ctx.terminal_state and ctx.terminal_state not in allowed:
        raise TerminalResolutionError(f"步骤终态不符合预期: {step_id} -> {ctx.terminal_state}")


def wait_for_expected_url(engine, fragment: str, *, timeout: int, stage: str) -> str:
    """等待目标 URL 片段命中，并将超时转换为语义异常。"""
    try:
        return engine._wait_for_url(fragment, timeout=timeout, stage=stage)
    except RuntimeError as exc:
        message = str(exc)
        if "超时" in message:
            raise StageTransitionTimeoutError(message) from exc
        raise


def collect_otp_code(engine, adapter, *, stage: str) -> str:
    """统一拉取 OTP，并将失败转换为 OTPCollectionError。"""
    try:
        code = str(engine._collect_verification_code(adapter, stage=stage) or "").strip()
    except RuntimeError as exc:
        raise OTPCollectionError(str(exc)) from exc
    if not code:
        raise OTPCollectionError(f"[{stage}] 未获取到验证码")
    return code


def wait_for_terminal(engine, *, prefix: str, timeout: int) -> str:
    """等待流程终态并将异常归类为终态解析失败。"""
    try:
        return str(engine._wait_for_terminal_outcome(prefix=prefix, timeout=timeout) or "").strip()
    except RuntimeError as exc:
        raise TerminalResolutionError(str(exc)) from exc


def wrap_target_error(name: str, exc: Exception) -> TargetNotFoundError:
    """把底层目标定位失败包装成统一异常类型。"""
    return TargetNotFoundError(f"目标定位失败: {name} ({exc})")


def run_named_action(engine, label: str, action) -> None:
    """统一执行一个具名 GUI 动作，保持日志和重试语义一致。"""
    try:
        engine._run_action(label, action)
    except RuntimeError as exc:
        raise StepPrecheckError(str(exc)) from exc


def click_and_wait_for_url(engine, driver, *, click_label: str, target_name: str, fragment: str, timeout: int, stage: str) -> str:
    """执行点击动作并等待页面跳转到目标 URL。"""
    try:
        run_named_action(engine, click_label, lambda: driver.click_named_target(target_name))
    except StepPrecheckError as exc:
        raise wrap_target_error(target_name, exc) from exc
    return wait_for_expected_url(engine, fragment, timeout=timeout, stage=stage)


def input_and_click_then_wait(
    engine,
    driver,
    *,
    input_label: str,
    input_target: str,
    input_value: str,
    click_label: str,
    click_target: str,
    fragment: str,
    timeout: int,
    stage: str,
) -> str:
    """执行“输入 + 点击 + 等待跳转”这一类常见步骤模板。"""
    run_named_action(engine, input_label, lambda: driver.input_text(input_target, input_value))
    run_named_action(engine, click_label, lambda: driver.click_named_target(click_target))
    return wait_for_expected_url(engine, fragment, timeout=timeout, stage=stage)
