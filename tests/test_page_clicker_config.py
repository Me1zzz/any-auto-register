import os
import unittest

from services.page_clicker.config import build_demo_url, build_parser, parse_optional_bool, build_config_from_args


class PageClickerConfigTests(unittest.TestCase):
    def test_parse_optional_bool_supports_common_values(self):
        self.assertTrue(parse_optional_bool("true"))
        self.assertFalse(parse_optional_bool("0"))
        self.assertIsNone(parse_optional_bool(None))

    def test_build_config_uses_demo_url_when_requested(self):
        parser = build_parser()
        args = parser.parse_args(["--demo", "local-click"])

        config = build_config_from_args(args)

        self.assertEqual(config.url, build_demo_url("local-click"))
        self.assertEqual(config.click_selector, "#start-button")
        self.assertEqual(config.wait_for_selector, "#start-button")

    def test_build_config_reads_headless_from_environment(self):
        parser = build_parser()
        args = parser.parse_args(["--url", "https://example.com"])
        original = os.environ.get("AUTOCLICK_HEADLESS")
        os.environ["AUTOCLICK_HEADLESS"] = "false"
        try:
            config = build_config_from_args(args)
        finally:
            if original is None:
                os.environ.pop("AUTOCLICK_HEADLESS", None)
            else:
                os.environ["AUTOCLICK_HEADLESS"] = original

        self.assertFalse(config.headless)

    def test_cli_headless_overrides_environment(self):
        parser = build_parser()
        args = parser.parse_args(["--url", "https://example.com", "--headless", "true"])
        original = os.environ.get("AUTOCLICK_HEADLESS")
        os.environ["AUTOCLICK_HEADLESS"] = "false"
        try:
            config = build_config_from_args(args)
        finally:
            if original is None:
                os.environ.pop("AUTOCLICK_HEADLESS", None)
            else:
                os.environ["AUTOCLICK_HEADLESS"] = original

        self.assertTrue(config.headless)

    def test_build_config_rejects_missing_url(self):
        parser = build_parser()
        args = parser.parse_args([])

        with self.assertRaises(ValueError):
            build_config_from_args(args)


if __name__ == "__main__":
    unittest.main()
