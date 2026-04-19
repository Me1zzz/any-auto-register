import unittest

from core.alias_pool.alias_email_provider import build_alias_email_alias_provider
from core.alias_pool.emailshield_provider import build_emailshield_alias_provider
from core.alias_pool.myalias_pro_provider import build_myalias_pro_alias_provider
from core.alias_pool.interactive_provider_registry import register_interactive_alias_providers
from core.alias_pool.secureinseconds_provider import build_secureinseconds_alias_provider
from core.alias_pool.simplelogin_provider import build_simplelogin_alias_provider
from core.alias_pool.config import build_alias_provider_source_specs
from core.alias_pool.provider_adapters import build_simple_generator_alias_provider, build_static_list_alias_provider
from core.alias_pool.provider_bootstrap import AliasProviderBootstrap
from core.alias_pool.provider_contracts import (
    AliasAutomationTestPolicy,
    AliasAutomationTestResult,
    AliasProvider,
    AliasProviderBootstrapContext,
)
from core.alias_pool.provider_registry import AliasProviderRegistry
from core.alias_pool.automation_test import AliasAutomationTestService


class _DummyAliasProvider:
    source_id = "vend-email-primary"
    source_kind = "vend_email"

    @property
    def provider_type(self) -> str:
        return self.source_kind

    def load_into(self, pool_manager) -> None:
        self.pool_manager = pool_manager

    def run_alias_generation_test(
        self,
        policy: AliasAutomationTestPolicy,
    ) -> AliasAutomationTestResult:
        return AliasAutomationTestResult(
            provider_type="vend_email",
            source_id=self.source_id,
        )


