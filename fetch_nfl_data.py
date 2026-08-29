"""Fetches NFL stats from nflverse-data (github.com/nflverse/nflverse-data) into
nfl_data/. This is the only script in the project that touches the network — run it
manually to refresh NFL data, then re-run Brownlow.py to rebuild index.html. Same
two-step flow as dropping a new round_N.txt into rounds/ for AFL: fetch/drop the raw
data, then regenerate.

No external dependencies (stdlib only), consistent with the rest of the project.
"""
import csv
import io
import os
import urllib.request

SEASON = 2025
OUT_DIR = "nfl_data"

SOURCES = {
    f"stats_player_week_{SEASON}.csv": f"https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{SEASON}.csv",
    f"stats_team_week_{SEASON}.csv":   f"https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_{SEASON}.csv",
    f"snap_counts_{SEASON}.csv":       f"https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{SEASON}.csv",
    f"roster_{SEASON}.csv":            f"https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_{SEASON}.csv",
}
# games.csv covers every season back to 1999 — filtered down to SEASON on save so
# nfl_data/ stays as lean and season-scoped as the rest of the fetched files.
GAMES_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"


def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def fetch_csv(name, url):
    print(f"Downloading {name} ...")
    data = download(url)
    dest = os.path.join(OUT_DIR, name)
    with open(dest, "wb") as f:
        f.write(data)
    print(f"  saved {dest} ({len(data)/1024:.0f} KB)")


def fetch_games():
    print("Downloading games.csv (filtering to season", SEASON, ") ...")
    raw = download(GAMES_URL).decode("utf-8")
    reader = csv.DictReader(io.StringIO(raw))
    rows = [r for r in reader if r.get("season") == str(SEASON)]
    dest = os.path.join(OUT_DIR, "games.csv")
    with open(dest, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=reader.fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  saved {dest} ({len(rows)} games)")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    ok, failed = 0, []
    for name, url in SOURCES.items():
        try:
            fetch_csv(name, url)
            ok += 1
        except Exception as e:
            print(f"⚠️  Failed to fetch {name}: {e}")
            failed.append(name)
    try:
        fetch_games()
        ok += 1
    except Exception as e:
        print(f"⚠️  Failed to fetch games.csv: {e}")
        failed.append("games.csv")

    print(f"\n{'✅' if not failed else '⚠️ '} Fetched {ok}/{ok+len(failed)} files into {OUT_DIR}/.")
    if failed:
        print(f"   Failed: {', '.join(failed)}")
    print("Run Brownlow.py to rebuild index.html with the refreshed NFL data.")


if __name__ == "__main__":
    main()
