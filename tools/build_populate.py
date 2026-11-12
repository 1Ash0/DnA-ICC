"""
Builds ../src/populate.sql from the data fetched off the ICC website:
  * data/feeds/*.json   (fetch_feeds.py: rank tables with history, schedule,
                         scorecards, player profiles)
  * data/raw/*.html     (fetch_rankings.py: rendered ranking tables) - used for
                         any table the feeds do not cover (men's T20I).
Run:  python build_populate.py
"""
import datetime as dt
import glob
import json
import re
from collections import defaultdict
from pathlib import Path

from bs4 import BeautifulSoup

HERE = Path(__file__).parent
FEEDS = HERE / "data" / "feeds"
RAW = HERE / "data" / "raw"
OUT = HERE.parent / "src" / "populate.sql"

# ---------------------------------------------------------------- reference data
FULL_MEMBERS = {  # name: (short_code, joined_year, region)
    "England": ("ENG", 1909, "Europe"), "Australia": ("AUS", 1909, "East Asia-Pacific"),
    "South Africa": ("SA", 1909, "Africa"), "West Indies": ("WI", 1926, "Americas"),
    "New Zealand": ("NZ", 1926, "East Asia-Pacific"), "India": ("IND", 1926, "Asia"),
    "Pakistan": ("PAK", 1952, "Asia"), "Sri Lanka": ("SL", 1981, "Asia"),
    "Zimbabwe": ("ZIM", 1992, "Africa"), "Bangladesh": ("BAN", 2000, "Asia"),
    "Ireland": ("IRE", 2017, "Europe"), "Afghanistan": ("AFG", 2017, "Asia"),
}
REGION = {}
for r, names in {
    "Africa": "Botswana Cameroon Eswatini Gambia Ghana Kenya Lesotho Malawi Mali Morocco Mozambique Namibia "
              "Nigeria Rwanda St_Helena Saint_Helena Seychelles Sierra_Leone Tanzania Uganda Zambia Cote_d'Ivoire Ivory_Coast",
    "Americas": "Argentina Bahamas Belize Bermuda Brazil Canada Cayman_Islands Chile Costa_Rica Falkland_Islands "
                "Mexico Panama Peru Suriname Turks_and_Caicos_Islands USA United_States_of_America",
    "Asia": "Bahrain Bhutan Hong_Kong Kuwait Malaysia Maldives Myanmar Nepal Oman Qatar Saudi_Arabia Singapore "
            "Thailand UAE United_Arab_Emirates Uzbekistan Iran Hong_Kong,_China Hong_Kong Cambodia",
    "East Asia-Pacific": "Cook_Islands Fiji Indonesia Japan Papua_New_Guinea Philippines Samoa South_Korea Korea "
                         "Timor-Leste Timor_Leste Vanuatu China Mongolia",
    "Europe": "Austria Belgium Bulgaria Croatia Cyprus Czech_Republic Czechia Denmark Estonia Finland France "
              "Germany Gibraltar Greece Guernsey Hungary Isle_of_Man Israel Italy Jersey Luxembourg Malta Netherlands "
              "Norway Portugal Romania Scotland Serbia Slovenia Spain Sweden Switzerland Turkey Turkiye Serbia",
}.items():
    for n in names.split():
        REGION[n.replace("_", " ")] = r
for n, (_, _, r) in FULL_MEMBERS.items():
    REGION[n] = r

