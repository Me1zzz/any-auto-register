from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path


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


@dataclass
class VendEmailServiceState:
    state_key: str
    service_email: str = ""
    mailbox_email: str = ""
    service_password: str = ""
    session_cookies: list[dict[str, str]] = field(default_factory=list)
    session_storage: dict[str, str] = field(default_factory=dict)
    last_login_at: str = ""
    last_verified_at: str = ""
    known_aliases: list[str] = field(default_factory=list)
    last_capture_summary: list[VendEmailCaptureRecord] = field(default_factory=list)
    last_error: str = ""


class VendEmailFileStateStore:
    def __init__(self, *, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def for_task(cls, *, task_id: str) -> "VendEmailFileStateStore":
        return cls(base_dir=Path(".alias_pool") / "vend_email" / task_id)

    def _path_for(self, state_key: str) -> Path:
        return self.base_dir / f"{state_key}.json"

    def save(self, state: VendEmailServiceState) -> None:
        self._path_for(state.state_key).write_text(
            json.dumps(asdict(state), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self, state_key: str) -> VendEmailServiceState:
        path = self._path_for(state_key)
        if not path.exists():
            return VendEmailServiceState(state_key=state_key)

        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["last_capture_summary"] = [
            VendEmailCaptureRecord(**item)
            for item in payload.get("last_capture_summary", [])
        ]
        return VendEmailServiceState(**payload)
