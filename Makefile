.PHONY: install hooks lint format typecheck test check

BACKEND := backend

install: hooks
	cd $(BACKEND) && uv sync

hooks:
	git config core.hooksPath .githooks

lint:
	cd $(BACKEND) && uv run ruff check app tests && uv run ruff format --check app tests

format:
	cd $(BACKEND) && uv run ruff format app tests && uv run ruff check --fix app tests

typecheck:
	cd $(BACKEND) && uv run mypy app

test:
	cd $(BACKEND) && (uv run pytest; s=$$?; [ $$s -eq 0 ] || [ $$s -eq 5 ])  # 5 = no tests collected

check: lint typecheck test
