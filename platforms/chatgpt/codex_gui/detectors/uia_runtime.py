from __future__ import annotations

import re
import time
from typing import Any

def box_from_rect(rect) -> dict[str, float]:
    return {
        "x": float(int(rect.left)),
        "y": float(int(rect.top)),
        "width": float(int(rect.width())),
        "height": float(int(rect.height())),
    }


def validate_address_bar_control(control) -> tuple[Any, dict[str, float]] | None:
    rect_getter = getattr(control, "rectangle", None)
    if not callable(rect_getter):
        return None
    try:
        rect = rect_getter()
        width_getter = getattr(rect, "width", None)
        height_getter = getattr(rect, "height", None)
        top_value = getattr(rect, "top", None)
        if not callable(width_getter) or not callable(height_getter) or top_value is None:
            return None
        width = int(float(str(width_getter())))
        height = int(float(str(height_getter())))
        top = int(float(str(top_value)))
    except Exception:
        return None
    if width <= 0 or height <= 0 or top < 0:
        return None
    return control, box_from_rect(rect)


def get_cached_address_bar(detector) -> tuple[Any, dict[str, float]] | None:
    cached = detector._address_bar_cache
    if cached is None:
        return None
    control, _box = cached
    validated = validate_address_bar_control(control)
    if validated is None:
        detector._address_bar_cache = None
        return None
    detector._address_bar_cache = validated
    detector._log_debug("[UIA] 复用已缓存地址栏控件")
    return validated


def cache_address_bar(detector, control) -> tuple[Any, dict[str, float]] | None:
    validated = validate_address_bar_control(control)
    if validated is None:
        detector._address_bar_cache = None
        return None
    detector._address_bar_cache = validated
    return validated


def focused_edit_control(detector, window) -> Any | None:
    for attr_name in ("get_focus", "get_active"):
        getter = getattr(window, attr_name, None)
        if not callable(getter):
            continue
        try:
            focused = getter()
        except Exception:
            continue
        if focused is None:
            continue
        candidates: list[Any] = []
        wrapper_getter = getattr(focused, "wrapper_object", None)
        if callable(wrapper_getter):
            try:
                candidates.append(wrapper_getter())
            except Exception:
                pass
        candidates.append(focused)
        for candidate in candidates:
            validated = validate_address_bar_control(candidate)
            if validated is not None:
                return candidate
    return None


def locate_address_bar(detector):
    started_at = time.perf_counter()
    cached = get_cached_address_bar(detector)
    if cached is not None:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        detector._log_debug(f"[耗时] 地址栏定位(cache)完成: elapsed={elapsed_ms:.1f}ms")
        return cached
    window = detector._find_edge_window()
    title_hints = [
        str(item or "").strip()
        for item in (
            detector.extra_config.get("codex_gui_pywinauto_address_bar_title"),
            "Address and search bar",
            "地址和搜索栏",
        )
        if str(item or "").strip()
    ]
    controls_to_try = [{"title": title_hint, "control_type": "Edit"} for title_hint in title_hints]
    controls_to_try.extend([
        {"auto_id": "view_0", "control_type": "Edit"},
        {"control_type": "Edit"},
    ])
    last_error: Exception | None = None
    for criteria in controls_to_try:
        try:
            control = window.child_window(**criteria).wrapper_object()
            rect = control.rectangle()
            validated = cache_address_bar(detector, control)
            if validated is None:
                continue
            detector._log_debug(f"[UIA] 地址栏定位成功: criteria={criteria}, rect={rect}")
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            detector._log_debug(f"[耗时] 地址栏定位(primary)完成: elapsed={elapsed_ms:.1f}ms")
            return validated
        except Exception as exc:
            last_error = exc
    focused_control = focused_edit_control(detector, window)
    if focused_control is not None:
        validated = cache_address_bar(detector, focused_control)
        if validated is not None:
            detector._log_debug(f"[UIA] 地址栏通过焦点 Edit 快速定位成功: control={focused_control}")
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            detector._log_debug(f"[耗时] 地址栏定位(focused)完成: elapsed={elapsed_ms:.1f}ms")
            return validated
    try:
        descendants = window.descendants(control_type="Edit")
    except Exception as exc:
        last_error = exc
        descendants = []
    for control in descendants:
        try:
            rect = control.rectangle()
            validated = cache_address_bar(detector, control)
            if validated is None:
                continue
            detector._log_debug(f"[UIA] 地址栏通过 Edit 回退定位成功: rect={rect}")
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            detector._log_debug(f"[耗时] 地址栏定位(fallback)完成: elapsed={elapsed_ms:.1f}ms")
            return validated
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"无法在当前浏览器窗口中定位地址栏 ({last_error})")


