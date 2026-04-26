from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _nonnegative_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


@dataclass
class InteractiveProviderState:
    state_key: str = ""
    service_account_email: str = ""
    confirmation_inbox_email: str = ""
    real_mailbox_email: str = ""
    service_password: str = ""
    username: str = ""
    session_state: dict[str, Any] = field(default_factory=dict)
    domain_options: list[dict[str, Any]] = field(default_factory=list)
    known_aliases: list[str] = field(default_factory=list)
    created_alias_count: int = 0
    alias_limit: int = 0
    exhausted: bool = False
    accounts_state: list[dict[str, Any]] = field(default_factory=list)
    active_account_email: str = ""
    current_stage: dict[str, str] = field(default_factory=lambda: {"code": "", "label": ""})
    stage_history: list[dict[str, Any]] = field(default_factory=list)
    last_failure: dict[str, Any] = field(default_factory=lambda: {"stageCode": "", "stageLabel": "", "reason": ""})
    last_capture_summary: list[dict[str, Any]] = field(default_factory=list)
    last_error: str = ""

    def __post_init__(self) -> None:
        self.created_alias_count = max(
            _nonnegative_int(self.created_alias_count),
            len(list(self.known_aliases or [])),
        )
        self.alias_limit = _nonnegative_int(self.alias_limit)
        if self.alias_limit and self.created_alias_count >= self.alias_limit:
            self.exhausted = True
