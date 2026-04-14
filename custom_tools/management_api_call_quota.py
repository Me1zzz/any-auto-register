#!/usr/bin/env python3
"""Query a credential's upstream quota through CLIProxyAPI management API.

This script uses the current project's management endpoints in two steps:

1. GET /v0/management/auth-files
   Resolve the target credential's ``auth_index`` when only a credential name
   or id is known.
2. POST /v0/management/api-call
   Ask CLIProxyAPI to make the real upstream quota request on behalf of that
   credential.

Important:
- ``/v0/management/api-call`` is a generic forwarding endpoint.
- To match the real manager behavior more closely, this script can now infer
  a built-in request recipe for known credential types instead of always
  requiring ``--upstream-url``.
- The only auto recipe grounded by the current repo plus your runtime log is
  OpenAI/Codex/ChatGPT usage refresh via ``https://chatgpt.com/backend-api/wham/usage``.
- The special token placeholder ``$TOKEN$`` in headers is resolved by
  CLIProxyAPI using the selected credential.

Examples
--------
Auto-detect recipe from an OpenAI/Codex credential:

    python scripts/management_api_call_quota.py \
        --base-url http://127.0.0.1:8317 \
        --management-key YOUR_KEY \
        --credential-name my-openai-auth.json

Query a single account directly by auth file name:

    python scripts/management_api_call_quota.py \
        --base-url http://127.0.0.1:8317 \
        --management-key YOUR_KEY \
        --auth-name cheryl4a93a6@hth.hush2u.com.json

List quota usage for every auth entry using per-account auto recipe inference:

    python scripts/management_api_call_quota.py \
        --base-url http://127.0.0.1:8317 \
        --management-key YOUR_KEY \
        --list-all-quota

Force the OpenAI/ChatGPT usage recipe by auth_index:

    python scripts/management_api_call_quota.py \
        --base-url http://127.0.0.1:8317 \
        --management-key YOUR_KEY \
        --auth-index openai-1 \
        --recipe openai-wham-usage

Manual override when the provider has no built-in recipe yet:

    python scripts/management_api_call_quota.py \
        --base-url http://127.0.0.1:8317 \
        --management-key YOUR_KEY \
        --credential-name my-credential.json \
        --recipe manual \
        --upstream-url https://example.com/v1/quota \
        --header 'x-api-key=$TOKEN$' \
        --header 'Accept=application/json'
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests


DEFAULT_BASE_URL = "http://127.0.0.1:8317"
DEFAULT_TIMEOUT_SECONDS = 60.0
PREFIXED_JSON_FILE_PATTERN = re.compile(r"^(?P<prefix>\d{6})___(?P<name>.+)$")


@dataclass(frozen=True)
class RequestRecipe:
    name: str
    method: str
    url: str
    headers: Dict[str, str]
    data: str = ""


@dataclass(frozen=True)
class QuotaTableRow:
    auth_index: str
    name: str
    upstream_status_code: Optional[int]
    used_percent: Optional[float]
    quota_refresh_time: Optional[str]
    error: str = ""


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Call CLIProxyAPI management /v0/management/api-call to query an "
            "upstream quota endpoint for a specific credential."
        )
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("CLIPROXY_BASE_URL", DEFAULT_BASE_URL),
        help=(
            "CLIProxyAPI base URL. Defaults to CLIPROXY_BASE_URL or "
            f"{DEFAULT_BASE_URL}."
        ),
    )
    parser.add_argument(
        "--management-key",
        default=os.getenv("CLIPROXY_MANAGEMENT_KEY") or os.getenv("MANAGEMENT_KEY"),
        help="Management API key. Defaults to CLIPROXY_MANAGEMENT_KEY or MANAGEMENT_KEY.",
    )
    parser.add_argument(
        "--auth-index",
        help="Target credential auth_index. If omitted, the script will resolve it from auth-files.",
    )
    parser.add_argument(
        "--credential-name",
        "--name",
        "--auth-name",
        dest="credential_name",
        metavar="AUTH_FILE_NAME",
        help=(
            "Resolve auth_index by the credential/auth file name from "
            "/v0/management/auth-files. --credential-name remains supported; "
            "you can also use --name or --auth-name."
        ),
    )
    parser.add_argument(
        "--credential-id",
        help="Resolve auth_index by the credential's id field from /v0/management/auth-files.",
    )
    parser.add_argument(
        "--list-all-quota",
        action="store_true",
        help=(
            "Fetch /v0/management/auth-files and print one quota row per credential. "
            "Best used with --recipe auto; accounts whose recipe cannot be inferred are "
            "reported in the error column instead of aborting the whole batch."
        ),
    )
    parser.add_argument(
        "--json-dir",
        "--json_dir",
        dest="json_dir",
        help=(
            "When used with --list-all-quota, look for matching local JSON files in this "
            "directory. Files whose yymmdd___ prefix date is today or later (UTC) are skipped "
            "without requesting a new refresh time; older files are refreshed and renamed "
            "using the new refresh date plus one day."
        ),
    )
    parser.add_argument(
        "--recipe",
        choices=["auto", "openai-wham-usage", "manual"],
        default="auto",
        help=(
            "Request recipe to use. 'auto' infers a built-in recipe from the matched "
            "credential, 'openai-wham-usage' forces the ChatGPT usage endpoint, and "
            "'manual' requires --upstream-url. Defaults to auto."
        ),
    )
    parser.add_argument(
        "--upstream-url",
        help="Manual upstream quota endpoint URL. Required only when --recipe=manual.",
    )
    parser.add_argument(
        "--upstream-method",
        default="GET",
        help="HTTP method used for the upstream quota request. Defaults to GET.",
    )
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help=(
            "Repeatable upstream request header. When omitted, built-in recipes use their "
            "own defaults; manual mode uses Authorization=Bearer $TOKEN$ and "
            "Accept=application/json."
        ),
    )
    parser.add_argument(
        "--data",
        default="",
        help="Optional raw request body string passed to /v0/management/api-call as data.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"HTTP timeout in seconds. Defaults to {DEFAULT_TIMEOUT_SECONDS}.",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification for requests from this script to CLIProxyAPI.",
    )
    return parser


def normalize_base_url(base_url: str) -> str:
    value = base_url.strip()
    if not value:
        raise ValueError("base-url cannot be empty")
    return value.rstrip("/")


def parse_headers(raw_headers: Iterable[str]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for item in raw_headers:
        if "=" not in item:
            raise ValueError(f"invalid --header value {item!r}; expected KEY=VALUE")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"invalid --header value {item!r}; header name cannot be empty")
        headers[key] = value
    if headers:
        return headers
    return {}


def manual_default_headers() -> Dict[str, str]:
    return {
        "Authorization": "Bearer $TOKEN$",
        "Accept": "application/json",
    }


def build_management_headers(management_key: str) -> Dict[str, str]:
    if not management_key.strip():
        raise ValueError("management key cannot be empty")
    return {
        "Authorization": f"Bearer {management_key.strip()}",
        "Content-Type": "application/json",
    }


def fetch_auth_files(
    session: requests.Session,
    base_url: str,
    timeout: float,
) -> List[Dict[str, Any]]:
    response = session.get(f"{base_url}/v0/management/auth-files", timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    files = payload.get("files", [])
    if not isinstance(files, list):
        raise RuntimeError("unexpected /v0/management/auth-files response: files is not a list")
    normalized: List[Dict[str, Any]] = []
    for item in files:
        if isinstance(item, dict):
            normalized.append(item)
    return normalized


def find_matching_auth_entries(
    auth_files: List[Dict[str, Any]],
    auth_index: Optional[str],
    credential_name: Optional[str],
    credential_id: Optional[str],
) -> List[Dict[str, Any]]:
    normalized_auth_index = (auth_index or "").strip()
    normalized_name = (credential_name or "").strip()
    normalized_id = (credential_id or "").strip()

    matches: List[Dict[str, Any]] = []
    for item in auth_files:
        item_auth_index = str(item.get("auth_index") or "").strip()
        item_name = str(item.get("name") or "").strip()
        item_id = str(item.get("id") or "").strip()

        if normalized_auth_index and item_auth_index == normalized_auth_index:
            matches.append(item)
            continue
        if normalized_name and item_name == normalized_name:
            matches.append(item)
            continue
        if normalized_id and item_id == normalized_id:
            matches.append(item)

    return matches


def resolve_target_auth(
    auth_files: List[Dict[str, Any]],
    auth_index: Optional[str],
    credential_name: Optional[str],
    credential_id: Optional[str],
) -> Tuple[str, Optional[Dict[str, Any]]]:
    normalized_auth_index = (auth_index or "").strip()
    if normalized_auth_index and not credential_name and not credential_id:
        matches = find_matching_auth_entries(auth_files, normalized_auth_index, None, None)
        if len(matches) == 1:
            return normalized_auth_index, matches[0]
        if len(matches) > 1:
            raise RuntimeError(
                "multiple credentials share the same auth_index unexpectedly:\n"
                + json.dumps(matches, ensure_ascii=False, indent=2)
            )
        return normalized_auth_index, None

    if not credential_name and not credential_id:
        raise ValueError(
            "please provide --auth-index, or use --credential-name / --auth-name / --name / --credential-id to resolve it"
        )

    matches = find_matching_auth_entries(auth_files, normalized_auth_index, credential_name, credential_id)

    if not matches:
        available = [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "auth_index": item.get("auth_index"),
                "provider": item.get("provider") or item.get("type"),
            }
            for item in auth_files
        ]
        raise RuntimeError(
            "target credential not found in /v0/management/auth-files. Available credentials:\n"
            + json.dumps(available, ensure_ascii=False, indent=2)
        )

    if len(matches) > 1:
        raise RuntimeError(
            "multiple credentials matched; please use --auth-index or a more specific id/name:\n"
            + json.dumps(matches, ensure_ascii=False, indent=2)
        )

    value = str(matches[0].get("auth_index") or "").strip()
    if not value:
        raise RuntimeError("matched credential does not contain auth_index")
    return value, matches[0]


def normalized_auth_text(auth_entry: Optional[Dict[str, Any]]) -> str:
    if not auth_entry:
        return ""
    parts = [
        str(auth_entry.get("provider") or ""),
        str(auth_entry.get("type") or ""),
        str(auth_entry.get("name") or ""),
        str(auth_entry.get("id") or ""),
        str(auth_entry.get("label") or ""),
        str(auth_entry.get("path") or ""),
        str(auth_entry.get("email") or ""),
    ]
    return " ".join(parts).strip().lower()


def infer_recipe_name(auth_entry: Optional[Dict[str, Any]]) -> Optional[str]:
    text = normalized_auth_text(auth_entry)
    if not text:
        return None

    openai_markers = (
        "openai",
        "codex",
        "chatgpt",
    )
    if any(marker in text for marker in openai_markers):
        return "openai-wham-usage"
    return None


def recipe_for_name(recipe_name: str) -> RequestRecipe:
    if recipe_name == "openai-wham-usage":
        return RequestRecipe(
            name="openai-wham-usage",
            method="GET",
            url="https://chatgpt.com/backend-api/wham/usage",
            headers={
                "Authorization": "Bearer $TOKEN$",
                "Accept": "application/json, text/plain, */*",
                "User-Agent": "Mozilla/5.0",
            },
        )
    raise ValueError(f"unsupported recipe: {recipe_name}")


def build_manual_recipe(
    upstream_method: str,
    upstream_url: Optional[str],
    raw_headers: Iterable[str],
    data: str,
) -> RequestRecipe:
    url = (upstream_url or "").strip()
    if not url:
        raise ValueError("--upstream-url is required when --recipe=manual")
    headers = parse_headers(raw_headers) or manual_default_headers()
    return RequestRecipe(
        name="manual",
        method=upstream_method.strip().upper() or "GET",
        url=url,
        headers=headers,
        data=data,
    )


def resolve_recipe(
    recipe_name: str,
    auth_entry: Optional[Dict[str, Any]],
    upstream_method: str,
    upstream_url: Optional[str],
    raw_headers: Iterable[str],
    data: str,
) -> RequestRecipe:
    explicit_headers = parse_headers(raw_headers)

    if recipe_name == "manual":
        return build_manual_recipe(upstream_method, upstream_url, raw_headers, data)

    inferred_name = recipe_name
    if recipe_name == "auto":
        if upstream_url:
            return build_manual_recipe(upstream_method, upstream_url, raw_headers, data)
        inferred_name = infer_recipe_name(auth_entry)
        if not inferred_name:
            auth_preview = {
                "provider": auth_entry.get("provider") if auth_entry else None,
                "type": auth_entry.get("type") if auth_entry else None,
                "name": auth_entry.get("name") if auth_entry else None,
                "id": auth_entry.get("id") if auth_entry else None,
                "auth_index": auth_entry.get("auth_index") if auth_entry else None,
            }
            raise RuntimeError(
                "could not infer a built-in quota recipe for this credential. "
                "Use --recipe manual --upstream-url ... or force a known recipe.\n"
                + json.dumps(auth_preview, ensure_ascii=False, indent=2)
            )

    recipe = recipe_for_name(inferred_name)
    headers = dict(recipe.headers)
    headers.update(explicit_headers)
    payload_data = data if data else recipe.data
    method = upstream_method.strip().upper() if upstream_method.strip() else recipe.method
    url = (upstream_url or "").strip() or recipe.url
    return RequestRecipe(
        name=recipe.name,
        method=method,
        url=url,
        headers=headers,
        data=payload_data,
    )


def call_management_api_call(
    session: requests.Session,
    base_url: str,
    timeout: float,
    auth_index: str,
    recipe: RequestRecipe,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "auth_index": auth_index,
        "method": recipe.method.strip().upper(),
        "url": recipe.url.strip(),
        "header": recipe.headers,
    }
    if recipe.data:
        payload["data"] = recipe.data

    response = session.post(
        f"{base_url}/v0/management/api-call",
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise RuntimeError("unexpected /v0/management/api-call response")
    return result


def compact_text(value: Any, *, max_length: int = 160) -> str:
    text = "" if value is None else " ".join(str(value).split())
    if not text:
        return "-"
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def combine_error_messages(*messages: Optional[str]) -> str:
    parts: List[str] = []
    seen = set()
    for message in messages:
        text = (message or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        parts.append(text)
    return " | ".join(parts)


def auth_name_for_display(auth_entry: Optional[Dict[str, Any]]) -> str:
    if not auth_entry:
        return ""
    return str(
        auth_entry.get("name")
        or auth_entry.get("label")
        or auth_entry.get("email")
        or auth_entry.get("path")
        or ""
    ).strip()


def normalize_json_file_name(file_name: str) -> str:
    match = PREFIXED_JSON_FILE_PATTERN.match(file_name)
    if not match:
        return file_name
    return match.group("name")


def parse_prefixed_refresh_date(file_name: str) -> Optional[date]:
    match = PREFIXED_JSON_FILE_PATTERN.match(file_name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group("prefix"), "%y%m%d").date()
    except ValueError:
        return None


def parse_formatted_utc_datetime(value: Optional[str]) -> Optional[datetime]:
    text = (value or "").strip()
    if not text or text == "-":
        return None
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


def build_prefixed_json_file_name(original_name: str, refresh_time: datetime) -> str:
    prefix = (refresh_time.astimezone(timezone.utc).date() + timedelta(days=1)).strftime("%y%m%d")
    return f"{prefix}___{normalize_json_file_name(original_name)}"


def build_json_dir_file_index(json_dir: Path) -> Dict[str, Path]:
    index: Dict[str, Path] = {}
    for file_path in sorted(json_dir.glob("*.json")):
        normalized_name = normalize_json_file_name(file_path.name)
        index.setdefault(normalized_name, file_path)
    return index


def auth_entry_json_file_candidates(auth_entry: Dict[str, Any]) -> List[str]:
    candidates: List[str] = []
    for raw_value in (auth_entry.get("name"), auth_entry.get("path")):
        text = str(raw_value or "").strip()
        if not text:
            continue
        candidate = normalize_json_file_name(Path(text).name)
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def resolve_auth_entry_json_file(auth_entry: Dict[str, Any], json_file_index: Dict[str, Path]) -> Optional[Path]:
    for candidate in auth_entry_json_file_candidates(auth_entry):
        matched = json_file_index.get(candidate)
        if matched is not None:
            return matched
    return None


def rename_json_file_for_refresh(file_path: Path, quota_refresh_time: Optional[str]) -> Optional[str]:
    refresh_time = parse_formatted_utc_datetime(quota_refresh_time)
    if refresh_time is None:
        return "cannot rename without a valid quota refresh time"

    target_name = build_prefixed_json_file_name(file_path.name, refresh_time)
    target_path = file_path.with_name(target_name)
    if target_path == file_path:
        return ""
    if target_path.exists():
        return f"rename target already exists: {target_path.name}"
    file_path.rename(target_path)
    return ""


def should_skip_refresh_for_file(file_path: Path, current_utc_date: date) -> bool:
    prefixed_date = parse_prefixed_refresh_date(file_path.name)
    if prefixed_date is None:
        return False
    return prefixed_date >= current_utc_date


def should_skip_refresh_for_auth_entry(auth_entry: Dict[str, Any], current_utc_date: date) -> bool:
    for raw_value in (auth_entry.get("name"), auth_entry.get("path")):
        text = str(raw_value or "").strip()
        if not text:
            continue
        prefixed_date = parse_prefixed_refresh_date(Path(text).name)
        if prefixed_date is not None:
            return prefixed_date >= current_utc_date
    return False


def coerce_optional_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            return int(text)
    return None


def decode_management_result_body(result: Dict[str, Any]) -> Any:
    body = result.get("body")
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"failed to decode upstream body JSON from management wrapper: {exc.msg}"
            ) from exc
    if body is None:
        raise RuntimeError("management wrapper body is empty")
    return body


def extract_used_percent_from_parsed_body(parsed_body: Any) -> float:
    if not isinstance(parsed_body, dict):
        raise RuntimeError("upstream body JSON is not an object")

    rate_limit = parsed_body.get("rate_limit")
    if not isinstance(rate_limit, dict):
        raise RuntimeError("missing rate_limit in upstream body")

    primary_window = rate_limit.get("primary_window")
    if not isinstance(primary_window, dict):
        raise RuntimeError("missing rate_limit.primary_window in upstream body")

    used_percent = primary_window.get("used_percent")
    if isinstance(used_percent, bool):
        raise RuntimeError("rate_limit.primary_window.used_percent must not be boolean")
    if isinstance(used_percent, (int, float)):
        return float(used_percent)
    if isinstance(used_percent, str):
        text = used_percent.strip()
        if not text:
            raise RuntimeError("rate_limit.primary_window.used_percent is empty")
        try:
            return float(text)
        except ValueError as exc:
            raise RuntimeError(
                "rate_limit.primary_window.used_percent is not numeric"
            ) from exc
    raise RuntimeError("missing rate_limit.primary_window.used_percent in upstream body")


def extract_used_percent_from_result(result: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
    try:
        parsed_body = decode_management_result_body(result)
        return extract_used_percent_from_parsed_body(parsed_body), None
    except Exception as exc:  # noqa: BLE001 - per-row extraction errors are reported in output.
        return None, compact_text(str(exc))


def format_utc_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def extract_quota_refresh_time_from_parsed_body(parsed_body: Any) -> str:
    if not isinstance(parsed_body, dict):
        raise RuntimeError("upstream body JSON is not an object")

    rate_limit = parsed_body.get("rate_limit")
    if not isinstance(rate_limit, dict):
        raise RuntimeError("missing rate_limit in upstream body")

    primary_window = rate_limit.get("primary_window")
    if not isinstance(primary_window, dict):
        raise RuntimeError("missing rate_limit.primary_window in upstream body")

    reset_at = primary_window.get("reset_at")
    if isinstance(reset_at, bool):
        raise RuntimeError("rate_limit.primary_window.reset_at must not be boolean")
    if isinstance(reset_at, (int, float)):
        try:
            return format_utc_datetime(datetime.fromtimestamp(float(reset_at), tz=timezone.utc))
        except (OverflowError, OSError, ValueError) as exc:
            raise RuntimeError("rate_limit.primary_window.reset_at is not a valid unix timestamp") from exc
    if isinstance(reset_at, str):
        text = reset_at.strip()
        if text:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError as exc:
                raise RuntimeError("rate_limit.primary_window.reset_at is not a valid ISO datetime") from exc
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return format_utc_datetime(parsed)

    reset_after_seconds = primary_window.get("reset_after_seconds")
    if isinstance(reset_after_seconds, bool):
        raise RuntimeError("rate_limit.primary_window.reset_after_seconds must not be boolean")
    if isinstance(reset_after_seconds, (int, float)):
        try:
            reset_time = datetime.now(timezone.utc).timestamp() + float(reset_after_seconds)
            return format_utc_datetime(datetime.fromtimestamp(reset_time, tz=timezone.utc))
        except (OverflowError, OSError, ValueError) as exc:
            raise RuntimeError(
                "rate_limit.primary_window.reset_after_seconds is not a valid duration"
            ) from exc
    if isinstance(reset_after_seconds, str):
        text = reset_after_seconds.strip()
        if not text:
            raise RuntimeError("rate_limit.primary_window.reset_after_seconds is empty")
        try:
            seconds = float(text)
        except ValueError as exc:
            raise RuntimeError(
                "rate_limit.primary_window.reset_after_seconds is not numeric"
            ) from exc
        reset_time = datetime.now(timezone.utc).timestamp() + seconds
        return format_utc_datetime(datetime.fromtimestamp(reset_time, tz=timezone.utc))

    raise RuntimeError(
        "missing rate_limit.primary_window.reset_at or reset_after_seconds in upstream body"
    )


def extract_quota_refresh_time_from_result(result: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    try:
        parsed_body = decode_management_result_body(result)
        return extract_quota_refresh_time_from_parsed_body(parsed_body), None
    except Exception as exc:  # noqa: BLE001 - per-row extraction errors are reported in output.
        return None, compact_text(str(exc))


def format_used_percent(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{value:.4f}".rstrip("0").rstrip(".")


def format_status_code(value: Optional[int]) -> str:
    if value is None:
        return "-"
    return str(value)


def quota_table_headers() -> List[str]:
    return [
        "auth_index",
        "name",
        "upstream_status_code",
        "used_percent",
        "额度的刷新时间",
        "error",
    ]


def render_quota_table_row(row: QuotaTableRow) -> List[str]:
    return [
        compact_text(row.auth_index),
        compact_text(row.name),
        format_status_code(row.upstream_status_code),
        format_used_percent(row.used_percent),
        compact_text(row.quota_refresh_time),
        compact_text(row.error),
    ]


def format_quota_table_line(rendered_row: List[str], column_widths: List[int]) -> str:
    return " | ".join(
        value.ljust(column_widths[index]) for index, value in enumerate(rendered_row)
    )


def build_quota_table_column_widths(rendered_rows: List[List[str]]) -> List[int]:
    return [
        max(len(rendered_row[index]) for rendered_row in rendered_rows)
        for index in range(len(rendered_rows[0]))
    ]


def expected_batch_recipe_name(
    recipe_name: str,
    auth_entry: Dict[str, Any],
    upstream_url: Optional[str],
) -> str:
    if recipe_name == "manual" or upstream_url:
        return "manual"
    if recipe_name != "auto":
        return recipe_name
    return infer_recipe_name(auth_entry) or recipe_name


def build_streaming_quota_table_column_widths(
    auth_files: List[Dict[str, Any]],
    recipe_name: str,
    upstream_url: Optional[str],
) -> List[int]:
    rendered_rows: List[List[str]] = [quota_table_headers()]
    for auth_entry in auth_files:
        rendered_rows.append(
            render_quota_table_row(
                QuotaTableRow(
                    auth_index=str(auth_entry.get("auth_index") or "").strip() or "-",
                    name=auth_name_for_display(auth_entry),
                    upstream_status_code=None,
                    used_percent=None,
                    quota_refresh_time=None,
                    error="",
                )
            )
        )
    return build_quota_table_column_widths(rendered_rows)


def render_quota_table(rows: List[QuotaTableRow]) -> str:
    headers = quota_table_headers()
    rendered_rows: List[List[str]] = [headers]
    for row in rows:
        rendered_rows.append(render_quota_table_row(row))

    column_widths = build_quota_table_column_widths(rendered_rows)

    lines: List[str] = []
    for row_index, rendered_row in enumerate(rendered_rows):
        lines.append(format_quota_table_line(rendered_row, column_widths))
        if row_index == 0:
            lines.append("-+-".join("-" * width for width in column_widths))
    return "\n".join(lines)


def build_batch_row(
    session: requests.Session,
    base_url: str,
    timeout: float,
    auth_entry: Dict[str, Any],
    recipe_name: str,
    upstream_method: str,
    upstream_url: Optional[str],
    raw_headers: Iterable[str],
    data: str,
) -> QuotaTableRow:
    auth_index = str(auth_entry.get("auth_index") or "").strip()
    name = auth_name_for_display(auth_entry)

    if not auth_index:
        return QuotaTableRow(
            auth_index="-",
            name=name,
            upstream_status_code=None,
            used_percent=None,
            quota_refresh_time=None,
            error="missing auth_index",
        )

    try:
        recipe = resolve_recipe(
            recipe_name=recipe_name,
            auth_entry=auth_entry,
            upstream_method=upstream_method,
            upstream_url=upstream_url,
            raw_headers=raw_headers,
            data=data,
        )
        result = call_management_api_call(
            session=session,
            base_url=base_url,
            timeout=timeout,
            auth_index=auth_index,
            recipe=recipe,
        )
        used_percent, extraction_error = extract_used_percent_from_result(result)
        quota_refresh_time, refresh_error = extract_quota_refresh_time_from_result(result)
        return QuotaTableRow(
            auth_index=auth_index,
            name=name,
            upstream_status_code=coerce_optional_int(result.get("status_code")),
            used_percent=used_percent,
            quota_refresh_time=quota_refresh_time,
            error=combine_error_messages(extraction_error, refresh_error),
        )
    except requests.HTTPError as exc:
        response = exc.response
        response_text = response.text if response is not None else str(exc)
        return QuotaTableRow(
            auth_index=auth_index,
            name=name,
            upstream_status_code=None,
            used_percent=None,
            quota_refresh_time=None,
            error=compact_text(response_text),
        )
    except requests.RequestException as exc:
        return QuotaTableRow(
            auth_index=auth_index,
            name=name,
            upstream_status_code=None,
            used_percent=None,
            quota_refresh_time=None,
            error=compact_text(str(exc)),
        )
    except Exception as exc:  # noqa: BLE001 - per-row failures belong in the table output.
        return QuotaTableRow(
            auth_index=auth_index,
            name=name,
            upstream_status_code=None,
            used_percent=None,
            quota_refresh_time=None,
            error=compact_text(str(exc)),
        )


def print_all_quota_results(
    session: requests.Session,
    base_url: str,
    timeout: float,
    auth_files: List[Dict[str, Any]],
    recipe_name: str,
    upstream_method: str,
    upstream_url: Optional[str],
    raw_headers: Iterable[str],
    data: str,
    json_dir: Optional[Path],
) -> None:
    if not auth_files:
        print("No auth entries found in /v0/management/auth-files.")
        return

    json_file_index = build_json_dir_file_index(json_dir) if json_dir is not None else {}
    current_utc_date = datetime.now(timezone.utc).date()

    headers = quota_table_headers()
    column_widths = build_streaming_quota_table_column_widths(
        auth_files=auth_files,
        recipe_name=recipe_name,
        upstream_url=upstream_url,
    )
    print(format_quota_table_line(headers, column_widths), flush=True)
    print("-+-".join("-" * width for width in column_widths), flush=True)

    for auth_entry in auth_files:
        if json_file_index and should_skip_refresh_for_auth_entry(auth_entry, current_utc_date):
            row = QuotaTableRow(
                auth_index=str(auth_entry.get("auth_index") or "").strip() or "-",
                name=auth_name_for_display(auth_entry),
                upstream_status_code=None,
                used_percent=None,
                quota_refresh_time=None,
                error="skipped refresh by auth-file name prefix",
            )
            print(format_quota_table_line(render_quota_table_row(row), column_widths), flush=True)
            continue

        json_file_path = (
            resolve_auth_entry_json_file(auth_entry, json_file_index) if json_file_index else None
        )
        if json_file_path is not None and should_skip_refresh_for_file(json_file_path, current_utc_date):
            row = QuotaTableRow(
                auth_index=str(auth_entry.get("auth_index") or "").strip() or "-",
                name=auth_name_for_display(auth_entry),
                upstream_status_code=None,
                used_percent=None,
                quota_refresh_time=None,
                error=f"skipped refresh by filename date: {json_file_path.name}",
            )
            print(format_quota_table_line(render_quota_table_row(row), column_widths), flush=True)
            continue

        row = build_batch_row(
            session=session,
            base_url=base_url,
            timeout=timeout,
            auth_entry=auth_entry,
            recipe_name=recipe_name,
            upstream_method=upstream_method,
            upstream_url=upstream_url,
            raw_headers=raw_headers,
            data=data,
        )
        if json_file_path is not None:
            rename_error = rename_json_file_for_refresh(json_file_path, row.quota_refresh_time)
            if rename_error:
                row = replace(row, error=combine_error_messages(row.error, rename_error))
        print(format_quota_table_line(render_quota_table_row(row), column_widths), flush=True)


def print_result(auth_index: str, recipe: RequestRecipe, result: Dict[str, Any]) -> None:
    # print(f"auth_index: {auth_index}")
    # print(f"recipe: {recipe.name}")
    # print(f"upstream_method: {recipe.method}")
    # print(f"upstream_url: {recipe.url}")
    # print(f"upstream_status_code: {result.get('status_code')}")
    # print("upstream_headers:")
    # print(json.dumps(result.get("header", {}), ensure_ascii=False, indent=2))

    body = result.get("body", "")
    print("upstream_body:")
    if isinstance(body, str):
        try:
            parsed = decode_management_result_body(result)
        except RuntimeError:
            print(body)
            return
        # print(json.dumps(parsed, ensure_ascii=False, indent=2))
        if "rate_limit" in parsed:
            print(parsed["rate_limit"])
        else:
            print(parsed)
        return

    # print(json.dumps(body, ensure_ascii=False, indent=2))
    print(body["rate_limit"])

def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()

    try:
        base_url = normalize_base_url(args.base_url)
        management_key = args.management_key or ""
        if not management_key.strip():
            raise ValueError("--management-key is required (or set CLIPROXY_MANAGEMENT_KEY)")

        session = requests.Session()
        session.verify = not args.insecure
        session.headers.update(build_management_headers(management_key))

        json_dir: Optional[Path] = None
        if args.json_dir:
            if not args.list_all_quota:
                raise ValueError("--json-dir can only be used together with --list-all-quota")
            json_dir = Path(args.json_dir).expanduser()
            if not json_dir.is_dir():
                raise ValueError(f"json-dir is not a directory: {json_dir}")

        auth_files = fetch_auth_files(session, base_url, args.timeout)
        if args.list_all_quota:
            print_all_quota_results(
                session=session,
                base_url=base_url,
                timeout=args.timeout,
                auth_files=auth_files,
                recipe_name=args.recipe,
                upstream_method=args.upstream_method,
                upstream_url=args.upstream_url,
                raw_headers=args.header,
                data=args.data,
                json_dir=json_dir,
            )
            return 0

        auth_index, auth_entry = resolve_target_auth(
            auth_files=auth_files,
            auth_index=args.auth_index,
            credential_name=args.credential_name,
            credential_id=args.credential_id,
        )
        recipe = resolve_recipe(
            recipe_name=args.recipe,
            auth_entry=auth_entry,
            upstream_method=args.upstream_method,
            upstream_url=args.upstream_url,
            raw_headers=args.header,
            data=args.data,
        )
        result = call_management_api_call(
            session=session,
            base_url=base_url,
            timeout=args.timeout,
            auth_index=auth_index,
            recipe=recipe,
        )
        print_result(auth_index, recipe, result)
        return 0
    except requests.HTTPError as exc:
        response = exc.response
        print(f"HTTP error: {exc}", file=sys.stderr)
        if response is not None:
            print(response.text, file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"request error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI script should surface a friendly error message.
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
