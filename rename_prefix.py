from pathlib import Path


def rename_files(folder_path: str, old_prefix: str = "xxx（占位）", new_prefix: str = "zzz（占位）") -> None:
    folder = Path(folder_path)

    if not folder.exists() or not folder.is_dir():
        print(f"目录不存在或不是有效目录: {folder}")
        return

    for file in folder.iterdir():
        if file.is_file() and file.name.startswith(old_prefix):
            new_name = new_prefix + file.name
            new_path = file.with_name(new_name)

            if new_path.exists():
                print(f"跳过，目标文件已存在: {new_path.name}")
                continue

            file.rename(new_path)
            print(f"已重命名: {file.name} -> {new_path.name}")


if __name__ == "__main__":
    target_folder = r"C:\Users\M\.cli-proxy-api"
    rename_files(target_folder, 'codex', 'zzz')
