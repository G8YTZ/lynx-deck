"""Media library: scans the media folder and probes each file with ffprobe.

Clip IDs are 1-based and follow filename order, so prefix files with numbers
(01_testcard.png, 02_ident.mp4 ...) to control the running order.
"""
import asyncio
import json
import logging

import yaml
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".m4v", ".ts"}
STILL_EXT = {".png", ".jpg", ".jpeg"}

# Per-clip behaviour, stored in clips.yaml alongside the media:
#   auto  - play, then move to the next clip (the default)
#   once  - same as auto (kept as an explicit, readable choice)
#   loop  - repeat this clip until told otherwise
#   hold  - play once, then stop on the last frame
BEHAVIOURS = ("auto", "once", "loop", "hold")
ATTR_FILE = "clips.yaml"


@dataclass
class Clip:
    id: int
    name: str          # display name (spaces replaced: controllers split on them)
    path: Path
    kind: str          # "video" or "still"
    duration: float    # seconds
    codec: str
    behaviour: str = "auto"


class Library:
    def __init__(self, cfg):
        self.cfg = cfg
        self.clips: list[Clip] = []
        self._cache: dict = {}   # (path, size, mtime) -> probe result

    # ----- per-clip attributes -------------------------------------------

    def _attr_path(self):
        return Path(self.cfg.media_dir) / ATTR_FILE

    def load_attrs(self):
        try:
            with open(self._attr_path()) as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            return {}
        except (OSError, yaml.YAMLError) as exc:
            log.warning("Could not read %s: %s", ATTR_FILE, exc)
            return {}

    def save_attrs(self, attrs):
        tmp = self._attr_path().with_suffix(".yaml.tmp")
        with open(tmp, "w") as f:
            yaml.safe_dump(attrs, f, sort_keys=True)
        tmp.replace(self._attr_path())

    def set_behaviour(self, name, behaviour=None, duration=None):
        """Update one clip's behaviour and/or still duration."""
        attrs = self.load_attrs()
        entry = dict(attrs.get(name) or {})
        if behaviour is not None:
            if behaviour not in BEHAVIOURS:
                raise ValueError(f"behaviour must be one of {BEHAVIOURS}")
            entry["play"] = behaviour
        if duration is not None:
            entry["duration"] = float(duration)
        attrs[name] = entry
        self.save_attrs(attrs)

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
        attrs = self.load_attrs()
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
            entry = attrs.get(p.name) or {}
            duration = probe["duration"]
            if kind == "still":
                duration = float(entry.get("duration", self.cfg.still_duration))
            behaviour = str(entry.get("play", "auto")).lower()
            if behaviour not in BEHAVIOURS:
                log.warning("%s: unknown behaviour %r, using auto", p.name, behaviour)
                behaviour = "auto"
            clips.append(Clip(len(clips) + 1, p.name.replace(" ", "_"), p, kind,
                              duration, probe["codec"], behaviour))
        self.clips = clips
        log.info("Library: %d clips", len(clips))
        for c in clips:
            log.info("  %2d  %-36s %-5s %-5s %6.1fs  %s",
                     c.id, c.name, c.kind, c.codec, c.duration, c.behaviour)


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
