import unittest
from types import SimpleNamespace
from unittest import mock

from api import tasks


class TaskLoggingTests(unittest.TestCase):
    def test_log_does_not_duplicate_existing_timestamp(self):
        task_id = "test_existing_timestamp"
        tasks._task_store.create(task_id, platform="chatgpt", total=1, source="test")

        tasks._log(task_id, "[14:53:48] [准备] 开始: 初始化")

        logs, _status = tasks._task_store.log_state(task_id)
        self.assertEqual(logs[-1], "[14:53:48] [准备] 开始: 初始化")

    def test_log_adds_timestamp_when_message_has_none(self):
        task_id = "test_missing_timestamp"
        tasks._task_store.create(task_id, platform="chatgpt", total=1, source="test")

        tasks._log(task_id, "[准备] 开始: 初始化")

        logs, _status = tasks._task_store.log_state(task_id)
        self.assertRegex(logs[-1], r"^\[\d{2}:\d{2}:\d{2}\] \[准备\] 开始: 初始化$")

    def test_log_routes_alias_pool_snapshots_to_debug_only(self):
        task_id = "test_alias_pool_debug"
        tasks._task_store.create(task_id, platform="chatgpt", total=1, source="test")

        with self.assertLogs(tasks.logger, level="DEBUG") as captured:
            tasks._log(task_id, "[AliasPool] 当前可用别名邮箱快照")

        logs, _status = tasks._task_store.log_state(task_id)
        self.assertEqual(logs, [])
        self.assertIn("[AliasPool] 当前可用别名邮箱快照", "\n".join(captured.output))

    def test_log_routes_cloudmail_list_response_to_debug_only(self):
        task_id = "test_cloudmail_debug"
        tasks._task_store.create(task_id, platform="chatgpt", total=1, source="test")

        with self.assertLogs(tasks.logger, level="DEBUG") as captured:
            tasks._log(task_id, "[CloudMail] emailList 响应: toEmail=<all> count=20 items=[]")

        logs, _status = tasks._task_store.log_state(task_id)
        self.assertEqual(logs, [])
        self.assertIn("[CloudMail] emailList 响应", "\n".join(captured.output))

    def test_alias_pool_snapshot_logs_visible_counts_not_provider_lists(self):
        task_id = "test_alias_pool_snapshot_summary"
        tasks._task_store.create(task_id, platform="chatgpt", total=1, source="test")
        pool_manager = mock.Mock()
        pool_manager.snapshot_available_aliases_by_kind.return_value = {
            "vend_email": [],
            "myalias_pro": ["ready@example.com"],
        }

        tasks._log_alias_pool_snapshot(task_id, pool_manager)

        logs, _status = tasks._task_store.log_state(task_id)
        joined_logs = "\n".join(logs)
        self.assertIn("[AliasPool] 当前可用别名邮箱: vend=0, myalias pro=1", joined_logs)
        self.assertNotIn("myalias pro: [", joined_logs)
        self.assertNotIn("vend: [", joined_logs)

    def test_auto_upload_missing_access_token_is_logged_as_skip(self):
        task_id = "test_missing_access_token_upload"
        tasks._task_store.create(task_id, platform="chatgpt", total=1, source="test")
        account = SimpleNamespace(email="user@example.com", platform="chatgpt", token="")

        with mock.patch(
            "services.external_sync.sync_account",
            return_value=[{"name": "CPA", "ok": False, "msg": "账号缺少 access_token"}],
        ):
            tasks._auto_upload_integrations(task_id, account)

        logs, _status = tasks._task_store.log_state(task_id)
        self.assertIn("[CPA] [SKIP] 账号缺少 access_token", logs[-1])
        self.assertNotIn("[FAIL] 账号缺少 access_token", logs[-1])


if __name__ == "__main__":
    unittest.main()
