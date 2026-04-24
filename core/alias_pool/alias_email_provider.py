from __future__ import annotations

from dataclasses import replace
import secrets
from typing import Any

from .alias_email_runtime import AliasEmailRuntimeContract, resolve_alias_email_runtime_builder
from .interactive_provider_base import InteractiveAliasProviderBase
from .interactive_provider_models import (
    AliasCreatedRecord,
    AliasDomainOption,
    AuthenticatedProviderContext,
    VerificationRequirement,
)


class AliasEmailProvider(InteractiveAliasProviderBase):
    source_kind = "alias_email"

    def __init__(self, *, spec, context):
        super().__init__(spec=spec, context=context)
        self._active_policy = getattr(context, "test_policy", None)
        self._runtime: AliasEmailRuntimeContract = resolve_alias_email_runtime_builder(
            getattr(context, "runtime_builder", None),
            spec=spec,
            context=context,
        )

    def run_alias_generation_test(self, policy):
        previous_policy = self._active_policy
        self._active_policy = policy
        try:
            return super().run_alias_generation_test(policy)
        finally:
            self._active_policy = previous_policy

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        persisted_state = self._state_repository.load()
        fresh_service_account = bool(getattr(self._active_policy, "fresh_service_account", False))
        inbox_email = str(self._spec.confirmation_inbox_config.get("match_email") or "").strip().lower()
        service_account_email = ""
        if not fresh_service_account:
            service_account_email = str(persisted_state.service_account_email or "").strip().lower()
        if not service_account_email:
            generated_service_account_email = str(self._runtime.generate_service_account_email() or "").strip().lower()
            service_account_email = generated_service_account_email or inbox_email
        if not service_account_email:
            raise RuntimeError("alias.email requires a CloudMail-backed service account email or match_email")
        confirmation_inbox_email = str(persisted_state.confirmation_inbox_email or "").strip().lower() or service_account_email
        real_mailbox_email = str(persisted_state.real_mailbox_email or "").strip().lower() or service_account_email
        return AuthenticatedProviderContext(
            service_account_email=service_account_email,
            confirmation_inbox_email=confirmation_inbox_email,
            real_mailbox_email=real_mailbox_email,
            service_password=str(persisted_state.service_password or ""),
            username=str(persisted_state.username or "") or service_account_email.split("@", 1)[0],
            session_state=dict(persisted_state.session_state or {}),
        )

    def resolve_verification_requirements(self, context: AuthenticatedProviderContext) -> list[VerificationRequirement]:
        return [
            VerificationRequirement(
                kind="request_magic_link",
                label="请求登录魔法链接",
                inbox_role="confirmation_inbox",
            ),
            VerificationRequirement(
                kind="magic_link_login",
                label="消费登录魔法链接",
                inbox_role="confirmation_inbox",
            ),
        ]

    def satisfy_verification_requirement(
        self,
        requirement: VerificationRequirement,
        context: AuthenticatedProviderContext,
    ) -> AuthenticatedProviderContext:
        if requirement.kind == "request_magic_link":
            public_session = self._runtime.bootstrap_public_session(
                service_account_email=context.service_account_email,
                session_state=context.session_state,
            )
            payload = public_session.payload
            updated_context = replace(context, session_state=dict(public_session.session_state))
            if self._runtime.account_exists_from_basic_info(payload):
                requested = self._runtime.request_magic_link(
                    service_account_email=context.service_account_email,
                    session_state=updated_context.session_state,
                )
                return replace(updated_context, session_state=dict(requested.session_state))
            signup = self._runtime.submit_signup(
                service_account_email=context.service_account_email,
                session_state=updated_context.session_state,
            )
            return replace(updated_context, session_state=dict(signup.session_state))
        if requirement.kind == "magic_link_login":
            consumed = self._runtime.consume_magic_link(
                service_account_email=context.service_account_email,
                session_state=context.session_state,
            )
            return replace(context, session_state=dict(consumed.session_state))
        return context

    def discover_alias_domains(self, context: AuthenticatedProviderContext) -> list[AliasDomainOption]:
        session_state = dict(context.session_state or {})
        settings = self._runtime.get_settings(session_state=session_state)
        domains = self._runtime.list_domains(session_state=settings.session_state)
        options = self._runtime.discover_domains_from_payloads(
            settings_payload=settings.payload,
            domains_payload=domains.payload,
        )
        if not options:
            raise RuntimeError("alias.email domain options unavailable")
        context.session_state.update(domains.session_state)
        return options

    def list_existing_aliases(self, context: AuthenticatedProviderContext) -> list[dict[str, Any]]:
        list_result = self._runtime.list_rules(session_state=context.session_state)
        context.session_state.update(list_result.session_state)
        return self._runtime.aliases_from_rules_payload(list_result.payload)

    def create_alias(
        self,
        *,
        context: AuthenticatedProviderContext,
        domain: AliasDomainOption | None,
        alias_index: int,
    ) -> AliasCreatedRecord:
        if domain is None:
            raise RuntimeError("alias.email requires discovered domains")
        local_part = self._build_alias_local_part(alias_index)
        created = self._runtime.create_rule(
            session_state=context.session_state,
            name=local_part,
            domain=domain.domain,
            custom=False,
        )
        context.session_state.update(created.session_state)
        alias_item = self._runtime.alias_from_create_payload(created.payload)
        metadata = dict(alias_item)
        metadata.pop("email", None)
        return AliasCreatedRecord(email=str(alias_item.get("email") or ""), metadata=metadata)

    def build_capture_summary(self):
        return self._runtime.build_capture_summary()

    def _build_alias_local_part(self, alias_index: int) -> str:
        token = secrets.token_hex(3)
        return f"aliasemail{alias_index:02d}{token}"


class AliasEmailAliasProvider(AliasEmailProvider):
    pass


def build_alias_email_alias_provider(spec, context):
    return AliasEmailProvider(spec=spec, context=context)
