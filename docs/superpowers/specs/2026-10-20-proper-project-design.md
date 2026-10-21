# Proper project: uv package, numpy rendering, pedalboard effects — design

Status: approved in conversation 2026-10-20; awaiting written-spec review.
Builds on: `2026-10-20-phasing-quintet-design.md` (the music design, unchanged here).

## Goal

Drop the standard-library-only constraint, which now limits both speed (a 3-minute piece takes
about 37 s to render) and sound quality (improvised EQ, half-rate reverb, approximate loudness).
Make the repository a normal Python project: a uv-managed package with a `quintet` command,
vectorised numpy rendering, and studio-grade effects from Spotify's pedalboard.

### Decisions

| Topic | Decision |
|---|---|
| Audio stack | numpy for rendering; pedalboard for reverb, EQ, compression, limiting; pyloudnorm for true LUFS |
| Packaging | `src/quintet/` package managed by uv (pyproject + committed `uv.lock`), console script `quintet` |
| Dev tools | pytest, ruff (dev dependency group) |
| Music | Generation is unchanged: same patterns, harmony, voicing, seeds and piece-file contents |
| Audio | Not byte-identical with the stdlib version (effects change); seeds still give the same notes |

### Non-goals

- Changing anything about how pieces are generated (that work continues in the music spec).
- Publishing to PyPI or bundling the 645 MB sample library into the package.
- Real-time playback.

## Layout

```
pyproject.toml          [project] deps: numpy, pedalboard, pyloudnorm; [dependency-groups] dev: pytest, ruff;
                        [project.scripts] quintet = "quintet.cli:main"; build backend: hatchling
uv.lock                 committed (replaces the stale, untracked one)
src/quintet/
  __init__.py           public API, same names as utils/__init__.py today (from quintet import * works)
  cli.py                the old main.py: per-seed loop, prints one line per piece
  config.py             moved as is; DEFAULT_SAMPLE_ROOT = repo root / "samples" (parents[2])
  samples.py            moved; WAV I/O via pedalboard.io.AudioFile, audio as float32 numpy arrays
  theory.py             moved as is
  pattern.py            moved as is
  voice.py              moved as is (one import line changes: sustainable_frames now lives in samples.py)
  render.py             numpy rendering (see below); keeps leveled, sustain, hairpin, mix, render, piece_code
  effects.py            pedalboard chain + loudness: replaces utils/reverb.py and utils/master.py
samples/                unchanged
tests/                  pytest; existing unittest classes run unchanged; effect tests rewritten
Makefile                help (default) · sync · run · test · lint · format
```

`utils/` and `main.py` are removed. Moving modules happens with `git mv` so history follows.

## Rendering with numpy (`render.py`, `samples.py`)

Same behaviour as today, vectorised:

- **Samples:** `Sample.load()` returns float32 in [-1, 1] (cached). `Sample.seconds` reads the
  header (`AudioFile(...).frames`).
- **Levelling:** `loudness_db` takes the loudest 0.3 s RMS using a cumulative sum of squares
  (`np.cumsum`); `leveled()` multiplies once and caches.
- **Notes:** `_note_audio` (cached) does the cut fade, sustain loop with equal-power crossfades,
  hairpin, attack and accent gain as numpy vector operations on the note.
- **Lines:** `voice_line` preallocates a float32 array for the whole piece and slice-assigns each
  note.
- **Mix:** per-voice volume-sine gains are computed per frame with numpy, not per 512-frame block.
  Constant-power pan gains give a `(frames, 2)` float32 stereo array.
- **Output:** 16-bit WAV written with `pedalboard.io.AudioFile`.

`sustainable_frames`, `loopable` and the loop constants move to `samples.py`. They describe what a
recording can do, and moving them removes `voice.py`'s lazy import of `render`.

## Effects (`effects.py`)

`finish(stereo, config) -> stereo` runs after the mix when `config.master` is on (and reverb when
`config.reverb > 0`):

1. **Reverb:** `pedalboard.Reverb(room_size=config.room, damping=0.5, wet_level=config.reverb,
   dry_level=1.0, width=1.0)`.