# Test status history (men).  (since, end)
TEST_STATUS = {
    "England": [("1877-03-15", None)], "Australia": [("1877-03-15", None)],
    "South Africa": [("1889-03-12", "1970-03-10"), ("1992-04-18", None)],
    "West Indies": [("1928-06-23", None)], "New Zealand": [("1930-01-10", None)],
    "India": [("1932-06-25", None)], "Pakistan": [("1952-10-16", None)],
    "Sri Lanka": [("1982-02-17", None)],
    "Zimbabwe": [("1992-10-18", "2006-01-18"), ("2011-08-04", None)],
    "Bangladesh": [("2000-11-10", None)], "Ireland": [("2018-05-11", None)],
    "Afghanistan": [("2018-06-14", None)],
}
ODI_STATUS_MEN = {
    "England": "1971-01-05", "Australia": "1971-01-05", "New Zealand": "1973-02-11", "Pakistan": "1973-02-11",
    "West Indies": "1973-09-05", "India": "1974-07-13", "Sri Lanka": "1975-06-07", "Zimbabwe": "1983-06-09",
    "Bangladesh": "1986-03-31", "South Africa": "1991-11-10", "Ireland": "2006-06-13", "Scotland": "2006-08-18",
    "Afghanistan": "2009-04-19", "Netherlands": "2018-03-04", "Nepal": "2018-03-15", "United Arab Emirates": "2014-01-01",
    "Papua New Guinea": "2014-11-08", "Namibia": "2019-04-27", "Oman": "2019-04-27",
    "United States of America": "2019-04-27", "USA": "2019-04-27", "Canada": "2023-04-01",
}
T20I_ALL_MEN, T20I_ALL_WOMEN = "2019-01-01", "2018-07-01"   # ICC gave T20I status to all members

ANALYSTS = [  # internal users (not on the website): needed for PUBLISHES / SUPERVISES
    (1, "rk.admin", "rk.admin@rankings.example.org", "Admin", None),
    (2, "men.analyst", "men.analyst@rankings.example.org", "Analyst", 1),
    (3, "women.analyst", "women.analyst@rankings.example.org", "Analyst", 1),
    (4, "match.analyst", "match.analyst@rankings.example.org", "Analyst", 1),
    (5, "trainee.analyst", "trainee.analyst@rankings.example.org", "Analyst", 4),
]
# Real retirements announced by the players (format, date)
RETIREMENTS = {
    3993: [("T20I", "2024-06-29"), ("TEST", "2025-05-12")],   # Virat Kohli
    3852: [("T20I", "2024-06-29"), ("TEST", "2025-05-07")],   # Rohit Sharma
    9311: [("T20I", "2024-06-30")],                            # Ravindra Jadeja
}

FMT = {"test": "TEST", "odi": "ODI", "t20": "T20I", "t20i": "T20I", "odiw": "ODI", "t20w": "T20I"}


# ---------------------------------------------------------------- helpers
def q(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("\\", "\\\\").replace("'", "''") + "'"


def mdy(s):  # "9/15/2026" or "9/15/2026T07:30..." -> date
    s = s.split("T")[0]
    m, d, y = s.split("/")
    return dt.date(int(y), int(m), int(d))


def dmy(s):  # "08/09/1999" -> date
    d, m, y = s.split("/")
    return dt.date(int(y), int(m), int(d))


def load(f):
    return json.loads(Path(f).read_text(encoding="utf-8"))


def gender_of(url_or_text):
    return "W" if "women" in (url_or_text or "").lower() else "M"


def overs_to_balls(o):
    try:
        o = str(o)
        if "." in o:
            a, b = o.split(".")
            return int(a) * 6 + int(b)
        return int(float(o)) * 6
    except ValueError:
        return 0


def to_int(v, default=0):
    try:
        return int(str(v).strip())
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------- collectors
members = {}            # name -> dict
teams = {}              # team_id -> dict(name, short, gender)
players = {}            # player_id -> dict(name, team_id, gender)
team_ratings = {}       # (team, fmt, date) -> (matches, points)
player_ratings = {}     # (player, fmt, disc, date) -> points
player_team_dates = defaultdict(list)   # player -> [(date, team)]


PLACEHOLDER = re.compile(r"^([A-H]\d|TBC|TBA|TBD)$|winner|loser|qualifier", re.I)


def add_team(tid, name, short, gender):
    tid = int(tid)
    name = re.sub(r" Cricket$", "", (name or "").strip())
    short = re.sub(r"-?W$", "", (short or "").strip()) if gender == "W" else (short or "").strip()
    if not tid or PLACEHOLDER.search(name):
        return
    if name in ("U.A.E.", "UAE"):
        name = "United Arab Emirates"
    if name == "USA":
        name = "United States of America"
    if tid not in teams:
        teams[tid] = {"name": name, "short": (short or "").strip(), "gender": gender}
    elif short and not teams[tid]["short"]:
        teams[tid]["short"] = short.strip()


def add_player(pid, name, tid, gender):
    pid = int(pid)
    p = players.setdefault(pid, {"name": name.strip(), "team": int(tid), "gender": gender})
    return p


# 1. rank feeds -------------------------------------------------------------
covered = set()
for f in sorted(FEEDS.glob("rank_*.json")):
    _, comp, kind, _ = f.stem.split("_")
    if kind == "allrounder":
        continue                      # derived: FLOOR(batting * bowling / 1000)
    r = list(load(f)["data"].values())[0]
    date = r.get("rank_date")
    if not date:
        continue
    fmt = FMT[comp]
    gender = "W" if comp.endswith("w") else "M"
    covered.add((kind, fmt, gender))
    for row in r.get("rank", []):
        add_team(row["team_id"], row.get("team_name") or row.get("Country"), row.get("shortname")
                 or (row.get("Country") if len(row.get("Country", "")) <= 4 else ""), gender)
        if kind == "team":
            team_ratings[(int(row["team_id"]), fmt, date)] = (to_int(row["Matches"]), to_int(row["Points"]))
        else:
            add_player(row["Player_id"], row["Player-name"], row["team_id"], gender)
            disc = "Batting" if kind == "bat" else "Bowling"
            player_ratings[(int(row["Player_id"]), fmt, disc, date)] = to_int(row["Points"])
            player_team_dates[int(row["Player_id"])].append((date, int(row["team_id"])))

# 2. raw HTML tables for anything the feeds did not cover ---------------------
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July",
                                      "August", "September", "October", "November", "December"], 1)}
