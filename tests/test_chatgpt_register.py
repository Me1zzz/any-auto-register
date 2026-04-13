import sys
import types
import unittest
from unittest import mock

curl_cffi_stub = types.ModuleType("curl_cffi")
curl_cffi_stub.requests = types.SimpleNamespace(Session=lambda *args, **kwargs: mock.Mock())
sys.modules.setdefault("curl_cffi", curl_cffi_stub)

smstome_tool_stub = types.ModuleType("smstome_tool")
smstome_tool_stub.PhoneEntry = type("PhoneEntry", (), {})
smstome_tool_stub.get_unused_phone = lambda *args, **kwargs: None
smstome_tool_stub.mark_phone_blacklisted = lambda *args, **kwargs: None
smstome_tool_stub.parse_country_slugs = lambda value: []
smstome_tool_stub.update_global_phone_list = lambda *args, **kwargs: 0
smstome_tool_stub.wait_for_otp = lambda *args, **kwargs: None
sys.modules.setdefault("smstome_tool", smstome_tool_stub)

from platforms.chatgpt.oauth_client import OAuthClient
from platforms.chatgpt.chatgpt_client import ChatGPTClient
from platforms.chatgpt.plugin import ChatGPTPlatform
from platforms.chatgpt.refresh_token_registration_engine import (
    EmailServiceAdapter,
    RefreshTokenRegistrationEngine,
)
from platforms.chatgpt.utils import FlowState
from core.base_platform import RegisterConfig


class DummyEmailService:
    service_type = type("ST", (), {"value": "dummy"})()

    def create_email(self):
        return {"email": "user@example.com", "service_id": "svc-1"}

    def get_verification_code(self, **kwargs):
        return "123456"


