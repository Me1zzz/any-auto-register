import unittest
from unittest import mock

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
                        "mailbox_email": "Real@Example.COM ",
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
                    "mailbox_email": "real@example.com",
                    "alias_domain": "cxwsss.online",
                    "alias_count": 0,
                    "state_key": "vend-1",
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
                        "mailbox_email": "Real@Example.COM ",
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
                    "mailbox_email": "real@example.com",
                    "alias_domain": "cxwsss.online",
                    "alias_count": 0,
                    "state_key": "vend-1",
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
                        "mailbox_email": "Real@Example.COM ",
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
                    "mailbox_email": "real@example.com",
                    "alias_domain": "cxwsss.online",
                    "alias_count": 0,
                    "state_key": "vend-1",
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
                        "mailbox_email": "Real@Example.COM ",
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
                    "mailbox_email": "real@example.com",
                    "alias_domain": "cxwsss.online",
                    "alias_count": 0,
                    "state_key": "vend-1",
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
                        "mailbox_email": "Real@Example.COM ",
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
                    "mailbox_email": "real@example.com",
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


if __name__ == "__main__":
    unittest.main()
