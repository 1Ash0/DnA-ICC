"""ICC Rankings - Phase 4 web application (Flask + PyMySQL, raw SQL only).
Modelled on https://www.icc-cricket.com/rankings
Run:  python app.py   ->  http://localhost:5000
"""
import datetime as dt
import os

import pymysql
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, url_for

import queries as Q
from db import error_text

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "icc-rankings-dev")

FORMAT_LABEL = {"TEST": "Test", "ODI": "ODI", "T20I": "T20I"}
GENDER_LABEL = {"M": "Men's", "W": "Women's"}
DISC_LABEL = {"batting": "Batting", "bowling": "Bowling", "allrounder": "All-Rounder"}


# ------------------------------------------------------------- input helpers
def arg_choice(name, choices, default):
    v = (request.args.get(name) or default).strip()
    return v if v in choices else default


def form_int(name, required=True, lo=None, hi=None):
    raw = (request.form.get(name) or "").strip()
    if not raw:
        if required:
            raise ValueError(f"'{name}' is required.")
        return None
    try:
        v = int(raw)
    except ValueError:
        raise ValueError(f"'{name}' must be a whole number.")
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise ValueError(f"'{name}' must be between {lo} and {hi}.")
    return v


def form_date(name, required=True):
    raw = (request.form.get(name) or "").strip()
    if not raw:
        if required:
            raise ValueError(f"'{name}' is required.")
        return None
    try:
        return dt.date.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"'{name}' must be a date (YYYY-MM-DD).")


def form_text(name, required=True, max_len=100):
    v = (request.form.get(name) or "").strip()
    if required and not v:
        raise ValueError(f"'{name}' is required.")
    if len(v) > max_len:
        raise ValueError(f"'{name}' is too long.")
    return v or None


def run_write(fn, ok_msg, *args):
    """Run a write; show a success or a clear error message."""
    try:
        n = fn(*args)
        flash(f"{ok_msg} ({n} row{'s' if n != 1 else ''} affected)", "success")
        return True
    except pymysql.Error as e:
        flash("Rejected by the database: " + error_text(e), "error")
    return False


@app.context_processor
def inject_globals():
    return dict(FORMAT_LABEL=FORMAT_LABEL, GENDER_LABEL=GENDER_LABEL, DISC_LABEL=DISC_LABEL)


@app.template_filter("d")
def fmt_date(v):
    return v.strftime("%d %B %Y") if hasattr(v, "strftime") else (v or "")


# ------------------------------------------------------------- pages
@app.route("/")
def home():
    tops = []
    for g, f in (("M", "TEST"), ("M", "ODI"), ("M", "T20I"), ("W", "ODI"), ("W", "T20I")):
        rows = Q.team_rankings(g, f, dt.date.today(), limit=5)
        tops.append((g, f, rows))
    bats = Q.player_rankings("M", "ODI", "batting", dt.date.today(), limit=5)
    return render_template("home.html", tops=tops, bats=bats)


# Q1 team rankings
@app.route("/rankings/teams")
def team_rankings():
    gender = arg_choice("gender", Q.GENDERS, "M")
    fmt = arg_choice("format", Q.FORMATS, "ODI")
    if gender == "W" and fmt == "TEST":
        flash("Women's Test teams are not ranked by the ICC; showing ODI instead.", "error")
        fmt = "ODI"
    dates = Q.rank_dates_team(gender, fmt)
    date = request.args.get("date") or dt.date.today().isoformat()   # latest table
    try:
        dt.date.fromisoformat(date)
    except ValueError:
        abort(400)
    rows = Q.team_rankings(gender, fmt, date)
    return render_template("team_rankings.html", rows=rows, gender=gender, fmt=fmt, dates=dates, date=date)


# Q2 player rankings
@app.route("/rankings/players")
def player_rankings():
    gender = arg_choice("gender", Q.GENDERS, "M")
    fmt = arg_choice("format", Q.FORMATS, "ODI")
    disc = arg_choice("discipline", tuple(Q.DISCIPLINES), "batting")
    if gender == "W" and fmt == "TEST":
        flash("Women's Test ratings are not published; showing ODI instead.", "error")
        fmt = "ODI"
    dates = Q.rank_dates_player(gender, fmt, disc)
    date = request.args.get("date") or dt.date.today().isoformat()   # latest table
    try:
        dt.date.fromisoformat(date)
    except ValueError:
        abort(400)
    rows = Q.player_rankings(gender, fmt, disc, date)
    return render_template("player_rankings.html", rows=rows, gender=gender, fmt=fmt, disc=disc,
                           dates=dates, date=date)


