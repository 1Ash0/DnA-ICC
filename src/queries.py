"""All raw SQL of the application. Every user value is passed as a %s parameter."""
from db import query, query_one, execute

FORMATS = ("TEST", "ODI", "T20I")
GENDERS = ("M", "W")
DISCIPLINES = {"batting": "Batting", "bowling": "Bowling", "allrounder": "All-rounder"}


# ============================================================ helpers
def rank_dates_team(gender, fmt):
    return [r["as_of_date"] for r in query(
        "SELECT DISTINCT tr.as_of_date FROM team_rating tr JOIN team t ON t.team_id = tr.team_id "
        "WHERE t.gender = %s AND tr.format_code = %s ORDER BY tr.as_of_date DESC", (gender, fmt))]


def rank_dates_player(gender, fmt, discipline):
    disc = "Batting" if discipline == "allrounder" else DISCIPLINES[discipline]
    return [r["as_of_date"] for r in query(
        "SELECT DISTINCT pr.as_of_date FROM player_rating pr JOIN player p ON p.player_id = pr.player_id "
        "WHERE p.gender = %s AND pr.format_code = %s AND pr.discipline = %s ORDER BY pr.as_of_date DESC",
        (gender, fmt, disc))]


# ============================================================ Q1 team rankings
# A ranking table "as of D" = the latest FULL publication on or before D (a date on which at
# least MIN_TABLE rows were published), plus any single-row snapshots published after it,
# keeping each team's/player's newest row.  Ratings carry forward like on the ICC site.
MIN_TABLE = 5

TEAM_RANKINGS_SQL = """
WITH rows_ AS (
    SELECT tr.team_id, tr.as_of_date, tr.matches, tr.points, tr.needs_recompute,
           ROUND(tr.points / tr.matches) AS rating
      FROM team_rating tr JOIN team t ON t.team_id = tr.team_id
     WHERE t.gender = %s AND tr.format_code = %s AND tr.as_of_date <= %s),
pub AS (SELECT as_of_date AS d FROM rows_ GROUP BY as_of_date HAVING COUNT(*) >= %s),
b AS (SELECT MAX(d) AS cur_d, (SELECT MAX(x.d) FROM pub x WHERE x.d < (SELECT MAX(d) FROM pub)) AS prev_d
        FROM pub),
cur AS (SELECT r.*, ROW_NUMBER() OVER (PARTITION BY r.team_id ORDER BY r.as_of_date DESC) AS rn
          FROM rows_ r JOIN b ON r.as_of_date >= b.cur_d),
prv AS (SELECT r.*, ROW_NUMBER() OVER (PARTITION BY r.team_id ORDER BY r.as_of_date DESC) AS rn
          FROM rows_ r JOIN b ON r.as_of_date >= b.prev_d AND r.as_of_date < b.cur_d),
rc AS (SELECT c.*, RANK() OVER (ORDER BY c.rating DESC, c.points DESC) AS pos FROM cur c WHERE c.rn = 1),
rp AS (SELECT p.*, RANK() OVER (ORDER BY p.rating DESC, p.points DESC) AS pos FROM prv p WHERE p.rn = 1)
SELECT rc.pos AS rank_position, t.team_id, t.team_name, t.team_code, m.short_code,
       rc.matches, rc.points, rc.rating, rc.as_of_date, rc.needs_recompute,
       MAX(rc.as_of_date) OVER () AS table_date,
       CAST(rp.pos AS SIGNED) - CAST(rc.pos AS SIGNED) AS movement
  FROM rc
  JOIN team t ON t.team_id = rc.team_id
  JOIN icc_member m ON m.member_id = t.member_id
  LEFT JOIN rp ON rp.team_id = rc.team_id
 ORDER BY rc.pos, t.team_name
 LIMIT %s
"""


def team_rankings(gender, fmt, date, limit=200):
    return query(TEAM_RANKINGS_SQL, (gender, fmt, date, MIN_TABLE, limit))


