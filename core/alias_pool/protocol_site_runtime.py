from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Iterable, Protocol

from core.http_client import HTTPClient


@dataclass(frozen=True)
class ProtocolRuntimeResponse:
    status_code: int
    url: str
    text: str
    headers: dict[str, Any] = field(default_factory=dict)


class _HiddenInputParser(HTMLParser):
    def __init__(self, names: set[str]):
        super().__init__()
        self._names = names
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "input":
            return
        attr_map = {key: value or "" for key, value in attrs}
        if attr_map.get("type", "").lower() != "hidden":
            return
        name = str(attr_map.get("name") or "").strip()
        if name in self._names:
            self.values[name] = str(attr_map.get("value") or "")


class _HttpClientLike(Protocol):
    def get(self, url: str, **kwargs) -> Any: ...

    def post(self, url: str, data: Any = None, json: Any = None, **kwargs) -> Any: ...


class ProtocolSiteRuntime:
    def __init__(self, *, client: _HttpClientLike | None = None):
        self._client = client or HTTPClient()
        self._last_url = ""

    def _build_response(self, response: Any, fallback_url: str) -> ProtocolRuntimeResponse:
        self._last_url = str(getattr(response, "url", fallback_url) or fallback_url)
        return ProtocolRuntimeResponse(
            status_code=int(getattr(response, "status_code", 0) or 0),
            url=self._last_url,
            text=str(getattr(response, "text", "") or ""),
            headers=dict(getattr(response, "headers", {}) or {}),
        )

    def get(self, url: str, **kwargs) -> ProtocolRuntimeResponse:
        return self._build_response(self._client.get(url, **kwargs), url)

    def post_form(self, url: str, data: dict[str, Any], **kwargs) -> ProtocolRuntimeResponse:
        return self._build_response(self._client.post(url, data=data, **kwargs), url)

    def post_json(self, url: str, payload: dict[str, Any], **kwargs) -> ProtocolRuntimeResponse:
        return self._build_response(self._client.post(url, json=payload, **kwargs), url)

    def export_cookies(self) -> list[dict[str, Any]]:
        session = getattr(self._client, "session", None)
        cookies = getattr(session, "cookies", None)
        if cookies is None:
            return []
        try:
            iterator = iter(cookies)
        except TypeError:
            return []
        result: list[dict[str, Any]] = []
        for cookie in iterator:
            result.append({"name": cookie.name, "value": cookie.value})
        return result

    def extract_hidden_inputs(self, html: str, *, names: Iterable[str]) -> dict[str, str]:
        parser = _HiddenInputParser(set(names))
        parser.feed(str(html or ""))
        return dict(parser.values)