class RefreshTokenRegistrationEngineTests(unittest.TestCase):
    def _make_engine(self, **kwargs):
        return RefreshTokenRegistrationEngine(
            email_service=DummyEmailService(),
            proxy_url="http://127.0.0.1:7890",
            callback_logger=lambda msg: None,
            max_retries=1,
            **kwargs,
        )

    @mock.patch("platforms.chatgpt.refresh_token_registration_engine.OAuthManager")
    @mock.patch("platforms.chatgpt.refresh_token_registration_engine.OAuthClient")
    def test_run_uses_oauth_single_chain_signup_main_chain(
        self,
        mock_oauth_client_cls,
        mock_oauth_manager_cls,
    ):
        oauth_client = mock.Mock()
        oauth_client.device_id = "device-fixed"
        oauth_client.ua = "UA"
        oauth_client.sec_ch_ua = '"Chromium";v="136"'
        oauth_client.impersonate = "chrome136"
        oauth_client.signup_and_get_tokens.return_value = {
            "access_token": "at",
            "refresh_token": "rt",
            "id_token": "id-token",
            "account_id": "acct-1",
        }
        oauth_client.last_error = ""
        oauth_client.last_workspace_id = "ws-1"
        oauth_client._decode_oauth_session_cookie.return_value = {
            "workspaces": [{"id": "ws-1"}]
        }
        oauth_client._get_cookie_value.return_value = "session-1"
        mock_oauth_client_cls.return_value = oauth_client

        oauth_manager = mock.Mock()
        oauth_manager.extract_account_info.return_value = {
            "email": "user@example.com",
            "account_id": "acct-1",
        }
        mock_oauth_manager_cls.return_value = oauth_manager

        engine = self._make_engine(extra_config={"register_max_retries": 1})
        result = engine.run()

        self.assertTrue(result.success)
        self.assertEqual(result.email, "user@example.com")
        self.assertEqual(result.account_id, "acct-1")
        self.assertEqual(result.workspace_id, "ws-1")
        self.assertEqual(result.refresh_token, "rt")
        self.assertEqual(result.session_token, "session-1")
        self.assertEqual(result.source, "register")

        oauth_client.signup_and_get_tokens.assert_called_once()
        oauth_client.login_and_get_tokens.assert_not_called()
        signup_args = oauth_client.signup_and_get_tokens.call_args.args
        self.assertEqual(signup_args[0], "user@example.com")
        self.assertEqual(signup_args[1], result.password)
        signup_kwargs = oauth_client.signup_and_get_tokens.call_args.kwargs
        self.assertFalse(signup_kwargs["allow_phone_verification"])
        self.assertEqual(signup_kwargs["signup_source"], "refresh_token_engine")

    @mock.patch("platforms.chatgpt.refresh_token_registration_engine.OAuthManager")
    @mock.patch("platforms.chatgpt.refresh_token_registration_engine.OAuthClient")
    def test_run_switches_to_login_when_signup_reports_existing_account(
        self,
        mock_oauth_client_cls,
        mock_oauth_manager_cls,
    ):
        oauth_client = mock.Mock()
        oauth_client.device_id = "device-fixed"
        oauth_client.ua = "UA"
        oauth_client.sec_ch_ua = '"Chromium";v="136"'
        oauth_client.impersonate = "chrome136"
        oauth_client.signup_and_get_tokens.return_value = None
        oauth_client.last_error = "注册失败: 400 - user_already_exists"
        oauth_client.login_and_get_tokens.return_value = {
            "access_token": "at",
            "refresh_token": "rt",
            "id_token": "id-token",
        }
        oauth_client.last_workspace_id = "ws-1"
        oauth_client._decode_oauth_session_cookie.return_value = {
            "workspaces": [{"id": "ws-1"}]
        }
        oauth_client._get_cookie_value.return_value = ""
        mock_oauth_client_cls.return_value = oauth_client

        oauth_manager = mock.Mock()
        oauth_manager.extract_account_info.return_value = {
            "email": "user@example.com",
            "account_id": "acct-existing",
        }
        mock_oauth_manager_cls.return_value = oauth_manager

        engine = self._make_engine()
        result = engine.run()

        self.assertTrue(result.success)
        self.assertEqual(result.source, "login")
        self.assertEqual(result.account_id, "acct-existing")
        oauth_client.signup_and_get_tokens.assert_called_once()
        login_kwargs = oauth_client.login_and_get_tokens.call_args.kwargs
        self.assertEqual(login_kwargs["login_source"], "existing_account_continue")
        self.assertTrue(login_kwargs["force_new_browser"])
        self.assertEqual(login_kwargs["user_agent"], "UA")

    @mock.patch("platforms.chatgpt.refresh_token_registration_engine.OAuthManager")
    @mock.patch("platforms.chatgpt.refresh_token_registration_engine.OAuthClient")
    def test_run_retry_uses_newly_created_email_in_next_attempt(
        self,
        mock_oauth_client_cls,
        mock_oauth_manager_cls,
    ):
        class RotatingEmailService:
            service_type = type("ST", (), {"value": "dummy"})()

            def __init__(self):
                self.index = 0

            def create_email(self):
                self.index += 1
                return {
                    "email": f"user{self.index}@example.com",
                    "service_id": f"svc-{self.index}",
                }

            def get_verification_code(self, **kwargs):
                return "123456"

        oauth_client = mock.Mock()
        oauth_client.device_id = "device-fixed"
        oauth_client.ua = "UA"
        oauth_client.sec_ch_ua = '"Chromium";v="136"'
        oauth_client.impersonate = "chrome136"
        oauth_client.last_error = ""
        signup_results = iter(
            [
                (None, "network timeout"),
                (
                    {
                        "access_token": "at",
                        "refresh_token": "rt",
                        "id_token": "id-token",
                        "account_id": "acct-1",
                    },
                    "",
                ),
            ]
        )

        def _signup_side_effect(*args, **kwargs):
            result_value, error_value = next(signup_results)
            oauth_client.last_error = error_value
            return result_value

        oauth_client.signup_and_get_tokens.side_effect = _signup_side_effect
        oauth_client.login_and_get_tokens.return_value = {
            "access_token": "at",
            "refresh_token": "rt",
            "id_token": "id-token",
            "account_id": "acct-1",
        }
        oauth_client.last_workspace_id = "ws-1"
        oauth_client._decode_oauth_session_cookie.return_value = {
            "workspaces": [{"id": "ws-1"}]
        }
        oauth_client._get_cookie_value.return_value = "session-1"
        mock_oauth_client_cls.return_value = oauth_client

        oauth_manager = mock.Mock()
        oauth_manager.extract_account_info.return_value = {
            "email": "user2@example.com",
            "account_id": "acct-1",
        }
        mock_oauth_manager_cls.return_value = oauth_manager

        engine = RefreshTokenRegistrationEngine(
            email_service=RotatingEmailService(),
            proxy_url="http://127.0.0.1:7890",
            callback_logger=lambda msg: None,
            max_retries=2,
        )
        result = engine.run()

        self.assertTrue(result.success)
        call_args = oauth_client.signup_and_get_tokens.call_args_list
        self.assertEqual(call_args[0].args[0], "user1@example.com")
        self.assertEqual(call_args[1].args[0], "user2@example.com")

    def test_email_service_adapter_does_not_auto_exclude_previously_used_codes(self):
        email_service = mock.Mock()
        email_service.get_verification_code.return_value = "890206"
        logs = []
        adapter = EmailServiceAdapter(
            email_service=email_service,
            email="user@example.com",
            log_fn=logs.append,
        )
        adapter._used_codes.add("890206")

        code = adapter.wait_for_verification_code(
            "user@example.com",
            timeout=30,
        )

        self.assertEqual(code, "890206")
        email_service.get_verification_code.assert_called_once_with(
            email="user@example.com",
            timeout=30,
            otp_sent_at=None,
            exclude_codes=set(),
        )

    def test_email_service_adapter_keeps_explicit_excluded_codes(self):
        email_service = mock.Mock()
        email_service.get_verification_code.return_value = "123456"
        adapter = EmailServiceAdapter(
            email_service=email_service,
            email="user@example.com",
            log_fn=lambda _msg: None,
        )
        adapter._used_codes.add("890206")

        adapter.wait_for_verification_code(
            "user@example.com",
            timeout=30,
            exclude_codes={"654321"},
        )

        email_service.get_verification_code.assert_called_once_with(
            email="user@example.com",
            timeout=30,
            otp_sent_at=None,
            exclude_codes={"654321"},
        )

    def test_email_service_adapter_builds_exclude_codes_for_cloudmail_message_dedupe(self):
        email_service = mock.Mock()
        email_service._cloudmail_message_dedupe = True
        adapter = EmailServiceAdapter(
            email_service=email_service,
            email="user@example.com",
            log_fn=lambda _msg: None,
        )
        adapter._used_message_ids.update({"msg-1", "msg-2"})

        self.assertEqual(adapter.build_exclude_codes(), {"msg-1", "msg-2"})

    def test_email_service_adapter_builds_exclude_codes_for_regular_codes(self):
        email_service = mock.Mock()
        email_service._cloudmail_message_dedupe = False
        adapter = EmailServiceAdapter(
            email_service=email_service,
            email="user@example.com",
            log_fn=lambda _msg: None,
        )
        adapter._used_codes.update({"111111", "222222"})

        self.assertEqual(adapter.build_exclude_codes(), {"111111", "222222"})

    def test_run_uses_mailbox_timeout_as_register_wait_base(self):
        engine = self._make_engine(
            extra_config={
                "mailbox_otp_timeout_seconds": 75,
                "chatgpt_register_otp_wait_seconds": 600,
            }
        )

        register_client = mock.Mock()
        register_client.register_complete_flow.return_value = (False, "user_already_exists")
        register_client.device_id = "device-fixed"
        register_client.ua = "UA"
        register_client.sec_ch_ua = '"Chromium";v="136"'
        register_client.impersonate = "chrome136"

        oauth_client = mock.Mock()
        oauth_client.login_and_get_tokens.return_value = {
            "access_token": "at",
            "refresh_token": "rt",
            "id_token": "id-token",
        }
        oauth_client.last_error = ""
        oauth_client.last_workspace_id = "ws-1"
        oauth_client._decode_oauth_session_cookie.return_value = {
            "workspaces": [{"id": "ws-1"}]
        }
        oauth_client._get_cookie_value.return_value = "session-1"

        with mock.patch.object(engine, "_build_chatgpt_client", return_value=register_client), \
            mock.patch.object(engine, "_build_oauth_client", return_value=oauth_client), \
            mock.patch("platforms.chatgpt.refresh_token_registration_engine.OAuthManager") as mock_oauth_manager_cls:
            oauth_manager = mock.Mock()
            oauth_manager.extract_account_info.return_value = {
                "email": "user@example.com",
                "account_id": "acct-1",
            }
            mock_oauth_manager_cls.return_value = oauth_manager

            result = engine.run()

        self.assertTrue(result.success)
        register_kwargs = register_client.register_complete_flow.call_args.kwargs
        self.assertEqual(register_kwargs["otp_wait_timeout"], 75)
        self.assertEqual(register_kwargs["max_otp_resend_attempts"], 5)


