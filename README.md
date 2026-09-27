# Lynx Deck

A media player for amateur television repeaters, running on a Raspberry Pi 4.

It plays video and stills to an HDMI output and is controlled by Bitfocus
Companion or an ATEM switcher over the standard text-based deck control
protocol on TCP 9993, so existing workflows need no changes at the controller
end. Clip changes are instant and the HDMI output never drops, which matters
when a switcher or an HDMI extender is downstream.

Built by Justin Cockett, G8YTZ, for the GB3OO and GB3JT amateur television
repeaters, and released under the GPL for anyone running an ATV repeater who
wants a deck they can maintain themselves.

## What it does
- **Plays** H.264 and H.265 video, and PNG and JPG stills, at 1080p
- **Decodes in hardware** on the Pi 4's HEVC block, using about 20% of one CPU
- **Cuts between clips instantly**, with no HDMI renegotiation or black gap
- **Takes control** from Companion or an ATEM: play, stop, goto, loop, single
  clip, clip list and notifications
- **Uploads over the network**, with drag-and-drop in the browser and every
  file checked before it can reach air
- **Runs a web interface** for transport, media, settings, status, reboot and
  software update
- **Looks after itself**: a watchdog restarts a wedged player, the transport is
  restored where it left off, and the deck falls back to a default slide if a
  clip goes missing
- **Reboots and updates remotely**, because a repeater site is rarely next door

## Per-clip behaviour
Each clip decides what happens when it ends - move on, repeat, or hold the last
frame - so a test card can sit on air indefinitely while idents play through.

## Hardware
A Raspberry Pi 4, an SD card, and a micro-HDMI cable to your switcher. The Pi 4
is a 1080p deck: it decodes 1080p HEVC with four to six times the headroom it
needs, but 4K is beyond it.

## Documentation
- `docs/Lynx_Deck_Installation_Guide.docx` - blank SD card to working deck
- `docs/Lynx_Deck_Web_Interface_Guide.docx` - day-to-day operation

## Quick start
    sudo apt install -y git mpv ffmpeg python3-yaml python3-fastapi python3-uvicorn
    git clone https://github.com/G8YTZ/lynx-deck.git ~/lynx-deck
    cd ~/lynx-deck && cp config/lynx_deck.yaml.example config/lynx_deck.yaml
    sudo cp systemd/lynx-deck.service /etc/systemd/system/
    sudo systemctl enable --now lynx-deck

The installation guide covers the rest: the HDMI output standard, audio
routing, the media folder and the maintenance permissions.

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

## Documentation
- `docs/Lynx_Deck_Installation_Guide.docx` - blank SD card to working deck
- `docs/Lynx_Deck_Web_Interface_Guide.docx` - day-to-day operation

## Requirements
Raspberry Pi 4, Raspberry Pi OS Lite (64-bit), no desktop.

    sudo apt install -y git mpv ffmpeg python3-yaml python3-fastapi python3-uvicorn

Allow the reboot and update endpoints to work without a password:

    echo "$USER ALL=(root) NOPASSWD: /sbin/shutdown, /usr/bin/systemctl restart lynx-deck, /usr/sbin/rfkill" | sudo tee /etc/sudoers.d/lynxdeck
    sudo chmod 440 /etc/sudoers.d/lynxdeck

## Web UI and REST API
Browse to `http://<deck>:8080`. Endpoints:

| Method | Path | Purpose |
|---|---|---|
| GET | `/system` | model, version, uptime, player health |
| POST | `/system/reboot` | reboot the deck |
| POST | `/system/restartPlayer` | rebuild mpv without rebooting |
| GET | `/system/update` | installed version, and whether the remote has anything newer |
| POST | `/system/update` | pull and restart (fast-forward only) |
| GET | `/player/health` | decoder drops and late frames |
| GET | `/system/output` | real HDMI mode and refresh rate, and what is playing |
| GET | `/system/network` | interfaces, addresses, whether Wi-Fi is blocked |
| POST | `/system/wifi` | body: `{"enabled":false}`; refuses if Ethernet is down |
| GET | `/system/controllers` | who is connected and what they last sent |
| GET/PUT | `/settings` | default clip, behaviour, still duration, volume |
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