for f in sorted(RAW.glob("*.html")):
    kind, gword, fmtw = f.stem.split("-")
    gender = "W" if gword == "womens" else "M"
    fmt = FMT[fmtw]
    if (kind, fmt, gender) in covered:
        continue
    html = f.read_text(encoding="utf-8")
    m = re.search(r"Rank date - (\d+) (\w+) (\d{4})", html)
    if not m:
        continue
    date = dt.date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1))).isoformat()
    soup = BeautifulSoup(html, "html.parser")
    for tr in soup.find("table").find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 4 or not tds[0].get_text(strip=True):
            continue
        a = tds[1].find("a")
        tm = re.search(r"/teams/(\d+)/([a-z\-]+)", a["href"]) if a else None
        if not tm:
            continue
        tid = tm.group(1)
        txt = tds[1].get_text(strip=True)
        slug_name = txt if len(txt) > 4 else tm.group(2).rsplit("-", 1)[0].replace("-", " ").title()
        add_team(tid, slug_name.replace("Usa", "USA").replace("Of", "of").replace("And", "and"),
                 tds[1].get_text(strip=True) if len(tds[1].get_text(strip=True)) <= 4 else "", gender)
        if kind == "team":
            team_ratings[(int(tid), fmt, date)] = (to_int(tds[2].get_text(strip=True)),
                                                   to_int(tds[3].get_text(strip=True)))
        else:
            pa = tds[2].find("a")
            pm = re.search(r"/rankings/(\d+)/", pa["href"]) if pa else None
            if not pm:
                continue
            spans = [s.get_text(strip=True) for s in pa.find_all("span") if not s.find("span")]
            name = " ".join(s.title() if s.isupper() else s for s in spans)
            add_player(pm.group(1), name, tid, gender)
            disc = "Batting" if kind == "bat" else "Bowling"
            player_ratings[(int(pm.group(1)), fmt, disc, date)] = to_int(tds[3].get_text(strip=True))
            player_team_dates[int(pm.group(1))].append((date, int(tid)))

# 3. schedule + scorecards ----------------------------------------------------
sched = {}
for f in sorted(FEEDS.glob("schedule_p*.json")):
    for g in load(f)["data"]["matches"]:
        sched[g["match_id"]] = g