# ============================================================ Q2 player rankings
# rows_ keeps only players eligible on date D: retired players leave that format's
# tables (eligibility, not deletion) but keep all their history.
PLAYER_ROWS_CTE = """
rows_ AS (
    SELECT pr.player_id, pr.discipline, pr.as_of_date, pr.rating_points
      FROM player_rating pr JOIN player p ON p.player_id = pr.player_id
     WHERE p.gender = %s AND pr.format_code = %s AND pr.discipline IN (%s, %s) AND pr.as_of_date <= %s
       AND NOT EXISTS (SELECT 1 FROM player_retired_format rf
                        WHERE rf.player_id = pr.player_id AND rf.format_code = pr.format_code
                          AND rf.retired_on <= %s)),
pub AS (SELECT discipline, as_of_date AS d FROM rows_ GROUP BY discipline, as_of_date HAVING COUNT(*) >= %s),
b AS (SELECT p1.discipline, MAX(p1.d) AS cur_d,
             (SELECT MAX(p2.d) FROM pub p2 WHERE p2.discipline = p1.discipline
                AND p2.d < (SELECT MAX(p3.d) FROM pub p3 WHERE p3.discipline = p1.discipline)) AS prev_d
        FROM pub p1 GROUP BY p1.discipline),
cur AS (SELECT r.*, ROW_NUMBER() OVER (PARTITION BY r.player_id, r.discipline ORDER BY r.as_of_date DESC) AS rn
          FROM rows_ r JOIN b ON b.discipline = r.discipline AND r.as_of_date >= b.cur_d),
prv AS (SELECT r.*, ROW_NUMBER() OVER (PARTITION BY r.player_id, r.discipline ORDER BY r.as_of_date DESC) AS rn
          FROM rows_ r JOIN b ON b.discipline = r.discipline
                             AND r.as_of_date >= b.prev_d AND r.as_of_date < b.cur_d)"""

PLAYER_RANKINGS_SQL = "WITH" + PLAYER_ROWS_CTE + """,
rc AS (SELECT c.*, RANK() OVER (ORDER BY c.rating_points DESC) AS pos FROM cur c WHERE c.rn = 1),
rp AS (SELECT p.*, RANK() OVER (ORDER BY p.rating_points DESC) AS pos FROM prv p WHERE p.rn = 1)
SELECT rc.pos AS rank_position, p.player_id, p.first_name, p.last_name, rc.rating_points, rc.as_of_date,
       MAX(rc.as_of_date) OVER () AS table_date,
       t.team_id, t.team_name, m.short_code,
       CAST(rp.pos AS SIGNED) - CAST(rc.pos AS SIGNED) AS movement
  FROM rc
  JOIN player p ON p.player_id = rc.player_id
  LEFT JOIN represents r ON r.player_id = p.player_id AND r.to_date IS NULL
  LEFT JOIN team t ON t.team_id = r.team_id
  LEFT JOIN icc_member m ON m.member_id = t.member_id
  LEFT JOIN rp ON rp.player_id = rc.player_id
 ORDER BY rc.pos, p.last_name
 LIMIT %s
"""

# all-rounder index is derived: batting points x bowling points / 1000 (ICC FAQ formula;
# matches the website's all-rounder tables exactly)
ALLROUNDER_SQL = "WITH" + PLAYER_ROWS_CTE + """,
idx AS (SELECT bt.player_id, FLOOR(bt.rating_points * bw.rating_points / 1000) AS rating_points,
               bt.rating_points AS bat_points, bw.rating_points AS bowl_points,
               GREATEST(bt.as_of_date, bw.as_of_date) AS as_of_date
          FROM cur bt
          JOIN cur bw ON bw.player_id = bt.player_id AND bw.discipline = 'Bowling' AND bw.rn = 1
         WHERE bt.discipline = 'Batting' AND bt.rn = 1)
SELECT RANK() OVER (ORDER BY i.rating_points DESC) AS rank_position, p.player_id, p.first_name,
       p.last_name, i.rating_points, i.bat_points, i.bowl_points, i.as_of_date,
       MAX(i.as_of_date) OVER () AS table_date,
       t.team_id, t.team_name, m.short_code, NULL AS movement
  FROM idx i
  JOIN player p ON p.player_id = i.player_id
  LEFT JOIN represents r ON r.player_id = p.player_id AND r.to_date IS NULL
  LEFT JOIN team t ON t.team_id = r.team_id
  LEFT JOIN icc_member m ON m.member_id = t.member_id
 ORDER BY rank_position, p.last_name
 LIMIT %s
"""


def player_rankings(gender, fmt, discipline, date, limit=100):
    if discipline == "allrounder":
        return query(ALLROUNDER_SQL, (gender, fmt, "Batting", "Bowling", date, date, MIN_TABLE, limit))
    disc = DISCIPLINES[discipline]
    return query(PLAYER_RANKINGS_SQL, (gender, fmt, disc, disc, date, date, MIN_TABLE, limit))


