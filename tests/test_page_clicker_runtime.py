import unittest
from unittest import mock

from services.page_clicker.models import PageClickConfig, PlaywrightOptions, PyAutoGUIOptions, TargetSpec
from services.page_clicker.runner import run_click_flow


class PageClickerRuntimeTests(unittest.TestCase):
    def test_run_click_flow_returns_clear_error_when_playwright_missing(self):
        config = PageClickConfig(
            backend="playwright",
            target=TargetSpec(kind="css", value="#start-button"),
            playwright=PlaywrightOptions(url="file:///demo.html", headless=True),
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
        self.assertEqual(result.backend, "playwright")
        self.assertIn("OptionalDependencyMissingError", error)
        self.assertIn("playwright", error)

    def test_run_click_flow_returns_clear_error_when_pyautogui_missing(self):
        config = PageClickConfig(
            backend="pyautogui",
            target=TargetSpec(kind="point", x=640, y=480),
            pyautogui=PyAutoGUIOptions(point=(640, 480), allow_gui_control=True),
        )

        original_import = __import__

        def _fake_import(name, *args, **kwargs):
            if name == "pyautogui":
                raise ModuleNotFoundError("No module named 'pyautogui'")
            return original_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=_fake_import):
            result = run_click_flow(config)

        self.assertFalse(result.success)
        error = result.error
        self.assertIsNotNone(error)
        if error is None:
            self.fail("expected runtime error when pyautogui is missing")
        self.assertEqual(result.backend, "pyautogui")
        self.assertIn("OptionalDependencyMissingError", error)
        self.assertIn("pyautogui", error)


if __name__ == "__main__":
    unittest.main()