class ChatGPTPlatformTests(unittest.TestCase):
    def test_gui_default_executor_skips_mailbox_timeout_override_for_codex_mode(self):
        mailbox = mock.Mock()
        mailbox.get_email.return_value = type(
            "MailboxAccount",
            (),
            {"account_id": "acct-1", "email": "user@example.com"},
        )()
        mailbox.get_current_ids.return_value = []
        mailbox.wait_for_code.return_value = "123456"

        class FakeAdapter:
            def run(self, context):
                context.email_service.create_email()
                code = context.email_service.get_verification_code(timeout=30)
                self.observed_code = code
                return type("Result", (), {"success": True})()

            def build_account(self, result, fallback_password):
                return mock.sentinel.account

        adapter = FakeAdapter()
        platform = ChatGPTPlatform(
            config=RegisterConfig(
                executor_type="headed",
                extra={
                    "default_executor": "gui_control",
                    "mailbox_otp_timeout_seconds": 999,
                },
            ),
            mailbox=mailbox,
        )

        with mock.patch(
            "platforms.chatgpt.plugin.build_chatgpt_registration_mode_adapter",
            return_value=adapter,
        ):
            account = platform.register(email="user@example.com", password="pw-demo")

        self.assertIs(account, mock.sentinel.account)
        self.assertEqual(adapter.observed_code, "123456")
        mailbox.wait_for_code.assert_called_once()
        self.assertEqual(mailbox.wait_for_code.call_args.kwargs["timeout"], 30)