# ============================================================ Q3 player profile
def player(pid):
    return query_one("""
        SELECT p.*, TIMESTAMPDIFF(YEAR, p.date_of_birth, CURDATE()) AS age,
               t.team_id, t.team_name, m.short_code, r.from_date
          FROM player p
          LEFT JOIN represents r ON r.player_id = p.player_id AND r.to_date IS NULL
          LEFT JOIN team t ON t.team_id = r.team_id
          LEFT JOIN icc_member m ON m.member_id = t.member_id
         WHERE p.player_id = %s""", (pid,))


def player_roles(pid):
    return [r["playing_role"] for r in query(
        "SELECT playing_role FROM player_role WHERE player_id = %s ORDER BY playing_role", (pid,))]


def player_retired(pid):
    return query("SELECT format_code, retired_on FROM player_retired_format WHERE player_id = %s "
                 "ORDER BY retired_on", (pid,))


def player_team_history(pid):
    return query("""SELECT r.team_id, t.team_name, r.from_date, r.to_date
                      FROM represents r JOIN team t ON t.team_id = r.team_id
                     WHERE r.player_id = %s ORDER BY r.from_date DESC""", (pid,))


def player_current_ranks(pid):
    """Current rating and rank of the player in every table (same carry-forward rule as Q2)."""
    return query("""
        WITH rows_ AS (
            SELECT pr.player_id, pr.format_code, pr.discipline, pr.as_of_date, pr.rating_points
              FROM player_rating pr JOIN player p ON p.player_id = pr.player_id
             WHERE p.gender = (SELECT gender FROM player WHERE player_id = %s)
               AND pr.as_of_date <= CURDATE()
               AND NOT EXISTS (SELECT 1 FROM player_retired_format rf
                                WHERE rf.player_id = pr.player_id AND rf.format_code = pr.format_code
                                  AND rf.retired_on <= CURDATE())),
        pub AS (SELECT format_code, discipline, MAX(as_of_date) AS cur_d
                  FROM (SELECT format_code, discipline, as_of_date FROM rows_
                         GROUP BY format_code, discipline, as_of_date HAVING COUNT(*) >= %s) f
                 GROUP BY format_code, discipline),
        cur AS (SELECT r.*, ROW_NUMBER() OVER (PARTITION BY r.player_id, r.format_code, r.discipline
                                               ORDER BY r.as_of_date DESC) AS rn
                  FROM rows_ r JOIN pub ON pub.format_code = r.format_code
                                       AND pub.discipline = r.discipline AND r.as_of_date >= pub.cur_d),
        ranked AS (SELECT c.*, RANK() OVER (PARTITION BY c.format_code, c.discipline
                                            ORDER BY c.rating_points DESC) AS rank_position
                     FROM cur c WHERE c.rn = 1)
        SELECT format_code, discipline, as_of_date, rating_points, rank_position
          FROM ranked WHERE player_id = %s
         ORDER BY FIELD(format_code, 'TEST', 'ODI', 'T20I'), discipline""", (pid, MIN_TABLE, pid))


def player_rating_history(pid):
    return query("""
        SELECT format_code, discipline, as_of_date, rating_points,
               rating_points - LAG(rating_points) OVER (PARTITION BY format_code, discipline
                                                         ORDER BY as_of_date) AS change_pts
          FROM player_rating WHERE player_id = %s
         ORDER BY FIELD(format_code, 'TEST', 'ODI', 'T20I'), discipline, as_of_date DESC""", (pid,))


def player_career(pid):
    """Career runs and wickets per format, derived from per-match appearances."""
    return query("""
        SELECT m.format_code, COUNT(*) AS matches,
               SUM(a.runs_scored) AS runs, SUM(a.balls_faced) AS balls,
               MAX(a.runs_scored) AS best_score,
               ROUND(SUM(a.runs_scored) * 100 / NULLIF(SUM(a.balls_faced), 0), 1) AS strike_rate,
               SUM(a.wickets_taken) AS wickets, SUM(a.runs_conceded) AS runs_conceded,
               ROUND(SUM(a.runs_conceded) * 6 / NULLIF(SUM(a.balls_bowled), 0), 2) AS economy
          FROM appeared_for a JOIN matches m ON m.match_id = a.match_id
         WHERE a.player_id = %s
         GROUP BY m.format_code
         ORDER BY FIELD(m.format_code, 'TEST', 'ODI', 'T20I')""", (pid,))


