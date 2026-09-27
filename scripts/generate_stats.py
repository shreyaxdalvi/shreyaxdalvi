#!/usr/bin/env python3
"""
Pull contribution + language data from the GitHub GraphQL API and draw four
SVGs in the same visual language as the ASCII portrait: hero total + weekly
sparkline, streaks, top languages, and a year-at-a-glance grid.

Standard library only -- urllib for HTTP, no third-party dependencies to
break in CI. Requires GITHUB_TOKEN and GH_LOGIN in the environment (the
workflow's built-in GITHUB_TOKEN is enough -- no PAT needed).
"""
import os
import sys
import json
import datetime
import urllib.request
import urllib.error

RAMP = " .`:-=+*cs#%@"
CHAR_W = 7.74
FONT_SIZE = 12.9
BG = "#0d1117"
FG = "#cfcfcf"
DIM = "#6e7681"
ACCENT = "#7dd3fc"

API_URL = "https://api.github.com/graphql"


def gql(query: str, variables: dict, token: str) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        API_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "profile-stats-script",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"GraphQL HTTP error: {e.code} {e.read()}\n")
        raise


def utc_window():
    today = datetime.datetime.now(datetime.timezone.utc).date()
    start = today - datetime.timedelta(days=364)
    frm = datetime.datetime.combine(start, datetime.time(0, 0, 0), datetime.timezone.utc)
    to = datetime.datetime.combine(today, datetime.time(23, 59, 59), datetime.timezone.utc)
    return frm.isoformat().replace("+00:00", "Z"), to.isoformat().replace("+00:00", "Z")


CONTRIB_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays { date contributionCount }
        }
      }
    }
    repositories(first: 100, privacy: PUBLIC, ownerAffiliations: OWNER, isFork: false) {
      nodes {
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""


def fetch(login: str, token: str) -> dict:
    frm, to = utc_window()
    data = gql(CONTRIB_QUERY, {"login": login, "from": frm, "to": to}, token)
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]["user"]


def compute_streaks(days):
    """days: list of (date, count) ordered chronologically."""
    longest = cur = 0
    longest_range = cur_range = None
    run_start = None
    for date, count in days:
        if count > 0:
            if run_start is None:
                run_start = date
            cur += 1
            if cur > longest:
                longest = cur
                longest_range = (run_start, date)
        else:
            cur = 0
            run_start = None
    # current streak = consecutive contributing days ending at the *last*
    # day in the window. A zero-count final day means current == 0 --
    # it must not skip past that day to find an earlier run.
    current = 0
    current_start = None
    end_date = days[-1][0] if days else None
    for date, count in reversed(days):
        if count > 0:
            current += 1
            current_start = date
        else:
            break
    return {
        "longest": longest,
        "longest_range": longest_range,
        "current": current,
        "current_range": (current_start, end_date) if current else None,
    }


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def svg_shell(width, height, title):
    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{esc(title)}">'
        f'<style>@font-face{{font-family:"RM";src:url(data:font/woff2;base64,{FONT_B64})'
        f' format("woff2");}}'
        f'text{{font-family:"RM","Liberation Mono",monospace;font-size:{FONT_SIZE}px;}}'
        f'.fg{{fill:{FG}}} .dim{{fill:{DIM}}} .accent{{fill:{ACCENT}}}</style>'
        f'<rect width="100%" height="100%" fill="{BG}"/>'
    )


FONT_B64 = ""  # populated in main() from the basic latin subset


def build_hero_svg(total, weekly_counts):
    w, h = 460, 160
    svg = [svg_shell(w, h, f"{total} contributions in the last year")]
    svg.append(f'<text x="20" y="40" class="fg" font-size="22">{total}</text>')
    svg.append(f'<text x="20" y="60" class="dim">contributions, last 365 days</text>')

    # weekly sparkline as columns (discrete, not a line -- see note in guide)
    max_v = max(weekly_counts) if weekly_counts and max(weekly_counts) > 0 else 1
    n = len(weekly_counts)
    plot_x, plot_y, plot_w, plot_h = 20, 90, w - 40, 55
    bw = plot_w / max(n, 1)
    for i, v in enumerate(weekly_counts):
        bh = (v / max_v) * plot_h
        x = plot_x + i * bw
        y = plot_y + plot_h - bh
        svg.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(bw-1,1):.1f}" '
            f'height="{max(bh,1):.1f}" class="accent" opacity="0.85"/>'
        )
    svg.append("</svg>")
    return "\n".join(svg)


