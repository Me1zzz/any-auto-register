from .base import AliasSourceState
from .manager import AliasEmailPoolManager


class AliasServiceProducerBase:
    source_kind = "alias_service"

    def __init__(self, *, source_id: str):
        self.source_id = source_id
        self._state = AliasSourceState.IDLE

    def state(self) -> AliasSourceState:
        return self._state

    def ensure_available(self, manager: AliasEmailPoolManager, *, minimum_count: int = 1) -> None:
        raise NotImplementedError("Alias service producers are not implemented yet.")

    def load_into(self, manager: AliasEmailPoolManager) -> None:
        raise NotImplementedError("Alias service producers are not implemented yet.")
