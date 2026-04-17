import unittest

from core.alias_pool.mailbox_verification_adapter import (
    build_mailbox_email_list_request,
    build_mailbox_login_request,
    extract_anchored_link_from_message_content,
    extract_token_from_storage,
    with_token_in_session_storage,
)


class MailboxVerificationAdapterTests(unittest.TestCase):
    def test_build_mailbox_login_request_uses_configured_base_url_and_credentials(self):
        request = build_mailbox_login_request(
            mailbox_base_url="https://mailbox.example",
            mailbox_email="admin@example.com",
            mailbox_password="secret-pass",
        )

        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["url"], "https://mailbox.example/api/login")
        self.assertEqual(
            request["json"],
            {
                "email": "admin@example.com",
                "password": "secret-pass",
            },
        )

    def test_with_token_in_session_storage_uses_local_storage_token_key(self):
        storage = with_token_in_session_storage({}, "token-123")

        self.assertEqual(storage, {"token": "token-123"})

    def test_with_token_in_session_storage_returns_copy_without_mutating_existing_dict(self):
        existing_storage = {"existing": "value"}

        updated_storage = with_token_in_session_storage(existing_storage, "token-123")

        self.assertIsNot(updated_storage, existing_storage)
        self.assertEqual(existing_storage, {"existing": "value"})
        self.assertEqual(
            updated_storage,
            {"existing": "value", "token": "token-123"},
        )

    def test_extract_token_from_storage_reads_string_token(self):
        token = extract_token_from_storage({"token": "token-123", "other": "ignored"})

        self.assertEqual(token, "token-123")

    def test_build_mailbox_email_list_request_uses_configured_base_url_and_authorization_header(self):
        request = build_mailbox_email_list_request(
            mailbox_base_url="https://mailbox.example",
            token="token-123",
        )

        self.assertEqual(request["method"], "GET")
        self.assertEqual(request["url"], "https://mailbox.example/api/email/list")
        self.assertEqual(
            request["params"],
            {
                "accountId": 1,
                "allReceive": 1,
                "emailId": 0,
                "timeSort": 0,
                "size": 100,
                "type": 0,
            },
        )
        self.assertEqual(request["headers"], {"authorization": "token-123"})

    def test_extract_anchored_link_from_message_content_returns_first_contiguous_substring_starting_at_anchor(self):
        message = """
        Hello there,
        Please confirm your account:
        https://mail.example.com/auth/confirmation?confirmation_token=abc123DEF
        Thank you.
        """

        link = extract_anchored_link_from_message_content(
            message,
            link_anchor="https://mail.example.com/auth/confirmation",
        )

        self.assertEqual(
            link,
            "https://mail.example.com/auth/confirmation?confirmation_token=abc123DEF",
        )

    def test_extract_anchored_link_from_message_content_stops_at_first_delimiter_after_anchor(self):
        message = (
            "Click here: "
            "https://mail.example.com/auth/confirmation?confirmation_token=abc123DEF>"
            "ignored"
        )

        link = extract_anchored_link_from_message_content(
            message,
            link_anchor="https://mail.example.com/auth/confirmation",
        )

        self.assertEqual(
            link,
            "https://mail.example.com/auth/confirmation?confirmation_token=abc123DEF",
        )

    def test_extract_anchored_link_from_message_content_returns_empty_string_when_anchor_does_not_match(self):
        self.assertEqual(
            extract_anchored_link_from_message_content(
                "https://www.vend.email/auth/confirmation?confirmation_token=abc123DEF",
                link_anchor="https://mail.example.com/auth/confirmation",
            ),
            "",
        )

    def test_extract_anchored_link_from_message_content_returns_empty_string_when_message_has_no_anchor(self):
        self.assertEqual(
            extract_anchored_link_from_message_content(
                "no confirmation link here",
                link_anchor="https://mail.example.com/auth/confirmation",
            ),
            "",
        )


if __name__ == "__main__":
    unittest.main()
