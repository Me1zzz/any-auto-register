import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.tasks import RegisterTaskRequest, _create_task_record, _run_register, _task_store  # noqa: E402
import platforms.chatgpt.plugin  # noqa: F401,E402


def main() -> None:
    req = RegisterTaskRequest(
        platform="chatgpt",
        count=1,
        concurrency=1,
        register_delay_seconds=0,
        proxy=None,
        executor_type="headed",
        captcha_solver="manual",
        extra={
            "chatgpt_registration_mode": "codex_gui",
            "codex_gui_edge_user_data_dir": r"C:\Users\M\AppData\Local\Microsoft\Edge\User Data",
            "codex_gui_edge_profile_directory": "Profile 1",
            "codex_gui_edge_snapshot_profile": True,
        },
    )
    task_id = "manual_codex_gui_profile1"
    _create_task_record(task_id, req, "manual-script", None)
    _run_register(task_id, req)
    snapshot = _task_store.snapshot(task_id)
    print("\n===== TASK SNAPSHOT =====")
    print(snapshot)


if __name__ == "__main__":
    main()
