from .base import AliasSourceState
from .manager import AliasEmailPoolManager


class AliasServiceProducerBase:
    source_kind = "alias_service"

    def __init__(self, *, source_id: str):
        self.source_id = source_id
        self._state = AliasSourceState.IDLE

    def state(self) -> AliasSourceState:
        return self._state

    def load_into(self, manager: AliasEmailPoolManager) -> None:
        raise NotImplementedError("Alias service producers are not implemented yet.")
