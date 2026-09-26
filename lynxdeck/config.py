"""Configuration loading. Unknown keys are ignored with a warning."""
import logging
from dataclasses import dataclass, fields
from pathlib import Path

import yaml

log = logging.getLogger(__name__)


@dataclass
class Config:
    media_dir: Path = Path("/srv/lynxdeck/media")
    video_format: str = "1080p50"        # reported to HyperDeck clients
    drm_connector: str = "HDMI-A-1"      # HDMI0 on the Pi 4 (port nearest USB-C)
    drm_mode: str = "1920x1080@50"       # HDMI output mode
    timecode_fps: int = 25
    still_duration: float = 10.0         # seconds a still holds when playing through the list
    hwdec: str = "auto"
    # watchdog
    mpv_timeout: float = 5.0        # max wait for any mpv reply
    watchdog_interval: float = 2.0  # how often to check the player is alive
    stall_timeout: float = 5.0      # playing but timecode frozen this long = stalled
    report_health: bool = True      # add a "player" field to transport info
    mpv_socket: Path = Path("/tmp/lynxdeck-mpv.sock")
    hyperdeck_port: int = 9993
    model: str = "HyperDeck Studio Mini"
    protocol_version: str = "1.11"
    unique_id: str = "LYNXDECK0001"
    volume_name: str = "LynxDeck"


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
    return cfg
