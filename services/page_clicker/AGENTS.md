# PAGE CLICKER KNOWLEDGE BASE

## OVERVIEW
Independent click-automation tool with two backends: Playwright for DOM/web flows and PyAutoGUI for foreground desktop flows. This is not a generic helper; it is a bounded subsystem with explicit safety rules.

## WHERE TO LOOK
| Task | Location | Notes |
|---|---|---|
| CLI entry | `__main__.py` | `python -m services.page_clicker ...` |
| Config / models | `config.py`, `models.py` | validates CLI and backend options |
| Orchestration | `runner.py` | backend selection and error normalization |
| Backend contract / implementations | `backends/` | `base.py`, `factory.py`, `playwright_backend.py`, `pyautogui_backend.py` |
| Static HTML analysis | `dom.py` | analysis helper only; not an execution backend |
| Demo | `demo/local_click.html` | local Playwright demo target |
| Tests | `../../tests/test_page_clicker_*.py` | runtime, config, DOM, backend coverage |

## CONVENTIONS
- CLI returns unified JSON results across both backends.
- Playwright backend is for real webpages, selectors, text targets, metadata, and browser screenshots.
- PyAutoGUI backend is for active desktop sessions, screen coordinates, image matching, and desktop screenshots.
- `human` mode means pacing/movement/protection choices; it is not an anti-detection feature.
- PyAutoGUI requires explicit `--allow-gui-control true` and keeps safety rails such as FailSafe and no blind clicking.

## ANTI-PATTERNS
- Do not describe or extend this tool as a detection-bypass, fingerprint-spoofing, or risk-control-evasion surface.
- Do not assume PyAutoGUI can run like headless Playwright.
- Do not use `dom.py` as if it performs real clicks.
- Do not bypass the explicit GUI-control guard when touching PyAutoGUI flows.

## COMMANDS
```bash
python -m services.page_clicker --backend playwright --demo local-click --target-css "#start-button"
python -m services.page_clicker --backend playwright --url "https://example.com" --target-text "Continue"
python -m services.page_clicker --backend pyautogui --target-point "640,480" --allow-gui-control true
```

## NOTES
- Read `README.md` here before changing behavior; it already captures the subsystem’s scope and guardrails well.
- Key tests: `test_page_clicker_config.py`, `test_page_clicker_dom.py`, `test_page_clicker_playwright_backend.py`, `test_page_clicker_pyautogui_backend.py`, `test_page_clicker_runner.py`, `test_page_clicker_runtime.py`.
