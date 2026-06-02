---
description: Regenerate documentation (HTML, text, JSON)
---

Regenerate documentation from source using Sphinx.

1. Run `make html` (or `make text` / `make json`) from the `docs/` directory.
2. Report the output (builder used, warnings, output location).
3. Do not commit the generated files under `docs/_build/`.

The API reference in `docs/api/index.rst` uses `sphinx.ext.autodoc` to generate
documentation from source docstrings. When adding a new public module, add an
`.. automodule::` directive to `docs/api/index.rst`.

If the build produces errors about a module (import failure, missing file), fix
the source or the directive in `docs/api/index.rst`.

The `scripts/generate_api_docs.py` script remains available for generating
standalone Markdown API docs outside of Sphinx.
