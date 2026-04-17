import unittest
from unittest import mock
from pathlib import Path
from tempfile import TemporaryDirectory

from core.alias_pool.base import (
    AliasEmailLease,
    AliasLeaseStatus,
    AliasPoolExhaustedError,
    AliasSourceState,
)
from core.alias_pool.config import normalize_cloudmail_alias_pool_config
from core.alias_pool.manager import AliasEmailPoolManager
from core.alias_pool.service_base import AliasServiceProducerBase
from core.alias_pool.simple_generator import SimpleAliasGeneratorProducer
from core.alias_pool.static_list import StaticAliasListProducer
from core.alias_pool.vend_email_state import (
    VendEmailCaptureRecord,
    VendEmailFileStateStore,
    VendEmailServiceState,
)
from core.alias_pool.vend_email_service import (
    VendEmailAliasServiceProducer,
    VendEmailContractRuntime,
    VendEmailForwarderRecord,
    VendEmailRuntimeExecution,
)


class AliasPoolConfigTests(unittest.TestCase):
    def test_normalize_legacy_cloudmail_alias_config_builds_static_source(self):
        result = normalize_cloudmail_alias_pool_config(
            {
                "cloudmail_alias_enabled": True,
                "cloudmail_alias_emails": "alias1@example.com\nalias2@example.com",
                "cloudmail_alias_mailbox_email": "real@example.com",
            },
            task_id="task-1",
        )

        self.assertEqual(
            result,
            {
                "enabled": True,
                "task_id": "task-1",
                "sources": [
                    {
                        "id": "legacy-static",
                        "type": "static_list",
                        "emails": ["alias1@example.com", "alias2@example.com"],
                        "mailbox_email": "real@example.com",
                    }
                ],
            },
        )

    def test_normalize_returns_disabled_pool_when_alias_not_enabled(self):
        result = normalize_cloudmail_alias_pool_config({}, task_id="task-2")

        self.assertFalse(result["enabled"])
        self.assertEqual(result["sources"], [])


class AliasPoolConfigV2Tests(unittest.TestCase):
    def test_normalize_accepts_explicit_sources_structure(self):
        result = normalize_cloudmail_alias_pool_config(
            {
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "legacy-static",
                        "type": "static_list",
                        "emails": ["alias1@example.com"],
                        "mailbox_email": "real@example.com",
                    }
                ],
            },
            task_id="task-v2",
        )

        self.assertEqual(result["sources"][0]["type"], "static_list")
        self.assertEqual(result["sources"][0]["emails"], ["alias1@example.com"])

    def test_normalize_excludes_unsupported_source_types_from_explicit_sources(self):
        result = normalize_cloudmail_alias_pool_config(
            {
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "service-a",
                        "type": "alias_service",
                        "endpoint": "https://example.invalid",
                    },
                    {
                        "id": "legacy-static",
                        "type": "static_list",
                        "emails": ["alias1@example.com"],
                        "mailbox_email": "real@example.com",
                    },
                ],
            },
            task_id="task-v2-unsupported",
        )

        self.assertEqual(
            result["sources"],
            [
                {
                    "id": "legacy-static",
                    "type": "static_list",
                    "emails": ["alias1@example.com"],
                    "mailbox_email": "real@example.com",
                }
            ],
        )

    def test_normalize_accepts_simple_generator_source(self):
        result = normalize_cloudmail_alias_pool_config(
            {
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "simple-1",
                        "type": "simple_generator",
                        "prefix": "msiabc.",
                        "suffix": "@manyme.com",
                        "mailbox_email": "real@example.com",
                        "count": 5,
                        "middle_length_min": 3,
                        "middle_length_max": 6,
                    }
                ],
            },
            task_id="task-simple-generator",
        )

        self.assertEqual(
            result["sources"],
            [
                {
                    "id": "simple-1",
                    "type": "simple_generator",
                    "prefix": "msiabc.",
                    "suffix": "@manyme.com",
                    "mailbox_email": "real@example.com",
                    "count": 5,
                    "middle_length_min": 3,
                    "middle_length_max": 6,
                }
            ],
        )

    def test_normalize_accepts_vend_email_source(self):
        result = normalize_cloudmail_alias_pool_config(
            {
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "vend-1",
                        "type": "vend_email",
                        "register_url": " https://vend.example/register ",
                        "mailbox_base_url": " https://mailbox.example/base ",
                        "mailbox_email": "Real@Example.COM ",
                        "mailbox_password": " secret-pass ",
                        "alias_domain": " CxWsss.Online ",
                        "alias_count": "-5",
                    }
                ],
            },
            task_id="task-vend-email",
        )

        self.assertEqual(
            result["sources"],
            [
                {
                    "id": "vend-1",
                    "type": "vend_email",
                    "register_url": "https://vend.example/register",
                    "mailbox_base_url": "https://mailbox.example/base",
                    "mailbox_email": "real@example.com",
                    "mailbox_password": "secret-pass",
                    "alias_domain": "cxwsss.online",
                    "alias_count": 0,
                    "state_key": "vend-1",
                }
            ],
        )


class AliasEmailLeaseTests(unittest.TestCase):
    def test_alias_email_lease_defaults_to_available_status(self):
        lease = AliasEmailLease(
            alias_email="alias@example.com",
            real_mailbox_email="real@example.com",
            source_kind="static_list",
            source_id="legacy-static",
            source_session_id="static",
        )

        self.assertEqual(lease.status, AliasLeaseStatus.AVAILABLE)
        self.assertEqual(lease.alias_email, "alias@example.com")
        self.assertEqual(lease.real_mailbox_email, "real@example.com")


