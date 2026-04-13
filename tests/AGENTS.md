# TESTS KNOWLEDGE BASE

## OVERVIEW
Repository test suite is mostly file-oriented `unittest` plus `unittest.mock`. Automated tests and manual smoke/fullrun scripts live side by side.

## WHERE TO LOOK
| Task | Location | Notes |
|---|---|---|
| Task runtime / control behavior | `test_register_task_controls.py`, `test_task_runtime.py` | backend orchestration expectations |
| ChatGPT registration flows | `test_chatgpt_register.py`, `test_chatgpt_registration_mode_adapter.py`, `test_codex_gui_registration_engine.py` | covers retries, mode adaptation, GUI path |
| Sync / status behavior | `test_chatgpt_sync.py`, `test_chatgpt_status_probe.py`, `test_chatgpt_account_state.py` | post-registration state surfaces |
| Page clicker | `test_page_clicker_*.py` | config, DOM, runtime, both backends |
| Manual scripts | `manual_codex_gui_profile1_smoketest.py`, `manual_codex_gui_profile1_fullrun.py` | not part of normal automated test loop |

## CONVENTIONS
- Use `unittest` style unless a specific file shows otherwise.
- `unittest.mock` is the normal dependency-isolation mechanism.
- Some tests stub optional dependencies (`curl_cffi`, `smstome_tool`, Playwright/PyAutoGUI import failures) rather than requiring full runtime setup.
- Read the relevant test file before changing flow-heavy code; tests double as behavior documentation here.

## ANTI-PATTERNS
- Do not assume pytest fixtures, pytest markers, or pytest config exist.
- Do not treat `manual_*` scripts as automated regression coverage.
- Do not assume the manual Codex GUI scripts are portable; they hard-code a local Windows Edge profile path.
- Do not infer subtree rules from one test file alone; this suite is domain-clustered by feature.

## NOTES
- `test_chatgpt_register.py` is a strong entry point for understanding retry/login fallback expectations in ChatGPT flows.
- `test_page_clicker_runtime.py` documents expected error handling when optional backend dependencies are missing.
- `manual_codex_gui_profile1_smoketest.py` and `manual_codex_gui_profile1_fullrun.py` are machine/profile-specific smoke helpers, not reusable general test entrypoints.
