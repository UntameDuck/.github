#!/usr/bin/env python3
"""Generate static API snapshots for the clickable UntameDuck activity dashboard.
Daily totals come from GitHub organization-scoped GraphQL, per-date event
links from public default-branch commits and newly opened PRs.
"""
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import json
import os
import re

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "profile/assets/org-contributions.svg"
README = ROOT / "profile/README.md"
DEST = ROOT / "docs/activity-data.json"
API = "https://api.github.com"
ORG = "UntameDuck"
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()

def api_get(path):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "UntameDuck-Pond-Activity",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    try:
        with urlopen(Request(API + path, headers=headers), timeout=40) as response:
            return json.load(response)
    except HTTPError as e:
        if e.code == 409:
            return []
        raise RuntimeError("GitHub API failed with %s on %s" % (e.code, path)) from e

def paginate(path):
    for page in range(1,100):
        join = "&" if "?" in path else "?"
        rows = api_get("%s%sper_page=100&page=%d" % (path,join,page))
        if not isinstance(rows,list):
            raise RuntimeError("Expected GitHub array at " + path)
        yield from rows
        if len(rows)<100:
            return
    raise RuntimeError("Unexpected pagination volume: " + path)

def public_events(since_date):
    events=defaultdict(list)
    repository_count=0
    for repo in paginate("/orgs/%s/repos?type=public" % ORG):
        if repo.get("fork") or repo["name"]==".github" or not repo.get("default_branch"):
            continue
        name=repo["name"]
        repository_count+=1
        suffix="/repos/%s/%s" % (ORG,quote(name,safe=""))
        branch=quote(repo["default_branch"],safe="")
        path="%s/commits?sha=%s&since=%sT00:00:00Z" % (suffix,branch,since_date)
        for row in paginate(path):
            c=row.get("commit") or {}
            who=c.get("author") or {}
            day=(who.get("date") or (c.get("committer") or {}).get("date") or "")[:10]
            if day<since_date:
                continue
            url=row.get("html_url") or ""
            if not url.startswith("https://github.com/%s/" % ORG):
                continue
            events[day].append({
                "type":"commit",
                "repo":name,
                "author":(row.get("author") or {}).get("login") or who.get("name") or "Unknown",
                "title":(c.get("message") or "Commit").splitlines()[0][:180],
                "url":url
            })
        for row in paginate("%s/pulls?state=all&sort=created&direction=desc" % suffix):
            day=(row.get("created_at") or "")[:10]
            if day<since_date:
                break
            url=row.get("html_url") or ""
            if not url.startswith("https://github.com/%s/" % ORG):
                continue
            events[day].append({
                "type":"pull_request",
                "repo":name,
                "author":(row.get("user") or {}).get("login") or "Unknown",
                "title":(row.get("title") or "Pull request")[:180],
                "url":url
            })
        print("Collected %s activity" % name,flush=True)
    return events,repository_count

def contributors_table():
    md=README.read_text(encoding="utf-8")
    if "<!-- CONTRIBUTORS:START -->" not in md:
        raise RuntimeError("README contribution markers missing")
    section=md.split("<!-- CONTRIBUTORS:START -->",1)[1].split("<!-- CONTRIBUTORS:END -->",1)[0]
    pairs=re.findall(r"\| \[@([^]]+)\]\(https://github.com/[^)]+\) \| ([0-9,]+) \| ([0-9,]+) \|",section)
    return [{"login":p[0],"commits":int(p[1].replace(",","")),"repositories":int(p[2].replace(",",""))} for p in pairs]

def streaks(days):
    counts=[v["count"] for v in days]
    current=0
    recent=counts[:-1] if counts and counts[-1]==0 else counts
    for n in reversed(recent):
        if n==0:break
        current+=1
    longest=0
    run=0
    for n in counts:
        run=run+1 if n>0 else 0
        longest=max(longest,run)
    return current,longest

def main():
    if not TOKEN:
        raise RuntimeError("GITHUB_TOKEN required for a trustworthy snapshot.")
    svg=SRC.read_text(encoding="utf-8")
    matches=re.findall(r"<title>(\d{4}-\d{2}-\d{2}): (\d+) contributions</title>",svg)
    if len(matches)<360:
        raise RuntimeError("Live heatmap not available yet: %d dated cells" % len(matches))
    days=sorted([{"date":day,"count":int(n)} for day,n in matches],key=lambda row:row["date"])
    since=days[0]["date"]
    end=days[-1]["date"]
    current,longest=streaks(days)
    events,repos=public_events(since)
    for day in events:
        events[day].sort(key=lambda e:(e["type"],e["repo"].lower(),e["title"].lower()))
    data={
        "organization":ORG,
        "generated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "period":{"from":since,"to":end,"days":len(days)},
        "summary":{
            "total_contributions":sum(v["count"] for v in days),
            "current_streak":current,
            "longest_streak":longest,
            "public_repositories_checked":repos,
            "available_detail_events":sum(map(len,events.values()))
        },
        "note":"Daily totals are GitHub organization-filtered contributions of discoverable public commit authors. Linked details include public default-branch commits and opened PRs only; counts can differ.",
        "days":days,
        "events":events,
        "contributors":contributors_table()
    }
    DEST.parent.mkdir(parents=True,exist_ok=True)
    DEST.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Wrote %d days, %d linked events, %d contributors" %
          (len(days),data["summary"]["available_detail_events"],len(data["contributors"])),flush=True)

if __name__=="__main__":
    main()
