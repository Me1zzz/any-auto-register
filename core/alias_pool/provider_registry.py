from __future__ import annotations

from typing import Protocol, TypeAlias

from .provider_contracts import AliasProvider, AliasProviderBootstrapContext, AliasProviderSourceSpec


class AliasProviderBuilder(Protocol):
    def __call__(
        self,
        spec: AliasProviderSourceSpec,
        context: AliasProviderBootstrapContext,
    ) -> AliasProvider: ...


ResolvedAliasProviderBuilder: TypeAlias = AliasProviderBuilder | None


class AliasProviderRegistry:
    def __init__(self):
        self._builders: dict[str, AliasProviderBuilder] = {}

    def register(self, provider_type: str, builder: AliasProviderBuilder) -> None:
        normalized_type = str(provider_type or "").strip()
        self._builders[normalized_type] = builder

    def resolve(self, provider_type: str) -> ResolvedAliasProviderBuilder:
        normalized_type = str(provider_type or "").strip()
        return self._builders.get(normalized_type)
