import argparse
import unittest
from unittest import mock

from core.base_mailbox import MailboxAccount, create_mailbox
from scripts import cloudmail_latest_code


def _json_response(payload, status_code=200, text=None):
    response = mock.Mock()
    response.status_code = status_code
    response.text = text if text is not None else str(payload)
    response.json.return_value = payload
    return response


def _text_response(status_code, text):
    response = mock.Mock()
    response.status_code = status_code
    response.text = text
    response.json.side_effect = ValueError("not json")
    return response


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

    def test_build_account_returns_empty_account_for_global_email_list_polling(self):
        args = argparse.Namespace(
            email="",
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

        self.assertEqual(account, MailboxAccount(email="", account_id=""))

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

    def test_scan_once_extracts_codes_and_skips_printed_ids(self):
        mailbox = mock.Mock()
        mailbox._resolve_lookup_context.return_value = ("", "", "")
        mailbox._list_mails.return_value = [
            {
                "emailId": "m-1",
                "toEmail": "a@example.com",
                "recipt": "alias1@example.com",
                "subject": "Your verification code is 654321",
            },
            {
                "emailId": "m-2",
                "toEmail": "b@example.com",
                "recipient": '[{"address":"alias2@example.com","name":""}]',
                "subject": "Your verification code is 123456",
            },
            {
                "emailId": "m-printed",
                "toEmail": "c@example.com",
                "subject": "Your verification code is 222222",
            },
        ]
        mailbox._match_alias_receipt.return_value = True
        mailbox._mail_id.side_effect = lambda message, index: str(message.get("emailId") or "")
        mailbox._safe_extract.side_effect = lambda text, pattern: "654321" if "654321" in text else ("123456" if "123456" in text else None)
        mailbox._mail_debug_summary.side_effect = (
            lambda message, index: (
                f"id={message.get('emailId')} toEmail={message.get('toEmail')} "
                f"recipient={message.get('recipt') or 'alias2@example.com'} subject={message.get('subject')}"
            )
        )
        printed_ids = {"m-printed"}

        lines = cloudmail_latest_code._scan_once(
            mailbox,
            MailboxAccount(email="", account_id=""),
            keyword="",
            code_pattern="",
            printed_ids=printed_ids,
        )

        self.assertEqual(
            lines,
            [
                "code=654321 id=m-1 toEmail=a@example.com recipient=alias1@example.com subject=Your verification code is 654321",
                "code=123456 id=m-2 toEmail=b@example.com recipient=alias2@example.com subject=Your verification code is 123456",
            ],
        )
        self.assertEqual(printed_ids, {"m-printed", "m-1", "m-2"})

    def test_scan_once_respects_alias_and_keyword_filters(self):
        mailbox = mock.Mock()
        mailbox._resolve_lookup_context.return_value = ("", "alias@example.com", "recipient:alias@example.com")
        mailbox._list_mails.return_value = [
            {
                "emailId": "m-1",
                "toEmail": "real@example.com",
                "subject": "Your verification code is 654321",
            },
            {
                "emailId": "m-2",
                "toEmail": "real@example.com",
                "subject": "ChatGPT verification code 123456",
            },
        ]
        mailbox._match_alias_receipt.side_effect = lambda message, alias: str(message.get("emailId")) == "m-2"
        mailbox._mail_id.side_effect = lambda message, index: str(message.get("emailId") or "")
        mailbox._safe_extract.side_effect = lambda text, pattern: "123456" if "123456" in text else None
        mailbox._mail_debug_summary.side_effect = lambda message, index: f"id={message.get('emailId')} toEmail={message.get('toEmail')} recipient=alias@example.com subject={message.get('subject')}"

        lines = cloudmail_latest_code._scan_once(
            mailbox,
            MailboxAccount(email="alias@example.com", account_id=""),
            keyword="ChatGPT",
            code_pattern="",
            printed_ids=set(),
        )

        self.assertEqual(
            lines,
            [
                "code=123456 id=m-2 toEmail=real@example.com recipient=alias@example.com subject=ChatGPT verification code 123456"
            ],
        )

    def test_scan_once_matches_alias_when_sender_contains_alias(self):
        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
            },
        )
        account = MailboxAccount(
            email="alias@example.com",
            account_id="real@example.com",
        )

        messages = [
            {
                "emailId": "m-1",
                "toEmail": "real@example.com",
                "recipient": '[{"address":"other@example.com","name":""}]',
                "from": "Support <alias@example.com>",
                "subject": "Your verification code is 123456",
                "content": "",
            }
        ]

        with mock.patch.object(mailbox, "_list_mails", return_value=messages):
            lines = cloudmail_latest_code._scan_once(
                mailbox,
                account,
                keyword="",
                code_pattern="",
                printed_ids=set(),
            )

        self.assertEqual(
            lines,
            [
                "code=123456 id=m-1 toEmail=real@example.com recipient=other@example.com subject=Your verification code is 123456"
            ],
        )

    def test_scan_once_matches_alias_when_send_email_contains_alias(self):
        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
            },
        )
        account = MailboxAccount(
            email="alias@example.com",
            account_id="real@example.com",
        )

        messages = [
            {
                "emailId": "m-1",
                "toEmail": "real@example.com",
                "recipient": '[{"address":"other@example.com","name":""}]',
                "sendEmail": "alias@example.com",
                "sendName": "Support",
                "subject": "Your verification code is 123456",
                "content": "",
            }
        ]

        with mock.patch.object(mailbox, "_list_mails", return_value=messages):
            lines = cloudmail_latest_code._scan_once(
                mailbox,
                account,
                keyword="",
                code_pattern="",
                printed_ids=set(),
            )

        self.assertEqual(
            lines,
            [
                "code=123456 id=m-1 toEmail=real@example.com recipient=other@example.com subject=Your verification code is 123456"
            ],
        )

    def test_scan_once_filters_shared_mailbox_by_alias_when_mailbox_email_provided(self):
        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
            },
        )
        account = MailboxAccount(
            email="alias@example.com",
            account_id="real@example.com",
        )

        messages = [
            {
                "emailId": "m-1",
                "toEmail": "real@example.com",
                "recipient": '[{"address":"other@example.com","name":""}]',
                "subject": "Your verification code is 654321",
                "content": "",
            },
            {
                "emailId": "m-2",
                "toEmail": "real@example.com",
                "recipient": '[{"address":"alias@example.com","name":""}]',
                "subject": "Your verification code is 123456",
                "content": "",
            },
        ]

        with mock.patch.object(mailbox, "_list_mails", return_value=messages):
            lines = cloudmail_latest_code._scan_once(
                mailbox,
                account,
                keyword="",
                code_pattern="",
                printed_ids=set(),
            )

        self.assertEqual(
            lines,
            [
                "code=123456 id=m-2 toEmail=real@example.com recipient=alias@example.com subject=Your verification code is 123456"
            ],
        )

    @mock.patch("scripts.cloudmail_latest_code.requests.post")
    def test_local_cloudmail_client_retries_after_auth_failure(self, mock_post):
        mock_post.side_effect = [
            _json_response({"code": 200, "data": {"token": "tok-1"}}),
            _text_response(401, "unauthorized"),
            _json_response({"code": 200, "data": {"token": "tok-2"}}),
            _json_response(
                {
                    "code": 200,
                    "data": [
                        {
                            "emailId": "m-1",
                            "toEmail": "demo@example.com",
                            "subject": "Your verification code is 654321",
                            "content": "",
                        }
                    ],
                }
            ),
        ]

        mailbox = cloudmail_latest_code.create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
            },
        )

        messages = mailbox._list_mails("demo@example.com")

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["emailId"], "m-1")
        self.assertEqual(mock_post.call_count, 4)
        self.assertEqual(mock_post.call_args_list[1].kwargs["json"]["toEmail"], "demo@example.com")
        self.assertEqual(mock_post.call_args_list[3].kwargs["headers"]["authorization"], "tok-2")

    @mock.patch("scripts.cloudmail_latest_code.requests.post")
    def test_local_cloudmail_client_omits_to_email_for_global_polling(self, mock_post):
        mock_post.side_effect = [
            _json_response({"code": 200, "data": {"token": "tok-1"}}),
            _json_response({"code": 200, "data": []}),
        ]

        mailbox = cloudmail_latest_code.create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
            },
        )

        mailbox._list_mails("")

        self.assertNotIn("toEmail", mock_post.call_args_list[1].kwargs["json"])

    def test_scan_once_uses_local_cloudmail_client_alias_matching(self):
        mailbox = cloudmail_latest_code.create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
            },
        )
        account = cloudmail_latest_code.MailboxAccount(
            email="alias@example.com",
            account_id="real@example.com",
        )

        messages = [
            {
                "emailId": "m-1",
                "toEmail": "real@example.com",
                "recipient": '[{"address":"other@example.com","name":""}]',
                "sendEmail": "alias@example.com",
                "subject": "Your verification code is 123456",
                "content": "",
            }
        ]

        with mock.patch.object(mailbox, "_list_mails", return_value=messages):
            lines = cloudmail_latest_code._scan_once(
                mailbox,
                account,
                keyword="",
                code_pattern="",
                printed_ids=set(),
            )

        self.assertEqual(
            lines,
            [
                "code=123456 id=m-1 toEmail=real@example.com recipient=other@example.com subject=Your verification code is 123456"
            ],
        )

    def test_run_polling_scans_every_cycle_and_deduplicates_by_message_id(self):
        args = argparse.Namespace(
            api_base="https://cloudmail.example.com",
            admin_email="admin@example.com",
            admin_password="secret",
            domain="mail.example.com",
            subdomain="",
            email="",
            mailbox_email="",
            wait_timeout=90,
            keyword="",
            code_pattern="",
            verbose=True,
        )
        fake_mailbox = mock.Mock()
        printed = []
        errors = []
        scan_results = [
            ["code=654321 id=m-1 toEmail=a@example.com recipient=x@example.com subject=Your verification code is 654321"],
            [],
            ["code=123456 id=m-2 toEmail=b@example.com recipient=y@example.com subject=Your verification code is 123456"],
            KeyboardInterrupt(),
        ]

        def scan_once_side_effect(*args, **kwargs):
            result = scan_results.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result

        with mock.patch.object(cloudmail_latest_code, "create_mailbox", return_value=fake_mailbox), mock.patch.object(
            cloudmail_latest_code,
            "_scan_once",
            side_effect=scan_once_side_effect,
        ) as mock_scan_once, mock.patch.object(cloudmail_latest_code.time, "sleep") as mock_sleep:
            exit_code = cloudmail_latest_code.run_polling(args, emit=printed.append, emit_error=errors.append)

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            printed,
            [
                "code=654321 id=m-1 toEmail=a@example.com recipient=x@example.com subject=Your verification code is 654321",
                "code=123456 id=m-2 toEmail=b@example.com recipient=y@example.com subject=Your verification code is 123456",
            ],
        )
        self.assertEqual(mock_scan_once.call_count, 4)
        self.assertEqual(mock_sleep.call_count, 3)
        mock_sleep.assert_called_with(0.1)
        self.assertTrue(any("已停止轮询" in message for message in errors))

    def test_run_polling_logs_error_and_continues_when_verbose(self):
        args = argparse.Namespace(
            api_base="https://cloudmail.example.com",
            admin_email="admin@example.com",
            admin_password="secret",
            domain="mail.example.com",
            subdomain="",
            email="",
            mailbox_email="",
            wait_timeout=90,
            keyword="",
            code_pattern="",
            verbose=True,
        )
        fake_mailbox = mock.Mock()
        errors = []
        scan_results = [RuntimeError("boom"), KeyboardInterrupt()]

        def scan_once_side_effect(*args, **kwargs):
            result = scan_results.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result

        with mock.patch.object(cloudmail_latest_code, "create_mailbox", return_value=fake_mailbox), mock.patch.object(
            cloudmail_latest_code,
            "_scan_once",
            side_effect=scan_once_side_effect,
        ), mock.patch.object(cloudmail_latest_code.time, "sleep") as mock_sleep:
            exit_code = cloudmail_latest_code.run_polling(args, emit=lambda _: None, emit_error=errors.append)

        self.assertEqual(exit_code, 0)
        self.assertTrue(any("轮询失败: boom" in message for message in errors))
        self.assertTrue(any("已停止轮询" in message for message in errors))
        mock_sleep.assert_called_with(0.1)


if __name__ == "__main__":
    unittest.main()
