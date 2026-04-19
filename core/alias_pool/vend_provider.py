from __future__ import annotations

import secrets
from typing import Any, cast

from core.alias_pool.base import AliasEmailLease, AliasSourceState
from core.base_mailbox import CloudMailMailbox
from core.alias_pool.provider_contracts import AliasAutomationTestPolicy
from core.alias_pool.vend_confirmation import ConfirmationReadResult
from core.alias_pool.vend_email_state import VendEmailCaptureRecord


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
    expected_domain = str(source.get("cloudmail_domain") or "").strip().lower()
    if not expected_domain:
        return bool(email)
    return email.endswith(f"@{expected_domain}")


class VendAliasProvider:
    source_kind = "vend_email"

    def __init__(self, *, spec, state_repository, runtime, confirmation_reader, telemetry):
        self._spec = spec
        provider_config = dict(getattr(spec, "provider_config", {}) or {})
        raw_source = dict(spec.raw_source or {})
        self.source = {
            **{key: value for key, value in raw_source.items() if key != "provider_config"},
            **provider_config,
        }
        self.source_id = spec.source_id
        self.state_store = getattr(state_repository, "store", state_repository)
        self._state_repository = state_repository
        self.runtime = runtime
        self._confirmation_reader = confirmation_reader
        self._telemetry = telemetry
        self._state = AliasSourceState.IDLE

    @property
    def provider_type(self) -> str:
        return self.source_kind

    def state(self):
        return self._state

    def load_into(self, pool_manager) -> None:
        policy = AliasAutomationTestPolicy(
            fresh_service_account=False,
            persist_state=True,
            minimum_alias_count=max(int(self.source.get("alias_count") or self._spec.desired_alias_count or 0), 0),
            capture_enabled=True,
        )
        state, alias_items, error = self._execute_policy(policy=policy, raise_on_error=True)
        for alias in alias_items:
            pool_manager.add_lease(
                AliasEmailLease(
                    alias_email=str(alias.get("email") or ""),
                    real_mailbox_email=str(getattr(state, "mailbox_email", "") or "").strip().lower(),
                    source_kind=self.source_kind,
                    source_id=self.source_id,
                    source_session_id=str(getattr(state, "state_key", "") or self._spec.state_key),
                )
            )
        if error:
            raise RuntimeError(error)

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
            state = self._state_repository.new_state() if bool(policy.fresh_service_account) else self._state_repository.load()
            self._reset_run_state(state)
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
        if self.runtime.login(state, self.source):
            self._telemetry.record_stage(state, "session_ready", status="completed")
            return
        if self.runtime.register(state, self.source):
            self._telemetry.record_stage(state, "register_submit", status="completed")
            confirmation_bootstrap_available = callable(getattr(self.runtime, "confirm", None))
            confirmation_bootstrap_error = self._attempt_confirmation_bootstrap(state)
            if confirmation_bootstrap_error is None:
                self._telemetry.record_stage(state, "session_ready", status="completed")
                return
            if confirmation_bootstrap_available:
                raise confirmation_bootstrap_error
            if not self.runtime.resend_confirmation(state, self.source):
                raise RuntimeError("vend.email confirmation bootstrap failed")
            if self.runtime.login(state, self.source):
                self._telemetry.record_stage(state, "session_ready", status="completed")
                return
        raise RuntimeError("vend.email session bootstrap failed")

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

    def _load_alias_items(self, state, minimum_alias_count: int) -> list[dict[str, str]]:
        target = max(
            int(self.source.get("alias_count") or self._spec.desired_alias_count or 0),
            int(minimum_alias_count or 0),
            0,
        )
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
