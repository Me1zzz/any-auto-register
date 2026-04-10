"""Dual-backend page click framework with Playwright and PyAutoGUI."""

from .config import build_config_from_args
from .models import ClickResult, PageClickConfig
from .runner import run_click_flow

__all__ = [
    "ClickResult",
    "PageClickConfig",
    "build_config_from_args",
    "run_click_flow",
]
