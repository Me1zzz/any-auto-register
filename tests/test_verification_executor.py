import unittest
from unittest import mock

from core.alias_pool.interactive_provider_models import (
    AuthenticatedProviderContext,
    VerificationRequirement,
)
from core.alias_pool.provider_contracts import AliasProviderSourceSpec
from core.alias_pool.verification_executor import VerificationExecutor


class _StubConfirmationReader:
    def fetch_confirmation(self, *, state, source: dict):
        class _Result:
            confirm_url = "https://provider.test/verify/token-1"
            error = ""

        return _Result()


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeHTTPClient:
    def __init__(self):
        self.calls = []

    def request(self, method: str, url: str, **kwargs) -> _FakeResponse:
        self.calls.append((method, url, kwargs))
        if url.endswith("/api/login"):
            return _FakeResponse({"token": "token-1"})
        if url.endswith("/api/email/list"):
            return _FakeResponse(
                {
                    "data": [
                        {
                            "recipient": "other@example.com",
                            "content": "https://provider.test/verify/stale-token",
                        },
                        {
                            "recipient": "real@example.com",
                            "content": (
                                "confirm real@example.com via "
                                "https://provider.test/verify/right-token"
                            ),
                        },
                    ]
                }
            )
        raise AssertionError(f"Unexpected request: {method} {url}")


class _FakeNestedListHTTPClient(_FakeHTTPClient):
    def request(self, method: str, url: str, **kwargs) -> _FakeResponse:
        self.calls.append((method, url, kwargs))
        if url.endswith("/api/login"):
            return _FakeResponse({"token": "token-1"})
        if url.endswith("/api/email/list"):
            return _FakeResponse(
                {
                    "code": 200,
                    "message": "success",
                    "data": {
                        "list": [
                            {
                                "recipient": "other@example.com",
                                "content": "https://provider.test/verify/stale-token",
                            },
                            {
                                "recipient": "real@example.com",
                                "content": (
                                    "confirm real@example.com via "
                                    "https://provider.test/verify/right-token"
                                ),
                            },
                        ]
                    },
                }
            )
        raise AssertionError(f"Unexpected request: {method} {url}")


class _FakeNestedTokenHTTPClient(_FakeNestedListHTTPClient):
    def request(self, method: str, url: str, **kwargs) -> _FakeResponse:
        self.calls.append((method, url, kwargs))
        if url.endswith("/api/login"):
            return _FakeResponse({"code": 200, "message": "success", "data": {"token": "token-1"}})
        if url.endswith("/api/email/list"):
            headers = kwargs.get("headers") or {}
            if headers.get("authorization") != "token-1":
                return _FakeResponse({"code": 401, "message": "invalid token", "data": {"list": []}})
            return _FakeResponse(
                {
                    "code": 200,
                    "message": "success",
                    "data": {
                        "list": [
                            {
                                "recipient": "real@example.com",
                                "content": (
                                    "confirm real@example.com via "
                                    "https://provider.test/verify/right-token"
                                ),
                            }
                        ]
                    },
                }
            )
        raise AssertionError(f"Unexpected request: {method} {url}")


class _FakeEmptyMailListHTTPClient:
    def __init__(self):
        self.calls = []

    def request(self, method: str, url: str, **kwargs) -> _FakeResponse:
        self.calls.append((method, url, kwargs))
        if url.endswith("/api/login"):
            return _FakeResponse({"token": "token-1"})
        if url.endswith("/api/email/list"):
            return _FakeResponse({"data": []})
        raise AssertionError(f"Unexpected request: {method} {url}")