def value_from_control(control) -> str:
    wrapper = control
    for method_name in ("get_value", "window_text"):
        method = getattr(wrapper, method_name, None)
        if callable(method):
            try:
                value = str(method() or "").strip()
            except Exception:
                value = ""
            if value:
                return value
    return ""


def focused_edit_candidate(detector):
    window = detector._find_edge_window()
    for attr_name in ("get_focus", "get_active"):
        getter = getattr(window, attr_name, None)
        if not callable(getter):
            continue
        try:
            focused = getter()
        except Exception:
            continue
        if focused is None:
            continue
        wrapper_getter = getattr(focused, "wrapper_object", None)
        if callable(wrapper_getter):
            try:
                wrapper = wrapper_getter()
            except Exception:
                wrapper = focused
        else:
            wrapper = focused
        value = value_from_control(focused)
        rect_getter = getattr(wrapper, "rectangle", None)
        if not callable(rect_getter):
            continue
        try:
            rect = rect_getter()
        except Exception:
            continue
        width_getter = getattr(rect, "width", None)
        height_getter = getattr(rect, "height", None)
        left = getattr(rect, "left", None)
        top = getattr(rect, "top", None)
        if not callable(width_getter) or not callable(height_getter):
            continue
        try:
            width = int(float(str(width_getter())))
            height = int(float(str(height_getter())))
            if left is None or top is None:
                continue
            left_value = float(str(left))
            top_value = float(str(top))
        except Exception:
            continue
        if width <= 0 or height <= 0:
            continue
        return {"text": value, "box": {"x": left_value, "y": top_value, "width": float(width), "height": float(height)}}
    return None


def boxes_intersect(first: dict[str, float], second: dict[str, float]) -> bool:
    ax1 = float(first.get("x") or 0)
    ay1 = float(first.get("y") or 0)
    ax2 = ax1 + float(first.get("width") or 0)
    ay2 = ay1 + float(first.get("height") or 0)
    bx1 = float(second.get("x") or 0)
    by1 = float(second.get("y") or 0)
    bx2 = bx1 + float(second.get("width") or 0)
    by2 = by1 + float(second.get("height") or 0)
    return ax1 < bx2 and ax2 > bx1 and ay1 < by2 and ay2 > by1


