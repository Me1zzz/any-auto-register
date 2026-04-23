from __future__ import annotations

import json
import random
import re
import secrets
import string
import time
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlencode, urlsplit

from core.http_client import HTTPClient, RequestConfig

from .mailbox_verification_adapter import (
    build_mailbox_login_request,
    extract_anchored_link_from_message_content,
)
from .provider_contracts import AliasProviderCapture


DEFAULT_SECUREINSECONDS_REGISTER_URL = "https://alias.secureinseconds.com/auth/register"
DEFAULT_SECUREINSECONDS_LOGIN_URL = "https://alias.secureinseconds.com/auth/signin"
DEFAULT_SECUREINSECONDS_MAILBOX_BASE_URL = "https://cxwsss.online"
DEFAULT_SECUREINSECONDS_SERVICE_EMAIL_DOMAIN = "cxwsss.online"
DEFAULT_SECUREINSECONDS_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)
DEFAULT_SECUREINSECONDS_FORWARDING_VERIFY_ANCHOR = (
    "https://alias.secureinseconds.com/api/user/emails/verify?token="
)

_SECUREINSECONDS_ALLOWED_HOST = "alias.secureinseconds.com"

_SENSITIVE_QUERY_PATTERNS = [
    re.compile(r"((?:user\[)?password(?:\])?=)([^&\s]+)", re.IGNORECASE),
    re.compile(r"((?:token|authorization|csrftoken)=)([^&\s]+)", re.IGNORECASE),
    re.compile(r"(([A-Za-z0-9_\-]*token[A-Za-z0-9_\-]*=))([^&\s]+)", re.IGNORECASE),
    re.compile(r"(([A-Za-z0-9_\-]*code[A-Za-z0-9_\-]*=))([^&\s]+)", re.IGNORECASE),
]

_SENSITIVE_JSON_PATTERNS = [
    re.compile(r'("(?:[A-Za-z0-9_\-]*token[A-Za-z0-9_\-]*|authorization|csrftoken|password)"\s*:\s*")([^"]+)(")', re.IGNORECASE),
    re.compile(r'("(?:[A-Za-z0-9_\-]*code[A-Za-z0-9_\-]*)"\s*:\s*")([^"]+)(")', re.IGNORECASE),
]


