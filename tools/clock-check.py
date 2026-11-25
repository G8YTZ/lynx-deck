#!/usr/bin/env python3
"""Where the pips actually are, measured on the Deck itself.

Run it a minute or two before the hour, with the station clock due on air:

    python3 tools/clock-check.py

It samples mpv's own audio position against the system clock while the
junction sound plays, and says where the long pip left the Deck. Position
30.000 s in the junction file IS the hour, so with a clock offset of N
seconds the long pip should leave the Deck N seconds BEFORE the hour, to
arrive on time after the coding and transmission delay.

Anything else is the Deck's own fault. If the Deck is right and the pips
are still out on air, the picture and the sound are drifting apart further
down the chain, not here.
"""
import argparse
import datetime as dt
import json
import socket
import sys
import time

LONG_PIP_AT = 30.0          # position in the junction file that IS the hour


class Mpv:
    def __init__(self, path):
        self.s = socket.socket(socket.AF_UNIX)
        self.s.settimeout(2.0)
        self.s.connect(path)
        self.buf = b""
        self.n = 0

    def get(self, prop):
        self.n += 1
        rid = self.n
        self.s.sendall(json.dumps({"command": ["get_property", prop],
                                   "request_id": rid}).encode() + b"\n")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            while b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if msg.get("request_id") == rid:        # ignore mpv's events
                    return msg.get("data")
            try:
                chunk = self.s.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            self.buf += chunk
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--socket", default="/tmp/lynxdeck-mpv.sock")
    ap.add_argument("--offset", type=float, default=None,
                    help="the Deck's clock offset, for the verdict line")
    ap.add_argument("--seconds", type=float, default=150.0, help="how long to watch")
    ap.add_argument("--minute", action="store_true",
                    help="the Deck is in test mode, with the pips on every minute")
    a = ap.parse_args()

    try:
        mpv = Mpv(a.socket)
    except OSError as exc:
        sys.exit(f"cannot reach mpv on {a.socket}: {exc}")

    period = 60.0 if a.minute else 3600.0
    print(f"watching {mpv.get('filename')}")
    for key in ("own-dir", "offset", "period", "file", "fired-at"):
        val = mpv.get("user-data/lynxclock/" + key)
        if val is not None:
            print(f"  {key:9} {val}")
    print("  system clock      audio position   file position   aid   "
          "where it should be      out by")
    end = time.time() + a.seconds
    seen, last = [], None
    while time.time() < end:
        pts = mpv.get("audio-pts")
        now = dt.datetime.now()
        tpos, aid = mpv.get("time-pos"), mpv.get("aid")
        if isinstance(pts, (int, float)):
            line = f"  {now:%H:%M:%S.%f}"[:-3] + f"   {pts:8.3f}"
            line += f"      {tpos:8.3f}" if isinstance(tpos, (int, float)) else "          -   "
            line += f"   {aid}"
            if a.offset is not None:
                # the script's own sum: pos = (clock time + AHEAD) within the period
                secs = (now.hour * 3600 + now.minute * 60 + now.second
                        + now.microsecond / 1e6 + a.offset)
                want = (secs + LONG_PIP_AT) % period
                line += f"        {want:8.3f}        {pts - want:+7.3f}"
            print(line)
            seen.append((now, pts))
            if last is not None and last < LONG_PIP_AT <= pts:
                # when did the file pass 30.000? interpolate between samples
                (t0, p0), (t1, p1) = seen[-2], seen[-1]
                span = (t1 - t0).total_seconds()
                k = (LONG_PIP_AT - p0) / (p1 - p0) if p1 != p0 else 0
                at = t0 + dt.timedelta(seconds=span * k)
                if a.minute:
                    mark = at.replace(second=0, microsecond=0)
                    if at.second >= 30:
                        mark += dt.timedelta(minutes=1)
                    name = "minute"
                else:
                    mark = at.replace(minute=0, second=0, microsecond=0)
                    if at.minute >= 30:
                        mark += dt.timedelta(hours=1)
                    name = "hour"
                early = (mark - at).total_seconds()
                print()
                print(f"LONG PIP left the Deck at {at:%H:%M:%S.%f}"[:-3])
                print(f"  that is {early:+.3f} s before the {name} "
                      f"by this Deck's system clock")
                if a.offset is not None:
                    err = early - a.offset
                    if abs(err) <= 0.05:
                        print(f"  clock offset is {a.offset:.2f} s: the Deck is right, "
                              f"so anything wrong on air is further down the chain")
                    else:
                        way = "EARLY" if err > 0 else "late"
                        print(f"  clock offset is {a.offset:.2f} s, so the Deck itself "
                              f"is {abs(err):.3f} s {way}")
                return
            last = pts
        time.sleep(0.1)
    print("\nno junction sound seen: was the clock on air, and playing?")


if __name__ == "__main__":
    main()
