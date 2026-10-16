#!/usr/bin/env python3
"""Generate a GitHub profile activity log using only the Python standard library."""
import calendar, datetime as dt, json, os, pathlib, subprocess, time, urllib.error, urllib.parse, urllib.request
BASE=pathlib.Path(__file__).resolve().parents[1]
USER="sunwoo162"
TZ=dt.timezone(dt.timedelta(hours=9))
TODAY=dt.datetime.now(TZ).date()
SITE="https://sunwoo162.github.io/sunwoo162/"
TOKEN=os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
def api(path,query=None):
    url="https://api.github.com"+path
    if query:url+="?"+urllib.parse.urlencode(query)
    headers={"User-Agent":"profile-activity","Accept":"application/vnd.github+json"}
    if TOKEN:headers["Authorization"]="Bearer "+TOKEN
    for retry in range(5):
        try:
            time.sleep(1)
            with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=30) as f:return json.load(f)
        except urllib.error.HTTPError as e:
            if e.code not in (403,429) or retry==4:raise
            time.sleep(18*(retry+1))
def search(path,query):
    all=[]
    for page in range(1,11):
        rows=api(path,{"q":query,"per_page":100,"page":page}).get("items",[])
        all+=rows
        if len(rows)<100:break
    return all
def local(iso):return dt.datetime.fromisoformat(iso.replace("Z","+00:00")).astimezone(TZ)
def fetch(days):
    first=TODAY-dt.timedelta(days=days-1)
    since=(first-dt.timedelta(days=1)).isoformat()
    public_repos={}
    def public(repo):
        if not repo:return False
        if repo not in public_repos:
            try:public_repos[repo]=api("/repos/"+repo).get("private") is False
            except Exception:public_repos[repo]=False
        return public_repos[repo]
    output=[]
    for item in search("/search/commits","author:"+USER+" committer-date:>="+since):
        repo=item.get("repository") or {}
        name=repo.get("full_name","")
        if repo.get("private") is True:continue
        if repo.get("private") is not False and not public(name):continue
        commit=item.get("commit") or {}
        stamp=(commit.get("committer") or {}).get("date") or (commit.get("author") or {}).get("date")
        if not stamp or local(stamp).date()<first:continue
        sha=item.get("sha","")
        output.append({"kind":"commit","date":local(stamp).date().isoformat(),"time":local(stamp).strftime("%H:%M"),
          "title":(commit.get("message") or sha).splitlines()[0],"repo":name,
          "url":item.get("html_url") or "https://github.com/"+name+"/commit/"+sha})
    for kind in ("pr","issue"):
        query="author:"+USER+" type:"+("pr" if kind=="pr" else "issue")+" created:>="+since
        for item in search("/search/issues",query):
            repo=item.get("repository_url","").split("/repos/")[-1]
            if not public(repo):continue
            stamp=item.get("created_at")
            if not stamp or local(stamp).date()<first:continue
            output.append({"kind":kind,"date":local(stamp).date().isoformat(),"time":local(stamp).strftime("%H:%M"),
              "title":item.get("title",""),"repo":repo,"url":item.get("html_url","")})
    return first,output
def rows(items):
    out=["| 시간(KST) | 유형 | 작업 | 저장소 |","|:--:|:--|:--|:--|"]
    for x in items:
        title=x["title"].replace("|","/").replace("\n"," ")
        out.append("| "+x["time"]+" | "+x["kind"].upper()+" | ["+title+"]("+x["url"]+") | "+x["repo"]+" |")
    if not items:out.append("| — | — | 공개 활동 없음 | — |")
    return "\n".join(out)
def readme(data):
    items=data.get(TODAY.isoformat(),[])
    counts={k:sum(x["kind"]==k for x in items) for k in ("commit","pr","issue")}
    return "\n".join([
      "### Today · "+TODAY.isoformat(),"",
      "**"+str(counts["commit"])+" Commits** · **"+str(counts["pr"])+" PRs** · **"+str(counts["issue"])+" Issues**","",
      rows(items),"",
      "[View all activity →]("+SITE+")",""
    ])
def main():
    data_path=BASE/"docs"/"activity.json"
    old={}
    if data_path.exists():old=json.loads(data_path.read_text(encoding="utf8")).get("days",{})
    first,items=fetch(45 if not old else 21)
    days={day:items for day,items in old.items() if day<first.isoformat()}
    for x in items:days.setdefault(x["date"],[]).append(x)
    days={day:sorted({(x["kind"],x["url"]):x for x in items}.values(),key=lambda x:x["time"],reverse=True) for day,items in sorted(days.items(),reverse=True)}
    data_path.parent.mkdir(exist_ok=True,parents=True)
    data_path.write_text(json.dumps({"user":USER,"timezone":"Asia/Seoul","days":days},ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    (BASE/"README.md").write_text(readme(days),encoding="utf8")
    archive=BASE/"activity"
    archive.mkdir(exist_ok=True)
    for day,items in days.items():
        (archive/(day+".md")).write_text("# "+day+" · Development Log\n\n[← 날짜별 달력]("+SITE+"?date="+day+")\n\n"+rows(items)+"\n",encoding="utf8")
    print("Collected",sum(map(len,days.values())),"public activities")
if __name__=="__main__":main()
