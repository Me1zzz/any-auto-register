from fastapi import APIRouter, HTTPException
import re
from pydantic import BaseModel, Field
from core.alias_pool.automation_test import AliasAutomationTestService
from core.alias_pool.browser_fallback_runtime import BrowserFallbackRuntime
from core.alias_pool.config import (
    decode_alias_provider_sources,
    encode_alias_provider_sources,
    normalize_cloudmail_alias_pool_config,
)
from core.alias_pool.protocol_site_runtime import ProtocolSiteRuntime
from core.alias_pool.provider_contracts import AliasAutomationTestPolicy, AliasProviderBootstrapContext
from core.alias_pool.probe import AliasSourceProbeService
from core.config_store import config_store
from services.mail_imports import MailImportExecuteRequest, MailImportSnapshotRequest, mail_import_registry

router = APIRouter(prefix="/config", tags=["config"])


def _default_alias_test_runtime_builder(_source: dict):
    source = dict(_source or {})
    if str(source.get("type") or "").strip().lower() in {"myalias_pro", "emailshield"}:
        return ProtocolSiteRuntime(), None
    return ProtocolSiteRuntime(), BrowserFallbackRuntime(headless=False)

CONFIG_KEYS = [
    "laoudo_auth",
    "laoudo_email",
    "laoudo_account_id",
    "yescaptcha_key",
    "twocaptcha_key",
    "default_executor",
    "default_captcha_solver",
    "duckmail_api_url",
    "duckmail_provider_url",
    "duckmail_bearer",
    "duckmail_domain",
    "duckmail_api_key",
    "freemail_api_url",
    "freemail_admin_token",
    "freemail_username",
    "freemail_password",
    "freemail_domain",
    "moemail_api_url",
    "moemail_api_key",
    "skymail_api_base",
    "skymail_token",
    "skymail_domain",
    "cloudmail_api_base",
    "cloudmail_admin_email",
    "cloudmail_admin_password",
    "cloudmail_domain",
    "cloudmail_subdomain",
    "cloudmail_alias_enabled",
    "cloudmail_alias_emails",
    "cloudmail_alias_service_static_enabled",
    "cloudmail_alias_service_simple_enabled",
    "cloudmail_alias_service_simple_prefix",
    "cloudmail_alias_service_simple_suffix",
    "cloudmail_alias_service_simple_count",
    "cloudmail_alias_service_simple_middle_length_min",
    "cloudmail_alias_service_simple_middle_length_max",
    "cloudmail_alias_service_vend_enabled",
    "cloudmail_alias_service_vend_source_id",
    "cloudmail_alias_service_vend_alias_count",
    "cloudmail_alias_service_vend_state_key",
    "cloudmail_team_account_email",
    "cloudmail_team_account_password",
    "cloudmail_team_otp_mailbox_email",
    "sources",
    "cloudmail_timeout",
    "mail_provider",
    "outlook_backend",
    "mailbox_otp_timeout_seconds",
    "maliapi_base_url",
    "maliapi_api_key",
    "maliapi_domain",
    "maliapi_auto_domain_strategy",
    "applemail_base_url",
    "applemail_pool_dir",
    "applemail_pool_file",
    "applemail_mailboxes",
    "gptmail_base_url",
    "gptmail_api_key",
    "gptmail_domain",
    "guerrillamail_api_url",
    "opentrashmail_api_url",
    "opentrashmail_domain",
    "opentrashmail_password",
    "cfworker_api_url",
    "cfworker_admin_token",
    "cfworker_custom_auth",
    "cfworker_domain",
    "cfworker_domains",
    "cfworker_enabled_domains",
    "cfworker_subdomain",
    "cfworker_random_subdomain",
    "cfworker_random_name_subdomain",
    "cfworker_fingerprint",
    "smstome_cookie",
    "smstome_country_slugs",
    "smstome_phone_attempts",
    "smstome_otp_timeout_seconds",
    "smstome_poll_interval_seconds",
    "smstome_sync_max_pages_per_country",
    "luckmail_base_url",
    "luckmail_api_key",
    "luckmail_email_type",
    "luckmail_domain",
    "cpa_enabled",
    "cpa_api_url",
    "cpa_api_key",
    "cpa_cleanup_enabled",
    "cpa_cleanup_interval_minutes",
    "cpa_cleanup_threshold",
    "cpa_cleanup_concurrency",
    "cpa_cleanup_register_delay_seconds",
    "sub2api_enabled",
    "sub2api_api_url",
    "sub2api_api_key",
    "sub2api_group_ids",
    "team_manager_url",
    "team_manager_key",
    "codex_proxy_url",
    "codex_proxy_key",
    "codex_proxy_upload_type",
    "codex_gui_target_detector",
    "codex_gui_edge_user_data_dir",
    "codex_gui_edge_profile_directory",
    "cliproxyapi_base_url",
    "cliproxyapi_management_key",
    "grok2api_url",
    "grok2api_app_key",
    "grok2api_pool",
    "grok2api_quota",
    "kiro_manager_path",
    "kiro_manager_exe",
    "contribution_enabled",
    "contribution_server_url",
    "contribution_key",
]