series, venues, matches, parts, apps = {}, {}, {}, [], []
for f in sorted(FEEDS.glob("scorecard_*.json")):
    d = load(f)["data"]
    md = d["Matchdetail"]
    mt = md["Match"]
    mid = int(mt["Id"])
    fmt = FMT.get(mt["Type"].lower().replace("t20i", "t20i"), None) or {"TEST": "TEST"}.get(mt["Type"].upper())
    if mt["Type"].upper().startswith("T20"):
        fmt = "T20I"
    elif mt["Type"].upper() == "ODI":
        fmt = "ODI"
    elif mt["Type"].upper() == "TEST":
        fmt = "TEST"
    else:
        continue                                   # youth / other formats are out of scope
    g = sched.get(str(mid), {})
    comp = g.get("comp_type", "")
    t_home, t_away = to_int(md.get("Team_Home")), to_int(md.get("Team_Away"))
    if not t_home or not t_away or t_home == t_away:
        continue                                   # teams still TBD
    tm = d.get("Teams", {})
    gender = "W" if comp.strip().endswith("- w") or "Women" in md["Series"]["Name"] else "M"
    for tid in (t_home, t_away):
        info = tm.get(str(tid), {})
        add_team(tid, info.get("Name_Full", g.get("teama") if str(tid) == g.get("teama_id") else g.get("teamb", "?")),
                 info.get("Name_Short", ""), gender)
    if t_home not in teams or t_away not in teams:
        continue
    s = md["Series"]
    sid = int(s["Id"])
    name = s["Name"]
    lname = name.lower()
    stype = ("Tri-series" if "tri" in lname.split() or "tri-series" in lname else
             "One-off" if "one-off" in lname else
             # named two-team trophies (Trans-Tasman, Border-Gavaskar, ...) are bilateral series
             "Tournament" if (any(w in lname for w in ("cup", "championship", "league", "games", "qualifier"))
                              or lname.startswith("icc ")) and " in " not in lname else "Bilateral")
    series[sid] = (name, mdy(s["Series_start_date"]), mdy(s["Series_end_date"]), stype)
    v = md["Venue"]
    ground = v["Name"].rsplit(",", 1)[0].strip() if "," in v["Name"] else v["Name"]
    city = v.get("City") or v["Name"].rsplit(",", 1)[-1].strip()
    venues[(ground, city)] = v.get("Country") or "Unknown"
    if mt.get("is_match_abandoned") in (True, "true"):
        status = "Abandoned"
    elif mt.get("Upcoming") in (True, "true") or md.get("Match_display_status") == "Upcoming":
        status = "Scheduled"
    elif mt.get("is_match_ended") in (True, "true") or md.get("Match_display_status") == "Result":
        status = "Completed"
    else:
        continue                                   # live: skip
    start = mdy(mt["Date"])
    end = mdy(mt.get("End_date") or mt["Date"])
    dls = "DLS" in (md.get("Result") or "") or "D/L" in (md.get("Result") or "")
    matches[mid] = dict(no=to_int(mt.get("Match_ordinal"), 1) or 1, date=start, end=end, status=status,
                        ground=ground, city=city, series=sid, fmt=fmt, dls=dls,
                        neutral=str(v.get("Neutralvenue")).lower() == "true")
    # participations
    totals = defaultdict(int)
    for inn in d.get("Innings") or []:
        totals[int(inn["Battingteam"])] += to_int(inn.get("Total"))
    win = md.get("Winningteam") or ""
    raw = (md.get("Raw_matchresult") or "").lower()
    for tid in (t_home, t_away):
        if status == "Completed":
            if win:
                res = "Won" if str(tid) == str(win) else "Lost"
            elif "draw" in (md.get("Result") or "").lower() or raw == "d":
                res = "Drawn"
            elif "tie" in (md.get("Result") or "").lower() or raw == "t":
                res = "Tied"
            else:
                res = "No result"
            runs = totals.get(tid, 0)
        else:
            res, runs = None, None
        side = "Neutral" if matches[mid]["neutral"] else ("Home" if tid == t_home else "Away")
        parts.append((mid, tid, side, runs, res))
    if status != "Completed":
        continue
    # appearances
    stats = {}
    for tid_s, info in tm.items():
        for pid, p in (info.get("Players") or {}).items():
            add_player(pid, p.get("Name_Full", "?"), tid_s, gender)
            players[int(pid)].setdefault("roles", set())
            role = (p.get("Role") or p.get("Skill_Name") or "").lower()
            players[int(pid)]["roles"].add("Wicket-keeper" if "keeper" in role else "All-rounder" if "all" in role
                                           else "Bowler" if "bowl" in role else "Batter")
            stats[int(pid)] = dict(team=int(tid_s), batted=False, bowled=False, r=0, b=0, w=0, rc=0, bb=0,
                                   xi=p.get("Confirm_XI") in (True, "true"))
            player_team_dates[int(pid)].append((start.isoformat(), int(tid_s)))
    for inn in d.get("Innings") or []:
        for b in inn.get("Batsmen") or []:
            st = stats.get(to_int(b.get("Batsman"), -1))
            if st is not None and str(b.get("Balls", "")).strip() != "":
                st.update(batted=True, r=to_int(b.get("Runs")), b=to_int(b.get("Balls")), xi=True)
        for w in inn.get("Bowlers") or []:
            st = stats.get(to_int(w.get("Bowler"), -1))
            if st is not None:
                balls = to_int(w.get("Balls_Bowled"), 0) or overs_to_balls(w.get("Overs", 0))
                st.update(bowled=True, w=to_int(w.get("Wickets")), rc=to_int(w.get("Runs")), bb=balls, xi=True)
    for pid, st in stats.items():
        if st["xi"]:
            apps.append((pid, mid, st))

