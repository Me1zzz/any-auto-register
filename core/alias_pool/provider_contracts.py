from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class AliasProviderSourceSpec:
    source_id: str
    provider_type: str
    raw_source: dict[str, Any]
    desired_alias_count: int = 0
    state_key: str = ""
    register_url: str = ""
    alias_domain: str = ""
    alias_domain_id: str = ""
    confirmation_inbox_config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AliasAutomationTestPolicy:
    fresh_service_account: bool
    persist_state: bool
    minimum_alias_count: int
    capture_enabled: bool


@dataclass(frozen=True)
class AliasProviderBootstrapContext:
    task_id: str
    purpose: str
    runtime_builder: Any = None
    state_store_factory: Any = None
    confirmation_reader: Any = None
    telemetry_sink: Any = None
    test_policy: AliasAutomationTestPolicy | None = None


@dataclass(frozen=True)
class AliasAccountIdentity:
    service_account_email: str = ""
    confirmation_inbox_email: str = ""
    real_mailbox_email: str = ""
    service_password: str = ""
    username: str = ""


@dataclass(frozen=True)
class AliasProviderStage:
    code: str
    label: str
    status: str
    detail: str = ""
    timestamp: str = ""


@dataclass(frozen=True)
class AliasProviderFailure:
    stage_code: str = ""
    stage_label: str = ""
    reason: str = ""
    retryable: bool | None = None
    category: str = ""


@dataclass(frozen=True)
class AliasProviderCapture:
    kind: str
    request_summary: dict[str, Any] = field(default_factory=dict)
    response_summary: dict[str, Any] = field(default_factory=dict)
    redaction_applied: bool = False


@dataclass(frozen=True)
class AliasAutomationTestResult:
    provider_type: str
    source_id: str
    account_identity: AliasAccountIdentity = field(default_factory=AliasAccountIdentity)
    aliases: list[dict[str, Any]] = field(default_factory=list)
    current_stage: AliasProviderStage | None = None
    stage_timeline: list[AliasProviderStage] = field(default_factory=list)
    failure: AliasProviderFailure = field(default_factory=AliasProviderFailure)
    capture_summary: list[AliasProviderCapture] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    ok: bool = True
    error: str = ""


@runtime_checkable
class AliasProvider(Protocol):
    source_id: str
    source_kind: str

    @property
    def provider_type(self) -> str:
        """Alias provider-facing vocabulary to existing alias-pool source_kind."""

        return self.source_kind

    def load_into(self, pool_manager) -> None: ...

    def run_alias_generation_test(
        self,
        policy: AliasAutomationTestPolicy,
    ) -> AliasAutomationTestResult: ...
