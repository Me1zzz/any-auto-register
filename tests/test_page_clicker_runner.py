import unittest
from unittest import mock

from services.page_clicker.models import ClickResult, PageClickConfig, PlaywrightOptions, TargetSpec
from services.page_clicker.runner import run_click_flow


class PageClickerRunnerTests(unittest.TestCase):
    def test_run_click_flow_delegates_to_selected_backend(self):
        config = PageClickConfig(
            backend="playwright",
            target=TargetSpec(kind="css", value="#start-button"),
            playwright=PlaywrightOptions(url="file:///demo.html"),
        )
        backend_result = ClickResult(success=True, backend="playwright", url="file:///demo.html")
        fake_backend = mock.Mock(run=mock.Mock(return_value=backend_result))

        with mock.patch("services.page_clicker.runner.build_backend", return_value=fake_backend) as build_backend:
            result = run_click_flow(config)

        build_backend.assert_called_once_with(config)
        fake_backend.run.assert_called_once_with(config)
        self.assertTrue(result.success)
        self.assertEqual(result.backend, "playwright")

    def test_run_click_flow_normalizes_backend_failures(self):
        config = PageClickConfig(
            backend="playwright",
            target=TargetSpec(kind="css", value="#start-button"),
            playwright=PlaywrightOptions(url="file:///demo.html"),
        )

        with mock.patch("services.page_clicker.runner.build_backend", side_effect=RuntimeError("boom")):
            result = run_click_flow(config)

        self.assertFalse(result.success)
        self.assertEqual(result.backend, "playwright")
        error = result.error
        self.assertIsNotNone(error)
        if error is None:
            self.fail("expected normalized error")
        self.assertIn("RuntimeError", error)
        self.assertIn("boom", error)


if __name__ == "__main__":
    unittest.main()
