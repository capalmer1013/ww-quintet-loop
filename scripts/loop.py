"""Listen to a piece's loop point without relying on the player to loop it.

Pieces are written to repeat seamlessly (the last frame runs straight into the first), but most
players restart the file to loop it -- VLC 3 included -- and leave a short gap. This writes, next
to the piece:

  --minutes M   <name>_loop.flac: the piece repeated end to end for at least M minutes, so the
                player never loops at all
  --seam        <name>_seam.wav: the piece's last SEAM_SECONDS then its first SEAM_SECONDS, to hear
                the join on its own

and prints how large the jump across the join is next to the piece's typical sample-to-sample step.
"""

import argparse
import math
from pathlib import Path

import numpy as np
from pedalboard.io import AudioFile

SEAM_SECONDS = 10.0


def read(path: Path) -> tuple[np.ndarray, float]:
    with AudioFile(str(path)) as f:
        return f.read(f.frames), f.samplerate


def write(path: Path, audio: np.ndarray, rate: float, repeats: int = 1) -> Path:
    with AudioFile(str(path), "w", samplerate=rate, num_channels=audio.shape[0], bit_depth=16) as f:
        for _ in range(repeats):
            f.write(audio)
    return path


def seam_report(audio: np.ndarray) -> str:
    jump = float(np.abs(audio[:, 0] - audio[:, -1]).max())
    step = float(np.percentile(np.abs(np.diff(audio, axis=1)).max(axis=0), 99))
    verdict = "seamless" if jump <= step else "a step at the join"
    return f"jump across the join {jump:.4f}, typical step {step:.4f}: {verdict}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("piece", type=Path, help="a piece's .wav, e.g. out/piece_9000.wav")
    parser.add_argument("--minutes", type=float, default=0.0, help="write <name>_loop.flac at least this long")
    parser.add_argument("--seam", action="store_true", help="write <name>_seam.wav around the join")
    args = parser.parse_args()

    audio, rate = read(args.piece)
    print(f"{args.piece}: {audio.shape[1] / rate:.2f} s, {seam_report(audio)}")
    stem = args.piece.with_suffix("")
    if args.minutes > 0:
        repeats = math.ceil(args.minutes * 60 * rate / audio.shape[1])
        path = write(stem.with_name(stem.name + "_loop.flac"), audio, rate, repeats)
        print(f"wrote {path} ({repeats} repeats, {repeats * audio.shape[1] / rate / 60:.1f} min)")
    if args.seam:
        n = min(round(SEAM_SECONDS * rate), audio.shape[1])
        join = np.concatenate([audio[:, -n:], audio[:, :n]], axis=1)
        path = write(stem.with_name(stem.name + "_seam.wav"), join, rate)
        print(f"wrote {path} (the join is at {n / rate:.1f} s)")


if __name__ == "__main__":
    main()
