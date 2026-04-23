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
        self._remaining_count = max(int(count or 0), 0)
        self._generated_aliases: set[str] = set()
        self._state = AliasSourceState.IDLE

    def state(self) -> AliasSourceState:
        return self._state

    def _generate_alias_email(self) -> str:
        middle_length = random.randint(self.middle_length_min, self.middle_length_max)
        middle = "".join(random.choices(self._ALPHABET, k=middle_length))
        return f"{self.prefix}{middle}{self.suffix}"

    def ensure_available(self, manager: AliasEmailPoolManager, *, minimum_count: int = 1) -> None:
        requested = max(int(minimum_count or 0), 1)
        if self._remaining_count <= 0:
            self._state = AliasSourceState.EXHAUSTED
            return
        self._state = AliasSourceState.ACTIVE
        try:
            produced = 0
            while self._remaining_count > 0 and produced < requested:
                alias_email = self._generate_alias_email()
                if alias_email in self._generated_aliases:
                    continue
                self._generated_aliases.add(alias_email)
                manager.add_lease(
                    AliasEmailLease(
                        alias_email=alias_email,
                        real_mailbox_email=self.mailbox_email,
                        source_kind=self.source_kind,
                        source_id=self.source_id,
                        source_session_id="simple-generator",
                    )
                )
                self._remaining_count -= 1
                produced += 1
            if self._remaining_count <= 0:
                self._state = AliasSourceState.EXHAUSTED
        except Exception:
            self._state = AliasSourceState.FAILED
            raise

    def load_into(self, manager: AliasEmailPoolManager) -> None:
        self.ensure_available(manager, minimum_count=self._remaining_count)
