# AFL Fantasy Brownlow Calculator

Simulates the Brownlow Medal using AFL Fantasy scores — the top 3 scorers in each game each round receive 3, 2, and 1 votes. Built as a Python script that generates a single-page HTML dashboard, updated weekly throughout the season.

**[View the live dashboard →](https://yourusername.github.io/afl-fantasy-brownlow)**

---

## Features

- **Leaderboard** — cumulative vote standings with form boxes showing last 5 rounds, current price, and injury flags
- **Vote Race** — animated round-by-round replay of the vote leaderboard building across the season
- **Round Scores** — browse every game by round, showing the 3 vote-getters per match
- **Player Stats** — search any player for score history, price chart, projected score, form rating, consistency rating, and an auto-generated trade report
- **Matchup Difficulty** — historical difficulty ratings per team and position, plus upcoming fixture projections
- **Trading Centre** — plan trades with side-by-side stat comparison, composite trade quality score, and scenario comparison
- **My Team** — build your squad in AFL Fantasy formation with signal labels, upgrade recommendations, and team tips
- **Rolling 22** — best projected 22-man team from loaded data, sortable by overall avg, form-weighted, or fixture-adjusted

---

## How it works

Data comes from [Footywire](https://www.footywire.com) fantasy score exports. Each round file is a tab-separated `.txt` file placed in the `rounds/` folder. Running the Python script parses all rounds and generates a self-contained `index.html` dashboard.

```
rounds/
├── round1.txt
├── round2.txt
├── ...
└── current_round.txt   ← post-round prices from the current week
```

Optional supporting files:

| File | Purpose |
|------|---------|
| `players.txt` | Player registry with positions and starting prices — enables position-based difficulty ratings |
| `fixture.txt` | Full season fixture — enables upcoming difficulty and projected scores |
| `current_round.txt` | Current week's price rankings — used for post-round prices in the leaderboard and player cards |
| `cba.txt` | Tab-separated centre bounce attendance % per round (`Player TM TOT AVG PS1 R0...R24`) — feeds the Draft page's CBA trend signal |
| `ages.txt` | Tab-separated `Player Team Age` (whole years) — optional, used as a small factor in the Draft page's Draft Score |

---

## Setup

Requires Python 3.8+. No external dependencies.

```bash
git clone https://github.com/yourusername/afl-fantasy-brownlow.git
cd afl-fantasy-brownlow
python3 Brownlow.py
```

This generates `index.html` and opens it in your browser.

---

## Updating each week

1. Add the new round file to `rounds/` (e.g. `round13.txt`)
2. Update `current_round.txt` with the latest price rankings
3. Run `python3 Brownlow.py`
4. Push to GitHub — the live site updates automatically

```bash
git add .
git commit -m "Round 13"
git push
```

---

## Data format

Round files use Footywire's tab-separated fantasy score export format. Paste the scores directly from Footywire into a `.txt` file — the parser handles team detection automatically.

The `current_round.txt` file uses this tab-separated format:

```
Rank    Player              Team        Games   Price       Total Score   Average Score   *Value
1       Bailey Smith        Cats        13      $1,151,000  1,559         119.9           10.4
2       Nick Daicos         Magpies     11      $1,111,000  1,318         119.8           10.8
```

---

## License

MIT
