from __future__ import annotations

from html import unescape
import re
import secrets
from typing import Any, cast

from core.alias_pool.account_logging import log_alias_service_account_registered
from core.alias_pool.base import AliasEmailLease, AliasSourceState
from core.base_mailbox import CloudMailMailbox
from core.alias_pool.provider_contracts import AliasAutomationTestPolicy
from core.alias_pool.vend_confirmation import ConfirmationReadResult
from core.alias_pool.vend_email_state import VendEmailCaptureRecord


_CAPTURE_DETAIL_LIMIT = 240
_HTML_ERROR_BLOCK_PATTERN = re.compile(
    r"<(?P<tag>div|section|article|p|span|ul)[^>]*"
    r"(?:"
    r"role=[\"']alert[\"']|"
    r"id=[\"'][^\"']*(?:error|alert|flash|notice)[^\"']*[\"']|"
    r"class=[\"'][^\"']*(?:error|alert|danger|red|invalid|flash|notice)[^\"']*[\"']"
    r")[^>]*>"
    r"(?P<body>.*?)"
    r"</(?P=tag)>",
    re.IGNORECASE | re.DOTALL,
)
_HTML_FAILURE_KEYWORDS = (
    "invalid",
    "already",
    "taken",
    "required",
    "error",
    "failed",
    "incorrect",
    "unconfirmed",
    "confirmation",
    "too many",
    "locked",
    "captcha",
)


def build_service_email(source: dict) -> str:
    mailbox = CloudMailMailbox(
        api_base=str(source.get("cloudmail_api_base") or "").strip(),
        admin_email=str(source.get("cloudmail_admin_email") or "").strip(),
        admin_password=str(source.get("cloudmail_admin_password") or "").strip(),
        domain=source.get("cloudmail_domain") or "",
        subdomain=str(source.get("cloudmail_subdomain") or "").strip(),
        timeout=int(source.get("cloudmail_timeout") or 30),
    )
    return mailbox.get_email().email


def build_service_password() -> str:
    return secrets.token_urlsafe(18)


def is_cloudmail_domain_email(value: str, source: dict) -> bool:
    email = str(value or "").strip().lower()
    if not email or "@" not in email:
        return False
    expected_domain = _effective_cloudmail_domain(source)
    if not expected_domain:
        return bool(email)
    return email.endswith(f"@{expected_domain}")


def _effective_cloudmail_domain(source: dict) -> str:
    base_domain = str(source.get("cloudmail_domain") or "").strip().lower().lstrip("@")
    subdomain = str(source.get("cloudmail_subdomain") or "").strip().lower().strip(".")
    if not subdomain:
        return base_domain
    if not base_domain:
        return subdomain
    if base_domain == subdomain or base_domain.startswith(f"{subdomain}."):
        return base_domain
    return f"{subdomain}.{base_domain}"


