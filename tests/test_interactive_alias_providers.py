import unittest
from unittest import mock
from unittest.mock import patch

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


class _FakeHTTPResponse:
    def __init__(self, status_code, payload, *, url=""):
        self.status_code = status_code
        self._payload = payload
        self.text = payload if isinstance(payload, str) else ""
        self.url = url or ""

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        if isinstance(self._payload, str):
            raise ValueError("response is not json")
        return self._payload


class _FakeHTTPSession:
    def __init__(self, responses):
        self._responses = {key: list(value) for key, value in responses.items()}
        self.requests = []

    def request(self, method, url, **kwargs):
        key = (method.upper(), url)
        self.requests.append({"method": method.upper(), "url": url, "kwargs": dict(kwargs)})
        queue = self._responses.get(key) or []
        if not queue:
            raise AssertionError(f"unexpected request: {method} {url}")
        response = queue.pop(0)
        self._responses[key] = queue
        return response


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


class _FakeProtocolResponse:
    def __init__(self, *, text: str, status_code: int = 200, url: str = "https://myalias.pro/"):
        self.text = text
        self.status_code = status_code
        self.url = url
        self.headers = {}


class _FakeMyAliasRuntime:
    def __init__(self):
        self.cookies = [{"name": "sessionid", "value": "cookie-1"}]
        self.alias_html = "myalias-existing@myalias.pro myalias-created-2@myalias.pro myalias-created-3@myalias.pro"
        self.post_json_calls = []

    def get(self, url, **kwargs):
        if "verify-registration" in url or "verify" in url:
            return _FakeProtocolResponse(text="verified", url=url)
        if url.rstrip("/") == "https://myalias.pro/api/auth/me":
            return _FakeProtocolResponse(
                text='{"success":true,"user":{"username":"generated-user","email":"generated@example.com","verified":true}}',
                url=url,
            )
        if url.rstrip("/") == "https://myalias.pro/api/emails":
            return _FakeProtocolResponse(
                text='{"success":true,"emails":[{"id":1,"email":"generated@example.com","type":"ACCOUNT","primary":true,"verified":true}]}',
                url=url,
            )
        if url.rstrip("/") == "https://myalias.pro/api/aliases/random":
            return _FakeProtocolResponse(
                text='{"success":true,"alias":"bay.black","fullEmail":"bay.black@myalias.pro"}',
                url=url,
            )
        if url.rstrip("/") == "https://myalias.pro/api/aliases":
            return _FakeProtocolResponse(
                text='{"success":true,"aliases":[{"aliasEmail":"myalias-existing@myalias.pro"}],"stats":{"totalAliases":1}}',
                url=url,
            )
        return _FakeProtocolResponse(text="ok", url=url)

    def post_form(self, url, data, **kwargs):
        if "signup" in url:
            return _FakeProtocolResponse(text="Check your email! Account Created Successfully!", url=url)
        if "login" in url:
            return _FakeProtocolResponse(text="logged-in", url="https://myalias.pro/aliases/")
        if "aliases" in url:
            local_part = str(data.get("local_part") or "myalias-created").strip()
            email = f"{local_part}@myalias.pro"
            self.alias_html = f"myalias-existing@myalias.pro {email}"
            return _FakeProtocolResponse(text=email, url=url)
        return _FakeProtocolResponse(text="posted", url=url)

    def post_json(self, url, payload, **kwargs):
        self.post_json_calls.append((url, dict(payload or {})))
        if url.rstrip("/") == "https://myalias.pro/api/auth/signup":
            return _FakeProtocolResponse(
                text='{"success":true,"message":"Account created successfully! Please check your email to verify your account before logging in.","verificationRequired":true,"user":{"id":1,"username":"generated-user","email":"generated@example.com","plan":"FREE"}}',
                url=url,
            )
        if url.rstrip("/") == "https://myalias.pro/api/auth/login":
            return _FakeProtocolResponse(
                text='{"success":true,"requiresTwoFactor":false,"user":{"username":"generated-user","email":"generated@example.com","verified":true}}',
                url=url,
            )
        if url.rstrip("/") == "https://myalias.pro/api/aliases":
            alias_email = str(payload.get("aliasEmail") or "myalias-created@myalias.pro").strip().lower()
            return _FakeProtocolResponse(
                text='{"success":true,"alias":{"aliasEmail":"' + alias_email + '"}}',
                url=url,
                status_code=201,
            )
        return _FakeProtocolResponse(text='{"success":true}', url=url)

    def extract_hidden_inputs(self, html, *, names):
        return {"csrfmiddlewaretoken": "csrf-1"}

    def export_cookies(self):
        return list(self.cookies)