# Q3 player profile
@app.route("/players/<int:pid>")
def player_page(pid):
    p = Q.player(pid)
    if not p:
        abort(404)
    return render_template("player.html", p=p, roles=Q.player_roles(pid), retired=Q.player_retired(pid),
                           history=Q.player_team_history(pid), ranks=Q.player_current_ranks(pid),
                           rating_history=Q.player_rating_history(pid), career=Q.player_career(pid),
                           apps=Q.player_appearances(pid), teams=Q.all_teams(p["gender"]),
                           today=dt.date.today())


# Q4 team profile
@app.route("/teams/<int:tid>")
def team_page(tid):
    t = Q.team(tid)
    if not t:
        abort(404)
    return render_template("team.html", t=t, status=Q.team_status(tid), trend=Q.team_rating_trend(tid),
                           record=Q.team_record(tid), top=Q.team_top_performers(tid),
                           squad=Q.team_squad(tid), matches=Q.team_matches(tid), today=dt.date.today())


@app.route("/teams")
def teams_page():
    return render_template("teams.html", teams=Q.search_teams(""))


# Q5 search
@app.route("/search")
def search():
    q = (request.args.get("q") or "").strip()
    players, teams = ([], [])
    if q:
        if len(q) > 60:
            flash("Search text is too long.", "error")
        else:
            players, teams = Q.search_players(q), Q.search_teams(q)
    return render_template("search.html", q=q, players=players, teams=teams)


# Q6 matches
@app.route("/matches")
def matches_page():
    fmt = arg_choice("format", ("",) + Q.FORMATS, "")
    status = arg_choice("status", ("", "Scheduled", "Completed", "Abandoned"), "")
    gender = arg_choice("gender", ("",) + Q.GENDERS, "")
    return render_template("matches.html", rows=Q.match_list(fmt, status, gender),
                           fmt=fmt, status=status, gender=gender)


@app.route("/matches/<int:mid>")
def match_page(mid):
    m = Q.match(mid)
    if not m:
        abort(404)
    return render_template("match.html", m=m, teams=Q.match_teams(mid), card=Q.match_scorecard(mid))


# Q7 head-to-head
@app.route("/head-to-head")
def h2h():
    gender = arg_choice("gender", Q.GENDERS, "M")
    fmt = arg_choice("format", ("",) + Q.FORMATS, "")
    t1, t2 = request.args.get("team1", type=int), request.args.get("team2", type=int)
    summary, rows, n1, n2 = None, [], None, None
    if t1 and t2:
        if t1 == t2:
            flash("Choose two different teams.", "error")
        else:
            a, b = Q.team(t1), Q.team(t2)
            if not a or not b:
                flash("Team not found.", "error")
            else:
                summary, rows, n1, n2 = Q.head_to_head(t1, t2, fmt), Q.h2h_matches(t1, t2, fmt), a, b
    return render_template("h2h.html", teams=Q.all_teams(gender), gender=gender, fmt=fmt, t1=t1, t2=t2,
                           summary=summary, rows=rows, n1=n1, n2=n2)


# Q8 comparison
@app.route("/rankings/player-comparison")
def compare():
    p1, p2 = request.args.get("p1", type=int), request.args.get("p2", type=int)
    data = None
    if p1 and p2:
        a, b = Q.player(p1), Q.player(p2)
        if not a or not b:
            flash("Player not found.", "error")
        else:
            ratings = Q.compare_players(p1, p2)
            keys = sorted({(r["format_code"], r["discipline"]) for r in ratings},
                          key=lambda k: (Q.FORMATS.index(k[0]), k[1]))
            grid = {(r["player_id"], r["format_code"], r["discipline"]): r for r in ratings}
            data = dict(a=a, b=b, cells=keys, grid=grid, ca={r["format_code"]: r for r in Q.player_career(p1)},
                        cb={r["format_code"]: r for r in Q.player_career(p2)})
    return render_template("compare.html", players=Q.players_for_select(), p1=p1, p2=p2, data=data)