class VerificationExecutorTests(unittest.TestCase):
    def test_executor_prefers_injected_confirmation_reader(self):
        executor = VerificationExecutor(confirmation_reader=_StubConfirmationReader())
        spec = AliasProviderSourceSpec(
            source_id="myalias-primary",
            provider_type="myalias_pro",
        )
        context = AuthenticatedProviderContext(
            confirmation_inbox_email="real@example.com",
            real_mailbox_email="real@example.com",
        )
        requirement = VerificationRequirement(
            kind="account_email",
            label="验证服务账号邮箱",
            inbox_role="confirmation_inbox",
        )

        result = executor.resolve_link(
            requirement=requirement,
            spec=spec,
            context=context,
        )

        self.assertEqual(result.kind, "account_email")
        self.assertEqual(result.link, "https://provider.test/verify/token-1")
        self.assertEqual(result.source, "confirmation_reader")

    def test_executor_filters_cloudmail_messages_by_target_email_before_extracting_link(self):
        client = _FakeHTTPClient()
        executor = VerificationExecutor(client=client)
        spec = AliasProviderSourceSpec(
            source_id="emailshield-primary",
            provider_type="emailshield",
            confirmation_inbox_config={
                "base_url": "https://mailbox.example",
                "account_email": "admin@example.com",
                "account_password": "secret-pass",
                "match_email": "real@example.com",
            },
        )
        context = AuthenticatedProviderContext(
            confirmation_inbox_email="real@example.com",
            real_mailbox_email="real@example.com",
        )
        requirement = VerificationRequirement(
            kind="account_email",
            label="验证服务账号邮箱",
            inbox_role="confirmation_inbox",
        )

        result = executor.resolve_link(
            requirement=requirement,
            spec=spec,
            context=context,
        )

        self.assertEqual(result.kind, "account_email")
        self.assertEqual(result.link, "https://provider.test/verify/right-token")
        self.assertEqual(result.source, "cloudmail_api")
        self.assertEqual(client.calls[-1][2]["headers"]["authorization"], "token-1")

    def test_executor_extracts_messages_from_cloudmail_data_list_payload(self):
        executor = VerificationExecutor(client=_FakeNestedListHTTPClient())
        spec = AliasProviderSourceSpec(
            source_id="emailshield-primary",
            provider_type="emailshield",
            confirmation_inbox_config={
                "base_url": "https://mailbox.example",
                "account_email": "admin@example.com",
                "account_password": "secret-pass",
                "match_email": "real@example.com",
            },
        )
        context = AuthenticatedProviderContext(
            confirmation_inbox_email="real@example.com",
            real_mailbox_email="real@example.com",
        )
        requirement = VerificationRequirement(
            kind="account_email",
            label="验证服务账号邮箱",
            inbox_role="confirmation_inbox",
        )

        result = executor.resolve_link(
            requirement=requirement,
            spec=spec,
            context=context,
        )

        self.assertEqual(result.kind, "account_email")
        self.assertEqual(result.link, "https://provider.test/verify/right-token")
        self.assertEqual(result.source, "cloudmail_api")

    def test_executor_extracts_token_from_cloudmail_nested_data_payload(self):
        client = _FakeNestedTokenHTTPClient()
        executor = VerificationExecutor(client=client)
        spec = AliasProviderSourceSpec(
            source_id="emailshield-primary",
            provider_type="emailshield",
            confirmation_inbox_config={
                "base_url": "https://mailbox.example",
                "account_email": "admin@example.com",
                "account_password": "secret-pass",
                "match_email": "real@example.com",
            },
        )
        context = AuthenticatedProviderContext(
            confirmation_inbox_email="real@example.com",
            real_mailbox_email="real@example.com",
        )
        requirement = VerificationRequirement(
            kind="account_email",
            label="验证服务账号邮箱",
            inbox_role="confirmation_inbox",
        )

        result = executor.resolve_link(
            requirement=requirement,
            spec=spec,
            context=context,
        )

        self.assertEqual(result.kind, "account_email")
        self.assertEqual(result.link, "https://provider.test/verify/right-token")
        self.assertEqual(result.source, "cloudmail_api")
        self.assertEqual(client.calls[-1][2]["headers"]["authorization"], "token-1")

    def test_executor_uses_target_mailbox_first_for_myalias_confirmation_lookup(self):
        client = _FakeEmptyMailListHTTPClient()
        executor = VerificationExecutor(client=client)
        spec = AliasProviderSourceSpec(
            source_id="myalias-primary",
            provider_type="myalias_pro",
            confirmation_inbox_config={
                "base_url": "https://mailbox.example",
                "account_email": "admin@example.com",
                "account_password": "secret-pass",
                "match_email": "real@example.com",
            },
        )
        context = AuthenticatedProviderContext(
            confirmation_inbox_email="real@example.com",
            real_mailbox_email="real@example.com",
        )
        requirement = VerificationRequirement(
            kind="account_email",
            label="验证服务账号邮箱",
            inbox_role="confirmation_inbox",
        )
        fake_time = mock.Mock()
        fake_time.monotonic.side_effect = [0.0, 0.0, 1.0]
        captured = {
            "init": None,
            "list_calls": [],
            "match_alias_calls": [],
        }

        class _PollingCloudMailMailboxFake:
            def __init__(self, *, api_base, admin_email, admin_password, domain, subdomain, timeout):
                captured["init"] = {
                    "api_base": api_base,
                    "admin_email": admin_email,
                    "admin_password": admin_password,
                    "domain": domain,
                    "subdomain": subdomain,
                    "timeout": timeout,
                }

            def _list_mails(self, email=""):
                captured["list_calls"].append(email)
                if len(captured["list_calls"]) == 1:
                    return []
                return [
                    {
                        "recipient": "real@example.com",
                        "content": (
                            "confirm real@example.com via "
                            "https://provider.test/verify/right-token"
                        ),
                    }
                ]

            def _match_alias_receipt(self, message, alias_email):
                captured["match_alias_calls"].append((message, alias_email))
                return str(message.get("recipient") or "") == str(alias_email)

        with mock.patch("core.alias_pool.verification_executor.CloudMailMailbox", _PollingCloudMailMailboxFake, create=True):
            with mock.patch("core.alias_pool.verification_executor.time", fake_time, create=True):
                result = executor.resolve_link(
                    requirement=requirement,
                    spec=spec,
                    context=context,
                )

        self.assertEqual(result.kind, "account_email")
        self.assertEqual(result.link, "https://provider.test/verify/right-token")
        self.assertEqual(result.source, "cloudmail_api")
        self.assertEqual(
            captured["init"],
            {
                "api_base": "https://mailbox.example",
                "admin_email": "admin@example.com",
                "admin_password": "secret-pass",
                "domain": "",
                "subdomain": "",
                "timeout": 30,
            },
        )
        self.assertEqual(captured["list_calls"], ["real@example.com", "real@example.com"])
        self.assertEqual(len(captured["match_alias_calls"]), 1)
        self.assertEqual(captured["match_alias_calls"][0][1], "real@example.com")

    def test_executor_falls_back_to_full_list_when_target_mailbox_returns_empty(self):
        executor = VerificationExecutor(client=_FakeEmptyMailListHTTPClient())
        spec = AliasProviderSourceSpec(
            source_id="myalias-primary",
            provider_type="myalias_pro",
            confirmation_inbox_config={
                "base_url": "https://mailbox.example",
                "account_email": "admin@example.com",
                "account_password": "secret-pass",
                "match_email": "real@example.com",
            },
        )
        context = AuthenticatedProviderContext(
            confirmation_inbox_email="real@example.com",
            real_mailbox_email="real@example.com",
        )
        requirement = VerificationRequirement(
            kind="account_email",
            label="妤犲矁鐦夐張宥呭鐠愶箑褰块柇顔绢唸",
            inbox_role="confirmation_inbox",
        )
        fake_time = mock.Mock()
        fake_time.monotonic.side_effect = [0.0, 0.0, 1.0]
        captured = {"list_calls": []}

        class _MailboxFake:
            def __init__(self, **kwargs):
                pass

            def _list_mails(self, email=""):
                captured["list_calls"].append(email)
                if email:
                    return []
                return [
                    {
                        "recipient": "real@example.com",
                        "content": "confirm real@example.com via https://provider.test/verify/right-token",
                    }
                ]

            def _match_alias_receipt(self, message, alias_email):
                return str(message.get("recipient") or "") == str(alias_email)

        with mock.patch("core.alias_pool.verification_executor.CloudMailMailbox", _MailboxFake, create=True):
            with mock.patch("core.alias_pool.verification_executor.time", fake_time, create=True):
                result = executor.resolve_link(
                    requirement=requirement,
                    spec=spec,
                    context=context,
                )

        self.assertEqual(result.link, "https://provider.test/verify/right-token")
        self.assertEqual(captured["list_calls"], ["real@example.com", ""])

    def test_executor_prefers_service_account_email_as_myalias_confirmation_target(self):
        executor = VerificationExecutor(client=_FakeEmptyMailListHTTPClient())
        spec = AliasProviderSourceSpec(
            source_id="myalias-primary",
            provider_type="myalias_pro",
            confirmation_inbox_config={
                "base_url": "https://mailbox.example",
                "account_email": "admin@example.com",
                "account_password": "secret-pass",
                "match_email": "admin@example.com",
            },
        )
        context = AuthenticatedProviderContext(
            service_account_email="generated@example.com",
            confirmation_inbox_email="admin@example.com",
            real_mailbox_email="admin@example.com",
        )
        requirement = VerificationRequirement(
            kind="account_email",
            label="验证服务账号邮箱",
            inbox_role="confirmation_inbox",
        )
        fake_time = mock.Mock()
        fake_time.monotonic.side_effect = [0.0, 0.0, 1.0]
        captured = {"match_alias_calls": []}

        class _MailboxFake:
            def __init__(self, **kwargs):
                pass

            def _list_mails(self, email=""):
                return [
                    {
                        "recipient": "generated@example.com",
                        "content": "confirm generated@example.com via https://provider.test/verify/generated-token",
                    }
                ]

            def _match_alias_receipt(self, message, alias_email):
                captured["match_alias_calls"].append(alias_email)
                return str(message.get("recipient") or "") == str(alias_email)

        with mock.patch("core.alias_pool.verification_executor.CloudMailMailbox", _MailboxFake, create=True):
            with mock.patch("core.alias_pool.verification_executor.time", fake_time, create=True):
                result = executor.resolve_link(
                    requirement=requirement,
                    spec=spec,
                    context=context,
                )

        self.assertEqual(result.link, "https://provider.test/verify/generated-token")
        self.assertEqual(captured["match_alias_calls"], ["generated@example.com"])


if __name__ == "__main__":
    unittest.main()
