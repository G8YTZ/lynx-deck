#!/usr/bin/env python3
"""Where the pips actually are in a junction file.

    python3 tools/clock-pips.py /srv/lynxdeck/clock/junction/junction_09.flac

The file runs from 59:30, so the five short pips belong at 25, 26, 27, 28
and 29 seconds, and the long one at 30.000, which IS the hour. Anything
else and the file itself is out, however good the clock is.

With no file named, every junction file this Deck has, its own first.
"""
import subprocess
import sys
from pathlib import Path

import numpy as np

RATE = 48000
FRAME = 480            # 10 ms
WANT = [25.0, 26.0, 27.0, 28.0, 29.0, 30.0]


def bursts(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1",
                          "-ar", str(RATE), "-f", "f32le", "-"],
                         check=True, capture_output=True).stdout
    a = np.abs(np.frombuffer(raw, dtype=np.float32))
    n = len(a) // FRAME
    env = a[:n * FRAME].reshape(n, FRAME).max(axis=1)
    on = env > a.max() * 0.3
    d = np.diff(on.astype(np.int8))
    starts = (np.flatnonzero(d == 1) + 1) / 100.0
    ends = (np.flatnonzero(d == -1) + 1) / 100.0
    return len(a) / RATE, list(zip(starts, ends))


def report(path):
    dur, b = bursts(path)
    print(f"\n{path}   {dur:.3f} s long")
    short = [s for s, e in b if e - s < 0.3]
    long_ = [s for s, e in b if e - s >= 0.3]
    for s, e in b:
        print(f"   {s:7.2f} s  for {e - s:.2f} s")
    if not long_:
        print("   no long pip found (music or speech may be masking it)")
        return
    err = long_[-1] - 30.0
    if abs(err) < 0.02:
        print("   long pip is on 30.000: this file is right")
    else:
        print(f"   long pip is at {long_[-1]:.2f}, so {abs(err):.2f} s "
              f"{'LATE' if err > 0 else 'EARLY'} in the file")
    if len(short) != 5:
        print(f"   {len(short)} short pips, expected 5")


def main():
    args = sys.argv[1:]
    if args:
        for a in args:
            report(Path(a))
        return
    for d in ("/srv/lynxdeck/clock/junction",
              str(Path(__file__).resolve().parent.parent / "clock" / "junction")):
        files = sorted(Path(d).glob("junction_*.flac")) if Path(d).is_dir() else []
        if files:
            print(f"\n=== {d}")
            report(files[0])


if __name__ == "__main__":
    main()
