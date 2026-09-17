PYTHON ?= python3
VENV ?= .venv
PYTEST = $(VENV)/bin/pytest

.PHONY: test build clean live-test

test:
	$(PYTEST) -q

build:
	$(PYTHON) tools/build.py

clean:
	rm -rf dist .pytest_cache
	find . -name '__pycache__' -type d -not -path './.venv/*' -exec rm -rf {} +

live-test:
	LRT_EPIKA_LIVE=1 $(PYTEST) -q -m live
