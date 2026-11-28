#!/usr/bin/env python3
"""Builds the graphics on github.com/mjajal.

Reads my contribution calendar (public and private work, the same numbers the
profile page shows) and writes the SVG cards in assets/. A GitHub Action runs
this every day, so the page keeps itself up to date.

Standard library only. Run it with:  python scripts/build_profile.py
"""
from __future__ import annotations

import datetime as dt
import html
import json
import math
import os
import re
import sys
import textwrap
import urllib.request
from pathlib import Path

USER = os.environ.get("PROFILE_USER", "mjajal")
FIRST_YEAR = 2023  # the year the account was created
ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

# ---------------------------------------------------------------- look & feel
BG = "#0d1117"
PANEL = "#161b22"
BORDER = "#30363d"
LINE = "#21262d"
TEXT = "#e6edf3"
SOFT = "#adbac7"
MUTED = "#8b949e"
DIM = "#6e7681"
RED = "#ff3b3b"
GREENS = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"]
# the bars replay every LOOP seconds and step through these colours, then start over
LOOP = 5
PALETTES = [
    GREENS,
    ["#161b22", "#5a2a00", "#9c4a00", "#e07b00", "#ffa630"],  # orange
    ["#161b22", "#5c1010", "#9b1c1c", "#dc3535", "#ff6b6b"],  # red
    ["#161b22", "#0c2d6b", "#1158c7", "#388bfd", "#79c0ff"],  # blue
    ["#161b22", "#2e1065", "#5b21b6", "#8b5cf6", "#c4b5fd"],  # purple
    ["#161b22", "#4d4000", "#8a7300", "#d4b106", "#ffe14d"],  # yellow
]
# up fast, hold, drop, then stay down until the next loop (the colour switches while down)
REPLAY = (
    "0%{transform:scaleY(0);animation-timing-function:cubic-bezier(.2,.8,.2,1)}"
    "16%{transform:scaleY(1)}"
    "80%{transform:scaleY(1);animation-timing-function:ease-in}"
    "86%,100%{transform:scaleY(0)}"
)
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,'Liberation Mono',monospace"

BASE_CSS = f"""
text{{font-family:{SANS};fill:{TEXT}}}
.mono{{font-family:{MONO}}}
.cap{{font-size:11px;letter-spacing:1.6px;font-weight:600;fill:{MUTED}}}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important}}}}
"""

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WEEKDAYS_LONG = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"]


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def n(value: float) -> str:
    """Short number for SVG coordinates."""
    text = f"{value:.1f}"
    return text[:-2] if text.endswith(".0") else text


def colour_steps(name: str, colours: list[str], props: tuple[str, ...]) -> str:
    """Keyframes that hold each colour for one loop, then jump to the next."""
    share = 100 / len(colours)
    frames = []
    for index, colour in enumerate(colours):
        rule = ";".join(f"{prop}:{colour}" for prop in props)
        end = "100" if index == len(colours) - 1 else f"{(index + 1) * share - 0.01:.2f}"
        frames.append(f"{index * share:.2f}%,{end}%{{{rule}}}")
    return f"@keyframes {name}{{{''.join(frames)}}}"


def shade(color: str, factor: float) -> str:
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (int(r * factor), int(g * factor), int(b * factor))


def svg(width: int, height: int, label: str, css: str, defs: str, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" fill="none" role="img" aria-label="{esc(label)}">\n'
        f"<title>{esc(label)}</title>\n"
        f'<defs><clipPath id="card"><rect width="{width}" height="{height}" rx="14"/></clipPath>{defs}</defs>\n'
        f"<style>{BASE_CSS}{css}</style>\n"
        f'<rect x=".5" y=".5" width="{width - 1}" height="{height - 1}" rx="14" fill="{BG}" stroke="{BORDER}"/>\n'
        f"{body}\n</svg>\n"
    )


