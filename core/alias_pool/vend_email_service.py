from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
import inspect
import ipaddress
import re
import secrets
import socket
import time
from urllib.parse import urlencode, quote_plus
from urllib.parse import unquote, urlsplit
from typing import Any, Callable, Protocol, cast

from core.http_client import HTTPClient
from core.base_mailbox import CloudMailMailbox, MailboxAccount

from .base import AliasSourceState
from .mailbox_verification_adapter import extract_anchored_link_from_message_content
from .provider_contracts import AliasProviderSourceSpec
from .vend_confirmation import VendConfirmationReader
from .vend_email_state import VendEmailServiceState
from .vend_email_state import VendEmailFileStateStore
from .vend_email_state import VendEmailCaptureRecord
from .vend_provider import VendAliasProvider
from .vend_state_repository import VendStateRepository
from .vend_telemetry import VendTelemetryRecorder


class VendEmailTaskStateStore:
    def __init__(self, path: Path | str):
        self._store = VendEmailFileStateStore(path)

    def load(self, state_key: str) -> VendEmailServiceState:
        try:
            state = self._store.load()
        except FileNotFoundError:
            state = VendEmailServiceState(
                state_key=state_key,
            )
        if not state.state_key:
            state.state_key = state_key
        return state

    def save(self, state: VendEmailServiceState) -> None:
        self._store.save(state)


def build_vend_email_task_state_store(*, task_id: str, source_id: str):
    return VendEmailTaskStateStore(
        VendEmailFileStateStore.for_task(task_id=task_id, source_id=source_id)._path
    )


def build_vend_email_state_store_for_key(*, state_key: str):
    return VendEmailTaskStateStore(
        VendEmailFileStateStore.for_state_key(state_key=state_key)._path
    )


