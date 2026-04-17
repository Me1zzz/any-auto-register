from pathlib import Path
from dataclasses import dataclass, field
from urllib.parse import urlencode, quote_plus
from typing import Callable, Protocol, cast

from .base import AliasEmailLease, AliasSourceState
from .vend_email_state import VendEmailServiceState
from .vend_email_state import VendEmailFileStateStore
from .vend_email_state import VendEmailCaptureRecord


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
    state_dir = Path("data") / "alias_pool" / "vend_email" / task_id
    return VendEmailTaskStateStore(state_dir / f"{source_id}.json")


def build_default_vend_email_runtime(source: dict):
    raise RuntimeError(
        f"vend.email runtime builder is not configured for source '{source.get('id') or 'vend-email'}'"
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

    def restore_session(self, state) -> bool:
        return bool(getattr(state, "session_cookies", None) or getattr(state, "session_storage", None))

    def register(self, state, source: dict) -> bool:
        service_email = self._service_email(state)
        local_part = service_email.split("@", 1)[0]
        execution = self._execute(
            state,
            source,
            VendEmailRuntimeOperation(
                name="register",
                method="POST",
                url=self._build_url(source, "/auth"),
                request_headers_whitelist=self._form_headers(),
                request_body_excerpt=self._form_encode(
                    [
                        ("user[name]", local_part),
                        ("user[email]", service_email),
                        ("user[password]", self._service_password(state)),
                    ]
                ),
            ),
        )
        return execution.ok

    def resend_confirmation(self, state, source: dict) -> bool:
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
        execution = self._execute(
            state,
            source,
            VendEmailRuntimeOperation(
                name="login",
                method="POST",
                url=self._build_url(source, "/auth/login"),
                request_headers_whitelist=self._form_headers(),
                request_body_excerpt=self._form_encode(
                    [
                        ("user[email]", self._service_email(state)),
                        ("user[password]", self._service_password(state)),
                    ]
                ),
            ),
        )
        return execution.ok

    def list_forwarders(self, state, source: dict) -> list[VendEmailForwarderRecord]:
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
        if not isinstance(payload, list):
            return []
        records: list[VendEmailForwarderRecord] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            record = self._forwarder_from_payload(item)
            if record is not None:
                records.append(record)
        return records

    def create_forwarder(
        self,
        state,
        source: dict,
        *,
        local_part: str,
        domain_id: str,
        recipient: str,
    ) -> VendEmailForwarderRecord | None:
        execution = self._execute(
            state,
            source,
            VendEmailRuntimeOperation(
                name="create_forwarder",
                method="POST",
                url=self._build_url(source, "/forwarders"),
                request_headers_whitelist=self._form_headers(),
                request_body_excerpt=self._form_encode(
                    [
                        ("forwarder[local_part]", local_part),
                        ("forwarder[domain_id]", str(domain_id)),
                        ("forwarder[recipient]", recipient),
                    ]
                ),
            ),
        )
        if not isinstance(execution.payload, dict):
            return None
        return self._forwarder_from_payload(execution.payload, recipient_email=recipient)

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

    def _build_url(self, source: dict, path: str) -> str:
        base_url = str(source.get("register_url") or "").strip().rstrip("/")
        return f"{base_url}{path}"

    def _service_email(self, state) -> str:
        return str(getattr(state, "service_email", "") or "").strip().lower()

    def _service_local_part(self, state) -> str:
        service_email = self._service_email(state)
        if "@" not in service_email:
            return service_email
        return service_email.split("@", 1)[0]

    def _service_password(self, state) -> str:
        return str(getattr(state, "service_password", "") or "")

    def _recipient_mailbox(self, source: dict, state) -> str:
        return str(source.get("mailbox_email") or getattr(state, "mailbox_email", "") or "").strip().lower()

    def _form_headers(self) -> dict[str, str]:
        return {"content-type": "application/x-www-form-urlencoded"}

    def _form_encode(self, items: list[tuple[str, str]]) -> str:
        return urlencode(items, quote_via=quote_plus, safe="[]")

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

    def _ensure_session(self, state) -> None:
        if self.runtime.restore_session(state):
            return
        if self.runtime.login(state, self.source):
            return
        if self.runtime.register(state, self.source):
            if not self.runtime.resend_confirmation(state, self.source):
                raise RuntimeError("vend.email confirmation bootstrap failed")
            if self.runtime.login(state, self.source):
                return
        raise RuntimeError("vend.email session bootstrap failed")

    def _capture_summary(self) -> list[VendEmailCaptureRecord]:
        capture_summary = getattr(self.runtime, "capture_summary", None)
        if not callable(capture_summary):
            raise VendEmailRuntimeProtocolError(
                "vend.email runtime must define callable capture_summary()"
            )
        typed_capture_summary = cast(
            Callable[[], list[VendEmailCaptureRecord]],
            capture_summary,
        )
        records = []
        for item in typed_capture_summary():
            if isinstance(item, VendEmailCaptureRecord):
                records.append(item)
            elif isinstance(item, dict):
                records.append(VendEmailCaptureRecord.from_dict(item))
            else:
                raise VendEmailRuntimeProtocolError(
                    "vend.email runtime capture_summary() must return VendEmailCaptureRecord items"
                )
        return records

    def load_into(self, manager) -> None:
        self._state = AliasSourceState.ACTIVE
        try:
            state_key = str(self.source.get("state_key") or self.source_id)
            state = self.state_store.load(state_key)
            self._ensure_session(state)

            aliases = list(self.runtime.list_aliases(state, self.source))
            target = max(int(self.source.get("alias_count") or 0), 0)
            missing_count = max(target - len(aliases), 0)
            if missing_count:
                aliases.extend(self.runtime.create_aliases(state, self.source, missing_count))

            unique_aliases = []
            seen = set()
            for alias in aliases:
                if alias in seen:
                    continue
                seen.add(alias)
                unique_aliases.append(alias)

            while len(unique_aliases) < target:
                remaining_missing_count = target - len(unique_aliases)
                created_aliases = list(
                    self.runtime.create_aliases(
                        state,
                        self.source,
                        remaining_missing_count,
                    )
                )
                if not created_aliases:
                    break

                for alias in created_aliases:
                    if alias in seen:
                        continue
                    seen.add(alias)
                    unique_aliases.append(alias)

            state.last_capture_summary = self._capture_summary()
            state.known_aliases = list(unique_aliases)
            state.mailbox_email = str(self.source.get("mailbox_email") or "").strip().lower()

            for alias_email in unique_aliases[:target]:
                manager.add_lease(
                    AliasEmailLease(
                        alias_email=alias_email,
                        real_mailbox_email=str(self.source.get("mailbox_email") or "").strip().lower(),
                        source_kind=self.source_kind,
                        source_id=self.source_id,
                        source_session_id=state_key,
                    )
                )

            state.state_key = state_key
            self.state_store.save(state)
            self._state = AliasSourceState.EXHAUSTED
        except Exception:
            self._state = AliasSourceState.FAILED
            raise
