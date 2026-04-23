from __future__ import annotations

from core.alias_pool.provider_contracts import AliasProviderCapture


def build_runtime_capture(
    kind: str,
    *,
    url: str = "",
    method: str = "",
    request_body_excerpt: str = "",
) -> AliasProviderCapture:
    return AliasProviderCapture(
        kind=kind,
        request_summary={
            "url": url,
            "method": method,
            "request_body_excerpt": request_body_excerpt,
        },
        response_summary={},
    )
