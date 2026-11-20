"""The schedule: cut to a clip at a time of day, or every hour at mm:ss.

The Deck's own version of the Companion time-of-day triggers it replaces.
An entry is a time, the days it runs and a clip; what happens after the cut
is the clip's own behaviour (hold, loop, once, auto), as before. Entries
ticked "in the guide" are programmes in the EPG (their title, and a length if
not an hour), as Companion's "EPG:" triggers were; the rest (the clock,
idents) are scheduled but kept out of the guide.

Times are on-air times: the Deck cuts early by the clock's "ahead by"
setting, so a 19:00 programme reaches viewers at 19:00.

After a restart the Deck rejoins what should be on air: the latest entry
before now, part way in, if its clip would still be running; otherwise the
default slide.

Kept in schedule.json beside the Deck's state file. Days are 0 = Monday.
"""
import asyncio
import datetime as dt
import json
import logging
import re
import time
import uuid
from pathlib import Path

log = logging.getLogger(__name__)

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
EVERY_DAY = list(range(7))
TICK = 0.2                     # seconds between looks at the clock
CLOCK_FADE = 1.0               # the clock fades to black this long before a scheduled cut
DEFAULT_MINUTES = 60           # a guide entry with no length given


class ScheduleError(ValueError):
    pass


def parse_time(text, hourly):
    """'19:00' or '19:00:30' (daily); '58:56' (hourly, mm:ss). -> seconds."""
    parts = [p for p in str(text).strip().split(":")]
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        raise ScheduleError(f"time {text!r}: use numbers like 19:00 or 58:56")
    if hourly:
        if len(nums) != 2 or not (0 <= nums[0] < 60 and 0 <= nums[1] < 60):
            raise ScheduleError(f"hourly time {text!r}: use mm:ss, such as 58:56")
        return nums[0] * 60 + nums[1]
    if len(nums) == 2:
        nums.append(0)
    if len(nums) != 3 or not (0 <= nums[0] < 24 and 0 <= nums[1] < 60 and 0 <= nums[2] < 60):
        raise ScheduleError(f"time {text!r}: use hh:mm or hh:mm:ss, such as 19:00")
    return nums[0] * 3600 + nums[1] * 60 + nums[2]


def clean(entry):
    """Check and normalise one entry from the web page or an import."""
    e = dict(entry)
    hourly = e.get("repeat") == "hourly"
    secs = parse_time(e.get("time", ""), hourly)
    if hourly:
        e["time"] = f"{secs // 60:02d}:{secs % 60:02d}"
    else:
        e["time"] = f"{secs // 3600:02d}:{secs // 60 % 60:02d}:{secs % 60:02d}"
    raw = EVERY_DAY if e.get("days") is None else e["days"]
    days = sorted({int(d) for d in raw if 0 <= int(d) <= 6})
    if not days:
        raise ScheduleError("pick at least one day")
    title = str(e.get("title") or "").strip()
    clip = str(e.get("clip") or "").strip()
    guide = bool(e.get("guide", bool(title)))     # older entries: a title meant "in the guide"
    if guide and not title:
        title = re.sub(r"[_]+", " ", Path(clip).stem).strip() if clip else ""
        if not title:
            raise ScheduleError("an entry in the guide needs a title (or a clip to take one from)")
    minutes = e.get("minutes")
    minutes = int(minutes) if minutes not in (None, "", 0, "0") else None
    if minutes is not None and not 1 <= minutes <= 24 * 60:
        raise ScheduleError("guide length must be 1 to 1440 minutes")
    return {
        "id": str(e.get("id") or uuid.uuid4().hex[:8]),
        "repeat": "hourly" if hourly else "daily",
        "time": e["time"],
        "days": days,
        "clip": clip,
        "guide": guide,
        "title": title,
        "minutes": minutes,
        "enabled": bool(e.get("enabled", True)),
    }


