from __future__ import annotations

import argparse
import os
from pathlib import Path

from .models import PageClickConfig, PlaywrightOptions, PyAutoGUIOptions, TargetSpec

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


def parse_int_tuple(raw: str, expected_length: int, label: str) -> tuple[int, ...]:
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != expected_length:
        raise ValueError(f"{label} 格式必须为 {expected_length} 个逗号分隔整数")
    try:
        return tuple(int(part) for part in parts)
    except ValueError as exc:
        raise ValueError(f"{label} 必须全部为整数") from exc


def parse_point(raw: str, label: str) -> tuple[int, int]:
    x, y = parse_int_tuple(raw, 2, label)
    return x, y


def parse_region(raw: str, label: str) -> tuple[int, int, int, int]:
    x, y, width, height = parse_int_tuple(raw, 4, label)
    return x, y, width, height


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="双后端页面自动点击框架")
    parser.add_argument("--backend", choices=["playwright", "pyautogui"], default="playwright")
    parser.add_argument("--click-mode", choices=["direct", "human"], default="direct")
    parser.add_argument("--timeout-ms", type=int, default=10_000, help="等待与点击超时时间（毫秒）")
    parser.add_argument("--screenshot-path", help="可选截图输出路径")

    parser.add_argument("--url", help="Playwright 后端目标页面 URL")
    parser.add_argument("--demo", choices=["local-click"], help="运行内置 Playwright 示例页面")
    parser.add_argument("--target-css", help="Playwright 使用的 CSS 目标")
    parser.add_argument("--click-selector", help="兼容旧参数，等价于 --target-css")
    parser.add_argument("--target-text", help="Playwright 使用的文本目标")
    parser.add_argument("--wait-css", help="Playwright 点击前等待的 CSS 目标")
    parser.add_argument("--wait-text", help="Playwright 点击前等待的文本目标")
    parser.add_argument("--headless", choices=["true", "false"], help="Playwright 是否无头运行")

    parser.add_argument("--target-image", help="PyAutoGUI 用于图像定位的文件路径")
    parser.add_argument("--target-point", help="PyAutoGUI 用于直接点击的屏幕坐标，格式 X,Y")
    parser.add_argument("--region", help="PyAutoGUI 定位搜索区域，格式 X,Y,W,H")
    parser.add_argument("--locate-confidence", type=float, help="PyAutoGUI 图像定位置信度")
    parser.add_argument("--move-duration-ms", type=int, default=200, help="PyAutoGUI 鼠标移动时长")
    parser.add_argument("--pre-click-delay-ms", type=int, default=100, help="PyAutoGUI 点击前停顿")
    parser.add_argument("--post-click-delay-ms", type=int, default=150, help="PyAutoGUI 点击后停顿")
    parser.add_argument("--failsafe", choices=["true", "false"], default="true", help="PyAutoGUI 是否启用 FailSafe")
    parser.add_argument(
        "--allow-gui-control",
        choices=["true", "false"],
        default="false",
        help="明确授权 PyAutoGUI 控制本机屏幕",
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


def _build_playwright_target(args: argparse.Namespace) -> TargetSpec:
    css_target = args.target_css or args.click_selector
    text_target = args.target_text
    configured = [name for name, value in (("css", css_target), ("text", text_target)) if value]
    if len(configured) != 1:
        raise ValueError("Playwright 后端必须且只能提供一个目标：--target-css/--click-selector 或 --target-text")

    if css_target:
        return TargetSpec(kind="css", value=css_target)
    return TargetSpec(kind="text", value=text_target)


def _build_playwright_wait_target(args: argparse.Namespace, fallback_target: TargetSpec) -> TargetSpec:
    configured = [name for name, value in (("css", args.wait_css), ("text", args.wait_text)) if value]
    if len(configured) > 1:
        raise ValueError("Playwright 等待目标只能配置一个：--wait-css 或 --wait-text")
    if args.wait_css:
        return TargetSpec(kind="css", value=args.wait_css)
    if args.wait_text:
        return TargetSpec(kind="text", value=args.wait_text)
    return fallback_target


def _build_playwright_config(args: argparse.Namespace, screenshot_path: Path | None) -> PageClickConfig:
    if args.target_image or args.target_point or args.region or args.locate_confidence is not None:
        raise ValueError("Playwright 后端不能使用 PyAutoGUI 专属参数")

    url = args.url
    if args.demo:
        url = build_demo_url(args.demo)
    if not url:
        raise ValueError("Playwright 后端必须提供 --url 或 --demo")

    target = _build_playwright_target(args)
    wait_target = _build_playwright_wait_target(args, target)
    return PageClickConfig(
        backend="playwright",
        click_mode=args.click_mode,
        timeout_ms=args.timeout_ms,
        screenshot_path=screenshot_path,
        target=target,
        playwright=PlaywrightOptions(
            url=url,
            wait_target=wait_target,
            headless=resolve_headless(args.headless),
            demo_name=args.demo,
        ),
    )


def _build_pyautogui_config(args: argparse.Namespace, screenshot_path: Path | None) -> PageClickConfig:
    if args.url or args.demo or args.target_css or args.click_selector or args.target_text or args.wait_css or args.wait_text:
        raise ValueError("PyAutoGUI 后端不能使用 Playwright 专属参数")
    if args.headless is not None:
        raise ValueError("PyAutoGUI 后端不支持 --headless")

    allow_gui_control = parse_optional_bool(args.allow_gui_control)
    if allow_gui_control is not True:
        raise ValueError("PyAutoGUI 后端必须显式传入 --allow-gui-control true")

    target_image = args.target_image
    target_point = args.target_point
    if bool(target_image) == bool(target_point):
        raise ValueError("PyAutoGUI 后端必须且只能提供一个目标：--target-image 或 --target-point")

    region = parse_region(args.region, "--region") if args.region else None
    if target_image:
        target = TargetSpec(kind="image", value=str(Path(target_image).resolve()), region=region)
        pyautogui_options = PyAutoGUIOptions(
            image_path=Path(target_image).resolve(),
            region=region,
            confidence=args.locate_confidence,
            move_duration_ms=args.move_duration_ms,
            pre_click_delay_ms=args.pre_click_delay_ms,
            post_click_delay_ms=args.post_click_delay_ms,
            failsafe=parse_optional_bool(args.failsafe) is not False,
            allow_gui_control=True,
        )
    else:
        x, y = parse_point(target_point, "--target-point")
        target = TargetSpec(kind="point", x=x, y=y, region=region)
        pyautogui_options = PyAutoGUIOptions(
            point=(x, y),
            region=region,
            confidence=args.locate_confidence,
            move_duration_ms=args.move_duration_ms,
            pre_click_delay_ms=args.pre_click_delay_ms,
            post_click_delay_ms=args.post_click_delay_ms,
            failsafe=parse_optional_bool(args.failsafe) is not False,
            allow_gui_control=True,
        )

    return PageClickConfig(
        backend="pyautogui",
        click_mode=args.click_mode,
        timeout_ms=args.timeout_ms,
        screenshot_path=screenshot_path,
        target=target,
        pyautogui=pyautogui_options,
    )


def build_config_from_args(args: argparse.Namespace) -> PageClickConfig:
    if args.timeout_ms <= 0:
        raise ValueError("--timeout-ms 必须大于 0")

    screenshot_path = Path(args.screenshot_path).resolve() if args.screenshot_path else None
    if args.backend == "playwright":
        return _build_playwright_config(args, screenshot_path)
    return _build_pyautogui_config(args, screenshot_path)
