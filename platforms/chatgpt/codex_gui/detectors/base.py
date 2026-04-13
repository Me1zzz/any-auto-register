from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CodexGUITargetResolution:
    locator: Any
    strategy_kind: str
    strategy_value: str
    box: dict[str, float] | None


@dataclass(frozen=True)
class PywinautoTextCandidate:
    text: str
    box: dict[str, float]


@dataclass(frozen=True)
class PywinautoBlankAreaClickConfig:
    enabled: bool
    box: dict[str, float] | None
    click_count_min: int
    click_count_max: int
    interval_seconds_min: float
    interval_seconds_max: float


class NullCodexGUILocator:
    def scroll_into_view_if_needed(self, timeout: int | None = None) -> None:
        return None

    def set_focus(self) -> None:
        return None


class CodexGUITargetDetector(ABC):
    @abstractmethod
    def resolve_target(self, name: str) -> CodexGUITargetResolution:
        raise NotImplementedError

    @abstractmethod
    def peek_target(self, name: str, *, timeout_ms: int | None = None) -> tuple[str, str, dict[str, float] | None]:
        raise NotImplementedError
