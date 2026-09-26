"""State engine: the single source of truth for transport state.

Every controller (HyperDeck TCP server now; REST API, web UI and scheduler
later) is just a client of this engine, so they always agree on state.
"""
import asyncio
import logging
import time

from .player import Mpv, MpvError

log = logging.getLogger(__name__)


class ClipNotFound(Exception):
    pass


class Engine:
    def __init__(self, cfg, library):
        self.cfg = cfg
        self.library = library
        self.mpv = Mpv(cfg, self._on_mpv_event)
        self.status = "stopped"      # "stopped" or "play"
        self.clip_id = None
        self.speed = 100
        self.loop = False
        self.single_clip = False
        self.position = 0.0          # seconds into the current clip
        self.started_at = time.monotonic()
        self._eof = False
        self._gen = 0                # bumps on every clip load; stale events are ignored
        self._still_timer = None
        self._listeners = []
        self._tasks = set()
        self._lock = asyncio.Lock()
        self._closing = False
        self._supervisor = None

    # ----- lifecycle -------------------------------------------------------

    async def start(self):
        await self.mpv.start()
        if self.library.clips:
            await self.goto_clip(1)
        self._supervisor = asyncio.create_task(self._supervise())

    async def close(self):
        self._closing = True
        self._cancel_still_timer()
        await self.mpv.close()

    async def _supervise(self):
        """Restart mpv if it ever dies, and re-cue the current clip."""
        while not self._closing:
            await self.mpv.wait()
            if self._closing:
                return
            log.error("mpv exited unexpectedly - restarting in 2 s")
            await asyncio.sleep(2)
            try:
                await self.mpv.start()
                if self.clip_id:
                    await self.goto_clip(self.clip_id)
            except Exception:
                log.exception("mpv restart failed")

    # ----- listeners -------------------------------------------------------

    def add_listener(self, callback):
        self._listeners.append(callback)

    def _notify(self):
        for cb in self._listeners:
            try:
                cb()
            except Exception:
                log.exception("Listener failed")

    def _spawn(self, coro):
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ----- transport commands ---------------------------------------------

    async def goto_clip(self, clip_id):
        async with self._lock:
            await self._load(clip_id)
            self._notify()

    async def seek_clip_start(self):
        async with self._lock:
            await self.mpv.command("seek", 0, "absolute")
            self._eof = False
            self._notify()

    async def seek_clip_end(self):
        async with self._lock:
            await self.mpv.command("seek", 100, "absolute-percent")
            self._notify()

    async def play(self, speed=100, loop=None, single_clip=None):
        async with self._lock:
            if self.clip_id is None:
                if not self.library.clips:
                    raise ClipNotFound("no clips")
                await self._load(1)
            self.speed = speed
            if loop is not None:
                self.loop = loop
            if single_clip is not None:
                self.single_clip = single_clip
            clip = self.library.get(self.clip_id)
            await self.mpv.set("speed", speed / 100)
            await self._apply_loop(clip)
            if self._eof and clip.kind == "video":
                await self.mpv.command("seek", 0, "absolute")
                self._eof = False
            await self.mpv.set("pause", False)
            self.status = "play"
            self._arm_still_timer(clip)
            self._notify()

    async def stop(self):
        async with self._lock:
            self._cancel_still_timer()
            await self.mpv.set("pause", True)
            self.status = "stopped"
            self._notify()

    # ----- internals (call with the lock held) -----------------------------

    async def _load(self, clip_id):
        clip = self.library.get(clip_id)
        if clip is None:
            raise ClipNotFound(clip_id)
        self._cancel_still_timer()
        self._gen += 1
        await self.mpv.set("pause", True)
        await self._apply_loop(clip)
        await self.mpv.command("loadfile", str(clip.path), "replace")
        self.clip_id = clip_id
        self.status = "stopped"
        self.position = 0.0
        self._eof = False
        log.info("Cued clip %d: %s", clip.id, clip.name)

    async def _apply_loop(self, clip):
        # Single-clip loop is handled by mpv itself, which makes it seamless.
        seamless = self.loop and self.single_clip and clip.kind == "video"
        await self.mpv.set("loop-file", "inf" if seamless else "no")

    def _arm_still_timer(self, clip):
        self._cancel_still_timer()
        if clip.kind == "still" and not self.single_clip:
            gen = self._gen
            self._still_timer = asyncio.get_running_loop().call_later(
                self.cfg.still_duration, lambda: self._spawn(self._advance(gen)))

    def _cancel_still_timer(self):
        if self._still_timer:
            self._still_timer.cancel()
            self._still_timer = None

    def _on_mpv_event(self, msg):
        # Runs inside the mpv reader task: never await the lock here, spawn instead.
        if msg.get("event") != "property-change":
            return
        name, data = msg.get("name"), msg.get("data")
        if name == "time-pos" and isinstance(data, (int, float)):
            self.position = float(data)
        elif name == "eof-reached" and data is True:
            self._eof = True
            if self.status == "play":
                self._spawn(self._advance(self._gen))

    async def _advance(self, gen):
        """Current clip finished: move on according to loop / single clip."""
        try:
            async with self._lock:
                if gen != self._gen or self.status != "play":
                    return
                if self.single_clip:
                    self.status = "stopped"      # non-looping single clip: hold last frame
                    self._notify()
                    return
                nxt = self.clip_id + 1
                if nxt > len(self.library.clips):
                    if not self.loop:
                        self.status = "stopped"
                        self._notify()
                        return
                    nxt = 1
                await self._load(nxt)
                clip = self.library.get(nxt)
                await self.mpv.set("pause", False)
                self.status = "play"
                self._arm_still_timer(clip)
                self._notify()
        except (MpvError, ClipNotFound):
            log.exception("Advance failed")

    # ----- state reporting -------------------------------------------------

    def timecode(self, seconds=None):
        fps = self.cfg.timecode_fps
        frames = int(round((self.position if seconds is None else seconds) * fps))
        ff = frames % fps
        s = frames // fps
        return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}:{ff:02d}"

    def transport_info(self):
        tc = self.timecode()
        return {
            "status": self.status,
            "speed": str(self.speed if self.status == "play" else 0),
            "slot id": "1",
            "clip id": str(self.clip_id) if self.clip_id else "none",
            "single clip": str(self.single_clip).lower(),
            "display timecode": tc,
            "timecode": tc,
            "video format": self.cfg.video_format,
            "loop": str(self.loop).lower(),
        }

    def uptime(self):
        return int(time.monotonic() - self.started_at)
