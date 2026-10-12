#!/usr/bin/env python3
"""
K South League: gameweek round-up video maker.

Reads a gameweek from your site (or a JSON file), draws a 1080x1920 vertical video
(intro, one scene per match, results, table, outro), records a voice-over and writes an MP4.

    python make_video.py --api https://k-south-league.vercel.app/api/data --week 3
    python make_video.py --data sample-data.json --week 2 --voice none

See README.md for setup.
"""
import argparse, asyncio, base64, io, json, math, os, re, shutil, subprocess, sys, tempfile, urllib.request, wave
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
W, H = 1080, 1920
FPS = 30
SR = 24000

NAVY, NAVY2, NAVY_D = (13, 26, 74), (27, 43, 107), (8, 16, 48)
ORG, SKY, WHITE, MUT = (255, 90, 31), (127, 212, 255), (255, 255, 255), (154, 167, 214)
YEL, RED, GREEN = (242, 194, 0), (229, 72, 77), (25, 184, 106)

LEAGUE = "K SOUTH LEAGUE"
PLACE = "EMBAKASI WEST  ·  EST. 2024"

# How the voice should SAY a name. Left side is matched as a whole word/phrase in the script text.
PRONOUNCE = {
    "2nd Avenue": "Second Avenue",
    "FC": "F C",
    "K South": "K South",
}

# ----------------------------------------------------------------------------- drawing helpers


@lru_cache(None)
def font(kind, size, weight=900):
    name = "BigShouldersDisplay[wght].ttf" if kind == "d" else "Archivo[wdth,wght].ttf"
    try:
        f = ImageFont.truetype(str(ASSETS / "fonts" / name), size)
        vals = []
        for a in f.get_variation_axes():
            nm = a["name"].decode() if isinstance(a["name"], bytes) else a["name"]
            vals.append(weight if "eight" in nm else 100 if "idth" in nm else a["default"])
        f.set_variation_by_axes(vals)
        return f
    except Exception:
        for fb in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"):
            try:
                return ImageFont.truetype(fb, size)
            except Exception:
                pass
        return ImageFont.load_default()


def hex2rgb(h):
    h = (h or "#8a93b8").lstrip("#")
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return (138, 147, 184)


