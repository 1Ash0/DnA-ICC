-- =====================================================================
--  ICC Rankings  -  Phase 4 schema (MySQL 8.0.16+)
--  Baseline: Team 32's Phase 3 Stage D model (17 relations, 3NF).
--  Run:  mysql -u root -p < schema.sql
-- =====================================================================
DROP DATABASE IF EXISTS icc_rankings;
CREATE DATABASE icc_rankings CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE icc_rankings;

-- ---------------------------------------------------------------------
-- Parent / reference tables
-- ---------------------------------------------------------------------
CREATE TABLE icc_member (
    member_id        INT          NOT NULL AUTO_INCREMENT,
    short_code       VARCHAR(5)   NOT NULL,
    name             VARCHAR(60)  NOT NULL,
    membership_type  ENUM('Full','Associate') NOT NULL,
    region           ENUM('Africa','Americas','Asia','East Asia-Pacific','Europe') NOT NULL,
    joined_year      SMALLINT     NULL,
    PRIMARY KEY (member_id),
    CONSTRAINT uq_member_short UNIQUE (short_code),
    CONSTRAINT uq_member_name  UNIQUE (name),
    CONSTRAINT ck_member_year  CHECK (joined_year IS NULL OR joined_year BETWEEN 1909 AND 2100)
);

CREATE TABLE format (
    format_code        VARCHAR(4)  NOT NULL,
    format_name        VARCHAR(40) NOT NULL,
    overs_per_innings  TINYINT     NULL,            -- NULL for Test
    PRIMARY KEY (format_code),
    CONSTRAINT uq_format_name UNIQUE (format_name),
    CONSTRAINT ck_format_code CHECK (format_code IN ('TEST','ODI','T20I')),
    CONSTRAINT ck_format_overs CHECK ((format_code = 'TEST' AND overs_per_innings IS NULL)
                                   OR (format_code <> 'TEST' AND overs_per_innings > 0))
);

CREATE TABLE venue (
    ground   VARCHAR(100) NOT NULL,
    city     VARCHAR(60)  NOT NULL,
    country  VARCHAR(60)  NOT NULL,
    PRIMARY KEY (ground, city)
);

CREATE TABLE series (
    series_id    INT          NOT NULL,          -- ICC series id
    series_name  VARCHAR(150) NOT NULL,
    start_date   DATE         NOT NULL,
    end_date     DATE         NOT NULL,
    series_type  ENUM('Bilateral','Tournament','Tri-series','One-off') NOT NULL,
    PRIMARY KEY (series_id),
    CONSTRAINT uq_series_name_start UNIQUE (series_name, start_date),
    CONSTRAINT ck_series_dates CHECK (end_date >= start_date)
);

CREATE TABLE app_user (
    user_id        INT          NOT NULL AUTO_INCREMENT,
    username       VARCHAR(40)  NOT NULL,
    email          VARCHAR(120) NOT NULL,
    role           ENUM('Admin','Analyst') NOT NULL,
    supervisor_id  INT          NULL,
    PRIMARY KEY (user_id),
    CONSTRAINT uq_user_username UNIQUE (username),
    CONSTRAINT uq_user_email    UNIQUE (email),
    CONSTRAINT ck_user_email    CHECK (email LIKE '%_@_%._%'),
    CONSTRAINT fk_user_supervisor FOREIGN KEY (supervisor_id) REFERENCES app_user(user_id)
        ON DELETE SET NULL ON UPDATE CASCADE
);

-- ---------------------------------------------------------------------
-- Teams and players
-- ---------------------------------------------------------------------
CREATE TABLE team (
    team_id    INT          NOT NULL,            -- ICC team id
    team_code  VARCHAR(8)   NOT NULL,            -- e.g. IND-M
    team_name  VARCHAR(60)  NOT NULL,
    gender     ENUM('M','W') NOT NULL,
    member_id  INT          NOT NULL,
    PRIMARY KEY (team_id),
    CONSTRAINT uq_team_code UNIQUE (team_code),
    CONSTRAINT uq_team_member_gender UNIQUE (member_id, gender),
    CONSTRAINT fk_team_member FOREIGN KEY (member_id) REFERENCES icc_member(member_id)
        ON DELETE RESTRICT ON UPDATE CASCADE
);

