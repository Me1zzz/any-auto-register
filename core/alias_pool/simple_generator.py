import random
import string

from .base import AliasEmailLease, AliasSourceState
from .manager import AliasEmailPoolManager


class SimpleAliasGeneratorProducer:
    source_kind = "simple_generator"
    _ALPHABET = string.ascii_lowercase + string.digits

    def __init__(
        self,
        *,
        source_id: str,
        prefix: str,
        suffix: str,
        mailbox_email: str,
        count: int,
        middle_length_min: int,
        middle_length_max: int,
    ):
        self.source_id = source_id
        self.prefix = prefix
        self.suffix = suffix
        self.mailbox_email = mailbox_email
        self.count = count
        self.middle_length_min = middle_length_min
        self.middle_length_max = middle_length_max
        self._state = AliasSourceState.IDLE

    def state(self) -> AliasSourceState:
        return self._state

    def _generate_alias_email(self) -> str:
        middle_length = random.randint(self.middle_length_min, self.middle_length_max)
        middle = "".join(random.choices(self._ALPHABET, k=middle_length))
        return f"{self.prefix}{middle}{self.suffix}"

    def load_into(self, manager: AliasEmailPoolManager) -> None:
        self._state = AliasSourceState.ACTIVE
        try:
            seen: set[str] = set()
            while len(seen) < self.count:
                alias_email = self._generate_alias_email()
                if alias_email in seen:
                    continue
                seen.add(alias_email)
                manager.add_lease(
                    AliasEmailLease(
                        alias_email=alias_email,
                        real_mailbox_email=self.mailbox_email,
                        source_kind=self.source_kind,
                        source_id=self.source_id,
                        source_session_id="simple-generator",
                    )
                )
            self._state = AliasSourceState.EXHAUSTED
        except Exception:
            self._state = AliasSourceState.FAILED
            raise
