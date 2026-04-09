from __future__ import annotations

from .models import OptionalDependencyMissingError


def extract_clickable_candidates(html: str) -> list[dict[str, str]]:
    """Extract simple clickable hints from static HTML.

    This is a helper for offline analysis only. Real clicks are executed by Playwright.
    """

    try:
        from selectolax.parser import HTMLParser
    except ModuleNotFoundError as exc:
        raise OptionalDependencyMissingError(
            "未安装 selectolax，无法使用静态 DOM 分析。请先执行 `pip install -r requirements.txt`。"
        ) from exc

    tree = HTMLParser(html)
    candidates: list[dict[str, str]] = []
    selector_map = {
        "button": "button",
        "a": "a",
        "input": "input",
        "summary": "summary",
    }

    for tag_name, fallback_selector in selector_map.items():
        for node in tree.css(tag_name):
            selector = node.attributes.get("id")
            if selector:
                selector = f"#{selector}"
            else:
                selector = fallback_selector

            text = (node.text() or "").strip()
            candidates.append(
                {
                    "tag": tag_name,
                    "selector": selector,
                    "text": text,
                }
            )

    return candidates