# 4. player profiles ------------------------------------------------------------
profiles = {}
for f in FEEDS.glob("player_*.json"):
    try:
        p = load(f)["data"]["profile"]
        profiles[int(p["player_id"])] = p
    except (KeyError, ValueError, TypeError):
        pass

# ---------------------------------------------------------------- derive rows
# members
for tid, t in teams.items():
    name = t["name"]
    if name not in members:
        fm = FULL_MEMBERS.get(name)
        members[name] = {"short": fm[0] if fm else None, "type": "Full" if fm else "Associate",
                         "year": fm[1] if fm else None, "region": REGION.get(name, "Asia" if fm is None else fm[2])}
    if not members[name]["short"] and t["short"]:
        members[name]["short"] = t["short"]
used = set()
for name, m in sorted(members.items()):
    code = (m["short"] or re.sub(r"[^A-Z]", "", name.upper())[:3]).upper()[:5]
    base, i = code, 2
    while code in used:
        code = f"{base[:4]}{i}"
        i += 1
    used.add(code)
    m["short"] = code
member_ids = {name: i for i, name in enumerate(sorted(members), 1)}

# drop teams whose member already has a team of that gender (keep the one with most data)
seen_mg = {}
for tid, t in sorted(teams.items()):
    key = (t["name"], t["gender"])
    seen_mg.setdefault(key, tid)
teams = {tid: t for tid, t in teams.items() if seen_mg[(t["name"], t["gender"])] == tid}

# players: names, current team, from_date
def split_name(pid, p):
    prof = profiles.get(pid)
    disp = (prof.get("name") if prof else None) or p["name"]
    parts_ = disp.split()
    first, last = (parts_[0], " ".join(parts_[1:])) if len(parts_) > 1 else (disp, disp)
    middle = None
    if prof and prof.get("fullname"):
        full = prof["fullname"].split()
        rest = [w for w in full if w not in parts_]
        middle = " ".join(rest) or None
    return first, middle, last


earliest = {}
for pid, lst in player_team_dates.items():
    earliest[pid] = min(d for d, _ in lst)
for pid, p in players.items():
    lst = sorted(player_team_dates.get(pid, []))
    if lst:
        p["team"] = lst[-1][1]
    p["team"] = p["team"] if p["team"] in teams else None

lines = []
w = lines.append
w("-- =====================================================================")
w("--  ICC Rankings - populate.sql (generated by tools/build_populate.py)")
w(f"--  Source: www.icc-cricket.com ranking tables, player profiles, schedule and")
w(f"--  scorecards, fetched {dt.date.today().isoformat()}.  Run after schema.sql.")
w("-- =====================================================================")
w("USE icc_rankings;")
w("SET NAMES utf8mb4;")
w("")


def insert(table, cols, rows, chunk=200):
    rows = list(rows)
    if not rows:
        return
    w(f"-- {table}: {len(rows)} rows")
    for i in range(0, len(rows), chunk):
        w(f"INSERT INTO {table} ({', '.join(cols)}) VALUES")
        w(",\n".join("  (" + ", ".join(q(v) for v in r) + ")" for r in rows[i:i + chunk]) + ";")
    w("")


insert("format", ["format_code", "format_name", "overs_per_innings"],
       [("TEST", "Test", None), ("ODI", "One Day International", 50), ("T20I", "Twenty20 International", 20)])
