from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .models import CodexGUIIdentity


@dataclass(slots=True)
class CodexGUIFlowContext:
    """承载 GUI 注册/登录流程在运行期共享的上下文数据。"""

    identity: CodexGUIIdentity
    auth_url: str
    auth_state: str
    email_adapter: Any
    logger: Callable[[str, str], None]
    extra_config: dict[str, Any]
    oauth_login_completed: bool = False
    terminal_state: str = ""
    current_stage: str = ""
    last_error: str = ""
    last_error_action: str = ""
    pending_step_id: str = ""
    gui_variant: str = "default"
    variant_requested: str = "default"
    variant_fallback_reason: str = ""
    official_signup_completed: bool = False
    register_tail_completed: bool = False
    workspace_enroll_result: dict[str, Any] = field(default_factory=dict)
    oauth_login_result: dict[str, Any] = field(default_factory=dict)
    workspace_cleanup_result: dict[str, Any] = field(default_factory=dict)
    cleanup_required: bool = False
    cleanup_retry_count: int = 0
    cleanup_compensation_context: dict[str, Any] = field(default_factory=dict)
    step_attempts: dict[str, int] = field(default_factory=dict)
    step_history: list[str] = field(default_factory=list)
