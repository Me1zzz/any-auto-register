from __future__ import annotations

import json
import random
import re
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from urllib.parse import urljoin

from .interactive_provider_base import ExistingAccountAliasProviderBase
from .interactive_provider_models import AliasCreatedRecord, AliasDomainOption, AuthenticatedProviderContext
from .provider_contracts import AliasProviderCapture


class SimpleLoginProvider(ExistingAccountAliasProviderBase):
    source_kind = "simplelogin"

    def __init__(self, *, spec, context):
        super().__init__(spec=spec, context=context)
        self._random = random.Random()
        self._captures: list[AliasProviderCapture] = []
        self._session: Any = None
        self._session_base_url = ""
        self._authenticated_account_email = ""

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        account = self.select_service_account()
        return AuthenticatedProviderContext(
            service_account_email=account["email"],
            confirmation_inbox_email=account["email"],
            real_mailbox_email=account["email"],
            service_password=account["password"],
            username=account["label"],
            session_state={"site_url": self._site_url()},
        )

    def build_capture_summary(self) -> list[AliasProviderCapture]:
        return list(self._captures)

    def pick_domain_option(self, domains: list[AliasDomainOption], alias_index: int) -> AliasDomainOption | None:
        if not domains:
            return None
        return self._random.choice(list(domains))

    def discover_alias_domains(self, context: AuthenticatedProviderContext) -> list[AliasDomainOption]:
        self._ensure_authenticated(context)
        settings_payload = self._request_json("read_settings", "GET", "/api/setting")
        domains_payload = self._request_json("read_domains", "GET", "/api/v2/setting/domains")
        options_payload = self._request_json("read_alias_options", "GET", "/api/v5/alias/options")

        default_domain = self._extract_default_domain(settings_payload)
        available_domains = self._parse_available_domains(domains_payload)
        options = self._parse_alias_options(
            options_payload,
            allowed_domains=available_domains,
            default_domain=default_domain,
        )
        if not options:
            raise RuntimeError("simplelogin live alias domains unavailable")

        context.session_state["site_url"] = self._site_url()
        context.session_state["default_domain"] = default_domain
        context.session_state["available_domains"] = list(available_domains)
        context.session_state["live_domain_count"] = len(options)
        return options

    def list_existing_aliases(self, context: AuthenticatedProviderContext) -> list[dict[str, str]]:
        self._ensure_authenticated(context)
        for endpoint in ("/api/v2/aliases", "/api/v3/aliases", "/api/aliases"):
            response, payload = self._request_json_allowing_fallback("list_aliases", "GET", endpoint)
            if response is None:
                continue
            return self._parse_existing_aliases(payload)
        return []

    def create_alias(self, *, context: AuthenticatedProviderContext, domain, alias_index: int) -> AliasCreatedRecord:
        if domain is None:
            raise RuntimeError("simplelogin alias creation requires discovered live domain options")

        self._ensure_authenticated(context)
        custom_payload = self._build_custom_alias_payload(domain, alias_index)
        request_attempts = [
            ("/api/v5/alias/random/new", {"signed_suffix": domain.key}),
            ("/api/v3/alias/random/new", {"signed_suffix": domain.key}),
            ("/api/v2/alias/random/new", {"signed_suffix": domain.key}),
            ("/api/v5/alias/custom/new", custom_payload),
            ("/api/v3/alias/custom/new", custom_payload),
            ("/api/v2/alias/custom/new", custom_payload),
        ]

        last_error = ""
        for endpoint, payload in request_attempts:
            self._wait_for_alias_creation_slot()
            response, response_payload = self._request_json_allowing_fallback(
                "create_alias",
                "POST",
                endpoint,
                json=payload,
            )
            if response is None:
                continue

            alias_email = self._extract_alias_email(response_payload)
            if alias_email:
                return AliasCreatedRecord(
                    email=alias_email.lower(),
                    metadata={
                        "signed_suffix": domain.key,
                        "domain": domain.domain,
                        "creation_endpoint": endpoint,
                    },
                )

            last_error = self._response_error_message(response.status_code, response_payload) or (
                f"simplelogin alias creation returned no alias email via {endpoint}"
            )

        raise RuntimeError(last_error or "simplelogin alias creation failed")

    def _site_url(self) -> str:
        configured = str(self._spec.provider_config.get("site_url") or "https://app.simplelogin.io/").strip()
        if not configured:
            configured = "https://app.simplelogin.io/"
        if not configured.endswith("/"):
            configured = f"{configured}/"
        return configured

    def _build_http_session(self, base_url: str):
        from curl_cffi.requests import Session

        return Session(
            headers={
                "accept": "application/json, text/plain, */*",
                "origin": base_url.rstrip("/"),
                "referer": base_url,
            },
            impersonate="chrome",
            timeout=30,
        )

    def _ensure_authenticated(self, context: AuthenticatedProviderContext):
        base_url = self._site_url()
        if self._session is None or self._session_base_url != base_url:
            self._session = self._build_http_session(base_url)
            self._session_base_url = base_url
            self._authenticated_account_email = ""

        if self._authenticated_account_email == context.service_account_email:
            return self._session

        login_payload = {
            "email": context.service_account_email,
            "password": context.service_password,
        }
        last_error = ""
        for endpoint in ("/api/auth/login", "/api/v2/auth/login", "/api/v3/auth/login"):
            response, payload = self._request_json_allowing_fallback(
                "login",
                "POST",
                endpoint,
                json=login_payload,
            )
            if response is None:
                continue
            if 200 <= int(response.status_code or 0) < 300:
                self._authenticated_account_email = context.service_account_email
                context.session_state["site_url"] = base_url
                context.session_state["login_endpoint"] = endpoint
                context.session_state["authenticated_account_email"] = context.service_account_email
                return self._session
            last_error = self._response_error_message(response.status_code, payload)

        raise RuntimeError(last_error or "simplelogin login endpoint unavailable")

    def _request_json(self, capture_kind: str, method: str, path: str, **kwargs) -> Any:
        session = self._session
        if session is None:
            raise RuntimeError("simplelogin session unavailable")
        url = self._url(path)
        response = session.request(method, url, **kwargs)
        payload = self._response_payload(response)
        self._record_capture(capture_kind, method, url, kwargs, response, payload)
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code >= 400:
            raise RuntimeError(self._response_error_message(status_code, payload))
        return payload

    def _request_json_allowing_fallback(self, capture_kind: str, method: str, path: str, **kwargs):
        session = self._session
        if session is None:
            raise RuntimeError("simplelogin session unavailable")
        url = self._url(path)
        response = session.request(method, url, **kwargs)
        payload = self._response_payload(response)
        self._record_capture(capture_kind, method, url, kwargs, response, payload)
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code in {404, 405}:
            return None, payload
        if status_code >= 400:
            return response, payload
        return response, payload

    def _url(self, path: str) -> str:
        return urljoin(self._site_url(), path.lstrip("/"))

    def _response_payload(self, response) -> Any:
        try:
            return response.json()
        except Exception:
            text = str(getattr(response, "text", "") or "")
            if not text:
                return {}
            try:
                return json.loads(text)
            except Exception:
                return text

    def _extract_default_domain(self, payload: Any) -> str:
        if isinstance(payload, Mapping):
            return str(payload.get("random_alias_default_domain") or "").strip().lower()
        return ""

    def _parse_available_domains(self, payload: Any) -> list[str]:
        raw_items: Sequence[Any]
        if isinstance(payload, Mapping):
            raw_items = list(payload.get("domains") or payload.get("data") or [])
        elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
            raw_items = list(payload)
        else:
            raw_items = []

        domains: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            enabled = True
            if isinstance(item, Mapping):
                enabled = not bool(item.get("disabled")) and bool(item.get("enabled", True))
                domain = str(item.get("domain") or item.get("name") or item.get("suffix") or "").strip().lower()
            else:
                domain = str(item or "").strip().lower()
            if not enabled or not domain or domain in seen:
                continue
            seen.add(domain)
            domains.append(domain)
        return domains

    def _parse_alias_options(
        self,
        payload: Any,
        *,
        allowed_domains: Sequence[str],
        default_domain: str,
    ) -> list[AliasDomainOption]:
        if isinstance(payload, Mapping):
            raw_items = list(payload.get("suffixes") or payload.get("data") or [])
        elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
            raw_items = list(payload)
        else:
            raw_items = []

        allowed = {str(item).strip().lower() for item in allowed_domains if str(item).strip()}
        options: list[AliasDomainOption] = []
        seen_keys: set[str] = set()
        for item in raw_items:
            if not isinstance(item, Mapping):
                continue
            if bool(item.get("disabled")) or bool(item.get("is_disabled")):
                continue
            signed_suffix = str(item.get("signed_suffix") or item.get("signedSuffix") or item.get("value") or "").strip()
            domain = str(item.get("domain") or self._extract_domain_from_signed_value(signed_suffix)).strip().lower()
            if not signed_suffix or not domain:
                continue
            if allowed and domain not in allowed:
                continue
            if signed_suffix in seen_keys:
                continue
            seen_keys.add(signed_suffix)
            raw_payload = dict(item)
            raw_payload.setdefault("signed_suffix", signed_suffix)
            options.append(
                AliasDomainOption(
                    key=signed_suffix,
                    domain=domain,
                    label=f"@{domain}",
                    raw=raw_payload,
                )
            )

        if default_domain:
            options.sort(key=lambda option: (option.domain != default_domain, option.domain, option.key))
        return options

    def _parse_existing_aliases(self, payload: Any) -> list[dict[str, str]]:
        if isinstance(payload, Mapping):
            raw_items = list(payload.get("aliases") or payload.get("data") or payload.get("items") or [])
        elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
            raw_items = list(payload)
        else:
            raw_items = []

        aliases: list[dict[str, str]] = []
        for item in raw_items:
            if isinstance(item, Mapping):
                alias_email = self._extract_alias_email(item)
            else:
                alias_email = str(item or "").strip().lower()
            if alias_email:
                aliases.append({"email": alias_email.lower()})
        return aliases

    def _extract_alias_email(self, payload: Any) -> str:
        if isinstance(payload, str):
            return payload.strip().lower() if "@" in payload else ""
        if not isinstance(payload, Mapping):
            return ""

        for key in ("email", "alias_email"):
            value = str(payload.get(key) or "").strip().lower()
            if value and "@" in value:
                return value

        alias_value = payload.get("alias")
        if isinstance(alias_value, str):
            alias_value = alias_value.strip().lower()
            if "@" in alias_value:
                return alias_value
        if isinstance(alias_value, Mapping):
            nested = self._extract_alias_email(alias_value)
            if nested:
                return nested

        data_value = payload.get("data")
        if isinstance(data_value, Mapping):
            return self._extract_alias_email(data_value)

        return ""

    def _extract_domain_from_signed_value(self, signed_value: str) -> str:
        value = str(signed_value or "").strip()
        if not value:
            return ""

        match = re.search(r"@(?P<domain>[^@]+?)\.ae[a-z0-9]+\.", value, re.IGNORECASE)
        if match:
            return str(match.group("domain") or "").strip(" .").lower()

        domain_segment = value
        at_index = domain_segment.rfind("@")
        if at_index < 0:
            return ""

        trailing = domain_segment[at_index + 1 :].strip(" .")
        if not trailing:
            return ""

        return trailing.split(".", 1)[0].strip(" .").lower() if "." not in trailing else trailing.lower()

    def _build_custom_alias_payload(self, domain: AliasDomainOption, alias_index: int) -> dict[str, str]:
        local_part = self._build_custom_local_part(alias_index)
        return {
            "alias_prefix": local_part,
            "local_part": local_part,
            "signed_suffix": domain.key,
        }

    def _build_custom_local_part(self, alias_index: int) -> str:
        task_fragment = re.sub(r"[^a-z0-9]+", "", str(self._context.task_id or "sl").lower())
        task_fragment = task_fragment[:12] or "sl"
        random_fragment = "".join(self._random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(6))
        return f"{task_fragment}{alias_index}{random_fragment}"

    def _response_error_message(self, status_code: int, payload: Any) -> str:
        message = ""
        if isinstance(payload, Mapping):
            for key in ("error", "message", "detail", "msg"):
                value = str(payload.get(key) or "").strip()
                if value:
                    message = value
                    break
        elif isinstance(payload, str):
            message = payload.strip()

        if message:
            return f"simplelogin HTTP {status_code}: {message}"
        return f"simplelogin HTTP {status_code}"

    def _record_capture(self, kind: str, method: str, url: str, request_kwargs: Mapping[str, Any], response, payload: Any) -> None:
        request_payload = request_kwargs.get("json")
        if request_payload is None:
            request_payload = request_kwargs.get("data")
        sanitized_request, request_redacted = self._sanitize_for_capture(request_payload)
        sanitized_response, response_redacted = self._sanitize_for_capture(payload)
        self._captures.append(
            AliasProviderCapture(
                kind=kind,
                request_summary={
                    "url": url,
                    "method": method,
                    "request_headers_whitelist": {},
                    "request_body_excerpt": self._capture_excerpt(sanitized_request),
                },
                response_summary={
                    "response_status": int(getattr(response, "status_code", 0) or 0),
                    "response_body_excerpt": self._capture_excerpt(sanitized_response),
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                },
                redaction_applied=bool(request_redacted or response_redacted),
            )
        )

    def _sanitize_for_capture(self, value: Any):
        redacted = False
        if isinstance(value, Mapping):
            sanitized: dict[str, Any] = {}
            for raw_key, raw_item in value.items():
                key = str(raw_key)
                if any(secret in key.lower() for secret in ("password", "token", "cookie", "authorization")):
                    sanitized[key] = "[REDACTED]"
                    redacted = True
                    continue
                child_value, child_redacted = self._sanitize_for_capture(raw_item)
                sanitized[key] = child_value
                redacted = redacted or child_redacted
            return sanitized, redacted

        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            sanitized_items = []
            for item in value:
                child_value, child_redacted = self._sanitize_for_capture(item)
                sanitized_items.append(child_value)
                redacted = redacted or child_redacted
            return sanitized_items, redacted

        if value is None:
            return "", redacted
        return value, redacted

    def _capture_excerpt(self, value: Any) -> str:
        if value in ("", None, {}, []):
            return ""
        if isinstance(value, str):
            text = value
        else:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if len(text) > 500:
            return f"{text[:497]}..."
        return text


class SimpleLoginAliasProvider(SimpleLoginProvider):
    pass


def build_simplelogin_provider(spec, context):
    return SimpleLoginProvider(spec=spec, context=context)


def build_simplelogin_alias_provider(spec, context):
    return build_simplelogin_provider(spec, context)
