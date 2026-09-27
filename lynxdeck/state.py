"""Runtime settings, changed from the web UI and kept across restarts.

The config file holds install-time decisions (ports, paths, output standard).
These are the things an operator changes day to day, so they live in their own
small file and the config is never rewritten.
"""
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# setting -> (config attribute, type)
EDITABLE = {
    "defaultClip": ("default_clip", str),
    "defaultBehaviour": ("default_behaviour", str),
    "stillDuration": ("still_duration", float),
    "volume": ("volume", int),
}


class State:
    def __init__(self, cfg):
        self.cfg = cfg
        self.path = Path(cfg.state_file)

    def load_into_config(self):
        """Apply saved settings over the config at startup."""
        try:
            with open(self.path) as f:
                data = json.load(f)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            log.warning("Could not read %s: %s", self.path, exc)
            return {}
        for key, value in data.items():
            if key in EDITABLE:
                attr, kind = EDITABLE[key]
                try:
                    setattr(self.cfg, attr, kind(value))
                except (TypeError, ValueError):
                    log.warning("Ignoring bad saved value for %s: %r", key, value)
        log.info("Applied %d saved settings", len(data))
        return data

    def current(self):
        return {key: getattr(self.cfg, attr)
                for key, (attr, _) in EDITABLE.items()}

    def save(self, changes):
        """Validate, apply to the live config, and write to disk."""
        applied = {}
        for key, value in changes.items():
            if key not in EDITABLE:
                raise ValueError(f"unknown setting: {key}")
            attr, kind = EDITABLE[key]
            try:
                typed = kind(value)
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be {kind.__name__}")
            if key == "defaultBehaviour" and typed not in ("auto", "once", "loop", "hold"):
                raise ValueError("defaultBehaviour must be auto, once, loop or hold")
            if key == "stillDuration" and not 1 <= typed <= 3600:
                raise ValueError("stillDuration must be between 1 and 3600 seconds")
            if key == "volume" and not 0 <= typed <= 130:
                raise ValueError("volume must be between 0 and 130")
            setattr(self.cfg, attr, typed)
            applied[key] = typed
        merged = self.current()
        tmp = self.path.with_suffix(".json.tmp")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(merged, f, indent=2)
        tmp.replace(self.path)
        return applied
