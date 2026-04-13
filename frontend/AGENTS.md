# FRONTEND KNOWLEDGE BASE

## OVERVIEW
Separate Vite + React + TypeScript package. Source lives under `frontend/src`; production build is emitted into root `static/` for FastAPI to serve.

## WHERE TO LOOK
| Task | Location | Notes |
|---|---|---|
| Frontend bootstrap | `src/main.tsx`, `src/App.tsx` | app mount and top-level shell |
| Main page containers | `src/pages/` | `Accounts.tsx` and `RegisterTaskPage.tsx` are the largest surfaces |
| Shared UI pieces | `src/components/` | settings-related controls have their own nested subtree |
| Client-side request / mode helpers | `src/lib/` | contains ChatGPT registration-mode helpers/adapters |
| Persistent UI state | `src/hooks/` | local hooks such as registration-mode persistence |
| Frontend tooling | `package.json`, `vite.config.ts`, `tsconfig*.json`, `eslint.config.js` | source of actual workflow conventions |

## CONVENTIONS
- `npm run build` runs `tsc -b && vite build`; typecheck is part of the normal build path.
- Vite output goes to `../static`, not `dist`, and `emptyOutDir: true` clears that target before writing new assets.
- Dev server proxies `/api` to `http://localhost:8000`; backend should already be running.
- Use `@/` imports for `src/*`.
- TypeScript is strict; unused locals and params are errors.
- ESLint is present but light. Do not assume type-aware ESLint or Prettier exists.

## ANTI-PATTERNS
- Do not treat `frontend/README.md` as authoritative project guidance; it is mostly stock Vite template text.
- Do not document or implement the frontend as a standalone production server; production assets are served by FastAPI.
- Do not mix backend startup instructions into this subtree except where they affect the Vite proxy split.
- Do not add subtree docs for `src/pages` or `src/components` unless local behavior diverges more than the current parent file covers.

## COMMANDS
```bash
cd frontend
npm install
npm run dev
npm run build
npm run lint
npm run preview
```

## NOTES
- `Accounts.tsx` is the heaviest account-management page; `RegisterTaskPage.tsx` is the registration-task orchestration page.
- ChatGPT-specific UI behavior is split across `src/components/ChatGPTRegistrationModeSwitch.tsx`, `src/hooks/usePersistentChatGPTRegistrationMode.ts`, and helpers under `src/lib/`.