# Q9 movers
@app.route("/rankings/movers")
def movers():
    gender = arg_choice("gender", Q.GENDERS, "M")
    fmt = arg_choice("format", Q.FORMATS, "ODI")
    disc = arg_choice("discipline", ("batting", "bowling"), "batting")
    if gender == "W" and fmt == "TEST":
        fmt = "ODI"
    dates = Q.rank_dates_player(gender, fmt, disc)
    d_to = request.args.get("to") or (dates[0].isoformat() if dates else "")
    d_from = request.args.get("from") or (dates[-1].isoformat() if dates else "")
    rows = Q.rating_movers(gender, fmt, disc, d_from, d_to) if d_from and d_to else []
    return render_template("movers.html", rows=rows, gender=gender, fmt=fmt, disc=disc, dates=dates,
                           d_from=d_from, d_to=d_to)


# Q10 statistics
@app.route("/stats")
def stats():
    fmt = arg_choice("format", Q.FORMATS, "TEST")
    since = request.args.get("since") or "2026-10-01"
    try:
        dt.date.fromisoformat(since)
    except ValueError:
        abort(400)
    return render_template("stats.html", fstats=Q.format_rating_stats(), members=Q.ranked_teams_per_member(),
                           idle=Q.teams_without_matches(fmt, since), fmt=fmt, since=since)


# Q11 series
@app.route("/series")
def series_list():
    return render_template("series_list.html", rows=Q.series_list())


@app.route("/series/<int:sid>")
def series_page(sid):
    s = Q.series(sid)
    if not s:
        abort(404)
    return render_template("series.html", s=s, top=Q.series_top_performers(sid),
                           impact=Q.series_rating_impact(sid), matches=Q.series_matches(sid))


# Q12 admin / workload
@app.route("/admin")
def admin():
    return render_template("admin.html", users=Q.users(), workload=Q.analyst_workload(),
                           teams=Q.all_teams(), players=Q.players_for_select(), today=dt.date.today())


# ------------------------------------------------------------- writes
@app.route("/players/new", methods=["POST"])
def player_new():
    try:
        pid = form_int("player_id", lo=1)
        first, last = form_text("first_name", max_len=50), form_text("last_name", max_len=60)
        middle = form_text("middle_name", required=False, max_len=100)
        dob = form_date("date_of_birth", required=False)
        gender = form_text("gender")
        role = form_text("playing_role")
        team_id = form_int("team_id")
        from_date = form_date("from_date")
        if gender not in Q.GENDERS:
            raise ValueError("Gender must be M or W.")
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("admin"))
    ok = run_write(Q.create_player, f"Added player {first} {last}.", pid, first, middle, last, dob, gender,
                   form_text("batting_style", False, 30), form_text("bowling_style", False, 50), role,
                   team_id, from_date)
    return redirect(url_for("player_page", pid=pid) if ok else url_for("admin"))


@app.route("/ratings/team/new", methods=["POST"])
def team_rating_new():
    try:
        tid, fmt = form_int("team_id"), form_text("format_code")
        date = form_date("as_of_date")
        matches, points = form_int("match_count"), form_int("points")
        trigger, user = form_text("update_trigger"), form_int("published_by")
    except ValueError as e:
        flash(str(e), "error")
        return redirect(request.referrer or url_for("admin"))
    run_write(Q.publish_team_rating, "Published team rating snapshot.", tid, fmt, date, matches, points,
              trigger, user)
    return redirect(request.referrer or url_for("admin"))


@app.route("/ratings/player/new", methods=["POST"])
def player_rating_new():
    try:
        pid, fmt, disc = form_int("player_id"), form_text("format_code"), form_text("discipline")
        date, pts, user = form_date("as_of_date"), form_int("rating_points"), form_int("published_by")
    except ValueError as e:
        flash(str(e), "error")
        return redirect(request.referrer or url_for("admin"))
    run_write(Q.publish_player_rating, "Published player rating.", pid, fmt, disc, date, pts, user)
    return redirect(request.referrer or url_for("admin"))


