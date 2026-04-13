from __future__ import annotations

from platforms.chatgpt.codex_gui.context import CodexGUIFlowContext
from platforms.chatgpt.codex_gui.models import CodexGUIIdentity
from platforms.chatgpt.refresh_token_registration_engine import RegistrationResult


def build_flow_context(engine, *, identity: CodexGUIIdentity, auth_url: str, email_adapter) -> CodexGUIFlowContext:
    return CodexGUIFlowContext(
        identity=identity,
        auth_url=auth_url,
        auth_state="",
        email_adapter=email_adapter,
        logger=engine._log,
        extra_config=engine.extra_config,
        oauth_login_completed=engine._oauth_login_completed,
    )


def initialize_run_result(engine) -> RegistrationResult:
    return RegistrationResult(success=False, logs=engine.logs, source="codex_gui")


def log_identity_summary(engine, identity: CodexGUIIdentity) -> None:
    engine._log("=" * 60)
    engine._log("开始 Codex GUI 注册/登录流程")
    engine._log(f"邮箱: {identity.email}")
    engine._log(f"全名: {identity.full_name}, 年龄: {identity.age}")
    engine._log("=" * 60)


def finalize_success_result(
    result: RegistrationResult,
    *,
    identity: CodexGUIIdentity,
    auth_state: str,
    auth_url: str,
) -> RegistrationResult:
    result.success = True
    result.email = identity.email
    result.password = identity.password
    result.account_id = identity.service_id or identity.email
    result.metadata = {
        "codex_gui_register_completed": True,
        "codex_gui_login_completed": True,
        "codex_gui_oauth_login_completed": True,
        "codex_gui_auth_state": auth_state,
        "codex_gui_auth_url": auth_url,
        "codex_gui_full_name": identity.full_name,
        "codex_gui_age": identity.age,
    }
    return result
