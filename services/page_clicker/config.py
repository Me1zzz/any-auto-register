from __future__ import annotations

import argparse
import os
from pathlib import Path

from .models import PageClickConfig

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def parse_optional_bool(value: str | bool | None) -> bool | None:
    if value is None or isinstance(value, bool):
        return value

    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(f"无效的布尔值: {value}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="基于 Playwright 的页面自动点击框架")
    parser.add_argument("--url", help="目标页面 URL")
    parser.add_argument(
        "--click-selector",
        default="#start-button",
        help="点击目标的 CSS selector",
    )
    parser.add_argument(
        "--wait-for-selector",
        help="点击前等待出现的 selector，默认回退到 click selector",
    )
    parser.add_argument(
        "--headless",
        choices=["true", "false"],
        help="是否无头运行；未传时可由环境变量控制",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=10_000,
        help="等待与点击超时时间（毫秒）",
    )
    parser.add_argument("--screenshot-path", help="可选截图输出路径")
    parser.add_argument(
        "--demo",
        choices=["local-click"],
        help="运行内置本地示例页面",
    )
    return parser


def build_demo_url(demo_name: str) -> str:
    if demo_name != "local-click":
        raise ValueError(f"不支持的 demo: {demo_name}")

    html_path = Path(__file__).resolve().parent / "demo" / "local_click.html"
    return html_path.as_uri()


def resolve_headless(cli_value: str | None) -> bool | None:
    if cli_value is not None:
        return parse_optional_bool(cli_value)

    for env_name in ("AUTOCLICK_HEADLESS", "PLAYWRIGHT_HEADLESS"):
        env_value = os.getenv(env_name)
        parsed = parse_optional_bool(env_value)
        if parsed is not None:
            return parsed
    return None


def build_config_from_args(args: argparse.Namespace) -> PageClickConfig:
    url = args.url
    if args.demo:
        url = build_demo_url(args.demo)

    if not url:
        raise ValueError("必须提供 --url 或 --demo")
    if not args.click_selector:
        raise ValueError("必须提供 --click-selector")
    if args.timeout_ms <= 0:
        raise ValueError("--timeout-ms 必须大于 0")

    screenshot_path = Path(args.screenshot_path).resolve() if args.screenshot_path else None
    wait_for_selector = args.wait_for_selector or args.click_selector
    return PageClickConfig(
        url=url,
        click_selector=args.click_selector,
        wait_for_selector=wait_for_selector,
        headless=resolve_headless(args.headless),
        timeout_ms=args.timeout_ms,
        screenshot_path=screenshot_path,
    )
