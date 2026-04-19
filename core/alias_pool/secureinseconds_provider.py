from __future__ import annotations

from .interactive_provider_base import InteractiveAliasProviderBase
from .interactive_provider_models import AliasCreatedRecord, AuthenticatedProviderContext, VerificationRequirement


class SecureInSecondsProvider(InteractiveAliasProviderBase):
    source_kind = "secureinseconds"

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
        return [VerificationRequirement(kind="forwarding_email", label="验证转发邮箱", inbox_role="confirmation_inbox")]

    def create_alias(self, *, context: AuthenticatedProviderContext, domain, alias_index: int) -> AliasCreatedRecord:
        return AliasCreatedRecord(email=f"secure-{alias_index}@alias.secureinseconds.com")


def build_secureinseconds_alias_provider(spec, context):
    return SecureInSecondsProvider(spec=spec, context=context)
