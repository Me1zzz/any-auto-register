from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CodexGUIIdentity:
    """描述当前 GUI 注册流程中生成出的账号身份信息。"""

    email: str
    password: str
    full_name: str
    age: int
    service_id: str = ""


@dataclass(slots=True)
class FlowStepResult:
    """描述单个步骤执行完成后的结果快照。"""

    success: bool = True
    stage_name: str = ""
    matched_url: str = ""
    matched_marker: str = ""
    terminal_state: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
