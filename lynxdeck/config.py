"""Configuration loading. Unknown keys are ignored with a warning."""
import logging
from dataclasses import dataclass, fields
from pathlib import Path

import yaml

from . import __version__

log = logging.getLogger(__name__)


@dataclass
class Config:
    media_dir: Path = Path("/srv/lynxdeck/media")
    video_format: str = "1080p50"        # reported to controllers
    drm_connector: str = "HDMI-A-1"      # HDMI0 on the Pi 4 (port nearest USB-C)
    drm_mode: str = "1920x1080@50"       # HDMI output mode
    timecode_fps: int = 25
    still_duration: float = 10.0         # seconds a still holds when playing through the list
    default_clip: str = ""         # clip name or number: booted to, returned to, fallen back to
    default_behaviour: str = "auto"   # auto | once | loop | hold, for clips with no entry
    # player: mpv, hardware decode straight to a DRM overlay plane (zero copy)
    hwdec: str = "drm"
    drm_draw_plane: str = "primary"
    drm_video_plane: str = "overlay"
    mpv_socket: str = "/tmp/lynxdeck-mpv.sock"
    poll_interval: float = 0.5      # how often to read the player's position
    # HDMI0 on the Pi 4. The 3.5mm jack is the ALSA default, so this must be set.
    audio_device: str = "alsa/sysdefault:CARD=vc4hdmi0"
    volume: int = 100
    # watchdog
    load_timeout: float = 5.0       # max wait for a clip to finish loading
    player_timeout: float = 5.0        # max wait for any player reply
    watchdog_interval: float = 2.0  # how often to check the player is alive
    stall_timeout: float = 8.0      # playing but timecode frozen this long = stalled
    start_grace: float = 6.0        # a clip gets this long to start before judging it
    restart_backoff: float = 5.0    # wait between restart attempts, multiplied each time
    max_restarts: int = 3           # then fall back to the default slide
    report_health: bool = True      # add a "player" field to transport info

    hyperdeck_port: int = 9993
    http_port: int = 8080
    max_upload_mb: int = 8192      # refuse anything larger
    state_file: str = "config/state.json"
    repo_dir: str = ""             # blank = the directory this package lives in
    api_token: str = ""            # blank = no auth (keep it on a trusted VLAN)
    model: str = "Lynx Deck"
    protocol_version: str = "1.11"
    unique_id: str = "LYNXDECK0001"
    volume_name: str = "LynxDeck"
    version: str = __version__


def load(path) -> Config:
    cfg = Config()
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    known = {f.name for f in fields(Config)}
    for key, value in data.items():
        if key not in known:
            log.warning("Unknown config key ignored: %s", key)
            continue
        default = getattr(cfg, key)
        setattr(cfg, key, type(default)(value))
    # mpv wants the "alsa/device" form; accept a bare device name too
    if not cfg.audio_device.startswith(("alsa/", "pipewire", "pulse")):
        cfg.audio_device = "alsa/" + cfg.audio_device
    return cfg
