#!/usr/bin/env python3
"""
Cat-Man: a Pac-Man style game played on your GitHub contribution graph.

A cat chomps through every green square while chasing three ghosts. Eat the
power pellet in the last row and the ghosts turn blue, then the cat catches
them. Generates two self-contained animated SVGs (dark + light, SMIL only,
no scripts, no external assets).

Usage:
    python catman.py USERNAME [--out dist] [--demo]

Data source (no dependencies, standard library only):
  1. the public contributions page (no token needed)
  2. fallback: GitHub GraphQL API, if GH_TOKEN / GITHUB_TOKEN is set
  --demo skips the network and draws a made-up graph (for previews only)
"""
import datetime as dt
import json
import os
import random
import re
import sys
import urllib.request

P, S = 20, 15            # cell pitch / cell size (px)
W, H = 1180, 300         # canvas
ROWS = 7
STEP = 0.06              # seconds the cat spends per cell
HOLD = 3.2               # seconds of finale + reset between loops
FONT = "ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,'Liberation Mono','DejaVu Sans Mono',monospace"

THEMES = {
    "dark": dict(
        bg=("#030712", "#07111F", "#0B1220"), glow1=("#7C3AED", .20), glow2=("#10B981", .12),
        grid="#94A3B8", grid_op=.06, noise_op=.06,
        panel="#0F172A", panel_op=.42, panel_stroke="#334155", shadow=("#000000", .45), sheen_op=.05,
        text="#F8FAFC", muted="#94A3B8", faint="#64748B", acc2="#22D3EE", acc3="#34D399", frame="#475569",
        empty="#1E293B", empty_op=.65, levels=("#0E4429", "#006D32", "#26A641", "#39D353"),
        cat="#FBBF24", cat_dark="#B45309", ear="#F9A8D4", eye="#0B1220",
        ghosts=("#F43F5E", "#F472B6", "#22D3EE"), scared="#3B82F6", pellet="#FDE68A", particle="#A5F3FC", particle_op=.5,
        pop="#FDE68A",
    ),
    "light": dict(
        bg=("#FFFFFF", "#F8FAFC", "#EEF6FF"), glow1=("#7C3AED", .09), glow2=("#10B981", .09),
        grid="#64748B", grid_op=.09, noise_op=.03,
        panel="#FFFFFF", panel_op=.70, panel_stroke="#CBD5E1", shadow=("#334155", .16), sheen_op=.55,
        text="#0F172A", muted="#475569", faint="#64748B", acc2="#2563EB", acc3="#047857", frame="#94A3B8",
        empty="#E2E8F0", empty_op=1, levels=("#9BE9A8", "#40C463", "#30A14E", "#216E39"),
        cat="#F59E0B", cat_dark="#92400E", ear="#F472B6", eye="#0F172A",
        ghosts=("#E11D48", "#DB2777", "#0891B2"), scared="#2563EB", pellet="#F59E0B", particle="#2563EB", particle_op=.25,
        pop="#B45309",
    ),
}


# ----------------------------------------------------------------------------- data
def fetch_html(user):
    req = urllib.request.Request(f"https://github.com/users/{user}/contributions",
                                 headers={"User-Agent": "cat-man-profile-game"})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    return parse_html(html)


def parse_html(html):
    cells = []
    for m in re.finditer(r"<td\b([^>]*)>", html):
        a = m.group(1)
        d = re.search(r'data-date="(\d{4}-\d{2}-\d{2})"', a)
        l = re.search(r'data-level="(\d)"', a)
        if d and l:
            cells.append((d.group(1), int(l.group(1))))
    return cells


def fetch_graphql(user, token):
    q = {"query": "query($u:String!){user(login:$u){contributionsCollection{contributionCalendar{weeks{contributionDays{date contributionLevel}}}}}}",
         "variables": {"u": user}}
    req = urllib.request.Request("https://api.github.com/graphql", data=json.dumps(q).encode(),
                                 headers={"Authorization": f"bearer {token}", "User-Agent": "cat-man-profile-game"})
    data = json.load(urllib.request.urlopen(req, timeout=30))
    return parse_graphql(data)


def parse_graphql(data):
    lv = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}
    weeks = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    return [(d["date"], lv.get(d["contributionLevel"], 0)) for w in weeks for d in w["contributionDays"]]


