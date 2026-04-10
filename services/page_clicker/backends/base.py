from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import ClickResult, PageClickConfig


class PageClickBackend(ABC):
    name: str

    @abstractmethod
    def run(self, config: PageClickConfig) -> ClickResult:
        raise NotImplementedError