class AliasSourceStateTests(unittest.TestCase):
    def test_alias_source_state_enum_values_match_contract(self):
        self.assertEqual(AliasSourceState.IDLE.value, "idle")
        self.assertEqual(AliasSourceState.ACTIVE.value, "active")
        self.assertEqual(AliasSourceState.EXHAUSTED.value, "exhausted")
        self.assertEqual(AliasSourceState.FAILED.value, "failed")


class AliasPoolManagerTests(unittest.TestCase):
    def test_static_list_producer_loads_aliases_into_pool_and_acquire_marks_lease(self):
        manager = AliasEmailPoolManager(task_id="task-1")
        producer = StaticAliasListProducer(
            source_id="legacy-static",
            emails=["alias1@example.com", "alias2@example.com"],
            mailbox_email="real@example.com",
        )

        producer.load_into(manager)

        lease = manager.acquire_alias()

        self.assertEqual(lease.alias_email, "alias1@example.com")
        self.assertEqual(lease.real_mailbox_email, "real@example.com")
        self.assertEqual(lease.status, AliasLeaseStatus.LEASED)

    def test_acquire_alias_raises_when_pool_empty(self):
        manager = AliasEmailPoolManager(task_id="task-2")

        with self.assertRaises(AliasPoolExhaustedError):
            manager.acquire_alias()

    def test_cleanup_clears_task_pool(self):
        manager = AliasEmailPoolManager(task_id="task-3")
        producer = StaticAliasListProducer(
            source_id="legacy-static",
            emails=["alias1@example.com"],
            mailbox_email="real@example.com",
        )

        producer.load_into(manager)
        manager.cleanup()

        with self.assertRaises(AliasPoolExhaustedError):
            manager.acquire_alias()


class AliasPoolManagerSourceStateTests(unittest.TestCase):
    def test_manager_counts_available_aliases_per_source(self):
        manager = AliasEmailPoolManager(task_id="task-source-count")
        manager.add_lease(
            AliasEmailLease(
                alias_email="a1@example.com",
                real_mailbox_email="real@example.com",
                source_kind="static_list",
                source_id="source-a",
                source_session_id="static",
            )
        )
        manager.add_lease(
            AliasEmailLease(
                alias_email="a2@example.com",
                real_mailbox_email="real@example.com",
                source_kind="static_list",
                source_id="source-a",
                source_session_id="static",
            )
        )

        self.assertEqual(manager.available_count_for_source("source-a"), 2)

    def test_register_source_tracks_registered_producer(self):
        manager = AliasEmailPoolManager(task_id="task-register-source")
        producer = mock.Mock()
        producer.source_id = "source-a"

        manager.register_source(producer)

        self.assertIs(manager._sources["source-a"], producer)

    def test_manager_reports_no_live_sources_when_all_registered_sources_are_failed(self):
        manager = AliasEmailPoolManager(task_id="task-source-state")
        producer = mock.Mock()
        producer.source_id = "source-a"
        producer.state.return_value = AliasSourceState.FAILED
        manager.register_source(producer)

        self.assertFalse(manager.has_live_sources())

    def test_manager_reports_live_sources_when_registered_source_is_active(self):
        manager = AliasEmailPoolManager(task_id="task-live-source")
        producer = mock.Mock()
        producer.source_id = "source-a"
        producer.state.return_value = AliasSourceState.ACTIVE
        manager.register_source(producer)

        self.assertTrue(manager.has_live_sources())


class StaticAliasListProducerStateTests(unittest.TestCase):
    def test_static_list_producer_reports_exhausted_after_loading_all_aliases(self):
        manager = AliasEmailPoolManager(task_id="task-static-state")
        producer = StaticAliasListProducer(
            source_id="legacy-static",
            emails=["alias1@example.com"],
            mailbox_email="real@example.com",
        )

        self.assertEqual(producer.source_kind, "static_list")
        self.assertEqual(producer.state(), AliasSourceState.IDLE)

        producer.load_into(manager)

        self.assertEqual(producer.state(), AliasSourceState.EXHAUSTED)


class AliasServiceProducerBaseTests(unittest.TestCase):
    def test_service_base_is_idle_alias_service_and_not_yet_loadable(self):
        manager = AliasEmailPoolManager(task_id="task-service-base")
        producer = AliasServiceProducerBase(source_id="future-service")

        self.assertEqual(producer.source_kind, "alias_service")
        self.assertEqual(producer.state(), AliasSourceState.IDLE)

        with self.assertRaises(NotImplementedError):
            producer.load_into(manager)


class SimpleAliasGeneratorProducerTests(unittest.TestCase):
    def test_simple_generator_loads_generated_aliases_into_pool(self):
        manager = AliasEmailPoolManager(task_id="task-simple-generator-load")
        producer = SimpleAliasGeneratorProducer(
            source_id="simple-1",
            prefix="msiabc.",
            suffix="@manyme.com",
            mailbox_email="real@example.com",
            count=3,
            middle_length_min=3,
            middle_length_max=3,
        )

        self.assertEqual(producer.source_kind, "simple_generator")
        self.assertEqual(producer.state(), AliasSourceState.IDLE)

        producer.load_into(manager)

        self.assertEqual(producer.state(), AliasSourceState.EXHAUSTED)

        leases = [manager.acquire_alias(), manager.acquire_alias(), manager.acquire_alias()]
        self.assertEqual(len(leases), 3)
        self.assertEqual([lease.source_kind for lease in leases], ["simple_generator"] * 3)
        self.assertEqual([lease.source_id for lease in leases], ["simple-1"] * 3)
        self.assertEqual([lease.real_mailbox_email for lease in leases], ["real@example.com"] * 3)

        for lease in leases:
            self.assertTrue(lease.alias_email.startswith("msiabc."))
            self.assertTrue(lease.alias_email.endswith("@manyme.com"))
            middle = lease.alias_email[len("msiabc.") : -len("@manyme.com")]
            self.assertEqual(len(middle), 3)
            self.assertRegex(middle, r"^[a-z0-9]+$")

    def test_simple_generator_deduplicates_aliases_within_one_load(self):
        manager = AliasEmailPoolManager(task_id="task-simple-generator-dedup")
        producer = SimpleAliasGeneratorProducer(
            source_id="simple-1",
            prefix="prefix.",
            suffix="@manyme.com",
            mailbox_email="real@example.com",
            count=5,
            middle_length_min=1,
            middle_length_max=1,
        )

        generated = iter(["a", "a", "b", "b", "c", "d", "e"])
        with mock.patch.object(
            producer,
            "_generate_alias_email",
            side_effect=lambda: f"prefix.{next(generated)}@manyme.com",
        ):
            producer.load_into(manager)

        leases = [manager.acquire_alias() for _ in range(5)]
        self.assertEqual(
            [lease.alias_email for lease in leases],
            [
                "prefix.a@manyme.com",
                "prefix.b@manyme.com",
                "prefix.c@manyme.com",
                "prefix.d@manyme.com",
                "prefix.e@manyme.com",
            ],
        )


