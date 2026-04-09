import unittest
from unittest import mock

from services.page_clicker.models import PageClickConfig
from services.page_clicker.runner import run_click_flow


class PageClickerRuntimeTests(unittest.TestCase):
    def test_run_click_flow_returns_clear_error_when_playwright_missing(self):
        config = PageClickConfig(
            url="file:///demo.html",
            click_selector="#start-button",
            headless=True,
        )

        original_import = __import__

        def _fake_import(name, *args, **kwargs):
            if name == "playwright.sync_api":
                raise ModuleNotFoundError("No module named 'playwright'")
            return original_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=_fake_import):
            result = run_click_flow(config)

        self.assertFalse(result.success)
        error = result.error
        self.assertIsNotNone(error)
        if error is None:
            self.fail("expected runtime error when playwright is missing")
        self.assertIn("ModuleNotFoundError", error)
        self.assertIn("playwright", error)


if __name__ == "__main__":
    unittest.main()