insert("icc_member", ["member_id", "short_code", "name", "membership_type", "region", "joined_year"],
       [(member_ids[n], m["short"], n, m["type"], m["region"], m["year"]) for n, m in sorted(members.items())])
insert("app_user", ["user_id", "username", "email", "role", "supervisor_id"], ANALYSTS)
insert("team", ["team_id", "team_code", "team_name", "gender", "member_id"],
       [(tid, f"{members[t['name']]['short']}-{t['gender']}", t["name"] + (" Women" if t["gender"] == "W" else ""),
         t["gender"], member_ids[t["name"]]) for tid, t in sorted(teams.items())])

# format status
status_rows = []
rated = defaultdict(lambda: "9999-12-31")
for (tid, fmt, date), _ in team_ratings.items():
    rated[(tid, fmt)] = min(rated[(tid, fmt)], date)
for mid, m in matches.items():
    for (pm, tid, *_r) in parts:
        if pm == mid:
            rated[(tid, m["fmt"])] = min(rated[(tid, m["fmt"])], m["date"].isoformat())
for tid, t in sorted(teams.items()):
    status_rows.append((tid, "T20I", T20I_ALL_WOMEN if t["gender"] == "W" else T20I_ALL_MEN, None))
    if t["gender"] == "M" and t["name"] in TEST_STATUS:
        for since, end in TEST_STATUS[t["name"]]:
            status_rows.append((tid, "TEST", since, end))
    elif (tid, "TEST") in rated and t["gender"] == "M":
        status_rows.append((tid, "TEST", rated[(tid, "TEST")], None))
    if (tid, "ODI") in rated or (t["gender"] == "M" and t["name"] in ODI_STATUS_MEN):
        since = ODI_STATUS_MEN.get(t["name"]) if t["gender"] == "M" else None
        first_seen = rated[(tid, "ODI")]
        since = min(since or first_seen, first_seen)
        status_rows.append((tid, "ODI", since, None))
insert("has_status_in", ["team_id", "format_code", "status_since", "status_end_date"], status_rows)

# players
prow, roles, reps = [], [], []
ident = set()
for pid, p in sorted(players.items()):
    if p["team"] is None:
        continue
    prof = profiles.get(pid, {})
    first, middle, last = split_name(pid, p)
    dob = None
    try:
        dob = dmy(prof["dob"]).isoformat() if prof.get("dob") else None
    except (ValueError, KeyError):
        dob = None
    key = (first, last, dob, p["gender"])
    if dob and key in ident:
        dob = None
    ident.add(key)
    bat = (prof.get("batting_style") or {}).get("text") if isinstance(prof.get("batting_style"), dict) else None
    bowl = (prof.get("bowling_style") or {}).get("text") if isinstance(prof.get("bowling_style"), dict) else None
    prow.append((pid, first, middle, last, dob, p["gender"], bat, bowl))
    rs = set(p.get("roles", set()))
    skill = ((prof.get("player_skill") or {}).get("role") or "").lower() if isinstance(prof.get("player_skill"), dict) else ""
    if skill:
        rs = {"Wicket-keeper" if "keeper" in skill else "All-rounder" if "all" in skill
              else "Bowler" if "bowl" in skill else "Batter"} | ({"Wicket-keeper"} & rs)
    if not rs:
        discs = {k[2] for k in player_ratings if k[0] == pid}
        rs = {"All-rounder"} if discs == {"Batting", "Bowling"} else {"Bowler"} if discs == {"Bowling"} else {"Batter"}
    roles += [(pid, r) for r in sorted(rs)]
    since = earliest.get(pid, "2026-01-01")
    try:
        deb = prof.get("international_debut", {}).get("match_date")
        if deb:
            since = min(since, dmy(deb).isoformat())
    except (ValueError, AttributeError):
        pass
    reps.append((pid, p["team"], since, None))
    p["since"] = since
valid_players = {r[0] for r in prow}
insert("player", ["player_id", "first_name", "middle_name", "last_name", "date_of_birth", "gender",
                  "batting_style", "bowling_style"], prow)
