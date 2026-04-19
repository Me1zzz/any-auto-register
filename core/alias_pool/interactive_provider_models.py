from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VerificationRequirement:
    kind: str
    label: str
    inbox_role: str
    required: bool = True


@dataclass(frozen=True)
class AliasDomainOption:
    key: str
    domain: str
    label: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuthenticatedProviderContext:
    service_account_email: str = ""
    confirmation_inbox_email: str = ""
    real_mailbox_email: str = ""
    service_password: str = ""
    username: str = ""
    session_state: dict[str, Any] = field(default_factory=dict)
    domain_options: list[AliasDomainOption] = field(default_factory=list)


@dataclass(frozen=True)
class AliasCreatedRecord:
    email: str
    metadata: dict[str, Any] = field(default_factory=dict)
