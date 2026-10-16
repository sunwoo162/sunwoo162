#!/usr/bin/env python3
"""Public GitHub activity index. KST date windows, explicit coverage, no secrets in output."""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = pathlib.Path(__file__).resolve().parents[1]
USER = "sunwoo162"
SITE = "https://sunwoo162.github.io/sunwoo162/"
KST = dt.timezone(dt.timedelta(hours=9))
TODAY = dt.datetime.now(KST).date()
TOKEN = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
API = "https://api.github.com"

def timestamp(iso):
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(KST)

def api(path, params=None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "sunwoo162-activity"}
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    for attempt in range(4):
        try:
            time.sleep(2.1 if path.startswith("/search/") else 0.15)
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=35) as res:
                return json.load(res)
        except urllib.error.HTTPError as exc:
            if exc.code not in (403, 429, 502, 503) or attempt == 3:
                raise
            pause = exc.headers.get("Retry-After")
            time.sleep(min(90, int(pause) if pause and pause.isdigit() else 20 * (attempt + 1)))

def search(query, endpoint):
    """Return (items, coverage). Never silently truncate >1000 GitHub Search matches."""
    collected = []
    total = 0
    incomplete = False
    for page in range(1, 11):
        result = api("/search/" + endpoint, {"q": query, "per_page": 100, "page": page})
        total = result.get("total_count", 0)
        incomplete = incomplete or result.get("incomplete_results", False)
        part = result.get("items", [])
        collected.extend(part)
        if len(part) < 100:
            break
    return collected, {"total": total, "limited": incomplete or total > 1000 or len(collected) < min(total, 1000)}

def utc_days_for_kst(day):
    # A KST day spans 15:00 UTC on the prior date through 14:59 UTC on this date.
    return (day - dt.timedelta(days=1)).isoformat() + ".." + day.isoformat()

def visible_repo(name, memo, hint=None):
    if not name:
        return False
    if hint is True:
        return False
    if hint is False:
        return True
    if name not in memo:
        try:
            memo[name] = api("/repos/" + name).get("private") is False
        except urllib.error.HTTPError as e:
            if e.code == 404:
                memo[name] = False
            else:
                raise
    return memo[name]

def entry(kind, event, when, title, repo, url, **extra):
    moment = timestamp(when)
    return {"kind": kind, "event": event, "date": moment.date().isoformat(),
            "time": moment.strftime("%H:%M"), "at": moment.isoformat(),
            "title": title, "repo": repo, "url": url, **extra}

def day_records(day):
    span = utc_days_for_kst(day)
    memo = {}
    results = []
    limitations = []
    def run(query, typ, description):
        records, coverage = search(query, typ)
        if coverage["limited"]:
            limitations.append(description + " (검색 결과 제한/불완전)")
        return records

    for obj in run("author:" + USER + " committer-date:" + span, "commits", "커밋"):
        repo_obj = obj.get("repository") or {}
        repo = repo_obj.get("full_name", "")
        if not visible_repo(repo, memo, repo_obj.get("private")):
            continue
        c = obj.get("commit") or {}
        when = (c.get("committer") or {}).get("date") or (c.get("author") or {}).get("date")
        if not when or timestamp(when).date() != day:
            continue
        sha = obj.get("sha", "")
        results.append(entry("commit", "committed", when,
            (c.get("message") or sha).splitlines()[0], repo,
            obj.get("html_url") or "https://github.com/" + repo + "/commit/" + sha,
            sha=sha[:12], source="commit-search"))

    # PR creation and merging are separate *events*. Same PR opened and merged
    # on one date is one row with both actions, while activity on different days
    # appears on both relevant dates.
    for event, selector in (("opened", "created:"), ("merged", "merged:"), ("closed", "closed:")):
        query = "type:pr author:" + USER + " " + selector + span
        for obj in run(query, "issues", "PR " + event):
            if "pull_request" not in obj:
                continue
            repo = (obj.get("repository_url") or "").split("/repos/")[-1]
            if not visible_repo(repo, memo):
                continue
            pull = obj["pull_request"]
            if event == "closed" and pull.get("merged_at"):
                continue
            when = (obj.get("created_at") if event == "opened" else
                    pull.get("merged_at") if event == "merged" else obj.get("closed_at"))
            if not when or timestamp(when).date() != day:
                continue
            number = obj.get("number")
            results.append(entry("pr", event, when, obj.get("title", ""), repo,
                obj.get("html_url", ""), number=number,
                status=("merged" if pull.get("merged_at") else obj.get("state", "open")),
                commits_url="https://github.com/" + repo + "/pull/" + str(number) + "/commits"))

    for obj in run("type:issue author:" + USER + " created:" + span, "issues", "Issue 생성"):
        repo = (obj.get("repository_url") or "").split("/repos/")[-1]
        if not visible_repo(repo, memo):
            continue
        when = obj.get("created_at")
        if when and timestamp(when).date() == day:
            results.append(entry("issue", "opened", when, obj.get("title", ""), repo, obj.get("html_url", "")))

    # Group duplicate PR events from the same date to avoid repeated cards.
    grouped = {}
    for item in results:
        key = (item["kind"], item["url"])
        if key not in grouped:
            copy = dict(item)
            if copy["kind"] == "pr":
                copy["events"] = [copy["event"]]
            grouped[key] = copy
        else:
            previous = grouped[key]
            if item["kind"] == "pr":
                previous.setdefault("events", [previous["event"]])
                if item["event"] not in previous["events"]:
                    previous["events"].append(item["event"])
            if item["at"] > previous["at"]:
                actions = previous.get("events", [])
                grouped[key] = dict(item)
                if item["kind"] == "pr":
                    grouped[key]["events"] = actions

    records = sorted(grouped.values(), key=lambda x: x["at"], reverse=True)
    state = "limited" if limitations else "indexed"
    return records, {"state": state,
                     "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                     "sources": ["github-commit-search", "github-issue-search"],
                     "notes": limitations,
                     "commit_scope": "GitHub commit-search index (not all unmerged branches)"}

