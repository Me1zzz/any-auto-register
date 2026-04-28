from __future__ import annotations

from dataclasses import replace

from core.base_mailbox import CloudMailMailbox

from .interactive_provider_base import InteractiveAliasProviderBase
from .interactive_provider_models import (
    AliasCreatedRecord,
    AliasDomainOption,
    AuthenticatedProviderContext,
    VerificationRequirement,
)
from .myalias_pro_adapter import MyAliasProAdapter
from .protocol_site_runtime import ProtocolSiteRuntime
from .verification_executor import VerificationExecutor


class MyAliasProProvider(InteractiveAliasProviderBase):
    source_kind = "myalias_pro"

    def __init__(self, *, spec, context):
        super().__init__(spec=spec, context=context)
        self._adapter = MyAliasProAdapter(spec=spec)
        self._verification_executor = VerificationExecutor(
            confirmation_reader=getattr(context, "confirmation_reader", None)
        )
        self._cached_runtimes = None

    def _build_runtimes(self):
        if self._cached_runtimes is not None:
            return self._cached_runtimes
        runtime_builder = getattr(self._context, "runtime_builder", None)
        if callable(runtime_builder):
            runtime = runtime_builder(dict(self._spec.raw_source or {}))
            if isinstance(runtime, tuple) and len(runtime) == 2:
                self._cached_runtimes = (runtime[0], runtime[1])
                return self._cached_runtimes
            self._cached_runtimes = (runtime, None)
            return self._cached_runtimes
        self._cached_runtimes = (ProtocolSiteRuntime(), None)
        return self._cached_runtimes

    def _confirmation_lookup_email(self) -> str:
        confirmation_inbox = dict(self._spec.confirmation_inbox_config or {})
        return str(
            confirmation_inbox.get("match_email")
            or confirmation_inbox.get("account_email")
            or confirmation_inbox.get("admin_email")
            or ""
        ).strip().lower()

    def _generate_service_account_email(self) -> str:
        confirmation_inbox = dict(self._spec.confirmation_inbox_config or {})
        mailbox = CloudMailMailbox(
            api_base=str(confirmation_inbox.get("api_base") or confirmation_inbox.get("base_url") or "").strip(),
            admin_email=str(confirmation_inbox.get("admin_email") or confirmation_inbox.get("account_email") or "").strip(),
            admin_password=str(confirmation_inbox.get("admin_password") or confirmation_inbox.get("account_password") or "").strip(),
            domain=confirmation_inbox.get("domain") or "",
            subdomain=str(confirmation_inbox.get("subdomain") or "").strip(),
            timeout=int(confirmation_inbox.get("timeout") or 30),
        )
        return str(mailbox.get_email().email or "").strip().lower()

    def rotates_service_account_after_alias_cap(self) -> bool:
        return True

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        state = self._account_selection_state or self._state_repository.load()
        persisted_service_email = str(state.service_account_email or "").strip().lower()
        if persisted_service_email and not bool(dict(state.session_state or {}).get("requires_verification")):
            inbox_email = str(state.confirmation_inbox_email or self._confirmation_lookup_email()).strip().lower()
            return AuthenticatedProviderContext(
                service_account_email=persisted_service_email,
                confirmation_inbox_email=inbox_email,
                real_mailbox_email=str(state.real_mailbox_email or inbox_email).strip().lower(),
                service_password=str(state.service_password or ""),
                username=str(state.username or persisted_service_email.split("@", 1)[0]),
                session_state=dict(state.session_state or {}),
                domain_options=self._domain_options_from_state(state),
            )

        service_email = self._generate_service_account_email()
        inbox_email = self._confirmation_lookup_email()
        protocol_runtime, browser_runtime = self._build_runtimes()
        context = AuthenticatedProviderContext(
            service_account_email=service_email,
            confirmation_inbox_email=inbox_email,
            real_mailbox_email=inbox_email,
        )
        context = self._adapter.open_entrypoint(protocol_runtime, browser_runtime, context)
        return self._adapter.authenticate_or_register(protocol_runtime, browser_runtime, context)

    def resolve_verification_requirements(self, context: AuthenticatedProviderContext) -> list[VerificationRequirement]:
        return [VerificationRequirement(kind="account_email", label="验证服务账号邮箱", inbox_role="confirmation_inbox")]

    def satisfy_verification_requirement(
        self,
        requirement: VerificationRequirement,
        context: AuthenticatedProviderContext,
    ) -> AuthenticatedProviderContext:
        resolution = self._verification_executor.resolve_link(
            requirement=requirement,
            spec=self._spec,
            context=context,
        )
        if resolution.error:
            raise RuntimeError(resolution.error)
        protocol_runtime, browser_runtime = self._build_runtimes()
        updated_context = replace(
            context,
            session_state={
                **dict(context.session_state or {}),
                "verification_link": resolution.link,
                "live_flow": True,
            },
        )
        return self._adapter.resolve_blocking_gate(protocol_runtime, browser_runtime, requirement, updated_context)

    def discover_alias_domains(self, context: AuthenticatedProviderContext) -> list[AliasDomainOption]:
        protocol_runtime, browser_runtime = self._build_runtimes()
        surface_context = self._adapter.load_alias_surface(protocol_runtime, browser_runtime, context)
        return list(self._adapter.extract_domain_options(protocol_runtime, browser_runtime, surface_context) or [])

    def list_existing_aliases(self, context: AuthenticatedProviderContext) -> list[dict[str, str]]:
        protocol_runtime, browser_runtime = self._build_runtimes()
        surface_context = self._adapter.load_alias_surface(protocol_runtime, browser_runtime, context)
        aliases = self._adapter.list_existing_aliases(protocol_runtime, browser_runtime, surface_context)
        return [dict(item) for item in list(aliases or []) if isinstance(item, dict)]

    def pick_domain_option(self, domains: list[AliasDomainOption], alias_index: int) -> AliasDomainOption | None:
        if not domains:
            return None
        return domains[(alias_index - 1) % len(domains)]

    def requires_alias_domain_options(self) -> bool:
        return False

    def build_capture_summary(self):
        return []

    def create_alias(
        self,
        *,
        context: AuthenticatedProviderContext,
        domain: AliasDomainOption | None,
        alias_index: int,
    ) -> AliasCreatedRecord:
        protocol_runtime, browser_runtime = self._build_runtimes()
        surface_context = self._adapter.load_alias_surface(protocol_runtime, browser_runtime, context)
        self._wait_for_alias_creation_slot()
        created = self._adapter.submit_alias_creation(
            protocol_runtime,
            browser_runtime,
            surface_context,
            domain,
            alias_index,
        )
        metadata = {
            **dict(created.metadata or {}),
            "live_flow": True,
            "live_alias_creation": True,
            "confirmed_alias_creation": True,
        }
        return AliasCreatedRecord(email=created.email, metadata=metadata)


def build_myalias_pro_alias_provider(spec, context):
    return MyAliasProProvider(spec=spec, context=context)
