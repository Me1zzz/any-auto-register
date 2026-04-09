import tempfile
import unittest
from pathlib import Path

from services.page_clicker.models import PageClickConfig
from services.page_clicker.runner import perform_click_flow


class _FakeLocator:
    def __init__(self, page):
        self._page = page
        self.first = self

    def inner_text(self, timeout):
        self._page.seen_timeout = timeout
        return "Start Automation"

    def click(self, timeout):
        self._page.clicked = True
        self._page.seen_timeout = timeout
        self._page.url = "file:///clicked.html"


class _FakePage:
    def __init__(self):
        self.url = "about:blank"
        self.clicked = False
        self.seen_timeout = None
        self.waited_for = None
        self.screenshot_target = None

    def goto(self, url, wait_until, timeout):
        self.url = url
        self.wait_until = wait_until
        self.seen_timeout = timeout

    def wait_for_selector(self, selector, timeout):
        self.waited_for = (selector, timeout)

    def locator(self, selector):
        self.selector = selector
        return _FakeLocator(self)

    def screenshot(self, path, full_page):
        self.screenshot_target = (path, full_page)
        Path(path).write_bytes(b"fake-image")

    def title(self):
        return "Page Clicker Demo - Clicked"


class PageClickerRunnerTests(unittest.TestCase):
    def test_perform_click_flow_runs_navigation_wait_click_and_screenshot(self):
        page = _FakePage()
        with tempfile.TemporaryDirectory() as tmp_dir:
            screenshot_path = Path(tmp_dir) / "shot.png"
            config = PageClickConfig(
                url="file:///demo.html",
                click_selector="#start-button",
                wait_for_selector="#start-button",
                timeout_ms=3210,
                screenshot_path=screenshot_path,
            )

            result = perform_click_flow(page, config)

        self.assertTrue(result.success)
        self.assertEqual(page.waited_for, ("#start-button", 3210))
        self.assertEqual(page.selector, "#start-button")
        self.assertTrue(page.clicked)
        self.assertEqual(result.final_url, "file:///clicked.html")
        self.assertEqual(result.title, "Page Clicker Demo - Clicked")
        self.assertEqual(result.clicked_text, "Start Automation")


if __name__ == "__main__":
    unittest.main()
