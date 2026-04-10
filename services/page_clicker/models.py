from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class TargetSpec:
    kind: str
    value: str | None = None
    x: int | None = None
    y: int | None = None
    region: tuple[int, int, int, int] | None = None


@dataclass(slots=True)
class PlaywrightOptions:
    url: str | None = None
    wait_target: TargetSpec | None = None
    headless: bool | None = None
    demo_name: str | None = None


@dataclass(slots=True)
class PyAutoGUIOptions:
    image_path: Path | None = None
    point: tuple[int, int] | None = None
    region: tuple[int, int, int, int] | None = None
    confidence: float | None = None
    move_duration_ms: int = 200
    pre_click_delay_ms: int = 100
    post_click_delay_ms: int = 150
    failsafe: bool = True
    allow_gui_control: bool = False


@dataclass(slots=True)
class PageClickConfig:
    backend: str = "playwright"
    click_mode: str = "direct"
    timeout_ms: int = 10_000
    screenshot_path: Path | None = None
    target: TargetSpec | None = None
    playwright: PlaywrightOptions | None = None
    pyautogui: PyAutoGUIOptions | None = None


@dataclass(slots=True)
class ClickResult:
    success: bool
    backend: str
    url: str | None = None
    target_kind: str | None = None
    target_value: str | None = None
    final_url: str | None = None
    title: str | None = None
    clicked_text: str | None = None
    clicked_position: tuple[int, int] | None = None
    screenshot_path: Path | None = None
    error: str | None = None


class OptionalDependencyMissingError(RuntimeError):
    """Raised when an optional framework dependency is unavailable."""
