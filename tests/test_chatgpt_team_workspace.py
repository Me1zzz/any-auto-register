import unittest
from unittest import mock


class ChatGPTTeamWorkspaceTests(unittest.TestCase):
    def test_team_workspace_functions_are_exported_from_chatgpt_package(self):
        from platforms.chatgpt import (
            invite_chatgpt_team_member,
            remove_chatgpt_team_member,
        )

        self.assertTrue(callable(invite_chatgpt_team_member))
        self.assertTrue(callable(remove_chatgpt_team_member))

    def test_invite_requires_cloudmail_provider(self):
        from platforms.chatgpt.team_workspace import invite_chatgpt_team_member

        with mock.patch(
            "platforms.chatgpt.team_workspace.config_store.get_all",
            return_value={"mail_provider": "luckmail"},
        ):
            result = invite_chatgpt_team_member(
                member_email="member@example.com",
                workspace_id="workspace-1",
                team_account={"email": "manager@example.com"},
            )

        self.assertFalse(result.success)
        self.assertIn("cloudmail", result.detail)

    def test_invite_uses_old_interface_and_returns_workspace_result(self):
        from platforms.chatgpt.team_workspace import (
            ChatGPTTeamWorkspaceResult,
            TeamWorkspaceSession,
            invite_chatgpt_team_member,
        )

        session = TeamWorkspaceSession(
            email="manager@example.com",
            access_token="access-token",
            workspace_id="workspace-1",
        )

        with mock.patch(
            "platforms.chatgpt.team_workspace.config_store.get_all",
            return_value={
                "mail_provider": "cloudmail",
                "cloudmail_api_base": "https://mail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_team_account_email": "manager@example.com",
            },
        ), mock.patch(
            "platforms.chatgpt.team_workspace.login_chatgpt_team_account",
            return_value=session,
        ) as mock_login, mock.patch(
            "platforms.chatgpt.team_workspace._send_team_invite_once",
            return_value=(200, {"ok": True}, ""),
        ) as mock_invite:
            result = invite_chatgpt_team_member(
                member_email="member@example.com",
                workspace_id="workspace-1",
                team_account={"email": "manager@example.com"},
            )

        self.assertIsInstance(result, ChatGPTTeamWorkspaceResult)
        self.assertTrue(result.success)
        self.assertEqual(result.member_email, "member@example.com")
        self.assertEqual(result.workspace_id, "workspace-1")
        self.assertTrue(result.as_metadata("workspace_enroll")["workspace_enroll_success"])
        mock_login.assert_called_once()
        mock_invite.assert_called_once_with(
            access_token="access-token",
            workspace_id="workspace-1",
            target_email="member@example.com",
            proxy_url=None,
        )

    def test_invite_can_resolve_workspace_id_from_team_session(self):
        from platforms.chatgpt.team_workspace import (
            TeamWorkspaceSession,
            invite_chatgpt_team_member,
        )

        session = TeamWorkspaceSession(
            email="manager@example.com",
            access_token="access-token",
            workspace_id="workspace-1",
        )

        with mock.patch(
            "platforms.chatgpt.team_workspace.config_store.get_all",
            return_value={
                "mail_provider": "cloudmail",
                "cloudmail_api_base": "https://mail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
                "cloudmail_team_account_email": "manager@example.com",
            },
        ), mock.patch(
            "platforms.chatgpt.team_workspace.login_chatgpt_team_account",
            return_value=session,
        ), mock.patch(
            "platforms.chatgpt.team_workspace._fetch_team_workspace_candidates",
            return_value=[{"account_id": "workspace-1", "role": "owner", "active": True}],
        ), mock.patch(
            "platforms.chatgpt.team_workspace._send_team_invite_once",
            return_value=(200, {"ok": True}, ""),
        ) as mock_invite:
            result = invite_chatgpt_team_member(
                member_email="member@example.com",
                workspace_id="",
                team_account={"email": "manager@example.com"},
            )

        self.assertTrue(result.success)
        self.assertEqual(result.workspace_id, "workspace-1")
        mock_invite.assert_called_once_with(
            access_token="access-token",
            workspace_id="workspace-1",
            target_email="member@example.com",
            proxy_url=None,
        )

    def test_remove_with_retry_succeeds_after_transient_failure(self):
        from platforms.chatgpt.team_workspace import (
            ChatGPTTeamWorkspaceResult,
            remove_chatgpt_team_member_with_retry,
        )

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
        from platforms.chatgpt.team_workspace import (
            ChatGPTTeamWorkspaceResult,
            remove_chatgpt_team_member_with_retry,
        )

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
        from platforms.chatgpt.team_workspace import build_cleanup_compensation_context

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

    def test_login_uses_cloudmail_admin_inbox_for_team_account_otp(self):
        from platforms.chatgpt.team_workspace import login_chatgpt_team_account

        oauth_instance = mock.Mock()
        oauth_instance.last_workspace_id = "workspace-1"
        oauth_instance.login_and_get_tokens.return_value = {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
        }

        with mock.patch(
            "platforms.chatgpt.team_workspace.CloudMailMailbox"
        ) as mailbox_cls, mock.patch(
            "platforms.chatgpt.team_workspace.OAuthClient",
            return_value=oauth_instance,
        ):
            mailbox = mailbox_cls.return_value
            mailbox.get_current_ids.return_value = {"old-message"}
            result = login_chatgpt_team_account(
                "manager@example.com",
                cfg={
                    "mail_provider": "cloudmail",
                    "cloudmail_api_base": "https://mail.example.com",
                    "cloudmail_admin_email": "admin@example.com",
                    "cloudmail_admin_password": "secret",
                    "mailbox_otp_timeout_seconds": "90",
                },
                force_refresh=True,
            )

        self.assertEqual(result.access_token, "access-token")
        mailbox.get_current_ids.assert_called_once()
        mailbox_account = mailbox.get_current_ids.call_args.args[0]
        self.assertEqual(mailbox_account.email, "manager@example.com")
        self.assertEqual(mailbox_account.account_id, "admin@example.com")
        oauth_instance.login_and_get_tokens.assert_called_once()
        self.assertEqual(oauth_instance.login_and_get_tokens.call_args.args[:3], ("manager@example.com", "", ""))

    def test_remove_deletes_joined_member_by_email(self):
        from platforms.chatgpt.team_workspace import (
            ChatGPTTeamWorkspaceResult,
            TeamWorkspaceSession,
            remove_chatgpt_team_member,
        )

        session = TeamWorkspaceSession(
            email="manager@example.com",
            access_token="access-token",
            workspace_id="workspace-1",
        )

        def fake_team_api_request(**kwargs):
            if kwargs["method"] == "DELETE":
                return 200, {"deleted": True}, ""
            raise AssertionError(f"unexpected request: {kwargs}")

        with mock.patch(
            "platforms.chatgpt.team_workspace.config_store.get_all",
            return_value={
                "mail_provider": "cloudmail",
                "cloudmail_api_base": "https://mail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
            },
        ), mock.patch(
            "platforms.chatgpt.team_workspace.login_chatgpt_team_account",
            return_value=session,
        ), mock.patch(
            "platforms.chatgpt.team_workspace._fetch_joined_members",
            return_value=(200, [{"user_id": "user-1", "email": "member@example.com"}], ""),
        ), mock.patch(
            "platforms.chatgpt.team_workspace._fetch_invited_members",
            return_value=(200, [], ""),
        ), mock.patch(
            "platforms.chatgpt.team_workspace._team_api_request",
            side_effect=fake_team_api_request,
        ) as mock_request:
            result = remove_chatgpt_team_member(
                member_email="member@example.com",
                workspace_id="workspace-1",
                team_account={"email": "manager@example.com"},
            )

        self.assertIsInstance(result, ChatGPTTeamWorkspaceResult)
        self.assertTrue(result.success)
        self.assertEqual(result.payload["removed_state"], "joined")
        mock_request.assert_called_once_with(
            method="DELETE",
            access_token="access-token",
            workspace_id="workspace-1",
            path="/users/user-1",
            proxy_url=None,
        )

    def test_remove_revokes_pending_invite_by_email(self):
        from platforms.chatgpt.team_workspace import (
            TeamWorkspaceSession,
            remove_chatgpt_team_member,
        )

        session = TeamWorkspaceSession(
            email="manager@example.com",
            access_token="access-token",
            workspace_id="workspace-1",
        )

        with mock.patch(
            "platforms.chatgpt.team_workspace.config_store.get_all",
            return_value={
                "mail_provider": "cloudmail",
                "cloudmail_api_base": "https://mail.example.com",
                "cloudmail_admin_email": "admin@example.com",
                "cloudmail_admin_password": "secret",
            },
        ), mock.patch(
            "platforms.chatgpt.team_workspace.login_chatgpt_team_account",
            return_value=session,
        ), mock.patch(
            "platforms.chatgpt.team_workspace._fetch_joined_members",
            return_value=(200, [], ""),
        ), mock.patch(
            "platforms.chatgpt.team_workspace._fetch_invited_members",
            return_value=(200, [{"email": "member@example.com"}], ""),
        ), mock.patch(
            "platforms.chatgpt.team_workspace._team_api_request",
            return_value=(200, {"revoked": True}, ""),
        ) as mock_request:
            result = remove_chatgpt_team_member(
                member_email="member@example.com",
                workspace_id="workspace-1",
                team_account={"email": "manager@example.com"},
            )

        self.assertTrue(result.success)
        self.assertEqual(result.payload["removed_state"], "invited")
        mock_request.assert_called_once_with(
            method="DELETE",
            access_token="access-token",
            workspace_id="workspace-1",
            path="/invites",
            proxy_url=None,
            payload={"email_address": "member@example.com"},
        )


if __name__ == "__main__":
    unittest.main()