def player_appearances(pid):
    return query("""
        SELECT m.match_id, m.match_date, m.format_code, s.series_name, a.batted, a.bowled,
               a.runs_scored, a.balls_faced, a.wickets_taken, a.runs_conceded, a.balls_bowled,
               opp.team_name AS opponent
          FROM appeared_for a
          JOIN matches m ON m.match_id = a.match_id
          JOIN series s ON s.series_id = m.series_id
          JOIN participates_in o ON o.match_id = m.match_id AND o.team_id <> a.team_id
          JOIN team opp ON opp.team_id = o.team_id
         WHERE a.player_id = %s ORDER BY m.match_date DESC""", (pid,))


# ============================================================ Q4 team profile
def team(tid):
    return query_one("""SELECT t.*, m.name AS member_name, m.short_code, m.membership_type, m.region,
                               m.joined_year
                          FROM team t JOIN icc_member m ON m.member_id = t.member_id
                         WHERE t.team_id = %s""", (tid,))


def team_status(tid):
    return query("""SELECT s.format_code, s.status_since, s.status_end_date
                      FROM has_status_in s WHERE s.team_id = %s
                     ORDER BY FIELD(s.format_code, 'TEST', 'ODI', 'T20I'), s.status_since""", (tid,))


def team_rating_trend(tid):
    return query("""
        SELECT tr.format_code, tr.as_of_date, tr.matches, tr.points,
               ROUND(tr.points / tr.matches) AS rating, tr.needs_recompute, u.username AS published_by,
               ROUND(tr.points / tr.matches)
                 - LAG(ROUND(tr.points / tr.matches)) OVER (PARTITION BY tr.format_code
                                                           ORDER BY tr.as_of_date) AS change_pts
          FROM team_rating tr JOIN app_user u ON u.user_id = tr.published_by
         WHERE tr.team_id = %s
         ORDER BY FIELD(tr.format_code, 'TEST', 'ODI', 'T20I'), tr.as_of_date DESC""", (tid,))


def team_record(tid):
    return query("""
        SELECT m.format_code, COUNT(*) AS played,
               SUM(p.result = 'Won') AS won, SUM(p.result = 'Lost') AS lost,
               SUM(p.result = 'Drawn') AS drawn, SUM(p.result = 'Tied') AS tied,
               SUM(p.result = 'No result') AS no_result
          FROM participates_in p JOIN matches m ON m.match_id = p.match_id
         WHERE p.team_id = %s AND m.status = 'Completed'
         GROUP BY m.format_code ORDER BY FIELD(m.format_code, 'TEST', 'ODI', 'T20I')""", (tid,))


def team_top_performers(tid):
    return query("""
        SELECT p.player_id, p.first_name, p.last_name, COUNT(*) AS matches,
               SUM(a.runs_scored) AS runs, SUM(a.wickets_taken) AS wickets
          FROM appeared_for a JOIN player p ON p.player_id = a.player_id
         WHERE a.team_id = %s
         GROUP BY p.player_id, p.first_name, p.last_name
         ORDER BY runs + 20 * wickets DESC LIMIT 10""", (tid,))


def team_squad(tid):
    return query("""
        SELECT p.player_id, p.first_name, p.last_name, p.batting_style, p.bowling_style,
               GROUP_CONCAT(DISTINCT pr.playing_role ORDER BY pr.playing_role SEPARATOR ', ') AS roles
          FROM represents r JOIN player p ON p.player_id = r.player_id
          LEFT JOIN player_role pr ON pr.player_id = p.player_id
         WHERE r.team_id = %s AND r.to_date IS NULL
         GROUP BY p.player_id, p.first_name, p.last_name, p.batting_style, p.bowling_style
         ORDER BY p.last_name""", (tid,))


def team_matches(tid):
    return query("""
        SELECT m.match_id, m.match_date, m.format_code, m.status, p.result, opp.team_name AS opponent,
               m.ground, m.city
          FROM participates_in p
          JOIN matches m ON m.match_id = p.match_id
          JOIN participates_in o ON o.match_id = p.match_id AND o.team_id <> p.team_id
          JOIN team opp ON opp.team_id = o.team_id
         WHERE p.team_id = %s ORDER BY m.match_date DESC""", (tid,))


