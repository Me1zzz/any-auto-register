from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CodexGUITargetResolution:
    """描述一次目标定位成功后的结果。"""

    locator: Any
    strategy_kind: str
    strategy_value: str
    box: dict[str, float] | None


@dataclass(frozen=True)
class PywinautoTextCandidate:
    """描述 UIA 树中提取出的一个可见文本候选。"""

    text: str
    box: dict[str, float]


@dataclass(frozen=True)
class PywinautoBlankAreaClickConfig:
    """描述 pywinauto 模式下空白区域点击的策略配置。"""

    enabled: bool
    box: dict[str, float] | None
    click_count_min: int
    click_count_max: int
    interval_seconds_min: float
    interval_seconds_max: float


class NullCodexGUILocator:
    """在 pywinauto 模式下占位的无操作 locator。"""

    def scroll_into_view_if_needed(self, timeout: int | None = None) -> None:
        """兼容 Playwright locator 接口；pywinauto 路径下无实际行为。"""
        return None

    def set_focus(self) -> None:
        """兼容 Playwright locator 接口；pywinauto 路径下无实际行为。"""
        return None


class CodexGUITargetDetector(ABC):
    """GUI 目标检测器的统一抽象接口。"""

    @abstractmethod
    def resolve_target(self, name: str) -> CodexGUITargetResolution:
        """解析一个命名目标并返回可执行的定位结果。"""
        raise NotImplementedError

    @abstractmethod
    def peek_target(self, name: str, *, timeout_ms: int | None = None) -> tuple[str, str, dict[str, float] | None]:
        """轻量查看目标是否可见，并返回策略和几何信息。"""
        raise NotImplementedError
