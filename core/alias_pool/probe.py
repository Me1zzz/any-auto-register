from dataclasses import dataclass, field
from typing import Any

from .base import AliasPoolExhaustedError
from .manager import AliasEmailPoolManager
from .simple_generator import SimpleAliasGeneratorProducer
from .static_list import StaticAliasListProducer
from .vend_email_service import build_vend_email_alias_service_producer
from .vend_email_state import VendEmailServiceState


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
    account: dict[str, Any] = field(default_factory=dict)
    aliases: list[dict[str, Any]] = field(default_factory=list)
    capture_summary: list[dict[str, Any]] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    current_stage: dict[str, str] = field(default_factory=lambda: {"code": "", "label": ""})
    stages: list[dict[str, Any]] = field(default_factory=list)
    failure: dict[str, Any] = field(
        default_factory=lambda: {"stageCode": "", "stageLabel": "", "reason": ""}
    )
    logs: list[str] = field(default_factory=list)
    error: str = ""


class AliasSourceProbeService:
    def __init__(self, *, runtime_builder=None, state_store_factory=None):
        self._runtime_builder = runtime_builder
        self._state_store_factory = state_store_factory

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
            account=self._build_account_summary(
                real_mailbox_email=lease.real_mailbox_email,
                service_email="",
                password="",
                username="",
            ),
            aliases=[{"email": lease.alias_email}] if lease.alias_email else [],
        )

    def _build_account_summary(
        self,
        *,
        real_mailbox_email: str,
        service_email: str,
        password: str,
        username: str,
    ) -> dict[str, str]:
        account = {
            "realMailboxEmail": self._as_string(real_mailbox_email),
            "serviceEmail": self._as_string(service_email),
            "password": self._as_string(password),
        }
        if self._as_string(username):
            account["username"] = self._as_string(username)
        return account

    def _build_alias_items(self, aliases: list[str], *, limit: int | None = None) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for alias_email in aliases[:limit] if limit is not None else aliases:
            if not self._as_string(alias_email):
                continue
            result.append({"email": self._as_string(alias_email)})
        return result

    def _build_vend_preview_aliases(self, primary_alias: str, aliases: list[str], *, target_count: int) -> list[dict[str, str]]:
        preview_aliases = [self._as_string(item).strip().lower() for item in aliases if self._as_string(item).strip()]
        primary = self._as_string(primary_alias).strip().lower()
        if primary and primary not in preview_aliases:
            preview_aliases.insert(0, primary)
        elif primary:
            preview_aliases = [primary] + [item for item in preview_aliases if item != primary]
        if not preview_aliases and primary:
            preview_aliases = [primary]
        return self._build_alias_items(preview_aliases, limit=target_count)

    def _build_probe_vend_source(self, source: dict) -> dict[str, Any]:
        probe_source = dict(source)
        probe_source["alias_count"] = max(self._as_int(source.get("alias_count"), 0), 3)
        return probe_source

    def _build_probe_vend_state_store(self, *, source_id: str):
        class ProbeVendStateStore:
            def __init__(self, *, current_source_id: str):
                self._saved_state: VendEmailServiceState | None = None
                self._source_id = current_source_id

            def load(self, state_key: str) -> VendEmailServiceState:
                if self._saved_state is not None:
                    return self._saved_state
                return VendEmailServiceState(state_key=str(state_key or self._source_id))

            def save(self, state: VendEmailServiceState) -> None:
                self._saved_state = state

            @property
            def saved_state(self) -> VendEmailServiceState | None:
                return self._saved_state

        return ProbeVendStateStore(current_source_id=source_id)

    def _probe_vend_email(self, source: dict, *, task_id: str) -> AliasProbeResult:
        source_id = self._as_string(source.get("id")) or "vend-email"
        probe_source = self._build_probe_vend_source(source)
        manager = AliasEmailPoolManager(task_id=task_id)
        use_probe_transient_store = task_id == "alias-test"
        probe_state_store = self._build_probe_vend_state_store(source_id=source_id) if use_probe_transient_store else None
        state_store_factory = self._state_store_factory
        if probe_state_store is not None:
            state_store_factory = lambda *_args, **_kwargs: probe_state_store
        producer = build_vend_email_alias_service_producer(
            source=probe_source,
            task_id=task_id,
            state_store_factory=state_store_factory,
            runtime_builder=self._runtime_builder,
        )
        manager.register_source(producer)

        try:
            producer.load_into(manager)
            lease = manager.acquire_alias()
        except Exception as exc:
            return AliasProbeResult(
                ok=False,
                source_id=source_id,
                source_type="vend_email",
                real_mailbox_email=self._as_string(source.get("mailbox_email")),
                error=str(exc),
            )

        saved_state = probe_state_store.saved_state if probe_state_store is not None else None
        if saved_state is None:
            state_store = getattr(producer, "state_store", None)
            if state_store is not None and hasattr(state_store, "load"):
                try:
                    saved_state = state_store.load(str(source.get("state_key") or source_id))
                except Exception:
                    saved_state = None

        capture_summary = []
        if saved_state is not None:
            capture_summary = [
                item.to_dict() if hasattr(item, "to_dict") else item
                for item in list(getattr(saved_state, "last_capture_summary", []) or [])
            ]
        saved_aliases = []
        if saved_state is not None:
            saved_aliases = [
                self._as_string(item).strip().lower()
                for item in list(getattr(saved_state, "known_aliases", []) or [])
                if self._as_string(item).strip()
            ]
        preview_aliases = saved_aliases or [lease.alias_email]
        target_alias_count = max(self._as_int(probe_source.get("alias_count"), 0), 0)
        if target_alias_count == 0:
            target_alias_count = max(len(preview_aliases), 1)
        target_alias_count = max(target_alias_count, 3)

        service_email = self._as_string(getattr(saved_state, "service_email", ""))
        real_mailbox_email = self._as_string(getattr(saved_state, "mailbox_email", "")) or lease.real_mailbox_email
        service_password = self._as_string(getattr(saved_state, "service_password", ""))
        username = service_email.split("@", 1)[0] if "@" in service_email else ""
        current_stage = getattr(saved_state, "current_stage", {"code": "", "label": ""})
        if not isinstance(current_stage, dict):
            current_stage = {"code": "", "label": ""}
        stages = [
            dict(item)
            for item in list(getattr(saved_state, "stage_history", []) or [])
            if isinstance(item, dict)
        ]
        failure = getattr(saved_state, "last_failure", {"stageCode": "", "stageLabel": "", "reason": ""})
        if not isinstance(failure, dict):
            failure = {"stageCode": "", "stageLabel": "", "reason": ""}
        normalized_failure: dict[str, Any] = {
            "stageCode": self._as_string(failure.get("stageCode")),
            "stageLabel": self._as_string(failure.get("stageLabel")),
            "reason": self._as_string(failure.get("reason")),
        }
        if "retryable" in failure:
            normalized_failure["retryable"] = bool(failure.get("retryable"))

        alias_items = self._build_vend_preview_aliases(
            lease.alias_email,
            preview_aliases,
            target_count=target_alias_count,
        )
        normalized_stages = []
        for item in stages:
            normalized_item = dict(item)
            if str(normalized_item.get("code") or "") == "aliases_ready":
                normalized_item["detail"] = f"预览共 {len(alias_items)} 个别名"
            normalized_stages.append(normalized_item)

        return AliasProbeResult(
            ok=True,
            source_id=lease.source_id,
            source_type=lease.source_kind,
            alias_email=self._as_string(alias_items[0].get("email")) if alias_items else lease.alias_email,
            real_mailbox_email=real_mailbox_email,
            service_email=service_email,
            account=self._build_account_summary(
                real_mailbox_email=real_mailbox_email,
                service_email=service_email,
                password=service_password,
                username=username,
            ),
            aliases=alias_items,
            capture_summary=capture_summary,
            steps=["load_source", "acquire_alias"],
            current_stage=current_stage,
            stages=normalized_stages,
            failure=normalized_failure,
            logs=[],
            error="",
        )