class _FakeMyAliasProtocolFailureRuntime(_FakeMyAliasRuntime):
    def post_json(self, url, payload, **kwargs):
        if url.rstrip("/") == "https://myalias.pro/api/auth/signup":
            return _FakeProtocolResponse(text='{"success":false,"message":"signup failed"}', url=url, status_code=400)
        return super().post_json(url, payload, **kwargs)

    def post_form(self, url, data, **kwargs):
        if "signup" in url:
            return _FakeProtocolResponse(text="signup failed", url=url)
        return super().post_form(url, data, **kwargs)


class _FakeBrowserRuntime:
    def __init__(self):
        self.opened = []
        self.fills = []
        self.clicks = []
        self.role_clicks = []
        self._url = "https://myalias.pro/signup/"

    def open(self, url):
        self.opened.append(url)
        self._url = url

    def fill(self, selector, value):
        self.fills.append((selector, value))

    def click(self, selector):
        self.clicks.append(selector)

    def click_role(self, role, name):
        self.role_clicks.append((role, name))
        if role == "button" and name == "Create Account":
            self._url = "https://myalias.pro/signup/complete"
        if role == "button" and name == "Sign In":
            self._url = "https://myalias.pro/aliases/"

    def current_url(self):
        return self._url

    def content(self):
        return "Check your email! Account Created Successfully!"

    def wait_for_text(self, text):
        if text != "Account Created Successfully":
            raise AssertionError(text)

    def wait_for_url(self, pattern):
        if "aliases" in pattern:
            self._url = "https://myalias.pro/aliases/"


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

    def test_simplelogin_uses_selected_account_from_rotating_state(self):
        store = _MemoryStore(
            InteractiveProviderState(
                state_key="simplelogin-primary",
                active_account_email="b@example.com",
                accounts_state=[
                    {
                        "email": "a@example.com",
                        "password": "pa",
                        "label": "a",
                        "service_account_email": "a@example.com",
                        "confirmation_inbox_email": "a@example.com",
                        "real_mailbox_email": "a@example.com",
                        "service_password": "pa",
                        "username": "a",
                        "session_state": {},
                        "domain_options": [],
                        "known_aliases": ["a-1@example.com", "a-2@example.com"],
                        "exhausted": True,
                    },
                    {
                        "email": "b@example.com",
                        "password": "pb",
                        "label": "bee",
                        "service_account_email": "b@example.com",
                        "confirmation_inbox_email": "b@example.com",
                        "real_mailbox_email": "b@example.com",
                        "service_password": "pb",
                        "username": "bee",
                        "session_state": {},
                        "domain_options": [],
                        "known_aliases": [],
                        "exhausted": False,
                    },
                ],
                known_aliases=["a-1@example.com", "a-2@example.com"],
            )
        )
        provider = SimpleLoginAliasProvider(
            spec=AliasProviderSourceSpec(
                source_id="simplelogin-primary",
                provider_type="simplelogin",
                state_key="simplelogin-primary",
                desired_alias_count=4,
                provider_config={
                    "site_url": "https://simplelogin.io/",
                    "single_account_alias_count": 2,
                    "accounts": [
                        {"email": "a@example.com", "password": "pa", "label": "a"},
                        {"email": "b@example.com", "password": "pb", "label": "bee"},
                    ],
                },
            ),
            context=AliasProviderBootstrapContext(
                task_id="alias-test",
                purpose="task_pool",
                state_store_factory=lambda state_key: store,
            ),
        )

        context = provider.ensure_authenticated_context("task_pool")

        self.assertEqual(context.service_account_email, "b@example.com")
        self.assertEqual(context.confirmation_inbox_email, "b@example.com")
        self.assertEqual(context.real_mailbox_email, "b@example.com")
        self.assertEqual(context.service_password, "pb")
        self.assertEqual(context.username, "bee")

    def test_emailshield_uses_selected_account_from_rotating_state(self):
        store = _MemoryStore(
            InteractiveProviderState(
                state_key="emailshield-primary",
                active_account_email="b@example.com",
                accounts_state=[
                    {
                        "email": "a@example.com",
                        "password": "pa",
                        "label": "a",
                        "service_account_email": "a@example.com",
                        "confirmation_inbox_email": "a@example.com",
                        "real_mailbox_email": "a@example.com",
                        "service_password": "pa",
                        "username": "a",
                        "session_state": {},
                        "domain_options": [],
                        "known_aliases": ["a-1@example.com", "a-2@example.com"],
                        "exhausted": True,
                    },
                    {
                        "email": "b@example.com",
                        "password": "pb",
                        "label": "bee",
                        "service_account_email": "b@example.com",
                        "confirmation_inbox_email": "b@example.com",
                        "real_mailbox_email": "b@example.com",
                        "service_password": "pb",
                        "username": "bee",
                        "session_state": {},
                        "domain_options": [],
                        "known_aliases": [],
                        "exhausted": False,
                    },
                ],
                known_aliases=["a-1@example.com", "a-2@example.com"],
            )
        )
        provider = EmailShieldAliasProvider(
            spec=AliasProviderSourceSpec(
                source_id="emailshield-primary",
                provider_type="emailshield",
                state_key="emailshield-primary",
                desired_alias_count=4,
                provider_config={
                    "single_account_alias_count": 2,
                    "accounts": [
                        {"email": "a@example.com", "password": "pa", "label": "a"},
                        {"email": "b@example.com", "password": "pb", "label": "bee"},
                    ],
                },
            ),
            context=AliasProviderBootstrapContext(
                task_id="alias-test",
                purpose="task_pool",
                state_store_factory=lambda state_key: store,
            ),
        )

        context = provider.ensure_authenticated_context("task_pool")

        self.assertEqual(context.service_account_email, "b@example.com")
        self.assertEqual(context.confirmation_inbox_email, "b@example.com")
        self.assertEqual(context.real_mailbox_email, "b@example.com")
        self.assertEqual(context.service_password, "pb")
        self.assertEqual(context.username, "bee")