def scan_owned_branches(first, last):
    """Best-effort branch coverage for recent days in public owned repositories.

    GitHub commit search can omit commits on feature branches. The repository
    commits endpoint covers the selected branch ref, so scan recent public
    branches and deduplicate by repository + SHA. Bounded scans report limits.
    """
    begin = dt.datetime.combine(first, dt.time.min, tzinfo=KST).astimezone(dt.timezone.utc).isoformat()
    until = dt.datetime.combine(last + dt.timedelta(days=1), dt.time.min, tzinfo=KST).astimezone(dt.timezone.utc).isoformat()
    repos = api("/users/" + USER + "/repos", {"type": "owner", "sort": "pushed", "per_page": 100, "page": 1})
    records = []
    notes = []
    for r in repos:
        if r.get("private"):
            continue
        pushed = r.get("pushed_at")
        if not pushed or timestamp(pushed).date() < first:
            continue
        name = r["full_name"]
        try:
            branches = api("/repos/" + name + "/branches", {"per_page": 100, "page": 1})
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 409):
                continue
            notes.append(name + " 브랜치 조회 실패")
            continue
        if len(branches) > 20:
            notes.append(name + " 브랜치가 20개를 넘어 일부만 조회")
        if len(branches) == 100:
            notes.append(name + " 브랜치 목록 제한 도달")
        for branch in branches[:20]:
            for page in (1, 2, 3):
                try:
                    rows = api("/repos/" + name + "/commits", {
                        "sha": branch["name"], "author": USER,
                        "since": begin, "until": until, "per_page": 100, "page": page})
                except urllib.error.HTTPError as exc:
                    if exc.code in (404, 409):
                        break
                    notes.append(name + " 커밋 조회 실패")
                    break
                for obj in rows:
                    commit = obj.get("commit") or {}
                    when = (commit.get("committer") or {}).get("date") or (commit.get("author") or {}).get("date")
                    if not when or not first <= timestamp(when).date() <= last:
                        continue
                    sha = obj.get("sha", "")
                    records.append(entry("commit", "committed", when,
                        (commit.get("message") or sha).splitlines()[0], name,
                        obj.get("html_url") or "https://github.com/" + name + "/commit/" + sha,
                        sha=sha[:12], source="branch-scan"))
                if len(rows) < 100:
                    break
                if page == 3:
                    notes.append(name + " 브랜치 커밋 조회 300건 상한")
    if len(repos) == 100:
        notes.append("공개 저장소 목록 100건 상한")
    return records, list(dict.fromkeys(notes))

def archive_table(items):
    lines = ["| 시간(KST) | 종류 | 작업 | 저장소 |",
             "|:--:|:--|:--|:--|"]
    for x in items:
        label = {"commit": "Commit", "pr": "PR", "issue": "Issue"}.get(x["kind"], x["kind"])
        title = x.get("title", "").replace("|", "/").replace("\n", " ")
        if x["kind"] == "pr":
            title += " (" + "/".join(x.get("events", [x.get("event", "")])) + ")"
        lines.append("| " + x["time"] + " | " + label + " | [" + title + "](" + x["url"] + ") | " + x["repo"] + " |")
    if not items:
        lines.append("| — | — | 기록 없음 | — |")
    return "\n".join(lines)

