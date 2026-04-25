import unittest
from unittest import mock

from platforms.chatgpt.chatgpt_registration_mode_adapter import (
    CODEX_GUI_VARIANT_DEFAULT,
    CODEX_GUI_VARIANT_OFFICIAL_SIGNUP,
    CHATGPT_REGISTRATION_MODE_ACCESS_TOKEN_ONLY,
    CHATGPT_REGISTRATION_MODE_CODEX_GUI,
    CHATGPT_REGISTRATION_MODE_REFRESH_TOKEN,
    ChatGPTRegistrationContext,
    build_chatgpt_registration_mode_adapter,
    resolve_codex_gui_variant,
    resolve_chatgpt_registration_mode,
)


class ChatGPTRegistrationModeAdapterTests(unittest.TestCase):
    def test_resolve_defaults_to_refresh_token_mode(self):
        self.assertEqual(
            resolve_chatgpt_registration_mode({}),
            CHATGPT_REGISTRATION_MODE_REFRESH_TOKEN,
        )

    def test_resolve_supports_boolean_no_rt_flag(self):
        self.assertEqual(
            resolve_chatgpt_registration_mode(
                {"chatgpt_has_refresh_token_solution": False}
            ),
            CHATGPT_REGISTRATION_MODE_ACCESS_TOKEN_ONLY,
        )

    def test_resolve_supports_codex_gui_mode(self):
        self.assertEqual(
            resolve_chatgpt_registration_mode({"chatgpt_registration_mode": "codex_gui"}),
            CHATGPT_REGISTRATION_MODE_CODEX_GUI,
        )

    def test_resolve_uses_gui_default_executor_as_codex_gui_fallback(self):
        self.assertEqual(
            resolve_chatgpt_registration_mode({"default_executor": "gui_control"}),
            CHATGPT_REGISTRATION_MODE_CODEX_GUI,
        )

    def test_resolve_uses_cloudmail_team_account_email_as_codex_gui_override(self):
        self.assertEqual(
            resolve_chatgpt_registration_mode(
                {
                    "chatgpt_registration_mode": "refresh_token",
                    "cloudmail_team_account_email": "manager@example.com",
                }
            ),
            CHATGPT_REGISTRATION_MODE_CODEX_GUI,
        )

    def test_resolve_codex_gui_variant_auto_official_for_cloudmail_team_account_email(self):
        resolution = resolve_codex_gui_variant(
            {"cloudmail_team_account_email": "manager@example.com"}
        )

        self.assertEqual(resolution.requested_variant, CODEX_GUI_VARIANT_OFFICIAL_SIGNUP)
        self.assertEqual(resolution.effective_variant, CODEX_GUI_VARIANT_OFFICIAL_SIGNUP)
        self.assertEqual(resolution.fallback_reason, "")

    def test_resolve_codex_gui_variant_requires_explicit_request_and_team_config(self):
        resolution = resolve_codex_gui_variant(
            {
                "codex_gui_variant": "official-signup",
                "chatgpt_team_member_account": {
                    "email": "owner@example.com",
                    "credential": "team-token",
                },
                "chatgpt_team_workspace_id": "ws-demo",
            }
        )

        self.assertEqual(resolution.requested_variant, CODEX_GUI_VARIANT_OFFICIAL_SIGNUP)
        self.assertEqual(resolution.effective_variant, CODEX_GUI_VARIANT_OFFICIAL_SIGNUP)
        self.assertEqual(resolution.fallback_reason, "")

    def test_resolve_codex_gui_variant_accepts_cloudmail_team_account_email(self):
        resolution = resolve_codex_gui_variant(
            {
                "codex_gui_variant": "official-signup",
                "cloudmail_team_account_email": "manager@example.com",
            }
        )

        self.assertEqual(resolution.requested_variant, CODEX_GUI_VARIANT_OFFICIAL_SIGNUP)
        self.assertEqual(resolution.effective_variant, CODEX_GUI_VARIANT_OFFICIAL_SIGNUP)
        self.assertEqual(resolution.fallback_reason, "")

    def test_resolve_codex_gui_variant_falls_back_when_team_config_missing(self):
        resolution = resolve_codex_gui_variant({"codex_gui_variant": "official_signup"})

        self.assertEqual(resolution.requested_variant, CODEX_GUI_VARIANT_OFFICIAL_SIGNUP)
        self.assertEqual(resolution.effective_variant, CODEX_GUI_VARIANT_DEFAULT)
        self.assertEqual(
            resolution.fallback_reason,
            "missing_or_incomplete_team_workspace_config",
        )

    def test_resolve_codex_gui_variant_defaults_without_request(self):
        resolution = resolve_codex_gui_variant({})

        self.assertEqual(resolution.requested_variant, CODEX_GUI_VARIANT_DEFAULT)
        self.assertEqual(resolution.effective_variant, CODEX_GUI_VARIANT_DEFAULT)
        self.assertEqual(resolution.fallback_reason, "")

    def test_build_account_marks_selected_mode(self):
        adapter = build_chatgpt_registration_mode_adapter(
            {"chatgpt_registration_mode": "access_token_only"}
        )
        result = type(
            "Result",
            (),
            {
                "email": "demo@example.com",
                "password": "pw",
                "account_id": "acct-demo",
                "access_token": "at-demo",
                "refresh_token": "",
                "id_token": "id-demo",
                "session_token": "session-demo",
                "workspace_id": "ws-demo",
                "source": "register",
            },
        )()

        account = adapter.build_account(result, fallback_password="fallback")

        self.assertEqual(account.email, "demo@example.com")
        self.assertEqual(account.password, "pw")
        self.assertEqual(
            account.extra["chatgpt_registration_mode"],
            CHATGPT_REGISTRATION_MODE_ACCESS_TOKEN_ONLY,
        )
        self.assertFalse(account.extra["chatgpt_has_refresh_token_solution"])

    def test_access_token_only_adapter_passes_runtime_context_to_engine(self):
        created = {}

        class FakeEngine:
            def __init__(self, **kwargs):
                created["kwargs"] = kwargs
                self.email = None
                self.password = None

            def run(self):
                created["email"] = self.email
                created["password"] = self.password
                return type("Result", (), {"success": True})()

        adapter = build_chatgpt_registration_mode_adapter(
            {"chatgpt_registration_mode": "access_token_only"}
        )
        context = ChatGPTRegistrationContext(
            email_service=object(),
            proxy_url="http://127.0.0.1:7890",
            callback_logger=lambda _msg: None,
            email="demo@example.com",
            password="pw-demo",
            browser_mode="headed",
            max_retries=5,
            extra_config={"register_max_retries": 5},
        )

        def _build_engine(_self, runtime_context):
            return FakeEngine(
                email_service=runtime_context.email_service,
                proxy_url=runtime_context.proxy_url,
                browser_mode=runtime_context.browser_mode,
                callback_logger=runtime_context.callback_logger,
                max_retries=runtime_context.max_retries,
                extra_config=runtime_context.extra_config,
            )

        with mock.patch(
            "platforms.chatgpt.chatgpt_registration_mode_adapter.AccessTokenOnlyChatGPTRegistrationAdapter._create_engine",
            side_effect=_build_engine,
            autospec=True,
        ):
            adapter.run(context)

        self.assertEqual(created["email"], "demo@example.com")
        self.assertEqual(created["password"], "pw-demo")
        self.assertEqual(created["kwargs"]["browser_mode"], "headed")
        self.assertEqual(created["kwargs"]["max_retries"], 5)

    def test_codex_gui_adapter_passes_runtime_context_to_engine(self):
        created = {}

        class FakeEngine:
            def __init__(self, **kwargs):
                created["kwargs"] = kwargs
                self.email = None
                self.password = None

            def run(self):
                created["email"] = self.email
                created["password"] = self.password
                return type("Result", (), {"success": True})()

        adapter = build_chatgpt_registration_mode_adapter(
            {"chatgpt_registration_mode": "codex_gui"}
        )
        context = ChatGPTRegistrationContext(
            email_service=object(),
            proxy_url="http://127.0.0.1:7890",
            callback_logger=lambda _msg: None,
            email="demo@example.com",
            password="pw-demo",
            browser_mode="headed",
            max_retries=2,
            extra_config={"chatgpt_registration_mode": "codex_gui"},
        )

        def _build_engine(_self, runtime_context):
            return FakeEngine(
                email_service=runtime_context.email_service,
                proxy_url=runtime_context.proxy_url,
                browser_mode=runtime_context.browser_mode,
                callback_logger=runtime_context.callback_logger,
                max_retries=runtime_context.max_retries,
                extra_config=runtime_context.extra_config,
            )

        with mock.patch(
            "platforms.chatgpt.chatgpt_registration_mode_adapter.CodexGuiChatGPTRegistrationAdapter._create_engine",
            side_effect=_build_engine,
            autospec=True,
        ):
            adapter.run(context)

        self.assertEqual(created["email"], "demo@example.com")
        self.assertEqual(created["password"], "pw-demo")
        self.assertEqual(created["kwargs"]["browser_mode"], "headed")
        self.assertEqual(created["kwargs"]["max_retries"], 2)


if __name__ == "__main__":
    unittest.main()
