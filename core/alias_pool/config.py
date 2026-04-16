from typing import Any


def _parse_alias_emails(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        raw = str(value or "").strip()
        items = raw.splitlines() if raw else []

    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        email = str(item or "").strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        result.append(email)
    return result


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_sources(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        source_type = str(item.get("type") or "").strip()
        if source_type != "static_list":
            continue

        normalized.append(
            {
                "id": str(item.get("id") or f"static-{index + 1}").strip()
                or f"static-{index + 1}",
                "type": "static_list",
                "emails": _parse_alias_emails(item.get("emails")),
                "mailbox_email": str(item.get("mailbox_email") or "").strip().lower(),
            }
        )
    return normalized


def normalize_cloudmail_alias_pool_config(
    extra: dict[str, Any], *, task_id: str
) -> dict[str, Any]:
    payload = dict(extra or {})
    enabled = _parse_bool(payload.get("cloudmail_alias_enabled"))
    explicit_sources = _normalize_sources(payload.get("sources"))
    emails = _parse_alias_emails(payload.get("cloudmail_alias_emails"))
    mailbox_email = str(payload.get("cloudmail_alias_mailbox_email") or "").strip().lower()

    if not enabled:
        return {
            "enabled": False,
            "task_id": task_id,
            "sources": [],
        }

    return {
        "enabled": True,
        "task_id": task_id,
        "sources": explicit_sources
        or [
            {
                "id": "legacy-static",
                "type": "static_list",
                "emails": emails,
                "mailbox_email": mailbox_email,
            }
        ],
    }
