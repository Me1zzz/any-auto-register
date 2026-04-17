import unittest
from unittest import mock
import tempfile
from pathlib import Path

import core.alias_pool.mailbox_verification_adapter as mailbox_verification_adapter

from core.alias_pool.base import (
    AliasEmailLease,
    AliasLeaseStatus,
    AliasPoolExhaustedError,
    AliasSourceState,
)
from core.alias_pool.config import normalize_cloudmail_alias_pool_config
from core.alias_pool.manager import AliasEmailPoolManager
from core.alias_pool.probe import AliasProbeResult, AliasSourceProbeService
from core.alias_pool.service_base import AliasServiceProducerBase
from core.alias_pool.simple_generator import SimpleAliasGeneratorProducer
from core.alias_pool.static_list import StaticAliasListProducer
from core.alias_pool.vend_email_state import (
    VendEmailCaptureRecord,
    VendEmailFileStateStore,
    VendEmailServiceState,
)
from core.alias_pool.vend_email_service import (
    VendEmailRuntimeExecutor,
    VendEmailRuntimeService,
    build_default_vend_executor,
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


class AliasConfigRouteContractTests(unittest.TestCase):
    def test_get_config_includes_saved_sources_for_alias_test_saved_mode(self):
        from api import config as config_api

        saved_sources = [
            {
                "id": "saved-source",
                "type": "static_list",
                "emails": ["saved@example.com"],
                "mailbox_email": "real@example.com",
            }
        ]

        with mock.patch.object(
            config_api.config_store,
            "get_all",
            return_value={
                "mail_provider": "cloudmail",
                "sources": saved_sources,
            },
        ):
            result = config_api.get_config()

        self.assertEqual(result["sources"], saved_sources)

    def test_update_config_preserves_sources_key(self):
        from api import config as config_api

        saved_sources = [
            {
                "id": "saved-source",
                "type": "static_list",
                "emails": ["saved@example.com"],
                "mailbox_email": "real@example.com",
            }
        ]

        with mock.patch.object(config_api.config_store, "set_many") as set_many:
            config_api.update_config(
                config_api.ConfigUpdate(
                    data={
                        "sources": saved_sources,
                        "ignored": "value",
                    }
                )
            )

        set_many.assert_called_once_with({"sources": saved_sources})

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


class AliasSourceProbeServiceTests(unittest.TestCase):
    def test_probe_result_retains_full_contract_shape_for_future_task_steps(self):
        result = AliasSourceProbeService().probe(
            {
                "sources": [
                    {
                        "id": "legacy-static",
                        "type": "static_list",
                        "emails": ["alias1@example.com"],
                        "mailbox_email": "real@example.com",
                    }
                ]
            },
            source_id="legacy-static",
            task_id="task-contract-shape",
        )

        self.assertEqual(
            result,
            AliasSourceProbeService().probe(
                {
                    "sources": [
                        {
                            "id": "legacy-static",
                            "type": "static_list",
                            "emails": ["alias1@example.com"],
                            "mailbox_email": "real@example.com",
                        }
                    ]
                },
                source_id="legacy-static",
                task_id="task-contract-shape-repeat",
            ),
        )
        self.assertEqual(result.service_email, "")
        self.assertEqual(result.capture_summary, [])
        self.assertEqual(result.steps, [])
        self.assertEqual(result.logs, [])

    def test_probe_uses_static_list_runtime_path_for_supported_sources(self):
        service = AliasSourceProbeService()

        def fake_load_into(self, manager):
            manager.add_lease(
                AliasEmailLease(
                    alias_email="runtime-static@example.com",
                    real_mailbox_email="runtime-real@example.com",
                    source_kind=self.source_kind,
                    source_id=self.source_id,
                    source_session_id="runtime-static",
                )
            )

        with mock.patch.object(StaticAliasListProducer, "load_into", autospec=True, side_effect=fake_load_into):
            result = service.probe(
                {
                    "sources": [
                        {
                            "id": "legacy-static",
                            "type": "static_list",
                            "emails": ["alias1@example.com", "alias2@example.com"],
                            "mailbox_email": "real@example.com",
                        }
                    ]
                },
                source_id="legacy-static",
                task_id="task-probe-static-runtime",
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.source_id, "legacy-static")
        self.assertEqual(result.source_type, "static_list")
        self.assertEqual(result.alias_email, "runtime-static@example.com")
        self.assertEqual(result.real_mailbox_email, "runtime-real@example.com")

    def test_probe_uses_simple_generator_runtime_path_for_supported_sources(self):
        service = AliasSourceProbeService()

        with mock.patch.object(
            SimpleAliasGeneratorProducer,
            "_generate_alias_email",
            autospec=True,
            return_value="runtime-generator@example.com",
        ):
            result = service.probe(
                {
                    "sources": [
                        {
                            "id": "simple-1",
                            "type": "simple_generator",
                            "prefix": "msiabc.",
                            "suffix": "@manyme.com",
                            "mailbox_email": "real@example.com",
                            "count": 1,
                            "middle_length_min": 3,
                            "middle_length_max": 3,
                        }
                    ]
                },
                source_id="simple-1",
                task_id="task-probe-generator-runtime",
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.source_id, "simple-1")
        self.assertEqual(result.source_type, "simple_generator")
        self.assertEqual(result.alias_email, "runtime-generator@example.com")
        self.assertEqual(result.real_mailbox_email, "real@example.com")

    def test_probe_returns_first_static_list_alias_for_matching_source(self):
        service = AliasSourceProbeService()

        result = service.probe(
            {
                "sources": [
                    {
                        "id": "legacy-static",
                        "type": "static_list",
                        "emails": ["alias1@example.com", "alias2@example.com"],
                        "mailbox_email": "real@example.com",
                    }
                ]
            },
            source_id="legacy-static",
            task_id="task-probe-static",
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.error, "")
        self.assertEqual(result.source_id, "legacy-static")
        self.assertEqual(result.source_type, "static_list")
        self.assertEqual(result.alias_email, "alias1@example.com")
        self.assertEqual(result.real_mailbox_email, "real@example.com")
        self.assertEqual(result.service_email, "")
        self.assertEqual(result.capture_summary, [])
        self.assertEqual(result.steps, [])
        self.assertEqual(result.logs, [])

    def test_probe_returns_generated_alias_for_matching_simple_generator_source(self):
        service = AliasSourceProbeService()

        with mock.patch.object(
            SimpleAliasGeneratorProducer,
            "_generate_alias_email",
            autospec=True,
            return_value="msiabc.ab1@manyme.com",
        ):
            result = service.probe(
                {
                    "sources": [
                        {
                            "id": "simple-1",
                            "type": "simple_generator",
                            "prefix": "msiabc.",
                            "suffix": "@manyme.com",
                            "mailbox_email": "real@example.com",
                            "count": 5,
                            "middle_length_min": 3,
                            "middle_length_max": 3,
                        }
                    ]
                },
                source_id="simple-1",
                task_id="task-probe-generator",
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.error, "")
        self.assertEqual(result.source_id, "simple-1")
        self.assertEqual(result.source_type, "simple_generator")
        self.assertEqual(result.alias_email, "msiabc.ab1@manyme.com")
        self.assertEqual(result.real_mailbox_email, "real@example.com")
        self.assertEqual(result.service_email, "")
        self.assertEqual(result.capture_summary, [])
        self.assertEqual(result.steps, [])
        self.assertEqual(result.logs, [])

    def test_probe_returns_structured_error_for_simple_generator_invalid_length_bounds(self):
        service = AliasSourceProbeService()

        result = service.probe(
            {
                "sources": [
                    {
                        "id": "simple-invalid",
                        "type": "simple_generator",
                        "prefix": "msiabc.",
                        "suffix": "@manyme.com",
                        "mailbox_email": "real@example.com",
                        "count": 5,
                        "middle_length_min": 6,
                        "middle_length_max": 3,
                    }
                ]
            },
            source_id="simple-invalid",
            task_id="task-probe-invalid-generator",
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "Invalid simple_generator bounds for source 'simple-invalid'.")
        self.assertEqual(result.source_id, "simple-invalid")
        self.assertEqual(result.source_type, "simple_generator")
        self.assertEqual(result.alias_email, "")
        self.assertEqual(result.real_mailbox_email, "real@example.com")
        self.assertEqual(result.service_email, "")
        self.assertEqual(result.capture_summary, [])
        self.assertEqual(result.steps, [])
        self.assertEqual(result.logs, [])

    def test_probe_returns_not_found_error_for_empty_static_list_source(self):
        service = AliasSourceProbeService()

        result = service.probe(
            {
                "sources": [
                    {
                        "id": "legacy-static",
                        "type": "static_list",
                        "emails": [],
                        "mailbox_email": "real@example.com",
                    }
                ]
            },
            source_id="legacy-static",
            task_id="task-probe-empty-static",
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "No alias preview available for source 'legacy-static'.")
        self.assertEqual(result.source_id, "legacy-static")
        self.assertEqual(result.source_type, "static_list")
        self.assertEqual(result.alias_email, "")
        self.assertEqual(result.real_mailbox_email, "real@example.com")
        self.assertEqual(result.service_email, "")
        self.assertEqual(result.capture_summary, [])
        self.assertEqual(result.steps, [])
        self.assertEqual(result.logs, [])

    def test_probe_returns_missing_source_error_when_source_id_is_not_found(self):
        service = AliasSourceProbeService()

        result = service.probe(
            {
                "sources": [
                    {
                        "id": "legacy-static",
                        "type": "static_list",
                        "emails": ["alias1@example.com"],
                        "mailbox_email": "real@example.com",
                    }
                ]
            },
            source_id="missing-source",
            task_id="task-probe-missing-source",
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "source 'missing-source' not found")
        self.assertEqual(result.source_id, "missing-source")
        self.assertEqual(result.source_type, "")
        self.assertEqual(result.alias_email, "")
        self.assertEqual(result.real_mailbox_email, "")
        self.assertEqual(result.service_email, "")
        self.assertEqual(result.capture_summary, [])
        self.assertEqual(result.steps, [])
        self.assertEqual(result.logs, [])

    def test_probe_service_returns_structured_vend_email_result(self):
        service = AliasSourceProbeService()
        service._probe_vend_email = lambda source, task_id: AliasProbeResult(
            ok=True,
            source_id="vend-email-primary",
            source_type="vend_email",
            alias_email="vendcapdemo20260417@serf.me",
            real_mailbox_email="admin@example.com",
            service_email="vendcap202604170108@example.com",
            capture_summary=[{"name": "login"}],
            steps=["register", "confirmation", "login", "create_forwarder"],
            logs=["created one forwarder"],
            error="",
        )

        result = service.probe(
            pool_config={
                "enabled": True,
                "sources": [
                    {
                        "id": "vend-email-primary",
                        "type": "vend_email",
                        "mailbox_email": "admin@example.com",
                    }
                ]
            },
            source_id="vend-email-primary",
            task_id="probe-task",
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.source_type, "vend_email")
        self.assertEqual(result.alias_email, "vendcapdemo20260417@serf.me")
        self.assertEqual(result.real_mailbox_email, "admin@example.com")
        self.assertEqual(result.service_email, "vendcap202604170108@example.com")
        self.assertEqual(result.capture_summary, [{"name": "login"}])
        self.assertEqual(result.steps, ["register", "confirmation", "login", "create_forwarder"])
        self.assertEqual(result.logs, ["created one forwarder"])

    def test_probe_hands_off_vend_email_runtime_with_task_scoped_store_and_source_hook(self):
        service = AliasSourceProbeService()
        runtime_result = AliasProbeResult(
            ok=True,
            source_id="vend-1",
            source_type="vend_email",
            alias_email="vendcapdemo20260417@serf.me",
            real_mailbox_email="Real@Example.com ",
            service_email="vendcap202604170108@cxwsss.online",
            capture_summary=[{"name": "login"}],
            steps=["register", "confirmation", "login", "list_forwarders", "create_forwarder"],
            logs=["vend probe completed"],
            error="",
        )
        store = mock.Mock(spec=VendEmailFileStateStore)
        executor = mock.Mock(spec=VendEmailRuntimeExecutor)
        runtime_service = mock.Mock()
        runtime_service.run_probe.return_value = runtime_result
        handoff = (store, executor, runtime_service)
        source = {
            "id": "vend-1",
            "type": "vend_email",
            "mailbox_email": "Real@Example.com ",
        }

        with mock.patch.object(service, "_build_vend_runtime_handoff", autospec=True, return_value=handoff) as build_handoff:
            result = service.probe(
                {"sources": [source]},
                source_id="vend-1",
                task_id="task-probe-vend-email-default",
            )

        build_handoff.assert_called_once_with(source=source, task_id="task-probe-vend-email-default")
        runtime_service.run_probe.assert_called_once_with(source=source)
        self.assertIs(result, runtime_result)

    def test_probe_allows_custom_vend_executor_construction_hook(self):
        service = AliasSourceProbeService()
        source = {
            "id": "vend-hook",
            "type": "vend_email",
            "mailbox_email": "hooked@example.com",
        }

        with mock.patch.object(service, "_build_vend_executor", autospec=True, return_value=mock.sentinel.executor) as build_executor:
            executor = service._build_vend_executor(source)

        self.assertIs(executor, mock.sentinel.executor)
        build_executor.assert_called_once_with(source)

    def test_probe_builds_vend_runtime_handoff_from_task_store_and_executor_hook(self):
        service = AliasSourceProbeService()
        source = {
            "id": "vend-build",
            "type": "vend_email",
            "mailbox_email": "handoff@example.com",
        }
        store = mock.Mock(spec=VendEmailFileStateStore)
        executor = mock.Mock(spec=VendEmailRuntimeExecutor)

        with mock.patch.object(VendEmailFileStateStore, "for_task", autospec=True, return_value=store) as for_task:
            with mock.patch.object(service, "_build_vend_executor", autospec=True, return_value=executor) as build_executor:
                with mock.patch("core.alias_pool.vend_email_service.VendEmailRuntimeService", autospec=True) as runtime_cls:
                    runtime_service = runtime_cls.return_value
                    handoff = service._build_vend_runtime_handoff(source=source, task_id="task-vend-build")

        for_task.assert_called_once_with(task_id="task-vend-build")
        build_executor.assert_called_once_with(source)
        runtime_cls.assert_called_once_with(state_store=store, executor=executor)
        self.assertEqual(handoff, (store, executor, runtime_service))

    def test_probe_default_vend_executor_is_not_the_synthetic_config_stub(self):
        service = AliasSourceProbeService()

        executor = service._build_vend_executor(
            {
                "id": "vend-runtime",
                "type": "vend_email",
                "register_url": "https://vend.example.test/register",
                "mailbox_base_url": "https://mail.example.com/",
                "mailbox_email": "admin@example.com",
                "mailbox_password": "mailbox-secret",
                "service_email": "ops@example.com",
                "service_password": "Vend#123",
                "mailbox_account_id": 7,
                "mailbox_token": "token-from-config",
                "confirmation_anchor": "https://vend.example.test/auth/confirmation",
                "confirmation_anchor_prefix": "https://vend.example.test/auth/confirmation?",
                "alias_domain": "serf.me",
                "alias_domain_id": "42",
                "mailbox_service_email": "ops@example.com",
            }
        )

        self.assertNotEqual(executor.__class__.__name__, "_DefaultVendEmailProbeExecutor")

    def test_probe_returns_explicit_unsupported_source_type_error_shape(self):
        service = AliasSourceProbeService()

        result = service.probe(
            {
                "sources": [
                    {
                        "id": "future-1",
                        "type": "future_service",
                        "mailbox_email": "Real@Example.com ",
                    }
                ]
            },
            source_id="future-1",
            task_id="task-probe-unsupported-type",
        )

        self.assertFalse(result.ok)
        self.assertEqual(
            result.error,
            "Alias source type 'future_service' is not recognized by the probe preview service.",
        )
        self.assertEqual(result.source_id, "future-1")
        self.assertEqual(result.source_type, "future_service")
        self.assertEqual(result.alias_email, "")
        self.assertEqual(result.real_mailbox_email, "Real@Example.com ")
        self.assertEqual(result.service_email, "")
        self.assertEqual(result.capture_summary, [])
        self.assertEqual(result.steps, [])
        self.assertEqual(result.logs, [])


class VendEmailStateStoreTests(unittest.TestCase):
    def test_state_store_round_trips_service_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VendEmailFileStateStore(base_dir=Path(tmpdir))
            state = VendEmailServiceState(
                state_key="vend-email-primary",
                service_email="vendcap202604170108@cxwsss.online",
                service_password="VendCap#2026!",
                session_cookies=[{"name": "sid", "value": "abc"}],
                session_storage={"token": "t1"},
                last_login_at="2026-04-17T09:00:00+08:00",
                last_verified_at="2026-04-17T09:02:00+08:00",
                known_aliases=["vendcapdemo20260417@serf.me"],
                last_capture_summary=[
                    VendEmailCaptureRecord(
                        name="login",
                        url="https://www.vend.email/auth/login",
                        method="POST",
                        request_headers_whitelist={"content-type": "application/x-www-form-urlencoded"},
                        request_body_excerpt="user[email]=vendcap202604170108@cxwsss.online",
                        response_status=302,
                        response_body_excerpt="",
                        captured_at="2026-04-17T09:03:00+08:00",
                    )
                ],
                last_error="",
            )

            store.save(state)
            loaded = store.load("vend-email-primary")

        self.assertEqual(loaded.service_email, "vendcap202604170108@cxwsss.online")
        self.assertEqual(loaded.known_aliases, ["vendcapdemo20260417@serf.me"])
        self.assertEqual(loaded.last_capture_summary[0].name, "login")


class _FakeVendExecutor(VendEmailRuntimeExecutor):
    def __init__(
        self,
        *,
        restore_session_result=False,
        forwarders=None,
        created_forwarder=None,
        capture_entries=None,
        service_email="vendcap202604170108@cxwsss.online",
    ):
        self.calls = []
        self.restore_session_result = restore_session_result
        self.forwarders = list(forwarders or [])
        self.created_forwarder = created_forwarder or {
            "alias_email": "vendcapdemo20260417@serf.me",
            "real_mailbox_email": "admin@cxwsss.online",
        }
        self.capture_entries = list(
            capture_entries
            or [
                {
                    "name": "login",
                    "url": "https://www.vend.email/auth/login",
                    "method": "POST",
                    "request_headers_whitelist": {"content-type": "application/x-www-form-urlencoded"},
                    "request_body_excerpt": "user[email]=vendcap202604170108@cxwsss.online",
                    "response_status": 302,
                    "response_body_excerpt": "",
                    "captured_at": "2026-04-17T10:00:00+08:00",
                }
            ]
        )
        self.service_email = service_email

    def restore_session(self, state, source):
        self.calls.append("restore_session")
        return self.restore_session_result

    def register(self, state, source):
        self.calls.append("register")
        return None

    def fetch_confirmation_link(self, source):
        self.calls.append("fetch_confirmation_link")
        return "https://www.vend.email/auth/confirmation?confirmation_token=abc123"

    def confirm(self, confirmation_link, source):
        self.calls.append("confirm")
        return None

    def login(self, state, source):
        self.calls.append("login")
        state.service_email = self.service_email
        return None

    def list_forwarders(self, state, source):
        self.calls.append("list_forwarders")
        return list(self.forwarders)

    def create_forwarder(self, state, source):
        self.calls.append("create_forwarder")
        return dict(self.created_forwarder)

    def capture_summary(self):
        return list(self.capture_entries)


class _FakeHTTPResponse:
    def __init__(self, status_code, text, headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = dict(headers or {"content-type": "application/json"})


class VendEmailRuntimeServiceTests(unittest.TestCase):
    def test_runtime_service_default_executor_reuses_runtime_requests_and_mailbox_verification_path(self):
        store = mock.Mock()
        store.load.return_value = VendEmailServiceState(state_key="vend-email-primary")

        request_calls = []
        responses = iter(
            [
                _FakeHTTPResponse(200, '{"ok": true}'),
                _FakeHTTPResponse(200, '{"token": "mailbox-token-123"}'),
                _FakeHTTPResponse(
                    200,
                    (
                        '[{"content": "Confirm here '
                        'https://vend.example.test/auth/confirmation?confirmation_token=abc123"}]'
                    ),
                ),
                _FakeHTTPResponse(200, '{"ok": true}'),
                _FakeHTTPResponse(200, '{"ok": true}'),
                _FakeHTTPResponse(200, '[]'),
                _FakeHTTPResponse(
                    200,
                    '{"email": "ops@serf.me", "recipient": "admin@cxwsss.online"}',
                ),
            ]
        )

        def fake_request(http_client, method, url, **kwargs):
            request_calls.append(
                {
                    "method": method,
                    "url": url,
                    "headers": dict(kwargs.get("headers") or {}),
                    "params": dict(kwargs.get("params") or {}),
                    "json": kwargs.get("json"),
                    "data": kwargs.get("data"),
                }
            )
            return next(responses)

        with mock.patch("core.http_client.HTTPClient.request", autospec=True, side_effect=fake_request):
            service = VendEmailRuntimeService(
                state_store=store,
                executor=build_default_vend_executor(
                    {
                        "id": "vend-email-primary",
                        "type": "vend_email",
                        "mailbox_email": "admin@cxwsss.online",
                        "state_key": "vend-email-primary",
                        "mailbox_base_url": "https://mail.example.com/",
                        "mailbox_password": "Mailbox#123",
                        "service_email": "ops@example.com",
                        "service_password": "Vend#123",
                        "mailbox_account_id": 7,
                        "mailbox_token": "token-from-config",
                        "register_url": "https://vend.example.test/register",
                        "confirmation_anchor": "https://vend.example.test/auth/confirmation",
                        "confirmation_anchor_prefix": "https://vend.example.test/auth/confirmation?",
                        "alias_domain": "serf.me",
                        "alias_domain_id": "42",
                        "mailbox_service_email": "ops@example.com",
                    }
                ),
            )
            result = service.run_probe(
                source={
                    "id": "vend-email-primary",
                    "type": "vend_email",
                    "mailbox_email": "admin@cxwsss.online",
                    "state_key": "vend-email-primary",
                    "mailbox_base_url": "https://mail.example.com/",
                    "mailbox_password": "Mailbox#123",
                    "service_email": "ops@example.com",
                    "service_password": "Vend#123",
                    "mailbox_account_id": 7,
                    "mailbox_token": "token-from-config",
                    "register_url": "https://vend.example.test/register",
                    "confirmation_anchor": "https://vend.example.test/auth/confirmation",
                    "confirmation_anchor_prefix": "https://vend.example.test/auth/confirmation?",
                    "alias_domain": "serf.me",
                    "alias_domain_id": "42",
                    "mailbox_service_email": "ops@example.com",
                }
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.alias_email, "ops@serf.me")
        self.assertEqual(result.real_mailbox_email, "admin@cxwsss.online")
        self.assertEqual(result.service_email, "ops@example.com")
        self.assertEqual(result.steps, ["register", "confirmation", "login", "list_forwarders", "create_forwarder"])
        self.assertEqual(
            [entry["name"] for entry in result.capture_summary],
            [
                "register",
                "mailbox_login",
                "mailbox_verification",
                "confirmation",
                "login",
                "list_forwarders",
                "create_forwarder",
            ],
        )
        self.assertEqual(len(request_calls), 7)
        self.assertEqual(request_calls[0]["method"], "POST")
        self.assertEqual(request_calls[0]["url"], "https://vend.example.test/register")
        self.assertEqual(request_calls[1]["url"], "https://mail.example.com/api/login")
        self.assertEqual(
            request_calls[1]["json"],
            {"email": "admin@cxwsss.online", "password": "Mailbox#123"},
        )
        self.assertEqual(request_calls[2]["url"], "https://mail.example.com/api/email/list")
        self.assertEqual(
            request_calls[2]["params"],
            {
                "accountId": 7,
                "allReceive": 1,
                "emailId": 0,
                "timeSort": 0,
                "size": 100,
                "type": 0,
            },
        )
        self.assertEqual(request_calls[2]["headers"], {"authorization": "mailbox-token-123"})
        self.assertEqual(request_calls[4]["url"], "https://vend.example.test/auth/login")
        self.assertEqual(
            request_calls[6]["data"],
            {
                "forwarder[local_part]": "ops",
                "forwarder[domain_id]": "42",
                "forwarder[recipient]": "admin@cxwsss.online",
            },
        )
        store.save.assert_called_once()
        saved_state = store.save.call_args.args[0]
        self.assertEqual(saved_state.known_aliases, ["ops@serf.me"])
        self.assertEqual(saved_state.last_capture_summary[0].name, "register")
        self.assertEqual(getattr(saved_state, "mailbox_email", ""), "admin@cxwsss.online")
        self.assertEqual(saved_state.service_email, "ops@example.com")
        self.assertEqual(saved_state.service_password, "Vend#123")
        self.assertEqual(
            saved_state.session_storage.get("confirmation_link"),
            "https://vend.example.test/auth/confirmation?confirmation_token=abc123",
        )
        self.assertEqual(saved_state.session_storage.get("token"), "mailbox-token-123")

    def test_normalize_accepts_vend_email_source_with_runtime_config_fields(self):
        result = normalize_cloudmail_alias_pool_config(
            {
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "vend-1",
                        "type": "vend_email",
                        "register_url": " https://vend.example.test/register ",
                        "mailbox_base_url": " https://mail.example.com/ ",
                        "mailbox_email": " Admin@Example.com ",
                        "mailbox_password": " mailbox-secret ",
                        "service_email": " Ops@Example.com ",
                        "service_password": " Vend#123 ",
                        "mailbox_account_id": "7",
                        "mailbox_token": " token-from-config ",
                        "confirmation_anchor": " https://vend.example.test/auth/confirmation ",
                        "alias_domain": " Serf.Me ",
                        "alias_domain_id": " 42 ",
                    }
                ],
            },
            task_id="task-vend-runtime-config",
        )

        self.assertEqual(
            result["sources"],
            [
                {
                    "id": "vend-1",
                    "type": "vend_email",
                    "register_url": "https://vend.example.test/register",
                    "mailbox_base_url": "https://mail.example.com/",
                    "mailbox_email": "admin@example.com",
                    "mailbox_password": "mailbox-secret",
                    "service_email": "ops@example.com",
                    "service_password": "Vend#123",
                    "mailbox_account_id": 7,
                    "mailbox_token": "token-from-config",
                    "confirmation_anchor": "https://vend.example.test/auth/confirmation",
                    "alias_domain": "serf.me",
                    "alias_domain_id": "42",
                    "alias_count": 0,
                    "state_key": "vend-1",
                }
            ],
        )

    def test_runtime_service_default_executor_raises_for_missing_required_config(self):
        with self.assertRaisesRegex(ValueError, "mailbox_base_url"):
            build_default_vend_executor(
                {
                    "id": "vend-email-primary",
                    "type": "vend_email",
                    "mailbox_email": "admin@cxwsss.online",
                    "mailbox_service_email": "ops@example.com",
                    "mailbox_password": "Mailbox#123",
                    "register_url": "https://vend.example.test/register",
                    "alias_domain": "serf.me",
                }
            )

    def test_runtime_service_skips_registration_steps_when_session_restored(self):
        executor = _FakeVendExecutor(restore_session_result=True)
        store = mock.Mock()
        store.load.return_value = VendEmailServiceState(state_key="vend-email-primary")

        service = VendEmailRuntimeService(state_store=store, executor=executor)

        result = service.run_probe(
            source={
                "id": "vend-email-primary",
                "type": "vend_email",
                "mailbox_email": "admin@cxwsss.online",
                "state_key": "vend-email-primary",
            }
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.steps, ["login", "list_forwarders", "create_forwarder"])
        self.assertEqual(
            executor.calls,
            ["restore_session", "login", "list_forwarders", "create_forwarder"],
        )

    def test_runtime_service_skips_forwarder_creation_when_existing_forwarder_found(self):
        executor = _FakeVendExecutor(
            forwarders=[
                {
                    "alias_email": "existing-forwarder@serf.me",
                    "real_mailbox_email": "admin@cxwsss.online",
                }
            ]
        )
        store = mock.Mock()
        store.load.return_value = VendEmailServiceState(state_key="vend-email-primary")

        service = VendEmailRuntimeService(state_store=store, executor=executor)
        result = service.run_probe(
            source={
                "id": "vend-email-primary",
                "type": "vend_email",
                "mailbox_email": "admin@cxwsss.online",
                "state_key": "vend-email-primary",
            }
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.alias_email, "existing-forwarder@serf.me")
        self.assertEqual(result.steps, ["register", "confirmation", "login", "list_forwarders"])
        self.assertEqual(
            executor.calls,
            [
                "restore_session",
                "register",
                "fetch_confirmation_link",
                "confirm",
                "login",
                "list_forwarders",
            ],
        )

    def test_runtime_service_returns_structured_error_when_forwarder_not_created(self):
        executor = _FakeVendExecutor(
            created_forwarder={"alias_email": "", "real_mailbox_email": "admin@cxwsss.online"}
        )
        store = mock.Mock()
        store.load.return_value = VendEmailServiceState(
            state_key="vend-email-primary",
            known_aliases=["previous-alias@serf.me"],
        )
        service = VendEmailRuntimeService(state_store=store, executor=executor)

        result = service.run_probe(
            source={
                "id": "vend-email-primary",
                "type": "vend_email",
                "mailbox_email": "admin@cxwsss.online",
                "state_key": "vend-email-primary",
            }
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "vend probe did not produce alias")
        self.assertEqual(result.steps, ["register", "confirmation", "login", "list_forwarders", "create_forwarder"])
        self.assertEqual(
            result.capture_summary,
            [
                {
                    "name": "login",
                    "url": "https://www.vend.email/auth/login",
                    "method": "POST",
                    "request_headers_whitelist": {"content-type": "application/x-www-form-urlencoded"},
                    "request_body_excerpt": "user[email]=vendcap202604170108@cxwsss.online",
                    "response_status": 302,
                    "response_body_excerpt": "",
                    "captured_at": "2026-04-17T10:00:00+08:00",
                }
            ],
        )
        saved_state = store.save.call_args.args[0]
        self.assertEqual(saved_state.known_aliases, [])
        self.assertEqual(saved_state.last_capture_summary[0].name, "login")
        self.assertEqual(saved_state.service_email, "vendcap202604170108@cxwsss.online")

    def test_runtime_service_raises_clear_error_for_unexpected_loaded_state(self):
        executor = _FakeVendExecutor()
        store = mock.Mock()
        store.load.return_value = object()
        service = VendEmailRuntimeService(state_store=store, executor=executor)

        with self.assertRaisesRegex(TypeError, r"state_store.load\(\) must return VendEmailServiceState"):
            service.run_probe(
                source={
                    "id": "vend-email-primary",
                    "type": "vend_email",
                    "mailbox_email": "admin@cxwsss.online",
                    "state_key": "vend-email-primary",
                }
            )

    def test_runtime_service_raises_clear_error_for_invalid_capture_summary_item(self):
        executor = _FakeVendExecutor(capture_entries=[{"name": "login"}])
        store = mock.Mock()
        store.load.return_value = VendEmailServiceState(state_key="vend-email-primary")
        service = VendEmailRuntimeService(state_store=store, executor=executor)

        with self.assertRaisesRegex(TypeError, r"capture_summary\(\) items must match VendEmailCaptureRecord fields"):
            service.run_probe(
                source={
                    "id": "vend-email-primary",
                    "type": "vend_email",
                    "mailbox_email": "admin@cxwsss.online",
                    "state_key": "vend-email-primary",
                }
            )


