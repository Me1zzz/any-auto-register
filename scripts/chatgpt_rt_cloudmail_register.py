#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Optional, Protocol, cast
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.base_mailbox import CloudMailMailbox, create_mailbox  # noqa: E402
from core.base_platform import Account, RegisterConfig  # noqa: E402
from platforms.chatgpt.plugin import ChatGPTPlatform  # noqa: E402


class _ConfigStoreLike(Protocol):
    def get(self, key: str, default: str = "") -> str:
        raise NotImplementedError


def _load_config_store() -> Optional[_ConfigStoreLike]:
    try:
        from core.config_store import config_store
    except Exception:
        return None
    return config_store


def _get_config_value(cli_value: Any, *keys: str, default: str = "") -> str:
    value = str(cli_value or "").strip()
    if value:
        return value

    store = _load_config_store()

    for key in keys:
        if store is not None:
            resolved = str(store.get(key, "") or "").strip()
            if resolved:
                return resolved

        env_value = str(os.getenv(key, "") or "").strip()
        if env_value:
            return env_value

        upper_env_value = str(os.getenv(key.upper(), "") or "").strip()
        if upper_env_value:
            return upper_env_value
    return default


def _parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _read_text_file(file_path: str) -> str:
    path = Path(str(file_path or "").strip())
    if not path:
        return ""
    if not str(path):
        return ""
    return path.read_text(encoding="utf-8")


def _normalize_alias_emails(*values: Any) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()

    for value in values:
        if value in (None, ""):
            continue

        if isinstance(value, (list, tuple, set)):
            iterable = value
        else:
            raw = str(value or "").replace(";", "\n").replace(",", "\n")
            iterable = raw.splitlines()

        for item in iterable:
            email = str(item or "").strip().lower()
            if not email or email in seen:
                continue
            seen.add(email)
            items.append(email)

    return items


def _to_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run ChatGPT RT registration with CloudMail alias support.",
    )

    parser.add_argument("--proxy", default="", help="HTTP/SOCKS proxy URL")
    parser.add_argument(
        "--browser-mode",
        default="protocol",
        choices=["protocol", "headless", "headed"],
        help="ChatGPT executor/browser mode",
    )
    parser.add_argument("--password", default="", help="Optional fixed account password")

    parser.add_argument("--cloudmail-api-base", default="", help="CloudMail API base URL")
    parser.add_argument("--cloudmail-admin-email", default="", help="CloudMail admin email")
    parser.add_argument("--cloudmail-admin-password", default="", help="CloudMail admin password")
    parser.add_argument("--cloudmail-domain", default="", help="CloudMail domain")
    parser.add_argument("--cloudmail-subdomain", default="", help="CloudMail subdomain")
    parser.add_argument(
        "--cloudmail-timeout",
        type=int,
        default=30,
        help="CloudMail HTTP timeout seconds",
    )

    parser.add_argument(
        "--cloudmail-alias-enabled",
        action="store_true",
        help="Enable CloudMail alias mode",
    )
    parser.add_argument(
        "--cloudmail-alias-emails",
        default="",
        help="Alias emails, separated by newline/comma/semicolon",
    )
    parser.add_argument(
        "--cloudmail-alias-emails-file",
        default="",
        help="Path to alias email file, one per line",
    )
    parser.add_argument(
        "--cloudmail-alias-mailbox-email",
        default="",
        help="Real mailbox email used behind alias mode",
    )
    parser.add_argument(
        "--task-alias-pool-key",
        default="",
        help="Optional task-scoped alias pool key",
    )
    parser.add_argument(
        "--release-alias-pool",
        action="store_true",
        help="Release alias pool key on exit",
    )

    parser.add_argument("--mailbox-otp-timeout-seconds", default="")
    parser.add_argument("--chatgpt-register-otp-wait-seconds", default="")
    parser.add_argument("--chatgpt-register-otp-resend-wait-seconds", default="")
    parser.add_argument("--chatgpt-register-otp-max-resends", default="")
    parser.add_argument("--chatgpt-oauth-otp-wait-seconds", default="")
    parser.add_argument("--chatgpt-oauth-otp-resend-wait-seconds", default="")
    parser.add_argument("--register-max-retries", default="")

    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Mirror engine logs to stderr",
    )

    return parser.parse_args()