def _utc_now_isoformat() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _truncate_text(value: Any, limit: int = 600) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _coerce_json_object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _coerce_json_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _safe_json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _redact_sensitive_text(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    redacted = text
    for pattern in _SENSITIVE_QUERY_PATTERNS:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    for pattern in _SENSITIVE_JSON_PATTERNS:
        redacted = pattern.sub(r"\1[REDACTED]\3", redacted)
    return redacted


def _parse_recipient_addresses(value: Any) -> set[str]:
    addresses: set[str] = set()

    def collect(item: Any) -> None:
        if item in (None, ""):
            return
        if isinstance(item, dict):
            for key in ("address", "email", "recipient", "toEmail"):
                normalized = _normalize_email(item.get(key))
                if normalized:
                    addresses.add(normalized)
            return
        if isinstance(item, (list, tuple, set)):
            for child in item:
                collect(child)
            return
        text = str(item).strip()
        if not text:
            return
        if text.startswith("[") or text.startswith("{"):
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed = None
            if parsed is not None:
                collect(parsed)
                return
        normalized = _normalize_email(text)
        if normalized:
            addresses.add(normalized)

    collect(value)
    return addresses


def _message_content(message: dict[str, Any]) -> str:
    return " ".join(
        [
            str(message.get("subject") or ""),
            str(message.get("text") or ""),
            str(message.get("content") or ""),
            str(message.get("html") or ""),
        ]
    )


def _message_matches_forwarding_email(message: dict[str, Any], forwarding_email: str) -> bool:
    normalized_forwarding_email = _normalize_email(forwarding_email)
    if not normalized_forwarding_email:
        return True
    if _normalize_email(message.get("toEmail")) == normalized_forwarding_email:
        return True
    for key in ("recipient", "recipients", "receipt", "recipt"):
        if normalized_forwarding_email in _parse_recipient_addresses(message.get(key)):
            return True
    return False


def build_secureinseconds_service_email(domain: str = DEFAULT_SECUREINSECONDS_SERVICE_EMAIL_DOMAIN) -> str:
    normalized_domain = str(domain or DEFAULT_SECUREINSECONDS_SERVICE_EMAIL_DOMAIN).strip().lower().lstrip("@")
    if not normalized_domain:
        normalized_domain = DEFAULT_SECUREINSECONDS_SERVICE_EMAIL_DOMAIN
    local_part = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    return f"{local_part}@{normalized_domain}"


def build_secureinseconds_service_password() -> str:
    entropy = secrets.token_urlsafe(9)
    compact = re.sub(r"[^A-Za-z0-9]", "", entropy)
    if len(compact) < 10:
        compact = compact + secrets.token_hex(6)
    return f"SisA1@{compact[:12]}"


def normalize_secureinseconds_forwarding_emails(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("forwardingEmails")
    if items is None:
        items = payload.get("emails")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _coerce_json_list(items):
        if not isinstance(item, dict):
            continue
        email = _normalize_email(item.get("email"))
        if not email or email in seen:
            continue
        seen.add(email)
        normalized.append(
            {
                "email": email,
                "verified": _parse_bool(item.get("verified")),
                "verifiedAt": str(item.get("verifiedAt") or item.get("verified_at") or ""),
                "isPrimary": _parse_bool(item.get("isPrimary") or item.get("is_primary")),
            }
        )
    return normalized


def normalize_secureinseconds_alias_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _coerce_json_list(payload.get("aliases")):
        if not isinstance(item, dict):
            continue
        alias_email = _normalize_email(item.get("alias") or item.get("email"))
        if not alias_email or alias_email in seen:
            continue
        seen.add(alias_email)
        forward_to_emails = [
            _normalize_email(email)
            for email in _coerce_json_list(item.get("forwardToEmails") or item.get("forward_to_emails"))
            if _normalize_email(email)
        ]
        normalized.append(
            {
                "alias": alias_email,
                "email": alias_email,
                "forwardToEmails": forward_to_emails,
                "description": str(item.get("description") or ""),
                "active": _parse_bool(item.get("active", True)),
                "deletedAt": str(item.get("deletedAt") or item.get("deleted_at") or ""),
                "aliasId": str(item.get("_id") or item.get("id") or ""),
            }
        )
    return normalized


def extract_secureinseconds_forwarding_verify_link(
    messages: Iterable[dict[str, Any]],
    *,
    forwarding_email: str,
    link_anchor: str = DEFAULT_SECUREINSECONDS_FORWARDING_VERIFY_ANCHOR,
) -> str:
    for message in messages:
        if not isinstance(message, dict):
            continue
        if not _message_matches_forwarding_email(message, forwarding_email):
            continue
        link = extract_anchored_link_from_message_content(
            _message_content(message),
            link_anchor=link_anchor,
        )
        if link:
            return link
    return ""


class SecureInSecondsRuntime:
    def __init__(
        self,
        *,
        register_url: str,
        login_url: str,
        mailbox_base_url: str = DEFAULT_SECUREINSECONDS_MAILBOX_BASE_URL,
        user_agent: str = DEFAULT_SECUREINSECONDS_USER_AGENT,
        http_client: HTTPClient | None = None,
        mailbox_http_client: HTTPClient | None = None,
    ):
        self._register_url = self._ensure_secureinseconds_url(
            register_url or DEFAULT_SECUREINSECONDS_REGISTER_URL,
            field_name="register_url",
        )
        self._login_url = self._ensure_secureinseconds_url(
            login_url or DEFAULT_SECUREINSECONDS_LOGIN_URL,
            field_name="login_url",
        )
        parsed_login_url = urlsplit(self._login_url)
        self._base_url = f"{parsed_login_url.scheme}://{parsed_login_url.netloc}"
        self._mailbox_base_url = self._ensure_generic_https_url(
            mailbox_base_url or DEFAULT_SECUREINSECONDS_MAILBOX_BASE_URL,
            field_name="mailbox_base_url",
        )
        self._user_agent = str(user_agent or DEFAULT_SECUREINSECONDS_USER_AGENT)
        self._client = http_client or HTTPClient(config=RequestConfig(max_retries=3, retry_delay=1.0))
        self._mailbox_client = mailbox_http_client or HTTPClient(config=RequestConfig(max_retries=3, retry_delay=1.0))
        self._captures: list[AliasProviderCapture] = []

    def capture_summary(self) -> list[AliasProviderCapture]:
        return list(self._captures)

    def export_session_state(self) -> dict[str, Any]:
        return {"cookies": self._serialize_cookies()}

    def restore_session(self, session_state: dict[str, Any], expected_email: str) -> bool:
        self._restore_cookies(_coerce_json_list(_coerce_json_object(session_state).get("cookies")))
        if not self._serialize_cookies():
            return False
        return _normalize_email(self.fetch_session_email()) == _normalize_email(expected_email)

    def fetch_session_email(self) -> str:
        _response, payload, _text = self._request(
            method="GET",
            url=f"{self._base_url}/api/auth/session",
            capture_kind="session",
            request_headers_whitelist={"content-type": "application/json"},
        )
        user = _coerce_json_object(_coerce_json_object(payload).get("user"))
        return _normalize_email(user.get("email"))

    def register_account(self, email: str, password: str) -> tuple[bool, str]:
        response, payload, text = self._request(
            method="POST",
            url=f"{self._base_url}/api/auth/register",
            json_body={
                "email": email,
                "password": password,
                "referralCode": None,
                "userAgent": self._user_agent,
            },
            capture_kind="register_account",
            request_headers_whitelist={"content-type": "application/json"},
            request_body_excerpt=_safe_json_dumps(
                {
                    "email": email,
                    "password": "[REDACTED]",
                    "referralCode": None,
                    "userAgent": self._user_agent,
                }
            ),
        )
        if int(getattr(response, "status_code", 0) or 0) in {200, 201}:
            return True, self._message_from_payload(payload, fallback="registered")
        return False, self._message_from_payload(payload, fallback=text or "secureinseconds registration failed")

    def login_account(self, email: str, password: str) -> bool:
        self._request(
            method="GET",
            url=f"{self._base_url}/api/auth/providers",
            capture_kind="auth_providers",
            request_headers_whitelist={"content-type": "application/json"},
        )
        _csrf_response, csrf_payload, _csrf_text = self._request(
            method="GET",
            url=f"{self._base_url}/api/auth/csrf",
            capture_kind="auth_csrf",
            request_headers_whitelist={"content-type": "application/json"},
        )
        csrf_token = str(_coerce_json_object(csrf_payload).get("csrfToken") or "").strip()
        if not csrf_token:
            raise RuntimeError("secureinseconds csrf token missing")
        login_payload = {
            "email": email,
            "password": password,
            "redirect": "false",
            "csrfToken": csrf_token,
            "callbackUrl": self._login_url,
            "json": "true",
        }
        self._request(
            method="POST",
            url=f"{self._base_url}/api/auth/callback/credentials",
            data_body=urlencode(login_payload),
            capture_kind="login_account",
            request_headers_whitelist={"content-type": "application/x-www-form-urlencoded"},
            request_body_excerpt=(
                f"email={email}&password=[REDACTED]&redirect=false&callbackUrl={self._login_url}&json=true"
            ),
            extra_headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        return _normalize_email(self.fetch_session_email()) == _normalize_email(email)

    def list_forwarding_emails(self) -> list[dict[str, Any]]:
        _response, payload, _text = self._request(
            method="GET",
            url=f"{self._base_url}/api/user/emails",
            capture_kind="list_forwarding_emails",
            request_headers_whitelist={"content-type": "application/json"},
        )
        return normalize_secureinseconds_forwarding_emails(_coerce_json_object(payload))

    def add_forwarding_email(self, email: str) -> tuple[bool, str]:
        response, payload, text = self._request(
            method="POST",
            url=f"{self._base_url}/api/user/emails",
            json_body={"email": email},
            capture_kind="add_forwarding_email",
            request_headers_whitelist={"content-type": "application/json"},
            request_body_excerpt=_safe_json_dumps({"email": email}),
        )
        if int(getattr(response, "status_code", 0) or 0) in {200, 201}:
            return True, self._message_from_payload(payload, fallback="Email added successfully.")
        return False, self._message_from_payload(payload, fallback=text or "Failed to add forwarding email.")

    def resend_forwarding_verification(self, email: str) -> tuple[bool, str]:
        response, payload, text = self._request(
            method="POST",
            url=f"{self._base_url}/api/user/emails/resend-verification",
            json_body={"email": email},
            capture_kind="resend_forwarding_verification",
            request_headers_whitelist={"content-type": "application/json"},
            request_body_excerpt=_safe_json_dumps({"email": email}),
        )
        if int(getattr(response, "status_code", 0) or 0) in {200, 201}:
            return True, self._message_from_payload(payload, fallback="Verification email sent.")
        return False, self._message_from_payload(payload, fallback=text or "Failed to resend verification email.")

    def fetch_forwarding_verify_link(
        self,
        *,
        mailbox_email: str,
        mailbox_password: str,
        match_email: str,
        timeout_seconds: int = 120,
        poll_interval_seconds: float = 3.0,
        link_anchor: str = DEFAULT_SECUREINSECONDS_FORWARDING_VERIFY_ANCHOR,
    ) -> str:
        token = self._mailbox_login_token(mailbox_email=mailbox_email, mailbox_password=mailbox_password)
        account_id = self._mailbox_account_id(token=token, mailbox_email=mailbox_email)
        deadline = time.monotonic() + max(int(timeout_seconds or 0), 1)
        while time.monotonic() < deadline:
            messages = self._mailbox_email_list(token=token, account_id=account_id)
            link = extract_secureinseconds_forwarding_verify_link(
                messages,
                forwarding_email=match_email,
                link_anchor=link_anchor,
            )
            if link:
                self._capture_mailbox_verification(status=200, detail="verification link found")
                return link
            time.sleep(max(float(poll_interval_seconds or 0), 0.5))
        self._capture_mailbox_verification(status=404, detail="verification link not found")
        return ""

    def verify_forwarding_email(self, verify_url: str) -> tuple[bool, str]:
        verified_url = self._ensure_secureinseconds_url(verify_url, field_name="verify_url")
        response, payload, text = self._request(
            method="GET",
            url=verified_url,
            capture_kind="verify_forwarding_email",
            request_headers_whitelist={"content-type": "application/json"},
        )
        if int(getattr(response, "status_code", 0) or 0) == 200:
            return True, self._message_from_payload(payload, fallback="Email verified successfully.")
        return False, self._message_from_payload(payload, fallback=text or "Failed to verify forwarding email.")

    def list_aliases(self) -> list[dict[str, Any]]:
        _response, payload, _text = self._request(
            method="GET",
            url=f"{self._base_url}/api/aliases",
            capture_kind="list_aliases",
            request_headers_whitelist={"content-type": "application/json"},
        )
        return normalize_secureinseconds_alias_items(_coerce_json_object(payload))

    def create_alias(
        self,
        *,
        prefix: str,
        description: str,
        forward_to_emails: list[str],
    ) -> dict[str, Any]:
        response, payload, text = self._request(
            method="POST",
            url=f"{self._base_url}/api/aliases",
            json_body={
                "prefix": prefix,
                "description": description,
                "forwardToEmails": list(forward_to_emails),
            },
            capture_kind="create_alias",
            request_headers_whitelist={"content-type": "application/json"},
            request_body_excerpt=_safe_json_dumps(
                {
                    "prefix": prefix,
                    "description": description,
                    "forwardToEmails": list(forward_to_emails),
                }
            ),
        )
        if int(getattr(response, "status_code", 0) or 0) not in {200, 201}:
            raise RuntimeError(self._message_from_payload(payload, fallback=text or "Failed to create alias."))
        alias_record = _coerce_json_object(_coerce_json_object(payload).get("alias"))
        alias_email = _normalize_email(alias_record.get("alias") or alias_record.get("email"))
        if not alias_email:
            raise RuntimeError("secureinseconds alias creation returned no alias email")
        alias_record["alias"] = alias_email
        return alias_record

    def _mailbox_login_token(self, *, mailbox_email: str, mailbox_password: str) -> str:
        request = build_mailbox_login_request(
            mailbox_base_url=self._mailbox_base_url,
            mailbox_email=mailbox_email,
            mailbox_password=mailbox_password,
        )
        response, payload, text = self._mailbox_request(
            method=str(request.get("method") or "POST"),
            url=str(request.get("url") or ""),
            json_body=_coerce_json_object(request.get("json")),
        )
        if int(getattr(response, "status_code", 0) or 0) != 200:
            raise RuntimeError(text or "secureinseconds mailbox login failed")
        payload_object = _coerce_json_object(payload)
        token = str(
            payload_object.get("token")
            or _coerce_json_object(payload_object.get("data")).get("token")
            or ""
        ).strip()
        if not token:
            raise RuntimeError("secureinseconds mailbox login token missing")
        return token

    def _mailbox_account_id(self, *, token: str, mailbox_email: str) -> int:
        response, payload, text = self._mailbox_request(
            method="GET",
            url=f"{self._mailbox_base_url}/api/account/list?accountId=0&size=30",
            extra_headers={"authorization": token},
        )
        if int(getattr(response, "status_code", 0) or 0) != 200:
            raise RuntimeError(text or "secureinseconds mailbox account list failed")
        payload_object = _coerce_json_object(payload)
        for item in _coerce_json_list(payload_object.get("data")):
            if not isinstance(item, dict):
                continue
            if _normalize_email(item.get("email")) != _normalize_email(mailbox_email):
                continue
            try:
                return int(item.get("accountId") or 0)
            except (TypeError, ValueError):
                continue
        raise RuntimeError("secureinseconds mailbox account id not found")

    def _mailbox_email_list(self, *, token: str, account_id: int) -> list[dict[str, Any]]:
        response, payload, text = self._mailbox_request(
            method="GET",
            url=(
                f"{self._mailbox_base_url}/api/email/list?"
                f"accountId={int(account_id)}&allReceive=1&emailId=0&timeSort=0&size=100&type=0"
            ),
            extra_headers={"authorization": token},
        )
        if int(getattr(response, "status_code", 0) or 0) != 200:
            raise RuntimeError(text or "secureinseconds mailbox email list failed")
        payload_object = _coerce_json_object(payload)
        data = _coerce_json_object(payload_object.get("data"))
        messages = [item for item in _coerce_json_list(data.get("list")) if isinstance(item, dict)]
        return messages

    def _mailbox_request(
        self,
        *,
        method: str,
        url: str,
        json_body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ):
        safe_url = self._ensure_generic_https_url(url, field_name="mailbox_request_url")
        headers = {"Content-Type": "application/json"}
        if extra_headers:
            headers.update({str(key): str(value) for key, value in extra_headers.items() if value not in (None, "")})
        response = self._mailbox_client.request(
            method.upper(),
            safe_url,
            headers=headers,
            json=json_body,
        )
        text = str(getattr(response, "text", "") or "")
        return response, self._parse_payload(response), text

    def _request(
        self,
        *,
        method: str,
        url: str,
        capture_kind: str,
        request_headers_whitelist: dict[str, Any],
        json_body: dict[str, Any] | None = None,
        data_body: str | None = None,
        request_body_excerpt: str = "",
        extra_headers: dict[str, str] | None = None,
    ):
        response = self._client.request(
            method.upper(),
            url,
            headers={**request_headers_whitelist, **(extra_headers or {})},
            json=json_body,
            data=data_body,
        )
        text = str(getattr(response, "text", "") or "")
        payload = self._parse_payload(response)
        request_body_text = request_body_excerpt or _truncate_text(_safe_json_dumps(json_body or data_body or ""))
        redacted_url = _redact_sensitive_text(url)
        redacted_request_body = _redact_sensitive_text(request_body_text)
        redacted_response_body = _redact_sensitive_text(_truncate_text(text))
        redaction_applied = (
            redacted_url != str(url)
            or redacted_request_body != request_body_text
            or redacted_response_body != _truncate_text(text)
        )
        self._captures.append(
            AliasProviderCapture(
                kind=capture_kind,
                request_summary={
                    "method": method.upper(),
                    "url": redacted_url,
                    "request_headers_whitelist": dict(request_headers_whitelist or {}),
                    "request_body_excerpt": redacted_request_body,
                },
                response_summary={
                    "response_status": int(getattr(response, "status_code", 0) or 0),
                    "response_body_excerpt": redacted_response_body,
                    "captured_at": _utc_now_isoformat(),
                },
                redaction_applied=redaction_applied,
            )
        )
        return response, payload, text

    def _parse_payload(self, response: Any) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception:
            payload = {}
        return _coerce_json_object(payload)

    def _message_from_payload(self, payload: dict[str, Any], *, fallback: str) -> str:
        return str(payload.get("message") or payload.get("error") or fallback).strip()

    def _serialize_cookies(self) -> list[dict[str, Any]]:
        cookies: list[dict[str, Any]] = []
        jar = getattr(self._client.session, "cookies", None)
        if jar is None:
            return cookies
        for cookie in jar:
            name = str(getattr(cookie, "name", "") or "").strip()
            if not name:
                continue
            cookies.append(
                {
                    "name": name,
                    "value": str(getattr(cookie, "value", "") or ""),
                    "domain": str(getattr(cookie, "domain", "") or ""),
                    "path": str(getattr(cookie, "path", "/") or "/"),
                    "secure": bool(getattr(cookie, "secure", False)),
                    "expires": getattr(cookie, "expires", None),
                }
            )
        return cookies

    def _restore_cookies(self, items: list[dict[str, Any]]) -> None:
        jar = getattr(self._client.session, "cookies", None)
        if jar is None:
            return
        try:
            jar.clear()
        except Exception:
            pass
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            kwargs: dict[str, Any] = {"path": str(item.get("path") or "/")}
            domain = str(item.get("domain") or "").strip()
            if domain:
                kwargs["domain"] = domain
            if item.get("expires") not in (None, ""):
                kwargs["expires"] = item.get("expires")
            if "secure" in item:
                kwargs["secure"] = bool(item.get("secure"))
            jar.set(name, str(item.get("value") or ""), **kwargs)

    def _capture_mailbox_verification(self, *, status: int, detail: str) -> None:
        self._captures.append(
            AliasProviderCapture(
                kind="mailbox_verification",
                request_summary={
                    "method": "POST",
                    "url": f"{self._mailbox_base_url}/api/login",
                    "request_headers_whitelist": {"content-type": "application/json"},
                    "request_body_excerpt": "mailbox verification request",
                },
                response_summary={
                    "response_status": int(status or 0),
                    "response_body_excerpt": detail,
                    "captured_at": _utc_now_isoformat(),
                },
                redaction_applied=True,
            )
        )

    def _ensure_secureinseconds_url(self, url: str, *, field_name: str) -> str:
        parsed = urlsplit(str(url or "").strip())
        if parsed.scheme != "https" or str(parsed.hostname or "").strip().lower() != _SECUREINSECONDS_ALLOWED_HOST:
            raise RuntimeError(f"secureinseconds field '{field_name}' must target https://{_SECUREINSECONDS_ALLOWED_HOST}")
        return parsed.geturl()

    def _ensure_generic_https_url(self, url: str, *, field_name: str) -> str:
        parsed = urlsplit(str(url or "").strip())
        if parsed.scheme != "https" or not str(parsed.hostname or "").strip():
            raise RuntimeError(f"secureinseconds field '{field_name}' must be a valid https URL")
        return parsed.geturl()