WRITE_ONLY_CONFIG_KEYS = {
    "cloudmail_admin_password",
    "cloudmail_team_account_password",
}


class ConfigUpdate(BaseModel):
    data: dict


class AppleMailImportRequest(BaseModel):
    content: str
    filename: str = ""
    pool_dir: str = ""
    bind_to_config: bool = True


class AliasGenerationTestRequest(BaseModel):
    sourceId: str
    useDraftConfig: bool = False
    config: dict = Field(default_factory=dict)


def _decode_config_value(key: str, value):
    if key in WRITE_ONLY_CONFIG_KEYS:
        return ""
    if key != "sources":
        return value
    return decode_alias_provider_sources(value)


def _encode_config_value(key: str, value):
    if key != "sources":
        return value
    return encode_alias_provider_sources(value)


_SENSITIVE_QUERY_PATTERNS = [
    re.compile(r"((?:user\[)?password(?:\])?=)([^&\s]+)", re.IGNORECASE),
    re.compile(r"((?:token|authorization)=)([^&\s]+)", re.IGNORECASE),
    re.compile(r"(([A-Za-z0-9_\-]*token[A-Za-z0-9_\-]*=))([^&\s]+)", re.IGNORECASE),
    re.compile(r"(([A-Za-z0-9_\-]*code[A-Za-z0-9_\-]*=))([^&\s]+)", re.IGNORECASE),
]


def _redact_sensitive_text(value):
    text = str(value or "")
    if not text:
        return ""
    redacted = text
    for pattern in _SENSITIVE_QUERY_PATTERNS:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    return redacted


