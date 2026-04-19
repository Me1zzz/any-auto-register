import importlib
import importlib.util
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
from core.alias_pool.provider_contracts import (
    AliasAccountIdentity,
    AliasAutomationTestPolicy,
    AliasAutomationTestResult,
    AliasProviderBootstrapContext,
    AliasProviderFailure,
    AliasProviderSourceSpec,
    AliasProviderStage,
)
from core.alias_pool.vend_provider import VendAliasProvider
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
                        "cloudmail_api_base": " https://cloudmail.example/base ",
                        "cloudmail_admin_email": " Admin@Example.COM ",
                        "cloudmail_admin_password": " secret-pass ",
                        "cloudmail_domain": "mail.example.com",
                        "cloudmail_subdomain": " pool-a ",
                        "cloudmail_timeout": "45",
                        "alias_domain": " CxWsss.Online ",
                        "alias_domain_id": " 42 ",
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
                    "register_url": "https://www.vend.email/auth/register",
                    "cloudmail_api_base": "https://cloudmail.example/base",
                    "cloudmail_admin_email": "Admin@Example.COM",
                    "cloudmail_admin_password": "secret-pass",
                    "cloudmail_domain": "mail.example.com",
                    "cloudmail_subdomain": "pool-a",
                    "cloudmail_timeout": 45,
                    "alias_domain": "cxwsss.online",
                    "alias_domain_id": "42",
                    "alias_count": 0,
                    "state_key": "vend-1",
                    "confirmation_inbox": {
                        "provider": "cloudmail",
                        "api_base": "https://cloudmail.example/base",
                        "admin_email": "Admin@Example.COM",
                        "admin_password": "secret-pass",
                        "domain": "mail.example.com",
                        "subdomain": "pool-a",
                        "timeout": 45,
                    },
                }
            ],
        )

    def test_normalize_accepts_sources_from_json_string_for_config_store_round_trip(self):
        result = normalize_cloudmail_alias_pool_config(
            {
                "cloudmail_alias_enabled": True,
                "sources": (
                    '[{"id":"vend-1","type":"vend_email","register_url":"https://vend.example",'
                    '"cloudmail_api_base":"https://cloudmail.example","cloudmail_admin_email":"Admin@Example.COM",'
                    '"cloudmail_admin_password":"secret-pass","cloudmail_domain":"mail.example.com",'
                    '"cloudmail_subdomain":"pool-a","cloudmail_timeout":50,'
                    '"alias_domain":"Serf.ME","alias_domain_id":"42",'
                    '"alias_count":2}]'
                ),
            },
            task_id="task-vend-json-string",
        )

        self.assertEqual(
            result["sources"],
            [
                {
                    "id": "vend-1",
                    "type": "vend_email",
                    "register_url": "https://www.vend.email/auth/register",
                    "cloudmail_api_base": "https://cloudmail.example",
                    "cloudmail_admin_email": "Admin@Example.COM",
                    "cloudmail_admin_password": "secret-pass",
                    "cloudmail_domain": "mail.example.com",
                    "cloudmail_subdomain": "pool-a",
                    "cloudmail_timeout": 50,
                    "alias_domain": "serf.me",
                    "alias_domain_id": "42",
                    "alias_count": 2,
                    "state_key": "vend-1",
                    "confirmation_inbox": {
                        "provider": "cloudmail",
                        "api_base": "https://cloudmail.example",
                        "admin_email": "Admin@Example.COM",
                        "admin_password": "secret-pass",
                        "domain": "mail.example.com",
                        "subdomain": "pool-a",
                        "timeout": 50,
                    },
                }
            ],
        )

    def test_normalize_builds_sources_from_cloudmail_service_toggles(self):
        result = normalize_cloudmail_alias_pool_config(
            {
                "cloudmail_alias_enabled": True,
                "cloudmail_alias_emails": "alias1@example.com\nalias2@example.com",
                "cloudmail_admin_password": "cloudmail-pass",
                "cloudmail_alias_service_static_enabled": True,
                "cloudmail_alias_service_simple_enabled": True,
                "cloudmail_alias_service_simple_prefix": "msi.",
                "cloudmail_alias_service_simple_suffix": "@manyme.com",
                "cloudmail_alias_service_simple_count": 2,
                "cloudmail_alias_service_simple_middle_length_min": 3,
                "cloudmail_alias_service_simple_middle_length_max": 6,
                "cloudmail_alias_service_vend_enabled": True,
                "cloudmail_alias_service_vend_source_id": "vend-cloudmail",
                "cloudmail_alias_service_vend_alias_count": 5,
                "cloudmail_alias_service_vend_state_key": "vend-state",
            },
            task_id="task-cloudmail-alias-services",
        )

        self.assertEqual(result["enabled"], True)
        self.assertEqual(
            result["sources"],
            [
                {
                    "id": "legacy-static",
                    "type": "static_list",
                    "emails": ["alias1@example.com", "alias2@example.com"],
                },
                {
                    "id": "cloudmail-simple",
                    "type": "simple_generator",
                    "prefix": "msi.",
                    "suffix": "@manyme.com",
                    "count": 2,
                    "middle_length_min": 3,
                    "middle_length_max": 6,
                },
                {
                    "id": "vend-cloudmail",
                    "type": "vend_email",
                    "register_url": "https://www.vend.email/auth/register",
                    "cloudmail_api_base": "",
                    "cloudmail_admin_email": "",
                    "cloudmail_admin_password": "cloudmail-pass",
                    "cloudmail_domain": "",
                    "cloudmail_subdomain": "",
                    "cloudmail_timeout": 30,
                    "alias_domain": "serf.me",
                    "alias_domain_id": "42",
                    "alias_count": 5,
                    "state_key": "vend-state",
                    "confirmation_inbox": {
                        "provider": "cloudmail",
                        "admin_password": "cloudmail-pass",
                        "timeout": 30,
                    },
                },
            ],
        )

    def test_normalize_prefers_explicit_vend_values_over_synthesized_defaults_for_same_source_id(self):
        result = normalize_cloudmail_alias_pool_config(
            {
                "cloudmail_alias_enabled": True,
                "cloudmail_api_base": "https://payload.example/api",
                "cloudmail_admin_email": "payload-admin@example.com",
                "cloudmail_admin_password": "payload-secret",
                "cloudmail_domain": "payload.example.com",
                "cloudmail_subdomain": "payload-sub",
                "cloudmail_timeout": 99,
                "cloudmail_alias_service_vend_enabled": True,
                "cloudmail_alias_service_vend_source_id": "vend-primary",
                "cloudmail_alias_service_vend_alias_count": 2,
                "cloudmail_alias_service_vend_state_key": "vend-state",
                "sources": [
                    {
                        "id": "vend-primary",
                        "type": "vend_email",
                        "register_url": "https://explicit.example/register",
                        "cloudmail_api_base": "https://explicit.example/api",
                        "cloudmail_admin_email": "explicit-admin@example.com",
                        "cloudmail_admin_password": "explicit-secret",
                        "cloudmail_domain": "explicit.example.com",
                        "cloudmail_subdomain": "explicit-sub",
                        "cloudmail_timeout": 41,
                        "alias_domain": "custom.example",
                        "alias_domain_id": "99",
                        "alias_count": 7,
                        "state_key": "explicit-state",
                    }
                ],
            },
            task_id="task-vend-explicit-precedence",
        )

        self.assertEqual(
            result["sources"],
            [
                {
                    "id": "vend-primary",
                    "type": "vend_email",
                    "register_url": "https://explicit.example/register",
                    "cloudmail_api_base": "https://explicit.example/api",
                    "cloudmail_admin_email": "explicit-admin@example.com",
                    "cloudmail_admin_password": "explicit-secret",
                    "cloudmail_domain": "explicit.example.com",
                    "cloudmail_subdomain": "explicit-sub",
                    "cloudmail_timeout": 41,
                    "alias_domain": "custom.example",
                    "alias_domain_id": "99",
                    "alias_count": 7,
                    "state_key": "explicit-state",
                    "confirmation_inbox": {
                        "provider": "cloudmail",
                        "api_base": "https://explicit.example/api",
                        "admin_email": "explicit-admin@example.com",
                        "admin_password": "explicit-secret",
                        "domain": "explicit.example.com",
                        "subdomain": "explicit-sub",
                        "timeout": 41,
                    },
                }
            ],
        )

    def test_normalize_accepts_interactive_provider_sources(self):
        result = normalize_cloudmail_alias_pool_config(
            {
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "myalias-primary",
                        "type": "myalias_pro",
                        "alias_count": 3,
                        "state_key": "myalias-primary",
                        "confirmation_inbox": {
                            "provider": "cloudmail",
                            "account_email": "real@example.com",
                            "account_password": "mail-pass",
                            "match_email": "real@example.com",
                        },
                        "provider_config": {
                            "signup_url": "https://myalias.pro/signup/",
                            "login_url": "https://myalias.pro/login/",
                        },
                    },
                    {
                        "id": "simplelogin-primary",
                        "type": "simplelogin",
                        "alias_count": 3,
                        "state_key": "simplelogin-primary",
                        "provider_config": {
                            "site_url": "https://simplelogin.io/",
                            "accounts": [{"email": "fust@fst.cxwsss.online", "label": "fust"}],
                        },
                    },
                ],
            },
            task_id="task-interactive-sources",
        )

        self.assertEqual(result["sources"][0]["type"], "myalias_pro")
        self.assertEqual(result["sources"][1]["type"], "simplelogin")
        self.assertEqual(result["sources"][1]["provider_config"]["site_url"], "https://simplelogin.io/")
        self.assertEqual(
            result["sources"][0]["confirmation_inbox"],
            {
                "provider": "cloudmail",
                "account_email": "real@example.com",
                "account_password": "mail-pass",
                "match_email": "real@example.com",
            },
        )

    def test_decode_alias_provider_sources_excludes_manyme(self):
        from core.alias_pool.config import decode_alias_provider_sources

        decoded = decode_alias_provider_sources(
            [
                {"id": "manyme-primary", "type": "manyme", "provider_config": {"site_url": "https://manyme.com/"}},
                {
                    "id": "alias-email-primary",
                    "type": "alias_email",
                    "provider_config": {"login_url": "https://alias.email/users/login/"},
                },
            ]
        )

        self.assertEqual(
            decoded,
            [
                {
                    "id": "alias-email-primary",
                    "type": "alias_email",
                    "alias_count": 0,
                    "state_key": "alias-email-primary",
                    "provider_config": {"login_url": "https://alias.email/users/login/"},
                }
            ],
        )