def text_candidates_in_region(detector, region: dict[str, float]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for control, text, box in detector.iter_visible_controls():
        if not boxes_intersect(box, region):
            continue
        value = value_from_control(control)
        candidate_text = value or str(text or "").strip()
        if not candidate_text:
            continue
        candidates.append({"text": candidate_text, "box": {**box}})
    return candidates


def visible_text_candidates(detector) -> list[dict[str, Any]]:
    started_at = time.perf_counter()
    candidates: list[dict[str, Any]] = []
    for control, text, box in detector.iter_visible_controls():
        value = value_from_control(control)
        candidate_text = value or str(text or "").strip()
        if not candidate_text:
            continue
        candidates.append({"text": candidate_text, "box": {**box}})
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    detector._log_debug(f"[耗时] 可见文本候选收集完成: count={len(candidates)}, elapsed={elapsed_ms:.1f}ms")
    return candidates


def page_marker_matched(detector, stage: str) -> tuple[bool, str | None]:
    started_at = time.perf_counter()
    markers = detector.page_text_markers_for_stage(stage)
    if not markers:
        return False, None
    normalized_markers = {marker: "".join(marker.lower().split()) for marker in markers}
    matched_markers: dict[str, dict[str, float]] = {}
    for candidate in visible_text_candidates(detector):
        normalized_candidate = "".join(str(candidate.get("text") or "").lower().split())
        for marker, normalized_marker in normalized_markers.items():
            if marker in matched_markers:
                continue
            if normalized_marker and normalized_marker in normalized_candidate:
                matched_markers[marker] = dict(candidate.get("box") or {})
    missing_markers = [marker for marker in markers if marker not in matched_markers]
    if missing_markers:
        detector._log_debug(f"[UIA] 页面文本未全部命中: stage={stage}, missing={missing_markers}")
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        detector._log_debug(f"[耗时] 页面文本匹配完成(未命中): stage={stage}, elapsed={elapsed_ms:.1f}ms")
        return False, ", ".join(missing_markers)
    detector._log_debug(f"[UIA] 页面文本全部命中: stage={stage}, markers={markers}")
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    detector._log_debug(f"[耗时] 页面文本匹配完成(命中): stage={stage}, elapsed={elapsed_ms:.1f}ms")
    return (True, markers[0]) if markers else (False, None)


def resolve_uia_target(detector, name: str) -> dict[str, Any]:
    started_at = time.perf_counter()
    configured = detector.configured_uia_target(name)
    keywords: list[str] = []
    if configured:
        configured_keywords = configured.get("keywords")
        if isinstance(configured_keywords, (list, tuple, set)):
            keywords.extend(str(item or "").strip() for item in configured_keywords if str(item or "").strip())
        else:
            value = str(configured.get("value") or configured.get("text") or configured.get("keyword") or "").strip()
            if value:
                keywords.append(value)
    keywords.extend(detector.builtin_target_keywords(name))
    keywords = list(dict.fromkeys(keywords))
    if not keywords:
        raise RuntimeError(f"缺少 Codex GUI pywinauto 关键词定义: {name}")
    candidates: list[tuple[int, str, dict[str, float]]] = []
    for _control, text, box in detector.iter_visible_controls():
        if not text:
            continue
        lowered_text = text.lower()
        for keyword in keywords:
            lowered_keyword = keyword.lower()
            if lowered_keyword and lowered_keyword in lowered_text:
                score = 0 if text == keyword else abs(len(text) - len(keyword)) + max(len(text.splitlines()) - 1, 0)
                candidates.append((score, keyword, {**box}))
                break
    if not candidates:
        raise RuntimeError(f"无法在当前 Edge UIA 树中定位目标: {name} (keywords={keywords})")
    score, matched_keyword, box = sorted(candidates, key=lambda item: (item[0], item[2]["y"], item[2]["x"]))[0]
    detector._log_debug(f"[UIA] 定位成功: name={name}, keyword={matched_keyword}, score={score}, box={box}")
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    detector._log_debug(f"[耗时] UIA 目标匹配完成: name={name}, candidates={len(candidates)}, elapsed={elapsed_ms:.1f}ms")
    return {
        "locator": detector._locator,
        "strategy_kind": "uia_text",
        "strategy_value": matched_keyword,
        "box": box,
    }


def find_edge_window(detector):
    Application, findwindows = detector._pywinauto_modules()
    title_keyword = str(detector.extra_config.get("codex_gui_pywinauto_window_title_keyword") or "Edge").strip() or "Edge"
    title_pattern = rf".*{re.escape(title_keyword)}.*"
    handles = list(findwindows.find_windows(title_re=title_pattern))
    if not handles:
        raise RuntimeError(f"没有找到标题包含 {title_keyword!r} 的已打开浏览器窗口")
    app = Application(backend="uia").connect(handle=handles[0])
    return app.window(handle=handles[0])


def iter_visible_controls(detector):
    started_at = time.perf_counter()
    window = detector._find_edge_window()
    try:
        descendants = window.iter_descendants()
    except AttributeError:
        descendants = window.descendants()
    setup_elapsed_ms = (time.perf_counter() - started_at) * 1000
    detector._log_debug(f"[耗时] 可见控件枚举准备完成: elapsed={setup_elapsed_ms:.1f}ms")
    for control in descendants:
        try:
            text = str(control.window_text() or "").strip()
        except Exception:
            text = ""
        try:
            rect = control.rectangle()
        except Exception:
            continue
        width = int(rect.width())
        height = int(rect.height())
        if width <= 0 or height <= 0:
            continue
        yield control, text, {
            "x": float(int(rect.left)),
            "y": float(int(rect.top)),
            "width": float(width),
            "height": float(height),
        }
