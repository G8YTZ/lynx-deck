#!/usr/bin/env python3
"""Put the station clock's pips on every minute, for testing, and back again.

    python3 tools/clock-test.py on
    python3 tools/clock-test.py off

Test mode uses the generic pips-only file, so there is no music and no
announcement; the face has to be on screen and playing, as usual. Turn it
off again when you have finished, or a restart of the player will.
"""
import argparse
import json
import socket
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("state", choices=["on", "off"])
    ap.add_argument("--socket", default="/tmp/lynxdeck-mpv.sock")
    a = ap.parse_args()
    try:
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(2.0)
        s.connect(a.socket)
        s.sendall(json.dumps({"command": ["script-message", "lynxclock-test",
                                          "yes" if a.state == "on" else "no"]}).encode() + b"\n")
    except OSError as exc:
        sys.exit(f"cannot reach mpv on {a.socket}: {exc}")
    print("pips every minute" if a.state == "on" else "pips on the hour")


if __name__ == "__main__":
    main()