def build_streak_svg(streaks):
    w, h = 460, 140
    svg = [svg_shell(w, h, "contribution streaks")]

    def fmt_range(r):
        if not r:
            return "--"
        a, b = r
        return f"{a} to {b}"

    svg.append(f'<text x="20" y="35" class="fg" font-size="18">current streak: {streaks["current"]} days</text>')
    svg.append(f'<text x="20" y="55" class="dim">{fmt_range(streaks["current_range"])}</text>')
    svg.append(f'<text x="20" y="90" class="fg" font-size="18">longest streak: {streaks["longest"]} days</text>')
    svg.append(f'<text x="20" y="110" class="dim">{fmt_range(streaks["longest_range"])}</text>')
    svg.append("</svg>")
    return "\n".join(svg)


def build_langs_svg(lang_bytes):
    w, h = 460, 200
    total = sum(lang_bytes.values()) or 1
    top = sorted(lang_bytes.items(), key=lambda kv: kv[1], reverse=True)[:6]
    svg = [svg_shell(w, h, "top languages by bytes")]
    svg.append(f'<text x="20" y="28" class="dim">top languages, by bytes</text>')
    y = 55
    bar_x = 130
    bar_w = w - bar_x - 50  # leave room for the pct label on the right
    for name, size in top:
        pct = size / total * 100
        bw = bar_w * (size / total)
        svg.append(f'<text x="20" y="{y}" class="fg">{esc(name)[:12]}</text>')
        svg.append(f'<rect x="{bar_x}" y="{y-10}" width="{bar_w:.1f}" height="10" fill="#21262d"/>')
        svg.append(f'<rect x="{bar_x}" y="{y-10}" width="{bw:.1f}" height="10" class="accent"/>')
        svg.append(
            f'<text x="{bar_x+bar_w+10}" y="{y}" class="dim" font-size="11">{pct:.1f}%</text>'
        )
        y += 26
    svg.append("</svg>")
    return "\n".join(svg)


def build_year_svg(days):
    """One character per day, using the portrait's own ramp."""
    cell = CHAR_W
    cols_per_row = 53  # ~53 weeks
    w = cols_per_row * cell + 20
    rows_n = 7
    h = rows_n * cell * 2 + 40
    svg = [svg_shell(w, h, "contributions, one character per day")]

    counts = [c for _, c in days]
    max_c = max(counts) if counts and max(counts) > 0 else 1

    # arrange into weeks (columns) x weekday (rows), matching calendar layout
    by_week = []
    week = []
    for date, count in days:
        week.append((date, count))
        if len(week) == 7:
            by_week.append(week)
            week = []
    if week:
        by_week.append(week)

    for wi, week in enumerate(by_week):
        for di, (date, count) in enumerate(week):
            idx = int((count / max_c) * (len(RAMP) - 1)) if max_c else 0
            ch = RAMP[min(idx, len(RAMP) - 1)]
            x = 15 + wi * cell
            y = 30 + di * cell * 2
            svg.append(f'<text x="{x:.1f}" y="{y:.1f}" class="fg">{esc(ch)}</text>')
    svg.append("</svg>")
    return "\n".join(svg)


def main():
    token = os.environ.get("GITHUB_TOKEN")
    login = os.environ.get("GH_LOGIN")
    font_path = os.environ.get("FONT_WOFF2", "assets/fonts/basic.woff2")
    if not token or not login:
        sys.stderr.write("GITHUB_TOKEN and GH_LOGIN must be set\n")
        sys.exit(1)

    global FONT_B64
    import base64
    with open(font_path, "rb") as f:
        FONT_B64 = base64.b64encode(f.read()).decode("ascii")

    user = fetch(login, token)
    cal = user["contributionsCollection"]["contributionCalendar"]
    total = cal["totalContributions"]

    days = []
    for week in cal["weeks"]:
        for d in week["contributionDays"]:
            days.append((d["date"], d["contributionCount"]))

    weekly_counts = [sum(c for _, c in week["contributionDays"]) for week in cal["weeks"]]

    lang_bytes = {}
    for repo in user["repositories"]["nodes"]:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            lang_bytes[name] = lang_bytes.get(name, 0) + edge["size"]

    streaks = compute_streaks(days)

    os.makedirs("assets/stats", exist_ok=True)
    with open("assets/stats/hero.svg", "w") as f:
        f.write(build_hero_svg(total, weekly_counts))
    with open("assets/stats/streak.svg", "w") as f:
        f.write(build_streak_svg(streaks))
    with open("assets/stats/langs.svg", "w") as f:
        f.write(build_langs_svg(lang_bytes))
    with open("assets/stats/year.svg", "w") as f:
        f.write(build_year_svg(days))

    print(f"wrote stats for {login}: {total} contributions, "
          f"streak current={streaks['current']} longest={streaks['longest']}")


if __name__ == "__main__":
    main()