def _utc_now_isoformat() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_safe_outbound_url(*, url: str, field_name: str) -> str:
    raw_url = str(url or "").strip()
    parsed = urlsplit(raw_url)
    if parsed.scheme not in {"http", "https"}:
        raise RuntimeError(f"vend.email source field '{field_name}' must use http or https")
    host = str(parsed.hostname or "").strip()
    if not host:
        raise RuntimeError(f"vend.email source field '{field_name}' must include a hostname")
    if host.lower() == "localhost":
        raise RuntimeError(f"vend.email source field '{field_name}' must not target localhost")

    try:
        host_ip = ipaddress.ip_address(host)
    except ValueError:
        host_ip = None

    if host_ip is not None and not host_ip.is_global:
        raise RuntimeError(
            f"vend.email source field '{field_name}' must not target private or local addresses"
        )

    try:
        address_infos = socket.getaddrinfo(
            host,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror:
        return raw_url

    for address_info in address_infos:
        resolved_host = str(address_info[4][0] or "").strip()
        if not resolved_host:
            continue
        try:
            resolved_ip = ipaddress.ip_address(resolved_host)
        except ValueError:
            continue
        if not resolved_ip.is_global:
            raise RuntimeError(
                f"vend.email source field '{field_name}' must not target private or local addresses"
            )

    return raw_url


class DefaultVendEmailRuntimeExecutor:
    def __init__(self, *, source: dict):
        self._source = dict(source)
        self._client = HTTPClient()
        _ensure_safe_outbound_url(
            url=self._require_string(source, "register_url"),
            field_name="register_url",
        )

    def execute(
        self,
        operation: VendEmailRuntimeOperation,
        state,
        source: dict,
    ) -> VendEmailRuntimeExecution:
        response_status = 0
        response_body_excerpt = ""
        payload = None
        ok = False
        response = None
        try:
            request_kwargs = self._build_request_kwargs(operation)
            response = self._client.request(operation.method, operation.url, **request_kwargs)
            response_status = int(getattr(response, "status_code", 0) or 0)
            raw_body = str(getattr(response, "text", "") or "")
            response_body_excerpt = raw_body[:4000]
            payload = self._parse_payload(response)
            ok = 200 <= response_status < 300
        except Exception as exc:
            response_body_excerpt = str(exc)
            ok = False

        state.session_cookies = self._extract_session_cookies()
        return VendEmailRuntimeExecution(
            ok=ok,
            response_status=response_status,
            response_body_excerpt=response_body_excerpt,
            captured_at=_utc_now_isoformat(),
            payload=payload,
            final_url=str(getattr(response, "url", "") or "") if response is not None else "",
            content_type=str(getattr(getattr(response, "headers", {}), "get", lambda *_: "")("content-type", "") or "") if response is not None else "",
        )

    def fetch_confirmation_link(self, state, source: dict) -> str:
        cloudmail_mailbox = self._build_cloudmail_mailbox(source)
        target_email = self._service_mailbox_email(state)
        confirmation_anchor = self._resolve_confirmation_anchor(source)
        deadline = time.monotonic() + 120

        while time.monotonic() < deadline:
            mails = cloudmail_mailbox._list_mails("")
            for idx, msg in enumerate(mails):
                if not cloudmail_mailbox._match_alias_receipt(msg, target_email):
                    continue
                content = " ".join(
                    [
                        str(msg.get("subject") or ""),
                        str(msg.get("content") or ""),
                        str(msg.get("text") or ""),
                        str(msg.get("html") or ""),
                    ]
                )
                confirmation_link = extract_anchored_link_from_message_content(
                    content,
                    link_anchor=confirmation_anchor,
                )
                if confirmation_link:
                    return confirmation_link
            time.sleep(3)

        raise RuntimeError("vend.email confirmation mail not found in CloudMail admin mailbox list")

    def _require_string(self, source: dict, key: str) -> str:
        value = str(source.get(key) or "").strip()
        if not value:
            raise RuntimeError(f"vend.email source missing required field: {key}")
        return value

    def _mailbox_email(self, source: dict, state) -> str:
        mailbox_email = self._service_mailbox_email(state)
        if not mailbox_email:
            raise RuntimeError("vend.email source missing required field: mailbox_email")
        return mailbox_email

    def _service_mailbox_email(self, state) -> str:
        return str(getattr(state, "mailbox_email", "") or "").strip().lower()

    def _confirmation_inbox_config(self, source: dict) -> dict[str, Any]:
        confirmation_inbox = source.get("confirmation_inbox")
        resolved = dict(confirmation_inbox) if isinstance(confirmation_inbox, dict) else {}

        def _set_if_missing(key: str, value: Any) -> None:
            if key in resolved and resolved.get(key) not in (None, ""):
                return
            if value in (None, ""):
                return
            resolved[key] = value

        _set_if_missing("provider", "cloudmail")
        _set_if_missing("api_base", source.get("cloudmail_api_base") or source.get("mailbox_base_url") or "")
        _set_if_missing("base_url", source.get("mailbox_base_url") or source.get("cloudmail_api_base") or "")
        _set_if_missing("admin_email", source.get("cloudmail_admin_email") or "")
        _set_if_missing("admin_password", source.get("cloudmail_admin_password") or "")
        _set_if_missing("domain", source.get("cloudmail_domain") or "")
        _set_if_missing("subdomain", source.get("cloudmail_subdomain") or "")
        if resolved.get("timeout") in (None, ""):
            resolved["timeout"] = int(source.get("cloudmail_timeout") or 30)
        _set_if_missing("account_email", source.get("mailbox_email") or "")
        _set_if_missing("account_password", source.get("mailbox_password") or "")
        _set_if_missing("match_email", resolved.get("account_email") or source.get("mailbox_email") or "")
        return resolved

    def _build_cloudmail_mailbox(self, source: dict) -> CloudMailMailbox:
        confirmation_inbox = self._confirmation_inbox_config(source)
        return CloudMailMailbox(
            api_base=self._require_string(confirmation_inbox, "api_base"),
            admin_email=str(confirmation_inbox.get("admin_email") or "").strip(),
            admin_password=self._require_string(confirmation_inbox, "admin_password"),
            domain=confirmation_inbox.get("domain") or "",
            subdomain=str(confirmation_inbox.get("subdomain") or "").strip(),
            timeout=int(confirmation_inbox.get("timeout") or 30),
        )

    def _resolve_confirmation_anchor(self, source: dict) -> str:
        configured_anchor = str(
            source.get("confirmation_anchor")
            or source.get("confirmation_anchor_prefix")
            or ""
        ).strip()
        if configured_anchor:
            return configured_anchor
        return f"{self._vend_base_url(source)}/auth/confirmation"

    def _build_request_kwargs(self, operation: VendEmailRuntimeOperation) -> dict[str, Any]:
        request_kwargs: dict[str, Any] = {}
        if operation.request_headers_whitelist:
            request_kwargs["headers"] = dict(operation.request_headers_whitelist)
        if operation.method.upper() != "GET" and operation.request_body_excerpt:
            request_kwargs["data"] = operation.request_body_excerpt
        return request_kwargs

    def _extract_session_cookies(self) -> list[dict[str, Any]]:
        cookies = getattr(self._client.session, "cookies", None)
        if cookies is None:
            return []
        result: list[dict[str, Any]] = []
        for cookie in cookies:
            name = str(getattr(cookie, "name", "") or "").strip()
            if not name:
                continue
            result.append(
                {
                    "name": name,
                    "value": str(getattr(cookie, "value", "") or ""),
                    "domain": str(getattr(cookie, "domain", "") or ""),
                    "path": str(getattr(cookie, "path", "/") or "/"),
                    "secure": bool(getattr(cookie, "secure", False)),
                    "expires": getattr(cookie, "expires", None),
                }
            )
        return result

    def _parse_payload(self, response: Any):
        text = str(getattr(response, "text", "") or "").strip()
        if not text:
            return None
        try:
            return response.json()
        except Exception:
            return {
                "html": text,
                "final_url": str(getattr(response, "url", "") or ""),
                "content_type": str(
                    getattr(getattr(response, "headers", {}), "get", lambda *_: "")(
                        "content-type",
                        "",
                    )
                    or ""
                ),
            }

    def _vend_base_url(self, source: dict) -> str:
        register_url = _ensure_safe_outbound_url(
            url=self._require_string(source, "register_url"),
            field_name="register_url",
        ).rstrip("/")
        for suffix in ("/auth/register", "/register"):
            if register_url.endswith(suffix):
                return register_url[: -len(suffix)]
        return register_url


def build_default_vend_email_runtime(source: dict):
    return VendEmailContractRuntime(
        executor=DefaultVendEmailRuntimeExecutor(source=source)
    )


def build_vend_email_alias_service_producer(
    *,
    source: dict,
    task_id: str,
    state_store_factory=None,
    runtime_builder=None,
) -> object:
    resolved_state_store_factory = cast(Any, state_store_factory)
    resolved_runtime_builder = cast(Any, runtime_builder)
    normalized_source = dict(source)
    source_id = str(normalized_source.get("id") or "vend-email")
    state_key = str(normalized_source.get("state_key") or source_id).strip() or source_id
    confirmation_inbox = normalized_source.get("confirmation_inbox")
    if not isinstance(confirmation_inbox, dict):
        confirmation_inbox = {}

    if not confirmation_inbox:
        fallback_account_email = str(normalized_source.get("mailbox_email") or "").strip()
        fallback_account_password = str(normalized_source.get("mailbox_password") or "").strip()
        fallback_base_url = str(normalized_source.get("mailbox_base_url") or "").strip()
        fallback_provider = "cloudmail" if any(
            [
                str(normalized_source.get("cloudmail_api_base") or "").strip(),
                str(normalized_source.get("cloudmail_admin_email") or "").strip(),
                str(normalized_source.get("cloudmail_admin_password") or "").strip(),
                str(normalized_source.get("cloudmail_domain") or "").strip(),
                str(normalized_source.get("cloudmail_subdomain") or "").strip(),
                fallback_account_email,
                fallback_account_password,
                fallback_base_url,
            ]
        ) else ""
        if fallback_provider:
            confirmation_inbox = {
                "provider": fallback_provider,
                "api_base": str(normalized_source.get("cloudmail_api_base") or "").strip(),
                "admin_email": str(normalized_source.get("cloudmail_admin_email") or "").strip(),
                "admin_password": str(normalized_source.get("cloudmail_admin_password") or "").strip(),
                "domain": normalized_source.get("cloudmail_domain") or "",
                "subdomain": str(normalized_source.get("cloudmail_subdomain") or "").strip(),
                "timeout": int(normalized_source.get("cloudmail_timeout") or 30),
                "account_email": fallback_account_email,
                "account_password": fallback_account_password,
                "match_email": fallback_account_email,
                "base_url": fallback_base_url,
            }
    else:
        confirmation_inbox = dict(confirmation_inbox)

    if confirmation_inbox:
        normalized_source["confirmation_inbox"] = confirmation_inbox
        if confirmation_inbox.get("base_url") and not normalized_source.get("mailbox_base_url"):
            normalized_source["mailbox_base_url"] = confirmation_inbox.get("base_url")
        if confirmation_inbox.get("account_email") and not normalized_source.get("mailbox_email"):
            normalized_source["mailbox_email"] = confirmation_inbox.get("account_email")
        if confirmation_inbox.get("account_password") and not normalized_source.get("mailbox_password"):
            normalized_source["mailbox_password"] = confirmation_inbox.get("account_password")

    if state_store_factory is None:
        state_store = build_vend_email_state_store_for_key(state_key=state_key)
    else:
        if not callable(resolved_state_store_factory):
            resolved_state_store_factory = build_vend_email_task_state_store
        state_store_factory_signature = inspect.signature(resolved_state_store_factory)
        supports_source_id = False
        accepts_keyword_task_id = False
        accepts_keyword_source_id = False
        positional_parameter_count = 0
        for parameter in state_store_factory_signature.parameters.values():
            if parameter.kind == inspect.Parameter.VAR_POSITIONAL:
                supports_source_id = True
                break
            if parameter.kind == inspect.Parameter.VAR_KEYWORD:
                accepts_keyword_task_id = True
                accepts_keyword_source_id = True
                continue
            if parameter.kind == inspect.Parameter.KEYWORD_ONLY:
                if parameter.name == "task_id":
                    accepts_keyword_task_id = True
                if parameter.name == "source_id":
                    accepts_keyword_source_id = True
                continue
            if parameter.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ):
                positional_parameter_count += 1
                if parameter.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
                    if parameter.name == "task_id":
                        accepts_keyword_task_id = True
                    if parameter.name == "source_id":
                        accepts_keyword_source_id = True

        try:
            if accepts_keyword_task_id and accepts_keyword_source_id:
                state_store = resolved_state_store_factory(task_id=task_id, source_id=source_id)
            else:
                two_arg_state_store_factory = cast(Callable[..., Any], resolved_state_store_factory)
                state_store = two_arg_state_store_factory(task_id, source_id)
        except TypeError:
            if supports_source_id or positional_parameter_count >= 2:
                raise
            one_arg_state_store_factory = cast(Callable[..., Any], resolved_state_store_factory)
            if accepts_keyword_task_id:
                state_store = one_arg_state_store_factory(task_id=task_id)
            else:
                state_store = one_arg_state_store_factory(task_id)

    if not callable(resolved_runtime_builder):
        resolved_runtime_builder = build_default_vend_email_runtime

    spec = AliasProviderSourceSpec(
        source_id=source_id,
        provider_type="vend_email",
        raw_source=normalized_source,
        desired_alias_count=max(int(normalized_source.get("alias_count") or 0), 0),
        state_key=state_key,
        register_url=str(normalized_source.get("register_url") or ""),
        alias_domain=str(normalized_source.get("alias_domain") or ""),
        alias_domain_id=str(normalized_source.get("alias_domain_id") or ""),
        confirmation_inbox_config=confirmation_inbox,
    )
    runtime = resolved_runtime_builder(normalized_source)
    return VendAliasProvider(
        spec=spec,
        state_repository=VendStateRepository(store=state_store, state_key=state_key),
        runtime=runtime,
        confirmation_reader=VendConfirmationReader(runtime=runtime),
        telemetry=VendTelemetryRecorder(),
    )


