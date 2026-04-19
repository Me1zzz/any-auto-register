from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AliasProbeResult:
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

    def probe(self, pool_config: dict, source_id: str, task_id: str) -> AliasProbeResult:
        from .automation_test import AliasAutomationTestService
        from .provider_contracts import AliasAutomationTestPolicy, AliasProviderBootstrapContext

        policy = AliasAutomationTestPolicy(
            fresh_service_account=True,
            persist_state=False,
            minimum_alias_count=3,
            capture_enabled=True,
        )
        context = AliasProviderBootstrapContext(
            task_id=task_id,
            purpose="automation_test",
            runtime_builder=self._runtime_builder,
            state_store_factory=self._state_store_factory,
            test_policy=policy,
        )
        return AliasAutomationTestService(policy=policy, context=context).run(
            pool_config=pool_config,
            source_id=source_id,
            task_id=task_id,
        )


def run_alias_source_probe(
    *,
    pool_config: dict,
    source_id: str,
    task_id: str,
    runtime_builder=None,
    state_store_factory=None,
) -> AliasProbeResult:
    service = AliasSourceProbeService(
        runtime_builder=runtime_builder,
        state_store_factory=state_store_factory,
    )
    return service.probe(pool_config=pool_config, source_id=source_id, task_id=task_id)
