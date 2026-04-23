import unittest

from core.alias_pool.browser_runtime import BrowserRuntimeStep, BrowserRuntimeSessionState
from core.alias_pool.service_adapter_protocol import SiteSessionContext, AliasServiceAdapter
from core.alias_pool.playwright_browser_runtime import PlaywrightAliasBrowserRuntime


class BrowserRuntimeContractTests(unittest.TestCase):
    def test_site_session_context_keeps_page_and_capture_state(self):
        context = SiteSessionContext(
            current_url="https://example.com/login",
            page_state={"cookies": [{"name": "sid", "value": "abc"}]},
            capture_keys=["login_submit"],
        )

        self.assertEqual(context.current_url, "https://example.com/login")
        self.assertEqual(context.page_state["cookies"][0]["name"], "sid")
        self.assertEqual(context.capture_keys, ["login_submit"])

    def test_runtime_step_requires_code_label_and_status(self):
        step = BrowserRuntimeStep(code="open_entrypoint", label="打开入口页", status="completed")

        self.assertEqual(step.code, "open_entrypoint")
        self.assertEqual(step.label, "打开入口页")
        self.assertEqual(step.status, "completed")

    def test_browser_session_state_keeps_storage_and_runtime_url(self):
        state = BrowserRuntimeSessionState(
            current_url="https://example.com/dashboard",
            cookies=[{"name": "sid", "value": "abc"}],
            local_storage={"token": "secret"},
        )

        self.assertEqual(state.current_url, "https://example.com/dashboard")
        self.assertEqual(state.cookies[0]["name"], "sid")
        self.assertEqual(state.local_storage["token"], "secret")

    def test_alias_service_adapter_protocol_surface_is_importable(self):
        self.assertIsNotNone(AliasServiceAdapter)

    def test_playwright_alias_browser_runtime_requires_executor_builder(self):
        with self.assertRaisesRegex(ValueError, "executor_builder"):
            PlaywrightAliasBrowserRuntime(site_url="https://simplelogin.io/", executor_builder=None)

    def test_playwright_alias_browser_runtime_wraps_executor_for_open_snapshot_and_restore(self):
        class _FakePage:
            def __init__(self):
                self.url = "about:blank"
                self.storage = {"token": "secret"}
                self.session = {"state": "ready"}
                self.html = "<html></html>"
                self.fills = []
                self.clicks = []
                self.waits = []

            def goto(self, url, **kwargs):
                self.url = url
                return object()

            def content(self):
                return self.html

            def evaluate(self, script, arg=None):
                if "localStorage" in script and "JSON.stringify" in script:
                    import json

                    return json.dumps(self.storage)
                if "sessionStorage" in script and "JSON.stringify" in script:
                    import json

                    return json.dumps(self.session)
                if "window.localStorage.setItem" in script:
                    for key, value in (arg or {}).items():
                        self.storage[key] = value
                    return None
                if "window.sessionStorage.setItem" in script:
                    for key, value in (arg or {}).items():
                        self.session[key] = value
                    return None
                return None

            def locator(self, selector):
                page = self

                class _Locator:
                    def fill(self, value):
                        page.fills.append((selector, value))

                    def click(self):
                        page.clicks.append(selector)

                return _Locator()

            def wait_for_url(self, pattern, **kwargs):
                self.waits.append(("url", pattern, dict(kwargs)))

            def wait_for_selector(self, selector, **kwargs):
                self.waits.append(("selector", selector, dict(kwargs)))

        class _FakeContext:
            def __init__(self, page):
                self._page = page
                self._cookies = []

            def new_page(self):
                return self._page

            def cookies(self):
                return list(self._cookies)

            def add_cookies(self, cookies):
                self._cookies.extend(cookies)

        class _FakeBrowser:
            def __init__(self, context):
                self._context = context

            def new_context(self, **kwargs):
                return self._context

            def close(self):
                return None

        class _FakePlaywright:
            def __init__(self, browser):
                self.chromium = self
                self._browser = browser

            def launch(self, **kwargs):
                return self._browser

            def stop(self):
                return None

        class _FakeExecutor:
            def __init__(self):
                self.page = _FakePage()
                self.context = _FakeContext(self.page)
                self.browser = _FakeBrowser(self.context)
                self.playwright = _FakePlaywright(self.browser)

            def close(self):
                return None

        runtime = PlaywrightAliasBrowserRuntime(
            site_url="https://simplelogin.io/",
            executor_builder=lambda: _FakeExecutor(),
        )

        step = runtime.open("https://app.simplelogin.io/auth/login")
        runtime.fill("input[type='email']", "util@fst.cxwsss.online")
        runtime.click("button[type=submit]")
        runtime.wait_for_url("**/dashboard/**")
        runtime.wait_for_selector("select[name='signed-alias-suffix']")
        html = runtime.content()
        snapshot = runtime.snapshot()
        runtime.restore(
            BrowserRuntimeSessionState(
                current_url="https://app.simplelogin.io/dashboard/",
                cookies=[{"name": "sid", "value": "abc", "url": "https://app.simplelogin.io/dashboard/"}],
                local_storage={"token": "restored-token"},
                session_storage={"state": "restored"},
            )
        )

        self.assertEqual(step.code, "open")
        self.assertEqual(runtime.current_url(), "https://app.simplelogin.io/dashboard/")
        self.assertEqual(html, "<html></html>")
        self.assertEqual(snapshot.current_url, "https://app.simplelogin.io/auth/login")
        self.assertEqual(snapshot.local_storage["token"], "secret")
        self.assertIn(("url", "**/dashboard/**", {"wait_until": "commit"}), runtime._page.waits)
        self.assertIn(("selector", "select[name='signed-alias-suffix']", {"state": "attached"}), runtime._page.waits)