def readme(data, coverage):
    key = TODAY.isoformat()
    items = data.get(key, [])
    commits = sum(x["kind"] == "commit" for x in items)
    prs = sum(x["kind"] == "pr" for x in items)
    issues = sum(x["kind"] == "issue" for x in items)
    state = coverage.get(key, {}).get("state", "not_collected")
    header = "### Today · " + key
    if state not in ("indexed", "legacy"):
        header += " · " + {"limited": "일부 수집", "error": "조회 오류", "not_collected": "미수집"}.get(state, state)
    return "\n".join([header, "",
        "**" + str(commits) + " Commits** · **" + str(prs) + " PRs** · **" + str(issues) + " Issues**", "",
        archive_table(items), "",
        "[View all activity →](" + SITE + ")", ""])

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=3, help="KST days to reindex; pass 21 to backfill")
    args = p.parse_args()
    n = max(1, min(35, args.days))
    dest = BASE / "docs" / "activity.json"
    old = json.loads(dest.read_text(encoding="utf8")) if dest.exists() else {}
    data = old.get("days", {})
    meta = old.get("coverage", {})
    for key in data:
        meta.setdefault(key, {"state": "legacy", "notes": ["이전 수집 로직의 기록; 재검증 필요"]})
    first = TODAY - dt.timedelta(days=n - 1)
    for i in range(n):
        day = first + dt.timedelta(days=i)
        key = day.isoformat()
        try:
            records, status = day_records(day)
            data[key] = records
            meta[key] = status
            print(key, len(records), status["state"], flush=True)
        except (urllib.error.URLError, ValueError, KeyError) as exc:
            status = meta.get(key, {})
            meta[key] = {**status, "state": "error",
                         "notes": ["최근 검색 실패. 이전 기록은 참고용: " + str(exc)[:160]]}
            print(key, "failed:", str(exc)[:120], flush=True)
    # Index public feature-branch commits in addition to global commit search.
    # Wider historical backfills rely on searchable GitHub history to limit API use.
    if n <= 3 and os.getenv("ACTIVITY_BRANCH_SCAN", "1") == "1":
        try:
            branch_items, branch_notes = scan_owned_branches(first, TODAY)
            for item in branch_items:
                key = item["date"]
                if key not in data or meta.get(key, {}).get("state") == "error":
                    continue
                exists = {(x["kind"], x["url"]) for x in data[key]}
                if (item["kind"], item["url"]) not in exists:
                    data[key].append(item)
                    exists.add((item["kind"], item["url"]))
            for i in range(n):
                day = (first + dt.timedelta(days=i)).isoformat()
                if day in data and meta.get(day, {}).get("state") != "error":
                    data[day].sort(key=lambda x: x.get("at", x.get("time", "")), reverse=True)
                    meta[day]["branch_scan"] = "public owned repositories, max 20 branches each"
                    if branch_notes:
                        meta[day]["state"] = "limited"
                        meta[day].setdefault("notes", []).extend(branch_notes[:8])
            print("Branch scan:", len(branch_items), "candidate commits", flush=True)
        except (urllib.error.URLError, ValueError, KeyError) as exc:
            print("Branch scan failed:", str(exc)[:120], flush=True)
            for i in range(n):
                day = (first + dt.timedelta(days=i)).isoformat()
                if day in meta:
                    meta[day]["state"] = "limited"
                    meta[day].setdefault("notes", []).append("브랜치 추가 수집 실패")

    data = dict(sorted(data.items(), reverse=True))
    payload = {"user": USER, "timezone": "Asia/Seoul",
               "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
               "coverage": meta, "days": data}
    dest.parent.mkdir(exist_ok=True, parents=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    (BASE / "README.md").write_text(readme(data, meta), encoding="utf8")
    folder = BASE / "activity"
    folder.mkdir(exist_ok=True)
    for key, items in data.items():
        if key >= first.isoformat():
            (folder / (key + ".md")).write_text(
                "# " + key + " · Development Log\n\n[Activity](" + SITE + "?date=" + key + ")\n\n" +
                archive_table(items) + "\n", encoding="utf8")
if __name__ == "__main__":
    main()