class VendEmailStateTests(unittest.TestCase):
    def test_capture_record_and_service_state_round_trip_through_spec_fields(self):
        capture_summary_record = VendEmailCaptureRecord(
            name="login",
            url="https://www.vend.email/auth/login",
            method="POST",
            request_headers_whitelist={"content-type": "application/x-www-form-urlencoded"},
            request_body_excerpt="user[email]=vendcap202604170108%40cxwsss.online",
            response_status=200,
            response_body_excerpt='{"ok":true}',
            captured_at="2026-04-16T10:01:00+08:00",
        )
        state = VendEmailServiceState(
            state_key="vend-1",
            service_email="vendcap202604170108@cxwsss.online",
            mailbox_email="admin@cxwsss.online",
            service_password="pass-123",
            session_cookies=[{"name": "session", "value": "cookie-1"}],
            session_storage={"token": "storage-1"},
            last_login_at="2026-04-16T20:00:00Z",
            last_verified_at="2026-04-16T20:05:00Z",
            known_aliases=["vendcapdemo20260417@serf.me", "vendcapdemo20260418@serf.me"],
            last_capture_summary=[capture_summary_record],
            last_error="",
        )

        payload = state.to_dict()

        self.assertEqual(
            payload,
            {
                "state_key": "vend-1",
                "service_email": "vendcap202604170108@cxwsss.online",
                "mailbox_email": "admin@cxwsss.online",
                "service_password": "pass-123",
                "session_cookies": [{"name": "session", "value": "cookie-1"}],
                "session_storage": {"token": "storage-1"},
                "last_login_at": "2026-04-16T20:00:00Z",
                "last_verified_at": "2026-04-16T20:05:00Z",
                "known_aliases": ["vendcapdemo20260417@serf.me", "vendcapdemo20260418@serf.me"],
                "last_capture_summary": [
                    {
                        "name": "login",
                        "url": "https://www.vend.email/auth/login",
                        "method": "POST",
                        "request_headers_whitelist": {"content-type": "application/x-www-form-urlencoded"},
                        "request_body_excerpt": "user[email]=vendcap202604170108%40cxwsss.online",
                        "response_status": 200,
                        "response_body_excerpt": '{"ok":true}',
                        "captured_at": "2026-04-16T10:01:00+08:00",
                    }
                ],
                "last_error": "",
            },
        )

        restored = VendEmailServiceState.from_dict(payload)

        self.assertEqual(restored, state)

    def test_service_state_from_dict_defaults_spec_fields_for_malformed_values(self):
        for malformed_value in [123, "not-a-list", None]:
            with self.subTest(last_capture_summary=malformed_value):
                restored = VendEmailServiceState.from_dict(
                    {
                        "state_key": "vend-1",
                        "service_email": "vendcap202604170108@cxwsss.online",
                        "mailbox_email": "admin@cxwsss.online",
                        "service_password": "secret-pass",
                        "session_cookies": "not-a-list",
                        "session_storage": "not-a-dict",
                        "last_login_at": 123,
                        "last_verified_at": None,
                        "known_aliases": "not-a-list",
                        "last_capture_summary": malformed_value,
                        "last_error": 456,
                    }
                )

                self.assertEqual(restored.service_email, "vendcap202604170108@cxwsss.online")
                self.assertEqual(restored.mailbox_email, "admin@cxwsss.online")
                self.assertEqual(restored.service_password, "secret-pass")
                self.assertEqual(restored.session_cookies, [])
                self.assertEqual(restored.session_storage, {})
                self.assertEqual(restored.last_login_at, "")
                self.assertEqual(restored.last_verified_at, "")
                self.assertEqual(restored.known_aliases, [])
                self.assertEqual(restored.last_capture_summary, [])
                self.assertEqual(restored.last_error, "456")

    def test_file_state_store_persists_and_restores_spec_state_shape(self):
        with TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "vend-email-state.json"
            store = VendEmailFileStateStore(store_path)
            expected = VendEmailServiceState(
                state_key="vend-1",
                service_email="vendcap202604170108@cxwsss.online",
                mailbox_email="admin@cxwsss.online",
                service_password="pass-123",
                session_cookies=[{"name": "session", "value": "cookie-1"}],
                session_storage={"token": "storage-1"},
                last_login_at="2026-04-16T20:00:00Z",
                last_verified_at="2026-04-16T20:05:00Z",
                known_aliases=["vendcapdemo20260417@serf.me"],
                last_capture_summary=[
                    VendEmailCaptureRecord(
                        name="create_forwarder",
                        url="https://www.vend.email/forwarders",
                        method="POST",
                        request_headers_whitelist={"content-type": "application/x-www-form-urlencoded"},
                        request_body_excerpt=(
                            "forwarder[local_part]=vendcapdemo20260417&"
                            "forwarder[domain_id]=42&"
                            "forwarder[recipient]=admin%40cxwsss.online"
                        ),
                        response_status=200,
                        response_body_excerpt='{"email":"vendcapdemo20260417@serf.me"}',
                        captured_at="2026-04-16T10:01:00+08:00",
                    )
                ],
                last_error="bootstrap failed",
            )

            store.save(expected)

            self.assertTrue(store_path.exists())
            restored = store.load()

            self.assertEqual(restored, expected)

    def test_service_state_from_dict_preserves_capture_summary_records_from_spec_field(self):
        restored = VendEmailServiceState.from_dict(
            {
                "state_key": "vend-1",
                "service_email": "vendcap202604170108@cxwsss.online",
                "mailbox_email": "admin@cxwsss.online",
                "service_password": "secret-pass",
                "last_capture_summary": [
                    {
                        "name": "register",
                        "url": "https://www.vend.email/auth",
                        "method": "POST",
                        "request_headers_whitelist": {"content-type": "application/x-www-form-urlencoded"},
                        "request_body_excerpt": (
                            "user[name]=vendcap202604170108&"
                            "user[email]=vendcap202604170108%40cxwsss.online&"
                            "user[password]=secret-pass"
                        ),
                        "response_status": 200,
                        "response_body_excerpt": '{"ok":true}',
                        "captured_at": "2026-04-16T10:00:00+08:00",
                    },
                    {
                        "name": "confirmation",
                        "url": "https://www.vend.email/auth/confirmation",
                        "method": "POST",
                        "request_headers_whitelist": {"content-type": "application/x-www-form-urlencoded"},
                        "request_body_excerpt": "user[email]=vendcap202604170108%40cxwsss.online",
                        "response_status": 200,
                        "response_body_excerpt": '{"ok":true}',
                        "captured_at": "2026-04-16T10:00:30+08:00",
                    },
                    {
                        "name": "login",
                        "url": "https://www.vend.email/auth/login",
                        "method": "POST",
                        "request_headers_whitelist": {"content-type": "application/x-www-form-urlencoded"},
                        "request_body_excerpt": "user[email]=vendcap202604170108%40cxwsss.online",
                        "response_status": 200,
                        "response_body_excerpt": '{"ok":true}',
                        "captured_at": "2026-04-16T10:01:00+08:00",
                    },
                    {
                        "name": "create_forwarder",
                        "url": "https://www.vend.email/forwarders",
                        "method": "POST",
                        "request_headers_whitelist": {"content-type": "application/x-www-form-urlencoded"},
                        "request_body_excerpt": (
                            "forwarder[local_part]=vendcapdemo20260417&"
                            "forwarder[domain_id]=42&"
                            "forwarder[recipient]=admin%40cxwsss.online"
                        ),
                        "response_status": 200,
                        "response_body_excerpt": '{"email":"vendcapdemo20260417@serf.me"}',
                        "captured_at": "2026-04-16T10:02:00+08:00",
                    }
                ],
            }
        )

        self.assertEqual(
            [record.name for record in restored.last_capture_summary],
            ["register", "confirmation", "login", "create_forwarder"],
        )


