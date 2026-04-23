import unittest
from unittest import mock

from core.alias_pool.browser_runtime import BrowserRuntimeSessionState, BrowserRuntimeStep
from core.alias_pool.browser_fallback_runtime import BrowserFallbackRuntime
from core.alias_pool.protocol_site_runtime import ProtocolRuntimeResponse, ProtocolSiteRuntime


class _FakeHttpResponse:
    def __init__(self, *, status_code=200, text="", headers=None, url="https://example.test/form"):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self.url = url


class _FakeHTTPClient:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return _FakeHttpResponse(
            text='<form><input type="hidden" name="csrfmiddlewaretoken" value="csrf-1"></form>',
            url=url,
        )

    def post(self, url, data=None, json=None, **kwargs):
        self.calls.append(("POST", url, {"data": data, "json": json, **kwargs}))
        return _FakeHttpResponse(text="ok", url=url)


class ProtocolSiteRuntimeTests(unittest.TestCase):
    def test_extract_hidden_inputs_returns_requested_fields(self):
        runtime = ProtocolSiteRuntime(client=_FakeHTTPClient())

        result = runtime.get("https://example.test/form")
        hidden = runtime.extract_hidden_inputs(result.text, names=("csrfmiddlewaretoken", "token"))

        self.assertIsInstance(result, ProtocolRuntimeResponse)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(hidden, {"csrfmiddlewaretoken": "csrf-1"})

    def test_post_form_uses_http_client_session(self):
        client = _FakeHTTPClient()
        runtime = ProtocolSiteRuntime(client=client)

        runtime.post_form("https://example.test/form", {"email": "a@example.com"})

        self.assertEqual(client.calls[0][0], "POST")
        self.assertEqual(client.calls[0][1], "https://example.test/form")
        self.assertEqual(client.calls[0][2]["data"], {"email": "a@example.com"})


class BrowserFallbackRuntimeTests(unittest.TestCase):
    def test_restore_applies_session_state_to_page_and_context(self):
        context = mock.Mock()
        page = mock.Mock()
        page.url = "https://example.test/dashboard"
        runtime = BrowserFallbackRuntime(page=page, context=context, browser=mock.Mock(), owns_session=False)

        runtime.restore(
            BrowserRuntimeSessionState(
                current_url="https://example.test/dashboard",
                cookies=[{"name": "sid", "value": "cookie-1", "url": "https://example.test"}],
            )
        )

        page.goto.assert_called_once_with("https://example.test/dashboard", wait_until="domcontentloaded")
        context.add_cookies.assert_called_once()
        self.assertEqual(runtime.current_url(), "https://example.test/dashboard")

    def test_open_navigates_page_and_returns_runtime_step(self):
        context = mock.Mock()
        page = mock.Mock()
        page.url = "https://example.test/login"
        page.content.return_value = "<html>login</html>"
        runtime = BrowserFallbackRuntime(page=page, context=context, browser=mock.Mock(), owns_session=False)

        step = runtime.open("https://example.test/login")

        page.goto.assert_called_once_with("https://example.test/login", wait_until="domcontentloaded")
        self.assertIsInstance(step, BrowserRuntimeStep)
        self.assertEqual(step.code, "open")
        self.assertEqual(step.status, "completed")
        self.assertEqual(step.detail, "https://example.test/login")

    def test_snapshot_returns_browser_runtime_session_state(self):
        context = mock.Mock()
        context.cookies.return_value = [{"name": "sid", "value": "cookie-1"}]
        page = mock.Mock()
        page.url = "https://example.test/dashboard"
        runtime = BrowserFallbackRuntime(page=page, context=context, browser=mock.Mock(), owns_session=False)

        snapshot = runtime.snapshot()

        self.assertIsInstance(snapshot, BrowserRuntimeSessionState)
        self.assertEqual(snapshot.current_url, "https://example.test/dashboard")
        self.assertEqual(snapshot.cookies, [{"name": "sid", "value": "cookie-1"}])

    def test_click_role_clicks_accessible_button_by_name(self):
        context = mock.Mock()
        page = mock.Mock()
        page.url = "https://example.test/signup"
        role_locator = mock.Mock()
        page.get_by_role.return_value = role_locator
        runtime = BrowserFallbackRuntime(page=page, context=context, browser=mock.Mock(), owns_session=False)

        runtime.click_role("button", "Create Account")

        page.get_by_role.assert_called_once_with("button", name="Create Account")
        role_locator.click.assert_called_once_with()

    def test_wait_for_text_waits_for_visible_success_copy(self):
        context = mock.Mock()
        page = mock.Mock()
        page.url = "https://example.test/signup"
        text_locator = mock.Mock()
        page.get_by_text.return_value = text_locator
        runtime = BrowserFallbackRuntime(page=page, context=context, browser=mock.Mock(), owns_session=False)

        runtime.wait_for_text("Account Created Successfully")

        page.get_by_text.assert_called_once_with("Account Created Successfully")
        text_locator.wait_for.assert_called_once_with(state="visible")

    def test_fill_role_enters_value_into_accessible_textbox_by_name(self):
        context = mock.Mock()
        page = mock.Mock()
        page.url = "https://example.test/signup"
        role_locator = mock.Mock()
        page.get_by_role.return_value = role_locator
        runtime = BrowserFallbackRuntime(page=page, context=context, browser=mock.Mock(), owns_session=False)

        runtime.fill_role("textbox", "Email address", "admin@example.com")

        page.get_by_role.assert_called_once_with("textbox", name="Email address")
        role_locator.fill.assert_called_once_with("admin@example.com")

    def test_fill_role_can_request_exact_accessible_name_match(self):
        context = mock.Mock()
        page = mock.Mock()
        page.url = "https://example.test/signup"
        role_locator = mock.Mock()
        page.get_by_role.return_value = role_locator
        runtime = BrowserFallbackRuntime(page=page, context=context, browser=mock.Mock(), owns_session=False)

        runtime.fill_role("textbox", "Password", "secret-pass", exact=True)

        page.get_by_role.assert_called_once_with("textbox", name="Password", exact=True)
        role_locator.fill.assert_called_once_with("secret-pass")
