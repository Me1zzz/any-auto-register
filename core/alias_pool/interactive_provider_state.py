from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class InteractiveProviderState:
    service_account_email: str = ""
    confirmation_inbox_email: str = ""
    real_mailbox_email: str = ""
    service_password: str = ""
    username: str = ""
    session_state: dict[str, Any] = field(default_factory=dict)
    domain_options: list[dict[str, Any]] = field(default_factory=list)
    known_aliases: list[str] = field(default_factory=list)
    current_stage: dict[str, str] = field(default_factory=lambda: {"code": "", "label": ""})
    stage_history: list[dict[str, Any]] = field(default_factory=list)
    last_failure: dict[str, Any] = field(default_factory=lambda: {"stageCode": "", "stageLabel": "", "reason": ""})
    last_capture_summary: list[dict[str, Any]] = field(default_factory=list)
    last_error: str = ""
