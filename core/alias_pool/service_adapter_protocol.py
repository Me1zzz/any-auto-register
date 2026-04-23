from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from core.alias_pool.interactive_provider_models import (
    AliasCreatedRecord,
    AliasDomainOption,
    AuthenticatedProviderContext,
    VerificationRequirement,
)


@dataclass(frozen=True)
class SiteSessionContext:
    current_url: str = ""
    page_state: dict[str, Any] = field(default_factory=dict)
    capture_keys: list[str] = field(default_factory=list)


class AliasServiceAdapter(Protocol):
    def open_entrypoint(
        self,
        protocol_runtime,
        browser_runtime,
        context: AuthenticatedProviderContext,
    ) -> AuthenticatedProviderContext: ...

    def authenticate_or_register(
        self,
        protocol_runtime,
        browser_runtime,
        context: AuthenticatedProviderContext,
    ) -> AuthenticatedProviderContext: ...

    def resolve_blocking_gate(
        self,
        protocol_runtime,
        browser_runtime,
        requirement: VerificationRequirement,
        context: AuthenticatedProviderContext,
    ) -> AuthenticatedProviderContext: ...

    def load_alias_surface(
        self,
        protocol_runtime,
        browser_runtime,
        context: AuthenticatedProviderContext,
    ) -> AuthenticatedProviderContext: ...

    def extract_domain_options(
        self,
        protocol_runtime,
        browser_runtime,
        context: AuthenticatedProviderContext,
    ) -> list[AliasDomainOption]: ...

    def list_existing_aliases(
        self,
        protocol_runtime,
        browser_runtime,
        context: AuthenticatedProviderContext,
    ) -> list[dict[str, str]]: ...

    def submit_alias_creation(
        self,
        protocol_runtime,
        browser_runtime,
        context: AuthenticatedProviderContext,
        domain_option: AliasDomainOption | None,
        alias_index: int,
    ) -> AliasCreatedRecord: ...
