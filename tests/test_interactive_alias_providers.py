import unittest

from core.alias_pool.myalias_pro_provider import MyAliasProProvider
from core.alias_pool.alias_email_provider import AliasEmailProvider
from core.alias_pool.interactive_provider_base import ExistingAccountAliasProviderBase, InteractiveAliasProviderBase
from core.alias_pool.base import AliasEmailLease
from core.alias_pool.interactive_provider_models import (
    AliasCreatedRecord,
    AliasDomainOption,
    AuthenticatedProviderContext,
    VerificationRequirement,
)
from core.alias_pool.interactive_provider_state import InteractiveProviderState
from core.alias_pool.interactive_state_repository import InteractiveStateRepository
from core.alias_pool.provider_contracts import (
    AliasAutomationTestPolicy,
    AliasProviderBootstrapContext,
    AliasProviderSourceSpec,
)
from core.alias_pool.emailshield_provider import EmailShieldAliasProvider
from core.alias_pool.simplelogin_provider import SimpleLoginAliasProvider
from core.alias_pool.secureinseconds_provider import SecureInSecondsProvider


class _MemoryStore:
    def __init__(self, state=None):
        self.state = state
        self.saved = []
        self.loaded_keys = []
        self.saved_keys = []

    def load(self, state_key=None):
        self.loaded_keys.append(state_key)
        return self.state

    def save(self, state, state_key=None):
        self.saved_keys.append(state_key)
        self.state = state
        self.saved.append(state)


class _FakeInteractiveProvider(InteractiveAliasProviderBase):
    source_kind = "fake_interactive"

    def __init__(self, *, spec, context):
        super().__init__(spec=spec, context=context)
        self.capture_calls = 0
        self.seen_contexts = []

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        context = AuthenticatedProviderContext(
            service_account_email="service@example.com",
            confirmation_inbox_email="real@example.com",
            real_mailbox_email="real@example.com",
            service_password="secret-pass",
            username="service",
        )
        self.seen_contexts.append(context)
        return context

    def resolve_verification_requirements(self, context: AuthenticatedProviderContext):
        return [
            VerificationRequirement(
                kind="account_email",
                label="验证服务账号邮箱",
                inbox_role="confirmation_inbox",
            )
        ]

    def satisfy_verification_requirement(self, requirement, context):
        return context

    def discover_alias_domains(self, context):
        return [AliasDomainOption(key="example.com", domain="example.com", label="@example.com")]

    def list_existing_aliases(self, context):
        return [{"email": "first@example.com"}]

    def create_alias(self, *, context, domain, alias_index):
        assert domain is not None
        return AliasCreatedRecord(email=f"created-{alias_index}@{domain.domain}")

    def build_capture_summary(self):
        self.capture_calls += 1
        return []


class _DuplicateInteractiveProvider(_FakeInteractiveProvider):
    def list_existing_aliases(self, context):
        return [
            {"email": "first@example.com"},
            {"email": "FIRST@example.com"},
        ]

    def create_alias(self, *, context, domain, alias_index):
        assert domain is not None
        if alias_index == 2:
            return AliasCreatedRecord(email="first@example.com")
        return AliasCreatedRecord(email="created-3@example.com")


class _PoolManager:
    def __init__(self):
        self.leases: list[AliasEmailLease] = []

    def add_lease(self, lease: AliasEmailLease) -> None:
        self.leases.append(lease)


class _ExistingAccountProvider(ExistingAccountAliasProviderBase):
    source_kind = "existing_account"

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        account = self.select_service_account()
        return AuthenticatedProviderContext(
            service_account_email=account["email"],
            service_password=account["password"],
            username=account["label"],
        )

    def create_alias(self, *, context, domain, alias_index):
        return AliasCreatedRecord(email=f"existing-{alias_index}@example.com")


