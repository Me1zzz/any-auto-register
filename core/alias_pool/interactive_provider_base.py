from __future__ import annotations

from dataclasses import replace
from typing import Mapping, Sequence

from core.alias_pool.base import AliasEmailLease
from core.alias_pool.interactive_provider_models import (
    AliasCreatedRecord,
    AliasDomainOption,
    AuthenticatedProviderContext,
    VerificationRequirement,
)
from core.alias_pool.interactive_provider_state import InteractiveProviderState
from core.alias_pool.interactive_state_repository import InteractiveStateRepository
from core.alias_pool.provider_contracts import (
    AliasAccountIdentity,
    AliasAutomationTestPolicy,
    AliasAutomationTestResult,
    AliasProviderBootstrapContext,
    AliasProviderCapture,
    AliasProviderFailure,
    AliasProviderSourceSpec,
    AliasProviderStage,
)


_REQUIREMENT_STAGE_CODES = {
    "account_email": "verify_account_email",
    "forwarding_email": "verify_forwarding_email",
    "magic_link_login": "consume_magic_link",
}


class InteractiveAliasProviderBase:
    source_kind = "interactive_alias_provider"

    def __init__(self, *, spec: AliasProviderSourceSpec, context: AliasProviderBootstrapContext):
        self._spec = spec
        self._context = context
        self.source_id = spec.source_id
        self._state_repository = self._build_state_repository()

    @property
    def provider_type(self) -> str:
        return self.source_kind

    def load_into(self, pool_manager) -> None:
        result = self.run_alias_generation_test(
            AliasAutomationTestPolicy(
                fresh_service_account=False,
                persist_state=True,
                minimum_alias_count=max(int(self._spec.desired_alias_count or 0), 1),
                capture_enabled=True,
            )
        )
        if not result.ok:
            raise RuntimeError(result.error or result.failure.reason or f"{self.provider_type} alias generation failed")

        for item in list(result.aliases or []):
            email = str(item.get("email") or "").strip().lower()
            if not email:
                continue
            pool_manager.add_lease(
                AliasEmailLease(
                    alias_email=email,
                    real_mailbox_email=str(result.account_identity.real_mailbox_email or "").strip().lower(),
                    source_kind=self.provider_type,
                    source_id=self.source_id,
                    source_session_id=self._spec.state_key or self.source_id,
                )
            )

    def run_alias_generation_test(self, policy: AliasAutomationTestPolicy) -> AliasAutomationTestResult:
        timeline: list[AliasProviderStage] = []

        def record(code: str, label: str, status: str, detail: str = "") -> None:
            timeline.append(AliasProviderStage(code=code, label=label, status=status, detail=detail))

        def update_last(status: str, detail: str = "") -> None:
            if not timeline:
                return
            last = timeline[-1]
            timeline[-1] = AliasProviderStage(
                code=last.code,
                label=last.label,
                status=status,
                detail=detail,
            )

        state = None

        try:
            if policy.fresh_service_account:
                state = self._state_repository.new_state()
            else:
                state = self._state_repository.load()

            context = self.ensure_authenticated_context("alias_test")
            record("session_ready", "会话已就绪", "completed")

            for requirement in self.resolve_verification_requirements(context):
                stage_code = _REQUIREMENT_STAGE_CODES.get(requirement.kind, requirement.kind)
                record(stage_code, requirement.label, "pending")
                context = self.satisfy_verification_requirement(requirement, context)
                update_last("completed")

            record("discover_alias_domains", "发现可用域名", "pending")
            domains = list(self.discover_alias_domains(context))
            context = replace(context, domain_options=domains)
            update_last("completed", detail=f"找到 {len(domains)} 个域名选项")

            record("list_aliases", "列出现有别名", "pending")
            aliases = [
                dict(item)
                for item in list(self.list_existing_aliases(context))
                if isinstance(item, dict)
            ]
            aliases = self._dedupe_alias_items(aliases)
            update_last("completed", detail=f"找到 {len(aliases)} 个别名")

            target = max(int(policy.minimum_alias_count or 0), int(self._spec.desired_alias_count or 0), 1)
            record("create_aliases", "创建别名", "pending")
            creation_attempt_count = len(aliases)
            stalled_attempt_count = 0
            max_stalled_attempts = max(target, 1)
            while len(aliases) < target and stalled_attempt_count < max_stalled_attempts:
                previous_alias_count = len(aliases)
                creation_attempt_count += 1
                alias_index = creation_attempt_count
                domain = self.pick_domain_option(domains, alias_index)
                created = self.create_alias(context=context, domain=domain, alias_index=alias_index)
                aliases.append({"email": created.email, **dict(created.metadata or {})})
                aliases = self._dedupe_alias_items(aliases)
                if len(aliases) == previous_alias_count:
                    stalled_attempt_count += 1
                    continue
                stalled_attempt_count = 0

            update_last("completed", detail=f"预览共 {len(aliases)} 个别名")
            record("aliases_ready", "别名预览已生成", "completed", detail=f"预览共 {len(aliases)} 个别名")

            self._update_state_from_context(state, context)
            state.domain_options = [self._domain_to_state_item(item) for item in domains]
            state.known_aliases = [
                str(item.get("email") or "").strip().lower()
                for item in aliases
                if str(item.get("email") or "").strip()
            ]
            state.current_stage = {"code": "aliases_ready", "label": "别名预览已生成"}
            state.stage_history = [self._stage_to_state_item(item) for item in timeline]
            state.last_failure = {"stageCode": "", "stageLabel": "", "reason": ""}
            state.last_error = ""
            if policy.capture_enabled:
                state.last_capture_summary = [self._capture_to_state_item(item) for item in self.build_capture_summary()]
            else:
                state.last_capture_summary = []

            if policy.persist_state:
                record("save_state", "保存预览状态", "pending")
                self._state_repository.save(state)
                update_last("completed")

            return AliasAutomationTestResult(
                provider_type=self.provider_type,
                source_id=self.source_id,
                account_identity=AliasAccountIdentity(
                    service_account_email=context.service_account_email,
                    confirmation_inbox_email=context.confirmation_inbox_email,
                    real_mailbox_email=context.real_mailbox_email,
                    service_password=context.service_password,
                    username=context.username,
                ),
                aliases=aliases[:target],
                current_stage=timeline[-1],
                stage_timeline=timeline,
                failure=AliasProviderFailure(),
                capture_summary=self._capture_summary_for_policy(policy),
                logs=[],
                ok=True,
                error="",
            )
        except Exception as exc:
            if timeline:
                failed_stage = timeline[-1]
                timeline[-1] = AliasProviderStage(
                    code=failed_stage.code,
                    label=failed_stage.label,
                    status="failed",
                    detail=str(exc),
                )
                current_stage = timeline[-1]
            else:
                current_stage = AliasProviderStage(code="session_ready", label="", status="failed", detail=str(exc))
                timeline.append(current_stage)

            return AliasAutomationTestResult(
                provider_type=self.provider_type,
                source_id=self.source_id,
                current_stage=current_stage,
                stage_timeline=timeline,
                failure=AliasProviderFailure(
                    stage_code=current_stage.code,
                    stage_label=current_stage.label,
                    reason=str(exc),
                    retryable=True,
                ),
                capture_summary=self._capture_summary_for_policy(policy),
                logs=[str(exc)],
                ok=False,
                error=str(exc),
            )

    def _build_state_repository(self) -> InteractiveStateRepository:
        state_key = self._spec.state_key or self.source_id
        store_factory = getattr(self._context, "state_store_factory", None)
        store = store_factory(state_key) if callable(store_factory) else None
        return InteractiveStateRepository(store=store, state_key=state_key)

    def _capture_summary_for_policy(self, policy: AliasAutomationTestPolicy) -> list[AliasProviderCapture]:
        if not policy.capture_enabled:
            return []
        return self.build_capture_summary()

    def _dedupe_alias_items(self, aliases: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
        unique_aliases: list[dict[str, object]] = []
        seen: set[str] = set()
        for item in aliases:
            email = str(item.get("email") or "").strip().lower()
            if not email or email in seen:
                continue
            seen.add(email)
            normalized = dict(item)
            normalized["email"] = email
            unique_aliases.append(normalized)
        return unique_aliases

    def _update_state_from_context(self, state: InteractiveProviderState, context: AuthenticatedProviderContext) -> None:
        state.service_account_email = context.service_account_email
        state.confirmation_inbox_email = context.confirmation_inbox_email
        state.real_mailbox_email = context.real_mailbox_email
        state.service_password = context.service_password
        state.username = context.username
        state.session_state = dict(context.session_state)

    def _domain_to_state_item(self, domain: AliasDomainOption) -> dict[str, object]:
        return {
            "key": domain.key,
            "domain": domain.domain,
            "label": domain.label,
            "raw": dict(domain.raw),
        }

    def _stage_to_state_item(self, stage: AliasProviderStage) -> dict[str, str]:
        return {
            "code": stage.code,
            "label": stage.label,
            "status": stage.status,
            "detail": stage.detail,
        }

    def _capture_to_state_item(self, capture: AliasProviderCapture) -> dict[str, object]:
        return {
            "kind": capture.kind,
            "request_summary": dict(capture.request_summary),
            "response_summary": dict(capture.response_summary),
            "redaction_applied": bool(capture.redaction_applied),
        }

    def pick_domain_option(self, domains: list[AliasDomainOption], alias_index: int) -> AliasDomainOption | None:
        if not domains:
            return None
        return domains[(alias_index - 1) % len(domains)]

    def build_capture_summary(self) -> list[AliasProviderCapture]:
        return []

    def list_existing_aliases(self, context: AuthenticatedProviderContext) -> list[dict[str, str]]:
        return []

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        raise NotImplementedError

    def resolve_verification_requirements(self, context: AuthenticatedProviderContext) -> list[VerificationRequirement]:
        return []

    def satisfy_verification_requirement(
        self,
        requirement: VerificationRequirement,
        context: AuthenticatedProviderContext,
    ) -> AuthenticatedProviderContext:
        return context

    def discover_alias_domains(self, context: AuthenticatedProviderContext) -> list[AliasDomainOption]:
        return []

    def create_alias(
        self,
        *,
        context: AuthenticatedProviderContext,
        domain: AliasDomainOption | None,
        alias_index: int,
    ) -> AliasCreatedRecord:
        raise NotImplementedError


class ExistingAccountAliasProviderBase(InteractiveAliasProviderBase):
    def select_service_account(self) -> dict[str, str]:
        accounts = list(self._spec.provider_config.get("accounts") or [])
        if not accounts:
            raise RuntimeError(f"{self.provider_type} provider requires at least one existing account")

        account = dict(accounts[0])
        email = str(account.get("email") or "").strip().lower()
        if not email:
            raise RuntimeError(f"{self.provider_type} provider requires account email")

        password = str(account.get("password") or email).strip()
        label = str(account.get("label") or account.get("username") or email.split("@")[0]).strip()
        return {"email": email, "password": password, "label": label}
