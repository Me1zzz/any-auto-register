import unittest

from core.alias_pool.interactive_provider_base import ExistingAccountAliasProviderBase, InteractiveAliasProviderBase
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


class _MemoryStore:
    def __init__(self, state=None):
        self.state = state
        self.saved = []

    def load(self):
        return self.state

    def save(self, state):
        self.state = state
        self.saved.append(state)


class _FakeInteractiveProvider(InteractiveAliasProviderBase):
    source_kind = "fake_interactive"

    def ensure_authenticated_context(self, mode: str) -> AuthenticatedProviderContext:
        return AuthenticatedProviderContext(
            service_account_email="service@example.com",
            confirmation_inbox_email="real@example.com",
            real_mailbox_email="real@example.com",
            service_password="secret-pass",
            username="service",
        )

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
                "save_state",
            ],
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


class InteractiveStateRepositoryTests(unittest.TestCase):
    def test_repository_load_returns_new_state_when_store_missing(self):
        repository = InteractiveStateRepository()

        state = repository.load()

        self.assertIsInstance(state, InteractiveProviderState)
        self.assertEqual(state.known_aliases, [])
        self.assertEqual(state.current_stage, {"code": "", "label": ""})

    def test_repository_save_passes_state_to_store(self):
        store = _MemoryStore()
        repository = InteractiveStateRepository(store=store)
        state = InteractiveProviderState(service_account_email="service@example.com")

        repository.save(state)

        self.assertEqual(store.saved, [state])


if __name__ == "__main__":
    unittest.main()