class AliasProviderConfigEncodingTests(unittest.TestCase):
    def test_encode_and_decode_alias_provider_sources_round_trip_supported_types(self):
        from core.alias_pool import config as alias_config

        self.assertTrue(hasattr(alias_config, "encode_alias_provider_sources"))
        self.assertTrue(hasattr(alias_config, "decode_alias_provider_sources"))

        sources = [
            {
                "id": "legacy-static",
                "type": "static_list",
                "emails": ["alias1@example.com"],
                "mailbox_email": "real@example.com",
            },
            {
                "id": "simple-1",
                "type": "simple_generator",
                "prefix": "msi.",
                "suffix": "@manyme.com",
                "count": 2,
                "middle_length_min": 3,
                "middle_length_max": 6,
                "mailbox_email": "real@example.com",
            },
            {
                "id": "vend-1",
                "type": "vend_email",
                "register_url": "https://accounts.example.test/register",
                "cloudmail_api_base": "https://cloudmail.example/api",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret-pass",
                "cloudmail_domain": "mail.example.com",
                "cloudmail_subdomain": "pool-a",
                "cloudmail_timeout": 45,
                "alias_domain": "serf.me",
                "alias_count": 2,
                "state_key": "vend-state",
                "alias_domain_id": "42",
            },
        ]

        encoded = alias_config.encode_alias_provider_sources(sources)

        self.assertEqual(
            alias_config.decode_alias_provider_sources(encoded),
            [
                {
                    "id": "legacy-static",
                    "type": "static_list",
                    "emails": ["alias1@example.com"],
                },
                {
                    "id": "simple-1",
                    "type": "simple_generator",
                    "prefix": "msi.",
                    "suffix": "@manyme.com",
                    "count": 2,
                    "middle_length_min": 3,
                    "middle_length_max": 6,
                },
                {
                    "id": "vend-1",
                    "type": "vend_email",
                    "register_url": "https://accounts.example.test/register",
                    "cloudmail_api_base": "https://cloudmail.example/api",
                    "cloudmail_admin_email": "admin@example.com",
                    "cloudmail_admin_password": "secret-pass",
                    "cloudmail_domain": "mail.example.com",
                    "cloudmail_subdomain": "pool-a",
                    "cloudmail_timeout": 45,
                    "alias_domain": "serf.me",
                    "alias_count": 2,
                    "state_key": "vend-state",
                    "alias_domain_id": "42",
                    "confirmation_inbox": {
                        "provider": "cloudmail",
                        "api_base": "https://cloudmail.example/api",
                        "admin_email": "admin@example.com",
                        "admin_password": "secret-pass",
                        "domain": "mail.example.com",
                        "subdomain": "pool-a",
                        "timeout": 45,
                    },
                    "provider_config": {
                        "register_url": "https://accounts.example.test/register",
                        "cloudmail_api_base": "https://cloudmail.example/api",
                        "cloudmail_admin_email": "admin@example.com",
                        "cloudmail_admin_password": "secret-pass",
                        "cloudmail_domain": "mail.example.com",
                        "cloudmail_subdomain": "pool-a",
                        "cloudmail_timeout": 45,
                        "alias_domain": "serf.me",
                        "alias_domain_id": "42",
                        "alias_count": 2,
                        "state_key": "vend-state",
                        "confirmation_inbox": {
                            "provider": "cloudmail",
                            "api_base": "https://cloudmail.example/api",
                            "admin_email": "admin@example.com",
                            "admin_password": "secret-pass",
                            "domain": "mail.example.com",
                            "subdomain": "pool-a",
                            "timeout": 45,
                        },
                    },
                },
            ],
        )

    def test_decode_alias_provider_sources_is_shape_consistent_for_vend_list_and_json_inputs(self):
        from core.alias_pool import config as alias_config

        logical_source = [
            {
                "id": "vend-1",
                "type": "vend_email",
                "register_url": "https://accounts.example.test/register",
                "cloudmail_api_base": "https://cloudmail.example/api",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret-pass",
                "cloudmail_domain": "mail.example.com",
                "cloudmail_subdomain": "pool-a",
                "cloudmail_timeout": 45,
                "alias_domain": "serf.me",
                "alias_count": 2,
                "state_key": "vend-state",
                "alias_domain_id": "42",
            }
        ]

        self.assertEqual(
            alias_config.decode_alias_provider_sources(logical_source),
            alias_config.decode_alias_provider_sources(alias_config.encode_alias_provider_sources(logical_source)),
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
            current_stage={"code": "aliases_ready", "label": "别名预览已生成"},
            stage_history=[
                {"code": "session_ready", "label": "会话已就绪", "status": "completed"},
                {
                    "code": "list_aliases",
                    "label": "列出现有别名",
                    "status": "completed",
                    "detail": "找到 2 个别名",
                },
                {
                    "code": "aliases_ready",
                    "label": "别名预览已生成",
                    "status": "completed",
                    "detail": "预览共 2 个别名",
                },
            ],
            last_failure={"stageCode": "", "stageLabel": "", "reason": ""},
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
                "current_stage": {"code": "aliases_ready", "label": "别名预览已生成"},
                "stage_history": [
                    {"code": "session_ready", "label": "会话已就绪", "status": "completed"},
                    {
                        "code": "list_aliases",
                        "label": "列出现有别名",
                        "status": "completed",
                        "detail": "找到 2 个别名",
                    },
                    {
                        "code": "aliases_ready",
                        "label": "别名预览已生成",
                        "status": "completed",
                        "detail": "预览共 2 个别名",
                    },
                ],
                "last_failure": {"stageCode": "", "stageLabel": "", "reason": ""},
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
                        "current_stage": 123,
                        "stage_history": "not-a-list",
                        "last_failure": "not-a-dict",
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
                self.assertEqual(restored.current_stage, {"code": "", "label": ""})
                self.assertEqual(restored.stage_history, [])
                self.assertEqual(
                    restored.last_failure,
                    {"stageCode": "", "stageLabel": "", "reason": ""},
                )
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
                current_stage={"code": "create_aliases", "label": "创建别名"},
                stage_history=[
                    {"code": "session_ready", "label": "会话已就绪", "status": "completed"},
                    {
                        "code": "create_aliases",
                        "label": "创建别名",
                        "status": "failed",
                        "detail": "bootstrap failed",
                    },
                ],
                last_failure={
                    "stageCode": "create_aliases",
                    "stageLabel": "创建别名",
                    "reason": "bootstrap failed",
                    "retryable": True,
                },
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
                "current_stage": {"code": "aliases_ready", "label": "别名预览已生成"},
                "stage_history": [
                    {"code": "session_ready", "label": "会话已就绪", "status": "completed"},
                    {
                        "code": "aliases_ready",
                        "label": "别名预览已生成",
                        "status": "completed",
                        "detail": "预览共 1 个别名",
                    },
                ],
                "last_failure": {"stageCode": "", "stageLabel": "", "reason": ""},
            }
        )

        self.assertEqual(
            [record.name for record in restored.last_capture_summary],
            ["register", "confirmation", "login", "create_forwarder"],
        )
        self.assertEqual(
            restored.current_stage,
            {"code": "aliases_ready", "label": "别名预览已生成"},
        )
        self.assertEqual(
            restored.stage_history,
            [
                {"code": "session_ready", "label": "会话已就绪", "status": "completed"},
                {
                    "code": "aliases_ready",
                    "label": "别名预览已生成",
                    "status": "completed",
                    "detail": "预览共 1 个别名",
                },
            ],
        )
        self.assertEqual(
            restored.last_failure,
            {"stageCode": "", "stageLabel": "", "reason": ""},
        )