## One long-lived player
mpv starts with the service and keeps running; clips are swapped with
`loadfile`, so the DRM planes are never released. No HDMI renegotiation
between clips, no console flash in the gap, and transitions are instant - a
controller needs no artificial wait between goto and play.

    --vo=gpu --gpu-context=drm --hwdec=drm
    --drm-draw-plane=primary --drm-drmprime-video-plane=overlay

That is the zero-copy path: mpv reports `drm_prime[rpi4_10]` and uses about
20% CPU on a Pi 4 at 1080p HEVC. `--hwdec=drm-copy` also decodes in hardware
but copies every frame back through system memory, costing nearly 200%.
`--hwdec=auto` falls back to software entirely, at about four frames a second.
Note that `--hwdec=drm` requires `--vo=gpu`; it will not work with `--vo=drm`.

## Frame counters
On the overlay path mpv's `frame-drop-count` rises steadily even on a still
image, because the video bypasses mpv's renderer and it cannot verify
presentations. Ignore it. The meaningful counters, exposed at
`/player/health`, are `decoder-frame-drop-count` and `vo-delayed-frame-count`;
both stay at zero when all is well.

## Status and settings panels
The web UI shows what the deck is actually doing rather than what the config
claims: the real HDMI mode and refresh rate read from the kernel, the playing
clip's codec and behaviour, which controllers are connected and how long since
each last spoke, the network interfaces, and the player health counters.

Day-to-day settings - default clip, default behaviour, still duration and
volume - are edited there too. They are saved to `config/state.json` and
applied over the config at startup, so the config file stays as install-time
defaults and is never rewritten.

Still duration only applies to clips set to `auto`; `loop` and `hold` hold a
still indefinitely.

## Networking at a repeater site
Use a DHCP reservation rather than a static address on the deck: addressing
stays in one place and survives a reimage.

Wi-Fi is best disabled so there is no second route. The UI has a button, which
refuses if Ethernet is not up. To disable the radio permanently, add
`dtoverlay=disable-wifi` to `/boot/firmware/config.txt`.

## Software update
The web UI has a Check for updates button, and an Update and restart button
that appears when the remote is ahead. It is a fast-forward pull of the
checked-out branch followed by a service restart, so it refuses rather than
guessing if tracked files have been edited locally. Untracked files - media,
logs, your config - never block it. Set `repo_dir` in the config if the
checkout is somewhere other than the package's parent directory.

Because the pull needs credentials, make sure git can authenticate without a
prompt: either a deploy key, or `git config --global credential.helper store`
with the token already saved.

## Output standard
The HDMI mode is set once by the kernel at boot, not by the player, so nothing
can renegotiate it later. Add to `/boot/firmware/cmdline.txt`, on the one line:

    video=HDMI-A-1:1920x1080@25e

The trailing `e` marks the mode as preferred; `D` alone loses to the monitor's
own EDID preference.

## Performance on a Pi 4
Measured, hardware decode: 1080p 8-bit 5.9x real time, 1080p 10-bit 4.0x,
4K 10-bit 0.8x. The Pi 4 is a 1080p deck; 4K desynchronises within seconds.

## Player control
State is established, never assumed:

- A cue loads the clip paused on its first frame; play is explicit.
- `play` is explicit. `pause` is a toggle, so it is only sent after checking.
- Every transport change is confirmed with `status`, which reports
  `( state playing )` or `( state paused )`. Do not use `is_playing`: it
  returns 1 whenever a stream is loaded, paused or not.
- Any mpv process we did not start is killed before launching one, since a
  stray holds the DRM planes and the new one gets nothing.

## Audio
The Pi's ALSA default is the 3.5mm headphone jack, so HDMI audio must be named
explicitly. `audio_device` defaults to HDMI0 (`vc4hdmi0`, the port nearest the
USB-C socket). Use `aplay -l` to confirm the card names on your board. The
startup log also reports whether each video is being decoded in hardware.

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

## Config
The package ships `config/lynx_deck.yaml.example`; your own settings live in
`config/lynx_deck.yaml`, which upgrades never touch:

    cp config/lynx_deck.yaml.example config/lynx_deck.yaml

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
