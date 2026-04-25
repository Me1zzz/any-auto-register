from __future__ import annotations

from typing import Any

from core.alias_pool.base import AliasPoolExhaustedError, AliasPoolStarvedError
from core.alias_pool.manager import AliasEmailPoolManager
from core.alias_pool.provider_contracts import (
    AliasAccountIdentity,
    AliasAutomationTestPolicy,
    AliasAutomationTestResult,
    AliasProviderBootstrapContext,
    AliasProviderFailure,
    AliasProviderSourceSpec,
    AliasProviderStage,
)
from core.alias_pool.simple_generator import SimpleAliasGeneratorProducer
from core.alias_pool.static_list import StaticAliasListProducer


class _SingleAliasProducerAdapter:
    def __init__(
        self,
        *,
        producer: Any,
        source_id: str,
        source_kind: str,
        mailbox_email: str,
        task_id: str,
        alias_count: int,
        low_watermark: int = 0,
    ):
        self.producer = producer
        self.source_id = source_id
        self.source_kind = source_kind
        self.mailbox_email = mailbox_email
        self.task_id = task_id
        self.alias_count = max(int(alias_count or 0), 0)
        self.low_watermark = max(int(low_watermark or 0), 0)

    @property
    def provider_type(self) -> str:
        return self.source_kind

    def load_into(self, pool_manager) -> None:
        self.producer.load_into(pool_manager)

    def ensure_available(self, pool_manager, *, minimum_count: int = 1) -> None:
        ensure_available = getattr(self.producer, "ensure_available", None)
        if callable(ensure_available):
            ensure_available(pool_manager, minimum_count=minimum_count)
            return
        self.producer.load_into(pool_manager)

    def run_alias_generation_test(
        self,
        policy: AliasAutomationTestPolicy,
    ) -> AliasAutomationTestResult:
        target_alias_count = max(self.alias_count, int(policy.minimum_alias_count or 0), 1)
        if hasattr(self.producer, "count"):
            self.producer.count = target_alias_count
        if hasattr(self.producer, "_remaining_count"):
            self.producer._remaining_count = max(
                int(getattr(self.producer, "_remaining_count", 0) or 0),
                target_alias_count,
            )
        manager = AliasEmailPoolManager(task_id=self.task_id)
        self.load_into(manager)
        aliases: list[dict[str, str]] = []
        real_mailbox_email = self.mailbox_email
        for _ in range(target_alias_count):
            try:
                lease = manager.acquire_alias(wait_timeout_seconds=0)
            except (AliasPoolExhaustedError, AliasPoolStarvedError):
                break
            if not real_mailbox_email:
                real_mailbox_email = lease.real_mailbox_email
            aliases.append({"email": lease.alias_email})
        if not aliases:
            raise AliasPoolExhaustedError("No alias preview available")
        return AliasAutomationTestResult(
            provider_type=self.provider_type,
            source_id=self.source_id,
            account_identity=AliasAccountIdentity(real_mailbox_email=real_mailbox_email),
            aliases=aliases,
            current_stage=AliasProviderStage(code="ready", label="Ready", status="completed"),
            stage_timeline=[AliasProviderStage(code="ready", label="Ready", status="completed")],
            failure=AliasProviderFailure(),
            ok=True,
            error="",
        )


def build_static_list_alias_provider(
    spec: AliasProviderSourceSpec,
    context: AliasProviderBootstrapContext,
):
    source = dict(spec.raw_source or {})
    producer = StaticAliasListProducer(
        source_id=spec.source_id or "legacy-static",
        emails=list(source.get("emails") or []),
        mailbox_email=str(source.get("mailbox_email") or "").strip().lower(),
    )
    return _SingleAliasProducerAdapter(
        producer=producer,
        source_id=spec.source_id,
        source_kind="static_list",
        mailbox_email=str(source.get("mailbox_email") or "").strip().lower(),
        task_id=context.task_id,
        alias_count=max(spec.desired_alias_count, 0),
        low_watermark=source.get("low_watermark") or 0,
    )


def build_simple_generator_alias_provider(
    spec: AliasProviderSourceSpec,
    context: AliasProviderBootstrapContext,
):
    source = dict(spec.raw_source or {})
    producer = SimpleAliasGeneratorProducer(
        source_id=spec.source_id or "simple-generator",
        prefix=str(source.get("prefix") or ""),
        suffix=str(source.get("suffix") or "").strip().lower(),
        mailbox_email=str(source.get("mailbox_email") or "").strip().lower(),
        count=max(spec.desired_alias_count, 1),
        middle_length_min=int(source.get("middle_length_min") or 3),
        middle_length_max=int(source.get("middle_length_max") or 6),
    )
    return _SingleAliasProducerAdapter(
        producer=producer,
        source_id=spec.source_id,
        source_kind="simple_generator",
        mailbox_email=str(source.get("mailbox_email") or "").strip().lower(),
        task_id=context.task_id,
        alias_count=max(spec.desired_alias_count, 0),
        low_watermark=source.get("low_watermark") or 0,
    )
