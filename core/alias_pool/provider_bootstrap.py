from __future__ import annotations

from core.alias_pool.provider_contracts import AliasProvider, AliasProviderBootstrapContext, AliasProviderSourceSpec
from core.alias_pool.provider_registry import AliasProviderRegistry


class AliasProviderBootstrap:
    def __init__(self, *, registry: AliasProviderRegistry):
        self._registry = registry

    def build(
        self,
        *,
        spec: AliasProviderSourceSpec,
        context: AliasProviderBootstrapContext,
    ) -> AliasProvider:
        builder = self._registry.resolve(spec.provider_type)
        if builder is None:
            raise ValueError(f"Unsupported alias provider type: {spec.provider_type}")
        return builder(spec, context)