class _FakeVendEmailRuntime:
    def __init__(
        self,
        *,
        restore_ok,
        login_ok,
        register_ok,
        resend_confirmation_ok=True,
        confirmation_link="https://www.vend.email/auth/confirmation?confirmation_token=abc123",
        confirm_ok=True,
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
        self.confirmation_link = confirmation_link
        self.confirm_ok = confirm_ok
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

    def fetch_confirmation_link(self, state, source):
        self.calls.append("fetch_confirmation_link")
        return self.confirmation_link

    def confirm(self, confirmation_link, source):
        self.calls.append("confirm")
        return self.confirm_ok

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

    def fetch_confirmation_link(self, state, source):
        return ""

    def confirm(self, confirmation_link, source):
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


def _html_execution(*, html: str, final_url: str, status: int = 200):
    return VendEmailRuntimeExecution(
        ok=200 <= status < 300,
        response_status=status,
        response_body_excerpt=html,
        captured_at="2026-04-16T10:00:00+08:00",
        payload={
            "html": html,
            "final_url": final_url,
            "content_type": "text/html; charset=utf-8",
        },
        final_url=final_url,
        content_type="text/html; charset=utf-8",
    )


REGISTER_FORM_HTML = '''
<html><head><meta name="csrf-token" content="register-csrf"></head><body>
  <form action="/auth" method="post">
    <input type="hidden" name="authenticity_token" value="register-auth-token" />
  </form>
</body></html>
'''

LOGIN_FORM_HTML = '''
<html><head><meta name="csrf-token" content="login-csrf"></head><body>
  <form action="/auth/login" method="post">
    <input type="hidden" name="authenticity_token" value="login-auth-token" />
  </form>
</body></html>
'''

FORWARDERS_NEW_FORM_HTML = '''
<html><head><meta name="csrf-token" content="forwarder-csrf"></head><body>
  <form action="/forwarders" method="post">
    <input type="hidden" name="authenticity_token" value="forwarder-auth-token" />
    <select name="forwarder[domain_id]">
      <option value="42" selected>serf.me</option>
      <option value="27">berrymail.cc</option>
    </select>
  </form>
</body></html>
'''

FORWARDERS_LIST_HTML = '''
<html><body>
  <a href="/forwarders/vendcapexisting20260417@serf.me">existing</a>
</body></html>
'''

FORWARDER_DETAIL_HTML = '''
<html><body>
  <h1>vendcap202604170108@serf.me</h1>
</body></html>
'''


class _FakeVendEmailDefaultExecutor:
    def __init__(self):
        self.calls = []
        self.login_attempts = 0

    def execute(self, operation, state, source):
        self.calls.append(
            {
                "name": operation.name,
                "method": operation.method,
                "url": operation.url,
                "request_body_excerpt": operation.request_body_excerpt,
            }
        )
        if operation.name == "login":
            self.login_attempts += 1
            if self.login_attempts == 1:
                return VendEmailRuntimeExecution(
                    ok=False,
                    response_status=401,
                    response_body_excerpt='{"ok":false}',
                    captured_at="2026-04-18T12:00:00+08:00",
                    payload={},
                )
        if operation.name == "list_forwarders":
            return VendEmailRuntimeExecution(
                ok=True,
                response_status=200,
                response_body_excerpt="[]",
                captured_at="2026-04-18T12:00:01+08:00",
                payload=[],
            )
        if operation.name == "create_forwarder":
            return VendEmailRuntimeExecution(
                ok=True,
                response_status=200,
                response_body_excerpt='{"email":"vendcapdemo20260417@serf.me","recipient":"admin@cxwsss.online"}',
                captured_at="2026-04-18T12:00:02+08:00",
                payload={
                    "email": "vendcapdemo20260417@serf.me",
                    "recipient": "admin@cxwsss.online",
                },
            )
        return VendEmailRuntimeExecution(
            ok=True,
            response_status=200,
            response_body_excerpt='{"ok":true}',
            captured_at="2026-04-18T12:00:00+08:00",
            payload={},
        )

    def fetch_confirmation_link(self, state, source) -> str:
        self.calls.append(
            {
                "name": "mailbox_verification",
                "method": "GET",
                "url": str(source.get("mailbox_base_url") or ""),
                "request_body_excerpt": "",
            }
        )
        return "https://www.vend.email/auth/confirmation?confirmation_token=abc123"


class _RecordingAutomationProvider:
    source_kind = "recording_provider"

    def __init__(self, *, spec: AliasProviderSourceSpec, context: AliasProviderBootstrapContext, result: AliasAutomationTestResult):
        self.source_id = spec.source_id
        self.spec = spec
        self.context = context
        self.result = result
        self.received_policy = None

    @property
    def provider_type(self) -> str:
        return self.source_kind

    def load_into(self, pool_manager) -> None:
        raise AssertionError("automation test path should not call load_into")

    def run_alias_generation_test(self, policy: AliasAutomationTestPolicy) -> AliasAutomationTestResult:
        self.received_policy = policy
        return self.result


class AliasAutomationTestServiceTests(unittest.TestCase):
    def test_service_builds_provider_context_and_maps_structured_result(self):
        spec = AliasProviderSourceSpec(
            source_id="simple-1",
            provider_type="simple_generator",
            raw_source={"id": "simple-1", "type": "simple_generator"},
            desired_alias_count=1,
        )
        provider_result = AliasAutomationTestResult(
            provider_type="simple_generator",
            source_id="simple-1",
            account_identity=AliasAccountIdentity(real_mailbox_email="real@example.com"),
            aliases=[{"email": "alias@example.com"}],
            current_stage=AliasProviderStage(code="ready", label="Ready", status="completed"),
            stage_timeline=[AliasProviderStage(code="ready", label="Ready", status="completed")],
            failure=AliasProviderFailure(),
            ok=True,
            error="",
        )
        seen = {}

        def bootstrap_build(*, spec, context):
            seen["spec"] = spec
            seen["context"] = context
            provider = _RecordingAutomationProvider(spec=spec, context=context, result=provider_result)
            seen["provider"] = provider
            return provider

        service_module = importlib.import_module("core.alias_pool.automation_test")
        service = service_module.AliasAutomationTestService(
            source_spec_builder=lambda pool_config: [spec],
            bootstrap=mock.Mock(build=bootstrap_build),
        )

        result = service.run(pool_config={"enabled": True, "sources": [spec.raw_source]}, source_id="simple-1", task_id="alias-test")

        self.assertEqual(result.source_id, "simple-1")
        self.assertEqual(result.source_type, "simple_generator")
        self.assertEqual(result.alias_email, "alias@example.com")
        self.assertEqual(result.real_mailbox_email, "real@example.com")
        self.assertEqual(result.current_stage, {"code": "ready", "label": "Ready"})
        self.assertEqual(result.stages, [{"code": "ready", "label": "Ready", "status": "completed"}])
        self.assertEqual(result.failure, {"stageCode": "", "stageLabel": "", "reason": ""})
        self.assertEqual(seen["spec"], spec)
        self.assertEqual(seen["context"].purpose, "automation_test")
        self.assertEqual(seen["context"].task_id, "alias-test")
        self.assertEqual(seen["context"].test_policy, AliasAutomationTestPolicy(
            fresh_service_account=True,
            persist_state=False,
            minimum_alias_count=3,
            capture_enabled=True,
        ))
        self.assertEqual(seen["provider"].received_policy, seen["context"].test_policy)

    def test_service_is_provider_first_for_vend_and_does_not_use_probe_service_as_primary_path(self):
        spec = AliasProviderSourceSpec(
            source_id="vend-1",
            provider_type="vend_email",
            raw_source={"id": "vend-1", "type": "vend_email"},
            desired_alias_count=2,
            state_key="vend-state",
            alias_domain_id="42",
        )
        provider_result = AliasAutomationTestResult(
            provider_type="vend_email",
            source_id="vend-1",
            account_identity=AliasAccountIdentity(
                service_account_email="service@example.com",
                real_mailbox_email="real@example.com",
                service_password="secret-pass",
                username="service",
            ),
            aliases=[{"email": "alias-001@example.com"}, {"email": "alias-002@example.com"}],
            current_stage=AliasProviderStage(code="aliases_ready", label="别名预览已生成", status="completed"),
            stage_timeline=[
                AliasProviderStage(code="session_ready", label="会话已就绪", status="completed"),
                AliasProviderStage(code="aliases_ready", label="别名预览已生成", status="completed", detail="预览共 2 个别名"),
            ],
            failure=AliasProviderFailure(),
            ok=True,
            error="",
        )
        seen = {}

        def bootstrap_build(*, spec, context):
            seen["spec"] = spec
            seen["context"] = context
            provider = _RecordingAutomationProvider(spec=spec, context=context, result=provider_result)
            seen["provider"] = provider
            return provider

        service_module = importlib.import_module("core.alias_pool.automation_test")
        service = service_module.AliasAutomationTestService(
            source_spec_builder=lambda pool_config: [spec],
            bootstrap=mock.Mock(build=bootstrap_build),
        )

        result = service.run(pool_config={"enabled": True, "sources": [spec.raw_source]}, source_id="vend-1", task_id="alias-test")

        self.assertEqual(result.source_id, "vend-1")
        self.assertEqual(result.source_type, "vend_email")
        self.assertEqual(result.alias_email, "alias-001@example.com")
        self.assertEqual(result.service_email, "service@example.com")
        self.assertEqual(result.real_mailbox_email, "real@example.com")
        self.assertEqual(result.account["password"], "secret-pass")
        self.assertEqual(result.account["username"], "service")
        self.assertEqual(result.steps, ["load_source", "acquire_alias"])
        self.assertEqual(result.current_stage, {"code": "aliases_ready", "label": "别名预览已生成"})
        self.assertEqual(result.stages[1]["detail"], "预览共 2 个别名")
        self.assertEqual(seen["spec"], spec)
        self.assertEqual(seen["context"].test_policy.minimum_alias_count, 3)

    def test_vend_adapter_calls_provider_run_alias_generation_test_directly(self):
        service_module = importlib.import_module("core.alias_pool.automation_test")
        spec = AliasProviderSourceSpec(
            source_id="vend-1",
            provider_type="vend_email",
            raw_source={"id": "vend-1", "type": "vend_email"},
            desired_alias_count=2,
            state_key="vend-state",
            alias_domain_id="42",
        )
        policy = AliasAutomationTestPolicy(
            fresh_service_account=True,
            persist_state=False,
            minimum_alias_count=3,
            capture_enabled=True,
        )
        context = AliasProviderBootstrapContext(
            task_id="manual-debug-run",
            purpose="automation_test",
            runtime_builder=mock.sentinel.runtime_builder,
            state_store_factory=mock.sentinel.state_store_factory,
            test_policy=policy,
        )
        provider_result = AliasAutomationTestResult(
            provider_type="vend_email",
            source_id="vend-1",
            account_identity=AliasAccountIdentity(
                service_account_email="service@example.com",
                real_mailbox_email="real@example.com",
                service_password="secret-pass",
                username="service",
            ),
            aliases=[
                {"email": "alias-001@example.com"},
                {"email": "alias-002@example.com"},
                {"email": "alias-003@example.com"},
            ],
            current_stage=AliasProviderStage(code="aliases_ready", label="别名预览已生成", status="completed"),
            stage_timeline=[AliasProviderStage(code="aliases_ready", label="别名预览已生成", status="completed")],
            failure=AliasProviderFailure(),
            ok=True,
            error="",
        )
        provider = mock.Mock()
        provider.provider_type = "vend_email"
        provider.run_alias_generation_test.return_value = provider_result

        with mock.patch.object(service_module, "build_vend_email_alias_service_producer", return_value=provider) as builder:
            adapter = service_module._VendEmailAliasProviderAdapter(spec=spec, context=context)
            result = adapter.run_alias_generation_test(policy)

        builder.assert_called_once_with(
            source=spec.raw_source,
            task_id="manual-debug-run",
            state_store_factory=mock.sentinel.state_store_factory,
            runtime_builder=mock.sentinel.runtime_builder,
        )
        provider.run_alias_generation_test.assert_called_once_with(policy)
        provider.load_into.assert_not_called()
        self.assertIs(result, provider_result)

    def test_provider_adapters_honor_context_task_id_and_policy_minimum_alias_count(self):
        module_path = Path(__file__).resolve().parents[1] / "core" / "alias_pool" / "provider_adapters.py"
        spec = importlib.util.spec_from_file_location("alias_provider_adapters_under_test", module_path)
        self.assertIsNotNone(spec)
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        with mock.patch.object(module, "AliasEmailPoolManager") as manager_cls:
            manager = manager_cls.return_value
            leases = [
                mock.Mock(alias_email="alias-001@example.com", real_mailbox_email="real@example.com"),
                mock.Mock(alias_email="alias-002@example.com", real_mailbox_email="real@example.com"),
                mock.Mock(alias_email="alias-003@example.com", real_mailbox_email="real@example.com"),
            ]
            manager.acquire_alias.side_effect = leases
            adapter = module.build_simple_generator_alias_provider(
                AliasProviderSourceSpec(
                    source_id="simple-1",
                    provider_type="simple_generator",
                    raw_source={
                        "id": "simple-1",
                        "type": "simple_generator",
                        "prefix": "msi.",
                        "suffix": "@manyme.com",
                        "mailbox_email": "real@example.com",
                        "count": 1,
                        "middle_length_min": 3,
                        "middle_length_max": 3,
                    },
                    desired_alias_count=1,
                ),
                AliasProviderBootstrapContext(task_id="task-from-context", purpose="automation_test"),
            )

            producer = adapter.producer
            result = adapter.run_alias_generation_test(
                AliasAutomationTestPolicy(
                    fresh_service_account=True,
                    persist_state=False,
                    minimum_alias_count=3,
                    capture_enabled=True,
                )
            )

        manager_cls.assert_called_once_with(task_id="task-from-context")
        self.assertEqual(producer.count, 3)
        self.assertEqual(result.aliases, [
            {"email": "alias-001@example.com"},
            {"email": "alias-002@example.com"},
            {"email": "alias-003@example.com"},
        ])
        self.assertEqual(result.account_identity.real_mailbox_email, "real@example.com")

    def test_provider_adapter_module_exists_for_static_and_simple_sources(self):
        module_path = Path(__file__).resolve().parents[1] / "core" / "alias_pool" / "provider_adapters.py"

        self.assertTrue(module_path.exists(), f"missing module: {module_path}")

        spec = importlib.util.spec_from_file_location("alias_provider_adapters_under_test", module_path)
        self.assertIsNotNone(spec)
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        self.assertTrue(hasattr(module, "build_static_list_alias_provider"))
        self.assertTrue(hasattr(module, "build_simple_generator_alias_provider"))

        static_provider = module.build_static_list_alias_provider(
            AliasProviderSourceSpec(
                source_id="legacy-static",
                provider_type="static_list",
                raw_source={
                    "id": "legacy-static",
                    "type": "static_list",
                    "emails": ["a@example.com", "b@example.com", "c@example.com"],
                    "mailbox_email": "real@example.com",
                },
            ),
            AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )
        simple_provider = module.build_simple_generator_alias_provider(
            AliasProviderSourceSpec(
                source_id="simple-1",
                provider_type="simple_generator",
                raw_source={
                    "id": "simple-1",
                    "type": "simple_generator",
                    "prefix": "msi.",
                    "suffix": "@manyme.com",
                    "mailbox_email": "real@example.com",
                    "count": 1,
                    "middle_length_min": 3,
                    "middle_length_max": 3,
                },
            ),
            AliasProviderBootstrapContext(task_id="alias-test", purpose="automation_test"),
        )

        static_result = static_provider.run_alias_generation_test(
            AliasAutomationTestPolicy(
                fresh_service_account=True,
                persist_state=False,
                minimum_alias_count=3,
                capture_enabled=True,
            )
        )
        simple_result = simple_provider.run_alias_generation_test(
            AliasAutomationTestPolicy(
                fresh_service_account=True,
                persist_state=False,
                minimum_alias_count=3,
                capture_enabled=True,
            )
        )

        self.assertEqual(static_result.provider_type, "static_list")
        self.assertEqual(
            static_result.aliases,
            [
                {"email": "a@example.com"},
                {"email": "b@example.com"},
                {"email": "c@example.com"},
            ],
        )
        self.assertEqual(static_result.account_identity.real_mailbox_email, "real@example.com")
        self.assertEqual(simple_result.provider_type, "simple_generator")
        self.assertEqual(simple_result.source_id, "simple-1")
        self.assertEqual(simple_result.account_identity.real_mailbox_email, "real@example.com")
        self.assertEqual(len(simple_result.aliases), 3)
        for item in simple_result.aliases:
            self.assertTrue(item["email"].startswith("msi."))
            self.assertTrue(item["email"].endswith("@manyme.com"))


class _UnsafeConfirmationExecutor(_FakeVendEmailDefaultExecutor):
    def fetch_confirmation_link(self, state, source) -> str:
        super().fetch_confirmation_link(state, source)
        return "http://127.0.0.1/internal/confirm?confirmation_token=abc123"


class VendEmailRuntimeContractTests(unittest.TestCase):
    def test_vend_alias_provider_prefers_legacy_top_level_fields_over_provider_config_during_migration(self):
        spec = AliasProviderSourceSpec(
            source_id="vend-email-primary",
            provider_type="vend_email",
            state_key="vend-email-primary",
            desired_alias_count=2,
            confirmation_inbox_config={
                "provider": "cloudmail",
                "account_email": "real@example.com",
            },
            provider_config={
                "register_url": "https://provider-config.example/register",
                "cloudmail_api_base": "https://provider-config.example/api",
                "cloudmail_admin_email": "provider-config-admin@example.com",
                "alias_domain": "provider-config.example",
                "confirmation_inbox": {
                    "provider": "cloudmail",
                    "account_email": "provider-config@example.com",
                },
            },
            raw_source={
                "id": "vend-email-primary",
                "type": "vend_email",
                "register_url": "https://legacy.example/register",
                "cloudmail_api_base": "https://legacy.example/api",
                "cloudmail_admin_email": "legacy-admin@example.com",
                "alias_domain": "legacy.example",
                "provider_config": {
                    "register_url": "https://provider-config.example/register",
                },
            },
        )

        provider = VendAliasProvider(
            spec=spec,
            state_repository=mock.Mock(store=mock.Mock()),
            runtime=mock.Mock(),
            confirmation_reader=mock.Mock(),
            telemetry=mock.Mock(),
        )

        self.assertEqual(provider.source["register_url"], "https://legacy.example/register")
        self.assertEqual(provider.source["cloudmail_api_base"], "https://legacy.example/api")
        self.assertEqual(provider.source["cloudmail_admin_email"], "legacy-admin@example.com")
        self.assertEqual(provider.source["alias_domain"], "legacy.example")
        self.assertEqual(
            provider.source["confirmation_inbox"],
            {
                "provider": "cloudmail",
                "account_email": "provider-config@example.com",
            },
        )

    def test_default_runtime_executor_prefers_confirmation_inbox_contract_for_mailbox_lookup(self):
        from core.alias_pool.vend_email_service import DefaultVendEmailRuntimeExecutor

        state = VendEmailServiceState(
            state_key="vend-email-primary",
            service_email="vendcap202604170108@cxwsss.online",
            mailbox_email="confirm-admin@cxwsss.online",
        )
        source = {
            "register_url": "https://www.vend.email/auth/register",
            "cloudmail_api_base": "https://legacy.example/api",
            "cloudmail_admin_email": "legacy-admin@example.com",
            "cloudmail_admin_password": "legacy-secret",
            "cloudmail_domain": "legacy.example.com",
            "cloudmail_subdomain": "legacy-sub",
            "cloudmail_timeout": 12,
            "confirmation_inbox": {
                "provider": "cloudmail",
                "api_base": "https://mailbox.example/api",
                "admin_email": "cloudmail-admin@example.com",
                "admin_password": "cloudmail-secret",
                "domain": "mail.example.com",
                "subdomain": "pool-a",
                "timeout": 45,
            },
        }
        captured_init = {}

        class _CloudMailMailboxFake:
            def __init__(self, *, api_base, admin_email, admin_password, domain, subdomain, timeout):
                captured_init.update(
                    {
                        "api_base": api_base,
                        "admin_email": admin_email,
                        "admin_password": admin_password,
                        "domain": domain,
                        "subdomain": subdomain,
                        "timeout": timeout,
                    }
                )

            def _list_mails(self, _email):
                return [
                    {
                        "subject": "Confirm your vend account",
                        "content": "https://www.vend.email/auth/confirmation?confirmation_token=abc123",
                    }
                ]

            def _match_alias_receipt(self, _message, alias_email):
                return alias_email == "confirm-admin@cxwsss.online"

        with mock.patch("core.alias_pool.vend_email_service.CloudMailMailbox", _CloudMailMailboxFake):
            executor = DefaultVendEmailRuntimeExecutor(source=source)
            confirmation_link = executor.fetch_confirmation_link(state, source)

        self.assertEqual(
            captured_init,
            {
                "api_base": "https://mailbox.example/api",
                "admin_email": "cloudmail-admin@example.com",
                "admin_password": "cloudmail-secret",
                "domain": "mail.example.com",
                "subdomain": "pool-a",
                "timeout": 45,
            },
        )
        self.assertEqual(
            confirmation_link,
            "https://www.vend.email/auth/confirmation?confirmation_token=abc123",
        )

    def test_contract_uses_base_url_when_register_url_points_to_register_page(self):
        state = VendEmailServiceState(
            state_key="vend-email-primary",
            service_email="vendcap202604170108@cxwsss.online",
            service_password="vend-secret",
            mailbox_email="admin@cxwsss.online",
        )
        source = {
            "register_url": "https://www.vend.email/auth/register",
            "mailbox_email": "admin@cxwsss.online",
            "alias_domain": "serf.me",
            "alias_domain_id": "42",
        }
        executor = _FakeVendEmailExecutor(
            [
                _html_execution(html=REGISTER_FORM_HTML, final_url="https://www.vend.email/auth/register"),
                _html_execution(html="<html><body>registered</body></html>", final_url="https://www.vend.email/"),
                _html_execution(html=LOGIN_FORM_HTML, final_url="https://www.vend.email/auth/login"),
                _html_execution(html="<html><body>dashboard</body></html>", final_url="https://www.vend.email/forwarders"),
            ]
        )
        runtime = VendEmailContractRuntime(executor=executor)

        self.assertTrue(runtime.register(state, source))
        self.assertTrue(runtime.login(state, source))

        self.assertEqual(executor.calls[0]["url"], "https://www.vend.email/auth/register")
        self.assertEqual(executor.calls[1]["url"], "https://www.vend.email/auth")
        self.assertEqual(executor.calls[2]["url"], "https://www.vend.email/auth/login")
        self.assertEqual(executor.calls[3]["url"], "https://www.vend.email/auth/login")

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
                    _html_execution(html=REGISTER_FORM_HTML, final_url="https://www.vend.email/auth/register"),
                    _html_execution(html="<html><body>registered</body></html>", final_url="https://www.vend.email/"),
                    _html_execution(html="<html><body>signed in</body></html>", final_url="https://www.vend.email/auth/login"),
                    _html_execution(html=LOGIN_FORM_HTML, final_url="https://www.vend.email/auth/login"),
                    _html_execution(html=LOGIN_FORM_HTML, final_url="https://www.vend.email/auth/login"),
                    _html_execution(html="<html><body>dashboard</body></html>", final_url="https://www.vend.email/forwarders"),
                    _html_execution(html=FORWARDERS_NEW_FORM_HTML, final_url="https://www.vend.email/forwarders/new"),
                    _html_execution(html=FORWARDER_DETAIL_HTML, final_url="https://www.vend.email/forwarders/vendcap202604170108@serf.me", status=302),
                ]
            )
        )

        self.assertTrue(runtime.register(state, source))
        self.assertTrue(runtime.confirm("https://www.vend.email/auth/confirmation?confirmation_token=abc123", source))
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
                alias_email="vendcap202604170108@serf.me",
                recipient_email="admin@cxwsss.online",
            ),
        )
        self.assertEqual(
            [capture.name for capture in runtime.capture_summary()],
            [
                "register_form",
                "register",
                "confirmation",
                "confirmation",
                "login_form",
                "login",
                "new_forwarder_form",
                "create_forwarder",
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
                _html_execution(html=FORWARDERS_LIST_HTML, final_url="https://www.vend.email/forwarders"),
                _html_execution(html=FORWARDERS_NEW_FORM_HTML, final_url="https://www.vend.email/forwarders/new"),
                _html_execution(html=FORWARDER_DETAIL_HTML, final_url="https://www.vend.email/forwarders/vendcap202604170108@serf.me", status=302),
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
                    recipient_email="",
                )
            ],
        )
        self.assertEqual(aliases, ["vendcap202604170108@serf.me"])
        self.assertEqual(executor.calls[0]["method"], "GET")
        self.assertEqual(executor.calls[0]["url"], "https://www.vend.email/forwarders")
        self.assertEqual(executor.calls[0]["request_body_excerpt"], "")
        self.assertEqual(executor.calls[1]["url"], "https://www.vend.email/forwarders/new")
        self.assertIn("authenticity_token=forwarder-auth-token", executor.calls[2]["request_body_excerpt"])
        self.assertIn("forwarder[local_part]=vendcap202604170108", executor.calls[2]["request_body_excerpt"])
        self.assertIn("forwarder[domain_id]=42", executor.calls[2]["request_body_excerpt"])
        self.assertIn("forwarder[recipient]=admin%40cxwsss.online", executor.calls[2]["request_body_excerpt"])


