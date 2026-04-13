# PLATFORMS KNOWLEDGE BASE

## OVERVIEW
Plugin root for platform-specific registration behavior. The main repo loads platform implementations dynamically rather than wiring them manually one by one.

## WHERE TO LOOK
| Task | Location | Notes |
|---|---|---|
| Plugin loading | `../core/registry.py` | `load_all()` imports `platforms.*.plugin` |
| Simple platform implementation | `<platform>/plugin.py`, `<platform>/core.py` | repeated pattern across several platforms |
| Platform-specific extras | `grok/`, `kiro/`, `trae/`, `cursor/` | some add `switch.py` or upload-specific helpers |
| Deepest subsystem | `chatgpt/` | read local AGENTS first |

## CONVENTIONS
- New platform behavior is expected to hang off the plugin boundary, not the API router layer.
- `plugin.py` is the discovery point; `core/registry.py` catches `ModuleNotFoundError` during plugin import, so a missing plugin file or a missing nested dependency can make a platform disappear from the registry.
- Several smaller platforms follow a compact `plugin.py` + `core.py` pattern; keep docs general here and push ChatGPT-specific detail into the child file.

## ANTI-PATTERNS
- Do not assume all platform directories are structurally identical.
- Do not put ChatGPT-specific token, GUI, or sentinel rules in this parent file.
- Do not document platform behavior from the API side first; start at the plugin boundary.

## NOTES
- `chatgpt/` is effectively its own subsystem.
- `grok/`, `kiro/`, `trae/`, and `cursor/` show platform-local deviations such as `switch.py` or upload integrations, but not enough to justify separate child files yet.
