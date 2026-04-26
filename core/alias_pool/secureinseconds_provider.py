from __future__ import annotations

import time
from dataclasses import replace
from typing import Any, cast

from core.base_mailbox import CloudMailMailbox

from .interactive_provider_base import InteractiveAliasProviderBase
from .interactive_provider_models import (
    AliasCreatedRecord,
    AliasDomainOption,
    AuthenticatedProviderContext,
    VerificationRequirement,
)
from .secureinseconds_service import (
    DEFAULT_SECUREINSECONDS_LOGIN_URL,
    DEFAULT_SECUREINSECONDS_MAILBOX_BASE_URL,
    DEFAULT_SECUREINSECONDS_REGISTER_URL,
    DEFAULT_SECUREINSECONDS_SERVICE_EMAIL_DOMAIN,
    DEFAULT_SECUREINSECONDS_USER_AGENT,
    DEFAULT_SECUREINSECONDS_FORWARDING_VERIFY_ANCHOR,
    SecureInSecondsRuntime,
    build_secureinseconds_service_email,
    build_secureinseconds_service_password,
    extract_secureinseconds_forwarding_verify_link,
)


def build_secureinseconds_runtime(*, provider_config: dict[str, Any]) -> SecureInSecondsRuntime:
    return SecureInSecondsRuntime(
        register_url=str(provider_config.get("register_url") or DEFAULT_SECUREINSECONDS_REGISTER_URL),
        login_url=str(provider_config.get("login_url") or DEFAULT_SECUREINSECONDS_LOGIN_URL),
        mailbox_base_url=str(
            provider_config.get("mailbox_base_url")
            or provider_config.get("confirmation_mailbox_base_url")
            or DEFAULT_SECUREINSECONDS_MAILBOX_BASE_URL
        ),
        user_agent=str(provider_config.get("user_agent") or DEFAULT_SECUREINSECONDS_USER_AGENT),
    )


