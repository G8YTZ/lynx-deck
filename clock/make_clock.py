#!/usr/bin/env python3
"""GB3OO station clock: the countdown's Deco Gold look, as a three-hand clock.

Same surround, sunburst, ring of 60 segments and typefaces as the
"Wholesome Viewing Follows" countdown (14 Nov 2026), with numerals and
hour, minute and sweep-second hands. Rendered ahead of time, so a clip
starting at 10:59:00 shows 10:59:00 at its first frame; Lynx Deck starts
it early by the chain delay so the hands are right on air.

  python3 make_clock.py face GB3OO_Clock.png          # the face for Lynx Deck (no hands)
  python3 make_clock.py --station GB3JT,MAIDSTONE,gb3jt.co.uk face GB3JT_Clock.png
  python3 make_clock.py still 10:09:32 [out.png]      # one frame
  python3 make_clock.py render 10:59:00 120 out.mp4   # a clip from that time

The two fonts (Italiana, Julius Sans One) are in fonts/ beside this script.
"""
import math
from pathlib import Path
import subprocess
import sys
from multiprocessing import Pool

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1920, 1080, 50
S = 2                                    # supersampling
CX, CY = W * S // 2, int(H * S * 0.47)
R_OUT, R_IN = 382 * S, 328 * S           # the countdown's segment ring
GAP_DEG = 1.7

GOLD = (214, 178, 96)
GOLD_LEAD = (255, 226, 150)
GOLD_DIM = (58, 48, 28)
GOLD_MID = (132, 110, 60)
TEXT = (226, 196, 128)
TEXT_SOFT = (150, 128, 84)
EDGE = (10, 8, 5)                        # a dark keyline round each hand

FONTS = Path(__file__).with_name("fonts")       # SIL Open Font Licence, see the OFL files
F_FIG = str(FONTS / "italiana-latin-400-normal.woff")
F_CAP = str(FONTS / "julius-sans-one-latin-400-normal.woff")

_bg = None
# call sign, town, web site; --station GB3JT,MAIDSTONE,gb3jt.co.uk for another
STATION = ["GB3OO", "FOLKESTONE", "gb3oo.co.uk"]
_fonts = {}


def font(path, size):
    key = (path, size)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(path, size)
    return _fonts[key]


def tracked(draw, cx, y, text, fnt, fill, track):
    widths = [draw.textlength(c, font=fnt) for c in text]
    x = cx - (sum(widths) + track * (len(text) - 1)) / 2
    for c, w in zip(text, widths):
        draw.text((x, y), c, font=fnt, fill=fill)
        x += w + track


def segment(i):
    a0 = math.radians(-93 + i * 6 + GAP_DEG / 2)       # centred on each minute
    a1 = math.radians(-93 + (i + 1) * 6 - GAP_DEG / 2)
    pts = [(CX + R_OUT * math.cos(a0 + (a1 - a0) * k / 4), CY + R_OUT * math.sin(a0 + (a1 - a0) * k / 4)) for k in range(5)]
    pts += [(CX + R_IN * math.cos(a0 + (a1 - a0) * k / 4), CY + R_IN * math.sin(a0 + (a1 - a0) * k / 4)) for k in range(4, -1, -1)]
    return pts


def background():
    global _bg
    if _bg is not None:
        return _bg
    w, h = W * S, H * S
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dx, dy = xx - CX, yy - CY
    r = np.hypot(dx, dy)
    lift = np.clip(1 - np.hypot(dx / (w * 0.5), dy / (h * 0.65)), 0, 1) ** 1.6 * 26
    ang = (np.degrees(np.arctan2(dy, dx)) + 360 + 3.75) % 360
    ray = (np.floor(ang / 7.5) % 2 == 0).astype(np.float32)
    fade = np.clip((r - (R_OUT + 30 * S)) / (60 * S), 0, 1) * np.clip(1 - (r - R_OUT) / (560 * S), 0, 1)
    inside = ((xx > 57 * S) & (xx < w - 57 * S) & (yy > 37 * S) & (yy < h - 37 * S)).astype(np.float32)
    k = ray * fade * inside * 0.05
    img = np.stack([lift + k * GOLD[0], lift + k * GOLD[1], lift * 1.15 + k * GOLD[2]], -1)
    img = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    # The ident's surround: fine rule, nested corner brackets, a diamond in each.
    fx0, fy0, fx1, fy1 = 55 * S, 35 * S, w - 55 * S, h - 35 * S
    d.rectangle([fx0, fy0, fx1, fy1], outline=(96, 80, 46), width=S)
    bright = (196, 164, 96)
    for cx, cy, sx, sy in ((fx0, fy0, 1, 1), (fx1, fy0, -1, 1), (fx1, fy1, -1, -1), (fx0, fy1, 1, -1)):
        for off, ln in ((0, 140), (12, 100), (25, 60)):
            x, y = cx + sx * off * S, cy + sy * off * S
            d.line([(x, y + sy * ln * S), (x, y), (x + sx * ln * S, y)], fill=bright, width=S)
        ddx, ddy, rr = cx + sx * 41 * S, cy + sy * 41 * S, 5 * S
        d.polygon([(ddx, ddy - rr), (ddx + rr, ddy), (ddx, ddy + rr), (ddx - rr, ddy)], fill=bright)
    # Fine rules either side of the ring, as on the countdown.
    for rr, col in ((R_OUT + 14 * S, GOLD_DIM), (R_IN - 14 * S, (40, 33, 19))):
        d.ellipse([CX - rr, CY - rr, CX + rr, CY + rr], outline=col, width=S)
    # The ring is the chapter ring now: every fifth segment full gold.
    for i in range(60):
        d.polygon(segment(i), fill=GOLD if i % 5 == 0 else GOLD_MID)
    # Numerals inside the ring, in Italiana, each centred on its own ink.
    f = font(F_FIG, 74 * S)
    rn = R_IN - 64 * S
    for n in range(1, 13):
        a = math.radians(-90 + n * 30)
        x, y = CX + rn * math.cos(a), CY + rn * math.sin(a)
        b = f.getbbox(str(n))
        d.text((x - (b[0] + b[2]) / 2, y - (b[1] + b[3]) / 2), str(n), font=f, fill=TEXT)
    # Lettering.
    tracked(d, CX, CY - 150 * S, STATION[0], font(F_CAP, 40 * S), TEXT, 20 * S)
    tracked(d, CX, CY + 104 * S, STATION[1], font(F_CAP, 18 * S), TEXT_SOFT, 8 * S)
    tracked(d, CX, h - 35 * S - 72 * S, STATION[2], font(F_CAP, 24 * S), TEXT_SOFT, 6 * S)   # the web site (Justin, 19 Nov)
    _bg = img
    return img