class InteractiveProviderContractTests(unittest.TestCase):
    def test_myalias_pro_maps_account_email_verification_to_shared_requirement(self):
        fake_runtime = _FakeMyAliasRuntime()
        provider = MyAliasProProvider(
            spec=AliasProviderSourceSpec(
                source_id="myalias-primary",
                provider_type="myalias_pro",
                state_key="myalias-primary",
                desired_alias_count=3,
                confirmation_inbox_config={
                    "api_base": "https://mailbox.example",
                    "admin_email": "admin@example.com",
                    "admin_password": "mail-pass",
                    "account_email": "real@example.com",
                    "account_password": "mail-pass",
                    "match_email": "real@example.com",
                    "domain": "example.com",
                },
                provider_config={
                    "signup_url": "https://myalias.pro/signup/",
                    "login_url": "https://myalias.pro/login/",
                    "alias_url": "https://myalias.pro/aliases/",
                },
            ),
            context=AliasProviderBootstrapContext(
                task_id="alias-test",
                purpose="automation_test",
                runtime_builder=lambda source: (fake_runtime, None),
                confirmation_reader=mock.Mock(
                    fetch_confirmation=mock.Mock(
                        return_value=type("_Result", (), {"confirm_url": "https://myalias.pro/verify/token-1", "error": ""})()
                    )
                ),
            ),
        )

        requirements = provider.resolve_verification_requirements(provider.ensure_authenticated_context("alias_test"))

        self.assertEqual(
            requirements,
            [VerificationRequirement(kind="account_email", label="验证服务账号邮箱", inbox_role="confirmation_inbox")],
        )

    def test_myalias_pro_generates_separate_service_account_email_from_cloudmail(self):
        fake_runtime = _FakeMyAliasRuntime()

        class _GeneratedMailbox:
            email = "generated@example.com"

        mailbox_mock = mock.Mock()
        mailbox_mock.get_email.return_value = _GeneratedMailbox()

        with mock.patch("core.alias_pool.myalias_pro_provider.CloudMailMailbox", return_value=mailbox_mock):
            provider = MyAliasProProvider(
                spec=AliasProviderSourceSpec(
                    source_id="myalias-primary",
                    provider_type="myalias_pro",
                    state_key="myalias-primary",
                    desired_alias_count=1,
                    confirmation_inbox_config={
                        "api_base": "https://mailbox.example",
                        "admin_email": "admin@example.com",
                        "admin_password": "mail-pass",
                        "account_email": "real@example.com",
                        "account_password": "mail-pass",
                        "match_email": "real@example.com",
                        "domain": "example.com",
                    },
                    provider_config={
                        "signup_url": "https://myalias.pro/signup/",
                        "login_url": "https://myalias.pro/login/",
                        "alias_url": "https://myalias.pro/aliases/",
                    },
                ),
                context=AliasProviderBootstrapContext(
                    task_id="alias-test",
                    purpose="automation_test",
                    runtime_builder=lambda source: (fake_runtime, None),
                ),
            )

            context = provider.ensure_authenticated_context("alias_test")

        self.assertEqual(context.service_account_email, "generated@example.com")
        self.assertEqual(context.confirmation_inbox_email, "real@example.com")
        self.assertEqual(context.real_mailbox_email, "real@example.com")
        self.assertNotEqual(context.service_account_email, context.confirmation_inbox_email)

    def test_myalias_pro_shared_loop_maps_requirement_to_verify_account_email_stage(self):
        fake_runtime = _FakeMyAliasRuntime()
        mailbox_mock = mock.Mock()
        mailbox_mock.get_email.return_value = type("_MailboxAccount", (), {"email": "generated@example.com"})()

        with mock.patch("core.alias_pool.myalias_pro_provider.CloudMailMailbox", return_value=mailbox_mock):
            provider = MyAliasProProvider(
                spec=AliasProviderSourceSpec(
                    source_id="myalias-primary",
                    provider_type="myalias_pro",
                    state_key="myalias-primary",
                    desired_alias_count=3,
                    confirmation_inbox_config={
                        "api_base": "https://mailbox.example",
                        "admin_email": "admin@example.com",
                        "admin_password": "mail-pass",
                        "account_email": "real@example.com",
                        "account_password": "mail-pass",
                        "match_email": "real@example.com",
                        "domain": "example.com",
                    },
                    provider_config={
                        "signup_url": "https://myalias.pro/signup/",
                        "login_url": "https://myalias.pro/login/",
                        "alias_url": "https://myalias.pro/aliases/",
                    },
                ),
                context=AliasProviderBootstrapContext(
                    task_id="alias-test",
                    purpose="automation_test",
                    runtime_builder=lambda source: (fake_runtime, None),
                    confirmation_reader=mock.Mock(
                        fetch_confirmation=mock.Mock(
                            return_value=type("_Result", (), {"confirm_url": "https://myalias.pro/verify/token-1", "error": ""})()
                        )
                    ),
                ),
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

    def test_myalias_pro_http_create_alias_uses_real_payload_shape(self):
        fake_runtime = _FakeMyAliasRuntime()
        mailbox_mock = mock.Mock()
        mailbox_mock.get_email.return_value = type("_MailboxAccount", (), {"email": "generated@example.com"})()

        with mock.patch("core.alias_pool.myalias_pro_provider.CloudMailMailbox", return_value=mailbox_mock):
            provider = MyAliasProProvider(
                spec=AliasProviderSourceSpec(
                    source_id="myalias-primary",
                    provider_type="myalias_pro",
                    state_key="myalias-primary",
                    desired_alias_count=2,
                    confirmation_inbox_config={
                        "api_base": "https://mailbox.example",
                        "admin_email": "admin@example.com",
                        "admin_password": "mail-pass",
                        "account_email": "real@example.com",
                        "account_password": "mail-pass",
                        "match_email": "real@example.com",
                        "domain": "example.com",
                    },
                    provider_config={
                        "signup_url": "https://myalias.pro/signup/",
                        "login_url": "https://myalias.pro/login/",
                        "alias_url": "https://myalias.pro/dashboard/",
                    },
                ),
                context=AliasProviderBootstrapContext(
                    task_id="alias-test",
                    purpose="automation_test",
                    runtime_builder=lambda source: (fake_runtime, None),
                    confirmation_reader=mock.Mock(
                        fetch_confirmation=mock.Mock(
                            return_value=type("_Result", (), {"confirm_url": "https://myalias.pro/api/auth/verify-registration?token=abc", "error": ""})()
                        )
                    ),
                ),
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
        self.assertIn(
            "https://myalias.pro/api/aliases/",
            [item[0] for item in fake_runtime.post_json_calls],
        )
        alias_create_call = next(item for item in fake_runtime.post_json_calls if item[0] == "https://myalias.pro/api/aliases/")
        self.assertEqual(alias_create_call[1]["comment"], "automation test")
        self.assertEqual(alias_create_call[1]["forwardToEmails"], ["generated@example.com"])
        self.assertRegex(str(alias_create_call[1]["aliasEmail"] or ""), r"^[a-z0-9]+@myalias\.pro$")

    def test_myalias_pro_reports_protocol_signup_failure_without_browser_fallback(self):
        fake_runtime = _FakeMyAliasProtocolFailureRuntime()
        fake_browser = _FakeBrowserRuntime()
        mailbox_mock = mock.Mock()
        mailbox_mock.get_email.return_value = type("_MailboxAccount", (), {"email": "generated@example.com"})()

        with mock.patch("core.alias_pool.myalias_pro_provider.CloudMailMailbox", return_value=mailbox_mock):
            provider = MyAliasProProvider(
                spec=AliasProviderSourceSpec(
                    source_id="myalias-primary",
                    provider_type="myalias_pro",
                    state_key="myalias-primary",
                    desired_alias_count=1,
                    confirmation_inbox_config={
                        "api_base": "https://mailbox.example",
                        "admin_email": "admin@example.com",
                        "admin_password": "mail-pass",
                        "account_email": "real@example.com",
                        "account_password": "mail-pass",
                        "match_email": "real@example.com",
                        "domain": "example.com",
                    },
                    provider_config={
                        "signup_url": "https://myalias.pro/signup/",
                        "login_url": "https://myalias.pro/login/",
                        "alias_url": "https://myalias.pro/aliases/",
                    },
                ),
                context=AliasProviderBootstrapContext(
                    task_id="alias-test",
                    purpose="automation_test",
                    runtime_builder=lambda source: (fake_runtime, fake_browser),
                ),
            )

            with self.assertRaisesRegex(RuntimeError, "signup failed"):
                provider.ensure_authenticated_context("alias_test")

        self.assertEqual(fake_browser.opened, [])


class EmailShieldAndSimpleLoginTests(unittest.TestCase):
    _LOGIN_URL = "https://app.simplelogin.io/api/auth/login"
    _SETTING_URL = "https://app.simplelogin.io/api/setting"
    _DOMAINS_URL = "https://app.simplelogin.io/api/v2/setting/domains"
    _ALIAS_OPTIONS_URL = "https://app.simplelogin.io/api/v5/alias/options"
    _ALIASES_V2_URL = "https://app.simplelogin.io/api/v2/aliases"
    _ALIASES_V3_URL = "https://app.simplelogin.io/api/v3/aliases"
    _ALIASES_FALLBACK_URL = "https://app.simplelogin.io/api/aliases"
    _RANDOM_CREATE_V5_URL = "https://app.simplelogin.io/api/v5/alias/random/new"
    _RANDOM_CREATE_V3_URL = "https://app.simplelogin.io/api/v3/alias/random/new"
    _RANDOM_CREATE_V2_URL = "https://app.simplelogin.io/api/v2/alias/random/new"

    def _build_simplelogin_provider(self, *, desired_alias_count=3):
        return SimpleLoginAliasProvider(
            spec=AliasProviderSourceSpec(
                source_id="simplelogin-primary",
                provider_type="simplelogin",
                state_key="simplelogin-primary",
                desired_alias_count=desired_alias_count,
                provider_config={
                    "site_url": "https://app.simplelogin.io/",
                    "accounts": [
                        {"email": "fust@fst.cxwsss.online", "label": "fust"},
                        {"email": "logon@fst.cxwsss.online", "label": "logon", "password": "secret-pass"},
                    ],
                },
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

    def _response(self, status_code, payload, *, url=""):
        return _FakeHTTPResponse(status_code, payload, url=url)

    def _session_for_discovery(self):
        return _FakeHTTPSession(
            {
                ("POST", self._LOGIN_URL): [self._response(200, {"ok": True})],
                ("GET", self._SETTING_URL): [
                    self._response(200, {"random_alias_default_domain": "simplelogin.com"})
                ],
                ("GET", self._DOMAINS_URL): [
                    self._response(
                        200,
                        {
                            "domains": [
                                {"domain": "simplelogin.com", "enabled": True},
                                {"domain": "aleeas.com", "enabled": True},
                                {"domain": "disabled.example", "enabled": False},
                            ]
                        },
                    )
                ],
                ("GET", self._ALIAS_OPTIONS_URL): [
                    self._response(
                        200,
                        {
                            "suffixes": [
                                {
                                    "signed_suffix": ".relearn763@aleeas.com.aeSMmw.cVxe2e9tMg2IiC2wXAO7CLb-8Bk",
                                    "is_custom": False,
                                },
                                {
                                    "signed_suffix": ".onion376@simplelogin.com.aeSMmw.tkj3IFpsj8LgW4ikJ55LVeeCILo",
                                    "is_custom": False,
                                },
                                {
                                    "signed_suffix": ".skipme@disabled.example.aeSMmw.disabled",
                                    "is_custom": False,
                                },
                            ]
                        },
                    )
                ],
            }
        )

    def test_emailshield_maps_account_verify_gate(self):
        provider = EmailShieldAliasProvider(
            spec=AliasProviderSourceSpec(
                source_id="emailshield-primary",
                provider_type="emailshield",
                state_key="emailshield-primary",
                desired_alias_count=3,
                provider_config={
                    "accounts": [{"email": "loga@fst.cxwsss.online"}],
                },
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        requirements = provider.resolve_verification_requirements(provider.ensure_authenticated_context("alias_test"))

        self.assertEqual(requirements, [])

    def test_emailshield_uses_existing_account_and_default_password_contract(self):
        provider = EmailShieldAliasProvider(
            spec=AliasProviderSourceSpec(
                source_id="emailshield-primary",
                provider_type="emailshield",
                state_key="emailshield-primary",
                desired_alias_count=2,
                provider_config={"accounts": [{"email": "loga@fst.cxwsss.online"}]},
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        context = provider.ensure_authenticated_context("alias_test")

        self.assertEqual(context.service_account_email, "loga@fst.cxwsss.online")
        self.assertEqual(context.real_mailbox_email, "loga@fst.cxwsss.online")
        self.assertEqual(context.service_password, "1103@loga")

    def test_emailshield_shared_flow_logs_in_and_confirms_created_alias_from_alias_list(self):
        provider = EmailShieldAliasProvider(
            spec=AliasProviderSourceSpec(
                source_id="emailshield-primary",
                provider_type="emailshield",
                state_key="emailshield-primary",
                desired_alias_count=2,
                provider_config={"accounts": [{"email": "loga@fst.cxwsss.online"}]},
            ),
            context=AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )
        base_url = "https://emailshield.app"
        session = _FakeHTTPSession(
            {
                ("GET", f"{base_url}/accounts/login/"): [
                    self._response(200, '<form><input type="hidden" name="csrfmiddlewaretoken" value="csrf-login"></form>')
                ],
                ("POST", f"{base_url}/accounts/login/"): [
                    self._response(200, "dashboard", url=f"{base_url}/accounts/dashboard/")
                ],
                ("GET", f"{base_url}/aliases/"): [
                    self._response(200, "existing j93hpkszv5@emailshield.cc"),
                    self._response(200, "existing j93hpkszv5@emailshield.cc"),
                    self._response(200, "existing j93hpkszv5@emailshield.cc created z9newalias@emailshield.cc"),
                ],
                ("GET", f"{base_url}/aliases/create/"): [
                    self._response(200, '<form><input type="hidden" name="csrfmiddlewaretoken" value="csrf-create"></form>')
                ],
                ("POST", f"{base_url}/aliases/create/"): [
                    self._response(200, "created", url=f"{base_url}/aliases/")
                ],
            }
        )

        with patch.object(provider, "_build_http_session", return_value=session):
            result = provider.run_alias_generation_test(
                AliasAutomationTestPolicy(
                    fresh_service_account=True,
                    persist_state=False,
                    minimum_alias_count=2,
                    capture_enabled=True,
                )
            )

        self.assertTrue(result.ok)
        self.assertEqual([item["email"] for item in result.aliases], [
            "j93hpkszv5@emailshield.cc",
            "z9newalias@emailshield.cc",
        ])
        self.assertEqual(result.account_identity.service_password, "1103@loga")
        self.assertEqual(result.capture_summary[0].kind, "open_login")
        self.assertEqual(result.capture_summary[-1].kind, "list_aliases")

    def test_simplelogin_selects_first_account_and_falls_back_password_to_email(self):
        provider = self._build_simplelogin_provider()

        context = provider.ensure_authenticated_context("alias_test")

        self.assertEqual(context.service_account_email, "fust@fst.cxwsss.online")
        self.assertEqual(context.service_password, "fust@fst.cxwsss.online")
        self.assertEqual(context.username, "fust")

    def test_simplelogin_discovers_live_alias_domains_via_authenticated_http_contracts(self):
        provider = self._build_simplelogin_provider()
        session = self._session_for_discovery()

        context = provider.ensure_authenticated_context("alias_test")
        with patch.object(provider, "_build_http_session", return_value=session):
            options = provider.discover_alias_domains(context)

        self.assertEqual([item.domain for item in options], ["simplelogin.com", "aleeas.com"])
        self.assertEqual(options[0].key, ".onion376@simplelogin.com.aeSMmw.tkj3IFpsj8LgW4ikJ55LVeeCILo")
        self.assertEqual(options[1].raw["signed_suffix"], ".relearn763@aleeas.com.aeSMmw.cVxe2e9tMg2IiC2wXAO7CLb-8Bk")
        self.assertEqual(context.session_state["default_domain"], "simplelogin.com")
        self.assertEqual(context.session_state["available_domains"], ["simplelogin.com", "aleeas.com"])
        self.assertEqual([item["url"] for item in session.requests], [
            self._LOGIN_URL,
            self._SETTING_URL,
            self._DOMAINS_URL,
            self._ALIAS_OPTIONS_URL,
        ])

    def test_simplelogin_create_alias_prefers_api_random_contract_and_returns_alias_metadata(self):
        provider = self._build_simplelogin_provider()
        provider._random.seed(7)
        session = _FakeHTTPSession(
            {
                ("POST", self._LOGIN_URL): [self._response(200, {"ok": True})],
                ("POST", self._RANDOM_CREATE_V5_URL): [
                    self._response(200, {"alias": {"email": "sisyphus@simplelogin.com"}})
                ],
            }
        )
        context = provider.ensure_authenticated_context("alias_test")
        domain = AliasDomainOption(
            key=".onion376@simplelogin.com.aeSMmw.tkj3IFpsj8LgW4ikJ55LVeeCILo",
            domain="simplelogin.com",
            label="@simplelogin.com",
        )

        with patch.object(provider, "_build_http_session", return_value=session):
            created = provider.create_alias(context=context, domain=domain, alias_index=2)

        self.assertEqual(created.email, "sisyphus@simplelogin.com")
        self.assertEqual(created.metadata["signed_suffix"], domain.key)
        self.assertEqual(created.metadata["creation_endpoint"], "/api/v5/alias/random/new")
        self.assertEqual(session.requests[1]["kwargs"]["json"], {"signed_suffix": domain.key})

    def test_simplelogin_shared_flow_discovers_live_options_and_returns_aliases(self):
        provider = self._build_simplelogin_provider(desired_alias_count=2)
        session = _FakeHTTPSession(
            {
                ("POST", self._LOGIN_URL): [self._response(200, {"ok": True})],
                ("GET", self._SETTING_URL): [
                    self._response(200, {"random_alias_default_domain": "simplelogin.com"})
                ],
                ("GET", self._DOMAINS_URL): [
                    self._response(
                        200,
                        {"domains": [{"domain": "simplelogin.com"}, {"domain": "aleeas.com"}]},
                    )
                ],
                ("GET", self._ALIAS_OPTIONS_URL): [
                    self._response(
                        200,
                        {
                            "suffixes": [
                                {"signed_suffix": ".onion376@simplelogin.com.aeSMmw.tkj3IFpsj8LgW4ikJ55LVeeCILo"},
                                {"signed_suffix": ".relearn763@aleeas.com.aeSMmw.cVxe2e9tMg2IiC2wXAO7CLb-8Bk"},
                            ]
                        },
                    )
                ],
                ("GET", self._ALIASES_V2_URL): [self._response(404, {"error": "missing"})],
                ("GET", self._ALIASES_V3_URL): [self._response(404, {"error": "missing"})],
                ("GET", self._ALIASES_FALLBACK_URL): [
                    self._response(200, {"aliases": [{"email": "existing@simplelogin.com"}]})
                ],
                ("POST", self._RANDOM_CREATE_V5_URL): [
                    self._response(200, {"alias": {"email": "created-2@aleeas.com"}})
                ],
            }
        )
        provider._random.seed(3)

        with patch.object(provider, "_build_http_session", return_value=session), patch.object(
            provider,
            "pick_domain_option",
            side_effect=lambda domains, alias_index: domains[1],
        ):
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
        self.assertEqual(
            [item["email"] for item in result.aliases],
            ["existing@simplelogin.com", "created-2@aleeas.com"],
        )
        self.assertEqual(result.aliases[1]["signed_suffix"], ".relearn763@aleeas.com.aeSMmw.cVxe2e9tMg2IiC2wXAO7CLb-8Bk")
        self.assertEqual(result.account_identity.service_account_email, "fust@fst.cxwsss.online")
        self.assertEqual(result.capture_summary[0].kind, "login")
        self.assertEqual(result.capture_summary[-1].kind, "create_alias")

    def test_simplelogin_shared_flow_returns_structured_failure_when_live_domain_options_missing(self):
        provider = self._build_simplelogin_provider()
        session = _FakeHTTPSession(
            {
                ("POST", self._LOGIN_URL): [self._response(200, {"ok": True})],
                ("GET", self._SETTING_URL): [self._response(200, {"random_alias_default_domain": "simplelogin.com"})],
                ("GET", self._DOMAINS_URL): [self._response(200, {"domains": []})],
                ("GET", self._ALIAS_OPTIONS_URL): [self._response(200, {"suffixes": []})],
            }
        )

        with patch.object(provider, "_build_http_session", return_value=session):
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
        self.assertEqual(result.failure.reason, "simplelogin live alias domains unavailable")

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
