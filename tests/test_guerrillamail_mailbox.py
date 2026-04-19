import unittest
from unittest import mock
from unittest.mock import patch

from core.base_mailbox import MailboxAccount, create_mailbox


class GuerrillaMailMailboxTests(unittest.TestCase):
    def _build_mailbox(self, **extra):
        config = {
            "guerrillamail_api_url": "https://api.guerrillamail.com/ajax.php",
        }
        config.update(extra)
        return create_mailbox("guerrillamail", extra=config)

    @patch("requests.Session")
    def test_get_email_creates_mailbox_with_random_verified_domain(self, mock_session_cls):
        session = mock.Mock()
        mock_session_cls.return_value = session
        session.get.side_effect = [
            _response(
                {
                    "email_addr": "initial@sharklasers.com",
                    "email_timestamp": 1776586635,
                    "sid_token": "sid-0",
                }
            ),
            _response(
                {
                    "email_addr": "demo123@guerrillamail.net",
                    "email_timestamp": 1776586636,
                    "sid_token": "sid-1",
                }
            ),
        ]

        mailbox = self._build_mailbox()

        with patch.object(type(mailbox), "_generate_local_part", return_value="demo123"), patch(
            "random.choice", return_value="guerrillamail.net"
        ):
            account = mailbox.get_email()

        self.assertEqual(account.email, "demo123@guerrillamail.net")
        self.assertEqual(account.account_id, "sid-1")
        self.assertEqual(
            account.extra,
            {
                "provider": "guerrillamail",
                "domain": "guerrillamail.net",
                "email_user": "demo123",
                "canonical_email": "demo123@guerrillamail.net",
            },
        )
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(
            session.get.call_args_list[0].kwargs["params"],
            {"f": "get_email_address", "lang": "en"},
        )
        self.assertEqual(
            session.get.call_args_list[1].kwargs["params"],
            {
                "f": "set_email_user",
                "email_user": "demo123",
                "lang": "en",
                "sid_token": "sid-0",
            },
        )

    @patch("requests.Session")
    def test_get_current_ids_reads_mail_list(self, mock_session_cls):
        session = mock.Mock()
        mock_session_cls.return_value = session
        session.get.return_value = _response(
            {
                "list": [
                    {"mail_id": "m1", "mail_subject": "Hello"},
                    {"mail_id": "m2", "mail_subject": "World"},
                ]
            }
        )

        mailbox = self._build_mailbox()
        mailbox._session = session
        ids = mailbox.get_current_ids(
            MailboxAccount(email="demo@guerrillamail.net", account_id="sid-1")
        )

        self.assertEqual(ids, {"m1", "m2"})
        session.get.assert_called_once_with(
            "https://api.guerrillamail.com/ajax.php",
            params={"f": "get_email_list", "offset": 0, "sid_token": "sid-1"},
            timeout=10,
        )

    @patch("requests.Session")
    def test_wait_for_code_respects_before_ids_and_otp_sent_at(self, mock_session_cls):
        session = mock.Mock()
        mock_session_cls.return_value = session
        session.get.side_effect = [
            _response(
                {
                    "list": [
                        {
                            "mail_id": "m1",
                            "mail_subject": "Your code 111111",
                            "mail_timestamp": 100,
                        },
                        {
                            "mail_id": "m2",
                            "mail_subject": "Your code 222222",
                            "mail_timestamp": 150,
                        },
                        {
                            "mail_id": "m3",
                            "mail_subject": "Your code 333333",
                            "mail_timestamp": 250,
                        },
                    ]
                }
            ),
            _response(
                {
                    "mail_id": "m3",
                    "mail_subject": "verification code",
                    "mail_body": "verification code 333333",
                }
            ),
        ]

        mailbox = self._build_mailbox()
        mailbox._session = session
        code = mailbox.wait_for_code(
            MailboxAccount(email="demo@guerrillamail.net", account_id="sid-1"),
            timeout=5,
            before_ids={"m1"},
            otp_sent_at=200,
        )

        self.assertEqual(code, "333333")
        self.assertEqual(mailbox._last_matched_message_id, "m3")
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(
            session.get.call_args_list[1].kwargs["params"],
            {"f": "fetch_email", "email_id": "m3", "sid_token": "sid-1"},
        )

    @patch("requests.Session")
    def test_wait_for_code_skips_excluded_message_ids_and_tracks_last_message_id(self, mock_session_cls):
        session = mock.Mock()
        mock_session_cls.return_value = session
        session.get.side_effect = [
            _response(
                {
                    "list": [
                        {"mail_id": "m1", "mail_subject": "Your code 111111", "mail_timestamp": 200},
                        {"mail_id": "m2", "mail_subject": "Your code 222222", "mail_timestamp": 201},
                    ]
                }
            ),
            _response(
                {
                    "mail_id": "m2",
                    "mail_subject": "Your code 222222",
                    "mail_body": "verification code 222222",
                }
            ),
        ]

        mailbox = self._build_mailbox()
        mailbox._session = session
        code = mailbox.wait_for_code(
            MailboxAccount(email="demo@guerrillamail.net", account_id="sid-1"),
            timeout=5,
            exclude_codes={"m1"},
        )

        self.assertEqual(code, "222222")
        self.assertEqual(mailbox._last_matched_message_id, "m2")
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(
            session.get.call_args_list[1].kwargs["params"],
            {"f": "fetch_email", "email_id": "m2", "sid_token": "sid-1"},
        )


def _response(payload, status_code=200):
    response = mock.Mock()
    response.status_code = status_code
    response.json.return_value = payload
    response.text = ""
    return response


if __name__ == "__main__":
    unittest.main()
