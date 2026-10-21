.DEFAULT_GOAL := help
.PHONY: help sync run test lint format

ARGS ?=

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-7s %s\n", $$1, $$2}'
	@echo '  e.g. make run ARGS="--seeds 0-10 --code"'

sync: ## Install the project and its dependencies (uv)
	uv sync

run: ## Generate pieces: make run ARGS="--seeds 0-10 --notes D.random --stems --code"
	uv run quintet $(ARGS)

test: ## Run the test suite
	uv run pytest

lint: ## Check the code with ruff
	uv run ruff check src tests

format: ## Format the code with ruff
	uv run ruff format src tests
