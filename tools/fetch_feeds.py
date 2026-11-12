"""
Fetch the public JSON feeds that the ICC rankings website itself loads
(assets-icc.sportz.io) and cache them under data/feeds/.  Run it LOCALLY:

    cd tools
    python fetch_feeds.py            # all stages, ~10-15 minutes, resumable

Why: fetch_rankings.py only sees what is drawn on screen. The rankings pages,
player profile pages and match centre call these feeds, which also carry the
rank history (date picker), dates of birth, batting/bowling styles and scorecards.

Politeness: one request at a time, DELAY seconds apart, every response cached
(re-running only fetches what is missing). robots.txt of www.icc-cricket.com
allows /rankings; the feed host publishes none.
"""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CLIENT = "tPZJbRgIub3Vua93%2FDWtyQ%3D%3D"
FEED = "https://assets-icc.sportz.io/cricket"
USER_AGENT = "CourseProjectBot/1.0 (student database project)"
DELAY = 0.8
OUT = Path(__file__).parent / "data" / "feeds"

COMP_TYPES = ["test", "odi", "t20", "odiw", "t20w"]   # no women's Test rankings
RANK_TYPES = ["team", "bat", "bowl", "allrounder"]
DATES = [None, "20261005", "20260803"]                 # latest, ~1 and ~3 months back
MAX_MATCHES = 70
TOP_N_PROFILES = 40                                    # profiles for the top N of each table


def get(key, url):
    """Return parsed JSON for url, using the cache data/feeds/<key>.json."""
    f = OUT / f"{key}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    if (OUT / f"{key}.empty").exists():
        return None
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            txt = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        print(f"  [http {e.code}] {key}")
        time.sleep(DELAY)
        return None
    except Exception as e:
        print(f"  [err] {key}: {e}")
        time.sleep(DELAY)
        return None
    time.sleep(DELAY)
    try:
        data = json.loads(txt)
    except ValueError:
        print(f"  [not json] {key}")
        return None
    if not data.get("data"):
        (OUT / f"{key}.empty").write_text(txt[:300], encoding="utf-8")
        print(f"  [empty] {key}")
        return None
    f.write_text(txt, encoding="utf-8")
    print(f"  [ok] {key}")
    return data


def find_list_of_dicts(obj, must_have):
    """Depth-first search for the first list of dicts that has one of the keys."""
    if isinstance(obj, list) and obj and isinstance(obj[0], dict) and any(k in obj[0] for k in must_have):
        return obj
    if isinstance(obj, dict):
        for v in obj.values():
            r = find_list_of_dicts(v, must_have)
            if r:
                return r
    if isinstance(obj, list):
        for v in obj:
            r = find_list_of_dicts(v, must_have)
            if r:
                return r
    return None


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    print("1/4 ranking tables")
    ranked_players = []
    for d in DATES:
        for c in COMP_TYPES:
            for t in RANK_TYPES:
                url = f"{FEED}/v1/ranking?client_id={CLIENT}&comp_type={c}&lang=en&feed_format=json&type={t}"
                if d:
                    url += f"&date={d}"
                data = get(f"rank_{c}_{t}_{d or 'latest'}", url)
                if data and d is None and t != "team":
                    rows = list(data["data"].values())[0].get("rank", [])
                    ranked_players += [r.get("Player_id") for r in rows[:TOP_N_PROFILES]]

    print("2/4 schedule (recent + upcoming internationals)")
    games = []
    for page in range(1, 11):
        url = (f"{FEED}/v1/schedule?client_id={CLIENT}&feed_format=json&lang=en&is_deleted=false"
               f"&pagination=true&page_number={page}&page_size=100&from_date=20260915&to_date=20261210"
               f"&is_upcoming=true&is_live=true&is_recent=true")
        data = get(f"schedule_p{page}", url)
        if not data:
            break
        lst = find_list_of_dicts(data["data"], ("game_id", "match_id", "Game_id")) or []
        games += lst
        if len(lst) < 100:
            break
    def when(g):
        m, d, y = g.get("match_date_gmt", "1/1/1900").split("/")
        return (int(y), int(m), int(d))
    # completed/abandoned internationals, most recent first, then a few upcoming fixtures
    full = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "25", "1188",         # men's full members
            "1119", "1121", "1123", "1125", "1126", "1129", "1131", "1133", "1135", "1155"}
    recent = sorted([g for g in games if g.get("recent") in (True, "true")], key=when, reverse=True)
    recent.sort(key=lambda g: (g.get("teama_id") in full) + (g.get("teamb_id") in full), reverse=True)
    upcoming = sorted([g for g in games if g.get("upcoming") in (True, "true")], key=when)
    pick = recent[:MAX_MATCHES - 10] + upcoming[:10]
    ids = []
    for g in pick:
        gid = g.get("game_id") or g.get("match_id") or g.get("Game_id")
        if gid and gid not in ids:
            ids.append(gid)
    print(f"   {len(games)} schedule rows, {len(ids)} scorecards to fetch")

    print("3/4 scorecards")
    card_players = []
    for gid in ids:
        data = get(f"scorecard_{gid}",
                   f"{FEED}/v1/game/scorecard?client_id={CLIENT}&feed_format=json&game_id={gid}&lang=en")
        if data:
            for team in (data["data"].get("Teams") or {}).values():
                card_players += list((team.get("Players") or {}).keys())

    print("4/4 player profiles")
    seen = []
    for pid in card_players + ranked_players:
        if pid and pid not in seen:
            seen.append(pid)
    print(f"   {len(seen)} profiles")
    for pid in seen:
        get(f"player_{pid}", f"{FEED}/v2/player?client_id={CLIENT}&player_id={pid}&lang=en&feed_format=json")
    print("Done. Now run:  python build_populate.py")


if __name__ == "__main__":
    sys.exit(main())
