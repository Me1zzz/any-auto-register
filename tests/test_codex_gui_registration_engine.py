import unittest
from unittest import mock
import sys
import types

from platforms.chatgpt.browser_session import PlaywrightEdgeBrowserSession
from platforms.chatgpt.geometry_helper import CodexGUIGeometryHelper
from platforms.chatgpt.gui_controller import PyAutoGUICodexGUIController
from platforms.chatgpt.target_detector import (
    CodexGUITargetResolution,
    PlaywrightCodexGUITargetDetector,
    PywinautoCodexGUITargetDetector,
)

curl_cffi_stub = types.ModuleType("curl_cffi")
setattr(curl_cffi_stub, "requests", types.SimpleNamespace(Session=lambda *args, **kwargs: mock.Mock()))
sys.modules.setdefault("curl_cffi", curl_cffi_stub)

smstome_tool_stub = types.ModuleType("smstome_tool")
setattr(smstome_tool_stub, "PhoneEntry", type("PhoneEntry", (), {}))
setattr(smstome_tool_stub, "get_unused_phone", lambda *args, **kwargs: None)
setattr(smstome_tool_stub, "mark_phone_blacklisted", lambda *args, **kwargs: None)
setattr(smstome_tool_stub, "parse_country_slugs", lambda value: [])
setattr(smstome_tool_stub, "update_global_phone_list", lambda *args, **kwargs: 0)
setattr(smstome_tool_stub, "wait_for_otp", lambda *args, **kwargs: None)
sys.modules.setdefault("smstome_tool", smstome_tool_stub)

from platforms.chatgpt.codex_gui_registration_engine import (
    CodexGUIDriver,
    CodexGUIRegistrationEngine,
    EmailServiceAdapter,
    PyAutoGUICodexGUIDriver,
)


class _DummyEmailService:
    service_type = type("ST", (), {"value": "dummy"})()

    def __init__(self, codes):
        self.codes = list(codes)
        self.calls = []

    def create_email(self):
        return {"email": "user@example.com", "service_id": "svc-1"}

    def get_verification_code(self, **kwargs):
        self.calls.append(kwargs)
        return self.codes.pop(0) if self.codes else None


class _FakePyAutoGUI:
    def __init__(self):
        self.current_position = (0, 0)
        self.moves = []
        self.clicks = []
        self.write_calls = []

    def size(self):
        return (1920, 1080)

    def position(self):
        return self.current_position

    def moveTo(self, x, y, duration=0):
        self.moves.append((x, y, duration))
        self.current_position = (x, y)

    def click(self, x, y):
        self.clicks.append((x, y))
        self.current_position = (x, y)

    def write(self, text, interval=0):
        self.write_calls.append((text, interval))

    def hotkey(self, *keys):
        return None

    def press(self, key):
        return None


class _FakeDriver(CodexGUIDriver):
    def __init__(self):
        self.current_url = ""
        self.events = []
        self.retry_pending = False

    def open_url(self, url: str, *, reuse_current: bool = False) -> None:
        self.events.append(("open_url", url, reuse_current))
        self.current_url = "https://auth.openai.com/log-in"

    def click_named_target(self, name: str) -> None:
        self.events.append(("click", name))
        transitions = {
            "register_button": "https://auth.openai.com/create-account",
            "otp_login_button": "https://auth.openai.com/email-verification",
            "complete_account_button": "https://auth.openai.com/add-phone",
            "resend_email_button": "https://auth.openai.com/email-verification",
            "retry_button": "https://auth.openai.com/create-account/password",
        }
        if name == "continue_button":
            if self.current_url.endswith("/sign-in-with-chatgpt/codex/consent"):
                self.current_url = "https://chatgpt.com/"
                return
            if self.current_url.endswith("/log-in"):
                self.current_url = "https://auth.openai.com/log-in/password"
                return
            if self.current_url.endswith("/create-account"):
                self.current_url = "https://auth.openai.com/create-account/password"
                return
            if self.current_url.endswith("/create-account/password"):
                self.current_url = "https://auth.openai.com/email-verification"
                return
        next_url = transitions.get(name)
        if next_url:
            self.current_url = next_url

    def input_text(self, name: str, text: str) -> None:
        self.events.append(("input", name, text))
        if name == "email_input" and self.current_url.endswith("/create-account"):
            return
        if name == "password_input":
            self.current_url = "https://auth.openai.com/create-account/password"
        elif name == "verification_code_input":
            if any(event == ("click", "otp_login_button") for event in self.events):
                self.current_url = "https://auth.openai.com/sign-in-with-chatgpt/codex/consent"
            else:
                self.current_url = "https://auth.openai.com/about-you"

    def read_current_url(self) -> str:
        return self.current_url

    def press_keys(self, *keys: str) -> None:
        self.events.append(("press", keys))

    def close(self) -> None:
        self.events.append(("close",))

    def wander_while_waiting(self, stage: str) -> None:
        self.events.append(("wander", stage))

    def page_marker_matched(self, stage: str) -> tuple[bool, str | None]:
        if stage == "注册-终态判断-add/phone" and self.current_url.endswith("/add-phone"):
            return True, "电话号码是必填项"
        if stage == "登录-终态判断-add/phone" and self.current_url.endswith("/add-phone"):
            return True, "电话号码是必填项"
        if stage == "注册-终态判断-consent" and self.current_url.endswith("/sign-in-with-chatgpt/codex/consent"):
            return True, "使用 ChatGPT 登录到 Codex"
        if stage == "登录-终态判断-consent" and self.current_url.endswith("/sign-in-with-chatgpt/codex/consent"):
            return True, "使用 ChatGPT 登录到 Codex"
        if stage == "注册-成功标志页" and self.current_url == "https://chatgpt.com/":
            return True, "You can close this window."
        if stage == "登录-成功标志页" and self.current_url == "https://chatgpt.com/":
            return True, "You can close this window."
        return False, None


class _FakeDriverWithLoginFailure(_FakeDriver):
    def input_text(self, name: str, text: str) -> None:
        super().input_text(name, text)
        if name == "verification_code_input" and any(event == ("click", "otp_login_button") for event in self.events):
            self.current_url = "https://auth.openai.com/add-phone"


class _FakeDriverWithRetry(_FakeDriver):
    def __init__(self):
        super().__init__()
        self._errored_once = False

    def click_named_target(self, name: str) -> None:
        if (
            name == "continue_button"
            and self.current_url.endswith("/create-account/password")
            and not self._errored_once
        ):
            self.events.append(("click", name))
            self.current_url = "https://auth.openai.com/error"
            self._errored_once = True
            return
        super().click_named_target(name)


class _FakeDriverWithRegisterConsent(_FakeDriver):
    def click_named_target(self, name: str) -> None:
        if name == "complete_account_button":
            self.events.append(("click", name))
            self.current_url = "https://auth.openai.com/sign-in-with-chatgpt/codex/consent"
            return
        super().click_named_target(name)


class _FakeDriverWithDomAdvance(_FakeDriver):
    def __init__(self):
        super().__init__()
        self.dom_stage = "log-in"

    def click_named_target(self, name: str) -> None:
        self.events.append(("click", name))
        if name == "register_button":
            self.dom_stage = "create-account"
            return
        if name == "continue_button" and self.dom_stage == "create-account":
            self.current_url = "https://auth.openai.com/create-account/password"
            return
        super().click_named_target(name)

    def input_text(self, name: str, text: str) -> None:
        self.events.append(("input", name, text))
        if name == "email_input":
            self.dom_stage = "create-account"
            return
        super().input_text(name, text)

    def peek_target(self, name: str):
        if self.dom_stage == "create-account" and name == "email_input":
            return ("css", "input[placeholder*='电子邮件地址']", {"x": 1.0, "y": 2.0, "width": 3.0, "height": 4.0})
        raise RuntimeError(f"target not visible: {name}")

    def peek_target_with_timeout(self, name: str, timeout_ms: int):
        return self.peek_target(name)

    def page_marker_matched(self, stage: str):
        return False, None


class _FakeDriverWithStrictMarkers(_FakeDriver):
    def __init__(self):
        super().__init__()
        self.stage_markers: dict[str, tuple[bool, str | None]] = {}

    def page_marker_matched(self, stage: str):
        return self.stage_markers.get(stage, (False, None))


class _FakeDriverWithLoginConsentSuccess(_FakeDriver):
    def input_text(self, name: str, text: str) -> None:
        super().input_text(name, text)
        if name == "verification_code_input" and any(event == ("click", "otp_login_button") for event in self.events):
            self.current_url = "https://auth.openai.com/sign-in-with-chatgpt/codex/consent"

    def page_marker_matched(self, stage: str):
        if stage == "登录-终态判断-consent" and self.current_url.endswith("/sign-in-with-chatgpt/codex/consent"):
            return True, "使用 ChatGPT 登录到 Codex"
        if stage == "登录-成功标志页" and self.current_url == "https://chatgpt.com/":
            return True, "You can close this window."
        return super().page_marker_matched(stage)