class VendEmailRuntime(Protocol):
    def restore_session(self, state) -> bool: ...

    def login(self, state, source: dict) -> bool: ...

    def register(self, state, source: dict) -> bool: ...

    def resend_confirmation(self, state, source: dict) -> bool: ...

    def list_forwarders(self, state, source: dict) -> list["VendEmailForwarderRecord"]: ...

    def create_forwarder(
        self,
        state,
        source: dict,
        *,
        local_part: str,
        domain_id: str,
        recipient: str,
    ) -> "VendEmailForwarderRecord | None": ...

    def list_aliases(self, state, source: dict) -> list[str]: ...

    def create_aliases(self, state, source: dict, missing_count: int) -> list[str]: ...

    def capture_summary(self) -> list[VendEmailCaptureRecord]: ...


class VendEmailRuntimeProtocolError(RuntimeError):
    pass


@dataclass(frozen=True)
class VendEmailForwarderRecord:
    alias_email: str
    recipient_email: str


@dataclass(frozen=True)
class VendEmailRuntimeOperation:
    name: str
    method: str
    url: str
    request_headers_whitelist: dict[str, str] = field(default_factory=dict)
    request_body_excerpt: str = ""


@dataclass(frozen=True)
class VendEmailRuntimeExecution:
    ok: bool
    response_status: int
    response_body_excerpt: str
    captured_at: str
    payload: object = None
    final_url: str = ""
    content_type: str = ""


