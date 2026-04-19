import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock, patch

from fastapi import BackgroundTasks

from api.tasks import (
    RegisterTaskRequest,
    _create_task_record,
    _run_register,
    _task_store,
    create_register_task,
)
from core.alias_pool.manager import AliasEmailPoolManager
from core.base_mailbox import BaseMailbox, MailboxAccount
from core.base_platform import Account, BasePlatform
from core.alias_pool.vend_email_state import VendEmailServiceState


class _FakeMailbox(BaseMailbox):
    def get_email(self) -> MailboxAccount:
        return MailboxAccount(email="demo@example.com")

    def get_current_ids(self, account: MailboxAccount) -> set:
        return set()

    def wait_for_code(
        self,
        account: MailboxAccount,
        keyword: str = "",
        timeout: int = 120,
        before_ids: set[Any] | None = None,
        code_pattern: str | None = None,
        **kwargs,
    ) -> str:
        def poll_once():
            return None

        return self._run_polling_wait(
            timeout=timeout,
            poll_interval=0.01,
            poll_once=poll_once,
        )


class _FakeAliasMailbox(_FakeMailbox):
    def __init__(self):
        self._last_account = MailboxAccount(
            email="alias@example.com",
            account_id="real@example.com",
            extra={
                "mailbox_alias": {
                    "enabled": True,
                    "alias_email": "alias@example.com",
                    "mailbox_email": "real@example.com",
                    "alias_domain": "example.com",
                    "alias_prefix": "",
                    "alias_suffix": "",
                }
            },
        )

    def get_email(self) -> MailboxAccount:
        return self._last_account

    def wait_for_code(
        self,
        account: MailboxAccount,
        keyword: str = "",
        timeout: int = 120,
        before_ids: set[Any] | None = None,
        code_pattern: str | None = None,
        **kwargs,
    ) -> str:
        return "123456"


class _FakeGuerrillaMailbox(_FakeMailbox):
    def __init__(self):
        self._last_account = MailboxAccount(
            email="demo123@spam4.me",
            account_id="sid-demo-1",
            extra={
                "provider": "guerrillamail",
                "domain": "spam4.me",
                "email_user": "demo123",
                "canonical_email": "demo123@guerrillamailblock.com",
            },
        )

    def get_email(self) -> MailboxAccount:
        return self._last_account

    def wait_for_code(
        self,
        account: MailboxAccount,
        keyword: str = "",
        timeout: int = 120,
        before_ids: set[Any] | None = None,
        code_pattern: str | None = None,
        **kwargs,
    ) -> str:
        return "123456"


class _PoolAwareMailbox(_FakeMailbox):
    def __init__(self):
        self._task_alias_pool_key = ""
        self._task_alias_pool = None


class _MailboxFactory:
    def __init__(self):
        self.instances = []

    def __call__(self, *args, **kwargs):
        mailbox = _PoolAwareMailbox()
        self.instances.append(mailbox)
        return mailbox


class _FakeVendEmailStateStore:
    def __init__(self):
        self.loaded_keys = []
        self.saved_states = []

    def load(self, state_key: str) -> VendEmailServiceState:
        self.loaded_keys.append(state_key)
        return VendEmailServiceState(
            state_key=state_key,
            service_email="vendcap202604170108@cxwsss.online",
            mailbox_email="real@example.com",
            service_password="vend-service-pass",
        )

    def save(self, state: VendEmailServiceState) -> None:
        self.saved_states.append(state)


