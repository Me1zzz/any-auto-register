from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RenameRule:
    prefix_to_add: str
    priority: int
    startswith_any: tuple[str, ...] = ()
    contains_any: tuple[str, ...] = ()

    def matches(self, file_name: str) -> bool:
        startswith_match = any(file_name.startswith(prefix) for prefix in self.startswith_any)
        contains_match = any(keyword in file_name for keyword in self.contains_any)
        return startswith_match or contains_match


def pick_rule(file_name: str, rules: list[RenameRule]) -> RenameRule | None:
    for rule in sorted(rules, key=lambda item: item.priority, reverse=True):
        if rule.matches(file_name):
            return rule
    return None


def rename_files(
    folder_path: str,
    rules: list[RenameRule] | None = None,
    old_prefix: str = "xxx（占位）",
    new_prefix: str = "zzz（占位）",
) -> None:
    folder = Path(folder_path)

    if not folder.exists() or not folder.is_dir():
        print(f"目录不存在或不是有效目录: {folder}")
        return

    effective_rules = rules or [
        RenameRule(prefix_to_add=new_prefix, priority=1, startswith_any=(old_prefix,)),
    ]

    for file in folder.iterdir():
        if not file.is_file():
            continue

        matched_rule = pick_rule(file.name, effective_rules)
        if matched_rule is None:
            continue

        if file.name.startswith(matched_rule.prefix_to_add):
            print(f"跳过，文件已带此前缀: {file.name}")
            continue

        new_name = matched_rule.prefix_to_add + file.name
        new_path = file.with_name(new_name)

        if new_path.exists():
            print(f"跳过，目标文件已存在: {new_path.name}")
            continue

        file.rename(new_path)
        print(
            f"已重命名(优先级 {matched_rule.priority}): {file.name} -> {new_path.name}"
        )


if __name__ == "__main__":
    target_folder = r"C:\Users\M\.cli-proxy-api"
    rename_rules = [
        RenameRule(
            prefix_to_add="00000",
            priority=100,
            contains_any=("me1zzz.tech", "tempforward.com"),
        ),
        RenameRule(
            prefix_to_add="zzz",
            priority=10,
            startswith_any=("codex",),
        ),
    ]
    rename_files(target_folder, rules=rename_rules)
