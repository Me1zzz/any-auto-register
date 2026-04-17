import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app


class AliasGenerationApiTests(unittest.TestCase):
    def test_alias_generation_test_api_returns_real_vend_probe_fields(self):
        client = TestClient(app)

        vend_steps = [
            {"phase": "probe", "result": "ok"},
            {"phase": "capture", "result": "ok"},
        ]
        vend_capture_summary = [{"entries": 2}]

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
        self.assertIn("steps", body)
        self.assertIsInstance(body["steps"], list)
        self.assertIn("captureSummary", body)
        self.assertIsInstance(body["captureSummary"], list)

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


if __name__ == "__main__":
    unittest.main()