class _FakeVendEmailRuntime:
    def __init__(self):
        self.calls = []

    def restore_session(self, state):
        self.calls.append(("restore_session", state.state_key))
        return True

    def login(self, state, source: dict):
        self.calls.append(("login", source.get("id")))
        return False

    def register(self, state, source: dict):
        self.calls.append(("register", source.get("id")))
        return False

    def list_aliases(self, state, source: dict):
        self.calls.append(("list_aliases", source.get("id"), state.state_key))
        return [
            "vendcapdemo20260417@serf.me",
            "vendcapdemo20260418@serf.me",
        ]

    def create_aliases(self, state, source: dict, missing_count: int):
        self.calls.append(("create_aliases", missing_count))
        return []

    def capture_summary(self):
        self.calls.append(("capture_summary",))
        return [
            {
                "name": "register",
                "url": "https://www.vend.email/auth",
                "method": "POST",
                "request_headers_whitelist": {"content-type": "application/x-www-form-urlencoded"},
                "request_body_excerpt": (
                    "user[name]=vendcap202604170108&"
                    "user[email]=vendcap202604170108%40cxwsss.online&"
                    "user[password]=vend-service-pass"
                ),
                "response_status": 200,
                "response_body_excerpt": '{"ok":true}',
                "captured_at": "2026-04-17T01:08:00+08:00",
            },
            {
                "name": "confirmation",
                "url": "https://www.vend.email/auth/confirmation",
                "method": "POST",
                "request_headers_whitelist": {"content-type": "application/x-www-form-urlencoded"},
                "request_body_excerpt": "user[email]=vendcap202604170108%40cxwsss.online",
                "response_status": 200,
                "response_body_excerpt": '{"ok":true}',
                "captured_at": "2026-04-17T01:09:00+08:00",
            },
            {
                "name": "login",
                "url": "https://www.vend.email/auth/login",
                "method": "POST",
                "request_headers_whitelist": {"content-type": "application/x-www-form-urlencoded"},
                "request_body_excerpt": "user[email]=vendcap202604170108%40cxwsss.online",
                "response_status": 200,
                "response_body_excerpt": '{"ok":true}',
                "captured_at": "2026-04-17T01:10:00+08:00",
            },
            {
                "name": "create_forwarder",
                "url": "https://www.vend.email/forwarders",
                "method": "POST",
                "request_headers_whitelist": {"content-type": "application/x-www-form-urlencoded"},
                "request_body_excerpt": (
                    "forwarder[local_part]=vendcapdemo20260417&"
                    "forwarder[domain_id]=42&"
                    "forwarder[recipient]=admin%40cxwsss.online"
                ),
                "response_status": 200,
                "response_body_excerpt": '{"email":"vendcapdemo20260417@serf.me"}',
                "captured_at": "2026-04-17T01:11:00+08:00",
            },
        ]


class _VendEmailRuntimeBuilder:
    def __init__(self):
        self.instances = []
        self.sources = []

    def __call__(self, source: dict):
        self.sources.append(dict(source))
        runtime = _FakeVendEmailRuntime()
        self.instances.append(runtime)
        return runtime


class _FakePlatform(BasePlatform):
    name = "fake"
    display_name = "Fake"

    def __init__(self, config=None, mailbox=None):
        super().__init__(cast(Any, config))
        self.mailbox = mailbox

    def register(self, email: str, password: str | None = None) -> Account:
        assert self.mailbox is not None
        account = self.mailbox.get_email()
        self.mailbox.wait_for_code(account, timeout=1)
        return Account(
            platform="fake",
            email=account.email,
            password=password or "pw",
        )

    def check_valid(self, account: Account) -> bool:
        return True


class _PoolAwarePlatform(_FakePlatform):
    def register(self, email: str, password: str | None = None) -> Account:
        assert self.mailbox is not None
        pool = self.mailbox._task_alias_pool
        assert pool is not None
        lease = pool.acquire_alias()
        return Account(
            platform="fake",
            email=lease.alias_email,
            password=password or "pw",
        )


class _FakeChatGPTWorkspacePlatform(BasePlatform):
    name = "chatgpt"
    display_name = "ChatGPT"

    _counter = 0

    def __init__(self, config=None, mailbox=None):
        super().__init__(cast(Any, config))
        self.mailbox = mailbox

    @classmethod
    def reset_counter(cls):
        cls._counter = 0

    def register(self, email: str, password: str | None = None) -> Account:
        type(self)._counter += 1
        index = type(self)._counter
        return Account(
            platform="chatgpt",
            email=f"user{index}@example.com",
            password=password or "pw",
            extra={"workspace_id": f"ws-{index}"},
        )

    def check_valid(self, account: Account) -> bool:
        return True


