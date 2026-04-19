from __future__ import annotations

from .interactive_provider_base import InteractiveAliasProviderBase
from .interactive_provider_models import AuthenticatedProviderContext


class SecureInSecondsAliasProvider(InteractiveAliasProviderBase):
    source_kind = "secureinseconds"

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        raise RuntimeError("secureinseconds interactive provider bootstrap not implemented yet")


def build_secureinseconds_alias_provider(spec, context):
    return SecureInSecondsAliasProvider(spec=spec, context=context)