@app.route("/matches/<int:mid>/result", methods=["POST"])
def match_result(mid):
    teams = Q.match_teams(mid)
    if len(teams) != 2:
        abort(404)
    status = form_text("status")
    results = []
    try:
        for t in teams:
            tid = t["team_id"]
            res = form_text(f"result_{tid}", required=False) or None
            runs = form_int(f"runs_{tid}", required=False, lo=0, hi=2000)
            results.append((tid, runs, res))
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("match_page", mid=mid))
    run_write(Q.update_match_result, "Match result updated (ratings of both teams flagged for recompute).",
              mid, status, results)
    return redirect(url_for("match_page", mid=mid))


@app.route("/matches/<int:mid>/delete", methods=["POST"])
def match_delete(mid):
    if run_write(Q.delete_match, f"Deleted match {mid}.", mid):
        return redirect(url_for("matches_page"))
    return redirect(url_for("match_page", mid=mid))


@app.route("/players/<int:pid>/retire", methods=["POST"])
def player_retire(pid):
    try:
        fmt, date = form_text("format_code"), form_date("retired_on")
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("player_page", pid=pid))
    run_write(Q.retire_player, f"Player retired from {fmt}; removed from current {fmt} tables.", pid, fmt, date)
    return redirect(url_for("player_page", pid=pid))


@app.route("/players/<int:pid>/team", methods=["POST"])
def player_change_team(pid):
    try:
        tid, date = form_int("team_id"), form_date("from_date")
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("player_page", pid=pid))
    run_write(Q.change_player_team, "Team changed: old spell closed, new spell opened.", pid, tid, date)
    return redirect(url_for("player_page", pid=pid))


@app.route("/players/<int:pid>/delete", methods=["POST"])
def player_delete(pid):
    if run_write(Q.delete_player, f"Deleted player {pid}.", pid):
        return redirect(url_for("search"))
    return redirect(url_for("player_page", pid=pid))


@app.route("/teams/<int:tid>/status/end", methods=["POST"])
def team_status_end(tid):
    try:
        fmt, date = form_text("format_code"), form_date("end_date")
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("team_page", tid=tid))
    run_write(Q.end_team_status, f"{fmt} status ended (history kept).", tid, fmt, date)
    return redirect(url_for("team_page", tid=tid))


@app.route("/teams/<int:tid>/rating/edit", methods=["POST"])
def team_rating_edit(tid):
    try:
        fmt, date = form_text("format_code"), form_date("as_of_date")
        matches, points = form_int("match_count"), form_int("points")
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("team_page", tid=tid))
    run_write(Q.correct_team_rating, "Rating snapshot corrected.", tid, fmt, date, matches, points)
    return redirect(url_for("team_page", tid=tid))


@app.route("/teams/<int:tid>/rating/delete", methods=["POST"])
def team_rating_delete(tid):
    try:
        fmt, date = form_text("format_code"), form_date("as_of_date")
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("team_page", tid=tid))
    run_write(Q.delete_team_rating, f"Deleted {fmt} snapshot of {date}.", tid, fmt, date)
    return redirect(url_for("team_page", tid=tid))


# ------------------------------------------------------------- JSON API (same queries)
@app.route("/api/rankings/teams")
def api_team_rankings():
    gender = arg_choice("gender", Q.GENDERS, "M")
    fmt = arg_choice("format", Q.FORMATS, "ODI")
    date = request.args.get("date") or dt.date.today().isoformat()
    try:
        dt.date.fromisoformat(date)
    except ValueError:
        return jsonify(error="date must be YYYY-MM-DD"), 400
    return jsonify(Q.team_rankings(gender, fmt, date))


@app.route("/api/search")
def api_search():
    q = (request.args.get("q") or "").strip()[:60]
    return jsonify(players=Q.search_players(q) if q else [], teams=Q.search_teams(q) if q else [])


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, msg="That page or record does not exist."), 404


@app.errorhandler(400)
def bad_request(e):
    return render_template("error.html", code=400, msg="The request had an invalid value."), 400


@app.errorhandler(pymysql.err.OperationalError)
def db_down(e):
    return render_template("error.html", code=503, msg="Database error: " + error_text(e)), 503


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=int(os.environ.get("PORT", "5000")))
