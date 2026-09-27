"""Player: mpv driven over its JSON IPC socket.

One mpv process runs for the life of the service and clips are swapped with
loadfile, so the DRM planes are never torn down: no HDMI renegotiation
between clips, no console flash in the gap, and transitions are instant.

Decoding is hardware, zero copy:

    --vo=gpu --gpu-context=drm --hwdec=drm
    --drm-draw-plane=primary --drm-drmprime-video-plane=overlay

mpv reports the output as drm_prime[rpi4_10] - the decoder's own frames going
straight to an overlay plane. Roughly 20% CPU on a Pi 4 at 1080p HEVC; the
copy variants cost nearly 200%.

A note on frame counters: on this path mpv's frame-drop-count rises steadily
even on a still image, because the video never passes through mpv's renderer
and it cannot verify presentations. The meaningful counters are
decoder-frame-drop-count and vo-delayed-frame-count, both of which stay at
zero when all is well. Health reporting uses those.
"""
import asyncio
import json
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)


class PlayerError(Exception):
    pass


class PlayerTimeout(PlayerError):
    """mpv accepted the command but never answered - it is wedged."""


class Mpv:
    def __init__(self, cfg, on_event=None):
        self.cfg = cfg
        self.on_event = on_event
        self.proc = None
        self.current = None
        self.is_still = False
        self.paused = True
        self._writer = None
        self._read_task = None
        self._pending = {}
        self._rid = 0
        self.file_loaded = asyncio.Event()
        self.eof = False

    # ----- process lifecycle ----------------------------------------------

    def build_args(self):
        return [
            "mpv", "--idle=yes", "--keep-open=always",
            f"--input-ipc-server={self.cfg.mpv_socket}",
            "--vo=gpu", "--gpu-context=drm",
            f"--hwdec={self.cfg.hwdec}",
            f"--drm-draw-plane={self.cfg.drm_draw_plane}",
            f"--drm-drmprime-video-plane={self.cfg.drm_video_plane}",
            f"--drm-connector={self.cfg.drm_connector}",
            "--fullscreen", "--no-osc", "--osd-level=0",
            "--no-input-default-bindings", "--input-vo-keyboard=no",
            "--input-terminal=no", "--really-quiet",
            "--image-display-duration=inf",     # stills hold until told otherwise
            f"--audio-device={self.cfg.audio_device}",
            f"--volume={self.cfg.volume}",
            "--audio-fallback-to-null=yes",     # silence must never stop the picture
            "--pause=yes",
        ]

    async def start(self):
        sock = Path(self.cfg.mpv_socket)
        sock.parent.mkdir(parents=True, exist_ok=True)
        if sock.exists():
            sock.unlink()
        await self._sweep_strays()
        log.info("Starting mpv (%s, hwdec=%s)", self.cfg.drm_connector, self.cfg.hwdec)
        self.proc = await asyncio.create_subprocess_exec(
            *self.build_args(), stdin=asyncio.subprocess.DEVNULL)
        reader = None
        deadline = time.monotonic() + self.cfg.load_timeout
        while time.monotonic() < deadline:
            if self.proc.returncode is not None:
                raise PlayerError(f"mpv exited at start-up (code {self.proc.returncode})")
            if sock.exists():
                try:
                    reader, self._writer = await asyncio.open_unix_connection(str(sock))
                    break
                except (ConnectionRefusedError, FileNotFoundError):
                    pass
            await asyncio.sleep(0.1)
        if reader is None:
            self.proc.kill()
            raise PlayerError("mpv IPC socket never appeared")
        self._read_task = asyncio.create_task(self._read_loop(reader))
        await self.command("observe_property", 1, "eof-reached")
        self.paused, self.current, self.is_still, self.eof = True, None, False, False
        log.info("Player ready (mpv -> %s)", self.cfg.audio_device)

    async def _sweep_strays(self):
        """Kill any mpv we did not start - a stray holds the DRM planes."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "pgrep", "-x", "mpv",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await proc.communicate()
        except FileNotFoundError:
            return
        mine = self.proc.pid if self.proc else None
        for pid in (int(p) for p in out.split() if p.isdigit()):
            if pid == mine:
                continue
            log.warning("Clearing a stray mpv (pid %d)", pid)
            try:
                await (await asyncio.create_subprocess_exec("kill", "-9", str(pid))).wait()
            except Exception:
                pass
        if out.strip():
            await asyncio.sleep(0.5)

    async def _read_loop(self, reader):
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if "event" in msg:
                    if msg["event"] == "file-loaded":
                        self.file_loaded.set()
                        self.eof = False
                    elif msg.get("name") == "eof-reached":
                        self.eof = bool(msg.get("data"))
                    if self.on_event:
                        try:
                            self.on_event(msg)
                        except Exception:
                            log.exception("Error handling an mpv event")
                elif "request_id" in msg:
                    fut = self._pending.pop(msg["request_id"], None)
                    if fut and not fut.done():
                        fut.set_result(msg)
        finally:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(PlayerError("mpv connection lost"))
            self._pending.clear()
            self._writer = None

    # ----- commands --------------------------------------------------------

    async def command(self, *args, timeout=None):
        timeout = timeout if timeout is not None else self.cfg.player_timeout
        if self._writer is None:
            raise PlayerError("player not connected")
        self._rid += 1
        rid = self._rid
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        self._writer.write((json.dumps({"command": list(args), "request_id": rid}) + "\n").encode())
        await self._writer.drain()
        try:
            msg = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            raise PlayerTimeout(f"{args[0]} timed out after {timeout} s")
        finally:
            self._pending.pop(rid, None)
        if msg.get("error") != "success":
            raise PlayerError(f"{args[0]} failed: {msg.get('error')}")
        return msg.get("data")

    async def get(self, prop, default=None):
        try:
            return await self.command("get_property", prop)
        except PlayerError:
            return default

    async def set(self, prop, value):
        return await self.command("set_property", prop, value)

    async def load(self, path, still=False, repeat=False, play=False, timeout=None):
        """Swap to this clip. The planes are never released, so no HDMI reset."""
        timeout = timeout if timeout is not None else self.cfg.load_timeout
        if self.proc is None or self.proc.returncode is not None:
            await self.start()
        self.file_loaded.clear()
        await self.set("pause", True)
        await self.set("loop-file", "inf" if repeat else "no")
        await self.command("loadfile", str(path), "replace")
        try:
            await asyncio.wait_for(self.file_loaded.wait(), timeout)
        except asyncio.TimeoutError:
            raise PlayerError(f"clip did not load within {timeout} s: {path}")
        self.current, self.is_still, self.eof = Path(path), still, False
        self.paused = True
        if play:
            await self.play()

    async def play(self):
        await self.set("pause", False)
        self.paused = False

    async def pause(self):
        """Hold the current frame."""
        await self.set("pause", True)
        self.paused = True

    async def seek(self, seconds):
        await self.command("seek", float(seconds), "absolute")

    async def get_time(self):
        pos = await self.get("time-pos")
        return float(pos) if isinstance(pos, (int, float)) else 0.0

    async def at_end(self):
        if self.is_still:
            return False
        return bool(await self.get("eof-reached", False))

    async def is_alive(self):
        if self.proc is None or self.proc.returncode is not None:
            return False
        await self.command("get_property", "mpv-version",
                           timeout=self.cfg.watchdog_interval)
        return True

    async def health(self):
        """The counters that actually mean something on the overlay path.

        frame-drop-count is not one of them: it rises even on a still image,
        because the video bypasses mpv's renderer entirely.
        """
        return {
            "decoderDrops": await self.get("decoder-frame-drop-count", 0),
            "lateFrames": await self.get("vo-delayed-frame-count", 0),
        }

    async def wait(self):
        if self.proc:
            await self.proc.wait()
        else:
            await asyncio.Event().wait()

    async def kill(self):
        if self._writer is not None:
            try:
                self._writer.close()
            except Exception:
                pass
            self._writer = None
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), 3)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self.proc.kill()
                    await self.proc.wait()
                except ProcessLookupError:
                    pass
        self.proc = None

    async def close(self):
        await self.kill()
