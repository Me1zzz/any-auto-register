from __future__ import annotations

"""Compatibility facade for Codex GUI target detectors."""

from platforms.chatgpt.codex_gui.detectors.base import (
    CodexGUITargetDetector,
    CodexGUITargetResolution,
    NullCodexGUILocator,
    PywinautoBlankAreaClickConfig,
    PywinautoTextCandidate,
)
from platforms.chatgpt.codex_gui.detectors.playwright_detector import PlaywrightCodexGUITargetDetector
from platforms.chatgpt.codex_gui.detectors.pywinauto_detector import PywinautoCodexGUITargetDetector

__all__ = [
    "CodexGUITargetDetector",
    "CodexGUITargetResolution",
    "NullCodexGUILocator",
    "PlaywrightCodexGUITargetDetector",
    "PywinautoBlankAreaClickConfig",
    "PywinautoCodexGUITargetDetector",
    "PywinautoTextCandidate",
]
