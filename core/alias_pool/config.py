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


def _parse_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_sources(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue

        source_type = str(item.get("type") or "").strip()
        source_id = str(item.get("id") or f"source-{index + 1}").strip() or f"source-{index + 1}"

        if source_type == "static_list":
            normalized.append(
                {
                    "id": source_id,
                    "type": "static_list",
                    "emails": _parse_alias_emails(item.get("emails")),
                    "mailbox_email": str(item.get("mailbox_email") or "").strip().lower(),
                }
            )
            continue

        if source_type == "simple_generator":
            min_length = _parse_int(item.get("middle_length_min"), 3)
            max_length = _parse_int(item.get("middle_length_max"), 6)
            if min_length <= 0:
                min_length = 3
            if max_length < min_length:
                max_length = min_length

            normalized.append(
                {
                    "id": source_id,
                    "type": "simple_generator",
                    "prefix": str(item.get("prefix") or "").strip(),
                    "suffix": str(item.get("suffix") or "").strip().lower(),
                    "mailbox_email": str(item.get("mailbox_email") or "").strip().lower(),
                    "count": max(_parse_int(item.get("count"), 0), 0),
                    "middle_length_min": min_length,
                    "middle_length_max": max_length,
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
