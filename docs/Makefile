SPHINXOPTS    ?=
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = .
BUILDDIR      = _build

help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

%:
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

.PHONY: help Makefile html text json

html:
	@$(SPHINXBUILD) -M html "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

text:
	@$(SPHINXBUILD) -M text "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

json:
	@$(SPHINXBUILD) -M json "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
