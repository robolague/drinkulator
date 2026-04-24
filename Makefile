.PHONY: install install-dev install-hooks lint test check ci-check format

install:
	uv sync

install-dev:
	uv sync --all-groups

install-hooks: install-dev
	uv run pre-commit install
	uv run pre-commit install --hook-type pre-push

lint:
	uv run ruff check .

test:
	uv run python -m pytest -q

check: ci-check

ci-check: lint test

format:
	uv run ruff check . --fix
