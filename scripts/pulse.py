#!/usr/bin/env python3
"""
Daily Client Pulse — serverless pipeline (GitHub Actions).
Pulls Vista Social data via the Vista Social API, writes data.json +
monthly archive into the repo working tree, and updates the Notion
"Daily Client Pulse" dashboard.

Env:
  VISTA_API_KEY  (required)  Vista Social API key (Settings > Integrations)
  NOTION_TOKEN   (optional)  Notion internal-integration token; Notion step
                             is skipped with a warning when absent.

Vista endpoints (apidocs.vistasocial.com):
  GET /api/integration/groups                          -> [{id,name,type}]
  GET /api/integration/data/daily?date_from&date_to&group_id   (YYYYMMDD)
  GET /api/integration/data/posts?date_from&date_to&group_id   (YYYYMMDD)
"""
import json, os, re, sys, urllib.parse, urllib.request
from datetime import date, timedelta
from zoneinfo import ZoneInfo

VISTA_KEY = os.environ.get("VISTA_API_KEY", "")
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
VISTA_BASE = "https://vistasocial.com/api/integration"

NOTION_DS_ID = "2612e956-282d-4e43-be29-b9c6a59d0b82"   # data source (collection)
NOTION_DB_ID = "24bb8a5c-1068-43b5-b0e5-38a7b2e6d9cc"   # database block
SUMMARY_PAGE = "3746468e-ef67-81c8-a3f4-e63e598f53b4"   # Daily Client Pulse page
TOP_N_POSTS = 60

# ---------- helpers ----------

def http(url, headers=None, method="GET", body=None):
    req = urllib.request.Request(url, method=method, headers=headers or {})
    if body is not None:
        req.data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode() or "{}")

def vista(path, **params):
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{VISTA_BASE}/{path}" + (f"?{qs}" if qs else "")
    return http(url, headers={"api-key": VISTA_KEY})

def notion(path, method="GET", body=None):
    return http(f"https://api.notion.com/v1/{path}", method=method, body=body,
                headers={"Authorization": f"Bearer {NOTION_TOKEN}",
                         "Notion-Version": "2022-06-28"})

def num(row, *names):
    """First present numeric field among candidate names; null -> 0."""
    for n in names:
        if n in row and row[n] is not None:
            try:
                return float(row[n])
            except (TypeError, ValueError):
                pass
    return 0

def parse_row_date(s):
    """Accept '20250301', '2025-03-01' or 'March 5, 2025' -> date."""
    s = str(s).strip()
    if re.fullmatch(r"\d{8}", s):
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return date.fromisoformat(s)
    months = {m: i + 1 for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"])}
    m = re.fullmatch(r"([A-Za-z]+) (\d{1,2}), (\d{4})", s)
    if m and m.group(1) in months:
        return date(int(m.group(3)), months[m.group(1)], int(m.group(2)))
    return None

def clean_title(msg):
    if not msg:
        return ""
    t = re.sub(r"#\S+", "", str(msg)).strip()
    t = t.split("\n")[0]
    return t[:70].strip()

# ---------- main ----------

def main():
    if not VISTA_KEY:
        sys.exit("VISTA_API_KEY is not set")

    today = date.fromisoformat(str(__import__("datetime").datetime
                                   .now(ZoneInfo("America/Phoenix")).date()))
    TO = today - timedelta(days=1)
    F7, F30 = TO - timedelta(days=6), TO - timedelta(days=29)
    ymd = lambda d: d.strftime("%Y%m%d")
    print(f"Windows: 7d {F7}..{TO} | 30d {F30}..{TO}")

    groups = [g for g in vista("groups") if g.get("type") == "CLIENT"]
    print(f"CLIENT groups: {len(groups)}: {[g['name'] for g in groups]}")

    clients, posts = [], []
    for g in groups:
        gid, name = g["id"], g["name"]
        try:
            d7 = vista("data/daily", date_from=ymd(F7), date_to=ymd(TO), group_id=gid)
            d30 = vista("data/daily", date_from=ymd(F30), date_to=ymd(TO), group_id=gid)
            praw = vista("data/posts", date_from=ymd(F30), date_to=ymd(TO), group_id=gid)
        except Exception as e:
            print(f"WARN {name}: pull failed, skipping ({e})")
            continue
        if clients == [] and d7:
            print("daily row keys:", sorted(d7[0].keys()))
        if not posts and praw:
            print("post row keys:", sorted(praw[0].keys()))

        v7 = sum(num(r, "impressions") for r in d7)
        e7 = sum(num(r, "engagement", "engagements") for r in d7)
        v30 = sum(num(r, "impressions") for r in d30)
        e30 = sum(num(r, "engagement", "engagements") for r in d30)

        # follower snapshot/growth: per (profile, network) series, last/first non-null
        series = {}
        for r in sorted(d7, key=lambda r: str(r.get("date", ""))):
            f = r.get("followers")
            if f is None:
                continue
            key = (str(r.get("profile", r.get("profile_id", ""))), str(r.get("network", "")))
            first, _ = series.get(key, (f, f))
            series[key] = (first, f)
        foll = int(sum(last for _, last in series.values()))
        growth = int(sum(last - first for first, last in series.values()))

        clients.append({"name": name, "v7": int(v7), "e7": int(e7),
                        "v30": int(v30), "e30": int(e30),
                        "foll": foll, "growth": growth})

        for r in praw:
            link = r.get("published_link") or r.get("url")
            if not link:
                continue
            d = parse_row_date(r.get("date", ""))
            posts.append({"client": name,
                          "net": str(r.get("network", "")).lower(),
                          "type": r.get("type") or r.get("post_type") or "",
                          "likes": int(num(r, "likes")),
                          "comments": int(num(r, "comments")),
                          "shares": int(num(r, "shares")),
                          "impr": int(num(r, "impressions")),
                          "eng": int(num(r, "engagement", "engagements")),
                          "date": d.isoformat() if d else "",
                          "url": link,
                          "title": clean_title(r.get("message"))})

    posts = sorted(posts, key=lambda p: (-p["impr"], -p["eng"]))[:TOP_N_POSTS]
    N = len(clients)
    if N == 0:
        sys.exit("No client data pulled — aborting before overwriting dashboards")

    short = lambda d: f"{d.strftime('%b')} {d.day}"
    data = {"meta": {"updated": f"{today.strftime('%b')} {today.day}, {today.year}",
                     "windows": {"7": f"Last 7 Days ({short(F7)}–{short(TO)})",
                                 "30": f"Last 30 Days ({short(F30)}–{short(TO)})"}},
            "clients": clients, "posts": posts}
    body = json.dumps(data, ensure_ascii=False, indent=1)
    for fname in ("data.json", f"data-{today.strftime('%Y-%m')}.json"):
        with open(fname, "w", encoding="utf-8") as f:
            f.write(body)
        print(f"wrote {fname}")

    tv7 = sum(c["v7"] for c in clients)
    tg = sum(c["growth"] for c in clients)
    ta = sum(c["foll"] for c in clients)
    print(f"N={N} totalV7={tv7:,} avg={round(tv7/N):,} growth={tg:,} audience={ta:,}")

    if not NOTION_TOKEN:
        print("NOTION_TOKEN not set — skipping Notion update")
        return
    try:
        update_notion(clients, today, N, tv7, tg, ta)
    except Exception as e:
        print(f"WARN Notion update failed: {e}")

# ---------- Notion ----------

def query_rows():
    try:  # newer data-source endpoint first
        out, cursor = [], None
        while True:
            b = {"page_size": 100}
            if cursor:
                b["start_cursor"] = cursor
            r = http(f"https://api.notion.com/v1/data_sources/{NOTION_DS_ID}/query",
                     method="POST", body=b,
                     headers={"Authorization": f"Bearer {NOTION_TOKEN}",
                              "Notion-Version": "2025-09-03"})
            out += r.get("results", [])
            if not r.get("has_more"):
                return out
            cursor = r.get("next_cursor")
    except Exception:
        r = notion(f"databases/{NOTION_DB_ID}/query", method="POST", body={"page_size": 100})
        return r.get("results", [])

def row_title(page):
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in prop.get("title", []))
    return ""

