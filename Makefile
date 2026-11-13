.PHONY: install hooks lint format typecheck test backend-check web-check check dev-api dev-web

BACKEND := backend
WEB := web

install: hooks
	cd $(BACKEND) && uv sync
	cd $(WEB) && npm ci

hooks:
	git config core.hooksPath .githooks

lint:
	cd $(BACKEND) && uv run ruff check app tests && uv run ruff format --check app tests

format:
	cd $(BACKEND) && uv run ruff format app tests && uv run ruff check --fix app tests
	cd $(WEB) && npm run format

typecheck:
	cd $(BACKEND) && uv run mypy app

test:
	cd $(BACKEND) && (uv run pytest; s=$$?; [ $$s -eq 0 ] || [ $$s -eq 5 ])  # 5 = no tests collected

backend-check: lint typecheck test

web-check:  # types, lint, formatting, and a production build
	cd $(WEB) && npm run check && npx vite build --logLevel warn

check: backend-check web-check

dev-api:  # local API on :8000 with its own SQLite database (not the deployed one)
	cd $(BACKEND) && DATABASE_URL="sqlite:///$(CURDIR)/$(BACKEND)/dev.db" uv run uvicorn app.main:app --reload --port 8000

dev-web:  # Vite on :5173, proxying /api to :8000
	cd $(WEB) && npm run dev
