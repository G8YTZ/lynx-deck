#!/usr/bin/env python3
"""Lynx Deck station clock: the sound for the top of the hour.

One file per hour, each starting at mm:59:30 (G8YTZ, 20 Nov 2026), written
as lossless FLAC: the announcements and music are decoded once to place them
in time and never re-encoded with a lossy codec (an AAC pass added audible
quantising noise to the announcements; Justin, 20 Nov 2026):

  59:30  music (Lillibullero, 20 s; silence until the recording arrives)
  59:55  five short pips, 0.1 s each, on :55 :56 :57 :58 :59
  00:00  the long pip, 0.5 s; its start is the hour (Greenwich Time Signal)
  00:01  the time announcement for the new hour

  python3 make_junction.py [ANNOUNCEMENTS_DIR] [--music FILE] [--out DIR]

ANNOUNCEMENTS_DIR holds one file per hour whose name ends in its number
(..._1.mp3 .. ..._12.mp3, or -1.mp3 and so on); an hour without one gets
the pips alone. The results (junction_01.flac .. junction_12.flac) go in
junction/ beside this script (the default every Deck starts with) or in
--out: Lynx Deck builds each repeater's own in /srv/lynxdeck/clock/junction.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

RATE = 48000
LENGTH = 38.0                 # seconds from 59:30 (room for a long
                              # announcement, and for the sound delay)
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
    """{hour: file} for files whose names end in 1 to 12 (hour_7.mp3, ...-7.wav)."""
    found = {}
    if folder and Path(folder).is_dir():
        for f in sorted(Path(folder).iterdir()):
            m = re.search(r"(\d+)\.[^.]+$", f.name)
            if m and 1 <= int(m.group(1)) <= 12:
                found[int(m.group(1))] = f
    return found


def main():
    ap = argparse.ArgumentParser(description="Build the twelve top-of-the-hour sounds.")
    ap.add_argument("announcements", nargs="?", help="folder of announcements ..1 to ..12")
    ap.add_argument("--music", help="music for 59:30 (cut to 20 s with a fade if longer)")
    ap.add_argument("--out", default=str(Path(__file__).with_name("junction")))
    a = ap.parse_args()
    found = announcements(a.announcements)
    music = None
    if a.music:
        music = decode(a.music)
        if len(music) > MUSIC_MAX * RATE:
            music = music[: int(MUSIC_MAX * RATE)].copy()
            n = RATE                                   # last second fades out
            music[-n:] *= np.linspace(1, 0, n, dtype=np.float32)[:, None]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for hour in range(1, 13):
        track = np.zeros((int(LENGTH * RATE), 2), dtype=np.float32)
        if music is not None:
            place(track, music, MUSIC_AT)
        for at in PIPS_AT:
            place(track, pip(SHORT), at)
        place(track, pip(LONG), LONG_AT)
        if hour in found:
            place(track, decode(found[hour], mono=True), ANNOUNCE_AT)
        peak = float(np.abs(track).max())
        if peak > 0.98:
            track *= 0.98 / peak
        part = out / f".junction_{hour:02d}.flac"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(RATE), "-ac", "2",
                        "-i", "-", "-c:a", "flac", "-sample_fmt", "s32", "-f", "flac", str(part)],
                       input=track.tobytes(), check=True)
        part.replace(out / f"junction_{hour:02d}.flac")
        (out / f"junction_{hour:02d}.m4a").unlink(missing_ok=True)   # the old lossy ones
        what = found[hour].name if hour in found else "pips only"
        print(f"junction_{hour:02d}.flac: {what}{', music' if music is not None else ''}, "
              f"peak {20 * np.log10(peak):.1f} dBFS", flush=True)


if __name__ == "__main__":
    main()