def occurrences(entry, start, end):
    """Local datetimes in (start, end] at which this entry fires."""
    hourly = entry["repeat"] == "hourly"
    secs = parse_time(entry["time"], hourly)
    out = []
    day = start.date()
    while day <= end.date():
        if day.weekday() in entry["days"]:
            midnight = dt.datetime.combine(day, dt.time())
            if hourly:
                first = max(0, (start - midnight).seconds // 3600 - 1) if day == start.date() else 0
                last = 23 if day < end.date() else end.hour
                for h in range(first, last + 1):
                    t = midnight + dt.timedelta(hours=h, seconds=secs)
                    if start < t <= end:
                        out.append(t)
            else:
                t = midnight + dt.timedelta(seconds=secs)
                if start < t <= end:
                    out.append(t)
        day += dt.timedelta(days=1)
    return out


class Scheduler:
    def __init__(self, cfg, engine, path=None):
        self.cfg = cfg
        self.engine = engine
        self.path = Path(path or Path(cfg.state_file).with_name("schedule.json"))
        self.entries = []
        self.last_fired = None          # {"id", "at", "clip"} for the web page
        self._task = None
        self._last = None
        self._faded_for = None
        self.cuts = 0                   # scheduled cuts made (SNMP)
        self.misses = 0                 # scheduled cuts that could not be made
        self.load()

    # ----- the list ------------------------------------------------------

    def load(self):
        try:
            data = json.loads(self.path.read_text())
            self.entries = [clean(e) for e in data.get("entries", [])]
        except FileNotFoundError:
            self.entries = []
        except (OSError, ValueError) as exc:
            log.error("Could not read %s: %s", self.path, exc)
            self.entries = []

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"entries": self.entries}, indent=1))
        tmp.replace(self.path)

    def put(self, entry):
        e = clean(entry)
        self.entries = [x for x in self.entries if x["id"] != e["id"]] + [e]
        self.entries.sort(key=self._sort_key)
        self.save()
        return e

    def delete(self, entry_id):
        before = len(self.entries)
        self.entries = [x for x in self.entries if x["id"] != entry_id]
        self.save()
        return len(self.entries) != before

    @staticmethod
    def _sort_key(e):
        hourly = e["repeat"] == "hourly"
        return (0 if hourly else 1, parse_time(e["time"], hourly), e["title"])

    # ----- time ----------------------------------------------------------

    def now(self):
        """On-air time: the Deck cuts early by the delay to air."""
        return dt.datetime.fromtimestamp(time.time() + float(self.cfg.clock_offset or 0))

    def clip_id(self, name):
        for c in self.engine.library.clips:
            if name in (c.path.name, c.name):
                return c.id
        return None

    # ----- running -------------------------------------------------------

    def start(self):
        self._task = asyncio.create_task(self._run())

    async def close(self):
        if self._task:
            self._task.cancel()

    async def _run(self):
        try:
            await self.rejoin()
        except Exception:
            log.exception("Schedule: could not rejoin after start")
        self._last = self.now()
        while True:
            await asyncio.sleep(TICK)
            now = self.now()
            if now < self._last or (now - self._last).total_seconds() > 120:
                log.warning("Schedule: the clock jumped (%s to %s); not catching up",
                            self._last.strftime("%H:%M:%S"), now.strftime("%H:%M:%S"))
                self._last = now
                continue
            due, soon = [], []
            ahead = now + dt.timedelta(seconds=CLOCK_FADE)
            for e in self.entries:
                if e["enabled"] and e["clip"]:
                    due += [(t, e) for t in occurrences(e, self._last, now)]
                    soon += occurrences(e, now, ahead)
            self._last = now
            if soon:
                await self._fade_clock(min(soon), now)
            if due:
                t, e = max(due, key=lambda d: d[0])   # two at once: the later wins
                await self.fire(e, t)

    async def _fade_clock(self, cut, now):
        """If the clock is on screen, fade it to black just before the cut."""
        if self._faded_for == cut:
            return
        clip = self.engine.library.get(self.engine.clip_id)
        if clip is None or clip.kind != "still" or not clip.path.stem.lower().endswith("clock"):
            return
        self._faded_for = cut
        left = max(0.1, (cut - now).total_seconds())
        try:
            await self.engine.player.command("script-message", "lynxclock-fadeout", f"{left:.2f}")
        except Exception as exc:
            log.warning("Schedule: could not fade the clock: %s", exc)

    async def fire(self, entry, at, resume=0.0):
        cid = self.clip_id(entry["clip"])
        what = entry["title"] or entry["clip"]
        if cid is None:
            self.misses += 1
            log.warning("Schedule %s %s: clip %s is not in the library",
                        at.strftime("%H:%M:%S"), what, entry["clip"])
            return
        try:
            await self.engine.scheduled_play(cid, resume=resume)
            self.cuts += 1
            self.last_fired = {"id": entry["id"], "at": at.strftime("%a %H:%M:%S"),
                               "clip": entry["clip"], "resume": round(resume)}
            log.info("Schedule %s: %s%s", at.strftime("%H:%M:%S"), what,
                     f" (rejoined {resume:.0f} s in)" if resume else "")
        except Exception as exc:
            self.misses += 1
            log.error("Schedule %s %s: could not play %s: %s",
                      at.strftime("%H:%M:%S"), what, entry["clip"], exc)

    def latest_before(self, now, horizon_hours=48):
        """The most recent (time, entry) before now, if any."""
        start = now - dt.timedelta(hours=horizon_hours)
        best = None
        for e in self.entries:
            if not (e["enabled"] and e["clip"]):
                continue
            ts = occurrences(e, start, now)
            if ts and (best is None or ts[-1] > best[0]):
                best = (ts[-1], e)
        return best

    async def rejoin(self):
        """After a restart, put on what the schedule says should be on air now."""
        now = self.now()
        found = self.latest_before(now)
        if not found:
            return
        at, e = found
        cid = self.clip_id(e["clip"])
        clip = self.engine.library.get(cid) if cid else None
        if clip is None:
            return
        elapsed = (now - at).total_seconds()
        if e["guide"] and elapsed > 60 * (e["minutes"] or DEFAULT_MINUTES):
            log.info("Schedule: %s has finished; staying on the default slide", e["title"])
            return
        if clip.kind == "still":
            running = clip.behaviour == "hold" or clip.behaviour == "loop" or elapsed < clip.duration
            resume = 0.0
        elif clip.behaviour == "loop" and clip.duration > 0:
            running, resume = True, elapsed % clip.duration
        else:
            running, resume = elapsed < clip.duration - 2, elapsed
        if running:
            await self.fire(e, at, resume=resume)
        else:
            log.info("Schedule: %s would have ended; staying on the default slide",
                     e["title"] or e["clip"])

    # ----- the guide -----------------------------------------------------

    def programmes(self):
        """The guide's programme slots in the form Lynx-Tx's epg.py builds
        from Companion (title, minutes, hh, mm, days with 0 = Sunday), so
        Lynx-Tx can read the Deck instead. An hourly entry is 24 slots."""
        out = []
        for e in self.entries:
            if not (e["enabled"] and e["guide"]):
                continue
            hourly = e["repeat"] == "hourly"
            secs = parse_time(e["time"], hourly)
            hours = range(24) if hourly else [secs // 3600]
            mm = (secs // 60) % 60
            for hh in hours:
                out.append({"title": e["title"], "minutes": e["minutes"], "hh": hh, "mm": mm,
                            "days": sorted((d + 1) % 7 for d in e["days"]), "trigger": e["id"]})
        out.sort(key=lambda p: (p["hh"], p["mm"], p["title"]))
        return out


    def guide(self, days=8):
        """Programmes (entries with a title) from now for `days`, as
        epg.py builds them from Companion: start, minutes, title; a programme
        never runs into the next one."""
        now = self.now()
        start = now - dt.timedelta(hours=24)
        end = now + dt.timedelta(days=days)
        slots = []
        for e in self.entries:
            if e["enabled"] and e["guide"]:
                slots += [(t, e) for t in occurrences(e, start, end)]
        slots.sort(key=lambda s: s[0])
        out = []
        for i, (t, e) in enumerate(slots):
            stop = t + dt.timedelta(minutes=e["minutes"] or DEFAULT_MINUTES)
            if i + 1 < len(slots) and slots[i + 1][0] < stop:
                stop = slots[i + 1][0]
            if stop <= now or stop <= t:
                continue
            out.append({"start": t.astimezone().isoformat(timespec="seconds"),
                        "minutes": int((stop - t).total_seconds() // 60),
                        "title": e["title"]})
        return out


# ----- importing Companion's EPG triggers --------------------------------

def load_export(data):
    """Triggers from a Companion export: YAML (Companion 5's own format) or
    JSON, possibly gzipped."""
    import gzip
    import yaml
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    text = data.decode("utf-8", errors="replace")
    try:
        doc = json.loads(text)
    except ValueError:
        doc = yaml.safe_load(text)
    triggers = (doc or {}).get("triggers") if isinstance(doc, dict) else None
    if not isinstance(triggers, dict):
        raise ValueError("no triggers in that file")
    return triggers


def fetch_companion(address, timeout=10.0):
    """Triggers straight from Companion (5.1: its own Export address)."""
    import urllib.request
    base = address.strip().rstrip("/")
    if not base.startswith("http"):
        base = "http://" + base
    last = None
    for path in ("/int/export/triggers/all?format=json&includeSecrets=false",
                 "/int/export/full?format=json"):
        try:
            with urllib.request.urlopen(base + path, timeout=timeout) as r:
                return load_export(r.read())
        except Exception as exc:
            last = exc
    raise RuntimeError(f"Companion at {address} did not answer: {last}")


MARK = re.compile(r"^\s*EPG(?::|\s)\s*(.+?)\s*$", re.I)
LENGTH = re.compile(r"\s*\(\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m(?:in)?)?\s*\)\s*$", re.I)


def _value(v):
    """Companion 5 wraps options as {"value": ..., "isExpression": ...}."""
    return v.get("value") if isinstance(v, dict) and "value" in v else v


def _event_seconds(t):
    """Companion's time of day: "19:00:15", or seconds since midnight."""
    if isinstance(t, (int, float)):
        return int(t) % 86400
    parts = [int(x) for x in str(t).strip().split(":")]
    while len(parts) < 3:
        parts.append(0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def _actions(lst):
    for a in lst or []:
        yield a
        for children in (a.get("children") or {}).values():
            yield from _actions(children)


def _clip_from_actions(trigger, clips):
    """The clip a trigger cuts to: a HyperDeck "go to clip by name" (the
    name), or "go to clip" by number (looked up in this Deck's list)."""
    by_id = {c.id: c.path.name for c in clips}
    for a in _actions(trigger.get("actions")):
        did = str(a.get("definitionId") or "")
        clip = _value((a.get("options") or {}).get("clip"))
        if clip in (None, ""):
            continue
        if did == "gotoName" or (isinstance(clip, str) and not clip.strip().isdigit()):
            return str(clip).strip()
        if did.startswith("goto"):
            try:
                return by_id.get(int(clip))
            except (TypeError, ValueError):
                pass
    return None


def from_companion(triggers, clips):
    """Schedule entries from Companion's enabled time-of-day triggers that cut
    the Deck to a clip. "EPG:" ones become programmes in the guide (title and
    length from the name, as Lynx-Tx's epg.py reads them); the rest (the
    clock) are scheduled but kept out of the guide. The same clip at the same
    minutes and seconds past every hour of the day becomes one hourly entry.
    Returns (entries, notes)."""
    names = {c.path.name for c in clips} | {c.name for c in clips}
    found, notes = [], []
    for tid, t in (triggers or {}).items():
        opts = t.get("options") or {}
        if not opts.get("enabled", True):
            continue
        events = [e for e in (t.get("events") or [])
                  if e.get("type") == "timeofday" and e.get("enabled", True)]
        if not events:
            continue
        clip = _clip_from_actions(t, clips)
        name = str(opts.get("name") or "")
        m = MARK.match(name)
        title, minutes = (m.group(1), None) if m else ("", None)
        if m:
            lm = LENGTH.search(title)
            if lm and (lm.group(1) or lm.group(2)):
                minutes = int(lm.group(1) or 0) * 60 + int(lm.group(2) or 0)
                title = title[:lm.start()].rstrip()
        if not clip:
            if m:
                notes.append(f"{title}: its actions name no clip; choose one")
            else:
                continue                      # not a playout trigger
        for ev in events:
            o = ev.get("options") or {}
            try:
                secs = _event_seconds(o.get("time", ""))
            except ValueError:
                notes.append(f"{name}: time {o.get('time')!r} not understood")
                continue
            days = sorted({(int(d) + 6) % 7 for d in (o.get("days") or []) if 0 <= int(d) <= 6})
            if days:
                found.append({"secs": secs, "days": days, "clip": clip or "",
                              "title": title, "minutes": minutes})
    # collapse "the same thing at mm:ss past every hour" into one hourly entry
    groups = {}
    for f in found:
        key = (f["clip"], f["title"], f["minutes"], tuple(f["days"]), f["secs"] % 3600)
        groups.setdefault(key, set()).add(f["secs"] // 3600)
    entries = []
    for (clip, title, minutes, days, mmss), hours in groups.items():
        on = bool(clip) and clip in names
        if clip and clip not in names:
            notes.append(f"{title or clip}: {clip} is not on this Deck; added switched off")
        base = {"clip": clip, "title": title, "guide": bool(title), "minutes": minutes,
                "days": list(days), "enabled": on}
        if len(hours) == 24:
            entries.append(clean({**base, "repeat": "hourly",
                                  "time": f"{mmss // 60:02d}:{mmss % 60:02d}"}))
        else:
            for h in sorted(hours):
                secs = h * 3600 + mmss
                entries.append(clean({**base, "repeat": "daily",
                                      "time": f"{secs // 3600:02d}:{secs // 60 % 60:02d}:{secs % 60:02d}"}))
    entries.sort(key=Scheduler._sort_key)
    return entries, sorted(set(notes))
