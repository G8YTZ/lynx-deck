"""State engine: the single source of truth for transport state.

Every controller (HyperDeck TCP server now; REST API, web UI and scheduler
later) is just a client of this engine, so they always agree on state.
"""
import asyncio
import contextlib
import logging
import time

from .player import Mpv, MpvError, MpvTimeout

log = logging.getLogger(__name__)


class ClipNotFound(Exception):
    pass


class PlayerUnavailable(Exception):
    """The player is wedged or restarting - the command cannot be honoured now."""


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
        self._watchdog = None
        self._restart_lock = asyncio.Lock()
        self.player_state = "ok"          # ok | stalled | restarting
        self._last_pos = 0.0
        self._last_pos_time = time.monotonic()
        self._probe_failures = 0
        self._grace_until = 0.0           # settle time after a restart

    # ----- lifecycle -------------------------------------------------------

    async def start(self):
        await self.mpv.start()
        if self.library.clips:
            await self.goto_clip(1)
        self._supervisor = asyncio.create_task(self._supervise())
        self._watchdog = asyncio.create_task(self._watch())

    async def close(self):
        self._closing = True
        self._cancel_still_timer()
        for task in (self._watchdog, self._supervisor):
            if task:
                task.cancel()
        await self.mpv.close()

    async def _supervise(self):
        """Notice if the mpv process dies and hand it to the restart path."""
        while not self._closing:
            await self.mpv.wait()
            if self._closing:
                return
            await asyncio.sleep(1)
            if (not self._restart_lock.locked()
                    and time.monotonic() >= self._grace_until):
                await self._restart_player("mpv exited")

    async def _watch(self):
        """Watchdog: prove mpv is answering, and that playback is progressing.

        The control protocol must never depend on the player, so this runs
        entirely outside the command lock.
        """
        while not self._closing:
            await asyncio.sleep(self.cfg.watchdog_interval)
            if self._closing or self._restart_lock.locked():
                continue
            if time.monotonic() < self._grace_until:
                continue      # let a freshly restarted player settle
            # 1. is mpv answering at all?
            try:
                await self.mpv.command("get_property", "mpv-version",
                                       timeout=self.cfg.watchdog_interval)
                self._probe_failures = 0
            except MpvError as exc:
                self._probe_failures += 1
                log.warning("Player probe failed (%d): %s", self._probe_failures, exc)
                if self._probe_failures >= 2:
                    self.player_state = "stalled"
                    self._notify()
                    await self._restart_player("player stopped answering")
                continue
            # 2. if it claims to be playing a video, is the timecode moving?
            clip = self.library.get(self.clip_id)
            playing_video = self.status == "play" and clip and clip.kind == "video"
            if playing_video and not self._eof:
                if abs(self.position - self._last_pos) > 0.05:
                    self._last_pos = self.position
                    self._last_pos_time = time.monotonic()
                elif time.monotonic() - self._last_pos_time > self.cfg.stall_timeout:
                    log.error("Playback stalled at %.2f s", self.position)
                    self.player_state = "stalled"
                    self._notify()
                    await self._restart_player("playback stalled")
            else:
                self._last_pos = self.position
                self._last_pos_time = time.monotonic()

    async def _restart_player(self, reason):
        """Rebuild mpv and put the transport back where it was."""
        if self._restart_lock.locked():
            return
        async with self._restart_lock:
            log.error("Restarting player: %s", reason)
            self.player_state = "restarting"
            self._notify()
            want_clip, want_pos, want_status = self.clip_id, self.position, self.status
            self._cancel_still_timer()
            try:
                await self.mpv.kill()
                await asyncio.sleep(1)
                await self.mpv.start()
            except Exception:
                log.exception("Player restart failed - retrying shortly")
                self.player_state = "stalled"
                self._notify()
                return
            try:
                async with self._guard(timeout=10):
                    if want_clip:
                        await self._load(want_clip)
                        clip = self.library.get(want_clip)
                        if want_pos > 1 and clip and clip.kind == "video":
                            with contextlib.suppress(MpvError):
                                await self.mpv.command("seek", want_pos, "absolute")
                        if want_status == "play":
                            await self.mpv.set("pause", False)
                            self.status = "play"
                            self._arm_still_timer(clip)
                    self.player_state = "ok"
                    self._probe_failures = 0
                    self._last_pos = self.position
                    self._last_pos_time = time.monotonic()
                    self._grace_until = time.monotonic() + max(
                        5.0, self.cfg.stall_timeout + self.cfg.watchdog_interval)
                    self._notify()
                log.info("Player restarted and resumed")
            except (MpvError, ClipNotFound, PlayerUnavailable):
                log.exception("Could not restore transport after restart")
                self.player_state = "stalled"
                self._notify()

    # ----- listeners -------------------------------------------------------

    def add_listener(self, callback):
        self._listeners.append(callback)

    def _notify(self):
        for cb in self._listeners:
            try:
                cb()
            except Exception:
                log.exception("Listener failed")

    @contextlib.asynccontextmanager
    async def _guard(self, timeout=3.0):
        """Take the command lock, or give up quickly rather than hang a client."""
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout)
        except asyncio.TimeoutError:
            raise PlayerUnavailable("player busy")
        try:
            yield
        finally:
            self._lock.release()

    def _spawn(self, coro):
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ----- transport commands ---------------------------------------------

    async def goto_clip(self, clip_id):
        async with self._guard():
            await self._load(clip_id)
            self._notify()

    async def seek_clip_start(self):
        async with self._guard():
            await self.mpv.command("seek", 0, "absolute")
            self._eof = False
            self._notify()

    async def seek_clip_end(self):
        async with self._guard():
            await self.mpv.command("seek", 100, "absolute-percent")
            self._notify()

    async def play(self, speed=100, loop=None, single_clip=None):
        async with self._guard():
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
        async with self._guard():
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
            async with self._guard():
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
        info = {
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
        if self.cfg.report_health:
            info["player"] = self.player_state
        return info

    def uptime(self):
        return int(time.monotonic() - self.started_at)
