from __future__ import annotations

from core.alias_pool.vend_email_state import VendEmailServiceState


class VendStateRepository:
    def __init__(self, *, store, state_key: str):
        self._store = store
        self._state_key = str(state_key or "")

    @property
    def store(self):
        return self._store

    @property
    def state_key(self) -> str:
        return self._state_key

    def load(self) -> VendEmailServiceState:
        try:
            return self._store.load(self._state_key)
        except TypeError:
            return self._store.load()

    def save(self, state: VendEmailServiceState) -> None:
        state.state_key = self._state_key
        self._store.save(state)

    def new_state(self) -> VendEmailServiceState:
        return VendEmailServiceState(state_key=self._state_key)
