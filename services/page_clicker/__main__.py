from __future__ import annotations

import json
import sys

from .config import build_config_from_args, build_parser
from .runner import run_click_flow


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        config = build_config_from_args(args)
    except ValueError as exc:
        print(f"[page_clicker] 参数错误: {exc}", file=sys.stderr)
        return 2

    result = run_click_flow(config)
    payload = {
        "success": result.success,
        "backend": result.backend,
        "url": result.url,
        "target_kind": result.target_kind,
        "target_value": result.target_value,
        "final_url": result.final_url,
        "title": result.title,
        "clicked_text": result.clicked_text,
        "clicked_position": result.clicked_position,
        "screenshot_path": str(result.screenshot_path) if result.screenshot_path else None,
        "error": result.error,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