def _sanitize_capture_summary(items):
    sanitized = []
    for item in list(items or []):
        if not isinstance(item, dict):
            continue
        capture_name = str(item.get("kind") or item.get("name") or "").strip().lower()
        raw_request_summary = item.get("requestSummary") or item.get("request_summary")
        raw_response_summary = item.get("responseSummary") or item.get("response_summary")
        has_legacy_request_fields = any(
            key in item for key in ("method", "url", "request_headers_whitelist", "request_body_excerpt")
        )
        has_legacy_response_fields = any(
            key in item for key in ("response_status", "response_body_excerpt", "captured_at")
        )
        if isinstance(raw_request_summary, dict):
            request_summary = {
                "method": _redact_sensitive_text(raw_request_summary.get("method")),
                "url": _redact_sensitive_text(raw_request_summary.get("url")),
                "request_headers_whitelist": dict(raw_request_summary.get("request_headers_whitelist") or {}),
                "request_body_excerpt": _redact_sensitive_text(raw_request_summary.get("request_body_excerpt")),
            }
        elif has_legacy_request_fields:
            request_summary = {
                "method": _redact_sensitive_text(item.get("method")),
                "url": _redact_sensitive_text(item.get("url")),
                "request_headers_whitelist": dict(item.get("request_headers_whitelist") or {}),
                "request_body_excerpt": _redact_sensitive_text(item.get("request_body_excerpt")),
            }
        else:
            request_summary = _redact_sensitive_text(raw_request_summary or item.get("request_body_excerpt"))
        if isinstance(raw_response_summary, dict):
            response_summary = {
                "response_status": int(raw_response_summary.get("response_status") or 0),
                "response_body_excerpt": _redact_sensitive_text(raw_response_summary.get("response_body_excerpt")),
                "captured_at": _redact_sensitive_text(raw_response_summary.get("captured_at")),
            }
        elif has_legacy_response_fields:
            response_summary = {
                "response_status": int(item.get("response_status") or 0),
                "response_body_excerpt": _redact_sensitive_text(item.get("response_body_excerpt")),
                "captured_at": _redact_sensitive_text(item.get("captured_at")),
            }
        else:
            response_summary = _redact_sensitive_text(raw_response_summary or item.get("response_body_excerpt"))
        if capture_name == "mailbox_verification":
            request_summary = "mailbox verification request"
            response_summary = "mailbox verification result"
            request_body_excerpt = "mailbox verification request"
            response_body_excerpt = "mailbox verification result"
        else:
            request_body_excerpt = _redact_sensitive_text(item.get("request_body_excerpt"))
            response_body_excerpt = _redact_sensitive_text(item.get("response_body_excerpt"))
        sanitized.append(
            {
                **item,
                "kind": capture_name,
                "name": str(item.get("name") or item.get("kind") or ""),
                "url": _redact_sensitive_text(item.get("url")),
                "requestSummary": request_summary,
                "responseSummary": response_summary,
                "redactionApplied": bool(item.get("redactionApplied") or item.get("redaction_applied") or capture_name == "mailbox_verification"),
                "request_body_excerpt": request_body_excerpt,
                "response_body_excerpt": response_body_excerpt,
                "request_summary": request_summary,
                "response_summary": response_summary,
            }
        )
    return sanitized


@router.get("")
def get_config():
    all_cfg = config_store.get_all()
    if all_cfg.get("mail_provider") == "outlook":
        all_cfg["mail_provider"] = "microsoft"
    if not all_cfg.get("mail_provider"):
        all_cfg["mail_provider"] = "cloudmail"
    if not all_cfg.get("applemail_base_url"):
        all_cfg["applemail_base_url"] = "https://www.appleemail.top"
    if not all_cfg.get("applemail_pool_dir"):
        all_cfg["applemail_pool_dir"] = "mail"
    if not all_cfg.get("applemail_mailboxes"):
        all_cfg["applemail_mailboxes"] = "INBOX,Junk"
    if not all_cfg.get("outlook_backend"):
        all_cfg["outlook_backend"] = "graph"
    if not all_cfg.get("gptmail_base_url"):
        all_cfg["gptmail_base_url"] = "https://mail.chatgpt.org.uk"
    if not all_cfg.get("guerrillamail_api_url"):
        all_cfg["guerrillamail_api_url"] = "https://api.guerrillamail.com/ajax.php"
    if not all_cfg.get("luckmail_base_url"):
        all_cfg["luckmail_base_url"] = "https://mails.luckyous.com/"
    if not str(all_cfg.get("contribution_enabled", "") or "").strip():
        all_cfg["contribution_enabled"] = "0"
    if not all_cfg.get("contribution_server_url"):
        all_cfg["contribution_server_url"] = "http://new.xem8k5.top:7317/"
    # 只返回已知 key，未设置的返回空字符串
    return {k: _decode_config_value(k, all_cfg.get(k, "")) for k in CONFIG_KEYS}


@router.put("")
def update_config(body: ConfigUpdate):
    # 只允许更新已知 key
    safe = {k: v for k, v in body.data.items() if k in CONFIG_KEYS}
    if safe.get("mail_provider") == "outlook":
        safe["mail_provider"] = "microsoft"
    for key in list(safe.keys()):
        if key in WRITE_ONLY_CONFIG_KEYS and str(safe.get(key) or "") == "":
            safe.pop(key, None)
    safe = {k: _encode_config_value(k, v) for k, v in safe.items()}
    config_store.set_many(safe)
    return {"ok": True, "updated": list(safe.keys())}