CREATE TABLE has_status_in (
    team_id          INT        NOT NULL,
    format_code      VARCHAR(4) NOT NULL,
    status_since     DATE       NOT NULL,
    status_end_date  DATE       NULL,            -- NULL = status currently held
    PRIMARY KEY (team_id, format_code, status_since),
    CONSTRAINT ck_status_dates CHECK (status_end_date IS NULL OR status_end_date > status_since),
    CONSTRAINT fk_status_team FOREIGN KEY (team_id) REFERENCES team(team_id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_status_format FOREIGN KEY (format_code) REFERENCES format(format_code)
        ON DELETE RESTRICT ON UPDATE CASCADE
);

CREATE TABLE player (
    player_id      INT          NOT NULL,        -- ICC player id
    first_name     VARCHAR(60)  NOT NULL,
    middle_name    VARCHAR(100) NULL,
    last_name      VARCHAR(60)  NOT NULL,
    date_of_birth  DATE         NULL,
    gender         ENUM('M','W') NOT NULL,
    batting_style  VARCHAR(30)  NULL,
    bowling_style  VARCHAR(50)  NULL,
    PRIMARY KEY (player_id),
    CONSTRAINT uq_player_identity UNIQUE (first_name, last_name, date_of_birth, gender),
    CONSTRAINT ck_player_dob CHECK (date_of_birth IS NULL OR date_of_birth >= '1900-01-01')
);
CREATE INDEX ix_player_last ON player(last_name);

CREATE TABLE player_role (
    player_id     INT NOT NULL,
    playing_role  ENUM('Batter','Bowler','All-rounder','Wicket-keeper','Captain') NOT NULL,
    PRIMARY KEY (player_id, playing_role),
    CONSTRAINT fk_role_player FOREIGN KEY (player_id) REFERENCES player(player_id)
        ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE player_retired_format (
    player_id    INT        NOT NULL,
    format_code  VARCHAR(4) NOT NULL,
    retired_on   DATE       NOT NULL,
    PRIMARY KEY (player_id, format_code),
    CONSTRAINT fk_retired_player FOREIGN KEY (player_id) REFERENCES player(player_id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_retired_format FOREIGN KEY (format_code) REFERENCES format(format_code)
        ON DELETE RESTRICT ON UPDATE CASCADE
);

CREATE TABLE represents (
    player_id  INT  NOT NULL,
    team_id    INT  NOT NULL,
    from_date  DATE NOT NULL,
    to_date    DATE NULL,                         -- NULL = current
    PRIMARY KEY (player_id, team_id, from_date),
    CONSTRAINT ck_represents_dates CHECK (to_date IS NULL OR to_date >= from_date),
    CONSTRAINT fk_rep_player FOREIGN KEY (player_id) REFERENCES player(player_id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_rep_team FOREIGN KEY (team_id) REFERENCES team(team_id)
        ON DELETE RESTRICT ON UPDATE CASCADE
);

-- ---------------------------------------------------------------------
-- Matches (MATCH is a reserved word, so the table is `matches`)
-- ---------------------------------------------------------------------
CREATE TABLE matches (
    match_id     INT          NOT NULL,          -- ICC match id
    match_no     SMALLINT     NOT NULL,          -- ordinal within the series
    match_date   DATE         NOT NULL,
    status       ENUM('Scheduled','Completed','Abandoned') NOT NULL DEFAULT 'Scheduled',
    ground       VARCHAR(100) NOT NULL,
    city         VARCHAR(60)  NOT NULL,
    series_id    INT          NOT NULL,
    format_code  VARCHAR(4)   NOT NULL,
    PRIMARY KEY (match_id),
    CONSTRAINT uq_match_series_no UNIQUE (series_id, match_no),
    CONSTRAINT ck_match_no CHECK (match_no > 0),
    CONSTRAINT fk_match_venue FOREIGN KEY (ground, city) REFERENCES venue(ground, city)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_match_series FOREIGN KEY (series_id) REFERENCES series(series_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_match_format FOREIGN KEY (format_code) REFERENCES format(format_code)
        ON DELETE RESTRICT ON UPDATE CASCADE
);
CREATE INDEX ix_match_date ON matches(match_date);

CREATE TABLE test_match (
    match_id        INT     NOT NULL,
    scheduled_days  TINYINT NOT NULL DEFAULT 5,
    days_played     TINYINT NULL,
    PRIMARY KEY (match_id),
    CONSTRAINT ck_test_days CHECK (scheduled_days BETWEEN 4 AND 6
                                   AND (days_played IS NULL OR days_played BETWEEN 0 AND scheduled_days)),
    CONSTRAINT fk_test_match FOREIGN KEY (match_id) REFERENCES matches(match_id)
        ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE limited_overs_match (
    match_id        INT     NOT NULL,
    overs_per_side  TINYINT NOT NULL,
    dls_applied     BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (match_id),
    CONSTRAINT ck_lo_overs CHECK (overs_per_side BETWEEN 1 AND 50),
    CONSTRAINT fk_lo_match FOREIGN KEY (match_id) REFERENCES matches(match_id)
        ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE participates_in (
    match_id    INT NOT NULL,
    team_id     INT NOT NULL,
    side        ENUM('Home','Away','Neutral') NOT NULL,
    total_runs  SMALLINT NULL,
    result      ENUM('Won','Lost','Drawn','Tied','No result') NULL,   -- NULL until played
    PRIMARY KEY (match_id, team_id),
    CONSTRAINT ck_part_runs CHECK (total_runs IS NULL OR total_runs >= 0),
    CONSTRAINT fk_part_match FOREIGN KEY (match_id) REFERENCES matches(match_id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_part_team FOREIGN KEY (team_id) REFERENCES team(team_id)
        ON DELETE RESTRICT ON UPDATE CASCADE
);
CREATE INDEX ix_part_team ON participates_in(team_id);

CREATE TABLE appeared_for (
    player_id      INT      NOT NULL,
    match_id       INT      NOT NULL,
    team_id        INT      NOT NULL,
    batted         BOOLEAN  NOT NULL DEFAULT FALSE,
    bowled         BOOLEAN  NOT NULL DEFAULT FALSE,
    runs_scored    SMALLINT NOT NULL DEFAULT 0,
    balls_faced    SMALLINT NOT NULL DEFAULT 0,
    wickets_taken  TINYINT  NOT NULL DEFAULT 0,
    runs_conceded  SMALLINT NOT NULL DEFAULT 0,
    balls_bowled   SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, match_id),
    CONSTRAINT ck_app_nonneg CHECK (runs_scored >= 0 AND balls_faced >= 0 AND runs_conceded >= 0
                                    AND balls_bowled >= 0 AND wickets_taken BETWEEN 0 AND 20),
    CONSTRAINT ck_app_batted CHECK (batted OR (runs_scored = 0 AND balls_faced = 0)),
    CONSTRAINT ck_app_bowled CHECK (bowled OR (balls_bowled = 0 AND wickets_taken = 0 AND runs_conceded = 0)),
    CONSTRAINT fk_app_player FOREIGN KEY (player_id) REFERENCES player(player_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_app_match FOREIGN KEY (match_id) REFERENCES matches(match_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    -- the team must be one of the two teams of that match
    CONSTRAINT fk_app_participation FOREIGN KEY (match_id, team_id)
        REFERENCES participates_in(match_id, team_id)
        ON DELETE RESTRICT ON UPDATE CASCADE
);

-- ---------------------------------------------------------------------
-- Weak rating entities
-- ---------------------------------------------------------------------
CREATE TABLE team_rating (
    team_id          INT          NOT NULL,
    format_code      VARCHAR(4)   NOT NULL,
    as_of_date       DATE         NOT NULL,
    matches          SMALLINT     NOT NULL,
    points           INT          NOT NULL,
    update_trigger   ENUM('Weekly','Annual','Match result','Status change') NOT NULL DEFAULT 'Weekly',
    needs_recompute  BOOLEAN      NOT NULL DEFAULT FALSE,
    published_by     INT          NOT NULL,
    PRIMARY KEY (team_id, format_code, as_of_date),
    CONSTRAINT ck_tr_matches CHECK (matches > 0),
    CONSTRAINT ck_tr_points  CHECK (points >= 0),
    CONSTRAINT fk_tr_team FOREIGN KEY (team_id) REFERENCES team(team_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_tr_format FOREIGN KEY (format_code) REFERENCES format(format_code)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_tr_publisher FOREIGN KEY (published_by) REFERENCES app_user(user_id)
        ON DELETE RESTRICT ON UPDATE CASCADE
);
CREATE INDEX ix_tr_lookup ON team_rating(format_code, as_of_date);

CREATE TABLE player_rating (
    player_id      INT        NOT NULL,
    format_code    VARCHAR(4) NOT NULL,
    discipline     ENUM('Batting','Bowling') NOT NULL,
    as_of_date     DATE       NOT NULL,
    rating_points  SMALLINT   NOT NULL,
    published_by   INT        NOT NULL,
    PRIMARY KEY (player_id, format_code, discipline, as_of_date),
    CONSTRAINT ck_pr_points CHECK (rating_points BETWEEN 0 AND 1000),
    CONSTRAINT fk_pr_player FOREIGN KEY (player_id) REFERENCES player(player_id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_pr_format FOREIGN KEY (format_code) REFERENCES format(format_code)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_pr_publisher FOREIGN KEY (published_by) REFERENCES app_user(user_id)
        ON DELETE RESTRICT ON UPDATE CASCADE
);
CREATE INDEX ix_pr_lookup ON player_rating(format_code, discipline, as_of_date);

-- =====================================================================
-- Triggers: rules that keys and CHECKs cannot express
-- =====================================================================
DELIMITER $$

-- Exactly two teams per match, of the same gender
CREATE TRIGGER trg_part_before_insert BEFORE INSERT ON participates_in
FOR EACH ROW
BEGIN
    DECLARE n INT;
    DECLARE other_gender CHAR(1);
    SELECT COUNT(*) INTO n FROM participates_in WHERE match_id = NEW.match_id;
    IF n >= 2 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'A match cannot have more than two teams.';
    END IF;
    SELECT t.gender INTO other_gender
      FROM participates_in p JOIN team t ON t.team_id = p.team_id
     WHERE p.match_id = NEW.match_id LIMIT 1;
    IF other_gender IS NOT NULL
       AND other_gender <> (SELECT gender FROM team WHERE team_id = NEW.team_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Both teams in a match must be of the same gender.';
    END IF;
    IF NEW.result IS NOT NULL AND NEW.result <> 'No result'
       AND (SELECT status FROM matches WHERE match_id = NEW.match_id) <> 'Completed' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only a Completed match can have a Won/Lost/Drawn/Tied result.';
    END IF;
END$$

-- Results of the two teams must agree; a changed result flags both ratings for recompute
CREATE TRIGGER trg_part_before_update BEFORE UPDATE ON participates_in
FOR EACH ROW
BEGIN
    DECLARE other_result VARCHAR(10);
    IF NEW.result IS NOT NULL AND NEW.result <> 'No result'
       AND (SELECT status FROM matches WHERE match_id = NEW.match_id) <> 'Completed' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only a Completed match can have a Won/Lost/Drawn/Tied result.';
    END IF;
    SELECT result INTO other_result FROM participates_in
     WHERE match_id = NEW.match_id AND team_id <> NEW.team_id LIMIT 1;
    IF NEW.result IS NOT NULL AND other_result IS NOT NULL AND NOT (
          (NEW.result = 'Won'  AND other_result = 'Lost')
       OR (NEW.result = 'Lost' AND other_result = 'Won')
       OR (NEW.result = other_result AND NEW.result IN ('Drawn','Tied','No result'))) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Inconsistent result: the other team''s result does not match (e.g. both Won).';
    END IF;
END$$

CREATE TRIGGER trg_part_after_update AFTER UPDATE ON participates_in
FOR EACH ROW
BEGIN
    IF NOT (NEW.result <=> OLD.result) OR NOT (NEW.total_runs <=> OLD.total_runs) THEN
        UPDATE team_rating tr
          JOIN matches m ON m.match_id = NEW.match_id
           SET tr.needs_recompute = TRUE
         WHERE tr.team_id = NEW.team_id
           AND tr.format_code = m.format_code
           AND tr.as_of_date = (SELECT mx FROM (SELECT MAX(as_of_date) AS mx FROM team_rating
                                 WHERE team_id = NEW.team_id AND format_code = m.format_code) x);
    END IF;
END$$

-- Appearances: match Completed, player represents that team on the match date
CREATE TRIGGER trg_app_before_insert BEFORE INSERT ON appeared_for
FOR EACH ROW
BEGIN
    DECLARE st VARCHAR(10);
    DECLARE md DATE;
    SELECT status, match_date INTO st, md FROM matches WHERE match_id = NEW.match_id;
    IF st <> 'Completed' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Appearances can only be recorded for Completed matches.';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM represents r
                    WHERE r.player_id = NEW.player_id AND r.team_id = NEW.team_id
                      AND r.from_date <= md AND (r.to_date IS NULL OR r.to_date >= md)) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Player does not represent that team on the match date.';
    END IF;
END$$

-- Representation: same gender as the team, no overlapping spells
CREATE TRIGGER trg_rep_before_insert BEFORE INSERT ON represents
FOR EACH ROW
BEGIN
    IF (SELECT gender FROM player WHERE player_id = NEW.player_id)
       <> (SELECT gender FROM team WHERE team_id = NEW.team_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Player and team must be of the same gender.';
    END IF;
    IF EXISTS (SELECT 1 FROM represents r
                WHERE r.player_id = NEW.player_id
                  AND r.from_date <= COALESCE(NEW.to_date, '9999-12-31')
                  AND COALESCE(r.to_date, '9999-12-31') >= NEW.from_date) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'New spell overlaps the player''s current team assignment; close it first.';
    END IF;
END$$

-- Retiring: no appearance in that format after the retirement date
CREATE TRIGGER trg_retire_before_insert BEFORE INSERT ON player_retired_format
FOR EACH ROW
BEGIN
    IF EXISTS (SELECT 1 FROM appeared_for a JOIN matches m ON m.match_id = a.match_id
                WHERE a.player_id = NEW.player_id AND m.format_code = NEW.format_code
                  AND m.match_date > NEW.retired_on) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Player has an appearance in this format after the retirement date.';
    END IF;
END$$

-- Team ratings: no women's Test; Test/ODI need the format status on that date
CREATE TRIGGER trg_tr_before_insert BEFORE INSERT ON team_rating
FOR EACH ROW
BEGIN
    IF NEW.format_code = 'TEST' AND (SELECT gender FROM team WHERE team_id = NEW.team_id) = 'W' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Women''s Test teams are not ranked.';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM has_status_in s
                    WHERE s.team_id = NEW.team_id AND s.format_code = NEW.format_code
                      AND s.status_since <= NEW.as_of_date
                      AND (s.status_end_date IS NULL OR s.status_end_date > NEW.as_of_date)) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Team does not hold status in this format on that date.';
    END IF;
END$$

-- Player ratings: no women's Test ratings
CREATE TRIGGER trg_pr_before_insert BEFORE INSERT ON player_rating
FOR EACH ROW
BEGIN
    IF NEW.format_code = 'TEST' AND (SELECT gender FROM player WHERE player_id = NEW.player_id) = 'W' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Women''s Test ratings are not published.';
    END IF;
END$$

-- Deleting a match: only Scheduled or Abandoned (participations cascade)
CREATE TRIGGER trg_match_before_delete BEFORE DELETE ON matches
FOR EACH ROW
BEGIN
    IF OLD.status = 'Completed' THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Completed matches cannot be deleted; mark the match Abandoned instead.';
    END IF;
END$$

-- Removing a format status is done by ending it, never by deleting history
-- (a team delete still removes its statuses: cascaded FK actions do not fire triggers)
CREATE TRIGGER trg_status_before_delete BEFORE DELETE ON has_status_in
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Format status history is kept: set status_end_date instead of deleting.';
END$$

-- A team cannot hold two overlapping periods of status in the same format
CREATE TRIGGER trg_status_before_insert BEFORE INSERT ON has_status_in
FOR EACH ROW
BEGIN
    IF EXISTS (SELECT 1 FROM has_status_in s
                WHERE s.team_id = NEW.team_id AND s.format_code = NEW.format_code
                  AND s.status_since <= COALESCE(NEW.status_end_date, '9999-12-31')
                  AND COALESCE(s.status_end_date, '9999-12-31') > NEW.status_since) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Overlaps an existing status period for this format.';
    END IF;
END$$

-- Ending a status: refused while the team has a rating published on/after the end date
CREATE TRIGGER trg_status_before_update BEFORE UPDATE ON has_status_in
FOR EACH ROW
BEGIN
    IF NEW.status_end_date IS NOT NULL AND EXISTS (
           SELECT 1 FROM team_rating tr
            WHERE tr.team_id = NEW.team_id AND tr.format_code = NEW.format_code
              AND tr.as_of_date >= NEW.status_end_date) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Team has a published rating in this format on or after that end date.';
    END IF;
END$$

-- ...and a status change flags the team's latest rating in that format for recompute
CREATE TRIGGER trg_status_after_update AFTER UPDATE ON has_status_in
FOR EACH ROW
BEGIN
    IF NOT (NEW.status_end_date <=> OLD.status_end_date) THEN
        UPDATE team_rating tr SET tr.needs_recompute = TRUE
         WHERE tr.team_id = NEW.team_id AND tr.format_code = NEW.format_code
           AND tr.as_of_date = (SELECT mx FROM (SELECT MAX(as_of_date) AS mx FROM team_rating
                                 WHERE team_id = NEW.team_id AND format_code = NEW.format_code) x);
    END IF;
END$$

-- A match with recorded appearances must stay Completed
CREATE TRIGGER trg_match_before_update BEFORE UPDATE ON matches
FOR EACH ROW
BEGIN
    IF OLD.status = 'Completed' AND NEW.status <> 'Completed'
       AND EXISTS (SELECT 1 FROM appeared_for WHERE match_id = OLD.match_id) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'This match has player appearances, so it must stay Completed.';
    END IF;
END$$

-- Closing or changing a team spell must not orphan the player's appearances for that team
CREATE TRIGGER trg_rep_before_update BEFORE UPDATE ON represents
FOR EACH ROW
BEGIN
    IF EXISTS (SELECT 1 FROM appeared_for a JOIN matches m ON m.match_id = a.match_id
                WHERE a.player_id = OLD.player_id AND a.team_id = OLD.team_id
                  AND m.match_date >= OLD.from_date
                  AND (OLD.to_date IS NULL OR m.match_date <= OLD.to_date)
                  AND (m.match_date < NEW.from_date OR m.match_date > COALESCE(NEW.to_date, '9999-12-31'))) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'The player has appearances for this team outside the new dates.';
    END IF;
    IF EXISTS (SELECT 1 FROM represents r
                WHERE r.player_id = NEW.player_id
                  AND NOT (r.team_id = OLD.team_id AND r.from_date = OLD.from_date)
                  AND r.from_date <= COALESCE(NEW.to_date, '9999-12-31')
                  AND COALESCE(r.to_date, '9999-12-31') >= NEW.from_date) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'The changed spell overlaps another team spell.';
    END IF;
END$$

-- A corrected player performance flags his team's latest rating in that format
CREATE TRIGGER trg_app_after_update AFTER UPDATE ON appeared_for
FOR EACH ROW
BEGIN
    UPDATE team_rating tr JOIN matches m ON m.match_id = NEW.match_id
       SET tr.needs_recompute = TRUE
     WHERE tr.team_id = NEW.team_id AND tr.format_code = m.format_code
       AND tr.as_of_date = (SELECT mx FROM (SELECT MAX(as_of_date) AS mx FROM team_rating
                             WHERE team_id = NEW.team_id AND format_code = m.format_code) x);
END$$

DELIMITER ;

-- =====================================================================
-- Derived values (not stored): team rating and rank are computed in views
-- =====================================================================
CREATE VIEW v_team_rating AS
SELECT tr.team_id, t.team_name, t.team_code, t.gender, tr.format_code, tr.as_of_date,
       tr.matches, tr.points, ROUND(tr.points / tr.matches) AS rating, tr.needs_recompute
  FROM team_rating tr JOIN team t ON t.team_id = tr.team_id;

CREATE VIEW v_player_current_team AS
SELECT r.player_id, r.team_id
  FROM represents r
 WHERE r.to_date IS NULL;
