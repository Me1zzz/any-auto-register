import unittest

from platforms.chatgpt.team_workspace import (
    ChatGPTTeamWorkspaceResult,
    build_cleanup_compensation_context,
    remove_chatgpt_team_member_with_retry,
)


class ChatGPTTeamWorkspaceTests(unittest.TestCase):
    def test_remove_with_retry_succeeds_after_transient_failure(self):
        attempts = []

        def remover(**kwargs):
            attempts.append(kwargs)
            if len(attempts) == 1:
                return ChatGPTTeamWorkspaceResult(
                    success=False,
                    action="remove",
                    workspace_id=kwargs["workspace_id"],
                    member_email=kwargs["member_email"],
                    attempts=1,
                    detail="temporary failure",
                )
            return ChatGPTTeamWorkspaceResult(
                success=True,
                action="remove",
                workspace_id=kwargs["workspace_id"],
                member_email=kwargs["member_email"],
                attempts=1,
                detail="removed",
            )

        result = remove_chatgpt_team_member_with_retry(
            member_email="new@example.com",
            workspace_id="ws-demo",
            team_account={"email": "owner@example.com"},
            max_attempts=3,
            retry_delay_seconds=0,
            remover=remover,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(attempts), 2)

    def test_remove_with_retry_returns_failure_and_compensation_context(self):
        def remover(**kwargs):
            return ChatGPTTeamWorkspaceResult(
                success=False,
                action="remove",
                workspace_id=kwargs["workspace_id"],
                member_email=kwargs["member_email"],
                attempts=1,
                detail="still present",
            )

        result = remove_chatgpt_team_member_with_retry(
            member_email="new@example.com",
            workspace_id="ws-demo",
            team_account={"email": "owner@example.com"},
            max_attempts=2,
            retry_delay_seconds=0,
            remover=remover,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(result.payload["compensation_context"]["member_email"], "new@example.com")
        self.assertEqual(result.payload["compensation_context"]["workspace_id"], "ws-demo")
        self.assertEqual(result.payload["compensation_context"]["team_account_identifier"], "owner@example.com")

    def test_build_cleanup_compensation_context_contains_future_recovery_inputs(self):
        context = build_cleanup_compensation_context(
            member_email="new@example.com",
            workspace_id="ws-demo",
            team_account={"email": "owner@example.com"},
            failure_detail="remove failed",
        )

        self.assertEqual(context["member_email"], "new@example.com")
        self.assertEqual(context["workspace_id"], "ws-demo")
        self.assertEqual(context["team_account_identifier"], "owner@example.com")
        self.assertEqual(context["failure_detail"], "remove failed")
        self.assertEqual(context["compensation_strategy"], "switch_team_account_cleanup")


if __name__ == "__main__":
    unittest.main()