class MailboxVerificationAdapterTests(unittest.TestCase):
    def test_build_mailbox_login_request_uses_configured_base_url_and_credentials(self):
        builder = mailbox_verification_adapter.build_mailbox_login_request
        request = builder(
            mailbox_base_url="https://mailbox.example",
            mailbox_email="admin@example.com",
            mailbox_password="secret-pass",
        )

        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["url"], "https://mailbox.example/api/login")
        self.assertEqual(
            request["json"],
            {
                "email": "admin@example.com",
                "password": "secret-pass",
            },
        )

    def test_with_token_in_session_storage_returns_updated_copy(self):
        helper = mailbox_verification_adapter.with_token_in_session_storage
        existing_storage = {"existing": "value"}
        updated_storage = helper(existing_storage, "token-123")

        self.assertIsNot(updated_storage, existing_storage)
        self.assertEqual(existing_storage, {"existing": "value"})
        self.assertEqual(updated_storage, {"existing": "value", "token": "token-123"})

    def test_extract_token_from_storage_reads_string_token(self):
        helper = mailbox_verification_adapter.extract_token_from_storage
        self.assertEqual(helper({"token": "token-123", "other": "ignored"}), "token-123")

    def test_build_mailbox_email_list_request_uses_base_url_and_token(self):
        builder = mailbox_verification_adapter.build_mailbox_email_list_request
        request = builder(
            mailbox_base_url="https://mailbox.example",
            token="token-123",
            account_id=7,
        )

        self.assertEqual(request["method"], "GET")
        self.assertEqual(request["url"], "https://mailbox.example/api/email/list")
        self.assertEqual(
            request["params"],
            {
                "accountId": 7,
                "allReceive": 1,
                "emailId": 0,
                "timeSort": 0,
                "size": 100,
                "type": 0,
            },
        )
        self.assertEqual(request["headers"], {"authorization": "token-123"})

    def test_extract_anchored_link_from_message_content_uses_configured_anchor(self):
        helper = mailbox_verification_adapter.extract_anchored_link_from_message_content
        text = (
            "Please confirm: "
            "https://www.vend.email/auth/confirmation?confirmation_token=abc123 thanks"
        )
        link = helper(
            text,
            link_anchor="https://www.vend.email/auth/confirmation",
        )

        self.assertEqual(
            link,
            "https://www.vend.email/auth/confirmation?confirmation_token=abc123",
        )


if __name__ == "__main__":
    unittest.main()
