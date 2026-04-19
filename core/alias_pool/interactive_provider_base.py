from __future__ import annotations

from dataclasses import replace

from core.alias_pool.base import AliasEmailLease
from core.alias_pool.interactive_provider_models import (
    AliasCreatedRecord,
    AliasDomainOption,
    AuthenticatedProviderContext,
    VerificationRequirement,
)
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

        try:
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
            update_last("completed", detail=f"找到 {len(aliases)} 个别名")

            target = max(int(policy.minimum_alias_count or 0), int(self._spec.desired_alias_count or 0), 1)
            record("create_aliases", "创建别名", "pending")
            while len(aliases) < target:
                alias_index = len(aliases) + 1
                domain = self.pick_domain_option(domains, alias_index)
                created = self.create_alias(context=context, domain=domain, alias_index=alias_index)
                aliases.append({"email": created.email, **dict(created.metadata or {})})

            update_last("completed", detail=f"预览共 {len(aliases)} 个别名")
            record("aliases_ready", "别名预览已生成", "completed", detail=f"预览共 {len(aliases)} 个别名")
            record("save_state", "保存预览状态", "completed")

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
                capture_summary=self.build_capture_summary() if policy.capture_enabled else [],
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
                capture_summary=self.build_capture_summary(),
                logs=[str(exc)],
                ok=False,
                error=str(exc),
            )

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
