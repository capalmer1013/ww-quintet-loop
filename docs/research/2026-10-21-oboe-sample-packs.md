# Replacement oboe sample libraries (research, 2026-10-21)

**Why:** the oboe sounds "quacky" and pokes out of the soft quintet blend. `MAX_LAYERS` caps every
instrument at `mp`, but the current oboe has no `mp`, a `p` layer missing C5–Ds5, and one `pp` note
(`oboe_F5_pp_0.25s.wav`). The sets on disk: pp 1 file, p 128, mf 138, f 140, ff 123.

**Method:** web research and GitHub API metadata only (file listings, sizes, SFZ text). **No sample
files were downloaded**, so anything that needs a file header or a listen is marked *unverified*.

## Top pick

**VSCO 2: Community Edition (VSCO 2 CE), `Woodwinds/Oboe/Sus`.** CC0, non-vibrato sustains,
a real soft velocity layer (`v1`), chromatic reach Bb3–F6 via 3–5 semitone sampling, only 35 MB to fetch.
Fallback / complement: **University of Iowa MIS oboe** (true chromatic `pp`, dry anechoic).

## Comparison

| | VSCO 2 CE | Iowa MIS | Philharmonia (likely current) | Sonatina (SSO) | Virtual Playing Orchestra |
|---|---|---|---|---|---|
| **License** | CC0 (repo `LICENSE`); readme asks for credit to Versilian Studios / Sam Gossner and a link, and says don't sell the samples directly | "Freely available… for any projects, without restrictions" (no formal licence text) | Free use incl. commercial; must not be sold or distributed "as is" as samples or a sampler instrument. Mirror also cites CC BY-SA 3.0 (unconfirmed on official site) | CC Sampling Plus 1.0 | No restrictions on making music; no repackaging/selling; mixed sources |
| **Audio sharing OK?** | Yes | Yes | Yes (rendered pieces are not "samples as is") | Yes (my reading of Sampling Plus: sampling into new works is allowed) | Yes |
| **Dynamics** | 2 layers: `v1` (vel 0–62), `v3` (63–127). SFZ gives `v1` +12 dB and `v3` +4 dB, so `v1` was recorded ~8 dB quieter. No `v2`. Not named pp/p/mp | `pp`, `mf`, `ff` | pianissimo / piano / forte / fortissimo family (current set has a gap at mp) | One layer | Repackages others; no oboe-specific layers found |
| **Coverage** | 9 pitches per layer (files A#2 D3 F3 A#3 D4 F4 A#4 D5 F5 = MIDI 58 62 65 70 74 77 82 86 89), SFZ spreads each ±1–2 semitones. Bb3–F6 | Chromatic, Bb3–Ab6, per dynamic | Chromatic-ish (current set: gaps at p) | 10 pitches, minor 3rds, a#3–c6 (plus e6 for ensemble) | n/a |
| **Sustain** | Files 1.2–4.8 MB (Sus) = several seconds *(unverified: bit depth not read)* | Unspecified; scale files, notes cut by silence | Has 0.25 s–very-long takes | ~2 s, plus looped versions | Looped |
| **Vibrato** | `Sus` = non-vibrato; separate `Vib` set (24 MB) | Not documented | Not documented | Not documented | n/a |
| **Format** | WAV, 44.1 kHz, 16 or 24-bit, stereo "Main" mic *(unverified)*; plain WAV + SFZ | AIFF 16-bit 44.1 kHz **mono**, anechoic | MP3 originally (lossy) | WAV stereo 16-bit 44.1 kHz | WAV + SFZ |
| **Tone** | Hall recording, "Main" mic, transparent chain *(no oboe-specific review found; inference only)* | Anechoic, single close Neumann KM 84, 1997 player: dry and direct, likely as nasal or more so *(inference)* | Likely your current "quack" | Sample-tuned up to 25 cents flat in the SFZ | n/a |
| **Download / size** | Per-file from GitHub `master`; oboe Sus 34.9 MB (18 files), Vib 24.0 MB; whole repo ~3 GB (don't) | Per-dynamic zips on one page; pp is about 10 MB (four range files) | philharmonia.co.uk/audio-sound-samples, Woodwind zip | Solo oboe 3.8 MB; release zip on GitHub | Wave files 603 MB |
| **Fits `samples/` layout?** | Needs conversion (below) | Needs slicing + renaming; no resample/mono step | Already the layout | Needs conversion; one dynamic only | Skip |

## Ranked recommendation

1. **VSCO 2 CE**
   - Only candidate that is CC0, DAW-grade WAV, and has a genuine soft layer distinct from the loud one.
   - Non-vibrato `Sus` plus hall ambience is the best bet for a covered, blendable oboe.
   - Costs: 9 source pitches means every other note is resampled up to ±2 semitones (tiny formant shift, fine in a soft
     blend); only 2 layers; tone is unverified.
2. **Iowa MIS** — only source with real chromatic `pp` and `mf` at every pitch, in the project's native
   format (mono, 16-bit, 44.1 kHz), so no pitch-shifting. Risk: anechoic and close-mic'd, so it may poke out as much as
   the current oboe. The project's convolution hall supplies the room, which helps.
3. **Philharmonia** (what you have) — only worth keeping if the filler fix works.
4. **Sonatina Solo Oboe** — single dynamic, minor-third spacing, sampled 8–25 cents flat. Poor fit.
5. **Virtual Playing Orchestra** — repackages SSO/VSCO/Iowa; adds nothing, 603 MB.

Not viable: Spitfire BBC SO Discover and LABS (plugin-only, no extractable WAV).

**Suggested decision step:** audition both. Fetch only `Woodwinds/Oboe/Sus` (35 MB) from VSCO and the three
Iowa oboe zips, render with the same seeds, compare. Low cost, and tone is the one thing this research could not settle.

## Conversion steps for VSCO 2 CE

1. **Fetch only the oboe folder** (sparse checkout of `sgossner/VSCO-2-CE`, `master`, `Woodwinds/Oboe/Sus`; skip `Stacc`
   and `Vib`). Put it outside `samples/` until the output is ready.
2. **Read headers** (sample rate, bit depth, channels, length). Not checked here. If not 44.1 kHz, resample.
3. **Fix octave naming.** Files are named in the "C3 = 60" convention: `Oboe_Sus_A#2_*` is MIDI 58, which this
   project calls `As3`. Confirm with a pitch detector before trusting the names (the SFZ `pitch_keycenter`s are
   authoritative).
4. **Mono-sum** the stereo "Main" file (average L/R), convert to 16-bit with dither.
5. **Fill the chromatic gaps.** Each target note = nearest source resampled by `2 ** (semitones / 12)`
   (≤ ±2 st). The project already has `retuned()` in `render.py` for cents-level shifts; do this offline instead so
   `samples/oboe/` stays one file per note.
6. **Trim.** Find the onset, leave ~10 ms before it, and cut `0.25s / 0.5s / 1s / 1.5s / long` (3 s) takes with a 30–80 ms fade-out
   so short takes don't click. Skip `very-long`; the project loops sustains itself (`samples.py` loop logic).
7. **Name and place:** `samples/oboe/notes/<dyn>/oboe_<note>_<dyn>_<length>.wav`, sharps as `s`.
   Map `v1` → `p` (or `mp`) and `v3` → `mf`. With `MAX_LAYERS["oboe"] == "mp"` only the `v1` layer plays;
   the leveller rescales to the dynamic's target either way, so the label mainly sets the target loudness.
8. **Level check.** `v1` needed +12 dB in the SFZ, so the raw files are quiet. README says no recording is ever boosted
   (a test checks every file). Normalise the converted files to a sensible RMS first, or that invariant breaks.
9. **Keep the old oboe** as `samples/oboe-philharmonia/` for A/B. `extended/` isn't used by pieces, so it can be dropped.
10. **Retune `INSTRUMENT_TRIM_DB["oboe"]`** (currently −6 dB) by ear. A softer source may not need it.
11. **Credit** Versilian Studios / Sam Gossner and link the VSCO: CE homepage in the README (asked for in their readme).

## Conversion steps if Iowa MIS wins instead

- Download `Oboe.pp.zip` and `Oboe.mf.zip` (the page's pp link currently points at `oboe.zip`; check) and slice each
  chromatic scale file into notes by silence detection (~−50 dB). Expect 33 notes (Bb3–Ab6).
- Name from the scale order; verify pitch with a detector.
- Already mono / 16-bit / 44.1 kHz: no resample or mono-sum. Convert AIFF → WAV.
- Same trim / fade / length variants as above. Map `pp` → `pp`, `mf` → `mp` or `mf`.
- No `p` or `mp`, so oboe would run one dynamic quieter than the other instruments' `mp` target unless relabelled.

## Open questions (need a download or a listen, both out of scope here)

- VSCO WAV bit depth, channel count and true durations; whether `v1` is truly soft in timbre or just quieter.
- Iowa note lengths and vibrato; whether the 1997 oboe tone is any better than Philharmonia's.
- Tone of either source in the blend.

## Sources

- [Philharmonia sound samples](https://philharmonia.co.uk/audio-sound-samples/)
- [skratchdot/philharmonia-samples mirror](https://github.com/skratchdot/philharmonia-samples/)
- [VSCO 2 CE repo](https://github.com/sgossner/VSCO-2-CE) and [Versilian community page](https://versilian-studios.com/vsco-community/)
- [Iowa MIS](https://theremin.music.uiowa.edu/MIS.html) and [oboe page](https://theremin.music.uiowa.edu/MISoboe.html)
- [Sonatina Symphonic Orchestra repo](https://github.com/peastman/sso)
- [Virtual Playing Orchestra](https://virtualplaying.com/virtual-playing-orchestra/)
