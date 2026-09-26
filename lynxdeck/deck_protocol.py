"""Deck control protocol server (TCP 9993), playback subset.

Implements the widely used text-based deck control protocol that Bitfocus
Companion and ATEM switchers speak, so Lynx Deck drops into an existing
workflow without changes at the controller end.

Accepts both single-line ("play: speed: 100 loop: true") and multi-line
("play:\\nspeed: 100\\n\\n") command forms. Replies use CRLF line endings.
"""
import asyncio
import logging
import re

from .engine import ClipNotFound, PlayerUnavailable
from .player import MpvError

log = logging.getLogger(__name__)

PARAM_KEYS = [
    "single clip", "clip id", "slot id", "speed", "loop", "enable", "override",
    "transport", "slot", "remote", "configuration", "dropped frames",
    "display timecode", "timeline position", "playrange", "cache",
    "dynamic range", "slate", "clip", "timecode", "timeline", "period",
    "count", "in", "out", "name", "video input", "audio input", "file format",
]
_KEY_RE = re.compile(
    r"(?:^|\s)(" + "|".join(re.escape(k) for k in sorted(PARAM_KEYS, key=len, reverse=True))
    + r"):\s*", re.IGNORECASE)

NOTIFY_KEYS = ["transport", "slot", "remote", "configuration", "dropped frames",
               "display timecode", "timeline position", "playrange", "cache",
               "dynamic range", "slate", "clip"]

UNSUPPORTED = {"record", "record spill", "format", "jog", "shuttle", "clips add",
               "clips clear", "identify", "slot unblock", "nas"}
ACCEPTED_NOOP = {"ping", "watchdog", "slot select", "preview", "playrange",
                 "playrange set", "playrange clear"}

CODEC_LABEL = {"h264": "H.264", "hevc": "H.265", "png": "Still", "mjpeg": "Still"}