def _build_cloudmail_extra(args: argparse.Namespace) -> dict[str, Any]:
    alias_file_content = ""
    if str(args.cloudmail_alias_emails_file or "").strip():
        alias_file_content = _read_text_file(args.cloudmail_alias_emails_file)

    alias_emails = _normalize_alias_emails(
        args.cloudmail_alias_emails,
        alias_file_content,
        _get_config_value("", "cloudmail_alias_emails"),
    )

    alias_enabled = args.cloudmail_alias_enabled or _parse_bool(
        _get_config_value("", "cloudmail_alias_enabled"),
        default=False,
    )

    return {
        "cloudmail_api_base": _get_config_value(
            args.cloudmail_api_base,
            "cloudmail_api_base",
            "base_url",
        ),
        "cloudmail_admin_email": _get_config_value(
            args.cloudmail_admin_email,
            "cloudmail_admin_email",
            "admin_email",
        ),
        "cloudmail_admin_password": _get_config_value(
            args.cloudmail_admin_password,
            "cloudmail_admin_password",
            "admin_password",
            "api_key",
        ),
        "cloudmail_domain": _get_config_value(
            args.cloudmail_domain,
            "cloudmail_domain",
            "domain",
        ),
        "cloudmail_subdomain": _get_config_value(
            args.cloudmail_subdomain,
            "cloudmail_subdomain",
            "subdomain",
        ),
        "cloudmail_timeout": args.cloudmail_timeout,
        "cloudmail_alias_enabled": alias_enabled,
        "cloudmail_alias_emails": alias_emails,
        "cloudmail_alias_mailbox_email": _get_config_value(
            args.cloudmail_alias_mailbox_email,
            "cloudmail_alias_mailbox_email",
            "cloudmail_mailbox_email",
        ),
    }


def _add_int_if_present(target: dict[str, Any], key: str, value: Any) -> None:
    resolved = _to_int(value)
    if resolved is not None:
        target[key] = resolved


def _build_chatgpt_extra(args: argparse.Namespace) -> dict[str, Any]:
    extra: dict[str, Any] = {
        "chatgpt_registration_mode": "refresh_token",
        "chatgpt_has_refresh_token_solution": True,
    }
    _add_int_if_present(
        extra,
        "mailbox_otp_timeout_seconds",
        _get_config_value(args.mailbox_otp_timeout_seconds, "mailbox_otp_timeout_seconds", "email_otp_timeout_seconds", "otp_timeout"),
    )
    _add_int_if_present(
        extra,
        "chatgpt_register_otp_wait_seconds",
        _get_config_value(args.chatgpt_register_otp_wait_seconds, "chatgpt_register_otp_wait_seconds"),
    )
    _add_int_if_present(
        extra,
        "chatgpt_register_otp_resend_wait_seconds",
        _get_config_value(args.chatgpt_register_otp_resend_wait_seconds, "chatgpt_register_otp_resend_wait_seconds"),
    )
    _add_int_if_present(
        extra,
        "chatgpt_register_otp_max_resends",
        _get_config_value(args.chatgpt_register_otp_max_resends, "chatgpt_register_otp_max_resends"),
    )
    _add_int_if_present(
        extra,
        "chatgpt_oauth_otp_wait_seconds",
        _get_config_value(args.chatgpt_oauth_otp_wait_seconds, "chatgpt_oauth_otp_wait_seconds"),
    )
    _add_int_if_present(
        extra,
        "chatgpt_oauth_otp_resend_wait_seconds",
        _get_config_value(args.chatgpt_oauth_otp_resend_wait_seconds, "chatgpt_oauth_otp_resend_wait_seconds"),
    )
    _add_int_if_present(
        extra,
        "register_max_retries",
        _get_config_value(args.register_max_retries, "register_max_retries"),
    )
    return extra


class ScriptLogger:
    def __init__(self, *, verbose: bool):
        self.verbose = verbose
        self.lines: list[str] = []

    def emit(self, message: str) -> None:
        text = str(message or "")
        self.lines.append(text)
        if self.verbose:
            print(text, file=sys.stderr)

    def script(self, message: str) -> None:
        text = f"[script] {message}"
        self.lines.append(text)
        print(text, file=sys.stderr)