class VendEmailRuntimeExecutor(Protocol):
    def execute(
        self,
        operation: VendEmailRuntimeOperation,
        state,
        source: dict,
    ) -> VendEmailRuntimeExecution: ...


class VendEmailContractRuntime:
    def __init__(self, *, executor: VendEmailRuntimeExecutor):
        self._executor = executor
        self._captures: list[VendEmailCaptureRecord] = []
        self._active_state = None

    def restore_session(self, state) -> bool:
        self._active_state = state
        return bool(getattr(state, "session_cookies", None) or getattr(state, "session_storage", None))

    def fetch_confirmation_link(self, state, source: dict) -> str:
        self._active_state = state
        fetch_confirmation_link = getattr(self._executor, "fetch_confirmation_link", None)
        if not callable(fetch_confirmation_link):
            raise VendEmailRuntimeProtocolError(
                "vend.email runtime executor must define fetch_confirmation_link()"
            )
        typed_fetch_confirmation_link = cast(Callable[[Any, dict], str], fetch_confirmation_link)
        confirmation_link = str(typed_fetch_confirmation_link(state, source) or "").strip()
        self._captures.append(
            VendEmailCaptureRecord(
                name="mailbox_verification",
                url=str(source.get("mailbox_base_url") or "").strip(),
                method="GET",
                request_headers_whitelist={},
                request_body_excerpt="",
                response_status=200 if confirmation_link else 0,
                response_body_excerpt="confirmation link captured",
                captured_at=_utc_now_isoformat(),
            )
        )
        return confirmation_link

    def confirm(self, confirmation_link: str, source: dict) -> bool:
        if not confirmation_link:
            return False
        state = self._active_state
        if state is None:
            raise VendEmailRuntimeProtocolError(
                "vend.email runtime confirmation requires an active state"
            )
        execution = self._execute_following_safe_redirects(
            state,
            source,
            operation_name="confirmation",
            url=confirmation_link,
        )
        html = self._execution_html(execution)
        final_url = execution.final_url or confirmation_link
        if self._is_login_page(html, final_url):
            return True
        if "already confirmed" in html.lower():
            return True
        return execution.ok and not self._is_confirmation_issue_page(html)

    def register(self, state, source: dict) -> bool:
        self._active_state = state
        service_email = self._service_email(state)
        local_part = service_email.split("@", 1)[0]
        register_page = self._fetch_form_page(state, source, name="register_form", path="/auth/register")
        execution = self._execute(
            state,
            source,
            VendEmailRuntimeOperation(
                name="register",
                method="POST",
                url=self._build_url(source, "/auth"),
                request_headers_whitelist=self._form_headers(
                    referer=self._build_url(source, "/auth/register"),
                    csrf_token=self._meta_csrf_token(register_page),
                ),
                request_body_excerpt=self._form_encode(
                    self._merge_form_fields(
                        register_page,
                        form_action="/auth",
                        extra_fields=[
                            ("user[name]", local_part),
                            ("user[email]", service_email),
                            ("user[password]", self._service_password(state)),
                            ("commit", "Sign up"),
                        ],
                    )
                ),
            ),
        )
        html = self._execution_html(execution)
        final_url = execution.final_url or self._build_url(source, "/auth")
        return execution.ok and not self._is_register_page(html, final_url)

    def resend_confirmation(self, state, source: dict) -> bool:
        self._active_state = state
        execution = self._execute(
            state,
            source,
            VendEmailRuntimeOperation(
                name="confirmation",
                method="POST",
                url=self._build_url(source, "/auth/confirmation"),
                request_headers_whitelist=self._form_headers(),
                request_body_excerpt=self._form_encode(
                    [("user[email]", self._service_email(state))]
                ),
            ),
        )
        return execution.ok

    def login(self, state, source: dict) -> bool:
        self._active_state = state
        login_page = self._fetch_form_page(state, source, name="login_form", path="/auth/login")
        execution = self._execute(
            state,
            source,
            VendEmailRuntimeOperation(
                name="login",
                method="POST",
                url=self._build_url(source, "/auth/login"),
                request_headers_whitelist=self._form_headers(
                    referer=self._build_url(source, "/auth/login"),
                    csrf_token=self._meta_csrf_token(login_page),
                ),
                request_body_excerpt=self._form_encode(
                    self._merge_form_fields(
                        login_page,
                        form_action="/auth/login",
                        extra_fields=[
                            ("user[email]", self._service_email(state)),
                            ("user[password]", self._service_password(state)),
                            ("commit", "Log in"),
                        ],
                    )
                ),
            ),
        )
        html = self._execution_html(execution)
        final_url = execution.final_url or self._build_url(source, "/auth/login")
        return execution.ok and not self._is_login_page(html, final_url)

    def list_forwarders(self, state, source: dict) -> list[VendEmailForwarderRecord]:
        self._active_state = state
        execution = self._execute(
            state,
            source,
            VendEmailRuntimeOperation(
                name="list_forwarders",
                method="GET",
                url=self._build_url(source, "/forwarders"),
            ),
        )
        payload = execution.payload
        if isinstance(payload, list):
            records: list[VendEmailForwarderRecord] = []
            for item in payload:
                if not isinstance(item, dict):
                    continue
                record = self._forwarder_from_payload(item)
                if record is not None:
                    records.append(record)
            return records

        html = self._execution_html(execution)
        final_url = execution.final_url or self._build_url(source, "/forwarders")
        if self._is_login_page(html, final_url):
            raise RuntimeError("vend.email forwarder list requires authenticated session")
        return self._parse_forwarders_from_html(html)

    def create_forwarder(
        self,
        state,
        source: dict,
        *,
        local_part: str,
        domain_id: str,
        recipient: str,
    ) -> VendEmailForwarderRecord | None:
        self._active_state = state
        new_page = self._fetch_form_page(state, source, name="new_forwarder_form", path="/forwarders/new")
        resolved_domain_id = self._resolve_forwarder_domain_id(
            html=self._execution_html(new_page),
            source=source,
            fallback_domain_id=domain_id,
        )
        execution = self._execute(
            state,
            source,
            VendEmailRuntimeOperation(
                name="create_forwarder",
                method="POST",
                url=self._build_url(source, "/forwarders"),
                request_headers_whitelist=self._form_headers(
                    referer=self._build_url(source, "/forwarders/new"),
                    csrf_token=self._meta_csrf_token(new_page),
                ),
                request_body_excerpt=self._form_encode(
                    self._merge_form_fields(
                        new_page,
                        form_action="/forwarders",
                        extra_fields=[
                            ("forwarder[local_part]", local_part),
                            ("forwarder[domain_id]", str(resolved_domain_id)),
                            ("forwarder[name]", ""),
                            ("forwarder[recipient]", recipient),
                            ("tags", ""),
                            ("forwarder[tags_string]", ""),
                            ("forwarder[title]", ""),
                            ("forwarder[description]", ""),
                            ("forwarder[supporting_details]", ""),
                        ],
                    )
                ),
            ),
        )
        if isinstance(execution.payload, dict) and "email" in execution.payload:
            return self._forwarder_from_payload(execution.payload, recipient_email=recipient)

        html = self._execution_html(execution)
        final_url = execution.final_url or self._build_url(source, "/forwarders")
        return self._forwarder_from_html(
            html=html,
            final_url=final_url,
            recipient_email=recipient,
        )

    def list_aliases(self, state, source: dict) -> list[str]:
        return [record.alias_email for record in self.list_forwarders(state, source)]

    def create_aliases(self, state, source: dict, missing_count: int) -> list[str]:
        if missing_count <= 0:
            return []

        aliases: list[str] = []
        base_local_part = self._service_local_part(state) or "vend"
        attempt = 0

        while len(aliases) < missing_count:
            local_part = base_local_part if attempt == 0 else f"{base_local_part}{attempt + 1}"
            attempt += 1
            created = self.create_forwarder(
                state,
                source,
                local_part=local_part,
                domain_id=str(source.get("alias_domain_id") or ""),
                recipient=self._recipient_mailbox(source, state),
            )
            if created is None or not created.alias_email:
                break
            aliases.append(created.alias_email)

        return aliases

    def capture_summary(self) -> list[VendEmailCaptureRecord]:
        return list(self._captures)

    def _execute(
        self,
        state,
        source: dict,
        operation: VendEmailRuntimeOperation,
    ) -> VendEmailRuntimeExecution:
        execution = self._executor.execute(operation, state, source)
        self._captures.append(
            VendEmailCaptureRecord(
                name=operation.name,
                url=operation.url,
                method=operation.method,
                request_headers_whitelist=dict(operation.request_headers_whitelist),
                request_body_excerpt=operation.request_body_excerpt,
                response_status=execution.response_status,
                response_body_excerpt=execution.response_body_excerpt,
                captured_at=execution.captured_at,
            )
        )
        return execution

    def _execute_following_safe_redirects(
        self,
        state,
        source: dict,
        *,
        operation_name: str,
        url: str,
        max_redirects: int = 5,
    ) -> VendEmailRuntimeExecution:
        current_url = url
        for _ in range(max_redirects + 1):
            _ensure_safe_outbound_url(url=current_url, field_name="confirmation_link")
            response = self._executor.execute(
                VendEmailRuntimeOperation(
                    name=operation_name,
                    method="GET",
                    url=current_url,
                ),
                state,
                source,
            )
            self._captures.append(
                VendEmailCaptureRecord(
                    name=operation_name,
                    url=current_url,
                    method="GET",
                    request_headers_whitelist={},
                    request_body_excerpt="",
                    response_status=response.response_status,
                    response_body_excerpt=response.response_body_excerpt,
                    captured_at=response.captured_at,
                )
            )
            final_url = response.final_url or current_url
            if final_url == current_url:
                return response
            current_url = final_url
        raise RuntimeError("vend.email confirmation exceeded redirect limit")

    def _build_url(self, source: dict, path: str) -> str:
        base_url = self._base_url(source)
        return f"{base_url}{path}"

    def _base_url(self, source: dict) -> str:
        register_url = str(source.get("register_url") or "").strip().rstrip("/")
        for suffix in ("/auth/register", "/register"):
            if register_url.endswith(suffix):
                return register_url[: -len(suffix)]
        return register_url

    def _service_email(self, state) -> str:
        return str(getattr(state, "service_email", "") or "").strip().lower()

    def _service_local_part(self, state) -> str:
        service_email = self._service_email(state)
        if "@" not in service_email:
            return service_email
        return service_email.split("@", 1)[0]

    def _service_password(self, state) -> str:
        return str(getattr(state, "service_password", "") or "")

    def _service_mailbox_email(self, state) -> str:
        return str(getattr(state, "mailbox_email", "") or "").strip().lower()

    def _recipient_mailbox(self, source: dict, state) -> str:
        return self._service_mailbox_email(state)

    def _html_headers(self) -> dict[str, str]:
        return {"accept": "text/html, application/xhtml+xml"}

    def _form_headers(
        self,
        *,
        referer: str = "",
        csrf_token: str = "",
    ) -> dict[str, str]:
        headers = {
            "content-type": "application/x-www-form-urlencoded",
            "accept": "text/vnd.turbo-stream.html, text/html, application/xhtml+xml",
        }
        if referer:
            headers["referer"] = referer
        if csrf_token:
            headers["x-csrf-token"] = csrf_token
        return headers

    def _form_encode(self, items: list[tuple[str, str]]) -> str:
        return urlencode(items, quote_via=quote_plus, safe="[]")

    def _execution_html(self, execution: VendEmailRuntimeExecution) -> str:
        if isinstance(execution.payload, dict):
            html = execution.payload.get("html")
            if isinstance(html, str):
                return html
        return str(execution.response_body_excerpt or "")

    def _meta_csrf_token(self, execution: VendEmailRuntimeExecution) -> str:
        html = self._execution_html(execution)
        match = re.search(r'<meta[^>]+name=["\']csrf-token["\'][^>]+content=["\']([^"\']+)', html, re.IGNORECASE)
        return unescape(match.group(1)) if match else ""

    def _parse_html_attributes(self, raw_attrs: str) -> dict[str, str]:
        attrs: dict[str, str] = {}
        for name, value in re.findall(r'([:\w\-\[\]]+)\s*=\s*["\']([^"\']*)["\']', raw_attrs):
            attrs[name.lower()] = unescape(value)
        return attrs

    def _extract_hidden_fields(self, html: str, *, form_action: str) -> list[tuple[str, str]]:
        form_match = re.search(
            rf'<form[^>]+action=["\'][^"\']*{re.escape(form_action)}[^"\']*["\'][^>]*>(.*?)</form>',
            html,
            re.IGNORECASE | re.DOTALL,
        )
        scope = form_match.group(1) if form_match else html
        fields: list[tuple[str, str]] = []
        for input_match in re.finditer(r'<input\b([^>]+)>', scope, re.IGNORECASE):
            attrs = self._parse_html_attributes(input_match.group(1))
            input_type = attrs.get("type", "").lower()
            name = attrs.get("name", "")
            if not name:
                continue
            if input_type == "hidden" or name == "authenticity_token":
                fields.append((name, attrs.get("value", "")))
        return fields

    def _merge_form_fields(
        self,
        execution: VendEmailRuntimeExecution,
        *,
        form_action: str,
        extra_fields: list[tuple[str, str]],
    ) -> list[tuple[str, str]]:
        hidden_fields = self._extract_hidden_fields(self._execution_html(execution), form_action=form_action)
        merged: dict[str, str] = {name: value for name, value in hidden_fields}
        for name, value in extra_fields:
            merged[name] = value
        return list(merged.items())

    def _fetch_form_page(
        self,
        state,
        source: dict,
        *,
        name: str,
        path: str,
    ) -> VendEmailRuntimeExecution:
        return self._execute(
            state,
            source,
            VendEmailRuntimeOperation(
                name=name,
                method="GET",
                url=self._build_url(source, path),
                request_headers_whitelist=self._html_headers(),
            ),
        )

    def _is_login_page(self, html: str, final_url: str) -> bool:
        normalized_html = html.lower()
        normalized_url = final_url.lower()
        return (
            "/auth/login" in normalized_url
            or "sign in to your account" in normalized_html
            or "you need to sign in or sign up before continuing" in normalized_html
        )

    def _is_register_page(self, html: str, final_url: str) -> bool:
        normalized_html = html.lower()
        normalized_url = final_url.lower()
        return "/auth/register" in normalized_url or "sign up for a free account" in normalized_html

    def _is_confirmation_issue_page(self, html: str) -> bool:
        normalized_html = html.lower()
        return "resend confirmation instructions" in normalized_html and "please review the problems below" in normalized_html

    def _parse_forwarders_from_html(self, html: str) -> list[VendEmailForwarderRecord]:
        aliases: list[VendEmailForwarderRecord] = []
        seen: set[str] = set()
        for alias_email in re.findall(r'/forwarders/([^"\'#?]+@[^"\'#?/]+)', html, re.IGNORECASE):
            decoded_alias = unquote(alias_email).strip().lower()
            if not decoded_alias or decoded_alias in seen:
                continue
            seen.add(decoded_alias)
            aliases.append(
                VendEmailForwarderRecord(
                    alias_email=decoded_alias,
                    recipient_email="",
                )
            )
        return aliases

    def _forwarder_from_html(
        self,
        *,
        html: str,
        final_url: str,
        recipient_email: str,
    ) -> VendEmailForwarderRecord | None:
        match = re.search(r'/forwarders/([^/?#]+@[^/?#]+)', final_url, re.IGNORECASE)
        alias_email = unquote(match.group(1)).strip().lower() if match else ""
        if not alias_email:
            heading_match = re.search(r'<h1[^>]*>([^<]+@[^<]+)</h1>', html, re.IGNORECASE)
            if heading_match:
                alias_email = unescape(heading_match.group(1)).strip().lower()
        if not alias_email:
            return None
        return VendEmailForwarderRecord(alias_email=alias_email, recipient_email=recipient_email)

    def _resolve_forwarder_domain_id(
        self,
        *,
        html: str,
        source: dict,
        fallback_domain_id: str,
    ) -> str:
        alias_domain = str(source.get("alias_domain") or "").strip().lower()
        configured_domain_id = str(source.get("alias_domain_id") or fallback_domain_id or "").strip()
        select_match = re.search(
            r'<select[^>]+name=["\']forwarder\[domain_id\]["\'][^>]*>(.*?)</select>',
            html,
            re.IGNORECASE | re.DOTALL,
        )
        if not select_match:
            return configured_domain_id
        options_html = select_match.group(1)
        parsed_options: list[tuple[str, str, bool]] = []
        for option_match in re.finditer(r'<option\b([^>]*)>(.*?)</option>', options_html, re.IGNORECASE | re.DOTALL):
            attrs = self._parse_html_attributes(option_match.group(1))
            value = attrs.get("value", "")
            label = unescape(re.sub(r'<[^>]+>', '', option_match.group(2))).strip().lower()
            is_selected = 'selected' in option_match.group(1).lower()
            parsed_options.append((value, label, is_selected))
        if alias_domain:
            for value, label, _ in parsed_options:
                if alias_domain in label:
                    return value or configured_domain_id
        if configured_domain_id:
            for value, _, _ in parsed_options:
                if value == configured_domain_id:
                    return configured_domain_id
        for value, _, is_selected in parsed_options:
            if is_selected and value:
                return value
        return parsed_options[0][0] if parsed_options else configured_domain_id

    def _forwarder_from_payload(
        self,
        payload: dict,
        *,
        recipient_email: str = "",
    ) -> VendEmailForwarderRecord | None:
        alias_email = str(payload.get("email") or payload.get("alias_email") or "").strip().lower()
        resolved_recipient = str(payload.get("recipient") or recipient_email or "").strip().lower()
        if not alias_email:
            return None
        return VendEmailForwarderRecord(
            alias_email=alias_email,
            recipient_email=resolved_recipient,
        )


class VendEmailAliasServiceProducer:
    source_kind = "vend_email"

    def __init__(self, *, source: dict, state_store, runtime: object):
        self.source = dict(source)
        self.source_id = str(source.get("id") or "vend-email")
        self.state_store = state_store
        self.runtime = cast(VendEmailRuntime, runtime)
        self._state = AliasSourceState.IDLE

    def state(self) -> AliasSourceState:
        return self._state

    def load_into(self, manager) -> None:
        delegated = build_vend_email_alias_service_producer(
            source=self.source,
            task_id=self.source_id,
            state_store_factory=lambda *_args, **_kwargs: self.state_store,
            runtime_builder=lambda _source: self.runtime,
        )
        typed_delegated = cast(VendAliasProvider, delegated)
        self._state = AliasSourceState.ACTIVE
        try:
            typed_delegated.load_into(manager)
            self._state = typed_delegated.state()
        except Exception:
            self._state = typed_delegated.state()
            raise
