"""REST API and web UI.

Every endpoint is a client of the same engine the deck protocol uses, so the
web UI, Companion and the TCP protocol can never disagree about state.
"""
import asyncio
import logging
import os
import re
import subprocess
from pathlib import Path

from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import __version__
from .engine import ClipNotFound, PlayerUnavailable
from .library import STILL_EXT, VIDEO_EXT, _probe
from .player import PlayerError
from . import station_clock, sysinfo
from .web_ui import PAGE
from .schedule_ui import PAGE as SCHEDULE_PAGE
from . import scheduler as sched

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")
# what the Pi 4 can actually hardware-decode
OK_CODECS = {"h264", "hevc", "png", "mjpeg"}

log = logging.getLogger(__name__)


def build_app(cfg, engine, deck_server=None, state=None):
    app = FastAPI(title="Lynx Deck", docs_url="/api/docs")

    def check(token):
        if cfg.api_token and token != cfg.api_token:
            raise HTTPException(status_code=401, detail="bad or missing token")

    def resolve(filename):
        """Map a display name back to the real file (uploads sanitise spaces)."""
        name = SAFE_NAME.sub("_", Path(filename).name)
        for c in engine.library.clips:
            if c.name == name or c.path.name == filename:
                return c.path
        path = Path(cfg.media_dir) / name
        return path if path.is_file() else None

    def clip_json(c):
        return {"clipIndex": c.id, "name": c.name, "kind": c.kind,
                "codec": c.codec, "durationSeconds": round(c.duration, 3),
                "duration": engine.timecode(c.duration), "behaviour": c.behaviour}

    # ----- pages -----
    @app.get("/", response_class=HTMLResponse)
    async def index():
        return PAGE

    # ----- system -----
    @app.get("/system")
    async def system():
        return {"model": cfg.model, "protocolVersion": cfg.protocol_version,
                "defaultClip": cfg.default_clip,
                "uniqueId": cfg.unique_id, "softwareVersion": cfg.version,
                "videoFormat": cfg.video_format, "uptimeSeconds": engine.uptime(),
                "player": engine.player_state}

    async def _run(*args, cwd=None, timeout=120):
        """Run a command and return (ok, output)."""
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=cwd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return False, f"{args[0]} timed out"
        return proc.returncode == 0, out.decode("utf-8", "replace").strip()

    async def _dirty(path):
        """Modified tracked files, ignoring the operator's own config.

        A checkout made before the config was untracked would otherwise count
        an edited lynx_deck.yaml as a local change and refuse to update.
        """
        ok, out = await _run("git", "status", "--porcelain",
                             "--untracked-files=no", cwd=path)
        lines = [ln for ln in out.splitlines()
                 if ln.strip() and "config/lynx_deck.yaml" not in ln
                 and "config/state.json" not in ln]
        return ok, "\n".join(lines)

    def repo_dir():
        return cfg.repo_dir or str(Path(__file__).resolve().parent.parent)

    @app.get("/system/output")
    async def output():
        """What the HDMI output is really doing, and what is playing on it."""
        info = await sysinfo.output(cfg)
        clip = engine.library.get(engine.clip_id)
        if clip:
            info["clip"] = {"name": clip.name, "kind": clip.kind,
                            "codec": clip.codec, "behaviour": clip.behaviour}
        return info

    @app.get("/system/network")
    async def network():
        return await sysinfo.network()

    @app.post("/system/wifi")
    async def wifi(body: dict, x_lynx_token: str = Header(default=None)):
        """Block or unblock Wi-Fi. Refuses to disable the link you are using."""
        check(x_lynx_token)
        enabled = bool(body.get("enabled"))
        if not enabled:
            net = await sysinfo.network()
            if not net["ethernetUp"]:
                raise HTTPException(
                    409, "Ethernet is not up - disabling Wi-Fi would cut you off")
        if not await sysinfo.set_wifi(enabled):
            raise HTTPException(500, "rfkill failed - check the sudoers entry")
        return await sysinfo.network()

    @app.get("/system/controllers")
    async def controllers():
        """Companion, ATEM or anything else talking the deck protocol."""
        if deck_server is None:
            return {"controllers": []}
        return {"controllers": deck_server.controllers()}

    @app.get("/settings")
    async def get_settings():
        if state is None:
            raise HTTPException(503, "settings unavailable")
        return state.current()

    @app.put("/settings")
    async def put_settings(body: dict, x_lynx_token: str = Header(default=None)):
        """Change the day-to-day settings; they survive a restart."""
        check(x_lynx_token)
        if state is None:
            raise HTTPException(503, "settings unavailable")
        try:
            applied = state.save(body)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        await engine.library.scan()
        engine.notify_library_changed()
        if {"clockOffset", "clockSecond"} & applied.keys():
            await engine.player.clock_settings()
        log.info("Settings changed: %s", applied)
        return state.current()

    @app.get("/system/update")
    async def update_status():
        """What is installed, and is there anything newer on the remote?"""
        ok, local = await _run("git", "rev-parse", "--short", "HEAD", cwd=repo_dir())
        if not ok:
            return {"version": __version__, "git": None,
                    "detail": "not a git checkout"}
        _, branch = await _run("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=repo_dir())
        _, subject = await _run("git", "log", "-1", "--pretty=%s", cwd=repo_dir())
        _, dirty = await _dirty(repo_dir())
        fetched, fetch_out = await _run("git", "fetch", "--quiet", cwd=repo_dir(), timeout=60)
        behind = 0
        if fetched:
            ok2, counts = await _run("git", "rev-list", "--left-right", "--count",
                                     f"HEAD...origin/{branch}", cwd=repo_dir())
            if ok2 and counts:
                parts = counts.split()
                behind = int(parts[1]) if len(parts) > 1 else 0
        return {"version": __version__, "git": local, "branch": branch,
                "message": subject, "localChanges": bool(dirty),
                "updateAvailable": behind > 0, "commitsBehind": behind,
                "detail": None if fetched else fetch_out}

    @app.post("/system/update")
    async def do_update(x_lynx_token: str = Header(default=None)):
        """Pull the latest code and restart the service.

        Fast-forward only: if the working tree has local changes, or the
        history has diverged, it refuses rather than guessing.
        """
        check(x_lynx_token)
        _, dirty = await _dirty(repo_dir())
        if dirty:
            raise HTTPException(409, f"local changes present:\n{dirty}")
        # if an older checkout still tracks the config, take it out of the way
        tracked, _ = await _run("git", "ls-files", "--error-unmatch",
                                "config/lynx_deck.yaml", cwd=repo_dir())
        if tracked:
            await _run("git", "rm", "--cached", "-q",
                       "config/lynx_deck.yaml", cwd=repo_dir())
            log.warning("Untracked config/lynx_deck.yaml so updates are not blocked")
        ok, out = await _run("git", "pull", "--ff-only", cwd=repo_dir(), timeout=180)
        if not ok:
            raise HTTPException(500, f"update failed:\n{out}")
        _, now = await _run("git", "rev-parse", "--short", "HEAD", cwd=repo_dir())
        if "Already up to date" in out:
            return {"updated": False, "git": now, "detail": out, "restarting": False}
        log.warning("Updated to %s - restarting", now)
        asyncio.get_running_loop().call_later(
            1, lambda: subprocess.Popen(
                ["sudo", "/usr/bin/systemctl", "restart", "lynx-deck"]))
        return {"updated": True, "git": now, "detail": out, "restarting": True}

    @app.post("/system/reboot")
    async def reboot(x_lynx_token: str = Header(default=None)):
        check(x_lynx_token)
        log.warning("Reboot requested via REST API")
        asyncio.get_running_loop().call_later(
            1, lambda: subprocess.Popen(["sudo", "/sbin/shutdown", "-r", "+0"]))
        return {"rebooting": True}

    @app.post("/system/shutdown")
    async def shutdown(x_lynx_token: str = Header(default=None)):
        """Stop cleanly so the card is not left mid-write."""
        check(x_lynx_token)
        log.warning("Shutdown requested via the web interface")
        asyncio.get_running_loop().call_later(
            1, lambda: subprocess.Popen(["sudo", "/sbin/shutdown", "-h", "+0"]))
        return {"shuttingDown": True}

    @app.post("/system/restartPlayer")
    async def restart_player(x_lynx_token: str = Header(default=None)):
        check(x_lynx_token)
        asyncio.create_task(engine._restart_player("requested via REST API"))
        return {"restarting": True}

    # ----- media -----
    @app.get("/media/workingset")
    async def workingset():
        return {"size": len(engine.library.clips),
                "workingset": [clip_json(c) for c in engine.library.clips]}

    @app.put("/media/upload/{filename}")
    async def upload(filename: str, request: Request,
                     x_lynx_token: str = Header(default=None)):
        """Streamed upload: body is the raw file, so large clips need no extra deps.

        Written to a temporary name and only moved into place once probed, so a
        half-uploaded file can never reach air.
        """
        check(x_lynx_token)
        name = SAFE_NAME.sub("_", Path(filename).name)
        ext = Path(name).suffix.lower()
        if ext not in VIDEO_EXT | STILL_EXT:
            raise HTTPException(415, f"unsupported file type {ext}")
        media = Path(cfg.media_dir)
        tmp = media / f".upload-{name}.part"
        limit = cfg.max_upload_mb * 1024 * 1024
        written = 0
        try:
            with open(tmp, "wb") as f:
                async for chunk in request.stream():
                    written += len(chunk)
                    if written > limit:
                        raise HTTPException(413, f"larger than {cfg.max_upload_mb} MB")
                    f.write(chunk)
            if written == 0:
                raise HTTPException(400, "empty upload")
            probe = await _probe(tmp)
            if probe is None:
                raise HTTPException(415, "not a readable media file")
            if probe["codec"] not in OK_CODECS:
                raise HTTPException(415, f"{probe['codec']} is not supported by the Pi 4")
            os.replace(tmp, media / name)
        except HTTPException:
            tmp.unlink(missing_ok=True)
            raise
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            raise HTTPException(500, f"write failed: {exc}")
        await engine.library.scan()
        engine.notify_library_changed()
        log.info("Uploaded %s (%.1f MB, %s)", name, written / 1e6, probe["codec"])
        return {"name": name, "bytes": written, "codec": probe["codec"],
                "clips": len(engine.library.clips)}

    # --- the station clock: this Deck's face and top-of-the-hour sounds -------
    # --- the schedule ------------------------------------------------------
    def schedule():
        s = getattr(engine, "scheduler", None)
        if s is None:
            raise HTTPException(503, "the schedule is not running")
        return s

    @app.get("/schedule", response_class=HTMLResponse)
    async def schedule_page():
        return SCHEDULE_PAGE

    @app.get("/schedule/entries")
    async def schedule_entries():
        s = schedule()
        found = s.latest_before(s.now())
        now = None
        if found:
            at, e = found
            now = {"id": e["id"], "title": e["title"], "clip": e["clip"],
                   "at": at.strftime("%a %H:%M:%S")}
        return {"entries": s.entries, "now": now, "last_fired": s.last_fired,
                "offset": cfg.clock_offset}

    @app.put("/schedule/entries")
    async def schedule_put(body: dict = Body(...), x_lynx_token: str = Header(default=None)):
        check(x_lynx_token)
        try:
            return schedule().put(body)
        except sched.ScheduleError as exc:
            raise HTTPException(400, str(exc))

    @app.delete("/schedule/entries/{entry_id}")
    async def schedule_delete(entry_id: str, x_lynx_token: str = Header(default=None)):
        check(x_lynx_token)
        if not schedule().delete(entry_id):
            raise HTTPException(404, "no such entry")
        return {"deleted": entry_id}

    @app.get("/schedule/programmes")
    async def schedule_programmes():
        """For Lynx-Tx's guide (epg.py): the programme slots, Companion's way."""
        return {"programmes": schedule().programmes(), "source": "Lynx Deck"}

    @app.get("/schedule/guide")
    async def schedule_guide(hours: int = 24 * 8):
        g = schedule().guide(days=max(1, hours) / 24)
        return {"guide": g}

    @app.post("/schedule/import")
    async def schedule_import(request: Request, companion: str = "",
                              x_lynx_token: str = Header(default=None)):
        """Companion's EPG: triggers, from its address or an uploaded export."""
        check(x_lynx_token)
        try:
            if companion:
                triggers = await asyncio.to_thread(sched.fetch_companion, companion)
            else:
                data = await request.body()
                triggers = sched.load_export(data)
        except Exception as exc:
            raise HTTPException(400, f"could not read Companion's triggers: {exc}")
        s = schedule()
        new, notes = sched.from_companion(triggers, engine.library.clips)
        have = {(e["repeat"], e["time"], tuple(e["days"]), e["title"]) for e in s.entries}
        added = skipped = 0
        for e in new:
            if (e["repeat"], e["time"], tuple(e["days"]), e["title"]) in have:
                skipped += 1
                continue
            s.put(e)
            added += 1
        return {"added": added, "skipped": skipped, "notes": notes}

    @app.get("/clock")
    async def clock_status():
        return station_clock.status(cfg)

    @app.put("/clock/sound/{filename}")
    async def clock_sound(filename: str, request: Request, rebuild: int = 1,
                          x_lynx_token: str = Header(default=None)):
        """An announcement (name ending 1..12) or the music; rebuilds the sounds
        unless ?rebuild=0 (the page sends a batch, then asks once)."""
        check(x_lynx_token)
        name = SAFE_NAME.sub("_", Path(filename).name)
        tmp = Path(cfg.clock_dir) / f".upload-{name}"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        try:
            with open(tmp, "wb") as f:
                async for chunk in request.stream():
                    written += len(chunk)
                    if written > 50 * 1024 * 1024:
                        raise HTTPException(413, "larger than 50 MB")
                    f.write(chunk)
            slot = await station_clock.save_sound(cfg, name, tmp)
            if rebuild:
                await station_clock.rebuild(cfg)
        except station_clock.ClockError as exc:
            raise HTTPException(400, str(exc))
        except OSError as exc:
            raise HTTPException(500, f"write failed: {exc}")
        finally:
            tmp.unlink(missing_ok=True)
        return {"slot": slot, **station_clock.status(cfg)}

    @app.post("/clock/rebuild")
    async def clock_rebuild(x_lynx_token: str = Header(default=None)):
        check(x_lynx_token)
        try:
            await station_clock.rebuild(cfg)
        except station_clock.ClockError as exc:
            raise HTTPException(500, str(exc))
        return station_clock.status(cfg)

    @app.delete("/clock/sound/{slot}")
    async def clock_sound_delete(slot: str, x_lynx_token: str = Header(default=None)):
        check(x_lynx_token)
        key = "music" if slot == "music" else int(slot) if slot.isdigit() and 1 <= int(slot) <= 12 else None
        if key is None or not station_clock.delete_sound(cfg, key):
            raise HTTPException(404, "no such sound")
        try:
            await station_clock.rebuild(cfg)
        except station_clock.ClockError as exc:
            raise HTTPException(500, str(exc))
        return station_clock.status(cfg)

    @app.post("/clock/face")
    async def clock_face(x_lynx_token: str = Header(default=None)):
        """Draw the face with the saved call sign, town and web address."""
        check(x_lynx_token)
        try:
            name = await station_clock.make_face(cfg, cfg.media_dir)
        except station_clock.ClockError as exc:
            raise HTTPException(500, f"could not draw the face: {exc}")
        await engine.library.scan()
        engine.notify_library_changed()
        return {"name": name, "clips": len(engine.library.clips)}

    @app.delete("/media/{filename}")
    async def delete_media(filename: str, x_lynx_token: str = Header(default=None)):
        check(x_lynx_token)
        path = resolve(filename)
        if path is None:
            raise HTTPException(404, "no such file")
        name = path.name
        path.unlink()
        await engine.library.scan()
        engine.notify_library_changed()
        return {"deleted": name, "clips": len(engine.library.clips)}

    @app.put("/media/{filename}/behaviour")
    async def set_behaviour(filename: str, body: dict,
                            x_lynx_token: str = Header(default=None)):
        """Per-clip behaviour: auto | once | loop | hold, and still duration."""
        check(x_lynx_token)
        path = resolve(filename)
        if path is None:
            raise HTTPException(404, "no such file")
        try:
            engine.library.set_behaviour(path.name, body.get("behaviour"),
                                         body.get("duration"))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        await engine.library.scan()
        engine.notify_library_changed()
        return {"name": path.name, "behaviour": body.get("behaviour")}

    @app.put("/transports/0/settings")
    async def settings(body: dict):
        """Set loop / single clip without starting or stopping playback."""
        try:
            await engine.set_flags(loop=body.get("loop"),
                                   single_clip=body.get("singleClip"))
        except PlayerUnavailable:
            raise HTTPException(503, "player restarting")
        return await transport()

    @app.post("/media/rescan")
    async def rescan(x_lynx_token: str = Header(default=None)):
        check(x_lynx_token)
        await engine.library.scan()
        engine.notify_library_changed()
        return {"clips": len(engine.library.clips)}

    # ----- transport -----
    @app.get("/player/health")
    async def player_health():
        """Counters that mean something: both should stay at zero."""
        return {"state": engine.player_state, **(await engine.player_health())}

    @app.get("/transports/0")
    async def transport():
        info = engine.transport_info()
        return {"status": info["status"], "speed": int(info["speed"]),
                "clipIndex": engine.clip_id, "loop": engine.loop,
                "singleClip": engine.single_clip, "timecode": info["timecode"],
                "positionSeconds": round(engine.position, 3),
                "player": engine.player_state}

    @app.put("/transports/0/play")
    async def play(body: dict | None = None):
        body = body or {}
        try:
            await engine.play(speed=int(body.get("speed", 100)),
                              loop=body.get("loop"),
                              single_clip=body.get("singleClip"))
        except ClipNotFound:
            raise HTTPException(404, "no such clip")
        except PlayerUnavailable:
            raise HTTPException(503, "player restarting")
        except PlayerError:
            raise HTTPException(500, "player error")
        return await transport()

    @app.put("/transports/0/stop")
    async def stop():
        try:
            await engine.stop()
        except PlayerUnavailable:
            raise HTTPException(503, "player restarting")
        return await transport()

    @app.put("/transports/0/clipIndex")
    async def set_clip(body: dict):
        try:
            await engine.goto_clip(int(body["clipIndex"]))
        except (KeyError, ValueError):
            raise HTTPException(400, "clipIndex required")
        except ClipNotFound:
            raise HTTPException(404, "no such clip")
        except PlayerUnavailable:
            raise HTTPException(503, "player restarting")
        return await transport()

    @app.exception_handler(PlayerUnavailable)
    async def unavailable(request, exc):
        return JSONResponse({"detail": "player restarting"}, status_code=503)

    return app


async def serve(cfg, engine, deck_server=None, state=None):
    import uvicorn
    app = build_app(cfg, engine, deck_server, state)
    config = uvicorn.Config(app, host="0.0.0.0", port=cfg.http_port,
                            log_level="warning", access_log=False)

    class Server(uvicorn.Server):
        def install_signal_handlers(self):
            """Leave signals to the main loop.

            uvicorn would otherwise capture SIGTERM for itself, so our own
            shutdown never runs and systemd waits out the full timeout before
            resorting to SIGKILL.
            """

    server = Server(config)
    log.info("Web UI and REST API on http://0.0.0.0:%d", cfg.http_port)
    await server.serve()
