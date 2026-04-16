from collections import deque

from .base import (
    AliasEmailLease,
    AliasLeaseStatus,
    AliasPoolExhaustedError,
    AliasSourceState,
)


class AliasEmailPoolManager:
    def __init__(self, *, task_id: str):
        self.task_id = task_id
        self._available = deque()
        self._sources = {}

    def register_source(self, producer) -> None:
        self._sources[producer.source_id] = producer

    def available_count_for_source(self, source_id: str) -> int:
        return sum(1 for lease in self._available if lease.source_id == source_id)

    def has_live_sources(self) -> bool:
        if not self._sources:
            return False
        return any(
            producer.state() in {AliasSourceState.IDLE, AliasSourceState.ACTIVE}
            for producer in self._sources.values()
        )

    def add_lease(self, lease: AliasEmailLease) -> None:
        self._available.append(lease)

    def acquire_alias(self) -> AliasEmailLease:
        if not self._available:
            raise AliasPoolExhaustedError("CloudMail 别名邮箱池已耗尽")
        lease = self._available.popleft()
        lease.status = AliasLeaseStatus.LEASED
        return lease

    def cleanup(self) -> None:
        self._available.clear()
