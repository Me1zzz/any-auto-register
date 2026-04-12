from __future__ import annotations

import ctypes
import random
import subprocess
import time
from typing import Any, Callable


class PyAutoGUICodexGUIController:
    def __init__(
        self,
        *,
        extra_config: dict[str, Any],
        logger_fn: Callable[[str], None],
        pyautogui_getter: Callable[[], Any],
    ) -> None:
        self.extra_config = dict(extra_config or {})
        self.logger_fn = logger_fn
        self._pyautogui_getter = pyautogui_getter

    def _log_debug(self, message: str) -> None:
        self.logger_fn(message)

    def _wait_range(self, min_key: str, max_key: str, default_min: float, default_max: float) -> tuple[float, float]:
        min_value = self.extra_config.get(min_key, default_min)
        max_value = self.extra_config.get(max_key, default_max)
        try:
            parsed_min = max(0.0, float(min_value or default_min))
        except Exception:
            parsed_min = default_min
        try:
            parsed_max = max(parsed_min, float(max_value or default_max))
        except Exception:
            parsed_max = max(default_max, parsed_min)
        return parsed_min, parsed_max

    def _random_wait_from_config(self, reason: str, min_key: str, max_key: str, default_min: float, default_max: float) -> float:
        wait_min, wait_max = self._wait_range(min_key, max_key, default_min, default_max)
        delay = random.uniform(wait_min, wait_max)
        self._log_debug(f"[节奏] 操作后随机停顿: reason={reason}, delay={delay * 1000:.1f}ms")
        return delay

    def _random_action_delay(self, reason: str) -> float:
        return self._random_wait_from_config(
            reason,
            "codex_gui_post_action_pause_seconds_min",
            "codex_gui_post_action_pause_seconds_max",
            0.2,
            1.5,
        )

    def random_post_action_pause(self, reason: str) -> None:
        delay = self._random_action_delay(reason)
        time.sleep(delay)

    def human_move_to(self, pyautogui, x: int, y: int, duration: float) -> None:
        try:
            start_x, start_y = pyautogui.position()
        except Exception:
            start_x, start_y = x, y
        total_duration = max(duration, 0.01)
        distance = max(((x - start_x) ** 2 + (y - start_y) ** 2) ** 0.5, 1.0)
        gravity = float(self.extra_config.get("codex_gui_windmouse_gravity", 9.0) or 9.0)
        wind = float(self.extra_config.get("codex_gui_windmouse_wind", 3.0) or 3.0)
        max_step = float(self.extra_config.get("codex_gui_windmouse_max_step", 15.0) or 15.0)
        target_area = float(self.extra_config.get("codex_gui_windmouse_target_area", 8.0) or 8.0)
        max_steps = max(100, int(self.extra_config.get("codex_gui_windmouse_max_steps", 160) or 160))
        self._log_debug(
            f"[GUI] WindMouse 移动: start=({start_x},{start_y}), target=({x},{y}), gravity={gravity:.2f}, wind={wind:.2f}, max_step={max_step:.2f}, target_area={target_area:.2f}, max_steps={max_steps}"
        )
        if distance <= 3:
            pyautogui.moveTo(x, y, duration=total_duration)
            return

        current_x = float(start_x)
        current_y = float(start_y)
        velocity_x = 0.0
        velocity_y = 0.0
        wind_x = 0.0
        wind_y = 0.0
        screen_width, screen_height = pyautogui.size()
        path: list[tuple[int, int]] = []

        for _index in range(max_steps):
            remaining_x = x - current_x
            remaining_y = y - current_y
            remaining_distance = (remaining_x * remaining_x + remaining_y * remaining_y) ** 0.5
            if remaining_distance < 1.0:
                break

            local_wind = min(wind, remaining_distance)
            if remaining_distance >= target_area:
                wind_x = wind_x / 1.6 + random.uniform(-local_wind, local_wind) / 3.0
                wind_y = wind_y / 1.6 + random.uniform(-local_wind, local_wind) / 3.0
            else:
                wind_x /= 1.3
                wind_y /= 1.3
                local_max = max(3.0, min(max_step, remaining_distance))
                max_step = max(local_max, 3.0)

            if remaining_distance > 0:
                velocity_x += wind_x + gravity * remaining_x / remaining_distance
                velocity_y += wind_y + gravity * remaining_y / remaining_distance

            velocity_mag = (velocity_x * velocity_x + velocity_y * velocity_y) ** 0.5
            if velocity_mag > max_step:
                clip = max_step / max(velocity_mag, 1e-6)
                velocity_x *= clip
                velocity_y *= clip

            current_x += velocity_x
            current_y += velocity_y
            step_x = int(round(current_x))
            step_y = int(round(current_y))
            step_x = max(1, min(int(screen_width) - 1, step_x))
            step_y = max(1, min(int(screen_height) - 1, step_y))
            if not path or path[-1] != (step_x, step_y):
                path.append((step_x, step_y))

        if not path or path[-1] != (x, y):
            path.append((x, y))

        step_duration = max(total_duration / max(len(path), 1), 0.0005)
        self._log_debug(
            f"[GUI] WindMouse 轨迹摘要: steps={len(path)}, start=({start_x},{start_y}), end=({x},{y}), step_duration={step_duration:.3f}s"
        )
        for index, (step_x, step_y) in enumerate(path, start=1):
            pyautogui.moveTo(step_x, step_y, duration=0)
            time.sleep(step_duration)

    def type_text_humanized(self, pyautogui, text: str) -> None:
        content = str(text or "")
        if not content:
            return
        self.paste_text(pyautogui, content, reason="field_input")
        settle = self._random_wait_from_config(
            "type_text",
            "codex_gui_typing_paste_settle_seconds_min",
            "codex_gui_typing_paste_settle_seconds_max",
            0.05,
            0.15,
        )
        time.sleep(settle)
        self.random_post_action_pause("type_text")

    def type_text_fast(self, pyautogui, text: str, *, reason: str = "fast_type") -> None:
        content = str(text or "")
        if not content:
            return
        self._log_debug(f"[GUI] 快速输入文本: reason={reason}, length={len(content)}")
        pyautogui.write(content, interval=0)

    def navigate_with_address_bar(self, pyautogui, url: str) -> None:
        target_url = str(url or "").strip()
        if not target_url:
            raise RuntimeError("缺少要输入到地址栏的 URL")
        self._log_debug(f"[GUI] 通过地址栏导航: url={target_url}")
        self.type_text_fast(pyautogui, target_url, reason="address_bar")
        pyautogui.press("enter")

    def paste_text(self, pyautogui, text: str, *, reason: str = "paste_text") -> None:
        content = str(text or "")
        if not content:
            return
        self._log_debug(f"[GUI] 剪贴板粘贴文本: reason={reason}, length={len(content)}")
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            input=content,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"设置剪贴板失败: {completed.stderr or completed.stdout}")
        pyautogui.hotkey("ctrl", "v")

    def click_screen_point(self, name: str, x: int, y: int) -> None:
        pyautogui = self._pyautogui_getter()
        move_duration = float(self.extra_config.get("codex_gui_move_duration_ms", 200) or 200) / 1000
        pre_min, pre_max = self._wait_range(
            "codex_gui_pre_click_delay_seconds_min",
            "codex_gui_pre_click_delay_seconds_max",
            0.2,
            1.5,
        )
        post_min, post_max = self._wait_range(
            "codex_gui_post_click_delay_seconds_min",
            "codex_gui_post_click_delay_seconds_max",
            0.2,
            1.5,
        )
        pre_click_delay = random.uniform(pre_min, pre_max)
        post_click_delay = random.uniform(post_min, post_max)
        self._log_debug(f"[GUI] 移动鼠标: name={name}, to=({x}, {y}), duration={move_duration:.3f}s")
        self.human_move_to(pyautogui, x, y, move_duration)
        time.sleep(max(pre_click_delay, 0))
        self._log_debug(f"[GUI] 点击目标: name={name}, point=({x}, {y})")
        pyautogui.click(x, y)
        time.sleep(max(post_click_delay, 0))
        self.random_post_action_pause(f"click:{name}")

    def focus_and_clear_input(self, name: str) -> None:
        pyautogui = self._pyautogui_getter()
        self._log_debug(f"[GUI] 清空输入框: name={name}")
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")
        self.random_post_action_pause(f"clear:{name}")

    def switch_to_english_input(self) -> None:
        self._log_debug("[输入法] 开始切换到英文输入模式")
        try:
            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            load_keyboard_layout = getattr(user32, "LoadKeyboardLayoutW", None)
            activate_keyboard_layout = getattr(user32, "ActivateKeyboardLayout", None)
            get_foreground_window = getattr(user32, "GetForegroundWindow", None)
            get_window_thread_process_id = getattr(user32, "GetWindowThreadProcessId", None)
            post_message = getattr(user32, "PostMessageW", None)
            if (
                callable(load_keyboard_layout)
                and callable(activate_keyboard_layout)
                and callable(get_foreground_window)
                and callable(get_window_thread_process_id)
                and callable(post_message)
            ):
                load_keyboard_layout_fn: Any = load_keyboard_layout
                activate_keyboard_layout_fn: Any = activate_keyboard_layout
                get_foreground_window_fn: Any = get_foreground_window
                get_window_thread_process_id_fn: Any = get_window_thread_process_id
                post_message_fn: Any = post_message
                hkl = load_keyboard_layout_fn("00000409", 1)
                if hkl:
                    activate_keyboard_layout_fn(hkl, 0)
                    hwnd = get_foreground_window_fn()
                    if hwnd:
                        get_window_thread_process_id_fn(hwnd, None)
                        wm_inputlangchangerequest = 0x0050
                        post_message_fn(hwnd, wm_inputlangchangerequest, 0, hkl)
                    self._log_debug("[输入法] 已通过 Win32 API 切换到英文键盘布局")
                    return
        except Exception as exc:
            self._log_debug(f"[输入法] Win32 API 切换失败，尝试快捷键回退: {exc}")

        pyautogui = self._pyautogui_getter()
        try:
            pyautogui.hotkey("ctrl", "space")
            ime_min, ime_max = self._wait_range(
                "codex_gui_ime_switch_wait_seconds_min",
                "codex_gui_ime_switch_wait_seconds_max",
                0.2,
                1.5,
            )
            time.sleep(random.uniform(ime_min, ime_max))
            self._log_debug("[输入法] 已通过 Ctrl+Space 尝试切换到英文输入模式")
        except Exception as exc:
            self._log_debug(f"[输入法] Ctrl+Space 切换失败，尝试 Shift: {exc}")
            pyautogui.press("shift")
            ime_min, ime_max = self._wait_range(
                "codex_gui_ime_switch_wait_seconds_min",
                "codex_gui_ime_switch_wait_seconds_max",
                0.2,
                1.5,
            )
            time.sleep(random.uniform(ime_min, ime_max))
            self._log_debug("[输入法] 已通过 Shift 尝试切换到英文输入模式")

    def press_keys(self, *keys: str) -> None:
        pyautogui = self._pyautogui_getter()
        filtered = [str(key or "").strip() for key in keys if str(key or "").strip()]
        if not filtered:
            return
        if len(filtered) == 1:
            pyautogui.press(filtered[0])
            return
        pyautogui.hotkey(*filtered)
