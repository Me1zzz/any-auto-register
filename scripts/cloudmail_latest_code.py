#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Callable, Optional, Protocol, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.base_mailbox import MailboxAccount, create_mailbox  # noqa: E402


class _ConfigStoreLike(Protocol):
    def get(self, key: str, default: str = "") -> str: ...


def _load_config_store() -> Optional[_ConfigStoreLike]:
    try:
        from core.config_store import config_store
    except Exception:
        return None
    return config_store


def _get_config_value(cli_value: str, *keys: str, default: str = "") -> str:
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Continuously poll CloudMail emailList and print the latest code.",
    )
    parser.add_argument("--api-base", default="", help="CloudMail API base URL")
    parser.add_argument("--admin-email", default="", help="CloudMail admin email")
    parser.add_argument("--admin-password", default="", help="CloudMail admin password")
    parser.add_argument("--domain", default="", help="CloudMail domain")
    parser.add_argument("--subdomain", default="", help="Optional CloudMail subdomain")
    parser.add_argument(
        "--email",
        default="",
        help="Target email to match. For alias mode, pass the alias email here.",
    )
    parser.add_argument(
        "--mailbox-email",
        default="",
        help="Real mailbox email used for toEmail filtering when different from --email.",
    )
    parser.add_argument(
        "--wait-timeout",
        type=int,
        default=300,
        help="Per polling cycle timeout in seconds before retrying.",
    )
    parser.add_argument(
        "--keyword",
        default="",
        help="Optional keyword filter passed to CloudMail mailbox polling.",
    )
    parser.add_argument(
        "--code-pattern",
        default="",
        help="Optional custom regex pattern for extracting the code.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print timeout/retry diagnostics to stderr.",
    )
    return parser.parse_args()


def _build_mailbox_extra(args: argparse.Namespace) -> dict[str, str]:
    return {
        "cloudmail_api_base": _get_config_value(args.api_base, "cloudmail_api_base", "base_url"),
        "cloudmail_admin_email": _get_config_value(
            args.admin_email,
            "cloudmail_admin_email",
            "admin_email",
        ),
        "cloudmail_admin_password": _get_config_value(
            args.admin_password,
            "cloudmail_admin_password",
            "admin_password",
            "api_key",
        ),
        "cloudmail_domain": _get_config_value(args.domain, "cloudmail_domain", "domain"),
        "cloudmail_subdomain": _get_config_value(args.subdomain, "cloudmail_subdomain", "subdomain"),
    }


def _build_account(args: argparse.Namespace) -> MailboxAccount:
    email = _get_config_value(args.email, "cloudmail_target_email", "cloudmail_alias_email")
    mailbox_email = _get_config_value(
        args.mailbox_email,
        "cloudmail_mailbox_email",
        "cloudmail_alias_mailbox_email",
    )

    if not email:
        raise RuntimeError("缺少目标邮箱：请通过 --email 或配置 cloudmail_target_email / cloudmail_alias_email 提供")

    account_id = mailbox_email or email
    return MailboxAccount(email=email, account_id=account_id)


def _format_match_output(mailbox: object, account: MailboxAccount, code: str) -> str:
    message_id = str(getattr(mailbox, "_last_matched_message_id", "") or "").strip()
    summary = ""

    list_mails = cast(Optional[Callable[[str], list[dict]]], getattr(mailbox, "_list_mails", None))
    resolve_lookup_context = cast(
        Optional[Callable[[MailboxAccount], tuple[str, str, str]]],
        getattr(mailbox, "_resolve_lookup_context", None),
    )
    mail_id = cast(Optional[Callable[[dict, int], str]], getattr(mailbox, "_mail_id", None))
    mail_debug_summary = cast(
        Optional[Callable[[dict, int], str]],
        getattr(mailbox, "_mail_debug_summary", None),
    )

    if all(callable(item) for item in (list_mails, resolve_lookup_context, mail_id, mail_debug_summary)) and message_id:
        assert list_mails is not None
        assert resolve_lookup_context is not None
        assert mail_id is not None
        assert mail_debug_summary is not None
        try:
            target, _, _ = resolve_lookup_context(account)
            mails = list_mails(target)
            for index, message in enumerate(mails):
                if mail_id(message, index) == message_id:
                    summary = str(mail_debug_summary(message, index) or "").strip()
                    break
        except Exception:
            summary = ""

    if summary:
        return f"code={str(code).strip()} {summary}"
    if message_id:
        return f"code={str(code).strip()} id={message_id}"
    return f"code={str(code).strip()}"


def run_polling(
    args: argparse.Namespace,
    *,
    emit: Callable[[str], None] = print,
    emit_error: Callable[[str], None] | None = None,
) -> int:
    emit_error = emit_error or (lambda message: print(message, file=sys.stderr))
    mailbox = create_mailbox("cloudmail", extra=_build_mailbox_extra(args))
    account = _build_account(args)

    while True:
        try:
            code = mailbox.wait_for_code(
                account,
                keyword=str(args.keyword or "").strip(),
                timeout=int(args.wait_timeout),
                code_pattern=str(args.code_pattern or "").strip(),
            )
            if code:
                emit(_format_match_output(mailbox, account, str(code)))
        except TimeoutError:
            if args.verbose:
                emit_error(f"[cloudmail] {int(args.wait_timeout)}s 内未获取到新验证码，继续轮询")
        except KeyboardInterrupt:
            if args.verbose:
                emit_error("[cloudmail] 已停止轮询")
            return 0


def main() -> int:
    args = _parse_args()
    return run_polling(args)


if __name__ == "__main__":
    raise SystemExit(main())
