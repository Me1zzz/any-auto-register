# SERVICES KNOWLEDGE BASE

## OVERVIEW
Mixed operational layer: some files are simple service helpers, others are standalone subsystems with their own CLI/runtime boundaries.

## WHERE TO LOOK
| Task | Location | Notes |
|---|---|---|
| External app install/start logic | `external_apps.py` | cross-cutting operational hub |
| External sync / uploads | `external_sync.py`, `chatgpt_sync.py`, `cliproxyapi_sync.py` | integration surfaces |
| Solver lifecycle bridge | `solver_manager.py` | root service hook used by `main.py` |
| Mail import extension package | `mail_imports/` | provider/registry/schema split |
| Click automation tool | `page_clicker/` | standalone subsystem; read local AGENTS |
| Turnstile solver runtime | `turnstile_solver/` | separate runtime package with its own start script |

## CONVENTIONS
- Do not assume all children are interchangeable helpers. `page_clicker`, `mail_imports`, and `turnstile_solver` each have their own internal boundaries.
- `external_apps.py` is the first place to check when repo docs mention external Git mirrors, cloned tools, or host-managed services.
- Local service behavior can be Windows/host-environment-sensitive; read the docs and startup scripts before normalizing everything into Docker-only assumptions.

## ANTI-PATTERNS
- Do not flatten this directory into a generic “service layer” in documentation.
- Do not document solver, page-clicker, and mail-import flows as one subsystem.
- Do not add a child AGENTS for `turnstile_solver/` or `mail_imports/` unless a future task needs rules beyond what this file already captures.

## NOTES
- `external_logs/` is runtime output, not source guidance.
- `page_clicker/` already has a strong README and now also has local AGENTS guidance because its local rules materially differ from the parent.
- `turnstile_solver/` is a standalone runtime package with its own entrypoint/dependency shape; `mail_imports/` is a provider-registry surface where registry aliases `outlook` to `microsoft`.
