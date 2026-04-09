from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class PageClickConfig:
    url: str
    click_selector: str
    wait_for_selector: str | None = None
    headless: bool | None = None
    timeout_ms: int = 10_000
    screenshot_path: Path | None = None


@dataclass(slots=True)
class ClickResult:
    success: bool
    url: str
    click_selector: str
    final_url: str | None = None
    title: str | None = None
    clicked_text: str | None = None
    screenshot_path: Path | None = None
    error: str | None = None


class OptionalDependencyMissingError(RuntimeError):
    """Raised when an optional framework dependency is unavailable."""
