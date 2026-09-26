# Lynx Deck

A HyperDeck-compatible playback server for the Raspberry Pi 4, part of the
Lynx family by G8YTZ. Controlled by Bitfocus Companion or an ATEM switcher
using the HyperDeck Ethernet Protocol on TCP 9993.

**Status:** v0.2 - HyperDeck protocol server, state engine, mpv playback, watchdog.

## Features (v1 target)
- H.264 and H.265 video, PNG and JPG stills
- 1080p HDMI output (4K/HDR planned for v2)
- HyperDeck protocol playback subset: play, stop, goto, loop, single clip, clip list, notify
- REST API and web UI with remote upload (coming next)

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

    sudo apt install -y git mpv ffmpeg python3-yaml

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
