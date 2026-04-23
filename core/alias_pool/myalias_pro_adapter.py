from __future__ import annotations

import json
import re
import secrets
import time
from urllib.parse import urlsplit
import random
import string

from dataclasses import replace

from .interactive_provider_models import AliasCreatedRecord, AuthenticatedProviderContext


class MyAliasProAdapter:
    _PREFIX_START_ALPHABET = string.ascii_lowercase
    _PREFIX_ALPHABET = string.ascii_lowercase + string.digits

    _BROWSER_SIGNUP_SUCCESS_TEXT = "Account Created Successfully"
    _BROWSER_TEXTBOX_NAMES = {
        "username": "Username",
        "email": "Email address",
        "password": "Password",
        "confirm_password": "Confirm Password",
    }

    def __init__(self, *, spec):
        self._spec = spec

    def _dismiss_cookie_consent(self, browser_runtime) -> None:
        try:
            if hasattr(browser_runtime, "click_role"):
                browser_runtime.click_role("button", "Save Preferences")
                return
            if hasattr(browser_runtime, "click"):
                browser_runtime.click("button")
        except Exception:
            return

    def _switch_to_browser_transport(
        self,
        browser_runtime,
        context: AuthenticatedProviderContext,
    ) -> AuthenticatedProviderContext:
        if browser_runtime is None:
            raise RuntimeError("browser fallback runtime unavailable")
        if hasattr(browser_runtime, "open"):
            browser_runtime.open(self.signup_url)
        session_state = {
            **dict(context.session_state or {}),
            "transport_mode": "browser",
            "signup_url": self.signup_url,
            "browser_session": self._read_browser_snapshot(browser_runtime),
        }
        return replace(context, session_state=session_state)

    def should_fallback_to_browser(self, protocol_runtime, browser_runtime) -> bool:
        export_cookies = getattr(protocol_runtime, "export_cookies", None)
        if not callable(export_cookies):
            return False
        raw_cookies = export_cookies()
        if not isinstance(raw_cookies, list):
            return False
        return False

    def _uses_browser_transport(self, context: AuthenticatedProviderContext, browser_runtime) -> bool:
        transport_mode = str((context.session_state or {}).get("transport_mode") or "").strip().lower()
        return transport_mode == "browser" and browser_runtime is not None

    def _read_browser_snapshot(self, browser_runtime) -> dict:
        snapshot = getattr(browser_runtime, "snapshot", lambda: None)()
        if snapshot is None:
            return {}
        return {
            "current_url": getattr(snapshot, "current_url", "") or "",
            "cookies": list(getattr(snapshot, "cookies", []) or []),
            "local_storage": dict(getattr(snapshot, "local_storage", {}) or {}),
            "session_storage": dict(getattr(snapshot, "session_storage", {}) or {}),
        }

    def _authenticate_or_register_in_browser(
        self,
        browser_runtime,
        context: AuthenticatedProviderContext,
        *,
        account_email: str,
        password: str,
        username: str,
    ) -> AuthenticatedProviderContext:
        if hasattr(browser_runtime, "open"):
            browser_runtime.open(self.signup_url)
        self._wait_for_browser_form_ready(
            browser_runtime,
            ("#username", "#email", "#password", "#confirmPassword"),
            settle_seconds=2.0,
        )
        self._dismiss_cookie_consent(browser_runtime)
        self._fill_browser_signup_fields(browser_runtime, username=username, account_email=account_email, password=password)
        time.sleep(1.0)
        if hasattr(browser_runtime, "click_role"):
            browser_runtime.click_role("button", "Create Account")
        elif hasattr(browser_runtime, "click"):
            browser_runtime.click("button[type='submit']")
        self._wait_for_browser_signup(browser_runtime)

        session_state = {
            **dict(context.session_state or {}),
            "transport_mode": "browser",
            "browser_session": self._read_browser_snapshot(browser_runtime),
            "requires_verification": True,
        }
        return replace(
            context,
            service_account_email=account_email,
            real_mailbox_email=str(context.real_mailbox_email or account_email),
            service_password=password,
            username=username,
            session_state=session_state,
        )

    def _is_browser_signup_success_content(self, html: str) -> bool:
        content = str(html or "").lower()
        return "account created successfully" in content and "go to login" in content

    def _fill_browser_field(self, browser_runtime, *, textbox_name: str, selector: str, value: str, exact: bool = False) -> None:
        fill_role = getattr(browser_runtime, "fill_role", None)
        if callable(fill_role):
            fill_role("textbox", textbox_name, value, exact=exact)
            return

        fill = getattr(browser_runtime, "fill", None)
        if callable(fill):
            fill(selector, value)

    def _fill_browser_signup_fields(self, browser_runtime, *, username: str, account_email: str, password: str) -> None:
        self._fill_browser_field(
            browser_runtime,
            textbox_name=self._BROWSER_TEXTBOX_NAMES["username"],
            selector="#username",
            value=username,
            exact=True,
        )
        self._fill_browser_field(
            browser_runtime,
            textbox_name=self._BROWSER_TEXTBOX_NAMES["email"],
            selector="#email",
            value=account_email,
            exact=True,
        )
        self._fill_browser_field(
            browser_runtime,
            textbox_name=self._BROWSER_TEXTBOX_NAMES["password"],
            selector="#password",
            value=password,
            exact=True,
        )
        self._fill_browser_field(
            browser_runtime,
            textbox_name=self._BROWSER_TEXTBOX_NAMES["confirm_password"],
            selector="#confirmPassword",
            value=password,
            exact=True,
        )

    def _fill_browser_login_fields(self, browser_runtime, *, account_email: str, password: str) -> None:
        self._fill_browser_field(
            browser_runtime,
            textbox_name=self._BROWSER_TEXTBOX_NAMES["email"],
            selector="#email",
            value=account_email,
            exact=True,
        )
        self._fill_browser_field(
            browser_runtime,
            textbox_name=self._BROWSER_TEXTBOX_NAMES["password"],
            selector="#password",
            value=password,
            exact=True,
        )

    def _wait_for_browser_form_ready(self, browser_runtime, selectors: tuple[str, ...], *, settle_seconds: float = 0.0) -> None:
        wait_for_selector = getattr(browser_runtime, "wait_for_selector", None)
        if callable(wait_for_selector):
            for selector in selectors:
                wait_for_selector(selector)
        else:
            time.sleep(5.0)
        if settle_seconds > 0:
            time.sleep(settle_seconds)

    def _wait_for_browser_signup(self, browser_runtime) -> None:
        wait_for_text = getattr(browser_runtime, "wait_for_text", None)
        if callable(wait_for_text):
            try:
                wait_for_text(self._BROWSER_SIGNUP_SUCCESS_TEXT)
                return
            except Exception:
                if self._browser_signup_succeeded(browser_runtime):
                    return

        wait_for_url = getattr(browser_runtime, "wait_for_url", None)
        if callable(wait_for_url):
            try:
                wait_for_url("**/login/**")
                return
            except Exception:
                if self._browser_signup_succeeded(browser_runtime):
                    return
                raise

        if not self._browser_signup_succeeded(browser_runtime):
            raise RuntimeError("myalias browser signup did not reach success state")

    def _browser_signup_succeeded(self, browser_runtime) -> bool:
        read_content = getattr(browser_runtime, "content", None)
        if not callable(read_content):
            return False
        for _ in range(2):
            if self._is_browser_signup_success_content(str(read_content() or "")):
                return True
        return False

    def _resolve_signup_username(self, context: AuthenticatedProviderContext, account_email: str) -> str:
        username = str(context.username or "").strip()
        if username:
            return username

        email_prefix = str(account_email or "").split("@", 1)[0].split("+", 1)[0].strip().lower()
        normalized = re.sub(r"[^a-z0-9._-]+", "-", email_prefix).strip("._-")
        if normalized:
            return normalized
        return "myalias-user"

    @staticmethod
    def _load_json_payload(response) -> dict:
        text = str(getattr(response, "text", "") or "")
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _merge_api_path(base_url: str, api_path: str) -> str:
        raw = str(base_url or "").strip()
        if not raw:
            return api_path
        parsed = urlsplit(raw)
        origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("://") if parsed.scheme and parsed.netloc else raw.rstrip("/")
        return f"{origin}{api_path}"

    @property
    def api_signup_url(self) -> str:
        return self._merge_api_path(self.signup_url, "/api/auth/signup/")

    @property
    def api_login_url(self) -> str:
        return self._merge_api_path(self.login_url, "/api/auth/login/")

    @property
    def api_me_url(self) -> str:
        return self._merge_api_path(self.alias_url, "/api/auth/me/")

    @property
    def api_emails_url(self) -> str:
        return self._merge_api_path(self.alias_url, "/api/emails/")

    @property
    def api_aliases_url(self) -> str:
        return self._merge_api_path(self.alias_url, "/api/aliases/")

    @property
    def api_aliases_random_url(self) -> str:
        return self._merge_api_path(self.alias_url, "/api/aliases/random/")

    @property
    def signup_url(self) -> str:
        return str(self._spec.provider_config.get("signup_url") or "https://myalias.pro/signup/").strip()

    @property
    def login_url(self) -> str:
        return str(self._spec.provider_config.get("login_url") or "https://myalias.pro/login/").strip()

    @property
    def alias_url(self) -> str:
        return str(self._spec.provider_config.get("alias_url") or "https://myalias.pro/aliases/").strip()

    def open_entrypoint(self, protocol_runtime, browser_runtime, context: AuthenticatedProviderContext) -> AuthenticatedProviderContext:
        try:
            protocol_runtime.get(self.signup_url)
        except Exception:
            return self._switch_to_browser_transport(browser_runtime, context)
        session_state = {
            **dict(context.session_state or {}),
            "transport_mode": "protocol",
            "signup_url": self.signup_url,
        }
        return replace(context, session_state=session_state)

    def authenticate_or_register(self, protocol_runtime, browser_runtime, context: AuthenticatedProviderContext) -> AuthenticatedProviderContext:
        password = str(context.service_password or secrets.token_urlsafe(12))
        account_email = str(
            context.service_account_email
            or context.confirmation_inbox_email
            or context.real_mailbox_email
            or ""
        ).strip().lower()
        username = self._resolve_signup_username(context, account_email)
        if self._uses_browser_transport(context, browser_runtime):
            return self._authenticate_or_register_in_browser(
                browser_runtime,
                context,
                account_email=account_email,
                password=password,
                username=username,
            )
        signup_response = protocol_runtime.post_json(
            self.api_signup_url,
            {
                "username": username,
                "email": account_email,
                "password": password,
            },
        )
        signup_payload = self._load_json_payload(signup_response)
        signup_succeeded = bool(signup_payload.get("success")) and bool(signup_payload.get("verificationRequired"))
        if not signup_succeeded:
            raise RuntimeError(str(signup_payload.get("message") or "myalias signup failed"))
        session_state = {
            **dict(context.session_state or {}),
            "transport_mode": "protocol",
            "requires_verification": True,
        }
        context = replace(
            context,
            service_account_email=account_email,
            real_mailbox_email=str(context.real_mailbox_email or account_email),
            service_password=password,
            username=username,
            session_state=session_state,
        )
        if browser_runtime is not None and self.should_fallback_to_browser(protocol_runtime, browser_runtime):
            return self._authenticate_or_register_in_browser(
                browser_runtime,
                context,
                account_email=account_email,
                password=password,
                username=username,
            )
        return context

    def resolve_blocking_gate(self, protocol_runtime, browser_runtime, requirement, context: AuthenticatedProviderContext) -> AuthenticatedProviderContext:
        verification_link = str((context.session_state or {}).get("verification_link") or "").strip()
        if verification_link:
            protocol_runtime.get(verification_link)
        account_email = str(
            context.service_account_email
            or context.confirmation_inbox_email
            or context.real_mailbox_email
            or ""
        ).strip().lower()
        password = str(context.service_password or "")
        username = self._resolve_signup_username(context, account_email)

        login_response = protocol_runtime.post_json(
            self.api_login_url,
            {"email": account_email, "password": password},
        )
        login_payload = self._load_json_payload(login_response)
        if not bool(login_payload.get("success")):
            raise RuntimeError(str(login_payload.get("message") or "myalias login failed after verification"))
        me_response = protocol_runtime.get(self.api_me_url)
        me_payload = self._load_json_payload(me_response)
        user_payload = me_payload.get("user") if isinstance(me_payload.get("user"), dict) else {}
        session_state = {
            **dict(context.session_state or {}),
            "requires_verification": False,
        }
        return replace(
            context,
            session_state=session_state,
            username=str((user_payload or {}).get("username") or username),
        )

    def load_alias_surface(self, protocol_runtime, browser_runtime, context: AuthenticatedProviderContext) -> AuthenticatedProviderContext:
        emails_response = protocol_runtime.get(self.api_emails_url)
        aliases_response = protocol_runtime.get(self.api_aliases_url)
        random_response = protocol_runtime.get(self.api_aliases_random_url)
        session_state = {
            **dict(context.session_state or {}),
            "myalias_emails_payload": self._load_json_payload(emails_response),
            "myalias_aliases_payload": self._load_json_payload(aliases_response),
            "myalias_aliases_random_payload": self._load_json_payload(random_response),
        }
        return replace(context, session_state=session_state)
        return context

    def extract_domain_options(self, protocol_runtime, browser_runtime, context):
        return []

    def list_existing_aliases(self, protocol_runtime, browser_runtime, context):
        payload = dict((context.session_state or {}).get("myalias_aliases_payload") or {})
        aliases = payload.get("aliases") if isinstance(payload.get("aliases"), list) else []
        result = []
        for alias in list(aliases or []):
            if not isinstance(alias, dict):
                continue
            email = str(alias.get("aliasEmail") or alias.get("email") or "").strip().lower()
            if email:
                result.append({"email": email})
        return result

    def submit_alias_creation(self, protocol_runtime, browser_runtime, context, domain_option, alias_index: int) -> AliasCreatedRecord:
        local_part = self._build_random_local_part()
        emails_payload = dict((context.session_state or {}).get("myalias_emails_payload") or {})
        available_emails = emails_payload.get("emails") if isinstance(emails_payload.get("emails"), list) else []
        primary_email = context.service_account_email
        for item in list(available_emails or []):
            if not isinstance(item, dict):
                continue
            if bool(item.get("primary")):
                primary_email = str(item.get("email") or primary_email).strip().lower()
                break
        alias_email = f"{local_part}@myalias.pro"
        response = protocol_runtime.post_json(
            self.api_aliases_url,
            {
                "aliasEmail": alias_email,
                "comment": "automation test",
                "forwardToEmails": [primary_email],
            },
        )
        payload = self._load_json_payload(response)
        created_alias = ""
        if isinstance(payload.get("alias"), dict):
            created_alias = str(payload.get("alias", {}).get("aliasEmail") or payload.get("alias", {}).get("email") or "").strip().lower()
        if not created_alias:
            created_alias = alias_email
        return AliasCreatedRecord(
            email=created_alias,
            metadata={"confirmed": True, "transport_mode": "protocol-http"},
        )

    def _build_random_local_part(self) -> str:
        length = random.randint(6, 10)
        start = random.choice(self._PREFIX_START_ALPHABET)
        remainder = "".join(random.choices(self._PREFIX_ALPHABET, k=length - 1))
        return f"{start}{remainder}"
