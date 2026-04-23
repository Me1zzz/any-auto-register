from collections import deque
import threading
import time

from .base import (
    AliasEmailLease,
    AliasLeaseStatus,
    AliasPoolExhaustedError,
    AliasSourceState,
)


class AliasEmailPoolManager:
    def __init__(self, *, task_id: str, log_fn=None):
        self.task_id = task_id
        self._log_fn = log_fn
        self._available = deque()
        self._sources = {}
        self._lock = threading.RLock()
        self._refill_lock = threading.Lock()
        self._background_refill_low_watermark = 0
        self._background_refill_interval_seconds = 0.5
        self._background_refill_stop_event = threading.Event()
        self._background_refill_wakeup = threading.Event()
        self._background_refill_thread = None

    @staticmethod
    def _format_source_kind(source_kind: object) -> str:
        normalized = str(source_kind or "").strip().lower()
        if normalized == "vend_email":
            return "vend"
        if not normalized:
            return "unknown"
        return normalized.replace("_", " ")

    def _log(self, message: str) -> None:
        if callable(self._log_fn):
            self._log_fn(message)

    def register_source(self, producer) -> None:
        with self._lock:
            self._sources[producer.source_id] = producer
        self._log(
            "[AliasPool] register source: "
            f"{self._format_source_kind(getattr(producer, 'source_kind', ''))}"
            f" source_id={getattr(producer, 'source_id', '')}"
        )
        self.request_background_refill_if_needed()

    def available_count(self) -> int:
        with self._lock:
            return len(self._available)

    def available_count_for_source(self, source_id: str) -> int:
        with self._lock:
            return sum(1 for lease in self._available if lease.source_id == source_id)

    def snapshot_available_aliases_by_kind(self) -> dict[str, list[str]]:
        with self._lock:
            aliases_by_kind: dict[str, list[str]] = {}
            for producer in self._sources.values():
                aliases_by_kind.setdefault(str(producer.source_kind), [])
            for lease in self._available:
                aliases_by_kind.setdefault(lease.source_kind, []).append(lease.alias_email)
            return aliases_by_kind

    def has_live_sources(self) -> bool:
        with self._lock:
            if not self._sources:
                return False
            return any(
                producer.state() in {AliasSourceState.IDLE, AliasSourceState.ACTIVE}
                for producer in self._sources.values()
            )

    def add_lease(self, lease: AliasEmailLease) -> None:
        with self._lock:
            self._available.append(lease)

    def _live_sources_snapshot(self):
        with self._lock:
            return [
                producer
                for producer in self._sources.values()
                if producer.state() in {AliasSourceState.IDLE, AliasSourceState.ACTIVE}
            ]

    def _refill_to_minimum(self, minimum_count: int) -> bool:
        target = max(int(minimum_count or 0), 1)
        produced_any = False
        with self._refill_lock:
            while True:
                current_available = self.available_count()
                if current_available >= target:
                    return produced_any
                live_sources = self._live_sources_snapshot()
                if not live_sources:
                    return produced_any

                made_progress = False
                needed = max(target - current_available, 1)
                for producer in live_sources:
                    before = self.available_count()
                    ensure_available = getattr(producer, "ensure_available", None)
                    self._log(
                        "[AliasPool] refill attempt: "
                        f"{self._format_source_kind(getattr(producer, 'source_kind', ''))} "
                        f"source_id={getattr(producer, 'source_id', '')} "
                        f"need={needed} available={before}"
                    )
                    try:
                        if callable(ensure_available):
                            ensure_available(self, minimum_count=needed)
                        else:
                            producer.load_into(self)
                    except Exception as exc:
                        self._log(
                            "[AliasPool] refill failed: "
                            f"{self._format_source_kind(getattr(producer, 'source_kind', ''))} "
                            f"source_id={getattr(producer, 'source_id', '')} "
                            f"need={needed} error={exc}"
                        )
                        continue
                    after = self.available_count()
                    if after > before:
                        produced_any = True
                        made_progress = True
                        self._log(
                            "[AliasPool] refill produced: "
                            f"{self._format_source_kind(getattr(producer, 'source_kind', ''))} "
                            f"source_id={getattr(producer, 'source_id', '')} "
                            f"+{after - before} available={after}"
                        )
                    else:
                        self._log(
                            "[AliasPool] refill no progress: "
                            f"{self._format_source_kind(getattr(producer, 'source_kind', ''))} "
                            f"source_id={getattr(producer, 'source_id', '')} "
                            f"available={after}"
                        )
                    if after >= target:
                        return produced_any
                    needed = max(target - after, 1)
                if not made_progress:
                    return produced_any

    def _background_refill_worker(self) -> None:
        while not self._background_refill_stop_event.is_set():
            try:
                self._background_refill_wakeup.wait(self._background_refill_interval_seconds)
                self._background_refill_wakeup.clear()
                if self._background_refill_stop_event.is_set():
                    break
                low_watermark = max(int(self._background_refill_low_watermark or 0), 0)
                if low_watermark <= 0:
                    continue
                while (
                    not self._background_refill_stop_event.is_set()
                    and self.available_count() < low_watermark
                    and self.has_live_sources()
                ):
                    produced = self._refill_to_minimum(low_watermark)
                    if not produced:
                        break
                    time.sleep(0)
            except Exception as exc:
                self._log(f"[AliasPool] background refill worker failed: {exc}")

    def start_background_refill(
        self,
        *,
        low_watermark: int = 10,
        interval_seconds: float = 0.5,
    ) -> None:
        thread_to_start = None
        with self._lock:
            self._background_refill_low_watermark = max(int(low_watermark or 0), 0)
            self._background_refill_interval_seconds = max(float(interval_seconds or 0.5), 0.1)
            self._background_refill_stop_event.clear()
            if self._background_refill_thread is None or not self._background_refill_thread.is_alive():
                self._background_refill_thread = threading.Thread(
                    target=self._background_refill_worker,
                    name=f"alias-pool-refill-{self.task_id}",
                    daemon=True,
                )
                thread_to_start = self._background_refill_thread
        if thread_to_start is not None:
            thread_to_start.start()
        self.request_background_refill_if_needed()

    def stop_background_refill(self) -> None:
        thread = None
        with self._lock:
            self._background_refill_stop_event.set()
            self._background_refill_wakeup.set()
            thread = self._background_refill_thread
            self._background_refill_thread = None
        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=1.0)

    def request_background_refill_if_needed(self) -> None:
        with self._lock:
            low_watermark = max(int(self._background_refill_low_watermark or 0), 0)
            should_wake = (
                low_watermark > 0
                and len(self._available) < low_watermark
                and any(
                    producer.state() in {AliasSourceState.IDLE, AliasSourceState.ACTIVE}
                    for producer in self._sources.values()
                )
            )
        if should_wake:
            self._background_refill_wakeup.set()

    def acquire_alias(self) -> AliasEmailLease:
        if self.available_count() <= 0 and not self._refill_to_minimum(1):
            raise AliasPoolExhaustedError("CloudMail é’î‚¢æ‚•é–­î†¾î†ˆå§¹çŠ²å‡¡é‘°æ¥€æ•–")
        with self._lock:
            if not self._available:
                raise AliasPoolExhaustedError("CloudMail é’î‚¢æ‚•é–­î†¾î†ˆå§¹çŠ²å‡¡é‘°æ¥€æ•–")
            lease = self._available.popleft()
            lease.status = AliasLeaseStatus.LEASED
        self.request_background_refill_if_needed()
        return lease

    def cleanup(self) -> None:
        self.stop_background_refill()
        with self._lock:
            self._available.clear()
