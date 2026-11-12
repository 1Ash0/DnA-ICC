# 45.mp4 – recording script (aim for 8–9 minutes)

**Before you start**
- Reload the data so the database is fresh. From `E:\45\45\45\src`:
  `cmd /c "mysql -u root -p < schema.sql"` then `cmd /c "mysql -u root -p < populate.sql"`.
- Window 1: browser at http://localhost:5000 (app running with `$env:DB_PASS` set).
- Window 2: `mysql -u root -p icc_rankings`, with `demo_queries.sql` open in Notepad to copy blocks from.
- Put the windows side by side. Record with **Win + Alt + R** (Xbox Game Bar), or OBS.
- Afterwards, save the video as `E:\45\45\45\45.mp4` and run `python tools\package.py`.

---

## 0. Opening (≈45 s)
Say: "This is Team 45's ICC Rankings database. MySQL 8 with a Flask backend, modelled on icc-cricket.com/rankings.
All data was taken from the ICC site: rankings at three dates, player profiles and real match scorecards."
Click through the nav: Overview → Team Rankings → Player Rankings → Matches → a player → a team.

## Queries (≈4 min, ~20 s each)
1. **Team Rankings:** Men's → Test. Point out "SA 23 matches, 2860 pts, 124, the same as the ICC site".
   Change the rank date to September and Apply. Then switch to Women's → T20I.
2. **Player Rankings:** Men's ODI Batting (Gill on top). Click **All-Rounder**: "derived as batting × bowling ÷ 1000".
3. **Search:** type `koh` → Kohli. Then `keeper` → wicket-keepers. Then `india` → teams with their status.
4. **Player profile:** click Shubman Gill. Point out age from DOB, styles, current ranks, rating history with change,
   career runs from appearances, and recent matches.
5. **Team profile:** India → status history, rating trend with change, win/loss record, top performers.
6. **Matches:** filter Status = Completed, Format = ODI. Open NZ v India (match 271652) to show the scorecard.
7. **Head-to-Head:** India v New Zealand, all formats → wins and losses.
8. **Player Comparison:** Gill v Kohli.
9. **Movers:** Men's Test batting, earliest → latest date.
10. **Series:** open "India in New Zealand, 5 ODI Series" → top performers and rating impact.
11. **Stats:** highest/lowest/average table, teams with no Test since 2026-10-01, teams per member.
12. **Admin:** analyst workload table, grouped by supervisor.

## Updates (≈4 min). For each: SQL before → do it in the UI → same SQL after
13. **Create team rating:** run block [13] (no rows). Go to Teams → Ireland → *Publish rating snapshot*:
    TEST, today, matches 10, points 300. Publish → green message. Re-run [13] → new row.
    Open Team Rankings → Men's Test: Ireland now appears in the table (rating 30).
    *(Optional error: matches 0 → red CHECK message.)*
14. **Create player rating:** run [14]. Go to Admin → *Publish a player rating*: Sharma, Abhishek – T20I – Batting – today.
    Enter **1500** first → red "CHECK violated". Then **891** → success. Re-run [14].
15. **Create player:** run [15] (empty). Go to Admin → *Add a player*: id 900001, Vaibhav Suryavanshi,
    DOB 2011-03-27, Male, Left Handed, Batter, team India, from today. Re-run [15] → player, role and spell.
    *(Optional error: pick gender Female with team India → trigger message, nothing saved.)*
16. **Update match result:** run [16] (India Won, NZ Lost, needs_recompute 0). Open match 271652 → *Change match result*.
    First set both to **Won** → red "Inconsistent result". Then set India **Lost**, NZ **Won** → success.
    Re-run [16]: results swapped and needs_recompute = 1 for both teams. Team Rankings Men's ODI now shows the badge.
17. **Retire player:** run [17]. Open Abhishek Sharma → *Retire from a format*: T20I, today. Re-run [17].
    Show Men's T20I Batting: he is gone from the table, but his history is still on his profile.
18. **Change team:** re-run [15]. Open player 900001 (search "Suryavanshi") → *Change team* → Nepal.
    Re-run [15]: the old spell is closed with a to_date and a new spell is open.
19. **End format status:** run [19]. Teams → Zimbabwe (men) → *End a format status*: TEST, today. Re-run [19]:
    end date set, old 1992–2006 period still kept, and the latest Test rating now shows needs_recompute = 1.
    Then *Publish rating snapshot* for Zimbabwe TEST with today's date → red "does not hold status".
    *(Optional error: try ending Ireland's TEST status today → refused, because step 13 published a rating today.)*
20. **Correct rating:** run the second query of [16]. India page → rating trend → ODI 07 Nov → *edit* → Save.
    Re-run: needs_recompute is back to 0.
21. **Delete match:** run [21]. Open match 274664 (Zimbabwe v Afghanistan, Scheduled) → *Delete match* → success.
    Open 271652 → Delete → refused (Completed). Re-run [21]: 274664 and its participations are gone.
22. **Delete rating snapshot:** Ireland page → TEST row from step 13 → *delete*. Re-run [13].
23. **Delete player:** player 900001 → *Delete player* → success. Re-run [15] (empty).
    Try deleting Abhishek Sharma → refused (RESTRICT, has history).

Close: "Every query is raw parameterised SQL in queries.py; constraint errors come straight from MySQL."
