import unittest
from unittest import mock

from platforms.chatgpt.codex_gui.context import CodexGUIFlowContext
from platforms.chatgpt.codex_gui.models import CodexGUIIdentity, FlowStepResult
from platforms.chatgpt.codex_gui.steps.official_signup import (
    ClickOfficialSignupFreeSignupStep,
    OpenOfficialSignupRuntimeProfileStep,
    SubmitOfficialSignupEmailStep,
    TypeChatGPTHomeStep,
)
from platforms.chatgpt.codex_gui.steps.registration.complete_registration_step import CompleteRegistrationStep
from platforms.chatgpt.codex_gui.workflows.official_signup_workflow import OfficialSignupWorkflow
from platforms.chatgpt.browser_session import PlaywrightEdgeBrowserSession
from platforms.chatgpt.codex_gui_driver import PyAutoGUICodexGUIDriver


class _FakeDriver:
    def __init__(self):
        self.current_url = ""
        self.events = []
        self.free_signup_visible = True

    def open_new_profile_browser(self, startup_url: str | None = None) -> None:
        self.events.append(("open_new_profile_browser", startup_url))
        self.current_url = startup_url or "about:blank"

    def navigate_with_address_bar(self, url: str) -> None:
        self.events.append(("navigate_with_address_bar", url))
        self.current_url = "https://chatgpt.com/"

    def click_named_target(self, name: str) -> None:
        self.events.append(("click", name))
        if name == "official_signup_free_signup_button":
            self.current_url = "https://chatgpt.com/"
        elif name == "official_signup_continue_button":
            self.current_url = "https://chatgpt.com/auth/signup/password"
        elif name == "complete_account_button":
            self.current_url = "https://chatgpt.com/"

    def input_text(self, name: str, text: str) -> None:
        self.events.append(("input", name, text))

    def peek_target_with_timeout(self, name: str, timeout_ms: int):
        self.events.append(("peek", name, timeout_ms))
        if name == "official_signup_free_signup_button" and self.free_signup_visible:
            return ("text", "免费注册", {"x": 1, "y": 1, "width": 2, "height": 2})
        raise RuntimeError("target not visible")

    def read_current_url(self) -> str:
        return self.current_url

    def close(self) -> None:
        self.events.append(("close",))


class _FakeEngine:
    def __init__(self, driver, *, pywinauto=False):
        self._driver = driver
        self._pywinauto = pywinauto
        self.logs = []
        self.waits = []
        self.stage_markers = []
        self.stage_ready_calls = []
        self.profile_completion_calls = []
        self.stage_ready_results = []

    def _log_step(self, stage: str, detail: str) -> None:
        self.logs.append((stage, detail))

    def _log(self, message: str, level: str = "info") -> None:
        self.logs.append((level, message))

    def _wait_timeout(self, key: str, default: int) -> int:
        return default

    def _stage_dom_probe_timeout_ms(self) -> int:
        return 750

    def _run_action(self, description: str, action) -> None:
        self.logs.append(("action", description))
        action()

    def _is_pywinauto_mode(self) -> bool:
        return self._pywinauto

    def _wait_for_stage_marker(self, stage: str, *, timeout: int) -> None:
        self.stage_markers.append((stage, timeout))

    def _wait_for_stage_ready(self, stage: str, *, timeout: int) -> str:
        self.stage_ready_calls.append((stage, timeout))
        if self.stage_ready_results:
            result = self.stage_ready_results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return self._driver.read_current_url()

    def _wait_for_registration_profile_disappear_or_terminal(self, *, timeout: int) -> str:
        self.profile_completion_calls.append(timeout)
        return "created"

    def _wait_for_any_url(self, fragments, *, timeout: int, stage: str) -> str:
        self.waits.append((list(fragments), timeout, stage))
        current_url = self._driver.read_current_url()
        if any(fragment in current_url for fragment in fragments):
            return current_url
        raise RuntimeError(f"URL did not match: {fragments}")


class _HistoryStep:
    def __init__(self, step_id: str):
        self.step_id = step_id

    def run(self, _engine, ctx):
        ctx.step_history.append(self.step_id)
        return FlowStepResult(success=True, stage_name=self.step_id)


