import os
import unittest

from services.page_clicker.config import build_config_from_args, build_demo_url, build_parser, parse_optional_bool


class PageClickerConfigTests(unittest.TestCase):
    def test_parse_optional_bool_supports_common_values(self):
        self.assertTrue(parse_optional_bool("true"))
        self.assertFalse(parse_optional_bool("0"))
        self.assertIsNone(parse_optional_bool(None))

    def test_build_playwright_config_uses_demo_url_when_requested(self):
        parser = build_parser()
        args = parser.parse_args(["--demo", "local-click", "--target-css", "#start-button"])

        config = build_config_from_args(args)

        self.assertEqual(config.backend, "playwright")
        self.assertIsNotNone(config.target)
        self.assertIsNotNone(config.playwright)
        target = config.target
        playwright_options = config.playwright
        if target is None or playwright_options is None:
            self.fail("expected playwright config to be populated")
        self.assertEqual(playwright_options.url, build_demo_url("local-click"))
        self.assertEqual(target.kind, "css")
        self.assertEqual(target.value, "#start-button")
        self.assertEqual(config.click_mode, "direct")

    def test_build_playwright_config_accepts_human_click_mode(self):
        parser = build_parser()
        args = parser.parse_args(["--demo", "local-click", "--target-css", "#start-button", "--click-mode", "human"])

        config = build_config_from_args(args)

        self.assertEqual(config.click_mode, "human")

    def test_build_playwright_config_reads_headless_from_environment(self):
        parser = build_parser()
        args = parser.parse_args(["--url", "https://example.com", "--target-css", "button.submit"])
        original = os.environ.get("AUTOCLICK_HEADLESS")
        os.environ["AUTOCLICK_HEADLESS"] = "false"
        try:
            config = build_config_from_args(args)
        finally:
            if original is None:
                os.environ.pop("AUTOCLICK_HEADLESS", None)
            else:
                os.environ["AUTOCLICK_HEADLESS"] = original

        self.assertIsNotNone(config.playwright)
        if config.playwright is None:
            self.fail("expected playwright options")
        self.assertFalse(config.playwright.headless)

    def test_cli_headless_overrides_environment(self):
        parser = build_parser()
        args = parser.parse_args(["--url", "https://example.com", "--target-css", "button.submit", "--headless", "true"])
        original = os.environ.get("AUTOCLICK_HEADLESS")
        os.environ["AUTOCLICK_HEADLESS"] = "false"
        try:
            config = build_config_from_args(args)
        finally:
            if original is None:
                os.environ.pop("AUTOCLICK_HEADLESS", None)
            else:
                os.environ["AUTOCLICK_HEADLESS"] = original

        self.assertIsNotNone(config.playwright)
        if config.playwright is None:
            self.fail("expected playwright options")
        self.assertTrue(config.playwright.headless)

    def test_build_playwright_config_rejects_missing_target(self):
        parser = build_parser()
        args = parser.parse_args(["--demo", "local-click"])

        with self.assertRaises(ValueError):
            build_config_from_args(args)

    def test_build_pyautogui_config_accepts_image_target(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "--backend",
                "pyautogui",
                "--target-image",
                "tests/fixtures/button.png",
                "--allow-gui-control",
                "true",
                "--region",
                "10,20,300,400",
            ]
        )

        config = build_config_from_args(args)

        self.assertEqual(config.backend, "pyautogui")
        self.assertIsNotNone(config.target)
        self.assertIsNotNone(config.pyautogui)
        target = config.target
        pyautogui_options = config.pyautogui
        if target is None or pyautogui_options is None:
            self.fail("expected pyautogui config to be populated")
        self.assertEqual(target.kind, "image")
        self.assertEqual(pyautogui_options.region, (10, 20, 300, 400))
        self.assertTrue(pyautogui_options.allow_gui_control)

    def test_build_pyautogui_config_accepts_point_target(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "--backend",
                "pyautogui",
                "--target-point",
                "640,480",
                "--allow-gui-control",
                "true",
            ]
        )

        config = build_config_from_args(args)

        self.assertIsNotNone(config.target)
        target = config.target
        if target is None:
            self.fail("expected point target")
        self.assertEqual(target.kind, "point")
        self.assertEqual(target.x, 640)
        self.assertEqual(target.y, 480)

    def test_build_pyautogui_config_requires_explicit_gui_authorization(self):
        parser = build_parser()
        args = parser.parse_args(["--backend", "pyautogui", "--target-point", "640,480"])

        with self.assertRaises(ValueError):
            build_config_from_args(args)

    def test_build_pyautogui_config_rejects_playwright_specific_flags(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "--backend",
                "pyautogui",
                "--target-point",
                "640,480",
                "--allow-gui-control",
                "true",
                "--url",
                "https://example.com",
            ]
        )

        with self.assertRaises(ValueError):
            build_config_from_args(args)


if __name__ == "__main__":
    unittest.main()
