"""
FanFooty Scraper for AFL Fantasy Brownlow Calculator
=====================================================
Fetches the current round's scores from fanfooty.com.au and saves
them as a round file ready for brownlow.py.

Usage:
    python scrape_fanfooty.py              # Scrape current round
    python scrape_fanfooty.py --round 11   # Label the file as round 11

Requirements:
    pip install requests beautifulsoup4
"""

import re
import os
import sys
import argparse

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("\n❌  Missing libraries. Run this first:")
    print("    pip install requests beautifulsoup4")
    sys.exit(1)

ROUNDS_FOLDER = "rounds"
URL = "https://www.fanfooty.com.au/game/roundscores.php"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
    "Referer": "https://www.fanfooty.com.au/",
}


def fetch_round_scores():
    print(f"  Fetching: {URL}")
    try:
        session = requests.Session()
        # First hit the homepage to get cookies
        session.get("https://www.fanfooty.com.au/", headers=HEADERS, timeout=15)
        r = session.get(URL, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.text
    except requests.exceptions.HTTPError as e:
        print(f"\n❌  HTTP error: {e}")
        print("    FanFooty may be blocking automated requests.")
        print("    See 'Manual copy' instructions below.\n")
        return None
    except requests.exceptions.ConnectionError:
        print("\n❌  Could not connect. Check your internet connection.\n")
        return None


def parse_html(html):
    """
    Parse the fanfooty roundscores page HTML.
    Returns: (round_num, list of {player, team, score})
    """
    soup = BeautifulSoup(html, "html.parser")

    # Get round number from page heading
    round_num = None
    for tag in soup.find_all(string=re.compile(r"Fantasy Scores.*Round\s+\d+")):
        m = re.search(r"Round\s+(\d+)", tag)
        if m:
            round_num = int(m.group(1))
            break

    players = []
    current_team = None

    # Each game is in an outer table cell. Teams are identified by italic tags
    # like: <i>St Kilda: 9.13.67</i>
    for tag in soup.find_all("i"):
        text = tag.get_text(strip=True)
        m = re.match(r"^(.+?):\s*\d+\.\d+\.\d+$", text)
        if m:
            current_team = m.group(1).strip()
            # Now find the table that follows this tag
            table = tag.find_next("table")
            if table and current_team:
                rows = table.find_all("tr")
                for row in rows:
                    cells = row.find_all(["td", "th"])
                    if len(cells) >= 2:
                        name_cell = cells[0].get_text(strip=True)
                        score_cell = cells[1].get_text(strip=True)
                        # Skip header rows
                        if name_cell.lower() in ("player", "") or score_cell.lower() in ("dt", ""):
                            continue
                        try:
                            score = int(score_cell)
                            if name_cell and score >= 0:
                                players.append({
                                    "player": name_cell,
                                    "team": current_team,
                                    "score": score
                                })
                        except ValueError:
                            pass

    return round_num, players


def save_round_file(round_num, players, folder):
    os.makedirs(folder, exist_ok=True)

    # Group by team preserving order
    teams_seen = []
    team_players = {}
    for p in players:
        if p["team"] not in team_players:
            teams_seen.append(p["team"])
            team_players[p["team"]] = []
        team_players[p["team"]].append(p)

    filepath = os.path.join(folder, f"round_{round_num}.txt")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"Fantasy Scores: Round {round_num}\n")
        for team in teams_seen:
            # We don't have the score line from scraping, use placeholder
            f.write(f"\n{team}: 0.0.0\n")
            f.write("Player\tDT\n")
            for p in team_players[team]:
                f.write(f"{p['player']}\t{p['score']}\n")

    return filepath


def print_manual_instructions(round_num):
    print("\n" + "=" * 60)
    print("  📋  MANUAL COPY METHOD (if scraper is blocked)")
    print("=" * 60)
    print(f"""
  1. Open in your browser:
     https://www.fanfooty.com.au/game/roundscores.php

  2. Press Ctrl+A to select all, then Ctrl+C to copy.

  3. Paste into a new file called:
     rounds/round_{round_num or 'XX'}.txt

  4. The brownlow.py script can also read that format directly.
     Alternatively, keep your existing format — the old txt format
     from AFL Fantasy works too!
""")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", type=int, help="Override round number for the saved file")
    args = parser.parse_args()

    print("\n🏉  FanFooty Scraper")
    print("=" * 40)

    html = fetch_round_scores()

    if html is None:
        print_manual_instructions(args.round)
        return

    round_num, players = parse_html(html)

    if not players:
        print("\n⚠️  No player data found. The page structure may have changed.")
        print_manual_instructions(args.round)
        return

    if args.round:
        round_num = args.round
    elif round_num is None:
        round_num = int(input("\n  Could not detect round number. Enter it manually: ").strip())

    filepath = save_round_file(round_num, players, ROUNDS_FOLDER)

    print(f"\n✅  Scraped {len(players)} players from Round {round_num}")
    print(f"   Saved to: {filepath}")
    print(f"\n   Now run:  python brownlow.py")
    print()


if __name__ == "__main__":
    main()