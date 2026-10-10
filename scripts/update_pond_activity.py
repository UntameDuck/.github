#!/usr/bin/env python3
"""Update UntameDuck's public GitHub author leaderboard and organization-scoped
contribution calendar. Standard library only; no fabricated fallback values."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape
import json
import os

ORG = "UntameDuck"
README = Path("profile/README.md")
ASSETS = Path("profile/assets")
BEGIN, END = "<!-- CONTRIBUTORS:START -->", "<!-- CONTRIBUTORS:END -->"
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
API = "https://api.github.com"
COLORS = ["#DDEBFB", "#9ED7FA", "#6EC2F7", "#3EAFF4", "#0F99F2", "#0D8BD8"]

def request(path, data=None, allow_empty=False):
    url = path if path.startswith("http") else API + path
    headers = {"Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "UntameDuck-Pond-Activity"}
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    body = json.dumps(data).encode("utf-8") if data is not None else None
    if body:
        headers["Content-Type"] = "application/json"
    try:
        with urlopen(Request(url, data=body, headers=headers), timeout=40) as response:
            return json.load(response)
    except HTTPError as exc:
        if allow_empty and exc.code in (404, 409):
            return []
        raise RuntimeError("GitHub API request failed (%s): %s" % (exc.code, url)) from exc
    except URLError as exc:
        raise RuntimeError("Could not reach GitHub API: %s" % url) from exc

def paginate(path, allow_empty=False):
    index = 1
    while True:
        rows = request(path + ("&" if "?" in path else "?")
                       + "per_page=100&page=" + str(index), allow_empty=allow_empty)
        if not isinstance(rows, list):
            raise RuntimeError("Unexpected GitHub API response for " + path)
        yield from rows
        if len(rows) < 100:
            return
        index += 1

def graphql(query, variables):
    result = request("/graphql", {"query": query, "variables": variables})
    if result.get("errors"):
        raise RuntimeError("GraphQL error: " + json.dumps(result["errors"])[:800])
    return result["data"]

def authors_and_commits():
    totals = Counter()
    by_repo = defaultdict(set)
    repos_checked = 0
    for repo in paginate("/orgs/%s/repos?type=public" % ORG):
        if repo.get("fork") or repo["name"] == ".github":
            continue
        name = repo["name"]
        branch = quote(repo["default_branch"], safe="")
        path = "/repos/%s/%s/commits?sha=%s" % (ORG, quote(name, safe=""), branch)
        any_commits = False
        for item in paginate(path, allow_empty=True):
            any_commits = True
            author = item.get("author") or {}
            login = author.get("login")
            if not login or author.get("type") == "Bot" or login.endswith("[bot]"):
                continue
            totals[login] += 1
            by_repo[login].add(name)
        repos_checked += int(any_commits)
    return totals, by_repo, repos_checked

def text(x, y, value, size=14, color="#597BA2", weight="400", anchor="start"):
    return ('<text x="%s" y="%s" fill="%s" text-anchor="%s" '
            'font-family="Arial,Helvetica,sans-serif" font-size="%s" '
            'font-weight="%s">%s</text>' % (x, y, color, anchor, size, weight, escape(str(value))))

def contributor_svg(totals, today):
    pairs = sorted(totals.items(), key=lambda it: (-it[1], it[0].casefold()))[:10]
    h = 180 + 56 * len(pairs)
    biggest = max([n for _, n in pairs], default=1)
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="%s" viewBox="0 0 1200 %s" role="img">' % (h,h),
        '<title>People in the Pond — GitHub contributors</title>',
        '<defs><linearGradient id="lagoon"><stop stop-color="#0D8BD8"/><stop offset=".5" stop-color="#3EAFF4"/><stop offset="1" stop-color="#9ED7FA"/></linearGradient></defs>',
        '<rect x="1" y="1" width="1198" height="%s" rx="27" fill="#F2F8FF" stroke="#D2E7FA" stroke-width="2"/>' % (h-2),
        '<rect x="32" y="29" width="6" height="48" rx="3" fill="#0D8BD8"/>',
        text(53,55,"PEOPLE IN THE POND",27,"#173D76","750"),
        text(53,80,"GitHub-linked commit authors · public default branches"),
        text(1157,54,"UPDATED %s UTC" % today,12,"#4879AD","700","end"),
        text(54,131,"GITHUB ACCOUNT",12,"#668AAF","750"),
        text(1150,131,"COMMITS",12,"#668AAF","750","end")
    ]
    for index, (login, count) in enumerate(pairs):
        y = 145 + 56 * index
        if index % 2 == 0:
            parts.append('<rect x="31" y="%s" width="1138" height="51" rx="10" fill="#E6F2FF"/>' % y)
        parts.extend([
            text(49,y+33,str(index+1).zfill(2),14,"#7B9AB7","600"),
            text(91,y+34,"@" + login,18,"#163E76","700"),
            '<rect x="395" y="%s" width="650" height="20" rx="10" fill="#CBDFF4"/>' % (y+18),
            '<rect x="395" y="%s" width="%.1f" height="20" rx="10" fill="url(#lagoon)"/>' % (y+18,max(5,650*count/biggest)),
            text(1148,y+34,format(count, ","),18,"#173D76","800","end")
        ])
    parts.append(text(40,h-19,"Commit counts do not represent organization membership or contribution-calendar totals.",12))
    parts.append("</svg>")
    return "\n".join(parts) + "\n"

def contribution_calendar(logins, start, end):
    org_data = graphql("query($login:String!){organization(login:$login){id}}", {"login": ORG})
    org = org_data.get("organization")
    if not org:
        raise RuntimeError("Organization not found on GitHub GraphQL")
    query = """query($login:String!, $org:ID!, $from:DateTime!, $to:DateTime!) {
       user(login:$login) {
         contributionsCollection(organizationID:$org, from:$from, to:$to) {
           contributionCalendar { weeks { contributionDays { date contributionCount } } }
         }
       }
    }"""
    counts = Counter()
    processed = 0
    failures = []
    for login in sorted(logins):
        try:
            data = graphql(query, {
                "login": login, "org": org["id"],
                "from": start.isoformat() + "T00:00:00Z",
                "to": (end + timedelta(days=1)).isoformat() + "T00:00:00Z"
            })
            if not data.get("user"):
                failures.append(login)
                continue
            weeks = data["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
            for week in weeks:
                for row in week["contributionDays"]:
                    day = datetime.strptime(row["date"], "%Y-%m-%d").date()
                    if start <= day <= end:
                        counts[day] += row["contributionCount"]
            processed += 1
        except Exception as exc:
            print("Contributor calendar unavailable for %s: %s" % (login,exc),flush=True)
            failures.append(login)
    if processed == 0:
        raise RuntimeError("No organization-filtered contribution calendars could be retrieved.")
    if failures:
        print("Partial coverage: %s of %s author calendars available" % (processed, len(logins)))
    return counts, processed, len(logins)

def streak_stats(counts, start, end):
    day = end if counts[end] else end-timedelta(days=1)
    current = 0
    while day >= start and counts[day]:
        current += 1
        day -= timedelta(days=1)
    longest = running = 0
    for delta in range((end-start).days + 1):
        day = start+timedelta(days=delta)
        running = running+1 if counts[day] else 0
        longest = max(longest, running)
    return current, longest

def activity_svg(counts, start, end, fetched, discovered):
    current, longest = streak_stats(counts, start, end)
    total = sum(counts.values())
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="430" viewBox="0 0 1200 430" role="img">',
        '<title>UntameDuck Pond Activity over the past 365 days</title>',
        '<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#F7FBFF"/><stop offset="1" stop-color="#E6F3FF"/></linearGradient><linearGradient id="stripe"><stop stop-color="#0D8BD8"/><stop offset=".5" stop-color="#3EAFF4"/><stop offset="1" stop-color="#9ED7FA"/></linearGradient></defs>',
        '<rect x="1" y="1" width="1198" height="428" rx="28" fill="url(#bg)" stroke="#C9E4FC" stroke-width="2"/>',
        '<rect x="32" y="34" width="6" height="50" rx="3" fill="#0D8BD8"/>',
        text(56,57,"POND ACTIVITY",29,"#153A70","800"),
        text(56,83,"Every contribution makes a ripple.",16),
        text(1157,58,"LAST 365 DAYS",13,"#176BA7","700","end")]
    metrics = [("TOTAL CONTRIBUTIONS",format(total,",")),
               ("CURRENT STREAK","%s days" % current),
               ("LONGEST STREAK","%s days" % longest)]
    for index,(label,value) in enumerate(metrics):
        x = 30+index*389
        parts.extend([
            '<rect x="%s" y="108" width="357" height="101" rx="20" fill="#FFFFFF" stroke="#D6E9FA"/>' % x,
            '<rect x="%s" y="108" width="357" height="5" rx="3" fill="url(#stripe)"/>' % x,
            text(x+18,144,label,13,"#5C80A8","700"),
            text(x+18,187,value,31,"#1A4E8C","800")])
    parts.append(text(32,244,"CONTRIBUTION HEATMAP",16,"#174277","750"))
    first_week = start - timedelta(days=(start.weekday()+1)%7)
    week_count = (end-first_week).days//7+1
    last_month = None
    for week in range(week_count):
        week_start = first_week + timedelta(days=week*7)
        month = (week_start.year,week_start.month)
        if month != last_month and week_start <= end:
            parts.append(text(round(86+week*19.65,1),261,week_start.strftime("%b"),11,"#668AAF"))
            last_month = month
        for index in range(7):
            day = week_start+timedelta(days=index)
            if not (start <= day <= end):
                continue
            n = counts[day]
            level = 0 if n == 0 else 1 if n <= 2 else 2 if n <= 5 else 3 if n <= 10 else 4 if n <= 18 else 5
            x,y=86+week*19.65,266+index*17.6
            parts.append('<rect x="%.1f" y="%.1f" width="13.8" height="13.8" rx="4" fill="%s"><title>%s: %s contributions</title></rect>' % (x,y,COLORS[level],day,n))
    for index,label in [(1,"Mon"),(3,"Wed"),(5,"Fri")]:
        parts.append(text(38,int(266+index*17.6+11),label,12,"#6B8FB1"))
    parts.append(text(32,417,"%s / %s public-author calendars queried · Updated %s UTC" % (fetched,discovered,end),12,"#668AAF"))
    parts.append(text(975,416,"Less",12))
    for i,color in enumerate(COLORS):
        parts.append('<rect x="%s" y="403" width="14" height="14" rx="4" fill="%s"/>' % (1015+21*i,color))
    parts.append(text(1180,416,"More",12,anchor="end"))
    parts.append("</svg>")
    return "\n".join(parts)+"\n"

def pond_html(counts, start, end):
    """A real 365-day heatmap in README-native HTML, without images or CSS."""
    from calendar import month_abbr
    first_sunday = start - timedelta(days=(start.weekday() + 1) % 7)
    sundays = []
    week = first_sunday
    while week <= end:
        sundays.append(week)
        week += timedelta(days=7)
    symbols = ("⬜", "💠", "🔹", "🔷", "🟦", "🔵")
    def level(n):
        return 0 if n == 0 else 1 if n <= 2 else 2 if n <= 5 else 3 if n <= 10 else 4 if n <= 18 else 5
    current, longest = streak_stats(counts, start, end)
    out = [
        "**%s contributions** · **%s-day current streak** · **%s-day longest streak** · **Last updated %s (UTC)**" %
        (format(sum(counts.values()), ","), current, longest, end.isoformat()),
        "",
        "<table>"
    ]
    headings = ["<tr><th>Day</th>"]
    previous_month = None
    for sunday in sundays:
        month = sunday.month
        title = month_abbr[month] if month != previous_month else ""
        headings.append("<th>%s</th>" % title)
        previous_month = month
    headings.append("</tr>")
    out.append("".join(headings))
    for weekday, day_name in enumerate(("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")):
        cells = ["<tr><th>%s</th>" % day_name]
        for sunday in sundays:
            date = sunday + timedelta(days=weekday)
            if date < start or date > end:
                cells.append("<td></td>")
                continue
            n = counts[date]
            caption = "%s: %s contribution%s" % (date, n, "" if n == 1 else "s")
            cells.append('<td title="%s">%s</td>' % (caption, symbols[level(n)]))
        cells.append("</tr>")
        out.append("".join(cells))
    out.extend([
        "</table>",
        "",
        "**Activity levels:** ⬜ None · 💠 1–2 · 🔹 3–5 · 🔷 6–10 · 🟦 11–18 · 🔵 19+",
        ""
    ])
    return "\n".join(out)

def main():
    if not TOKEN:
        raise RuntimeError("A GITHUB_TOKEN is required to fetch real contribution data.")
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=364)
    totals, repo_sets, repo_count = authors_and_commits()
    if not totals:
        raise RuntimeError("No linked authors discovered; refusing to replace snapshot with empty stats")
    daily, fetched, discovered = contribution_calendar(totals.keys(), start, today)
    date_str = today.isoformat()
    ranked = sorted(totals.items(), key=lambda item: (-item[1],item[0].casefold()))
    table = [
        "**Updated %s (UTC)** · **%s linked-author commits · %s author accounts · %s repositories with commits**" %
        (date_str,format(sum(totals.values()),","),len(totals),repo_count),
        "",
        "| GitHub Account | Default-Branch Commits | Repositories |",
        "| :--- | ---: | ---: |"
    ]
    for login,n in ranked:
        table.append("| [@%s](https://github.com/%s) | %s | %s |" %
                     (login,quote(login,safe=""),format(n,","),len(repo_sets[login])))
    content = README.read_text(encoding="utf-8")
    if content.count(BEGIN)!=1 or content.count(END)!=1:
        raise RuntimeError("README requires one CONTRIBUTORS:START and CONTRIBUTORS:END marker")
    head,tail=content.split(BEGIN,1)
    _,foot=tail.split(END,1)
    updated_readme = head + BEGIN + "\n" + "\n".join(table) + "\n\n" + END + foot
    pond_begin, pond_end = "<!-- POND-GRASS:START -->", "<!-- POND-GRASS:END -->"
    if updated_readme.count(pond_begin) != 1 or updated_readme.count(pond_end) != 1:
        raise RuntimeError("README requires one POND-GRASS start and end marker")
    pond_head, pond_tail = updated_readme.split(pond_begin, 1)
    _, pond_foot = pond_tail.split(pond_end, 1)
    updated_readme = pond_head + pond_begin + "\n" + pond_html(daily, start, today) + "\n" + pond_end + pond_foot
    README.write_text(updated_readme, encoding="utf-8")
    ASSETS.mkdir(parents=True,exist_ok=True)
    (ASSETS/"pond-contributors.svg").write_text(contributor_svg(totals,date_str),encoding="utf-8")
    (ASSETS/"org-contributions.svg").write_text(activity_svg(daily,start,today,fetched,discovered),encoding="utf-8")
    print("Updated %s commit authors and %s organization-filtered calendars." % (len(totals),fetched))

if __name__ == "__main__":
    main()
