from dataclasses import dataclass, field
from typing import Any

from .base import AliasPoolExhaustedError
from .manager import AliasEmailPoolManager
from .simple_generator import SimpleAliasGeneratorProducer
from .static_list import StaticAliasListProducer


@dataclass(frozen=True)
class AliasProbeResult:
    """Task 1 probe contract.

    The full result shape is intentional even though Task 1 only fills a subset
    with meaningful values. Later tasks will populate ``service_email``,
    ``capture_summary``, ``steps``, and ``logs`` without changing this public
    contract.
    """

    ok: bool
    source_id: str
    source_type: str = ""
    alias_email: str = ""
    real_mailbox_email: str = ""
    service_email: str = ""
    capture_summary: list[dict[str, Any]] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    error: str = ""


class AliasSourceProbeService:
    def _as_string(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value)

    def _as_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def probe(self, pool_config: dict, source_id: str, task_id: str) -> AliasProbeResult:
        """Probe one configured alias source.

        ``task_id`` is part of the approved Task 1 interface even though the
        current single-source probe logic does not need task-scoped branching
        yet. Keeping it in the signature preserves the reviewed API contract for
        later task-aware probe flows.
        """

        source = self._find_source(pool_config=pool_config, source_id=source_id)
        if source is None:
            return AliasProbeResult(
                ok=False,
                source_id=source_id,
                error=f"source '{source_id}' not found",
            )

        source_type = str(source.get("type") or "")

        if source_type in {"static_list", "simple_generator"}:
            return self._probe_supported_source(source=source, task_id=task_id)
        if source_type == "vend_email":
            return self._probe_vend_email(source, task_id=task_id)
        return AliasProbeResult(
            ok=False,
            source_id=source_id,
            source_type=source_type,
            real_mailbox_email=self._as_string(source.get("mailbox_email")),
            error=f"Alias source type '{source_type}' is not recognized by the probe preview service.",
        )

    def _find_source(self, *, pool_config: dict, source_id: str) -> dict | None:
        sources = list(pool_config.get("sources") or [])
        for source in sources:
            if str(source.get("id") or "") == source_id:
                return source
        return None

    def _build_supported_producer(self, source: dict):
        source_type = self._as_string(source.get("type"))
        if source_type == "static_list":
            return StaticAliasListProducer(
                source_id=self._as_string(source.get("id")) or "legacy-static",
                emails=list(source.get("emails") or []),
                mailbox_email=self._as_string(source.get("mailbox_email")).strip().lower(),
            )
        if source_type == "simple_generator":
            return SimpleAliasGeneratorProducer(
                source_id=self._as_string(source.get("id")) or "simple-generator",
                prefix=self._as_string(source.get("prefix")),
                suffix=self._as_string(source.get("suffix")).strip().lower(),
                mailbox_email=self._as_string(source.get("mailbox_email")).strip().lower(),
                count=1,
                middle_length_min=self._as_int(source.get("middle_length_min"), 3),
                middle_length_max=self._as_int(source.get("middle_length_max"), 6),
            )
        return None

    def _has_invalid_simple_generator_bounds(self, source: dict) -> bool:
        if self._as_string(source.get("type")) != "simple_generator":
            return False
        middle_length_min = self._as_int(source.get("middle_length_min"), 0)
        middle_length_max = self._as_int(source.get("middle_length_max"), 0)
        return middle_length_min > middle_length_max

    def _probe_supported_source(self, *, source: dict, task_id: str) -> AliasProbeResult:
        source_id = self._as_string(source.get("id"))
        source_type = self._as_string(source.get("type"))
        producer = self._build_supported_producer(source)
        if producer is None:
            return AliasProbeResult(
                ok=False,
                source_id=source_id,
                source_type=source_type,
                real_mailbox_email=self._as_string(source.get("mailbox_email")),
                error=f"Alias source type '{source_type}' is not recognized by the probe preview service.",
            )

        manager = AliasEmailPoolManager(task_id=task_id)
        manager.register_source(producer)

        try:
            producer.load_into(manager)
            lease = manager.acquire_alias()
        except AliasPoolExhaustedError:
            return AliasProbeResult(
                ok=False,
                source_id=source_id,
                source_type=source_type,
                real_mailbox_email=self._as_string(source.get("mailbox_email")),
                error=f"No alias preview available for source '{source_id}'.",
            )
        except ValueError:
            if self._has_invalid_simple_generator_bounds(source):
                return AliasProbeResult(
                    ok=False,
                    source_id=source_id,
                    source_type=source_type,
                    real_mailbox_email=self._as_string(source.get("mailbox_email")),
                    error=f"Invalid simple_generator bounds for source '{source_id}'.",
                )
            raise

        return AliasProbeResult(
            ok=True,
            source_id=lease.source_id,
            source_type=lease.source_kind,
            alias_email=lease.alias_email,
            real_mailbox_email=lease.real_mailbox_email,
        )

    def _build_vend_executor(self, source: dict):
        from .vend_email_service import build_default_vend_executor

        return build_default_vend_executor(source)

    def _build_vend_runtime_handoff(self, *, source: dict, task_id: str):
        from .vend_email_service import VendEmailRuntimeService
        from .vend_email_state import VendEmailFileStateStore

        state_store = VendEmailFileStateStore.for_task(task_id=task_id)
        executor = self._build_vend_executor(source)
        runtime_service = VendEmailRuntimeService(
            state_store=state_store,
            executor=executor,
        )
        return state_store, executor, runtime_service

    def _probe_vend_email(self, source: dict, *, task_id: str) -> AliasProbeResult:
        _, _, runtime_service = self._build_vend_runtime_handoff(source=source, task_id=task_id)
        return runtime_service.run_probe(source=source)