insert("player_role", ["player_id", "playing_role"], roles)
insert("represents", ["player_id", "team_id", "from_date", "to_date"], reps)
insert("player_retired_format", ["player_id", "format_code", "retired_on"],
       [(pid, f, d) for pid, lst in RETIREMENTS.items() if pid in valid_players for f, d in lst])

# series / venues / matches
insert("series", ["series_id", "series_name", "start_date", "end_date", "series_type"],
       [(sid, *v) for sid, v in sorted(series.items())])
insert("venue", ["ground", "city", "country"], [(g, c, k) for (g, c), k in sorted(venues.items())])
used_no = set()
mrows = []
for mid, m in sorted(matches.items(), key=lambda kv: (kv[1]["date"], kv[0])):
    no = m["no"]
    while (m["series"], no) in used_no:
        no += 1
    used_no.add((m["series"], no))
    mrows.append((mid, no, m["date"].isoformat(), m["status"], m["ground"], m["city"], m["series"], m["fmt"]))
insert("matches", ["match_id", "match_no", "match_date", "status", "ground", "city", "series_id", "format_code"], mrows)
insert("test_match", ["match_id", "scheduled_days", "days_played"],
       [(mid, 5, ((m["end"] - m["date"]).days + 1) if m["status"] == "Completed" else None)
        for mid, m in sorted(matches.items()) if m["fmt"] == "TEST"])
insert("limited_overs_match", ["match_id", "overs_per_side", "dls_applied"],
       [(mid, 50 if m["fmt"] == "ODI" else 20, m["dls"]) for mid, m in sorted(matches.items()) if m["fmt"] != "TEST"])
part_rows = [p for p in parts if p[0] in matches and p[1] in teams]
insert("participates_in", ["match_id", "team_id", "side", "total_runs", "result"], part_rows)
okpart = {(p[0], p[1]) for p in part_rows}
app_rows = []
for pid, mid, st in apps:
    if pid not in valid_players or (mid, st["team"]) not in okpart or players[pid]["team"] != st["team"]:
        continue
    if players[pid]["since"] > matches[mid]["date"].isoformat():
        continue
    app_rows.append((pid, mid, st["team"], st["batted"], st["bowled"], st["r"], st["b"], st["w"], st["rc"], st["bb"]))
insert("appeared_for", ["player_id", "match_id", "team_id", "batted", "bowled", "runs_scored", "balls_faced",
                        "wickets_taken", "runs_conceded", "balls_bowled"], app_rows)

# ratings (latest snapshot published by the admin, older ones by the analysts)
latest_t = defaultdict(str)
for (tid, fmt, date) in team_ratings:
    latest_t[(teams.get(tid, {}).get("gender"), fmt)] = max(latest_t[(teams.get(tid, {}).get("gender"), fmt)], date)
tr_rows = []
for (tid, fmt, date), (mt_, pts) in sorted(team_ratings.items()):
    if tid not in teams or mt_ <= 0:
        continue
    g = teams[tid]["gender"]
    pub = 1 if date == latest_t[(g, fmt)] else (2 if g == "M" else 3)
    tr_rows.append((tid, fmt, date, mt_, pts, "Weekly", False, pub))
insert("team_rating", ["team_id", "format_code", "as_of_date", "matches", "points", "update_trigger",
                       "needs_recompute", "published_by"], tr_rows)
latest_p = defaultdict(str)
for (pid, fmt, disc, date) in player_ratings:
    k = (players[pid]["gender"], fmt, disc)
    latest_p[k] = max(latest_p[k], date)
pr_rows = []
for (pid, fmt, disc, date), pts in sorted(player_ratings.items()):
    if pid not in valid_players:
        continue
    g = players[pid]["gender"]
    pub = 1 if date == latest_p[(g, fmt, disc)] else (2 if g == "M" else 3)
    pr_rows.append((pid, fmt, disc, date, pts, pub))
insert("player_rating", ["player_id", "format_code", "discipline", "as_of_date", "rating_points", "published_by"],
       pr_rows)

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"members={len(members)} teams={len(teams)} players={len(prow)} profiles={len(profiles)} "
      f"series={len(series)} venues={len(venues)} matches={len(mrows)} parts={len(part_rows)} "
      f"appearances={len(app_rows)} team_ratings={len(tr_rows)} player_ratings={len(pr_rows)}")
print(f"-> {OUT}")
