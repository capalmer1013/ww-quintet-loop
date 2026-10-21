.DEFAULT_GOAL := help
.PHONY: help sync run loop seam batch lush daw raw test lint format fixtures

ARGS ?=
N ?= 10
FILE ?=
MINUTES ?= 60

help: ## List targets and every quintet flag
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'
	@echo ''
	@echo '  make run on its own makes one new piece, seeded from the clock. Flags go in ARGS, and work'
	@echo '  with the presets too (later flags win):'
	@echo '    make run ARGS="--seeds 0-10 --notes D.random --stems --code"'
	@echo '    make lush ARGS="--count 5"'
	@echo ''
	@echo '  Flags (defaults in brackets):'
	@echo '    --seeds A | A-B | now          one piece per seed; A-B excludes B; now = from the clock [now]'
	@echo '    --count N                      with --seeds now: how many new pieces [1]'
	@echo '    --notes random | C.random | C.lydian | C.maj9 ...'
	@echo '                                   key and mode, a mode on C, or a fixed set [random]'
	@echo '    --tempo BPM                    0 = random 55-75 per seed [0]'
	@echo '    --max-seconds S                longest piece (one full phase cycle) [360]'
	@echo '    --reverb AMOUNT                hall reverb, 0 = dry [0.5]'
	@echo '    --room SIZE                    hall size 0-1, 0.8 is about a 2.6 s decay [0.8]'
	@echo '    --reverb-ir FILE               a recorded space (impulse response WAV) instead of the hall [none]'
	@echo '    --master / --no-master         phone-friendly EQ, compression, -16 LUFS [on]'
	@echo '    --saturation AMOUNT            gentle tape-style warmth when mastering, 0 = clean [0.3]'
	@echo '    --humanize / --no-humanize     timing, breaths, varied takes and levels [on]'
	@echo '    --intonation / --no-intonation each note tuned a few cents off [on]'
	@echo '    --a4 HZ                        concert pitch; samples are A440, 432 is ~32 cents flat [440]'
	@echo '    --stems / --no-stems           also write one mono WAV per instrument [off]'
	@echo '    --code / --no-code             also write a .py that rebuilds each piece [off]'
	@echo '    --output-dir DIR               where pieces go [out]'
	@echo '    --sample-root DIR              the sample library [samples/]'
	@echo '    -h, --help                     print these from quintet itself (make run ARGS="--help")'

sync: ## Install the project and its dependencies (uv)
	uv sync

run: ## Generate pieces: make run ARGS="--seeds 0-10 --notes D.random --stems --code"
	uv run quintet $(ARGS)

loop: ## Repeat a piece into one long file (players gap when looping): make loop FILE=out/x.wav MINUTES=60
	uv run python scripts/loop.py $(FILE) --minutes $(MINUTES)

seam: ## Write a piece's last 10 s + first 10 s to hear its loop point: make seam FILE=out/x.wav
	uv run python scripts/loop.py $(FILE) --seam

batch: ## N new pieces in one run (default 10): make batch N=20
	uv run quintet --count $(N) $(ARGS)

lush: ## The warmest sound: a little more reverb, a bigger hall
	uv run quintet --reverb 0.7 --room 0.9 $(ARGS)

daw: ## For mixing elsewhere: per-instrument stems and a piece file
	uv run quintet --stems --code $(ARGS)

raw: ## Humanizing, intonation, mastering and reverb off, for A/B comparisons
	uv run quintet --no-humanize --no-intonation --no-master --reverb 0 $(ARGS)

test: ## Run the test suite
	uv run pytest

lint: ## Check the code with ruff
	uv run ruff check src tests scripts

format: ## Format the code with ruff
	uv run ruff format src tests scripts

fixtures: ## Re-record the generation parity fixture (only after changing generation on purpose)
	uv run python scripts/record_generation.py
