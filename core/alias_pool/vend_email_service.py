from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Protocol

from core.http_client import HTTPClient

from .mailbox_verification_adapter import (
    build_mailbox_email_list_request,
    build_mailbox_login_request,
    extract_anchored_link_from_message_content,
    extract_token_from_storage,
    with_token_in_session_storage,
)
from .probe import AliasProbeResult
from .vend_email_state import VendEmailCaptureRecord, VendEmailServiceState


@dataclass(frozen=True)
class VendEmailRuntimeExecution:
    response_status: int
    response_body_excerpt: str
    payload: Any = None


class VendEmailRuntimeExecutor(Protocol):
    def restore_session(self, state: VendEmailServiceState, source: dict) -> bool: ...

    def register(self, state: VendEmailServiceState, source: dict): ...

    def fetch_confirmation_link(self, source: dict) -> str: ...

    def confirm(self, confirmation_link: str, source: dict): ...

    def login(self, state: VendEmailServiceState, source: dict): ...

    def list_forwarders(self, state: VendEmailServiceState, source: dict) -> list[dict]: ...

    def create_forwarder(self, state: VendEmailServiceState, source: dict) -> dict: ...

    def capture_summary(self) -> list[dict]: ...


class _VendHTTPRuntime:
    def __init__(self, *, source: dict):
        self.source = dict(source)
        self._capture_entries: list[dict[str, Any]] = []
        self._client = HTTPClient()
        self._active_state: VendEmailServiceState | None = None

    def _require_string(self, key: str) -> str:
        value = str(self.source.get(key) or "").strip()
        if not value:
            raise ValueError(key)
        return value

    def _require_int(self, key: str) -> int:
        value = self.source.get(key)
        if value is None:
            raise ValueError(key)
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(key) from exc

    def _capture(
        self,
        *,
        name: str,
        method: str,
        url: str,
        headers: dict[str, str] | None,
        body_excerpt: str,
        response_status: int,
        response_body_excerpt: str,
    ) -> None:
        self._capture_entries.append(
            {
                "name": name,
                "url": url,
                "method": method,
                "request_headers_whitelist": dict(headers or {}),
                "request_body_excerpt": body_excerpt,
                "response_status": response_status,
                "response_body_excerpt": response_body_excerpt,
                "captured_at": "configured-runtime",
            }
        )

    def _execute(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_payload: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> VendEmailRuntimeExecution:
        response = self._client.request(
            method,
            url,
            headers=headers,
            params=params,
            json=json_payload,
            data=data,
        )
        payload: Any = None
        try:
            payload = json.loads(response.text)
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = None
        return VendEmailRuntimeExecution(
            response_status=int(getattr(response, "status_code", 0) or 0),
            response_body_excerpt=str(getattr(response, "text", "") or ""),
            payload=payload,
        )

    def _service_email(self, state: VendEmailServiceState) -> str:
        service_email = str(state.service_email or self.source.get("service_email") or "").strip().lower()
        if not service_email:
            service_email = self._require_string("mailbox_service_email").lower()
        return service_email

    def _service_password(self, state: VendEmailServiceState) -> str:
        service_password = str(state.service_password or self.source.get("service_password") or "").strip()
        if not service_password:
            service_password = self._require_string("mailbox_password")
        return service_password

    def _mailbox_email(self, state: VendEmailServiceState) -> str:
        mailbox_email = str(state.mailbox_email or self.source.get("mailbox_email") or "").strip().lower()
        if not mailbox_email:
            raise ValueError("mailbox_email")
        return mailbox_email

    def _register_url(self) -> str:
        return self._require_string("register_url")

    def _vend_base_url(self) -> str:
        register_url = self._register_url().rstrip("/")
        for suffix in ("/auth/register", "/register"):
            if register_url.endswith(suffix):
                return register_url[: -len(suffix)]
        return register_url

    def restore_session(self, state: VendEmailServiceState, source: dict) -> bool:
        self._active_state = state
        return bool(state.session_cookies or state.session_storage)

    def register(self, state: VendEmailServiceState, source: dict):
        self._active_state = state
        service_email = self._service_email(state)
        service_password = self._service_password(state)
        local_part = service_email.partition("@")[0]
        data = {
            "user[name]": local_part,
            "user[email]": service_email,
            "user[password]": service_password,
        }
        execution = self._execute(method="POST", url=self._register_url(), data=data)
        state.service_email = service_email
        state.service_password = service_password
        state.mailbox_email = self._mailbox_email(state)
        state.session_storage["register_url"] = self._register_url()
        self._capture(
            name="register",
            method="POST",
            url=self._register_url(),
            headers={},
            body_excerpt="&".join(f"{key}={value}" for key, value in data.items()),
            response_status=execution.response_status,
            response_body_excerpt=execution.response_body_excerpt,
        )
        return None

    def fetch_confirmation_link(self, source: dict) -> str:
        state = self._active_state
        if state is None:
            state = VendEmailServiceState(
                state_key=str(source.get("state_key") or source.get("id") or "vend-email"),
                service_email=str(source.get("service_email") or source.get("mailbox_service_email") or "").strip().lower(),
                mailbox_email=str(source.get("mailbox_email") or "").strip().lower(),
                service_password=str(source.get("service_password") or source.get("mailbox_password") or "").strip(),
            )
            self._active_state = state
        mailbox_login_request = build_mailbox_login_request(
            mailbox_base_url=self._require_string("mailbox_base_url"),
            mailbox_email=self._mailbox_email(state),
            mailbox_password=self._require_string("mailbox_password"),
        )
        login_execution = self._execute(
            method=str(mailbox_login_request["method"]),
            url=str(mailbox_login_request["url"]),
            json_payload=dict(mailbox_login_request["json"]),
        )
        token = ""
        if isinstance(login_execution.payload, dict):
            token = str(login_execution.payload.get("token") or "").strip()
        if not token:
            token = extract_token_from_storage(state.session_storage)
        state.session_storage = with_token_in_session_storage(state.session_storage, token)
        self._capture(
            name="mailbox_login",
            method=str(mailbox_login_request["method"]),
            url=str(mailbox_login_request["url"]),
            headers={},
            body_excerpt=str(mailbox_login_request["json"]),
            response_status=login_execution.response_status,
            response_body_excerpt=login_execution.response_body_excerpt,
        )

        mailbox_list_request = build_mailbox_email_list_request(
            mailbox_base_url=self._require_string("mailbox_base_url"),
            token=token,
            account_id=self._require_int("mailbox_account_id"),
        )
        mailbox_execution = self._execute(
            method=str(mailbox_list_request["method"]),
            url=str(mailbox_list_request["url"]),
            params=dict(mailbox_list_request["params"]),
            headers=dict(mailbox_list_request["headers"]),
        )
        confirmation_anchor = str(
            self.source.get("confirmation_anchor")
            or self.source.get("confirmation_anchor_prefix")
            or ""
        ).strip()
        message_content = mailbox_execution.response_body_excerpt
        if isinstance(mailbox_execution.payload, list):
            for item in mailbox_execution.payload:
                if isinstance(item, dict):
                    candidate = str(item.get("content") or item.get("body") or "")
                    if candidate:
                        message_content = candidate
                        break
        confirmation_link = extract_anchored_link_from_message_content(
            message_content,
            link_anchor=confirmation_anchor,
        )
        self._capture(
            name="mailbox_verification",
            method=str(mailbox_list_request["method"]),
            url=str(mailbox_list_request["url"]),
            headers=dict(mailbox_list_request["headers"]),
            body_excerpt="",
            response_status=mailbox_execution.response_status,
            response_body_excerpt=confirmation_link or mailbox_execution.response_body_excerpt,
        )
        return confirmation_link

    def confirm(self, confirmation_link: str, source: dict):
        execution = self._execute(method="POST", url=confirmation_link)
        self._capture(
            name="confirmation",
            method="POST",
            url=confirmation_link,
            headers={},
            body_excerpt="",
            response_status=execution.response_status,
            response_body_excerpt=execution.response_body_excerpt,
        )
        return None

    def login(self, state: VendEmailServiceState, source: dict):
        self._active_state = state
        login_url = f"{self._vend_base_url()}/auth/login"
        data = {
            "user[email]": self._service_email(state),
            "user[password]": self._service_password(state),
        }
        execution = self._execute(method="POST", url=login_url, data=data)
        state.service_email = self._service_email(state)
        state.service_password = self._service_password(state)
        self._capture(
            name="login",
            method="POST",
            url=login_url,
            headers={},
            body_excerpt="&".join(f"{key}={value}" for key, value in data.items()),
            response_status=execution.response_status,
            response_body_excerpt=execution.response_body_excerpt,
        )
        return None

    def list_forwarders(self, state: VendEmailServiceState, source: dict) -> list[dict]:
        self._active_state = state
        url = f"{self._vend_base_url()}/forwarders"
        execution = self._execute(method="GET", url=url)
        self._capture(
            name="list_forwarders",
            method="GET",
            url=url,
            headers={},
            body_excerpt="",
            response_status=execution.response_status,
            response_body_excerpt=execution.response_body_excerpt,
        )
        if isinstance(execution.payload, list):
            return [item for item in execution.payload if isinstance(item, dict)]
        return []

    def create_forwarder(self, state: VendEmailServiceState, source: dict) -> dict:
        self._active_state = state
        url = f"{self._vend_base_url()}/forwarders"
        service_email = self._service_email(state)
        local_part = service_email.partition("@")[0] or str(source.get("id") or "vend-email")
        data = {
            "forwarder[local_part]": local_part,
            "forwarder[domain_id]": str(self._require_string("alias_domain_id")),
            "forwarder[recipient]": self._mailbox_email(state),
        }
        execution = self._execute(method="POST", url=url, data=data)
        self._capture(
            name="create_forwarder",
            method="POST",
            url=url,
            headers={},
            body_excerpt="&".join(f"{key}={value}" for key, value in data.items()),
            response_status=execution.response_status,
            response_body_excerpt=execution.response_body_excerpt,
        )
        if isinstance(execution.payload, dict):
            payload = dict(execution.payload)
        else:
            payload = {}
        alias_email = str(payload.get("email") or payload.get("alias_email") or "").strip().lower()
        recipient = str(payload.get("recipient") or self._mailbox_email(state) or "").strip().lower()
        return {
            "alias_email": alias_email,
            "real_mailbox_email": recipient,
        }

    def capture_summary(self) -> list[dict]:
        return list(self._capture_entries)


def build_default_vend_executor(source: dict) -> VendEmailRuntimeExecutor:
    required_keys = [
        "mailbox_base_url",
        "mailbox_password",
        "mailbox_account_id",
        "register_url",
        "alias_domain",
        "alias_domain_id",
    ]
    service_email = source.get("service_email") or source.get("mailbox_service_email")
    if service_email in (None, ""):
        required_keys.append("mailbox_service_email")
    for key in required_keys:
        value = source.get(key)
        if value is None or str(value).strip() == "":
            raise ValueError(key)
    return _VendHTTPRuntime(source=source)


class VendEmailStateStore(Protocol):
    def load(self, state_key: str) -> VendEmailServiceState: ...

    def save(self, state: VendEmailServiceState) -> None: ...


class VendEmailRuntimeService:
    def __init__(self, *, state_store: VendEmailStateStore, executor: VendEmailRuntimeExecutor):
        self.state_store = state_store
        self.executor = executor

    def _load_state(self, state_key: str) -> VendEmailServiceState:
        state = self.state_store.load(state_key)
        if not isinstance(state, VendEmailServiceState):
            raise TypeError("state_store.load() must return VendEmailServiceState")
        return state

    def _normalize_capture_summary(self, items: list[dict[str, Any]]) -> list[VendEmailCaptureRecord]:
        try:
            return [VendEmailCaptureRecord(**item) for item in items]
        except TypeError as exc:
            raise TypeError("capture_summary() items must match VendEmailCaptureRecord fields") from exc

    def run_probe(self, *, source: dict) -> AliasProbeResult:
        state_key = str(source.get("state_key") or source.get("id") or "vend-email")
        state = self._load_state(state_key)
        state.mailbox_email = str(state.mailbox_email or source.get("mailbox_email") or "").strip().lower()
        if not state.service_email:
            state.service_email = str(
                source.get("service_email") or source.get("mailbox_service_email") or ""
            ).strip().lower()
        if not state.service_password:
            state.service_password = str(
                source.get("service_password") or source.get("mailbox_password") or ""
            ).strip()
        confirmation_link = str(state.session_storage.get("confirmation_link") or "")

        steps: list[str] = []
        if not self.executor.restore_session(state, source):
            steps.append("register")
            self.executor.register(state, source)
            confirmation_link = self.executor.fetch_confirmation_link(source)
            steps.append("confirmation")
            self.executor.confirm(confirmation_link, source)

        steps.append("login")
        self.executor.login(state, source)

        steps.append("list_forwarders")
        forwarders = self.executor.list_forwarders(state, source)
        if forwarders:
            alias_email = str(forwarders[0].get("alias_email") or "").strip().lower()
            real_mailbox_email = str(
                forwarders[0].get("real_mailbox_email") or state.mailbox_email or source.get("mailbox_email") or ""
            ).strip().lower()
        else:
            steps.append("create_forwarder")
            created = self.executor.create_forwarder(state, source)
            alias_email = str(created.get("alias_email") or "").strip().lower()
            real_mailbox_email = str(
                created.get("real_mailbox_email") or state.mailbox_email or source.get("mailbox_email") or ""
            ).strip().lower()

        capture_summary = list(self.executor.capture_summary())
        if "register_url" in source:
            state.session_storage["register_url"] = str(source.get("register_url") or "")
        state.session_storage["confirmation_link"] = confirmation_link
        state.known_aliases = [alias_email] if alias_email else []
        state.last_capture_summary = self._normalize_capture_summary(capture_summary)
        self.state_store.save(state)

        return AliasProbeResult(
            ok=bool(alias_email),
            source_id=str(source.get("id") or ""),
            source_type="vend_email",
            alias_email=alias_email,
            real_mailbox_email=real_mailbox_email,
            service_email=state.service_email,
            capture_summary=[asdict(item) for item in state.last_capture_summary],
            steps=steps,
            logs=["vend probe completed"],
            error="" if alias_email else "vend probe did not produce alias",
        )
