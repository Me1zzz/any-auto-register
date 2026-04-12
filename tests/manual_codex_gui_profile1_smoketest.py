import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from platforms.chatgpt.codex_gui_driver import PyAutoGUICodexGUIDriver


def _log(message: str) -> None:
    print(message)


def main() -> None:
    driver = PyAutoGUICodexGUIDriver(
        extra_config={
            "codex_gui_edge_command": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            "codex_gui_edge_user_data_dir": r"C:\Users\M\AppData\Local\Microsoft\Edge\User Data",
            "codex_gui_edge_profile_directory": "Profile 1",
            "codex_gui_edge_snapshot_profile": True,
            "codex_gui_edge_startup_url": "https://auth.openai.com/log-in",
            "codex_gui_dom_timeout_ms": 30000,
        },
        logger_fn=_log,
    )

    try:
        driver.open_url("https://auth.openai.com/log-in", reuse_current=False)
        time.sleep(2)
        current_url = driver.read_current_url()
        print(f"[SMOKETEST] current_url={current_url}")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
