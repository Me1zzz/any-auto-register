from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CodexGUIIdentity:
    email: str
    password: str
    full_name: str
    age: int
    service_id: str = ""


@dataclass(slots=True)
class FlowStepResult:
    success: bool = True
    stage_name: str = ""
    matched_url: str = ""
    matched_marker: str = ""
    terminal_state: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