# ============================================================ Q5 search
def search_players(q):
    like = f"%{q}%"
    return query("""
        SELECT DISTINCT p.player_id, p.first_name, p.middle_name, p.last_name, p.gender,
               t.team_name, t.team_id,
               (SELECT GROUP_CONCAT(playing_role SEPARATOR ', ') FROM player_role x
                 WHERE x.player_id = p.player_id) AS roles
          FROM player p
          LEFT JOIN represents r ON r.player_id = p.player_id AND r.to_date IS NULL
          LEFT JOIN team t ON t.team_id = r.team_id
          LEFT JOIN player_role pr ON pr.player_id = p.player_id
         WHERE CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name) LIKE %s
            OR t.team_name LIKE %s OR pr.playing_role LIKE %s
         ORDER BY p.last_name, p.first_name LIMIT 100""", (like, like, like))


def search_teams(q):
    like = f"%{q}%"
    return query("""
        SELECT t.team_id, t.team_name, t.team_code, t.gender,
               GROUP_CONCAT(CASE WHEN s.status_end_date IS NULL THEN s.format_code END
                            ORDER BY FIELD(s.format_code, 'TEST', 'ODI', 'T20I') SEPARATOR ', ')
                 AS current_status
          FROM team t
          JOIN icc_member m ON m.member_id = t.member_id
          LEFT JOIN has_status_in s ON s.team_id = t.team_id
         WHERE t.team_name LIKE %s OR t.team_code LIKE %s OR m.short_code LIKE %s
         GROUP BY t.team_id, t.team_name, t.team_code, t.gender
         ORDER BY t.team_name LIMIT 50""", (like, like, like))


# ============================================================ Q6 matches
def match_list(fmt, status, gender):
    return query("""
        SELECT m.match_id, m.match_no, m.match_date, m.status, m.format_code, m.ground, m.city,
               s.series_id, s.series_name,
               GROUP_CONCAT(CONCAT(t.team_name, IFNULL(CONCAT(' ', p.total_runs), ''),
                                   IFNULL(CONCAT(' (', p.result, ')'), ''))
                            ORDER BY p.side SEPARATOR '  v  ') AS teams
          FROM matches m
          JOIN series s ON s.series_id = m.series_id
          JOIN participates_in p ON p.match_id = m.match_id
          JOIN team t ON t.team_id = p.team_id
         WHERE (%s = '' OR m.format_code = %s) AND (%s = '' OR m.status = %s)
           AND (%s = '' OR t.gender = %s)
         GROUP BY m.match_id, m.match_no, m.match_date, m.status, m.format_code, m.ground, m.city,
                  s.series_id, s.series_name
         ORDER BY m.match_date DESC, m.match_id DESC""",
                 (fmt, fmt, status, status, gender, gender))


def match(mid):
    return query_one("""
        SELECT m.*, s.series_name, s.series_type, v.country,
               tm.days_played, tm.scheduled_days, lo.overs_per_side, lo.dls_applied
          FROM matches m
          JOIN series s ON s.series_id = m.series_id
          JOIN venue v ON v.ground = m.ground AND v.city = m.city
          LEFT JOIN test_match tm ON tm.match_id = m.match_id
          LEFT JOIN limited_overs_match lo ON lo.match_id = m.match_id
         WHERE m.match_id = %s""", (mid,))


def match_teams(mid):
    return query("""SELECT p.team_id, t.team_name, t.gender, p.side, p.total_runs, p.result
                      FROM participates_in p JOIN team t ON t.team_id = p.team_id
                     WHERE p.match_id = %s ORDER BY p.side""", (mid,))


def match_scorecard(mid):
    return query("""
        SELECT a.team_id, p.player_id, p.first_name, p.last_name, a.batted, a.bowled, a.runs_scored,
               a.balls_faced, a.wickets_taken, a.runs_conceded, a.balls_bowled,
               CONCAT(FLOOR(a.balls_bowled / 6), '.', MOD(a.balls_bowled, 6)) AS overs
          FROM appeared_for a JOIN player p ON p.player_id = a.player_id
         WHERE a.match_id = %s
         ORDER BY a.team_id, a.batted DESC, a.runs_scored DESC""", (mid,))


# ============================================================ Q7 head-to-head
def head_to_head(t1, t2, fmt):
    return query_one("""
        SELECT COUNT(*) AS played,
               SUM(a.result = 'Won') AS t1_won, SUM(b.result = 'Won') AS t2_won,
               SUM(a.result = 'Drawn') AS drawn, SUM(a.result = 'Tied') AS tied,
               SUM(a.result = 'No result') AS no_result
          FROM participates_in a
          JOIN participates_in b ON b.match_id = a.match_id AND b.team_id = %s
          JOIN matches m ON m.match_id = a.match_id
         WHERE a.team_id = %s AND m.status = 'Completed' AND (%s = '' OR m.format_code = %s)""",
                     (t2, t1, fmt, fmt))


