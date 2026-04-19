from __future__ import annotations

from .interactive_provider_base import ExistingAccountAliasProviderBase
from .interactive_provider_models import AuthenticatedProviderContext


class SimpleLoginAliasProvider(ExistingAccountAliasProviderBase):
    source_kind = "simplelogin"

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        account = self.select_service_account()
        confirmation_inbox = dict(self._spec.confirmation_inbox_config or {})
        inbox_email = str(
            confirmation_inbox.get("match_email")
            or confirmation_inbox.get("account_email")
            or ""
        ).strip().lower()
        return AuthenticatedProviderContext(
            service_account_email=account["email"],
            confirmation_inbox_email=inbox_email,
            real_mailbox_email=inbox_email,
            service_password=account["password"],
            username=account["label"],
        )

    def discover_alias_domains(self, context: AuthenticatedProviderContext):
        raise RuntimeError("simplelogin signed domain discovery not implemented yet")


def build_simplelogin_alias_provider(spec, context):
    return SimpleLoginAliasProvider(spec=spec, context=context)
