from __future__ import annotations

from dataclasses import dataclass
import json
import random
import threading
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import quote

import requests


DEFAULT_PROXY_SWITCH_BASE_URL = "http://127.0.0.1:9097"
_SWITCH_LOCK = threading.Lock()


@dataclass(frozen=True)
class ProxySwitchResult:
    ok: bool
    reason: str = ""
    proxy_name: str = ""
    node_name: str = ""
    status_code: int = 0


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on", "enabled", "enable", "开启", "开"}


def _parse_node_names(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        text = str(value or "").strip()
        if not text:
            return []
        raw_items: list[Any]
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            raw_items = parsed
        else:
            raw_items = []
            for line in text.splitlines():
                raw_items.extend(line.split(","))

    nodes: list[str] = []
    seen = set()
    for item in raw_items:
        name = str(item or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        nodes.append(name)
    return nodes


def _format_requests_put_expression(url: str, node_name: str) -> str:
    payload = json.dumps({"name": node_name}, ensure_ascii=False)
    return (
        f"requests.put({url!r}, "
        "headers={'Content-Type': 'application/json', \"Authorization\": f\"Bearer token\"}, "
        f"json={payload})"
    )


def switch_proxy_after_account(
    config: Mapping[str, Any],
    *,
    log_fn: Callable[[str], None],
    request_put: Callable[..., Any] | None = None,
    chooser: Callable[[Sequence[str]], str] | None = None,
    timeout: int = 10,
) -> ProxySwitchResult:
    if not _parse_bool(config.get("cloudmail_proxy_switch_enabled")):
        return ProxySwitchResult(ok=False, reason="disabled")

    proxy_name = str(config.get("cloudmail_proxy_switch_proxy_name") or "").strip()
    token = str(config.get("cloudmail_proxy_switch_token") or "").strip()
    nodes = _parse_node_names(config.get("cloudmail_proxy_switch_nodes"))

    if not proxy_name:
        log_fn("[ProxySwitch] 跳过代理切换: proxy_name 为空")
        return ProxySwitchResult(ok=False, reason="missing_config")
    if not token or not nodes:
        log_fn("[ProxySwitch] 跳过代理切换: token 或节点列表为空")
        return ProxySwitchResult(ok=False, reason="missing_config", proxy_name=proxy_name)

    select_node = chooser or random.choice
    node_name = str(select_node(nodes) or "").strip()
    if not node_name:
        log_fn("[ProxySwitch] 跳过代理切换: 随机节点为空")
        return ProxySwitchResult(ok=False, reason="missing_config", proxy_name=proxy_name)

    request_put = request_put or requests.put
    url = f"{DEFAULT_PROXY_SWITCH_BASE_URL}/proxies/{quote(proxy_name, safe='')}"
    log_fn(_format_requests_put_expression(url, node_name))

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    try:
        with _SWITCH_LOCK:
            response = request_put(
                url,
                headers=headers,
                json={"name": node_name},
                timeout=timeout,
            )
    except Exception as exc:
        log_fn(f"[ProxySwitch] 代理切换失败: {exc}")
        return ProxySwitchResult(
            ok=False,
            reason=str(exc),
            proxy_name=proxy_name,
            node_name=node_name,
        )

    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code >= 400:
        body = str(getattr(response, "text", "") or "").strip()
        if body:
            body = body[:200]
            log_fn(f"[ProxySwitch] 代理切换失败: HTTP {status_code} {body}")
        else:
            log_fn(f"[ProxySwitch] 代理切换失败: HTTP {status_code}")
        return ProxySwitchResult(
            ok=False,
            reason=f"HTTP {status_code}",
            proxy_name=proxy_name,
            node_name=node_name,
            status_code=status_code,
        )

    log_fn(f"[ProxySwitch] 代理切换成功: {proxy_name} -> {node_name}")
    return ProxySwitchResult(
        ok=True,
        proxy_name=proxy_name,
        node_name=node_name,
        status_code=status_code,
    )
