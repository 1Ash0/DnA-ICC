-- =====================================================================
-- Video demo: run each block in the mysql client BEFORE and AFTER the
-- matching UI action (same query both times).   mysql -u root -p icc_rankings
-- =====================================================================
USE icc_rankings;

-- [13] CREATE team rating  (Ireland Test snapshot)
SELECT team_id, format_code, as_of_date, matches, points, ROUND(points/matches) AS rating, published_by
  FROM team_rating WHERE team_id = 13 AND format_code = 'TEST';

-- [14] CREATE player rating  (Abhishek Sharma, T20I batting)
SELECT player_id, format_code, discipline, as_of_date, rating_points
  FROM player_rating WHERE player_id = 66799 AND format_code = 'T20I' ORDER BY as_of_date;

-- [15] CREATE player (+ role + team spell, one transaction)   and [18] change team
SELECT p.player_id, p.first_name, p.last_name, r.team_id, r.from_date, r.to_date, pr.playing_role
  FROM player p LEFT JOIN represents r USING (player_id) LEFT JOIN player_role pr USING (player_id)
 WHERE p.player_id = 900001;

-- [16] UPDATE match result  and [20] correct rating (needs_recompute flag)
SELECT match_id, team_id, total_runs, result FROM participates_in WHERE match_id = 271652;
SELECT team_id, format_code, as_of_date, matches, points, needs_recompute
  FROM team_rating WHERE team_id IN (4, 5) AND format_code = 'ODI' AND as_of_date = '2026-11-07';

-- [17] UPDATE retire player from a format
SELECT * FROM player_retired_format WHERE player_id = 66799;

-- [19] UPDATE end a team's format status  (Zimbabwe men)
SELECT * FROM has_status_in WHERE team_id = 10 ORDER BY format_code, status_since;
SELECT as_of_date, needs_recompute FROM team_rating WHERE team_id = 10 AND format_code = 'TEST' ORDER BY as_of_date;

-- [21] DELETE scheduled match (participations cascade)
SELECT m.match_id, m.status, m.match_date, p.team_id
  FROM matches m LEFT JOIN participates_in p USING (match_id) WHERE m.match_id IN (274664, 271652);

-- [22] DELETE rating snapshot  -> re-run the [13] query
-- [23] DELETE player           -> re-run the [15] query
