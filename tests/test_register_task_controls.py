import unittest
from unittest.mock import patch

from fastapi import BackgroundTasks

from api.tasks import (
    RegisterTaskRequest,
    _create_task_record,
    _run_register,
    _task_store,
    create_register_task,
)
from core.base_mailbox import BaseMailbox, MailboxAccount
from core.base_platform import Account, BasePlatform


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
        before_ids: set = None,
        code_pattern: str = None,
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


class _FakePlatform(BasePlatform):
    name = "fake"
    display_name = "Fake"

    def __init__(self, config=None, mailbox=None):
        super().__init__(config)
        self.mailbox = mailbox

    def register(self, email: str, password: str = None) -> Account:
        account = self.mailbox.get_email()
        self.mailbox.wait_for_code(account, timeout=1)
        return Account(
            platform="fake",
            email=account.email,
            password=password or "pw",
        )

    def check_valid(self, account: Account) -> bool:
        return True


class _FakeChatGPTWorkspacePlatform(BasePlatform):
    name = "chatgpt"
    display_name = "ChatGPT"

    _counter = 0

    def __init__(self, config=None, mailbox=None):
        super().__init__(config)
        self.mailbox = mailbox

    @classmethod
    def reset_counter(cls):
        cls._counter = 0

    def register(self, email: str, password: str = None) -> Account:
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
