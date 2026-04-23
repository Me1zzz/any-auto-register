from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urljoin

from .interactive_provider_base import ExistingAccountAliasProviderBase
from .interactive_provider_models import AliasCreatedRecord, AuthenticatedProviderContext
from .provider_contracts import AliasProviderCapture


class EmailShieldProvider(ExistingAccountAliasProviderBase):
    source_kind = "emailshield"

    def __init__(self, *, spec, context):
        super().__init__(spec=spec, context=context)
        self._captures: list[AliasProviderCapture] = []
        self._session: Any = None
        self._session_base_url = ""
        self._authenticated_account_email = ""

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        account = self.select_service_account()
        configured_password = self._configured_password_for_email(account["email"])
        password = configured_password or self._default_password_for_email(account["email"])
        return AuthenticatedProviderContext(
            service_account_email=account["email"],
            confirmation_inbox_email=account["email"],
            real_mailbox_email=account["email"],
            service_password=password,
            username=account["label"],
            session_state={"site_url": self._site_url()},
        )

    def build_capture_summary(self) -> list[AliasProviderCapture]:
        return list(self._captures)

    def list_existing_aliases(self, context: AuthenticatedProviderContext) -> list[dict[str, str]]:
        self._ensure_authenticated(context)
        response = self._request("list_aliases", "GET", "/aliases/")
        aliases = self._extract_alias_emails_from_html(str(getattr(response, "text", "") or ""))
        return [{"email": email} for email in aliases]

    def create_alias(self, *, context: AuthenticatedProviderContext, domain, alias_index: int) -> AliasCreatedRecord:
        self._ensure_authenticated(context)
        existing_aliases = {item["email"] for item in self.list_existing_aliases(context)}
        create_page = self._request("open_create_alias", "GET", "/aliases/create/")
        hidden = self._extract_hidden_inputs(str(getattr(create_page, "text", "") or ""))
        note = self._build_alias_note(alias_index)
        payload = {
            **hidden,
            "email_destination": context.real_mailbox_email or context.service_account_email,
            "note": note,
        }
        self._request("create_alias", "POST", "/aliases/create/", data=payload)

        aliases_after = self.list_existing_aliases(context)
        new_aliases = [item["email"] for item in aliases_after if item["email"] not in existing_aliases]
        if not new_aliases:
            raise RuntimeError("emailshield alias creation succeeded but no new alias was found on /aliases/")

        created_email = new_aliases[0]
        return AliasCreatedRecord(
            email=created_email,
            metadata={
                "creation_endpoint": "/aliases/create/",
                "destination_email": context.real_mailbox_email or context.service_account_email,
                "note": note,
                "confirmed": True,
            },
        )

    def _site_url(self) -> str:
        configured = str(self._spec.provider_config.get("site_url") or "https://emailshield.app/").strip()
        if not configured:
            configured = "https://emailshield.app/"
        if not configured.endswith("/"):
            configured = f"{configured}/"
        return configured

    def _build_http_session(self, base_url: str):
        from curl_cffi.requests import Session

        return Session(
            headers={
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "origin": base_url.rstrip("/"),
                "referer": base_url,
            },
            impersonate="chrome",
            timeout=30,
            allow_redirects=True,
        )

    def _ensure_authenticated(self, context: AuthenticatedProviderContext):
        base_url = self._site_url()
        if self._session is None or self._session_base_url != base_url:
            self._session = self._build_http_session(base_url)
            self._session_base_url = base_url
            self._authenticated_account_email = ""

        if self._authenticated_account_email == context.service_account_email:
            return self._session

        login_page = self._request("open_login", "GET", "/accounts/login/")
        hidden = self._extract_hidden_inputs(str(getattr(login_page, "text", "") or ""))
        payload = {
            **hidden,
            "username": context.service_account_email,
            "password": context.service_password,
        }
        response = self._request("login", "POST", "/accounts/login/", data=payload)
        final_url = str(getattr(response, "url", "") or "")
        if "/accounts/dashboard/" not in final_url:
            response_text = str(getattr(response, "text", "") or "")
            if "Welcome back" in response_text or "Sign in to your account" in response_text:
                raise RuntimeError("emailshield login failed: account credentials rejected")
            raise RuntimeError("emailshield login failed: dashboard redirect not reached")

        self._authenticated_account_email = context.service_account_email
        context.session_state["site_url"] = base_url
        context.session_state["login_path"] = "/accounts/login/"
        context.session_state["authenticated_account_email"] = context.service_account_email
        return self._session

    def _request(self, capture_kind: str, method: str, path: str, **kwargs):
        session = self._session
        if session is None:
            raise RuntimeError("emailshield session unavailable")
        url = self._url(path)
        response = session.request(method, url, **kwargs)
        self._record_capture(capture_kind, method, url, kwargs, response)
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code >= 400:
            raise RuntimeError(self._response_error_message(status_code, str(getattr(response, "text", "") or "")))
        return response

    def _url(self, path: str) -> str:
        return urljoin(self._site_url(), path.lstrip("/"))

    def _extract_hidden_inputs(self, html: str) -> dict[str, str]:
        from .protocol_site_runtime import ProtocolSiteRuntime

        runtime = ProtocolSiteRuntime()
        return runtime.extract_hidden_inputs(html, names=("csrfmiddlewaretoken", "csrf_token"))

    def _extract_alias_emails_from_html(self, html: str) -> list[str]:
        matches = re.findall(r"([A-Za-z0-9._%+-]+@emailshield\.cc)", html or "", flags=re.IGNORECASE)
        seen: set[str] = set()
        aliases: list[str] = []
        for item in matches:
            email = str(item or "").strip().lower()
            if not email or email in seen:
                continue
            seen.add(email)
            aliases.append(email)
        return aliases

    def _default_password_for_email(self, email: str) -> str:
        local_part = str(email or "").split("@", 1)[0].strip()
        if not local_part:
            raise RuntimeError("emailshield provider requires a valid account email to derive default password")
        return f"1103@{local_part}"

    def _configured_password_for_email(self, email: str) -> str:
        accounts = list(self._spec.provider_config.get("accounts") or [])
        normalized_email = str(email or "").strip().lower()
        for item in accounts:
            if not isinstance(item, Mapping):
                continue
            account_email = str(item.get("email") or "").strip().lower()
            if account_email != normalized_email:
                continue
            return str(item.get("password") or "").strip()
        return ""

    def _build_alias_note(self, alias_index: int) -> str:
        task_fragment = re.sub(r"[^a-z0-9]+", "-", str(self._context.task_id or "emailshield").lower()).strip("-")
        task_fragment = task_fragment[:24] or "emailshield"
        return f"{task_fragment}-{alias_index}"

    def _response_error_message(self, status_code: int, response_text: str) -> str:
        message = " ".join(str(response_text or "").split())[:240]
        if message:
            return f"emailshield HTTP {status_code}: {message}"
        return f"emailshield HTTP {status_code}"

    def _sanitize_for_capture(self, value: Any):
        redacted = False
        if isinstance(value, Mapping):
            sanitized: dict[str, Any] = {}
            for key, item in value.items():
                normalized_key = str(key or "").lower()
                if normalized_key in {"password", "csrfmiddlewaretoken", "csrf_token"}:
                    sanitized[str(key)] = "<redacted>"
                    redacted = True
                    continue
                sanitized[str(key)] = item
            return sanitized, redacted
        return value, redacted

    def _capture_excerpt(self, value: Any) -> str:
        if value in (None, "", {}, []):
            return ""
        text = str(value)
        return text[:400]

    def _record_capture(self, kind: str, method: str, url: str, request_kwargs: Mapping[str, Any], response) -> None:
        request_payload = request_kwargs.get("json")
        if request_payload is None:
            request_payload = request_kwargs.get("data")
        sanitized_request, request_redacted = self._sanitize_for_capture(request_payload)
        sanitized_response, response_redacted = self._sanitize_for_capture(str(getattr(response, "text", "") or ""))
        self._captures.append(
            AliasProviderCapture(
                kind=kind,
                request_summary={
                    "url": url,
                    "method": method,
                    "request_headers_whitelist": {},
                    "request_body_excerpt": self._capture_excerpt(sanitized_request),
                },
                response_summary={
                    "response_status": int(getattr(response, "status_code", 0) or 0),
                    "response_body_excerpt": self._capture_excerpt(sanitized_response),
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                },
                redaction_applied=bool(request_redacted or response_redacted),
            )
        )


class EmailShieldAliasProvider(EmailShieldProvider):
    pass


def build_emailshield_provider(spec, context):
    return EmailShieldProvider(spec=spec, context=context)


def build_emailshield_alias_provider(spec, context):
    return build_emailshield_provider(spec, context)
