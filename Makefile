.PHONY: install build check test test-lan audit web worker
install:
	uv sync --frozen --group dev
	pnpm --dir frontend install --frozen-lockfile
build:
	pnpm --dir frontend build
check:
	.venv/bin/ruff check backend scripts
	.venv/bin/ruff format --check backend scripts
	.venv/bin/mypy backend/boxen
	pnpm --dir frontend check
	pnpm --dir frontend exec prettier --check src e2e
test: build
	.venv/bin/pytest backend/tests --cov=boxen --cov-report=term-missing
	pnpm --dir frontend test
	pnpm --dir frontend test:e2e
test-lan: build
	pnpm --dir frontend exec playwright test --config playwright.lan.config.ts
audit:
	.venv/bin/pip-audit --local --skip-editable
	pnpm --dir frontend audit --prod
web:
	.venv/bin/boxen web
worker:
	.venv/bin/boxen worker
