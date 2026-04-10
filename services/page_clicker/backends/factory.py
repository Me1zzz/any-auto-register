from __future__ import annotations

from ..models import PageClickConfig
from .base import PageClickBackend
from .playwright_backend import PlaywrightPageClickBackend
from .pyautogui_backend import PyAutoGUIPageClickBackend


def build_backend(config: PageClickConfig) -> PageClickBackend:
    if config.backend == "playwright":
        return PlaywrightPageClickBackend()
    if config.backend == "pyautogui":
        return PyAutoGUIPageClickBackend()
    raise ValueError(f"未知后端类型: {config.backend}")
