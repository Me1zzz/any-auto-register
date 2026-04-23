from __future__ import annotations

from html.parser import HTMLParser


_CLICKABLE_TAGS = {"button", "a", "input", "summary"}
_VOID_TAGS = {"input"}


class _ClickableCandidateParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.candidates: list[dict[str, str]] = []
        self._stack: list[dict[str, str | list[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = str(tag or "").strip().lower()
        if normalized_tag not in _CLICKABLE_TAGS:
            return

        attr_map = {
            str(key or "").strip().lower(): str(value or "").strip()
            for key, value in attrs
            if str(key or "").strip()
        }
        selector = f"#{attr_map['id']}" if attr_map.get("id") else normalized_tag
        candidate: dict[str, str | list[str]] = {
            "tag": normalized_tag,
            "selector": selector,
            "text_parts": [],
        }
        self._stack.append(candidate)
        if normalized_tag in _VOID_TAGS:
            self._flush_last_candidate()

    def handle_data(self, data: str) -> None:
        if not self._stack:
            return
        text = str(data or "")
        if not text.strip():
            return
        self._stack[-1]["text_parts"].append(text)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = str(tag or "").strip().lower()
        if not self._stack:
            return
        if str(self._stack[-1].get("tag") or "") != normalized_tag:
            return
        self._flush_last_candidate()

    def close(self) -> None:
        super().close()
        while self._stack:
            self._flush_last_candidate()

    def _flush_last_candidate(self) -> None:
        candidate = self._stack.pop()
        text_parts = candidate.pop("text_parts", [])
        text = " ".join(str(part or "").strip() for part in text_parts if str(part or "").strip())
        self.candidates.append(
            {
                "tag": str(candidate.get("tag") or ""),
                "selector": str(candidate.get("selector") or ""),
                "text": text,
            }
        )


def extract_clickable_candidates(html: str) -> list[dict[str, str]]:
    """Extract simple clickable hints from static HTML.

    This is a helper for offline analysis only. Real clicks are executed by Playwright.
    """

    parser = _ClickableCandidateParser()
    parser.feed(str(html or ""))
    parser.close()
    return parser.candidates
