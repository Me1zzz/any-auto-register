from __future__ import annotations

from .interactive_provider_base import InteractiveAliasProviderBase
from .interactive_provider_models import AuthenticatedProviderContext


class AliasEmailAliasProvider(InteractiveAliasProviderBase):
    source_kind = "alias_email"

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        raise RuntimeError("alias_email interactive provider bootstrap not implemented yet")


def build_alias_email_alias_provider(spec, context):
    return AliasEmailAliasProvider(spec=spec, context=context)
