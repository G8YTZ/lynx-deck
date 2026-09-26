"""mpv driver: runs mpv full-screen on DRM (no desktop) and talks JSON IPC."""
import asyncio
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


class MpvError(Exception):
    pass


class MpvTimeout(MpvError):
    """mpv accepted the command but never answered - it is wedged."""


class Mpv:
    def __init__(self, cfg, on_event):
        self.cfg = cfg
        self.on_event = on_event      # plain function, called from the reader task
        self.proc = None
        self._writer = None
        self._read_task = None
        self._pending = {}
        self._rid = 0

    def build_args(self):
        return [
            "mpv", "--idle=yes", f"--input-ipc-server={self.cfg.mpv_socket}",
            "--vo=gpu", "--gpu-context=drm",
            f"--drm-connector={self.cfg.drm_connector}",
            f"--drm-mode={self.cfg.drm_mode}",
            f"--hwdec={self.cfg.hwdec}",
            "--fullscreen", "--keep-open=always", "--image-display-duration=inf",
            "--video-sync=display-resample", "--pause=yes",
            "--osc=no", "--osd-level=0", "--no-input-default-bindings",
            "--input-vo-keyboard=no", "--input-terminal=no", "--really-quiet",
        ]

    async def start(self):
        sock = Path(self.cfg.mpv_socket)
        sock.parent.mkdir(parents=True, exist_ok=True)
        if sock.exists():
            sock.unlink()
        log.info("Starting mpv")
        # stdin to /dev/null: a lesson learned the hard way on Lynx
        self.proc = await asyncio.create_subprocess_exec(
            *self.build_args(), stdin=asyncio.subprocess.DEVNULL)
        reader = None
        for _ in range(100):
            if self.proc.returncode is not None:
                raise MpvError(f"mpv exited during start-up (code {self.proc.returncode})")
            if sock.exists():
                try:
                    reader, self._writer = await asyncio.open_unix_connection(str(sock))
                    break
                except (ConnectionRefusedError, FileNotFoundError):
                    pass
            await asyncio.sleep(0.1)
        if reader is None:
            self.proc.kill()
            raise MpvError("mpv IPC socket never appeared")
        self._read_task = asyncio.create_task(self._read_loop(reader))
        await self.command("observe_property", 1, "eof-reached")
        await self.command("observe_property", 2, "time-pos")
        log.info("mpv ready")

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
                    try:
                        self.on_event(msg)
                    except Exception:
                        log.exception("Error handling mpv event")
                elif "request_id" in msg:
                    fut = self._pending.pop(msg["request_id"], None)
                    if fut and not fut.done():
                        fut.set_result(msg)
        finally:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(MpvError("mpv connection lost"))
            self._pending.clear()
            self._writer = None

    async def command(self, *args, timeout=None):
        timeout = timeout if timeout is not None else self.cfg.mpv_timeout
        if self._writer is None:
            raise MpvError("mpv not connected")
        self._rid += 1
        rid = self._rid
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        self._writer.write((json.dumps({"command": list(args), "request_id": rid}) + "\n").encode())
        await self._writer.drain()
        try:
            msg = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            raise MpvTimeout(f"{args[0]} timed out after {timeout} s")
        finally:
            self._pending.pop(rid, None)
        if msg.get("error") != "success":
            raise MpvError(f"{args[0]} failed: {msg.get('error')}")
        return msg.get("data")

    async def set(self, prop, value):
        return await self.command("set_property", prop, value)

    async def kill(self):
        """Hard stop, used by the watchdog when mpv stops answering."""
        if not self.proc or self.proc.returncode is not None:
            return
        try:
            self.proc.terminate()
            await asyncio.wait_for(self.proc.wait(), 3)
        except (asyncio.TimeoutError, ProcessLookupError):
            try:
                self.proc.kill()
                await self.proc.wait()
            except ProcessLookupError:
                pass

    async def wait(self):
        if self.proc:
            await self.proc.wait()

    async def close(self):
        if not self.proc or self.proc.returncode is not None:
            return
        try:
            await self.command("quit", timeout=2)
        except Exception:
            if self.proc.returncode is None:
                try:
                    self.proc.terminate()
                except ProcessLookupError:
                    pass
        try:
            await asyncio.wait_for(self.proc.wait(), 5)
        except asyncio.TimeoutError:
            self.proc.kill()
