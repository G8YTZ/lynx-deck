"""REST API and web UI.

Endpoint shapes follow Blackmagic's HyperDeck REST API where sensible, so
Companion's generic HTTP module and any HyperDeck-aware tooling feel at home.
Everything here is a client of the same engine the TCP protocol uses.
"""
import asyncio
import logging
import subprocess

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from .engine import ClipNotFound, PlayerUnavailable
from .player import MpvError
from .web_ui import PAGE

log = logging.getLogger(__name__)


def build_app(cfg, engine):
    app = FastAPI(title="Lynx Deck", docs_url="/api/docs")

    def check(token):
        if cfg.api_token and token != cfg.api_token:
            raise HTTPException(status_code=401, detail="bad or missing token")

    def clip_json(c):
        return {"clipIndex": c.id, "name": c.name, "kind": c.kind,
                "codec": c.codec, "durationSeconds": round(c.duration, 3),
                "duration": engine.timecode(c.duration)}

    # ----- pages -----
    @app.get("/", response_class=HTMLResponse)
    async def index():
        return PAGE

    # ----- system -----
    @app.get("/system")
    async def system():
        return {"model": cfg.model, "protocolVersion": cfg.protocol_version,
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

    @app.post("/media/rescan")
    async def rescan(x_lynx_token: str = Header(default=None)):
        check(x_lynx_token)
        await engine.library.scan()
        engine.notify_library_changed()
        return {"clips": len(engine.library.clips)}

    # ----- transport -----
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
        except MpvError:
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
