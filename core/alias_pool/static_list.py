from collections import deque

from .base import AliasEmailLease, AliasSourceState
from .manager import AliasEmailPoolManager


class StaticAliasListProducer:
    source_kind = "static_list"

    def __init__(self, *, source_id: str, emails: list[str], mailbox_email: str):
        self.source_id = source_id
        self.emails = list(emails or [])
        self.mailbox_email = mailbox_email
        self._remaining = deque(self.emails)
        self._state = AliasSourceState.IDLE

    def state(self) -> AliasSourceState:
        return self._state

    def ensure_available(self, manager: AliasEmailPoolManager, *, minimum_count: int = 1) -> None:
        requested = max(int(minimum_count or 0), 1)
        if not self._remaining:
            self._state = AliasSourceState.EXHAUSTED
            return
        self._state = AliasSourceState.ACTIVE
        produced = 0
        while self._remaining and produced < requested:
            manager.add_lease(
                AliasEmailLease(
                    alias_email=self._remaining.popleft(),
                    real_mailbox_email=self.mailbox_email,
                    source_kind="static_list",
                    source_id=self.source_id,
                    source_session_id="static",
                )
            )
            produced += 1
        if not self._remaining:
            self._state = AliasSourceState.EXHAUSTED

    def load_into(self, manager: AliasEmailPoolManager) -> None:
        self.ensure_available(manager, minimum_count=len(self._remaining))
