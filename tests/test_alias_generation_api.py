import unittest
from unittest import mock
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from api.config import _decode_config_value, _default_alias_test_runtime_builder, _encode_config_value
from core.alias_pool.config import normalize_cloudmail_alias_pool_config
from core.alias_pool.provider_contracts import AliasAutomationTestPolicy, AliasProviderBootstrapContext
from core.alias_pool.probe import AliasProbeResult, AliasSourceProbeService
from core.alias_pool.vend_email_state import VendEmailCaptureRecord, VendEmailServiceState


class AliasGenerationApiTests(unittest.TestCase):
    def test_config_value_helpers_delegate_source_serialization_to_alias_pool_config(self):
        payload_sources = [{"id": "vend-1", "type": "vend_email", "alias_count": 2, "state_key": "vend-state", "alias_domain_id": "42"}]

        with patch("api.config.encode_alias_provider_sources", return_value='[{"id":"vend-1"}]') as encode_sources, patch(
            "api.config.decode_alias_provider_sources",
            return_value=payload_sources,
        ) as decode_sources:
            encoded = _encode_config_value("sources", payload_sources)
            decoded = _decode_config_value("sources", '[{"id":"vend-1"}]')

        self.assertEqual(encoded, '[{"id":"vend-1"}]')
        self.assertEqual(decoded, payload_sources)
        encode_sources.assert_called_once_with(payload_sources)
        decode_sources.assert_called_once_with('[{"id":"vend-1"}]')

    def test_backend_normalize_preserves_explicit_simple_generator_sources(self):
        result = normalize_cloudmail_alias_pool_config(
            {
                "cloudmail_alias_enabled": True,
                "cloudmail_alias_emails": "legacy@example.com",
                "sources": [
                    {
                        "id": "simple-1",
                        "type": "simple_generator",
                        "prefix": "msi.",
                        "suffix": "@manyme.com",
                        "count": 2,
                        "middle_length_min": 3,
                        "middle_length_max": 6,
                    }
                ],
            },
            task_id="alias-test",
        )

        self.assertEqual(
            result["sources"],
            [
                {
                    "id": "simple-1",
                    "type": "simple_generator",
                    "prefix": "msi.",
                    "suffix": "@manyme.com",
                    "count": 2,
                    "middle_length_min": 3,
                    "middle_length_max": 6,
                },
            ],
        )

    def test_backend_normalize_builds_vend_source_from_service_toggles_without_explicit_sources(self):
        result = normalize_cloudmail_alias_pool_config(
            {
                "cloudmail_alias_enabled": True,
                "cloudmail_alias_emails": "legacy@example.com",
                "cloudmail_admin_password": "cloudmail-pass",
                "cloudmail_alias_service_static_enabled": True,
                "cloudmail_alias_service_vend_enabled": True,
                "cloudmail_alias_service_vend_alias_count": 4,
            },
            task_id="alias-test",
        )

        self.assertEqual(
            result["sources"],
            [
                {
                    "id": "legacy-static",
                    "type": "static_list",
                    "emails": ["legacy@example.com"],
                },
                {
                    "id": "vend-email-primary",
                    "type": "vend_email",
                    "register_url": "https://www.vend.email/auth/register",
                    "cloudmail_api_base": "",
                    "cloudmail_admin_email": "",
                    "cloudmail_admin_password": "cloudmail-pass",
                    "cloudmail_domain": "",
                    "cloudmail_subdomain": "",
                    "cloudmail_timeout": 30,
                    "alias_domain": "",
                    "alias_domain_id": "",
                    "alias_count": 4,
                    "state_key": "vend-email-primary",
                    "confirmation_inbox": {
                        "provider": "cloudmail",
                        "admin_password": "cloudmail-pass",
                        "timeout": 30,
                    },
                }
            ],
        )

    def test_alias_generation_test_api_supports_saved_static_source_after_config_round_trip(self):
        client = TestClient(app)
        saved_config = {
            "cloudmail_alias_enabled": True,
            "sources": '[{"id": "qa-static", "type": "static_list", "emails": ["a@example.com"], "mailbox_email": "real@example.com"}]',
        }

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.get_all", return_value=saved_config
        ):
            resp = client.post(
                "/api/config/alias-test",
                json={"sourceId": "qa-static", "useDraftConfig": False},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["sourceId"], "qa-static")
        self.assertEqual(body["aliasEmail"], "a@example.com")

    def test_alias_generation_test_api_uses_unified_automation_test_service(self):
        client = TestClient(app)

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.get_all",
            return_value={"cloudmail_alias_enabled": True, "sources": []},
        ), patch(
            "api.config.normalize_cloudmail_alias_pool_config",
            return_value={"enabled": True, "task_id": "alias-test", "sources": []},
        ) as normalize_config, patch("api.config.AliasAutomationTestService") as automation_service_cls:
            automation_service = automation_service_cls.return_value
            automation_service.run.return_value = AliasProbeResult(
                ok=True,
                source_id="qa-static",
                source_type="static_list",
                alias_email="a@example.com",
                real_mailbox_email="real@example.com",
                account={"realMailboxEmail": "real@example.com", "serviceEmail": "", "password": ""},
                aliases=[{"email": "a@example.com"}],
            )

            resp = client.post(
                "/api/config/alias-test",
                json={"sourceId": "qa-static", "useDraftConfig": False},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["sourceId"], "qa-static")
        self.assertEqual(body["aliasEmail"], "a@example.com")
        normalize_config.assert_called_once_with(
            {"cloudmail_alias_enabled": True, "sources": []},
            task_id="alias-test",
        )
        automation_service.run.assert_called_once_with(
            pool_config={"enabled": True, "task_id": "alias-test", "sources": []},
            source_id="qa-static",
            task_id="alias-test",
        )

    def test_alias_generation_test_api_supports_legacy_static_fallback_from_draft_config(self):
        client = TestClient(app)

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.get_all", return_value={}
        ):
            resp = client.post(
                "/api/config/alias-test",
                json={
                    "sourceId": "legacy-static",
                    "useDraftConfig": True,
                    "config": {
                        "cloudmail_alias_enabled": True,
                        "cloudmail_alias_emails": "a@example.com",
                    },
                },
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["sourceId"], "legacy-static")
        self.assertEqual(body["aliasEmail"], "a@example.com")

    def test_alias_generation_test_api_supports_myalias_source_shape(self):
        client = TestClient(app)
        expected_source = {
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
        }

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.get_all",
            return_value={
                "cloudmail_alias_enabled": True,
                "sources": [expected_source],
            },
        ), patch("api.config.AliasAutomationTestService") as service_cls:
            service = service_cls.return_value
            service.run.return_value = AliasProbeResult(
                ok=True,
                source_id="myalias-primary",
                source_type="myalias_pro",
                alias_email="myalias-1@myalias.pro",
                real_mailbox_email="real@example.com",
                service_email="service@myalias.pro",
                account={"realMailboxEmail": "real@example.com", "serviceEmail": "service@myalias.pro", "password": "secret-pass"},
                aliases=[
                    {"email": "myalias-1@myalias.pro"},
                    {"email": "myalias-2@myalias.pro"},
                    {"email": "myalias-3@myalias.pro"},
                ],
                current_stage={"code": "aliases_ready", "label": "别名预览已生成"},
                stages=[
                    {"code": "session_ready", "label": "会话已就绪", "status": "completed"},
                    {"code": "verify_account_email", "label": "验证服务账号邮箱", "status": "completed"},
                    {"code": "create_aliases", "label": "创建别名", "status": "completed"},
                ],
            )

            resp = client.post("/api/config/alias-test", json={"sourceId": "myalias-primary", "useDraftConfig": False})

        self.assertEqual(resp.status_code, 200)
        service.run.assert_called_once()
        pool_config = service.run.call_args.kwargs["pool_config"]
        self.assertEqual(pool_config["sources"], [expected_source])
        self.assertEqual(service.run.call_args.kwargs["source_id"], "myalias-primary")
        body = resp.json()
        self.assertEqual(body["sourceType"], "myalias_pro")
        self.assertEqual(len(body["aliases"]), 3)
        self.assertEqual(body["stages"][1]["code"], "verify_account_email")

    def test_backend_normalize_preserves_emailshield_existing_account_source_shape(self):
        result = normalize_cloudmail_alias_pool_config(
            {
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "emailshield-primary",
                        "type": "emailshield",
                        "alias_count": 3,
                        "state_key": "emailshield-primary",
                        "provider_config": {
                            "accounts": [
                                {"email": "loga@fst.cxwsss.online"},
                                {"email": "juso@fst.cxwsss.online"},
                            ],
                        },
                    }
                ],
            },
            task_id="alias-test",
        )

        self.assertEqual(
            result["sources"],
            [
                {
                    "id": "emailshield-primary",
                    "type": "emailshield",
                    "alias_count": 3,
                    "state_key": "emailshield-primary",
                    "provider_config": {
                        "accounts": [
                            {"email": "loga@fst.cxwsss.online"},
                            {"email": "juso@fst.cxwsss.online"},
                        ],
                    },
                }
            ],
        )

    def test_backend_normalize_builds_myalias_source_from_fixed_cloudmail_fields(self):
        result = normalize_cloudmail_alias_pool_config(
            {
                "cloudmail_alias_enabled": True,
                "cloudmail_alias_myalias_pro_enabled": True,
                "cloudmail_alias_myalias_pro_alias_count": 2,
                "cloudmail_api_base": "https://cxwsss.online/",
                "cloudmail_admin_email": "admin@cxwsss.online",
                "cloudmail_admin_password": "1103@Icity",
                "cloudmail_domain": "cxwsss.online",
            },
            task_id="alias-test",
        )

        self.assertEqual(
            result["sources"],
            [
                {
                    "id": "myalias-pro-primary",
                    "type": "myalias_pro",
                    "alias_count": 2,
                    "state_key": "myalias-pro-primary",
                    "confirmation_inbox": {
                        "provider": "cloudmail",
                        "api_base": "https://cxwsss.online/",
                        "admin_email": "admin@cxwsss.online",
                        "account_email": "admin@cxwsss.online",
                        "admin_password": "1103@Icity",
                        "account_password": "1103@Icity",
                        "domain": "cxwsss.online",
                        "timeout": 30,
                    },
                    "provider_config": {
                        "signup_url": "https://myalias.pro/signup/",
                        "login_url": "https://myalias.pro/login/",
                        "alias_url": "https://myalias.pro/aliases/",
                    },
                }
            ],
        )

    def test_get_config_decodes_sources_json_string(self):
        client = TestClient(app)

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.get_all",
            return_value={
                "cloudmail_admin_password": "secret-pass",
                "sources": (
                    '[{"id":"vend-1","type":"vend_email","register_url":"https://accounts.example.test/register",'
                    '"cloudmail_api_base":"https://cloudmail.example/api","cloudmail_admin_email":"admin@example.com",'
                    '"cloudmail_admin_password":"secret-pass","cloudmail_domain":"mail.example.com",'
                    '"cloudmail_subdomain":"pool-a","cloudmail_timeout":45,"alias_domain":"serf.me",'
                    '"alias_domain_id":"42","alias_count":2,"state_key":"vend-state"}]'
                )
            },
        ):
            resp = client.get("/api/config")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(
            body["sources"],
            [
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
                    "alias_domain_id": "42",
                    "alias_count": 2,
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
                        "confirmation_inbox": {
                            "provider": "cloudmail",
                            "api_base": "https://cloudmail.example/api",
                            "admin_email": "admin@example.com",
                            "admin_password": "secret-pass",
                            "domain": "mail.example.com",
                            "subdomain": "pool-a",
                            "timeout": 45,
                        },
                        "state_key": "vend-state",
                    },
                    "state_key": "vend-state",
                }
            ],
        )
        self.assertEqual(body["cloudmail_admin_password"], "")

    def test_get_config_preserves_cloudmail_alias_service_keys(self):
        client = TestClient(app)

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.get_all",
            return_value={
                "cloudmail_alias_enabled": True,
                "cloudmail_alias_service_static_enabled": True,
                "cloudmail_alias_service_vend_enabled": True,
                "cloudmail_alias_service_vend_alias_count": "5",
                "cloudmail_alias_service_vend_state_key": "vend-state",
            },
        ):
            resp = client.get("/api/config")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["cloudmail_alias_enabled"], True)
        self.assertEqual(body["cloudmail_alias_service_static_enabled"], True)
        self.assertEqual(body["cloudmail_alias_service_vend_enabled"], True)
        self.assertEqual(body["cloudmail_alias_service_vend_alias_count"], "5")
        self.assertEqual(body["cloudmail_alias_service_vend_state_key"], "vend-state")

    def test_get_config_returns_default_guerrillamail_api_url(self):
        client = TestClient(app)

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.get_all", return_value={}
        ):
            resp = client.get("/api/config")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(
            body["guerrillamail_api_url"],
            "https://api.guerrillamail.com/ajax.php",
        )

    def test_update_config_accepts_guerrillamail_provider_and_api_url(self):
        client = TestClient(app)

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.set_many"
        ) as set_many:
            resp = client.put(
                "/api/config",
                json={
                    "data": {
                        "mail_provider": "guerrillamail",
                        "guerrillamail_api_url": "https://api.guerrillamail.com/ajax.php",
                    }
                },
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            set_many.call_args.args[0],
            {
                "mail_provider": "guerrillamail",
                "guerrillamail_api_url": "https://api.guerrillamail.com/ajax.php",
            },
        )

    def test_update_config_encodes_sources_as_json_string_for_store(self):
        client = TestClient(app)
        payload_sources = [
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
                "state_key": "vend-1-state",
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
            }
        ]

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.set_many"
        ) as set_many:
            resp = client.put(
                "/api/config",
                json={"data": {"sources": payload_sources, "mail_provider": "cloudmail"}},
            )

        self.assertEqual(resp.status_code, 200)
        stored_payload = set_many.call_args.args[0]
        self.assertEqual(stored_payload["mail_provider"], "cloudmail")
        self.assertEqual(
            stored_payload["sources"],
            '[{"id": "vend-1", "type": "vend_email", "register_url": "https://accounts.example.test/register", "cloudmail_api_base": "https://cloudmail.example/api", "cloudmail_admin_email": "admin@example.com", "cloudmail_admin_password": "secret-pass", "cloudmail_domain": "mail.example.com", "cloudmail_subdomain": "pool-a", "cloudmail_timeout": 45, "alias_domain": "serf.me", "alias_domain_id": "42", "alias_count": 2, "confirmation_inbox": {"provider": "cloudmail", "api_base": "https://cloudmail.example/api", "admin_email": "admin@example.com", "admin_password": "secret-pass", "domain": "mail.example.com", "subdomain": "pool-a", "timeout": 45}, "provider_config": {"register_url": "https://accounts.example.test/register", "cloudmail_api_base": "https://cloudmail.example/api", "cloudmail_admin_email": "admin@example.com", "cloudmail_admin_password": "secret-pass", "cloudmail_domain": "mail.example.com", "cloudmail_subdomain": "pool-a", "cloudmail_timeout": 45, "alias_domain": "serf.me", "alias_domain_id": "42", "alias_count": 2, "state_key": "vend-1-state", "confirmation_inbox": {"provider": "cloudmail", "api_base": "https://cloudmail.example/api", "admin_email": "admin@example.com", "admin_password": "secret-pass", "domain": "mail.example.com", "subdomain": "pool-a", "timeout": 45}}, "state_key": "vend-1-state"}]',
        )

    def test_alias_generation_test_api_preserves_full_vend_source_from_draft_config(self):
        client = TestClient(app)
        draft_source = {
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
        }

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.get_all",
            return_value={},
        ), patch(
            "api.config.AliasAutomationTestService"
        ) as automation_service_cls:
            automation_service = automation_service_cls.return_value
            automation_service.run.return_value = AliasProbeResult(
                ok=True,
                source_id="vend-1",
                source_type="vend_email",
                alias_email="alias@example.com",
                real_mailbox_email="real@example.com",
                service_email="service@example.com",
                account={"realMailboxEmail": "real@example.com", "serviceEmail": "service@example.com", "password": "secret-pass"},
                aliases=[{"email": "alias@example.com"}],
            )

            resp = client.post(
                "/api/config/alias-test",
                json={
                    "sourceId": "vend-1",
                    "useDraftConfig": True,
                    "config": {
                        "cloudmail_alias_enabled": True,
                        "sources": [draft_source],
                    },
                },
            )

        self.assertEqual(resp.status_code, 200)
        automation_service.run.assert_called_once()
        pool_config = automation_service.run.call_args.kwargs["pool_config"]
        self.assertEqual(pool_config["sources"], [draft_source])

    def test_alias_generation_test_api_builds_explicit_policy_and_context_for_service(self):
        client = TestClient(app)

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.get_all",
            return_value={"cloudmail_alias_enabled": True, "sources": []},
        ), patch(
            "api.config.normalize_cloudmail_alias_pool_config",
            return_value={"enabled": True, "task_id": "alias-test", "sources": []},
        ), patch("api.config.AliasAutomationTestService") as automation_service_cls:
            automation_service = automation_service_cls.return_value
            automation_service.run.return_value = AliasProbeResult(
                ok=True,
                source_id="qa-static",
                source_type="static_list",
                alias_email="a@example.com",
                real_mailbox_email="real@example.com",
                account={"realMailboxEmail": "real@example.com", "serviceEmail": "", "password": ""},
                aliases=[{"email": "a@example.com"}],
            )

            resp = client.post(
                "/api/config/alias-test",
                json={"sourceId": "qa-static", "useDraftConfig": False},
            )

        self.assertEqual(resp.status_code, 200)
        _, kwargs = automation_service_cls.call_args
        self.assertEqual(
            kwargs["policy"],
            AliasAutomationTestPolicy(
                fresh_service_account=True,
                persist_state=False,
                minimum_alias_count=3,
                capture_enabled=True,
            ),
        )
        self.assertEqual(
            kwargs["context"],
            AliasProviderBootstrapContext(
                task_id="alias-test",
                purpose="automation_test",
                runtime_builder=_default_alias_test_runtime_builder,
                test_policy=AliasAutomationTestPolicy(
                    fresh_service_account=True,
                    persist_state=False,
                    minimum_alias_count=3,
                    capture_enabled=True,
                ),
            ),
        )

    def test_update_config_skips_empty_write_only_cloudmail_admin_password(self):
        client = TestClient(app)

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.set_many"
        ) as set_many:
            resp = client.put(
                "/api/config",
                json={"data": {"cloudmail_admin_password": "", "mail_provider": "cloudmail"}},
            )

        self.assertEqual(resp.status_code, 200)
        stored_payload = set_many.call_args.args[0]
        self.assertEqual(stored_payload, {"mail_provider": "cloudmail"})

    def test_cloudmail_team_account_config_keys_are_supported(self):
        client = TestClient(app)

        with patch("api.config.config_store.set_many") as set_many:
            resp = client.put(
                "/api/config",
                json={
                    "data": {
                        "cloudmail_team_account_email": "manager@example.com",
                        "cloudmail_team_account_password": "team-secret",
                        "cloudmail_team_otp_mailbox_email": "admin@example.com",
                    }
                },
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            set_many.call_args.args[0],
            {
                "cloudmail_team_account_email": "manager@example.com",
                "cloudmail_team_account_password": "team-secret",
                "cloudmail_team_otp_mailbox_email": "admin@example.com",
            },
        )

        with patch(
            "api.config.config_store.get_all",
            return_value={
                "cloudmail_team_account_email": "manager@example.com",
                "cloudmail_team_account_password": "team-secret",
                "cloudmail_team_otp_mailbox_email": "admin@example.com",
            },
        ):
            get_resp = client.get("/api/config")

        self.assertEqual(get_resp.status_code, 200)
        body = get_resp.json()
        self.assertEqual(body["cloudmail_team_account_email"], "manager@example.com")
        self.assertEqual(body["cloudmail_team_account_password"], "")
        self.assertEqual(body["cloudmail_team_otp_mailbox_email"], "admin@example.com")

    def test_alias_generation_test_api_returns_real_vend_probe_fields(self):
        client = TestClient(app)

        vend_steps = [
            {"code": "register_submit", "label": "注册表单提交", "status": "ok"},
            {
                "code": "fetch_confirmation_mail",
                "label": "查找确认邮件",
                "status": "ok",
            },
            {"code": "open_confirmation_link", "label": "打开确认链接", "status": "ok"},
            {"code": "list_aliases", "label": "列出现有别名", "status": "ok"},
            {
                "code": "create_aliases",
                "label": "创建别名",
                "status": "ok",
                "detail": "已补齐 2 个别名",
            },
        ]
        vend_capture_summary = [
            {
                "name": "confirmation",
                "url": "https://www.vend.email/auth/confirmation?confirmation_token=abc123",
                "method": "GET",
                "request_body_excerpt": "confirmation_token=abc123",
                "response_body_excerpt": '{"ok":true}',
                "response_status": 200,
                "captured_at": "2026-04-19T12:00:00+08:00",
            }
        ]
        vend_aliases = [
            {"email": "alias-001@vend.example"},
            {"email": "alias-002@vend.example"},
            {"email": "alias-003@vend.example"},
        ]
        vend_account = {
            "realMailboxEmail": "real@example.com",
            "serviceEmail": "service-account@vend.example",
            "password": "vend-secret",
            "username": "vend-demo",
        }
        vend_failure = {"stageCode": "", "stageLabel": "", "reason": ""}

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.get_all", return_value={}
        ), patch(
            "api.config.normalize_cloudmail_alias_pool_config",
            return_value={
                "enabled": True,
                "task_id": "alias-test",
                "sources": [
                    {
                        "id": "vend-1",
                        "type": "vend_email",
                        "mailbox_email": "real@example.com",
                        "vendor": "vend",
                    }
                ],
            },
        ), patch("api.config.AliasAutomationTestService") as service_cls:
            service = service_cls.return_value
            service.run.return_value.ok = True
            service.run.return_value.source_id = "vend-1"
            service.run.return_value.source_type = "vend_email"
            service.run.return_value.alias_email = "real@example.com"
            service.run.return_value.real_mailbox_email = "real@example.com"
            service.run.return_value.service_email = "alias-001@vend.example"
            service.run.return_value.capture_summary = vend_capture_summary
            service.run.return_value.steps = vend_steps
            service.run.return_value.account = vend_account
            service.run.return_value.aliases = vend_aliases
            service.run.return_value.current_stage = {
                "code": "aliases_ready",
                "label": "别名预览已生成",
            }
            service.run.return_value.stages = vend_steps
            service.run.return_value.failure = vend_failure
            service.run.return_value.logs = []
            service.run.return_value.error = ""

            resp = client.post(
                "/api/config/alias-test",
                json={
                    "sourceId": "vend-1",
                    "useDraftConfig": True,
                    "config": {
                        "cloudmail_alias_enabled": True,
                        "sources": [
                            {
                                "id": "vend-1",
                                "type": "vend_email",
                                "mailbox_email": "real@example.com",
                                "vendor": "vend",
                            }
                        ],
                    },
                },
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["sourceId"], "vend-1")
        self.assertEqual(body["sourceType"], "vend_email")
        self.assertEqual(body["serviceEmail"], "alias-001@vend.example")
        self.assertEqual(
            body["accountIdentity"],
            {
                "serviceAccountEmail": "alias-001@vend.example",
                "confirmationInboxEmail": "real@example.com",
                "realMailboxEmail": "real@example.com",
                "servicePassword": "vend-secret",
                "username": "vend-demo",
            },
        )
        self.assertEqual(body["account"], vend_account)
        self.assertEqual(body["aliases"], vend_aliases)
        self.assertEqual(
            body["currentStage"],
            {"code": "aliases_ready", "label": "别名预览已生成"},
        )
        self.assertEqual(body["stages"], vend_steps)
        self.assertEqual(body["failure"], vend_failure)
        self.assertEqual(body["aliasEmail"], "alias-001@vend.example")
        self.assertIn("steps", body)
        self.assertIsInstance(body["steps"], list)
        self.assertIn("captureSummary", body)
        self.assertIsInstance(body["captureSummary"], list)
        self.assertEqual(body["captureSummary"][0]["kind"], "confirmation")
        self.assertEqual(body["captureSummary"][0]["requestSummary"]["method"], "GET")
        self.assertEqual(body["captureSummary"][0]["responseSummary"]["response_status"], 200)

    def test_alias_generation_test_api_sanitizes_mailbox_verification_capture_summary(self):
        client = TestClient(app)

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.get_all", return_value={}
        ), patch(
            "api.config.normalize_cloudmail_alias_pool_config",
            return_value={
                "enabled": True,
                "task_id": "alias-test",
                "sources": [
                    {
                        "id": "vend-1",
                        "type": "vend_email",
                        "mailbox_email": "real@example.com",
                    }
                ],
            },
        ), patch("api.config.AliasAutomationTestService") as service_cls:
            service = service_cls.return_value
            service.run.return_value.ok = False
            service.run.return_value.source_id = "vend-1"
            service.run.return_value.source_type = "vend_email"
            service.run.return_value.alias_email = ""
            service.run.return_value.real_mailbox_email = "real@example.com"
            service.run.return_value.service_email = ""
            service.run.return_value.capture_summary = [
                {
                    "name": "mailbox_verification",
                    "method": "GET",
                    "url": "https://mailbox.example/base?token=abc123&confirmation_token=def456&code=ghi789",
                    "request_body_excerpt": "",
                    "response_body_excerpt": "https://vend.example/auth/confirmation?confirmation_token=abc123&code=xyz789",
                }
            ]
            service.run.return_value.steps = []
            service.run.return_value.logs = []
            service.run.return_value.error = "vend.email session bootstrap failed"

            resp = client.post(
                "/api/config/alias-test",
                json={"sourceId": "vend-1", "useDraftConfig": False},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        capture = body["captureSummary"][0]
        self.assertEqual(capture["request_summary"], "mailbox verification request")
        self.assertEqual(capture["response_summary"], "mailbox verification result")
        self.assertNotIn("token=abc123", capture["url"])
        self.assertNotIn("confirmation_token=def456", capture["url"])
        self.assertNotIn("code=ghi789", capture["url"])
        self.assertIn("token=[REDACTED]", capture["url"])
        self.assertIn("confirmation_token=[REDACTED]", capture["url"])
        self.assertIn("code=[REDACTED]", capture["url"])
        self.assertNotIn("confirmation_token", capture["response_body_excerpt"])
        self.assertNotIn("abc123", capture["response_body_excerpt"])
        self.assertNotIn("xyz789", capture["response_body_excerpt"])
        self.assertEqual(capture["kind"], "mailbox_verification")
        self.assertEqual(capture["requestSummary"], "mailbox verification request")
        self.assertEqual(capture["responseSummary"], "mailbox verification result")

    def test_alias_generation_test_api_uses_draft_config_when_requested(self):
        client = TestClient(app)

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.get_all", return_value={}
        ), patch(
            "api.config.normalize_cloudmail_alias_pool_config",
            return_value={
                "enabled": True,
                "task_id": "alias-test",
                "sources": [
                    {
                        "id": "simple-1",
                        "type": "simple_generator",
                        "prefix": "msiabc.",
                        "suffix": "@manyme.com",
                        "mailbox_email": "real@example.com",
                        "count": 1,
                    }
                ],
            },
        ) as normalize_config, patch(
            "api.config.AliasAutomationTestService"
        ) as service_cls:
            service = service_cls.return_value
            service.run.return_value.ok = True
            service.run.return_value.source_id = "simple-1"
            service.run.return_value.source_type = "simple_generator"
            service.run.return_value.alias_email = "msiabc.123@manyme.com"
            service.run.return_value.real_mailbox_email = "real@example.com"
            service.run.return_value.service_email = ""
            service.run.return_value.capture_summary = []
            service.run.return_value.steps = []
            service.run.return_value.logs = []
            service.run.return_value.error = ""

            resp = client.post(
                "/api/config/alias-test",
                json={
                    "sourceId": "simple-1",
                    "useDraftConfig": True,
                    "config": {
                        "cloudmail_alias_enabled": True,
                        "sources": [
                            {
                                "id": "simple-1",
                                "type": "simple_generator",
                                "prefix": "msiabc.",
                                "suffix": "@manyme.com",
                                "mailbox_email": "real@example.com",
                                "count": 1,
                            }
                        ],
                    },
                },
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["sourceId"], "simple-1")
        self.assertEqual(body["aliasEmail"], "msiabc.123@manyme.com")
        normalize_config.assert_called_once_with(
            {
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "simple-1",
                        "type": "simple_generator",
                        "prefix": "msiabc.",
                        "suffix": "@manyme.com",
                        "mailbox_email": "real@example.com",
                        "count": 1,
                    }
                ],
            },
            task_id="alias-test",
        )

    def test_alias_generation_test_api_returns_structured_error(self):
        client = TestClient(app)

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.get_all", return_value={}
        ), patch(
            "api.config.normalize_cloudmail_alias_pool_config",
            return_value={"enabled": False, "task_id": "alias-test", "sources": []},
        ), patch("api.config.AliasAutomationTestService") as service_cls:
            service = service_cls.return_value
            service.run.return_value.ok = False
            service.run.return_value.source_id = "missing"
            service.run.return_value.source_type = ""
            service.run.return_value.alias_email = ""
            service.run.return_value.real_mailbox_email = ""
            service.run.return_value.service_email = ""
            service.run.return_value.capture_summary = []
            service.run.return_value.steps = []
            service.run.return_value.logs = []
            service.run.return_value.error = "source 'missing' not found"

            resp = client.post(
                "/api/config/alias-test",
                json={"sourceId": "missing", "useDraftConfig": False},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "source 'missing' not found")

    def test_alias_generation_test_api_returns_structured_failure_when_provider_raises(self):
        client = TestClient(app)

        provider = mock.Mock()
        provider.run_alias_generation_test.side_effect = RuntimeError("alias preview unavailable")

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.get_all",
            return_value={
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "broken-source",
                        "type": "static_list",
                        "emails": ["a@example.com"],
                    }
                ],
            },
        ), patch(
            "core.alias_pool.automation_test.AliasProviderBootstrap.build",
            return_value=provider,
        ):
            resp = client.post(
                "/api/config/alias-test",
                json={"sourceId": "broken-source", "useDraftConfig": False},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["sourceId"], "broken-source")
        self.assertEqual(body["sourceType"], "static_list")
        self.assertEqual(body["error"], "alias preview unavailable")
        self.assertEqual(
            body["failure"],
            {
                "stageCode": "run_alias_generation_test",
                "stageLabel": "",
                "reason": "alias preview unavailable",
            },
        )

    def test_alias_generation_test_api_uses_saved_config_when_draft_disabled(self):
        client = TestClient(app)
        saved_config = {
            "cloudmail_alias_enabled": True,
            "sources": [
                {
                    "id": "saved-source",
                    "type": "static_list",
                    "emails": ["a@example.com"],
                    "mailbox_email": "real@example.com",
                }
            ],
        }

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.get_all", return_value=saved_config
        ), patch(
            "api.config.normalize_cloudmail_alias_pool_config",
            return_value={
                "enabled": True,
                "task_id": "alias-test",
                "sources": saved_config["sources"],
            },
        ) as normalize_config, patch(
            "api.config.AliasAutomationTestService"
        ) as service_cls:
            service = service_cls.return_value
            service.run.return_value.ok = True
            service.run.return_value.source_id = "saved-source"
            service.run.return_value.source_type = "static_list"
            service.run.return_value.alias_email = "a@example.com"
            service.run.return_value.real_mailbox_email = "real@example.com"
            service.run.return_value.service_email = ""
            service.run.return_value.capture_summary = []
            service.run.return_value.steps = []
            service.run.return_value.logs = []
            service.run.return_value.error = ""

            resp = client.post(
                "/api/config/alias-test",
                json={
                    "sourceId": "saved-source",
                    "useDraftConfig": False,
                    "config": {
                        "sources": [
                            {
                                "id": "draft-source",
                                "type": "static_list",
                                "emails": ["draft@example.com"],
                                "mailbox_email": "draft-real@example.com",
                            }
                        ]
                    },
                },
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["sourceId"], "saved-source")
        self.assertEqual(body["aliasEmail"], "a@example.com")
        normalize_config.assert_called_once_with(saved_config, task_id="alias-test")

    def test_alias_generation_probe_service_uses_fresh_vend_state_for_alias_test(self):
        persistent_state_store = mock.Mock()
        persistent_state_store.load.return_value = VendEmailServiceState(
            state_key="vend-email-state-key",
            service_email="stale-service@example.com",
            mailbox_email="stale-mailbox@example.com",
            service_password="stale-pass",
            known_aliases=[
                "stale-001@serf.me",
                "stale-002@serf.me",
                "stale-003@serf.me",
            ],
            current_stage={"code": "aliases_ready", "label": "别名预览已生成"},
            stage_history=[
                {"code": "aliases_ready", "label": "别名预览已生成", "status": "completed", "detail": "预览共 3 个别名"}
            ],
            last_capture_summary=[
                VendEmailCaptureRecord(
                    name="stale_capture",
                    url="https://vend.example/stale",
                    method="GET",
                    request_headers_whitelist={},
                    request_body_excerpt="",
                    response_status=200,
                    response_body_excerpt="stale",
                    captured_at="2026-04-17T01:00:00+08:00",
                )
            ],
        )
        runtime = mock.Mock()
        runtime.restore_session.return_value = True
        runtime.login.return_value = False
        runtime.register.return_value = False
        runtime.list_aliases.return_value = ["fresh-001@serf.me"]
        runtime.create_aliases.side_effect = [["fresh-002@serf.me", "fresh-003@serf.me"]]
        runtime.capture_summary.return_value = [
            VendEmailCaptureRecord(
                name="create_forwarder",
                url="https://vend.example/forwarders",
                method="POST",
                request_headers_whitelist={"content-type": "application/x-www-form-urlencoded"},
                request_body_excerpt="forwarder[domain_id]=42",
                response_status=200,
                response_body_excerpt='{"email":"fresh-001@serf.me"}',
                captured_at="2026-04-17T01:11:00+08:00",
            )
        ]

        service = AliasSourceProbeService(
            state_store_factory=lambda current_task_id, current_source_id: persistent_state_store,
            runtime_builder=lambda source: runtime,
        )

        with patch("core.alias_pool.vend_provider.build_service_email", return_value="fresh-service@example.com"), patch(
            "core.alias_pool.vend_provider.build_service_password", return_value="fresh-pass"
        ):
            result = service.probe(
                pool_config={
                    "enabled": True,
                    "task_id": "alias-test",
                    "sources": [
                        {
                            "id": "vend-email-primary",
                            "type": "vend_email",
                            "register_url": "https://vend.example/register",
                            "mailbox_base_url": "https://mailbox.example/base",
                            "mailbox_email": "real@example.com",
                            "mailbox_password": "secret-pass",
                            "cloudmail_domain": "example.com",
                            "alias_domain": "serf.me",
                            "alias_domain_id": "42",
                            "alias_count": 1,
                            "state_key": "vend-email-state-key",
                        }
                    ],
                },
                source_id="vend-email-primary",
                task_id="alias-test",
            )

        self.assertEqual(
            result,
            AliasProbeResult(
                ok=True,
                source_id="vend-email-primary",
                source_type="vend_email",
                alias_email="fresh-001@serf.me",
                real_mailbox_email="real@example.com",
                service_email="fresh-service@example.com",
                account={
                    "realMailboxEmail": "real@example.com",
                    "serviceEmail": "fresh-service@example.com",
                    "password": "fresh-pass",
                    "username": "fresh-service",
                },
                aliases=[
                    {"email": "fresh-001@serf.me"},
                    {"email": "fresh-002@serf.me"},
                    {"email": "fresh-003@serf.me"},
                ],
                capture_summary=[
                    {
                        "name": "create_forwarder",
                        "url": "https://vend.example/forwarders",
                        "method": "POST",
                        "request_headers_whitelist": {"content-type": "application/x-www-form-urlencoded"},
                        "request_body_excerpt": "forwarder[domain_id]=42",
                        "response_status": 200,
                        "response_body_excerpt": '{"email":"fresh-001@serf.me"}',
                        "captured_at": "2026-04-17T01:11:00+08:00",
                    }
                ],
                steps=["load_source", "acquire_alias"],
                current_stage={"code": "aliases_ready", "label": "别名预览已生成"},
                stages=[
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
                failure={"stageCode": "", "stageLabel": "", "reason": ""},
                logs=[],
                error="",
            ),
        )
        persistent_state_store.load.assert_not_called()
        persistent_state_store.save.assert_not_called()

    def test_alias_generation_probe_service_forces_three_aliases_for_alias_test_run(self):
        runtime = mock.Mock()
        runtime.restore_session.return_value = True
        runtime.login.return_value = False
        runtime.register.return_value = False
        runtime.list_aliases.return_value = ["fresh-001@serf.me"]
        runtime.create_aliases.side_effect = [["fresh-002@serf.me", "fresh-003@serf.me"]]
        runtime.capture_summary.return_value = []

        service = AliasSourceProbeService(runtime_builder=lambda source: runtime)

        with patch("core.alias_pool.vend_provider.build_service_email", return_value="fresh-service@example.com"), patch(
            "core.alias_pool.vend_provider.build_service_password", return_value="fresh-pass"
        ):
            result = service.probe(
                pool_config={
                    "enabled": True,
                    "task_id": "alias-test",
                    "sources": [
                        {
                            "id": "vend-email-primary",
                            "type": "vend_email",
                            "register_url": "https://vend.example/register",
                            "cloudmail_domain": "example.com",
                            "mailbox_email": "real@example.com",
                            "alias_domain": "serf.me",
                            "alias_domain_id": "42",
                            "alias_count": 1,
                            "state_key": "vend-email-state-key",
                        }
                    ],
                },
                source_id="vend-email-primary",
                task_id="alias-test",
            )

        self.assertEqual(result.alias_email, "fresh-001@serf.me")
        self.assertEqual(
            result.aliases,
            [
                {"email": "fresh-001@serf.me"},
                {"email": "fresh-002@serf.me"},
                {"email": "fresh-003@serf.me"},
            ],
        )
        runtime.create_aliases.assert_called_once()
        create_args = runtime.create_aliases.call_args.args
        self.assertEqual(create_args[2], 2)
        self.assertEqual(
            result.stages,
            [
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

    def test_alias_generation_probe_service_no_longer_depends_on_alias_test_task_id(self):
        service = AliasSourceProbeService(
            runtime_builder=mock.Mock(),
            state_store_factory=mock.Mock(),
        )

        with patch("core.alias_pool.automation_test.AliasAutomationTestService") as automation_cls:
            automation_cls.return_value.run.side_effect = ValueError("source 'vend-email-primary' not found")

            with self.assertRaisesRegex(ValueError, "source 'vend-email-primary' not found"):
                service.probe(
                    pool_config={"enabled": True, "sources": []},
                    source_id="vend-email-primary",
                    task_id="manual-debug-run",
                )

        _, kwargs = automation_cls.call_args
        self.assertEqual(
            kwargs["policy"],
            AliasAutomationTestPolicy(
                fresh_service_account=True,
                persist_state=False,
                minimum_alias_count=3,
                capture_enabled=True,
            ),
        )
        self.assertEqual(
            kwargs["context"],
            AliasProviderBootstrapContext(
                task_id="manual-debug-run",
                purpose="automation_test",
                runtime_builder=service._runtime_builder,
                state_store_factory=service._state_store_factory,
                test_policy=AliasAutomationTestPolicy(
                    fresh_service_account=True,
                    persist_state=False,
                    minimum_alias_count=3,
                    capture_enabled=True,
                ),
            ),
        )

    def test_alias_generation_test_api_supports_alias_email_stage_codes(self):
        client = TestClient(app)

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.get_all",
            return_value={
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "alias-email-primary",
                        "type": "alias_email",
                        "alias_count": 3,
                        "state_key": "alias-email-primary",
                        "confirmation_inbox": {"provider": "cloudmail", "match_email": "real@example.com"},
                        "provider_config": {"login_url": "https://alias.email/users/login/"},
                    }
                ],
            },
        ), patch("api.config.AliasAutomationTestService") as service_cls:
            service_cls.return_value.run.return_value = AliasProbeResult(
                ok=True,
                source_id="alias-email-primary",
                source_type="alias_email",
                alias_email="alpha@alias.email",
                real_mailbox_email="real@example.com",
                service_email="real@example.com",
                account={"realMailboxEmail": "real@example.com", "serviceEmail": "real@example.com", "password": ""},
                aliases=[
                    {"email": "alpha@alias.email"},
                    {"email": "beta@alias.email"},
                    {"email": "gamma@alias.email"},
                ],
                current_stage={"code": "consume_magic_link", "label": "消费魔法链接"},
                stages=[
                    {"code": "request_magic_link", "label": "请求魔法链接", "status": "completed"},
                    {"code": "consume_magic_link", "label": "消费魔法链接", "status": "completed"},
                    {"code": "discover_alias_domains", "label": "发现可用域名", "status": "completed"},
                ],
            )

            response = client.post("/api/config/alias-test", json={"sourceId": "alias-email-primary", "useDraftConfig": False})

        body = response.json()
        self.assertEqual(body["sourceType"], "alias_email")
        self.assertEqual(body["stages"][0]["code"], "request_magic_link")
        self.assertEqual(body["stages"][1]["code"], "consume_magic_link")

    def test_alias_generation_test_api_supports_secureinseconds_forwarding_stage_codes(self):
        client = TestClient(app)

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.get_all",
            return_value={
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "secureinseconds-primary",
                        "type": "secureinseconds",
                        "alias_count": 3,
                        "state_key": "secureinseconds-primary",
                        "confirmation_inbox": {
                            "provider": "cloudmail",
                            "account_email": "real@example.com",
                            "account_password": "mail-pass",
                            "match_email": "admin@cxwsss.online",
                        },
                        "provider_config": {
                            "register_url": "https://alias.secureinseconds.com/auth/register",
                            "login_url": "https://alias.secureinseconds.com/auth/signin",
                        },
                    }
                ],
            },
        ), patch("api.config.AliasAutomationTestService") as service_cls:
            service_cls.return_value.run.return_value = AliasProbeResult(
                ok=True,
                source_id="secureinseconds-primary",
                source_type="secureinseconds",
                alias_email="svcsecur02-rnd1@alias.secureinseconds.com",
                real_mailbox_email="admin@cxwsss.online",
                service_email="svcsecure01@cxwsss.online",
                account={
                    "realMailboxEmail": "admin@cxwsss.online",
                    "serviceEmail": "svcsecure01@cxwsss.online",
                    "password": "SisA1@TestPass",
                    "username": "svcsecure01",
                },
                aliases=[
                    {"email": "existing@alias.secureinseconds.com"},
                    {"email": "svcsecur02-rnd1@alias.secureinseconds.com"},
                    {"email": "svcsecur03-rnd2@alias.secureinseconds.com"},
                ],
                current_stage={"code": "aliases_ready", "label": "别名预览已生成"},
                stages=[
                    {"code": "session_ready", "label": "会话已就绪", "status": "completed"},
                    {"code": "verify_forwarding_email", "label": "验证转发邮箱", "status": "completed"},
                    {"code": "discover_alias_domains", "label": "发现可用域名", "status": "completed"},
                    {"code": "list_aliases", "label": "列出现有别名", "status": "completed"},
                    {"code": "create_aliases", "label": "创建别名", "status": "completed"},
                ],
            )

            response = client.post("/api/config/alias-test", json={"sourceId": "secureinseconds-primary", "useDraftConfig": False})

        body = response.json()
        self.assertEqual(body["sourceType"], "secureinseconds")
        self.assertEqual(body["accountIdentity"]["serviceAccountEmail"], "svcsecure01@cxwsss.online")
        self.assertEqual(body["accountIdentity"]["realMailboxEmail"], "admin@cxwsss.online")
        self.assertEqual(body["stages"][1]["code"], "verify_forwarding_email")
        self.assertEqual(len(body["aliases"]), 3)

    def test_alias_generation_test_api_keeps_account_identity_compatibility_for_interactive_provider(self):
        client = TestClient(app)

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.get_all",
            return_value={
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "simplelogin-primary",
                        "type": "simplelogin",
                        "alias_count": 3,
                        "state_key": "simplelogin-primary",
                        "provider_config": {
                            "site_url": "https://simplelogin.io/",
                            "accounts": [{"email": "fust@fst.cxwsss.online", "label": "fust"}],
                        },
                    }
                ],
            },
        ), patch("api.config.AliasAutomationTestService") as service_cls:
            service_cls.return_value.run.return_value = AliasProbeResult(
                ok=True,
                source_id="simplelogin-primary",
                source_type="simplelogin",
                alias_email="sisyrun0419a.relearn763@aleeas.com",
                real_mailbox_email="fust@fst.cxwsss.online",
                service_email="fust@fst.cxwsss.online",
                account={
                    "realMailboxEmail": "fust@fst.cxwsss.online",
                    "serviceEmail": "fust@fst.cxwsss.online",
                    "password": "fust@fst.cxwsss.online",
                    "username": "fust",
                },
                aliases=[
                    {"email": "sisyrun0419a.relearn763@aleeas.com"},
                    {"email": "sisyrun0419b.onion376@simplelogin.com"},
                    {"email": "sisyrun0419c.skies135@slmails.com"},
                ],
            )

            response = client.post("/api/config/alias-test", json={"sourceId": "simplelogin-primary", "useDraftConfig": False})

        body = response.json()
        self.assertEqual(body["accountIdentity"]["serviceAccountEmail"], "fust@fst.cxwsss.online")
        self.assertEqual(body["accountIdentity"]["servicePassword"], "fust@fst.cxwsss.online")
        self.assertEqual(body["accountIdentity"]["username"], "fust")
        self.assertEqual(len(body["aliases"]), 3)


if __name__ == "__main__":
    unittest.main()