# ------------------------------------------------------------------ the data
def http(url: str, data: bytes | None = None, headers: dict | None = None) -> str:
    request = urllib.request.Request(
        url, data=data, headers={"User-Agent": "profile-readme-builder", **(headers or {})}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def year_end(year: int, today: dt.date) -> dt.date:
    return min(dt.date(year, 12, 31), today)


def from_graphql(today: dt.date, token: str) -> dict[str, int]:
    query = (
        "query($login:String!,$from:DateTime!,$to:DateTime!){user(login:$login){"
        "contributionsCollection(from:$from,to:$to){contributionCalendar{weeks{"
        "contributionDays{date contributionCount}}}}}}"
    )
    days: dict[str, int] = {}
    for year in range(FIRST_YEAR, today.year + 1):
        variables = {
            "login": USER,
            "from": f"{year}-01-01T00:00:00Z",
            "to": f"{year_end(year, today)}T23:59:59Z",
        }
        payload = json.dumps({"query": query, "variables": variables}).encode()
        reply = json.loads(http(
            "https://api.github.com/graphql", payload,
            {"Authorization": f"bearer {token}", "Content-Type": "application/json"},
        ))
        if reply.get("errors"):
            raise RuntimeError(reply["errors"])
        calendar = reply["data"]["user"]["contributionsCollection"]["contributionCalendar"]
        for week in calendar["weeks"]:
            for day in week["contributionDays"]:
                if day["date"].startswith(str(year)):
                    days[day["date"]] = day["contributionCount"]
    return days


CELL = re.compile(r"<td[^>]*data-date=[^>]*>")
TIP = re.compile(r'<tool-tip[^>]*\sfor="([^"]+)"[^>]*>([^<]*)</tool-tip>')


def from_profile_page(today: dt.date) -> dict[str, int]:
    """Same calendar the profile page draws, read from its public HTML."""
    days: dict[str, int] = {}
    for year in range(FIRST_YEAR, today.year + 1):
        page = http(
            f"https://github.com/users/{USER}/contributions?from={year}-01-01&to={year_end(year, today)}",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        cells = {}
        for tag in CELL.findall(page):
            date = re.search(r'data-date="([\d-]+)"', tag)
            cell_id = re.search(r'\sid="([^"]+)"', tag)
            if date and cell_id:
                cells[cell_id.group(1)] = date.group(1)
        found = 0
        for cell_id, tip in TIP.findall(page):
            date = cells.get(cell_id)
            if not date or not date.startswith(str(year)):
                continue
            count = re.match(r"([\d,]+)\s+contribution", html.unescape(tip).strip())
            days[date] = int(count.group(1).replace(",", "")) if count else 0
            found += 1
        if not found:
            raise RuntimeError(f"no calendar cells found for {year}")
    return days


def load_days(today: dt.date) -> dict[str, int]:
    """Tries both sources and keeps the fuller one (private work counts too)."""
    results = []
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        try:
            results.append(("graphql", from_graphql(today, token)))
        except Exception as error:  # noqa: BLE001 - fall back to the other source
            print(f"graphql source failed: {error}", file=sys.stderr)
    try:
        results.append(("profile page", from_profile_page(today)))
    except Exception as error:  # noqa: BLE001
        print(f"profile page source failed: {error}", file=sys.stderr)
    if not results:
        raise SystemExit("could not read the contribution calendar from any source")
    for name, days in results:
        print(f"{name}: {sum(days.values()):,} contributions over {len(days):,} days")
    name, days = max(results, key=lambda item: sum(item[1].values()))
    print(f"using: {name}")
    return {date: count for date, count in days.items() if date <= today.isoformat()}


def streaks(days: dict[str, int], today: dt.date) -> tuple[int, int, int]:
    """(longest streak, current streak, longest streak before the current one) in days."""
    one = dt.timedelta(days=1)
    longest = run = 0
    day = dt.date(FIRST_YEAR, 1, 1)
    while day <= today:
        run = run + 1 if days.get(day.isoformat(), 0) else 0
        longest = max(longest, run)
        day += one
    current = 0
    day = today if days.get(today.isoformat(), 0) else today - one
    while days.get(day.isoformat(), 0):
        current += 1
        day -= one
    # `day` is now the last day before the current streak began
    previous = run = 0
    cursor = dt.date(FIRST_YEAR, 1, 1)
    while cursor <= day:
        run = run + 1 if days.get(cursor.isoformat(), 0) else 0
        previous = max(previous, run)
        cursor += one
    return longest, current, previous


# ------------------------------------------------------------------- header
def build_header() -> str:
    width, height = 880, 250
    phrases = ["data trailblazer", "AI agent mastermind", "relentless troubleshooter", "data-platform architect"]
    char_w = 10.2
    slot = 4.0
    total = slot * len(phrases)

    frames = []
    for index, phrase in enumerate(phrases):
        count = len(phrase)
        begin = index * slot
        full = f"{count * char_w:.0f}px"

        def at(seconds: float) -> str:
            return f"{(begin + seconds) / total * 100:.2f}%"

        frames += [
            f"{at(0)}{{transform:translateX(0);animation-timing-function:steps({count},end)}}",
            f"{at(count * 0.065)}{{transform:translateX({full});animation-timing-function:linear}}",
            f"{at(2.9)}{{transform:translateX({full});animation-timing-function:steps({count},end)}}",
            f"{at(2.9 + count * 0.03)}{{transform:translateX(0);animation-timing-function:linear}}",
        ]
    frames.append("100%{transform:translateX(0)}")
    share = 100 / len(phrases)

    css = f"""
.name{{font-size:46px;font-weight:800;letter-spacing:-.5px}}
.role{{font-size:12px;letter-spacing:2px;font-weight:600;fill:{RED}}}
.tag{{font-size:15px;fill:{MUTED}}}
.typed{{font-size:18px;font-weight:600}}
.ph{{opacity:0;animation:show {total:.0f}s linear infinite}}
.ph0{{opacity:1}}
.cover{{transform:translateX({len(phrases[0]) * char_w:.0f}px);animation:type {total:.0f}s infinite}}
.caret{{animation:blink 1s steps(1,end) infinite}}
.node{{font-size:11px;fill:{SOFT}}}
.col{{font-size:9px;letter-spacing:2px;font-weight:600;fill:{DIM}}}
.hub{{font-size:12px;font-weight:700;fill:{TEXT}}}
.pipe{{stroke:{BORDER};stroke-width:1.4}}
@keyframes show{{0%,{share - 0.05:.2f}%{{opacity:1}}{share:.2f}%,100%{{opacity:0}}}}
@keyframes type{{{''.join(frames)}}}
@keyframes blink{{0%{{opacity:1}}50%{{opacity:0}}}}
"""
    defs = f"""
<pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="1.5" cy="1.5" r="1" fill="{LINE}"/></pattern>
<radialGradient id="glowRed" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(60 20) scale(460 300)"><stop stop-color="{RED}" stop-opacity=".2"/><stop offset="1" stop-color="{RED}" stop-opacity="0"/></radialGradient>
<radialGradient id="glowGreen" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(820 240) scale(380 240)"><stop stop-color="{GREENS[4]}" stop-opacity=".1"/><stop offset="1" stop-color="{GREENS[4]}" stop-opacity="0"/></radialGradient>
<clipPath id="pill"><rect x="45" y="163" width="318" height="40" rx="9"/></clipPath>
<filter id="blur" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="9"/></filter>
"""

    typed = "".join(
        f'<text class="mono typed ph ph{index}" x="88" y="189" textLength="{len(phrase) * char_w:.0f}" '
        f'lengthAdjust="spacingAndGlyphs" style="animation-delay:{index * slot:.0f}s">{esc(phrase)}</text>'
        for index, phrase in enumerate(phrases)
    )

    # the data-flow picture: what comes in, the platform, what it serves
    rows = [62, 96, 130, 164, 198]
    sources = ["batch", "streaming", "CDC", "events", "APIs"]
    sinks = ["warehouse", "backend APIs", "MCP server", "dashboards", "metrics"]
    consumers = [("AI agents", 113), ("LLM", 147)]  # fed through the MCP server
    src_x, src_w = 392, 76
    hub_left, hub_right, hub_y = 508, 614, 130
    sink_x, sink_w = 654, 92
    ai_x, ai_w = 776, 72
    served = "#ff7b72"

    def dot(path: str, color: str, start: float, dur: float) -> str:
        timing = f'dur="{dur}s" begin="-{start:.1f}s" repeatCount="indefinite"'
        return (
            f'<circle r="2.6" fill="{color}" opacity="0"><animateMotion {timing} path="{path}"/>'
            f'<animate attributeName="opacity" values="0;1;1;0" keyTimes="0;.15;.85;1" {timing}/></circle>'
        )

    def pill(x: float, y: float, w: float, name: str, accent: bool = False) -> str:
        bright = f' style="fill:{TEXT}"' if accent else ""
        return (
            f'<rect x="{x}" y="{y - 12}" width="{w}" height="24" rx="12" fill="{PANEL}" stroke="{served if accent else BORDER}"/>'
            f'<text class="mono node" x="{x + w / 2:.0f}" y="{y + 4}" text-anchor="middle"{bright}>{name}</text>'
        )

    pipes, dots, nodes = [], [], []
    for index, y in enumerate(rows):
        into = f"M{src_x + src_w} {y}C{src_x + src_w + 22} {y} {hub_left - 22} {hub_y} {hub_left} {hub_y}"
        out = f"M{hub_right} {hub_y}C{hub_right + 22} {hub_y} {sink_x - 22} {y} {sink_x} {y}"
        pipes.append(f'<path class="pipe" d="{into}"/><path class="pipe" d="{out}"/>')
        for shift in (0, 1.3):
            dots.append(dot(into, GREENS[4], index * 0.5 + shift, 2.6))
            dots.append(dot(out, served, index * 0.5 + 1.1 + shift, 2.6))
        nodes.append(pill(src_x, y, src_w, sources[index]))
        nodes.append(pill(sink_x, y, sink_w, sinks[index], accent=sinks[index] == "MCP server"))
    for index, (name, y) in enumerate(consumers):
        path = f"M{sink_x + sink_w} {hub_y}C{sink_x + sink_w + 16} {hub_y} {ai_x - 16} {y} {ai_x} {y}"
        pipes.append(f'<path class="pipe" d="{path}"/>')
        dots.append(dot(path, served, index * 0.8, 1.6))
        nodes.append(pill(ai_x, y, ai_w, name))
    nodes.append(
        f'<text class="col" x="{src_x + src_w / 2:.0f}" y="38" text-anchor="middle">INGEST</text>'
        f'<text class="col" x="{sink_x + sink_w / 2:.0f}" y="38" text-anchor="middle">SERVE</text>'
    )

    body = f"""
<g clip-path="url(#card)"><rect width="{width}" height="{height}" fill="url(#dots)"/><rect width="{width}" height="{height}" fill="url(#glowRed)"/><rect width="{width}" height="{height}" fill="url(#glowGreen)"/></g>
<text class="role" x="46" y="60">SENIOR DATA ENGINEER · DATA PLATFORM</text>
<text class="name" x="44" y="110">Maulik Jajal</text>
<text class="tag" x="46" y="140">Building the platforms data moves through.</text>
<rect x="44.5" y="162.5" width="319" height="41" rx="10" fill="{PANEL}" stroke="{BORDER}"/>
<text class="mono typed" x="62" y="189" style="fill:{RED}">&gt;</text>
{typed}
<g clip-path="url(#pill)"><g transform="translate(88 168)"><g class="cover"><rect width="300" height="30" fill="{PANEL}"/><rect class="caret" x="2" y="4" width="9" height="22" rx="1.5" fill="{RED}"/></g></g></g>
{''.join(pipes)}
{''.join(dots)}
{''.join(nodes)}
<rect x="{hub_left}" y="{hub_y - 20}" width="{hub_right - hub_left}" height="40" rx="12" fill="{RED}" opacity=".35" filter="url(#blur)"/>
<rect x="{hub_left}" y="{hub_y - 20}" width="{hub_right - hub_left}" height="40" rx="12" fill="#1c1215" stroke="{RED}" stroke-width="1.4"/>
<text class="mono hub" x="{(hub_left + hub_right) / 2:.0f}" y="{hub_y + 4}" text-anchor="middle">data platform</text>
"""
    label = "Maulik Jajal, Senior Data Engineer: data trailblazer, AI agent mastermind, relentless troubleshooter, data-platform architect"
    return svg(width, height, label, css, defs, body)


# ------------------------------------------------------- 3D contribution map
def build_contrib3d(days: dict[str, int], today: dt.date) -> str:
    width, height = 880, 490
    one = dt.timedelta(days=1)
    start = today - dt.timedelta(days=364)
    start -= dt.timedelta(days=(start.weekday() + 1) % 7)  # back to Sunday
    cells = []
    day = start
    while day <= today:
        cells.append((day, days.get(day.isoformat(), 0)))
        day += one
    weeks = math.ceil(len(cells) / 7)
    counts = [count for _, count in cells]
    total = sum(counts)
    peak = max(counts) or 1
    worked = sorted(count for count in counts if count)

    def quantile(share: float) -> int:
        return worked[min(len(worked) - 1, int(share * len(worked)))] if worked else 0

    q1, q2, q3 = quantile(0.25), quantile(0.5), quantile(0.75)

    def level(count: int) -> int:
        return 1 if count <= q1 else 2 if count <= q2 else 3 if count <= q3 else 4

    grid = 748.0
    a = grid / (weeks + 7)       # half a tile, across
    b = a * 0.44                 # half a tile, down
    ox = (width - grid) / 2 + 7 * a
    oy = 120.0
    fa, fb = a * 0.86, b * 0.86  # tiles sit slightly apart

    ground, blocks = [], []
    for index, (_, count) in enumerate(cells):
        week, dow = divmod(index, 7)
        cx = ox + (week - dow) * a
        cy = oy + (week + dow) * b + b
        if not count:
            ground.append(f"M{n(cx)} {n(cy - fb)}l{n(fa)} {n(fb)}l{n(-fa)} {n(fb)}l{n(-fa)} {n(-fb)}z")
            continue
        lv = level(count)
        h = 5 + 80 * (count / peak) ** 0.6
        left = f"M{n(cx - fa)} {n(cy)}l{n(fa)} {n(fb)}v{n(-h)}l{n(-fa)} {n(-fb)}z"
        right = f"M{n(cx)} {n(cy + fb)}l{n(fa)} {n(-fb)}v{n(-h)}l{n(-fa)} {n(fb)}z"
        top = f"M{n(cx)} {n(cy - fb - h)}l{n(fa)} {n(fb)}l{n(-fa)} {n(fb)}l{n(-fa)} {n(-fb)}z"
        delay = 0.05 + week * 0.008 + dow * 0.005
        blocks.append(
            f'<g class="k" style="transform-origin:{n(cx)}px {n(cy + fb)}px;animation-delay:{delay:.2f}s">'
            f'<path class="l{lv}" d="{left}"/><path class="r{lv}" d="{right}"/><path class="t{lv}" d="{top}"/></g>'
        )

    labels = []
    last_month = None
    for week in range(weeks):
        first = cells[week * 7][0]
        if first.month != last_month:
            if last_month is not None or first.day <= 7:
                x = ox + (week - 7.7) * a
                y = oy + (week + 7.7) * b + b
                labels.append(f'<text class="mono mon" x="{n(x)}" y="{n(y)}" text-anchor="end">{MONTHS[first.month - 1]}</text>')
            last_month = first.month

    # headline numbers; anything too small to be worth showing is left out
    all_time = sum(days.values())
    longest, current, previous = streaks(days, today)
    busiest = max(counts)
    active = sum(1 for count in counts if count)
    stats = []
    if current >= 3:
        stats.append((f"{current} days", "CURRENT STREAK"))
        if previous >= 5:
            stats.append((f"{previous} days", "PREVIOUS\nLONGEST STREAK"))
    elif longest >= 5:
        stats.append((f"{longest} days", "LONGEST STREAK"))
    if active >= 30:
        stats.append((f"{active}", "ACTIVE DAYS\nIN PAST YEAR"))
    if busiest >= 25:
        stats.append((f"{busiest}", "BUSIEST DAY"))
    stat_svg = []
    x = 44
    for value, caption in stats[:3]:
        lines = caption.split("\n")  # a long caption sits on two lines
        stat_svg.append(
            f'<text class="num" x="{x}" y="{height - 66}">'
            + re.sub(r"^[\d,]+", lambda m: f'<tspan class="hl">{m.group()}</tspan>', esc(value))
            + "</text>"
            + "".join(
                f'<text class="cap" x="{x}" y="{height - 46 + 15 * n}">{line}</text>'
                for n, line in enumerate(lines)
            )
        )
        x += round(max(max(len(line) for line in lines) * 8.7, len(value) * 15)) + 28

    since = ""
    if all_time >= total * 1.2:
        since = f'<text class="sub" x="{width - 40}" y="152" text-anchor="end"><tspan class="hl">{all_time:,}</tspan> since {FIRST_YEAR}</text>'

    faces = ""
    for lv in range(1, 5):
        for face, dim in (("t", 1.0), ("l", .72), ("r", .48)):
            first = shade(GREENS[lv], dim)
            colours = [shade(palette[lv], dim) for palette in PALETTES]
            faces += (
                f".{face}{lv}{{fill:{first};stroke:{first};"
                f"animation:c{face}{lv} {LOOP * len(PALETTES)}s linear infinite}}"
                + colour_steps(f"c{face}{lv}", colours, ("fill", "stroke"))
            )
    css = f"""
.k{{animation:rise {LOOP}s infinite backwards}}
.k path{{stroke-width:.4;stroke-linejoin:round}}
{faces}
.mon{{font-size:10px;fill:{DIM}}}
.big{{font-size:54px;font-weight:800;letter-spacing:-1px}}
.lbl{{font-size:15px;fill:{SOFT}}}
.sub{{font-size:12px;fill:{MUTED}}}
.num{{font-size:26px;font-weight:700}}
.foot{{font-size:11px;fill:{DIM}}}
.hl{{fill:{GREENS[4]};animation:chl {LOOP * len(PALETTES)}s linear infinite}}
{colour_steps('chl', [palette[4] for palette in PALETTES], ('fill',))}
@keyframes rise{{{REPLAY}}}
"""
    defs = f"""
<radialGradient id="floor" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(440 300) scale(520 240)"><stop stop-color="{GREENS[3]}" stop-opacity=".09"/><stop offset="1" stop-color="{GREENS[3]}" stop-opacity="0"/></radialGradient>
"""
    body = f"""
<g clip-path="url(#card)"><rect width="{width}" height="{height}" fill="url(#floor)"/></g>
<path d="{''.join(ground)}" fill="{PANEL}" stroke="{LINE}" stroke-width=".6"/>
{''.join(blocks)}
{''.join(labels)}
<text class="cap" x="{width - 40}" y="52" text-anchor="end">LAST 12 MONTHS</text>
<text class="big hl" x="{width - 40}" y="106" text-anchor="end">{total:,}</text>
<text class="lbl" x="{width - 40}" y="130" text-anchor="end">contributions</text>
{since}
{''.join(stat_svg)}
<text class="foot" x="{width - 40}" y="{height - 22}" text-anchor="end">public + private work · rebuilt daily</text>
"""
    label = f"3D view of {total:,} GitHub contributions over the last 12 months"
    return svg(width, height, label, css, defs, body)


# ------------------------------------------------------------- rhythm charts
def build_rhythm(days: dict[str, int], today: dt.date) -> str:
    width, height = 880, 240
    base, tallest = 198.0, 92.0

    months = []
    year, month = today.year, today.month
    for _ in range(12):
        months.append((year, month))
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    months.reverse()
    by_month = [
        (MONTHS[m - 1], sum(c for d, c in days.items() if d.startswith(f"{y}-{m:02d}")), MONTHS_LONG[m - 1])
        for y, m in months
    ]

    window_start = (today - dt.timedelta(days=364)).isoformat()
    by_weekday = [0] * 7
    for date, count in days.items():
        if date >= window_start:
            by_weekday[dt.date.fromisoformat(date).weekday()] += count

    by_year = [(y, sum(c for d, c in days.items() if d.startswith(str(y)))) for y in range(FIRST_YEAR, today.year + 1)]
    year_peak = max(count for _, count in by_year) or 1
    by_year = [(y, count) for y, count in by_year if count >= year_peak * 0.05]

    def bars(values: list[int], names: list[str], x0: float, span: float, bar: float, delay: float) -> str:
        peak = max(values) or 1
        pitch = span / len(values)
        parts = []
        for index, value in enumerate(values):
            h = max(2.0, tallest * value / peak)
            x = x0 + index * pitch + (pitch - bar) / 2
            best = value == peak
            bright = f' style="fill:{TEXT}"' if best else ""
            parts.append(
                f'<rect class="bar" x="{n(x)}" y="{n(base - h)}" width="{n(bar)}" height="{n(h)}" rx="3" '
                f'fill="url(#bars)" opacity="{1 if best else .6}" style="animation-delay:{delay + index * .03:.2f}s"/>'
                f'<text class="mono tick" x="{n(x + bar / 2)}" y="216" text-anchor="middle"'
                f'{bright}>{names[index]}</text>'
            )
            if value >= peak * 0.25 and (best or len(values) <= 5):
                parts.append(
                    f'<text class="mono val" x="{n(x + bar / 2)}" y="{n(base - h - 6)}" text-anchor="middle">{value:,}</text>'
                )
        return "".join(parts)

    month_values = [value for _, value, _ in by_month]
    top_month = by_month[month_values.index(max(month_values))][2]
    top_weekday = WEEKDAYS_LONG[by_weekday.index(max(by_weekday))]
    top_year = max(by_year, key=lambda item: item[1])[0]
    year_line = f"Busiest: {top_year}"

    css = f"""
.say{{font-size:15px;font-weight:600}}
.tick{{font-size:10px;fill:{DIM}}}
.val{{font-size:10px;fill:{SOFT}}}
.bar{{transform-origin:0 {base:.0f}px;animation:grow {LOOP}s infinite backwards}}
.hi{{animation:hi {LOOP * len(PALETTES)}s linear infinite}}.lo{{animation:lo {LOOP * len(PALETTES)}s linear infinite}}
{colour_steps('hi', [palette[4] for palette in PALETTES], ('stop-color',))}
{colour_steps('lo', [palette[2] for palette in PALETTES], ('stop-color',))}
@keyframes grow{{{REPLAY}}}
"""
    defs = (
        f'<linearGradient id="bars" gradientUnits="userSpaceOnUse" x1="0" y1="{base - tallest:.0f}" x2="0" y2="{base:.0f}">'
        f'<stop class="hi" stop-color="{GREENS[4]}"/><stop class="lo" offset="1" stop-color="{GREENS[2]}"/></linearGradient>'
    )
    body = f"""
<text class="cap" x="44" y="44">BY MONTH</text>
<text class="say" x="44" y="68">{top_month} was the peak</text>
{bars(month_values, [name for name, _, _ in by_month], 44, 372, 19, .05)}
<path d="M440 36V{height - 30}M684 36V{height - 30}" stroke="{LINE}"/>
<text class="cap" x="464" y="44">BY WEEKDAY</text>
<text class="say" x="464" y="68">{top_weekday} run hottest</text>
{bars(by_weekday, WEEKDAYS, 464, 196, 17, .2)}
<text class="cap" x="708" y="44">BY YEAR</text>
<text class="say" x="708" y="68">{year_line}</text>
{bars([count for _, count in by_year], [str(y) for y, _ in by_year], 708, 132, min(24, 132 / len(by_year) - 10), .35)}
"""
    return svg(width, height, "Contributions by month, weekday and year", css, defs, body)


# ------------------------------------------------------------------ journey
JOURNEY = [
    ("2023 → now", "League", "Senior Data Engineer → Senior Data Engineer II",
     "Healthcare data platform and backend services on GCP: real-time and batch pipelines, "
     "zero-downtime migrations, a care LLM agent and its MCP server",
     "Raised the Floor for Everyone Award · Data Quality Achievement Award"),
    ("2022 → 2023", "Innovaccer", "Senior Data Engineer",
     "Multi-source FHIR pipelines and reusable integration templates on Snowflake and AWS", ""),
    ("2018 → 2022", "d2i", "Data Engineer → Senior Data Engineer",
     "Built the core pipeline platform and led the data engineering team as it grew. "
     "Real-time and batch hospital data on AWS: EHR integrations, pipeline and platform automation", ""),
    ("2017 → 2018", "Stevens Institute of Technology", "M.S. Computer Science",
     "Master's Fellowship · Course Assistant for Data Structures & Algorithms", ""),
    ("2015 → 2016", "Infosys", "Systems Engineer, Test",
     "SAP testing and test automation. Where I learned to break things on purpose.", ""),
    ("2011 → 2015", "Dharmsinh Desai University", "B.Tech, Information Technology",
     "Nadiad, Gujarat, India. Where it all started.", ""),
]


def build_journey() -> str:
    width = 880
    y = 92
    rows, positions = [], []
    for index, (years, place, role, what, extra) in enumerate(JOURNEY):
        positions.append(y)
        now = index == 0
        lines = textwrap.wrap(what, 96, break_on_hyphens=False)
        bright = f' style="fill:{TEXT}"' if now else ""
        dot = (
            f'<circle cx="176" cy="{y - 5}" r="5" fill="{RED}"><animate attributeName="r" values="5;13" dur="1.8s" repeatCount="indefinite"/>'
            f'<animate attributeName="opacity" values=".55;0" dur="1.8s" repeatCount="indefinite"/></circle>'
            f'<circle cx="176" cy="{y - 5}" r="5" fill="{RED}"/>'
            if now else
            f'<circle cx="176" cy="{y - 5}" r="4.5" fill="{BG}" stroke="{DIM}" stroke-width="1.5"/>'
        )
        rows.append(
            f'<text class="mono yrs" x="152" y="{y}" text-anchor="end"{bright}>{esc(years)}</text>'
            f"{dot}"
            f'<text class="place" x="202" y="{y}">{esc(place)}<tspan class="role" dx="10">{esc(role)}</tspan></text>'
            + "".join(
                f'<text class="what" x="202" y="{y + 21 + 18 * n}">{esc(line)}</text>'
                for n, line in enumerate(lines)
            )
        )
        more = 18 * (len(lines) - 1)  # a long description wraps onto a second line
        if extra:
            rows.append(f'<text class="extra" x="202" y="{y + 41 + more}">{esc(extra)}</text>')
            y += 20
        y += 64 + more
    height = y - 64 + 21 + 34
    css = f"""
.yrs{{font-size:12px;fill:{MUTED}}}
.place{{font-size:16px;font-weight:700}}
.role{{font-size:13px;font-weight:400;fill:{MUTED}}}
.what{{font-size:13px;fill:{SOFT}}}
.extra{{font-size:12px;fill:{DIM}}}
"""
    body = f"""
<text class="cap" x="44" y="46">THE ROAD SO FAR</text>
<text class="cap" x="{width - 40}" y="46" text-anchor="end" style="fill:{DIM}">NOW → THEN</text>
<path d="M176 {positions[0] - 5}V{positions[-1] - 5}" stroke="{BORDER}" stroke-width="1.5"/>
{''.join(rows)}
"""
    return svg(width, height, "Career timeline, from now back to 2011", css, "", body)


# ----------------------------------------------------------- LinkedIn button
def build_linkedin() -> str:
    width, height = 268, 46
    blue = "#0a66c2"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="Connect with me on LinkedIn"><title>Connect with me on LinkedIn</title>'
        f'<rect width="{width}" height="{height}" rx="10" fill="{blue}"/>'
        f'<rect x="14" y="11" width="24" height="24" rx="4" fill="#fff"/>'
        f'<text x="26" y="29.5" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" font-size="15.5" font-weight="700" fill="{blue}">in</text>'
        f'<text x="50" y="28.5" font-family="{SANS}" font-size="15" font-weight="600" fill="#fff">Let\'s talk on LinkedIn</text>'
        f'<path d="M232 23h14m-5-5l5 5-5 5" stroke="#fff" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round">'
        f'<animateTransform attributeName="transform" type="translate" values="0 0;4 0;0 0" dur="1.6s" repeatCount="indefinite"/></path>'
        f"</svg>\n"
    )


# -------------------------------------------------------------- intro lines
def build_intro() -> str:
    """The two intro lines on a dark card, so they read the same in any theme."""
    width, height = 880, 96
    emoji = "'Segoe UI Emoji','Apple Color Emoji','Noto Color Emoji'"
    css = f".one{{font-size:17px}}.two{{font-size:17px;fill:{SOFT};font-family:{SANS},{emoji}}}"
    body = (
        f'<text class="one" x="28" y="40" textLength="824" lengthAdjust="spacingAndGlyphs">'
        f'<tspan font-weight="700">Hi, I&#39;m Maulik Jajal.</tspan> Data trailblazer, AI agent mastermind, '
        f'relentless troubleshooter, and data-platform architect.</text>'
        f'<text class="two" x="{width / 2:.0f}" y="72" text-anchor="middle">'
        f'<tspan font-style="italic">Usually all four before lunch.</tspan> ☕⚡</text>'
    )
    label = ("Hi, I am Maulik Jajal. Data trailblazer, AI agent mastermind, relentless troubleshooter, "
             "and data-platform architect. Usually all four before lunch.")
    return svg(width, height, label, css, "", body)


def main() -> None:
    today = dt.datetime.now(dt.timezone.utc).date()
    days = load_days(today)
    ASSETS.mkdir(exist_ok=True)
    cards = {
        "header.svg": build_header(),
        "contrib-3d.svg": build_contrib3d(days, today),
        "rhythm.svg": build_rhythm(days, today),
        "journey.svg": build_journey(),
        "linkedin.svg": build_linkedin(),
        "intro.svg": build_intro(),
    }
    for name, content in cards.items():
        (ASSETS / name).write_text(content, encoding="utf-8", newline="\n")
        print(f"wrote assets/{name} ({len(content) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
