"""Media library: scans the media folder and probes each file with ffprobe.

Clip IDs are 1-based and follow filename order, so prefix files with numbers
(01_testcard.png, 02_ident.mp4 ...) to control the running order.
"""
import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".m4v", ".ts"}
STILL_EXT = {".png", ".jpg", ".jpeg"}


@dataclass
class Clip:
    id: int
    name: str          # display name (spaces replaced: HyperDeck clients split on them)
    path: Path
    kind: str          # "video" or "still"
    duration: float    # seconds
    codec: str


class Library:
    def __init__(self, cfg):
        self.cfg = cfg
        self.clips: list[Clip] = []
        self._cache: dict = {}   # (path, size, mtime) -> probe result

    def get(self, clip_id):
        if clip_id is None or not 1 <= clip_id <= len(self.clips):
            return None
        return self.clips[clip_id - 1]

    async def scan(self):
        media = Path(self.cfg.media_dir)
        if not media.is_dir():
            log.error("Media folder %s does not exist", media)
            self.clips = []
            return
        files = sorted(
            (p for p in media.iterdir()
             if p.is_file() and not p.name.startswith(".")
             and p.suffix.lower() in VIDEO_EXT | STILL_EXT),
            key=lambda p: p.name.casefold(),
        )
        clips = []
        for p in files:
            st = p.stat()
            key = (str(p), st.st_size, st.st_mtime)
            probe = self._cache.get(key) or await _probe(p)
            if probe is None:
                log.warning("Skipping unreadable file %s", p.name)
                continue
            self._cache[key] = probe
            kind = "still" if p.suffix.lower() in STILL_EXT else "video"
            duration = self.cfg.still_duration if kind == "still" else probe["duration"]
            clips.append(Clip(len(clips) + 1, p.name.replace(" ", "_"), p, kind,
                              duration, probe["codec"]))
        self.clips = clips
        log.info("Library: %d clips", len(clips))
        for c in clips:
            log.info("  %2d  %-40s %-5s %s %.1fs", c.id, c.name, c.kind, c.codec, c.duration)


async def _probe(path: Path):
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name:format=duration",
        "-of", "json", str(path),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        return None
    try:
        info = json.loads(out)
        codec = info["streams"][0]["codec_name"]
        duration = float(info.get("format", {}).get("duration") or 0)
    except (ValueError, KeyError, IndexError):
        return None
    return {"codec": codec, "duration": duration}
