import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services.page_clicker.backends.playwright_backend import perform_playwright_click_flow
from services.page_clicker.models import PageClickConfig, PlaywrightOptions, TargetSpec


class _FakeLocator:
    def __init__(self, page):
        self._page = page
        self.first = self
        self.hovered = False
        self.click_called = False
        self.wait_calls = []

    def inner_text(self, timeout):
        self._page.seen_timeout = timeout
        return "Start Automation"

    def hover(self, timeout):
        self._page.seen_timeout = timeout
        self.hovered = True

    def bounding_box(self, timeout):
        self._page.seen_timeout = timeout
        return {"x": 100.0, "y": 200.0, "width": 80.0, "height": 40.0}

    def click(self, timeout):
        self.click_called = True
        self._page.clicked = True
        self._page.seen_timeout = timeout
        self._page.url = "file:///clicked.html"

    def wait_for(self, state, timeout):
        self.wait_calls.append((state, timeout))


class _FakeMouse:
    def __init__(self, page):
        self._page = page
        self.moves = []
        self.down_count = 0
        self.up_count = 0

    def move(self, x, y, steps):
        self.moves.append((x, y, steps))

    def down(self):
        self.down_count += 1

    def up(self):
        self.up_count += 1
        self._page.clicked = True
        self._page.url = "file:///clicked-human.html"


class _FakePage:
    def __init__(self):
        self.url = "about:blank"
        self.clicked = False
        self.seen_timeout = None
        self.screenshot_target = None
        self.mouse = _FakeMouse(self)
        self.locators = {}

    def goto(self, url, wait_until, timeout):
        self.url = url
        self.wait_until = wait_until
        self.seen_timeout = timeout

    def locator(self, selector):
        key = ("css", selector)
        if key not in self.locators:
            self.locators[key] = _FakeLocator(self)
        return self.locators[key]

    def get_by_text(self, text):
        key = ("text", text)
        if key not in self.locators:
            self.locators[key] = _FakeLocator(self)
        return self.locators[key]

    def screenshot(self, path, full_page):
        self.screenshot_target = (path, full_page)
        Path(path).write_bytes(b"fake-image")

    def title(self):
        return "Page Clicker Demo - Clicked"


class PageClickerPlaywrightBackendTests(unittest.TestCase):
    def test_perform_playwright_click_flow_runs_direct_click_and_screenshot(self):
        page = _FakePage()
        with tempfile.TemporaryDirectory() as tmp_dir:
            screenshot_path = Path(tmp_dir) / "shot.png"
            config = PageClickConfig(
                backend="playwright",
                target=TargetSpec(kind="css", value="#start-button"),
                timeout_ms=3210,
                screenshot_path=screenshot_path,
                playwright=PlaywrightOptions(
                    url="file:///demo.html",
                    wait_target=TargetSpec(kind="css", value="#start-button"),
                ),
            )

            result = perform_playwright_click_flow(page, config)

        locator = page.locators[("css", "#start-button")]
        self.assertTrue(result.success)
        self.assertTrue(page.clicked)
        self.assertTrue(locator.click_called)
        self.assertEqual(locator.wait_calls, [("visible", 3210)])
        self.assertEqual(result.final_url, "file:///clicked.html")
        self.assertEqual(result.title, "Page Clicker Demo - Clicked")
        self.assertEqual(result.clicked_text, "Start Automation")
        self.assertEqual(result.backend, "playwright")

    def test_perform_playwright_click_flow_uses_human_click_mode(self):
        page = _FakePage()
        config = PageClickConfig(
            backend="playwright",
            click_mode="human",
            target=TargetSpec(kind="css", value="#start-button"),
            timeout_ms=3210,
            playwright=PlaywrightOptions(
                url="file:///demo.html",
                wait_target=TargetSpec(kind="css", value="#start-button"),
            ),
        )

        with mock.patch("services.page_clicker.backends.playwright_backend.random.uniform", side_effect=[0.5, 0.5]), mock.patch(
            "services.page_clicker.backends.playwright_backend.random.randint",
            side_effect=[60, 12, 40, 80],
        ), mock.patch("services.page_clicker.backends.playwright_backend._sleep_ms"):
            result = perform_playwright_click_flow(page, config)

        locator = page.locators[("css", "#start-button")]
        self.assertTrue(result.success)
        self.assertTrue(locator.hovered)
        self.assertFalse(locator.click_called)
        self.assertEqual(page.mouse.moves, [(140.0, 220.0, 12)])
        self.assertEqual(page.mouse.down_count, 1)
        self.assertEqual(page.mouse.up_count, 1)
        self.assertEqual(result.final_url, "file:///clicked-human.html")
        self.assertEqual(result.clicked_position, (140, 220))


if __name__ == "__main__":
    unittest.main()