class VendAliasProviderAutomationTestTests(unittest.TestCase):
    def test_builder_returns_vend_alias_provider(self):
        from core.alias_pool.vend_email_service import build_vend_email_alias_service_producer
        from core.alias_pool.vend_provider import VendAliasProvider

        producer = build_vend_email_alias_service_producer(
            source={
                "id": "vend-email-primary",
                "type": "vend_email",
                "register_url": "https://www.vend.email/auth/register",
                "alias_domain": "serf.me",
                "alias_domain_id": "42",
                "alias_count": 1,
                "state_key": "vend-email-primary",
            },
            task_id="task-vend-provider-builder",
            runtime_builder=lambda source: _FakeVendEmailRuntime(
                restore_ok=True,
                login_ok=False,
                register_ok=False,
                aliases=["alias-001@serf.me"],
            ),
        )

        self.assertIsInstance(producer, VendAliasProvider)

    def test_run_alias_generation_test_uses_policy_for_fresh_run_and_alias_count(self):
        from core.alias_pool.vend_provider import VendAliasProvider
        from core.alias_pool.vend_state_repository import VendStateRepository
        from core.alias_pool.vend_telemetry import VendTelemetryRecorder

        stale_state = VendEmailServiceState(
            state_key="vend-email-primary",
            service_email="old@example.com",
            mailbox_email="old@example.com",
            service_password="old-pass",
            known_aliases=["old@serf.me"],
        )
        fresh_state = VendEmailServiceState(state_key="vend-email-primary")
        state_repository = mock.Mock()
        state_repository.load.return_value = stale_state
        state_repository.new_state.return_value = fresh_state
        self.assertFalse(hasattr(importlib.import_module("core.alias_pool.vend_email_service"), "_build_service_email"))
        self.assertFalse(hasattr(importlib.import_module("core.alias_pool.vend_email_service"), "_build_service_password"))
        runtime = _FakeVendEmailRuntime(
            restore_ok=False,
            login_ok=[False, True],
            register_ok=True,
            confirm_ok=True,
            aliases=["new-001@serf.me"],
            created_aliases=["new-002@serf.me", "new-003@serf.me"],
        )
        provider = VendAliasProvider(
            spec=AliasProviderSourceSpec(
                source_id="vend-email-primary",
                provider_type="vend_email",
                raw_source={
                    "id": "vend-email-primary",
                    "type": "vend_email",
                    "register_url": "https://www.vend.email/auth/register",
                    "cloudmail_domain": "example.com",
                    "confirmation_inbox": {
                        "provider": "cloudmail",
                        "account_email": "confirm@example.com",
                        "match_email": "confirm@example.com",
                    },
                    "alias_domain": "serf.me",
                    "alias_domain_id": "42",
                    "alias_count": 1,
                    "state_key": "vend-email-primary",
                },
                desired_alias_count=1,
                state_key="vend-email-primary",
                alias_domain_id="42",
                confirmation_inbox_config={
                    "provider": "cloudmail",
                    "account_email": "confirm@example.com",
                    "match_email": "confirm@example.com",
                },
            ),
            state_repository=state_repository,
            runtime=runtime,
            confirmation_reader=mock.Mock(),
            telemetry=VendTelemetryRecorder(),
        )

        with mock.patch(
            "core.alias_pool.vend_provider.build_service_email",
            return_value="fresh-service@example.com",
        ), mock.patch(
            "core.alias_pool.vend_provider.build_service_password",
            return_value="fresh-pass",
        ):
            result = provider.run_alias_generation_test(
                AliasAutomationTestPolicy(
                    fresh_service_account=True,
                    persist_state=False,
                    minimum_alias_count=3,
                    capture_enabled=True,
                )
            )

        state_repository.load.assert_not_called()
        state_repository.save.assert_not_called()
        self.assertTrue(result.ok)
        self.assertEqual(
            result.aliases,
            [
                {"email": "new-001@serf.me"},
                {"email": "new-002@serf.me"},
                {"email": "new-003@serf.me"},
            ],
        )
        self.assertTrue(result.account_identity.service_account_email)
        self.assertNotEqual(result.account_identity.service_account_email, "old@example.com")
        self.assertEqual(result.account_identity.confirmation_inbox_email, "confirm@example.com")
        self.assertEqual(result.account_identity.real_mailbox_email, "confirm@example.com")
        self.assertEqual(result.account_identity.service_password, "fresh-pass")
        self.assertEqual(result.account_identity.username, "fresh-service")

    def test_run_alias_generation_test_does_not_default_mailbox_identity_to_service_email_without_confirmation_inbox(self):
        from core.alias_pool.vend_provider import VendAliasProvider
        from core.alias_pool.vend_telemetry import VendTelemetryRecorder

        fresh_state = VendEmailServiceState(state_key="vend-email-primary")
        state_repository = mock.Mock()
        state_repository.new_state.return_value = fresh_state
        runtime = _FakeVendEmailRuntime(
            restore_ok=True,
            login_ok=False,
            register_ok=False,
            aliases=["new-001@serf.me"],
        )
        provider = VendAliasProvider(
            spec=AliasProviderSourceSpec(
                source_id="vend-email-primary",
                provider_type="vend_email",
                raw_source={
                    "id": "vend-email-primary",
                    "type": "vend_email",
                    "register_url": "https://www.vend.email/auth/register",
                    "cloudmail_domain": "example.com",
                    "alias_domain": "serf.me",
                    "alias_domain_id": "42",
                    "alias_count": 1,
                    "state_key": "vend-email-primary",
                },
                desired_alias_count=1,
                state_key="vend-email-primary",
                alias_domain_id="42",
            ),
            state_repository=state_repository,
            runtime=runtime,
            confirmation_reader=mock.Mock(),
            telemetry=VendTelemetryRecorder(),
        )

        with mock.patch(
            "core.alias_pool.vend_provider.build_service_email",
            return_value="fresh-service@example.com",
        ), mock.patch(
            "core.alias_pool.vend_provider.build_service_password",
            return_value="fresh-pass",
        ):
            result = provider.run_alias_generation_test(
                AliasAutomationTestPolicy(
                    fresh_service_account=True,
                    persist_state=False,
                    minimum_alias_count=1,
                    capture_enabled=True,
                )
            )

        self.assertEqual(fresh_state.service_email, "fresh-service@example.com")
        self.assertEqual(fresh_state.mailbox_email, "")
        self.assertEqual(result.account_identity.service_account_email, "fresh-service@example.com")
        self.assertEqual(result.account_identity.confirmation_inbox_email, "")
        self.assertEqual(result.account_identity.real_mailbox_email, "")

    def test_compatibility_builder_delegates_old_producer_load_into_to_provider(self):
        from core.alias_pool.vend_email_service import VendEmailAliasServiceProducer

        manager = mock.Mock()
        runtime = _FakeVendEmailRuntime(
            restore_ok=True,
            login_ok=False,
            register_ok=False,
            aliases=["alias-001@serf.me"],
        )
        state_store = mock.Mock()
        producer = VendEmailAliasServiceProducer(
            source={
                "id": "vend-email-primary",
                "type": "vend_email",
                "register_url": "https://www.vend.email/auth/register",
                "alias_domain": "serf.me",
                "alias_domain_id": "42",
                "alias_count": 1,
                "state_key": "vend-email-primary",
            },
            state_store=state_store,
            runtime=runtime,
        )

        with mock.patch("core.alias_pool.vend_email_service.build_vend_email_alias_service_producer") as builder:
            delegated = mock.Mock()
            builder.return_value = delegated

            producer.load_into(manager)

        builder.assert_called_once_with(
            source=producer.source,
            task_id="vend-email-primary",
            state_store_factory=mock.ANY,
            runtime_builder=mock.ANY,
        )
        delegated.load_into.assert_called_once_with(manager)


