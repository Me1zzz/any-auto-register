import unittest

from platforms.chatgpt.codex_gui.context import CodexGUIFlowContext
from platforms.chatgpt.codex_gui.models import CodexGUIIdentity, FlowStepResult
from platforms.chatgpt.codex_gui.workflows.official_signup_workflow import OfficialSignupWorkflow


class _Step:
    def __init__(self, step_id):
        self.step_id = step_id

    def run(self, engine, ctx):
        ctx.step_history.append(self.step_id)
        return FlowStepResult(success=True, stage_name=self.step_id)


class OfficialSignupWorkflowTests(unittest.TestCase):
    def test_workflow_runs_official_signup_front_half_in_order(self):
        workflow = OfficialSignupWorkflow(
            steps=[
                _Step("official_signup.open_entry"),
                _Step("official_signup.navigate_signup"),
                _Step("official_signup.submit_email"),
                _Step("official_signup.submit_password"),
            ]
        )
        ctx = CodexGUIFlowContext(
            identity=CodexGUIIdentity(
                email="new@example.com",
                password="Secret123!",
                full_name="Demo User",
                age=30,
            ),
            auth_url="https://auth.openai.com/oauth/authorize?state=demo",
            auth_state="demo",
            email_adapter=object(),
            logger=lambda _message, _level="info": None,
            extra_config={},
        )

        result = workflow.run(object(), ctx)

        self.assertTrue(result.success)
        self.assertEqual(
            ctx.step_history,
            [
                "official_signup.open_entry",
                "official_signup.navigate_signup",
                "official_signup.submit_email",
                "official_signup.submit_password",
            ],
        )
        self.assertTrue(ctx.official_signup_completed)


if __name__ == "__main__":
    unittest.main()