def _make_context(extra_config=None):
    return CodexGUIFlowContext(
        identity=CodexGUIIdentity(
            email="user@example.com",
            password="password",
            full_name="User Example",
            age=30,
        ),
        auth_url="https://auth.openai.com/oauth/authorize?state=demo",
        auth_state="demo",
        email_adapter=object(),
        logger=lambda _message, _level="info": None,
        extra_config=dict(extra_config or {}),
    )


class OfficialSignupStartupStepTests(unittest.TestCase):
    def test_default_workflow_starts_with_runtime_profile_home_and_skips_address_bar_step(self):
        workflow = OfficialSignupWorkflow()

        self.assertEqual(
            [step.step_id for step in workflow._steps[:3]],
            [
                "official_signup.open_runtime_profile",
                "official_signup.click_free_signup",
                "official_signup.submit_email",
            ],
        )

    def test_default_workflow_reuses_original_registration_password_step(self):
        workflow = OfficialSignupWorkflow()

        self.assertEqual(workflow._steps[2].step_id, "official_signup.submit_email")
        self.assertEqual(workflow._steps[3].step_id, "registration.submit_password")

    def test_open_runtime_profile_step_initializes_new_profile_browser(self):
        driver = _FakeDriver()
        engine = _FakeEngine(driver)
        ctx = _make_context()

        result = OpenOfficialSignupRuntimeProfileStep().run(engine, ctx)

        self.assertTrue(result.success)
        self.assertEqual(driver.events, [("open_new_profile_browser", "https://chatgpt.com")])
        self.assertEqual(result.matched_url, "https://chatgpt.com")
        self.assertEqual(engine.stage_ready_calls, [("官网注册-首页", 60)])
        self.assertEqual(ctx.current_stage, "官网注册-打开 runtime profile 浏览器")
        self.assertIn("runtime profile", engine.logs[0][1])

    def test_open_runtime_profile_step_rejects_direct_configured_profile_reuse(self):
        driver = _FakeDriver()
        engine = _FakeEngine(driver)
        ctx = _make_context(
            {
                "codex_gui_edge_user_data_dir": r"D:\Profiles\Edge\User Data",
                "codex_gui_edge_snapshot_profile": False,
            }
        )

        with self.assertRaisesRegex(RuntimeError, "官网注册变体不允许直接复用真实 Edge Profile"):
            OpenOfficialSignupRuntimeProfileStep().run(engine, ctx)

        self.assertEqual(driver.events, [])

    def test_type_chatgpt_home_step_uses_address_bar_and_waits_for_chatgpt(self):
        driver = _FakeDriver()
        engine = _FakeEngine(driver)
        ctx = _make_context()

        result = TypeChatGPTHomeStep().run(engine, ctx)

        self.assertTrue(result.success)
        self.assertEqual(driver.events, [("navigate_with_address_bar", "chatgpt.com")])
        self.assertEqual(result.matched_url, "https://chatgpt.com/")
        self.assertEqual(engine.stage_ready_calls, [("官网注册-首页", 60)])
        self.assertEqual(engine.waits, [])

    def test_type_chatgpt_home_step_waits_for_home_stage_even_when_chatgpt_url_matches(self):
        driver = _FakeDriver()
        engine = _FakeEngine(driver, pywinauto=True)
        ctx = _make_context()

        result = TypeChatGPTHomeStep().run(engine, ctx)

        self.assertTrue(result.success)
        self.assertEqual(driver.events, [("navigate_with_address_bar", "chatgpt.com")])
        self.assertEqual(engine.stage_ready_calls, [("官网注册-首页", 60)])
        self.assertEqual(engine.stage_markers, [])
        self.assertEqual(engine.waits, [])

    def test_click_free_signup_step_waits_for_login_or_signup_dialog(self):
        driver = _FakeDriver()
        engine = _FakeEngine(driver, pywinauto=True)
        ctx = _make_context()

        result = ClickOfficialSignupFreeSignupStep().run(engine, ctx)

        self.assertTrue(result.success)
        self.assertEqual(driver.events, [("click", "official_signup_free_signup_button")])
        self.assertEqual(engine.stage_ready_calls, [("官网注册-登录或注册弹窗", 10)])
        self.assertEqual(engine.stage_markers, [])

    def test_click_free_signup_step_waits_for_dialog_even_when_chatgpt_url_matches(self):
        driver = _FakeDriver()
        engine = _FakeEngine(driver)
        ctx = _make_context()

        result = ClickOfficialSignupFreeSignupStep().run(engine, ctx)

        self.assertTrue(result.success)
        self.assertEqual(driver.events, [("click", "official_signup_free_signup_button")])
        self.assertEqual(engine.stage_ready_calls, [("官网注册-登录或注册弹窗", 10)])
        self.assertEqual(engine.waits, [])

    def test_click_free_signup_step_restarts_runtime_profile_when_dialog_missing(self):
        driver = _FakeDriver()
        engine = _FakeEngine(driver)
        engine.stage_ready_results = [
            RuntimeError("[官网注册-登录或注册弹窗] 等待页面阶段就绪超时"),
        ]
        ctx = _make_context()

        result = ClickOfficialSignupFreeSignupStep().run(engine, ctx)

        self.assertTrue(result.success)
        self.assertEqual(
            driver.events,
            [
                ("click", "official_signup_free_signup_button"),
                ("close",),
            ],
        )
        self.assertEqual(ctx.pending_step_id, "official_signup.open_runtime_profile")
        self.assertEqual(
            engine.stage_ready_calls,
            [
                ("官网注册-登录或注册弹窗", 10),
            ],
        )

    def test_official_signup_workflow_reopens_browser_and_replays_flow_when_dialog_missing(self):
        driver = _FakeDriver()
        engine = _FakeEngine(driver)
        engine.stage_ready_results = [
            "https://chatgpt.com",
            RuntimeError("[官网注册-登录或注册弹窗] 等待页面阶段就绪超时"),
            "https://chatgpt.com",
            "https://chatgpt.com/",
        ]
        ctx = _make_context()
        workflow = OfficialSignupWorkflow(
            steps=[
                OpenOfficialSignupRuntimeProfileStep(),
                ClickOfficialSignupFreeSignupStep(),
                _HistoryStep("official_signup.submit_email"),
            ]
        )

        result = workflow.run(engine, ctx)

        self.assertTrue(result.success)
        self.assertEqual(
            driver.events,
            [
                ("open_new_profile_browser", "https://chatgpt.com"),
                ("click", "official_signup_free_signup_button"),
                ("close",),
                ("open_new_profile_browser", "https://chatgpt.com"),
                ("click", "official_signup_free_signup_button"),
            ],
        )
        self.assertEqual(
            engine.stage_ready_calls,
            [
                ("官网注册-首页", 60),
                ("官网注册-登录或注册弹窗", 10),
                ("官网注册-首页", 60),
                ("官网注册-登录或注册弹窗", 10),
            ],
        )
        self.assertEqual(
            ctx.step_history,
            [
                "official_signup.open_runtime_profile",
                "official_signup.click_free_signup",
                "official_signup.open_runtime_profile",
                "official_signup.click_free_signup",
                "official_signup.submit_email",
            ],
        )
        self.assertTrue(ctx.official_signup_completed)

    def test_submit_email_waits_for_password_page_marker_in_pywinauto_mode(self):
        driver = _FakeDriver()
        engine = _FakeEngine(driver, pywinauto=True)
        ctx = _make_context()

        result = SubmitOfficialSignupEmailStep().run(engine, ctx)

        self.assertTrue(result.success)
        self.assertEqual(
            driver.events,
            [
                ("input", "official_signup_email_input", "user@example.com"),
                ("click", "official_signup_continue_button"),
            ],
        )
        self.assertEqual(engine.stage_markers, [("注册-密码页", 60)])
        self.assertEqual(result.matched_url, "/password")

    def test_complete_registration_returns_created_when_official_signup_age_prompt_disappears(self):
        driver = _FakeDriver()
        engine = _FakeEngine(driver, pywinauto=True)
        ctx = _make_context()
        ctx.gui_variant = "official_signup"

        result = CompleteRegistrationStep().run(engine, ctx)

        self.assertTrue(result.success)
        self.assertEqual(ctx.terminal_state, "created")
        self.assertEqual(result.terminal_state, "created")
        self.assertEqual(engine.profile_completion_calls, [60])

    def test_driver_open_new_profile_browser_ensures_browser_session(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(extra_config={}, logger_fn=logs.append)
        driver._browser_session.ensure_browser_session = mock.Mock(return_value=object())

        driver.open_new_profile_browser("https://chatgpt.com")

        driver._browser_session.ensure_browser_session.assert_called_once_with(startup_url="https://chatgpt.com")
        self.assertTrue(any("runtime profile" in entry for entry in logs))

    def test_driver_open_new_profile_browser_in_pywinauto_mode_does_not_start_playwright_session(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(
            extra_config={"codex_gui_target_detector": "pywinauto"},
            logger_fn=logs.append,
        )
        driver._browser_session.ensure_browser_session = mock.Mock(side_effect=AssertionError("must not attach playwright"))
        driver._browser_session.launch_edge_process_only = mock.Mock(return_value=object())

        driver.open_new_profile_browser("https://chatgpt.com")

        driver._browser_session.launch_edge_process_only.assert_called_once_with(startup_url="https://chatgpt.com")
        driver._browser_session.ensure_browser_session.assert_not_called()

    def test_driver_address_bar_navigation_normalizes_bare_domain_for_playwright_mode(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(extra_config={}, logger_fn=logs.append)
        driver._browser_session.open_url = mock.Mock()

        driver.navigate_with_address_bar("chatgpt.com")

        driver._browser_session.open_url.assert_called_once_with("https://chatgpt.com", reuse_current=True)

    def test_driver_address_bar_navigation_uses_pywinauto_address_bar_method(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(
            extra_config={"codex_gui_target_detector": "pywinauto"},
            logger_fn=logs.append,
        )
        driver._navigate_with_address_bar = mock.Mock()

        driver.navigate_with_address_bar("chatgpt.com")

        driver._navigate_with_address_bar.assert_called_once_with("chatgpt.com")

    def test_browser_session_process_only_launch_starts_edge_without_playwright_or_cdp(self):
        logs = []
        session = PlaywrightEdgeBrowserSession(
            extra_config={
                "codex_gui_edge_profile_directory": "Default",
                "codex_gui_edge_startup_url": "about:blank",
            },
            logger_fn=logs.append,
            import_playwright=lambda: self.fail("playwright should not be imported"),
            resolve_edge_command=lambda: r"C:\Edge\msedge.exe",
        )
        process = mock.Mock()
        session.prepare_edge_runtime_user_data_dir = mock.Mock(return_value=r"D:\Temp\EdgeRuntime")

        with mock.patch("platforms.chatgpt.browser_session.subprocess.Popen", return_value=process) as popen_mock, mock.patch(
            "platforms.chatgpt.browser_session.time.sleep"
        ):
            launched = session.launch_edge_process_only()

        self.assertIs(launched, process)
        args = popen_mock.call_args.args[0]
        self.assertNotIn("--remote-debugging-port", " ".join(args))
        self.assertIn(r"--user-data-dir=D:\Temp\EdgeRuntime", args)
        self.assertIn("--profile-directory=Default", args)
        self.assertEqual(args[-1], "about:blank")
        self.assertIs(session._edge_process, process)
        self.assertEqual(session._edge_user_data_dir, r"D:\Temp\EdgeRuntime")

    def test_browser_session_process_only_launch_uses_explicit_startup_url(self):
        logs = []
        session = PlaywrightEdgeBrowserSession(
            extra_config={
                "codex_gui_edge_profile_directory": "Default",
                "codex_gui_edge_startup_url": "about:blank",
            },
            logger_fn=logs.append,
            import_playwright=lambda: self.fail("playwright should not be imported"),
            resolve_edge_command=lambda: r"C:\Edge\msedge.exe",
        )
        process = mock.Mock()
        session.prepare_edge_runtime_user_data_dir = mock.Mock(return_value=r"D:\Temp\EdgeRuntime")

        with mock.patch("platforms.chatgpt.browser_session.subprocess.Popen", return_value=process) as popen_mock, mock.patch(
            "platforms.chatgpt.browser_session.time.sleep"
        ):
            launched = session.launch_edge_process_only(startup_url="https://chatgpt.com")

        self.assertIs(launched, process)
        args = popen_mock.call_args.args[0]
        self.assertEqual(args[-1], "https://chatgpt.com")


if __name__ == "__main__":
    unittest.main()
