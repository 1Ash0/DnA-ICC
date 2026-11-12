# ICC Rankings – Phase 4 (Team 45, "bcnf")

A populated MySQL database and a Flask web application modelled on the
**ICC rankings website** (<https://www.icc-cricket.com/rankings>): team, batting,
bowling and all-rounder tables for Test, ODI and T20I (men and women), rank-date
history, player and team profiles, matches with scorecards, head-to-head,
player comparison, and an admin area for publishing ratings.

## Stack

| Part | Choice | Version |
|---|---|---|
| Paradigm / DBMS | Relational, **MySQL Community Server** | 8.0.44 (needs 8.0.16+ for CHECK) |
| Query language | Raw SQL (PyMySQL `%s` parameters), no ORM or query builder | |
| Backend | Python + **Flask** | Python 3.12/3.13, Flask 3.x |
| DB driver | **PyMySQL** (+ `cryptography`, needed for MySQL 8's default `caching_sha2_password` login) | 1.1.x |
| Frontend | Server-rendered **Jinja2** templates + plain CSS (`static/style.css`) | |

## Setup and run

```bash
# 1. create and fill the database (run from the src/ folder)
cd src
mysql -u root -p < schema.sql          # macOS/Linux, or Windows cmd.exe
mysql -u root -p < populate.sql
#    Windows PowerShell has no "<" redirect; use:
#    cmd /c "mysql -u root -p < schema.sql"
#    cmd /c "mysql -u root -p < populate.sql"

# 2. install Python dependencies
pip install -r requirements.txt

# 3. point the app at your MySQL (defaults: localhost:3306, root, empty password, icc_rankings)
#    Windows PowerShell:  $env:DB_PASS="yourpassword"
#    macOS/Linux:         export DB_PASS=yourpassword
#    optional: DB_HOST, DB_PORT, DB_USER, DB_NAME

# 4. start the app (set FLASK_DEBUG=1 for the auto-reloader/debugger)
python app.py
```

Open **<http://localhost:5000>**.

`schema.sql` drops and recreates the `icc_rankings` database, so running both
scripts on a fresh server always reproduces the same database.

### Where the data comes from

Everything in `populate.sql` was taken from www.icc-cricket.com (fetched 10–12 Nov 2026):

* **Ranking tables** (team, batting, bowling) for every gender and format, at three rank
  dates each (latest, early Oct 2026, early Aug 2026), from the rankings pages and their
  date picker. They give 686 team-rating rows and about 3,000 player-rating rows.
* **Player profiles** (full name, date of birth, batting/bowling style, role, debut).
* **Matches** (Sep–Dec 2026 internationals) from the schedule and match-centre scorecards,
  with series, venues, results and per-player batting/bowling figures.
* The saved rendered ranking pages (`tools/data/raw`) are used as a fallback for any table
  the JSON feeds do not cover.

The scripts in the project repository's `tools/` folder (not part of the submission zip and not
needed to run the app) reproduce this: `fetch_rankings.py` saves the rendered ranking
pages, `fetch_feeds.py` saves the JSON the same pages load, and `build_populate.py`
turns both into `src/populate.sql`. Only the five `app_user` rows (internal staff accounts
needed for "published by") and the format-status start dates (ICC history: Test debuts,
T20I status for all members from 2018/2019) are not read from the rankings pages.

## Design Changes

Our Mini World (ICC Rankings, Phase 1 by Team 45) was modelled in **Phase 2 by Team 41**
(EER) and converted in **Phase 3 by Team 32** (relational model, 3NF). Team 32's
Stage D model (17 relations) is the baseline. All 17 relations are implemented with the
attributes, keys and foreign keys listed by Team 32. Changes:

1. **`MATCH` table renamed `matches`.** `MATCH` is a reserved word in MySQL.
2. **`HAS_STATUS_IN.status_end_date` kept** (it is in Team 32's text but missing from the
   Stage D drawing). The Phase 1 "end a status instead of deleting history" rule needs it.
   A trigger refuses deleting status rows.
3. **Weekday rule (women Tuesday, men Wednesday) not enforced.** The real rank dates on the
   website break it (e.g. men's ODI batting is dated Tue 10 Nov 2026), so a CHECK would
   reject real data.
4. **"Only matches completed before the update date feed a rating" not enforced.** Ratings
   are stored as published (the algorithm is a black box) and no rating row references
   individual matches, so there is nothing to compare against.
5. **Website IDs used as primary keys** for `team`, `player`, `series` and `matches`
   (no AUTO_INCREMENT). This keeps every row traceable to the ICC page it came from and
   makes `populate.sql` reproducible.
6. **`player.date_of_birth` and `icc_member.joined_year` are nullable.** DOBs are only
   fetched for profiled players (the top of each table plus everyone in the scorecards).
   The ICC does not publish joining years for associates. The alternate key
   `(first_name, last_name, date_of_birth, gender)` is still declared UNIQUE.
7. **`participates_in.result` and `total_runs` are nullable.** A Scheduled match has two
   participants but no result yet.
8. **Domains made explicit with ENUM/CHECK:** `membership_type`, `region`, `gender`,
   `series_type`, `match status`, `side`, `result`, `playing_role`, `discipline`,
   `update_trigger`. Also `rating_points BETWEEN 0 AND 1000`, `matches > 0`,
   `overs_per_innings` NULL only for Test, `end_date >= start_date`, and batted/bowled
   flags consistent with the figures. These enforce the Phase 1 rules.
9. **Triggers added for rules keys cannot express** (all from Phase 1/2):
   * exactly two teams per match, of the same gender;
   * the two results must agree (no "both Won"); changing a result sets
     `needs_recompute` on both teams' latest rating;
   * an appearance only in a Completed match, for a team the player represents on that date
     (the composite FK `(match_id, team_id)` → `participates_in` checks that the team played);
   * a team spell must match the player's gender and not overlap the current one;
   * retiring is refused if the player appeared in that format after the retirement date;
   * no women's Test team or player ratings, and Test/ODI team ratings only for teams
     holding that status on that date;
   * only Scheduled/Abandoned matches can be deleted; a match with appearances must stay
     Completed, and only a Completed match can carry a Won/Lost/Drawn/Tied result;
   * a team cannot hold two overlapping periods of status in one format; ending a status is
     refused while the team has a rating dated on/after the end date (Phase 1: "no published
     rating in a format it no longer holds"), and it sets `needs_recompute`;
   * changing or closing a team spell may not orphan the player's appearances for that team;
   * correcting a player's per-match figures sets `needs_recompute` on his team's rating.
   MySQL has no deferred constraints, so "exactly two teams" is enforced as "at most two"
   on insert; every match in `populate.sql` has exactly two.
10. **Derived values computed, not stored** (as Team 32 decided): team rating
    `ROUND(points/matches)`, every rank via `RANK() OVER`, age, career runs and wickets,
    and the all-rounder rating `FLOOR(batting × bowling / 1000)`. We checked the
    all-rounder formula against the website's all-rounder tables: it matched every player.
    View `v_team_rating` exposes the derived team rating.
11. **Self-supervision CHECK dropped from `app_user`.** MySQL does not allow a CHECK on a
    column used by an FK with a referential action (`ON DELETE SET NULL`).
12. **How a ranking table "as of a date" is assembled.** The ICC republishes the full
    table on each rank date, while our admin form publishes one row at a time. A table as
    of date D is therefore the latest full publication on or before D plus any newer
    single rows, taking each team's or player's newest row. With only the scraped data this
    is exactly the website's table. A rating published through the app joins the current
    table instead of replacing it.
13. **Delete rules chosen:** RESTRICT for history (ratings, appearances, participations,
    represents → team, members → teams). CASCADE for owned rows (roles, retirements,
    statuses, represents → player, participations and subclass rows → match). SET NULL for
    a removed supervisor. ON UPDATE CASCADE everywhere.

## Features

Each item below is reachable from the navigation bar, a link, a filter or a form.
Every query runs as raw parameterised SQL in `src/queries.py`.

### Queries (read)

1. **Team rankings:** *Team Rankings* (`/rankings/teams?gender=M&format=TEST&date=…`). Choose
   Men's/Women's and Test/ODI/T20I with the tabs, and *Latest* or a past rank date in the date box. Shows
   position, movement since the previous snapshot, matches, points and rating
   (`ROUND(points/matches)`, `RANK() OVER`).
2. **Player rankings, including all-rounders:** *Player Rankings*
   (`/rankings/players?gender=W&format=ODI&discipline=batting|bowling|allrounder&date=…`).
   Batting and bowling come from stored ratings. All-rounder is derived (batting × bowling ÷
   1000) with a self-join. Players retired from that format are excluded.
3. **Search:** search bar on every page (`/search?q=…`). Players whose name, team or role
   partly matches (e.g. "koh" finds Kohli, "keeper" finds wicket-keepers), and teams whose
   name or code matches, with their current format status.
4. **Player profile:** click any player (`/players/<id>`). Shows role, age (from DOB),
   styles, retired formats, current rating and rank in every table, rating history with
   change (`LAG`), career runs and wickets per format (`SUM` over appearances), recent
   matches and team history.
5. **Team profile:** click any team (`/teams/<id>`). Shows format-status history, rating trend
   with change from the previous snapshot, win/loss record per format, top performers,
   squad and matches.
6. **Matches and scorecards:** *Matches* (`/matches?format=&status=&gender=`) and click a
   match (`/matches/<id>`). Filter by format, status and gender. A match page shows both
   teams, venue, result and each player's batting and bowling figures.
7. **Head-to-head:** *Head-to-Head* (`/head-to-head?team1=4&team2=5&format=ODI`). Shows
   wins, losses, draws, ties and no-results between two teams, with the list of matches.
8. **Player comparison:** *Player Comparison* (`/rankings/player-comparison?p1=…&p2=…`).
   Shows the two players' latest ratings side by side per format and discipline, with
   recorded runs and wickets.
9. **Biggest movers:** *Movers* (`/rankings/movers?…&from=…&to=…`). Shows the players who
   improved most between two chosen rank dates.
10. **Series report:** *Series* then a series (`/series/<id>`). Shows the series' matches,
    top run-scorers and wicket-takers, and each team's rating before vs after the series.
11. **Statistics:** *Stats* (`/stats?format=TEST&since=…`). Shows the highest, lowest and
    average team rating per table and date, teams with no recorded match in a format since
    a date, and ranked teams per ICC member grouped by format.
12. **Analyst workload:** *Admin* (`/admin`). Shows rating rows published per user per
    month, grouped under their supervisor (recursive `app_user` join).

### Updates (write)

13. **Create – publish a team rating snapshot:** team page → *Admin actions → Publish
    rating snapshot*, or *Admin* (`POST /ratings/team/new`). `INSERT INTO team_rating`.
    Rejected for `matches = 0`, a team without that format status, a women's Test row, or a
    duplicate.
14. **Create – publish a player rating:** *Admin → Publish a player rating*
    (`POST /ratings/player/new`). `INSERT INTO player_rating`. Rejected outside 0–1000
    (e.g. 1500), for women's Test, or for a duplicate.
15. **Create – add a player:** *Admin → Add a player* (`POST /players/new`). One transaction
    inserts `player`, `player_role` and `represents`. A gender mismatch with the team, or a
    duplicate id or identity, rolls everything back.
16. **Update – change a match result:** match page → *Change match result*
    (`POST /matches/<id>/result`). Runs `UPDATE matches` and `UPDATE participates_in` in one
    transaction. Inconsistent results (both Won) are rejected, and a change sets
    `needs_recompute` on both teams' latest rating, which then shows a badge on the rankings
    table.
17. **Update – retire a player from a format:** player page → *Retire from a format*
    (`POST /players/<id>/retire`). The player disappears from that format's current table
    while keeping all history. Refused if the player appeared in that format after the date.
18. **Update – change a player's team:** player page → *Change team*
    (`POST /players/<id>/team`). Runs `UPDATE represents SET to_date` on the old spell plus an
    insert of the new spell, atomically.
19. **Update – end a team's format status:** team page → *End a format status*
    (`POST /teams/<id>/status/end`). `UPDATE has_status_in SET status_end_date`. This is refused
    while the team has a rating dated on/after the end date. It flags the latest rating for
    recompute, and after it new ratings in that format are rejected (e.g. end Zimbabwe's Test
    status, then try to publish a Zimbabwe Test snapshot).
20. **Update – correct a rating snapshot:** team page → rating trend → *edit*
    (`POST /teams/<id>/rating/edit`). `UPDATE team_rating` and clears `needs_recompute`.
21. **Delete – delete a match:** match page → *Delete match* (`POST /matches/<id>/delete`).
    `DELETE FROM matches`. Works for Scheduled/Abandoned matches, and participations cascade.
    A Completed match is refused with a message.
22. **Delete – delete a rating snapshot:** team page → rating trend → *delete*
    (`POST /teams/<id>/rating/delete`). `DELETE FROM team_rating`.
23. **Delete – delete a player:** player page → *Delete player*
    (`POST /players/<id>/delete`). Refused (RESTRICT) for players with ratings or
    appearances. Works for a newly added player.

A JSON API backed by the same queries is also available: `/api/rankings/teams?gender=&format=&date=`
and `/api/search?q=`.

Invalid IDs show a 404 page. Empty results show "No … found" messages. Every database
error (CHECK, FK, trigger) is shown as a red message containing MySQL's reason.

## Repository layout

```
README.md          this file
phase3.pdf         Team 32's Phase 3 report on our Mini World
src/
  schema.sql       database, 17 tables, keys, checks, 16 triggers, 2 views
  populate.sql     data from www.icc-cricket.com (generated by tools/build_populate.py)
  app.py           Flask entry point (routes)
  db.py            connection settings + query/transaction helpers (PyMySQL)
  queries.py       every SQL statement of the app
  requirements.txt
  templates/, static/
```

Project repository only (not in the zip): `tools/` (data fetchers, the `populate.sql` generator,
`package.py`), `VIDEO_SCRIPT.md` and `demo_queries.sql` (video demo aids).
