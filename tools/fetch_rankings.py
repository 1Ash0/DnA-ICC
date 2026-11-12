"""
Polite fetcher for the public ICC ranking tables (run it LOCALLY).

 * Checks robots.txt first (a missing file = no restrictions published).
 * One request at a time, DELAY_SECONDS between pages, identifies itself.
 * Saves the rendered HTML of each page to data/raw/ and never refetches a cached page
   (delete the file or pass --refresh to fetch again).
 * The tables are drawn by JavaScript, so it uses a headless browser (Playwright).
 * Writes the extracted rows to data/<page>.json for you to review.

Setup:
    pip install playwright
    playwright install chromium
Run:
    python fetch_rankings.py            # all pages
    python fetch_rankings.py --only team-mens-odi
    python fetch_rankings.py --refresh
"""
import argparse
import datetime
import json
import re
import time
import urllib.error
import urllib.request
import urllib.robotparser
from pathlib import Path

BASE = "https://www.icc-cricket.com"
USER_AGENT = "CourseProjectBot/1.0 (student database project; contact: your-email@example.com)"
DELAY_SECONDS = 6
DATA_DIR = Path(__file__).parent / "data"
RAW_DIR = DATA_DIR / "raw"

# name -> (path, kind). Paths taken from the ICC rankings index page.
PAGES = {
    "team-mens-test":   ("/rankings/team-rankings/mens/test",   "team"),
    "team-mens-odi":    ("/rankings/team-rankings/mens/odi",    "team"),
    "team-mens-t20i":   ("/rankings/team-rankings/mens/t20i",   "team"),
    "team-womens-odi":  ("/rankings/team-rankings/womens/odi",  "team"),
    "team-womens-t20i": ("/rankings/team-rankings/womens/t20i", "team"),
    "bat-mens-odi":     ("/rankings/batting/mens/odi",          "player"),
    "bowl-mens-odi":    ("/rankings/bowling/mens/odi",          "player"),
    "bat-mens-t20i":    ("/rankings/batting/mens/t20i",         "player"),
    "bowl-mens-t20i":   ("/rankings/bowling/mens/t20i",         "player"),
    "bat-mens-test":    ("/rankings/batting/mens/test",         "player"),
    "bowl-mens-test":   ("/rankings/bowling/mens/test",         "player"),
    "bat-womens-odi":   ("/rankings/batting/womens/odi",        "player"),
    "bowl-womens-odi":  ("/rankings/bowling/womens/odi",        "player"),
    "bat-womens-t20i":  ("/rankings/batting/womens/t20i",       "player"),
    "bowl-womens-t20i": ("/rankings/bowling/womens/t20i",       "player"),
}


def robots_allows(path):
    """True if robots.txt permits fetching `path` (or if there is no robots.txt)."""
    rp = urllib.robotparser.RobotFileParser()
    try:
        req = urllib.request.Request(BASE + "/robots.txt", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            rp.parse(resp.read().decode("utf-8", "replace").splitlines())
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return True            # no robots.txt published
        return False               # 401/403/5xx: be conservative
    except Exception:
        return False
    return rp.can_fetch(USER_AGENT, BASE + path)


ROWS_JS = """() => [...document.querySelectorAll('table tr')].map(tr =>
    [...tr.querySelectorAll('th,td')].map(c => c.innerText.trim().replace(/\\s+/g, ' ')))
    .filter(r => r.length > 1)"""

DATE_RE = re.compile(
    r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b"
    r"|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b")


def collect_rows(page, max_rounds=60):
    """The ranking lists are drawn lazily: only some rows exist in the DOM at a time.
    Scroll and click any 'load more' button repeatedly, remembering every row seen,
    until a few rounds in a row add nothing new."""
    seen, stable = {}, 0
    for _ in range(max_rounds):
        for r in page.evaluate(ROWS_JS):
            m = re.match(r"^\s*(\d+)", r[0])     # position, possibly followed by a movement arrow
            if m:
                seen.setdefault(tuple(r), int(m.group(1)))
        count = len(seen)

        btn = page.get_by_role("button", name=re.compile(r"load more|show more|view more", re.I))
        if btn.count():
            try:
                btn.first.click(timeout=3000)
            except Exception:
                pass
        page.mouse.wheel(0, 1800)
        page.wait_for_timeout(700)

        stable = stable + 1 if len(seen) == count else 0
        if stable >= 4:
            break
    return [list(k) for k, _ in sorted(seen.items(), key=lambda kv: kv[1])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="fetch a single page key, e.g. team-mens-odi")
    ap.add_argument("--refresh", action="store_true", help="ignore the cache")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright  # imported late so --help works without it

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    keys = [args.only] if args.only else list(PAGES)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=USER_AGENT)
        page = ctx.new_page()
        first_network_hit = True

        for key in keys:
            path, kind = PAGES[key]
            raw_file = RAW_DIR / f"{key}.html"
            out_file = DATA_DIR / f"{key}.json"

            if raw_file.exists() and not args.refresh:
                print(f"[cache] {key}")
                continue
            if not robots_allows(path):
                print(f"[skip]  {key}: robots.txt disallows {path}")
                continue

            if not first_network_hit:
                time.sleep(DELAY_SECONDS)
            first_network_hit = False

            print(f"[fetch] {key}  {BASE + path}")
            try:
                # "networkidle" never fires on pages with ads/analytics, so only wait for the
                # document itself, then wait for the table to be drawn.
                resp = page.goto(BASE + path, wait_until="domcontentloaded", timeout=60_000)
                if resp is not None and resp.status >= 400:
                    print(f"        HTTP {resp.status} for {key}; skipping")
                    continue
                page.wait_for_selector("table tr td", timeout=45_000)
                page.wait_for_timeout(1500)  # let the table finish filling
            except Exception as e:
                print(f"        could not load {key}: {type(e).__name__}; skipping")
                continue

            rows = collect_rows(page)
            if not rows:
                print(f"        0 rows parsed for {key}; NOT cached, send me the page layout")
                continue
            body_text = page.inner_text("body")
            raw_file.write_text(page.content(), encoding="utf-8")
            out_file.write_text(json.dumps({
                "page": key, "kind": kind,
                "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "dates_on_page": list(dict.fromkeys(DATE_RE.findall(body_text)))[:6],
                "row_count": len(rows),
                "rows": rows,
            }, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"        {len(rows)} rows, positions "
                  f"{rows[0][0]}..{rows[-1][0]} -> {out_file.name}")

        browser.close()
    print("Done. Review data/*.json before turning it into SQL.")


if __name__ == "__main__":
    main()