class RegisterTaskControlFlowTests(unittest.TestCase):
    def _proxy_pool_stub(self):
        return Mock(get_next=Mock(return_value=None), report_success=Mock(), report_fail=Mock())

    def _build_request(self, **overrides):
        payload = {
            "platform": "fake",
            "count": 1,
            "concurrency": 1,
            "proxy": "http://proxy.local:8080",
            "extra": {"mail_provider": "fake"},
        }
        payload.update(overrides)
        return RegisterTaskRequest(**payload)

    def _run_with_control(self, task_id: str, *, stop: bool = False, skip: bool = False):
        req = self._build_request()
        _create_task_record(task_id, req, "manual", None)
        if stop:
            _task_store.request_stop(task_id)
        if skip:
            _task_store.request_skip_current(task_id)

        with (
            patch("core.registry.get", return_value=_FakePlatform),
            patch("core.base_mailbox.create_mailbox", return_value=_FakeMailbox()),
            patch("core.config_store.config_store.get_all", return_value={}),
            patch("core.proxy_pool.proxy_pool", new=self._proxy_pool_stub()),
            patch("core.db.save_account", side_effect=lambda account: account),
            patch("api.tasks._save_task_log"),
        ):
            _run_register(task_id, req)

        return _task_store.snapshot(task_id)

    def test_skip_current_marks_attempt_as_skipped(self):
        snapshot = self._run_with_control("task-control-skip", skip=True)

        self.assertEqual(snapshot["status"], "done")
        self.assertEqual(snapshot["success"], 0)
        self.assertEqual(snapshot["skipped"], 1)
        self.assertEqual(snapshot["errors"], [])

    def test_stop_marks_task_as_stopped(self):
        snapshot = self._run_with_control("task-control-stop", stop=True)

        self.assertEqual(snapshot["status"], "stopped")
        self.assertEqual(snapshot["success"], 0)
        self.assertEqual(snapshot["skipped"], 0)
        self.assertEqual(snapshot["errors"], [])

    def test_chatgpt_logs_workspace_progress_after_each_success(self):
        task_id = "task-chatgpt-workspace-progress"
        req = self._build_request(platform="chatgpt", count=2, concurrency=1)
        _create_task_record(task_id, req, "manual", None)
        _FakeChatGPTWorkspacePlatform.reset_counter()

        with (
            patch("core.registry.get", return_value=_FakeChatGPTWorkspacePlatform),
            patch("core.base_mailbox.create_mailbox", return_value=_FakeMailbox()),
            patch("core.config_store.config_store.get_all", return_value={}),
            patch("core.proxy_pool.proxy_pool", new=self._proxy_pool_stub()),
            patch("core.db.save_account", side_effect=lambda account: account),
            patch("api.tasks._save_task_log"),
        ):
            _run_register(task_id, req)

        snapshot = _task_store.snapshot(task_id)
        joined_logs = "\n".join(snapshot["logs"])

        self.assertIn("workspace进度: 1/2", joined_logs)
        self.assertIn("workspace进度: 2/2", joined_logs)

    def test_register_persists_mailbox_alias_metadata(self):
        task_id = "task-alias-mailbox-extra"
        req = self._build_request()
        _create_task_record(task_id, req, "manual", None)
        saved_accounts = []

        def _capture(account):
            saved_accounts.append(account)
            return account

        with (
            patch("core.registry.get", return_value=_FakePlatform),
            patch("core.base_mailbox.create_mailbox", return_value=_FakeAliasMailbox()),
            patch("core.config_store.config_store.get_all", return_value={}),
            patch("core.proxy_pool.proxy_pool", new=self._proxy_pool_stub()),
            patch("core.db.save_account", side_effect=_capture),
            patch("api.tasks._save_task_log"),
        ):
            _run_register(task_id, req)

        self.assertEqual(len(saved_accounts), 1)
        account = saved_accounts[0]
        self.assertEqual(account.email, "alias@example.com")
        self.assertEqual(account.extra.get("mailbox_email"), "real@example.com")
        self.assertEqual(
            account.extra.get("mailbox_alias"),
            {
                "enabled": True,
                "alias_email": "alias@example.com",
                "mailbox_email": "real@example.com",
                "alias_domain": "example.com",
                "alias_prefix": "",
                "alias_suffix": "",
            },
        )

    def test_register_persists_guerrillamail_metadata_without_mailbox_email_sid(self):
        task_id = "task-guerrillamail-mailbox-extra"
        req = self._build_request(extra={"mail_provider": "guerrillamail"})
        _create_task_record(task_id, req, "manual", None)
        saved_accounts = []

        def _capture(account):
            saved_accounts.append(account)
            return account

        with (
            patch("core.registry.get", return_value=_FakePlatform),
            patch("core.base_mailbox.create_mailbox", return_value=_FakeGuerrillaMailbox()),
            patch("core.config_store.config_store.get_all", return_value={}),
            patch("core.proxy_pool.proxy_pool", new=self._proxy_pool_stub()),
            patch("core.db.save_account", side_effect=_capture),
            patch("api.tasks._save_task_log"),
        ):
            _run_register(task_id, req)

        self.assertEqual(len(saved_accounts), 1)
        account = saved_accounts[0]
        self.assertEqual(account.email, "demo123@spam4.me")
        self.assertEqual(account.extra.get("mail_provider"), "guerrillamail")
        self.assertEqual(account.extra.get("canonical_email"), "demo123@guerrillamailblock.com")
        self.assertEqual(account.extra.get("email_user"), "demo123")
        self.assertEqual(account.extra.get("domain"), "spam4.me")
        self.assertIsNone(account.extra.get("mailbox_email"))

    def test_run_register_reuses_one_task_alias_pool_across_attempts(self):
        task_id = "task-alias-pool-reuse"
        req = self._build_request(
            count=2,
            concurrency=1,
            extra={
                "mail_provider": "cloudmail",
                "cloudmail_alias_enabled": True,
                "cloudmail_alias_emails": "alias1@example.com\nalias2@example.com",
                "cloudmail_alias_mailbox_email": "real@example.com",
            }
        )
        _create_task_record(task_id, req, "manual", None)
        mailbox_factory = _MailboxFactory()
        saved_accounts = []

        with (
            patch("core.registry.get", return_value=_PoolAwarePlatform),
            patch("core.base_mailbox.create_mailbox", side_effect=mailbox_factory),
            patch("core.config_store.config_store.get_all", return_value={}),
            patch("core.proxy_pool.proxy_pool", new=self._proxy_pool_stub()),
            patch("core.db.save_account", side_effect=lambda account: saved_accounts.append(account) or account),
            patch("api.tasks._save_task_log"),
        ):
            _run_register(task_id, req)

        self.assertEqual(len(mailbox_factory.instances), 2)
        first_mailbox, second_mailbox = mailbox_factory.instances
        self.assertEqual(first_mailbox._task_alias_pool_key, task_id)
        self.assertIs(first_mailbox._task_alias_pool, second_mailbox._task_alias_pool)
        self.assertIsInstance(first_mailbox._task_alias_pool, AliasEmailPoolManager)
        self.assertEqual(
            [account.email for account in saved_accounts],
            ["alias1@example.com", "alias2@example.com"],
        )

    def test_run_register_builds_task_pool_via_registered_static_producer_path(self):
        task_id = "task-static-producer-path"
        req = self._build_request(
            extra={
                "mail_provider": "cloudmail",
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "legacy-static",
                        "type": "static_list",
                        "emails": ["alias1@example.com", "alias2@example.com"],
                        "mailbox_email": "real@example.com",
                    }
                ],
            },
            count=2,
            concurrency=1,
        )
        _create_task_record(task_id, req, "manual", None)
        mailbox_factory = _MailboxFactory()
        saved_accounts = []

        with (
            patch("core.registry.get", return_value=_PoolAwarePlatform),
            patch("core.base_mailbox.create_mailbox", side_effect=mailbox_factory),
            patch("core.config_store.config_store.get_all", return_value={}),
            patch("core.proxy_pool.proxy_pool", new=self._proxy_pool_stub()),
            patch(
                "core.db.save_account",
                side_effect=lambda account: saved_accounts.append(account) or account,
            ),
            patch("api.tasks._save_task_log"),
        ):
            _run_register(task_id, req)

        self.assertEqual(
            [account.email for account in saved_accounts],
            ["alias1@example.com", "alias2@example.com"],
        )

    def test_run_register_builds_task_pool_via_simple_generator_source(self):
        task_id = "task-simple-generator-producer-path"
        req = self._build_request(
            extra={
                "mail_provider": "cloudmail",
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "simple-1",
                        "type": "simple_generator",
                        "prefix": "msiabc.",
                        "suffix": "@manyme.com",
                        "mailbox_email": "real@example.com",
                        "count": 2,
                        "middle_length_min": 3,
                        "middle_length_max": 3,
                    }
                ],
            },
            count=2,
            concurrency=1,
        )
        _create_task_record(task_id, req, "manual", None)
        mailbox_factory = _MailboxFactory()
        saved_accounts = []

        with (
            patch("core.registry.get", return_value=_PoolAwarePlatform),
            patch("core.base_mailbox.create_mailbox", side_effect=mailbox_factory),
            patch("core.config_store.config_store.get_all", return_value={}),
            patch("core.proxy_pool.proxy_pool", new=self._proxy_pool_stub()),
            patch(
                "core.db.save_account",
                side_effect=lambda account: saved_accounts.append(account) or account,
            ),
            patch("api.tasks._save_task_log"),
        ):
            _run_register(task_id, req)

        self.assertEqual(len(mailbox_factory.instances), 2)
        first_mailbox, second_mailbox = mailbox_factory.instances
        self.assertIs(first_mailbox._task_alias_pool, second_mailbox._task_alias_pool)
        self.assertIsInstance(first_mailbox._task_alias_pool, AliasEmailPoolManager)
        self.assertEqual(len(saved_accounts), 2)
        for account in saved_accounts:
            self.assertTrue(account.email.startswith("msiabc."))
            self.assertTrue(account.email.endswith("@manyme.com"))

    def test_run_register_builds_task_pool_via_vend_email_source(self):
        task_id = "task-vend-email-producer-path"
        created_state_stores = []

        def _build_state_store(current_task_id: str):
            self.assertEqual(current_task_id, task_id)
            store = _FakeVendEmailStateStore()
            created_state_stores.append(store)
            return store

        req = self._build_request(
            extra={
                "mail_provider": "cloudmail",
                "cloudmail_alias_enabled": True,
                "sources": [
                {
                    "id": "vend-email-primary",
                    "type": "vend_email",
                    "register_url": "https://vend.example/register",
                    "mailbox_base_url": "https://mailbox.example/base",
                    "mailbox_email": "real@example.com",
                    "mailbox_password": "secret-pass",
                    "alias_domain": "vend.example.com",
                    "alias_domain_id": "42",
                    "alias_count": 2,
                    "state_key": "vend-email-state-key",
                }
            ],
            "vend_email_runtime_builder": _VendEmailRuntimeBuilder(),
                "vend_email_state_store_factory": _build_state_store,
            },
            count=2,
            concurrency=1,
        )
        _create_task_record(task_id, req, "manual", None)
        mailbox_factory = _MailboxFactory()
        saved_accounts = []
        runtime_builder = req.extra["vend_email_runtime_builder"]

        with (
            patch("core.registry.get", return_value=_PoolAwarePlatform),
            patch("core.base_mailbox.create_mailbox", side_effect=mailbox_factory),
            patch("core.config_store.config_store.get_all", return_value={}),
            patch("core.proxy_pool.proxy_pool", new=self._proxy_pool_stub()),
            patch(
                "core.db.save_account",
                side_effect=lambda account: saved_accounts.append(account) or account,
            ),
            patch("api.tasks._save_task_log"),
        ):
            _run_register(task_id, req)

        self.assertEqual(len(mailbox_factory.instances), 2)
        first_mailbox, second_mailbox = mailbox_factory.instances
        self.assertIs(first_mailbox._task_alias_pool, second_mailbox._task_alias_pool)
        self.assertIsInstance(first_mailbox._task_alias_pool, AliasEmailPoolManager)
        self.assertEqual(
            [account.email for account in saved_accounts],
            ["vendcapdemo20260417@serf.me", "vendcapdemo20260418@serf.me"],
        )
        self.assertEqual(len(runtime_builder.instances), 1)
        self.assertEqual(len(created_state_stores), 1)
        self.assertEqual(created_state_stores[0].loaded_keys, ["vend-email-state-key"])
        self.assertEqual(len(created_state_stores[0].saved_states), 1)
        self.assertEqual(
            created_state_stores[0].saved_states[0].service_email,
            created_state_stores[0].saved_states[0].mailbox_email,
        )
        self.assertEqual(
            created_state_stores[0].saved_states[0].mailbox_email,
            created_state_stores[0].saved_states[0].service_email,
        )
        self.assertEqual(
            created_state_stores[0].saved_states[0].service_password,
            "vend-service-pass",
        )
        self.assertNotEqual(
            created_state_stores[0].saved_states[0].service_password,
            req.extra["sources"][0]["mailbox_password"],
        )
        self.assertEqual(
            [record.name for record in created_state_stores[0].saved_states[0].last_capture_summary],
            ["register", "confirmation", "login", "create_forwarder"],
        )
        self.assertEqual(
            runtime_builder.sources,
            [
                {
                    "id": "vend-email-primary",
                    "type": "vend_email",
                    "register_url": "https://www.vend.email/auth/register",
                    "cloudmail_api_base": "",
                    "cloudmail_admin_email": "",
                    "cloudmail_admin_password": "",
                    "cloudmail_domain": "",
                    "cloudmail_subdomain": "",
                    "cloudmail_timeout": 30,
                    "alias_domain": "vend.example.com",
                    "alias_domain_id": "42",
                    "alias_count": 2,
                    "state_key": "vend-email-state-key",
                }
            ],
        )

    def test_run_register_propagates_internal_type_error_from_vend_email_state_store_factory(self):
        task_id = "task-vend-email-factory-type-error"

        def _broken_state_store_factory(current_task_id: str, current_source_id: str):
            self.assertEqual(current_task_id, task_id)
            self.assertEqual(current_source_id, "vend-email-primary")
            raise TypeError("state store exploded internally")

        req = self._build_request(
            extra={
                "mail_provider": "cloudmail",
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "vend-email-primary",
                        "type": "vend_email",
                        "register_url": "https://vend.example/register",
                        "mailbox_base_url": "https://mailbox.example/base",
                        "mailbox_email": "real@example.com",
                        "mailbox_password": "secret-pass",
                        "alias_domain": "vend.example.com",
                        "alias_domain_id": "42",
                        "alias_count": 2,
                        "state_key": "vend-email-state-key",
                    }
                ],
                "vend_email_runtime_builder": _VendEmailRuntimeBuilder(),
                "vend_email_state_store_factory": _broken_state_store_factory,
            },
            count=1,
            concurrency=1,
        )
        _create_task_record(task_id, req, "manual", None)

        with (
            patch("core.registry.get", return_value=_PoolAwarePlatform),
            patch("core.base_mailbox.create_mailbox", side_effect=_MailboxFactory()),
            patch("core.config_store.config_store.get_all", return_value={}),
            patch("core.proxy_pool.proxy_pool", new=self._proxy_pool_stub()),
            patch("core.db.save_account", side_effect=lambda account: account),
            patch("api.tasks._save_task_log"),
        ):
            _run_register(task_id, req)

        snapshot = _task_store.snapshot(task_id)
        self.assertEqual(snapshot["status"], "failed")
        self.assertEqual(snapshot["error"], "state store exploded internally")
        self.assertEqual(snapshot["errors"], [])

    def test_run_register_uses_default_vend_runtime_builder_without_placeholder_failure(self):
        task_id = "task-vend-email-default-runtime"
        req = self._build_request(
            extra={
                "mail_provider": "cloudmail",
                "cloudmail_alias_enabled": True,
                "sources": [
                    {
                        "id": "vend-email-primary",
                        "type": "vend_email",
                        "register_url": "https://vend.example/register",
                        "mailbox_base_url": "https://mailbox.example/base",
                        "mailbox_email": "real@example.com",
                        "mailbox_password": "secret-pass",
                        "alias_domain": "vend.example.com",
                        "alias_domain_id": "42",
                        "alias_count": 1,
                        "state_key": "vend-email-state-key",
                    }
                ],
            },
            count=1,
            concurrency=1,
        )
        _create_task_record(task_id, req, "manual", None)

        with (
            patch("core.registry.get", return_value=_PoolAwarePlatform),
            patch("core.base_mailbox.create_mailbox", side_effect=_MailboxFactory()),
            patch("core.config_store.config_store.get_all", return_value={}),
            patch("core.proxy_pool.proxy_pool", new=self._proxy_pool_stub()),
            patch("core.db.save_account", side_effect=lambda account: account),
            patch("api.tasks._save_task_log"),
            patch(
                "core.alias_pool.vend_email_service.DefaultVendEmailRuntimeExecutor.execute",
                side_effect=AssertionError("default-runtime-used"),
            ),
        ):
            _run_register(task_id, req)

        snapshot = _task_store.snapshot(task_id)
        self.assertEqual(snapshot["status"], "failed")
        self.assertEqual(snapshot["error"], "default-runtime-used")

    def test_build_vend_email_alias_service_producer_uses_state_key_store_by_default(self):
        from core.alias_pool.vend_email_service import build_vend_email_alias_service_producer

        producer = build_vend_email_alias_service_producer(
            source={
                "id": "vend-email-primary",
                "type": "vend_email",
                "register_url": "https://vend.example/register",
                "mailbox_base_url": "https://mailbox.example/base",
                "mailbox_email": "real@example.com",
                "mailbox_password": "secret-pass",
                "alias_domain": "vend.example.com",
                "alias_domain_id": "42",
                "alias_count": 1,
                "state_key": "vend-email-state-key",
            },
            task_id="task-vend-email-default-store",
            runtime_builder=_VendEmailRuntimeBuilder(),
        )

        store_path = producer.state_store._store._path
        self.assertEqual(
            store_path,
            Path("data") / "alias_pool" / "vend_email" / "states" / "vend-email-state-key.json",
        )

    def test_create_register_task_keeps_alias_config_in_request(self):
        req = self._build_request(
            extra={
                "mail_provider": "cloudmail",
                "cloudmail_alias_enabled": True,
                "cloudmail_alias_prefix": "alias+",
                "cloudmail_alias_suffix": ".team",
                "cloudmail_alias_domain": "alias.example.com",
            }
        )
        background_tasks = BackgroundTasks()

        with patch("api.tasks.enqueue_register_task", return_value="task-123") as enqueue_mock:
            result = create_register_task(req, background_tasks)

        self.assertEqual(result, {"task_id": "task-123"})
        enqueue_mock.assert_called_once()
        called_req = enqueue_mock.call_args.args[0]
        self.assertTrue(called_req.extra["cloudmail_alias_enabled"])
        self.assertEqual(called_req.extra["cloudmail_alias_prefix"], "alias+")
        self.assertEqual(called_req.extra["cloudmail_alias_suffix"], ".team")
        self.assertEqual(called_req.extra["cloudmail_alias_domain"], "alias.example.com")


if __name__ == "__main__":
    unittest.main()
