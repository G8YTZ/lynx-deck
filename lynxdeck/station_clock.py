"""The station clock's own files: each Deck's face and top-of-the-hour sounds.

Everything a repeater makes its own lives in clock_dir (default
/srv/lynxdeck/clock), outside the code, so updates never touch it:

  sounds/hour_1.mp3 .. hour_12.mp3   announcements, as uploaded
  sounds/music.<ext>                  music for 59:30 (optional)
  junction/junction_01.flac ..        built from the above by make_junction.py (lossless)

The face is drawn by make_clock.py with the station's call sign, town and web
address and saved into the media folder as an ordinary still, so it is called
up like any other clip. Without any of this, clock.lua falls back to the
generic files in the repo's clock/ folder (pips, no music, no announcement).
"""
import asyncio
import json
import logging
import re
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)

REPO_CLOCK = Path(__file__).resolve().parent.parent / "clock"
AUDIO_EXT = {".mp3", ".wav", ".aif", ".aiff", ".m4a", ".aac", ".flac", ".ogg", ".opus"}


class ClockError(Exception):
    pass


def sounds_dir(cfg):
    return Path(cfg.clock_dir) / "sounds"


def junction_dir(cfg):
    return Path(cfg.clock_dir) / "junction"


def slot_for(filename):
    """'music', or the hour 1..12 from a name ending in its number, else None."""
    stem = Path(filename).stem
    if "music" in stem.lower():
        return "music"
    m = re.search(r"(\d+)$", stem)
    if m and 1 <= int(m.group(1)) <= 12:
        return int(m.group(1))
    return None


def _slot_files(cfg, slot):
    base = "music" if slot == "music" else f"hour_{slot}"
    d = sounds_dir(cfg)
    return [p for p in d.glob(base + ".*") if p.suffix.lower() in AUDIO_EXT] if d.is_dir() else []


def status(cfg):
    hours = [h for h in range(1, 13) if _slot_files(cfg, h)]
    music = _slot_files(cfg, "music")
    built = sorted(junction_dir(cfg).glob("junction_*.flac")) if junction_dir(cfg).is_dir() else []
    return {
        "hours": hours,
        "music": music[0].name if music else None,
        "built": time.strftime("%d %b %Y %H:%M", time.localtime(built[0].stat().st_mtime))
                 if len(built) == 12 else None,
        "using": "this Deck's own" if len(built) == 12 else "the generic pips",
        "call": cfg.clock_call, "town": cfg.clock_town, "web": cfg.clock_web,
        "clip": cfg.clock_clip,
    }


async def _run(*args, timeout=600):
    p = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                             stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(p.communicate(), timeout)
    except asyncio.TimeoutError:
        p.kill()
        raise ClockError(f"{Path(args[1]).name} took too long")
    if p.returncode != 0:
        text = err.decode(errors="replace").strip().splitlines()
        why = text[-1] if text else f"{Path(args[1]).name} failed"
        if "No module named" in why:
            why += " (on the Deck: sudo apt install -y python3-numpy python3-pil)"
        raise ClockError(why)
    return out.decode(errors="replace")


async def has_audio(path):
    try:
        out = await _run("ffprobe", "-v", "error", "-select_streams", "a",
                         "-show_entries", "stream=codec_name", "-of", "json", str(path), timeout=30)
        return bool(json.loads(out).get("streams"))
    except (ClockError, ValueError):
        return False


async def save_sound(cfg, filename, tmp):
    """Put an uploaded file (already written to tmp) in its slot, then rebuild."""
    slot = slot_for(filename)
    ext = Path(filename).suffix.lower()
    if slot is None:
        raise ClockError("name it after its hour (..1 to ..12) or put 'music' in the name")
    if ext not in AUDIO_EXT:
        raise ClockError(f"unsupported sound file {ext}")
    if not await has_audio(tmp):
        raise ClockError("no sound found in the file")
    sounds_dir(cfg).mkdir(parents=True, exist_ok=True)
    for old in _slot_files(cfg, slot):
        old.unlink()
    dest = sounds_dir(cfg) / (("music" if slot == "music" else f"hour_{slot}") + ext)
    Path(tmp).replace(dest)
    log.info("Clock sound %s saved as %s", filename, dest.name)
    return slot


def delete_sound(cfg, slot):
    files = _slot_files(cfg, slot)
    for f in files:
        f.unlink()
    return bool(files)


_building = asyncio.Lock()


async def rebuild(cfg):
    """Twelve top-of-the-hour sounds from this Deck's announcements and music."""
    async with _building:
        args = [sys.executable, str(REPO_CLOCK / "make_junction.py"), str(sounds_dir(cfg)),
                "--out", str(junction_dir(cfg))]
        music = _slot_files(cfg, "music")
        if music:
            args += ["--music", str(music[0])]
        out = await _run(*args)
        log.info("Clock sounds rebuilt: %s", out.strip().splitlines()[-1] if out.strip() else "")


async def make_face(cfg, media_dir):
    """Draw the face for this station and save it as a numbered still clip."""
    parts = [re.sub(r"[,\n]", " ", v or "").strip() for v in (cfg.clock_call, cfg.clock_town, cfg.clock_web)]
    name_call = re.sub(r"[^A-Za-z0-9]", "", parts[0]) or "Station"
    name = f"{int(cfg.clock_clip):02d}_{name_call}_Clock.png"
    dest = Path(media_dir) / name
    part = Path(media_dir) / f".{name}.part.png"
    await _run(sys.executable, str(REPO_CLOCK / "make_clock.py"), "--station", ",".join(parts),
               "face", str(part), timeout=300)
    part.replace(dest)
    log.info("Clock face made: %s", name)
    return name