class ChatGPTClientRegisterFlowOtpTests(unittest.TestCase):
    def _make_client(self):
        client = object.__new__(ChatGPTClient)
        client.proxy = "http://127.0.0.1:7890"
        client.verbose = False
        client.browser_mode = "protocol"
        client.device_id = "device-fixed"
        client.accept_language = "en-US,en;q=0.9"
        client.impersonate = "chrome136"
        client.chrome_major = 136
        client.chrome_full = "136.0.7103.100"
        client.ua = "UA"
        client.sec_ch_ua = '"Chromium";v="136"'
        client.session = mock.Mock(headers={})
        client.last_registration_state = FlowState()
        client.last_stage = ""
        client._log = lambda _msg: None
        return client

    def test_register_complete_flow_resends_until_code_received(self):
        client = self._make_client()
        register_state = FlowState(
            page_type="register_password",
            current_url="https://auth.openai.com/create-account/password",
        )
        otp_state = FlowState(
            page_type="email_otp_verification",
            current_url="https://auth.openai.com/email-verification",
        )
        about_you_state = FlowState(
            page_type="about_you",
            current_url="https://auth.openai.com/about-you",
        )
        mail_client = mock.Mock()
        mail_client.wait_for_verification_code.side_effect = [TimeoutError("t1"), TimeoutError("t2"), "123456"]

        with mock.patch.object(client, "visit_homepage", return_value=True), \
            mock.patch.object(client, "get_csrf_token", return_value="csrf"), \
            mock.patch.object(client, "signin", return_value="https://auth.openai.com/authorize"), \
            mock.patch.object(client, "authorize", return_value="https://auth.openai.com/create-account/password"), \
            mock.patch.object(client, "_state_from_url", side_effect=[register_state, otp_state]), \
            mock.patch.object(client, "_is_registration_complete_state", side_effect=lambda state: False), \
            mock.patch.object(client, "_state_is_password_registration", side_effect=lambda state: state.page_type == "register_password"), \
            mock.patch.object(client, "_state_is_email_otp", side_effect=lambda state: state.page_type == "email_otp_verification"), \
            mock.patch.object(client, "_state_is_about_you", side_effect=lambda state: state.page_type == "about_you"), \
            mock.patch.object(client, "_state_requires_navigation", return_value=False), \
            mock.patch.object(client, "register_user", return_value=(True, "ok")), \
            mock.patch.object(client, "send_email_otp", side_effect=[True, True, True]) as send_otp, \
            mock.patch.object(client, "verify_email_otp", return_value=(True, about_you_state)), \
            mock.patch("platforms.chatgpt.chatgpt_client.random.uniform", side_effect=[80, 90, 100]):
            ok, message = client.register_complete_flow(
                "user@example.com",
                "Secret123!",
                "Foo",
                "Bar",
                "1990-01-01",
                mail_client,
                stop_before_about_you_submission=True,
                otp_wait_timeout=100,
            )

        self.assertTrue(ok)
        self.assertEqual(message, "pending_about_you_submission")
        self.assertEqual(send_otp.call_count, 3)
        wait_calls = mail_client.wait_for_verification_code.call_args_list
        self.assertEqual([call.kwargs["timeout"] for call in wait_calls], [80, 90, 100])
        self.assertIsNotNone(wait_calls[0].kwargs["otp_sent_at"])
        self.assertLess(wait_calls[0].kwargs["otp_sent_at"], wait_calls[1].kwargs["otp_sent_at"])
        self.assertLess(wait_calls[1].kwargs["otp_sent_at"], wait_calls[2].kwargs["otp_sent_at"])

    def test_register_complete_flow_fails_after_default_five_resends(self):
        client = self._make_client()
        register_state = FlowState(
            page_type="register_password",
            current_url="https://auth.openai.com/create-account/password",
        )
        otp_state = FlowState(
            page_type="email_otp_verification",
            current_url="https://auth.openai.com/email-verification",
        )
        mail_client = mock.Mock()
        mail_client.wait_for_verification_code.side_effect = [TimeoutError(f"t{i}") for i in range(6)]

        with mock.patch.object(client, "visit_homepage", return_value=True), \
            mock.patch.object(client, "get_csrf_token", return_value="csrf"), \
            mock.patch.object(client, "signin", return_value="https://auth.openai.com/authorize"), \
            mock.patch.object(client, "authorize", return_value="https://auth.openai.com/create-account/password"), \
            mock.patch.object(client, "_state_from_url", side_effect=[register_state, otp_state]), \
            mock.patch.object(client, "_is_registration_complete_state", side_effect=lambda state: False), \
            mock.patch.object(client, "_state_is_password_registration", side_effect=lambda state: state.page_type == "register_password"), \
            mock.patch.object(client, "_state_is_email_otp", side_effect=lambda state: state.page_type == "email_otp_verification"), \
            mock.patch.object(client, "_state_is_about_you", side_effect=lambda state: False), \
            mock.patch.object(client, "_state_requires_navigation", return_value=False), \
            mock.patch.object(client, "register_user", return_value=(True, "ok")), \
            mock.patch.object(client, "send_email_otp", side_effect=[True, True, True, True, True, True]) as send_otp, \
            mock.patch("platforms.chatgpt.chatgpt_client.random.uniform", side_effect=[100, 100, 100, 100, 100, 100]):
            ok, message = client.register_complete_flow(
                "user@example.com",
                "Secret123!",
                "Foo",
                "Bar",
                "1990-01-01",
                mail_client,
                otp_wait_timeout=100,
            )

        self.assertFalse(ok)
        self.assertIn("已重发 5/5 次", message)
        self.assertEqual(send_otp.call_count, 6)


