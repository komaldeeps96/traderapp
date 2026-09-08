VENV := backend/.venv
PY   := $(VENV)/bin/python

.PHONY: help setup dev backend frontend test test-backend test-unit test-e2e \
        test-e2e-ui build typecheck lint lint-backend lint-frontend check clean

help:
	@echo "setup         install backend and frontend dependencies"
	@echo "dev           API and dev server together, on the WiFi"
	@echo "backend       run the API on :8000"
	@echo "frontend      run the dev server on :3000"
	@echo "check         lint + typecheck + every suite — what CI runs"
	@echo "lint          ruff and eslint"
	@echo "test          run every suite"
	@echo "test-backend  pytest"
	@echo "test-unit     vitest"
	@echo "test-e2e      playwright (starts its own servers)"
	@echo "test-e2e-ui   playwright, watching it run"
	@echo "build         production frontend build"
	@echo "typecheck     tsc across both workspaces"

setup:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -e "backend[dev]"
	npm install
	cd e2e && npx playwright install chromium firefox webkit
	@test -f backend/config/settings.yaml || \
		cp backend/config/settings.example.yaml backend/config/settings.yaml
	@echo "Add your Alpaca keys to backend/config/settings.yaml"

# Both servers bind 0.0.0.0, so the terminal is reachable from anything on the
# home WiFi without a second mode to remember: a phone or iPad opens
# http://$(LAN_IP):3000 and gets the *dev* server — hot reload included, since
# Vite aims its HMR socket at whatever host served the page. The API answers
# cross-origin on :8000, which is what settings.cors_origin_regex permits.
#
# http://$(LAN_IP):8000 also works on its own and is same-origin, but it serves
# whatever `make build` last wrote to frontend/dist — a snapshot, not the code
# you are editing. Use :3000 while developing.
#
# To keep a run laptop-only: TRADERAPP_CORS_ORIGIN_REGEX= make backend, and
# `npm run dev -- --host 127.0.0.1`.
LAN_IP := $(shell ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo 127.0.0.1)

backend:
	@echo "API   http://localhost:8000  ·  http://$(LAN_IP):8000"
	cd backend && .venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

frontend:
	@echo "UI    http://localhost:3000  ·  http://$(LAN_IP):3000"
	npm run dev

# Both at once, which is how the terminal actually gets used. -j2 runs them in
# parallel under one Ctrl-C; their logs interleave, so run the two targets in
# separate windows when you need to read either closely.
dev:
	@echo
	@echo "  this mac      http://localhost:3000"
	@echo "  phone/tablet  http://$(LAN_IP):3000"
	@echo
	@$(MAKE) -j2 backend frontend

# The whole gate, in the order that fails fastest: linters, then types, then
# the suites cheapest first. Same steps as CI, so a green `make check` means a
# green pipeline.
check: lint typecheck test

lint: lint-backend lint-frontend

lint-backend:
	cd backend && .venv/bin/ruff check app tests

lint-frontend:
	npm run lint

test: test-backend test-unit test-e2e

test-backend:
	cd backend && .venv/bin/python -m pytest -m "not live"

test-unit:
	npm run test:unit

test-e2e:
	npm run test:e2e

test-e2e-ui:
	npm run test:e2e:ui

build:
	npm run build

typecheck:
	npm run typecheck

clean:
	rm -rf frontend/dist e2e/test-results e2e/playwright-report
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