class AliasProviderBootstrapTests(unittest.TestCase):
    def test_shared_interactive_provider_registry_helper_registers_all_planned_types(self):
        registry = AliasProviderRegistry()

        returned = register_interactive_alias_providers(registry)

        self.assertIs(returned, registry)
        self.assertIs(registry.resolve("myalias_pro"), build_myalias_pro_alias_provider)
        self.assertIs(registry.resolve("secureinseconds"), build_secureinseconds_alias_provider)
        self.assertIs(registry.resolve("emailshield"), build_emailshield_alias_provider)
        self.assertIs(registry.resolve("simplelogin"), build_simplelogin_alias_provider)
        self.assertIs(registry.resolve("alias_email"), build_alias_email_alias_provider)

    def test_planned_provider_modules_export_expected_builder_functions(self):
        registry = AliasProviderRegistry()
        registry.register("myalias_pro", build_myalias_pro_alias_provider)
        registry.register("secureinseconds", build_secureinseconds_alias_provider)
        registry.register("emailshield", build_emailshield_alias_provider)
        registry.register("simplelogin", build_simplelogin_alias_provider)
        registry.register("alias_email", build_alias_email_alias_provider)

        self.assertIs(registry.resolve("myalias_pro"), build_myalias_pro_alias_provider)
        self.assertIs(registry.resolve("secureinseconds"), build_secureinseconds_alias_provider)
        self.assertIs(registry.resolve("emailshield"), build_emailshield_alias_provider)
        self.assertIs(registry.resolve("simplelogin"), build_simplelogin_alias_provider)
        self.assertIs(registry.resolve("alias_email"), build_alias_email_alias_provider)

    def test_supported_interactive_provider_types_all_build_alias_provider_instances(self):
        bootstrap = AliasAutomationTestService()._build_default_bootstrap()
        specs = build_alias_provider_source_specs(
            {
                "enabled": True,
                "task_id": "alias-test",
                "sources": [
                    {
                        "id": "myalias-pro-primary",
                        "type": "myalias_pro",
                        "alias_count": 2,
                        "state_key": "myalias-pro-primary",
                        "confirmation_inbox": {
                            "provider": "cloudmail",
                            "account_email": "real@example.com",
                            "account_password": "mail-pass",
                            "match_email": "real@example.com",
                        },
                    },
                    {
                        "id": "secureinseconds-primary",
                        "type": "secureinseconds",
                        "alias_count": 2,
                        "state_key": "secureinseconds-primary",
                        "confirmation_inbox": {
                            "provider": "cloudmail",
                            "account_email": "real@example.com",
                            "account_password": "mail-pass",
                            "match_email": "real@example.com",
                        },
                    },
                    {
                        "id": "emailshield-primary",
                        "type": "emailshield",
                        "alias_count": 2,
                        "state_key": "emailshield-primary",
                        "confirmation_inbox": {
                            "provider": "cloudmail",
                            "account_email": "real@example.com",
                            "account_password": "mail-pass",
                            "match_email": "real@example.com",
                        },
                    },
                    {
                        "id": "simplelogin-primary",
                        "type": "simplelogin",
                        "alias_count": 2,
                        "state_key": "simplelogin-primary",
                        "provider_config": {
                            "site_url": "https://simplelogin.io/",
                            "accounts": [
                                {"email": "fust@fst.cxwsss.online", "label": "fust"},
                            ],
                        },
                        "confirmation_inbox": {
                            "provider": "cloudmail",
                            "account_email": "real@example.com",
                            "account_password": "mail-pass",
                            "match_email": "real@example.com",
                        },
                    },
                    {
                        "id": "alias-email-primary",
                        "type": "alias_email",
                        "alias_count": 2,
                        "state_key": "alias-email-primary",
                        "confirmation_inbox": {
                            "provider": "cloudmail",
                            "account_email": "real@example.com",
                            "account_password": "mail-pass",
                            "match_email": "real@example.com",
                        },
                    },
                ],
            }
        )
        context = AliasProviderBootstrapContext(task_id="alias-test-run", purpose="automation_test")

        for spec in specs:
            provider = bootstrap.build(spec=spec, context=context)
            self.assertIsInstance(provider, AliasProvider)
            self.assertEqual(provider.provider_type, spec.provider_type)

    def test_simplelogin_provider_returns_clear_not_implemented_domain_discovery_failure(self):
        service = AliasAutomationTestService()

        result = service.run(
            pool_config={
                "enabled": True,
                "task_id": "alias-test",
                "sources": [
                    {
                        "id": "simplelogin-primary",
                        "type": "simplelogin",
                        "alias_count": 2,
                        "state_key": "simplelogin-primary",
                        "provider_config": {
                            "site_url": "https://simplelogin.io/",
                            "accounts": [
                                {"email": "fust@fst.cxwsss.online", "label": "fust"},
                            ],
                        },
                        "confirmation_inbox": {
                            "provider": "cloudmail",
                            "account_email": "real@example.com",
                            "account_password": "mail-pass",
                            "match_email": "real@example.com",
                        },
                    }
                ],
            },
            source_id="simplelogin-primary",
            task_id="alias-test-run",
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.source_type, "simplelogin")
        self.assertEqual(result.failure.get("stageCode"), "discover_alias_domains")
        self.assertIn("signed domain discovery not implemented yet", result.error)

    def test_build_alias_provider_source_specs_supports_provider_config_backed_simplelogin_source(self):
        pool_config = {
            "enabled": True,
            "task_id": "alias-test",
            "sources": [
                {
                    "id": "simplelogin-primary",
                    "type": "simplelogin",
                    "alias_count": 3,
                    "state_key": "simplelogin-primary",
                    "confirmation_inbox": {
                        "provider": "cloudmail",
                        "account_email": "real@example.com",
                        "account_password": "mail-pass",
                        "match_email": "real@example.com",
                    },
                    "provider_config": {
                        "site_url": "https://simplelogin.io/",
                        "accounts": [
                            {"email": "fust@fst.cxwsss.online", "label": "fust"},
                            {"email": "logon@fst.cxwsss.online", "label": "logon", "password": "secret-pass"},
                        ],
                    },
                }
            ],
        }

        specs = build_alias_provider_source_specs(pool_config)

        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].source_id, "simplelogin-primary")
        self.assertEqual(specs[0].provider_type, "simplelogin")
        self.assertEqual(specs[0].desired_alias_count, 3)
        self.assertEqual(specs[0].state_key, "simplelogin-primary")
        self.assertEqual(specs[0].provider_config["site_url"], "https://simplelogin.io/")
        self.assertEqual(
            specs[0].provider_config["accounts"],
            [
                {"email": "fust@fst.cxwsss.online", "label": "fust"},
                {"email": "logon@fst.cxwsss.online", "label": "logon", "password": "secret-pass"},
            ],
        )
        self.assertEqual(
            specs[0].confirmation_inbox_config,
            {
                "provider": "cloudmail",
                "account_email": "real@example.com",
                "account_password": "mail-pass",
                "match_email": "real@example.com",
            },
        )

    def test_build_alias_provider_source_specs_populates_vend_provider_config_for_migration(self):
        pool_config = {
            "enabled": True,
            "task_id": "alias-test",
            "sources": [
                {
                    "id": "vend-email-primary",
                    "type": "vend_email",
                    "register_url": "https://legacy.example/register",
                    "cloudmail_api_base": "https://legacy.example/api",
                    "cloudmail_admin_email": "legacy-admin@example.com",
                    "cloudmail_admin_password": "legacy-pass",
                    "cloudmail_domain": "legacy.example.com",
                    "cloudmail_subdomain": "legacy-sub",
                    "cloudmail_timeout": 41,
                    "confirmation_inbox": {
                        "provider": "cloudmail",
                        "api_base": "https://mailbox.example/api",
                        "admin_email": "mailbox-admin@example.com",
                        "admin_password": "mailbox-pass",
                        "domain": "mailbox.example.com",
                        "subdomain": "mailbox-sub",
                        "timeout": 55,
                        "account_email": "real@example.com",
                        "account_password": "real-pass",
                        "match_email": "real@example.com",
                    },
                    "alias_domain": "serf.me",
                    "alias_domain_id": "42",
                    "alias_count": 2,
                    "state_key": "vend-email-primary",
                }
            ],
        }

        specs = build_alias_provider_source_specs(pool_config)

        self.assertEqual(specs[0].provider_config["register_url"], "https://legacy.example/register")
        self.assertEqual(specs[0].provider_config["cloudmail_api_base"], "https://legacy.example/api")
        self.assertEqual(specs[0].provider_config["cloudmail_admin_email"], "legacy-admin@example.com")
        self.assertEqual(specs[0].provider_config["cloudmail_admin_password"], "legacy-pass")
        self.assertEqual(specs[0].provider_config["cloudmail_domain"], "legacy.example.com")
        self.assertEqual(specs[0].provider_config["cloudmail_subdomain"], "legacy-sub")
        self.assertEqual(specs[0].provider_config["cloudmail_timeout"], 41)
        self.assertEqual(specs[0].provider_config["alias_domain"], "serf.me")
        self.assertEqual(specs[0].provider_config["alias_domain_id"], "42")
        self.assertEqual(specs[0].provider_config["alias_count"], 2)
        self.assertEqual(specs[0].provider_config["state_key"], "vend-email-primary")
        self.assertEqual(
            specs[0].provider_config["confirmation_inbox"],
            {
                "provider": "cloudmail",
                "api_base": "https://mailbox.example/api",
                "admin_email": "mailbox-admin@example.com",
                "admin_password": "mailbox-pass",
                "domain": "mailbox.example.com",
                "subdomain": "mailbox-sub",
                "timeout": 55,
                "account_email": "real@example.com",
                "account_password": "real-pass",
                "match_email": "real@example.com",
            },
        )

    def test_build_alias_provider_source_specs_wraps_vend_confirmation_inbox_config(self):
        pool_config = {
            "enabled": True,
            "task_id": "alias-test",
            "sources": [
                {
                    "id": "vend-email-primary",
                    "type": "vend_email",
                    "register_url": "https://www.vend.email/auth/register",
                    "cloudmail_api_base": "https://mail.example/api",
                    "cloudmail_admin_email": "admin@example.com",
                    "cloudmail_admin_password": "secret-pass",
                    "cloudmail_domain": "example.com",
                    "cloudmail_subdomain": "mx",
                    "cloudmail_timeout": 30,
                    "confirmation_inbox": {
                        "provider": "cloudmail",
                        "account_email": "confirm-admin@example.com",
                        "account_password": "confirm-secret",
                        "match_email": "confirm-admin@example.com",
                    },
                    "alias_domain": "serf.me",
                    "alias_domain_id": "42",
                    "alias_count": 2,
                    "state_key": "vend-email-primary",
                }
            ],
        }

        specs = build_alias_provider_source_specs(pool_config)

        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].source_id, "vend-email-primary")
        self.assertEqual(specs[0].provider_type, "vend_email")
        self.assertEqual(specs[0].desired_alias_count, 2)
        self.assertEqual(specs[0].state_key, "vend-email-primary")
        self.assertEqual(specs[0].register_url, "https://www.vend.email/auth/register")
        self.assertEqual(specs[0].alias_domain, "serf.me")
        self.assertEqual(specs[0].alias_domain_id, "42")
        self.assertEqual(
            specs[0].raw_source,
            {
                "id": "vend-email-primary",
                "type": "vend_email",
                "register_url": "https://www.vend.email/auth/register",
                "cloudmail_api_base": "https://mail.example/api",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret-pass",
                "cloudmail_domain": "example.com",
                "cloudmail_subdomain": "mx",
                "cloudmail_timeout": 30,
                "confirmation_inbox": {
                    "provider": "cloudmail",
                    "account_email": "confirm-admin@example.com",
                    "account_password": "confirm-secret",
                    "match_email": "confirm-admin@example.com",
                },
                "alias_domain": "serf.me",
                "alias_domain_id": "42",
                "alias_count": 2,
                "state_key": "vend-email-primary",
            },
        )
        self.assertEqual(
            specs[0].confirmation_inbox_config,
            {
                "provider": "cloudmail",
                "api_base": "https://mail.example/api",
                "admin_email": "admin@example.com",
                "admin_password": "secret-pass",
                "domain": "example.com",
                "subdomain": "mx",
                "timeout": 30,
                "account_email": "confirm-admin@example.com",
                "account_password": "confirm-secret",
                "match_email": "confirm-admin@example.com",
            },
        )

    def test_registry_resolves_registered_builder(self):
        registry = AliasProviderRegistry()
        marker = _DummyAliasProvider()
        registry.register("vend_email", lambda spec, context: marker)

        resolved = registry.resolve("vend_email")

        self.assertIsNotNone(resolved)
        assert resolved is not None
        spec = build_alias_provider_source_specs(
            {
                "enabled": True,
                "task_id": "alias-test",
                "sources": [{"id": "vend-email-primary", "type": "vend_email"}],
            }
        )[0]
        context = AliasProviderBootstrapContext(task_id="alias-test-run", purpose="automation_test")
        self.assertIs(resolved(spec, context), marker)

    def test_bootstrap_passes_automation_test_context_to_builder(self):
        seen = {}
        registry = AliasProviderRegistry()

        def _builder(spec, context):
            seen["spec"] = spec
            seen["context"] = context
            return _DummyAliasProvider()

        registry.register("vend_email", _builder)
        bootstrap = AliasProviderBootstrap(registry=registry)
        spec = build_alias_provider_source_specs(
            {
                "enabled": True,
                "task_id": "alias-test",
                "sources": [{"id": "vend-email-primary", "type": "vend_email", "state_key": "vend-email-primary"}],
            }
        )[0]
        context = AliasProviderBootstrapContext(
            task_id="alias-test-run",
            purpose="automation_test",
            test_policy=AliasAutomationTestPolicy(
                fresh_service_account=True,
                persist_state=False,
                minimum_alias_count=3,
                capture_enabled=True,
            ),
        )

        bootstrap.build(spec=spec, context=context)

        self.assertIs(seen["spec"], spec)
        self.assertEqual(seen["context"].purpose, "automation_test")
        self.assertEqual(seen["context"].test_policy.minimum_alias_count, 3)

    def test_bootstrap_raises_clear_error_for_unsupported_provider_type(self):
        bootstrap = AliasProviderBootstrap(registry=AliasProviderRegistry())
        spec = build_alias_provider_source_specs(
            {
                "enabled": True,
                "task_id": "alias-test",
                "sources": [{"id": "unsupported-1", "type": "unsupported_provider"}],
            }
        )[0]
        context = AliasProviderBootstrapContext(task_id="alias-test-run", purpose="automation_test")

        with self.assertRaisesRegex(ValueError, "Unsupported alias provider type: unsupported_provider"):
            bootstrap.build(spec=spec, context=context)

    def test_alias_provider_contract_exposes_minimal_structured_result_defaults(self):
        provider = _DummyAliasProvider()
        policy = AliasAutomationTestPolicy(
            fresh_service_account=True,
            persist_state=False,
            minimum_alias_count=1,
            capture_enabled=True,
        )

        self.assertIsInstance(provider, AliasProvider)

        result = provider.run_alias_generation_test(policy)

        self.assertEqual(result.provider_type, "vend_email")
        self.assertEqual(result.source_id, "vend-email-primary")
        self.assertEqual(result.account_identity.service_account_email, "")
        self.assertEqual(result.aliases, [])
        self.assertEqual(result.stage_timeline, [])
        self.assertEqual(result.capture_summary, [])
        self.assertEqual(result.logs, [])
        self.assertTrue(result.ok)
        self.assertEqual(result.error, "")
        self.assertEqual(provider.source_kind, result.provider_type)

    def test_supported_provider_types_all_build_alias_provider_instances(self):
        registry = AliasProviderRegistry()
        registry.register("static_list", build_static_list_alias_provider)
        registry.register("simple_generator", build_simple_generator_alias_provider)
        registry.register("vend_email", lambda spec, context: _DummyAliasProvider())

        specs = build_alias_provider_source_specs(
            {
                "enabled": True,
                "task_id": "alias-test",
                "sources": [
                    {
                        "id": "legacy-static",
                        "type": "static_list",
                        "emails": ["alias@example.com"],
                        "mailbox_email": "real@example.com",
                    },
                    {
                        "id": "simple-1",
                        "type": "simple_generator",
                        "prefix": "msi.",
                        "suffix": "@manyme.com",
                        "count": 1,
                        "middle_length_min": 3,
                        "middle_length_max": 3,
                        "mailbox_email": "real@example.com",
                    },
                    {
                        "id": "vend-email-primary",
                        "type": "vend_email",
                        "register_url": "https://www.vend.email/auth/register",
                        "alias_domain": "serf.me",
                        "alias_domain_id": "42",
                        "alias_count": 1,
                        "state_key": "vend-email-primary",
                    },
                ],
            }
        )
        context = AliasProviderBootstrapContext(task_id="alias-test-run", purpose="automation_test")

        for spec in specs:
            builder = registry.resolve(spec.provider_type)
            self.assertIsNotNone(builder, f"missing builder for {spec.provider_type}")
            assert builder is not None
            provider = builder(spec, context)
            self.assertIsInstance(provider, AliasProvider)
            self.assertEqual(provider.provider_type, spec.provider_type)