class OAuthClientPasswordlessTests(unittest.TestCase):
    def _make_client(self):
        return OAuthClient({}, proxy="http://127.0.0.1:7890", verbose=False)

    def test_handle_otp_verification_resends_until_code_received(self):
        client = self._make_client()
        client.config = {
            "chatgpt_oauth_otp_wait_seconds": 30,
            "chatgpt_oauth_otp_max_resends": 5,
        }
        state = FlowState(
            page_type="email_otp_verification",
            continue_url="https://auth.openai.com/email-verification",
            current_url="https://auth.openai.com/email-verification",
        )
        mail_client = mock.Mock()
        mail_client._used_codes = set()
        mail_client.wait_for_verification_code.side_effect = [TimeoutError("t1"), TimeoutError("t2"), "654321"]
        next_state = FlowState(
            page_type="consent",
            continue_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            current_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
        )

        def _post_side_effect(url, **kwargs):
            if url.endswith("/api/accounts/passwordless/send-otp"):
                return mock.Mock(status_code=200, url=url, text="", json=mock.Mock(return_value={}))
            if url.endswith("/api/accounts/email-otp/validate"):
                return mock.Mock(
                    status_code=200,
                    url=url,
                    text="",
                    json=mock.Mock(return_value={"page": {"type": "consent"}}),
                )
            raise AssertionError(f"unexpected POST url: {url}")

        with mock.patch("platforms.chatgpt.oauth_client.get_sentinel_token_via_browser", return_value="sentinel"), \
            mock.patch.object(client, "_headers", return_value={}), \
            mock.patch.object(client, "_browser_pause"), \
            mock.patch.object(client, "_state_from_payload", return_value=next_state), \
            mock.patch.object(type(client), "_sample_otp_wait_timeout", side_effect=[31, 30, 29]), \
            mock.patch.object(client.session, "post", side_effect=_post_side_effect) as post_mock, \
            mock.patch.object(client, "_log"):
            resolved_state = client._handle_otp_verification(
                "user@example.com",
                "device-fixed",
                "UA",
                '"Chromium";v="136"',
                "chrome136",
                mail_client,
                state,
                prefer_passwordless_login=True,
            )

        self.assertEqual(resolved_state, next_state)
        self.assertEqual(mail_client.wait_for_verification_code.call_count, 3)
        self.assertEqual(post_mock.call_count, 3)
        wait_calls = mail_client.wait_for_verification_code.call_args_list
        self.assertEqual([call.kwargs["timeout"] for call in wait_calls], [31, 30, 29])
        self.assertLess(wait_calls[0].kwargs["otp_sent_at"], wait_calls[1].kwargs["otp_sent_at"])
        self.assertLess(wait_calls[1].kwargs["otp_sent_at"], wait_calls[2].kwargs["otp_sent_at"])

    def test_handle_otp_verification_fails_after_default_five_resends(self):
        client = self._make_client()
        client.config = {"chatgpt_oauth_otp_wait_seconds": 30}
        state = FlowState(
            page_type="email_otp_verification",
            continue_url="https://auth.openai.com/email-verification",
            current_url="https://auth.openai.com/email-verification",
        )
        mail_client = mock.Mock()
        mail_client._used_codes = set()
        mail_client.wait_for_verification_code.side_effect = [TimeoutError(f"t{i}") for i in range(6)]

        with mock.patch("platforms.chatgpt.oauth_client.get_sentinel_token_via_browser", return_value="sentinel"), \
            mock.patch.object(client, "_headers", return_value={}), \
            mock.patch.object(client, "_browser_pause"), \
            mock.patch.object(client, "_log"), \
            mock.patch.object(type(client), "_sample_otp_wait_timeout", side_effect=[30, 30, 30, 30, 30, 30]), \
            mock.patch.object(client.session, "post", return_value=mock.Mock(status_code=200, url="https://auth.openai.com/api/accounts/passwordless/send-otp", text="", json=mock.Mock(return_value={}))), \
            mock.patch.object(client.session, "get", return_value=mock.Mock(status_code=200, url="https://auth.openai.com/api/accounts/email-otp/send", text="", json=mock.Mock(return_value={}))):
            next_state = client._handle_otp_verification(
                "user@example.com",
                "device-fixed",
                "UA",
                '"Chromium";v="136"',
                "chrome136",
                mail_client,
                state,
                prefer_passwordless_login=True,
            )

        self.assertIsNone(next_state)
        self.assertIn("已重发 5/5 次", client.last_error)

    def test_handle_otp_verification_resend_failures_still_consume_budget(self):
        client = self._make_client()
        client.config = {
            "chatgpt_oauth_otp_wait_seconds": 30,
            "chatgpt_oauth_otp_max_resends": 2,
        }
        state = FlowState(
            page_type="email_otp_verification",
            continue_url="https://auth.openai.com/email-verification",
            current_url="https://auth.openai.com/email-verification",
        )
        mail_client = mock.Mock()
        mail_client._used_codes = set()
        mail_client.wait_for_verification_code.side_effect = [TimeoutError("t1"), TimeoutError("t2"), TimeoutError("t3")]

        with mock.patch("platforms.chatgpt.oauth_client.get_sentinel_token_via_browser", return_value="sentinel"), \
            mock.patch.object(client, "_headers", return_value={}), \
            mock.patch.object(client, "_browser_pause"), \
            mock.patch.object(client, "_log"), \
            mock.patch.object(type(client), "_sample_otp_wait_timeout", side_effect=[30, 30, 30]), \
            mock.patch.object(client.session, "post", return_value=mock.Mock(status_code=500, url="https://auth.openai.com/api/accounts/passwordless/send-otp", text="err", json=mock.Mock(return_value={}))), \
            mock.patch.object(client.session, "get", return_value=mock.Mock(status_code=500, url="https://auth.openai.com/api/accounts/email-otp/send", text="err", json=mock.Mock(return_value={}))):
            next_state = client._handle_otp_verification(
                "user@example.com",
                "device-fixed",
                "UA",
                '"Chromium";v="136"',
                "chrome136",
                mail_client,
                state,
                prefer_passwordless_login=True,
            )

        self.assertIsNone(next_state)
        self.assertIn("已重发 2/2 次", client.last_error)

    def test_handle_otp_verification_keeps_original_otp_sent_at_across_resends(self):
        client = self._make_client()
        client.config = {
            "chatgpt_oauth_otp_wait_seconds": 30,
            "chatgpt_oauth_otp_max_resends": 2,
        }
        state = FlowState(
            page_type="email_otp_verification",
            continue_url="https://auth.openai.com/email-verification",
            current_url="https://auth.openai.com/email-verification",
        )
        mail_client = mock.Mock()
        mail_client._used_codes = set()
        observed_otp_sent_at = []

        def _wait_for_verification_code(*args, **kwargs):
            observed_otp_sent_at.append(kwargs["otp_sent_at"])
            raise TimeoutError(f"t{len(observed_otp_sent_at)}")

        mail_client.wait_for_verification_code.side_effect = _wait_for_verification_code

        with mock.patch("platforms.chatgpt.oauth_client.get_sentinel_token_via_browser", return_value="sentinel"), \
            mock.patch.object(client, "_headers", return_value={}), \
            mock.patch.object(client, "_browser_pause"), \
            mock.patch.object(client, "_log"), \
            mock.patch.object(type(client), "_sample_otp_wait_timeout", side_effect=[30, 30, 30]), \
            mock.patch.object(client.session, "post", return_value=mock.Mock(status_code=200, url="https://auth.openai.com/api/accounts/passwordless/send-otp", text="", json=mock.Mock(return_value={}))), \
            mock.patch.object(client.session, "get", return_value=mock.Mock(status_code=200, url="https://auth.openai.com/api/accounts/email-otp/send", text="", json=mock.Mock(return_value={}))):
            next_state = client._handle_otp_verification(
                "user@example.com",
                "device-fixed",
                "UA",
                '"Chromium";v="136"',
                "chrome136",
                mail_client,
                state,
                prefer_passwordless_login=True,
            )

        self.assertIsNone(next_state)
        self.assertEqual(len(observed_otp_sent_at), 3)
        self.assertTrue(all(value == observed_otp_sent_at[0] for value in observed_otp_sent_at))

    def test_handle_otp_verification_uses_message_id_dedupe_for_cloudmail(self):
        client = self._make_client()
        client.config = {
            "chatgpt_oauth_otp_wait_seconds": 30,
            "chatgpt_oauth_otp_max_resends": 1,
        }
        state = FlowState(
            page_type="email_otp_verification",
            continue_url="https://auth.openai.com/email-verification",
            current_url="https://auth.openai.com/email-verification",
        )
        mail_client = mock.Mock()
        mail_client._used_codes = {"236944"}
        mail_client._used_message_ids = {"m-1"}
        type(mail_client).uses_cloudmail_message_dedupe = mock.PropertyMock(return_value=True)

        def _wait_for_verification_code(*args, **kwargs):
            self.assertEqual(kwargs["exclude_codes"], {"m-1"})
            mail_client._last_message_id = "m-2"
            return "236944"

        mail_client.wait_for_verification_code.side_effect = _wait_for_verification_code
        next_state = FlowState(
            page_type="consent",
            continue_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            current_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
        )

        def _post_side_effect(url, **kwargs):
            if url.endswith("/api/accounts/email-otp/validate"):
                return mock.Mock(
                    status_code=200,
                    url=url,
                    text="",
                    json=mock.Mock(return_value={"page": {"type": "consent"}}),
                )
            raise AssertionError(f"unexpected POST url: {url}")

        with mock.patch("platforms.chatgpt.oauth_client.get_sentinel_token_via_browser", return_value="sentinel"), \
            mock.patch.object(client, "_headers", return_value={}), \
            mock.patch.object(client, "_browser_pause"), \
            mock.patch.object(client, "_state_from_payload", return_value=next_state), \
            mock.patch.object(type(client), "_sample_otp_wait_timeout", return_value=30), \
            mock.patch.object(client.session, "post", side_effect=_post_side_effect), \
            mock.patch.object(client, "_log") as log_mock:
            resolved_state = client._handle_otp_verification(
                "user@example.com",
                "device-fixed",
                "UA",
                '"Chromium";v="136"',
                "chrome136",
                mail_client,
                state,
                prefer_passwordless_login=False,
            )

        self.assertEqual(resolved_state, next_state)
        logged_messages = [call.args[0] for call in log_mock.call_args_list if call.args]
        self.assertNotIn("跳过已尝试验证码: 236944", logged_messages)

    def test_submit_signup_register_uses_minimal_headers_strategy(self):
        client = self._make_client()
        client.session.post = mock.Mock(
            return_value=mock.Mock(status_code=200, url="https://auth.openai.com/api/accounts/user/register")
        )

        with mock.patch(
            "platforms.chatgpt.oauth_client.get_sentinel_token_via_browser",
            return_value="sentinel-demo",
        ), mock.patch(
            "platforms.chatgpt.oauth_client.build_sentinel_token",
            return_value="",
        ):
            ok = client._submit_signup_register(
                "user@example.com",
                "Secret123!",
                "device-fixed",
                user_agent="UA",
                sec_ch_ua='"Chromium";v="136"',
                impersonate="chrome136",
                referer="https://auth.openai.com/create-account/password",
            )

        self.assertTrue(ok)
        kwargs = client.session.post.call_args.kwargs
        self.assertIn("data", kwargs)
        self.assertNotIn("json", kwargs)
        headers = kwargs["headers"]
        self.assertEqual(headers["Referer"], "https://auth.openai.com/create-account/password")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["Accept"], "application/json")
        self.assertEqual(headers["openai-sentinel-token"], "sentinel-demo")
        self.assertNotIn("Origin", headers)
        self.assertNotIn("oai-device-id", headers)

    def test_login_and_get_tokens_prefers_passwordless_over_password_verify(self):
        client = self._make_client()
        login_password_state = FlowState(
            page_type="login_password",
            continue_url="https://auth.openai.com/log-in/password",
            current_url="https://auth.openai.com/log-in/password",
        )
        email_otp_state = FlowState(
            page_type="email_otp_verification",
            continue_url="https://auth.openai.com/email-verification",
            current_url="https://auth.openai.com/email-verification",
        )
        consent_state = FlowState(
            page_type="consent",
            continue_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            current_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
        )

        with mock.patch.object(client, "_bootstrap_oauth_session", return_value="https://auth.openai.com/log-in"), \
            mock.patch.object(client, "_submit_authorize_continue", return_value=login_password_state) as submit_continue, \
            mock.patch.object(client, "_send_passwordless_login_otp", return_value=email_otp_state) as send_passwordless, \
            mock.patch.object(client, "_handle_otp_verification", return_value=consent_state), \
            mock.patch.object(client, "_oauth_submit_workspace_and_org", return_value=("auth-code", None)), \
            mock.patch.object(client, "_exchange_code_for_tokens", return_value={"access_token": "at"}), \
            mock.patch.object(client, "_submit_password_verify") as submit_password:
            tokens = client.login_and_get_tokens(
                "user@example.com",
                "Secret123!",
                "device-fixed",
                user_agent="UA",
                sec_ch_ua='"Chromium";v="136"',
                impersonate="chrome136",
                skymail_client=mock.Mock(),
                prefer_passwordless_login=True,
                allow_phone_verification=False,
            )

        self.assertEqual(tokens["access_token"], "at")
        submit_continue.assert_called_once()
        self.assertEqual(submit_continue.call_args.kwargs["screen_hint"], "login")
        send_passwordless.assert_called_once()
        submit_password.assert_not_called()

    def test_login_and_get_tokens_visits_add_phone_continue_url_before_phone_branch(self):
        client = self._make_client()
        add_phone_state = FlowState(
            page_type="add_phone",
            continue_url="https://auth.openai.com/add-phone",
            current_url="https://auth.openai.com/api/accounts/email-otp/validate",
            source="api",
        )
        consent_state = FlowState(
            page_type="consent",
            continue_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            current_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
        )

        with mock.patch.object(client, "_bootstrap_oauth_session", return_value="https://auth.openai.com/log-in"), \
            mock.patch.object(client, "_submit_authorize_continue", return_value=add_phone_state), \
            mock.patch.object(client, "_follow_flow_state", return_value=(None, consent_state)) as follow_state, \
            mock.patch.object(client, "_oauth_submit_workspace_and_org", return_value=("auth-code", None)), \
            mock.patch.object(client, "_exchange_code_for_tokens", return_value={"access_token": "at"}), \
            mock.patch.object(client, "_handle_add_phone_verification") as handle_phone:
            tokens = client.login_and_get_tokens(
                "user@example.com",
                "Secret123!",
                "device-fixed",
                prefer_passwordless_login=True,
                allow_phone_verification=False,
            )

        self.assertEqual(tokens["access_token"], "at")
        follow_state.assert_called_once()
        handle_phone.assert_not_called()

    def test_login_and_get_tokens_uses_canonical_consent_url_when_state_is_add_phone(self):
        client = self._make_client()
        add_phone_state = FlowState(
            page_type="add_phone",
            continue_url="https://auth.openai.com/add-phone",
            current_url="https://auth.openai.com/add-phone",
        )

        with mock.patch.object(client, "_bootstrap_oauth_session", return_value="https://auth.openai.com/log-in"), \
            mock.patch.object(client, "_submit_authorize_continue", return_value=add_phone_state), \
            mock.patch.object(client, "_state_supports_workspace_resolution", return_value=True), \
            mock.patch.object(client, "_state_requires_navigation", return_value=False), \
            mock.patch.object(client, "_oauth_submit_workspace_and_org", return_value=("auth-code", None)) as submit_workspace, \
            mock.patch.object(client, "_exchange_code_for_tokens", return_value={"access_token": "at"}):
            tokens = client.login_and_get_tokens(
                "user@example.com",
                "Secret123!",
                "device-fixed",
                prefer_passwordless_login=True,
                allow_phone_verification=False,
                skymail_client=mock.Mock(),
            )

        self.assertEqual(tokens["access_token"], "at")
        self.assertEqual(
            submit_workspace.call_args.args[0],
            "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
        )

    def test_login_and_get_tokens_retries_once_when_add_phone_has_no_workspace(self):
        client = self._make_client()
        add_phone_state = FlowState(
            page_type="add_phone",
            continue_url="https://auth.openai.com/add-phone",
            current_url="https://auth.openai.com/add-phone",
        )

        with mock.patch.object(client, "_bootstrap_oauth_session", return_value="https://auth.openai.com/log-in") as bootstrap, \
            mock.patch.object(client, "_submit_authorize_continue", return_value=add_phone_state) as submit_continue, \
            mock.patch.object(client, "_state_supports_workspace_resolution", return_value=False), \
            mock.patch.object(client, "_state_requires_navigation", return_value=False):
            tokens = client.login_and_get_tokens(
                "user@example.com",
                "Secret123!",
                "device-fixed",
                prefer_passwordless_login=True,
                allow_phone_verification=False,
                skymail_client=mock.Mock(),
            )

        self.assertIsNone(tokens)
        self.assertEqual(bootstrap.call_count, 2)
        self.assertEqual(submit_continue.call_count, 2)
        self.assertIn("未获取到 workspace / callback", client.last_error)

    def test_send_passwordless_login_otp_does_not_send_email_field(self):
        client = self._make_client()
        response = mock.Mock()
        response.status_code = 200
        response.url = "https://auth.openai.com/api/accounts/passwordless/send-otp"
        response.json.return_value = {"page": {"type": "email_otp_verification"}}
        client.session.post = mock.Mock(return_value=response)

        expected_state = FlowState(
            page_type="email_otp_verification",
            continue_url="https://auth.openai.com/email-verification",
            current_url="https://auth.openai.com/email-verification",
        )
        with mock.patch.object(
            client,
            "_state_from_payload",
            return_value=expected_state,
        ):
            state = client._send_passwordless_login_otp(
                "user@example.com",
                "device-fixed",
            )

        self.assertEqual(state, expected_state)
        kwargs = client.session.post.call_args.kwargs
        self.assertNotIn("json", kwargs)
        self.assertNotIn("data", kwargs)

    def test_login_and_get_tokens_submits_about_you_when_configured(self):
        client = self._make_client()
        about_you_state = FlowState(
            page_type="about_you",
            continue_url="https://auth.openai.com/about-you",
            current_url="https://auth.openai.com/about-you",
        )
        consent_state = FlowState(
            page_type="consent",
            continue_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            current_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
        )

        with mock.patch.object(client, "_bootstrap_oauth_session", return_value="https://auth.openai.com/log-in"), \
            mock.patch.object(client, "_submit_authorize_continue", return_value=about_you_state), \
            mock.patch.object(client, "_submit_about_you_create_account", return_value=consent_state) as submit_about_you, \
            mock.patch.object(client, "_oauth_submit_workspace_and_org", return_value=("auth-code", None)), \
            mock.patch.object(client, "_exchange_code_for_tokens", return_value={"access_token": "at"}):
            tokens = client.login_and_get_tokens(
                "user@example.com",
                "Secret123!",
                "device-fixed",
                prefer_passwordless_login=True,
                allow_phone_verification=False,
                complete_about_you_if_needed=True,
                first_name="Ivy",
                last_name="Stone",
                birthdate="1990-01-02",
                skymail_client=mock.Mock(),
            )

        self.assertEqual(tokens["access_token"], "at")
        submit_about_you.assert_called_once()
        self.assertEqual(submit_about_you.call_args.args[0], "Ivy")
        self.assertEqual(submit_about_you.call_args.args[1], "Stone")
        self.assertEqual(submit_about_you.call_args.args[2], "1990-01-02")


