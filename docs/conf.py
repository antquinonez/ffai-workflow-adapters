project = "ffai-workflow-adapters"
copyright = "2025, Antonio Quinonez"
author = "Antonio Quinonez"

release = "0.1.0"
version = "0.1"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

source_suffix = {
    ".md": "markdown",
    ".rst": "restructuredtext",
}

html_theme = "sphinx_book_theme" if tags.has("html") else "basic"
html_static_path = ["_static"]

autoclass_content = "class"
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
}
autodoc_typehints = "description"
autodoc_typehints_format = "short"

napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True
napoleon_use_ivar = True

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}
