from __future__ import annotations

from typing import Any


def _provider_display_name(provider_type: str) -> str:
    display = str(provider_type or "").strip().replace("_", " ")
    return display or "alias provider"


def log_alias_service_account_registered(
    log_fn: Any,
    *,
    provider_type: str,
    email: str,
    password: str = "",
    username: str = "",
) -> None:
    if not callable(log_fn):
        return
    normalized_email = str(email or "").strip()
    if not normalized_email:
        return

    parts = [
        f"email={normalized_email}",
        f"password={str(password or '').strip()}",
    ]
    normalized_username = str(username or "").strip()
    if normalized_username:
        parts.append(f"username={normalized_username}")

    try:
        log_fn(
            f"[AliasPool] {_provider_display_name(provider_type)} 服务账号注册成功: "
            + " ".join(parts)
        )
    except Exception:
        return
