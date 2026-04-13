from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .models import CodexGUIIdentity


@dataclass(slots=True)
class CodexGUIFlowContext:
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
    step_attempts: dict[str, int] = field(default_factory=dict)
    step_history: list[str] = field(default_factory=list)
