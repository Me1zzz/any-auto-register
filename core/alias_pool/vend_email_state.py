import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _string_field(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, str):
        return value
    return ""


@dataclass
class VendEmailCaptureRecord:
    name: str
    url: str
    method: str
    request_headers_whitelist: dict[str, str]
    request_body_excerpt: str
    response_status: int
    response_body_excerpt: str
    captured_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "url": self.url,
            "method": self.method,
            "request_headers_whitelist": dict(self.request_headers_whitelist),
            "request_body_excerpt": self.request_body_excerpt,
            "response_status": self.response_status,
            "response_body_excerpt": self.response_body_excerpt,
            "captured_at": self.captured_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "VendEmailCaptureRecord":
        raw_request_headers_whitelist = payload.get("request_headers_whitelist")
        if not isinstance(raw_request_headers_whitelist, dict):
            raw_request_headers_whitelist = {}

        response_status_value = payload.get("response_status")
        if isinstance(response_status_value, int):
            response_status = response_status_value
        elif isinstance(response_status_value, str):
            try:
                response_status = int(response_status_value)
            except ValueError:
                response_status = 0
        else:
            response_status = 0

        return cls(
            name=_string_field(payload, "name"),
            url=_string_field(payload, "url"),
            method=_string_field(payload, "method"),
            request_headers_whitelist={
                str(key): str(value)
                for key, value in raw_request_headers_whitelist.items()
                if isinstance(key, str) and isinstance(value, str)
            },
            request_body_excerpt=_string_field(payload, "request_body_excerpt"),
            response_status=response_status,
            response_body_excerpt=_string_field(payload, "response_body_excerpt"),
            captured_at=_string_field(payload, "captured_at"),
        )


@dataclass
class VendEmailServiceState:
    state_key: str
    service_email: str = ""
    mailbox_email: str = ""
    service_password: str = ""
    session_cookies: list[dict[str, Any]] = field(default_factory=list)
    session_storage: dict[str, Any] = field(default_factory=dict)
    last_login_at: str = ""
    last_verified_at: str = ""
    known_aliases: list[str] = field(default_factory=list)
    last_capture_summary: list[VendEmailCaptureRecord] = field(default_factory=list)
    last_error: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "state_key": self.state_key,
            "service_email": self.service_email,
            "mailbox_email": self.mailbox_email,
            "service_password": self.service_password,
            "session_cookies": list(self.session_cookies),
            "session_storage": dict(self.session_storage),
            "last_login_at": self.last_login_at,
            "last_verified_at": self.last_verified_at,
            "known_aliases": list(self.known_aliases),
            "last_capture_summary": [capture.to_dict() for capture in self.last_capture_summary],
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "VendEmailServiceState":
        raw_capture_summary = payload.get("last_capture_summary")
        if not isinstance(raw_capture_summary, list):
            raw_capture_summary = []

        raw_known_aliases = payload.get("known_aliases")
        if not isinstance(raw_known_aliases, list):
            raw_known_aliases = []

        raw_session_cookies = payload.get("session_cookies")
        if not isinstance(raw_session_cookies, list):
            raw_session_cookies = []

        raw_session_storage = payload.get("session_storage")
        if not isinstance(raw_session_storage, dict):
            raw_session_storage = {}

        capture_summary = [
            VendEmailCaptureRecord.from_dict(item)
            for item in raw_capture_summary
            if isinstance(item, dict)
        ]
        known_aliases = [str(item) for item in raw_known_aliases if isinstance(item, str)]
        return cls(
            state_key=_string_field(payload, "state_key"),
            service_email=_string_field(payload, "service_email"),
            mailbox_email=_string_field(payload, "mailbox_email"),
            service_password=_string_field(payload, "service_password"),
            session_cookies=[item for item in raw_session_cookies if isinstance(item, dict)],
            session_storage=dict(raw_session_storage),
            last_login_at=_string_field(payload, "last_login_at"),
            last_verified_at=_string_field(payload, "last_verified_at"),
            known_aliases=known_aliases,
            last_capture_summary=capture_summary,
            last_error=str(payload.get("last_error") or ""),
        )


class VendEmailFileStateStore:
    def __init__(self, path: Path | str):
        self._path = Path(path)

    def load(self) -> VendEmailServiceState:
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("vend.email state file must contain a JSON object")
        return VendEmailServiceState.from_dict(payload)

    def save(self, state: VendEmailServiceState) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
