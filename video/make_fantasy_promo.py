#!/usr/bin/env python3
"""
Fantasy K South promo video.

A hype intro, then a walkthrough of how the Fantasy section works (team and rules, prices,
transfers, captain and bench, scoring, the Home page) and a peek at what is coming
(mini leagues and the chips: Bench Boost, Triple Captain, Wild Card, Free Hit).
Vertical 1080x1920 with a voice-over. It uses the same engine and voices as make_video.py.

    python make_fantasy_promo.py
    python make_fantasy_promo.py --site https://YOUR-SITE --cta "FOLLOW @YOURPAGE" --voice edge
    python make_fantasy_promo.py --short                    (about two minutes: leaves out the captain and home page scenes)
    python make_fantasy_promo.py --skip soon,outro          (or choose the scenes to leave out yourself)

With --site it reads your live rules (budget, transfers, scoring) so the video always matches the site.
"""
import argparse, json, math, shutil, subprocess, sys, tempfile, urllib.request, wave
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import make_video as mv
from ambient import ambient, mix_under
from make_video import (W, H, FPS, SR, NAVY, ORG, SKY, WHITE, MUT, YEL, RED, GREEN, font, text, fit, put, rrect, shape,
                        ease, back, prog, slide, logo, pitch, Voice, wav_array, ffmpeg_exe)

SCENES = ["intro", "team", "prices", "transfers", "captain", "scoring", "home", "soon", "outro"]

# ----------------------------------------------------------------------------- the rules (same as fantasy.js)
RULES = dict(squad=10, starters=7, budget=50000, clubLimit=2, comp=dict(GK=2, DEF=3, MID=3, FWD=2), freeTransfers=2, hitCost=4,
             deadlineMinutes=60, appearance=1, goal=dict(GK=6, DEF=6, MID=5, FWD=4), assist=3, cs=dict(GK=4, DEF=4, MID=1, FWD=0),
             yellow=-1, red=-3, penMissed=-2, captain=2)


def load_rules(site):
    if not site:
        return RULES
    url = site.rstrip("/")
    if not url.endswith("/config"):
        url += "/api/fantasy/config"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ksl-promo/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            cfg = json.loads(r.read().decode("utf-8")).get("cfg") or {}
        print("  using the live rules from", url)
        return {**RULES, **cfg}
    except Exception as e:
        print("  couldn't read the live rules (%s), using the defaults" % e)
        return RULES


ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def words(n):
    n = int(n)
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else " " + ONES[n % 10])
    return "{:,}".format(n)


