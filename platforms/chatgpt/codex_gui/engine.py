"""Compatibility entrypoint for the Codex GUI engine."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from platforms.chatgpt.codex_gui_registration_engine import CodexGUIRegistrationEngine as CodexGUIRegistrationEngine

__all__ = ["CodexGUIRegistrationEngine"]
