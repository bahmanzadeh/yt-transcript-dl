.DEFAULT_GOAL := all
UV ?= uv

.PHONY: all lock-check sync lint format test test-unit test-integration coverage check build install

all: check build

lock-check:
	$(UV) lock --check

sync: lock-check
	$(UV) sync --locked

lint: sync
	$(UV) run --locked ruff check src tests
	$(UV) run --locked ruff format --check src tests
	bash -n scripts/install.sh

format: sync
	$(UV) run --locked ruff format src tests

test: test-unit

test-unit: sync
	$(UV) run --locked pytest tests/unit

build: sync
	$(UV) run --locked python -m build --no-isolation

test-integration: build
	$(UV) run --locked pytest -m integration tests/integration

coverage: sync
	$(UV) run --locked pytest --cov=yt_transcript_dl --cov-report=term-missing tests/unit

check: lint test-unit

install:
	bash scripts/install.sh
