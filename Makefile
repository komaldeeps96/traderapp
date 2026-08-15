VENV := backend/.venv
PY   := $(VENV)/bin/python

.PHONY: help setup dev backend frontend test test-backend test-unit test-e2e \
        test-e2e-ui build typecheck lint lint-backend lint-frontend check clean

help:
	@echo "setup         install backend and frontend dependencies"
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

# Bound to 0.0.0.0 so devices on the home WiFi can use the terminal too:
# a phone/iPad opens http://<this-mac's-ip>:8000 and gets the built UI,
# same-origin API and WebSocket included. (ipconfig getifaddr en0 prints
# the address.) Swap in --host 127.0.0.1 to keep it laptop-only.
backend:
	cd backend && .venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

frontend:
	npm run dev

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
