from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class CodexGUIConfigMixin:
    extra_config: dict[str, Any]
    _codex_gui_config_cache: dict[str, Any] | None

    def _config_file_path(self) -> Path:
        configured = str(
            self.extra_config.get("codex_gui_config_file")
            or self.extra_config.get("codex_gui_page_markers_file")
            or self.extra_config.get("codex_gui_blank_area_clicks_file")
            or ""
        ).strip()
        if configured:
            return Path(configured)
        return Path(__file__).parents[2] / "codex_gui_config.json"

    def codex_gui_config(self) -> dict[str, Any]:
        if self._codex_gui_config_cache is not None:
            return self._codex_gui_config_cache
        path = self._config_file_path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._codex_gui_config_cache = {}
            return self._codex_gui_config_cache
        if not isinstance(payload, dict):
            raise RuntimeError(f"Codex GUI 配置格式错误: {path}")
        self._codex_gui_config_cache = payload
        return payload

    def page_markers(self) -> dict[str, list[str]]:
        payload = self.codex_gui_config().get("page_markers")
        if not isinstance(payload, dict):
            return {}
        markers: dict[str, list[str]] = {}
        for stage, values in payload.items():
            if not isinstance(values, list):
                continue
            markers[str(stage)] = [str(item or "").strip() for item in values if str(item or "").strip()]
        return markers

    def blank_area_clicks(self) -> dict[str, Any]:
        payload = self.codex_gui_config().get("blank_area_clicks")
        return payload if isinstance(payload, dict) else {}

    def waits_config(self) -> dict[str, Any]:
        payload = self.codex_gui_config().get("waits")
        return payload if isinstance(payload, dict) else {}
