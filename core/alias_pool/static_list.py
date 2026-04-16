from .base import AliasEmailLease, AliasSourceState
from .manager import AliasEmailPoolManager


class StaticAliasListProducer:
    source_kind = "static_list"

    def __init__(self, *, source_id: str, emails: list[str], mailbox_email: str):
        self.source_id = source_id
        self.emails = list(emails or [])
        self.mailbox_email = mailbox_email
        self._state = AliasSourceState.IDLE

    def state(self) -> AliasSourceState:
        return self._state

    def load_into(self, manager: AliasEmailPoolManager) -> None:
        self._state = AliasSourceState.ACTIVE
        for email in self.emails:
            manager.add_lease(
                AliasEmailLease(
                    alias_email=email,
                    real_mailbox_email=self.mailbox_email,
                    source_kind="static_list",
                    source_id=self.source_id,
                    source_session_id="static",
                )
            )
        self._state = AliasSourceState.EXHAUSTED
