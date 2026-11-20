#!/usr/bin/env python3
"""Lynx Deck's SNMP agent: serves the lynxDeck branch of mibs/LYNX-MIB.txt for
snmpd (pass_persist), as Lynx-Tx's tools/lynx-snmp-agent.py does for lynxTx.

snmpd starts this once and talks to it on stdin/stdout. The values come from
the Deck's own /api/health (lynxdeck/health.py, cached 5 s), so a monitoring
system polling every few seconds never reaches the player itself. If the Deck
does not answer, lynxDeckState reads notAnswering(4) and everything else
unknown: an alarm, as it should be.

/etc/snmp/snmpd.conf.d/lynx-deck.conf (scripts/setup_snmp.sh writes it):
  pass_persist .1.3.6.1.4.1.8072.9999.1.3 /usr/bin/python3 /usr/local/lib/lynx-deck/lynx-deck-snmp-agent.py

On Net-SNMP's experimental branch (.1.3.6.1.4.1.8072.9999) with Lynx-Tx until the repeater
group has its own Private Enterprise Number.
"""
import json
import sys
import time
import urllib.request

BASE = ".1.3.6.1.4.1.8072.9999.1.3"          # lynxDeck
URL = "http://127.0.0.1:8080/api/health"

# column: (health key, pass_persist type, value when Lynx-Tx is down)
OBJECTS = {
    1: ("deckState", "integer", 4),
    2: ("playerState", "integer", 4),
    3: ("clipName", "string", ""),
    4: ("clipIndex", "gauge", 0),
    5: ("clipCount", "gauge", 0),
    6: ("decoderDrops", "counter", 0),
    7: ("lateFrames", "counter", 0),
    8: ("playerRestarts", "counter", 0),
    9: ("timeSynced", "integer", 2),
    10: ("scheduleEntries", "gauge", 0),
    11: ("scheduleOnAir", "string", ""),
    12: ("scheduleCuts", "counter", 0),
    13: ("scheduleMisses", "counter", 0),
    14: ("hdmiConnected", "integer", 2),
    15: ("cpuTempDeciC", "integer", 0),
    16: ("uptimeS", "gauge", 0),
    17: ("cpuLoadPct", "gauge", 0),
    18: ("diskFreeMB", "gauge", 0),
    19: ("version", "string", "unknown"),
    20: ("clockOffsetMs", "integer", 0),
}
OIDS = [f"{BASE}.{n}.0" for n in sorted(OBJECTS)]

_cache = {"t": 0.0, "v": None}


def health():
    if time.time() - _cache["t"] > 5:
        try:
            with urllib.request.urlopen(URL, timeout=3) as r:
                _cache["v"] = json.loads(r.read())
        except Exception:
            _cache["v"] = None
        _cache["t"] = time.time()
    return _cache["v"]


def value(oid):
    n = int(oid[len(BASE) + 1:].split(".")[0])
    key, typ, down = OBJECTS[n]
    h = health()
    v = down if h is None else h.get(key, down)
    if typ == "counter":
        v = int(v) % (1 << 32)
    elif typ == "gauge":
        v = max(0, int(v))
    return typ, v


def oid_key(oid):
    return [int(x) for x in oid.strip(".").split(".")]


def reply(*lines):
    sys.stdout.write("\n".join(str(x) for x in lines) + "\n")
    sys.stdout.flush()


def main():
    while True:
        cmd = sys.stdin.readline()
        if not cmd:
            return
        cmd = cmd.strip().lower()
        if cmd == "ping":
            reply("PONG")
        elif cmd in ("get", "getnext"):
            oid = sys.stdin.readline().strip()
            if not oid.startswith("."):
                oid = "." + oid
            if cmd == "get":
                target = oid if oid in OIDS else None
            else:
                k = oid_key(oid)
                target = next((o for o in OIDS if oid_key(o) > k), None)
            if target is None:
                reply("NONE")
            else:
                typ, v = value(target)
                reply(target, typ, v)
        elif cmd == "set":
            sys.stdin.readline()
            sys.stdin.readline()
            reply("not-writable")
        else:
            reply("NONE")


if __name__ == "__main__":
    main()
