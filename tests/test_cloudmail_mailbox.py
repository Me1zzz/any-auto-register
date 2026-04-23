import unittest
from typing import cast
from unittest import mock

from core.alias_pool.base import AliasEmailLease
from core.base_mailbox import CloudMailMailbox, MailboxAccount, create_mailbox


class CloudMailMailboxTests(unittest.TestCase):
    def setUp(self):
        CloudMailMailbox._token_cache.clear()
        CloudMailMailbox._seen_ids.clear()
        CloudMailMailbox._skip_logged_ids.clear()
        CloudMailMailbox._alias_pools.clear()

    def test_get_email_uses_configured_domain(self):
        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
            },
        )

        account = mailbox.get_email()

        self.assertTrue(account.email.endswith("@mail.example.com"))
        self.assertEqual(account.account_id, account.email)
        self.assertEqual(account.extra, {})

    def test_get_email_supports_legacy_field_names(self):
        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "base_url": "https://cloudmail.example.com",
                "admin_password": "secret",
                "domain": "mail.example.com",
                "subdomain": "pool-a",
            },
        )

        account = mailbox.get_email()

        self.assertTrue(account.email.endswith("@pool-a.mail.example.com"))
        self.assertEqual(account.account_id, account.email)

    def test_get_email_uses_preconfigured_alias_when_enabled(self):
        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
                "cloudmail_alias_enabled": "1",
                "cloudmail_alias_emails": "alias1@alias.example.com\nalias2@alias.example.com",
            },
        )

        with mock.patch("random.choice", return_value="alias2@alias.example.com"):
            account = mailbox.get_email()

        self.assertEqual(account.email, "alias2@alias.example.com")
        self.assertEqual(account.account_id, "")
        self.assertEqual(
            account.extra,
            {
                "mailbox_alias": {
                    "enabled": True,
                    "alias_email": "alias2@alias.example.com",
                    "mailbox_email": "",
                }
            },
        )

    def test_get_email_allows_alias_without_real_mailbox(self):
        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
                "cloudmail_alias_enabled": "1",
                "cloudmail_alias_emails": "alias2@alias.example.com",
            },
        )

        account = mailbox.get_email()

        self.assertEqual(account.email, "alias2@alias.example.com")
        self.assertEqual(account.account_id, "")
        self.assertEqual(
            account.extra,
            {
                "mailbox_alias": {
                    "enabled": True,
                    "alias_email": "alias2@alias.example.com",
                    "mailbox_email": "",
                }
            },
        )

    def test_get_email_does_not_repeat_alias_within_same_task_pool(self):
        mailbox_a = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
                "cloudmail_alias_enabled": "1",
                "cloudmail_alias_emails": "alias1@alias.example.com\nalias2@alias.example.com",
            },
        )
        mailbox_b = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
                "cloudmail_alias_enabled": "1",
                "cloudmail_alias_emails": "alias1@alias.example.com\nalias2@alias.example.com",
            },
        )
        assert isinstance(mailbox_a, CloudMailMailbox)
        assert isinstance(mailbox_b, CloudMailMailbox)
        mailbox_a._task_alias_pool_key = "task-1"
        mailbox_b._task_alias_pool_key = "task-1"

        with mock.patch("random.shuffle", side_effect=lambda items: None):
            account_a = mailbox_a.get_email()
            account_b = mailbox_b.get_email()

        self.assertEqual(account_a.email, "alias1@alias.example.com")
        self.assertEqual(account_b.email, "alias2@alias.example.com")

    def test_get_email_raises_when_task_alias_pool_is_exhausted(self):
        mailbox_a = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
                "cloudmail_alias_enabled": "1",
                "cloudmail_alias_emails": "alias1@alias.example.com",
            },
        )
        mailbox_b = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
                "cloudmail_alias_enabled": "1",
                "cloudmail_alias_emails": "alias1@alias.example.com",
            },
        )
        assert isinstance(mailbox_a, CloudMailMailbox)
        assert isinstance(mailbox_b, CloudMailMailbox)
        mailbox_a._task_alias_pool_key = "task-1"
        mailbox_b._task_alias_pool_key = "task-1"

        mailbox_a.get_email()
        with self.assertRaises(RuntimeError):
            mailbox_b.get_email()

    def test_get_email_prefers_task_alias_pool_lease_over_legacy_alias_list(self):
        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
                "cloudmail_alias_enabled": "1",
                "cloudmail_alias_emails": "legacy1@alias.example.com\nlegacy2@alias.example.com",
            },
        )
        assert isinstance(mailbox, CloudMailMailbox)
        mailbox = cast(CloudMailMailbox, mailbox)
        lease = AliasEmailLease(
            alias_email="lease@alias.example.com",
            real_mailbox_email="lease-real@mail.example.com",
            source_kind="static_list",
            source_id="legacy-static",
            source_session_id="session-1",
        )
        mailbox._task_alias_pool = mock.Mock(acquire_alias=mock.Mock(return_value=lease))

        with mock.patch.object(
            mailbox,
            "_pick_alias_email",
            side_effect=AssertionError("legacy alias fallback should not run when a lease is available"),
        ):
            account = mailbox.get_email()

        self.assertEqual(account.email, "lease@alias.example.com")
        self.assertEqual(account.account_id, "lease-real@mail.example.com")
        self.assertEqual(mailbox._last_alias_lease, lease)
        self.assertEqual(
            account.extra,
            {
                "mailbox_alias": {
                    "enabled": True,
                    "alias_email": "lease@alias.example.com",
                    "mailbox_email": "lease-real@mail.example.com",
                }
            },
        )
        mailbox._task_alias_pool.acquire_alias.assert_called_once_with()

    def test_get_email_prefers_public_alias_consumer_context(self):
        mailbox = CloudMailMailbox(
            api_base="https://mail.example/api",
            admin_email="admin@example.com",
            admin_password="secret-pass",
            alias_enabled=True,
        )
        lease = AliasEmailLease(
            alias_email="alias@example.com",
            real_mailbox_email="real@example.com",
            source_kind="static_list",
            source_id="legacy-static",
            source_session_id="task-1",
        )
        context = mock.Mock()
        context.acquire_alias_lease.return_value = lease

        mailbox.bind_alias_consumer(context)
        consumed = mailbox._consume_alias_lease()

        self.assertIs(consumed, lease)
        context.acquire_alias_lease.assert_called_once_with()

    def test_release_alias_pool_resets_task_alias_allocation(self):
        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
                "cloudmail_alias_enabled": "1",
                "cloudmail_alias_emails": "alias1@alias.example.com\nalias2@alias.example.com",
            },
        )
        assert isinstance(mailbox, CloudMailMailbox)
        mailbox._task_alias_pool_key = "task-1"

        with mock.patch("random.shuffle", side_effect=lambda items: None):
            first = mailbox.get_email()
            CloudMailMailbox.release_alias_pool("task-1")
            second = mailbox.get_email()

        self.assertEqual(first.email, "alias1@alias.example.com")
        self.assertEqual(second.email, "alias1@alias.example.com")

    @mock.patch("requests.post")
    def test_wait_for_code_retries_after_auth_failure(self, mock_post):
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

        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
            },
        )
        account = MailboxAccount(email="demo@example.com", account_id="demo@example.com")

        code = mailbox.wait_for_code(account, timeout=5)

        self.assertEqual(code, "654321")
        self.assertEqual(mock_post.call_count, 4)

    @mock.patch("requests.post")
    def test_wait_for_code_uses_fixed_three_second_poll_interval(self, mock_post):
        mock_post.side_effect = [
            _json_response({"code": 200, "data": {"token": "tok-1"}}),
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

        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
            },
        )
        account = MailboxAccount(email="demo@example.com", account_id="demo@example.com")

        with mock.patch.object(
            mailbox, "_run_polling_wait", wraps=mailbox._run_polling_wait
        ) as polling_mock:
            code = mailbox.wait_for_code(account, timeout=5)

        self.assertEqual(code, "654321")
        self.assertEqual(polling_mock.call_args.kwargs["poll_interval"], 3)

    @mock.patch("requests.post")
    def test_wait_for_code_filters_by_recipt_for_alias(self, mock_post):
        mock_post.side_effect = [
            _json_response({"code": 200, "data": {"token": "tok-1"}}),
            _json_response(
                {
                    "code": 200,
                    "data": [
                        {
                            "emailId": "m-1",
                            "toEmail": "real@mail.example.com",
                            "recipt": "other@alias.example.com",
                            "subject": "Your verification code is 111111",
                            "content": "",
                        },
                        {
                            "emailId": "m-2",
                            "toEmail": "real@mail.example.com",
                            "recipt": "alias@alias.example.com",
                            "subject": "Your verification code is 654321",
                            "content": "",
                        }
                    ],
                }
            ),
        ]

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
            email="alias@alias.example.com",
            account_id="real@mail.example.com",
        )

        code = mailbox.wait_for_code(account, timeout=5)

        self.assertEqual(code, "654321")
        self.assertEqual(mock_post.call_args_list[1].kwargs["json"]["toEmail"], "alias@alias.example.com")

    @mock.patch("requests.post")
    def test_wait_for_code_filters_by_recipient_json_string_for_alias(self, mock_post):
        mock_post.side_effect = [
            _json_response({"code": 200, "data": {"token": "tok-1"}}),
            _json_response(
                {
                    "code": 200,
                    "data": [
                        {
                            "emailId": 64,
                            "toEmail": "sss@me1zzz.tech",
                            "recipient": '[{"address":"other@dralias.com","name":""}]',
                            "subject": "Your ChatGPT code is 111111",
                            "text": None,
                        },
                        {
                            "emailId": 65,
                            "toEmail": "sss@me1zzz.tech",
                            "recipient": '[{"address":"lunar.emoticon487@dralias.com","name":""}]',
                            "subject": "Your ChatGPT code is 267510",
                            "text": None,
                        },
                    ],
                }
            ),
        ]

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
            email="lunar.emoticon487@dralias.com",
            account_id="sss@me1zzz.tech",
        )

        code = mailbox.wait_for_code(account, timeout=5)

        self.assertEqual(code, "267510")
        self.assertEqual(mock_post.call_args_list[1].kwargs["json"]["toEmail"], "lunar.emoticon487@dralias.com")

    @mock.patch("requests.post")
    def test_wait_for_code_matches_alias_when_sender_contains_alias(self, mock_post):
        mock_post.side_effect = [
            _json_response({"code": 200, "data": {"token": "tok-1"}}),
            _json_response(
                {
                    "code": 200,
                    "data": [
                        {
                            "emailId": "m-1",
                            "toEmail": "real@mail.example.com",
                            "recipient": '[{"address":"other@alias.example.com","name":""}]',
                            "from": "OpenAI <alias@alias.example.com>",
                            "subject": "Your verification code is 654321",
                            "content": "",
                        }
                    ],
                }
            ),
        ]

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
            email="alias@alias.example.com",
            account_id="real@mail.example.com",
        )

        code = mailbox.wait_for_code(account, timeout=5)

        self.assertEqual(code, "654321")

    @mock.patch("requests.post")
    def test_wait_for_code_matches_alias_when_send_email_contains_alias(self, mock_post):
        mock_post.side_effect = [
            _json_response({"code": 200, "data": {"token": "tok-1"}}),
            _json_response(
                {
                    "code": 200,
                    "data": [
                        {
                            "emailId": "m-1",
                            "toEmail": "real@mail.example.com",
                            "recipient": '[{"address":"other@alias.example.com","name":""}]',
                            "sendEmail": "alias@alias.example.com",
                            "sendName": "OpenAI",
                            "subject": "Your verification code is 654321",
                            "content": "",
                        }
                    ],
                }
            ),
        ]

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
            email="alias@alias.example.com",
            account_id="real@mail.example.com",
        )

        code = mailbox.wait_for_code(account, timeout=5)

        self.assertEqual(code, "654321")

    @mock.patch("requests.post")
    def test_wait_for_code_accepts_mailbox_fallback_when_alias_recipient_metadata_is_missing(self, mock_post):
        mock_post.side_effect = [
            _json_response({"code": 200, "data": {"token": "tok-1"}}),
            _json_response({"code": 200, "data": []}),
            _json_response(
                {
                    "code": 200,
                    "data": [
                        {
                            "emailId": "m-1",
                            "toEmail": "admin@cxwsss.online",
                            "recipient": "admin@cxwsss.online",
                            "subject": "Your ChatGPT code is 654321",
                            "content": "",
                        }
                    ],
                }
            ),
        ]

        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
            },
        )
        assert isinstance(mailbox, CloudMailMailbox)
        logs = []
        setattr(mailbox, "_log_fn", logs.append)
        account = MailboxAccount(
            email="alias@myalias.pro",
            account_id="admin@cxwsss.online",
        )

        code = mailbox.wait_for_code(account, timeout=5)

        self.assertEqual(code, "654321")
        self.assertIn("enabled mailbox fallback", "\n".join(logs))
        self.assertEqual(mock_post.call_args_list[1].kwargs["json"]["toEmail"], "alias@myalias.pro")
        self.assertEqual(mock_post.call_args_list[2].kwargs["json"]["toEmail"], "admin@cxwsss.online")

    @mock.patch("requests.post")
    def test_wait_for_code_prefers_send_email_over_legacy_from(self, mock_post):
        mock_post.side_effect = [
            _json_response({"code": 200, "data": {"token": "tok-1"}}),
            _json_response(
                {
                    "code": 200,
                    "data": [
                        {
                            "emailId": "m-1",
                            "toEmail": "real@mail.example.com",
                            "recipient": '[{"address":"other@alias.example.com","name":""}]',
                            "sendEmail": "alias@alias.example.com",
                            "from": "OpenAI <support@example.com>",
                            "subject": "Your verification code is 654321",
                            "content": "",
                        }
                    ],
                }
            ),
        ]

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
            email="alias@alias.example.com",
            account_id="real@mail.example.com",
        )

        code = mailbox.wait_for_code(account, timeout=5)

        self.assertEqual(code, "654321")

    @mock.patch("requests.post")
    def test_wait_for_code_matches_alias_when_body_contains_alias(self, mock_post):
        mock_post.side_effect = [
            _json_response({"code": 200, "data": {"token": "tok-1"}}),
            _json_response(
                {
                    "code": 200,
                    "data": [
                        {
                            "emailId": "m-1",
                            "toEmail": "real@mail.example.com",
                            "recipient": '[{"address":"other@alias.example.com","name":""}]',
                            "from": "OpenAI <support@example.com>",
                            "subject": "Your verification code is 654321",
                            "content": "Delivery target: alias@alias.example.com",
                        }
                    ],
                }
            ),
        ]

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
            email="alias@alias.example.com",
            account_id="real@mail.example.com",
        )

        code = mailbox.wait_for_code(account, timeout=5)

        self.assertEqual(code, "654321")

    @mock.patch("requests.post")
    def test_get_current_ids_filters_by_recipient_when_real_mailbox_missing(self, mock_post):
        mock_post.side_effect = [
            _json_response({"code": 200, "data": {"token": "tok-1"}}),
            _json_response(
                {
                    "code": 200,
                    "data": [
                        {
                            "emailId": "m-1",
                            "toEmail": "other@mail.example.com",
                            "recipient": '[{"address":"other@alias.example.com","name":""}]',
                            "subject": "Your verification code is 111111",
                            "content": "",
                        },
                        {
                            "emailId": "m-2",
                            "toEmail": "shared@mail.example.com",
                            "recipient": '[{"address":"alias@alias.example.com","name":""}]',
                            "subject": "Your verification code is 654321",
                            "content": "",
                        },
                    ],
                }
            ),
        ]

        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
            },
        )
        account = MailboxAccount(email="alias@alias.example.com", account_id="")

        current_ids = mailbox.get_current_ids(account)

        self.assertEqual(current_ids, {"m-2"})
        self.assertEqual(mock_post.call_args_list[1].kwargs["json"]["toEmail"], "alias@alias.example.com")

    @mock.patch("requests.post")
    def test_wait_for_code_filters_by_recipient_when_real_mailbox_missing(self, mock_post):
        mock_post.side_effect = [
            _json_response({"code": 200, "data": {"token": "tok-1"}}),
            _json_response(
                {
                    "code": 200,
                    "data": [
                        {
                            "emailId": "m-1",
                            "toEmail": "other@mail.example.com",
                            "recipient": '[{"address":"other@alias.example.com","name":""}]',
                            "subject": "Your verification code is 111111",
                            "content": "",
                        },
                        {
                            "emailId": "m-2",
                            "toEmail": "shared@mail.example.com",
                            "recipient": '[{"address":"alias@alias.example.com","name":""}]',
                            "subject": "Your verification code is 654321",
                            "content": "",
                        },
                    ],
                }
            ),
        ]

        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
            },
        )
        account = MailboxAccount(email="alias@alias.example.com", account_id="")

        code = mailbox.wait_for_code(account, timeout=5)

        self.assertEqual(code, "654321")
        self.assertNotIn("toEmail", mock_post.call_args_list[1].kwargs["json"])

    @mock.patch("requests.post")
    def test_wait_for_code_times_out_when_recipient_missing_and_real_mailbox_missing(self, mock_post):
        mock_post.side_effect = [
            _json_response({"code": 200, "data": {"token": "tok-1"}}),
            _json_response(
                {
                    "code": 200,
                    "data": [
                        {
                            "emailId": "m-1",
                            "toEmail": "shared@mail.example.com",
                            "subject": "Your verification code is 654321",
                            "content": "",
                        }
                    ],
                }
            ),
        ]

        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
            },
        )
        account = MailboxAccount(email="alias@alias.example.com", account_id="")

        with self.assertRaises(TimeoutError):
            mailbox.wait_for_code(account, timeout=1)

    def test_match_alias_receipt_accepts_to_email_target(self):
        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
            },
        )

        message = {
            "recipient": '[{"address":"alias@myalias.pro","name":""}]',
            "toEmail": "generated@mail.example.com",
            "subject": "Please verify your account",
            "content": "No direct target email in body",
        }

        self.assertTrue(mailbox._match_alias_receipt(message, "generated@mail.example.com"))

    @mock.patch("requests.post")
    def test_wait_for_code_returns_duplicate_code_when_not_explicitly_excluded(self, mock_post):
        mock_post.side_effect = [
            _json_response({"code": 200, "data": {"token": "tok-1"}}),
            _json_response(
                {
                    "code": 200,
                    "data": [
                        {
                            "emailId": "m-1",
                            "toEmail": "demo@example.com",
                            "subject": "Your verification code is 654321",
                            "content": "",
                        },
                        {
                            "emailId": "m-2",
                            "toEmail": "demo@example.com",
                            "subject": "Your verification code is 123456",
                            "content": "",
                        },
                    ],
                }
            ),
        ]

        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
            },
        )
        account = MailboxAccount(email="demo@example.com", account_id="demo@example.com")

        code = mailbox.wait_for_code(
            account,
            timeout=5,
            exclude_codes={"111111"},
        )

        self.assertEqual(code, "654321")

    @mock.patch("requests.post")
    def test_wait_for_code_skips_excluded_email_and_continues_scanning(self, mock_post):
        mock_post.side_effect = [
            _json_response({"code": 200, "data": {"token": "tok-1"}}),
            _json_response(
                {
                    "code": 200,
                    "data": [
                        {
                            "emailId": "m-1",
                            "toEmail": "demo@example.com",
                            "subject": "Your verification code is 654321",
                            "content": "",
                        },
                        {
                            "emailId": "m-2",
                            "toEmail": "demo@example.com",
                            "subject": "Your verification code is 123456",
                            "content": "",
                        },
                    ],
                }
            ),
        ]

        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
            },
        )
        account = MailboxAccount(email="demo@example.com", account_id="demo@example.com")

        code = mailbox.wait_for_code(
            account,
            timeout=1,
            exclude_codes={"m-1"},
        )

        self.assertEqual(code, "123456")

    @mock.patch("requests.post")
    def test_list_mails_logs_sanitized_response_without_content(self, mock_post):
        mock_post.side_effect = [
            _json_response({"code": 200, "data": {"token": "tok-1"}}),
            _json_response(
                {
                    "code": 200,
                    "data": [
                        {
                            "emailId": "m-1",
                            "toEmail": "real@mail.example.com",
                            "recipt": "alias@alias.example.com",
                            "subject": "Your verification code is 654321",
                            "content": "very large body",
                        }
                    ],
                }
            ),
        ]

        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
            },
        )
        assert isinstance(mailbox, CloudMailMailbox)
        logs = []
        setattr(mailbox, "_log_fn", logs.append)

        mails = mailbox._list_mails("real@mail.example.com")

        self.assertEqual(len(mails), 1)
        joined_logs = "\n".join(logs)
        self.assertIn("emailList 响应", joined_logs)
        self.assertIn("recipient=alias@alias.example.com", joined_logs)
        self.assertIn("subject=Your verification code is 654321", joined_logs)
        self.assertNotIn("very large body", joined_logs)
        self.assertNotIn('"content"', joined_logs)

    @mock.patch("requests.post")
    def test_wait_for_code_logs_reason_when_alias_does_not_match(self, mock_post):
        mock_post.side_effect = [
            _json_response({"code": 200, "data": {"token": "tok-1"}}),
            _json_response(
                {
                    "code": 200,
                    "data": [
                        {
                            "emailId": "m-1",
                            "toEmail": "real@mail.example.com",
                            "recipient": '[{"address":"other@alias.example.com","name":""}]',
                            "subject": "Your verification code is 111111",
                            "content": "",
                        }
                    ],
                }
            ),
        ]

        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
            },
        )
        assert isinstance(mailbox, CloudMailMailbox)
        assert isinstance(mailbox, CloudMailMailbox)
        logs = []
        setattr(mailbox, "_log_fn", logs.append)
        account = MailboxAccount(
            email="alias@alias.example.com",
            account_id="real@mail.example.com",
        )

        with self.assertRaises(TimeoutError):
            mailbox.wait_for_code(account, timeout=1)

        joined_logs = "\n".join(logs)
        self.assertIn("跳过邮件: alias 不匹配", joined_logs)
        self.assertIn("recipient=other@alias.example.com", joined_logs)

    @mock.patch("requests.post")
    def test_wait_for_code_logs_reason_when_code_is_excluded(self, mock_post):
        mock_post.side_effect = [
            _json_response({"code": 200, "data": {"token": "tok-1"}}),
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

        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
            },
        )
        assert isinstance(mailbox, CloudMailMailbox)
        logs = []
        setattr(mailbox, "_log_fn", logs.append)
        account = MailboxAccount(email="demo@example.com", account_id="demo@example.com")

        with self.assertRaises(TimeoutError):
            mailbox.wait_for_code(account, timeout=1, exclude_codes={"m-1"})

        joined_logs = "\n".join(logs)
        self.assertIn("跳过邮件: 命中排除邮件 emailId=m-1", joined_logs)
        self.assertIn("subject=Your verification code is 654321", joined_logs)

    def test_wait_for_code_logs_skip_reason_only_once_per_message(self):
        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
            },
        )
        assert isinstance(mailbox, CloudMailMailbox)
        logs = []
        setattr(mailbox, "_log_fn", logs.append)
        account = MailboxAccount(
            email="alias@alias.example.com",
            account_id="real@mail.example.com",
        )
        repeated_mail = {
            "emailId": "m-1",
            "toEmail": "real@mail.example.com",
            "recipient": '[{"address":"other@alias.example.com","name":""}]',
            "subject": "Your verification code is 111111",
            "content": "",
        }

        def fake_run_polling_wait(*, poll_once, **kwargs):
            for _ in range(10):
                self.assertIsNone(poll_once())
            raise TimeoutError("等待验证码超时 (1s)")

        with mock.patch.object(mailbox, "_list_mails", return_value=[repeated_mail]), mock.patch.object(
            mailbox,
            "_run_polling_wait",
            side_effect=fake_run_polling_wait,
        ):
            with self.assertRaises(TimeoutError):
                mailbox.wait_for_code(account, timeout=1)

        alias_skip_logs = [line for line in logs if "跳过邮件: alias 不匹配" in line]
        self.assertEqual(len(alias_skip_logs), 1)

    def test_wait_for_code_logs_once_for_each_distinct_skipped_message(self):
        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
            },
        )
        assert isinstance(mailbox, CloudMailMailbox)
        logs = []
        setattr(mailbox, "_log_fn", logs.append)
        account = MailboxAccount(
            email="alias@alias.example.com",
            account_id="real@mail.example.com",
        )
        repeated_mails = [
            {
                "emailId": "m-1",
                "toEmail": "real@mail.example.com",
                "recipient": '[{"address":"other1@alias.example.com","name":""}]',
                "subject": "Your verification code is 111111",
                "content": "",
            },
            {
                "emailId": "m-2",
                "toEmail": "real@mail.example.com",
                "recipient": '[{"address":"other2@alias.example.com","name":""}]',
                "subject": "Your verification code is 222222",
                "content": "",
            },
        ]

        def fake_run_polling_wait(*, poll_once, **kwargs):
            for _ in range(10):
                self.assertIsNone(poll_once())
            raise TimeoutError("等待验证码超时 (1s)")

        with mock.patch.object(mailbox, "_list_mails", return_value=repeated_mails), mock.patch.object(
            mailbox,
            "_run_polling_wait",
            side_effect=fake_run_polling_wait,
        ):
            with self.assertRaises(TimeoutError):
                mailbox.wait_for_code(account, timeout=1)

        alias_skip_logs = [line for line in logs if "跳过邮件: alias 不匹配" in line]
        self.assertEqual(len(alias_skip_logs), 2)
        self.assertTrue(any("recipient=other1@alias.example.com" in line for line in alias_skip_logs))
        self.assertTrue(any("recipient=other2@alias.example.com" in line for line in alias_skip_logs))

    def test_wait_for_code_persists_skip_logs_for_same_account_across_retries(self):
        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
            },
        )
        assert isinstance(mailbox, CloudMailMailbox)
        logs = []
        setattr(mailbox, "_log_fn", logs.append)
        account = MailboxAccount(email="demo@example.com", account_id="demo@example.com")
        repeated_mail = {
            "emailId": "m-1",
            "toEmail": "demo@example.com",
            "subject": "Your verification code is 654321",
            "content": "",
        }

        with mock.patch.object(mailbox, "_list_mails", return_value=[repeated_mail]), mock.patch.object(
            mailbox,
            "_run_polling_wait",
            side_effect=lambda *, poll_once, **kwargs: poll_once(),
        ):
            self.assertIsNone(mailbox.wait_for_code(account, timeout=1, exclude_codes={"m-1"}))
            self.assertIsNone(mailbox.wait_for_code(account, timeout=1, exclude_codes={"m-1"}))

        exclude_logs = [line for line in logs if "跳过邮件: 命中排除邮件 emailId=m-1" in line]
        self.assertEqual(len(exclude_logs), 1)

    @mock.patch("requests.post")
    def test_wait_for_code_does_not_exclude_different_email_with_same_code(self, mock_post):
        mock_post.side_effect = [
            _json_response({"code": 200, "data": {"token": "tok-1"}}),
            _json_response(
                {
                    "code": 200,
                    "data": [
                        {
                            "emailId": "m-1",
                            "toEmail": "demo@example.com",
                            "subject": "Your verification code is 654321",
                            "content": "",
                        },
                        {
                            "emailId": "m-2",
                            "toEmail": "demo@example.com",
                            "subject": "Your verification code is 654321",
                            "content": "",
                        },
                    ],
                }
            ),
        ]

        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
            },
        )
        account = MailboxAccount(email="demo@example.com", account_id="demo@example.com")

        code = mailbox.wait_for_code(account, timeout=5, exclude_codes={"m-1"})

        self.assertEqual(code, "654321")

    def test_wait_for_code_uses_randomized_poll_interval_for_cloudmail(self):
        mailbox = create_mailbox(
            "cloudmail",
            extra={
                "cloudmail_api_base": "https://cloudmail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_domain": "mail.example.com",
            },
        )
        assert isinstance(mailbox, CloudMailMailbox)
        account = MailboxAccount(email="demo@example.com", account_id="demo@example.com")

        with mock.patch.object(mailbox, "_run_polling_wait", return_value="123456") as mock_run_polling_wait:
            code = mailbox.wait_for_code(account, timeout=5)

        self.assertEqual(code, "123456")
        self.assertEqual(mock_run_polling_wait.call_args.kwargs["poll_interval"], 3)
        self.assertEqual(mock_run_polling_wait.call_args.kwargs["timeout"], 5)
        self.assertTrue(callable(mock_run_polling_wait.call_args.kwargs["poll_once"]))


def _json_response(payload: dict, status_code: int = 200):
    response = mock.Mock()
    response.status_code = status_code
    response.text = str(payload)
    response.json.return_value = payload
    return response


def _text_response(status_code: int, text: str):
    response = mock.Mock()
    response.status_code = status_code
    response.text = text
    response.json.side_effect = ValueError("not json")
    return response


if __name__ == "__main__":
    unittest.main()