class _FakeDriverWithRegisterConsentSuccess(_FakeDriverWithRegisterConsent):
    def page_marker_matched(self, stage: str):
        if stage == "注册-终态判断-consent" and self.current_url.endswith("/sign-in-with-chatgpt/codex/consent"):
            return True, "使用 ChatGPT 登录到 Codex"
        if stage == "注册-成功标志页" and self.current_url == "https://chatgpt.com/":
            return True, "You can close this window."
        return False, None


class CodexGUIRegistrationEngineTests(unittest.TestCase):
    def test_engine_module_reexports_driver_classes(self):
        from platforms.chatgpt.codex_gui_driver import CodexGUIDriver as SplitCodexGUIDriver
        from platforms.chatgpt.codex_gui_driver import PyAutoGUICodexGUIDriver as SplitPyAutoGUICodexGUIDriver

        self.assertIs(CodexGUIDriver, SplitCodexGUIDriver)
        self.assertIs(PyAutoGUICodexGUIDriver, SplitPyAutoGUICodexGUIDriver)

    def _make_engine(self, email_service, driver):
        engine = CodexGUIRegistrationEngine(
            email_service=email_service,
            callback_logger=lambda _msg: None,
            extra_config={
                "chatgpt_registration_mode": "codex_gui",
                "codex_gui_retry_target": "retry_button",
                "codex_gui_resend_target": "resend_email_button",
                "codex_gui_error_retry_url_contains": ["/error"],
            },
        )
        engine._build_driver = lambda: driver
        engine._fetch_auth_payload = lambda: {
            "state": "demo-state",
            "url": "https://auth.openai.com/oauth/authorize?state=demo-state",
        }
        return engine

    def test_run_completes_register_and_login_flow(self):
        email_service = _DummyEmailService(["111111", "222222"])
        driver = _FakeDriver()
        engine = self._make_engine(email_service, driver)

        result = engine.run()

        self.assertTrue(result.success)
        self.assertIsNotNone(result.metadata)
        metadata = result.metadata or {}
        self.assertEqual(result.email, "user@example.com")
        self.assertEqual(result.account_id, "svc-1")
        self.assertTrue(metadata["codex_gui_register_completed"])
        self.assertTrue(metadata["codex_gui_login_completed"])
        self.assertTrue(metadata["codex_gui_oauth_login_completed"])
        self.assertIn(("click", "register_button"), driver.events)
        self.assertIn(("click", "otp_login_button"), driver.events)
        self.assertIn(("click", "continue_button"), driver.events)

    def test_run_fails_when_login_ends_at_add_phone(self):
        email_service = _DummyEmailService(["111111", "222222"])
        driver = _FakeDriverWithLoginFailure()
        engine = self._make_engine(email_service, driver)

        result = engine.run()

        self.assertFalse(result.success)
        self.assertIn("add-phone", result.error_message)

    def test_run_resends_email_and_excludes_old_codes(self):
        email_service = _DummyEmailService(["111111", None, "222222"])
        driver = _FakeDriver()
        engine = self._make_engine(email_service, driver)

        result = engine.run()

        self.assertTrue(result.success)
        self.assertEqual(len(email_service.calls), 3)
        self.assertEqual(email_service.calls[0]["exclude_codes"], set())
        self.assertEqual(email_service.calls[1]["exclude_codes"], {"111111"})
        self.assertEqual(email_service.calls[2]["exclude_codes"], {"111111"})
        self.assertIn(("click", "resend_email_button"), driver.events)

    def test_collect_verification_code_uses_pywinauto_resend_strategy(self):
        email_service = _DummyEmailService([None, None, None])
        driver = _FakeDriver()
        engine = CodexGUIRegistrationEngine(
            email_service=email_service,
            callback_logger=lambda _msg: None,
            extra_config={
                "chatgpt_registration_mode": "codex_gui",
                "codex_gui_target_detector": "pywinauto",
                "codex_gui_resend_target": "resend_email_button",
                "codex_gui_otp_resend_wait_seconds_min": 5,
                "codex_gui_otp_resend_wait_seconds_max": 8,
                "codex_gui_otp_max_resends_min": 8,
                "codex_gui_otp_max_resends_max": 8,
            },
        )
        engine._driver = driver
        adapter = mock.Mock(spec=EmailServiceAdapter)
        adapter.email = "user@example.com"
        adapter.build_exclude_codes.return_value = set()
        adapter.wait_for_verification_code.return_value = None

        with self.assertRaisesRegex(RuntimeError, "多次重发后仍未收到验证码"), mock.patch(
            "platforms.chatgpt.codex_gui_registration_engine.random.uniform", return_value=5.5
        ):
            engine._collect_verification_code(adapter, stage="注册")

        self.assertEqual(adapter.wait_for_verification_code.call_count, 8)
        resend_clicks = [event for event in driver.events if event == ("click", "resend_email_button")]
        self.assertEqual(len(resend_clicks), 7)

    def test_collect_verification_code_pywinauto_retries_after_timeout(self):
        email_service = _DummyEmailService([])
        driver = _FakeDriver()
        engine = CodexGUIRegistrationEngine(
            email_service=email_service,
            callback_logger=lambda _msg: None,
            extra_config={
                "chatgpt_registration_mode": "codex_gui",
                "codex_gui_target_detector": "pywinauto",
                "codex_gui_resend_target": "resend_email_button",
                "codex_gui_otp_resend_wait_seconds_min": 5,
                "codex_gui_otp_resend_wait_seconds_max": 5,
                "codex_gui_otp_max_resends_min": 2,
                "codex_gui_otp_max_resends_max": 2,
            },
        )
        engine._driver = driver
        adapter = mock.Mock(spec=EmailServiceAdapter)
        adapter.email = "user@example.com"
        adapter.build_exclude_codes.return_value = set()
        adapter.wait_for_verification_code.side_effect = [TimeoutError("mail wait timed out"), "123456"]

        code = engine._collect_verification_code(adapter, stage="注册")

        self.assertEqual(code, "123456")
        self.assertEqual(adapter.wait_for_verification_code.call_count, 2)
        resend_clicks = [event for event in driver.events if event == ("click", "resend_email_button")]
        self.assertEqual(len(resend_clicks), 1)

    def test_collect_verification_code_pywinauto_propagates_non_timeout_error(self):
        email_service = _DummyEmailService([])
        driver = _FakeDriver()
        engine = CodexGUIRegistrationEngine(
            email_service=email_service,
            callback_logger=lambda _msg: None,
            extra_config={
                "chatgpt_registration_mode": "codex_gui",
                "codex_gui_target_detector": "pywinauto",
                "codex_gui_resend_target": "resend_email_button",
                "codex_gui_otp_resend_wait_seconds_min": 5,
                "codex_gui_otp_resend_wait_seconds_max": 5,
                "codex_gui_otp_max_resends_min": 2,
                "codex_gui_otp_max_resends_max": 2,
            },
        )
        engine._driver = driver
        adapter = mock.Mock(spec=EmailServiceAdapter)
        adapter.email = "user@example.com"
        adapter.build_exclude_codes.return_value = set()
        adapter.wait_for_verification_code.side_effect = RuntimeError("mailbox broken")

        with self.assertRaisesRegex(RuntimeError, "mailbox broken"):
            engine._collect_verification_code(adapter, stage="注册")

        resend_clicks = [event for event in driver.events if event == ("click", "resend_email_button")]
        self.assertEqual(len(resend_clicks), 0)

    def test_run_retries_last_action_when_error_page_detected(self):
        email_service = _DummyEmailService(["111111", "222222"])
        driver = _FakeDriverWithRetry()
        engine = self._make_engine(email_service, driver)

        result = engine.run()

        self.assertTrue(result.success)
        self.assertIn(("click", "retry_button"), driver.events)
        continue_clicks = [event for event in driver.events if event == ("click", "continue_button")]
        self.assertGreaterEqual(len(continue_clicks), 2)

    def test_run_clicks_continue_when_registration_directly_enters_consent(self):
        email_service = _DummyEmailService(["111111", "222222"])
        driver = _FakeDriverWithRegisterConsentSuccess()
        engine = self._make_engine(email_service, driver)

        result = engine.run()

        self.assertTrue(result.success)
        self.assertIn(("click", "complete_account_button"), driver.events)
        self.assertIn(("click", "continue_button"), driver.events)
        self.assertEqual(driver.current_url, "https://chatgpt.com/")

    def test_run_succeeds_when_login_consent_leads_to_success_marker(self):
        email_service = _DummyEmailService(["111111", "222222"])
        driver = _FakeDriverWithLoginConsentSuccess()
        engine = self._make_engine(email_service, driver)

        result = engine.run()

        self.assertTrue(result.success)
        self.assertEqual(driver.current_url, "https://chatgpt.com/")

    def test_wait_for_stage_accepts_dom_match_when_url_has_not_updated(self):
        email_service = _DummyEmailService(["111111", "222222"])
        driver = _FakeDriverWithDomAdvance()
        engine = self._make_engine(email_service, driver)
        engine._driver = driver

        driver.click_named_target("register_button")
        current = engine._wait_for_any_url(
            ["/create-account"],
            timeout=1,
            stage="注册-创建账户页",
        )

        self.assertEqual(current, "")
        self.assertIn(("click", "register_button"), driver.events)

    def test_driver_prefers_edge_when_opening_new_oauth_window(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(
            extra_config={"codex_gui_edge_command": r"C:\Edge\msedge.exe"},
            logger_fn=logs.append,
        )

        fake_page = mock.Mock()
        fake_page.url = "https://auth.openai.com/log-in"
        driver._browser_session.open_url = mock.Mock()

        with mock.patch("platforms.chatgpt.codex_gui_registration_engine.time.sleep"):
            driver.open_url("https://auth.openai.com/oauth/authorize?state=demo", reuse_current=False)

        driver._browser_session.open_url.assert_called_once_with(
            "https://auth.openai.com/oauth/authorize?state=demo",
            reuse_current=False,
        )

    def test_ensure_browser_session_defaults_to_cdp_attach_mode(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(extra_config={}, logger_fn=logs.append)
        driver._browser_session.ensure_edge_cdp_session = mock.Mock(return_value="page")

        page = driver._ensure_browser_session()

        self.assertEqual(page, "page")
        driver._browser_session.ensure_edge_cdp_session.assert_called_once()
        self.assertTrue(any("attach_mode=cdp" in entry for entry in logs))

    def test_wait_for_cdp_endpoint_returns_base_url(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(extra_config={}, logger_fn=logs.append)
        driver._cdp_port = 9222
        fake_response = mock.Mock()
        fake_response.read.return_value = b'{"webSocketDebuggerUrl":"ws://127.0.0.1:9222/devtools/browser/demo"}'
        fake_context = mock.Mock()
        fake_context.__enter__ = mock.Mock(return_value=fake_response)
        fake_context.__exit__ = mock.Mock(return_value=False)

        with mock.patch("platforms.chatgpt.browser_session.urllib.request.urlopen", return_value=fake_context):
            base_url = driver._wait_for_cdp_endpoint()

        self.assertEqual(base_url, "http://127.0.0.1:9222")

    def test_wait_for_cdp_endpoint_mentions_profile_when_timeout_with_configured_profile(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(
            extra_config={
                "codex_gui_edge_user_data_dir": r"C:\Users\M\AppData\Local\Microsoft\Edge\User Data",
                "codex_gui_edge_profile_directory": "Default",
            },
            logger_fn=logs.append,
        )
        driver._cdp_port = 9222

        with mock.patch(
            "platforms.chatgpt.browser_session.urllib.request.urlopen",
            side_effect=TimeoutError("timed out"),
        ), mock.patch("platforms.chatgpt.browser_session.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "profile 可能未真正以调试模式启动"):
                driver._wait_for_cdp_endpoint()

    def test_validate_profile_for_cdp_raises_when_lock_exists(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(
            extra_config={
                "codex_gui_edge_user_data_dir": r"C:\Users\M\AppData\Local\Microsoft\Edge\User Data",
                "codex_gui_edge_profile_directory": "Default",
                "codex_gui_edge_snapshot_profile": False,
            },
            logger_fn=logs.append,
        )

        with mock.patch.object(driver._browser_session, "profile_lock_exists", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "profile 可能正被运行中的浏览器占用"):
                driver._validate_profile_for_cdp()

    def test_pick_cdp_page_prefers_non_edge_tabs(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(extra_config={}, logger_fn=logs.append)
        page1 = mock.Mock(url="edge://newtab")
        page2 = mock.Mock(url="https://auth.openai.com/log-in")
        context = mock.Mock()
        context.pages = [page1, page2]
        browser = mock.Mock()
        browser.contexts = [context]
        driver._browser = browser

        page = driver._pick_cdp_page()

        self.assertIs(page, page2)

    def test_build_edge_launch_args_uses_configured_profile_directory(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(
            extra_config={
                "codex_gui_edge_command": r"C:\Edge\msedge.exe",
                "codex_gui_edge_user_data_dir": r"D:\Profiles\EdgeUserData",
                "codex_gui_edge_profile_directory": "Profile 3",
                "codex_gui_edge_startup_url": "https://auth.openai.com/",
            },
            logger_fn=logs.append,
        )
        driver._cdp_port = 9333

        with mock.patch.object(driver._browser_session, "prepare_edge_runtime_user_data_dir", return_value=r"D:\Temp\EdgeSnapshot"):
            args = driver._build_edge_launch_args()

        self.assertIn(r"--user-data-dir=D:\Temp\EdgeSnapshot", args)
        self.assertIn("--profile-directory=Profile 3", args)
        self.assertEqual(args[-1], "https://auth.openai.com/")

    def test_prepare_edge_runtime_user_data_dir_uses_snapshot_by_default(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(
            extra_config={
                "codex_gui_edge_user_data_dir": r"D:\Profiles\EdgeUserData",
                "codex_gui_edge_profile_directory": "Profile 1",
            },
            logger_fn=logs.append,
        )

        with mock.patch.object(driver._browser_session, "snapshot_source_profile", return_value=r"D:\Temp\EdgeSnapshot") as snapshot_mock:
            runtime_dir = driver._prepare_edge_runtime_user_data_dir(r"D:\Profiles\EdgeUserData")

        self.assertEqual(runtime_dir, r"D:\Temp\EdgeSnapshot")
        snapshot_mock.assert_called_once_with(r"D:\Profiles\EdgeUserData", "Profile 1")

    def test_validate_profile_for_cdp_skips_lock_check_in_snapshot_mode(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(
            extra_config={
                "codex_gui_edge_user_data_dir": r"D:\Profiles\EdgeUserData",
                "codex_gui_edge_profile_directory": "Profile 1",
            },
            logger_fn=logs.append,
        )

        with mock.patch.object(driver._browser_session, "profile_lock_exists", side_effect=AssertionError("should not be called")):
            driver._validate_profile_for_cdp()

        self.assertTrue(any("已启用 Profile 快照模式" in entry for entry in logs))

    def test_close_does_not_delete_configured_edge_profile_dir(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(
            extra_config={
                "codex_gui_edge_user_data_dir": r"D:\Profiles\EdgeUserData",
                "codex_gui_edge_snapshot_profile": False,
            },
            logger_fn=logs.append,
        )
        driver._edge_user_data_dir = r"D:\Profiles\EdgeUserData"
        driver._edge_process = mock.Mock()

        with mock.patch("platforms.chatgpt.browser_session.shutil.rmtree") as rmtree_mock:
            driver.close()

        rmtree_mock.assert_not_called()

    def test_close_terminates_spawned_edge_process(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(extra_config={}, logger_fn=logs.append)
        process = mock.Mock()
        driver._edge_process = process
        driver._edge_user_data_dir = None
        driver._browser = mock.Mock()
        driver._pw = mock.Mock()

        driver.close()

        process.terminate.assert_called_once()
        process.wait.assert_called_once()

    def test_ensure_edge_cdp_session_cleans_process_on_endpoint_failure(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(extra_config={}, logger_fn=logs.append)
        process = mock.Mock()
        fake_pw = mock.Mock()
        driver._pw = fake_pw
        driver._browser_session.validate_profile_for_cdp = mock.Mock()
        driver._browser_session.build_edge_launch_args = mock.Mock(return_value=[r"C:\Edge\msedge.exe"])

        with mock.patch("platforms.chatgpt.browser_session.subprocess.Popen", return_value=process):
            with mock.patch.object(driver._browser_session, "wait_for_cdp_endpoint", side_effect=RuntimeError("cdp timeout")):
                with self.assertRaisesRegex(RuntimeError, "cdp timeout"):
                    driver._ensure_edge_cdp_session()

        process.terminate.assert_called_once()
        process.wait.assert_called_once()
        self.assertIsNone(driver._edge_process)

    def test_run_logs_step_start_messages(self):
        email_service = _DummyEmailService(["111111", "222222"])
        driver = _FakeDriver()
        captured_logs: list[str] = []
        engine = CodexGUIRegistrationEngine(
            email_service=email_service,
            callback_logger=captured_logs.append,
            extra_config={
                "chatgpt_registration_mode": "codex_gui",
                "codex_gui_retry_target": "retry_button",
                "codex_gui_resend_target": "resend_email_button",
                "codex_gui_error_retry_url_contains": ["/error"],
                "codex_gui_edge_command": r"C:\Edge\msedge.exe",
            },
        )
        engine._build_driver = lambda: driver
        engine._fetch_auth_payload = lambda: {
            "state": "demo-state",
            "url": "https://auth.openai.com/oauth/authorize?state=demo-state",
        }

        result = engine.run()

        self.assertTrue(result.success)
        self.assertTrue(any("[准备] 开始: 初始化 Codex GUI 注册/登录流程" in entry for entry in captured_logs))
        self.assertTrue(any("[注册] 开始: 使用 Edge 最大化窗口打开 OAuth 授权链接" in entry for entry in captured_logs))
        self.assertTrue(any("[注册-打开登录页] 开始: 等待页面命中: /log-in" in entry for entry in captured_logs))
        self.assertTrue(any("[注册] 点击注册按钮" in entry for entry in captured_logs))

    def test_driver_converts_dom_box_to_screen_point(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(extra_config={}, logger_fn=logs.append)
        driver._page = mock.Mock()
        driver._page.evaluate.return_value = {
            "screenX": 10,
            "screenY": 20,
            "outerWidth": 1200,
            "outerHeight": 900,
            "innerWidth": 1180,
            "innerHeight": 820,
            "screenWidth": 1920,
            "screenHeight": 1080,
            "visualOffsetLeft": 0,
            "visualOffsetTop": 0,
            "url": "https://auth.openai.com/log-in",
            "title": "登录",
        }

        fake_gui = mock.Mock()
        fake_gui.size.return_value = (1920, 1080)

        with mock.patch.object(driver, "_import_pyautogui", return_value=fake_gui):
            point = driver._screen_point_from_box(
                "register_button",
                {"x": 100, "y": 200, "width": 80, "height": 20},
            )

        self.assertEqual(point, (160, 300))
        self.assertTrue(any("[坐标] 计算完成" in entry for entry in logs))

    def test_driver_chooses_random_point_inside_middle_80_percent(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(extra_config={}, logger_fn=logs.append)

        with mock.patch("platforms.chatgpt.geometry_helper.random.uniform", side_effect=[26.0, 42.0]):
            dom_x, dom_y = driver._random_middle80_point_from_box(
                "register_button",
                {"x": 10.0, "y": 20.0, "width": 100.0, "height": 40.0},
            )

        self.assertEqual((dom_x, dom_y), (26.0, 42.0))
        self.assertTrue(any("[DOM] 随机点击点" in entry for entry in logs))

    def test_click_screen_point_uses_humanized_multi_segment_move(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(extra_config={"codex_gui_windmouse_max_steps": 12}, logger_fn=logs.append)
        fake_gui = _FakePyAutoGUI()

        with mock.patch.object(driver, "_import_pyautogui", return_value=fake_gui), mock.patch(
            "platforms.chatgpt.gui_controller.time.sleep"
        ), mock.patch(
            "platforms.chatgpt.gui_controller.random.uniform",
            return_value=0.0,
        ):
            driver._click_screen_point("register_button", 100, 200)

        self.assertGreaterEqual(len(fake_gui.moves), 1)
        self.assertEqual(fake_gui.clicks[-1], (100, 200))
        self.assertTrue(any("[GUI] WindMouse 移动" in entry for entry in logs))
        self.assertTrue(any("[GUI] WindMouse 轨迹摘要" in entry for entry in logs))
        self.assertFalse(any("[GUI] WindMouse 轨迹点" in entry for entry in logs))
        self.assertTrue(any("[节奏] 操作后随机停顿: reason=click:register_button" in entry for entry in logs))

    def test_driver_resolves_builtin_text_target(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(extra_config={}, logger_fn=logs.append)
        fake_locator = mock.Mock()
        fake_locator.bounding_box.return_value = {"x": 1, "y": 2, "width": 3, "height": 4}
        fake_page = mock.Mock()
        fake_page.content.return_value = "<html><body><a>注册</a></body></html>"
        fake_page.get_by_text.return_value.first = fake_locator
        driver._page = fake_page

        resolved = driver._resolve_target_locator("register_button")

        self.assertIs(resolved.locator, fake_locator)
        self.assertEqual(resolved.strategy_kind, "text")
        self.assertEqual(resolved.strategy_value, "注册")
        self.assertEqual(resolved.box, {"x": 1, "y": 2, "width": 3, "height": 4})
        self.assertTrue(any("[DOM] 开始获取当前页面 DOM: target=register_button" in entry for entry in logs))

    def test_driver_resolves_complete_account_button_with_alternate_text_variant(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(extra_config={}, logger_fn=logs.append)
        fake_role_locator = mock.Mock()
        fake_text_locator = mock.Mock()
        fake_role_locator.wait_for.side_effect = RuntimeError("primary text missing")
        fake_text_locator.wait_for.side_effect = RuntimeError("primary text missing")
        fake_alt_role_locator = mock.Mock()
        fake_alt_role_locator.bounding_box.return_value = {"x": 10, "y": 20, "width": 30, "height": 40}

        fake_page = mock.Mock()
        fake_page.content.return_value = "<html><body><button>完成帐户创建</button></body></html>"

        def _get_by_role(role, name, exact=False):
            if name == "完成账户创建":
                return mock.Mock(first=fake_role_locator)
            if name == "完成帐户创建":
                return mock.Mock(first=fake_alt_role_locator)
            return mock.Mock(first=mock.Mock())

        def _get_by_text(text, exact=False):
            if text == "完成账户创建":
                return mock.Mock(first=fake_text_locator)
            return mock.Mock(first=mock.Mock())

        fake_page.get_by_role.side_effect = _get_by_role
        fake_page.get_by_text.side_effect = _get_by_text
        driver._page = fake_page

        resolved = driver._resolve_target_locator("complete_account_button")

        self.assertIs(resolved.locator, fake_alt_role_locator)
        self.assertEqual(resolved.strategy_kind, "role")
        self.assertEqual(resolved.strategy_value, "完成帐户创建")
        self.assertEqual(resolved.box, {"x": 10, "y": 20, "width": 30, "height": 40})

    def test_driver_uses_playwright_detector_by_default(self):
        driver = PyAutoGUICodexGUIDriver(extra_config={}, logger_fn=lambda _msg: None)

        self.assertIsInstance(driver._target_detector, PlaywrightCodexGUITargetDetector)

    def test_driver_selects_pywinauto_detector_when_configured(self):
        driver = PyAutoGUICodexGUIDriver(
            extra_config={"codex_gui_target_detector": "pywinauto"},
            logger_fn=lambda _msg: None,
        )

        self.assertIsInstance(driver._target_detector, PywinautoCodexGUITargetDetector)

    def test_click_named_target_uses_screen_space_box_for_pywinauto_resolution(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(extra_config={}, logger_fn=logs.append)
        driver._resolve_target_locator = mock.Mock(
            return_value=CodexGUITargetResolution(
                locator=mock.Mock(scroll_into_view_if_needed=mock.Mock()),
                strategy_kind="uia_text",
                strategy_value="继续",
                box={"x": 100.0, "y": 200.0, "width": 80.0, "height": 20.0},
            )
        )
        driver._screen_point_from_dom_point = mock.Mock()
        driver._click_screen_point = mock.Mock()

        with mock.patch("platforms.chatgpt.codex_gui_driver.random.uniform", side_effect=[116.0, 214.0]):
            driver.click_named_target("continue_button")

        driver._screen_point_from_dom_point.assert_not_called()
        driver._click_screen_point.assert_called_once_with("continue_button", 116, 214)

    def test_open_url_uses_address_bar_navigation_in_pywinauto_mode(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(
            extra_config={"codex_gui_target_detector": "pywinauto"},
            logger_fn=logs.append,
        )
        driver._navigate_with_address_bar = mock.Mock()
        driver._browser_session.open_url = mock.Mock()

        driver.open_url("https://auth.openai.com/oauth/authorize?state=demo", reuse_current=False)

        driver._navigate_with_address_bar.assert_called_once_with(
            "https://auth.openai.com/oauth/authorize?state=demo"
        )
        driver._browser_session.open_url.assert_not_called()

    def test_navigate_with_address_bar_focuses_location_and_types_url_fast(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(
            extra_config={"codex_gui_target_detector": "pywinauto"},
            logger_fn=logs.append,
        )
        fake_gui = _FakePyAutoGUI()
        fake_control = mock.Mock()
        detector = mock.Mock(spec=PywinautoCodexGUITargetDetector)
        detector.locate_address_bar.return_value = (
            fake_control,
            {"x": 100.0, "y": 60.0, "width": 200.0, "height": 20.0},
        )
        driver._target_detector = detector
        driver._click_screen_point = mock.Mock()
        driver._gui_controller.navigate_with_address_bar = mock.Mock()

        with mock.patch.object(driver, "_import_pyautogui", return_value=fake_gui), mock.patch(
            "platforms.chatgpt.codex_gui_driver.random.uniform", side_effect=[178.0, 71.0]
        ), mock.patch(
            "platforms.chatgpt.codex_gui_driver.time.sleep"
        ):
            driver._navigate_with_address_bar("https://auth.openai.com/log-in")

        fake_control.set_focus.assert_called_once()
        driver._click_screen_point.assert_called_once_with("browser_address_bar", 178, 71)
        driver._gui_controller.navigate_with_address_bar.assert_called_once_with(
            fake_gui, "https://auth.openai.com/log-in"
        )
        self.assertEqual(fake_gui.write_calls, [])

    def test_navigate_with_address_bar_falls_back_to_clipboard_when_value_is_truncated(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(
            extra_config={"codex_gui_target_detector": "pywinauto"},
            logger_fn=logs.append,
        )
        fake_gui = _FakePyAutoGUI()
        fake_control = mock.Mock()
        fake_control.window_text.return_value = "https://auth.openai.com/oauth/authorize?client_id=app_EMoamEEZ73"
        detector = mock.Mock(spec=PywinautoCodexGUITargetDetector)
        detector.locate_address_bar.return_value = (
            fake_control,
            {"x": 100.0, "y": 60.0, "width": 200.0, "height": 20.0},
        )
        driver._target_detector = detector
        driver._click_screen_point = mock.Mock()
        driver._gui_controller.navigate_with_address_bar = mock.Mock()
        driver._gui_controller.paste_text = mock.Mock()

        with mock.patch.object(driver, "_import_pyautogui", return_value=fake_gui), mock.patch(
            "platforms.chatgpt.codex_gui_driver.time.sleep"
        ):
            driver._navigate_with_address_bar("https://auth.openai.com/oauth/authorize?client_id=app_EMoamEEZ73f0Ck")

        driver._gui_controller.paste_text.assert_called_once_with(
            fake_gui,
            "https://auth.openai.com/oauth/authorize?client_id=app_EMoamEEZ73f0Ck",
            reason="address_bar_fallback",
        )

    def test_read_current_url_uses_address_bar_text_in_pywinauto_mode(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(
            extra_config={"codex_gui_target_detector": "pywinauto"},
            logger_fn=logs.append,
        )
        fake_control = mock.Mock()
        fake_control.window_text.return_value = "https://auth.openai.com/log-in"
        detector = mock.Mock(spec=PywinautoCodexGUITargetDetector)
        detector.locate_address_bar.return_value = (
            fake_control,
            {"x": 100.0, "y": 60.0, "width": 200.0, "height": 20.0},
        )
        driver._target_detector = detector

        current_url = driver.read_current_url()

        self.assertEqual(current_url, "https://auth.openai.com/log-in")

    def test_pywinauto_detector_prefers_configured_keywords_before_builtin(self):
        logs = []
        detector = PywinautoCodexGUITargetDetector(
            extra_config={
                "codex_gui_pywinauto_targets": {
                    "register_button": {"keywords": ["自定义注册"]}
                }
            },
            logger_fn=logs.append,
            browser_session=mock.Mock(),
        )
        detector.iter_visible_controls = mock.Mock(
            return_value=iter(
                [
                    (mock.Mock(), "注册", {"x": 30.0, "y": 40.0, "width": 10.0, "height": 12.0}),
                    (mock.Mock(), "自定义注册", {"x": 10.0, "y": 20.0, "width": 50.0, "height": 18.0}),
                ]
            )
        )

        resolved = detector.resolve_target("register_button")

        self.assertEqual(resolved.strategy_kind, "uia_text")
        self.assertEqual(resolved.strategy_value, "自定义注册")
        self.assertEqual(resolved.box, {"x": 10.0, "y": 20.0, "width": 50.0, "height": 18.0})

    def test_pywinauto_detector_uses_builtin_keyword_when_no_configured_target(self):
        detector = PywinautoCodexGUITargetDetector(
            extra_config={},
            logger_fn=lambda _msg: None,
            browser_session=mock.Mock(),
        )
        detector.iter_visible_controls = mock.Mock(
            return_value=iter(
                [
                    (mock.Mock(), "立即注册", {"x": 1.0, "y": 2.0, "width": 30.0, "height": 12.0}),
                ]
            )
        )

        resolved = detector.resolve_target("register_button")

        self.assertEqual(resolved.strategy_kind, "uia_text")
        self.assertEqual(resolved.strategy_value, "注册")
        self.assertEqual(resolved.box, {"x": 1.0, "y": 2.0, "width": 30.0, "height": 12.0})

    def test_pywinauto_detector_reads_unified_codex_gui_config(self):
        detector = PywinautoCodexGUITargetDetector(
            extra_config={},
            logger_fn=lambda _msg: None,
            browser_session=mock.Mock(),
        )

        markers = detector.page_text_markers_for_stage("注册-创建账户页")
        blank_config = detector.blank_area_click_config_for_target("email_input")
        waits = detector.waits_config()

        self.assertIn("创建帐户", markers)
        self.assertTrue(blank_config.enabled)
        self.assertGreater(blank_config.click_count_min, 0)
        self.assertIn("stage_probe_interval_seconds_min", waits)

    def test_driver_loads_unified_waits_into_controller_config(self):
        driver = PyAutoGUICodexGUIDriver(
            extra_config={"codex_gui_target_detector": "pywinauto"},
            logger_fn=lambda _msg: None,
        )

        self.assertEqual(driver.extra_config.get("codex_gui_pre_click_delay_seconds_min"), 0)
        self.assertEqual(driver._gui_controller.extra_config.get("codex_gui_pre_click_delay_seconds_min"), 0)
        self.assertEqual(driver._gui_controller.extra_config.get("codex_gui_stage_probe_interval_seconds_min"), 0.05)

    def test_input_text_switches_to_english_input_before_typing(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(extra_config={}, logger_fn=logs.append)
        fake_gui = _FakePyAutoGUI()
        driver.click_named_target = mock.Mock()
        driver._focus_and_clear_input = mock.Mock()
        driver._switch_to_english_input = mock.Mock()
        driver._verify_pywinauto_input = mock.Mock()

        with mock.patch.object(driver, "_import_pyautogui", return_value=fake_gui), mock.patch(
            "platforms.chatgpt.gui_controller.random.uniform",
            return_value=0.05,
        ), mock.patch("platforms.chatgpt.gui_controller.time.sleep"), mock.patch.object(
            driver._gui_controller, "paste_text"
        ) as paste_mock:
            driver.input_text("email_input", "user@example.com")

        driver.click_named_target.assert_called_once_with("email_input")
        driver._switch_to_english_input.assert_called_once()
        driver._focus_and_clear_input.assert_called_once_with("email_input")
        paste_mock.assert_called_once_with(fake_gui, "user@example.com", reason="field_input")
        self.assertTrue(any("delay=50.0ms" in entry for entry in logs))
        self.assertTrue(any("[节奏] 操作后随机停顿: reason=type_text" in entry for entry in logs))
        driver._verify_pywinauto_input.assert_not_called()

    def test_input_text_verifies_pywinauto_input_when_detector_enabled(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(
            extra_config={"codex_gui_target_detector": "pywinauto"},
            logger_fn=logs.append,
        )
        fake_gui = _FakePyAutoGUI()
        driver.click_named_target = mock.Mock()
        driver._focus_and_clear_input = mock.Mock()
        driver._switch_to_english_input = mock.Mock()
        driver._verify_pywinauto_input = mock.Mock()

        with mock.patch.object(driver, "_import_pyautogui", return_value=fake_gui), mock.patch(
            "platforms.chatgpt.gui_controller.random.uniform",
            return_value=0.05,
        ), mock.patch("platforms.chatgpt.gui_controller.time.sleep"):
            driver.input_text("email_input", "user@example.com")

        driver._verify_pywinauto_input.assert_called_once_with("email_input", "user@example.com")

    def test_verify_pywinauto_input_prefers_focused_edit_value(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(
            extra_config={"codex_gui_target_detector": "pywinauto"},
            logger_fn=logs.append,
        )
        detector = mock.Mock(spec=PywinautoCodexGUITargetDetector)
        detector.focused_edit_candidate.return_value = mock.Mock(
            text="user@example.com",
            box={"x": 100.0, "y": 100.0, "width": 120.0, "height": 24.0},
        )
        detector.boxes_intersect.return_value = True
        detector.text_candidates_in_region.return_value = []
        driver._target_detector = detector
        driver.peek_target = mock.Mock(return_value=("uia_text", "邮箱", {"x": 110.0, "y": 105.0, "width": 100.0, "height": 20.0}))

        driver._verify_pywinauto_input("email_input", "user@example.com")

        detector.text_candidates_in_region.assert_not_called()

    def test_verify_pywinauto_input_falls_back_to_region_text_candidates(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(
            extra_config={"codex_gui_target_detector": "pywinauto"},
            logger_fn=logs.append,
        )
        detector = mock.Mock(spec=PywinautoCodexGUITargetDetector)
        detector.focused_edit_candidate.return_value = mock.Mock(
            text="",
            box={"x": 100.0, "y": 100.0, "width": 120.0, "height": 24.0},
        )
        detector.boxes_intersect.return_value = True
        detector.text_candidates_in_region.return_value = [
            mock.Mock(text="user@example.com", box={"x": 102.0, "y": 103.0, "width": 130.0, "height": 20.0})
        ]
        driver._target_detector = detector
        driver.peek_target = mock.Mock(return_value=("uia_text", "邮箱", {"x": 110.0, "y": 105.0, "width": 100.0, "height": 20.0}))

        driver._verify_pywinauto_input("email_input", "user@example.com")

        detector.text_candidates_in_region.assert_called_once()

    def test_verify_pywinauto_password_accepts_masked_focused_value(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(
            extra_config={"codex_gui_target_detector": "pywinauto"},
            logger_fn=logs.append,
        )
        detector = mock.Mock(spec=PywinautoCodexGUITargetDetector)
        detector.focused_edit_candidate.return_value = mock.Mock(
            text="••••••••",
            box={"x": 100.0, "y": 100.0, "width": 120.0, "height": 24.0},
        )
        detector.boxes_intersect.return_value = True
        detector.text_candidates_in_region.return_value = []
        driver._target_detector = detector
        driver.peek_target = mock.Mock(return_value=("uia_text", "密码", {"x": 110.0, "y": 105.0, "width": 100.0, "height": 20.0}))

        driver._verify_pywinauto_input("password_input", "super-secret-password")

        detector.text_candidates_in_region.assert_not_called()

    def test_verify_pywinauto_password_accepts_masked_region_text(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(
            extra_config={"codex_gui_target_detector": "pywinauto"},
            logger_fn=logs.append,
        )
        detector = mock.Mock(spec=PywinautoCodexGUITargetDetector)
        detector.focused_edit_candidate.return_value = mock.Mock(
            text="",
            box={"x": 100.0, "y": 100.0, "width": 120.0, "height": 24.0},
        )
        detector.boxes_intersect.return_value = True
        detector.text_candidates_in_region.return_value = [
            mock.Mock(text="••••••••", box={"x": 102.0, "y": 103.0, "width": 130.0, "height": 20.0})
        ]
        driver._target_detector = detector
        driver.peek_target = mock.Mock(return_value=("uia_text", "密码", {"x": 110.0, "y": 105.0, "width": 100.0, "height": 20.0}))

        driver._verify_pywinauto_input("password_input", "super-secret-password")

        detector.text_candidates_in_region.assert_called_once()

    def test_verify_pywinauto_input_raises_when_no_match_found(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(
            extra_config={
                "codex_gui_target_detector": "pywinauto",
                "codex_gui_pywinauto_input_verify_timeout_seconds": 0.1,
            },
            logger_fn=logs.append,
        )
        detector = mock.Mock(spec=PywinautoCodexGUITargetDetector)
        detector.focused_edit_candidate.return_value = None
        detector.text_candidates_in_region.return_value = []
        driver._target_detector = detector
        driver.peek_target = mock.Mock(return_value=("uia_text", "邮箱", {"x": 110.0, "y": 105.0, "width": 100.0, "height": 20.0}))

        with self.assertRaisesRegex(RuntimeError, "输入确认失败"), mock.patch(
            "platforms.chatgpt.codex_gui_driver.time.sleep"
        ):
            driver._verify_pywinauto_input("email_input", "user@example.com")

    def test_input_text_retries_when_pywinauto_verification_fails(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(
            extra_config={
                "codex_gui_target_detector": "pywinauto",
                "codex_gui_pywinauto_input_retry_count": 2,
            },
            logger_fn=logs.append,
        )
        fake_gui = _FakePyAutoGUI()
        driver.click_named_target = mock.Mock()
        driver._focus_and_clear_input = mock.Mock()
        driver._switch_to_english_input = mock.Mock()
        driver._verify_pywinauto_input = mock.Mock(side_effect=[RuntimeError("first fail"), None])

        with mock.patch.object(driver, "_import_pyautogui", return_value=fake_gui), mock.patch(
            "platforms.chatgpt.gui_controller.random.uniform",
            return_value=0.05,
        ), mock.patch("platforms.chatgpt.gui_controller.time.sleep"):
            driver.input_text("email_input", "user@example.com")

        self.assertEqual(driver.click_named_target.call_count, 2)
        self.assertEqual(driver._verify_pywinauto_input.call_count, 2)

    def test_gui_controller_fast_navigation_types_full_url_without_per_char_delay(self):
        logs = []
        fake_gui = _FakePyAutoGUI()
        controller = PyAutoGUICodexGUIController(
            extra_config={},
            logger_fn=logs.append,
            pyautogui_getter=lambda: fake_gui,
        )

        controller.navigate_with_address_bar(fake_gui, "https://auth.openai.com/log-in")

        self.assertEqual(fake_gui.write_calls, [("https://auth.openai.com/log-in", 0)])

    def test_gui_controller_type_text_humanized_uses_clipboard_paste(self):
        logs = []
        fake_gui = _FakePyAutoGUI()
        controller = PyAutoGUICodexGUIController(
            extra_config={},
            logger_fn=logs.append,
            pyautogui_getter=lambda: fake_gui,
        )

        with mock.patch.object(controller, "paste_text") as paste_mock, mock.patch(
            "platforms.chatgpt.gui_controller.random.uniform", return_value=0.05
        ), mock.patch("platforms.chatgpt.gui_controller.time.sleep"):
            controller.type_text_humanized(fake_gui, "user@example.com")

        paste_mock.assert_called_once_with(fake_gui, "user@example.com", reason="field_input")

    def test_gui_controller_paste_text_uses_clipboard_and_ctrl_v(self):
        logs = []
        fake_gui = _FakePyAutoGUI()
        controller = PyAutoGUICodexGUIController(
            extra_config={},
            logger_fn=logs.append,
            pyautogui_getter=lambda: fake_gui,
        )

        with mock.patch("platforms.chatgpt.gui_controller.subprocess.run") as run_mock:
            run_mock.return_value = mock.Mock(returncode=0, stderr="", stdout="")
            controller.paste_text(fake_gui, "https://auth.openai.com/log-in", reason="test")

        run_mock.assert_called_once()

    def test_gui_controller_random_post_action_pause_uses_new_bounds(self):
        logs = []
        controller = PyAutoGUICodexGUIController(
            extra_config={},
            logger_fn=logs.append,
            pyautogui_getter=lambda: _FakePyAutoGUI(),
        )

        with mock.patch("platforms.chatgpt.gui_controller.random.uniform", return_value=0.8), mock.patch(
            "platforms.chatgpt.gui_controller.time.sleep"
        ) as sleep_mock:
            controller.random_post_action_pause("click:test")

        sleep_mock.assert_called_once_with(0.8)
        self.assertTrue(any("delay=800.0ms" in entry for entry in logs))

    def test_wander_while_waiting_uses_visible_windmouse_motion(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(extra_config={}, logger_fn=logs.append)
        fake_gui = _FakePyAutoGUI()
        driver._random_page_hover_point = mock.Mock(return_value=(400, 500))
        driver._human_move_to = mock.Mock()

        with mock.patch.object(driver, "_import_pyautogui", return_value=fake_gui), mock.patch(
            "platforms.chatgpt.codex_gui_driver.random.uniform",
            return_value=0.6,
        ):
            driver.wander_while_waiting("注册-创建账户页")

        driver._human_move_to.assert_called_once_with(fake_gui, 400, 500, 0.6)
        self.assertTrue(any("等待中随机 WindMouse 漫游" in entry for entry in logs))

    def test_waiting_stage_wanders_mouse_until_condition_met(self):
        logs = []
        engine = CodexGUIRegistrationEngine(
            email_service=_DummyEmailService(["111111"]),
            callback_logger=logs.append,
            extra_config={"chatgpt_registration_mode": "codex_gui"},
        )
        driver = _FakeDriver()
        driver.current_url = "https://auth.openai.com/log-in"
        engine._driver = driver

        calls = {"count": 0}

        def _wander(stage):
            logs.append(f"wander:{stage}")
            calls["count"] += 1
            if calls["count"] == 1:
                driver.current_url = "https://auth.openai.com/create-account"

        driver.wander_while_waiting = _wander

        with mock.patch("platforms.chatgpt.codex_gui_registration_engine.time.sleep"):
            current = engine._wait_for_any_url(["/create-account"], timeout=1, stage="注册-创建账户页")

        self.assertEqual(current, "https://auth.openai.com/create-account")
        self.assertGreaterEqual(calls["count"], 1)
        self.assertTrue(any("wander:注册-创建账户页" in entry for entry in logs))

    def test_stage_dom_match_prefers_page_text_marker_when_available(self):
        logs = []
        engine = CodexGUIRegistrationEngine(
            email_service=_DummyEmailService(["111111"]),
            callback_logger=logs.append,
            extra_config={"chatgpt_registration_mode": "codex_gui"},
        )
        driver = mock.Mock(spec=CodexGUIDriver)
        driver.page_marker_matched = mock.Mock(return_value=(True, "电子邮件地址"))
        engine._driver = driver

        matched, marker = engine._stage_dom_matched("注册-创建账户页")

        self.assertTrue(matched)
        self.assertEqual(marker, "电子邮件地址")
        driver.peek_target.assert_not_called()

    def test_wait_for_stage_marker_succeeds_only_when_all_markers_present(self):
        logs = []
        engine = CodexGUIRegistrationEngine(
            email_service=_DummyEmailService(["111111"]),
            callback_logger=logs.append,
            extra_config={"chatgpt_registration_mode": "codex_gui", "codex_gui_stage_probe_interval_seconds": 0.8},
        )
        driver = _FakeDriverWithStrictMarkers()
        engine._driver = driver
        calls = {"count": 0}

        def _page_marker_matched(stage: str):
            calls["count"] += 1
            if calls["count"] == 1:
                return False, "继续"
            return True, "创建帐户"

        driver.page_marker_matched = _page_marker_matched

        with mock.patch("platforms.chatgpt.codex_gui_registration_engine.time.sleep"):
            engine._wait_for_stage_marker("注册-创建账户页", timeout=1)

        self.assertGreaterEqual(calls["count"], 2)

    def test_wait_for_url_uses_stage_markers_only_in_pywinauto_mode(self):
        logs = []
        engine = CodexGUIRegistrationEngine(
            email_service=_DummyEmailService(["111111"]),
            callback_logger=logs.append,
            extra_config={
                "chatgpt_registration_mode": "codex_gui",
                "codex_gui_target_detector": "pywinauto",
            },
        )
        driver = _FakeDriverWithStrictMarkers()
        driver.stage_markers["注册-创建账户页"] = (True, "创建帐户")
        engine._driver = driver
        engine._wait_for_stage_marker = mock.Mock()
        driver.read_current_url = mock.Mock(side_effect=RuntimeError("should not read address bar"))

        current = engine._wait_for_url("/create-account", timeout=1, stage="注册-创建账户页")

        engine._wait_for_stage_marker.assert_called_once_with("注册-创建账户页", timeout=1)
        self.assertEqual(current, "/create-account")
        driver.read_current_url.assert_not_called()

    def test_click_named_target_uses_inner80_random_point_for_uia(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(extra_config={}, logger_fn=logs.append)
        driver._resolve_target_locator = mock.Mock(
            return_value=CodexGUITargetResolution(
                locator=mock.Mock(scroll_into_view_if_needed=mock.Mock()),
                strategy_kind="uia_text",
                strategy_value="继续",
                box={"x": 100.0, "y": 200.0, "width": 80.0, "height": 20.0},
            )
        )
        driver._click_screen_point = mock.Mock()

        with mock.patch("platforms.chatgpt.codex_gui_driver.random.uniform", side_effect=[116.0, 214.0]):
            driver.click_named_target("continue_button")

        driver._click_screen_point.assert_called_once_with("continue_button", 116, 214)

    def test_resolve_target_locator_preclicks_blank_area_for_input_targets_in_pywinauto_mode(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(
            extra_config={"codex_gui_target_detector": "pywinauto"},
            logger_fn=logs.append,
        )
        blank_config = mock.Mock(
            enabled=True,
            box={"x": 1400.0, "y": 220.0, "width": 260.0, "height": 180.0},
            click_count_min=2,
            click_count_max=2,
            interval_seconds_min=0.2,
            interval_seconds_max=0.2,
        )
        detector = mock.Mock(spec=PywinautoCodexGUITargetDetector)
        detector.blank_area_click_config_for_target.return_value = blank_config
        detector.resolve_target.return_value = CodexGUITargetResolution(
            locator=mock.Mock(),
            strategy_kind="uia_text",
            strategy_value="电子邮件地址",
            box={"x": 100.0, "y": 200.0, "width": 80.0, "height": 20.0},
        )
        driver._target_detector = detector
        driver._click_screen_point = mock.Mock()

        with mock.patch.object(driver, "_import_pyautogui", return_value=_FakePyAutoGUI()), mock.patch(
            "platforms.chatgpt.codex_gui_driver.random.randint", return_value=2
        ), mock.patch(
            "platforms.chatgpt.codex_gui_driver.random.uniform", side_effect=[1430.0, 250.0, 0.2, 1450.0, 270.0]
        ), mock.patch("platforms.chatgpt.codex_gui_driver.time.sleep"):
            resolved = driver._resolve_target_locator("email_input")

        self.assertEqual(resolved.strategy_value, "电子邮件地址")
        self.assertEqual(driver._click_screen_point.call_count, 2)
        driver._click_screen_point.assert_any_call("blank_area:email_input:1", 1430, 250)
        driver._click_screen_point.assert_any_call("blank_area:email_input:2", 1450, 270)

    def test_resolve_target_locator_skips_blank_area_preclick_for_non_input_targets(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(
            extra_config={"codex_gui_target_detector": "pywinauto"},
            logger_fn=logs.append,
        )
        detector = mock.Mock(spec=PywinautoCodexGUITargetDetector)
        detector.resolve_target.return_value = CodexGUITargetResolution(
            locator=mock.Mock(),
            strategy_kind="uia_text",
            strategy_value="注册",
            box={"x": 100.0, "y": 200.0, "width": 80.0, "height": 20.0},
        )
        driver._target_detector = detector
        driver._click_screen_point = mock.Mock()

        resolved = driver._resolve_target_locator("register_button")

        self.assertEqual(resolved.strategy_value, "注册")
        detector.blank_area_click_config_for_target.assert_not_called()
        driver._click_screen_point.assert_not_called()

    def test_navigate_with_address_bar_uses_inner80_random_point(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(
            extra_config={"codex_gui_target_detector": "pywinauto"},
            logger_fn=logs.append,
        )
        fake_gui = _FakePyAutoGUI()
        fake_control = mock.Mock()
        detector = mock.Mock(spec=PywinautoCodexGUITargetDetector)
        detector.locate_address_bar.return_value = (
            fake_control,
            {"x": 100.0, "y": 60.0, "width": 200.0, "height": 20.0},
        )
        driver._target_detector = detector
        driver._click_screen_point = mock.Mock()
        driver._gui_controller.navigate_with_address_bar = mock.Mock()

        with mock.patch.object(driver, "_import_pyautogui", return_value=fake_gui), mock.patch(
            "platforms.chatgpt.codex_gui_driver.random.uniform", side_effect=[130.0, 74.0]
        ), mock.patch("platforms.chatgpt.codex_gui_driver.time.sleep"):
            driver._navigate_with_address_bar("https://auth.openai.com/log-in")

        driver._click_screen_point.assert_called_once_with("browser_address_bar", 130, 74)

    def test_pywinauto_target_detector_reuses_cached_address_bar_control(self):
        logs = []
        detector = PywinautoCodexGUITargetDetector(extra_config={}, logger_fn=logs.append, browser_session=mock.Mock())

        class _FakeRect:
            left = 100
            top = 60

            @staticmethod
            def width():
                return 200

            @staticmethod
            def height():
                return 20

        fake_control = mock.Mock()
        fake_control.rectangle.return_value = _FakeRect()
        fake_window = mock.Mock()
        fake_window.child_window.return_value.wrapper_object.return_value = fake_control

        with mock.patch.object(detector, "_find_edge_window", side_effect=[fake_window, AssertionError("should not resolve window again")]):
            first_control, first_box = detector.locate_address_bar()
            second_control, second_box = detector.locate_address_bar()

        self.assertIs(first_control, fake_control)
        self.assertIs(second_control, fake_control)
        self.assertEqual(first_box, second_box)
        self.assertTrue(any("地址栏定位(cache)完成" in entry for entry in logs))

    def test_pywinauto_target_detector_prefers_focused_edit_before_descendants_fallback(self):
        logs = []
        detector = PywinautoCodexGUITargetDetector(extra_config={}, logger_fn=logs.append, browser_session=mock.Mock())

        class _FakeRect:
            left = 120
            top = 70

            @staticmethod
            def width():
                return 240

            @staticmethod
            def height():
                return 24

        focused_control = mock.Mock()
        focused_control.rectangle.return_value = _FakeRect()
        focused_control.window_text.return_value = "https://auth.openai.com/log-in"

        fake_window = mock.Mock()
        fake_window.child_window.return_value.wrapper_object.side_effect = RuntimeError("primary miss")
        fake_window.get_focus.return_value = focused_control
        fake_window.descendants.side_effect = AssertionError("should not use descendants fallback")

        with mock.patch.object(detector, "_find_edge_window", return_value=fake_window):
            resolved_control, resolved_box = detector.locate_address_bar()

        self.assertIs(resolved_control, focused_control)
        self.assertEqual(resolved_box["x"], 120.0)
        self.assertEqual(resolved_box["width"], 240.0)
        self.assertTrue(any("地址栏定位(focused)完成" in entry for entry in logs))

    def test_wait_for_terminal_outcome_returns_add_phone(self):
        logs = []
        engine = CodexGUIRegistrationEngine(
            email_service=_DummyEmailService(["111111"]),
            callback_logger=logs.append,
            extra_config={"chatgpt_registration_mode": "codex_gui", "codex_gui_stage_probe_interval_seconds": 0.8},
        )
        driver = _FakeDriverWithStrictMarkers()
        driver.stage_markers["注册-终态判断-add/phone"] = (True, "电话号码是必填项")
        engine._driver = driver

        with mock.patch("platforms.chatgpt.codex_gui_registration_engine.time.sleep"):
            terminal = engine._wait_for_terminal_outcome(prefix="注册", timeout=1)

        self.assertEqual(terminal, "add-phone")

    def test_wait_for_stage_marker_in_pywinauto_mode_retries_text_only_before_15s(self):
        logs = []
        engine = CodexGUIRegistrationEngine(
            email_service=_DummyEmailService(["111111"]),
            callback_logger=logs.append,
            extra_config={
                "chatgpt_registration_mode": "codex_gui",
                "codex_gui_target_detector": "pywinauto",
                "codex_gui_stage_probe_interval_seconds": 0.1,
            },
        )
        driver = _FakeDriverWithStrictMarkers()
        driver.read_current_url = mock.Mock(side_effect=RuntimeError("should not read url before 15s window expires"))
        engine._driver = driver

        marker_results = iter([
            (False, None),
            (False, None),
            (True, "创建帐户"),
        ])
        driver.page_marker_matched = mock.Mock(side_effect=lambda _stage: next(marker_results))

        perf_values = iter([0.0, 1.0, 2.0, 3.0])
        time_values = iter([100.0, 100.1, 100.2, 100.3])
        with mock.patch("platforms.chatgpt.codex_gui_registration_engine.time.perf_counter", side_effect=lambda: next(perf_values)), mock.patch(
            "platforms.chatgpt.codex_gui_registration_engine.time.time", side_effect=lambda: next(time_values)
        ), mock.patch("platforms.chatgpt.codex_gui_registration_engine.time.sleep"):
            engine._wait_for_stage_marker("注册-创建账户页", timeout=30)

        driver.read_current_url.assert_not_called()
        self.assertEqual(driver.page_marker_matched.call_count, 3)

    def test_wait_for_stage_marker_in_pywinauto_mode_reads_url_after_15s_window(self):
        logs = []
        engine = CodexGUIRegistrationEngine(
            email_service=_DummyEmailService(["111111"]),
            callback_logger=logs.append,
            extra_config={
                "chatgpt_registration_mode": "codex_gui",
                "codex_gui_target_detector": "pywinauto",
                "codex_gui_stage_probe_interval_seconds": 0.1,
            },
        )
        driver = _FakeDriverWithStrictMarkers()
        driver.read_current_url = mock.Mock(return_value="https://auth.openai.com/error")
        engine._driver = driver
        driver.page_marker_matched = mock.Mock(return_value=(False, None))
        engine._handle_retry_page = mock.Mock(side_effect=RuntimeError("retry handled"))

        perf_values = iter([0.0, 5.0, 10.0, 15.1])
        time_values = iter([200.0, 200.1, 200.2, 200.3])
        with mock.patch("platforms.chatgpt.codex_gui_registration_engine.time.perf_counter", side_effect=lambda: next(perf_values)), mock.patch(
            "platforms.chatgpt.codex_gui_registration_engine.time.time", side_effect=lambda: next(time_values)
        ), mock.patch("platforms.chatgpt.codex_gui_registration_engine.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "retry handled"):
                engine._wait_for_stage_marker("注册-密码页", timeout=30)

        driver.read_current_url.assert_called_once()
        engine._handle_retry_page.assert_called_once_with("注册-密码页")

    def test_wait_for_terminal_outcome_in_pywinauto_mode_delays_url_fallback_until_15s(self):
        logs = []
        engine = CodexGUIRegistrationEngine(
            email_service=_DummyEmailService(["111111"]),
            callback_logger=logs.append,
            extra_config={
                "chatgpt_registration_mode": "codex_gui",
                "codex_gui_target_detector": "pywinauto",
                "codex_gui_stage_probe_interval_seconds": 0.1,
            },
        )
        driver = _FakeDriverWithStrictMarkers()
        driver.read_current_url = mock.Mock(return_value="https://auth.openai.com/error")
        engine._driver = driver
        driver.page_marker_matched = mock.Mock(return_value=(False, None))
        engine._handle_retry_page = mock.Mock(side_effect=RuntimeError("terminal retry handled"))

        perf_values = iter([0.0, 4.0, 8.0, 12.0, 15.2])
        time_values = iter([300.0, 300.1, 300.2, 300.3, 300.4])
        with mock.patch("platforms.chatgpt.codex_gui_registration_engine.time.perf_counter", side_effect=lambda: next(perf_values)), mock.patch(
            "platforms.chatgpt.codex_gui_registration_engine.time.time", side_effect=lambda: next(time_values)
        ), mock.patch("platforms.chatgpt.codex_gui_registration_engine.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "terminal retry handled"):
                engine._wait_for_terminal_outcome(prefix="注册", timeout=30)

        driver.read_current_url.assert_called_once()
        engine._handle_retry_page.assert_called_once_with("注册-终态判断")

    def test_stage_probe_interval_uses_random_range_when_not_configured(self):
        engine = CodexGUIRegistrationEngine(
            email_service=_DummyEmailService(["111111"]),
            extra_config={"chatgpt_registration_mode": "codex_gui"},
        )

        with mock.patch("platforms.chatgpt.codex_gui_registration_engine.random.uniform", return_value=1.1):
            self.assertEqual(engine._stage_probe_interval_seconds(), 1.1)

    def test_stage_dom_match_uses_short_probe_timeout_when_supported(self):
        logs = []
        engine = CodexGUIRegistrationEngine(
            email_service=_DummyEmailService(["111111"]),
            callback_logger=logs.append,
            extra_config={
                "chatgpt_registration_mode": "codex_gui",
                "codex_gui_stage_dom_probe_timeout_ms": 750,
            },
        )
        driver = mock.Mock(spec=CodexGUIDriver)
        driver.peek_target_with_timeout = mock.Mock(return_value=("text", "邮箱", {"x": 1.0, "y": 2.0, "width": 3.0, "height": 4.0}))
        engine._driver = driver

        matched, target = engine._stage_dom_matched("注册-创建账户页")

        self.assertTrue(matched)
        self.assertEqual(target, "email_input")
        driver.peek_target_with_timeout.assert_called_once_with("email_input", 750)
        driver.peek_target.assert_not_called()

    def test_wait_timeout_defaults_to_60_for_codex_gui_flows(self):
        engine = CodexGUIRegistrationEngine(
            email_service=_DummyEmailService(["111111"]),
            extra_config={"chatgpt_registration_mode": "codex_gui"},
        )

        self.assertEqual(engine._wait_timeout("codex_gui_wait_timeout_seconds", 60), 60)

    def test_stage_probe_interval_defaults_to_random_range(self):
        engine = CodexGUIRegistrationEngine(
            email_service=_DummyEmailService(["111111"]),
            extra_config={"chatgpt_registration_mode": "codex_gui"},
        )

        with mock.patch("platforms.chatgpt.codex_gui_registration_engine.random.uniform", return_value=1.1):
            self.assertEqual(engine._stage_probe_interval_seconds(), 1.1)

    def test_stage_probe_interval_uses_configured_range(self):
        engine = CodexGUIRegistrationEngine(
            email_service=_DummyEmailService(["111111"]),
            extra_config={
                "chatgpt_registration_mode": "codex_gui",
                "codex_gui_stage_probe_interval_seconds_min": 0.9,
                "codex_gui_stage_probe_interval_seconds_max": 1.2,
            },
        )

        with mock.patch("platforms.chatgpt.codex_gui_registration_engine.random.uniform", return_value=1.05):
            self.assertEqual(engine._stage_probe_interval_seconds(), 1.05)

    def test_stage_dom_probe_timeout_defaults_to_one_second(self):
        engine = CodexGUIRegistrationEngine(
            email_service=_DummyEmailService(["111111"]),
            extra_config={"chatgpt_registration_mode": "codex_gui"},
        )

        self.assertEqual(engine._stage_dom_probe_timeout_ms(), 1000)

    def test_target_detector_prefers_configured_target_before_builtin(self):
        logs = []
        browser_session = mock.Mock()
        fake_page = mock.Mock()
        browser_session.require_page.return_value = fake_page
        detector = PlaywrightCodexGUITargetDetector(
            extra_config={
                "codex_gui_targets": {
                    "register_button": {"kind": "text", "value": "自定义注册"}
                }
            },
            logger_fn=logs.append,
            browser_session=browser_session,
        )
        configured_locator = mock.Mock()
        configured_locator.bounding_box.return_value = {"x": 5, "y": 6, "width": 7, "height": 8}
        fake_page.content.return_value = "<html></html>"

        def _get_by_text(text, exact=False):
            if text == "自定义注册":
                return mock.Mock(first=configured_locator)
            self.fail(f"builtin target should not be tried before configured one: {text}")

        fake_page.get_by_text.side_effect = _get_by_text

        resolved = detector.resolve_target("register_button")

        self.assertIs(resolved.locator, configured_locator)
        self.assertEqual(resolved.strategy_kind, "text")
        self.assertEqual(resolved.strategy_value, "自定义注册")
        self.assertEqual(resolved.box, {"x": 5, "y": 6, "width": 7, "height": 8})

    def test_geometry_helper_converts_dom_point_without_pyautogui_execution(self):
        logs = []
        browser_session = mock.Mock()
        browser_session.browser_metrics.return_value = {
            "screenX": 10,
            "screenY": 20,
            "outerWidth": 1200,
            "outerHeight": 900,
            "innerWidth": 1180,
            "innerHeight": 820,
            "screenWidth": 1920,
            "screenHeight": 1080,
            "visualOffsetLeft": 0,
            "visualOffsetTop": 0,
        }
        fake_gui = mock.Mock()
        fake_gui.size.return_value = (1920, 1080)
        helper = CodexGUIGeometryHelper(
            logger_fn=logs.append,
            browser_session=browser_session,
            pyautogui_getter=lambda: fake_gui,
        )

        point = helper.screen_point_from_box("register_button", {"x": 100, "y": 200, "width": 80, "height": 20})

        self.assertEqual(point, (160, 300))
        fake_gui.moveTo.assert_not_called()

    def test_gui_controller_clicks_screen_coordinates_only(self):
        logs = []
        fake_gui = _FakePyAutoGUI()
        controller = PyAutoGUICodexGUIController(
            extra_config={"codex_gui_windmouse_max_steps": 12},
            logger_fn=logs.append,
            pyautogui_getter=lambda: fake_gui,
        )

        with mock.patch("platforms.chatgpt.gui_controller.time.sleep"), mock.patch(
            "platforms.chatgpt.gui_controller.random.uniform",
            return_value=0.0,
        ):
            controller.click_screen_point("register_button", 100, 200)

        self.assertEqual(fake_gui.clicks[-1], (100, 200))
        self.assertTrue(any("[GUI] 点击目标: name=register_button, point=(100, 200)" in entry for entry in logs))


if __name__ == "__main__":
    unittest.main()
