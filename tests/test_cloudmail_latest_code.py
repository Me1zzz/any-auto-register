import argparse
import unittest
from unittest import mock

from core.base_mailbox import MailboxAccount
from scripts import cloudmail_latest_code


class CloudMailLatestCodeScriptTests(unittest.TestCase):
    def test_build_mailbox_extra_uses_cli_then_config_fallbacks(self):
        args = argparse.Namespace(
            api_base="",
            admin_email="",
            admin_password="",
            domain="",
            subdomain="",
            email="demo@example.com",
            mailbox_email="",
            wait_timeout=300,
            keyword="",
            code_pattern="",
            verbose=False,
        )

        def fake_get(key, default=""):
            values = {
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
                "cloudmail_subdomain": "pool-a",
            }
            return values.get(key, default)

        fake_store = mock.Mock()
        fake_store.get.side_effect = fake_get

        with mock.patch.object(cloudmail_latest_code, "_load_config_store", return_value=fake_store):
            extra = cloudmail_latest_code._build_mailbox_extra(args)

        self.assertEqual(
            extra,
            {
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
                "cloudmail_subdomain": "pool-a",
            },
        )

    def test_build_account_uses_real_mailbox_when_provided(self):
        args = argparse.Namespace(
            email="alias@alias.example.com",
            mailbox_email="real@mail.example.com",
            api_base="",
            admin_email="",
            admin_password="",
            domain="",
            subdomain="",
            wait_timeout=300,
            keyword="",
            code_pattern="",
            verbose=False,
        )

        account = cloudmail_latest_code._build_account(args)

        self.assertEqual(
            account,
            MailboxAccount(
                email="alias@alias.example.com",
                account_id="real@mail.example.com",
            ),
        )

    def test_build_account_falls_back_to_email_when_mailbox_missing(self):
        args = argparse.Namespace(
            email="demo@example.com",
            mailbox_email="",
            api_base="",
            admin_email="",
            admin_password="",
            domain="",
            subdomain="",
            wait_timeout=300,
            keyword="",
            code_pattern="",
            verbose=False,
        )

        account = cloudmail_latest_code._build_account(args)

        self.assertEqual(account, MailboxAccount(email="demo@example.com", account_id="demo@example.com"))

    def test_run_polling_prints_each_new_code_and_retries_after_timeout(self):
        args = argparse.Namespace(
            api_base="https://cloudmail.example.com",
            admin_email="admin@example.com",
            admin_password="secret",
            domain="mail.example.com",
            subdomain="",
            email="demo@example.com",
            mailbox_email="",
            wait_timeout=30,
            keyword="",
            code_pattern="",
            verbose=True,
        )
        fake_mailbox = mock.Mock()

        state = [0]

        def wait_for_code_side_effect(*args, **kwargs):
            current = state[0]
            if current == 0:
                state[0] = 1
                fake_mailbox._last_matched_message_id = "m-1"
                return "654321"
            if current == 1:
                state[0] = 2
                raise TimeoutError("timeout")
            if current == 2:
                state[0] = 3
                fake_mailbox._last_matched_message_id = "m-2"
                return "123456"
            raise KeyboardInterrupt()

        fake_mailbox.wait_for_code.side_effect = wait_for_code_side_effect
        fake_mailbox._resolve_lookup_context.return_value = ("demo@example.com", "", "demo@example.com")
        fake_mailbox._list_mails.side_effect = [
            [
                {
                    "emailId": "m-1",
                    "toEmail": "demo@example.com",
                    "recipt": "alias@example.com",
                    "subject": "Your verification code is 654321",
                }
            ],
            [
                {
                    "emailId": "m-2",
                    "toEmail": "demo@example.com",
                    "recipient": '[{"address":"alias2@example.com","name":""}]',
                    "subject": "Your verification code is 123456",
                }
            ],
        ]
        fake_mailbox._mail_id.side_effect = lambda message, index: str(message.get("emailId") or "")
        fake_mailbox._mail_debug_summary.side_effect = (
            lambda message, index: (
                f"id={message.get('emailId')} toEmail={message.get('toEmail')} "
                f"recipient={message.get('recipt') or 'alias2@example.com'} subject={message.get('subject')}"
            )
        )
        printed = []
        errors = []

        with mock.patch.object(cloudmail_latest_code, "create_mailbox", return_value=fake_mailbox):
            exit_code = cloudmail_latest_code.run_polling(args, emit=printed.append, emit_error=errors.append)

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            printed,
            [
                "code=654321 id=m-1 toEmail=demo@example.com recipient=alias@example.com subject=Your verification code is 654321",
                "code=123456 id=m-2 toEmail=demo@example.com recipient=alias2@example.com subject=Your verification code is 123456",
            ],
        )
        self.assertEqual(fake_mailbox.wait_for_code.call_count, 4)
        self.assertTrue(any("未获取到新验证码" in message for message in errors))
        self.assertTrue(any("已停止轮询" in message for message in errors))

    def test_format_match_output_falls_back_to_message_id_when_summary_lookup_fails(self):
        mailbox = mock.Mock()
        mailbox._last_matched_message_id = "m-9"
        mailbox._resolve_lookup_context.side_effect = RuntimeError("boom")

        result = cloudmail_latest_code._format_match_output(
            mailbox,
            MailboxAccount(email="demo@example.com", account_id="demo@example.com"),
            "888888",
        )

        self.assertEqual(result, "code=888888 id=m-9")

    def test_run_polling_passes_keyword_and_custom_pattern(self):
        args = argparse.Namespace(
            api_base="https://cloudmail.example.com",
            admin_email="admin@example.com",
            admin_password="secret",
            domain="mail.example.com",
            subdomain="",
            email="demo@example.com",
            mailbox_email="real@mail.example.com",
            wait_timeout=90,
            keyword="ChatGPT",
            code_pattern=r"OTP[:\s]+(\d{6})",
            verbose=False,
        )
        fake_mailbox = mock.Mock()
        fake_mailbox.wait_for_code.side_effect = KeyboardInterrupt()

        with mock.patch.object(cloudmail_latest_code, "create_mailbox", return_value=fake_mailbox):
            exit_code = cloudmail_latest_code.run_polling(args, emit=lambda _: None, emit_error=lambda _: None)

        self.assertEqual(exit_code, 0)
        call = fake_mailbox.wait_for_code.call_args
        self.assertEqual(
            call.args[0],
            MailboxAccount(email="demo@example.com", account_id="real@mail.example.com"),
        )
        self.assertEqual(call.kwargs["keyword"], "ChatGPT")
        self.assertEqual(call.kwargs["timeout"], 90)
        self.assertEqual(call.kwargs["code_pattern"], r"OTP[:\s]+(\d{6})")


if __name__ == "__main__":
    unittest.main()