def update_notion(clients, today, N, tv7, tg, ta):
    rows = {row_title(p): p["id"] for p in query_rows()}
    names = {c["name"] for c in clients}
    for c in clients:
        props = {"7-Day Views": {"number": c["v7"]},
                 "Avg Daily Views": {"number": round(c["v7"] / 7)},
                 "Current Followers": {"number": c["foll"]},
                 "7-Day Follower Growth": {"number": c["growth"]},
                 "7-Day Engagement": {"number": c["e7"]},
                 "Last Updated": {"date": {"start": today.isoformat()}}}
        if c["name"] in rows:
            notion(f"pages/{rows[c['name']]}", method="PATCH", body={"properties": props})
        else:
            props["Client"] = {"title": [{"text": {"content": c["name"]}}]}
            notion("pages", method="POST",
                   body={"parent": {"database_id": NOTION_DB_ID}, "properties": props})
            print(f"Notion: created row {c['name']}")
    for name, pid in rows.items():
        if name and name not in names:
            notion(f"pages/{pid}", method="PATCH", body={"archived": True})
            print(f"Notion: archived stale row {name}")

    # summary callouts: rewrite the numbers in place, preserving formatting
    def walk(block_id, depth=0):
        found, cursor = [], None
        while True:
            url = f"blocks/{block_id}/children?page_size=100" + \
                  (f"&start_cursor={cursor}" if cursor else "")
            r = notion(url)
            for b in r.get("results", []):
                if b["type"] == "callout":
                    found.append(b)
                elif b.get("has_children") and depth < 3:
                    found += walk(b["id"], depth + 1)
            if not r.get("has_more"):
                return found
            cursor = r.get("next_cursor")

    NUM = r"[\d,]{3,}"
    for co in walk(SUMMARY_PAGE):
        rich = co["callout"].get("rich_text", [])
        text = "".join(t.get("plain_text", "") for t in rich)
        subs = None
        if "TOTAL 7-DAY VIEWS" in text:
            subs = [(NUM, f"{tv7:,}", 1), (r"all \d+ client", f"all {N} client", 0)]
        elif "AVERAGE 7-DAY VIEWS" in text:
            subs = [(NUM, f"{round(tv7/N):,}", 1), (r"\d+ clients", f"{N} clients", 0)]
        elif "FOLLOWER GROWTH" in text:
            subs = [(r"\+" + NUM, f"+{tg:,}", 0), (NUM + r" total audience", f"{ta:,} total audience", 0)]
        if not subs:
            continue
        for t in rich:
            if t.get("type") != "text":
                continue
            s = t["text"]["content"]
            for pat, repl, count in subs:
                s = re.sub(pat, repl.replace("\\", "\\\\"), s, count=count)
            t["text"]["content"] = s
            t.pop("plain_text", None)
        notion(f"blocks/{co['id']}", method="PATCH", body={"callout": {"rich_text": rich}})
    print("Notion updated")

if __name__ == "__main__":
    main()