def h2h_matches(t1, t2, fmt):
    return query("""
        SELECT m.match_id, m.match_date, m.format_code, a.result AS t1_result, a.total_runs AS t1_runs,
               b.total_runs AS t2_runs, m.ground, m.city
          FROM participates_in a
          JOIN participates_in b ON b.match_id = a.match_id AND b.team_id = %s
          JOIN matches m ON m.match_id = a.match_id
         WHERE a.team_id = %s AND (%s = '' OR m.format_code = %s)
         ORDER BY m.match_date DESC""", (t2, t1, fmt, fmt))


def all_teams(gender=""):
    return query("SELECT team_id, team_name, gender FROM team WHERE (%s = '' OR gender = %s) "
                 "ORDER BY gender, team_name", (gender, gender))


# ============================================================ Q8 comparison
def compare_players(p1, p2):
    return query("""
        SELECT p.player_id, pr.format_code, pr.discipline, pr.rating_points, pr.as_of_date
          FROM player p
          JOIN player_rating pr ON pr.player_id = p.player_id
         WHERE p.player_id IN (%s, %s)
           AND pr.as_of_date = (SELECT MAX(x.as_of_date) FROM player_rating x
                                 WHERE x.player_id = pr.player_id AND x.format_code = pr.format_code
                                   AND x.discipline = pr.discipline)
         ORDER BY FIELD(pr.format_code, 'TEST', 'ODI', 'T20I'), pr.discipline""", (p1, p2))


def players_for_select():
    return query("""SELECT p.player_id, p.first_name, p.last_name, t.team_name
                      FROM player p
                      LEFT JOIN represents r ON r.player_id = p.player_id AND r.to_date IS NULL
                      LEFT JOIN team t ON t.team_id = r.team_id
                     ORDER BY p.last_name, p.first_name""")


# ============================================================ Q9 movers
def rating_movers(gender, fmt, discipline, d_from, d_to, limit=25):
    return query("""
        SELECT p.player_id, p.first_name, p.last_name, t.team_name,
               a.rating_points AS before_pts, b.rating_points AS after_pts,
               b.rating_points - a.rating_points AS gain
          FROM player_rating a
          JOIN player_rating b ON b.player_id = a.player_id AND b.format_code = a.format_code
                              AND b.discipline = a.discipline AND b.as_of_date = %s
          JOIN player p ON p.player_id = a.player_id
          LEFT JOIN represents r ON r.player_id = p.player_id AND r.to_date IS NULL
          LEFT JOIN team t ON t.team_id = r.team_id
         WHERE a.as_of_date = %s AND a.format_code = %s AND a.discipline = %s AND p.gender = %s
         ORDER BY gain DESC, after_pts DESC LIMIT %s""",
                 (d_to, d_from, fmt, DISCIPLINES[discipline], gender, limit))


# ============================================================ Q10 statistics (aggregates)
def format_rating_stats():
    return query("""
        SELECT t.gender, tr.format_code, tr.as_of_date, COUNT(*) AS teams,
               MAX(ROUND(tr.points / tr.matches)) AS highest,
               MIN(ROUND(tr.points / tr.matches)) AS lowest,
               ROUND(AVG(tr.points / tr.matches), 1) AS average
          FROM team_rating tr JOIN team t ON t.team_id = tr.team_id
         GROUP BY t.gender, tr.format_code, tr.as_of_date
         ORDER BY t.gender, FIELD(tr.format_code, 'TEST', 'ODI', 'T20I'), tr.as_of_date DESC""")


def ranked_teams_per_member():
    return query("""
        SELECT m.member_id, m.name, m.membership_type, m.region,
               COUNT(DISTINCT CASE WHEN tr.format_code = 'TEST' THEN t.team_id END) AS test_teams,
               COUNT(DISTINCT CASE WHEN tr.format_code = 'ODI'  THEN t.team_id END) AS odi_teams,
               COUNT(DISTINCT CASE WHEN tr.format_code = 'T20I' THEN t.team_id END) AS t20i_teams
          FROM icc_member m
          JOIN team t ON t.member_id = m.member_id
          LEFT JOIN team_rating tr ON tr.team_id = t.team_id
         GROUP BY m.member_id, m.name, m.membership_type, m.region
        HAVING test_teams + odi_teams + t20i_teams > 0
         ORDER BY test_teams + odi_teams + t20i_teams DESC, m.name""")


