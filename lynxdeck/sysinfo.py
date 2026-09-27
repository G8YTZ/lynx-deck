"""What the deck is actually doing, read from the system rather than config.

The config says what we asked for; these report what we got. A mismatch
between the two is exactly the sort of thing that should be visible at a
glance rather than discovered at a repeater site.
"""
import asyncio
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

DRM = Path("/sys/class/drm")


async def _run(*args, timeout=10):
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except (FileNotFoundError, asyncio.TimeoutError):
        return False, ""
    return proc.returncode == 0, out.decode("utf-8", "replace")


async def output(cfg):
    """The real HDMI state: connected, resolution and refresh rate."""
    info = {"connector": cfg.drm_connector, "connected": False,
            "mode": None, "refresh": None, "configured": cfg.video_format}
    base = DRM / f"card1-{cfg.drm_connector}"
    if not base.exists():
        for cand in DRM.glob(f"card*-{cfg.drm_connector}"):
            base = cand
            break
    try:
        info["connected"] = (base / "status").read_text().strip() == "connected"
        modes = (base / "modes").read_text().split()
        if modes:
            info["mode"] = modes[0]
    except OSError:
        pass
    # Which mode is in use cannot be read from the CRTC while the player
    # holds DRM master, so use the connector's mode list instead. A "userdef"
    # mode is one created by a video= kernel argument, which is how the output
    # standard is set here - so that is the one we are running. The
    # "preferred" flag is only the monitor's own EDID opinion.
    ok, out = await _run("modetest", "-M", "vc4", "-c")
    if ok:
        section, first = False, None
        for line in out.splitlines():
            if re.match(r"\d+\s+\d+\s+(dis)?connected\s+", line):
                section = cfg.drm_connector in line
                continue
            if not section:
                continue
            m = re.match(r"\s+#(\d+)\s+(\d+x\d+)\s+([\d.]+)", line)
            if not m:
                continue
            if first is None:
                first = (m.group(2), float(m.group(3)))
            if "userdef" in line:
                info["mode"], info["refresh"] = m.group(2), float(m.group(3))
                info["source"] = "set at boot"
                break
        if info["refresh"] is None and first:
            info["mode"], info["refresh"] = first
            info["source"] = "monitor preferred"
    return info


async def network():
    """Interfaces that are up, with their addresses."""
    ok, out = await _run("ip", "-o", "-4", "addr", "show")
    ifaces = []
    if ok:
        for line in out.splitlines():
            parts = line.split()
            if len(parts) > 3 and parts[1] != "lo":
                ifaces.append({"name": parts[1], "address": parts[3].split("/")[0]})
    ok, out = await _run("ip", "-o", "link", "show")
    states = {}
    if ok:
        for line in out.splitlines():
            m = re.match(r"\d+:\s+([^:@]+).*state (\w+)", line)
            if m:
                states[m.group(1)] = m.group(2)
    for i in ifaces:
        i["state"] = states.get(i["name"], "unknown")
    ok, out = await _run("rfkill", "list", "wifi")
    wifi_blocked = "yes" in out.lower().split("soft blocked:")[-1][:6] if ok else None
    return {"interfaces": ifaces, "wifiBlocked": wifi_blocked,
            "ethernetUp": any(i["name"].startswith("e") and i["state"] == "UP"
                              for i in ifaces)}


async def set_wifi(enabled):
    """Block or unblock the Wi-Fi radio."""
    action = "unblock" if enabled else "block"
    ok, _ = await _run("sudo", "/usr/sbin/rfkill", action, "wifi")
    if not ok:
        ok, _ = await _run("sudo", "rfkill", action, "wifi")
    return ok
