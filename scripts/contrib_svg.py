#!/usr/bin/env python3
"""
contrib_svg.py — render the contribution calendar as an SVG that loads in gradually.

GitHub serves README images through camo, which rules out JS but does allow CSS
animation inside an SVG. So the grid is drawn once and each cell is given an
animation-delay derived from its column: the squares sweep in left to right over
a couple of seconds and then hold, the way the calendar fills on a cold load.

Data comes from the public contributions fragment
(https://github.com/users/<login>/contributions) — no token, no API scope. That
page is unreachable from a sandbox whose egress proxy only permits the GitHub
API, which is why this is built to run in Actions rather than locally.

Usage:
    python3 scripts/contrib_svg.py --user marcmsawaya --out assets/contributions.svg
    python3 scripts/contrib_svg.py --demo --out /tmp/demo.svg   # synthetic data
"""

import argparse
import datetime as dt
import html.parser
import random
import re
import sys
import urllib.request

CELL, GAP = 11, 3            # square size and spacing, matching GitHub's calendar
PAD_X, PAD_TOP = 26, 22      # room for weekday labels and the month row
LEVEL_FILL = {               # GitHub's dark-theme green ramp
    0: "#161b22", 1: "#0e4429", 2: "#006d32", 3: "#26a641", 4: "#39d353",
}
BG = "#0d1117"
TEXT = "#8b949e"
SWEEP_SECONDS = 2.4          # how long the whole grid takes to arrive
CELL_FADE = 0.45             # how long one square takes to appear
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class _CalendarParser(html.parser.HTMLParser):
    """Pull (date, level) out of the contribution fragment's <td> cells."""

    def __init__(self):
        super().__init__()
        self.days = []

    def handle_starttag(self, tag, attrs):
        if tag not in ("td", "rect"):
            return
        a = dict(attrs)
        date, level = a.get("data-date"), a.get("data-level")
        if date and level is not None:
            try:
                self.days.append((dt.date.fromisoformat(date), int(level)))
            except ValueError:
                pass


def fetch(user):
    req = urllib.request.Request(
        f"https://github.com/users/{user}/contributions",
        headers={"User-Agent": "contrib-svg (github actions)"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8", "replace")
    p = _CalendarParser()
    p.feed(body)
    if not p.days:
        # the fragment's markup has changed shape before; fail loudly rather than
        # committing an empty calendar over a good one
        raise SystemExit("contrib_svg: parsed 0 days — the contributions markup changed")
    return sorted(p.days)


def demo_days():
    today = dt.date.today()
    start = today - dt.timedelta(days=364)
    random.seed(7)
    out = []
    for i in range(365):
        d = start + dt.timedelta(days=i)
        lvl = 0 if d.weekday() >= 5 and random.random() < 0.6 else random.choice(
            [0, 0, 1, 1, 2, 2, 3, 4])
        out.append((d, lvl))
    return out


def build_svg(days, user):
    # column 0 is the week containing the first day; rows are Sun..Sat like GitHub
    first = days[0][0]
    origin = first - dt.timedelta(days=(first.weekday() + 1) % 7)
    cells, months, seen_month = [], [], set()
    max_col = 0

    for d, level in days:
        offset = (d - origin).days
        col, row = divmod(offset, 7)
        max_col = max(max_col, col)
        x = PAD_X + col * (CELL + GAP)
        y = PAD_TOP + row * (CELL + GAP)
        # delay is a function of the column, so the grid arrives as a left-to-right
        # sweep instead of every square popping at once
        delay = round(col / max(1, 52) * SWEEP_SECONDS, 3)
        cells.append(
            f'<rect class="d" x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" '
            f'fill="{LEVEL_FILL.get(level, LEVEL_FILL[0])}" '
            f'style="animation-delay:{delay}s"><title>{d.isoformat()}: level {level}</title></rect>'
        )
        key = (d.year, d.month)
        if d.day <= 7 and key not in seen_month:
            seen_month.add(key)
            months.append(f'<text class="lbl" x="{x}" y="14">{MONTHS[d.month - 1]}</text>')

    width = PAD_X + (max_col + 1) * (CELL + GAP) + 10
    height = PAD_TOP + 7 * (CELL + GAP) + 24
    weekdays = "".join(
        f'<text class="lbl" x="2" y="{PAD_TOP + r * (CELL + GAP) + CELL - 1}">{n}</text>'
        for r, n in ((1, "Mon"), (3, "Wed"), (5, "Fri"))
    )
    total = sum(1 for _, lvl in days if lvl > 0)
    caption = (f'<text class="lbl" x="{PAD_X}" y="{height - 7}">'
               f'{user} · {total} active days in the last year</text>')

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{user} contribution calendar">
  <style>
    /* Default to visible and let the animation take it away first. With
       fill-mode backwards the square holds opacity 0 through its delay, fades
       in, then falls back to this rule — so a renderer that ignores CSS
       animation shows a complete calendar rather than an empty box. */
    .d {{ opacity: 1; animation: pop {CELL_FADE}s ease-out backwards; }}
    .lbl {{ fill: {TEXT}; font: 9px ui-monospace, SFMono-Regular, Menlo, monospace; }}
    @keyframes pop {{
      from {{ opacity: 0; }}
      to   {{ opacity: 1; }}
    }}
    @media (prefers-reduced-motion: reduce) {{
      .d {{ opacity: 1; animation: none; }}
    }}
  </style>
  <rect width="{width}" height="{height}" fill="{BG}" rx="6"/>
  {"".join(months)}
  {weekdays}
  {"".join(cells)}
  {caption}
</svg>
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="marcmsawaya")
    ap.add_argument("--out", required=True)
    ap.add_argument("--demo", action="store_true", help="synthetic data, for local checks")
    args = ap.parse_args()

    days = demo_days() if args.demo else fetch(args.user)
    svg = build_svg(days, args.user)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(svg)
    print(f"{args.out}: {len(days)} days, {len(svg)} bytes")


if __name__ == "__main__":
    main()
