from __future__ import annotations

from core.alias_pool.interactive_provider_state import InteractiveProviderState


class InteractiveStateRepository:
    def __init__(self, *, store=None, state_key: str = ""):
        self._store = store
        self._state_key = str(state_key or "")
        self._memory_state: InteractiveProviderState | None = None

    @property
    def store(self):
        return self._store

    @property
    def state_key(self) -> str:
        return self._state_key

    def new_state(self) -> InteractiveProviderState:
        return InteractiveProviderState(state_key=self._state_key)

    def load(self) -> InteractiveProviderState:
        if self._store is None:
            if self._memory_state is None:
                self._memory_state = self.new_state()
            self._memory_state.state_key = self._state_key
            return self._memory_state
        try:
            loaded = self._store.load(self._state_key)
        except TypeError:
            loaded = self._store.load()
        if loaded is None:
            return self.new_state()
        loaded.state_key = self._state_key
        return loaded

    def save(self, state: InteractiveProviderState) -> None:
        state.state_key = self._state_key
        if self._store is None:
            self._memory_state = state
            return
        try:
            self._store.save(state, self._state_key)
        except TypeError:
            self._store.save(state)
