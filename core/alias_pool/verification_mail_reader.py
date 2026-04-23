from __future__ import annotations

import re


def extract_first_http_link(body: str) -> str:
    match = re.search(r"https?://[^\s'\"]+", str(body or ""))
    return match.group(0) if match else ""
