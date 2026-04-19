from __future__ import annotations

from .interactive_provider_models import (
    AliasCreatedRecord,
    AliasDomainOption,
    AuthenticatedProviderContext,
    VerificationRequirement,
)
from .interactive_provider_base import InteractiveAliasProviderBase


class AliasEmailProvider(InteractiveAliasProviderBase):
    source_kind = "alias_email"

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        inbox_email = str(self._spec.confirmation_inbox_config.get("match_email") or "").strip().lower()
        return AuthenticatedProviderContext(
            service_account_email=inbox_email,
            confirmation_inbox_email=inbox_email,
            real_mailbox_email=inbox_email,
        )

    def resolve_verification_requirements(self, context: AuthenticatedProviderContext) -> list[VerificationRequirement]:
        return [
            VerificationRequirement(
                kind="magic_link_login",
                label="消费登录魔法链接",
                inbox_role="confirmation_inbox",
            )
        ]

    def discover_alias_domains(self, context: AuthenticatedProviderContext) -> list[AliasDomainOption]:
        return [AliasDomainOption(key="alias.email", domain="alias.email", label="@alias.email")]

    def create_alias(
        self,
        *,
        context: AuthenticatedProviderContext,
        domain: AliasDomainOption | None,
        alias_index: int,
    ) -> AliasCreatedRecord:
        if domain is None:
            raise RuntimeError("alias.email requires discovered domains")
        return AliasCreatedRecord(email=f"alias-email-{alias_index}{domain.label}")


class AliasEmailAliasProvider(AliasEmailProvider):
    pass


def build_alias_email_alias_provider(spec, context):
    return AliasEmailProvider(spec=spec, context=context)