class VendAliasProvider:
    source_kind = "vend_email"

    def __init__(
        self,
        *,
        spec,
        state_repository,
        runtime,
        confirmation_reader,
        telemetry,
        log_fn=None,
    ):
        self._spec = spec
        provider_config = dict(getattr(spec, "provider_config", {}) or {})
        raw_source = dict(spec.raw_source or {})
        self.source = {
            **provider_config,
            **{key: value for key, value in raw_source.items() if key != "provider_config"},
        }
        self.source_id = spec.source_id
        try:
            self.low_watermark = max(int(raw_source.get("low_watermark") or 0), 0)
        except (TypeError, ValueError):
            self.low_watermark = 0
        self.state_store = getattr(state_repository, "store", state_repository)
        self._state_repository = state_repository
        self.runtime = runtime
        self._confirmation_reader = confirmation_reader
        self._telemetry = telemetry
        self._log_fn = log_fn
        self._state = AliasSourceState.IDLE

    @property
    def provider_type(self) -> str:
        return self.source_kind

    def state(self):
        return self._state

    def ensure_available(self, pool_manager, *, minimum_count: int = 1) -> None:
        requested = max(int(minimum_count or 0), 1)
        target_cap = max(
            int(self.source.get("alias_count") or self._spec.desired_alias_count or 0),
            1,
        )
        state = self._state_repository.load()
        known_aliases_before = list(dict.fromkeys(list(getattr(state, "known_aliases", []) or [])))
        created_alias_count = max(
            int(getattr(state, "created_alias_count", 0) or len(known_aliases_before)),
            len(known_aliases_before),
        )
        rotated_state = False
        if (
            bool(getattr(state, "exhausted", False))
            or created_alias_count >= target_cap
            or len(known_aliases_before) >= target_cap
        ):
            state = self._state_repository.new_state()
            known_aliases_before = []
            created_alias_count = 0
            rotated_state = True
        state.alias_limit = target_cap

        try:
            self._state = AliasSourceState.ACTIVE
            self._reset_run_state(state)
            if rotated_state:
                self._reset_runtime_session()
            self._ensure_session(state)
            remaining_capacity = max(target_cap - created_alias_count, 0)
            create_count = min(requested, remaining_capacity)
            alias_items = self._create_new_alias_items(
                state,
                create_count,
                existing_aliases=known_aliases_before,
            )
            state.last_capture_summary = self._capture_summary()
            state.known_aliases = list(
                dict.fromkeys(
                    [
                        str(email or "").strip().lower()
                        for email in known_aliases_before
                        if str(email or "").strip()
                    ]
                    + [
                        str(item.get("email") or "").strip().lower()
                        for item in alias_items
                        if str(item.get("email") or "").strip()
                    ]
                )
            )
            state.created_alias_count = max(created_alias_count + len(alias_items), len(state.known_aliases))
            state.alias_limit = target_cap
            state.exhausted = bool(state.created_alias_count >= target_cap)
            self._telemetry.record_stage(
                state,
                "aliases_ready",
                status="completed",
                detail=f"预览共 {len(alias_items)} 个别名",
            )
            state.last_failure = {"stageCode": "", "stageLabel": "", "reason": ""}
            state.last_error = ""
            self._telemetry.record_stage(state, "save_state", status="completed")
            self._state_repository.save(state)
            known_before_set = set(known_aliases_before)
            for item in alias_items:
                email = str(item.get("email") or "").strip().lower()
                if not email or email in known_before_set:
                    continue
                pool_manager.add_lease(
                    AliasEmailLease(
                        alias_email=email,
                        real_mailbox_email=str(getattr(state, "mailbox_email", "") or "").strip().lower(),
                        source_kind=self.source_kind,
                        source_id=self.source_id,
                        source_session_id=str(getattr(state, "state_key", "") or self._spec.state_key),
                    )
                )
            self._state = AliasSourceState.ACTIVE
        except Exception as exc:
            self._state = AliasSourceState.FAILED
            stage_code = self._telemetry.resolve_failure_stage_code(state)
            history = [
                item
                for item in list(getattr(state, "stage_history", []) or [])
                if isinstance(item, dict)
            ]
            if history and str(history[-1].get("code") or "") == stage_code:
                self._telemetry.update_stage_status(
                    state,
                    stage_code,
                    status="failed",
                    detail=str(exc),
                )
            else:
                self._telemetry.record_stage(
                    state,
                    stage_code,
                    status="failed",
                    detail=str(exc),
                )
            self._telemetry.record_failure(state, stage_code, str(exc), retryable=True)
            state.last_error = str(exc)
            try:
                state.last_capture_summary = self._capture_summary()
            except Exception:
                pass
            self._state_repository.save(state)
            raise

    def load_into(self, pool_manager) -> None:
        self.ensure_available(
            pool_manager,
            minimum_count=max(int(self.source.get("alias_count") or self._spec.desired_alias_count or 0), 1),
        )

    def run_alias_generation_test(self, policy: AliasAutomationTestPolicy):
        _state, alias_items, _error = self._execute_policy(policy=policy, raise_on_error=False)
        return self._telemetry.build_result(
            provider_type=self.provider_type,
            source_id=self.source_id,
            state=_state,
            aliases=alias_items,
            ok=not bool(_error),
            error=_error,
        )

    def _execute_policy(self, *, policy: AliasAutomationTestPolicy, raise_on_error: bool):
        state = None
        alias_items: list[dict[str, str]] = []
        try:
            self._state = AliasSourceState.ACTIVE
            fresh_service_account = bool(policy.fresh_service_account)
            state = self._state_repository.new_state() if fresh_service_account else self._state_repository.load()
            self._reset_run_state(state)
            if fresh_service_account:
                self._reset_runtime_session()
            self._ensure_session(state)
            alias_items = self._load_alias_items(state, policy.minimum_alias_count)
            if bool(policy.capture_enabled):
                state.last_capture_summary = self._capture_summary()
            else:
                state.last_capture_summary = []
            state.known_aliases = [str(item.get("email") or "").strip().lower() for item in alias_items if str(item.get("email") or "").strip()]
            self._telemetry.record_stage(
                state,
                "aliases_ready",
                status="completed",
                detail=f"预览共 {len(alias_items)} 个别名",
            )
            state.last_failure = {"stageCode": "", "stageLabel": "", "reason": ""}
            state.last_error = ""
            self._telemetry.record_stage(state, "save_state", status="completed")
            if bool(policy.persist_state):
                self._state_repository.save(state)
            self._state = AliasSourceState.EXHAUSTED
            return state, alias_items, ""
        except Exception as exc:
            self._state = AliasSourceState.FAILED
            if state is None:
                raise
            try:
                if bool(policy.capture_enabled):
                    state.last_capture_summary = self._capture_summary()
            except Exception:
                pass
            stage_code = self._telemetry.resolve_failure_stage_code(state)
            history = [item for item in list(getattr(state, "stage_history", []) or []) if isinstance(item, dict)]
            if history and str(history[-1].get("code") or "") == stage_code:
                self._telemetry.update_stage_status(state, stage_code, status="failed", detail=str(exc))
            else:
                self._telemetry.record_stage(state, stage_code, status="failed", detail=str(exc))
            self._telemetry.record_failure(state, stage_code, str(exc), retryable=True)
            state.last_error = str(exc)
            if bool(policy.persist_state):
                self._state_repository.save(state)
            if raise_on_error:
                raise
            return state, alias_items, str(exc)

    def _reset_run_state(self, state) -> None:
        state.stage_history = []
        state.current_stage = {"code": "", "label": ""}
        state.last_failure = {"stageCode": "", "stageLabel": "", "reason": ""}
        state.last_error = ""
        state.last_capture_summary = []

    def _reset_runtime_session(self) -> None:
        reset_session = getattr(self.runtime, "reset_session", None)
        if callable(reset_session):
            reset_session()

    def _configured_confirmation_inbox_email(self) -> str:
        inbox_config = dict(getattr(self._spec, "confirmation_inbox_config", {}) or {})
        configured_email = str(
            inbox_config.get("match_email")
            or inbox_config.get("account_email")
            or self.source.get("mailbox_email")
            or ""
        ).strip().lower()
        return configured_email

    def _ensure_session(self, state) -> None:
        current_service_email = str(getattr(state, "service_email", "") or "").strip().lower()
        if not current_service_email or not is_cloudmail_domain_email(current_service_email, self.source):
            state.service_email = build_service_email(self.source)
        current_mailbox_email = str(getattr(state, "mailbox_email", "") or "").strip().lower()
        configured_mailbox_email = self._configured_confirmation_inbox_email()
        if configured_mailbox_email:
            if current_mailbox_email != configured_mailbox_email:
                state.mailbox_email = configured_mailbox_email
        if not getattr(state, "service_password", ""):
            state.service_password = build_service_password()
        if self.runtime.restore_session(state):
            self._telemetry.record_stage(state, "session_ready", status="completed")
            return
        failure_details: list[str] = []
        if self.runtime.login(state, self.source):
            self._telemetry.record_stage(state, "session_ready", status="completed")
            return
        failure_details.append(self._capture_failure_detail("login", "login_form", "login"))
        if self.runtime.register(state, self.source):
            self._telemetry.record_stage(state, "register_submit", status="completed")
            confirmation_bootstrap_available = callable(getattr(self.runtime, "confirm", None))
            confirmation_bootstrap_error = self._attempt_confirmation_bootstrap(state)
            if confirmation_bootstrap_error is None:
                self._telemetry.record_stage(state, "session_ready", status="completed")
                self._log_service_account_registered(state)
                return
            if confirmation_bootstrap_available:
                raise confirmation_bootstrap_error
            if not self.runtime.resend_confirmation(state, self.source):
                raise self._bootstrap_error(
                    "vend.email confirmation bootstrap failed",
                    [self._capture_failure_detail("confirmation", "confirmation")],
                )
            if self.runtime.login(state, self.source):
                self._telemetry.record_stage(state, "session_ready", status="completed")
                self._log_service_account_registered(state)
                return
            raise self._bootstrap_error(
                "vend.email login failed after confirmation bootstrap",
                [self._capture_failure_detail("login", "login_form", "login")],
            )
        failure_details.append(self._capture_failure_detail("register", "register_form", "register"))
        raise self._bootstrap_error("vend.email session bootstrap failed", failure_details)

    def _log_service_account_registered(self, state) -> None:
        log_alias_service_account_registered(
            self._log_fn,
            provider_type="vend",
            email=str(getattr(state, "service_email", "") or ""),
            password=str(getattr(state, "service_password", "") or ""),
        )

    def _bootstrap_error(self, message: str, details: list[str]) -> RuntimeError:
        clean_details = list(dict.fromkeys(detail for detail in details if detail))
        if not clean_details:
            return RuntimeError(message)
        return RuntimeError(f"{message}: {'; '.join(clean_details)}")

    def _capture_failure_detail(self, label: str, *capture_names: str) -> str:
        try:
            records = self._capture_summary()
        except Exception as exc:
            return f"{label} failed (capture_summary unavailable: {exc})"

        wanted = {str(name or "").strip() for name in capture_names if str(name or "").strip()}
        matched_records = [
            record
            for record in records
            if str(getattr(record, "name", "") or "").strip() in wanted
        ]
        if not matched_records:
            return f"{label} failed"
        submitted_records = [
            record
            for record in matched_records
            if not str(getattr(record, "name", "") or "").strip().endswith("_form")
        ]
        if submitted_records:
            matched_records = submitted_records
        record_details = [
            self._format_capture_failure_detail(record)
            for record in matched_records[-1:]
        ]
        record_details = [detail for detail in record_details if detail]
        if not record_details:
            return f"{label} failed"
        return f"{label} failed ({'; '.join(record_details)})"

    def _format_capture_failure_detail(self, record: VendEmailCaptureRecord) -> str:
        parts = []
        name = str(getattr(record, "name", "") or "").strip()
        if name:
            parts.append(name)
        status = int(getattr(record, "response_status", 0) or 0)
        if status:
            parts.append(f"status={status}")
        response_body = self._capture_response_detail(
            str(getattr(record, "response_body_excerpt", "") or "")
        )
        if response_body:
            parts.append(f"body={response_body}")
        return " ".join(parts)

    def _capture_response_detail(self, value: str) -> str:
        html_failure_text = self._extract_html_failure_text(value)
        if html_failure_text:
            return self._compact_capture_detail(html_failure_text)
        return self._compact_capture_detail(value)

    def _extract_html_failure_text(self, value: str) -> str:
        raw = str(value or "")
        if "<" not in raw or ">" not in raw:
            return ""
        body = re.sub(r"<head\b[^>]*>.*?</head>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
        body = re.sub(r"<script\b[^>]*>.*?</script>", " ", body, flags=re.IGNORECASE | re.DOTALL)
        body = re.sub(r"<style\b[^>]*>.*?</style>", " ", body, flags=re.IGNORECASE | re.DOTALL)

        block_texts = []
        for match in _HTML_ERROR_BLOCK_PATTERN.finditer(body):
            text = self._html_to_text(match.group("body"))
            if text:
                block_texts.append(text)
        unique_block_texts = list(dict.fromkeys(block_texts))
        if unique_block_texts:
            return " | ".join(unique_block_texts[:3])

        plain_text = self._html_to_text(body)
        if not plain_text:
            return ""
        for line in re.split(r"[\r\n]+|(?<=[.!?])\s+", plain_text):
            candidate = line.strip()
            if not candidate:
                continue
            lowered = candidate.lower()
            if any(keyword in lowered for keyword in _HTML_FAILURE_KEYWORDS):
                return candidate
        return ""

    def _html_to_text(self, value: str) -> str:
        text = re.sub(r"<!--.*?-->", " ", str(value or ""), flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        return " ".join(unescape(text).split())

    def _compact_capture_detail(self, value: str) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= _CAPTURE_DETAIL_LIMIT:
            return text
        return text[: _CAPTURE_DETAIL_LIMIT - 3].rstrip() + "..."

    def _attempt_confirmation_bootstrap(self, state) -> Exception | None:
        confirm = getattr(self.runtime, "confirm", None)
        if not callable(confirm):
            return RuntimeError("vend.email confirmation bootstrap unavailable")
        try:
            self._telemetry.record_stage(state, "fetch_confirmation_mail", status="pending")
            confirmation_link = ""
            fetch_confirmation = getattr(self._confirmation_reader, "fetch_confirmation", None)
            if callable(fetch_confirmation):
                result = fetch_confirmation(state=state, source=self.source)
                if isinstance(result, ConfirmationReadResult):
                    if result.error:
                        raise RuntimeError(result.error)
                    confirmation_link = str(result.confirm_url or "").strip()
                elif isinstance(result, str):
                    confirmation_link = str(result or "").strip()
                else:
                    raw_confirm_url = getattr(result, "confirm_url", "")
                    confirmation_link = raw_confirm_url.strip() if isinstance(raw_confirm_url, str) else ""
                    raw_error = getattr(result, "error", "")
                    error = raw_error.strip() if isinstance(raw_error, str) else ""
                    if error:
                        raise RuntimeError(error)
            if not confirmation_link:
                fetch_confirmation_link = getattr(self.runtime, "fetch_confirmation_link", None)
                if callable(fetch_confirmation_link):
                    confirmation_link = str(fetch_confirmation_link(state, self.source) or "").strip()
            if not confirmation_link:
                error = RuntimeError("vend.email confirmation mail did not contain a confirmation link")
                self._telemetry.update_stage_status(
                    state,
                    "fetch_confirmation_mail",
                    status="failed",
                    detail=str(error),
                )
                return error
            self._telemetry.update_stage_status(state, "fetch_confirmation_mail", status="completed")
            self._telemetry.record_stage(state, "open_confirmation_link", status="pending")
            if not confirm(confirmation_link, self.source):
                error = RuntimeError("vend.email confirmation step returned unsuccessful result")
                self._telemetry.update_stage_status(
                    state,
                    "open_confirmation_link",
                    status="failed",
                    detail=str(error),
                )
                return error
            self._telemetry.update_stage_status(state, "open_confirmation_link", status="completed")
            if self.runtime.login(state, self.source):
                return None
            return RuntimeError("vend.email login failed after confirmation bootstrap")
        except Exception as exc:
            return exc

    def _load_alias_items(
        self,
        state,
        minimum_alias_count: int,
        *,
        target_alias_count: int | None = None,
    ) -> list[dict[str, str]]:
        if target_alias_count is None:
            target = max(
                int(self.source.get("alias_count") or self._spec.desired_alias_count or 0),
                int(minimum_alias_count or 0),
                0,
            )
        else:
            target = max(int(target_alias_count or 0), 0)
        self._telemetry.record_stage(state, "list_aliases", status="pending")
        aliases = list(self.runtime.list_aliases(state, self.source))
        missing_count = max(target - len(aliases), 0)
        existing_aliases_seen = set(aliases)
        created_alias_total = 0
        list_alias_detail = f"找到 {len(aliases)} 个别名"
        if missing_count:
            self._telemetry.update_stage_status(state, "list_aliases", status="completed", detail=list_alias_detail)
            self._telemetry.record_stage(state, "create_aliases", status="pending")
            initial_created_aliases = list(self.runtime.create_aliases(state, self.source, missing_count))
            aliases.extend(initial_created_aliases)
            for alias in initial_created_aliases:
                if alias in existing_aliases_seen:
                    continue
                existing_aliases_seen.add(alias)
                created_alias_total += 1
            self._telemetry.update_stage_status(
                state,
                "create_aliases",
                status="completed",
                detail=f"已补齐 {created_alias_total} 个别名",
            )
        else:
            self._telemetry.update_stage_status(state, "list_aliases", status="completed", detail=list_alias_detail)

        unique_aliases = []
        seen = set()
        for alias in aliases:
            if alias in seen:
                continue
            seen.add(alias)
            unique_aliases.append(alias)

        while len(unique_aliases) < target:
            remaining_missing_count = target - len(unique_aliases)
            created_aliases = list(self.runtime.create_aliases(state, self.source, remaining_missing_count))
            if not created_aliases:
                break
            for alias in created_aliases:
                if alias not in existing_aliases_seen:
                    existing_aliases_seen.add(alias)
                    created_alias_total += 1
                if alias in seen:
                    continue
                seen.add(alias)
                unique_aliases.append(alias)
            self._telemetry.update_stage_status(
                state,
                "create_aliases",
                status="completed",
                detail=f"已补齐 {created_alias_total} 个别名",
            )

        return [{"email": alias} for alias in unique_aliases[:target]]

    def _create_new_alias_items(
        self,
        state,
        requested_count: int,
        *,
        existing_aliases: list[str],
    ) -> list[dict[str, str]]:
        target = max(int(requested_count or 0), 0)
        if target <= 0:
            return []

        existing_seen = {
            str(alias or "").strip().lower()
            for alias in existing_aliases
            if str(alias or "").strip()
        }
        created_aliases: list[str] = []
        self._telemetry.record_stage(state, "create_aliases", status="pending")
        stalled_attempt_count = 0
        max_stalled_attempts = max(target, 1)
        while len(created_aliases) < target and stalled_attempt_count < max_stalled_attempts:
            missing_count = target - len(created_aliases)
            batch = list(self.runtime.create_aliases(state, self.source, missing_count))
            if not batch:
                break

            made_progress = False
            for alias in batch:
                email = str(alias or "").strip().lower()
                if not email or email in existing_seen:
                    continue
                existing_seen.add(email)
                created_aliases.append(email)
                made_progress = True

            if not made_progress:
                stalled_attempt_count += 1
                continue
            stalled_attempt_count = 0

        self._telemetry.update_stage_status(
            state,
            "create_aliases",
            status="completed",
            detail=f"created {len(created_aliases)} aliases",
        )
        return [{"email": alias} for alias in created_aliases[:target]]

    def _capture_summary(self) -> list[VendEmailCaptureRecord]:
        capture_summary = getattr(self.runtime, "capture_summary", None)
        if not callable(capture_summary):
            raise RuntimeError("vend.email runtime must define callable capture_summary()")
        typed_capture_summary = cast(Any, capture_summary)
        records = []
        for item in typed_capture_summary():
            if isinstance(item, VendEmailCaptureRecord):
                records.append(item)
            elif isinstance(item, dict):
                records.append(VendEmailCaptureRecord.from_dict(item))
            else:
                raise RuntimeError(
                    "vend.email runtime capture_summary() must return VendEmailCaptureRecord items"
                )
        return records
