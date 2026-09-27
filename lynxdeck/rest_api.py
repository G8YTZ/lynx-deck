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

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .engine import ClipNotFound, PlayerUnavailable
from .library import STILL_EXT, VIDEO_EXT, _probe
from .player import PlayerError
from .web_ui import PAGE

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")
# what the Pi 4 can actually hardware-decode
OK_CODECS = {"h264", "hevc", "png", "mjpeg"}

log = logging.getLogger(__name__)


def build_app(cfg, engine):
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

    @app.post("/system/reboot")
    async def reboot(x_lynx_token: str = Header(default=None)):
        check(x_lynx_token)
        log.warning("Reboot requested via REST API")
        asyncio.get_running_loop().call_later(
            1, lambda: subprocess.Popen(["sudo", "/sbin/shutdown", "-r", "+0"]))
        return {"rebooting": True}

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


async def serve(cfg, engine):
    import uvicorn
    app = build_app(cfg, engine)
    config = uvicorn.Config(app, host="0.0.0.0", port=cfg.http_port,
                            log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    log.info("Web UI and REST API on http://0.0.0.0:%d", cfg.http_port)
    await server.serve()