def ease(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def back(t):
    t = max(0.0, min(1.0, t))
    c1 = 1.70158
    return 1 + (c1 + 1) * (t - 1) ** 3 + c1 * (t - 1) ** 2


def prog(t, start, dur):
    return max(0.0, min(1.0, (t - start) / dur)) if dur > 0 else float(t >= start)


@lru_cache(maxsize=1024)
def text(txt, kind, size, weight, fill, stroke=0, stroke_fill=(0, 0, 0)):
    f = font(kind, size, weight)
    l, t, r, b = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), txt, font=f, stroke_width=stroke)
    pad = 4
    im = Image.new("RGBA", (r - l + 2 * pad, b - t + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((pad - l, pad - t), txt, font=f, fill=fill + (255,), stroke_width=stroke, stroke_fill=stroke_fill + (255,))
    return im


def fit(txt, kind, max_w, size, weight, fill, min_size=26, **kw):
    while size > min_size:
        l = text(txt, kind, size, weight, fill, **kw)
        if l.width - 8 <= max_w:
            return l
        size -= 2
    return text(txt, kind, min_size, weight, fill, **kw)


def name_layer(name, maxw, size=50, weight=800, fill=WHITE):
    """Team name in capitals, wrapped onto two lines if it does not fit."""
    name = name.upper()
    one = text(name, "d", size, weight, fill)
    words = name.split()
    if one.width <= maxw or len(words) < 2:
        return one if one.width <= maxw else fit(name, "d", maxw, size, weight, fill)
    best = None
    for k in range(1, len(words)):
        la, lb = text(" ".join(words[:k]), "d", size, weight, fill), text(" ".join(words[k:]), "d", size, weight, fill)
        w = max(la.width, lb.width)
        if best is None or w < best[0]:
            best = (w, la, lb)
    w, la, lb = best
    if w > maxw:
        return fit(name, "d", maxw, size, weight, fill)
    im = Image.new("RGBA", (w, la.height + lb.height - 8), (0, 0, 0, 0))
    im.alpha_composite(la, ((w - la.width) // 2, 0))
    im.alpha_composite(lb, ((w - lb.width) // 2, la.height - 8))
    return im


def put(base, layer, x, y, a=1.0, s=1.0, anchor="c"):
    """Paste an RGBA layer onto base. (x, y) is the centre, or left/right edge for anchor l/r."""
    if layer is None or a <= 0.004:
        return
    if s != 1.0:
        layer = layer.resize((max(1, int(layer.width * s)), max(1, int(layer.height * s))), Image.BILINEAR)
    w, h = layer.size
    px = x - w / 2 if anchor == "c" else x if anchor == "l" else x - w
    m = layer.getchannel("A")
    if a < 1:
        m = m.point([int(i * a) for i in range(256)])
    base.paste(layer, (int(round(px)), int(round(y - h / 2))), m)


def shape(w, h, fn, ss=2):
    im = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    fn(ImageDraw.Draw(im), w * ss, h * ss, ss)
    return im.resize((w, h), Image.LANCZOS)


@lru_cache(None)
def rrect(w, h, r, fill, outline=None, width=0):
    return shape(w, h, lambda d, W_, H_, s: d.rounded_rectangle((0, 0, W_ - 1, H_ - 1), r * s, fill=fill, outline=outline, width=width * s))


@lru_cache(None)
def icon(kind, size=44):
    def draw(d, N, _, s):
        if kind == "goal":
            d.ellipse((N * .04, N * .04, N * .96, N * .96), fill=(255, 255, 255, 255), outline=(20, 20, 30, 255), width=s * 2)
            pts = [(N / 2 + N * .2 * math.sin(math.radians(a)), N / 2 - N * .2 * math.cos(math.radians(a))) for a in range(0, 360, 72)]
            d.polygon(pts, fill=(20, 20, 30, 255))
            for a in range(0, 360, 72):
                d.ellipse((N / 2 + N * .38 * math.sin(math.radians(a + 36)) - N * .07, N / 2 - N * .38 * math.cos(math.radians(a + 36)) - N * .07,
                           N / 2 + N * .38 * math.sin(math.radians(a + 36)) + N * .07, N / 2 - N * .38 * math.cos(math.radians(a + 36)) + N * .07), fill=(20, 20, 30, 255))
        elif kind == "assist":
            d.ellipse((N * .04, N * .04, N * .96, N * .96), fill=SKY + (255,))
            f = font("d", int(N * .62), 900)
            d.text((N / 2, N / 2), "A", font=f, fill=NAVY + (255,), anchor="mm")
        elif kind in ("yellow", "red"):
            d.rounded_rectangle((N * .22, N * .06, N * .78, N * .94), N * .08, fill=(YEL if kind == "yellow" else RED) + (255,))
        elif kind == "cs":
            d.polygon([(N * .1, N * .1), (N * .9, N * .1), (N * .9, N * .55), (N * .5, N * .95), (N * .1, N * .55)], fill=GREEN + (255,))
            d.line([(N * .3, N * .5), (N * .46, N * .66), (N * .72, N * .32)], fill=(255, 255, 255, 255), width=int(N * .1), joint="curve")
    return shape(size, size, draw, 3)


def lum(c):
    return .299 * c[0] + .587 * c[1] + .114 * c[2]


class Badges:
    dirs = [ASSETS / "badges", HERE.parent / "public" / "badges"]
    cache_dir = Path(tempfile.gettempdir()) / "ksl_badges"

    @classmethod
    @lru_cache(None)
    def load(cls, ref):
        if not ref:
            return None
        try:
            if ref.startswith("data:"):
                return Image.open(io.BytesIO(base64.b64decode(ref.split(",", 1)[1]))).convert("RGBA")
            name = os.path.basename(ref.split("?")[0])
            for d in cls.dirs:
                if (d / name).exists():
                    return Image.open(d / name).convert("RGBA")
            if ref.startswith("http"):
                cls.cache_dir.mkdir(exist_ok=True)
                p = cls.cache_dir / name
                if not p.exists():
                    urllib.request.urlretrieve(ref, p)
                return Image.open(p).convert("RGBA")
        except Exception as e:
            print("  (couldn't load badge %s: %s)" % (ref[:40], e))
        return None


@lru_cache(None)
def crest(tid, badge, color, short, size):
    S = 2
    N = size * S
    col = hex2rgb(color)
    im = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    img = Badges.load(badge)

    def put_img(img, bw, bh):
        r = min(bw / img.width, bh / img.height)
        sm = img.resize((max(1, int(img.width * r)), max(1, int(img.height * r))), Image.LANCZOS)
        im.alpha_composite(sm, ((N - sm.width) // 2, (N - sm.height) // 2))

    if img is not None and img.width / img.height > 1.6:  # wide wordmark: white plate
        h = int(N * .6)
        y0 = (N - h) // 2
        d.rounded_rectangle((0, y0, N - 1, y0 + h), int(N * .06), fill=(255, 255, 255, 255), outline=col + (255,), width=S * 6)
        put_img(img, int(N * .88), int(h * .82))
    else:
        d.ellipse((0, 0, N - 1, N - 1), fill=(10, 18, 58, 255), outline=col + (255,), width=S * 7)
        if img is not None:
            put_img(img, int(N * .72), int(N * .72))
        else:
            d.ellipse((S * 7, S * 7, N - 1 - S * 7, N - 1 - S * 7), fill=col + (255,))
            d.text((N / 2, N / 2), (short or "?")[0], font=font("d", int(N * .55), 900), fill=(20, 20, 30, 255) if lum(col) > 150 else WHITE + (255,), anchor="mm")
    return im.resize((size, size), Image.LANCZOS)


def team_crest(t, size):
    return crest(t["id"], t.get("badge") or "", t.get("c") or "", t.get("short") or "", size)


@lru_cache(None)
def logo(height):
    p = ASSETS / "logo.png"
    if not p.exists():
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    im = Image.open(p).convert("RGBA")
    return im.resize((int(im.width * height / im.height), height), Image.LANCZOS)


@lru_cache(None)
def pitch():
    y = np.linspace(0, 1, H)[:, None, None]
    arr = np.array(NAVY2, float) * (1 - y) + np.array(NAVY_D, float) * y
    arr = np.broadcast_to(arr, (H, W, 3)).copy()
    for i, y0 in enumerate(range(0, H, 160)):
        if i % 2:
            arr[y0:y0 + 160] *= 1.045
    im = Image.fromarray(np.clip(arr, 0, 255).astype("uint8"))
    d = ImageDraw.Draw(im, "RGBA")
    ln = (255, 255, 255, 26)
    d.ellipse((W / 2 - 280, H / 2 - 280, W / 2 + 280, H / 2 + 280), outline=ln, width=7)
    d.ellipse((W / 2 - 9, H / 2 - 9, W / 2 + 9, H / 2 + 9), fill=ln)
    d.line((0, H / 2, W, H / 2), fill=ln, width=7)
    d.rectangle((W / 2 - 340, -10, W / 2 + 340, 250), outline=ln, width=7)
    d.rectangle((W / 2 - 340, H - 250, W / 2 + 340, H + 10), outline=ln, width=7)
    return im


def chrome(week, header=True):
    im = pitch().copy()
    d = ImageDraw.Draw(im)
    for i, c in enumerate((ORG, WHITE, SKY)):
        d.rectangle((W * i // 3, H - 16, W * (i + 1) // 3, H), fill=c)
    foot = text(PLACE, "a", 28, 700, MUT)
    im.paste(foot, (int(W / 2 - foot.width / 2), H - 70), foot)
    if header:
        lg = logo(130)
        im.paste(lg, (70, 70), lg)
        t1 = text(LEAGUE, "d", 78, 900, WHITE)
        t2 = text("GAMEWEEK %d" % week, "d", 54, 800, SKY)
        im.paste(t1, (230, 82), t1)
        im.paste(t2, (230, 150), t2)
    return im


# ----------------------------------------------------------------------------- data


def load_data(a):
    if a.data:
        return json.load(open(a.data, encoding="utf-8"))
    
    url = a.api.strip()
    while "https://https://" in url:
        url = url.replace("https://https://", "https://")
    while "http://http://" in url:
        url = url.replace("http://http://", "http://")
        
    print(f"Attempting to fetch from: '{url}'")
    req = urllib.request.Request(url, headers={"User-Agent": "ksl-video/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def fmt_day(d):
    dt = datetime.strptime(d, "%Y-%m-%d")
    return "%s %d %s" % (dt.strftime("%a").upper(), dt.day, dt.strftime("%b").upper())


def played(f):
    return f.get("hg") is not None and f.get("ag") is not None


def ordinal(n):
    return "%d%s" % (n, "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


POS = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh", 8: "eighth"}
NUM = ["nil", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
nw = lambda n: NUM[n] if 0 <= n < len(NUM) else str(n)


def join(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


class Model:
    def __init__(self, data, week):
        self.teams = {t["id"]: t for t in data["teams"]}
        self.players = {p["id"]: p for p in data.get("players", [])}
        self.fixtures = data["fixtures"]
        self.stats = data.get("stats", [])
        dates = sorted({f["date"] for f in self.fixtures})
        self.wk = lambda f: int(f["week"]) if f.get("week") else dates.index(f["date"]) + 1
        weeks = sorted({self.wk(f) for f in self.fixtures})
        if week is None:
            done = [self.wk(f) for f in self.fixtures if played(f)]
            if not done:
                sys.exit("No results entered yet, so there is no gameweek to summarise.")
            week = max(done)
        self.week = week
        self.next_week = next((w for w in weeks if w > week), None)
        self.next_date = min((f["date"] for f in self.fixtures if self.wk(f) == self.next_week), default=None) if self.next_week else None
        fx = sorted([f for f in self.fixtures if self.wk(f) == week and played(f)], key=lambda f: (f["date"], f.get("time", "")))
        if not fx:
            sys.exit("Gameweek %d has no finished matches yet." % week)
        self.dates = sorted({f["date"] for f in fx})
        self.matches = [self.match(f) for f in fx]
        ids = {f["id"] for f in fx}
        ws = [s for s in self.stats if s["fixture"] in ids]
        self.yellows = sum(int(s.get("yellow") or 0) for s in ws)
        self.reds = sum(int(s.get("red") or 0) for s in ws)
        self.goals = sum(m["hg"] + m["ag"] for m in self.matches)
        self.cleans = sum((m["hg"] == 0) + (m["ag"] == 0) for m in self.matches)
        agg = {}
        for s in ws:
            if s.get("goals"):
                agg[s["player"]] = agg.get(s["player"], 0) + int(s["goals"])
        best = sorted(agg.items(), key=lambda kv: (-kv[1], self.pname(kv[0])))
        self.top = (self.pname(best[0][0]), best[0][1]) if best else None
        self.table = self.standings(week)
        self.prev = self.standings(week - 1) if any(self.wk(f) < week and played(f) for f in self.fixtures) else None

    def pname(self, pid):
        return self.players.get(pid, {}).get("name", "Unknown")

    def match(self, f):
        sides = {}
        for tid in (f["home"], f["away"]):
            rows = [s for s in self.stats if s["fixture"] == f["id"] and s["team"] == tid and s["player"] in self.players]
            lst = lambda k: [(self.pname(s["player"]), int(s[k])) for s in rows if int(s.get(k) or 0) > 0]
            sides[tid] = dict(has=bool(rows), goals=lst("goals"), assists=lst("assists"), yellow=lst("yellow"), red=lst("red"),
                              gk=[self.pname(s["player"]) for s in rows if s.get("played") and self.players[s["player"]].get("pos") == "GK"],
                              n=sum(int(s.get("goals") or 0) for s in rows))
        return dict(f=f, home=self.teams[f["home"]], away=self.teams[f["away"]], hg=int(f["hg"]), ag=int(f["ag"]), sides=sides)

    def standings(self, upto):
        rows = {t: dict(t=self.teams[t], p=0, gf=0, ga=0, pts=0) for t in self.teams}
        for f in self.fixtures:
            if not played(f) or self.wk(f) > upto:
                continue
            for tid, g, c in ((f["home"], f["hg"], f["ag"]), (f["away"], f["ag"], f["hg"])):
                r = rows.get(tid)
                if r:
                    r["p"] += 1; r["gf"] += g; r["ga"] += c
                    r["pts"] += 3 if g > c else 1 if g == c else 0
        return sorted(rows.values(), key=lambda r: (-r["pts"], -(r["gf"] - r["ga"]), -r["gf"], r["t"]["name"]))


# ----------------------------------------------------------------------------- narration with banter & edge


def goal_phrase(lst):
    out = []
    for n, k in lst:
        out.append(n if k == 1 else n + " twice" if k == 2 else n + " with a massive hat-trick" if k == 3 else "%s with %s absolute goals" % (n, nw(k)))
    return join(out)


def narration(M):
    n = len(M.matches)
    sc = {}
    sc["intro"] = [("a", "Damn, welcome back to Gameweek %d of the K South League! Let's see who showed up and who completely messed it up." % M.week)]
    for i, m in enumerate(M.matches):
        h, a, hg, ag = m["home"]["name"], m["away"]["name"], m["hg"], m["ag"]
        diff = abs(hg - ag)
        
        if hg > ag:
            if diff >= 3:
                res = "%s completely destroyed %s, smashing them %s to %s!" % (h, a, nw(hg), nw(ag))
            else:
                res = "%s held their nerve and beat %s, %s to %s." % (h, a, nw(hg), nw(ag))
        elif ag > hg:
            if diff >= 3:
                res = "%s went away and absolutely humiliated %s, crushing them %s to %s!" % (a, h, nw(ag), nw(hg))
            else:
                res = "%s pulled off a sweet away win at %s, taking it %s to %s." % (a, h, nw(ag), nw(hg))
        elif hg == 0:
            res = "%s and %s played out a bloody boring goalless draw. Absolute snooze fest." % (h, a)
        else:
            res = "%s and %s shared the points in a wild %s all draw." % (h, a, nw(hg))
            
        segs = [("result", ("In match %s, " % nw(i + 1) if n > 1 else "") + res)]
        parts = []
        for t in (m["home"], m["away"]):
            g = m["sides"][t["id"]]["goals"]
            if g:
                parts.append("%s put in work for %s." % (goal_phrase(g), t["name"]))
        if parts:
            segs.append(("goals", " ".join(parts)))
            
        y = [nm for t in (m["home"], m["away"]) for nm, _ in m["sides"][t["id"]]["yellow"]]
        r = [nm for t in (m["home"], m["away"]) for nm, _ in m["sides"][t["id"]]["red"]]
        cs = []
        if len(y) > 4:
            cs.append("Ref was handing cards out like candy, with %s yellow cards flying around." % nw(len(y)))
        elif y:
            cs.append(("A clumsy yellow card for %s." if len(y) == 1 else "Yellow cards handed out to %s.") % join(y))
        if r:
            cs.append("And damn, %s got sent packing!" % join(r))
        if cs:
            segs.append(("cards", " ".join(cs)))
            
        clean = [t["name"] for t, c in ((m["home"], ag), (m["away"], hg)) if c == 0 and (hg + ag) > 0]
        if clean:
            segs.append(("cs", "Props to %s for locking down a clean sheet." % join(clean)))
            
        sc["m%d" % i] = segs
        
    r = ["Hell of a week. That is %s goals, %s and %s total." % (nw(M.goals), "one lonely yellow card" if M.yellows == 1 else "%s yellow cards" % nw(M.yellows),
                                                          "zero red cards, boring" if M.reds == 0 else "one red card" if M.reds == 1 else "%s brutal red cards" % nw(M.reds))]
    if M.top:
        r.append("Shoutout to %s, absolute baller of the week with %s." % (M.top[0], nw(M.top[1]) + (" goal" if M.top[1] == 1 else " goals")))
    sc["results"] = [("a", " ".join(r))]
    
    t0 = M.table
    s = ["%s are sitting pretty at the top with %s points." % (t0[0]["t"]["name"], t0[0]["pts"])] if t0[0]["p"] else ["The table is wide open, anybody's game."]
    if len(t0) > 1 and t0[0]["p"]:
        s.append("%s are chasing hard in second with %s." % (t0[1]["t"]["name"], t0[1]["pts"]))
    if M.prev:
        pp = {r["t"]["id"]: i for i, r in enumerate(M.prev)}
        mv = sorted(((pp[r["t"]["id"]] - i, r["t"]["name"], i + 1) for i, r in enumerate(t0)), reverse=True)
        if mv and mv[0][0] > 0:
            s.append("Watch out, %s made a massive jump up to %s." % (mv[0][1], POS.get(mv[0][2], ordinal(mv[0][2]))))
    sc["table"] = [("a", " ".join(s))]
    
    if M.next_date:
        dt = datetime.strptime(M.next_date, "%Y-%m-%d")
        o = "Don't slack off. Gameweek %d is coming up fast on %s the %s of %s. Catch you next time!" % (M.next_week, dt.strftime("%A"), ordinal(dt.day), dt.strftime("%B"))
    else:
        o = "That's it for this round. Keep up with the K South League or get left behind."
    sc["outro"] = [("a", o)]
    return sc


# ----------------------------------------------------------------------------- scenes
# Each scene: background image + draw(img, t, cues) where cues maps a name to the second its sentence starts.


def chip(txt, fill=ORG, color=NAVY):
    t = text(txt, "d", 46, 900, color)
    c = rrect(t.width + 70, 74, 37, fill + (255,))
    c = c.copy()
    c.alpha_composite(t, (35, (74 - t.height) // 2))
    return c


def slide(t, start, dx=0, dy=0, dur=.6):
    p = ease(prog(t, start, dur))
    return p, dx * (1 - p), dy * (1 - p)


def scene_intro(M):
    bg = chrome(M.week, header=False)
    ds = " AND ".join(fmt_day(d) for d in M.dates[:2]) if len(M.dates) > 1 else fmt_day(M.dates[0])

    def draw(im, t, C):
        put(im, text(LEAGUE + "  ·  EMBAKASI WEST", "d", 54, 800, SKY), W / 2, 130, a=prog(t, .1, .5))
        put(im, logo(560), W / 2, 590, a=prog(t, .1, .4), s=.55 + .45 * back(prog(t, .1, .9)))
        rw = int((W - 140) * ease(prog(t, .7, .55)))
        if rw > 10:
            rb = rrect(W - 140, 200, 18, ORG + (255,)).resize((rw, 200))
            put(im, rb, W / 2, 1060)
            put(im, text("GAMEWEEK", "d", 170, 900, NAVY), W / 2, 1062, a=prog(t, 1.0, .3))
        n = text(str(M.week), "d", 560, 900, WHITE, stroke=10, stroke_fill=ORG)
        put(im, n, W / 2, 1450, a=prog(t, 1.2, .4), s=.7 + .3 * back(prog(t, 1.2, .8)))
        put(im, text(ds, "d", 90, 800, SKY), W / 2, 1745, a=prog(t, 1.9, .5))
    return bg, draw


def side_rows(S, flag_cs):
    rows = []
    for nm, k in S["goals"]:
        rows.append(("goals", "goal", nm + (" ×%d" % k if k > 1 else "")))
    if not S["goals"]:
        rows.append(("goals", None, "No goals"))
    for nm, k in S["assists"]:
        rows.append(("goals", "assist", nm + (" ×%d" % k if k > 1 else "")))
    for nm, _ in S["yellow"]:
        rows.append(("cards", "yellow", nm))
    for nm, _ in S["red"]:
        rows.append(("cards", "red", nm))
    if flag_cs:
        rows.append(("cs", "cs", "Clean sheet" + (" · " + ", ".join(S["gk"]) if S["gk"] else "")))
    if len(rows) > 8:
        rows = rows[:7] + [("cards", None, "+%d more" % (len(rows) - 7))]
    return rows


def scene_match(M, i):
    m = M.matches[i]
    bg = chrome(M.week)
    n = len(M.matches)
    h, a = m["home"], m["away"]
    panel = rrect(1000, 800, 36, (255, 255, 255, 16), (255, 255, 255, 40), 2)
    cols = [(h, 285), (a, 805)]
    rows = {t["id"]: side_rows(m["sides"][t["id"]], (m["ag"] if t is h else m["hg"]) == 0 and m["hg"] + m["ag"] > 0) for t in (h, a)}
    has = m["sides"][h["id"]]["has"] or m["sides"][a["id"]]["has"]

    def draw(im, t, C):
        put(im, chip("MATCH %d OF %d" % (i + 1, n)), W / 2, 330, a=prog(t, .1, .4), s=.9 + .1 * ease(prog(t, .1, .4)))
        for k, tm in enumerate((h, a)):
            x = 210 if k == 0 else 870
            p, dx, _ = slide(t, .2 + .12 * k, dx=-320 if k == 0 else 320, dur=.75)
            put(im, team_crest(tm, 290), x + dx, 640, a=p)
            put(im, name_layer(tm["name"], 340, 74, 900), x + dx, 850, a=p)
        r0 = C.get("result", .5)
        pr = prog(t, r0, 1.0)
        hs, as_ = round(m["hg"] * ease(pr)), round(m["ag"] * ease(pr))
        pop = 1 + .12 * math.sin(math.pi * prog(t, r0 + 1.0, .35))
        put(im, text(str(hs), "d", 270, 900, WHITE), 440, 640, a=prog(t, r0 - .1, .3), s=pop)
        put(im, text("-", "d", 200, 900, ORG), 540, 640, a=prog(t, r0 - .1, .3))
        put(im, text(str(as_), "d", 270, 900, WHITE), 640, 640, a=prog(t, r0 - .1, .3), s=pop)
        put(im, chip("FULL TIME", SKY, NAVY), W / 2, 800, a=prog(t, r0 + .9, .4))
        put(im, panel, W / 2, 1360, a=prog(t, .5, .5))
        for tm, cx in cols:
            put(im, text(tm["short"], "d", 70, 900, hex2rgb(tm["c"]) if lum(hex2rgb(tm["c"])) > 115 else WHITE), cx, 1010, a=prog(t, .6, .4))
        if not has:
            put(im, text("Match details not recorded", "a", 40, 600, MUT), W / 2, 1360, a=prog(t, 1.0, .4))
            return
        put(im, rrect(4, 640, 2, (255, 255, 255, 40)), W / 2, 1420, a=prog(t, .6, .4))
        for tm, cx in cols:
            seen = {}
            for kind, ic, label in rows[tm["id"]]:
                j = seen.get(kind, 0)
                seen[kind] = j + 1
                st = C.get(kind, C.get("goals", .5)) if kind != "cs" else C.get("cs", C.get("cards", C.get("goals", .5)))
                p, dx, _ = slide(t, st + .25 * j, dx=40, dur=.45)
                yy = 1105 + 72 * (len(rows[tm["id"]]) and rows[tm["id"]].index((kind, ic, label)))
                if ic:
                    put(im, icon(ic, 46), cx - 215 + dx, yy, a=p)
                put(im, fit(label, "a", 385 if ic else 420, 42, 700, WHITE if ic else MUT), cx - 175 + dx if ic else cx - 215 + dx, yy, a=p, anchor="l")
    return bg, draw


def scene_results(M):
    bg = chrome(M.week)
    ms = M.matches[:5]
    step = 270 if len(ms) <= 4 else 220
    ch = step - 30

    def draw(im, t, C):
        put(im, text("RESULTS", "d", 190, 900, WHITE), W / 2, 365, a=prog(t, .1, .4))
        for i, m in enumerate(ms):
            p, _, dy = slide(t, .4 + .3 * i, dy=60, dur=.55)
            y = 660 + step * i + dy
            put(im, rrect(1000, ch, 30, (255, 255, 255, 18), (255, 255, 255, 44), 2), W / 2, y, a=p)
            cs = 112 if step >= 270 else 84
            for tm, x in ((m["home"], 170), (m["away"], 910)):
                put(im, team_crest(tm, cs), x, y - ch * .16, a=p)
                put(im, name_layer(tm["name"], 280, 48 if step >= 270 else 40), x, y + ch * .33, a=p)
            put(im, text("%d - %d" % (m["hg"], m["ag"]), "d", 150, 900, ORG), W / 2, y, a=p)
        ty = 660 + step * (len(ms) - 1) + ch / 2 + 45
        tiles = [("GOALS", M.goals), ("YELLOWS", M.yellows), ("REDS", M.reds), ("CLEAN SHEETS", M.cleans)]
        for k, (lab, v) in enumerate(tiles):
            p, _, dy = slide(t, 1.6 + .15 * k, dy=40, dur=.5)
            x = 165 + 250 * k
            put(im, rrect(230, 190, 26, (255, 255, 255, 18), (255, 255, 255, 44), 2), x, ty + 95 + dy, a=p)
            put(im, text(str(v), "d", 110, 900, ORG), x, ty + 75 + dy, a=p)
            put(im, text(lab, "a", 26, 700, MUT), x, ty + 152 + dy, a=p)
        if M.top:
            put(im, text("TOP SCORER  %s  (%d)" % (M.top[0].upper(), M.top[1]), "d", 64, 800, SKY), W / 2, ty + 290, a=prog(t, 2.4, .5))
    return bg, draw


def scene_table(M):
    bg = chrome(M.week)
    rows = M.table
    n = len(rows)
    step = min(170, int(1200 / max(n, 1)))
    pp = {r["t"]["id"]: i for i, r in enumerate(M.prev)} if M.prev else None

    def draw(im, t, C):
        put(im, text("TABLE", "d", 190, 900, WHITE), W / 2, 330, a=prog(t, .1, .4))
        put(im, text("AFTER GAMEWEEK %d" % M.week, "d", 54, 800, SKY), W / 2, 450, a=prog(t, .2, .4))
        for lab, x in (("P", 700), ("GD", 790), ("PTS", 900)):
            put(im, text(lab, "a", 28, 700, MUT), x, 520, a=prog(t, .4, .4))
        for i, r in enumerate(rows):
            p, dx, _ = slide(t, .5 + .2 * i, dx=120, dur=.5)
            y = 590 + step * i + step / 2 - 30
            put(im, rrect(1000, step - 16, 26, (255, 255, 255, 22 if i else 40), (255, 255, 255, 44), 2), W / 2 + dx, y, a=p)
            if i == 0:
                put(im, rrect(12, step - 16, 6, ORG + (255,)), 46 + dx, y, a=p)
            put(im, text(str(i + 1), "d", 80, 900, ORG if i == 0 else WHITE), 105 + dx, y, a=p)
            put(im, team_crest(r["t"], 96), 215 + dx, y, a=p)
            put(im, fit(r["t"]["name"], "d", 300, 64, 800, WHITE), 285 + dx, y, a=p, anchor="l")
            put(im, text(str(r["p"]), "a", 38, 600, WHITE), 700 + dx, y, a=p)
            g = r["gf"] - r["ga"]
            put(im, text(("+" if g > 0 else "") + str(g), "a", 38, 600, WHITE), 790 + dx, y, a=p)
            put(im, text(str(r["pts"]), "d", 84, 900, ORG), 900 + dx, y, a=p)
            if pp is not None:
                d = pp[r["t"]["id"]] - i
                if d:
                    up = d > 0
                    tri = shape(32, 26, lambda dr, W_, H_, s: dr.polygon([(W_ / 2, 0), (W_, H_), (0, H_)] if up else [(0, 0), (W_, 0), (W_ / 2, H_)], fill=(GREEN if up else RED) + (255,)))
                    put(im, tri, 1008 + dx, y - 20, a=p)
                    put(im, text(str(abs(d)), "a", 30, 800, GREEN if up else RED), 1008 + dx, y + 20, a=p)
    return bg, draw


def scene_outro(M, cta):
    bg = chrome(M.week, header=False)

    def draw(im, t, C):
        put(im, logo(470), W / 2, 520, a=prog(t, .1, .4), s=.6 + .4 * back(prog(t, .1, .9)))
        put(im, text("THAT'S A WRAP", "d", 170, 900, WHITE), W / 2, 960, a=prog(t, .7, .5))
        if M.next_week:
            rb = rrect(W - 200, 210, 18, ORG + (255,))
            p = ease(prog(t, 1.2, .5))
            put(im, rb, W / 2, 1260, a=p)
            put(im, text("NEXT UP: GAMEWEEK %d" % M.next_week, "d", 92, 900, NAVY), W / 2, 1220, a=p)
            put(im, text(fmt_day(M.next_date), "d", 66, 800, NAVY), W / 2, 1310, a=p)
        put(im, text(cta, "d", 74, 800, SKY), W / 2, 1530, a=prog(t, 1.8, .5))
        put(im, text("EMBAKASI WEST", "d", 54, 700, MUT), W / 2, 1625, a=prog(t, 2.0, .5))
    return bg, draw


# ----------------------------------------------------------------------------- voice


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg") or sys.exit("ffmpeg not found. Run: pip install imageio-ffmpeg")


def to_wav(src, dst):
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(src), "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", str(dst)], check=True)


def say(txt):
    for k, v in PRONOUNCE.items():
        txt = re.sub(r"(?<![\w])%s(?![\w])" % re.escape(k), v, txt)
    return txt


KOKORO_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"


class Voice:
    def __init__(self, backend, name, rate):
        self.rate = rate
        order = [backend] if backend != "auto" else ["edge", "kokoro", "sapi"]
        self.kind, self.err = None, []
        for b in order:
            try:
                getattr(self, "_init_" + b)(name)
                self.kind = b
                break
            except Exception as e:
                self.err.append("%s: %s" % (b, e))
        if self.kind is None and backend not in ("none",):
            print("  No voice engine available, the video will be silent:")
            for e in self.err:
                print("   -", e)
        print("  Voice engine:", self.kind or "none (silent)")

    # --- engines
    def _init_none(self, name):
        raise RuntimeError("voice disabled")

    def _init_edge(self, name):
        import edge_tts  # pip install edge-tts (needs internet)
        self.edge, self.name = edge_tts, name or "en-KE-ChilembaNeural"
        self._edge_say("Ready.", Path(tempfile.gettempdir()) / "ksl_probe.mp3")

    def _edge_say(self, txt, out):
        async def go():
            try:
                await self.edge.Communicate(txt, self.name, rate=self.rate).save(str(out))
            except Exception:
                if self.name != "en-GB-RyanNeural":  # fall back to a voice that always exists
                    self.name = "en-GB-RyanNeural"
                    await self.edge.Communicate(txt, self.name, rate=self.rate).save(str(out))
                else:
                    raise
        asyncio.run(go())

    def _init_kokoro(self, name):
        import soundfile  # noqa: F401
        from kokoro_onnx import Kokoro  # pip install kokoro-onnx soundfile
        d = HERE / "tts"
        d.mkdir(exist_ok=True)
        for f in ("kokoro-v1.0.int8.onnx", "voices-v1.0.bin"):
            if not (d / f).exists():
                print("  downloading voice model %s (one time) ..." % f)
                urllib.request.urlretrieve(KOKORO_URL + f, d / f)
        self.k, self.name = Kokoro(str(d / "kokoro-v1.0.int8.onnx"), str(d / "voices-v1.0.bin")), name or "bm_george"

    def _init_sapi(self, name):
        import pyttsx3  # pip install pyttsx3 (Windows offline voices)
        self.sapi = pyttsx3

    # --- speak one sentence to a wav at SR
    def speak(self, txt, out):
        txt = say(txt)
        if self.kind == "edge":
            tmp = Path(str(out) + ".mp3")
            self._edge_say(txt, tmp)
            to_wav(tmp, out)
        elif self.kind == "kokoro":
            import soundfile as sf
            s, sr = self.k.create(txt, voice=self.name, speed=1.04, lang="en-gb" if self.name.startswith("b") else "en-us")
            tmp = Path(str(out) + ".tmp.wav")
            sf.write(str(tmp), s, sr)
            to_wav(tmp, out)
        elif self.kind == "sapi":
            e = self.sapi.init()
            e.setProperty("rate", 185)
            tmp = Path(str(out) + ".tmp.wav")
            e.save_to_file(txt, str(tmp))
            e.runAndWait()
            to_wav(tmp, out)
        else:
            return None
        return out


def wav_array(p):
    with wave.open(str(p)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


# ----------------------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description="Make a gameweek round-up video for the K South League.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--api", help="your site's data address, e.g. https://YOUR-SITE/api/data")
    src.add_argument("--data", help="a JSON file with the same data (see sample-data.json)")
    ap.add_argument("--week", type=int, help="gameweek number (default: the latest one with results)")
    ap.add_argument("--out", help="output file (default gameweek-N.mp4)")
    ap.add_argument("--voice", default="auto", choices=["auto", "edge", "kokoro", "sapi", "none"])
    ap.add_argument("--voice-name", help="voice to use, e.g. en-KE-ChilembaNeural (edge) or bm_george (kokoro)")
    ap.add_argument("--rate", default="+6%", help="speaking speed for the edge voice, e.g. +10%%")
    ap.add_argument("--cta", default="FOLLOW K SOUTH LEAGUE", help="line shown on the last screen, e.g. your page name")
    ap.add_argument("--music", help="optional background music file (mp3/wav) mixed quietly under the voice")
    ap.add_argument("--stills", help="also save a PNG of the end of every scene into this folder")
    ap.add_argument("--no-video", action="store_true", help="only make stills and the script text")
    a = ap.parse_args()

    print("Loading data ...")
    M = Model(load_data(a), a.week)
    out = Path(a.out or "gameweek-%d.mp4" % M.week)
    print("Gameweek %d: %d matches, %d goals" % (M.week, len(M.matches), M.goals))

    script = narration(M)
    scenes = [("intro",) + scene_intro(M)]
    for i in range(len(M.matches)):
        scenes.append(("m%d" % i,) + scene_match(M, i))
    scenes += [("results",) + scene_results(M), ("table",) + scene_table(M), ("outro",) + scene_outro(M, a.cta)]

    print("Recording the voice-over ...")
    voice = Voice("none" if a.no_video and a.voice == "auto" else a.voice, a.voice_name, a.rate)
    work = Path(tempfile.mkdtemp(prefix="ksl_video_"))
    LEAD, GAP, TAIL = .5, .3, .9
    timeline = []
    for name, bg, draw in scenes:
        cues, clips, t = {}, [], LEAD
        for j, (cue, line) in enumerate(script[name]):
            w = voice.speak(line, work / ("%s_%d.wav" % (name, j))) if voice.kind else None
            audio = wav_array(w) if w else np.zeros(int(len(line.split()) * .36 * SR), np.float32)
            cues[cue] = t
            clips.append((t, audio))
            t += len(audio) / SR + GAP
        dur = max(t + TAIL - GAP, 6.0 if name in ("intro", "outro") else 7.0)
        timeline.append((name, bg, draw, cues, clips, dur))
        print("  %-8s %.1fs" % (name, dur))
    (out.with_suffix(".txt")).write_text("\n\n".join("[%s]\n%s" % (n, " ".join(l for _, l in script[n])) for n in script), encoding="utf-8")

    total = sum(x[5] for x in timeline)
    track = np.zeros(int((total + 1) * SR), np.float32)
    t0 = 0.0
    for name, bg, draw, cues, clips, dur in timeline:
        for st, audio in clips:
            i = int((t0 + st) * SR)
            track[i:i + len(audio)] += audio
        t0 += dur
    track = np.clip(track, -1, 1)
    wav_path = work / "voice.wav"
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((track * 32767).astype(np.int16).tobytes())

    if a.stills:
        Path(a.stills).mkdir(parents=True, exist_ok=True)
        for name, bg, draw, cues, clips, dur in timeline:
            im = bg.copy(); draw(im, dur - .05, cues); im.save(Path(a.stills) / (name + ".png"))
        print("Stills saved to", a.stills)
    if a.no_video:
        print("Script text:", out.with_suffix(".txt"))
        return

    audio_in = wav_path
    if a.music:
        mixed = work / "mixed.wav"
        subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(wav_path), "-stream_loop", "-1", "-i", a.music, "-filter_complex",
                        "[1:a]volume=0.14,aresample=%d,aformat=channel_layouts=mono[m];[0:a][m]amix=inputs=2:duration=first:normalize=0" % SR, "-ar", str(SR), str(mixed)], check=True)
        audio_in = mixed

    print("Rendering %d frames ..." % int(total * FPS))
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H), "-r", str(FPS), "-i", "-",
           "-i", str(audio_in), "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
           "-t", "%.2f" % total, "-movflags", "+faststart", str(out)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    prev = None
    done = 0
    for name, bg, draw, cues, clips, dur in timeline:
        nf = int(math.ceil(dur * FPS))
        for fi in range(nf):
            im = bg.copy()
            draw(im, fi / FPS, cues)
            if prev is not None and fi < 8:  # short crossfade from the previous scene
                im = Image.blend(prev, im, (fi + 1) / 9)
            p.stdin.write(im.tobytes())
            done += 1
            if done % 90 == 0:
                print("  %d%%" % (100 * done // int(total * FPS)), end="\r", flush=True)
        prev = im
    p.stdin.close()
    p.wait()
    shutil.rmtree(work, ignore_errors=True)
    print("\nDone: %s  (%.0fs). Voice-over text: %s" % (out, total, out.with_suffix(".txt")))


if __name__ == "__main__":
    main()