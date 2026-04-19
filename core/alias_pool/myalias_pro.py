from __future__ import annotations

from .interactive_provider_base import InteractiveAliasProviderBase
from .interactive_provider_models import AuthenticatedProviderContext


class MyAliasProAliasProvider(InteractiveAliasProviderBase):
    source_kind = "myalias_pro"

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        raise RuntimeError("myalias_pro interactive provider bootstrap not implemented yet")


def build_myalias_pro_alias_provider(spec, context):
    return MyAliasProAliasProvider(spec=spec, context=context)