class VendEmailAliasServiceProducerTests(unittest.TestCase):
    def test_default_runtime_bootstrap_fetches_confirmation_link_before_confirming(self):
        manager = AliasEmailPoolManager(task_id="task-vend-email-default-bootstrap")
        state_store = mock.Mock()
        state_store.load.return_value = VendEmailServiceState(
            state_key="vend-email-state-key",
        )
        runtime = _FakeVendEmailRuntime(
            restore_ok=False,
            login_ok=[False, True],
            register_ok=True,
            confirm_ok=True,
            aliases=["vendcapdemo20260417@serf.me"],
            captures=[],
        )

        producer = VendEmailAliasServiceProducer(
            source={
                "id": "vend-email-primary",
                "type": "vend_email",
                "register_url": "https://www.vend.email/auth/register",
                "alias_domain": "serf.me",
                "alias_count": 1,
                "state_key": "vend-email-state-key",
            },
            state_store=state_store,
            runtime=runtime,
        )

        with mock.patch(
            "core.alias_pool.vend_provider.build_service_email",
            return_value="vendcap202604170108@cxwsss.online",
        ):
            producer.load_into(manager)

        self.assertEqual(
            runtime.calls[:6],
            [
                "restore",
                "login",
                "register",
                "fetch_confirmation_link",
                "confirm",
                "login",
            ],
        )
        lease = manager.acquire_alias()
        self.assertEqual(lease.alias_email, "vendcapdemo20260417@serf.me")
        saved_state = state_store.save.call_args.args[0]
        self.assertEqual(lease.real_mailbox_email, saved_state.mailbox_email)
        self.assertEqual(saved_state.state_key, "vend-email-state-key")
        self.assertEqual(saved_state.known_aliases, ["vendcapdemo20260417@serf.me"])

    def test_confirm_uses_active_state_and_rejects_local_confirmation_urls(self):
        state = VendEmailServiceState(
            state_key="vend-email-primary",
            service_email="vendcap202604170108@cxwsss.online",
            service_password="vend-secret",
            mailbox_email="admin@cxwsss.online",
        )
        runtime = VendEmailContractRuntime(executor=_UnsafeConfirmationExecutor())

        runtime.restore_session(state)

        with self.assertRaisesRegex(RuntimeError, "must not target private or local addresses"):
            runtime.confirm(
                "http://127.0.0.1/internal/confirm?confirmation_token=abc123",
                {
                    "register_url": "https://www.vend.email/auth/register",
                    "mailbox_base_url": "https://mailbox.example/base",
                },
            )

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
                name="mailbox_verification",
                url="",
                method="GET",
                request_headers_whitelist={},
                request_body_excerpt="",
                response_status=200,
                response_body_excerpt="confirmation link captured",
                captured_at="2026-04-16T10:03:00+08:00",
            ),
            VendEmailCaptureRecord(
                name="confirmation",
                url="https://www.vend.email/auth/confirmation?confirmation_token=abc123",
                method="GET",
                request_headers_whitelist={},
                request_body_excerpt="",
                response_status=200,
                response_body_excerpt='{"ok":true}',
                captured_at="2026-04-16T10:03:10+08:00",
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
            confirm_ok=True,
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
                "fetch_confirmation_link",
                "confirm",
                "login",
            ],
        )
        self.assertIn("list_aliases", runtime.calls)
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
                captures[2],
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
                captures[4],
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
        self.assertEqual(
            saved_state.current_stage,
            {"code": "aliases_ready", "label": "别名预览已生成"},
        )
        self.assertEqual(
            saved_state.stage_history,
            [
                {"code": "register_submit", "label": "注册表单提交", "status": "completed"},
                {
                    "code": "fetch_confirmation_mail",
                    "label": "查找确认邮件",
                    "status": "completed",
                },
                {
                    "code": "open_confirmation_link",
                    "label": "打开确认链接",
                    "status": "completed",
                },
                {"code": "session_ready", "label": "会话已就绪", "status": "completed"},
                {
                    "code": "list_aliases",
                    "label": "列出现有别名",
                    "status": "completed",
                    "detail": "找到 1 个别名",
                },
                {
                    "code": "create_aliases",
                    "label": "创建别名",
                    "status": "completed",
                    "detail": "已补齐 2 个别名",
                },
                {
                    "code": "aliases_ready",
                    "label": "别名预览已生成",
                    "status": "completed",
                    "detail": "预览共 3 个别名",
                },
                {"code": "save_state", "label": "保存预览状态", "status": "completed"},
            ],
        )
        self.assertEqual(
            saved_state.last_failure,
            {"stageCode": "", "stageLabel": "", "reason": ""},
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
            confirm_ok=False,
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
            ["restore", "login", "register", "fetch_confirmation_link", "confirm"],
        )
        self.assertEqual(producer.state(), AliasSourceState.FAILED)
        saved_state = state_store.save.call_args.args[0]
        self.assertEqual(
            saved_state.current_stage,
            {"code": "open_confirmation_link", "label": "打开确认链接"},
        )
        self.assertEqual(
            saved_state.stage_history,
            [
                {"code": "register_submit", "label": "注册表单提交", "status": "completed"},
                {
                    "code": "fetch_confirmation_mail",
                    "label": "查找确认邮件",
                    "status": "completed",
                },
                {
                    "code": "open_confirmation_link",
                    "label": "打开确认链接",
                    "status": "failed",
                    "detail": "vend.email confirmation step returned unsuccessful result",
                },
            ],
        )
        self.assertEqual(
            saved_state.last_failure,
            {
                "stageCode": "open_confirmation_link",
                "stageLabel": "打开确认链接",
                "reason": "vend.email confirmation step returned unsuccessful result",
                "retryable": True,
            },
        )

    def test_producer_persists_concrete_fetch_confirmation_mail_exception(self):
        manager = AliasEmailPoolManager(task_id="task-vend-email-fetch-failed")
        state_store = mock.Mock()
        state_store.load.return_value = VendEmailServiceState(
            state_key="vend-email-primary",
            service_email="vendcap202604170108@cxwsss.online",
            service_password="vend-service-pass",
        )
        runtime = _FakeVendEmailRuntime(
            restore_ok=False,
            login_ok=False,
            register_ok=True,
            aliases=[],
        )
        runtime.fetch_confirmation_link = mock.Mock(side_effect=RuntimeError("mailbox timeout waiting for confirmation mail"))

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

        with self.assertRaisesRegex(RuntimeError, "mailbox timeout waiting for confirmation mail"):
            producer.load_into(manager)

        saved_state = state_store.save.call_args.args[0]
        self.assertEqual(
            saved_state.current_stage,
            {"code": "fetch_confirmation_mail", "label": "查找确认邮件"},
        )
        self.assertEqual(
            saved_state.last_failure,
            {
                "stageCode": "fetch_confirmation_mail",
                "stageLabel": "查找确认邮件",
                "reason": "mailbox timeout waiting for confirmation mail",
                "retryable": True,
            },
        )
        self.assertEqual(
            saved_state.stage_history,
            [
                {"code": "register_submit", "label": "注册表单提交", "status": "completed"},
                {
                    "code": "fetch_confirmation_mail",
                    "label": "查找确认邮件",
                    "status": "failed",
                    "detail": "mailbox timeout waiting for confirmation mail",
                },
            ],
        )

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
        self.assertEqual(saved_state.service_email, "vendcap202604170108@cxwsss.online")
        self.assertEqual(saved_state.mailbox_email, "admin@cxwsss.online")
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

        self.assertEqual(
            state_store.load.return_value.service_email,
            "vendcap202604170108@cxwsss.online",
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
