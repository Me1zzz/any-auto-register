#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, cast
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass(eq=False)
class MailboxAccount:
    email: str
    account_id: str = ""
    extra: dict[str, Any] | None = None

    def __eq__(self, other: object) -> bool:
        if other is None:
            return False
        return (
            self.email == str(getattr(other, "email", "") or "")
            and self.account_id == str(getattr(other, "account_id", "") or "")
            and self.extra == getattr(other, "extra", None)
        )


class _ConfigStoreLike(Protocol):
    def get(self, key: str, default: str = "") -> str: ...


class _MailboxAccountLike(Protocol):
    email: str
    account_id: str


class CloudMailClient:
    def __init__(
        self,
        *,
        api_base: str,
        admin_email: str,
        admin_password: str,
        domain: Any,
        subdomain: str,
        timeout: int = 30,
    ):
        self.api = str(api_base or "").rstrip("/")
        self.admin_email = str(admin_email or "").strip()
        self.admin_password = str(admin_password or "").strip()
        self.domain = domain
        self.subdomain = str(subdomain or "").strip()
        self.timeout = max(int(timeout or 30), 5)
        self._token = ""
        self._token_expire_at = 0.0
        self._last_matched_message_id = ""

    @staticmethod
    def _extract_domain_from_url(url: str) -> str:
        parsed = urlparse(str(url or ""))
        host = (parsed.netloc or parsed.path.split("/")[0] or "").strip()
        if ":" in host:
            host = host.split(":", 1)[0].strip()
        return host

    @staticmethod
    def _normalize_domain(value: Any) -> str:
        domain = str(value or "").strip().lstrip("@")
        if "://" in domain:
            domain = CloudMailClient._extract_domain_from_url(domain)
        return domain.strip()

    def _domain_candidates(self) -> list[str]:
        candidates: list[str] = []

        if isinstance(self.domain, (list, tuple, set)):
            iterable = self.domain
        else:
            raw = str(self.domain or "").strip()
            parsed = None
            if raw.startswith("[") and raw.endswith("]"):
                try:
                    parsed = json.loads(raw)
                except Exception:
                    parsed = None
            if isinstance(parsed, list):
                iterable = parsed
            elif raw:
                iterable = (
                    raw.replace(";", "\n")
                    .replace(",", "\n")
                    .replace("|", "\n")
                    .splitlines()
                )
            else:
                iterable = []

        for item in iterable:
            normalized = self._normalize_domain(item)
            if normalized:
                candidates.append(normalized)

        if not candidates:
            inferred = self._normalize_domain(self._extract_domain_from_url(self.api))
            if inferred:
                candidates.append(inferred)
        return candidates

    def _resolve_admin_email(self) -> str:
        if self.admin_email:
            return self.admin_email
        domains = self._domain_candidates()
        if domains:
            return f"admin@{domains[0]}"
        return "admin@example.com"

    def _ensure_config(self) -> None:
        if not self.api or not self.admin_password:
            raise RuntimeError(
                "CloudMail 未配置完整：请设置 cloudmail_api_base 与 cloudmail_admin_password"
            )

    @staticmethod
    def _headers(token: str = "") -> dict[str, str]:
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
        }
        if token:
            headers["authorization"] = token
        return headers

    def _generate_token(self) -> str:
        self._ensure_config()
        payload = {
            "email": self._resolve_admin_email(),
            "password": self.admin_password,
        }
        response = requests.post(
            f"{self.api}/api/public/genToken",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"CloudMail 生成 token 失败: {response.status_code} {str(response.text or '')[:200]}"
            )

        try:
            data = response.json()
        except Exception:
            data = {}

        if data.get("code") != 200:
            raise RuntimeError(f"CloudMail 生成 token 失败: {data}")

        token = str(((data.get("data") or {}).get("token") or "")).strip()
        if not token:
            raise RuntimeError("CloudMail 生成 token 失败: 响应未返回 token")
        return token

    def _get_token(self, *, force_refresh: bool = False) -> str:
        now = time.time()
        if not force_refresh and self._token and now < self._token_expire_at:
            return self._token

        self._token = self._generate_token()
        self._token_expire_at = now + 3600
        return self._token

    def _list_mails(self, email: str = "", *, retry_auth: bool = True) -> list[dict[str, Any]]:
        token = self._get_token()
        payload: dict[str, str] = {"timeSort": "desc"}
        if email:
            payload["toEmail"] = email

        response = requests.post(
            f"{self.api}/api/public/emailList",
            json=payload,
            headers=self._headers(token),
            timeout=self.timeout,
        )
        if response.status_code == 401 and retry_auth:
            token = self._get_token(force_refresh=True)
            response = requests.post(
                f"{self.api}/api/public/emailList",
                json=payload,
                headers=self._headers(token),
                timeout=self.timeout,
            )
        if response.status_code != 200:
            return []

        try:
            data = response.json()
        except Exception:
            data = {}
        if data.get("code") != 200:
            return []

        mails = data.get("data") or []
        return [item for item in mails if isinstance(item, dict)]

    def _resolve_lookup_context(self, account: _MailboxAccountLike) -> tuple[str, str, str]:
        mailbox_email = str(account.account_id or "").strip()
        account_email = str(account.email or "").strip()

        if mailbox_email:
            alias_email = ""
            if self._normalize_email_value(mailbox_email) != self._normalize_email_value(account_email):
                alias_email = self._normalize_email_value(account_email)
            return mailbox_email, alias_email, mailbox_email

        alias_email = self._normalize_email_value(account_email)
        seen_key = f"recipient:{alias_email}" if alias_email else ""
        return "", alias_email, seen_key

    @staticmethod
    def _normalize_email_value(value: Any) -> str:
        return str(value or "").strip().lower()

    def _collect_recipient_addresses(self, value: Any) -> set[str]:
        addresses: set[str] = set()

        def collect(item: Any) -> None:
            if item in (None, ""):
                return

            if isinstance(item, dict):
                for key in ("address", "email", "recipient", "recipt", "receipt", "toEmail"):
                    normalized = self._normalize_email_value(item.get(key))
                    if normalized:
                        addresses.add(normalized)
                return

            if isinstance(item, (list, tuple, set)):
                for child in item:
                    collect(child)
                return

            text = str(item).strip()
            if not text:
                return

            if text.startswith("[") or text.startswith("{"):
                try:
                    parsed = json.loads(text)
                except Exception:
                    parsed = None
                if parsed is not None:
                    collect(parsed)
                    return

            normalized = self._normalize_email_value(text)
            if normalized:
                addresses.add(normalized)

        collect(value)
        return addresses

    def _contains_alias_email(self, value: Any, normalized_alias: str) -> bool:
        if not normalized_alias or value in (None, ""):
            return False

        if isinstance(value, dict):
            return any(self._contains_alias_email(item, normalized_alias) for item in value.values())

        if isinstance(value, (list, tuple, set)):
            return any(self._contains_alias_email(item, normalized_alias) for item in value)

        text = str(value).strip()
        if not text:
            return False

        if text.startswith("[") or text.startswith("{"):
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = None
            if parsed is not None:
                return self._contains_alias_email(parsed, normalized_alias)

        return normalized_alias in text.lower()

    def _match_alias_receipt(self, message: dict[str, Any], alias_email: str) -> bool:
        if not alias_email:
            return True

        normalized_alias = self._normalize_email_value(alias_email)
        recipient_addresses = set()
        for key in ("recipt", "receipt", "recipient", "recipients"):
            recipient_addresses.update(self._collect_recipient_addresses(message.get(key)))
        if normalized_alias in recipient_addresses:
            return True

        for key in (
            "sendEmail",
            "sendName",
            "from",
            "fromEmail",
            "from_email",
            "sender",
            "senderEmail",
            "sender_email",
            "mailFrom",
            "mail_from",
        ):
            if self._contains_alias_email(message.get(key), normalized_alias):
                return True

        for key in ("content", "text", "html"):
            if self._contains_alias_email(message.get(key), normalized_alias):
                return True

        return False

    @staticmethod
    def _mail_id(message: dict[str, Any], index: int = 0) -> str:
        for key in ("emailId", "id", "mailId", "messageId"):
            value = message.get(key)
            if value not in (None, ""):
                return str(value)
        digest = (
            str(message.get("date") or message.get("time") or "")
            + "|"
            + str(message.get("subject") or "")
        )
        return f"idx-{index}-{digest}"

    def _mail_debug_summary(self, message: dict[str, Any], index: int = 0) -> str:
        if not isinstance(message, dict):
            return f"idx={index} invalid-message"

        message_id = self._mail_id(message, index)
        subject = str(message.get("subject") or "").strip()
        if len(subject) > 80:
            subject = subject[:77] + "..."

        recipient_addresses = set()
        for key in ("recipt", "receipt", "recipient", "recipients"):
            recipient_addresses.update(self._collect_recipient_addresses(message.get(key)))
        recipients = sorted(recipient_addresses)
        recipients_text = ",".join(recipients[:3]) if recipients else "-"
        if len(recipients) > 3:
            recipients_text += ",..."

        return (
            f"id={message_id} toEmail={str(message.get('toEmail') or '').strip()} "
            f"recipient={recipients_text} subject={subject}"
        )

    @staticmethod
    def _safe_extract(text: str, pattern: str = "") -> Optional[str]:
        content = str(text or "")
        if not content:
            return None

        patterns: list[str] = []
        if pattern:
            patterns.append(pattern)

        patterns.extend(
            [
                r"(?is)(?:verification\s+code|one[-\s]*time\s+(?:password|code)|security\s+code|login\s+code|验证码|校验码|动态码|認證碼|驗證碼)[^0-9]{0,30}(\d{6})",
                r"(?is)\bcode\b[^0-9]{0,12}(\d{6})",
                r"(?<!#)(?<!\d)(\d{6})(?!\d)",
            ]
        )

        for regex in patterns:
            matched = re.search(regex, content)
            if matched:
                return matched.group(1) if matched.groups() else matched.group(0)
        return None


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
    parser.add_argument("--api-base", default="https://me1zzz.tech", help="CloudMail API base URL")
    parser.add_argument("--admin-email", default="admin@me1zzz.tech", help="CloudMail admin email")
    parser.add_argument("--admin-password", default="1103@Icity", help="CloudMail admin password")
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


