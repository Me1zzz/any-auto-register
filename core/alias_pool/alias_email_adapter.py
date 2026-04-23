from __future__ import annotations

import re
from dataclasses import replace

from .interactive_provider_models import AliasCreatedRecord, AliasDomainOption, AuthenticatedProviderContext


class AliasEmailAdapter:
    def __init__(self, *, spec):
        self._spec = spec

    @property
    def login_url(self) -> str:
        return str(self._spec.provider_config.get("login_url") or "https://alias.email/users/login/").strip()

    @property
    def alias_url(self) -> str:
        return str(self._spec.provider_config.get("alias_url") or "https://alias.email/aliases/").strip()

    def open_entrypoint(self, protocol_runtime, browser_runtime, context: AuthenticatedProviderContext) -> AuthenticatedProviderContext:
        protocol_runtime.get(self.login_url)
        return context

    def authenticate_or_register(self, protocol_runtime, browser_runtime, context: AuthenticatedProviderContext) -> AuthenticatedProviderContext:
        account_email = str(context.confirmation_inbox_email or context.real_mailbox_email or "").strip().lower()
        protocol_runtime.post_form(self.login_url, {"email": account_email})
        session_state = {
            **dict(context.session_state or {}),
            "transport_mode": "protocol",
        }
        return replace(
            context,
            service_account_email=account_email,
            real_mailbox_email=str(context.real_mailbox_email or account_email),
            session_state=session_state,
        )

    def resolve_blocking_gate(self, protocol_runtime, browser_runtime, requirement, context: AuthenticatedProviderContext) -> AuthenticatedProviderContext:
        verification_link = str((context.session_state or {}).get("verification_link") or "").strip()
        if requirement.kind == "magic_link_login" and verification_link:
            protocol_runtime.get(verification_link)
        return context

    def load_alias_surface(self, protocol_runtime, browser_runtime, context: AuthenticatedProviderContext) -> AuthenticatedProviderContext:
        protocol_runtime.get(self.alias_url)
        return context

    def extract_domain_options(self, protocol_runtime, browser_runtime, context):
        return [AliasDomainOption(key="alias.email", domain="alias.email", label="@alias.email")]

    def list_existing_aliases(self, protocol_runtime, browser_runtime, context):
        page = protocol_runtime.get(self.alias_url)
        emails = re.findall(r"[A-Za-z0-9._%+-]+@alias\.email", str(getattr(page, "text", "") or ""), re.IGNORECASE)
        return [{"email": email.lower()} for email in emails]

    def submit_alias_creation(self, protocol_runtime, browser_runtime, context, domain_option, alias_index: int) -> AliasCreatedRecord:
        local_part = f"alias-email-{alias_index}"
        response = protocol_runtime.post_form(self.alias_url, {"local_part": local_part})
        matched = re.search(r"([A-Za-z0-9._%+-]+@alias\.email)", str(getattr(response, "text", "") or ""), re.IGNORECASE)
        email = matched.group(1).lower() if matched else f"{local_part}@alias.email"
        return AliasCreatedRecord(
            email=email,
            metadata={
                "confirmed": True,
                "transport_mode": str((context.session_state or {}).get("transport_mode") or "protocol"),
            },
        )
