#!/usr/bin/env python3
"""Generate two theme-aware SVG calendars from UntameDuck public repo commits."""
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, time as clock, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ORG = "UntameDuck"
KST = ZoneInfo("Asia/Seoul")
DEST = Path(__file__).resolve().parents[1] / "profile" / "assets"
COLORS = {
    "light": {
        "border": "#CBEAF3", "text": "#184E68",
        "muted": "#618FA5", "accent": "#279CC2",
        "levels": ["#E2F3F8", "#BBEAF5", "#88D8EC", "#50BEDD", "#279CC2"]
    },
    "dark": {
        "border": "#27495C", "text": "#DCF6FF",
        "muted": "#91B9CC", "accent": "#70D9F1",
        "levels": ["#19374A", "#235C76", "#2888AA", "#3DB9DA", "#78E0F2"]
    }
}

def get_json(path, params=None):
    url = "https://api.github.com" + path
    if params:
        url += "?" + urlencode(params)
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "untameduck-contribution-ocean"
    }
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    for attempt in range(4):
        try:
            with urlopen(Request(url, headers=headers), timeout=45) as response:
                data = response.read()
                return json.loads(data) if data else []
        except HTTPError as err:
            if err.code == 409:
                return []
            if err.code in (500, 502, 503, 504) and attempt < 3:
                time.sleep(3 * (attempt + 1))
                continue
            raise RuntimeError(f"GitHub API {err.code}: {url}") from err
        except (URLError, TimeoutError) as err:
            if attempt < 3:
                time.sleep(3 * (attempt + 1))
                continue
            raise RuntimeError(f"GitHub request failed: {url}") from err
    raise RuntimeError(f"GitHub request failed: {url}")

def pages(path, params=None):
    for page in range(1, 101):
        items = get_json(path, dict(params or {}, per_page=100, page=page))
        if not isinstance(items, list):
            raise RuntimeError(f"Invalid GitHub response: {path}")
        yield from items
        if len(items) < 100:
            return
    raise RuntimeError(f"Refusing to truncate API pages: {path}")

def bot(commit):
    for part in ("author", "committer"):
        user = commit.get(part) or {}
        login = (user.get("login") or "").lower()
        if user.get("type") == "Bot" or login.endswith("[bot]") or login == "github-actions":
            return True
    return False

def collect(start):
    start_utc = datetime.combine(start, clock.min, KST).astimezone(timezone.utc)
    since = start_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    totals = Counter()
    repos = sorted(pages(f"/orgs/{ORG}/repos", {"type": "public"}), key=lambda r: r["name"].lower())
    examined = 0
    for repo in repos:
        if (repo["name"] == ".github" or repo.get("fork") or repo.get("archived")
                or repo.get("disabled") or not repo.get("default_branch")
                or repo.get("size", 0) == 0):
            continue
        examined += 1
        path = f"/repos/{quote(ORG)}/{quote(repo['name'])}/commits"
        for item in pages(path, {"sha": repo["default_branch"], "since": since}):
            if bot(item):
                continue
            timestamp = ((item.get("commit") or {}).get("committer") or {}).get("date")
            if not timestamp:
                continue
            day = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(KST).date()
            if day >= start:
                totals[day] += 1
    return totals, examined

def streaks(totals, start, today):
    longest = running = 0
    for n in range((today - start).days + 1):
        day = start + timedelta(days=n)
        running = running + 1 if totals[day] else 0
        longest = max(longest, running)
    end = today if totals[today] else today - timedelta(days=1)
    current = 0
    while end >= start and totals[end]:
        current += 1
        end -= timedelta(days=1)
    return current, longest

def level(count):
    if not count:
        return 0
    if count == 1:
        return 1
    if count <= 3:
        return 2
    if count <= 6:
        return 3
    return 4

def render(totals, start, today, examined, theme):
    c = COLORS[theme]
    origin = start - timedelta(days=(start.weekday() + 1) % 7)
    if (today - origin).days // 7 + 1 > 54:
        raise RuntimeError("Calendar exceeds 54 weeks")
    current, longest = streaks(totals, start, today)
    total = sum(totals.values())
    face = "-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif"
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="285" viewBox="0 0 960 285" role="img" aria-labelledby="title description">',
        f'<title id="title">UntameDuck Contribution Ocean ({theme})</title>',
        f'<desc id="description">Last 365 days: {total} commits in {examined} organization repositories; current streak {current} days; longest streak {longest} days.</desc>',
        f'<text x="48" y="37" font-family="{face}" font-weight="700" font-size="19" fill="{c["text"]}">UntameDuck · Contribution Ocean</text>',
    ]
    for x, label, number, unit in (
        (48, "CURRENT STREAK", current, "days"),
        (350, "LONGEST STREAK · 365D", longest, "days"),
        (670, "COMMITS · 365D", total, "commits"),
    ):
        svg.append(f'<text x="{x}" y="82" font-family="{face}" font-size="11" letter-spacing="0.8" fill="{c["muted"]}">{label}</text>')
        svg.append(f'<text x="{x}" y="109" font-family="{face}" font-weight="700" font-size="25" fill="{c["accent"]}">{number} <tspan font-size="12" font-weight="400" fill="{c["muted"]}">{unit}</tspan></text>')
    svg.append(f'<path d="M48 121H912" stroke="{c["border"]}"/>')
    day = origin
    while day <= today:
        if day.day == 1 and day >= start:
            col = (day - origin).days // 7
            svg.append(f'<text x="{48+col*16}" y="136" font-family="{face}" font-size="10.5" fill="{c["muted"]}">{day.strftime("%b")}</text>')
        day += timedelta(days=1)
    for n in range((today - origin).days + 1):
        day = origin + timedelta(days=n)
        if day < start:
            continue
        count = totals[day]
        x, y = 48 + (n // 7) * 16, 142 + (n % 7) * 16
        shade = c["levels"][level(count)]
        plural = "s" if count != 1 else ""
        svg.append(f'<rect x="{x}" y="{y}" width="12" height="12" rx="2.5" fill="{shade}"><title>{day}: {count} commit{plural}</title></rect>')
    svg.append(f'<text x="48" y="272" font-family="{face}" font-size="10.5" fill="{c["muted"]}">Updated {today} · Asia/Seoul · {examined} repositories</text>')
    svg.append(f'<text x="784" y="272" font-family="{face}" font-size="10.5" fill="{c["muted"]}">Less</text>')
    for i, shade in enumerate(c["levels"]):
        svg.append(f'<rect x="{813+i*17}" y="262" width="12" height="12" rx="2.5" fill="{shade}"/>')
    svg.append(f'<text x="903" y="272" font-family="{face}" font-size="10.5" fill="{c["muted"]}">More</text>')
    return "\n".join(svg + ["</svg>", ""])

def main():
    today = datetime.now(KST).date()
    start = today - timedelta(days=364)
    totals, examined = collect(start)
    DEST.mkdir(parents=True, exist_ok=True)
    for theme in COLORS:
        path = DEST / f"contributions-{theme}.svg"
        svg = render(totals, start, today, examined, theme)
        if not path.exists() or path.read_text(encoding="utf-8") != svg:
            path.write_text(svg, encoding="utf-8")
    print(f"Generated both themes, {sum(totals.values())} commits across {examined} repositories.")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Contribution update failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
