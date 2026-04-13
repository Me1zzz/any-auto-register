# PROJECT KNOWLEDGE BASE

**Generated:** 2026-04-13 Asia/Shanghai
**Commit:** `8c097f4`
**Branch:** `me1zzz-main`

## OVERVIEW
Multi-platform account registration and management system. Root app is FastAPI + SQLite/SQLModel; frontend is React + TypeScript + Vite; selected automation flows use Playwright/Camoufox and related local services.

## STRUCTURE
```text
any-auto-register/
├── api/             # FastAPI routers; tasks/accounts are orchestration-heavy
├── core/            # shared runtime, registry, DB, scheduler, mailbox/proxy primitives
├── electron/        # separate Electron package and desktop packaging lane
├── frontend/        # separate Vite/React package; production build emits into ../static
├── platforms/       # plugin root; each platform provides its own plugin/core pair or richer subtree
├── services/        # mixed service layer plus standalone subsystems
├── static/          # built frontend artifacts served by FastAPI
├── tests/           # unittest-style tests plus a few manual smoke/fullrun scripts
├── main.py          # backend composition root and SPA host
└── start_backend.ps1/.bat  # preferred Windows launch path
```

## WHERE TO LOOK
| Task | Location | Notes |
|---|---|---|
| App startup / shutdown | `main.py` | initializes DB, platform registry, scheduler, solver, SPA fallback |
| Add or change API route | `api/` | `api/tasks.py` and `api/accounts.py` are the busiest surfaces |
| Platform registration behavior | `platforms/` | plugin architecture; `core/registry.py` auto-loads `*/plugin.py` |
| ChatGPT-specific flow | `platforms/chatgpt/` | separate subsystem; read local AGENTS first |
| Shared runtime / task control | `core/` | task lifecycle and execution primitives live here |
| External tools / solver / sync helpers | `services/` | mixed service layer; some subdirs are runnable subsystems |
| Frontend pages and request shaping | `frontend/src/` | page containers under `pages/`, helpers under `lib/`, hooks under `hooks/` |
| Desktop packaging | `electron/` | separate Node package; not part of normal web dev loop |
| Test coverage | `tests/` | `unittest` + `unittest.mock`; manual scripts live beside automated tests |

## CODE MAP
| Symbol / Surface | Location | Role |
|---|---|---|
| `app = FastAPI(...)` | `main.py` | repo composition root |
| `load_all()` | `core/registry.py` | auto-loads platform plugins from `platforms/*/plugin.py` |
| `enqueue_register_task()` / `_run_register()` | `api/tasks.py` | registration orchestration entry path |
| `ChatGPTPlatform` | `platforms/chatgpt/plugin.py` | ChatGPT plugin boundary |
| `Accounts.tsx` | `frontend/src/pages/Accounts.tsx` | largest account-management UI surface |
| `RegisterTaskPage.tsx` | `frontend/src/pages/RegisterTaskPage.tsx` | registration-task UI orchestration |
| `external_apps.py` | `services/external_apps.py` | external service/plugin control plane |

## CONVENTIONS
- Preferred local startup on Windows is `start_backend.ps1` or `start_backend.bat`, not ad hoc Python invocation.
- Expected conda environment is `any-auto-register`; docs and troubleshooting assume that exact name.
- Frontend production build goes to `../static`; backend serves built assets from port `8000`.
- Frontend dev mode is split: backend on `8000`, Vite on `5173`, `/api` proxied by Vite.
- React frontend uses `@/` alias for `frontend/src/*`.
- Frontend TypeScript is strict; unused locals/params are errors.
- Frontend linting is intentionally light. No checked-in Prettier, `.editorconfig`, or repo-wide formatter config.
- Tests are plain `unittest`-style files under `tests/`; do not assume pytest config exists.
- Docker and local runtime both treat the solver as a first-class integrated service.

## ANTI-PATTERNS (THIS PROJECT)
- Do not document or implement this repo as CI-driven; there is no checked-in GitHub Actions or repo-wide task runner.
- Do not treat `frontend/README.md` as project truth; it is the default Vite template and mostly boilerplate.
- Do not add global ignore rules for docs images/HTML casually; repo assets are intentionally committed.
- Do not use `services/page_clicker` as a detection-bypass surface; local child guidance is explicit about that boundary.
- Do not assume `services/` is one uniform layer; several subtrees are standalone subsystems with their own rules.
- Do not assume every platform under `platforms/` is symmetric; `platforms/chatgpt/` is much deeper than the rest.

## UNIQUE STYLES
- Python backend code is spread across root-level domain folders (`api`, `core`, `platforms`, `services`) rather than a single `src/` package.
- Electron, frontend, and backend are sibling runtimes, not one workspace-managed monorepo.
- Runtime artifacts and operator scripts live near source; separate code from generated/log/runtime state when navigating.

## COMMANDS
```bash
# backend setup
pip install -r requirements.txt
python -m playwright install chromium
python -m camoufox fetch

# preferred backend start / stop on Windows
.\start_backend.ps1
.\stop_backend.ps1

# manual backend start
python main.py

# frontend
cd frontend
npm install
npm run dev
npm run build
npm run lint

# docker
docker compose up -d --build
docker compose logs -f app
docker compose down
```

## NOTES
- `main.py` serves SPA assets only when `./static` exists.
- Electron dev expects the backend to already be running; packaged Electron has a separate build path.
- `tests/` contains both automated tests and manual smoke/fullrun scripts; check the filename before assuming automation.
- Child AGENTS files exist only where local guidance materially changes behavior.