def teams_without_matches(fmt, since):
    return query("""
        SELECT t.team_id, t.team_name, t.gender
          FROM team t
          JOIN has_status_in s ON s.team_id = t.team_id AND s.format_code = %s AND s.status_end_date IS NULL
         WHERE EXISTS (SELECT 1 FROM team_rating tr WHERE tr.team_id = t.team_id AND tr.format_code = %s)
           AND NOT EXISTS (SELECT 1 FROM participates_in p JOIN matches m ON m.match_id = p.match_id
                            WHERE p.team_id = t.team_id AND m.format_code = %s AND m.match_date >= %s)
         ORDER BY t.gender, t.team_name""", (fmt, fmt, fmt, since))


# ============================================================ Q11 series report
def series_list():
    return query("""SELECT s.*, COUNT(m.match_id) AS n_matches,
                           GROUP_CONCAT(DISTINCT m.format_code) AS formats
                      FROM series s LEFT JOIN matches m ON m.series_id = s.series_id
                     GROUP BY s.series_id ORDER BY s.start_date DESC""")


def series(sid):
    return query_one("SELECT * FROM series WHERE series_id = %s", (sid,))


def series_top_performers(sid):
    return query("""
        SELECT p.player_id, p.first_name, p.last_name, t.team_name, COUNT(*) AS matches,
               SUM(a.runs_scored) AS runs, SUM(a.wickets_taken) AS wickets
          FROM series s
          JOIN matches m ON m.series_id = s.series_id
          JOIN participates_in pi ON pi.match_id = m.match_id
          JOIN appeared_for a ON a.match_id = m.match_id AND a.team_id = pi.team_id
          JOIN player p ON p.player_id = a.player_id
          JOIN team t ON t.team_id = a.team_id
         WHERE s.series_id = %s
         GROUP BY p.player_id, p.first_name, p.last_name, t.team_name
         ORDER BY runs DESC, wickets DESC LIMIT 15""", (sid,))


def series_rating_impact(sid):
    """Rating of each team before the series started and at the latest snapshot after it."""
    return query("""
        SELECT t.team_id, t.team_name, x.format_code,
               (SELECT ROUND(tr.points / tr.matches) FROM team_rating tr
                 WHERE tr.team_id = t.team_id AND tr.format_code = x.format_code
                   AND tr.as_of_date < s.start_date ORDER BY tr.as_of_date DESC LIMIT 1) AS before_rating,
               (SELECT ROUND(tr.points / tr.matches) FROM team_rating tr
                 WHERE tr.team_id = t.team_id AND tr.format_code = x.format_code
                   AND tr.as_of_date >= s.end_date ORDER BY tr.as_of_date LIMIT 1) AS after_rating
          FROM series s
          JOIN (SELECT DISTINCT m.series_id, m.format_code, p.team_id
                  FROM matches m JOIN participates_in p ON p.match_id = m.match_id
                 WHERE m.series_id = %s) x ON x.series_id = s.series_id
          JOIN team t ON t.team_id = x.team_id
         WHERE s.series_id = %s""", (sid, sid))


def series_matches(sid):
    return match_list_by_series(sid)


def match_list_by_series(sid):
    return query("""
        SELECT m.match_id, m.match_no, m.match_date, m.status, m.format_code, m.ground, m.city,
               GROUP_CONCAT(CONCAT(t.team_name, IFNULL(CONCAT(' ', p.total_runs), ''),
                                   IFNULL(CONCAT(' (', p.result, ')'), '')) ORDER BY p.side SEPARATOR '  v  ') AS teams
          FROM matches m JOIN participates_in p ON p.match_id = m.match_id JOIN team t ON t.team_id = p.team_id
         WHERE m.series_id = %s
         GROUP BY m.match_id, m.match_no, m.match_date, m.status, m.format_code, m.ground, m.city
         ORDER BY m.match_no""", (sid,))


# ============================================================ Q12 analyst workload
def analyst_workload():
    return query("""
        SELECT COALESCE(sup.username, '(none)') AS supervisor, u.username, u.role,
               DATE_FORMAT(x.as_of_date, '%%Y-%%m') AS month, COUNT(*) AS snapshots
          FROM app_user u
          LEFT JOIN app_user sup ON sup.user_id = u.supervisor_id
          JOIN (SELECT published_by, as_of_date FROM team_rating
                UNION ALL SELECT published_by, as_of_date FROM player_rating) x
            ON x.published_by = u.user_id
         GROUP BY supervisor, u.username, u.role, month
         ORDER BY supervisor, u.username, month""")


