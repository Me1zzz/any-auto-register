import json
from typing import Any


VEND_EMAIL_DEFAULT_CONFIG = {
    "source_id": "vend-email-primary",
    "register_url": "https://www.vend.email/auth/register",
    "alias_domain": "serf.me",
    "alias_domain_id": "42",
}


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


def _parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    raw = str(value or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if isinstance(parsed, list):
        return parsed
    return []


def _parse_string(value: Any) -> str:
    return str(value or "").strip()


def _hydrate_explicit_vend_sources(
    explicit_sources: list[dict[str, Any]],
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    hydrated: list[dict[str, Any]] = []
    default_register_url = str(VEND_EMAIL_DEFAULT_CONFIG["register_url"])
    default_alias_domain = str(VEND_EMAIL_DEFAULT_CONFIG["alias_domain"])
    default_alias_domain_id = str(VEND_EMAIL_DEFAULT_CONFIG["alias_domain_id"])

    for source in explicit_sources:
        if str(source.get("type") or "").strip() != "vend_email":
            hydrated.append(source)
            continue

        register_url = _parse_string(source.get("register_url"))
        if not register_url or "vend.example" in register_url:
            register_url = default_register_url

        alias_domain = _parse_string(source.get("alias_domain")) or default_alias_domain
        alias_domain_id = _parse_string(source.get("alias_domain_id")) or default_alias_domain_id

        hydrated.append(
            {
                **source,
                "register_url": register_url,
                "cloudmail_api_base": _parse_string(source.get("cloudmail_api_base"))
                or _parse_string(payload.get("cloudmail_api_base")),
                "cloudmail_admin_email": _parse_string(source.get("cloudmail_admin_email"))
                or _parse_string(payload.get("cloudmail_admin_email")),
                "cloudmail_admin_password": _parse_string(source.get("cloudmail_admin_password"))
                or _parse_string(payload.get("cloudmail_admin_password")),
                "cloudmail_domain": source.get("cloudmail_domain")
                or payload.get("cloudmail_domain")
                or "",
                "cloudmail_subdomain": _parse_string(source.get("cloudmail_subdomain"))
                or _parse_string(payload.get("cloudmail_subdomain")),
                "cloudmail_timeout": _parse_int(
                    source.get("cloudmail_timeout") if source.get("cloudmail_timeout") not in (None, "") else payload.get("cloudmail_timeout"),
                    30,
                ),
                "alias_domain": alias_domain,
                "alias_domain_id": alias_domain_id,
            }
        )

    return hydrated


def _merge_sources(
    explicit_sources: list[dict[str, Any]],
    synthesized_sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []

    def _source_key(source: dict[str, Any]) -> str:
        source_type = str(source.get("type") or "").strip()
        if source_type == "vend_email":
            source_id = str(source.get("id") or "").strip()
            return f"vend:{source_id}"
        return source_type

    by_key: dict[str, dict[str, Any]] = {}

    for source in explicit_sources:
        source_type = str(source.get("type") or "").strip()
        if not source_type:
            continue
        by_key[_source_key(source)] = dict(source)

    for source in synthesized_sources:
        source_type = str(source.get("type") or "").strip()
        if not source_type:
            continue
        source_key = _source_key(source)
        existing = by_key.get(source_key)
        if existing is None:
            by_key[source_key] = dict(source)
            continue
        if source_type == "vend_email":
            merged_source = dict(source)
            merged_source.update(existing)
            for field_key, value in source.items():
                if field_key in {
                    "register_url",
                    "cloudmail_api_base",
                    "cloudmail_admin_email",
                    "cloudmail_admin_password",
                    "cloudmail_domain",
                    "cloudmail_subdomain",
                    "cloudmail_timeout",
                    "alias_domain",
                    "alias_domain_id",
                }:
                    merged_source[field_key] = value
            by_key[source_key] = merged_source

    ordered_keys = ["static_list", "simple_generator"]
    for key in ordered_keys:
        source = by_key.pop(key, None)
        if source is not None:
            merged.append(source)

    vend_keys = sorted(key for key in by_key if key.startswith("vend:"))
    for key in vend_keys:
        source = by_key.pop(key, None)
        if source is not None:
            merged.append(source)

    for source in by_key.values():
        merged.append(source)
    return merged


def _build_cloudmail_alias_sources(payload: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []

    legacy_alias_emails = _parse_alias_emails(payload.get("cloudmail_alias_emails"))

    if _parse_bool(payload.get("cloudmail_alias_service_static_enabled")) and legacy_alias_emails:
        sources.append(
            {
                "id": "legacy-static",
                "type": "static_list",
                "emails": legacy_alias_emails,
            }
        )

    if _parse_bool(payload.get("cloudmail_alias_service_simple_enabled")):
        simple_suffix = _parse_string(payload.get("cloudmail_alias_service_simple_suffix")).lower()
        if simple_suffix:
            sources.append(
                {
                    "id": "cloudmail-simple",
                    "type": "simple_generator",
                    "prefix": _parse_string(payload.get("cloudmail_alias_service_simple_prefix")),
                    "suffix": simple_suffix,
                    "count": max(_parse_int(payload.get("cloudmail_alias_service_simple_count"), 0), 0),
                    "middle_length_min": max(
                        _parse_int(payload.get("cloudmail_alias_service_simple_middle_length_min"), 3),
                        1,
                    ),
                    "middle_length_max": max(
                        _parse_int(payload.get("cloudmail_alias_service_simple_middle_length_max"), 6),
                        1,
                    ),
                }
            )

    if _parse_bool(payload.get("cloudmail_alias_service_vend_enabled")):
        vend_source_id = _parse_string(payload.get("cloudmail_alias_service_vend_source_id")) or str(
            VEND_EMAIL_DEFAULT_CONFIG["source_id"]
        )
        vend_state_key = _parse_string(payload.get("cloudmail_alias_service_vend_state_key")) or vend_source_id
        sources.append(
                {
                    "id": vend_source_id,
                    "type": "vend_email",
                    "register_url": str(VEND_EMAIL_DEFAULT_CONFIG["register_url"]),
                    "cloudmail_api_base": _parse_string(payload.get("cloudmail_api_base")),
                    "cloudmail_admin_email": _parse_string(payload.get("cloudmail_admin_email")),
                    "cloudmail_admin_password": _parse_string(payload.get("cloudmail_admin_password")),
                    "cloudmail_domain": payload.get("cloudmail_domain") or "",
                    "cloudmail_subdomain": _parse_string(payload.get("cloudmail_subdomain")),
                    "cloudmail_timeout": _parse_int(payload.get("cloudmail_timeout"), 30),
                    "alias_domain": str(VEND_EMAIL_DEFAULT_CONFIG["alias_domain"]),
                    "alias_domain_id": str(VEND_EMAIL_DEFAULT_CONFIG["alias_domain_id"]),
                    "alias_count": max(
                    _parse_int(payload.get("cloudmail_alias_service_vend_alias_count"), 0),
                    0,
                ),
                "state_key": vend_state_key,
            }
        )

    normalized_sources: list[dict[str, Any]] = []
    for source in sources:
        source_type = str(source.get("type") or "").strip()
        if source_type == "simple_generator":
            min_length = int(source.get("middle_length_min") or 3)
            max_length = int(source.get("middle_length_max") or min_length)
            if max_length < min_length:
                max_length = min_length
            source["middle_length_min"] = min_length
            source["middle_length_max"] = max_length
        normalized_sources.append(source)

    return normalized_sources


def _normalize_sources(value: Any) -> list[dict[str, Any]]:
    value = _parse_json_list(value)

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
                    "count": max(_parse_int(item.get("count"), 0), 0),
                    "middle_length_min": min_length,
                    "middle_length_max": max_length,
                }
            )
            continue

        if source_type == "vend_email":
            normalized.append(
                {
                    "id": source_id,
                    "type": "vend_email",
                    "register_url": str(item.get("register_url") or "").strip(),
                    "cloudmail_api_base": str(item.get("cloudmail_api_base") or "").strip(),
                    "cloudmail_admin_email": str(item.get("cloudmail_admin_email") or "").strip(),
                    "cloudmail_admin_password": str(item.get("cloudmail_admin_password") or "").strip(),
                    "cloudmail_domain": item.get("cloudmail_domain") or "",
                    "cloudmail_subdomain": str(item.get("cloudmail_subdomain") or "").strip(),
                    "cloudmail_timeout": _parse_int(item.get("cloudmail_timeout"), 30),
                    "alias_domain": str(item.get("alias_domain") or "").strip().lower(),
                    "alias_domain_id": str(item.get("alias_domain_id") or "").strip(),
                    "alias_count": max(_parse_int(item.get("alias_count"), 0), 0),
                    "state_key": str(item.get("state_key") or source_id).strip() or source_id,
                }
            )
    return normalized


def normalize_cloudmail_alias_pool_config(
    extra: dict[str, Any], *, task_id: str
) -> dict[str, Any]:
    payload = dict(extra or {})
    enabled = _parse_bool(payload.get("cloudmail_alias_enabled"))
    explicit_sources = _hydrate_explicit_vend_sources(
        _normalize_sources(payload.get("sources")),
        payload,
    )
    synthesized_sources = _normalize_sources(_build_cloudmail_alias_sources(payload))
    resolved_sources = _merge_sources(explicit_sources, synthesized_sources)
    emails = _parse_alias_emails(payload.get("cloudmail_alias_emails"))

    if not enabled:
        return {
            "enabled": False,
            "task_id": task_id,
            "sources": [],
        }

    return {
        "enabled": True,
        "task_id": task_id,
        "sources": resolved_sources
        or [
            {
                "id": "legacy-static",
                "type": "static_list",
                "emails": emails,
            }
        ],
    }