def money_words(n):
    n = int(n)
    return words(n // 1000) + " thousand shillings" if n % 1000 == 0 and n < 1000000 else "{:,} shillings".format(n)


ksh = lambda n: "KSh {:,}".format(int(n))

# ----------------------------------------------------------------------------- jerseys drawn from each club's logo (same designs as the site)


def bez(p0, p1, p2, p3, n=16):
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                    u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
    return out


NECK = bez((20, 3), (22, 9), (27, 12), (32, 12)) + bez((32, 12), (37, 12), (42, 9), (44, 3))[1:]
SHIRT = [(20, 3), (2, 13), (10, 26), (17, 22), (17, 55), (47, 55), (47, 22), (54, 26), (62, 13), (44, 3)] + bez((44, 3), (42, 9), (37, 12), (32, 12))[1:] + bez((32, 12), (27, 12), (22, 9), (20, 3))[1:-1]


def cuffs(L, c, w):
    L([(2, 13), (10, 26)], c, w)
    L([(62, 13), (54, 26)], c, w)


def k_civo(P, L, E, R, col):
    R(0, 0, 64, 58, "#0b0b0c")
    for pts in ([(17, 27), (32, 41), (32, 46), (17, 32)], [(17, 37), (29, 49), (29, 53), (17, 42)], [(47, 27), (32, 41), (32, 46), (47, 32)], [(47, 37), (35, 49), (35, 53), (47, 42)]):
        P(pts, "#d4a64a")
    cuffs(L, "#d4a64a", 5); L(NECK, "#d4a64a", 3.5)
    return 35, 17, "#ffffff"


def k_elland(P, L, E, R, col):
    R(0, 0, 64, 58, "#e30000"); cuffs(L, "#ffffff", 5); L(NECK, "#ffffff", 3)
    E(32, 35, 12.5, 9.5, "#ffffff", 1.7); E(32, 35, 10.3, 7.4, "#ffffff", .7)
    return 40, 14, "#ffffff"


def k_samba(P, L, E, R, col):
    R(0, 0, 64, 58, "#eef0f2")
    P([(17, 12), (47, 12), (47, 30), (17, 22)], "#dfe2e6"); P([(17, 22), (47, 30), (47, 55), (40, 55)], "#cfd3d8"); P([(17, 22), (40, 55), (17, 55)], "#f8f9fa")
    P([(20, 3), (2, 13), (10, 26), (17, 22)], "#0b0b0c"); P([(44, 3), (62, 13), (54, 26), (47, 22)], "#0b0b0c")
    cuffs(L, "#eef0f2", 3); L(NECK, "#0b0b0c", 3.2)
    for i in range(8):
        R(17 + i * 3.75, 53 if i % 2 else 51, 3.75, 2, "#0b0b0c")
    return 36, 17, "#0b0b0c"


def k_baraka(P, L, E, R, col):
    R(0, 0, 64, 58, "#edbc3f"); cuffs(L, "#0b0b0b", 5); L(NECK, "#0b0b0b", 3.5)
    sh = [(23.5, 22), (40.5, 22), (40.5, 35.5), (38, 41), (32, 45.5), (26, 41), (23.5, 35.5)]
    P(sh, "#0b0b0b"); L(sh + [sh[0]], "#ffffff", .9)
    return 36, 14, "#edbc3f"


def k_avenue(P, L, E, R, col):
    R(0, 0, 64, 58, "#0b0b0d")
    for pts in ([(17, 44), (47, 38), (47, 40.4), (17, 46.4)], [(17, 48.2), (47, 42.2), (47, 44.6), (17, 50.6)], [(17, 52.4), (47, 46.4), (47, 49), (17, 54.8)]):
        P(pts, "#ffffff")
    cuffs(L, "#ffffff", 4); L(NECK, "#ffffff", 3)
    return 36, 18, "#ffffff"


def k_mandem(P, L, E, R, col):
    R(0, 0, 64, 58, "#070707")
    P([(26.5, 22.5), (27.7, 16.5), (30.3, 19.9), (32, 15.5), (33.7, 19.9), (36.3, 16.5), (37.5, 22.5)], "#daa33f")
    P([(17, 45.5), (22, 44.5), (27, 46), (33, 44.8), (39, 46), (44, 45), (47, 45.8), (47, 50.5), (43, 51.5), (38, 50.3), (32, 51.8), (26, 50.5), (21, 51.6), (17, 50.6)], "#ffffff")
    P([(17, 53), (47, 50.5), (47, 53.3), (17, 55.4)], "#daa33f")
    cuffs(L, "#ffffff", 4); L(NECK, "#daa33f", 3)
    return 36, 15, "#ffffff"


def k_default(P, L, E, R, col):
    R(0, 0, 64, 58, col); cuffs(L, (255, 255, 255, 150), 4); L(NECK, "#ffffff", 2.5)
    return 38, 20, "#ffffff"


KITS = dict(civo=k_civo, elland=k_elland, samba=k_samba, baraka=k_baraka, avenue=k_avenue, mandem=k_mandem)
CLUBS = {"civo": "CIV", "elland": "ELL", "samba": "SAM", "baraka": "BAR", "avenue": "2AV", "mandem": "MAN"}


@lru_cache(None)
def kit(theme, num, size=200, color="#1971c2"):
    ss = 4
    k = size * ss / 64
    w, h = int(64 * k), int(58 * k)
    art = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(art)
    pt = lambda pts: [(x * k, y * k) for x, y in pts]
    P = lambda pts, f: d.polygon(pt(pts), fill=f)
    L = lambda pts, c, wd: d.line(pt(pts), fill=c, width=max(1, int(wd * k)), joint="curve")
    E = lambda cx, cy, rx, ry, c, wd: d.ellipse(((cx - rx) * k, (cy - ry) * k, (cx + rx) * k, (cy + ry) * k), outline=c, width=max(1, int(wd * k)))
    R = lambda x, y, ww, hh, f: P([(x, y), (x + ww, y), (x + ww, y + hh), (x, y + hh)], f)
    ny, fs, nc = KITS.get(theme, k_default)(P, L, E, R, color)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(pt(SHIRT), fill=255)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(art, mask=mask)
    od = ImageDraw.Draw(out)
    od.line(pt(SHIRT + [SHIRT[0]]), fill=(0, 0, 0, 115), width=int(2 * k), joint="curve")
    od.text((32 * k, ny * k), str(num), font=font("d", int(fs * k), 900), fill=nc, anchor="ms")
    return out.resize((size, int(size * 58 / 64)), Image.LANCZOS)


# ----------------------------------------------------------------------------- building blocks


def pill(txt, fill, color, size=34, pad=(22, 9), kind="a", weight=800):
    t = text(txt, kind, size, weight, color)
    im = rrect(t.width + 2 * pad[0], t.height + 2 * pad[1], (t.height + 2 * pad[1]) // 2, tuple(fill) + (255,) if len(fill) == 3 else fill).copy()
    im.alpha_composite(t, (pad[0], pad[1]))
    return im


@lru_cache(None)
def card(theme, num, name, sub, size=140, price=None, badge=None, dim=False, marks=False):
    """The player card from the site: shirt, name, next fixture, optional price tag above the shirt and C/V badge."""
    kt = kit(theme, num, size)
    pn, sb = pill(name, WHITE, NAVY, max(14, size // 9), (8, 3)), pill(sub, NAVY, WHITE, max(12, size // 10), (8, 2))
    pr = pill(price, (255, 210, 31), NAVY, max(13, size // 9), (9, 3)) if price else None
    wid = max(kt.width, pn.width, sb.width, pr.width if pr else 0) + 12
    top = (pr.height + 6) if pr else 0
    im = Image.new("RGBA", (wid, top + kt.height + pn.height + sb.height + 4), (0, 0, 0, 0))
    if pr:
        im.alpha_composite(pr, ((wid - pr.width) // 2, 0))
    im.alpha_composite(kt, ((wid - kt.width) // 2, top))
    im.alpha_composite(pn, ((wid - pn.width) // 2, top + kt.height + 2))
    im.alpha_composite(sb, ((wid - sb.width) // 2, top + kt.height + 2 + pn.height))
    if badge:
        b = shape(size // 4 + 6, size // 4 + 6, lambda dr, w_, h_, s: dr.ellipse((0, 0, w_ - 1, h_ - 1), fill=(ORG if badge == "C" else NAVY) + (255,), outline=(255, 255, 255, 255), width=3 * s))
        bt = text(badge, "a", size // 6, 800, WHITE)
        b.alpha_composite(bt, ((b.width - bt.width) // 2, (b.height - bt.height) // 2))
        im.alpha_composite(b, (wid // 2 + kt.width // 2 - b.width + 6, top - 4))
    if marks:
        def mk(n, cx, cy):
            c = shape(46, 46, lambda dr, w_, h_, s: dr.ellipse((0, 0, w_ - 1, h_ - 1), fill=ORG + (255,), outline=(255, 255, 255, 255), width=3 * s))
            t_ = text(str(n), "d", 34, 900, WHITE)
            c.alpha_composite(t_, ((46 - t_.width) // 2, (46 - t_.height) // 2))
            im.alpha_composite(c, (int(cx - 23), int(cy - 23)))
        mk(1, (wid - pr.width) // 2 - 32, pr.height // 2)
        mk(2, (wid - pn.width) // 2 - 32, top + kt.height + 2 + pn.height // 2)
        mk(3, (wid + sb.width) // 2 + 32, top + kt.height + 2 + pn.height + sb.height // 2)
    if dim:
        a = im.getchannel("A").point(lambda v: int(v * .35))
        im.putalpha(a)
    return im


@lru_cache(None)
def pitch_panel(w, h):
    y = np.arange(h)[:, None, None]
    arr = np.where((y // 70) % 2 == 0, np.array([20, 108, 66], float), np.array([15, 92, 55], float))
    arr = np.broadcast_to(arr, (h, w, 3)).astype("uint8").copy()
    im = Image.fromarray(arr).convert("RGBA")
    d = ImageDraw.Draw(im)
    ln = (255, 255, 255, 200)
    d.rectangle((w * .29, -4, w * .71, 100), outline=ln, width=5)
    d.ellipse((w / 2 - 110, h - 110, w / 2 + 110, h + 110), outline=ln, width=5)
    d.line((0, h - 1, w, h - 1), fill=ln, width=5)
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), 36, fill=255)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(im, mask=m)
    ImageDraw.Draw(out).rounded_rectangle((1, 1, w - 2, h - 2), 36, outline=(255, 255, 255, 215), width=5)
    return out


def scene_bg(label=None, header=True):
    im = pitch().copy()
    d = ImageDraw.Draw(im)
    for i, c in enumerate((ORG, WHITE, SKY)):
        d.rectangle((W * i // 3, H - 16, W * (i + 1) // 3, H), fill=c)
    ft = text("FANTASY K SOUTH  ·  FREE TO PLAY", "a", 28, 700, MUT)
    im.paste(ft, (int(W / 2 - ft.width / 2), H - 70), ft)
    if header:
        lg = logo(120)
        im.paste(lg, (70, 64), lg)
        t1, t2 = text("FANTASY K SOUTH", "d", 72, 900, WHITE), text((label or "").upper(), "d", 52, 800, SKY)
        im.paste(t1, (220, 74), t1)
        im.paste(t2, (220, 142), t2)
    return im


def card_in(im, c, x, y, t, start, dy=50, dur=.55, s=1.0):
    p, _, off = slide(t, start, dy=dy, dur=dur)
    put(im, c, x, y + off, a=p, s=s)


def panel(w, h, fill=(255, 255, 255, 20), line=(255, 255, 255, 46)):
    return rrect(w, h, 28, fill, line, 2)


# ----------------------------------------------------------------------------- scenes
# every scene: (segments=[(cue, narration)], background, draw(im, t, cues))


def sc_intro(R, a):
    segs = [("a", "Get ready! Fantasy K South is here. Build your dream team from the players of the league, score points every gameweek, and take on your friends. And it is completely free to play.")]
    bg = scene_bg(header=False)

    def draw(im, t, C):
        put(im, text("K SOUTH LEAGUE  ·  EMBAKASI WEST", "d", 54, 800, SKY), W / 2, 120, a=prog(t, .1, .4))
        put(im, logo(300), W / 2, 330, a=prog(t, .1, .4), s=.6 + .4 * back(prog(t, .1, .9)))
        put(im, text("FANTASY", "d", 300, 900, WHITE, stroke=8, stroke_fill=ORG), W / 2, 680, a=prog(t, .4, .4), s=.7 + .3 * back(prog(t, .4, .8)))
        put(im, text("K SOUTH", "d", 230, 900, ORG), W / 2, 930, a=prog(t, .7, .4), s=.7 + .3 * back(prog(t, .7, .8)))
        for i, (th, n, dx, y, sz, d0) in enumerate((("civo", 10, -300, 1260, 270, 1.0), ("elland", 9, 300, 1260, 270, 1.15), ("baraka", 7, 0, 1230, 340, 1.3))):
            card_in(im, kit(th, n, sz), W / 2 + dx, y, t, d0, dy=160, dur=.7)
        put(im, pill("FREE TO PLAY", ORG, WHITE, 52, (40, 14), "d", 900), W / 2, 1520, a=prog(t, 1.9, .4), s=.8 + .2 * ease(prog(t, 1.9, .4)))
        put(im, text("PICK YOUR SEVEN. BEAT YOUR FRIENDS.", "d", 76, 800, SKY), W / 2, 1660, a=prog(t, 2.4, .5))
    return segs, bg, draw


def sc_team(R, a):
    c, comp = R["comp"], R["comp"]
    segs = [("squad", "Here is how it works. You pick %s players: %s goalkeepers, %s defenders, %s midfielders and %s forwards. %s play on the pitch and %s wait on the bench."
             % (words(R["squad"]), words(comp["GK"]), words(comp["DEF"]), words(comp["MID"]), words(comp["FWD"]), words(R["starters"]).capitalize(), words(R["squad"] - R["starters"]))),
            ("budget", "You have %s to spend, and no more than %s players can come from the same club." % (money_words(R["budget"]), words(R["clubLimit"])))]
    bg = scene_bg("Build your team")
    pan = pitch_panel(960, 1040)
    rows = [[("samba", 1, "GK", "SAM (H)")], [("civo", 4, "DEF", "ELL (A)"), ("avenue", 5, "DEF", "BAR (H)")],
            [("elland", 8, "MID", "CIV (H)"), ("baraka", 10, "MID", "MAN (A)"), ("mandem", 6, "MID", "2AV (H)")], [("civo", 9, "FWD", "ELL (A)")]]
    ys = [420, 660, 900, 1140]

    def draw(im, t, C):
        s0 = C.get("squad", .5)
        put(im, pan, W / 2, 800, a=prog(t, .2, .5))
        k = 0
        for r, row in enumerate(rows):
            for j, (th, n, nm, sb) in enumerate(row):
                x = W / 2 + (j - (len(row) - 1) / 2) * 300
                card_in(im, card(th, n, nm, sb, 190), x, ys[r], t, s0 + .12 * k)
                k += 1
        put(im, panel(960, 280), W / 2, 1510, a=prog(t, s0 + 1.5, .4))
        put(im, text("BENCH", "d", 40, 800, MUT), 130, 1395, a=prog(t, s0 + 1.5, .4))
        for j, (th, n, nm, sb) in enumerate((("mandem", 13, "GK", "SAM (H)"), ("avenue", 3, "DEF", "BAR (H)"), ("baraka", 11, "FWD", "MAN (A)"))):
            card_in(im, card(th, n, nm, sb, 130), W / 2 + (j - 1) * 300, 1520, t, s0 + 1.6 + .12 * j)
        b0 = C.get("budget", 9)
        chips = [pill(txt, fill, NAVY, 36, (22, 12), "d", 900) for txt, fill in ((str(R["squad"]) + " PLAYERS", ORG), (ksh(R["budget"]) + " BUDGET", SKY), ("MAX %d PER CLUB" % R["clubLimit"], WHITE))]
        gap = 22
        x = W / 2 - (sum(c.width for c in chips) + gap * 2) / 2
        for j, c in enumerate(chips):
            put(im, c, x + c.width / 2, 1740, a=prog(t, b0 + .2 * j, .4), s=.85 + .15 * ease(prog(t, b0 + .2 * j, .4)))
            x += c.width + gap
    return segs, bg, draw


def sc_prices(R, a):
    segs = [("price", "Every player has a price. On the Transfers screen it sits in a tag above the shirt, with the player's name and their next fixture, home or away."),
            ("bank", "Your whole squad has to fit inside your budget, and whatever you do not spend stays in your bank.")]
    bg = scene_bg("Prices")
    spent = R["budget"] - 1500

    def legend(n, title, sub):
        im = panel(430, 150 if sub else 110).copy()
        c = shape(56, 56, lambda dr, w_, h_, s: dr.ellipse((0, 0, w_ - 1, h_ - 1), fill=ORG + (255,)))
        t_ = text(str(n), "d", 42, 900, WHITE)
        c.alpha_composite(t_, ((56 - t_.width) // 2, (56 - t_.height) // 2))
        im.alpha_composite(c, (24, (im.height - 56) // 2))
        f1 = text(title, "d", 50, 900, WHITE)
        im.alpha_composite(f1, (100, 22 if sub else (im.height - f1.height) // 2))
        if sub:
            f2 = text(sub, "a", 24, 600, MUT)
            im.alpha_composite(f2, (100, 92))
        return im

    def draw(im, t, C):
        s0 = C.get("price", .5)
        put(im, card("baraka", 10, "Mwangi", "ELL (H)", 420, price="KSh 5,000", marks=True), 290, 760, a=prog(t, .2, .5), s=.9 + .1 * ease(prog(t, .2, .5)))
        for k, (n, title, sub, y) in enumerate(((1, "PRICE TAG", "KSh, above the shirt", 520), (2, "PLAYER NAME", "", 700), (3, "NEXT FIXTURE", "(H) at home  ·  (A) away", 860))):
            card_in(im, legend(n, title, sub), 790, y, t, s0 + .6 + .7 * k, dy=30)
        b0 = C.get("bank", 11)
        put(im, panel(960, 360), W / 2, 1480, a=prog(t, b0, .5))
        fill = ease(prog(t, b0 + .3, 1.2))
        put(im, text("SQUAD VALUE", "a", 28, 700, MUT), 290, 1390, a=prog(t, b0 + .2, .4))
        put(im, text("BANK", "a", 28, 700, MUT), 760, 1390, a=prog(t, b0 + .2, .4))
        put(im, text(ksh(spent * fill), "d", 84, 900, WHITE), 290, 1465, a=prog(t, b0 + .2, .4))
        put(im, text(ksh(R["budget"] - spent * fill), "d", 84, 900, ORG), 760, 1465, a=prog(t, b0 + .2, .4))
        put(im, rrect(860, 34, 17, (255, 255, 255, 40)), W / 2, 1570, a=prog(t, b0, .5))
        wbar = int(860 * spent / R["budget"] * fill)
        if wbar > 10:
            put(im, rrect(wbar, 34, 17, ORG + (255,)), 110 + wbar / 2, 1570)
        put(im, text("%s BUDGET" % ksh(R["budget"]), "a", 30, 700, SKY), W / 2, 1630, a=prog(t, b0 + .6, .4))
        put(im, text("Prices are set by the league", "a", 28, 600, MUT), W / 2, 1720, a=prog(t, b0 + 1.2, .5))
    return segs, bg, draw


def sc_transfers(R, a):
    segs = [("open", "Want to change your team? Open Transfers, tap a player, choose Transfer out, then pick a replacement in the same position."),
            ("free", "You get %s free transfers every gameweek." % words(R["freeTransfers"])),
            ("hit", "Each extra transfer costs %s points." % words(R["hitCost"])),
            ("deadline", "And watch the clock: teams lock %s before the gameweek's first kick-off." % ("one hour" if R["deadlineMinutes"] == 60 else "%s minutes" % words(R["deadlineMinutes"])))]
    bg = scene_bg("Transfers")

    def tile(lab, val, sub):
        im = panel(290, 170).copy()
        for txt, y, f in ((lab, 34, text(lab, "a", 24, 700, MUT)), (val, 88, text(val, "d", 62, 900, WHITE)), (sub, 138, text(sub, "a", 24, 600, MUT))):
            im.alpha_composite(f, ((290 - f.width) // 2, y - f.height // 2))
        return im

    def draw(im, t, C):
        o = C.get("open", .5)
        seg = rrect(620, 84, 42, (255, 255, 255, 24), (255, 255, 255, 50), 2).copy()
        pt, tt = text("Pick Team", "a", 36, 700, WHITE), text("Transfers", "a", 36, 800, WHITE)
        seg.alpha_composite(rrect(300, 68, 34, ORG + (255,)), (306, 8))
        seg.alpha_composite(pt, (155 - pt.width // 2, 42 - pt.height // 2)); seg.alpha_composite(tt, (456 - tt.width // 2, 42 - tt.height // 2))
        put(im, seg, W / 2, 340, a=prog(t, .2, .4))
        for i, (a_, b_, c_) in enumerate((("BANK", ksh(1500), "squad " + ksh(R["budget"] - 1500)), ("TRANSFERS", "1 / %d free" % R["freeTransfers"], "no cost"), ("DEADLINE", "Sat 08:00", "in 3d 21h"))):
            card_in(im, tile(a_, b_, c_), 190 + i * 350, 540, t, .4 + .12 * i, dy=30)
        sel = rrect(960, 130, 24, (255, 255, 255, 22), (255, 210, 31, 255), 4).copy()
        for txt, x, y, sz, col in (("Mwangi · MID · KSh 5,000", 30, 65, 36, WHITE),):
            f = text(txt, "a", sz, 700, col); sel.alpha_composite(f, (x, y - f.height // 2))
        cb, ob = pill("Cancel", (255, 255, 255, 40), WHITE, 30, (18, 10)), pill("Transfer out", ORG, WHITE, 30, (22, 10))
        sel.alpha_composite(cb, (960 - cb.width - 26, (130 - cb.height) // 2)); sel.alpha_composite(ob, (960 - cb.width - 26 - ob.width - 14, (130 - ob.height) // 2))
        card_in(im, sel, W / 2, 760, t, o + .6, dy=30)
        for i, (th, n, nm, meta, pts, pr) in enumerate((("elland", 8, "Kamau", "Elland · MID", "14", "KSh 5,500"), ("civo", 6, "Otieno", "Civo · MID", "11", "KSh 5,000"), ("avenue", 10, "Wafula", "2nd Avenue · MID", "9", "KSh 4,500"))):
            row = rrect(960, 118, 20, (255, 255, 255, 18), (255, 255, 255, 40), 2).copy()
            kt = kit(th, n, 78)
            row.alpha_composite(kt, (20, 59 - kt.height // 2))
            f1, f2 = text(nm, "a", 36, 800, WHITE), text(meta, "a", 24, 600, MUT)
            row.alpha_composite(f1, (125, 22)); row.alpha_composite(f2, (125, 68))
            for txt, x in ((pts + " pts", 480), (pr, 600)):
                f = text(txt, "a", 28, 700, WHITE); row.alpha_composite(f, (x, 59 - f.height // 2))
            pk = pill("Pick", ORG, WHITE, 30, (26, 10)); row.alpha_composite(pk, (960 - pk.width - 26, (118 - pk.height) // 2))
            card_in(im, row, W / 2, 940 + i * 140, t, o + 1.2 + .25 * i, dy=40)
        for k, (cue, lab, fill, col) in enumerate((("free", "%d FREE TRANSFERS EVERY GAMEWEEK" % R["freeTransfers"], GREEN, WHITE), ("hit", "EXTRA TRANSFERS: −%d POINTS EACH" % R["hitCost"], RED, WHITE),
                                                  ("deadline", "LOCKS %s BEFORE FIRST KICK-OFF" % ("1 HOUR" if R["deadlineMinutes"] == 60 else "%d MIN" % R["deadlineMinutes"]), YEL, NAVY))):
            c0 = C.get(cue, 9)
            put(im, pill(lab, fill, col, 46, (28, 16), "d", 900), W / 2, 1430 + k * 120, a=prog(t, c0, .4), s=.85 + .15 * back(prog(t, c0, .6)))
    return segs, bg, draw


def sc_captain(R, a):
    segs = [("cap", "Pick a captain and they score double points."),
            ("vice", "Choose a vice-captain too. If your captain does not play, the vice takes the armband."),
            ("subs", "And if a starter does not play, a bench player steps in automatically, in order, as long as your formation stays legal.")]
    bg = scene_bg("Captain and bench")

    def draw(im, t, C):
        c0, v0, s0 = C.get("cap", .5), C.get("vice", 4), C.get("subs", 9)
        card_in(im, card("civo", 9, "Captain", "ELL (A)", 300, badge="C"), 300, 640, t, c0)
        put(im, pill("×%d POINTS" % R["captain"], ORG, WHITE, 60, (30, 14), "d", 900), 300, 960, a=prog(t, c0 + .6, .4), s=.8 + .2 * back(prog(t, c0 + .6, .6)))
        card_in(im, card("elland", 8, "Vice", "CIV (H)", 300, badge="V"), 780, 640, t, v0)
        put(im, pill("TAKES OVER IF NO PLAY", SKY, NAVY, 40, (24, 12), "d", 800), 780, 960, a=prog(t, v0 + .6, .4))
        put(im, rrect(900, 6, 3, (255, 255, 255, 60)), W / 2, 1080, a=prog(t, s0 - .3, .4))
        put(im, text("AUTO-SUBS", "d", 80, 900, SKY), W / 2, 1160, a=prog(t, s0, .4))
        card_in(im, card("baraka", 10, "Starter", "DNP", 230, dim=True), 300, 1450, t, s0 + .3)
        card_in(im, card("avenue", 11, "Bench", "BAR (H)", 230), 780, 1450, t, s0 + .6)
        p = prog(t, s0 + 1.1, .5)
        for dy, up in ((-40, False), (40, True)):
            put(im, shape(120, 90, lambda d_, w_, h_, s_: d_.polygon([(w_ * .5, h_ * .05), (w_ * .95, h_ * .55), (w_ * .62, h_ * .55), (w_ * .62, h_ * .95), (w_ * .38, h_ * .95), (w_ * .38, h_ * .55), (w_ * .05, h_ * .55)] if up else [(w_ * .5, h_ * .95), (w_ * .05, h_ * .45), (w_ * .38, h_ * .45), (w_ * .38, h_ * .05), (w_ * .62, h_ * .05), (w_ * .62, h_ * .45), (w_ * .95, h_ * .45)], fill=(GREEN if up else RED) + (255,))), 540 + (30 if up else -30), 1450 + dy * .2 + (20 if up else -20), a=p)
        put(im, text("IF YOUR FORMATION STAYS LEGAL", "a", 30, 700, MUT), W / 2, 1690, a=prog(t, s0 + 1.4, .5))
    return segs, bg, draw


def sc_scoring(R, a):
    pos = lambda v: ("+%d" % v) if v > 0 else "−%d" % abs(v)
    rows = [("PLAYING", pos(R["appearance"])), ("GOAL · GK / DEF", pos(R["goal"]["GK"])), ("GOAL · MID", pos(R["goal"]["MID"])), ("GOAL · FWD", pos(R["goal"]["FWD"])),
            ("ASSIST", pos(R["assist"])), ("CLEAN SHEET · GK / DEF", pos(R["cs"]["GK"])), ("CLEAN SHEET · MID", pos(R["cs"]["MID"])),
            ("YELLOW CARD", pos(R["yellow"])), ("RED CARD", pos(R["red"])), ("PENALTY MISSED", pos(R["penMissed"]))]
    segs = [("good", "Now the points. Playing earns %s. A goal is worth %s for goalkeepers and defenders, %s for midfielders, and %s for forwards. An assist is worth %s. A clean sheet gives %s to goalkeepers and defenders, and %s to midfielders."
             % (words(R["appearance"]), words(R["goal"]["GK"]), words(R["goal"]["MID"]), words(R["goal"]["FWD"]), words(R["assist"]), words(R["cs"]["GK"]), words(R["cs"]["MID"]))),
            ("bad", "But be careful. A yellow card costs %s, a red card costs %s, and a missed penalty costs %s." % (words(abs(R["yellow"])), words(abs(R["red"])), words(abs(R["penMissed"]))))]
    bg = scene_bg("Scoring")

    def draw(im, t, C):
        g0, b0 = C.get("good", .5), C.get("bad", 14)
        for i, (lab, val) in enumerate(rows):
            neg = val.startswith("−")
            st = b0 + .35 * (i - 7) if neg else g0 + .55 * i
            p, dx, _ = slide(t, st, dx=-120, dur=.5)
            row = rrect(960, 120, 26, (255, 255, 255, 20), (255, 255, 255, 46), 2).copy()
            f = text(lab, "d", 56, 800, WHITE)
            row.alpha_composite(f, (40, 60 - f.height // 2))
            chip = pill(val, RED if neg else GREEN, WHITE, 66, (34, 6), "d", 900)
            row.alpha_composite(chip, (960 - chip.width - 30, 60 - chip.height // 2))
            put(im, row, W / 2 + dx, 340 + i * 140, a=p)
        put(im, text("Points are added when the league saves each match's stats", "a", 28, 600, MUT), W / 2, 1740, a=prog(t, g0 + 6, .5))
    return segs, bg, draw


def sc_home(R, a):
    segs = [("tiles", "Every gameweek, your Home page shows your points, the league average and the highest score. Tap Your points to see your lineup, or tap Highest to see exactly how the top manager lined up."),
            ("board", "Then check the leaderboard and see where you rank.")]
    bg = scene_bg("Your home page")

    def tl(lab, val, sub, hint, mid=False, w=300, h=330):
        im = (rrect(w, h, 26, (15, 90, 55, 255)) if mid else rrect(w, h, 26, (255, 255, 255, 22), (255, 255, 255, 50), 2)).copy()
        for txt, y, f in ((lab, 52, text(lab, "a", 24, 700, (216, 245, 228) if mid else MUT)), (val, 138, text(val, "d", 130 if mid else 100, 900, WHITE)),
                          (sub, 232, text(sub, "a", 24, 600, (216, 245, 228) if mid else MUT)), (hint, 288, text(hint, "a", 22, 800, (255, 217, 184) if mid else ORG))):
            if txt:
                im.alpha_composite(f, ((w - f.width) // 2, y - f.height // 2))
        return im

    def draw(im, t, C):
        a0, b0 = C.get("tiles", .5), C.get("board", 12)
        put(im, text("GAMEWEEK 2", "d", 100, 900, WHITE), W / 2, 350, a=prog(t, .2, .4))
        card_in(im, tl("AVERAGE", "21.4", "across 8 managers", ""), 190, 700, t, a0)
        card_in(im, tl("YOUR POINTS", "52", "Ranked 2 of 8", "View your team ›", True, 330, 380), 540, 700, t, a0 + .25)
        card_in(im, tl("HIGHEST", "71", "Pipeline Pirates", "View their team ›"), 890, 700, t, a0 + .5)
        for k, (cx, lab) in enumerate(((540, "TAP TO SEE YOUR LINEUP"), (890, "TAP TO SEE THE TOP TEAM"))):
            put(im, text(lab, "a", 24, 700, YEL), cx, 940, a=prog(t, a0 + 4 + 1.5 * k, .4))
        put(im, text("LEADERBOARD", "d", 80, 900, SKY), W / 2, 1080, a=prog(t, b0, .4))
        for i, (tm, mg, pts) in enumerate((("Pipeline Pirates", "Otieno", 53), ("Your Team", "You", 52), ("Kibera Kings", "Joseph", 47), ("Embakasi Eagles", "Wanjiku", 44))):
            row = rrect(960, 112, 22, (255, 210, 31, 40) if i == 1 else (255, 255, 255, 18), (255, 210, 31, 255) if i == 1 else (255, 255, 255, 40), 3 if i == 1 else 2).copy()
            for txt, x, f in ((str(i + 1), 30, text(str(i + 1), "d", 64, 900, ORG)), (tm, 120, text(tm, "a", 38, 800, WHITE)), (mg, 560, text(mg, "a", 30, 600, MUT)), (str(pts), 880, text(str(pts), "d", 72, 900, WHITE))):
                row.alpha_composite(f, (x, 56 - f.height // 2))
            card_in(im, row, W / 2, 1230 + i * 130, t, b0 + .3 + .25 * i, dy=40)
    return segs, bg, draw


def icon_layer(kind, s=130):
    def dr(d, w, h, ss):
        if kind == "bench":
            d.rounded_rectangle((w * .05, h * .6, w * .95, h * .72), 8 * ss, fill=(255, 255, 255, 230))
            for i in range(3):
                x = w * (.18 + .32 * i)
                d.polygon([(x, h * .22), (x + w * .18, h * .22), (x + w * .24, h * .38), (x + w * .15, h * .42), (x + w * .15, h * .58), (x + w * .03, h * .58), (x + w * .03, h * .42), (x - w * .06, h * .38)], fill=(255, 210, 31, 255))
        elif kind == "triple":
            d.ellipse((w * .1, h * .1, w * .9, h * .9), fill=ORG + (255,), outline=(255, 255, 255, 255), width=5 * ss)
            d.text((w / 2, h / 2), "C", font=font("d", int(h * .6), 900), fill=WHITE + (255,), anchor="mm")
        elif kind == "wild":
            d.rounded_rectangle((w * .18, h * .08, w * .82, h * .92), 12 * ss, fill=(127, 212, 255, 255), outline=(255, 255, 255, 255), width=4 * ss)
            d.text((w / 2, h * .5), "W", font=font("d", int(h * .62), 900), fill=NAVY + (255,), anchor="mm")
        else:
            d.polygon([(w * .58, h * .02), (w * .2, h * .56), (w * .46, h * .56), (w * .36, h * .98), (w * .8, h * .38), (w * .52, h * .38)], fill=(255, 210, 31, 255))
    return shape(s, s, dr, 3)


def sc_soon(R, a):
    segs = [("mini", "And this is just the start. Future updates will bring mini leagues, so you can take on your friends in your own private league."),
            ("chips", "Plus chips. Bench Boost, where your bench players' points count. Triple Captain, where your captain scores triple. Wild Card, for a full team overhaul. And Free Hit, for a one week reshuffle. Details are still to be confirmed, so stay tuned.")]
    bg = scene_bg("Coming soon")
    chips = (("bench", "BENCH BOOST", "Your bench points count"), ("triple", "TRIPLE CAPTAIN", "Captain scores ×3"), ("wild", "WILD CARD", "Rebuild your team"), ("free", "FREE HIT", "One-week reshuffle"))

    def draw(im, t, C):
        m0, c0 = C.get("mini", .5), C.get("chips", 8)
        put(im, pill("COMING IN FUTURE UPDATES", ORG, WHITE, 52, (36, 14), "d", 900), W / 2, 330, a=prog(t, .2, .4), s=.85 + .15 * back(prog(t, .2, .6)))
        big = rrect(960, 330, 30, (255, 255, 255, 22), (127, 212, 255, 255), 4).copy()
        f1, f2 = text("MINI LEAGUES", "d", 100, 900, WHITE), text("Play in your own private league with friends", "a", 34, 600, MUT)
        big.alpha_composite(f1, (50, 90)); big.alpha_composite(f2, (50, 220))
        for i in range(3):
            big.alpha_composite(kit(("civo", "baraka", "mandem")[i], (7, 10, 9)[i], 110), (590 + i * 100, 110 + (i % 2) * 40))
        card_in(im, big, W / 2, 620, t, m0, dy=40)
        put(im, text("CHIPS", "d", 90, 900, SKY), W / 2, 880, a=prog(t, c0 - .3, .4))
        for i, (kd, ttl, sub) in enumerate(chips):
            cd = rrect(460, 330, 28, (255, 255, 255, 20), (255, 255, 255, 50), 2).copy()
            cd.alpha_composite(icon_layer(kd, 120), (170, 28))
            f1, f2 = text(ttl, "d", 56, 900, WHITE), text(sub, "a", 28, 600, MUT)
            cd.alpha_composite(f1, ((460 - f1.width) // 2, 168)); cd.alpha_composite(f2, ((460 - f2.width) // 2, 248))
            card_in(im, cd, 290 + (i % 2) * 500, 1090 + (i // 2) * 360, t, c0 + .7 * i, dy=40, s=1.0)
        put(im, text("Details to be confirmed", "a", 28, 600, MUT), W / 2, 1800, a=prog(t, c0 + 4, .5))
    return segs, bg, draw


def sc_outro(R, a):
    segs = [("a", "So sign in with Google, pick your team, and let the banter begin. Fantasy K South. Free to play.")]
    bg = scene_bg(header=False)

    def draw(im, t, C):
        put(im, logo(420), W / 2, 420, a=prog(t, .1, .4), s=.6 + .4 * back(prog(t, .1, .9)))
        put(im, text("FANTASY K SOUTH", "d", 150, 900, WHITE), W / 2, 790, a=prog(t, .5, .4))
        for i, (txt, fill, col) in enumerate((("SIGN IN WITH GOOGLE", ORG, WHITE), ("PICK YOUR TEAM", SKY, NAVY), ("LET THE BANTER BEGIN", WHITE, NAVY))):
            put(im, pill(txt, fill, col, 66, (40, 18), "d", 900), W / 2, 1010 + i * 150, a=prog(t, 1.0 + .4 * i, .4), s=.85 + .15 * back(prog(t, 1.0 + .4 * i, .6)))
        put(im, text(a.cta, "d", 74, 800, SKY), W / 2, 1530, a=prog(t, 2.4, .5))
        if a.site:
            put(im, text(a.site.replace("https://", "").replace("http://", "").rstrip("/").upper(), "d", 56, 700, MUT), W / 2, 1625, a=prog(t, 2.6, .5))
        put(im, text("FREE TO PLAY  ·  EMBAKASI WEST", "d", 50, 700, MUT), W / 2, 1720, a=prog(t, 2.8, .5))
    return segs, bg, draw


BUILD = dict(intro=sc_intro, team=sc_team, prices=sc_prices, transfers=sc_transfers, captain=sc_captain, scoring=sc_scoring, home=sc_home, soon=sc_soon, outro=sc_outro)

# ----------------------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description="Make the Fantasy K South promo video.")
    ap.add_argument("--site", help="your site address (e.g. https://your-site.com). Reads your live fantasy rules and shows the address on the last screen")
    ap.add_argument("--out", default="fantasy-promo.mp4")
    ap.add_argument("--voice", default="auto", choices=["auto", "edge", "kokoro", "sapi", "none"])
    ap.add_argument("--voice-name", help="pick a different voice, e.g. en-GB-SoniaNeural (edge), bf_emma (kokoro) or Zira (Windows). The default is a female voice")
    ap.add_argument("--rate", default="+8%", help="speaking speed for the edge voice")
    ap.add_argument("--cta", default="FOLLOW K SOUTH LEAGUE", help="line on the last screen, e.g. your page name")
    ap.add_argument("--skip", default="", help="comma-separated scenes to leave out: " + ",".join(SCENES))
    ap.add_argument("--short", action="store_true", help="leave out the captain and home page scenes for a shorter video")
    ap.add_argument("--music", default="ambient", help="background music: ambient (built in, the default), none, or the path to your own mp3/wav")
    ap.add_argument("--music-db", type=float, default=-13.0, help="how loud the music is compared with the voice (default -13, more negative = quieter)")
    ap.add_argument("--stills", help="save a PNG of the end of every scene into this folder")
    ap.add_argument("--no-video", action="store_true", help="only make stills and the script text")
    a = ap.parse_args()
    skip = {s.strip() for s in a.skip.split(",") if s.strip()} | ({"captain", "home"} if a.short else set())
    bad = skip - set(SCENES)
    if bad:
        sys.exit("Unknown scene(s) in --skip: " + ", ".join(sorted(bad)) + ". Choose from: " + ", ".join(SCENES))
    R = load_rules(a.site)
    scenes = [(n,) + BUILD[n](R, a) for n in SCENES if n not in skip]

    print("Recording the voice-over ...")
    voice = Voice("none" if a.no_video and a.voice == "auto" else a.voice, a.voice_name, a.rate,
                  defaults={"edge": "en-KE-AsiliaNeural", "kokoro": "af_heart", "sapi": "Zira"}, fallback="en-GB-SoniaNeural")  # female voices
    work = Path(tempfile.mkdtemp(prefix="ksl_promo_"))
    LEAD, GAP, TAIL = .5, .3, .9
    timeline = []
    for name, segs, bg, draw in scenes:
        cues, clips, t = {}, [], LEAD
        for j, (cue, line) in enumerate(segs):
            w = voice.speak(line, work / ("%s_%d.wav" % (name, j))) if voice.kind else None
            audio = wav_array(w) if w else np.zeros(int(len(line.split()) * .36 * SR), np.float32)
            cues[cue] = t
            clips.append((t, audio))
            t += len(audio) / SR + GAP
        dur = max(t + TAIL - GAP, 6.0)
        timeline.append((name, segs, bg, draw, cues, clips, dur))
        print("  %-10s %.1fs" % (name, dur))
    out = Path(a.out)
    out.with_suffix(".txt").write_text("\n\n".join("[%s]\n%s" % (n, " ".join(l for _, l in segs)) for n, segs, *_ in timeline), encoding="utf-8")

    total = sum(x[6] for x in timeline)
    track = np.zeros(int((total + 1) * SR), np.float32)
    t0 = 0.0
    for name, segs, bg, draw, cues, clips, dur in timeline:
        for st, audio in clips:
            i = int((t0 + st) * SR)
            track[i:i + len(audio)] += audio
        t0 += dur
    track = np.clip(track, -1, 1)
    if a.music.lower() != "none":
        print("Adding background music (%s) ..." % ("ambient, built in" if a.music.lower() == "ambient" else a.music))
        if a.music.lower() == "ambient":
            music = ambient(total + 3, SR)
        else:
            mw = work / "music.wav"
            mv.to_wav(a.music, mw)
            music = wav_array(mw)
        track = mix_under(track, music, SR, music_db=a.music_db)
    wav_path = work / "voice.wav"
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(track, -1, 1) * 32767).astype(np.int16).tobytes())

    if a.stills:
        Path(a.stills).mkdir(parents=True, exist_ok=True)
        for name, segs, bg, draw, cues, clips, dur in timeline:
            im = bg.copy(); draw(im, dur - .05, cues); im.save(Path(a.stills) / (name + ".png"))
        print("Stills saved to", a.stills)
    if a.no_video:
        print("Script text:", out.with_suffix(".txt"))
        return

    audio_in = wav_path

    nfr = int(total * FPS)
    print("Rendering %d frames ..." % nfr)
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H), "-r", str(FPS), "-i", "-", "-i", str(audio_in),
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-t", "%.2f" % total, "-movflags", "+faststart", str(out)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    prev, done = None, 0
    for name, segs, bg, draw, cues, clips, dur in timeline:
        for fi in range(int(math.ceil(dur * FPS))):
            im = bg.copy()
            draw(im, fi / FPS, cues)
            if prev is not None and fi < 8:
                im = Image.blend(prev, im, (fi + 1) / 9)
            p.stdin.write(im.tobytes())
            done += 1
            if done % 90 == 0:
                print("  %d%%" % (100 * done // nfr), end="\r", flush=True)
        prev = im
    p.stdin.close()
    p.wait()
    shutil.rmtree(work, ignore_errors=True)
    print("\nDone: %s  (%.0fs). Voice-over text: %s" % (out, total, out.with_suffix(".txt")))


if __name__ == "__main__":
    main()
