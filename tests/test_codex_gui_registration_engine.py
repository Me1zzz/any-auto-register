import unittest
from unittest import mock
import sys
import types

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


class CodexGUIRegistrationEngineTests(unittest.TestCase):
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
        driver = _FakeDriverWithRegisterConsent()
        engine = self._make_engine(email_service, driver)

        result = engine.run()

        self.assertTrue(result.success)
        self.assertIn(("click", "complete_account_button"), driver.events)
        self.assertIn(("click", "continue_button"), driver.events)
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
        driver._ensure_browser_session = mock.Mock(return_value=fake_page)

        with mock.patch("platforms.chatgpt.codex_gui_registration_engine.time.sleep"):
            driver.open_url("https://auth.openai.com/oauth/authorize?state=demo", reuse_current=False)

        driver._ensure_browser_session.assert_called_once()
        fake_page.goto.assert_called_once_with(
            "https://auth.openai.com/oauth/authorize?state=demo",
            wait_until="domcontentloaded",
            timeout=15000,
        )
        fake_page.bring_to_front.assert_called_once()
        self.assertGreaterEqual(fake_page.evaluate.call_count, 1)
        self.assertTrue(any("[浏览器] 开始打开链接" in entry for entry in logs))
        self.assertTrue(any("[浏览器] 尝试将 Edge 窗口前置到最上层" in entry for entry in logs))

    def test_ensure_browser_session_defaults_to_cdp_attach_mode(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(extra_config={}, logger_fn=logs.append)
        driver._import_playwright = mock.Mock(return_value=mock.Mock(return_value=mock.Mock(start=mock.Mock(return_value=mock.Mock()))))
        driver._ensure_edge_cdp_session = mock.Mock(return_value="page")

        page = driver._ensure_browser_session()

        self.assertEqual(page, "page")
        driver._ensure_edge_cdp_session.assert_called_once()
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

        with mock.patch("platforms.chatgpt.codex_gui_registration_engine.urllib.request.urlopen", return_value=fake_context):
            base_url = driver._wait_for_cdp_endpoint()

        self.assertEqual(base_url, "http://127.0.0.1:9222")

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

        with mock.patch("platforms.chatgpt.codex_gui_registration_engine.random.uniform", side_effect=[26.0, 42.0]):
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
            "platforms.chatgpt.codex_gui_registration_engine.time.sleep"
        ), mock.patch(
            "platforms.chatgpt.codex_gui_registration_engine.random.uniform",
            return_value=0.0,
        ):
            driver._click_screen_point("register_button", 100, 200)

        self.assertGreaterEqual(len(fake_gui.moves), 1)
        self.assertEqual(fake_gui.clicks[-1], (100, 200))
        self.assertTrue(any("[GUI] WindMouse 移动" in entry for entry in logs))
        self.assertTrue(any("[GUI] WindMouse 轨迹点" in entry for entry in logs))
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

        locator, strategy_kind, strategy_value, box = driver._resolve_target_locator("register_button")

        self.assertIs(locator, fake_locator)
        self.assertEqual(strategy_kind, "text")
        self.assertEqual(strategy_value, "注册")
        self.assertEqual(box, {"x": 1, "y": 2, "width": 3, "height": 4})
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

        locator, strategy_kind, strategy_value, box = driver._resolve_target_locator("complete_account_button")

        self.assertIs(locator, fake_alt_role_locator)
        self.assertEqual(strategy_kind, "role")
        self.assertEqual(strategy_value, "完成帐户创建")
        self.assertEqual(box, {"x": 10, "y": 20, "width": 30, "height": 40})

    def test_input_text_switches_to_english_input_before_typing(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(extra_config={}, logger_fn=logs.append)
        fake_gui = _FakePyAutoGUI()
        driver.click_named_target = mock.Mock()
        driver._focus_and_clear_input = mock.Mock()
        driver._switch_to_english_input = mock.Mock()

        with mock.patch.object(driver, "_import_pyautogui", return_value=fake_gui), mock.patch(
            "platforms.chatgpt.codex_gui_registration_engine.random.uniform",
            return_value=0.02,
        ), mock.patch("platforms.chatgpt.codex_gui_registration_engine.time.sleep"):
            driver.input_text("email_input", "user@example.com")

        driver.click_named_target.assert_called_once_with("email_input")
        driver._switch_to_english_input.assert_called_once()
        driver._focus_and_clear_input.assert_called_once_with("email_input")
        self.assertEqual(len(fake_gui.write_calls), len("user@example.com"))
        self.assertTrue(all(interval == 0 for _text, interval in fake_gui.write_calls))
        self.assertEqual("".join(text for text, _interval in fake_gui.write_calls), "user@example.com")
        self.assertTrue(any("delay=20.0ms" in entry for entry in logs))
        self.assertTrue(any("[节奏] 操作后随机停顿: reason=type_text" in entry for entry in logs))

    def test_wander_while_waiting_uses_visible_windmouse_motion(self):
        logs = []
        driver = PyAutoGUICodexGUIDriver(extra_config={}, logger_fn=logs.append)
        fake_gui = _FakePyAutoGUI()
        driver._random_page_hover_point = mock.Mock(return_value=(400, 500))
        driver._human_move_to = mock.Mock()

        with mock.patch.object(driver, "_import_pyautogui", return_value=fake_gui), mock.patch(
            "platforms.chatgpt.codex_gui_registration_engine.random.uniform",
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


if __name__ == "__main__":
    unittest.main()
