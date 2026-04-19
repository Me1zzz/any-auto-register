from __future__ import annotations

from .alias_email_provider import build_alias_email_alias_provider
from .emailshield_provider import build_emailshield_alias_provider
from .myalias_pro_provider import build_myalias_pro_alias_provider
from .provider_registry import AliasProviderRegistry
from .secureinseconds_provider import build_secureinseconds_alias_provider
from .simplelogin_provider import build_simplelogin_alias_provider


def register_interactive_alias_providers(registry: AliasProviderRegistry) -> AliasProviderRegistry:
    registry.register("myalias_pro", build_myalias_pro_alias_provider)
    registry.register("secureinseconds", build_secureinseconds_alias_provider)
    registry.register("emailshield", build_emailshield_alias_provider)
    registry.register("simplelogin", build_simplelogin_alias_provider)
    registry.register("alias_email", build_alias_email_alias_provider)
    return registry