def users():
    return query("""SELECT u.user_id, u.username, u.email, u.role, s.username AS supervisor
                      FROM app_user u LEFT JOIN app_user s ON s.user_id = u.supervisor_id
                     ORDER BY u.user_id""")


# ============================================================ WRITES
def create_player(pid, first, middle, last, dob, gender, bat, bowl, role, team_id, from_date):
    """CREATE: player + role + representation in one transaction."""
    return execute([
        ("INSERT INTO player (player_id, first_name, middle_name, last_name, date_of_birth, gender, "
         "batting_style, bowling_style) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
         (pid, first, middle, last, dob, gender, bat, bowl)),
        ("INSERT INTO player_role (player_id, playing_role) VALUES (%s, %s)", (pid, role)),
        ("INSERT INTO represents (player_id, team_id, from_date, to_date) VALUES (%s, %s, %s, NULL)",
         (pid, team_id, from_date)),
    ])


def publish_team_rating(team_id, fmt, date, matches, points, trigger, user_id):
    """CREATE: publish one team rating snapshot row."""
    return execute([(
        "INSERT INTO team_rating (team_id, format_code, as_of_date, matches, points, update_trigger, "
        "needs_recompute, published_by) VALUES (%s, %s, %s, %s, %s, %s, FALSE, %s)",
        (team_id, fmt, date, matches, points, trigger, user_id))])


def publish_player_rating(pid, fmt, disc, date, points, user_id):
    """CREATE: one player rating snapshot row."""
    return execute([(
        "INSERT INTO player_rating (player_id, format_code, discipline, as_of_date, rating_points, "
        "published_by) VALUES (%s, %s, %s, %s, %s, %s)", (pid, fmt, disc, date, points, user_id))])


def update_match_result(mid, status, results):
    """UPDATE: change match status and both teams' results/runs (one transaction).
    results = [(team_id, total_runs, result), (team_id, total_runs, result)]"""
    stmts = [("UPDATE matches SET status = %s WHERE match_id = %s", (status, mid))]
    # clear first so the consistency trigger compares the two new values, not old vs new
    stmts += [("UPDATE participates_in SET result = NULL WHERE match_id = %s AND team_id = %s",
               (mid, tid)) for tid, _, _ in results]
    stmts += [("UPDATE participates_in SET total_runs = %s, result = %s WHERE match_id = %s AND team_id = %s",
               (runs, res, mid, tid)) for tid, runs, res in results]
    return execute(stmts)


def retire_player(pid, fmt, date):
    """UPDATE (of the multi-valued retired_formats attribute): adds a retirement row."""
    return execute([("INSERT INTO player_retired_format (player_id, format_code, retired_on) "
                     "VALUES (%s, %s, %s)", (pid, fmt, date))])


def change_player_team(pid, new_team, date):
    """UPDATE: close the current spell (to_date) and open a new one, atomically."""
    return execute([
        ("UPDATE represents SET to_date = DATE_SUB(%s, INTERVAL 1 DAY) "
         "WHERE player_id = %s AND to_date IS NULL", (date, pid)),
        ("INSERT INTO represents (player_id, team_id, from_date, to_date) VALUES (%s, %s, %s, NULL)",
         (pid, new_team, date)),
    ])


def end_team_status(tid, fmt, end_date):
    """UPDATE: end a format status by writing its end date (history is kept)."""
    return execute([("UPDATE has_status_in SET status_end_date = %s "
                     "WHERE team_id = %s AND format_code = %s AND status_end_date IS NULL",
                     (end_date, tid, fmt))])


def correct_team_rating(tid, fmt, date, matches, points):
    """UPDATE: correct a published team snapshot and clear the recompute flag."""
    return execute([("UPDATE team_rating SET matches = %s, points = %s, needs_recompute = FALSE "
                     "WHERE team_id = %s AND format_code = %s AND as_of_date = %s",
                     (matches, points, tid, fmt, date))])


def delete_match(mid):
    """DELETE: only Scheduled/Abandoned (trigger); participations cascade."""
    return execute([("DELETE FROM matches WHERE match_id = %s", (mid,))])


def delete_team_rating(tid, fmt, date):
    """DELETE: remove one team rating snapshot."""
    return execute([("DELETE FROM team_rating WHERE team_id = %s AND format_code = %s AND as_of_date = %s",
                     (tid, fmt, date))])


def delete_player(pid):
    """DELETE: refused by RESTRICT FKs when the player has appearances or ratings."""
    return execute([("DELETE FROM player WHERE player_id = %s", (pid,))])