class _FakeVendEmailRuntime:
    def __init__(
        self,
        *,
        restore_ok,
        login_ok,
        register_ok,
        resend_confirmation_ok=True,
        aliases,
        created_aliases=None,
        captures=None,
    ):
        self.restore_ok = restore_ok
        if isinstance(login_ok, list):
            self.login_results = list(login_ok)
            self.login_ok = bool(self.login_results[-1]) if self.login_results else False
        else:
            self.login_results = None
            self.login_ok = login_ok
        self.register_ok = register_ok
        self.resend_confirmation_ok = resend_confirmation_ok
        self.aliases = list(aliases)
        self.created_aliases = list(created_aliases or [])
        self.captures = list(captures or [])
        self.calls = []

    def restore_session(self, state):
        self.calls.append("restore")
        return self.restore_ok

    def login(self, state, source):
        self.calls.append("login")
        if self.login_results is not None:
            if not self.login_results:
                raise AssertionError("unexpected extra vend login call")
            return self.login_results.pop(0)
        return self.login_ok

    def register(self, state, source):
        self.calls.append("register")
        return self.register_ok

    def resend_confirmation(self, state, source):
        self.calls.append("resend_confirmation")
        return self.resend_confirmation_ok

    def list_aliases(self, state, source):
        self.calls.append("list_aliases")
        return list(self.aliases)

    def create_aliases(self, state, source, missing_count):
        self.calls.append(f"create_aliases:{missing_count}")
        created = self.created_aliases[:missing_count]
        self.created_aliases = self.created_aliases[missing_count:]
        return created

    def capture_summary(self):
        return list(self.captures)


class _FakeVendEmailRuntimeWithoutCaptureSummary:
    def __init__(self, *, aliases):
        self.aliases = list(aliases)

    def restore_session(self, state):
        return True

    def login(self, state, source):
        return False

    def register(self, state, source):
        return False

    def resend_confirmation(self, state, source):
        return False

    def list_aliases(self, state, source):
        return list(self.aliases)

    def create_aliases(self, state, source, missing_count):
        return []


class _FakeVendEmailExecutor:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def execute(self, operation, state, source):
        self.calls.append(
            {
                "name": operation.name,
                "method": operation.method,
                "url": operation.url,
                "request_body_excerpt": operation.request_body_excerpt,
            }
        )
        if not self._responses:
            raise AssertionError("unexpected vend runtime operation")
        return self._responses.pop(0)


