from __future__ import annotations

from .backends.factory import build_backend
from .models import ClickResult, PageClickConfig


def _target_value(config: PageClickConfig) -> str | None:
    target = config.target
    if target is None:
        return None
    if target.value is not None:
        return target.value
    if target.x is not None and target.y is not None:
        return f"{target.x},{target.y}"
    return None


def run_click_flow(config: PageClickConfig) -> ClickResult:
    try:
        backend = build_backend(config)
        return backend.run(config)
    except Exception as exc:
        error_type = exc.__class__.__name__
        url = config.playwright.url if config.playwright is not None else None
        target = config.target
        return ClickResult(
            success=False,
            backend=config.backend,
            url=url,
            target_kind=target.kind if target else None,
            target_value=_target_value(config),
            screenshot_path=config.screenshot_path,
            error=f"{error_type}: {exc}",
        )