def _normalize_account_payload(account: Account) -> dict[str, Any]:
    extra = dict(account.extra or {})
    return {
        "platform": account.platform,
        "email": account.email,
        "password": account.password,
        "user_id": account.user_id,
        "region": account.region,
        "token": account.token,
        "status": getattr(account.status, "value", str(account.status)),
        "trial_end_time": account.trial_end_time,
        "created_at": account.created_at,
        "extra": extra,
    }


def _cloudmail_payload(mailbox: Any, task_alias_pool_key: str) -> dict[str, Any]:
    last_account = getattr(mailbox, "_last_account", None)
    alias_email = str(getattr(last_account, "email", "") or "").strip()
    mailbox_email = str(getattr(last_account, "account_id", "") or "").strip()
    normalized_alias = alias_email.lower()
    normalized_mailbox = mailbox_email.lower()
    alias_enabled = bool(getattr(mailbox, "alias_enabled", False))
    alias_active = bool(
        alias_enabled
        and alias_email
        and (not mailbox_email or normalized_alias != normalized_mailbox)
    )
    return {
        "alias_enabled": alias_enabled,
        "alias_active": alias_active,
        "alias_email": alias_email,
        "mailbox_email": mailbox_email,
        "last_matched_message_id": str(getattr(mailbox, "_last_matched_message_id", "") or "").strip(),
        "task_alias_pool_key": str(task_alias_pool_key or "").strip(),
    }


def _dump_json(payload: dict[str, Any], *, pretty: bool) -> None:
    if pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def run(args: argparse.Namespace) -> int:
    logger = ScriptLogger(verbose=bool(args.verbose))
    task_alias_pool_key = str(args.task_alias_pool_key or "").strip()
    if not task_alias_pool_key and args.release_alias_pool:
        task_alias_pool_key = f"script-{uuid4().hex[:12]}"

    mailbox = None
    cloudmail_extra: dict[str, Any] = {}
    try:
        cloudmail_extra = _build_cloudmail_extra(args)
        chatgpt_extra = _build_chatgpt_extra(args)
        logger.script("creating CloudMail mailbox")
        mailbox = create_mailbox("cloudmail", extra=cloudmail_extra, proxy=str(args.proxy or ""))
        if task_alias_pool_key:
            setattr(mailbox, "_task_alias_pool_key", task_alias_pool_key)

        config = RegisterConfig(
            executor_type=args.browser_mode,
            proxy=(args.proxy or None),
            extra=chatgpt_extra,
        )

        logger.script("starting ChatGPT RT registration")
        platform = ChatGPTPlatform(config=config)
        setattr(platform, "mailbox", mailbox)
        setattr(platform, "_log_fn", logger.emit)
        account = cast(Any, platform).register(email="", password=str(args.password or ""))

        payload = {
            "ok": True,
            "account": _normalize_account_payload(account),
            "chatgpt": {
                "registration_mode": "refresh_token",
                "token_source": str((account.extra or {}).get("chatgpt_token_source") or ""),
                "workspace_id": str((account.extra or {}).get("workspace_id") or ""),
                "session_token": str((account.extra or {}).get("session_token") or ""),
            },
            "cloudmail": _cloudmail_payload(mailbox, task_alias_pool_key),
            "logs": logger.lines,
        }
        _dump_json(payload, pretty=bool(args.pretty))
        return 0
    except Exception as exc:
        logger.script(f"registration failed: {exc}")
        if args.verbose:
            traceback.print_exc(file=sys.stderr)
        payload = {
            "ok": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
            "cloudmail": _cloudmail_payload(mailbox, task_alias_pool_key) if mailbox is not None else {
                "alias_enabled": _parse_bool(cloudmail_extra.get("cloudmail_alias_enabled"), default=False),
                "alias_active": False,
                "alias_email": "",
                "mailbox_email": "",
                "last_matched_message_id": "",
                "task_alias_pool_key": task_alias_pool_key,
            },
            "logs": logger.lines,
        }
        _dump_json(payload, pretty=bool(args.pretty))
        return 1
    finally:
        if args.release_alias_pool and task_alias_pool_key:
            releaser = getattr(CloudMailMailbox, "release_alias_pool", None)
            if callable(releaser):
                try:
                    releaser(task_alias_pool_key)
                except Exception as release_error:
                    print(
                        f"[script] release alias pool failed: {release_error}",
                        file=sys.stderr,
                    )


def main() -> int:
    return run(_parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
