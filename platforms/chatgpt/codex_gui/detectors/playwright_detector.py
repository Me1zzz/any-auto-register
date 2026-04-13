from __future__ import annotations

from typing import Any, Callable

from platforms.chatgpt.codex_gui.detectors.base import CodexGUITargetDetector, CodexGUITargetResolution
from platforms.chatgpt.codex_gui.detectors import dom_runtime
from platforms.chatgpt.codex_gui.targets.catalog import builtin_dom_target_strategies


class PlaywrightCodexGUITargetDetector(CodexGUITargetDetector):
    def __init__(self, *, extra_config: dict[str, Any], logger_fn: Callable[[str], None], browser_session: Any) -> None:
        self.extra_config = dict(extra_config or {})
        self.logger_fn = logger_fn
        self.browser_session = browser_session
        self._timeout_ms = int(self.extra_config.get("codex_gui_dom_timeout_ms", 15_000) or 15_000)

    def _log_debug(self, message: str) -> None:
        self.logger_fn(message)

    def _require_page(self):
        return self.browser_session.require_page()

    def fetch_dom_snapshot(self, target_name: str) -> tuple[str, list[dict[str, str]]]:
        return dom_runtime.fetch_dom_snapshot(self, target_name)

    def configured_dom_target(self, name: str) -> dict[str, Any] | None:
        return dom_runtime.configured_dom_target(self, name)

    def builtin_target_strategies(self, name: str) -> list[tuple[str, str]]:
        return builtin_dom_target_strategies(name)

    def locator_from_strategy(self, page, strategy_kind: str, strategy_value: str):
        return dom_runtime.locator_from_strategy(self, page, strategy_kind, strategy_value)

    def resolve_target(self, name: str, *, timeout_ms: int | None = None) -> CodexGUITargetResolution:
        result = dom_runtime.resolve_dom_target(self, name, timeout_ms=timeout_ms)
        return CodexGUITargetResolution(
            locator=result.get("locator"),
            strategy_kind=str(result.get("strategy_kind") or ""),
            strategy_value=str(result.get("strategy_value") or ""),
            box=result.get("box"),
        )

    def peek_target(self, name: str, *, timeout_ms: int | None = None) -> tuple[str, str, dict[str, float] | None]:
        resolved = self.resolve_target(name, timeout_ms=timeout_ms)
        return resolved.strategy_kind, resolved.strategy_value, resolved.box
