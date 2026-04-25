"""Team workspace member-management boundary for ChatGPT GUI OAuth flows."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


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
) -> None:
    if not str(member_email or "").strip():
        raise ValueError("缺少待管理的 Team 成员邮箱")
    if not str(workspace_id or "").strip():
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
    **kwargs,
) -> ChatGPTTeamWorkspaceResult:
    ensure_team_workspace_config(
        member_email=member_email,
        workspace_id=workspace_id,
        team_account=team_account,
    )
    if inviter is not None:
        return inviter(
            member_email=member_email,
            workspace_id=workspace_id,
            team_account=team_account,
            **kwargs,
        )
    if logger:
        logger(f"[TeamWorkspace] invite boundary not configured: {member_email} -> {workspace_id}")
    return ChatGPTTeamWorkspaceResult(
        success=False,
        action="invite",
        workspace_id=workspace_id,
        member_email=member_email,
        attempts=1,
        detail="team_workspace_inviter_not_configured",
    )


def remove_chatgpt_team_member(
    *,
    member_email: str,
    workspace_id: str,
    team_account: dict[str, Any] | None,
    remover: Callable[..., ChatGPTTeamWorkspaceResult] | None = None,
    logger: Callable[[str], None] | None = None,
    **kwargs,
) -> ChatGPTTeamWorkspaceResult:
    ensure_team_workspace_config(
        member_email=member_email,
        workspace_id=workspace_id,
        team_account=team_account,
    )
    if remover is not None:
        return remover(
            member_email=member_email,
            workspace_id=workspace_id,
            team_account=team_account,
            **kwargs,
        )
    if logger:
        logger(f"[TeamWorkspace] remove boundary not configured: {member_email} <- {workspace_id}")
    return ChatGPTTeamWorkspaceResult(
        success=False,
        action="remove",
        workspace_id=workspace_id,
        member_email=member_email,
        attempts=1,
        detail="team_workspace_remover_not_configured",
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
    **kwargs,
) -> ChatGPTTeamWorkspaceResult:
    ensure_team_workspace_config(
        member_email=member_email,
        workspace_id=workspace_id,
        team_account=team_account,
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
    payload["compensation_context"] = build_cleanup_compensation_context(
        member_email=member_email,
        workspace_id=workspace_id,
        team_account=team_account,
        failure_detail=detail,
    )
    return ChatGPTTeamWorkspaceResult(
        success=False,
        action="remove",
        workspace_id=workspace_id,
        member_email=member_email,
        attempts=attempts_limit,
        detail=detail,
        payload=payload,
    )
