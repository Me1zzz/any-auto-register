import unittest
from typing import cast

from core.alias_pool.secureinseconds_service import (
    SecureInSecondsRuntime,
    extract_secureinseconds_forwarding_verify_link,
    normalize_secureinseconds_alias_items,
    normalize_secureinseconds_forwarding_emails,
)
from core.http_client import HTTPClient


class _FakeCookieJar(list):
    def set(self, name, value, **kwargs):
        self.append(_FakeCookie(name=name, value=value, **kwargs))

    def clear(self):
        del self[:]


class _FakeCookie:
    def __init__(self, *, name, value, domain="", path="/", secure=False, expires=None):
        self.name = name
        self.value = value
        self.domain = domain
        self.path = path
        self.secure = secure
        self.expires = expires


class _FakeSession:
    def __init__(self):
        self.cookies = _FakeCookieJar()


class _FakeResponse:
    def __init__(self, *, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text else ("" if payload is None else str(payload))

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeHTTPClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.session = _FakeSession()

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        if not self.responses:
            raise AssertionError(f"unexpected request {method} {url}")
        return self.responses.pop(0)


class SecureInSecondsServiceTests(unittest.TestCase):
    def test_normalize_forwarding_emails_prefers_forwarding_emails_shape(self):
        items = normalize_secureinseconds_forwarding_emails(
            {
                "forwardingEmails": [
                    {"email": "Admin@cxwsss.online", "verified": True, "verifiedAt": "2026-04-22T12:56:20.242Z", "isPrimary": False},
                    {"email": "admin@cxwsss.online", "verified": False},
                ]
            }
        )

        self.assertEqual(
            items,
            [
                {
                    "email": "admin@cxwsss.online",
                    "verified": True,
                    "verifiedAt": "2026-04-22T12:56:20.242Z",
                    "isPrimary": False,
                }
            ],
        )

    def test_normalize_alias_items_maps_alias_and_forward_to_emails(self):
        aliases = normalize_secureinseconds_alias_items(
            {
                "aliases": [
                    {
                        "alias": "SisDebug01@alias.secureinseconds.com",
                        "forwardToEmails": ["Admin@cxwsss.online"],
                        "description": "SIS automation verification",
                        "active": True,
                        "deletedAt": None,
                        "_id": "alias-1",
                    }
                ]
            }
        )

        self.assertEqual(
            aliases,
            [
                {
                    "alias": "sisdebug01@alias.secureinseconds.com",
                    "email": "sisdebug01@alias.secureinseconds.com",
                    "forwardToEmails": ["admin@cxwsss.online"],
                    "description": "SIS automation verification",
                    "active": True,
                    "deletedAt": "",
                    "aliasId": "alias-1",
                }
            ],
        )

    def test_extract_forwarding_verify_link_matches_forwarding_email(self):
        link = extract_secureinseconds_forwarding_verify_link(
            [
                {
                    "toEmail": "other@cxwsss.online",
                    "text": "Verify your SecureAlias email: https://alias.secureinseconds.com/api/user/emails/verify?token=skip-me",
                },
                {
                    "toEmail": "admin@cxwsss.online",
                    "text": "Verify your SecureAlias email: https://alias.secureinseconds.com/api/user/emails/verify?token=abc123",
                },
            ],
            forwarding_email="admin@cxwsss.online",
        )

        self.assertEqual(
            link,
            "https://alias.secureinseconds.com/api/user/emails/verify?token=abc123",
        )

    def test_runtime_login_account_uses_nextauth_credentials_sequence(self):
        client = _FakeHTTPClient(
            [
                _FakeResponse(payload={"credentials": {}}),
                _FakeResponse(payload={"csrfToken": "csrf-token-123"}),
                _FakeResponse(payload={"ok": True}),
                _FakeResponse(payload={"user": {"email": "svcsecure01@cxwsss.online"}}),
            ]
        )
        runtime = SecureInSecondsRuntime(
            register_url="https://alias.secureinseconds.com/auth/register",
            login_url="https://alias.secureinseconds.com/auth/signin",
            http_client=cast(HTTPClient, client),
            mailbox_http_client=cast(HTTPClient, _FakeHTTPClient([])),
        )

        ok = runtime.login_account("svcsecure01@cxwsss.online", "SisA1@TestPass")

        self.assertTrue(ok)
        self.assertEqual(
            [call["url"] for call in client.calls],
            [
                "https://alias.secureinseconds.com/api/auth/providers",
                "https://alias.secureinseconds.com/api/auth/csrf",
                "https://alias.secureinseconds.com/api/auth/callback/credentials",
                "https://alias.secureinseconds.com/api/auth/session",
            ],
        )
        callback_request = client.calls[2]
        self.assertEqual(callback_request["kwargs"]["headers"]["Content-Type"], "application/x-www-form-urlencoded")
        self.assertIn("csrfToken=csrf-token-123", callback_request["kwargs"]["data"])
        self.assertIn("email=svcsecure01%40cxwsss.online", callback_request["kwargs"]["data"])

    def test_runtime_create_alias_returns_normalized_alias_record(self):
        client = _FakeHTTPClient(
            [
                _FakeResponse(
                    status_code=201,
                    payload={
                        "alias": {
                            "alias": "SisDebug01-rdig7x@alias.secureinseconds.com",
                            "forwardToEmails": ["admin@cxwsss.online"],
                            "description": "SIS automation verification",
                            "_id": "69e8c5a067ca4b11ba726a15",
                        }
                    },
                )
            ]
        )
        runtime = SecureInSecondsRuntime(
            register_url="https://alias.secureinseconds.com/auth/register",
            login_url="https://alias.secureinseconds.com/auth/signin",
            http_client=cast(HTTPClient, client),
            mailbox_http_client=cast(HTTPClient, _FakeHTTPClient([])),
        )

        alias_record = runtime.create_alias(
            prefix="sisdebug01",
            description="SIS automation verification",
            forward_to_emails=["admin@cxwsss.online"],
        )

        self.assertEqual(
            alias_record,
            {
                "alias": "sisdebug01-rdig7x@alias.secureinseconds.com",
                "forwardToEmails": ["admin@cxwsss.online"],
                "description": "SIS automation verification",
                "_id": "69e8c5a067ca4b11ba726a15",
            },
        )
        self.assertEqual(client.calls[0]["url"], "https://alias.secureinseconds.com/api/aliases")
        self.assertEqual(
            client.calls[0]["kwargs"]["json"],
            {
                "prefix": "sisdebug01",
                "description": "SIS automation verification",
                "forwardToEmails": ["admin@cxwsss.online"],
            },
        )

    def test_runtime_redacts_sensitive_token_and_password_in_capture_summary(self):
        client = _FakeHTTPClient(
            [
                _FakeResponse(
                    payload={"message": "Email verified successfully."},
                    text='{"message":"Email verified successfully."}',
                )
            ]
        )
        runtime = SecureInSecondsRuntime(
            register_url="https://alias.secureinseconds.com/auth/register",
            login_url="https://alias.secureinseconds.com/auth/signin",
            http_client=cast(HTTPClient, client),
            mailbox_http_client=cast(HTTPClient, _FakeHTTPClient([])),
        )

        ok, _message = runtime.verify_forwarding_email(
            "https://alias.secureinseconds.com/api/user/emails/verify?token=secret-token-123"
        )

        self.assertTrue(ok)
        capture = runtime.capture_summary()[0]
        self.assertEqual(
            capture.request_summary["url"],
            "https://alias.secureinseconds.com/api/user/emails/verify?token=[REDACTED]",
        )
        self.assertTrue(capture.redaction_applied)


if __name__ == "__main__":
    unittest.main()
