# CHATGPT PLATFORM KNOWLEDGE BASE

## OVERVIEW
Largest and most specialized platform subtree in the repo. This directory mixes protocol registration, refresh-token and access-token flows, GUI/Codex registration, browser/session handling, status probing, payment checks, and external upload helpers.

## WHERE TO LOOK
| Task | Location | Notes |
|---|---|---|
| Plugin boundary | `plugin.py` | `ChatGPTPlatform` wires mailbox handling and mode adapter selection |
| Registration mode routing | `chatgpt_registration_mode_adapter.py` | decides which flow implementation runs |
| Protocol / OAuth-heavy flow | `oauth_client.py`, `oauth.py`, `oauth_pkce_client.py` | largest logic surface in subtree |
| Refresh-token flow | `refresh_token_registration_engine.py` | tested heavily from `tests/test_chatgpt_register.py` |
| Access-token-only flow | `access_token_only_registration_engine.py` | legacy/alternate path |
| GUI / Codex flow | `codex_gui_registration_engine.py`, `codex_gui_driver.py`, `gui_controller.py`, `target_detector.py` | headed interaction path |
| Session / browser / sentinel helpers | `browser_session.py`, `sentinel_browser.py`, `sentinel_token.py`, `sentinel_batch.py` | browser/session management |
| Status / payment / uploads | `status_probe.py`, `payment.py`, `cpa_upload.py`, `sub2api_upload.py` | post-registration state and external integration |

## CONVENTIONS
- `plugin.py` is the stable entry; most call paths fan out from `build_chatgpt_registration_mode_adapter(...)`.
- Registration mode defaults to `refresh_token`; the adapter also still honors the legacy boolean flag `chatgpt_has_refresh_token_solution`.
- Mailbox timeout and registration mode are influenced by `extra_config`; inspect adapter/context wiring before changing flow details.
- This subtree spans protocol, browser, and GUI modes. Always identify which mode you are touching before editing.
- Tests in `tests/` are the quickest way to learn expected behavior for retries, login fallback, token capture, and mode adaptation.

## ANTI-PATTERNS
- Do not treat this subtree as a typical small platform plugin.
- Do not make parent-level `platforms/` docs carry ChatGPT-only rules.
- Do not change GUI/Codex behavior as if it were headless/protocol behavior; those paths have different assumptions and failure modes.
- Do not start with `oauth_client.py` alone for every task; first locate the active mode and then read only the relevant engine + adapter path.

## NOTES
- `oauth_client.py` is the main knowledge bottleneck and one of the largest hotspots in this subtree.
- `codex_gui_config.json` is a local artifact/config surface tied to GUI registration.
- Relevant tests include `test_chatgpt_register.py`, `test_chatgpt_registration_mode_adapter.py`, `test_codex_gui_registration_engine.py`, `test_chatgpt_status_probe.py`, and related upload/sync tests.
