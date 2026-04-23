from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class BrowserRuntimeStep:
    code: str
    label: str
    status: str
    detail: str = ""


@dataclass
class BrowserRuntimeSessionState:
    current_url: str = ""
    cookies: list[dict[str, Any]] = field(default_factory=list)
    local_storage: dict[str, str] = field(default_factory=dict)
    session_storage: dict[str, str] = field(default_factory=dict)


class BrowserRuntime(Protocol):
    def open(self, url: str) -> BrowserRuntimeStep: ...

    def restore(self, state: BrowserRuntimeSessionState) -> None: ...

    def snapshot(self) -> BrowserRuntimeSessionState: ...

    def current_url(self) -> str: ...