@router.post("/alias-test")
def alias_generation_test(body: AliasGenerationTestRequest):
    merged = config_store.get_all().copy()
    if body.useDraftConfig:
        draft_config = dict(body.config or {})
        for key in list(draft_config.keys()):
            if key in WRITE_ONLY_CONFIG_KEYS and str(draft_config.get(key) or "") == "":
                draft_config.pop(key, None)
        if "sources" not in draft_config and any(
            key in draft_config
            for key in (
                "cloudmail_alias_enabled",
                "cloudmail_alias_emails",
            )
        ):
            draft_config["sources"] = []
        merged.update(draft_config)

    pool_config = normalize_cloudmail_alias_pool_config(merged, task_id="alias-test")
    runtime_builder = None
    for source in list(pool_config.get("sources") or []):
        if str(source.get("id") or "") != body.sourceId:
            continue
        if str(source.get("type") or "").strip().lower() == "myalias_pro":
            runtime_builder = _default_alias_test_runtime_builder
        break

    policy = AliasAutomationTestPolicy(
        fresh_service_account=True,
        persist_state=False,
        minimum_alias_count=3,
        capture_enabled=True,
    )
    context = AliasProviderBootstrapContext(
        task_id="alias-test",
        purpose="automation_test",
        runtime_builder=runtime_builder,
        test_policy=policy,
    )

    result = AliasAutomationTestService(policy=policy, context=context).run(
        pool_config=pool_config,
        source_id=body.sourceId,
        task_id="alias-test",
    )
    aliases = list(result.aliases or [])
    compatibility_alias_email = result.alias_email
    if aliases and isinstance(aliases[0], dict):
        compatibility_alias_email = str(
            aliases[0].get("email")
            or aliases[0].get("aliasEmail")
            or compatibility_alias_email
            or ""
        )
    return {
        "ok": result.ok,
        "sourceId": result.source_id,
        "sourceType": result.source_type,
        "aliasEmail": compatibility_alias_email,
        "realMailboxEmail": result.real_mailbox_email,
        "serviceEmail": result.service_email,
        "accountIdentity": {
            "serviceAccountEmail": str(result.service_email or result.account.get("serviceEmail") or ""),
            "confirmationInboxEmail": str(result.real_mailbox_email or result.account.get("realMailboxEmail") or ""),
            "realMailboxEmail": str(result.real_mailbox_email or result.account.get("realMailboxEmail") or ""),
            "servicePassword": str(result.account.get("password") or result.account.get("servicePassword") or ""),
            "username": str(result.account.get("username") or result.account.get("userName") or ""),
        },
        "account": dict(result.account or {}),
        "aliases": aliases,
        "currentStage": result.current_stage,
        "stages": list(result.stages or []),
        "failure": dict(result.failure or {"stage": "", "reason": ""}),
        "captureSummary": _sanitize_capture_summary(result.capture_summary),
        "steps": result.steps,
        "logs": result.logs,
        "error": result.error,
    }


@router.post("/applemail/import")
def import_applemail_pool(body: AppleMailImportRequest):
    try:
        strategy = mail_import_registry.get("applemail")
        result = strategy.execute(
            MailImportExecuteRequest(
                type="applemail",
                content=body.content,
                filename=body.filename,
                pool_dir=body.pool_dir,
                bind_to_config=body.bind_to_config,
            )
        )
        snapshot = result.snapshot.model_dump()
        return {
            "filename": snapshot["filename"],
            "path": result.meta.get("path", ""),
            "count": snapshot["count"],
            "pool_dir": snapshot["pool_dir"],
            "bound_to_config": bool(result.meta.get("bound_to_config")),
            "items": snapshot["items"],
            "truncated": snapshot["truncated"],
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/applemail/pool")
def get_applemail_pool_snapshot(
    pool_dir: str = "",
    pool_file: str = "",
):
    try:
        strategy = mail_import_registry.get("applemail")
        snapshot = strategy.get_snapshot(
            MailImportSnapshotRequest(
                type="applemail",
                pool_dir=pool_dir,
                pool_file=pool_file,
            )
        )
        return snapshot.model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
