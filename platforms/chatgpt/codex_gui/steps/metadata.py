from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class StepMetadata:
    """描述一个 GUI 步骤的语义信息与来源映射。"""

    step_id: str
    stage_name: str
    intent: str
    legacy_mapping: str
    expected_url_fragment: str = ""
    expected_targets: tuple[str, ...] = field(default_factory=tuple)
