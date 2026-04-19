import json
from typing import Any

from .provider_contracts import AliasProviderSourceSpec


VEND_EMAIL_DEFAULT_CONFIG = {
    "source_id": "vend-email-primary",
    "register_url": "https://www.vend.email/auth/register",
    "alias_domain": "serf.me",
    "alias_domain_id": "42",
}

INTERACTIVE_PROVIDER_TYPES = {
    "myalias_pro",
    "secureinseconds",
    "emailshield",
    "simplelogin",
    "alias_email",
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


def _parse_provider_config(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _decode_interactive_source(item: dict[str, Any], source_id: str, provider_type: str) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "id": source_id,
        "type": provider_type,
        "alias_count": max(_parse_int(item.get("alias_count"), 0), 0),
        "state_key": _parse_string(item.get("state_key")) or source_id,
        "provider_config": _parse_provider_config(item.get("provider_config")),
    }
    confirmation_inbox = item.get("confirmation_inbox")
    if isinstance(confirmation_inbox, dict):
        normalized["confirmation_inbox"] = dict(confirmation_inbox)
    return normalized


def _build_vend_confirmation_inbox_config(
    item: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(payload or {})
    raw_confirmation_inbox = item.get("confirmation_inbox")
    confirmation_inbox = raw_confirmation_inbox if isinstance(raw_confirmation_inbox, dict) else {}

    api_base = _parse_string(confirmation_inbox.get("api_base") or confirmation_inbox.get("base_url")) or _parse_string(
        item.get("cloudmail_api_base")
    ) or _parse_string(payload.get("cloudmail_api_base"))
    admin_email = _parse_string(confirmation_inbox.get("admin_email")) or _parse_string(
        item.get("cloudmail_admin_email")
    ) or _parse_string(payload.get("cloudmail_admin_email"))
    admin_password = _parse_string(confirmation_inbox.get("admin_password")) or _parse_string(
        item.get("cloudmail_admin_password")
    ) or _parse_string(payload.get("cloudmail_admin_password"))
    domain = confirmation_inbox.get("domain") or item.get("cloudmail_domain") or payload.get("cloudmail_domain") or ""
    subdomain = _parse_string(confirmation_inbox.get("subdomain")) or _parse_string(
        item.get("cloudmail_subdomain")
    ) or _parse_string(payload.get("cloudmail_subdomain"))
    timeout = _parse_int(
        confirmation_inbox.get("timeout")
        if confirmation_inbox.get("timeout") not in (None, "")
        else item.get("cloudmail_timeout")
        if item.get("cloudmail_timeout") not in (None, "")
        else payload.get("cloudmail_timeout"),
        30,
    )
    account_email = _parse_string(confirmation_inbox.get("account_email") or confirmation_inbox.get("email")) or _parse_string(
        item.get("mailbox_email")
    ) or _parse_string(payload.get("mailbox_email")) or _parse_string(payload.get("cloudmail_alias_mailbox_email"))
    account_password = _parse_string(confirmation_inbox.get("account_password") or confirmation_inbox.get("password")) or _parse_string(
        item.get("mailbox_password")
    ) or _parse_string(payload.get("mailbox_password"))
    base_url = _parse_string(confirmation_inbox.get("base_url")) or _parse_string(item.get("mailbox_base_url")) or _parse_string(
        payload.get("mailbox_base_url")
    )
    match_email = _parse_string(confirmation_inbox.get("match_email")) or account_email
    provider = _parse_string(confirmation_inbox.get("provider"))
    if not provider and any(
        [api_base, admin_email, admin_password, str(domain or "").strip(), subdomain, account_email, account_password, base_url]
    ):
        provider = "cloudmail"

    normalized: dict[str, Any] = {}
    if provider:
        normalized["provider"] = provider
    if api_base:
        normalized["api_base"] = api_base
    if base_url:
        normalized["base_url"] = base_url
    if admin_email:
        normalized["admin_email"] = admin_email
    if admin_password:
        normalized["admin_password"] = admin_password
    if domain:
        normalized["domain"] = domain
    if subdomain:
        normalized["subdomain"] = subdomain
    if normalized:
        normalized["timeout"] = timeout
    if account_email:
        normalized["account_email"] = account_email
    if account_password:
        normalized["account_password"] = account_password
    if match_email:
        normalized["match_email"] = match_email
    return normalized


def _decode_vend_source(item: dict[str, Any], source_id: str) -> dict[str, Any]:
    vend_item: dict[str, Any] = {
        "id": source_id,
        "type": "vend_email",
    }

    ordered_optional_fields = [
        "register_url",
        "cloudmail_api_base",
        "cloudmail_admin_email",
        "cloudmail_admin_password",
        "cloudmail_domain",
        "cloudmail_subdomain",
        "cloudmail_timeout",
        "alias_domain",
        "alias_domain_id",
        "alias_count",
    ]
    for field_name in ordered_optional_fields:
        if field_name in item:
            vend_item[field_name] = item.get(field_name)

    confirmation_inbox = _build_vend_confirmation_inbox_config(item)
    if confirmation_inbox:
        vend_item["confirmation_inbox"] = confirmation_inbox

    provider_config = {
        key: vend_item[key]
        for key in (
            "register_url",
            "cloudmail_api_base",
            "cloudmail_admin_email",
            "cloudmail_admin_password",
            "cloudmail_domain",
            "cloudmail_subdomain",
            "cloudmail_timeout",
            "alias_domain",
            "alias_domain_id",
            "alias_count",
        )
        if key in vend_item
    }
    provider_config["state_key"] = item.get("state_key") or source_id
    if confirmation_inbox:
        provider_config["confirmation_inbox"] = confirmation_inbox
    vend_item["provider_config"] = provider_config

    vend_item["state_key"] = item.get("state_key") or source_id
    return vend_item


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
        confirmation_inbox = _build_vend_confirmation_inbox_config(source, payload)

        hydrated_source = {
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
        if confirmation_inbox:
            hydrated_source["confirmation_inbox"] = confirmation_inbox
        hydrated.append(hydrated_source)

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
                    "confirmation_inbox": _build_vend_confirmation_inbox_config(
                        {
                            "cloudmail_api_base": _parse_string(payload.get("cloudmail_api_base")),
                            "cloudmail_admin_email": _parse_string(payload.get("cloudmail_admin_email")),
                            "cloudmail_admin_password": _parse_string(payload.get("cloudmail_admin_password")),
                            "cloudmail_domain": payload.get("cloudmail_domain") or "",
                            "cloudmail_subdomain": _parse_string(payload.get("cloudmail_subdomain")),
                            "cloudmail_timeout": _parse_int(payload.get("cloudmail_timeout"), 30),
                            "mailbox_email": _parse_string(payload.get("cloudmail_alias_mailbox_email")),
                        }
                    ),
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
            confirmation_inbox = _build_vend_confirmation_inbox_config(item)
            vend_source = {
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
            if confirmation_inbox:
                vend_source["confirmation_inbox"] = confirmation_inbox
            normalized.append(vend_source)
            continue

        if source_type in INTERACTIVE_PROVIDER_TYPES:
            normalized.append(_decode_interactive_source(item, source_id, source_type))
    return normalized


def decode_alias_provider_sources(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        parsed = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    if not isinstance(parsed, list):
        return []

    sanitized: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue

        source_type = _parse_string(item.get("type"))
        source_id = _parse_string(item.get("id"))
        if source_type == "static_list":
            sanitized.append(
                {
                    "id": source_id,
                    "type": "static_list",
                    "emails": _parse_alias_emails(item.get("emails")),
                }
            )
            continue

        if source_type == "simple_generator":
            sanitized.append(
                {
                    "id": source_id,
                    "type": "simple_generator",
                    "prefix": item.get("prefix") or "",
                    "suffix": item.get("suffix") or "",
                    "count": item.get("count"),
                    "middle_length_min": item.get("middle_length_min"),
                    "middle_length_max": item.get("middle_length_max"),
                }
            )
            continue

        if source_type == "vend_email":
            sanitized.append(_decode_vend_source(item, source_id))
            continue

        if source_type in INTERACTIVE_PROVIDER_TYPES:
            sanitized.append(_decode_interactive_source(item, source_id, source_type))

    return sanitized


def encode_alias_provider_sources(value: Any) -> str:
    if value in (None, ""):
        return ""

    sanitized = decode_alias_provider_sources(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return ""
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return ""
        if not isinstance(parsed, list):
            return ""

    return json.dumps(sanitized, ensure_ascii=False)


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


def build_alias_provider_source_specs(pool_config: dict[str, Any]) -> list[AliasProviderSourceSpec]:
    specs: list[AliasProviderSourceSpec] = []

    for source in list(pool_config.get("sources") or []):
        provider_type = _parse_string(source.get("type"))
        source_id = _parse_string(source.get("id"))
        if not provider_type or not source_id:
            continue

        confirmation_inbox_config: dict[str, Any] = {}
        provider_config: dict[str, Any] = {}
        if provider_type == "vend_email":
            confirmation_inbox_config = {
                "api_base": _parse_string(source.get("cloudmail_api_base")),
                "admin_email": _parse_string(source.get("cloudmail_admin_email")),
                "admin_password": _parse_string(source.get("cloudmail_admin_password")),
                "domain": source.get("cloudmail_domain") or "",
                "subdomain": _parse_string(source.get("cloudmail_subdomain")),
                "timeout": _parse_int(source.get("cloudmail_timeout"), 30),
            }
            explicit_confirmation_inbox = source.get("confirmation_inbox")
            if isinstance(explicit_confirmation_inbox, dict):
                for key in (
                    "provider",
                    "base_url",
                    "api_base",
                    "admin_email",
                    "admin_password",
                    "domain",
                    "subdomain",
                    "timeout",
                    "account_email",
                    "account_password",
                    "match_email",
                ):
                    value = explicit_confirmation_inbox.get(key)
                    if value in (None, ""):
                        continue
                    confirmation_inbox_config[key] = value
            provider_config = _parse_provider_config(source.get("provider_config"))
            if not provider_config:
                provider_config = _decode_vend_source(source, source_id).get("provider_config", {})
        if provider_type in INTERACTIVE_PROVIDER_TYPES:
            provider_config = _parse_provider_config(source.get("provider_config"))
            explicit_confirmation_inbox = source.get("confirmation_inbox")
            if isinstance(explicit_confirmation_inbox, dict):
                confirmation_inbox_config = dict(explicit_confirmation_inbox)

        specs.append(
            AliasProviderSourceSpec(
                source_id=source_id,
                provider_type=provider_type,
                state_key=_parse_string(source.get("state_key")) or source_id,
                desired_alias_count=max(
                    _parse_int(
                        source.get("alias_count")
                        if source.get("alias_count") not in (None, "")
                        else source.get("count"),
                        0,
                    ),
                    0,
                ),
                confirmation_inbox_config=confirmation_inbox_config,
                provider_config=provider_config,
                raw_source=dict(source),
                register_url=_parse_string(source.get("register_url")),
                alias_domain=_parse_string(source.get("alias_domain")).lower(),
                alias_domain_id=_parse_string(source.get("alias_domain_id")),
            )
        )

    return specs
