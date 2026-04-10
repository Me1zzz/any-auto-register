import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from services.page_clicker.backends.pyautogui_backend import PyAutoGUIPageClickBackend
from services.page_clicker.models import PageClickConfig, PyAutoGUIOptions, TargetSpec


class _FakeScreenshot:
    def __init__(self):
        self.saved_path = None

    def save(self, path):
        self.saved_path = path
        Path(path).write_bytes(b"fake-image")


class _FakePyAutoGUI:
    def __init__(self, locate_point=None):
        self.FAILSAFE = True
        self.PAUSE = 0
        self.locate_point = locate_point
        self.moves = []
        self.clicks = []
        self.down_count = 0
        self.up_count = 0
        self.screenshots = []

    def locateCenterOnScreen(self, image_path, confidence=None, region=None):
        return self.locate_point

    def moveTo(self, x, y, duration):
        self.moves.append((x, y, duration))

    def click(self, x, y):
        self.clicks.append((x, y))

    def mouseDown(self):
        self.down_count += 1

    def mouseUp(self):
        self.up_count += 1

    def screenshot(self):
        screenshot = _FakeScreenshot()
        self.screenshots.append(screenshot)
        return screenshot


class PageClickerPyAutoGUIBackendTests(unittest.TestCase):
    def test_pyautogui_backend_clicks_image_target_and_saves_screenshot(self):
        backend = PyAutoGUIPageClickBackend()
        fake_gui = _FakePyAutoGUI(locate_point=SimpleNamespace(x=123, y=456))
        with tempfile.TemporaryDirectory() as tmp_dir:
            screenshot_path = Path(tmp_dir) / "screen.png"
            config = PageClickConfig(
                backend="pyautogui",
                target=TargetSpec(kind="image", value="button.png"),
                screenshot_path=screenshot_path,
                pyautogui=PyAutoGUIOptions(
                    image_path=Path("button.png"),
                    allow_gui_control=True,
                    move_duration_ms=300,
                    pre_click_delay_ms=10,
                    post_click_delay_ms=20,
                ),
            )

            with mock.patch.dict("sys.modules", {"pyautogui": fake_gui}), mock.patch(
                "services.page_clicker.backends.pyautogui_backend._sleep_ms"
            ):
                result = backend.run(config)

        self.assertTrue(result.success)
        self.assertEqual(result.backend, "pyautogui")
        self.assertEqual(result.clicked_position, (123, 456))
        self.assertEqual(fake_gui.moves, [(123, 456, 0.3)])
        self.assertEqual(fake_gui.clicks, [(123, 456)])
        self.assertEqual(len(fake_gui.screenshots), 1)

    def test_pyautogui_backend_uses_mouse_down_up_in_human_mode(self):
        backend = PyAutoGUIPageClickBackend()
        fake_gui = _FakePyAutoGUI(locate_point=SimpleNamespace(x=80, y=90))
        config = PageClickConfig(
            backend="pyautogui",
            click_mode="human",
            target=TargetSpec(kind="image", value="button.png"),
            pyautogui=PyAutoGUIOptions(
                image_path=Path("button.png"),
                allow_gui_control=True,
                pre_click_delay_ms=60,
            ),
        )

        with mock.patch.dict("sys.modules", {"pyautogui": fake_gui}), mock.patch(
            "services.page_clicker.backends.pyautogui_backend._sleep_ms"
        ):
            result = backend.run(config)

        self.assertTrue(result.success)
        self.assertEqual(fake_gui.clicks, [])
        self.assertEqual(fake_gui.down_count, 1)
        self.assertEqual(fake_gui.up_count, 1)

    def test_pyautogui_backend_clicks_explicit_point(self):
        backend = PyAutoGUIPageClickBackend()
        fake_gui = _FakePyAutoGUI()
        config = PageClickConfig(
            backend="pyautogui",
            target=TargetSpec(kind="point", x=640, y=480),
            pyautogui=PyAutoGUIOptions(
                point=(640, 480),
                allow_gui_control=True,
            ),
        )

        with mock.patch.dict("sys.modules", {"pyautogui": fake_gui}), mock.patch(
            "services.page_clicker.backends.pyautogui_backend._sleep_ms"
        ):
            result = backend.run(config)

        self.assertTrue(result.success)
        self.assertEqual(result.clicked_position, (640, 480))
        self.assertEqual(fake_gui.clicks, [(640, 480)])


if __name__ == "__main__":
    unittest.main()
