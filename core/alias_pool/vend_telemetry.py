from __future__ import annotations

from typing import Any

from core.alias_pool.provider_contracts import (
    AliasAccountIdentity,
    AliasAutomationTestResult,
    AliasProviderCapture,
    AliasProviderFailure,
    AliasProviderStage,
)


class VendTelemetryRecorder:
    _STAGE_LABELS = {
        "session_ready": "会话已就绪",
        "register_submit": "注册表单提交",
        "fetch_confirmation_mail": "查找确认邮件",
        "open_confirmation_link": "打开确认链接",
        "list_aliases": "列出现有别名",
        "create_aliases": "创建别名",
        "aliases_ready": "别名预览已生成",
        "save_state": "保存预览状态",
    }

    def stage_label(self, code: str) -> str:
        return self._STAGE_LABELS.get(str(code or ""), str(code or ""))

    def record_stage(self, state, name: str, *, status: str, **extras) -> None:
        stage_entry = {
            "code": str(name or ""),
            "label": self.stage_label(name),
            "status": str(status or ""),
        }
        for key, value in extras.items():
            if value is None or value == "":
                continue
            if key == "detail":
                stage_entry["detail"] = str(value)
            else:
                stage_entry[str(key)] = value
        if stage_entry["code"] != "save_state":
            state.current_stage = {
                "code": stage_entry["code"],
                "label": stage_entry["label"],
            }
        state.stage_history = list(getattr(state, "stage_history", []) or []) + [stage_entry]

    def update_stage_status(
        self,
        state,
        code: str,
        *,
        status: str,
        detail: str = "",
        update_current: bool = True,
    ) -> None:
        updated_history = []
        for entry in list(getattr(state, "stage_history", []) or []):
            if isinstance(entry, dict) and str(entry.get("code") or "") == str(code or ""):
                updated_entry = dict(entry)
                updated_entry["status"] = status
                if detail:
                    updated_entry["detail"] = detail
                updated_history.append(updated_entry)
            else:
                updated_history.append(entry)
        state.stage_history = updated_history
        if update_current:
            state.current_stage = {
                "code": str(code or ""),
                "label": self.stage_label(code),
            }

    def record_failure(
        self,
        state,
        stage: str,
        reason: str,
        *,
        retryable: bool | None = None,
    ) -> None:
        state.current_stage = {
            "code": str(stage or ""),
            "label": self.stage_label(stage),
        }
        failure: dict[str, Any] = {
            "stageCode": str(stage or ""),
            "stageLabel": self.stage_label(stage),
            "reason": str(reason or ""),
        }
        if retryable is not None:
            failure["retryable"] = bool(retryable)
        state.last_failure = failure

    def resolve_failure_stage_code(self, state) -> str:
        history = [item for item in list(getattr(state, "stage_history", []) or []) if isinstance(item, dict)]
        if history:
            last_code = str(history[-1].get("code") or "")
            if last_code in {"fetch_confirmation_mail", "register_submit", "list_aliases", "create_aliases", "save_state"}:
                return last_code
            if last_code == "open_confirmation_link":
                return "open_confirmation_link"
        codes = {str(item.get("code") or "") for item in history}
        if "register_submit" in codes and "open_confirmation_link" not in codes:
            return "fetch_confirmation_mail"
        if "list_aliases" in codes and "create_aliases" not in codes:
            return "list_aliases"
        return "session_ready"

    def build_result(
        self,
        *,
        provider_type: str,
        source_id: str,
        state,
        aliases: list[dict],
        ok: bool,
        error: str = "",
    ) -> AliasAutomationTestResult:
        current_stage_payload = getattr(state, "current_stage", {}) or {}
        current_stage = AliasProviderStage(
            code=str(current_stage_payload.get("code") or ""),
            label=str(current_stage_payload.get("label") or ""),
            status="completed" if ok else "failed" if str(current_stage_payload.get("code") or "") else "",
        ) if current_stage_payload else None

        stage_timeline = [
            AliasProviderStage(
                code=str(item.get("code") or ""),
                label=str(item.get("label") or ""),
                status=str(item.get("status") or ""),
                detail=str(item.get("detail") or ""),
            )
            for item in list(getattr(state, "stage_history", []) or [])
            if isinstance(item, dict)
        ]
        failure_payload = getattr(state, "last_failure", {}) or {}
        failure = AliasProviderFailure(
            stage_code=str(failure_payload.get("stageCode") or ""),
            stage_label=str(failure_payload.get("stageLabel") or ""),
            reason=str(failure_payload.get("reason") or ""),
            retryable=failure_payload.get("retryable") if "retryable" in failure_payload else None,
        )
        captures = [
            AliasProviderCapture(
                kind=str(getattr(item, "name", "") or ""),
                request_summary={
                    "method": str(getattr(item, "method", "") or ""),
                    "url": str(getattr(item, "url", "") or ""),
                    "request_headers_whitelist": dict(getattr(item, "request_headers_whitelist", {}) or {}),
                    "request_body_excerpt": str(getattr(item, "request_body_excerpt", "") or ""),
                },
                response_summary={
                    "response_status": int(getattr(item, "response_status", 0) or 0),
                    "response_body_excerpt": str(getattr(item, "response_body_excerpt", "") or ""),
                    "captured_at": str(getattr(item, "captured_at", "") or ""),
                },
                redaction_applied=False,
            )
            for item in list(getattr(state, "last_capture_summary", []) or [])
        ]
        service_email = str(getattr(state, "service_email", "") or "")
        account_identity = AliasAccountIdentity(
            service_account_email=service_email,
            confirmation_inbox_email=str(getattr(state, "mailbox_email", "") or ""),
            real_mailbox_email=str(getattr(state, "mailbox_email", "") or ""),
            service_password=str(getattr(state, "service_password", "") or ""),
            username=service_email.split("@", 1)[0] if "@" in service_email else "",
        )
        return AliasAutomationTestResult(
            provider_type=provider_type,
            source_id=source_id,
            account_identity=account_identity,
            aliases=list(aliases),
            current_stage=current_stage,
            stage_timeline=stage_timeline,
            failure=failure,
            capture_summary=captures,
            logs=[],
            ok=ok,
            error=str(error or ""),
        )