def create_mailbox(provider: str, extra: Optional[dict[str, str]] = None) -> CloudMailClient:
    if provider != "cloudmail":
        raise ValueError(f"Unsupported mailbox provider: {provider}")

    extra = extra or {}
    timeout_raw = extra.get("cloudmail_timeout", extra.get("timeout", 30))
    try:
        timeout_value = int(timeout_raw)
    except (TypeError, ValueError):
        timeout_value = 30

    return CloudMailClient(
        api_base=extra.get("cloudmail_api_base") or extra.get("base_url") or "",
        admin_email=extra.get("cloudmail_admin_email") or extra.get("admin_email") or "",
        admin_password=(
            extra.get("cloudmail_admin_password")
            or extra.get("admin_password")
            or extra.get("api_key")
            or ""
        ),
        domain=extra.get("cloudmail_domain") or extra.get("domain") or "",
        subdomain=extra.get("cloudmail_subdomain") or extra.get("subdomain") or "",
        timeout=timeout_value,
    )


def _build_account(args: argparse.Namespace) -> MailboxAccount:
    email = _get_config_value(args.email, "cloudmail_target_email", "cloudmail_alias_email")
    mailbox_email = _get_config_value(
        args.mailbox_email,
        "cloudmail_mailbox_email",
        "cloudmail_alias_mailbox_email",
    )

    if not email and not mailbox_email:
        return MailboxAccount(email="", account_id="")

    account_id = mailbox_email or email
    return MailboxAccount(email=email, account_id=account_id)


