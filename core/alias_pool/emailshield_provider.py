from __future__ import annotations

from .interactive_provider_base import InteractiveAliasProviderBase
from .interactive_provider_models import AuthenticatedProviderContext


class EmailShieldAliasProvider(InteractiveAliasProviderBase):
    source_kind = "emailshield"

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        raise RuntimeError("emailshield interactive provider bootstrap not implemented yet")


def build_emailshield_alias_provider(spec, context):
    return EmailShieldAliasProvider(spec=spec, context=context)
