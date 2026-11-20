"""Everything the SNMP agent serves (tools/lynx-deck-snmp-agent.py, MIB in
mibs/LYNX-MIB.txt, branch lynxDeck), as plain numbers, at /api/health.

The same arrangement as Lynx-Tx's: snmpd runs the agent, the agent asks this
page (cached 5 s), and nothing here waits on anything slow.
"""
import asyncio
import glob
import os
import shutil
import time
from pathlib import Path

PLAYER_STATES = {"ok": 1, "stalled": 2, "restarting": 3}
_sync = {"t": 0.0, "v": 2}


async def time_synced():
    """1 if the Pi's clock is synchronised (NTP), else 2. Cached 30 s."""
    if time.monotonic() - _sync["t"] > 30:
        v = 2
        try:
            p = await asyncio.create_subprocess_exec(
                "timedatectl", "show", "-p", "NTPSynchronized", "--value",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(p.communicate(), 5)
            v = 1 if out.decode().strip() == "yes" else 2
        except Exception:
            v = 1 if Path("/run/systemd/timesync/synchronized").exists() else 2
        _sync.update(t=time.monotonic(), v=v)
    return _sync["v"]


def hdmi_connected(cfg):
    """1 if the Deck's HDMI output sees a monitor or the ATEM, else 2."""
    for p in glob.glob(f"/sys/class/drm/card*-{cfg.drm_connector}/status"):
        try:
            return 1 if Path(p).read_text().strip() == "connected" else 2
        except OSError:
            pass
    return 2


def cpu_temp_deci():
    for z in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
        try:
            if "cpu" in Path(z, "type").read_text() or z.endswith("zone0"):
                return int(Path(z, "temp").read_text()) // 100
        except (OSError, ValueError):
            pass
    return 0


def host(cfg):
    out = {"uptimeS": 0, "cpuLoadPct": 0, "diskFreeMB": 0}
    try:
        out["uptimeS"] = int(float(Path("/proc/uptime").read_text().split()[0]))
        out["cpuLoadPct"] = int(round(os.getloadavg()[0] * 100 / (os.cpu_count() or 1)))
        media = cfg.media_dir if os.path.isdir(cfg.media_dir) else "/"
        out["diskFreeMB"] = shutil.disk_usage(media).free // (1 << 20)
    except (OSError, ValueError):
        pass
    return out


async def snapshot(cfg, engine):
    clip = engine.library.get(engine.clip_id)
    player = PLAYER_STATES.get(engine.player_state, 4)
    if player != 1:
        state = 3                                   # playerFault
    else:
        state = 1 if engine.status == "play" else 2
    counters = await engine.player_health()
    sched = getattr(engine, "scheduler", None)
    on_air, entries = "", 0
    if sched:
        entries = sum(1 for e in sched.entries if e["enabled"])
        found = sched.latest_before(sched.now())
        if found:
            on_air = found[1]["title"] or found[1]["clip"]
    return {
        "deckState": state,
        "playerState": player,
        "clipName": clip.name if clip else "",
        "clipIndex": clip.id if clip else 0,
        "clipCount": len(engine.library.clips),
        "decoderDrops": counters.get("decoderDrops") or 0,
        "lateFrames": counters.get("lateFrames") or 0,
        "playerRestarts": engine.restarts_total,
        "timeSynced": await time_synced(),
        "scheduleEntries": entries,
        "scheduleOnAir": on_air,
        "scheduleCuts": sched.cuts if sched else 0,
        "scheduleMisses": sched.misses if sched else 0,
        "hdmiConnected": hdmi_connected(cfg),
        "cpuTempDeciC": cpu_temp_deci(),
        **host(cfg),
        "version": cfg.version,
        "clockOffsetMs": int(round(float(cfg.clock_offset or 0) * 1000)),
    }
