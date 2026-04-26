from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

from core.base_mailbox import CloudMailMailbox
from core.http_client import HTTPClient

from .mailbox_verification_adapter import (
    build_mailbox_email_list_request,
    build_mailbox_login_request,
    extract_anchored_link_from_message_content,
)


@dataclass(frozen=True)
class VerificationLinkResolution:
    kind: str
    link: str = ""
    source: str = ""
    error: str = ""


class VerificationExecutorHTTPClient(Protocol):
    def request(self, method: str, url: str, **kwargs) -> "VerificationExecutorResponse": ...


class VerificationExecutorResponse(Protocol):
    def json(self) -> dict[str, Any]: ...


class _MailboxReceiptMatcher:
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

    def match_alias_receipt(self, message: dict[str, Any], alias_email: str) -> bool:
        if not alias_email:
            return True
        normalized_alias = self._normalize_email_value(alias_email)
        recipient_addresses = set()
        for key in ("recipt", "receipt", "recipient", "recipients"):
            recipient_addresses.update(self._collect_recipient_addresses(message.get(key)))
        if normalized_alias in recipient_addresses:
            return True

        for key in (
            "toEmail",
            "toName",
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

    def match_mailbox_target(self, message: dict[str, Any], mailbox_email: str) -> bool:
        normalized_target = self._normalize_email_value(mailbox_email)
        if not normalized_target:
            return False

        recipient_addresses = set()
        for key in ("recipt", "receipt", "recipient", "recipients", "toEmail"):
            recipient_addresses.update(self._collect_recipient_addresses(message.get(key)))
        return normalized_target in recipient_addresses


class VerificationExecutor:
    def __init__(self, *, client: VerificationExecutorHTTPClient | None = None, confirmation_reader: Any = None):
        self._client = client or HTTPClient()
        self._confirmation_reader = confirmation_reader

    @staticmethod
    def _is_myalias_cloudmail_lookup(spec) -> bool:
        provider_type = str(getattr(spec, "provider_type", "") or "").strip().lower()
        return provider_type == "myalias_pro"

    @staticmethod
    def _extract_message_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
        data = payload.get("data")
        if isinstance(data, dict):
            nested_list = data.get("list")
            if isinstance(nested_list, list):
                return [message for message in nested_list if isinstance(message, dict)]
        if isinstance(data, list):
            return [message for message in data if isinstance(message, dict)]
        rows = payload.get("rows")
        if isinstance(rows, list):
            return [message for message in rows if isinstance(message, dict)]
        return []

    @staticmethod
    def _extract_token(payload: dict[str, Any]) -> str:
        token = payload.get("token")
        if token not in (None, ""):
            return str(token).strip()
        data = payload.get("data")
        if isinstance(data, dict):
            nested_token = data.get("token")
            if nested_token not in (None, ""):
                return str(nested_token).strip()
        return ""

    def _resolve_link_via_cloudmail_mailbox(
        self,
        *,
        requirement,
        inbox: dict[str, Any],
        target_email: str,
    ) -> VerificationLinkResolution:
        mailbox = CloudMailMailbox(
            api_base=str(inbox.get("api_base") or inbox.get("base_url") or "").strip(),
            admin_email=str(inbox.get("admin_email") or inbox.get("account_email") or "").strip(),
            admin_password=str(inbox.get("admin_password") or inbox.get("account_password") or "").strip(),
            domain=inbox.get("domain") or "",
            subdomain=str(inbox.get("subdomain") or "").strip(),
            timeout=int(inbox.get("timeout") or 30),
        )

        deadline = time.monotonic() + 180
        last_error = ""
        receipt_matcher = _MailboxReceiptMatcher()
        while time.monotonic() < deadline:
            try:
                messages = mailbox._list_mails("")
                last_error = ""
            except Exception as exc:
                last_error = str(exc).strip()
                time.sleep(5)
                continue
            for message in messages:
                try:
                    cloudmail_match = mailbox._match_alias_receipt(message, target_email)
                except Exception:
                    cloudmail_match = False
                if not cloudmail_match and not receipt_matcher.match_alias_receipt(message, target_email):
                    continue
                content = " ".join(
                    [
                        str(message.get("subject") or ""),
                        str(message.get("content") or ""),
                        str(message.get("text") or ""),
                        str(message.get("html") or ""),
                    ]
                )
                link = self._extract_myalias_verification_link(content)
                if link:
                    return VerificationLinkResolution(
                        kind=requirement.kind,
                        link=link,
                        source="cloudmail_api",
                    )
            time.sleep(3)

        return VerificationLinkResolution(
            kind=requirement.kind,
            error=last_error or "verification link not found",
        )

    @staticmethod
    def _extract_myalias_verification_link(message_content: str) -> str:
        content = str(message_content or "")
        candidates = re.findall(r"https?://[^\s\"'<>]+", content)
        for candidate in candidates:
            normalized = str(candidate or "").strip()
            lowered = normalized.lower()
            if not lowered:
                continue
            if "myalias.pro" not in lowered:
                continue
            if any(token in lowered for token in ("verify", "confirm", "activate", "token", "account-verification")):
                return normalized
        return extract_anchored_link_from_message_content(content, link_anchor="https://")

    def resolve_link(self, *, requirement, spec, context) -> VerificationLinkResolution:
        fetch_confirmation = getattr(self._confirmation_reader, "fetch_confirmation", None)
        if callable(fetch_confirmation):
            result = fetch_confirmation(state=context, source=dict(spec.raw_source or {}))
            link = str(getattr(result, "confirm_url", "") or "").strip()
            if link:
                return VerificationLinkResolution(
                    kind=requirement.kind,
                    link=link,
                    source="confirmation_reader",
                )

        inbox = dict(spec.confirmation_inbox_config or {})
        base_url = str(inbox.get("base_url") or inbox.get("api_base") or "").strip().rstrip("/")
        account_email = str(
            inbox.get("account_email")
            or inbox.get("match_email")
            or context.confirmation_inbox_email
            or ""
        ).strip()
        target_email = str(
            context.service_account_email
            or inbox.get("match_email")
            or inbox.get("account_email")
            or context.confirmation_inbox_email
            or ""
        ).strip()
        account_password = str(inbox.get("account_password") or "").strip()
        if not base_url or not account_email or not account_password:
            return VerificationLinkResolution(
                kind=requirement.kind,
                error="confirmation inbox config incomplete",
            )

        if self._is_myalias_cloudmail_lookup(spec):
            return self._resolve_link_via_cloudmail_mailbox(
                requirement=requirement,
                inbox=inbox,
                target_email=target_email,
            )

        login_request = build_mailbox_login_request(
            mailbox_base_url=base_url,
            mailbox_email=account_email,
            mailbox_password=account_password,
        )
        login_response = self._client.request(
            login_request["method"],
            login_request["url"],
            json=login_request["json"],
        )
        login_payload = getattr(login_response, "json", lambda: {})() if callable(getattr(login_response, "json", None)) else {}
        token = self._extract_token(login_payload if isinstance(login_payload, dict) else {})
        if not token:
            return VerificationLinkResolution(
                kind=requirement.kind,
                error="mailbox token unavailable",
            )

        mail_request = build_mailbox_email_list_request(mailbox_base_url=base_url, token=token)
        mail_response = self._client.request(
            mail_request["method"],
            mail_request["url"],
            params=mail_request["params"],
            headers=mail_request["headers"],
        )
        payload = mail_response.json()
        messages = self._extract_message_list(payload)
        anchor = "https://"
        receipt_matcher = _MailboxReceiptMatcher()
        for message in messages:
            if not receipt_matcher.match_alias_receipt(message, target_email):
                continue
            content = " ".join(
                [
                    str(message.get("subject") or ""),
                    str(message.get("content") or ""),
                    str(message.get("text") or ""),
                    str(message.get("html") or ""),
                ]
            )
            link = extract_anchored_link_from_message_content(content, link_anchor=anchor)
            if link:
                return VerificationLinkResolution(
                    kind=requirement.kind,
                    link=link,
                    source="cloudmail_api",
                )

        return VerificationLinkResolution(
            kind=requirement.kind,
            error="verification link not found",
        )