def parse_line(line):
    """'goto: clip id: 3' -> ('goto', {'clip id': '3'})"""
    if ":" not in line:
        return line.strip().lower(), {}
    cmd, rest = line.split(":", 1)
    parts = _KEY_RE.split(rest)
    params = {parts[i].lower(): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    return cmd.strip().lower(), params


def block(code, title, fields=None, lines=None):
    out = [f"{code} {title}:"]
    out += [f"{k}: {v}" for k, v in (fields or {}).items()]
    out += lines or []
    return "\r\n".join(out) + "\r\n\r\n"


def simple(code, text):
    return f"{code} {text}\r\n"


def as_bool(value):
    return value.strip().lower() in ("true", "1", "yes")


class Session:
    def __init__(self, writer):
        self.writer = writer
        self.notify = {k: False for k in NOTIFY_KEYS}
        self.peer = writer.get_extra_info("peername")
        self.busy = False      # while a command runs, async messages wait
        self.deferred = []     # so the reply always precedes the 508 it caused

    def send(self, text):
        if not self.writer.is_closing():
            self.writer.write(text.encode())


class DeckServer:
    def __init__(self, cfg, engine):
        self.cfg = cfg
        self.engine = engine
        self.sessions = set()
        self.server = None
        engine.add_listener(self._on_transport_change)

    async def start(self):
        self.server = await asyncio.start_server(
            self._handle, host="0.0.0.0", port=self.cfg.hyperdeck_port)
        log.info("Deck protocol listening on TCP %d", self.cfg.hyperdeck_port)

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for s in list(self.sessions):
            s.writer.close()

    def _on_transport_change(self):
        text = block(508, "transport info", self.engine.transport_info())
        for s in list(self.sessions):
            if s.notify["transport"]:
                if s.busy:
                    s.deferred.append(text)
                else:
                    s.send(text)

    async def _handle(self, reader, writer):
        s = Session(writer)
        self.sessions.add(s)
        log.info("Client connected: %s", s.peer)
        s.send(block(500, "connection info", {
            "protocol version": self.cfg.protocol_version,
            "model": self.cfg.model,
        }))
        multi_cmd, multi_params = None, {}
        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", "replace").strip()
                if multi_cmd is not None:            # inside a multi-line command
                    if line:
                        k, _, v = line.partition(":")
                        multi_params[k.strip().lower()] = v.strip()
                        continue
                    cmd, params, multi_cmd = multi_cmd, multi_params, None
                elif not line:
                    continue
                elif line.endswith(":") and line.count(":") == 1:
                    multi_cmd, multi_params = line[:-1].strip().lower(), {}
                    continue
                else:
                    cmd, params = parse_line(line)
                log.debug("%s -> %s %s", s.peer, cmd, params)
                if cmd == "quit":
                    break
                s.busy = True
                try:
                    reply = await self._dispatch(s, cmd, params)
                finally:
                    s.busy = False
                s.send(reply)
                for text in s.deferred:
                    s.send(text)
                s.deferred.clear()
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            self.sessions.discard(s)
            writer.close()
            log.info("Client disconnected: %s", s.peer)

    async def _dispatch(self, s, cmd, p):
        e = self.engine
        lib = e.library
        try:
            if cmd in ACCEPTED_NOOP:
                return simple(200, "ok")
            if cmd in UNSUPPORTED:
                return simple(103, "unsupported")
            if cmd in ("help", "?"):
                return block(201, "help", lines=[
                    "play, stop, goto, transport info, clips get, clips count,",
                    "disk list, slot info, device info, notify, remote, ping, quit"])
            if cmd == "device info":
                return block(204, "device info", {
                    "protocol version": self.cfg.protocol_version,
                    "model": self.cfg.model,
                    "unique id": self.cfg.unique_id,
                    "slot count": "1",
                    "software version": "LynxDeck 0.1",
                })
            if cmd == "slot info":
                return block(202, "slot info", {
                    "slot id": "1", "status": "mounted",
                    "volume name": self.cfg.volume_name,
                    "recording time": "0", "video format": self.cfg.video_format,
                })
            if cmd == "disk list":
                return block(206, "disk list", {"slot id": "1"}, [
                    f"{c.id}: {c.name} {CODEC_LABEL.get(c.codec, c.codec)} "
                    f"{self.cfg.video_format} {e.timecode(c.duration)}"
                    for c in lib.clips])
            if cmd == "clips count":
                return block(214, "clips count", {"clip count": str(len(lib.clips))})
            if cmd == "clips get":
                first = int(p.get("clip id", 1))
                count = int(p.get("count", len(lib.clips)))
                chosen = [c for c in lib.clips if first <= c.id < first + count]
                return block(205, "clips info", {"clip count": str(len(chosen))}, [
                    f"{c.id}: {c.name} 00:00:00:00 {e.timecode(c.duration)}"
                    for c in chosen])
            if cmd == "transport info":
                return block(208, "transport info", e.transport_info())
            if cmd == "play":
                speed = int(p.get("speed", 100))
                if speed == 0:
                    await e.stop()
                    return simple(200, "ok")
                if speed < 0 or speed > 1600:
                    return simple(103, "unsupported")   # reverse play not in v1
                await e.play(speed=speed,
                             loop=as_bool(p["loop"]) if "loop" in p else None,
                             single_clip=as_bool(p["single clip"]) if "single clip" in p else None)
                return simple(200, "ok")
            if cmd == "stop":
                await e.stop()
                return simple(200, "ok")
            if cmd == "goto":
                return await self._goto(p)
            if cmd == "notify":
                if not p:
                    return block(209, "notify", {k: str(v).lower() for k, v in s.notify.items()})
                for k, v in p.items():
                    if k in s.notify:
                        s.notify[k] = as_bool(v)
                return simple(200, "ok")
            if cmd == "remote":
                if not p:
                    return block(210, "remote info", {"enabled": "true", "override": "false"})
                return simple(200, "ok")
            if cmd == "configuration":
                if not p:
                    return block(211, "configuration", {
                        "audio input": "embedded", "video input": "HDMI",
                        "file format": "H.264"})
                return simple(200, "ok")
            if cmd == "uptime":
                return block(213, "uptime", {"uptime": str(e.uptime())})
            return simple(100, "syntax error")
        except PlayerUnavailable:
            return simple(150, "invalid state")     # restarting or wedged
        except ClipNotFound:
            return simple(109, "out of range")
        except ValueError:
            return simple(102, "invalid value")
        except MpvError:
            log.exception("Player error")
            return simple(108, "internal error")

    async def _goto(self, p):
        e = self.engine
        if "clip id" in p:
            v = p["clip id"]
            if v[:1] in "+-" and e.clip_id:
                target = e.clip_id + int(v)
            else:
                target = int(v)
            await e.goto_clip(target)
        elif p.get("clip") == "start":
            await e.seek_clip_start()
        elif p.get("clip") == "end":
            await e.seek_clip_end()
        elif p.get("timeline") == "start":
            await e.goto_clip(1)
        elif p.get("timeline") == "end":
            await e.goto_clip(len(e.library.clips))
        else:
            return simple(103, "unsupported")      # timecode goto not in v1
        return simple(200, "ok")
