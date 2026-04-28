from __future__ import annotations

import threading
import time
from collections.abc import Callable


DEFAULT_ALIAS_CREATION_INTERVAL_SECONDS = 3.0

_registry_lock = threading.Lock()
_locks_by_key: dict[str, threading.Lock] = {}
_last_started_at_by_key: dict[str, float] = {}


def wait_for_alias_creation_slot(
    service_key: str,
    *,
    minimum_interval_seconds: float = DEFAULT_ALIAS_CREATION_INTERVAL_SECONDS,
    monotonic_fn: Callable[[], float] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
) -> None:
    interval = max(float(minimum_interval_seconds or 0), 0.0)
    if interval <= 0:
        return

    key = str(service_key or "alias-service").strip() or "alias-service"
    monotonic = monotonic_fn or time.monotonic
    sleep = sleep_fn or time.sleep
    key_lock = _lock_for_key(key)

    with key_lock:
        now = monotonic()
        last_started_at = _last_started_at_by_key.get(key)
        if last_started_at is not None:
            remaining = interval - (now - last_started_at)
            if remaining > 0:
                sleep(remaining)
                now = monotonic()
        _last_started_at_by_key[key] = now


def _lock_for_key(key: str) -> threading.Lock:
    with _registry_lock:
        key_lock = _locks_by_key.get(key)
        if key_lock is None:
            key_lock = threading.Lock()
            _locks_by_key[key] = key_lock
        return key_lock


def _reset_alias_creation_throttle_for_tests() -> None:
    with _registry_lock:
        _last_started_at_by_key.clear()
