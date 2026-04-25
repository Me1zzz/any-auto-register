"""ChatGPT Team workspace invite/remove helpers.

This module intentionally exposes small function-level APIs so task
orchestration can call Team operations without depending on a FastAPI route.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from core.base_mailbox import CloudMailMailbox, MailboxAccount
from core.config_store import config_store
from core.proxy_utils import build_requests_proxy_config

from .oauth_client import OAuthClient

try:
    from curl_cffi import requests as cffi_requests
except ImportError:  # pragma: no cover - dependency fallback
    import requests as cffi_requests


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CHATGPT_ACCOUNTS_CHECK_URL = "https://chatgpt.com/backend-api/accounts/check/v4-2023-04-27"
TEAM_SESSION_TTL_SECONDS = 20 * 60

_SESSION_CACHE_LOCK = threading.Lock()
_SESSION_CACHE: dict[str, tuple["TeamWorkspaceSession", float]] = {}


@dataclass(slots=True)
class ChatGPTTeamWorkspaceResult:
    success: bool
    action: str
    workspace_id: str
    member_email: str
    attempts: int = 1
    detail: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def as_metadata(self, prefix: str) -> dict[str, Any]:
        return {
            f"{prefix}_success": self.success,
            f"{prefix}_action": self.action,
            f"{prefix}_workspace_id": self.workspace_id,
            f"{prefix}_member_email": self.member_email,
            f"{prefix}_attempts": self.attempts,
            f"{prefix}_detail": self.detail,
            f"{prefix}_payload": dict(self.payload),
        }


@dataclass
class TeamWorkspaceSession:
    email: str
    access_token: str
    workspace_id: str = ""
    refresh_token: str = ""
    session_token: str = ""
    account_id: str = ""


class TeamWorkspaceEmailService:
    """Email service adapter for passwordless ChatGPT login via CloudMail."""

    service_type = type("ST", (), {"value": "cloudmail"})()

    def __init__(
        self,
        mailbox: CloudMailMailbox,
        team_email: str,
        mailbox_email: str,
        timeout_seconds: int,
    ):
        self.mailbox = mailbox
        self.team_email = _normalize_email(team_email)
        self.mailbox_email = str(mailbox_email or "").strip()
        self.timeout_seconds = max(30, int(timeout_seconds or 600))
        self._acct: MailboxAccount | None = None
        self._before_ids: set[str] = set()
        self._used_codes: set[str] = set()
        self._used_message_ids: set[str] = set()
        self._last_code = ""
        self._last_code_at = 0.0
        self._last_success_code = ""
        self._last_success_code_at = 0.0
        self._last_message_id = ""
        self._cloudmail_message_dedupe = True

    @property
    def uses_cloudmail_message_dedupe(self) -> bool:
        return True

    def create_email(self, config=None) -> dict[str, str]:
        if not self._acct:
            self._acct = MailboxAccount(
                email=self.team_email,
                account_id=self.mailbox_email,
                extra={
                    "mailbox_alias": {
                        "enabled": True,
                        "alias_email": self.team_email,
                        "mailbox_email": self.mailbox_email,
                    }
                },
            )
            get_current_ids = getattr(self.mailbox, "get_current_ids", None)
            if callable(get_current_ids):
                self._before_ids = set(get_current_ids(self._acct) or [])
        return {"email": self.team_email, "service_id": self.mailbox_email, "token": ""}

    def remember_successful_code(self, code: str) -> None:
        code = str(code or "").strip()
        if not code:
            return
        self._last_success_code = code
        self._last_success_code_at = time.time()
        self._used_codes.add(code)
        message_id = str(getattr(self.mailbox, "_last_matched_message_id", "") or "").strip()
        if message_id:
            self._used_message_ids.add(message_id)
            self._last_message_id = message_id

    def get_recent_code(self, max_age_seconds: int = 180, *, prefer_successful: bool = True) -> str:
        _ = prefer_successful
        if self._last_success_code and time.time() - self._last_success_code_at <= max_age_seconds:
            return self._last_success_code
        if self._last_code and time.time() - self._last_code_at <= max_age_seconds:
            return self._last_code
        return ""

    def wait_for_verification_code(
        self,
        email: str,
        timeout: int = 90,
        otp_sent_at: float | None = None,
        exclude_codes=None,
    ) -> str:
        code = self.get_verification_code(
            email=email,
            timeout=timeout,
            otp_sent_at=otp_sent_at,
            exclude_codes=exclude_codes,
        )
        if code:
            self._last_code = str(code).strip()
            self._last_code_at = time.time()
        return code

    def get_verification_code(
        self,
        email=None,
        email_id=None,
        timeout=120,
        pattern=None,
        otp_sent_at=None,
        exclude_codes=None,
    ) -> str:
        _ = email_id, pattern
        if not self._acct:
            self.create_email()
        if not self._acct:
            raise RuntimeError("CloudMail team mailbox account was not initialized")
        code = self.mailbox.wait_for_code(
            self._acct,
            keyword="",
            timeout=max(int(timeout or 0), self.timeout_seconds),
            before_ids=self._before_ids,
            otp_sent_at=otp_sent_at,
            exclude_codes=set(exclude_codes or set()),
        )
        self._last_message_id = str(getattr(self.mailbox, "_last_matched_message_id", "") or "").strip()
        if code:
            self._used_codes.add(str(code).strip())
            if self._last_message_id:
                self._used_message_ids.add(self._last_message_id)
        return str(code or "").strip()

    def update_status(self, success, error=None):
        return None

    @property
    def status(self):
        return None


def team_account_identifier(team_account: dict[str, Any] | None) -> str:
    team_account = team_account or {}
    return str(
        team_account.get("email")
        or team_account.get("username")
        or team_account.get("id")
        or team_account.get("account_id")
        or ""
    ).strip()


def build_cleanup_compensation_context(
    *,
    member_email: str,
    workspace_id: str,
    team_account: dict[str, Any] | None,
    failure_detail: str,
) -> dict[str, Any]:
    return {
        "member_email": str(member_email or "").strip(),
        "workspace_id": str(workspace_id or "").strip(),
        "team_account_identifier": team_account_identifier(team_account),
        "failure_detail": str(failure_detail or "").strip(),
        "compensation_strategy": "switch_team_account_cleanup",
        "compensation_executed": False,
    }


def ensure_team_workspace_config(
    *,
    member_email: str,
    workspace_id: str,
    team_account: dict[str, Any] | None,
    require_workspace_id: bool = True,
) -> None:
    if not str(member_email or "").strip():
        raise ValueError("缺少待管理的 Team 成员邮箱")
    if require_workspace_id and not str(workspace_id or "").strip():
        raise ValueError("缺少 ChatGPT Team 工作空间 ID")
    if not team_account_identifier(team_account):
        raise ValueError("缺少 ChatGPT Team 会员账号标识")


def invite_chatgpt_team_member(
    *,
    member_email: str,
    workspace_id: str,
    team_account: dict[str, Any] | None,
    inviter: Callable[..., ChatGPTTeamWorkspaceResult] | None = None,
    logger: Callable[[str], None] | None = None,
    proxy_url: str | None = None,
    log_fn: Callable[[str], None] | None = None,
    **kwargs,
) -> ChatGPTTeamWorkspaceResult:
    ensure_team_workspace_config(
        member_email=member_email,
        workspace_id=workspace_id,
        team_account=team_account,
        require_workspace_id=inviter is not None,
    )
    try:
        if inviter is not None:
            raw_result = inviter(
                member_email=member_email,
                workspace_id=workspace_id,
                team_account=team_account,
                **kwargs,
            )
        else:
            raw_result = _invite_chatgpt_team_member_via_cloudmail(
                member_email=member_email,
                workspace_id=workspace_id,
                team_account=team_account,
                proxy_url=proxy_url,
                log_fn=log_fn or logger,
            )
        return _coerce_workspace_result(
            raw_result,
            action="invite",
            member_email=member_email,
            workspace_id=workspace_id,
        )
    except Exception as exc:
        detail = str(exc) or "team_workspace_invite_failed"
        if logger:
            logger(f"[TeamWorkspace] invite failed: {member_email} -> {workspace_id}: {detail}")
        return ChatGPTTeamWorkspaceResult(
            success=False,
            action="invite",
            workspace_id=str(workspace_id or "").strip(),
            member_email=str(member_email or "").strip(),
            attempts=1,
            detail=detail,
            payload={"error": detail},
        )


def remove_chatgpt_team_member(
    *,
    member_email: str,
    workspace_id: str,
    team_account: dict[str, Any] | None,
    remover: Callable[..., ChatGPTTeamWorkspaceResult] | None = None,
    logger: Callable[[str], None] | None = None,
    proxy_url: str | None = None,
    log_fn: Callable[[str], None] | None = None,
    **kwargs,
) -> ChatGPTTeamWorkspaceResult:
    ensure_team_workspace_config(
        member_email=member_email,
        workspace_id=workspace_id,
        team_account=team_account,
        require_workspace_id=remover is not None,
    )
    try:
        if remover is not None:
            raw_result = remover(
                member_email=member_email,
                workspace_id=workspace_id,
                team_account=team_account,
                **kwargs,
            )
        else:
            raw_result = _remove_chatgpt_team_member_via_cloudmail(
                member_email=member_email,
                workspace_id=workspace_id,
                team_account=team_account,
                proxy_url=proxy_url,
                log_fn=log_fn or logger,
            )
        return _coerce_workspace_result(
            raw_result,
            action="remove",
            member_email=member_email,
            workspace_id=workspace_id,
        )
    except Exception as exc:
        detail = str(exc) or "team_workspace_remove_failed"
        if logger:
            logger(f"[TeamWorkspace] remove failed: {member_email} <- {workspace_id}: {detail}")
        return ChatGPTTeamWorkspaceResult(
            success=False,
            action="remove",
            workspace_id=str(workspace_id or "").strip(),
            member_email=str(member_email or "").strip(),
            attempts=1,
            detail=detail,
            payload={"error": detail},
        )


def remove_chatgpt_team_member_with_retry(
    *,
    member_email: str,
    workspace_id: str,
    team_account: dict[str, Any] | None,
    max_attempts: int = 3,
    retry_delay_seconds: float = 1.0,
    remover: Callable[..., ChatGPTTeamWorkspaceResult] | None = None,
    logger: Callable[[str], None] | None = None,
    proxy_url: str | None = None,
    log_fn: Callable[[str], None] | None = None,
    **kwargs,
) -> ChatGPTTeamWorkspaceResult:
    ensure_team_workspace_config(
        member_email=member_email,
        workspace_id=workspace_id,
        team_account=team_account,
        require_workspace_id=remover is not None,
    )
    attempts_limit = max(1, int(max_attempts or 1))
    last_result: ChatGPTTeamWorkspaceResult | None = None
    for attempt in range(1, attempts_limit + 1):
        result = remove_chatgpt_team_member(
            member_email=member_email,
            workspace_id=workspace_id,
            team_account=team_account,
            remover=remover,
            logger=logger,
            proxy_url=proxy_url,
            log_fn=log_fn,
            **kwargs,
        )
        result.attempts = attempt
        last_result = result
        if result.success:
            return result
        if logger:
            logger(f"[TeamWorkspace] remove attempt {attempt}/{attempts_limit} failed: {result.detail}")
        if attempt < attempts_limit and retry_delay_seconds > 0:
            time.sleep(retry_delay_seconds)
    detail = last_result.detail if last_result else "remove_failed"
    payload = dict(last_result.payload if last_result else {})
    resolved_workspace_id = last_result.workspace_id if last_result and last_result.workspace_id else workspace_id
    payload["compensation_context"] = build_cleanup_compensation_context(
        member_email=member_email,
        workspace_id=resolved_workspace_id,
        team_account=team_account,
        failure_detail=detail,
    )
    return ChatGPTTeamWorkspaceResult(
        success=False,
        action="remove",
        workspace_id=str(resolved_workspace_id or "").strip(),
        member_email=str(member_email or "").strip(),
        attempts=attempts_limit,
        detail=detail,
        payload=payload,
    )


def _invite_chatgpt_team_member_via_cloudmail(
    *,
    member_email: str,
    workspace_id: str,
    team_account: dict[str, Any] | None,
    proxy_url: str | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    cfg = _load_cloudmail_team_config()
    _merge_team_account_credential(cfg, team_account)
    manager_email = _validate_email(
        _resolve_team_account_email(team_account, cfg),
        "team_account.email",
    )
    member_email = _validate_email(member_email, "member_email")
    workspace_id = str(workspace_id or "").strip()
    session = login_chatgpt_team_account(manager_email, cfg=cfg, proxy_url=proxy_url, log_fn=log_fn)
    if not workspace_id:
        workspace_id = _resolve_workspace_id(session=session, proxy_url=proxy_url)

    status_code, body, raw = _send_team_invite_once(
        access_token=session.access_token,
        workspace_id=workspace_id,
        target_email=member_email,
        proxy_url=proxy_url,
    )
    error_text = _extract_error_text(status_code, body, raw)
    if 200 <= status_code < 300:
        return {
            "success": True,
            "action": "invite",
            "team_member_email": manager_email,
            "target_email": member_email,
            "member_email": member_email,
            "workspace_id": workspace_id,
            "response": body,
        }
    if status_code in (409, 422) or _is_already_member_or_invited(error_text):
        return {
            "success": True,
            "action": "invite",
            "team_member_email": manager_email,
            "target_email": member_email,
            "member_email": member_email,
            "workspace_id": workspace_id,
            "detail": error_text,
            "response": body or {"detail": error_text},
        }
    raise RuntimeError(error_text or f"ChatGPT Team invite failed: HTTP {status_code}")


def _remove_chatgpt_team_member_via_cloudmail(
    *,
    member_email: str,
    workspace_id: str,
    team_account: dict[str, Any] | None,
    proxy_url: str | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    cfg = _load_cloudmail_team_config()
    _merge_team_account_credential(cfg, team_account)
    manager_email = _validate_email(
        _resolve_team_account_email(team_account, cfg),
        "team_account.email",
    )
    member_email = _validate_email(member_email, "member_email")
    workspace_id = str(workspace_id or "").strip()
    session = login_chatgpt_team_account(manager_email, cfg=cfg, proxy_url=proxy_url, log_fn=log_fn)
    if not workspace_id:
        workspace_id = _resolve_workspace_id(session=session, proxy_url=proxy_url)

    joined_status, joined_members, joined_error = _fetch_joined_members(
        access_token=session.access_token,
        workspace_id=workspace_id,
        proxy_url=proxy_url,
    )
    if joined_status >= 400:
        raise RuntimeError(joined_error or f"Read ChatGPT Team members failed: HTTP {joined_status}")

    for member in joined_members:
        if _normalize_email(member.get("email")) != member_email:
            continue
        user_id = str(member.get("user_id") or "").strip()
        if not user_id:
            raise RuntimeError(f"Team member {member_email} has no user_id")
        status_code, body, raw = _team_api_request(
            method="DELETE",
            access_token=session.access_token,
            workspace_id=workspace_id,
            path=f"/users/{user_id}",
            proxy_url=proxy_url,
        )
        if 200 <= status_code < 300:
            return _build_remove_result(manager_email, member_email, workspace_id, "joined", body)
        raise RuntimeError(_extract_error_text(status_code, body, raw))

    invited_status, invited_members, invited_error = _fetch_invited_members(
        access_token=session.access_token,
        workspace_id=workspace_id,
        proxy_url=proxy_url,
    )
    if invited_status >= 400:
        raise RuntimeError(invited_error or f"Read ChatGPT Team invites failed: HTTP {invited_status}")

    for invite in invited_members:
        if _normalize_email(invite.get("email")) != member_email:
            continue
        status_code, body, raw = _team_api_request(
            method="DELETE",
            access_token=session.access_token,
            workspace_id=workspace_id,
            path="/invites",
            proxy_url=proxy_url,
            payload={"email_address": member_email},
        )
        if 200 <= status_code < 300:
            return _build_remove_result(manager_email, member_email, workspace_id, "invited", body)
        raise RuntimeError(_extract_error_text(status_code, body, raw))

    return {
        "success": True,
        "action": "remove",
        "team_member_email": manager_email,
        "target_email": member_email,
        "member_email": member_email,
        "workspace_id": workspace_id,
        "removed_state": "not_found",
        "message": "target email is not currently joined or invited",
    }


def login_chatgpt_team_account(
    team_member_email: str,
    *,
    cfg: dict[str, Any] | None = None,
    proxy_url: str | None = None,
    log_fn: Callable[[str], None] | None = None,
    force_refresh: bool = False,
) -> TeamWorkspaceSession:
    config = dict(cfg or _load_cloudmail_team_config())
    email = _validate_email(team_member_email, "team_member_email")
    cache_key = f"{email}|{proxy_url or ''}"
    now = time.time()
    if not force_refresh:
        with _SESSION_CACHE_LOCK:
            cached = _SESSION_CACHE.get(cache_key)
            if cached and now < cached[1] and cached[0].access_token:
                return cached[0]

    mailbox = _build_cloudmail_mailbox(config, proxy_url=proxy_url)
    mailbox_email = _resolve_team_otp_mailbox_email(config)
    timeout_seconds = _read_int_config(config, "mailbox_otp_timeout_seconds", default=600, minimum=30, maximum=3600)
    email_service = TeamWorkspaceEmailService(mailbox, email, mailbox_email, timeout_seconds)
    email_service.create_email()

    oauth_client = OAuthClient(
        config,
        proxy=proxy_url,
        verbose=False,
        browser_mode=str(config.get("chatgpt_team_browser_mode") or config.get("executor_type") or "protocol"),
    )
    if log_fn:
        oauth_client._log = lambda msg: log_fn(f"[ChatGPT Team] {msg}")

    password = str(config.get("cloudmail_team_account_password") or config.get("chatgpt_team_account_password") or "")
    tokens = oauth_client.login_and_get_tokens(
        email,
        password,
        "",
        skymail_client=email_service,
        prefer_passwordless_login=True,
        allow_phone_verification=False,
        force_new_browser=True,
        force_chatgpt_entry=False,
        screen_hint="login",
        force_password_login=False,
        login_source="team_workspace",
    )
    if not tokens:
        raise RuntimeError(str(getattr(oauth_client, "last_error", "") or "ChatGPT team account login failed"))

    workspace_id = str(tokens.get("workspace_id") or getattr(oauth_client, "last_workspace_id", "") or "").strip()
    session = TeamWorkspaceSession(
        email=email,
        access_token=str(tokens.get("access_token") or "").strip(),
        refresh_token=str(tokens.get("refresh_token") or "").strip(),
        session_token=str(tokens.get("session_token") or "").strip(),
        account_id=str(tokens.get("account_id") or "").strip(),
        workspace_id=workspace_id,
    )
    if not session.access_token:
        raise RuntimeError("ChatGPT team account login did not return an access_token")

    with _SESSION_CACHE_LOCK:
        _SESSION_CACHE[cache_key] = (session, now + TEAM_SESSION_TTL_SECONDS)
    return session


def _load_cloudmail_team_config() -> dict[str, Any]:
    cfg = dict(config_store.get_all() or {})
    provider = str(cfg.get("mail_provider") or "cloudmail").strip().lower()
    if provider != "cloudmail":
        raise RuntimeError("ChatGPT Team workspace operations are only available when mail_provider is cloudmail")
    if not str(cfg.get("cloudmail_api_base") or "").strip():
        raise RuntimeError("cloudmail_api_base is required for ChatGPT Team workspace operations")
    if not str(cfg.get("cloudmail_admin_password") or "").strip():
        raise RuntimeError("cloudmail_admin_password is required for ChatGPT Team workspace operations")
    return cfg


def _build_cloudmail_mailbox(config: dict[str, Any], *, proxy_url: str | None) -> CloudMailMailbox:
    return CloudMailMailbox(
        api_base=str(config.get("cloudmail_api_base") or ""),
        admin_email=str(config.get("cloudmail_admin_email") or ""),
        admin_password=str(config.get("cloudmail_admin_password") or ""),
        domain=config.get("cloudmail_domain") or "",
        subdomain=str(config.get("cloudmail_subdomain") or ""),
        alias_enabled=True,
        alias_emails="",
        alias_mailbox_email=_resolve_team_otp_mailbox_email(config),
        timeout=_read_int_config(config, "cloudmail_timeout", default=30, minimum=5, maximum=300),
        proxy=proxy_url,
    )


def _resolve_team_otp_mailbox_email(config: dict[str, Any]) -> str:
    explicit = str(
        config.get("cloudmail_team_otp_mailbox_email")
        or config.get("cloudmail_alias_mailbox_email")
        or ""
    ).strip()
    if explicit:
        return explicit
    admin_email = str(config.get("cloudmail_admin_email") or "").strip()
    if admin_email:
        return admin_email
    return CloudMailMailbox(
        api_base=str(config.get("cloudmail_api_base") or ""),
        admin_email="",
        admin_password=str(config.get("cloudmail_admin_password") or ""),
        domain=config.get("cloudmail_domain") or "",
    )._resolve_admin_email()


def _resolve_workspace_id(*, session: TeamWorkspaceSession, proxy_url: str | None) -> str:
    candidates = _fetch_team_workspace_candidates(
        access_token=session.access_token,
        proxy_url=proxy_url,
    )
    candidate_ids = [str(item.get("account_id") or "").strip() for item in candidates if item.get("account_id")]
    if session.workspace_id and session.workspace_id in candidate_ids:
        return session.workspace_id
    if candidate_ids:
        return candidate_ids[0]
    if session.workspace_id:
        return session.workspace_id
    raise RuntimeError("No available ChatGPT Team workspace found for team account")


def _team_api_request(
    *,
    method: str,
    access_token: str,
    workspace_id: str,
    path: str,
    proxy_url: Optional[str],
    payload: Optional[dict[str, Any]] = None,
    timeout_seconds: int = 35,
) -> tuple[int, dict[str, Any], str]:
    url = f"https://chatgpt.com/backend-api/accounts/{workspace_id}{path}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Origin": "https://chatgpt.com",
        "Referer": "https://chatgpt.com/",
        "chatgpt-account-id": workspace_id,
    }
    if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        headers["Content-Type"] = "application/json"
    session = _build_http_session(proxy_url, timeout_seconds)
    try:
        if method.upper() == "GET":
            response = session.get(url, headers=headers)
        elif method.upper() == "POST":
            response = session.post(url, headers=headers, json=payload or {})
        elif method.upper() == "DELETE":
            response = session.delete(url, headers=headers, json=payload) if payload else session.delete(url, headers=headers)
        else:
            raise ValueError(f"unsupported method: {method}")
        return int(response.status_code or 0), _safe_json(response), _safe_text(response)
    except Exception as exc:
        return 599, {}, str(exc)


def _send_team_invite_once(
    *,
    access_token: str,
    workspace_id: str,
    target_email: str,
    proxy_url: Optional[str],
) -> tuple[int, dict[str, Any], str]:
    payload = {
        "email_addresses": [target_email],
        "role": "standard-user",
        "resend_emails": True,
    }
    return _team_api_request(
        method="POST",
        access_token=access_token,
        workspace_id=workspace_id,
        path="/invites",
        proxy_url=proxy_url,
        payload=payload,
    )


def _fetch_team_workspace_candidates(
    *,
    access_token: str,
    proxy_url: Optional[str],
    timeout_seconds: int = 35,
) -> list[dict[str, Any]]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Origin": "https://chatgpt.com",
        "Referer": "https://chatgpt.com/",
    }
    session = _build_http_session(proxy_url, timeout_seconds)
    try:
        response = session.get(CHATGPT_ACCOUNTS_CHECK_URL, headers=headers)
        if int(response.status_code or 0) != 200:
            return []
        payload = _safe_json(response)
    except Exception:
        return []
    accounts = payload.get("accounts") if isinstance(payload, dict) else {}
    if not isinstance(accounts, dict):
        return []
    rows: list[dict[str, Any]] = []
    for account_id, item in accounts.items():
        if not isinstance(item, dict):
            continue
        account = item.get("account") if isinstance(item.get("account"), dict) else {}
        entitlement = item.get("entitlement") if isinstance(item.get("entitlement"), dict) else {}
        plan = str(account.get("plan_type") or entitlement.get("subscription_plan") or "").lower()
        if "team" not in plan and "enterprise" not in plan:
            continue
        rows.append(
            {
                "account_id": str(account_id or "").strip(),
                "name": str(account.get("name") or "").strip(),
                "role": str(account.get("account_user_role") or "").strip(),
                "active": bool(entitlement.get("has_active_subscription")),
                "is_default": bool(account.get("is_default")),
            }
        )
    rows.sort(
        key=lambda item: (
            0 if item.get("is_default") else 1,
            0 if item.get("active") else 1,
            0 if str(item.get("role") or "").lower() in {"owner", "admin", "manager"} else 1,
        )
    )
    return [row for row in rows if row.get("account_id")]


def _fetch_joined_members(
    *,
    access_token: str,
    workspace_id: str,
    proxy_url: Optional[str],
    timeout_seconds: int = 35,
) -> tuple[int, list[dict[str, Any]], str]:
    status_code, body, raw = _team_api_request(
        method="GET",
        access_token=access_token,
        workspace_id=workspace_id,
        path="/users?limit=100&offset=0",
        proxy_url=proxy_url,
        timeout_seconds=timeout_seconds,
    )
    if status_code >= 400:
        return status_code, [], _extract_error_text(status_code, body, raw)
    items = body.get("items") if isinstance(body, dict) else []
    rows = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "user_id": str(item.get("id") or "").strip(),
                "email": str(item.get("email") or "").strip(),
                "role": str(item.get("role") or "").strip(),
                "status": "joined",
            }
        )
    return 200, rows, ""


def _fetch_invited_members(
    *,
    access_token: str,
    workspace_id: str,
    proxy_url: Optional[str],
    timeout_seconds: int = 35,
) -> tuple[int, list[dict[str, Any]], str]:
    status_code, body, raw = _team_api_request(
        method="GET",
        access_token=access_token,
        workspace_id=workspace_id,
        path="/invites",
        proxy_url=proxy_url,
        timeout_seconds=timeout_seconds,
    )
    if status_code >= 400:
        return status_code, [], _extract_error_text(status_code, body, raw)
    items = body.get("items") if isinstance(body, dict) else []
    rows = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "email": str(item.get("email_address") or "").strip(),
                "role": str(item.get("role") or "").strip(),
                "status": "invited",
            }
        )
    return 200, rows, ""


def _build_http_session(proxy_url: Optional[str], timeout_seconds: int):
    kwargs: dict[str, Any] = {
        "impersonate": "chrome120",
        "timeout": max(3, int(timeout_seconds or 35)),
    }
    if proxy_url:
        try:
            kwargs["proxy"] = proxy_url
            return cffi_requests.Session(**kwargs)
        except TypeError:
            session = cffi_requests.Session()
            session.proxies = build_requests_proxy_config(proxy_url)
            return session
    try:
        return cffi_requests.Session(**kwargs)
    except TypeError:
        return cffi_requests.Session()


def _safe_json(response) -> dict[str, Any]:
    try:
        data = response.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _safe_text(response) -> str:
    try:
        return str(response.text or "").strip()
    except Exception:
        return ""


def _extract_error_text(status_code: int, body: dict[str, Any], raw_text: str) -> str:
    for key in ("detail", "message"):
        value = body.get(key) if isinstance(body, dict) else ""
        if value:
            return str(value)
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict) and error.get("message"):
        return str(error.get("message"))
    if raw_text:
        return str(raw_text)[:500]
    return f"ChatGPT Team request failed: HTTP {status_code}"


def _is_already_member_or_invited(error_text: str) -> bool:
    text = str(error_text or "").lower()
    return any(
        marker in text
        for marker in (
            "already in workspace",
            "already in team",
            "already a member",
            "already invited",
            "email already exists",
        )
    )


def _build_remove_result(
    team_member_email: str,
    target_email: str,
    workspace_id: str,
    removed_state: str,
    response: dict[str, Any],
) -> dict[str, Any]:
    return {
        "success": True,
        "action": "remove",
        "team_member_email": team_member_email,
        "target_email": target_email,
        "workspace_id": workspace_id,
        "removed_state": removed_state,
        "response": response,
    }


def _coerce_workspace_result(
    value: Any,
    *,
    action: str,
    member_email: str,
    workspace_id: str,
    attempts: int = 1,
) -> ChatGPTTeamWorkspaceResult:
    if isinstance(value, ChatGPTTeamWorkspaceResult):
        return value
    if isinstance(value, dict):
        payload = dict(value)
        return ChatGPTTeamWorkspaceResult(
            success=bool(value.get("success")),
            action=str(value.get("action") or action),
            workspace_id=str(value.get("workspace_id") or workspace_id or "").strip(),
            member_email=str(value.get("member_email") or value.get("target_email") or member_email or "").strip(),
            attempts=_safe_int(value.get("attempts"), default=attempts),
            detail=str(value.get("detail") or value.get("message") or "").strip(),
            payload=payload,
        )
    detail = "workspace_result_invalid"
    return ChatGPTTeamWorkspaceResult(
        success=False,
        action=action,
        workspace_id=str(workspace_id or "").strip(),
        member_email=str(member_email or "").strip(),
        attempts=attempts,
        detail=detail,
        payload={"raw_result": value},
    )


def _resolve_team_account_email(team_account: dict[str, Any] | None, config: dict[str, Any]) -> str:
    team_account = team_account or {}
    return str(
        team_account.get("email")
        or team_account.get("username")
        or config.get("cloudmail_team_account_email")
        or config.get("chatgpt_team_account_email")
        or team_account_identifier(team_account)
        or ""
    ).strip()


def _merge_team_account_credential(config: dict[str, Any], team_account: dict[str, Any] | None) -> None:
    team_account = team_account or {}
    credential = str(
        team_account.get("password")
        or team_account.get("credential")
        or team_account.get("token")
        or ""
    ).strip()
    if not credential:
        return
    config.setdefault("cloudmail_team_account_password", credential)
    config.setdefault("chatgpt_team_account_password", credential)


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _validate_email(value: Any, field_name: str) -> str:
    email = _normalize_email(value)
    if not EMAIL_RE.match(email):
        raise ValueError(f"{field_name} is not a valid email address")
    return email


def _normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _read_int_config(
    config: dict[str, Any],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(config.get(key) or default)
    except Exception:
        parsed = default
    return max(minimum, min(parsed, maximum))
