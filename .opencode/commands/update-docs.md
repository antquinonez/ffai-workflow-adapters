---
description: Regenerate API reference documentation
---

Regenerate the AI-consumable API reference from source.

1. Run `scripts/generate_api_docs.py` using the project venv Python (`.venv/bin/python`).
2. Report the output (number of modules, file sizes).
3. Do not commit the generated files.

The script reads `PUBLIC_MODULES` from its own module list. When adding a new
public module, add it to `PUBLIC_MODULES` in `scripts/generate_api_docs.py`.

If the script fails, investigate and fix the issue. Common causes:
- Import errors: check that the module is importable from the project root
- Missing modules: check that the module name in `PUBLIC_MODULES` matches an actual file