2. **EQ:** `HighpassFilter(60)`, `PeakFilter(300 Hz, -3 dB, q=1.0)`,
   `PeakFilter(3500 Hz, +3.5 dB, q=0.9)`, matching the current measured curve.
3. **Compression:** `Compressor(threshold_db=target - 8 after pre-gain, ratio=2, attack_ms=20,
   release_ms=300)`, after a pre-gain that brings the mix to the target loudness (same idea as now).
4. **Loudness:** measure with `pyloudnorm.Meter(44100)` (true K-weighted, gated LUFS) and gain to
   `TARGET_LUFS` = -16.
5. **Limiting:** `Limiter(threshold_db=-1.0)`, then a final check that the peak is at most -1 dBFS.

Each stage has its own constant at the top of `effects.py`.

**Seamless loops:** pedalboard's processors are stateful and know nothing about loops, so each
stateful stage processes the piece's own last `PREROLL` seconds followed by the piece, and keeps
only the last `n` frames. `PREROLL` is the reverb tail (about 2 × RT60) or the compressor/limiter
release, whichever is longer. One rendered loop then equals a loop that follows another; a test
checks this.

`--reverb 0` skips the reverb; `--no-master` skips EQ, compression, loudness and the limiter, and
falls back to the old peak-safe scaling. Stems stay dry and unmastered.

## CLI and piece files

- `quintet` takes every current `Config` flag unchanged (`--seeds`, `--notes`, `--tempo`,
  `--reverb`, `--room`, `--master`, `--stems`, `--code`, `--max-seconds`, `--output-dir`,
  `--sample-root`).
- `--sample-root` defaults to the repository's `samples/`. A clear error names the flag if that
  folder isn't there (for example, if the package is installed elsewhere).
- Piece files become:
  ```python
  """piece_3: seed 3, F.maj9, 61 bpm, 120.00s"""
  from quintet import *

  Config(tempo=61.0, reverb=0.3, room=0.8, master=True)
  render('piece_3', F.maj9, ...)
  ```
  They run with `uv run python out/piece_3.py`.
- Old piece files (`from utils import *` plus a `sys.path` line) stop working. They are generated
  output, so the README says to regenerate them.

## Makefile and docs

| Target | Runs |
|---|---|
| `help` (default) | lists targets |
| `sync` | `uv sync` |
| `run` | `uv run quintet $(ARGS)` |
| `test` | `uv run pytest` |
| `lint` | `uv run ruff check` |
| `format` | `uv run ruff format` |

The README is rewritten around `make sync` and `make run`. The "no dependencies" text goes, and the
mastering and reverb sections describe the pedalboard chain. The music spec's section 15 (stdlib
reverb) and section 26's mastering notes get a pointer to this spec.

## Testing

- All current tests move to `tests/` under pytest and keep passing, except the stdlib-effect tests
  (`test_reverb.py`, `test_master.py`), which are replaced by `test_effects.py`:
  - reverb tail decays;
  - loop seam: one loop matches a loop that follows another;
  - EQ response at a few frequencies within ±1 dB of the design;
  - output loudness within ±0.5 LU of -16 (pyloudnorm);
  - peak at most -1 dBFS;
  - `--no-master` / `--reverb 0` skip their stages.
- Rendering tests compare behaviour (lengths, cuts, fades, accents, pan, sines), not bytes.
- **Generation parity:** for 20 seeds, the piece code the new package generates equals what the
  current stdlib version generates. This is recorded as fixture files before the move, so the move
  provably keeps the music the same.
- **Performance check** (not a strict test): a 3-minute piece renders in under 5 s.

## Risks

- **pedalboard wheels:** available for macOS, Linux and Windows on Python 3.10–3.13; the
  `requires-python` range will match what's available.
- **Reverb character:** pedalboard's reverb is also Freeverb-based, so it should sound similar but
  cleaner. Its `wet_level` scale differs from ours, so `--reverb` is recalibrated to give the
  current wet/dry balance at 0.3.
