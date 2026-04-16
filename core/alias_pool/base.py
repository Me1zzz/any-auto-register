from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class AliasLeaseStatus(str, Enum):
    """Lifecycle state for a single alias entry managed by the task pool."""

    AVAILABLE = "available"
    LEASED = "leased"
    CONSUMED = "consumed"
    INVALID = "invalid"


class AliasSourceState(str, Enum):
    """Lifecycle state for an alias source producer."""

    IDLE = "idle"
    ACTIVE = "active"
    EXHAUSTED = "exhausted"
    FAILED = "failed"


class AliasSourceProducer(Protocol):
    source_id: str
    source_kind: str

    def load_into(self, manager: Any) -> None: ...

    def state(self) -> AliasSourceState: ...


@dataclass
class AliasEmailLease:
    """Represents one alias entry tracked by the task-scoped pool.

    The ``status`` field models the pool-entry lifecycle rather than mailbox state.
    New leases default to ``AVAILABLE`` intentionally so producers can register
    fresh entries before a consumer acquires them.
    """

    alias_email: str
    real_mailbox_email: str
    source_kind: str
    source_id: str
    source_session_id: str
    status: AliasLeaseStatus = AliasLeaseStatus.AVAILABLE
    metadata: dict[str, Any] = field(default_factory=dict)


class AliasPoolExhaustedError(RuntimeError):
    pass
