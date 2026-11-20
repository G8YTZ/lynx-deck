#!/usr/bin/env python3
"""Lynx Deck station clock: the sound for the top of the hour.

One file per hour, each starting at mm:59:30 (G8YTZ, 20 Nov 2026):

  59:30  music (Lillibullero, 20 s; silence until the recording arrives)
  59:55  five short pips, 0.1 s each, on :55 :56 :57 :58 :59
  00:00  the long pip, 0.5 s; its start is the hour (Greenwich Time Signal)
  00:01  the time announcement for the new hour

  python3 make_junction.py ANNOUNCEMENTS_DIR [MUSIC_FILE]

ANNOUNCEMENTS_DIR holds one file per hour whose name ends in its number
(..._1.mp3 .. ..._12.mp3, or -1.mp3 and so on). The results go in
junction/junction_01.m4a .. junction_12.m4a beside this script, where
clock.lua looks for them.
"""
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

RATE = 48000
LENGTH = 35.0                 # seconds from 59:30
MUSIC_AT, MUSIC_MAX = 0.0, 20.0
PIPS_AT = [25.0, 26.0, 27.0, 28.0, 29.0]   # :55 to :59
LONG_AT = 30.0                # 00:00:00
SHORT, LONG = 0.1, 0.5
ANNOUNCE_AT = 31.0            # half a second after the long pip ends
PIP_PEAK_DBFS = -15.0         # a -18 dBFS line-up tone, PPM 4
RAMP = 0.004                  # 4 ms edges: no clicks, still crisp


def decode(path, mono=False):
    """Any file ffmpeg reads, as stereo float at RATE. A mono voice goes to
    both sides at full level (ffmpeg's own upmix would drop it 3 dB)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1" if mono else "2",
                          "-ar", str(RATE), "-f", "f32le", "-"], check=True, capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.float32)
    return np.stack([a, a], -1) if mono else a.reshape(-1, 2)


def pip(seconds):
    n = int(round(seconds * RATE))
    t = np.arange(n) / RATE
    tone = np.sin(2 * np.pi * 1000 * t) * 10 ** (PIP_PEAK_DBFS / 20)
    r = int(RAMP * RATE)
    edge = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, r))
    tone[:r] *= edge
    tone[-r:] *= edge[::-1]
    return np.stack([tone, tone], -1).astype(np.float32)


def place(track, sound, at):
    i = int(round(at * RATE))
    j = min(len(track), i + len(sound))
    track[i:j] += sound[:j - i]


def announcements(folder):
    found = {}
    for f in Path(folder).iterdir():
        m = re.search(r"(\d+)\.[^.]+$", f.name)
        if m and 1 <= int(m.group(1)) <= 12:
            found[int(m.group(1))] = f
    missing = sorted(set(range(1, 13)) - set(found))
    if missing:
        sys.exit(f"no announcement for hour(s) {missing}")
    return found


def main():
    found = announcements(sys.argv[1])
    music = decode(sys.argv[2])[: int(MUSIC_MAX * RATE)] if len(sys.argv) > 2 else None
    out = Path(__file__).with_name("junction")
    out.mkdir(exist_ok=True)
    for hour in range(1, 13):
        track = np.zeros((int(LENGTH * RATE), 2), dtype=np.float32)
        if music is not None:
            place(track, music, MUSIC_AT)
        for at in PIPS_AT:
            place(track, pip(SHORT), at)
        place(track, pip(LONG), LONG_AT)
        place(track, decode(found[hour], mono=True), ANNOUNCE_AT)
        peak = float(np.abs(track).max())
        if peak > 0.98:
            track *= 0.98 / peak
        dest = out / f"junction_{hour:02d}.m4a"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(RATE), "-ac", "2",
                        "-i", "-", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(dest)],
                       input=track.tobytes(), check=True)
        print(f"{dest.name}: {found[hour].name}, peak {20 * np.log10(peak):.1f} dBFS")


if __name__ == "__main__":
    main()