class VendEmailRuntimeContractTests(unittest.TestCase):
    def test_contract_register_resend_login_and_create_forwarder_capture_observed_shapes(self):
        state = VendEmailServiceState(
            state_key="vend-email-primary",
            service_email="vendcap202604170108@cxwsss.online",
            service_password="vend-secret",
            mailbox_email="admin@cxwsss.online",
        )
        source = {
            "register_url": "https://www.vend.email",
            "mailbox_email": "admin@cxwsss.online",
            "alias_domain": "serf.me",
            "alias_domain_id": "42",
        }
        runtime = VendEmailContractRuntime(
            executor=_FakeVendEmailExecutor(
                [
                    VendEmailRuntimeExecution(
                        ok=True,
                        response_status=200,
                        response_body_excerpt='{"ok":true}',
                        captured_at="2026-04-16T10:00:00+08:00",
                    ),
                    VendEmailRuntimeExecution(
                        ok=True,
                        response_status=200,
                        response_body_excerpt='{"ok":true}',
                        captured_at="2026-04-16T10:00:30+08:00",
                    ),
                    VendEmailRuntimeExecution(
                        ok=True,
                        response_status=200,
                        response_body_excerpt='{"ok":true}',
                        captured_at="2026-04-16T10:01:00+08:00",
                    ),
                    VendEmailRuntimeExecution(
                        ok=True,
                        response_status=200,
                        response_body_excerpt='{"email":"vendcapdemo20260417@serf.me"}',
                        captured_at="2026-04-16T10:02:00+08:00",
                        payload={
                            "email": "vendcapdemo20260417@serf.me",
                            "recipient": "admin@cxwsss.online",
                        },
                    ),
                ]
            )
        )

        self.assertTrue(runtime.register(state, source))
        self.assertTrue(runtime.resend_confirmation(state, source))
        self.assertTrue(runtime.login(state, source))
        created = runtime.create_forwarder(
            state,
            source,
            local_part="vendcapdemo20260417",
            domain_id="42",
            recipient="admin@cxwsss.online",
        )

        self.assertEqual(
            created,
            VendEmailForwarderRecord(
                alias_email="vendcapdemo20260417@serf.me",
                recipient_email="admin@cxwsss.online",
            ),
        )
        self.assertEqual(
            runtime.capture_summary(),
            [
                VendEmailCaptureRecord(
                    name="register",
                    url="https://www.vend.email/auth",
                    method="POST",
                    request_headers_whitelist={"content-type": "application/x-www-form-urlencoded"},
                    request_body_excerpt=(
                        "user[name]=vendcap202604170108&"
                        "user[email]=vendcap202604170108%40cxwsss.online&"
                        "user[password]=vend-secret"
                    ),
                    response_status=200,
                    response_body_excerpt='{"ok":true}',
                    captured_at="2026-04-16T10:00:00+08:00",
                ),
                VendEmailCaptureRecord(
                    name="confirmation",
                    url="https://www.vend.email/auth/confirmation",
                    method="POST",
                    request_headers_whitelist={"content-type": "application/x-www-form-urlencoded"},
                    request_body_excerpt="user[email]=vendcap202604170108%40cxwsss.online",
                    response_status=200,
                    response_body_excerpt='{"ok":true}',
                    captured_at="2026-04-16T10:00:30+08:00",
                ),
                VendEmailCaptureRecord(
                    name="login",
                    url="https://www.vend.email/auth/login",
                    method="POST",
                    request_headers_whitelist={"content-type": "application/x-www-form-urlencoded"},
                    request_body_excerpt=(
                        "user[email]=vendcap202604170108%40cxwsss.online&"
                        "user[password]=vend-secret"
                    ),
                    response_status=200,
                    response_body_excerpt='{"ok":true}',
                    captured_at="2026-04-16T10:01:00+08:00",
                ),
                VendEmailCaptureRecord(
                    name="create_forwarder",
                    url="https://www.vend.email/forwarders",
                    method="POST",
                    request_headers_whitelist={"content-type": "application/x-www-form-urlencoded"},
                    request_body_excerpt=(
                        "forwarder[local_part]=vendcapdemo20260417&"
                        "forwarder[domain_id]=42&"
                        "forwarder[recipient]=admin%40cxwsss.online"
                    ),
                    response_status=200,
                    response_body_excerpt='{"email":"vendcapdemo20260417@serf.me"}',
                    captured_at="2026-04-16T10:02:00+08:00",
                ),
            ],
        )

    def test_contract_lists_forwarders_and_create_aliases_preserving_recipient_split(self):
        state = VendEmailServiceState(
            state_key="vend-email-primary",
            service_email="vendcap202604170108@cxwsss.online",
            service_password="vend-secret",
            mailbox_email="admin@cxwsss.online",
        )
        source = {
            "register_url": "https://www.vend.email",
            "mailbox_email": "admin@cxwsss.online",
            "alias_domain": "serf.me",
            "alias_domain_id": "42",
            "alias_count": 2,
        }
        executor = _FakeVendEmailExecutor(
            [
                VendEmailRuntimeExecution(
                    ok=True,
                    response_status=200,
                    response_body_excerpt='[{"email":"vendcapexisting20260417@serf.me","recipient":"admin@cxwsss.online"}]',
                    captured_at="2026-04-16T10:03:00+08:00",
                    payload=[
                        {
                            "email": "vendcapexisting20260417@serf.me",
                            "recipient": "admin@cxwsss.online",
                        }
                    ],
                ),
                VendEmailRuntimeExecution(
                    ok=True,
                    response_status=200,
                    response_body_excerpt='{"email":"vendcap202604170108@serf.me"}',
                    captured_at="2026-04-16T10:04:00+08:00",
                    payload={
                        "email": "vendcap202604170108@serf.me",
                        "recipient": "admin@cxwsss.online",
                    },
                ),
            ]
        )
        runtime = VendEmailContractRuntime(executor=executor)

        listed = runtime.list_forwarders(state, source)
        aliases = runtime.create_aliases(state, source, 1)

        self.assertEqual(
            listed,
            [
                VendEmailForwarderRecord(
                    alias_email="vendcapexisting20260417@serf.me",
                    recipient_email="admin@cxwsss.online",
                )
            ],
        )
        self.assertEqual(aliases, ["vendcap202604170108@serf.me"])
        self.assertEqual(executor.calls[0]["method"], "GET")
        self.assertEqual(executor.calls[0]["url"], "https://www.vend.email/forwarders")
        self.assertEqual(executor.calls[0]["request_body_excerpt"], "")
        self.assertEqual(executor.calls[1]["request_body_excerpt"], (
            "forwarder[local_part]=vendcap202604170108&"
            "forwarder[domain_id]=42&"
            "forwarder[recipient]=admin%40cxwsss.online"
        ))


