from __future__ import annotations

import re
import secrets
from dataclasses import replace

from .interactive_provider_models import AliasCreatedRecord, AuthenticatedProviderContext


class SecureInSecondsAdapter:
    def __init__(self, *, spec):
        self._spec = spec

    @property
    def register_url(self) -> str:
        return str(self._spec.provider_config.get("register_url") or "https://alias.secureinseconds.com/auth/register").strip()

    @property
    def login_url(self) -> str:
        return str(self._spec.provider_config.get("login_url") or "https://alias.secureinseconds.com/auth/signin").strip()

    @property
    def alias_url(self) -> str:
        return str(self._spec.provider_config.get("alias_url") or "https://alias.secureinseconds.com/dashboard/aliases").strip()

    def classify_alias_gate(self, text: str) -> str:
        if "forward" in str(text or "").lower():
            return "forwarding_email"
        return ""

    def open_entrypoint(self, protocol_runtime, browser_runtime, context: AuthenticatedProviderContext) -> AuthenticatedProviderContext:
        protocol_runtime.get(self.register_url)
        session_state = {
            **dict(context.session_state or {}),
            "transport_mode": "protocol",
        }
        return replace(context, session_state=session_state)

    def authenticate_or_register(self, protocol_runtime, browser_runtime, context: AuthenticatedProviderContext) -> AuthenticatedProviderContext:
        password = str(context.service_password or secrets.token_urlsafe(12))
        account_email = str(context.confirmation_inbox_email or context.real_mailbox_email or "").strip().lower()
        protocol_runtime.post_form(self.register_url, {"email": account_email, "password": password})
        protocol_runtime.post_form(self.login_url, {"email": account_email, "password": password})
        session_state = {
            **dict(context.session_state or {}),
            "transport_mode": "protocol",
        }
        return replace(
            context,
            service_account_email=account_email,
            real_mailbox_email=str(context.real_mailbox_email or account_email),
            service_password=password,
            session_state=session_state,
        )

    def resolve_blocking_gate(self, protocol_runtime, browser_runtime, requirement, context: AuthenticatedProviderContext) -> AuthenticatedProviderContext:
        verification_link = str((context.session_state or {}).get("verification_link") or "").strip()
        if verification_link:
            protocol_runtime.get(verification_link)
        return context

    def load_alias_surface(self, protocol_runtime, browser_runtime, context: AuthenticatedProviderContext) -> AuthenticatedProviderContext:
        protocol_runtime.get(self.alias_url)
        return context

    def extract_domain_options(self, protocol_runtime, browser_runtime, context):
        return []

    def list_existing_aliases(self, protocol_runtime, browser_runtime, context):
        page = protocol_runtime.get(self.alias_url)
        emails = re.findall(r"[A-Za-z0-9._%+-]+@alias\.secureinseconds\.com", str(page.text or ""), re.IGNORECASE)
        return [{"email": email.lower()} for email in emails]

    def submit_alias_creation(self, protocol_runtime, browser_runtime, context, domain_option, alias_index: int) -> AliasCreatedRecord:
        local_part = f"secure-{alias_index}"
        response = protocol_runtime.post_form(self.alias_url, {"local_part": local_part})
        response_text = str(getattr(response, "text", "") or "")
        if self.classify_alias_gate(response_text) == "forwarding_email":
            verification_link = str((context.session_state or {}).get("verification_link") or "").strip()
            if verification_link:
                protocol_runtime.get(verification_link)
            response = protocol_runtime.post_form(self.alias_url, {"local_part": local_part})
            response_text = str(getattr(response, "text", "") or "")
        matched = re.search(r"([A-Za-z0-9._%+-]+@alias\.secureinseconds\.com)", response_text, re.IGNORECASE)
        email = matched.group(1).lower() if matched else f"{local_part}@alias.secureinseconds.com"
        return AliasCreatedRecord(
            email=email,
            metadata={"confirmed": True, "transport_mode": "protocol"},
        )