def rot(pts, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    # pts are (along, across) with along pointing at 12 o'clock
    return [(CX + y * s + x * c, CY - y * c + x * s) for x, y in pts]


def hand(d, deg, length, width, tail, fill):
    """A Deco lozenge hand: widest a third of the way out, a fine spine."""
    k = width / 2
    shape = [(0, -tail), (k * 0.45, 0), (k, length * 0.32), (0, length), (-k, length * 0.32), (-k * 0.45, 0)]
    d.polygon(rot(shape, deg), fill=fill, outline=EDGE, width=2 * S)
    d.line(rot([(0, length * 0.1), (0, length * 0.9)], deg), fill=EDGE, width=S)


def frame(t):
    """t: seconds since midnight (fractions sweep the second hand)."""
    img = background().copy()
    d = ImageDraw.Draw(img)
    sec = t % 60
    mins = (t / 60) % 60
    hrs = (t / 3600) % 12
    hand(d, hrs * 30, 200 * S, 30 * S, 34 * S, GOLD)   # the thinner one (Justin, 19 Nov)
    hand(d, mins * 6, 305 * S, 20 * S, 40 * S, GOLD)
    # Sweep second hand: a hairline, a diamond near the tip, a round counterweight.
    a = sec * 6
    d.line(rot([(0, -80 * S), (0, 318 * S)], a), fill=GOLD_LEAD, width=3 * S)
    dx, dy = rot([(0, 262 * S)], a)[0]
    r = 11 * S
    d.polygon(rot([(0, 262 * S - r), (r * 0.7, 262 * S), (0, 262 * S + r), (-r * 0.7, 262 * S)], a), fill=GOLD_LEAD)
    tx, ty = rot([(0, -62 * S)], a)[0]
    d.ellipse([tx - 10 * S, ty - 10 * S, tx + 10 * S, ty + 10 * S], fill=GOLD_LEAD)
    d.ellipse([CX - 15 * S, CY - 15 * S, CX + 15 * S, CY + 15 * S], fill=GOLD_LEAD, outline=EDGE, width=S)
    d.ellipse([CX - 5 * S, CY - 5 * S, CX + 5 * S, CY + 5 * S], fill=EDGE)
    return img.resize((W, H), Image.LANCZOS)


def parse(hms):
    p = [float(x) for x in hms.split(":")]
    return p[0] * 3600 + p[1] * 60 + (p[2] if len(p) > 2 else 0)


_start = 0.0


def raw(n):
    return frame(_start + n / FPS).tobytes()


def render(start, dur, out):
    global _start
    _start = start
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", str(dur),
           "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-g", str(FPS),
           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    with Pool() as pool:
        for data in pool.imap(raw, range(int(dur * FPS)), chunksize=8):
            p.stdin.write(data)
    p.stdin.close()
    return p.wait()


if __name__ == "__main__":
    if sys.argv[1] == "--station":
        STATION[:] = sys.argv[2].split(",")
        del sys.argv[1:3]
    if sys.argv[1] == "face":
        background().resize((W, H), Image.LANCZOS).save(sys.argv[2])
    elif sys.argv[1] == "still":
        frame(parse(sys.argv[2])).save(sys.argv[3] if len(sys.argv) > 3 else "clock.png")
    else:
        sys.exit(render(parse(sys.argv[2]), float(sys.argv[3]), sys.argv[4]))