class BrowserFallbackTests(unittest.TestCase):
    def test_chatgpt_create_account_uses_browser_fallback_on_challenge(self):
        client = ChatGPTClient(proxy="http://127.0.0.1:7890", verbose=False, browser_mode="headless")
        client._get_sentinel_token = mock.Mock(return_value="sentinel-token")
        client._browser_submit_create_account = mock.Mock(
            return_value=(
                True,
                FlowState(
                    page_type="consent",
                    continue_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
                    current_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
                ),
            )
        )

        response = mock.Mock()
        response.status_code = 403
        response.text = "<!DOCTYPE html>Just a moment..."
        response.url = "https://auth.openai.com/about-you"
        client.session.post = mock.Mock(return_value=response)

        ok, next_state = client.create_account("Ivy", "Stone", "1990-01-02", return_state=True)

        self.assertTrue(ok)
        self.assertEqual(next_state.page_type, "consent")
        client._browser_submit_create_account.assert_called_once()

    def test_chatgpt_create_account_protocol_mode_skips_browser_fallback(self):
        client = ChatGPTClient(proxy="http://127.0.0.1:7890", verbose=False, browser_mode="protocol")
        client._get_sentinel_token = mock.Mock(return_value="sentinel-token")
        client._browser_submit_create_account = mock.Mock()

        response = mock.Mock()
        response.status_code = 403
        response.text = "<!DOCTYPE html>Just a moment..."
        response.url = "https://auth.openai.com/about-you"
        response.json.side_effect = ValueError("not json")
        client.session.post = mock.Mock(return_value=response)

        ok, detail = client.create_account("Ivy", "Stone", "1990-01-02", return_state=True)

        self.assertFalse(ok)
        self.assertIn("HTTP 403", detail)
        client._browser_submit_create_account.assert_not_called()

    def test_load_workspace_session_data_uses_browser_warm_page_when_needed(self):
        client = OAuthClient({}, proxy="http://127.0.0.1:7890", verbose=False, browser_mode="headless")
        client._decode_oauth_session_cookie = mock.Mock(
            side_effect=[
                None,
                {"workspaces": [{"id": "ws-1"}]},
            ]
        )
        client._fetch_consent_page_html = mock.Mock(return_value="")
        client._browser_warm_page = mock.Mock(
            return_value={
                "url": "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
                "html": "<html></html>",
            }
        )

        session_data = client._load_workspace_session_data(
            "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            user_agent="UA",
            impersonate="chrome136",
        )

        self.assertEqual(session_data["workspaces"][0]["id"], "ws-1")
        client._browser_warm_page.assert_called_once()

    def test_workspace_submit_falls_back_to_browser_callback_when_api_follow_has_no_code(self):
        client = OAuthClient({}, proxy="http://127.0.0.1:7890", verbose=False, browser_mode="headless")
        client._load_workspace_session_data = mock.Mock(
            return_value={"workspaces": [{"id": "ws-1"}]}
        )
        client._oauth_follow_for_code = mock.Mock(return_value=(None, "https://auth.openai.com/sign-in-with-chatgpt/codex/consent"))
        client._browser_capture_callback = mock.Mock(
            return_value="http://localhost:1455/auth/callback?code=auth-code&state=demo"
        )

        response = mock.Mock()
        response.status_code = 200
        response.url = "https://auth.openai.com/api/accounts/workspace/select"
        response.text = '{"continue_url":"https://auth.openai.com/sign-in-with-chatgpt/codex/consent"}'
        response.json.return_value = {
            "continue_url": "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            "page": {
                "type": "consent",
                "payload": {
                    "url": "https://auth.openai.com/sign-in-with-chatgpt/codex/consent"
                },
            },
            "data": {
                "orgs": [],
            },
        }
        client.session.post = mock.Mock(return_value=response)

        code, state = client._oauth_submit_workspace_and_org(
            "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            "device-fixed",
            "UA",
            "chrome136",
        )

        self.assertEqual(code, "auth-code")
        self.assertEqual(state.page_type, "oauth_callback")
        client._browser_capture_callback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
