from __future__ import annotations

import re
import secrets
from dataclasses import replace

from .interactive_provider_models import AliasCreatedRecord, AuthenticatedProviderContext


class EmailShieldAdapter:
    def __init__(self, *, spec):
        self._spec = spec

    @property
    def register_url(self) -> str:
        return str(self._spec.provider_config.get("register_url") or "https://emailshield.app/accounts/register/").strip()

    @property
    def login_url(self) -> str:
        return str(self._spec.provider_config.get("login_url") or "https://emailshield.app/accounts/login/").strip()

    @property
    def alias_url(self) -> str:
        return str(self._spec.provider_config.get("alias_url") or "https://emailshield.app/dashboard/add/").strip()

    def classify_dashboard_gate(self, path: str) -> str:
        if "/accounts/verify-email/" in str(path or ""):
            return "account_email"
        return ""

    def _ensure_protocol_success(self, response, *, action: str) -> str:
        status_code = int(getattr(response, "status_code", 0) or 0)
        body = str(getattr(response, "text", "") or "")
        if status_code < 200 or status_code >= 300:
            raise RuntimeError(f"emailshield {action} failed")
        lowered = body.strip().lower()
        if lowered and any(token in lowered for token in ("error", "failed", "denied", "invalid")):
            raise RuntimeError(f"emailshield {action} failed")
        return body

    def open_entrypoint(self, protocol_runtime, browser_runtime, context: AuthenticatedProviderContext) -> AuthenticatedProviderContext:
        response = protocol_runtime.get(self.register_url)
        self._ensure_protocol_success(response, action="register entrypoint")
        session_state = {
            **dict(context.session_state or {}),
            "transport_mode": "protocol",
            "register_url": self.register_url,
        }
        return replace(context, session_state=session_state)

    def authenticate_or_register(self, protocol_runtime, browser_runtime, context: AuthenticatedProviderContext) -> AuthenticatedProviderContext:
        password = str(context.service_password or secrets.token_urlsafe(12))
        register_page = protocol_runtime.get(self.register_url)
        register_html = self._ensure_protocol_success(register_page, action="registration")
        hidden = protocol_runtime.extract_hidden_inputs(register_html, names=("csrfmiddlewaretoken", "csrf_token"))
        account_email = str(context.confirmation_inbox_email or context.real_mailbox_email or "").strip().lower()
        register_response = protocol_runtime.post_form(
            self.register_url,
            {
                **dict(hidden or {}),
                "email": account_email,
                "password1": password,
                "password2": password,
            },
        )
        self._ensure_protocol_success(register_response, action="registration")
        login_response = protocol_runtime.post_form(
            self.login_url,
            {"email": account_email, "password": password},
        )
        self._ensure_protocol_success(login_response, action="login")
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
        if requirement.kind == "account_email" and verification_link:
            response = protocol_runtime.get(verification_link)
            self._ensure_protocol_success(response, action="account email verification")
        return context

    def load_alias_surface(self, protocol_runtime, browser_runtime, context: AuthenticatedProviderContext) -> AuthenticatedProviderContext:
        response = protocol_runtime.get(self.alias_url)
        self._ensure_protocol_success(response, action="alias surface load")
        return context

    def extract_domain_options(self, protocol_runtime, browser_runtime, context):
        return []

    def list_existing_aliases(self, protocol_runtime, browser_runtime, context):
        return []

    def submit_alias_creation(self, protocol_runtime, browser_runtime, context, domain_option, alias_index: int) -> AliasCreatedRecord:
        local_part = f"shield-{alias_index}"
        response = protocol_runtime.post_form(self.alias_url, {"local_part": local_part})
        body = self._ensure_protocol_success(response, action="alias creation")
        matched = re.search(r"([A-Za-z0-9._%+-]+@emailshield\.cc)", body, re.IGNORECASE)
        if matched is None:
            raise RuntimeError("emailshield alias creation failed")
        email = matched.group(1).lower()
        return AliasCreatedRecord(
            email=email,
            metadata={"confirmed": True, "transport_mode": "protocol"},
        )