class InteractiveAliasProviderBaseTests(unittest.TestCase):
    def test_shared_loop_returns_three_aliases_and_stage_timeline(self):
        provider = _FakeInteractiveProvider(
            spec=AliasProviderSourceSpec(
                source_id="fake-provider",
                provider_type="fake_interactive",
                state_key="fake-provider",
                desired_alias_count=3,
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        result = provider.run_alias_generation_test(
            AliasAutomationTestPolicy(
                fresh_service_account=True,
                persist_state=False,
                minimum_alias_count=3,
                capture_enabled=True,
            )
        )

        self.assertTrue(result.ok)
        self.assertEqual(len(result.aliases), 3)
        self.assertEqual(
            [item["email"] for item in result.aliases],
            ["first@example.com", "created-2@example.com", "created-3@example.com"],
        )
        self.assertEqual(result.account_identity.service_account_email, "service@example.com")
        self.assertEqual(
            [item.code for item in result.stage_timeline],
            [
                "session_ready",
                "verify_account_email",
                "discover_alias_domains",
                "list_aliases",
                "create_aliases",
                "aliases_ready",
            ],
        )

    def test_shared_loop_records_save_state_only_when_persisting(self):
        store = _MemoryStore()
        provider = _FakeInteractiveProvider(
            spec=AliasProviderSourceSpec(
                source_id="fake-provider",
                provider_type="fake_interactive",
                state_key="interactive-state-key",
                desired_alias_count=3,
            ),
            context=AliasProviderBootstrapContext(
                task_id="alias-test",
                purpose="automation_test",
                state_store_factory=lambda state_key: store,
            ),
        )

        result = provider.run_alias_generation_test(
            AliasAutomationTestPolicy(
                fresh_service_account=True,
                persist_state=True,
                minimum_alias_count=3,
                capture_enabled=True,
            )
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.stage_timeline[-1].code, "save_state")
        self.assertEqual(store.saved_keys, ["interactive-state-key"])
        self.assertEqual(store.saved[0].known_aliases, ["first@example.com", "created-2@example.com", "created-3@example.com"])

    def test_saved_state_matches_completed_save_state_timeline(self):
        store = _MemoryStore()
        provider = _FakeInteractiveProvider(
            spec=AliasProviderSourceSpec(
                source_id="fake-provider",
                provider_type="fake_interactive",
                state_key="interactive-state-key",
                desired_alias_count=3,
            ),
            context=AliasProviderBootstrapContext(
                task_id="alias-test",
                purpose="automation_test",
                state_store_factory=lambda state_key: store,
            ),
        )

        result = provider.run_alias_generation_test(
            AliasAutomationTestPolicy(
                fresh_service_account=True,
                persist_state=True,
                minimum_alias_count=3,
                capture_enabled=True,
            )
        )

        self.assertTrue(result.ok)
        self.assertEqual(store.saved[0].current_stage, {"code": "save_state", "label": "保存预览状态"})
        self.assertEqual(store.saved[0].stage_history[-1]["code"], "save_state")
        self.assertEqual(store.saved[0].stage_history[-1]["status"], "completed")
        self.assertEqual(
            [item["code"] for item in store.saved[0].stage_history],
            [item.code for item in result.stage_timeline],
        )

    def test_shared_loop_returns_structured_failure_when_domain_discovery_fails(self):
        class _FailingProvider(_FakeInteractiveProvider):
            def discover_alias_domains(self, context):
                raise RuntimeError("signed domain options unavailable")

        provider = _FailingProvider(
            spec=AliasProviderSourceSpec(
                source_id="fake-provider",
                provider_type="fake_interactive",
                state_key="fake-provider",
                desired_alias_count=3,
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        result = provider.run_alias_generation_test(
            AliasAutomationTestPolicy(
                fresh_service_account=True,
                persist_state=False,
                minimum_alias_count=3,
                capture_enabled=True,
            )
        )

        self.assertFalse(result.ok)
        self.assertIsNotNone(result.current_stage)
        self.assertEqual(result.failure.stage_code, "discover_alias_domains")
        self.assertEqual(result.failure.reason, "signed domain options unavailable")
        assert result.current_stage is not None
        self.assertEqual(result.current_stage.code, "discover_alias_domains")

    def test_failure_capture_summary_respects_capture_enabled_false(self):
        class _FailingProvider(_FakeInteractiveProvider):
            def discover_alias_domains(self, context):
                raise RuntimeError("signed domain options unavailable")

        provider = _FailingProvider(
            spec=AliasProviderSourceSpec(
                source_id="fake-provider",
                provider_type="fake_interactive",
                state_key="fake-provider",
                desired_alias_count=3,
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        result = provider.run_alias_generation_test(
            AliasAutomationTestPolicy(
                fresh_service_account=True,
                persist_state=False,
                minimum_alias_count=3,
                capture_enabled=False,
            )
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.capture_summary, [])
        self.assertEqual(provider.capture_calls, 0)

    def test_shared_loop_suppresses_duplicate_aliases_in_result(self):
        provider = _DuplicateInteractiveProvider(
            spec=AliasProviderSourceSpec(
                source_id="fake-provider",
                provider_type="fake_interactive",
                state_key="fake-provider",
                desired_alias_count=3,
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        result = provider.run_alias_generation_test(
            AliasAutomationTestPolicy(
                fresh_service_account=True,
                persist_state=False,
                minimum_alias_count=3,
                capture_enabled=True,
            )
        )

        self.assertEqual(
            [item["email"] for item in result.aliases],
            ["first@example.com", "created-3@example.com"],
        )

    def test_load_into_suppresses_duplicate_alias_leases(self):
        provider = _DuplicateInteractiveProvider(
            spec=AliasProviderSourceSpec(
                source_id="fake-provider",
                provider_type="fake_interactive",
                state_key="fake-provider",
                desired_alias_count=3,
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )
        pool_manager = _PoolManager()

        provider.load_into(pool_manager)

        self.assertEqual(
            [lease.alias_email for lease in pool_manager.leases],
            ["first@example.com", "created-3@example.com"],
        )

    def test_loaded_state_seeds_authenticated_context_when_not_fresh(self):
        loaded_state = InteractiveProviderState(
            state_key="interactive-state-key",
            service_account_email="loaded-service@example.com",
            confirmation_inbox_email="loaded-confirm@example.com",
            real_mailbox_email="loaded-real@example.com",
            service_password="loaded-pass",
            username="loaded-user",
            session_state={"cookie": "loaded-cookie"},
            domain_options=[
                {
                    "key": "loaded.example.com",
                    "domain": "loaded.example.com",
                    "label": "@loaded.example.com",
                    "raw": {"source": "loaded"},
                }
            ],
        )
        store = _MemoryStore(state=loaded_state)
        provider = _FakeInteractiveProvider(
            spec=AliasProviderSourceSpec(
                source_id="fake-provider",
                provider_type="fake_interactive",
                state_key="interactive-state-key",
                desired_alias_count=3,
            ),
            context=AliasProviderBootstrapContext(
                task_id="alias-test",
                purpose="automation_test",
                state_store_factory=lambda state_key: store,
            ),
        )

        result = provider.run_alias_generation_test(
            AliasAutomationTestPolicy(
                fresh_service_account=False,
                persist_state=False,
                minimum_alias_count=3,
                capture_enabled=True,
            )
        )

        seeded_context = provider.seen_contexts[0]
        self.assertEqual(seeded_context.service_account_email, "service@example.com")
        self.assertEqual(result.account_identity.service_account_email, "loaded-service@example.com")
        self.assertEqual(result.account_identity.confirmation_inbox_email, "loaded-confirm@example.com")
        self.assertEqual(result.account_identity.real_mailbox_email, "loaded-real@example.com")
        self.assertEqual(result.account_identity.service_password, "loaded-pass")
        self.assertEqual(result.account_identity.username, "loaded-user")

    def test_existing_account_helper_uses_first_configured_account(self):
        provider = _ExistingAccountProvider(
            spec=AliasProviderSourceSpec(
                source_id="existing-provider",
                provider_type="existing_account",
                provider_config={
                    "accounts": [
                        {"email": "fust@example.com", "label": "Fust"},
                        {"email": "other@example.com", "password": "ignored-pass"},
                    ]
                },
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        account = provider.select_service_account()

        self.assertEqual(
            account,
            {"email": "fust@example.com", "password": "fust@example.com", "label": "Fust"},
        )


class InteractiveProviderContractTests(unittest.TestCase):
    def test_myalias_pro_maps_account_email_verification_to_shared_requirement(self):
        provider = MyAliasProProvider(
            spec=AliasProviderSourceSpec(
                source_id="myalias-primary",
                provider_type="myalias_pro",
                state_key="myalias-primary",
                desired_alias_count=3,
                confirmation_inbox_config={
                    "account_email": "real@example.com",
                    "account_password": "mail-pass",
                    "match_email": "real@example.com",
                },
                provider_config={
                    "signup_url": "https://myalias.pro/signup/",
                    "login_url": "https://myalias.pro/login/",
                },
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        requirements = provider.resolve_verification_requirements(provider.ensure_authenticated_context("alias_test"))

        self.assertEqual(
            requirements,
            [VerificationRequirement(kind="account_email", label="验证服务账号邮箱", inbox_role="confirmation_inbox")],
        )

    def test_myalias_pro_shared_loop_maps_requirement_to_verify_account_email_stage(self):
        provider = MyAliasProProvider(
            spec=AliasProviderSourceSpec(
                source_id="myalias-primary",
                provider_type="myalias_pro",
                state_key="myalias-primary",
                desired_alias_count=3,
                confirmation_inbox_config={
                    "account_email": "real@example.com",
                    "account_password": "mail-pass",
                    "match_email": "real@example.com",
                },
                provider_config={
                    "signup_url": "https://myalias.pro/signup/",
                    "login_url": "https://myalias.pro/login/",
                },
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        result = provider.run_alias_generation_test(
            AliasAutomationTestPolicy(
                fresh_service_account=True,
                persist_state=False,
                minimum_alias_count=3,
                capture_enabled=True,
            )
        )

        self.assertTrue(result.ok)
        self.assertEqual(
            [item.code for item in result.stage_timeline],
            [
                "session_ready",
                "verify_account_email",
                "discover_alias_domains",
                "list_aliases",
                "create_aliases",
                "aliases_ready",
            ],
        )


class EmailShieldAndSimpleLoginTests(unittest.TestCase):
    _PROVIDER_CONFIG_SIGNED_OPTIONS_HTML = """
    <select name="signed-alias-suffix">
      <option value=".relearn763@aleeas.com.aeSMmw.cVxe2e9tMg2IiC2wXAO7CLb-8Bk">Mismatch label without canonical domain</option>
      <option value=".onion376@simplelogin.com.aeSMmw.tkj3IFpsj8LgW4ikJ55LVeeCILo">Another mismatched label</option>
    </select>
    """

    _SESSION_SIGNED_OPTIONS_HTML = """
    <select name="signed-alias-suffix">
      <option value=".orbit999@sessiondomain.com.aeSMmw.sessionToken123">Session label override</option>
    </select>
    """

    def test_emailshield_maps_account_verify_gate(self):
        provider = EmailShieldAliasProvider(
            spec=AliasProviderSourceSpec(
                source_id="emailshield-primary",
                provider_type="emailshield",
                state_key="emailshield-primary",
                desired_alias_count=3,
                confirmation_inbox_config={"account_email": "real@example.com", "match_email": "real@example.com"},
                provider_config={
                    "register_url": "https://emailshield.app/accounts/register/",
                    "login_url": "https://emailshield.app/accounts/login/",
                },
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        requirements = provider.resolve_verification_requirements(provider.ensure_authenticated_context("alias_test"))

        self.assertEqual(
            requirements,
            [VerificationRequirement(kind="account_email", label="验证 EmailShield 账号邮箱", inbox_role="confirmation_inbox")],
        )

    def test_simplelogin_selects_first_account_and_falls_back_password_to_email(self):
        provider = SimpleLoginAliasProvider(
            spec=AliasProviderSourceSpec(
                source_id="simplelogin-primary",
                provider_type="simplelogin",
                state_key="simplelogin-primary",
                desired_alias_count=3,
                provider_config={
                    "site_url": "https://simplelogin.io/",
                    "accounts": [
                        {"email": "fust@fst.cxwsss.online", "label": "fust"},
                        {"email": "logon@fst.cxwsss.online", "label": "logon", "password": "secret-pass"},
                    ],
                },
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        context = provider.ensure_authenticated_context("alias_test")

        self.assertEqual(context.service_account_email, "fust@fst.cxwsss.online")
        self.assertEqual(context.service_password, "fust@fst.cxwsss.online")
        self.assertEqual(context.username, "fust")

    def test_simplelogin_discovers_signed_alias_suffix_options_from_provider_config(self):
        provider = SimpleLoginAliasProvider(
            spec=AliasProviderSourceSpec(
                source_id="simplelogin-primary",
                provider_type="simplelogin",
                state_key="simplelogin-primary",
                desired_alias_count=3,
                provider_config={
                    "site_url": "https://simplelogin.io/",
                    "accounts": [{"email": "fust@fst.cxwsss.online"}],
                    "signed_alias_suffix_html": self._PROVIDER_CONFIG_SIGNED_OPTIONS_HTML,
                },
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        context = provider.ensure_authenticated_context("alias_test")
        options = provider.discover_alias_domains(context)

        self.assertEqual([item.domain for item in options], ["aleeas.com", "simplelogin.com"])
        self.assertEqual(options[0].key, ".relearn763@aleeas.com.aeSMmw.cVxe2e9tMg2IiC2wXAO7CLb-8Bk")
        self.assertEqual(options[0].raw["signed_value"], ".relearn763@aleeas.com.aeSMmw.cVxe2e9tMg2IiC2wXAO7CLb-8Bk")
        self.assertEqual(options[0].raw["text"], "Mismatch label without canonical domain")

    def test_simplelogin_prefers_session_state_signed_options_over_provider_config(self):
        provider = SimpleLoginAliasProvider(
            spec=AliasProviderSourceSpec(
                source_id="simplelogin-primary",
                provider_type="simplelogin",
                state_key="simplelogin-primary",
                desired_alias_count=3,
                provider_config={
                    "site_url": "https://simplelogin.io/",
                    "accounts": [{"email": "fust@fst.cxwsss.online"}],
                    "signed_alias_suffix_html": self._PROVIDER_CONFIG_SIGNED_OPTIONS_HTML,
                },
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        context = AuthenticatedProviderContext(
            service_account_email="fust@fst.cxwsss.online",
            confirmation_inbox_email="fust@fst.cxwsss.online",
            real_mailbox_email="fust@fst.cxwsss.online",
            service_password="fust@fst.cxwsss.online",
            username="fust",
            session_state={"signed_alias_suffix_html": self._SESSION_SIGNED_OPTIONS_HTML},
        )

        options = provider.discover_alias_domains(context)

        self.assertEqual([item.domain for item in options], ["sessiondomain.com"])
        self.assertEqual(options[0].key, ".orbit999@sessiondomain.com.aeSMmw.sessionToken123")

    def test_simplelogin_shared_flow_discovers_signed_options_and_returns_aliases(self):
        provider = SimpleLoginAliasProvider(
            spec=AliasProviderSourceSpec(
                source_id="simplelogin-primary",
                provider_type="simplelogin",
                state_key="simplelogin-primary",
                desired_alias_count=2,
                provider_config={
                    "site_url": "https://simplelogin.io/",
                    "accounts": [{"email": "fust@fst.cxwsss.online", "label": "fust"}],
                    "signed_alias_suffix_html": self._PROVIDER_CONFIG_SIGNED_OPTIONS_HTML,
                },
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        result = provider.run_alias_generation_test(
            AliasAutomationTestPolicy(
                fresh_service_account=True,
                persist_state=False,
                minimum_alias_count=2,
                capture_enabled=True,
            )
        )

        self.assertTrue(result.ok)
        self.assertEqual(
            [item.code for item in result.stage_timeline],
            [
                "session_ready",
                "discover_alias_domains",
                "list_aliases",
                "create_aliases",
                "aliases_ready",
            ],
        )
        self.assertEqual(len(result.aliases), 2)
        self.assertTrue(result.aliases[0]["email"].startswith("simplelogin-1@"))
        self.assertIn(
            result.aliases[0]["email"],
            {"simplelogin-1@aleeas.com", "simplelogin-1@simplelogin.com"},
        )
        self.assertIn(
            result.aliases[0]["signed_value"],
            {
                ".relearn763@aleeas.com.aeSMmw.cVxe2e9tMg2IiC2wXAO7CLb-8Bk",
                ".onion376@simplelogin.com.aeSMmw.tkj3IFpsj8LgW4ikJ55LVeeCILo",
            },
        )
        self.assertEqual(result.account_identity.service_account_email, "fust@fst.cxwsss.online")

    def test_simplelogin_shared_flow_returns_structured_failure_when_signed_options_missing(self):
        provider = SimpleLoginAliasProvider(
            spec=AliasProviderSourceSpec(
                source_id="simplelogin-primary",
                provider_type="simplelogin",
                state_key="simplelogin-primary",
                desired_alias_count=3,
                provider_config={"site_url": "https://simplelogin.io/", "accounts": [{"email": "fust@fst.cxwsss.online"}]},
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        result = provider.run_alias_generation_test(
            AliasAutomationTestPolicy(
                fresh_service_account=True,
                persist_state=False,
                minimum_alias_count=3,
                capture_enabled=True,
            )
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.failure.stage_code, "discover_alias_domains")
        self.assertEqual(result.failure.reason, "signed domain options unavailable")

    def test_secureinseconds_maps_forwarding_verification_to_shared_requirement(self):
        provider = SecureInSecondsProvider(
            spec=AliasProviderSourceSpec(
                source_id="secureinseconds-primary",
                provider_type="secureinseconds",
                state_key="secureinseconds-primary",
                desired_alias_count=3,
                confirmation_inbox_config={
                    "account_email": "real@example.com",
                    "account_password": "mail-pass",
                    "match_email": "real@example.com",
                },
                provider_config={
                    "register_url": "https://alias.secureinseconds.com/auth/register",
                    "login_url": "https://alias.secureinseconds.com/auth/signin",
                },
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        requirements = provider.resolve_verification_requirements(provider.ensure_authenticated_context("alias_test"))

        self.assertEqual(
            requirements,
            [VerificationRequirement(kind="forwarding_email", label="验证转发邮箱", inbox_role="confirmation_inbox")],
        )

    def test_secureinseconds_shared_loop_maps_requirement_to_verify_forwarding_email_stage(self):
        provider = SecureInSecondsProvider(
            spec=AliasProviderSourceSpec(
                source_id="secureinseconds-primary",
                provider_type="secureinseconds",
                state_key="secureinseconds-primary",
                desired_alias_count=3,
                confirmation_inbox_config={
                    "account_email": "real@example.com",
                    "account_password": "mail-pass",
                    "match_email": "real@example.com",
                },
                provider_config={
                    "register_url": "https://alias.secureinseconds.com/auth/register",
                    "login_url": "https://alias.secureinseconds.com/auth/signin",
                },
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        result = provider.run_alias_generation_test(
            AliasAutomationTestPolicy(
                fresh_service_account=True,
                persist_state=False,
                minimum_alias_count=3,
                capture_enabled=True,
            )
        )

        self.assertTrue(result.ok)
        self.assertEqual(
            [item.code for item in result.stage_timeline],
            [
                "session_ready",
                "verify_forwarding_email",
                "discover_alias_domains",
                "list_aliases",
                "create_aliases",
                "aliases_ready",
            ],
        )


class InteractiveStateRepositoryTests(unittest.TestCase):
    def test_repository_load_returns_new_state_when_store_missing(self):
        repository = InteractiveStateRepository(state_key="interactive-state-key")

        state = repository.load()

        self.assertIsInstance(state, InteractiveProviderState)
        self.assertEqual(state.known_aliases, [])
        self.assertEqual(state.current_stage, {"code": "", "label": ""})
        self.assertEqual(state.state_key, "interactive-state-key")

    def test_repository_save_passes_state_to_store(self):
        store = _MemoryStore()
        repository = InteractiveStateRepository(store=store, state_key="interactive-state-key")
        state = InteractiveProviderState(service_account_email="service@example.com")

        repository.save(state)

        self.assertEqual(store.saved, [state])
        self.assertEqual(store.saved_keys, ["interactive-state-key"])
        self.assertEqual(state.state_key, "interactive-state-key")

    def test_repository_load_uses_state_key_and_normalizes_loaded_state(self):
        store = _MemoryStore(state=InteractiveProviderState(service_account_email="service@example.com"))
        repository = InteractiveStateRepository(store=store, state_key="interactive-state-key")

        state = repository.load()

        self.assertEqual(store.loaded_keys, ["interactive-state-key"])
        self.assertEqual(state.state_key, "interactive-state-key")


class AliasEmailProviderTests(unittest.TestCase):
    def test_alias_email_maps_magic_link_login_requirement(self):
        provider = AliasEmailProvider(
            spec=AliasProviderSourceSpec(
                source_id="alias-email-primary",
                provider_type="alias_email",
                state_key="alias-email-primary",
                desired_alias_count=3,
                confirmation_inbox_config={"match_email": "real@example.com"},
                provider_config={"login_url": "https://alias.email/users/login/"},
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        requirements = provider.resolve_verification_requirements(provider.ensure_authenticated_context("alias_test"))

        self.assertEqual(
            requirements,
            [VerificationRequirement(kind="magic_link_login", label="消费登录魔法链接", inbox_role="confirmation_inbox")],
        )

    def test_alias_email_discovers_fixed_alias_email_domain(self):
        provider = AliasEmailProvider(
            spec=AliasProviderSourceSpec(
                source_id="alias-email-primary",
                provider_type="alias_email",
                state_key="alias-email-primary",
                desired_alias_count=3,
                confirmation_inbox_config={"match_email": "real@example.com"},
                provider_config={"login_url": "https://alias.email/users/login/"},
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        context = provider.ensure_authenticated_context("alias_test")
        options = provider.discover_alias_domains(context)

        self.assertEqual(options, [AliasDomainOption(key="alias.email", domain="alias.email", label="@alias.email")])

    def test_alias_email_create_alias_requires_discovered_domain(self):
        provider = AliasEmailProvider(
            spec=AliasProviderSourceSpec(
                source_id="alias-email-primary",
                provider_type="alias_email",
                state_key="alias-email-primary",
                desired_alias_count=3,
                confirmation_inbox_config={"match_email": "real@example.com"},
                provider_config={"login_url": "https://alias.email/users/login/"},
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        context = provider.ensure_authenticated_context("alias_test")

        with self.assertRaisesRegex(RuntimeError, "alias.email requires discovered domains"):
            provider.create_alias(context=context, domain=None, alias_index=1)


if __name__ == "__main__":
    unittest.main()