class VendEmailAliasServiceProducerTests(unittest.TestCase):
    def test_producer_falls_back_from_restore_to_login(self):
        manager = AliasEmailPoolManager(task_id="task-vend-email-load")
        state_store = mock.Mock()
        loaded_state = VendEmailServiceState(
            state_key="vend-email-primary",
            service_email="vendcap202604170108@cxwsss.online",
            mailbox_email="admin@cxwsss.online",
            service_password="vend-secret",
        )
        state_store.load.return_value = loaded_state
        captures = [
            VendEmailCaptureRecord(
                name="login",
                url="https://www.vend.email/auth/login",
                method="POST",
                request_headers_whitelist={"content-type": "application/x-www-form-urlencoded"},
                request_body_excerpt="user[email]=vendcap202604170108%40cxwsss.online",
                response_status=200,
                response_body_excerpt='{"ok":true}',
                captured_at="2026-04-16T10:01:00+08:00",
            )
        ]
        runtime = _FakeVendEmailRuntime(
            restore_ok=False,
            login_ok=True,
            register_ok=False,
            aliases=["vendcapdemo20260417@serf.me", "vendcapdemo20260418@serf.me"],
            captures=captures,
        )

        producer = VendEmailAliasServiceProducer(
            source={
                "id": "vend-email-primary",
                "type": "vend_email",
                "register_url": "https://www.vend.email/auth/register",
                "mailbox_base_url": "https://cxwsss.online/",
                "mailbox_email": "admin@cxwsss.online",
                "mailbox_password": "1103@Icity",
                "alias_domain": "serf.me",
                "alias_count": 2,
                "state_key": "vend-email-primary",
            },
            state_store=state_store,
            runtime=runtime,
        )

        self.assertEqual(producer.state(), AliasSourceState.IDLE)

        producer.load_into(manager)

        self.assertEqual(runtime.calls[:2], ["restore", "login"])
        self.assertEqual(producer.state(), AliasSourceState.EXHAUSTED)

        lease1 = manager.acquire_alias()
        lease2 = manager.acquire_alias()
        self.assertEqual(lease1.source_kind, "vend_email")
        self.assertEqual(lease1.real_mailbox_email, "admin@cxwsss.online")
        self.assertEqual(
            {lease1.alias_email, lease2.alias_email},
            {"vendcapdemo20260417@serf.me", "vendcapdemo20260418@serf.me"},
        )
        self.assertEqual(lease1.source_session_id, "vend-email-primary")
        self.assertEqual(lease2.source_session_id, "vend-email-primary")
        state_store.save.assert_called_once()
        saved_state = state_store.save.call_args.args[0]
        self.assertIs(saved_state, loaded_state)
        self.assertEqual(saved_state.service_email, "vendcap202604170108@cxwsss.online")
        self.assertEqual(saved_state.mailbox_email, "admin@cxwsss.online")
        self.assertEqual(saved_state.service_password, "vend-secret")
        self.assertEqual(
            [capture.name for capture in saved_state.last_capture_summary],
            ["login"],
        )

    def test_producer_keeps_service_account_identity_separate_from_mailbox_config(self):
        manager = AliasEmailPoolManager(task_id="task-vend-email-service-identity")
        state_store = mock.Mock()
        loaded_state = VendEmailServiceState(
            state_key="vend-email-primary",
            service_email="vendcap202604170108@cxwsss.online",
            service_password="vend-secret",
        )
        state_store.load.return_value = loaded_state
        runtime = _FakeVendEmailRuntime(
            restore_ok=True,
            login_ok=False,
            register_ok=False,
            aliases=["vendcapdemo20260417@serf.me"],
            captures=[],
        )

        producer = VendEmailAliasServiceProducer(
            source={
                "id": "vend-email-primary",
                "type": "vend_email",
                "register_url": "https://www.vend.email/auth/register",
                "mailbox_base_url": "https://cxwsss.online/",
                "mailbox_email": "admin@cxwsss.online",
                "mailbox_password": "mailbox-secret",
                "alias_domain": "serf.me",
                "alias_count": 1,
                "state_key": "vend-email-primary",
            },
            state_store=state_store,
            runtime=runtime,
        )

        producer.load_into(manager)

        saved_state = state_store.save.call_args.args[0]
        self.assertEqual(saved_state.service_email, "vendcap202604170108@cxwsss.online")
        self.assertEqual(saved_state.mailbox_email, "admin@cxwsss.online")
        self.assertEqual(saved_state.service_password, "vend-secret")
        lease = manager.acquire_alias()
        self.assertEqual(lease.real_mailbox_email, "admin@cxwsss.online")
        self.assertEqual(lease.alias_email, "vendcapdemo20260417@serf.me")

    def test_producer_bootstrap_registers_confirms_then_logs_in_before_alias_loading(self):
        manager = AliasEmailPoolManager(task_id="task-vend-email-register")
        state_store = mock.Mock()
        loaded_state = VendEmailServiceState(
            state_key="vend-email-state-key",
            service_email="vendcap202604170108@cxwsss.online",
            mailbox_email="admin@cxwsss.online",
            service_password="old-pass",
            last_capture_summary=[
                VendEmailCaptureRecord(
                    name="login",
                    url="https://old.example/auth/login",
                    method="POST",
                    request_headers_whitelist={"content-type": "application/x-www-form-urlencoded"},
                    request_body_excerpt="user[email]=vendcap202604170108%40cxwsss.online",
                    response_status=200,
                    response_body_excerpt='{"ok":true}',
                    captured_at="2026-04-15T10:01:00+08:00",
                )
            ],
        )
        state_store.load.return_value = loaded_state
        captures = [
            VendEmailCaptureRecord(
                name="register",
                url="https://www.vend.email/auth",
                method="POST",
                request_headers_whitelist={"content-type": "application/x-www-form-urlencoded"},
                request_body_excerpt=(
                    "user[name]=vendcap202604170108&"
                    "user[email]=vendcap202604170108%40cxwsss.online&"
                    "user[password]=old-pass"
                ),
                response_status=200,
                response_body_excerpt='{"ok":true}',
                captured_at="2026-04-16T10:02:00+08:00",
            ),
            VendEmailCaptureRecord(
                name="confirmation",
                url="https://www.vend.email/auth/confirmation",
                method="POST",
                request_headers_whitelist={"content-type": "application/x-www-form-urlencoded"},
                request_body_excerpt="user[email]=vendcap202604170108%40cxwsss.online",
                response_status=200,
                response_body_excerpt='{"ok":true}',
                captured_at="2026-04-16T10:03:00+08:00",
            ),
            VendEmailCaptureRecord(
                name="login",
                url="https://www.vend.email/auth/login",
                method="POST",
                request_headers_whitelist={"content-type": "application/x-www-form-urlencoded"},
                request_body_excerpt=(
                    "user[email]=vendcap202604170108%40cxwsss.online&"
                    "user[password]=old-pass"
                ),
                response_status=200,
                response_body_excerpt='{"ok":true}',
                captured_at="2026-04-16T10:03:30+08:00",
            ),
            VendEmailCaptureRecord(
                name="create_forwarder",
                url="https://www.vend.email/forwarders",
                method="POST",
                request_headers_whitelist={"content-type": "application/x-www-form-urlencoded"},
                request_body_excerpt=(
                    "forwarder[local_part]=vendcapdemo20260417&"
                    "forwarder[domain_id]=42&"
                    "forwarder[recipient]=admin%40cxwsss.online"
                ),
                response_status=200,
                response_body_excerpt='{"email":"vendcapdemo20260417@serf.me"}',
                captured_at="2026-04-16T10:04:00+08:00",
            ),
        ]
        runtime = _FakeVendEmailRuntime(
            restore_ok=False,
            login_ok=[False, True],
            register_ok=True,
            resend_confirmation_ok=True,
            aliases=["vendcapexisting20260417@serf.me"],
            created_aliases=[
                "vendcapexisting20260417@serf.me",
                "vendcapdemo20260417@serf.me",
                "vendcapdemo20260418@serf.me",
            ],
            captures=captures,
        )

        producer = VendEmailAliasServiceProducer(
            source={
                "id": "vend-email-primary",
                "type": "vend_email",
                "register_url": "https://www.vend.email/auth/register",
                "mailbox_base_url": "https://cxwsss.online/",
                "mailbox_email": "admin@cxwsss.online",
                "mailbox_password": "1103@Icity",
                "alias_domain": "serf.me",
                "alias_count": 3,
                "state_key": "vend-email-state-key",
            },
            state_store=state_store,
            runtime=runtime,
        )

        producer.load_into(manager)

        self.assertEqual(
            runtime.calls[:6],
            [
                "restore",
                "login",
                "register",
                "resend_confirmation",
                "login",
                "list_aliases",
            ],
        )
        self.assertIn("create_aliases:2", runtime.calls)
        leases = [manager.acquire_alias(), manager.acquire_alias(), manager.acquire_alias()]
        self.assertEqual(
            [lease.alias_email for lease in leases],
            [
                "vendcapexisting20260417@serf.me",
                "vendcapdemo20260417@serf.me",
                "vendcapdemo20260418@serf.me",
            ],
        )
        self.assertEqual(
            [lease.source_session_id for lease in leases],
            ["vend-email-state-key", "vend-email-state-key", "vend-email-state-key"],
        )
        saved_state = state_store.save.call_args.args[0]
        self.assertEqual(saved_state.service_email, "vendcap202604170108@cxwsss.online")
        self.assertEqual(saved_state.mailbox_email, "admin@cxwsss.online")
        self.assertEqual(saved_state.service_password, "old-pass")
        self.assertEqual(
            saved_state.last_capture_summary,
            [
                captures[0],
                captures[1],
                VendEmailCaptureRecord(
                    name="login",
                    url="https://www.vend.email/auth/login",
                    method="POST",
                    request_headers_whitelist={"content-type": "application/x-www-form-urlencoded"},
                    request_body_excerpt=(
                        "user[email]=vendcap202604170108%40cxwsss.online&"
                        "user[password]=old-pass"
                    ),
                    response_status=200,
                    response_body_excerpt='{"ok":true}',
                    captured_at="2026-04-16T10:03:30+08:00",
                ),
                captures[3],
            ],
        )
        self.assertEqual(
            getattr(saved_state, "known_aliases", None),
            [
                "vendcapexisting20260417@serf.me",
                "vendcapdemo20260417@serf.me",
                "vendcapdemo20260418@serf.me",
            ],
        )

    def test_producer_fails_when_confirmation_step_fails_after_register(self):
        manager = AliasEmailPoolManager(task_id="task-vend-email-confirmation-failed")
        state_store = mock.Mock()
        state_store.load.return_value = VendEmailServiceState(
            state_key="vend-email-primary",
            service_email="vendcap202604170108@cxwsss.online",
            service_password="vend-service-pass",
        )
        runtime = _FakeVendEmailRuntime(
            restore_ok=False,
            login_ok=[False, True],
            register_ok=True,
            resend_confirmation_ok=False,
            aliases=[],
        )

        producer = VendEmailAliasServiceProducer(
            source={
                "id": "vend-email-primary",
                "type": "vend_email",
                "register_url": "https://www.vend.email/auth/register",
                "mailbox_base_url": "https://cxwsss.online/",
                "mailbox_email": "admin@cxwsss.online",
                "mailbox_password": "1103@Icity",
                "alias_domain": "cxwsss.online",
                "alias_count": 1,
                "state_key": "vend-email-primary",
            },
            state_store=state_store,
            runtime=runtime,
        )

        with self.assertRaises(RuntimeError):
            producer.load_into(manager)

        self.assertEqual(
            runtime.calls,
            ["restore", "login", "register", "resend_confirmation"],
        )
        self.assertEqual(producer.state(), AliasSourceState.FAILED)

    def test_producer_deduplicates_aliases_before_saving_state_and_leases(self):
        manager = AliasEmailPoolManager(task_id="task-vend-email-dedup")
        state_store = mock.Mock()
        state_store.load.return_value = VendEmailServiceState(
            state_key="vend-email-primary",
            service_email="vendcap202604170108@cxwsss.online",
            service_password="vend-service-pass",
        )
        runtime = _FakeVendEmailRuntime(
            restore_ok=True,
            login_ok=False,
            register_ok=False,
            aliases=["dup@cxwsss.online", "dup@cxwsss.online", "unique@cxwsss.online"],
            created_aliases=["dup@cxwsss.online", "new@cxwsss.online"],
        )

        producer = VendEmailAliasServiceProducer(
            source={
                "id": "vend-email-primary",
                "type": "vend_email",
                "register_url": "https://www.vend.email/auth/register",
                "mailbox_base_url": "https://cxwsss.online/",
                "mailbox_email": "admin@cxwsss.online",
                "mailbox_password": "1103@Icity",
                "alias_domain": "cxwsss.online",
                "alias_count": 3,
                "state_key": "vend-email-primary",
            },
            state_store=state_store,
            runtime=runtime,
        )

        producer.load_into(manager)

        leases = [manager.acquire_alias(), manager.acquire_alias(), manager.acquire_alias()]
        self.assertEqual(
            [lease.alias_email for lease in leases],
            ["dup@cxwsss.online", "unique@cxwsss.online", "new@cxwsss.online"],
        )
        saved_state = state_store.save.call_args.args[0]
        self.assertNotEqual(saved_state.service_email, saved_state.mailbox_email)
        self.assertNotEqual(saved_state.service_password, producer.source["mailbox_password"])
        self.assertEqual(
            getattr(saved_state, "known_aliases", None),
            ["dup@cxwsss.online", "unique@cxwsss.online", "new@cxwsss.online"],
        )

    def test_producer_marks_failed_when_restore_login_register_all_fail(self):
        manager = AliasEmailPoolManager(task_id="task-vend-email-failed")
        state_store = mock.Mock()
        state_store.load.return_value = VendEmailServiceState(
            state_key="vend-email-primary",
            service_email="vendcap202604170108@cxwsss.online",
            service_password="vend-service-pass",
        )
        runtime = _FakeVendEmailRuntime(
            restore_ok=False,
            login_ok=False,
            register_ok=False,
            aliases=[],
        )

        producer = VendEmailAliasServiceProducer(
            source={
                "id": "vend-email-primary",
                "type": "vend_email",
                "register_url": "https://www.vend.email/auth/register",
                "mailbox_base_url": "https://cxwsss.online/",
                "mailbox_email": "admin@cxwsss.online",
                "mailbox_password": "1103@Icity",
                "alias_domain": "cxwsss.online",
                "alias_count": 1,
                "state_key": "vend-email-primary",
            },
            state_store=state_store,
            runtime=runtime,
        )

        self.assertNotEqual(
            state_store.load.return_value.service_email,
            producer.source["mailbox_email"],
        )
        self.assertNotEqual(
            state_store.load.return_value.service_password,
            producer.source["mailbox_password"],
        )

        with self.assertRaises(RuntimeError):
            producer.load_into(manager)

        self.assertEqual(producer.state(), AliasSourceState.FAILED)

    def test_producer_requires_runtime_capture_summary_contract(self):
        manager = AliasEmailPoolManager(task_id="task-vend-email-missing-capture-summary")
        state_store = mock.Mock()
        state_store.load.return_value = VendEmailServiceState(
            state_key="vend-email-primary",
            service_email="vendcap202604170108@cxwsss.online",
            service_password="vend-service-pass",
        )
        runtime = _FakeVendEmailRuntimeWithoutCaptureSummary(
            aliases=["alias1@cxwsss.online"],
        )

        producer = VendEmailAliasServiceProducer(
            source={
                "id": "vend-email-primary",
                "type": "vend_email",
                "register_url": "https://www.vend.email/auth/register",
                "mailbox_base_url": "https://cxwsss.online/",
                "mailbox_email": "admin@cxwsss.online",
                "mailbox_password": "1103@Icity",
                "alias_domain": "cxwsss.online",
                "alias_count": 1,
                "state_key": "vend-email-primary",
            },
            state_store=state_store,
            runtime=runtime,
        )

        self.assertNotEqual(
            state_store.load.return_value.service_email,
            producer.source["mailbox_email"],
        )
        self.assertNotEqual(
            state_store.load.return_value.service_password,
            producer.source["mailbox_password"],
        )

        with self.assertRaisesRegex(RuntimeError, "capture_summary"):
            producer.load_into(manager)

        self.assertEqual(producer.state(), AliasSourceState.FAILED)


if __name__ == "__main__":
    unittest.main()
