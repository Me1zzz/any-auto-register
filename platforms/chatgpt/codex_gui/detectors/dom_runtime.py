from __future__ import annotations

from typing import Any

from services.page_clicker.dom import extract_clickable_candidates


def fetch_dom_snapshot(detector, target_name: str) -> tuple[str, list[dict[str, str]]]:
    page = detector._require_page()
    detector._log_debug(f"[DOM] 开始获取当前页面 DOM: target={target_name}")
    html = str(page.content() or "")
    try:
        candidates = extract_clickable_candidates(html)
    except Exception as exc:
        detector._log_debug(f"[DOM] 静态候选提取失败（忽略）: {exc}")
        candidates = []
    preview = []
    for item in candidates[:8]:
        text = str(item.get("text") or "").strip()
        selector = str(item.get("selector") or "").strip()
        if text or selector:
            preview.append(f"{item.get('tag')}:{text or selector}")
    detector._log_debug(f"[DOM] 获取完成: len={len(html)}, clickable={len(candidates)}, sample={preview}")
    return html, candidates


def configured_dom_target(detector, name: str) -> dict[str, Any] | None:
    targets = detector.extra_config.get("codex_gui_targets") or detector.extra_config.get("codex_gui_step_targets") or {}
    if not isinstance(targets, dict):
        raise RuntimeError("codex_gui_targets 配置格式错误，必须为字典")
    target = targets.get(name)
    return target if isinstance(target, dict) else None


def locator_from_strategy(detector, page, strategy_kind: str, strategy_value: str):
    if strategy_kind == "css":
        return page.locator(strategy_value).first
    if strategy_kind == "text":
        return page.get_by_text(strategy_value, exact=False).first
    if strategy_kind == "role":
        return page.get_by_role("button", name=strategy_value, exact=False).first
    raise RuntimeError(f"不支持的 DOM 定位策略: {strategy_kind}")


def resolve_dom_target(detector, name: str, *, timeout_ms: int | None = None) -> dict[str, Any]:
    page = detector._require_page()
    fetch_dom_snapshot(detector, name)
    configured = detector.configured_dom_target(name)
    strategies: list[tuple[str, str]] = []
    if configured:
        kind = str(configured.get("kind") or "").strip().lower()
        value = str(configured.get("value") or configured.get("selector") or configured.get("text") or "").strip()
        if kind in {"css", "text", "role"} and value:
            strategies.append((kind, value))
    strategies.extend(detector.builtin_target_strategies(name))
    last_error: Exception | None = None
    for strategy_kind, strategy_value in strategies:
        detector._log_debug(f"[DOM] 开始定位目标: name={name}, strategy={strategy_kind}, value={strategy_value}")
        locator = locator_from_strategy(detector, page, strategy_kind, strategy_value)
        try:
            effective_timeout_ms = int(timeout_ms if timeout_ms is not None else detector._timeout_ms)
            locator.wait_for(state="visible", timeout=effective_timeout_ms)
            box = locator.bounding_box(timeout=effective_timeout_ms)
            detector._log_debug(
                f"[DOM] 定位成功: name={name}, strategy={strategy_kind}, value={strategy_value}, box={box}"
            )
            return {
                "locator": locator,
                "strategy_kind": strategy_kind,
                "strategy_value": strategy_value,
                "box": box,
            }
        except Exception as exc:
            last_error = exc
            detector._log_debug(
                f"[DOM] 定位失败: name={name}, strategy={strategy_kind}, value={strategy_value}, error={exc}"
            )
    raise RuntimeError(f"无法在当前页面 DOM 中定位目标: {name} ({last_error})")