class SecureInSecondsProvider(InteractiveAliasProviderBase):
    source_kind = "secureinseconds"

    def __init__(self, *, spec, context):
        super().__init__(spec=spec, context=context)
        self._runtime: SecureInSecondsRuntime | None = None
        self._active_context_email: str = ""

    def rotates_service_account_after_alias_cap(self) -> bool:
        return True

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        state = self._account_selection_state or self._state_repository.load()
        forwarding_email = self._ensure_forwarding_email(state=state)
        context = AuthenticatedProviderContext(
            confirmation_inbox_email=forwarding_email,
            real_mailbox_email=forwarding_email,
        )
        policy = getattr(self._context, "test_policy", None)
        if policy is not None and bool(getattr(policy, "fresh_service_account", False)):
            context = self._ensure_runtime_for_context(context, bootstrap_if_missing=True)
        return context

    def resolve_verification_requirements(self, context: AuthenticatedProviderContext) -> list[VerificationRequirement]:
        return [
            VerificationRequirement(
                kind="forwarding_email",
                label="验证转发邮箱",
                inbox_role="confirmation_inbox",
            )
        ]

    def satisfy_verification_requirement(
        self,
        requirement: VerificationRequirement,
        context: AuthenticatedProviderContext,
    ) -> AuthenticatedProviderContext:
        if requirement.kind != "forwarding_email":
            return context

        forwarding_email = self._context_forwarding_email(context) or self._ensure_forwarding_email()
        if not forwarding_email:
            raise RuntimeError("secureinseconds forwarding email is required")

        context = replace(
            context,
            confirmation_inbox_email=forwarding_email,
            real_mailbox_email=forwarding_email,
        )
        context = self._ensure_runtime_for_context(context, bootstrap_if_missing=True)
        forwarding_email = self._context_forwarding_email(context) or forwarding_email
        runtime = self._require_runtime()

        forwarding_items = runtime.list_forwarding_emails()
        matched = self._find_forwarding_email(forwarding_items, forwarding_email)

        if matched is None:
            added, message = runtime.add_forwarding_email(forwarding_email)
            if not added and "already" not in message.lower():
                raise RuntimeError(message)
            forwarding_items = runtime.list_forwarding_emails()
            matched = self._find_forwarding_email(forwarding_items, forwarding_email)

        if matched is None:
            raise RuntimeError("secureinseconds forwarding email was not returned after add")

        if not bool(matched.get("verified")):
            verify_link = self._fetch_forwarding_verify_link(runtime=runtime, forwarding_email=forwarding_email)
            if not verify_link:
                resent, resend_message = runtime.resend_forwarding_verification(forwarding_email)
                if not resent:
                    raise RuntimeError(resend_message)
                verify_link = self._fetch_forwarding_verify_link(runtime=runtime, forwarding_email=forwarding_email)
            if not verify_link:
                raise RuntimeError("secureinseconds forwarding verification mail did not contain a verification link")
            verified, message = runtime.verify_forwarding_email(verify_link)
            if not verified:
                raise RuntimeError(message)
            forwarding_items = runtime.list_forwarding_emails()
            matched = self._find_forwarding_email(forwarding_items, forwarding_email)
            if matched is None or not bool(matched.get("verified")):
                raise RuntimeError("secureinseconds forwarding email is still unverified")

        return replace(
            context,
            confirmation_inbox_email=forwarding_email,
            real_mailbox_email=forwarding_email,
            username=self._username_from_email(context.service_account_email),
            session_state=runtime.export_session_state(),
        )

    def discover_alias_domains(self, context: AuthenticatedProviderContext) -> list[AliasDomainOption]:
        return [
            AliasDomainOption(
                key="alias.secureinseconds.com",
                domain="alias.secureinseconds.com",
                label="@alias.secureinseconds.com",
            )
        ]

    def list_existing_aliases(self, context: AuthenticatedProviderContext) -> list[dict[str, Any]]:
        context = self._ensure_runtime_for_context(context, bootstrap_if_missing=False)
        aliases = []
        expected_forwarding_email = str(
            context.real_mailbox_email or context.confirmation_inbox_email or ""
        ).strip().lower()
        for item in self._require_runtime().list_aliases():
            if not bool(item.get("active", True)):
                continue
            if str(item.get("deletedAt") or "").strip():
                continue
            forward_to_emails = [str(email or "").strip().lower() for email in list(item.get("forwardToEmails") or [])]
            if expected_forwarding_email and expected_forwarding_email not in forward_to_emails:
                continue
            aliases.append(
                {
                    "email": str(item.get("email") or "").strip().lower(),
                    "aliasId": str(item.get("aliasId") or ""),
                    "description": str(item.get("description") or ""),
                    "forwardToEmails": forward_to_emails,
                }
            )
        return aliases

    def create_alias(self, *, context: AuthenticatedProviderContext, domain, alias_index: int) -> AliasCreatedRecord:
        context = self._ensure_runtime_for_context(context, bootstrap_if_missing=False)
        runtime = self._require_runtime()
        forward_to_emails = [context.real_mailbox_email or context.confirmation_inbox_email]
        forward_to_emails = [email for email in forward_to_emails if email]
        if not forward_to_emails:
            raise RuntimeError("secureinseconds requires a verified forwarding email before alias creation")

        alias_record = runtime.create_alias(
            prefix=self._alias_prefix(context, alias_index),
            description=f"SecureInSeconds automation alias {alias_index}",
            forward_to_emails=forward_to_emails,
        )
        alias_email = str(alias_record.get("alias") or alias_record.get("email") or "").strip().lower()
        if not alias_email:
            raise RuntimeError("secureinseconds create alias returned empty alias email")
        return AliasCreatedRecord(
            email=alias_email,
            metadata={
                "aliasId": str(alias_record.get("_id") or alias_record.get("id") or ""),
                "description": str(alias_record.get("description") or ""),
                "forwardToEmails": list(alias_record.get("forwardToEmails") or []),
            },
        )

    def build_capture_summary(self):
        runtime = self._runtime
        if runtime is None:
            return []
        return runtime.capture_summary()

    def _provider_config(self) -> dict[str, Any]:
        return dict(self._spec.provider_config or {})

    def _ensure_runtime_for_context(
        self,
        context: AuthenticatedProviderContext,
        *,
        bootstrap_if_missing: bool,
    ) -> AuthenticatedProviderContext:
        runtime = self._runtime or self._build_runtime()
        self._runtime = runtime

        service_account_email = str(context.service_account_email or "").strip().lower()
        service_password = str(context.service_password or "").strip()
        username = str(context.username or self._username_from_email(service_account_email)).strip()
        active_context_email = self._active_context_email.strip().lower()

        if (
            service_account_email
            and active_context_email
            and service_account_email == active_context_email
        ):
            return replace(
                context,
                service_account_email=service_account_email,
                service_password=service_password,
                username=username,
                session_state=runtime.export_session_state(),
            )

        if service_account_email and runtime.restore_session(context.session_state, service_account_email):
            self._active_context_email = service_account_email
            return replace(
                context,
                service_account_email=service_account_email,
                service_password=service_password,
                username=username,
                session_state=runtime.export_session_state(),
            )

        if service_account_email and service_password and runtime.login_account(service_account_email, service_password):
            self._active_context_email = service_account_email
            return replace(
                context,
                service_account_email=service_account_email,
                service_password=service_password,
                username=username,
                session_state=runtime.export_session_state(),
            )

        if not bootstrap_if_missing:
            raise RuntimeError("secureinseconds service account session unavailable")

        return self._bootstrap_service_account(context, runtime)

    def _bootstrap_service_account(
        self,
        context: AuthenticatedProviderContext,
        runtime: SecureInSecondsRuntime,
    ) -> AuthenticatedProviderContext:
        service_email_domain = str(
            self._provider_config().get("service_email_domain") or DEFAULT_SECUREINSECONDS_SERVICE_EMAIL_DOMAIN
        ).strip().lower()
        for _ in range(3):
            service_account_email = build_secureinseconds_service_email(domain=service_email_domain)
            service_password = build_secureinseconds_service_password()
            registered, message = runtime.register_account(service_account_email, service_password)
            if not registered:
                if "already" in message.lower():
                    continue
                raise RuntimeError(message)
            if not runtime.login_account(service_account_email, service_password):
                raise RuntimeError("secureinseconds login failed after registration")
            self._active_context_email = service_account_email
            return replace(
                context,
                service_account_email=service_account_email,
                service_password=service_password,
                username=self._username_from_email(service_account_email),
                session_state=runtime.export_session_state(),
            )
        raise RuntimeError("secureinseconds failed to create a unique service account")

    def _alias_prefix(self, context: AuthenticatedProviderContext, alias_index: int) -> str:
        local_part = str(context.service_account_email or "secureinseconds").split("@", 1)[0]
        compact = "".join(character for character in local_part.lower() if character.isalnum())
        base = compact[:8] or "securein"
        return f"{base}{alias_index:02d}"

    def _ensure_forwarding_email(self, *, state=None) -> str:
        state = state if state is not None else self._account_selection_state
        forwarding_email = self._state_forwarding_email(state) or self._configured_forwarding_email()
        if not forwarding_email:
            forwarding_email = self._generate_forwarding_email()
        if state is not None and forwarding_email:
            state.confirmation_inbox_email = forwarding_email
            state.real_mailbox_email = forwarding_email
        return forwarding_email

    def _state_forwarding_email(self, state) -> str:
        if state is None:
            return ""
        for value in (
            getattr(state, "real_mailbox_email", ""),
            getattr(state, "confirmation_inbox_email", ""),
        ):
            email = str(value or "").strip().lower()
            if email and not self._is_cloudmail_admin_email(email):
                return email
        return ""

    def _configured_forwarding_email(self) -> str:
        inbox = dict(self._spec.confirmation_inbox_config or {})
        explicit_email = str(
            inbox.get("forwarding_email")
            or inbox.get("real_mailbox_email")
            or inbox.get("destination_email")
            or self._provider_config().get("forwarding_email")
            or ""
        ).strip().lower()
        if explicit_email:
            return explicit_email

        for key in ("match_email", "account_email"):
            email = str(inbox.get(key) or "").strip().lower()
            if email and not self._is_cloudmail_admin_email(email):
                return email
        return ""

    def _context_forwarding_email(self, context: AuthenticatedProviderContext) -> str:
        return str(context.real_mailbox_email or context.confirmation_inbox_email or "").strip().lower()

    def _is_cloudmail_admin_email(self, email: str) -> bool:
        normalized_email = str(email or "").strip().lower()
        admin_email = str(self._spec.confirmation_inbox_config.get("admin_email") or "").strip().lower()
        return bool(normalized_email and admin_email and normalized_email == admin_email)

    def _generate_forwarding_email(self) -> str:
        account = self._build_cloudmail_mailbox().get_email()
        return str(account.account_id or account.email or "").strip().lower()

    def _build_cloudmail_mailbox(self) -> CloudMailMailbox:
        inbox = dict(self._spec.confirmation_inbox_config or {})
        return CloudMailMailbox(
            api_base=str(inbox.get("api_base") or inbox.get("base_url") or "").strip(),
            admin_email=str(inbox.get("admin_email") or "").strip(),
            admin_password=str(inbox.get("admin_password") or "").strip(),
            domain=inbox.get("domain") or "",
            subdomain=str(inbox.get("subdomain") or "").strip(),
            timeout=self._mailbox_timeout_seconds(),
        )

    def _fetch_forwarding_verify_link(
        self,
        *,
        runtime: SecureInSecondsRuntime,
        forwarding_email: str,
    ) -> str:
        mailbox_email = self._mailbox_email()
        mailbox_password = self._mailbox_password()
        if (
            mailbox_email
            and mailbox_password
            and mailbox_email == str(forwarding_email or "").strip().lower()
            and not self._is_cloudmail_admin_email(mailbox_email)
        ):
            return runtime.fetch_forwarding_verify_link(
                mailbox_email=mailbox_email,
                mailbox_password=mailbox_password,
                match_email=forwarding_email,
                timeout_seconds=self._mailbox_timeout_seconds(),
                link_anchor=self._forwarding_verify_anchor(),
            )
        return self._fetch_forwarding_verify_link_via_cloudmail(forwarding_email)

    def _fetch_forwarding_verify_link_via_cloudmail(self, forwarding_email: str) -> str:
        mailbox = self._build_cloudmail_mailbox()
        timeout_seconds = self._mailbox_timeout_seconds()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            messages: list[dict[str, Any]] = []
            for lookup_email in (forwarding_email, ""):
                try:
                    items = mailbox._list_mails(lookup_email)
                except Exception:
                    continue
                messages.extend([item for item in list(items or []) if isinstance(item, dict)])
                if lookup_email and messages:
                    break
            link = extract_secureinseconds_forwarding_verify_link(
                messages,
                forwarding_email=forwarding_email,
                link_anchor=self._forwarding_verify_anchor(),
            )
            if link:
                return link
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(3, remaining))
        return ""

    def _mailbox_email(self) -> str:
        return str(
            self._spec.confirmation_inbox_config.get("account_email")
            or self._spec.confirmation_inbox_config.get("match_email")
            or ""
        ).strip().lower()

    def _mailbox_password(self) -> str:
        return str(self._spec.confirmation_inbox_config.get("account_password") or "").strip()

    def _mailbox_timeout_seconds(self) -> int:
        raw_timeout = self._spec.confirmation_inbox_config.get("timeout")
        try:
            timeout = int(raw_timeout) if raw_timeout not in (None, "") else 120
        except (TypeError, ValueError):
            timeout = 120
        return max(timeout, 15)

    def _forwarding_verify_anchor(self) -> str:
        return str(
            self._provider_config().get("forwarding_verify_anchor") or DEFAULT_SECUREINSECONDS_FORWARDING_VERIFY_ANCHOR
        ).strip()

    def _find_forwarding_email(self, items: list[dict[str, Any]], email: str) -> dict[str, Any] | None:
        normalized_email = str(email or "").strip().lower()
        for item in items:
            if str(item.get("email") or "").strip().lower() == normalized_email:
                return dict(item)
        return None

    def _username_from_email(self, email: str) -> str:
        local_part = str(email or "").split("@", 1)[0].strip()
        return local_part

    def _require_runtime(self) -> SecureInSecondsRuntime:
        if self._runtime is None:
            raise RuntimeError("secureinseconds runtime not initialized")
        return self._runtime

    def _is_runtime_compatible(self, candidate) -> bool:
        required_methods = (
            "export_session_state",
            "restore_session",
            "register_account",
            "login_account",
            "list_forwarding_emails",
            "add_forwarding_email",
            "resend_forwarding_verification",
            "fetch_forwarding_verify_link",
            "verify_forwarding_email",
            "list_aliases",
            "create_alias",
        )
        return all(callable(getattr(candidate, method_name, None)) for method_name in required_methods)

    def _build_runtime(self) -> SecureInSecondsRuntime:
        runtime_builder = getattr(self._context, "runtime_builder", None)
        provider_config = self._provider_config()
        if callable(runtime_builder):
            for args, kwargs in (
                ((), {"provider_type": self.source_kind, "provider_config": provider_config}),
                ((provider_config,), {}),
                ((), {}),
            ):
                try:
                    candidate = runtime_builder(*args, **kwargs)
                except TypeError:
                    continue
                if candidate is not None and self._is_runtime_compatible(candidate):
                    return cast(SecureInSecondsRuntime, candidate)
        return build_secureinseconds_runtime(provider_config=provider_config)


def build_secureinseconds_alias_provider(spec, context):
    return SecureInSecondsProvider(spec=spec, context=context)
