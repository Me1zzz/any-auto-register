import unittest
from unittest import mock
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from core.alias_pool.config import normalize_cloudmail_alias_pool_config
from core.alias_pool.probe import AliasProbeResult, AliasSourceProbeService
from core.alias_pool.vend_email_state import VendEmailCaptureRecord, VendEmailServiceState


class AliasGenerationApiTests(unittest.TestCase):
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
                    "alias_domain": "serf.me",
                    "alias_domain_id": "42",
                    "alias_count": 4,
                    "state_key": "vend-email-primary",
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

    def test_get_config_decodes_sources_json_string(self):
        client = TestClient(app)

        with patch("core.config_store.config_store.get", return_value=""), patch(
            "api.config.config_store.get_all",
            return_value={
                "cloudmail_admin_password": "secret-pass",
                "sources": (
                    '[{"id":"vend-1","type":"vend_email","mailbox_email":"real@example.com",'
                    '"mailbox_password":"secret-pass","alias_domain_id":"42","alias_count":2}]'
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
                    "alias_count": 2,
                    "state_key": "vend-1",
                    "alias_domain_id": "42",
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
                "mailbox_email": "real@example.com",
                "mailbox_password": "secret-pass",
                "mailbox_base_url": "https://mailbox.example/base",
                "register_url": "https://vend.example/register",
                "alias_count": 2,
                "state_key": "vend-1-state",
                "alias_domain_id": "42",
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
            '[{"id": "vend-1", "type": "vend_email", "alias_count": 2, "state_key": "vend-1-state"}]',
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
        vend_capture_summary = [{"entries": 2}]
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
        ), patch("api.config.AliasSourceProbeService") as probe_service_cls:
            probe_service = probe_service_cls.return_value
            probe_service.probe.return_value.ok = True
            probe_service.probe.return_value.source_id = "vend-1"
            probe_service.probe.return_value.source_type = "vend_email"
            probe_service.probe.return_value.alias_email = "real@example.com"
            probe_service.probe.return_value.real_mailbox_email = "real@example.com"
            probe_service.probe.return_value.service_email = "alias-001@vend.example"
            probe_service.probe.return_value.capture_summary = vend_capture_summary
            probe_service.probe.return_value.steps = vend_steps
            probe_service.probe.return_value.account = vend_account
            probe_service.probe.return_value.aliases = vend_aliases
            probe_service.probe.return_value.current_stage = {
                "code": "aliases_ready",
                "label": "别名预览已生成",
            }
            probe_service.probe.return_value.stages = vend_steps
            probe_service.probe.return_value.failure = vend_failure
            probe_service.probe.return_value.logs = []
            probe_service.probe.return_value.error = ""

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
        ), patch("api.config.AliasSourceProbeService") as probe_service_cls:
            probe_service = probe_service_cls.return_value
            probe_service.probe.return_value.ok = False
            probe_service.probe.return_value.source_id = "vend-1"
            probe_service.probe.return_value.source_type = "vend_email"
            probe_service.probe.return_value.alias_email = ""
            probe_service.probe.return_value.real_mailbox_email = "real@example.com"
            probe_service.probe.return_value.service_email = ""
            probe_service.probe.return_value.capture_summary = [
                {
                    "name": "mailbox_verification",
                    "method": "GET",
                    "url": "https://mailbox.example/base?token=abc123&confirmation_token=def456&code=ghi789",
                    "request_body_excerpt": "",
                    "response_body_excerpt": "https://vend.example/auth/confirmation?confirmation_token=abc123&code=xyz789",
                }
            ]
            probe_service.probe.return_value.steps = []
            probe_service.probe.return_value.logs = []
            probe_service.probe.return_value.error = "vend.email session bootstrap failed"

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
            "api.config.AliasSourceProbeService"
        ) as probe_service_cls:
            probe_service = probe_service_cls.return_value
            probe_service.probe.return_value.ok = True
            probe_service.probe.return_value.source_id = "simple-1"
            probe_service.probe.return_value.source_type = "simple_generator"
            probe_service.probe.return_value.alias_email = "msiabc.123@manyme.com"
            probe_service.probe.return_value.real_mailbox_email = "real@example.com"
            probe_service.probe.return_value.service_email = ""
            probe_service.probe.return_value.capture_summary = []
            probe_service.probe.return_value.steps = []
            probe_service.probe.return_value.logs = []
            probe_service.probe.return_value.error = ""

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
        ), patch("api.config.AliasSourceProbeService") as probe_service_cls:
            probe_service = probe_service_cls.return_value
            probe_service.probe.return_value.ok = False
            probe_service.probe.return_value.source_id = "missing"
            probe_service.probe.return_value.source_type = ""
            probe_service.probe.return_value.alias_email = ""
            probe_service.probe.return_value.real_mailbox_email = ""
            probe_service.probe.return_value.service_email = ""
            probe_service.probe.return_value.capture_summary = []
            probe_service.probe.return_value.steps = []
            probe_service.probe.return_value.logs = []
            probe_service.probe.return_value.error = "source 'missing' not found"

            resp = client.post(
                "/api/config/alias-test",
                json={"sourceId": "missing", "useDraftConfig": False},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "source 'missing' not found")

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
            "api.config.AliasSourceProbeService"
        ) as probe_service_cls:
            probe_service = probe_service_cls.return_value
            probe_service.probe.return_value.ok = True
            probe_service.probe.return_value.source_id = "saved-source"
            probe_service.probe.return_value.source_type = "static_list"
            probe_service.probe.return_value.alias_email = "a@example.com"
            probe_service.probe.return_value.real_mailbox_email = "real@example.com"
            probe_service.probe.return_value.service_email = ""
            probe_service.probe.return_value.capture_summary = []
            probe_service.probe.return_value.steps = []
            probe_service.probe.return_value.logs = []
            probe_service.probe.return_value.error = ""

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

        with patch("core.alias_pool.vend_email_service._build_service_email", return_value="fresh-service@example.com"), patch(
            "core.alias_pool.vend_email_service._build_service_password", return_value="fresh-pass"
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
                real_mailbox_email="fresh-service@example.com",
                service_email="fresh-service@example.com",
                account={
                    "realMailboxEmail": "fresh-service@example.com",
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

        with patch("core.alias_pool.vend_email_service._build_service_email", return_value="fresh-service@example.com"), patch(
            "core.alias_pool.vend_email_service._build_service_password", return_value="fresh-pass"
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


if __name__ == "__main__":
    unittest.main()
