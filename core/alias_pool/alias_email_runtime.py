from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import inspect
import json
import re
import secrets
import time
from typing import Any, Protocol, runtime_checkable, cast
from urllib.parse import urlsplit

import requests

from core.base_mailbox import CloudMailMailbox, MailboxAccount, create_mailbox
from core.http_client import HTTPClient

from .interactive_provider_models import AliasDomainOption
from .mailbox_verification_adapter import extract_anchored_link_from_message_content
from .provider_contracts import AliasProviderCapture


_CSRF_INPUT_RE = re.compile(
    r'name=["\']csrfmiddlewaretoken["\'][^>]*value=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_SIGNUP_UNKNOWN_ERROR_RE = re.compile(r"unknown error\. please try again later", re.IGNORECASE)
_MAGIC_LINK_RATE_LIMIT_RE = re.compile(r"too many login attempts", re.IGNORECASE)
_MAGIC_LINK_SENT_RE = re.compile(r"we['’]ve sent you a magic link", re.IGNORECASE)


@dataclass(frozen=True)
class AliasEmailRuntimeResult:
    session_state: dict[str, Any]
    payload: Any = None
    response_status: int = 0
    final_url: str = ""


@runtime_checkable
class AliasEmailRuntimeContract(Protocol):
    def generate_service_account_email(self) -> str: ...
    def bootstrap_public_session(self, *, service_account_email: str, session_state: dict[str, Any] | None = None) -> AliasEmailRuntimeResult: ...
    def submit_signup(self, *, service_account_email: str, session_state: dict[str, Any]) -> AliasEmailRuntimeResult: ...
    def request_magic_link(self, *, service_account_email: str, session_state: dict[str, Any]) -> AliasEmailRuntimeResult: ...
    def consume_magic_link(self, *, service_account_email: str, session_state: dict[str, Any]) -> AliasEmailRuntimeResult: ...
    def get_settings(self, *, session_state: dict[str, Any]) -> AliasEmailRuntimeResult: ...
    def list_domains(self, *, session_state: dict[str, Any]) -> AliasEmailRuntimeResult: ...
    def list_rules(self, *, session_state: dict[str, Any], page: int = 1, limit: int = 100, query: str = "", domain: str = "", email: str = "") -> AliasEmailRuntimeResult: ...
    def create_rule(self, *, session_state: dict[str, Any], name: str, domain: str, custom: bool = False) -> AliasEmailRuntimeResult: ...
    def discover_domains_from_payloads(self, *, settings_payload: Any, domains_payload: Any) -> list[AliasDomainOption]: ...
    def aliases_from_rules_payload(self, payload: Any) -> list[dict[str, Any]]: ...
    def alias_from_create_payload(self, payload: Any) -> dict[str, Any]: ...
    def account_exists_from_basic_info(self, payload: Any) -> bool: ...
    def build_capture_summary(self) -> list[AliasProviderCapture]: ...


class AliasEmailRuntime:
    def __init__(
        self,
        *,
        login_url: str,
        confirmation_inbox_config: dict[str, Any],
        http_client: HTTPClient | None = None,
        mailbox_factory=None,
        sleep_fn=None,
        monotonic_fn=None,
    ):
        self._login_url = str(login_url or "https://alias.email/users/login/").strip()
        self._confirmation_inbox_config = dict(confirmation_inbox_config or {})
        self._site_base_url = self._derive_site_base_url(self._login_url)
        self._http_client = http_client or HTTPClient()
        self._requests_session = requests.Session()
        self._allow_requests_fallback = http_client is None
        self._prefer_requests_session = http_client is None
        self._mailbox_factory = mailbox_factory or self._default_mailbox_factory
        self._sleep_fn = sleep_fn or time.sleep
        self._monotonic_fn = monotonic_fn or time.monotonic
        self._captures: list[AliasProviderCapture] = []
        self._rpc_request_id = 1

    @property
    def login_url(self) -> str:
        return self._login_url

    @property
    def captures(self) -> list[AliasProviderCapture]:
        return list(self._captures)

    def build_capture_summary(self) -> list[AliasProviderCapture]:
        return list(self._captures)

    def generate_service_account_email(self) -> str:
        mailbox = self._mailbox_factory(self._confirmation_inbox_config)
        account = mailbox.get_email()
        return str(account.account_id or account.email or "").strip().lower()

    def bootstrap_public_session(self, *, service_account_email: str, session_state: dict[str, Any] | None = None) -> AliasEmailRuntimeResult:
        state = self._apply_session_state(session_state)
        login_response = self._request_capture(
            kind="login_page",
            method="GET",
            url=self._login_url,
            headers=self._html_headers(),
        )
        state = self._merge_session_state(state, self._session_state_snapshot())
        csrf_token = self._extract_csrf_token(login_response.payload) or str(state.get("csrf_token") or "")
        if csrf_token:
            state["csrf_token"] = csrf_token
        basic_info = self._rpc_request(
            method_name="get_basic_account_info",
            params={"email": service_account_email},
            session_state=state,
            authenticated=False,
        )
        state = self._merge_session_state(state, basic_info.session_state)
        state["basic_account_info"] = basic_info.payload
        return AliasEmailRuntimeResult(
            session_state=state,
            payload=basic_info.payload,
            response_status=basic_info.response_status,
            final_url=basic_info.final_url,
        )

    def submit_signup(self, *, service_account_email: str, session_state: dict[str, Any]) -> AliasEmailRuntimeResult:
        result = self._form_post(
            kind="register_submit",
            path="/users/signup/",
            data={"email": service_account_email},
            session_state=session_state,
        )
        self._raise_on_signup_failure(payload=result.payload)
        return result

    def request_magic_link(self, *, service_account_email: str, session_state: dict[str, Any]) -> AliasEmailRuntimeResult:
        result = self._form_post(
            kind="request_magic_link",
            path="/users/send_magic_link/",
            data={"email": service_account_email},
            session_state=session_state,
        )
        self._raise_on_magic_link_failure(payload=result.payload)
        return result

    def consume_magic_link(self, *, service_account_email: str, session_state: dict[str, Any]) -> AliasEmailRuntimeResult:
        magic_link_url = self._poll_magic_link(service_account_email=service_account_email)
        state = self._apply_session_state(session_state)
        response = self._request_capture(
            kind="consume_magic_link",
            method="GET",
            url=magic_link_url,
            headers=self._html_headers(referer=self._login_url),
        )
        state = self._merge_session_state(state, self._session_state_snapshot())
        state["authenticated"] = True
        state["magic_link_url"] = magic_link_url
        return AliasEmailRuntimeResult(
            session_state=state,
            payload=response.payload,
            response_status=response.response_status,
            final_url=response.final_url,
        )

    def get_settings(self, *, session_state: dict[str, Any]) -> AliasEmailRuntimeResult:
        return self._rpc_request(
            method_name="get_settings",
            params={},
            session_state=session_state,
            authenticated=True,
        )

    def list_domains(self, *, session_state: dict[str, Any]) -> AliasEmailRuntimeResult:
        return self._rpc_request(
            method_name="list_domains",
            params={},
            session_state=session_state,
            authenticated=True,
        )

    def list_rules(
        self,
        *,
        session_state: dict[str, Any],
        page: int = 1,
        limit: int = 100,
        query: str = "",
        domain: str = "",
        email: str = "",
    ) -> AliasEmailRuntimeResult:
        params: dict[str, Any] = {"page": max(int(page or 1), 1), "limit": max(int(limit or 1), 1)}
        if query:
            params["query"] = query
        if domain:
            params["domain"] = domain
        if email:
            params["email"] = email
        return self._rpc_request(
            method_name="list_rules",
            params=params,
            session_state=session_state,
            authenticated=True,
        )

    def create_rule(
        self,
        *,
        session_state: dict[str, Any],
        name: str,
        domain: str,
        custom: bool = False,
    ) -> AliasEmailRuntimeResult:
        return self._rpc_request(
            method_name="create_rule",
            params={"name": name, "domain": domain, "custom": bool(custom)},
            session_state=session_state,
            authenticated=True,
        )

    def discover_domains_from_payloads(
        self,
        *,
        settings_payload: Any,
        domains_payload: Any,
    ) -> list[AliasDomainOption]:
        settings_result = self._extract_result(settings_payload)
        domains_result = self._extract_result(domains_payload)
        options: list[AliasDomainOption] = []
        seen: set[str] = set()
        default_domain = str(settings_result.get("domain") or "").strip().lower()
        domain_items = list(domains_result.get("domains") or [])
        for item in domain_items:
            if not isinstance(item, dict):
                continue
            domain = str(item.get("domain") or "").strip().lower()
            if not domain or domain in seen:
                continue
            seen.add(domain)
            is_default = bool(item.get("is_default")) or domain == default_domain
            label = f"@{domain}"
            if is_default:
                label = f"{label} (default)"
            options.append(
                AliasDomainOption(
                    key=domain,
                    domain=domain,
                    label=label,
                    raw=dict(item),
                )
            )
        if default_domain and default_domain not in seen:
            options.insert(
                0,
                AliasDomainOption(
                    key=default_domain,
                    domain=default_domain,
                    label=f"@{default_domain} (default)",
                    raw={"domain": default_domain, "is_default": True},
                ),
            )
        return options

    def aliases_from_rules_payload(self, payload: Any) -> list[dict[str, Any]]:
        result = self._extract_result(payload)
        aliases: list[dict[str, Any]] = []
        for item in list(result.get("rules") or []):
            if not isinstance(item, dict):
                continue
            email = str(item.get("email") or "").strip().lower()
            if not email:
                continue
            normalized = dict(item)
            normalized["email"] = email
            aliases.append(normalized)
        return aliases

    def alias_from_create_payload(self, payload: Any) -> dict[str, Any]:
        result = self._extract_result(payload)
        email = str(result.get("email") or "").strip().lower()
        if not email:
            raise RuntimeError("alias.email create_rule response missing email")
        normalized = dict(result)
        normalized["email"] = email
        return normalized

    def account_exists_from_basic_info(self, payload: Any) -> bool:
        result = self._extract_result(payload)
        for key in ("is_account_exist", "exists", "account_exists", "has_account", "found", "registered"):
            value = result.get(key)
            if isinstance(value, bool):
                return value
        for key in ("status", "state"):
            value = str(result.get(key) or "").strip().lower()
            if value in {"exists", "registered", "active"}:
                return True
            if value in {"missing", "not_found", "absent", "new"}:
                return False
        if result.get("user") or result.get("account"):
            return True
        return False

    def _derive_site_base_url(self, login_url: str) -> str:
        parsed = urlsplit(login_url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
        return "https://alias.email"

    def _default_mailbox_factory(self, config: dict[str, Any]) -> CloudMailMailbox:
        mailbox = create_mailbox("cloudmail", extra={
            "cloudmail_api_base": str(config.get("api_base") or config.get("base_url") or ""),
            "cloudmail_admin_email": str(config.get("admin_email") or ""),
            "cloudmail_admin_password": str(config.get("admin_password") or ""),
            "cloudmail_domain": config.get("domain") or "",
            "cloudmail_subdomain": str(config.get("subdomain") or ""),
            "cloudmail_timeout": int(config.get("timeout") or 30),
        })
        assert isinstance(mailbox, CloudMailMailbox)
        return mailbox

    def _cookie_jars(self) -> list[Any]:
        jars: list[Any] = []
        http_session = getattr(self._http_client, "session", None)
        http_cookie_jar = getattr(http_session, "cookies", None)
        if http_cookie_jar is not None:
            jars.append(http_cookie_jar)
        request_cookie_jar = getattr(self._requests_session, "cookies", None)
        if request_cookie_jar is not None and request_cookie_jar not in jars:
            jars.append(request_cookie_jar)
        return jars

    def _active_cookie_jar(self):
        if self._prefer_requests_session:
            return getattr(self._requests_session, "cookies", None)
        http_session = getattr(self._http_client, "session", None)
        return getattr(http_session, "cookies", None)

    def _apply_session_state(self, session_state: dict[str, Any] | None) -> dict[str, Any]:
        state = dict(session_state or {})
        cookie_jars = self._cookie_jars()
        for cookie_jar in cookie_jars:
            clear = getattr(cookie_jar, "clear", None)
            if callable(clear):
                clear()
        if not cookie_jars:
            return state
        for cookie in list(state.get("cookies") or []):
            if not isinstance(cookie, dict):
                continue
            name = str(cookie.get("name") or "").strip()
            if not name:
                continue
            for cookie_jar in cookie_jars:
                cookie_jar.set(
                    name,
                    str(cookie.get("value") or ""),
                    domain=str(cookie.get("domain") or "") or None,
                    path=str(cookie.get("path") or "/") or "/",
                )
        return state

    def _session_state_snapshot(self) -> dict[str, Any]:
        cookies = []
        cookie_jar = self._active_cookie_jar()
        if cookie_jar is not None:
            for cookie in cookie_jar:
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
        return {"cookies": cookies}

    def _merge_session_state(self, current: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
        merged = dict(current)
        merged.update(update)
        return merged

    def _next_rpc_request_id(self) -> int:
        current = self._rpc_request_id
        self._rpc_request_id += 1
        return current

    def _raise_on_rpc_error(self, *, method_name: str, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        error = payload.get("error")
        if not isinstance(error, dict):
            return
        message = str(error.get("message") or "alias.email rpc request failed").strip()
        code = error.get("code")
        if code not in (None, ""):
            raise RuntimeError(f"alias.email rpc {method_name} failed: [{code}] {message}")
        raise RuntimeError(f"alias.email rpc {method_name} failed: {message}")

    def _request_capture(self, *, kind: str, method: str, url: str, headers=None, json_body=None, data=None) -> AliasEmailRuntimeResult:
        request_kwargs: dict[str, Any] = {}
        if headers:
            request_kwargs["headers"] = dict(headers)
        if json_body is not None:
            request_kwargs["json"] = json_body
        if data is not None:
            request_kwargs["data"] = data
        request_kwargs.setdefault("timeout", 30)
        request_kwargs.setdefault("allow_redirects", True)
        if self._prefer_requests_session:
            response = self._requests_session.request(method, url, **request_kwargs)
        else:
            try:
                response = self._http_client.request(method, url, **request_kwargs)
            except Exception:
                if not self._allow_requests_fallback:
                    raise
                self._prefer_requests_session = True
                response = self._requests_session.request(method, url, **request_kwargs)
        payload = self._parse_payload(response)
        self._captures.append(
            AliasProviderCapture(
                kind=kind,
                request_summary={
                    "method": method.upper(),
                    "url": url,
                    "request_headers_whitelist": self._capture_request_headers(headers or {}),
                    "request_body_excerpt": self._body_excerpt(json_body if json_body is not None else data),
                },
                response_summary={
                    "response_status": int(getattr(response, "status_code", 0) or 0),
                    "response_body_excerpt": self._body_excerpt(payload),
                    "captured_at": self._utc_now_isoformat(),
                },
                redaction_applied=False,
            )
        )
        return AliasEmailRuntimeResult(
            session_state=self._session_state_snapshot(),
            payload=payload,
            response_status=int(getattr(response, "status_code", 0) or 0),
            final_url=str(getattr(response, "url", "") or ""),
        )

    def _rpc_request(
        self,
        *,
        method_name: str,
        params: dict[str, Any],
        session_state: dict[str, Any],
        authenticated: bool,
    ) -> AliasEmailRuntimeResult:
        state = self._apply_session_state(session_state)
        csrf_token = str(state.get("csrf_token") or "")
        headers = self._json_headers(csrf_token=csrf_token)
        if authenticated:
            headers["referer"] = f"{self._site_base_url}/dashboard/"
        else:
            headers["referer"] = self._login_url
        result = self._request_capture(
            kind=method_name,
            method="POST",
            url=f"{self._site_base_url}/api/rpc/",
            headers=headers,
            json_body={
                "jsonrpc": "2.0",
                "method": method_name,
                "params": params,
                "id": self._next_rpc_request_id(),
            },
        )
        self._raise_on_rpc_error(method_name=method_name, payload=result.payload)
        return AliasEmailRuntimeResult(
            session_state=self._merge_session_state(state, result.session_state),
            payload=result.payload,
            response_status=result.response_status,
            final_url=result.final_url,
        )

    def _form_post(self, *, kind: str, path: str, data: dict[str, Any], session_state: dict[str, Any]) -> AliasEmailRuntimeResult:
        state = self._apply_session_state(session_state)
        csrf_token = str(state.get("csrf_token") or "")
        form_data = dict(data)
        if csrf_token:
            form_data.setdefault("csrfmiddlewaretoken", csrf_token)
        form_data.setdefault("next", "/users/dashboard/")
        form_data.setdefault("alias_name", "")
        response = self._request_capture(
            kind=kind,
            method="POST",
            url=f"{self._site_base_url}{path}",
            headers=self._form_headers(csrf_token=csrf_token),
            data=form_data,
        )
        state = self._merge_session_state(state, response.session_state)
        return AliasEmailRuntimeResult(
            session_state=state,
            payload=response.payload,
            response_status=response.response_status,
            final_url=response.final_url,
        )

    def _poll_magic_link(self, *, service_account_email: str) -> str:
        mailbox = self._mailbox_factory(self._confirmation_inbox_config)
        timeout_seconds = max(int(self._confirmation_inbox_config.get("timeout") or 30), 5)
        deadline = self._monotonic_fn() + timeout_seconds
        target_email = str(service_account_email or "").strip().lower()
        while self._monotonic_fn() < deadline:
            mails = mailbox._list_mails("")
            for message in mails:
                if not mailbox._match_alias_receipt(message, target_email):
                    continue
                content = " ".join(
                    [
                        str(message.get("subject") or ""),
                        str(message.get("content") or ""),
                        str(message.get("text") or ""),
                        str(message.get("html") or ""),
                    ]
                )
                magic_link_url = extract_anchored_link_from_message_content(
                    content,
                    link_anchor=f"{self._site_base_url}/users/magic-link/verify/",
                )
                if magic_link_url:
                    return magic_link_url
            self._sleep_fn(3)
        raise RuntimeError("alias.email magic link mail not found in CloudMail admin mailbox list")

    def _extract_result(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict):
            result = payload.get("result")
            if isinstance(result, dict):
                return result
            return payload
        return {}

    def _extract_csrf_token(self, payload: Any) -> str:
        if isinstance(payload, dict):
            for key in ("csrf_token", "csrfToken", "csrftoken"):
                value = str(payload.get(key) or "").strip()
                if value:
                    return value
            html = str(payload.get("html") or "")
        else:
            html = str(payload or "")
        match = _CSRF_INPUT_RE.search(html)
        if match:
            return str(match.group(1) or "").strip()
        return ""

    def _payload_html(self, payload: Any) -> str:
        if isinstance(payload, dict):
            return str(payload.get("html") or "")
        return str(payload or "")

    def _raise_on_signup_failure(self, *, payload: Any) -> None:
        html = self._payload_html(payload)
        if html and _SIGNUP_UNKNOWN_ERROR_RE.search(html):
            raise RuntimeError("alias.email signup failed: Unknown error. Please try again later")

    def _raise_on_magic_link_failure(self, *, payload: Any) -> None:
        html = self._payload_html(payload)
        if not html:
            return
        if _MAGIC_LINK_RATE_LIMIT_RE.search(html):
            raise RuntimeError("alias.email magic link failed: Too many login attempts from your address")
        if _MAGIC_LINK_SENT_RE.search(html):
            return

    def _parse_payload(self, response) -> Any:
        try:
            return response.json()
        except Exception:
            return {
                "html": str(getattr(response, "text", "") or ""),
                "content_type": str(getattr(getattr(response, "headers", {}), "get", lambda *_: "")("content-type", "") or ""),
            }

    def _capture_request_headers(self, headers: dict[str, Any]) -> dict[str, Any]:
        allowed = {}
        for key in ("content-type", "referer", "x-csrftoken", "x-requested-with"):
            value = headers.get(key)
            if value in (None, ""):
                continue
            allowed[key] = value
        return allowed

    def _body_excerpt(self, value: Any) -> str:
        if value in (None, ""):
            return ""
        if isinstance(value, str):
            return value[:4000]
        try:
            return json.dumps(value, ensure_ascii=False)[:4000]
        except Exception:
            return str(value)[:4000]

    def _html_headers(self, *, referer: str = "") -> dict[str, str]:
        headers = {"accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
        if referer:
            headers["referer"] = referer
        return headers

    def _json_headers(self, *, csrf_token: str = "") -> dict[str, str]:
        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "x-requested-with": "XMLHttpRequest",
        }
        if csrf_token:
            headers["x-csrftoken"] = csrf_token
        return headers

    def _form_headers(self, *, csrf_token: str = "") -> dict[str, str]:
        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "content-type": "application/x-www-form-urlencoded",
            "referer": self._login_url,
        }
        if csrf_token:
            headers["x-csrftoken"] = csrf_token
        return headers

    def _utc_now_isoformat(self) -> str:
        return datetime.now(timezone.utc).isoformat()


def build_alias_email_runtime(*, spec=None, context=None, login_url: str = "", confirmation_inbox_config=None):
    resolved_login_url = str(login_url or getattr(spec, "provider_config", {}).get("login_url") or "https://alias.email/users/login/")
    resolved_inbox = dict(confirmation_inbox_config or getattr(spec, "confirmation_inbox_config", {}) or {})
    return AliasEmailRuntime(
        login_url=resolved_login_url,
        confirmation_inbox_config=resolved_inbox,
    )


def resolve_alias_email_runtime_builder(builder, *, spec, context):
    if not callable(builder):
        return build_alias_email_runtime(spec=spec, context=context)
    attempts = [
        lambda: builder(spec=spec, context=context),
        lambda: builder(spec, context),
        lambda: builder(spec=spec),
        lambda: builder(spec),
    ]
    for attempt in attempts:
        try:
            candidate = attempt()
        except TypeError:
            continue
        if candidate is not None:
            return cast(AliasEmailRuntimeContract, candidate)
    return cast(AliasEmailRuntimeContract, build_alias_email_runtime(spec=spec, context=context))
