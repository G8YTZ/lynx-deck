# Lynx Deck

A networked media playback server for the Raspberry Pi 4, part of the Lynx
family by G8YTZ. It speaks the standard text-based deck control protocol on
TCP 9993, so Bitfocus Companion and ATEM switchers drive it with no changes
at the controller end.

**Status:** v0.6 - deck protocol, state engine, mpv playback, watchdog,
REST API, web UI, media upload, per-clip behaviour and a default slide.

## Features (v1 target)
- H.264 and H.265 video, PNG and JPG stills
- 1080p HDMI output (4K/HDR planned for v2)
- Deck protocol playback subset: play, stop, goto, loop, single clip, clip list, notify
- REST API, web UI, drag-and-drop upload, self-healing player watchdog

## Watchdog
The control protocol never depends on the player. Every mpv call has a timeout,
the command lock is never held indefinitely, and a separate watchdog task:

- probes mpv every `watchdog_interval` seconds and restarts it after two failures
- restarts it if playback claims to be running but the timecode stops advancing
  for `stall_timeout` seconds
- restarts it if the process dies
- puts the transport back where it was afterwards (clip, position, play state)

`transport info` gains a `player: ok | stalled | restarting` field so Companion
can see trouble instead of a cheerful "connected". Set `report_health: false`
to suppress it.

## Requirements
Raspberry Pi 4, Raspberry Pi OS Lite (64-bit), no desktop.

    sudo apt install -y git mpv ffmpeg python3-yaml python3-fastapi python3-uvicorn

Allow the reboot endpoint to work without a password:

    echo "$USER ALL=(root) NOPASSWD: /sbin/shutdown" | sudo tee /etc/sudoers.d/lynxdeck
    sudo chmod 440 /etc/sudoers.d/lynxdeck

## Web UI and REST API
Browse to `http://<deck>:8080`. Endpoints:

| Method | Path | Purpose |
|---|---|---|
| GET | `/system` | model, version, uptime, player health |
| POST | `/system/reboot` | reboot the deck |
| POST | `/system/restartPlayer` | rebuild mpv without rebooting |
| GET | `/media/workingset` | clip list |
| POST | `/media/rescan` | rescan the media folder |
| GET | `/transports/0` | transport state |
| PUT | `/transports/0/play` | body: `{"loop":true,"singleClip":false}` |
| PUT | `/transports/0/stop` | stop |
| PUT | `/transports/0/clipIndex` | body: `{"clipIndex":2}` |
| PUT | `/media/upload/<name>` | raw file as the request body |
| DELETE | `/media/<name>` | remove a file |
| PUT | `/media/<name>/behaviour` | body: `{"behaviour":"loop","duration":15}` |
| PUT | `/transports/0/settings` | body: `{"loop":true,"singleClip":false}` (does not start playback) |

Uploads are streamed to a temporary name and only moved into place once
probed, so a half-uploaded file can never reach air. Anything the Pi 4 cannot
hardware-decode is rejected with a reason. From the command line:

    curl -X PUT --data-binary @ident.mp4 http://<deck>:8080/media/upload/03_ident.mp4

Set `api_token` in the config to require an `X-Lynx-Token` header on reboot
and rescan. Companion drives all of these with its generic HTTP module.

## Per-clip behaviour
Each clip decides what happens when it ends, set from the web UI or stored in
`clips.yaml` in the media folder:

    01_testcard.png: { play: loop, duration: 15 }
    02_ident.mp4:    { play: once }
    03_course.mp4:   { play: hold }

- `auto` / `once` - move on to the next clip (the default)
- `loop` - repeat this clip; for video mpv loops it seamlessly, with no reload gap
- `hold` - play once, then stop on the last frame
- `duration` - how long a still is held before moving on

`default_behaviour` in the config sets what an unmarked clip does. With
Companion triggers driving the running order, set it to `hold` so nothing
advances on its own.

## The default slide
`default_clip` names the clip the deck falls back to - by filename or number.
It is played at boot, returned to when the running order finishes, and used if
a clip disappears while the player is restarting. Point it at your test card
and the deck always ends up showing something sensible, whatever goes wrong.

The controller's own `single clip` flag always takes precedence over per-clip
behaviour, so Companion and an ATEM behave exactly as they expect to.

## Media
Put files in `/srv/lynxdeck/media`. Clip IDs follow filename order, so
number them: `01_testcard.png`, `02_ident.mp4` ...

## Run by hand

    cd ~/lynx-deck
    python3 -m lynxdeck --config config/lynx_deck.yaml --debug

## Run as a service

    sudo cp systemd/lynx-deck.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now lynx-deck
    journalctl -u lynx-deck -f

## Force HDMI output at boot
So the Pi outputs 1080p50 even if the ATEM is powered after it:

    sudo sed -i '1 s/$/ video=HDMI-A-1:1920x1080@50D/' /boot/firmware/cmdline.txt
