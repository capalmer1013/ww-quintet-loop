.DEFAULT_GOAL := help
.PHONY: help run test

ARGS ?=

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-6s %s\n", $$1, $$2}'
	@echo '  e.g. make run ARGS="--notes C.lydian --seeds 1000-1010 --code"'

run: ## Generate pieces: make run ARGS="--notes C.maj7s11 --seeds 1000-1100 --stems --code"
	python3 main.py $(ARGS)

test: ## Run the unittest suite
	python3 -m unittest
