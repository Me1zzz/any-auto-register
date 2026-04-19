from __future__ import annotations

from .interactive_provider_base import InteractiveAliasProviderBase
from .interactive_provider_models import AliasCreatedRecord, AuthenticatedProviderContext, VerificationRequirement


class MyAliasProProvider(InteractiveAliasProviderBase):
    source_kind = "myalias_pro"

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        inbox_email = str(
            self._spec.confirmation_inbox_config.get("match_email")
            or self._spec.confirmation_inbox_config.get("account_email")
            or ""
        ).strip().lower()
        return AuthenticatedProviderContext(
            confirmation_inbox_email=inbox_email,
            real_mailbox_email=inbox_email,
        )

    def resolve_verification_requirements(self, context: AuthenticatedProviderContext) -> list[VerificationRequirement]:
        return [VerificationRequirement(kind="account_email", label="验证服务账号邮箱", inbox_role="confirmation_inbox")]

    def create_alias(self, *, context: AuthenticatedProviderContext, domain, alias_index: int) -> AliasCreatedRecord:
        return AliasCreatedRecord(email=f"myalias-{alias_index}@myalias.pro")


def build_myalias_pro_alias_provider(spec, context):
    return MyAliasProProvider(spec=spec, context=context)
