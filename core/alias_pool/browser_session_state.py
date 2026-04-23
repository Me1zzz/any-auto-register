from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PersistedBrowserSessionState:
    current_url: str = ""
    cookies: list[dict[str, Any]] = field(default_factory=list)
    local_storage: dict[str, str] = field(default_factory=dict)
    session_storage: dict[str, str] = field(default_factory=dict)
