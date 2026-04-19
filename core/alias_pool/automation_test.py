from __future__ import annotations

from typing import Any, cast

from .config import build_alias_provider_source_specs
from .interactive_provider_builders import register_interactive_alias_provider_builders
from .provider_adapters import build_simple_generator_alias_provider, build_static_list_alias_provider
from .provider_bootstrap import AliasProviderBootstrap
from .provider_contracts import (
    AliasAccountIdentity,
    AliasAutomationTestPolicy,
    AliasAutomationTestResult,
    AliasProvider,
    AliasProviderBootstrapContext,
    AliasProviderCapture,
    AliasProviderFailure,
    AliasProviderSourceSpec,
    AliasProviderStage,
)
from .provider_registry import AliasProviderRegistry
from .probe import AliasProbeResult
from .vend_email_service import build_vend_email_alias_service_producer


class _VendEmailAliasProviderAdapter:
    source_kind = "vend_email"

    def __init__(self, *, spec: AliasProviderSourceSpec, context: AliasProviderBootstrapContext):
        self.source_id = spec.source_id
        self._spec = spec
        self._context = context

    @property
    def provider_type(self) -> str:
        return self.source_kind

    def load_into(self, pool_manager) -> None:
        raise AssertionError("automation test path should use run_alias_generation_test")

    def run_alias_generation_test(
        self,
        policy: AliasAutomationTestPolicy,
    ) -> AliasAutomationTestResult:
        producer = build_vend_email_alias_service_producer(
            source=dict(self._spec.raw_source or {}),
            task_id=self._context.task_id,
            state_store_factory=self._context.state_store_factory,
            runtime_builder=self._context.runtime_builder,
        )
        return cast(AliasProvider, producer).run_alias_generation_test(policy)


class AliasAutomationTestService:
    def __init__(
        self,
        *,
        source_spec_builder=None,
        bootstrap=None,
        policy: AliasAutomationTestPolicy | None = None,
        context: AliasProviderBootstrapContext | None = None,
    ):
        self._source_spec_builder = source_spec_builder or build_alias_provider_source_specs
        self._bootstrap = bootstrap or self._build_default_bootstrap()
        self._policy = policy
        self._context = context

    def _build_default_bootstrap(self):
        registry = AliasProviderRegistry()
        registry.register("static_list", build_static_list_alias_provider)
        registry.register("simple_generator", build_simple_generator_alias_provider)
        registry.register("vend_email", self._build_vend_email_alias_provider)
        register_interactive_alias_provider_builders(registry)
        return AliasProviderBootstrap(registry=registry)

    def _build_vend_email_alias_provider(
        self,
        spec: AliasProviderSourceSpec,
        context: AliasProviderBootstrapContext,
    ):
        return _VendEmailAliasProviderAdapter(spec=spec, context=context)

    def run(self, *, pool_config: dict, source_id: str, task_id: str) -> AliasProbeResult:
        specs = list(self._source_spec_builder(pool_config) or [])
        spec = next((item for item in specs if item.source_id == source_id), None)
        if spec is None:
            return AliasProbeResult(
                ok=False,
                source_id=source_id,
                error=f"source '{source_id}' not found",
            )

        policy = self._policy or AliasAutomationTestPolicy(
            fresh_service_account=True,
            persist_state=False,
            minimum_alias_count=3,
            capture_enabled=True,
        )
        context = self._context or AliasProviderBootstrapContext(
            task_id=task_id,
            purpose="automation_test",
            test_policy=policy,
        )
        if context.test_policy is None:
            context = AliasProviderBootstrapContext(
                task_id=context.task_id,
                purpose=context.purpose,
                runtime_builder=context.runtime_builder,
                state_store_factory=context.state_store_factory,
                confirmation_reader=context.confirmation_reader,
                telemetry_sink=context.telemetry_sink,
                test_policy=policy,
            )

        provider_type = str(spec.provider_type or "")
        try:
            provider = self._bootstrap.build(spec=spec, context=context)
            provider_provider_type = getattr(provider, "provider_type", None)
            if isinstance(provider_provider_type, str) and provider_provider_type.strip():
                provider_type = provider_provider_type
        except Exception as exc:
            return AliasProbeResult(
                ok=False,
                source_id=source_id,
                source_type=provider_type,
                failure={
                    "stageCode": "build_provider",
                    "stageLabel": "",
                    "reason": str(exc),
                },
                error=str(exc),
            )

        try:
            result = provider.run_alias_generation_test(policy)
        except Exception as exc:
            return AliasProbeResult(
                ok=False,
                source_id=source_id,
                source_type=provider_type,
                failure={
                    "stageCode": "run_alias_generation_test",
                    "stageLabel": "",
                    "reason": str(exc),
                },
                error=str(exc),
            )
        return self._to_probe_result(result)

    def _to_probe_result(self, result: AliasAutomationTestResult) -> AliasProbeResult:
        aliases = list(result.aliases or [])
        alias_email = ""
        if aliases and isinstance(aliases[0], dict):
            alias_email = str(aliases[0].get("email") or aliases[0].get("aliasEmail") or "")

        current_stage = {"code": "", "label": ""}
        if result.current_stage is not None:
            current_stage = {
                "code": str(result.current_stage.code or ""),
                "label": str(result.current_stage.label or ""),
            }

        stages = [
            dict(
                {"code": str(item.code or ""), "label": str(item.label or ""), "status": str(item.status or "")},
                **({"detail": str(item.detail or "")} if str(item.detail or "") else {}),
            )
            for item in list(result.stage_timeline or [])
        ]

        failure: dict[str, Any] = {
            "stageCode": str(result.failure.stage_code or ""),
            "stageLabel": str(result.failure.stage_label or ""),
            "reason": str(result.failure.reason or ""),
        }
        if result.failure.retryable is not None:
            failure["retryable"] = bool(result.failure.retryable)

        account = {
            "realMailboxEmail": str(result.account_identity.real_mailbox_email or ""),
            "serviceEmail": str(result.account_identity.service_account_email or ""),
            "password": str(result.account_identity.service_password or ""),
        }
        if str(result.account_identity.username or ""):
            account["username"] = str(result.account_identity.username or "")

        capture_summary = []
        for item in list(result.capture_summary or []):
            request_summary = dict(item.request_summary or {})
            response_summary = dict(item.response_summary or {})
            capture_summary.append(
                {
                    "name": str(item.kind or ""),
                    "url": str(request_summary.get("url") or ""),
                    "method": str(request_summary.get("method") or ""),
                    "request_headers_whitelist": dict(request_summary.get("request_headers_whitelist") or {}),
                    "request_body_excerpt": str(request_summary.get("request_body_excerpt") or ""),
                    "response_status": int(response_summary.get("response_status") or 0),
                    "response_body_excerpt": str(response_summary.get("response_body_excerpt") or ""),
                    "captured_at": str(response_summary.get("captured_at") or ""),
                }
            )

        return AliasProbeResult(
            ok=bool(result.ok),
            source_id=result.source_id,
            source_type=result.provider_type,
            alias_email=alias_email,
            real_mailbox_email=str(result.account_identity.real_mailbox_email or ""),
            service_email=str(result.account_identity.service_account_email or ""),
            account=account,
            aliases=aliases,
            capture_summary=capture_summary,
            steps=["load_source", "acquire_alias"] if bool(result.ok) else [],
            current_stage=current_stage,
            stages=stages,
            failure=failure,
            logs=[str(item) for item in list(result.logs or [])],
            error=str(result.error or ""),
        )