def demo_cells():
    rnd = random.Random(5)
    end = dt.date.today()
    start = end - dt.timedelta(days=364)
    out, d = [], start
    busy = 0.0
    while d <= end:
        busy = max(0.0, busy + rnd.uniform(-.45, .5))
        lvl = 0 if rnd.random() > min(.85, .18 + busy * .35) else min(4, 1 + int(rnd.random() * 4 * min(1, busy + .3)))
        out.append((d.isoformat(), lvl))
        d += dt.timedelta(days=1)
    return out


def load(user, demo):
    if demo:
        return demo_cells()
    err = None
    try:
        cells = fetch_html(user)
        if cells:
            return cells
        err = "contributions page had no day cells"
    except Exception as e:  # noqa: BLE001
        err = repr(e)
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        try:
            return fetch_graphql(user, token)
        except Exception as e:  # noqa: BLE001
            err += f" | graphql: {e!r}"
    raise SystemExit(f"Could not read contributions for {user}: {err}")


def to_grid(cells):
    cells = sorted(cells)
    first = dt.date.fromisoformat(cells[0][0])
    sunday0 = first - dt.timedelta(days=(first.weekday() + 1) % 7)
    grid = {}
    for ds, lvl in cells:
        d = dt.date.fromisoformat(ds)
        grid[((d - sunday0).days // 7, (d.weekday() + 1) % 7)] = (lvl, d)
    return grid


# ----------------------------------------------------------------------------- drawing
def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build(theme, grid):
    T = THEMES[theme]
    cols = max(c for c, _ in grid) + 1
    x0 = round(28 + (1124 - ((cols - 1) * P + S)) / 2)
    y0 = 112
    cx = lambda c: x0 + c * P + S / 2
    cy = lambda r: y0 + r * P + S / 2

    rowlen = (cols - 1) * P
    L = ROWS * rowlen + (ROWS - 1) * P
    run = L / P * STEP
    D = run + HOLD
    rf = run / D
    tf = lambda d: rf * d / L          # time fraction at which the cat has travelled d px
    tr = rf + (1 - rf) * .55           # when eaten food regrows
    dly = .15 / D

    def pos(d):
        d = max(0, min(L, d))
        r = min(int(d // (rowlen + P)), ROWS - 1)
        rem = d - r * (rowlen + P)
        if rem <= rowlen:
            c = rem if r % 2 == 0 else rowlen - rem
            return cx(0) + c, cy(r)
        c = rowlen if r % 2 == 0 else 0
        return cx(0) + c, cy(r) + (rem - rowlen)

    def rel_path(d0, d1):
        pts = [pos(d0)]
        for k in range(ROWS):
            for dd in (k * (rowlen + P) + rowlen, (k + 1) * (rowlen + P)):
                if d0 < dd < d1:
                    pts.append(pos(dd))
        pts.append(pos(d1))
        sx, sy = pts[0]
        return "M0,0 " + " ".join(f"L{x - sx:.1f},{y - sy:.1f}" for x, y in pts[1:])

    def cell_dist(c, r):
        return r * (rowlen + P) + (c * P if r % 2 == 0 else (cols - 1 - c) * P)

    o = []
    A = o.append
    label = ("Cat-Man: an animated game where a cat eats a year of GitHub contributions, "
             "chases three ghosts and catches them after a power pellet.")
    A('<?xml version="1.0" encoding="UTF-8"?>')
    A(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="{esc(label)}">')
    A('<title>Cat-Man</title>')
    A(f'<desc>{esc(label)}</desc>')

    g2 = T["acc2"]
    A('<defs>')
    A(f'<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{T["bg"][0]}"/><stop offset=".55" stop-color="{T["bg"][1]}"/><stop offset="1" stop-color="{T["bg"][2]}"/></linearGradient>')
    for gid, (c, op), x, y, r in (("g1", T["glow1"], 220, 120, 420), ("g2", T["glow2"], 980, 260, 440)):
        A(f'<radialGradient id="{gid}" gradientUnits="userSpaceOnUse" cx="{x}" cy="{y}" r="{r}"><stop offset="0" stop-color="{c}" stop-opacity="{op}"/><stop offset="1" stop-color="{c}" stop-opacity="0"/></radialGradient>')
    A(f'<linearGradient id="shim" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{T["frame"]}" stop-opacity=".55"/><stop offset=".38" stop-color="{T["frame"]}" stop-opacity=".55"/><stop offset=".5" stop-color="{g2}"/><stop offset=".62" stop-color="{T["frame"]}" stop-opacity=".55"/><stop offset="1" stop-color="{T["frame"]}" stop-opacity=".55"/><animateTransform attributeName="gradientTransform" type="translate" from="-1 0" to="1 0" dur="9s" repeatCount="indefinite"/></linearGradient>')
    A(f'<linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF" stop-opacity="{T["sheen_op"]}"/><stop offset=".35" stop-color="#FFFFFF" stop-opacity="0"/></linearGradient>')
    A(f'<pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40 0H0V40" fill="none" stroke="{T["grid"]}" stroke-opacity="{T["grid_op"]}"/></pattern>')
    A('<filter id="noise" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency=".85" numOctaves="2" seed="7"/><feColorMatrix type="saturate" values="0"/></filter>')
    sc, so = T["shadow"]
    A(f'<filter id="shadow" x="-10%" y="-10%" width="120%" height="130%"><feDropShadow dx="0" dy="10" stdDeviation="14" flood-color="{sc}" flood-opacity="{so}"/></filter>')
    A('<clipPath id="frame"><rect x="8" y="8" width="1164" height="284" rx="24"/></clipPath>')
    A('</defs>')
    A(f'<g clip-path="url(#frame)" font-family="{FONT}">')
    A(f'<rect width="{W}" height="{H}" fill="url(#bg)"/><rect width="{W}" height="{H}" fill="url(#g1)"/><rect width="{W}" height="{H}" fill="url(#g2)"/><rect width="{W}" height="{H}" fill="url(#grid)"/>')
    A(f'<rect width="{W}" height="{H}" filter="url(#noise)" opacity="{T["noise_op"]}"/>')
    rnd = random.Random(3)
    for _ in range(8):
        x, y, r = rnd.uniform(20, 1160), rnd.uniform(70, 285), rnd.uniform(.9, 1.8)
        A(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r:.1f}" fill="{T["particle"]}" opacity="{T["particle_op"]}"><animate attributeName="cy" values="{y:.0f};{y - 30:.0f};{y:.0f}" dur="{rnd.uniform(9, 15):.1f}s" repeatCount="indefinite"/></circle>')

    # panel + header chrome
    A(f'<rect x="28" y="68" width="1124" height="212" rx="16" fill="{T["panel"]}" fill-opacity="{T["panel_op"]}" filter="url(#shadow)"/>')
    A(f'<rect x="28" y="68" width="1124" height="212" rx="16" fill="url(#sheen)"/>')
    A(f'<rect x="28.5" y="68.5" width="1123" height="211" rx="16" fill="none" stroke="{T["panel_stroke"]}"/>')
    A(f'<line x1="8" y1="56" x2="1172" y2="56" stroke="{T["panel_stroke"]}" stroke-opacity=".7"/>')
    for x, c in ((36, "#FF5F57"), (57, "#FEBC2E"), (78, "#28C840")):
        A(f'<circle cx="{x}" cy="32" r="5.5" fill="{c}"/>')
    A(f'<text x="102" y="36.5" font-size="13" fill="{T["muted"]}"><tspan fill="{T["acc3"]}" font-weight="700">cat@game</tspan>:~$ <tspan fill="{T["text"]}">./cat-man --eat contributions</tspan></text>')
    A(f'<circle cx="1050" cy="32" r="4" fill="{T["acc3"]}"><animate attributeName="opacity" values="1;.35;1" dur="2s" repeatCount="indefinite"/></circle>')
    A(f'<text x="1148" y="36" font-size="11.5" letter-spacing="1.6" font-weight="700" text-anchor="end" fill="{T["muted"]}">[ PLAYING ]</text>')

    # month + weekday labels
    last_c, last_m = -9, None
    for c in range(cols):
        ds = [grid[(c, r)][1] for r in range(ROWS) if (c, r) in grid]
        if not ds:
            continue
        m = ds[0].month
        if m != last_m and c - last_c >= 3:
            A(f'<text x="{x0 + c * P}" y="101" font-size="10.5" fill="{T["faint"]}">{ds[0].strftime("%b")}</text>')
            last_c = c
        last_m = m
    for r, name in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        A(f'<text x="{x0 - 8}" y="{cy(r) + 3.5:.1f}" font-size="10" text-anchor="end" fill="{T["faint"]}">{name}</text>')

    # board: empty squares underneath, food on top
    for (c, r) in sorted(grid):
        A(f'<rect x="{x0 + c * P}" y="{y0 + r * P}" width="{S}" height="{S}" rx="3" fill="{T["empty"]}" fill-opacity="{T["empty_op"]}"/>')
    pellet_cell = (0, ROWS - 1) if (0, ROWS - 1) in grid else None
    for (c, r) in sorted(grid):
        lvl = grid[(c, r)][0]
        if lvl == 0 or (c, r) == pellet_cell:
            continue
        te = max(0.0, tf(cell_dist(c, r) - 5))
        kt = f"0;{te:.4f};{te + dly:.4f};{tr:.4f};{tr + .04:.4f};1"
        A(f'<rect x="{x0 + c * P}" y="{y0 + r * P}" width="{S}" height="{S}" rx="3" fill="{T["levels"][lvl - 1]}">'
          f'<animate attributeName="opacity" values="1;1;0;0;1;1" keyTimes="{kt}" dur="{D:.2f}s" repeatCount="indefinite"/></rect>')

    # power pellet (first cell of the last row)
    t_pellet = None
    if pellet_cell:
        c, r = pellet_cell
        t_pellet = max(0.0, tf(cell_dist(c, r) - 5))
        kt = f"0;{t_pellet:.4f};{t_pellet + dly:.4f};{tr:.4f};{tr + .04:.4f};1"
        A(f'<g><animate attributeName="opacity" values="1;1;0;0;1;1" keyTimes="{kt}" dur="{D:.2f}s" repeatCount="indefinite"/>'
          f'<circle cx="{cx(c):.1f}" cy="{cy(r):.1f}" r="6" fill="{T["pellet"]}"><animate attributeName="r" values="4.5;7;4.5" dur="1s" repeatCount="indefinite"/></circle>'
          f'<circle cx="{cx(c):.1f}" cy="{cy(r):.1f}" r="10" fill="none" stroke="{T["pellet"]}" stroke-opacity=".45"><animate attributeName="r" values="8;13;8" dur="1s" repeatCount="indefinite"/></circle></g>')
    t_scared = t_pellet if t_pellet is not None else tf((ROWS - 1) * (rowlen + P))

    # ghosts
    gh_def = [(.11, L, 800), (.19, L - 3 * P, 400), (.27, L - 6 * P, 200)]
    for i, (a, d1, pts) in enumerate(gh_def):
        d0 = L * a
        sx, sy = pos(d0)
        e = max(.0001, rf * (d1 - d0) / L)
        te = tf(d1 - 6)
        col = T["ghosts"][i]
        eyes = (f'<circle cx="-3" cy="-2" r="2.4" fill="#fff"/><circle cx="3" cy="-2" r="2.4" fill="#fff"/>'
                f'<circle cx="-2.2" cy="-1.8" r="1.1" fill="#0B1220"/><circle cx="3.8" cy="-1.8" r="1.1" fill="#0B1220"/>')
        body = "M-8,8 V-1 A8,8 0 0 1 8,-1 V8 L5.3,5.3 L2.7,8 L0,5.3 L-2.7,8 L-5.3,5.3 Z"
        A(f'<g transform="translate({sx:.1f},{sy:.1f})">'
          f'<animateMotion dur="{D:.2f}s" repeatCount="indefinite" path="{rel_path(d0, d1)}" calcMode="linear" keyPoints="0;1;1" keyTimes="0;{e:.4f};1"/>'
          f'<animate attributeName="opacity" values="1;1;0;0;1" keyTimes="0;{te:.4f};{te + .006:.4f};.997;1" dur="{D:.2f}s" repeatCount="indefinite"/>'
          f'<path d="{body}" fill="{col}"><animate attributeName="fill" calcMode="discrete" values="{col};{T["scared"]};{col}" keyTimes="0;{t_scared:.4f};.997" dur="{D:.2f}s" repeatCount="indefinite"/></path>'
          f'{eyes}</g>')
        # score pop when this ghost is eaten
        px, py = pos(d1)
        A(f'<text x="{px:.1f}" y="{py - 12:.1f}" font-size="11" font-weight="700" text-anchor="middle" fill="{T["pop"]}" opacity="0">{pts}'
          f'<animate attributeName="opacity" values="0;0;1;1;0;0" keyTimes="0;{te:.4f};{te + .008:.4f};{te + .05:.4f};{te + .07:.4f};1" dur="{D:.2f}s" repeatCount="indefinite"/>'
          f'<animateTransform attributeName="transform" type="translate" values="0 0;0 0;0 -10;0 -10" keyTimes="0;{te:.4f};{te + .06:.4f};1" dur="{D:.2f}s" repeatCount="indefinite"/></text>')

    # the cat
    ca, sa = 7.28, 5.29
    cc, sc_ = 8.98, .63
    open_d = f"M0,0 L{ca},{-sa} A9,9 0 1 0 {ca},{sa} Z"
    shut_d = f"M0,0 L{cc},{-sc_} A9,9 0 1 0 {cc},{sc_} Z"
    flip_kt = ["0"] + [f"{tf(k * (rowlen + P)):.4f}" for k in range(1, ROWS)]
    flip_v = ";".join("1 1" if k % 2 == 0 else "-1 1" for k in range(ROWS))
    sx, sy = pos(0)
    A(f'<g transform="translate({sx:.1f},{sy:.1f})">'
      f'<animateMotion dur="{D:.2f}s" repeatCount="indefinite" path="{rel_path(0, L)}" calcMode="linear" keyPoints="0;1;1" keyTimes="0;{rf:.4f};1"/>'
      f'<animate attributeName="opacity" values="1;1;0;0;1" keyTimes="0;{rf + .01:.4f};{rf + .05:.4f};.997;1" dur="{D:.2f}s" repeatCount="indefinite"/>'
      f'<g><animateTransform attributeName="transform" type="scale" calcMode="discrete" values="{flip_v}" keyTimes="{";".join(flip_kt)}" dur="{D:.2f}s" repeatCount="indefinite"/>'
      f'<line x1="-5" y1="1" x2="-14" y2="-1" stroke="{T["cat_dark"]}" stroke-width=".9" stroke-linecap="round" opacity=".8"/>'
      f'<line x1="-5" y1="3.5" x2="-14" y2="5.5" stroke="{T["cat_dark"]}" stroke-width=".9" stroke-linecap="round" opacity=".8"/>'
      f'<polygon points="-7.4,-5.2 -6.9,-13.4 -2.4,-8.6" fill="{T["cat"]}"/><polygon points="-6.6,-6.4 -6.5,-11 -3.8,-8" fill="{T["ear"]}"/>'
      f'<polygon points="2.4,-8.6 6.9,-13.4 7.4,-5.2" fill="{T["cat"]}"/><polygon points="3.8,-8 6.5,-11 6.6,-6.4" fill="{T["ear"]}"/>'
      f'<path d="{open_d}" fill="{T["cat"]}"><animate attributeName="d" values="{open_d};{shut_d};{open_d}" dur=".3s" repeatCount="indefinite"/></path>'
      f'<circle cx="-1.2" cy="-3.6" r="1.6" fill="{T["eye"]}"/><circle cx="-.7" cy="-4.1" r=".5" fill="#fff"/>'
      f'</g></g>')

    A('</g>')
    A(f'<rect x="8.5" y="8.5" width="1163" height="283" rx="24" fill="none" stroke="url(#shim)" stroke-width="1.3"/>')
    # legend (inside the frame, bottom right)
    lx = x0 + (cols - 1) * P + S - (5 * P + 62)
    A(f'<text x="{lx - 8}" y="268" font-size="10" text-anchor="end" fill="{T["faint"]}">Less</text>')
    A(f'<rect x="{lx}" y="258" width="{S - 3}" height="{S - 3}" rx="3" fill="{T["empty"]}" fill-opacity="{T["empty_op"]}"/>')
    for k, col in enumerate(T["levels"]):
        A(f'<rect x="{lx + (k + 1) * (S - 3 + 5)}" y="258" width="{S - 3}" height="{S - 3}" rx="3" fill="{col}"/>')
    A(f'<text x="{lx + 5 * (S - 3 + 5) + 4}" y="268" font-size="10" fill="{T["faint"]}">More</text>')
    A('</svg>')
    return "\n".join(o)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = "dist"
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
        args = [a for a in args if a != out]
    if not args:
        raise SystemExit(__doc__)
    user = args[0]
    cells = load(user, "--demo" in sys.argv)
    grid = to_grid(cells)
    os.makedirs(out, exist_ok=True)
    for theme in ("dark", "light"):
        svg = build(theme, grid)
        path = os.path.join(out, f"catman-{theme}.svg")
        open(path, "w", encoding="utf-8").write(svg)
        print(f"wrote {path} ({len(svg) // 1024} KB, {len(grid)} days)")


if __name__ == "__main__":
    main()