def _format_match_output(mailbox: object, account: _MailboxAccountLike, code: str) -> str:
    message_id = str(getattr(mailbox, "_last_matched_message_id", "") or "").strip()
    summary = ""

    list_mails = cast(Optional[Callable[[str], list[dict[str, Any]]]], getattr(mailbox, "_list_mails", None))
    resolve_lookup_context = cast(
        Optional[Callable[[_MailboxAccountLike], tuple[str, str, str]]],
        getattr(mailbox, "_resolve_lookup_context", None),
    )
    mail_id = cast(Optional[Callable[[dict[str, Any], int], str]], getattr(mailbox, "_mail_id", None))
    mail_debug_summary = cast(
        Optional[Callable[[dict[str, Any], int], str]],
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


def _scan_once(
    mailbox: object,
    account: _MailboxAccountLike,
    *,
    keyword: str,
    code_pattern: str,
    printed_ids: set[str],
) -> list[str]:
    list_mails = cast(Optional[Callable[[str], list[dict[str, Any]]]], getattr(mailbox, "_list_mails", None))
    resolve_lookup_context = cast(
        Optional[Callable[[_MailboxAccountLike], tuple[str, str, str]]],
        getattr(mailbox, "_resolve_lookup_context", None),
    )
    match_alias_receipt = cast(
        Optional[Callable[[dict[str, Any], str], bool]],
        getattr(mailbox, "_match_alias_receipt", None),
    )
    mail_id = cast(Optional[Callable[[dict[str, Any], int], str]], getattr(mailbox, "_mail_id", None))
    safe_extract = cast(Optional[Callable[[str, str], Optional[str]]], getattr(mailbox, "_safe_extract", None))

    if not all(callable(item) for item in (list_mails, resolve_lookup_context, match_alias_receipt, mail_id, safe_extract)):
        raise RuntimeError("CloudMail mailbox missing required methods for polling")

    assert list_mails is not None
    assert resolve_lookup_context is not None
    assert match_alias_receipt is not None
    assert mail_id is not None
    assert safe_extract is not None

    target, alias_email, _ = resolve_lookup_context(account)
    outputs: list[str] = []
    mails = list_mails(target)
    keyword_lower = keyword.lower()

    for index, message in enumerate(mails):
        mid = str(mail_id(message, index) or "").strip()
        if not mid or mid in printed_ids:
            continue
        if alias_email and not match_alias_receipt(message, alias_email):
            continue

        content = " ".join(
            [
                str(message.get("subject") or ""),
                str(message.get("content") or ""),
                str(message.get("text") or ""),
                str(message.get("html") or ""),
            ]
        )
        if keyword_lower and keyword_lower not in content.lower():
            continue

        code = safe_extract(content, code_pattern)
        if not code:
            continue

        setattr(mailbox, "_last_matched_message_id", mid)
        printed_ids.add(mid)
        outputs.append(_format_match_output(mailbox, account, code))

    return outputs


def run_polling(
    args: argparse.Namespace,
    *,
    emit: Callable[[str], None] = print,
    emit_error: Callable[[str], None] | None = None,
) -> int:
    emit_error = emit_error or (lambda message: print(message, file=sys.stderr))
    mailbox = create_mailbox("cloudmail", extra=_build_mailbox_extra(args))
    account = _build_account(args)
    printed_ids: set[str] = set()
    keyword = str(args.keyword or "").strip()
    code_pattern = str(args.code_pattern or "").strip()

    while True:
        try:
            for line in _scan_once(
                mailbox,
                account,
                keyword=keyword,
                code_pattern=code_pattern,
                printed_ids=printed_ids,
            ):
                emit(line)
            time.sleep(0.1)
        except KeyboardInterrupt:
            if args.verbose:
                emit_error("[cloudmail] 已停止轮询")
            return 0
        except Exception as exc:
            if args.verbose:
                emit_error(f"[cloudmail] 轮询失败: {exc}")
            time.sleep(0.1)


def main() -> int:
    args = _parse_args()
    return run_polling(args)


if __name__ == "__main__":
    raise SystemExit(main())
