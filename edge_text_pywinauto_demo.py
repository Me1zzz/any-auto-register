"""UI Automation demo using `pywinauto` for an already-open Edge window.

Install:
    pip install pywinauto

Examples:
    python edge_text_pywinauto_demo.py
    python edge_text_pywinauto_demo.py --keyword 登录 --keyword 搜索
    python edge_text_pywinauto_demo.py --title-keyword Edge

Notes:
    - This script reads the Windows accessibility tree exposed by Edge.
    - Output coordinates are absolute screen coordinates: {text, x, y, w, h}.
    - Page content coverage depends on what Edge exposes through UI Automation.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from typing import Iterable

from pywinauto import Application, findwindows


@dataclass(frozen=True)
class TextBox:
    text: str
    x: int
    y: int
    w: int
    h: int

    def to_dict(self) -> dict[str, int | str]:
        return {
            "text": self.text,
            "x": self.x,
            "y": self.y,
            "w": self.w,
            "h": self.h,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read Edge accessible text and rectangles via pywinauto.",
    )
    parser.add_argument(
        "--title-keyword",
        default="Edge",
        help="Keyword used to choose the Edge window by title.",
    )
    parser.add_argument(
        "--keyword",
        action="append",
        default=[],
        help="Only keep results whose text contains this keyword. Repeatable.",
    )
    return parser.parse_args()


def matches_keywords(text: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    return any(keyword in text for keyword in keywords)


def find_edge_window(title_keyword: str):
    title_pattern = rf".*{re.escape(title_keyword)}.*"
    handles = findwindows.find_windows(title_re=title_pattern)
    if not handles:
        raise RuntimeError(
            f"没有找到标题包含 {title_keyword!r} 的已打开 Edge 窗口。"
        )

    app = Application(backend="uia").connect(handle=handles[0])
    return app.window(handle=handles[0])


def deduplicate(items: Iterable[TextBox]) -> list[TextBox]:
    seen: set[tuple[str, int, int, int, int]] = set()
    deduped: list[TextBox] = []

    for item in items:
        key = (item.text, item.x, item.y, item.w, item.h)
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    return sorted(deduped, key=lambda item: (item.y, item.x, item.text))


def main() -> None:
    args = parse_args()
    edge_window = find_edge_window(args.title_keyword)

    items: list[TextBox] = []
    for control in edge_window.iter_descendants():
        try:
            text = (control.window_text() or "").strip()
        except Exception:
            continue

        if not text or not matches_keywords(text, args.keyword):
            continue

        try:
            rect = control.rectangle()
        except Exception:
            continue

        x = int(rect.left)
        y = int(rect.top)
        w = int(rect.width())
        h = int(rect.height())
        if w <= 0 or h <= 0:
            continue

        items.append(TextBox(text=text, x=x, y=y, w=w, h=h))

    print(json.dumps([item.to_dict() for item in deduplicate(items)], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
