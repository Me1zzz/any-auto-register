from __future__ import annotations

from core.alias_pool.interactive_provider_state import InteractiveProviderState


class InteractiveStateRepository:
    def __init__(self, *, store=None):
        self._store = store

    def new_state(self) -> InteractiveProviderState:
        return InteractiveProviderState()

    def load(self) -> InteractiveProviderState:
        if self._store is None:
            return self.new_state()
        loaded = self._store.load()
        if loaded is None:
            return self.new_state()
        return loaded

    def save(self, state: InteractiveProviderState) -> None:
        if self._store is None:
            return
        self._store.save(state)
