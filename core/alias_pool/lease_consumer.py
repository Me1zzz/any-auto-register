from __future__ import annotations


class AliasLeaseConsumerContext:
    def __init__(self, *, pool_manager):
        self._pool_manager = pool_manager

    def acquire_alias_lease(self):
        if self._pool_manager is None:
            return None
        return self._pool_manager.acquire_alias()

    def release(self) -> None:
        cleanup = getattr(self._pool_manager, "cleanup", None)
        if callable(cleanup):
            cleanup()
