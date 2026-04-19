from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ConfirmationReadResult:
    confirm_url: str = ""
    error: str = ""


class ConfirmationInboxReader(Protocol):
    def fetch_confirmation(self, *, state, source: dict) -> ConfirmationReadResult: ...


class VendConfirmationReader:
    def __init__(self, *, runtime):
        self._runtime = runtime

    def fetch_confirmation(self, *, state, source: dict) -> ConfirmationReadResult:
        fetch_confirmation_link = getattr(self._runtime, "fetch_confirmation_link", None)
        if not callable(fetch_confirmation_link):
            return ConfirmationReadResult(
                error="vend.email confirmation bootstrap unavailable",
            )
        confirm_url = str(fetch_confirmation_link(state, source) or "").strip()
        return ConfirmationReadResult(confirm_url=confirm_url)
