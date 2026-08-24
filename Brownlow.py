import os, re, json, math
from collections import defaultdict
from datetime import datetime

ROUNDS_FOLDER      = "rounds"
CURRENT_ROUND_FILE = os.path.join(ROUNDS_FOLDER, "current_round.txt")
PLAYERS_FILE       = "players.txt"
FIXTURE_FILE       = "fixture.txt"
CURRENT_ROUND      = 12   # <-- update each week

TEAM_MAP = {
    "Sydney Swans":"Swans","Swans":"Swans",
    "Hawthorn Hawks":"Hawks","Hawthorn":"Hawks","Hawks":"Hawks",
    "Carlton Blues":"Blues","Carlton":"Blues","Blues":"Blues",
    "Geelong Cats":"Cats","Geelong":"Cats","Cats":"Cats",
    "Brisbane Lions":"Lions","Brisbane":"Lions","Lions":"Lions",
    "Collingwood Magpies":"Magpies","Collingwood":"Magpies","Magpies":"Magpies",
    "Essendon Bombers":"Bombers","Essendon":"Bombers","Bombers":"Bombers",
    "Fremantle Dockers":"Dockers","Fremantle":"Dockers","Dockers":"Dockers",
    "Gold Coast Suns":"Suns","Gold Coast":"Suns","Suns":"Suns",
    "GWS Giants":"Giants","Greater Western Sydney":"Giants","Giants":"Giants",
    "Melbourne Demons":"Demons","Melbourne":"Demons","Demons":"Demons",
    "North Melbourne Kangaroos":"Kangaroos","North Melbourne":"Kangaroos","Kangaroos":"Kangaroos",
    "Port Adelaide Power":"Power","Port Adelaide":"Power","Power":"Power",
    "Richmond Tigers":"Tigers","Richmond":"Tigers","Tigers":"Tigers",
    "St Kilda Saints":"Saints","St Kilda":"Saints","Saints":"Saints",
    "West Coast Eagles":"Eagles","West Coast":"Eagles","Eagles":"Eagles",
    "Western Bulldogs":"Bulldogs","Bulldogs":"Bulldogs",
    "Adelaide Crows":"Crows","Adelaide":"Crows","Crows":"Crows",
    "SYD":"Swans","HAW":"Hawks","CAR":"Blues","GEE":"Cats","BRL":"Lions","BL":"Lions",
    "COL":"Magpies","ESS":"Bombers","FRE":"Dockers","GCS":"Suns","GWS":"Giants",
    "MEL":"Demons","NM":"Kangaroos","NTH":"Kangaroos","PA":"Power","PTA":"Power",
    "RIC":"Tigers","RCH":"Tigers","STK":"Saints","WCE":"Eagles","WB":"Bulldogs","WBD":"Bulldogs",
    "ADE":"Crows","ADEL":"Crows","PAD":"Power",
}

def normalise_team(raw):
    raw = raw.strip()
    if raw in TEAM_MAP: return TEAM_MAP[raw]
    stripped = raw.strip(".")
    if stripped in TEAM_MAP: return TEAM_MAP[stripped]
    best = None
    for k, v in TEAM_MAP.items():
        if k.lower() in raw.lower() and (best is None or len(k) > len(best[0])):
            best = (k, v)
    return best[1] if best else raw

def parse_players_file(filepath):
    if not os.path.exists(filepath): return []
    players = []
    current_team = None
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            parts = [p.strip() for p in line.split("\t")]
            if parts[0].upper() == "PLAYER": continue
            if len(parts) >= 1 and parts[0] and (len(parts) < 2 or not parts[1]):
                current_team = normalise_team(parts[0]); continue
            if len(parts) >= 1 and parts[0] and current_team:
                name = parts[0].strip()
                pos_str   = parts[1].strip() if len(parts) > 1 else ""
                price_str = parts[2].strip() if len(parts) > 2 else ""
                positions = [p.strip() for p in pos_str.split("/")] if pos_str else []
                price = None
                if price_str:
                    try: price = int(price_str.replace("$","").replace(",","").strip())
                    except: pass
                if name:
                    players.append({"name":name,"team":current_team,"positions":positions,"starting_price":price})
    return players

def build_name_matcher(players_data):
    """Build exact/case-insensitive/surname+team lookup indexes over players_data's
    (name, team) pairs, for matching a name from an external per-round export (CBA
    export, Champion Data CSV, players.txt registry) onto the right player record
    even when the source spells/cases/nicknames it differently. Returns
    resolve(name, team=None): exact -> case/space-insensitive -> unique
    surname+team fallback (team=None skips that last tier, e.g. two same-surname
    teammates never silently collide)."""
    def norm(s): return re.sub(r'\s+', ' ', s.strip().lower())
    def surname(s):
        parts = s.strip().split()
        return parts[-1].lower() if parts else ''
    by_exact, by_lower = {}, {}
    by_surname_team = defaultdict(list)
    for p in players_data:
        by_exact[p["name"]] = p
        by_lower[norm(p["name"])] = p
        by_surname_team[(surname(p["name"]), p["team"])].append(p)
    def resolve(name, team=None):
        target = by_exact.get(name) or by_lower.get(norm(name))
        if target is None and team is not None:
            cands = by_surname_team.get((surname(name), team))
            if cands and len(cands) == 1: target = cands[0]
        return target
    return resolve

CBA_FILE = "cba.txt"

def parse_cba_file(filepath):
    """Parse a CBA% (centre bounce attendance) export: tab-separated Player, TM, TOT,
    AVG, PS1, R0..R24. PS1 is a pre-season hitout, not a real round, so it's skipped —
    only the R<n> columns get mapped onto round numbers. "-" means the player wasn't
    in the side that round (not 0%), so it's dropped rather than counted as a real 0."""
    if not os.path.exists(filepath): return []
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()
    if len(lines) < 2: return []
    header = [c.strip() for c in lines[0].rstrip("\n").split("\t")]
    round_cols = []
    for col in header[5:]:
        m = re.match(r"^R(\d+)$", col)
        round_cols.append(int(m.group(1)) if m else None)
    def pct(s):
        s = s.strip()
        if not s or s == "-": return None
        try: return int(s.replace("%",""))
        except: return None
    results = []
    for line in lines[1:]:
        line = line.rstrip("\n")
        if not line.strip(): continue
        parts = line.split("\t")
        if len(parts) < 5: continue
        name = clean_name(parts[0].strip())
        team = normalise_team(parts[1].strip())
        avg = pct(parts[3])
        history = {}
        for i, rn in enumerate(round_cols):
            if rn is None: continue
            idx = 5 + i
            if idx < len(parts):
                v = pct(parts[idx])
                if v is not None: history[rn] = v
        if name: results.append({"name": name, "team": team, "avg": avg, "history": history})
    return results

def attach_cba_data(players_data, cba_rows):
    """Match CBA rows onto players_data by name, tolerating the same kind of spelling
    drift between external sources that build_players_data already has to handle
    (e.g. registry 'Jacob van Rooyen' vs this export's own casing) — exact match, then
    case/whitespace-insensitive, then surname+team when that's unambiguous."""
    resolve = build_name_matcher(players_data)
    matched, unmatched = 0, []
    for row in cba_rows:
        target = resolve(row["name"], row["team"])
        if target:
            target["cba_avg"] = row["avg"]
            target["cba_history"] = row["history"]
            matched += 1
        else:
            unmatched.append(row["name"])
    tail = f" — unmatched: {', '.join(unmatched[:10])}{' ...' if len(unmatched) > 10 else ''}" if unmatched else ""
    print(f"ℹ️  CBA import: {matched}/{len(cba_rows)} players matched{tail}")

CHAMPION_DATA_FOLDER = ROUNDS_FOLDER  # round_N.csv lives alongside round_N.txt
CHAMPION_DATA_ID_COLS = {"MatchId", "Player", "Team"}

def parse_champion_round_csv(filepath):
    """Parse one Champion Data round export (comma-separated, header row, one row
    per player per match — Rating/Equity/disposal/pressure/clearance/ruck/scoring
    stats etc). Different rounds' exports have carried different column sets (e.g.
    some include CoachesVotes/ExpVotes/Votes3, others don't) so the stat columns to
    keep are read from THIS file's own header rather than a fixed list — nothing
    gets silently dropped just because an older/newer export added or removed a
    column. Returns [{"name","team","stats": {col: number_or_None}}]. Blank cells
    become None, never 0 — a missing stat must never look like 'did it and scored
    zero' (same principle as '-' handling in parse_cba_file)."""
    import csv
    if not os.path.exists(filepath): return []
    rows = []
    with open(filepath, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        stat_cols = [c for c in (reader.fieldnames or []) if c not in CHAMPION_DATA_ID_COLS]
        for r in reader:
            name = clean_name((r.get("Player") or "").strip())
            team = normalise_team((r.get("Team") or "").strip())
            if not name: continue
            stats = {}
            for col in stat_cols:
                raw = (r.get(col) or "").strip()
                if raw == "":
                    stats[col] = None
                    continue
                try: stats[col] = float(raw) if "." in raw else int(raw)
                except ValueError: stats[col] = None
            rows.append({"name": name, "team": team, "stats": stats})
    return rows

def load_champion_round_data(folder):
    """Scan folder for round_N.csv (Champion Data format — distinct from the older
    round_N.txt files read by load_all_rounds). Returns {round_int: [row, ...]}. A
    malformed file is skipped with a warning, not a crash — this is a growing,
    hand-dropped-in data source and one bad file must not break the whole report."""
    result = {}
    if not os.path.exists(folder): return result
    for fname in sorted(os.listdir(folder)):
        m = re.match(r"^round_(\d+)\.csv$", fname)
        if not m: continue
        rn = int(m.group(1))
        try:
            rows = parse_champion_round_csv(os.path.join(folder, fname))
            if rows: result[rn] = rows
        except Exception as e:
            print(f"⚠️  Skipped {fname}: could not parse Champion Data CSV ({e})")
    return result

def attach_round_stats(players_data, champion_by_round):
    """Match each round's Champion Data rows onto players_data (same tiered
    matching as attach_cba_data). Mirrors its structure/print style. Stores every
    round's full stat dict under advanced_history — nothing is pre-filtered here;
    downstream consumers (archetypes, UI) pick out what they need."""
    if not champion_by_round: return
    resolve = build_name_matcher(players_data)
    matched, unmatched = 0, []
    for rn, rows in champion_by_round.items():
        for row in rows:
            target = resolve(row["name"], row["team"])
            if target is None:
                unmatched.append(f"{row['name']} (R{rn})")
                continue
            target.setdefault("advanced_history", {})[rn] = row["stats"]
            matched += 1
    total = sum(len(v) for v in champion_by_round.values())
    tail = f" — unmatched: {', '.join(unmatched[:10])}{' ...' if len(unmatched) > 10 else ''}" if unmatched else ""
    print(f"ℹ️  Advanced stats import: {matched}/{total} rows matched across {len(champion_by_round)} round(s){tail}")

def compute_advanced_averages(players_data):
    """Season-to-date mean per stat, over only the rounds where that player has
    advanced data (not divided by total games) — same 'missing != zero' principle
    as everywhere else in this file. Averages over whatever stat keys actually
    appear across that player's rounds (column sets can vary round to round, see
    parse_champion_round_csv), not a fixed list. Recomputes fully each run — cheap
    (rounds so far x ~45 stats x ~450 players), no incremental state to keep in sync."""
    for p in players_data:
        hist = p.get("advanced_history") or {}
        all_cols = set()
        for rd in hist.values(): all_cols.update(rd.keys())
        avgs = {}
        for col in all_cols:
            vals = [rd[col] for rd in hist.values() if rd.get(col) is not None]
            avgs[col] = round(sum(vals) / len(vals), 2) if vals else None
        p["advanced_avg"] = avgs

def _weighted_rate(advanced_avg, terms):
    """terms: list of (stat_key, weight, mode). mode is 'tog' (scaled to 'per 100%
    TimeOnGround', so a rotating player isn't penalised relative to one who plays
    every minute — measures playing STYLE, not game time), 'disposal' (scaled to
    'per 100 disposals' — measures OUTPUT PER TOUCH, decoupled from how much of the
    ball a player gets at all; this is what separates a player who does a lot WITH
    a given touch from one who just accumulates touches), or 'raw' (used as-is,
    for stats already expressed as a rate/percentage, e.g. DisposalEfficiency).
    Returns None if every listed stat is missing (or its required denominator —
    TimeOnGround / Disposals — is missing for every term using it)."""
    tog = advanced_avg.get("TimeOnGround")
    disp = advanced_avg.get("Disposals")
    total, any_val = 0.0, False
    for stat_key, weight, mode in terms:
        v = advanced_avg.get(stat_key)
        if v is None: continue
        if mode == "tog":
            if not tog: continue
            v = v / tog * 100
        elif mode == "disposal":
            if not disp: continue
            v = v / disp * 100
        total += v * weight
        any_val = True
    return total if any_val else None

# Each archetype is a WEIGHTED combination of stats (primary stat weighted
# highest, secondary/tertiary stats contribute less) rather than a single raw
# number — this is what lets every Champion Data column get stored (see
# CHAMPION_DATA_ID_COLS / parse_champion_round_csv) while still letting the
# stats that actually define a playing style dominate the classification.
#
# Fields: (key, label, terms, rationale, color, phrase)
#   label    — plain-language name (avoids stat jargon like "clearance beast").
#   color    — hex used for the badge on the front end; one distinct hue per
#              archetype so tags are visually distinguishable at a glance, not
#              all the same amber.
#   phrase   — short lower-case clause ("wins the hard ball at stoppages") used
#              to build the synthesized multi-tag conclusion sentence (see
#              compute_player_archetypes) — every phrase must read naturally
#              after "he ".
ARCHETYPES = [
    ("clearance_beast", "Contested Bull",
     [("TotalClearances",1.0,"tog"), ("ContestedPossessions",0.4,"tog"), ("PostClearanceContestedPossessions",0.3,"tog")],
     "Wins the contested footy at stoppages — a genuine clearance threat who thrives when the ball's in dispute.",
     "#f97316", "wins the hard ball at stoppages"),
    ("pressure_player", "Pressure Tackler",
     [("Tackles",1.0,"tog"), ("PressureActs",0.6,"tog")],
     "High tackle/pressure numbers — the kind of player who lifts in wet, low-scoring, congested games.",
     "#ef4444", "brings relentless tackling pressure"),
    ("ruck_dominance", "Dominant Ruck",
     [("Hitouts",1.0,"tog"), ("HitoutsToAdvantage",0.8,"tog")],
     "Wins hitouts and directs a meaningful share to advantage — a genuine first-use ruck weapon, not just a contest-attender.",
     "#a78bfa", "dominates hitouts as a genuine #1 ruck"),
    ("intercept_defender", "Rebound Defender",
     [("Intercepts",1.0,"tog"), ("InterceptMarks",0.7,"tog"), ("Marks",0.2,"tog")],
     "Reads the play off the opposition and repels it — a rebound/intercept threat who profits from turnover-prone opposition attacks.",
     "#38bdf8", "reads and repels the opposition's ball movement"),
    ("clean_user", "Clean Disposal",
     [("DisposalEfficiency",1.0,"raw"), ("Equity_BallUse",0.5,"raw"), ("Equity_PostClearance",0.3,"raw")],
     "Rarely wastes it and gains real ground with it — a low-turnover, territory-gaining disposal user.",
     "#2dd4bf", "rarely wastes a possession"),
    ("forward_threat", "Goal Threat",
     [("Goals",1.0,"tog"), ("ShotsAtGoal",0.6,"tog"), ("xScore",0.5,"raw")],
     "Gets to the scoreboard directly — genuine multiple-goal upside on his day.",
     "#facc15", "gets to the scoreboard himself"),
    ("score_creator", "Playmaker",
     [("GoalAssists",1.5,"disposal"), ("ScoreInvolvements",1.0,"disposal"), ("ScoreLaunches",0.8,"disposal"), ("AssistedMetresGained",0.3,"disposal")],
     "Turns an unusually high share of his own touches into scoring plays for someone else — a link-up efficiency signal.",
     "#4ade80", "sets up scores for others"),
    ("accumulator", "Ball Magnet",
     [("Disposals",1.0,"tog"), ("GroundBallGets",0.4,"tog"), ("HandballReceives",0.4,"tog"), ("FirstPossessions",0.3,"tog")],
     "Racks up a high number of the footy relative to most players — sheer repeated involvement.",
     "#f472b6", "racks up a high volume of the ball"),
    ("stoppage_fixture", "Stoppage Regular",
     [("CentreBounceAttendancePercentage",1.0,"raw"), ("TotalClearances",0.2,"tog")],
     "Lives at centre bounces — a role this entrenched underpins any clearance/ruck tag above with real midfield minutes, not a one-off game.",
     "#94a3b8", "lives at centre bounces"),
]

# Curated 2-tag conclusions for the most narratively meaningful combinations —
# keyed by frozenset({key1, key2}). Any pair not listed here falls back to a
# generic "combines X and Y" sentence built from the phrase fields above (see
# _archetype_conclusion). This is where a genuinely interpretive read (e.g. the
# 'suits wet weather' angle) gets attached, rather than just concatenating tags.
ARCHETYPE_COMBO_NOTES = {
    frozenset({"clearance_beast", "pressure_player"}):
        "A genuine contested-footy bull who also tackles hard — this profile tends to hold up well in wet, slow, congested games where clean disposal is scarce and the contest is everything.",
    frozenset({"ruck_dominance", "clearance_beast"}):
        "Wins the ruck contest AND follows up at ground level — an old-fashioned #1 ruck who does more than just tap it down.",
    frozenset({"ruck_dominance", "stoppage_fixture"}):
        "About as traditional a #1 ruck profile as it gets — dominates hitouts and is rostered at virtually every centre bounce.",
    frozenset({"intercept_defender", "clean_user"}):
        "Reads the play and uses it cleanly going the other way — a genuine rebounding defender, not just a spoiler who kicks it straight back.",
    frozenset({"pressure_player", "intercept_defender"}):
        "Tackles hard and reads the intercept — a defensive pressure player who both stops opposition ball movement and turns it back the other way.",
    frozenset({"score_creator", "forward_threat"}):
        "Creates scores for others AND finishes his own — a complete forward threat rather than a pure crumber or a pure kick-for-goal type.",
    frozenset({"accumulator", "clean_user"}):
        "Racks up a high number of possessions and rarely wastes them — an efficient, high-output ball-user.",
    frozenset({"accumulator", "score_creator"}):
        "High-possession AND disproportionately creative with it — a genuine engine-room playmaker.",
    frozenset({"forward_threat", "clean_user"}):
        "A clean user of the footy who also converts — low-waste, high-impact around goal.",
    frozenset({"clearance_beast", "stoppage_fixture"}):
        "A genuine stoppage midfielder — wins it at the source because he's rostered there virtually every centre bounce.",
}

MIN_ADVANCED_ROUNDS = 1        # a player needs at least this many advanced-stat rounds to be considered at all
PERCENTILE_THRESHOLD = 80      # top ~20th percentile by SPECIALIZATION (see below) gets tagged
MIN_ABSOLUTE_PERCENTILE = 55   # and must still be at least moderately good at it in absolute terms
RUCK_GATE_MIN_CONTESTS = 3     # avg RuckContests below this excludes a player from Ruck Dominance entirely

def compute_player_archetypes(players_data):
    """Tags each covered player with the archetypes their statistical PROFILE
    actually skews toward, not just 'is a good/heavily-involved player'. A raw
    top-percentile-per-archetype approach was tried first and rejected: it mostly
    just re-identified the same handful of high-minutes, high-involvement
    midfielders (Cripps/Oliver/Gawn-types) across nearly every archetype at once,
    since a heavily-involved player racks up elevated per-TOG rates on almost
    every counting stat simultaneously — that measures overall quality, not style.

    Fix: for each covered player, first percentile-rank them on every archetype
    they qualify for (as before), then compute their own BASELINE = the mean of
    those percentiles (their general level across all measured traits). A
    player's specialization in an archetype is (percentile - baseline) — how much
    that one trait stands out ABOVE THEIR OWN typical level, not above the whole
    competition. Tag the top PERCENTILE_THRESHOLD-th percentile of players by
    specialization for that archetype, with an MIN_ABSOLUTE_PERCENTILE floor so a
    generally poor player's 'least bad' stat doesn't get flagged as a defining
    trait just because it's high relative to their own weak baseline.

    Scored against season-to-date advanced_avg (not a single round) so one big or
    bad game doesn't flip a tag on and off week to week. Players with zero
    advanced-stat coverage get archetypes: [] and advanced_coverage: 'none'
    rather than a misleading empty-looks-like-'plays no role' result."""
    covered = [p for p in players_data if len(p.get("advanced_history") or {}) >= MIN_ADVANCED_ROUNDS]

    # Pass 1: raw weighted rate + percentile per (player, archetype).
    percentiles = {id(p): {} for p in covered}
    raw_values = {id(p): {} for p in covered}
    for arch_key, label, terms, rationale, color, phrase in ARCHETYPES:
        scored = []
        for p in covered:
            if arch_key == "ruck_dominance" and (p["advanced_avg"].get("RuckContests") or 0) < RUCK_GATE_MIN_CONTESTS:
                continue
            v = _weighted_rate(p["advanced_avg"], terms)
            if v is not None: scored.append((p, v))
        if len(scored) < 5: continue  # too few covered players yet for a percentile to mean anything
        scored.sort(key=lambda t: t[1])
        n = len(scored)
        for i, (p, v) in enumerate(scored):
            percentiles[id(p)][arch_key] = (i + 1) / n * 100
            raw_values[id(p)][arch_key] = v

    # Pass 2: each player's own baseline = mean percentile across archetypes they qualified for.
    baseline = {id(p): (sum(pcs.values()) / len(pcs) if (pcs := percentiles[id(p)]) else None) for p in covered}

    # Pass 3: tag by specialization (percentile above own baseline), ranked within each archetype.
    # Exception: ruck_dominance is scored against an already-narrow, physically-gated
    # cohort (RuckContests >= RUCK_GATE_MIN_CONTESTS) where the "good players score
    # high on everything" confound barely applies — rucks don't also tend to dominate
    # accumulator/pressure/score-creator numbers the way general midfield bulls do.
    # Baseline-correcting it anyway compares a ruck's ruck-only percentile against a
    # baseline partly built from percentiles in the FULL league population (an
    # apples-to-oranges mix), which was demonstrably wrong in testing — it excluded
    # genuine elite rucks (Gawn, Nankervis) whose broad general play inflates their
    # baseline, in favour of narrower ruck specialists. So ruck_dominance keeps the
    # simple absolute-percentile rule instead.
    arch_meta = {a[0]: {"label": a[1], "rationale": a[3], "color": a[4], "phrase": a[5]} for a in ARCHETYPES}
    for arch_key, meta in arch_meta.items():
        label, rationale, color = meta["label"], meta["rationale"], meta["color"]
        if arch_key == "ruck_dominance":
            entries = [(p, percentiles[id(p)][arch_key]) for p in covered if arch_key in percentiles[id(p)]]
            if len(entries) < 5: continue
            for p, pct in entries:
                if pct >= PERCENTILE_THRESHOLD:
                    p.setdefault("_archetype_hits", []).append({
                        "key": arch_key, "label": label, "color": color, "value": round(raw_values[id(p)][arch_key], 2),
                        "percentile": round(pct, 1), "specialization": round(pct, 1), "rationale": rationale,
                    })
            continue
        entries = []
        for p in covered:
            pct = percentiles[id(p)].get(arch_key)
            if pct is None or baseline[id(p)] is None: continue
            entries.append((p, pct, pct - baseline[id(p)]))
        if len(entries) < 5: continue
        entries.sort(key=lambda t: t[2])
        n = len(entries)
        for i, (p, pct, spec) in enumerate(entries):
            spec_percentile = (i + 1) / n * 100
            if spec_percentile >= PERCENTILE_THRESHOLD and pct >= MIN_ABSOLUTE_PERCENTILE:
                p.setdefault("_archetype_hits", []).append({
                    "key": arch_key, "label": label, "color": color, "value": round(raw_values[id(p)][arch_key], 2),
                    "percentile": round(pct, 1), "specialization": round(spec, 1), "rationale": rationale,
                })

    for p in players_data:
        hits = p.pop("_archetype_hits", [])
        hits.sort(key=lambda h: -h["specialization"])
        p["archetypes"] = hits
        n_adv = len(p.get("advanced_history") or {})
        p["advanced_coverage"] = "none" if n_adv == 0 else ("limited" if n_adv < 3 else "season")
        p["archetype_conclusion"] = _archetype_conclusion(hits, arch_meta, p["advanced_coverage"])

def _archetype_conclusion(hits, arch_meta, coverage):
    """Synthesize a single takeaway sentence from a player's tagged archetypes,
    rather than leaving the reader to infer what a list of separate badges means
    together. 0 tags: an honest 'nothing stands out (yet)' read, distinguishing a
    genuinely balanced profile from simply not having data. 1 tag: its own
    rationale already reads as a complete sentence. 2+: a curated combo note for
    the two strongest tags where one exists (ARCHETYPE_COMBO_NOTES), else a
    generic sentence built from their short phrases — with any further tags
    named afterward so nothing tagged is silently dropped from the summary."""
    if not hits:
        if coverage == "none": return None
        return "No single trait clearly stands out yet — a fairly balanced statistical profile so far."
    if len(hits) == 1:
        return hits[0]["rationale"]
    top_two = hits[:2]
    combo_key = frozenset(h["key"] for h in top_two)
    note = ARCHETYPE_COMBO_NOTES.get(combo_key)
    if note is None:
        p1, p2 = arch_meta[top_two[0]["key"]]["phrase"], arch_meta[top_two[1]["key"]]["phrase"]
        note = f"Combines two traits: he {p1} and {p2}."
    if len(hits) > 2:
        extra = ", ".join(h["label"] for h in hits[2:])
        note += f" Also shows signs of: {extra}."
    return note

MIN_ARCHETYPE_TEAM_PLAYERS = 5   # need at least this many distinct tagged players who've faced a team
MIN_ARCHETYPE_TEAM_SPEC = 2.5    # specialization (see below) must clear this to be worth calling out

def compute_archetype_team_weaknesses(players_data):
    """For each archetype, which opposing team(s) concede MORE than usual
    specifically to players carrying that tag, and which defend it unusually
    well — distinct from just 'this team is generally bad/good defensively'.

    For each (team, archetype) pair, average every tagged player's own (score
    vs that team minus their own season average) delta, aggregated across
    everyone who holds the tag. Tried this first without correction and it was
    misleading: a team
    that's simply weak overall shows an inflated delta against EVERY archetype,
    which reads as if that team has a specific hole for that playing style when
    really it's just bad defensively full stop (North Melbourne topped almost
    every archetype's list in testing). Fixed the same way individual player
    specialization was — subtract that team's own baseline (its average delta
    across ALL archetypes) so what's left is specifically 'why this archetype
    against this team', not 'this team concedes to everyone'.

    Returns {archetype_key: [{"team","avg_delta","specialization","n_players",
    "direction"}]} — up to 2 entries each way (worst-defending / best-defending
    against that archetype specifically), direction is 'weak' or 'strong'."""
    by_archetype = defaultdict(list)
    for p in players_data:
        for a in p.get("archetypes") or []:
            by_archetype[a["key"]].append(p)

    team_arch_deltas = defaultdict(lambda: defaultdict(list))
    for arch_key, tagged in by_archetype.items():
        for p in tagged:
            hist = p.get("history") or []
            if len(hist) < 5: continue
            season_avg = sum(h["score"] for h in hist) / len(hist)
            by_opp = defaultdict(list)
            for h in hist:
                if h.get("opponent"): by_opp[h["opponent"]].append(h["score"])
            for opp, scores in by_opp.items():
                avg = sum(scores) / len(scores)
                team_arch_deltas[opp][arch_key].append(avg - season_avg)

    team_baseline = {}
    for team, archd in team_arch_deltas.items():
        all_deltas = [v for vs in archd.values() for v in vs]
        team_baseline[team] = sum(all_deltas) / len(all_deltas) if all_deltas else 0

    entries_by_arch = defaultdict(list)
    for team, archd in team_arch_deltas.items():
        base = team_baseline[team]
        for arch_key, deltas in archd.items():
            if len(deltas) < MIN_ARCHETYPE_TEAM_PLAYERS: continue
            avg = sum(deltas) / len(deltas)
            spec = avg - base
            if abs(spec) >= MIN_ARCHETYPE_TEAM_SPEC:
                entries_by_arch[arch_key].append({
                    "team": team, "avg_delta": round(avg, 1), "specialization": round(spec, 1),
                    "n_players": len(deltas), "direction": "weak" if spec > 0 else "strong",
                })

    result = {}
    for arch_key, entries in entries_by_arch.items():
        entries.sort(key=lambda e: -e["specialization"])
        weak = [e for e in entries if e["direction"] == "weak"][:2]
        strong = list(reversed([e for e in entries if e["direction"] == "strong"][-2:]))
        combined = weak + strong
        if combined: result[arch_key] = combined
    return result

def detect_format(lines):
    for line in lines:
        line = line.strip()
        if re.match(r"^(.+?):\s*\d+\.\d+\.\d+\s*$", line): return "fanfooty"
        if line.upper() == "FIXTURE": return "footywire_old"
        if re.match(r"^\d+\t.+\t.+\t\$[\d,]+\t\$[\d,]+\t\d+\t[\d.]+$", line): return "footywire"
    return None

def clean_name(name):
    return re.sub(r'\s+(INJ|Injured|SUS|Susp|Suspended|Out|Omitted)$', '', name.strip(), flags=re.IGNORECASE).strip()

def parse_price(s):
    try: return int(s.replace("$","").replace(",","").strip())
    except: return None

def format_price(price):
    if price is None: return '—'
    if price < 1_000_000: return f'${round(price/1000)}K'
    return f'${price/1_000_000:.3f}M'

def parse_fanfooty(lines):
    players, team_order, team_players = [], [], defaultdict(list)
    current_team, expect_header = None, False
    for line in lines:
        line = line.strip()
        if not line: continue
        if line.lower().startswith("fantasy scores:"): continue
        if any(line.startswith(x) for x in ["LEGEND","DT =","Fan Tools","Advertisement"]): continue
        m = re.match(r"^(.+?):\s*\d+\.\d+\.\d+\s*$", line)
        if m:
            raw_team = m.group(1).strip()
            current_team = normalise_team(raw_team)
            expect_header = True
            if current_team not in team_players: team_order.append(current_team)
            continue
        if expect_header: expect_header = False; continue
        parts = line.split()
        if len(parts) >= 2:
            name_parts, score = [], None
            for part in parts:
                try: score = int(part); break
                except: name_parts.append(part)
            if score is not None and name_parts and current_team:
                name = clean_name(" ".join(name_parts))
                e = {"player":name,"team":current_team,"score":score,"price":None}
                players.append(e); team_players[current_team].append(e)
    games = []
    for i in range(0, len(team_order)-1, 2):
        ta, tb = team_order[i], team_order[i+1]
        combined = sorted(team_players[ta]+team_players[tb], key=lambda x:x["score"], reverse=True)
        games.append({"team_a":ta,"team_b":tb,"all_players":combined})
    return players, games

def parse_footywire(lines):
    player_lines = []
    for line in lines:
        s = line.strip()
        if s.upper() in ("FIXTURE", "END FIXTURE"): continue
        if s.lower().startswith("fantasy scores:"): continue
        player_lines.append(s)
    all_players = []
    for line in player_lines:
        parts = line.split("\t")
        if len(parts) >= 6:
            try:
                name = clean_name(parts[1].strip())
                short_team = parts[2].strip()
                price = parse_price(parts[4].strip())
                score = int(parts[5].strip())
                team = normalise_team(short_team)
                all_players.append({"player":name,"team":team,"score":score,"price":price,"short_team":short_team})
            except: pass
    return all_players

def parse_current_round(filepath):
    """Returns (current_prices dict, injured_set, suspended_set).
    injured_set catches every unavailability flag ('INJ', 'Injured', 'Susp', 'Suspended',
    'Out', 'Omitted') and is used everywhere availability matters (projections, trade
    suggestions, upcoming fixtures). suspended_set is the 'Susp'/'Suspended' subset of
    that, kept separately purely so the UI can label them SUS instead of INJ."""
    current_prices = {}
    injured_set = set()
    suspended_set = set()
    if not os.path.exists(filepath): return current_prices, injured_set, suspended_set
    with open(filepath,"r",encoding="utf-8") as f: lines = f.readlines()
    for line in lines:
        line = line.strip()
        if not line: continue
        parts = line.split("\t")
        if len(parts) < 5: continue
        if parts[0].strip().lower() == "rank": continue
        try: int(parts[0].strip())
        except: continue
        raw_name = parts[1].strip()
        # Detect injury/suspension flag BEFORE cleaning name
        if re.search(r'\s+(SUS|Susp|Suspended)$', raw_name, re.IGNORECASE):
            suspended_set.add(clean_name(raw_name))
            injured_set.add(clean_name(raw_name))
        elif re.search(r'\s+(INJ|Injured|Out|Omitted)$', raw_name, re.IGNORECASE):
            injured_set.add(clean_name(raw_name))
        name = clean_name(raw_name)
        price = parse_price(parts[4].strip())
        if name and price: current_prices[name] = price
    return current_prices, injured_set, suspended_set

def assign_votes_to_games(games):
    vote_results = []
    for game in games:
        game_votes = []
        for rank, player in enumerate(game["all_players"], 1):
            votes = {1:3,2:2,3:1}.get(rank,0)
            e = {**player,"votes":votes}
            game_votes.append(e); vote_results.append(e)
            if rank >= 3: break
        game["votes"] = game_votes
    return vote_results

def build_games_from_players(all_players, fixture_for_round):
    team_players = defaultdict(list)
    for p in all_players:
        team_players[p["team"]].append(p)
    games = []
    used_teams = set()
    for ta, tb in fixture_for_round:
        pa = team_players.get(ta, [])
        pb = team_players.get(tb, [])
        if not pa and not pb: continue
        combined = sorted(pa + pb, key=lambda x: x["score"], reverse=True)
        games.append({"team_a": ta, "team_b": tb, "all_players": combined})
        used_teams.add(ta); used_teams.add(tb)
    remaining_teams = [t for t in team_players if t not in used_teams]
    for i in range(0, len(remaining_teams)-1, 2):
        ta, tb = remaining_teams[i], remaining_teams[i+1]
        combined = sorted(team_players[ta]+team_players[tb], key=lambda x:x["score"], reverse=True)
        games.append({"team_a":ta,"team_b":tb,"all_players":combined})
    return games

def parse_round_file(filepath, fixture_for_round):
    with open(filepath,"r",encoding="utf-8") as f: lines = f.readlines()
    fmt = detect_format(lines)
    if fmt == "fanfooty":
        players, games = parse_fanfooty(lines)
    else:
        players = parse_footywire(lines)
        games = build_games_from_players(players, fixture_for_round)
    assign_votes_to_games(games)
    votes = []
    for game in games:
        votes.extend(game.get("votes", []))
    return votes, games, players

def parse_fixture_file(filepath):
    fixture = {}
    if not os.path.exists(filepath): return fixture
    current_round = None
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            if line.lower().startswith("fixture") and "venue" in line.lower(): continue
            m_open  = re.match(r"^opening round\s*$", line, re.IGNORECASE)
            m_round = re.match(r"^round\s+(\d+)\s*$", line, re.IGNORECASE)
            if m_open:  current_round = 0; fixture[0] = []; continue
            if m_round: current_round = int(m_round.group(1)); fixture[current_round] = []; continue
            if current_round is None: continue
            m = re.match(r"^(.+?)\s+vs\.?\s+(.+?)(?:\t.*)?$", line, re.IGNORECASE)
            if m:
                ta = normalise_team(m.group(1).strip())
                tb = normalise_team(m.group(2).strip())
                fixture[current_round].append((ta, tb))
    return fixture

def load_all_rounds(folder, fixture):
    all_rounds = {}
    if not os.path.exists(folder): return all_rounds
    for filename in sorted(os.listdir(folder)):
        if not filename.endswith(".txt"): continue
        if filename == "current_round.txt": continue
        m = re.search(r"(\d+)", filename)
        rn = int(m.group(1)) if m else None
        if rn is None:
            if "opening" in filename.lower(): rn = 0
            else: continue
        fix_for_round = fixture.get(rn, [])
        votes, games, players = parse_round_file(os.path.join(folder, filename), fix_for_round)
        all_rounds[rn] = {"votes":votes,"games":games,"all_players":players}
    return all_rounds

def make_player_key(name, team):
    return f"{name}|{team}"

def build_leaderboard(all_rounds, current_prices):
    vote_totals  = defaultdict(lambda: {"team":"","votes":0,"name":""})
    dt_totals    = defaultdict(int)
    round_counts = defaultdict(int)
    # Track per-round votes for each player (for form column)
    per_round_votes = defaultdict(dict)  # key -> {round_num: votes}
    sorted_rns = sorted(all_rounds.keys())
    for rn in sorted_rns:
        data = all_rounds[rn]
        for e in data["votes"]:
            key = make_player_key(e["player"], e["team"])
            vote_totals[key]["team"]  = e["team"]
            vote_totals[key]["name"]  = e["player"]
            vote_totals[key]["votes"] += e["votes"]
            per_round_votes[key][rn]  = e["votes"]
        seen = set()
        for game in data["games"]:
            for p in game["all_players"]:
                key = make_player_key(p["player"], p["team"])
                if key not in seen:
                    seen.add(key)
                    dt_totals[key] += p["score"]
                    round_counts[key] += 1
                if not vote_totals[key]["team"]:
                    vote_totals[key]["team"] = p["team"]
                    vote_totals[key]["name"] = p["player"]
    lb = []
    last5_rns = sorted_rns[-5:]  # last 5 rounds loaded
    for key, d in vote_totals.items():
        if d["votes"] == 0: continue
        rc  = round_counts[key]
        avg = round(dt_totals[key]/rc, 1) if rc > 0 else 0
        price = current_prices.get(d["name"])
        # form_history: list of (round_label, votes) for last 5 rounds
        form_history = []
        for rn in last5_rns:
            v = per_round_votes[key].get(rn, 0)
            form_history.append({"r": rn, "v": v})
        lb.append({"player":d["name"],"team":d["team"],"key":key,"votes":d["votes"],
                   "total_dt":dt_totals[key],"avg":avg,"rounds":rc,"price":price,
                   "form_history": form_history})
    lb.sort(key=lambda x:(x["votes"],x["total_dt"]),reverse=True)
    return lb

def build_rounds_data(all_rounds):
    rounds_data = []
    for rn in sorted(all_rounds.keys()):
        games = []
        for game in all_rounds[rn]["games"]:
            games.append({"team_a":game["team_a"],"team_b":game["team_b"],"votes":game.get("votes",[])})
        rounds_data.append({"round":rn,"games":games})
    return rounds_data

def build_players_data(all_rounds, current_prices, players_registry):
    sorted_rounds = sorted(all_rounds.keys())

    # players.txt is hand-maintained separately from the weekly round-results feed,
    # so the same real player can be spelled differently between the two sources
    # (e.g. "Connor MacDonald" vs registry "Connor Macdonald", "Harrison Himmelberg"
    # vs registry nickname "Harry Himmelberg"). An exact-string registry lookup then
    # silently misses them — they get no positions/starting_price on their real
    # history-backed entry, AND a second registry-only stub entry gets created for
    # the same person under the other spelling, showing up as a duplicate row
    # anywhere the app lists "every player". Resolve by exact match, then
    # case/whitespace-insensitive match, then surname+team (only when that surname
    # is unique for the team, so e.g. two "Macdonald"s on the same list don't
    # collide) to catch nickname variants like Harry/Harrison, Jack/Jackson.
    resolve_registry = build_name_matcher(players_registry)

    pre_prices = {}
    for rn in sorted_rounds:
        for p in all_rounds[rn]["all_players"]:
            key = make_player_key(p["player"], p["team"])
            if key not in pre_prices: pre_prices[key] = {}
            pre_prices[key][rn] = p.get("price")
    # Opponent per round per team, for fixture history / "vs" display.
    team_opponent = {}
    for rn in sorted_rounds:
        team_opponent[rn] = {}
        for game in all_rounds[rn].get("games", []):
            ta = normalise_team(game["team_a"]); tb = normalise_team(game["team_b"])
            team_opponent[rn][ta] = tb
            team_opponent[rn][tb] = ta
    player_data = {}
    for rn in sorted_rounds:
        for p in all_rounds[rn]["all_players"]:
            key = make_player_key(p["player"], p["team"])
            if key not in player_data:
                reg = resolve_registry(p["player"], p["team"])
                player_data[key] = {
                    "name":p["player"],"team":p["team"],"key":key,
                    "history":[],"current_price":current_prices.get(p["player"]),
                    "positions": reg["positions"] if reg else [],
                    "starting_price": reg["starting_price"] if reg else None
                }
            votes = 0
            for v in all_rounds[rn]["votes"]:
                if v["player"] == p["player"] and v["team"] == p["team"]: votes = v["votes"]; break
            pre_price = p.get("price")
            next_rounds = [r for r in sorted_rounds if r > rn]
            post_price = None
            for nr in next_rounds:
                candidate = pre_prices.get(key,{}).get(nr)
                if candidate is not None: post_price = candidate; break
            if post_price is None: post_price = current_prices.get(p["player"])
            opponent = team_opponent.get(rn, {}).get(normalise_team(p["team"]))
            player_data[key]["history"].append({
                "round":rn,"score":p["score"],
                "pre_price":pre_price,"post_price":post_price,"votes":votes,
                "opponent":opponent
            })
    matched_registry_ids = set()
    for v in player_data.values():
        reg = resolve_registry(v["name"], v["team"])
        if reg: matched_registry_ids.add(id(reg))
    for rp in players_registry:
        if id(rp) not in matched_registry_ids:
            key = make_player_key(rp["name"], rp["team"])
            if key not in player_data:
                player_data[key] = {
                    "name":rp["name"],"team":rp["team"],"key":key,
                    "history":[],"current_price":current_prices.get(rp["name"]),
                    "positions":rp["positions"],
                    "starting_price":rp["starting_price"]
                }
    # current_round.txt only lists players who featured this week, so anyone who
    # hasn't played yet (or was omitted the week prices were captured) falls
    # through with current_price=None even though players.txt has their price.
    # Fall back to their most recent known post-round price, then to their
    # players.txt starting price, so the UI always has something to show.
    for pd in player_data.values():
        if pd["current_price"] is not None: continue
        latest_post = None
        for h in pd["history"]:
            if h.get("post_price") is not None: latest_post = h["post_price"]
        pd["current_price"] = latest_post if latest_post is not None else pd.get("starting_price")
    return list(player_data.values())

def build_team_difficulty(all_rounds, players_registry):
    pos_lookup = {}
    for p in players_registry:
        pos_lookup[p["name"]] = p["positions"] if p["positions"] else []

    ALL_POSITIONS = ["DEF", "MID", "RUC", "FWD"]
    sorted_rounds = sorted(all_rounds.keys())
    total_rounds  = len(sorted_rounds)

    DECAY = 0.85
    def round_weight(rn):
        idx = sorted_rounds.index(rn)
        rounds_from_end = total_rounds - 1 - idx
        return DECAY ** rounds_from_end

    player_all_scores  = defaultdict(list)
    player_pos_scores  = {pos: defaultdict(list) for pos in ALL_POSITIONS}

    for rn in sorted_rounds:
        for game in all_rounds[rn]["games"]:
            for p in game["all_players"]:
                pname = p["player"]; sc = p["score"]
                player_all_scores[pname].append(sc)
                positions = pos_lookup.get(pname, [])
                for ap in ALL_POSITIONS:
                    if any(ap in pos for pos in positions):
                        player_pos_scores[ap][pname].append(sc)

    def player_avg(pname):
        scores = player_all_scores.get(pname, [])
        return sum(scores)/len(scores) if scores else None

    def player_pos_avg(pname, pos):
        scores = player_pos_scores[pos].get(pname, [])
        return sum(scores)/len(scores) if scores else None

    conceded_all = defaultdict(list)
    conceded_pos = {pos: defaultdict(list) for pos in ALL_POSITIONS}

    for rn in sorted_rounds:
        w = round_weight(rn)
        for game in all_rounds[rn]["games"]:
            ta = normalise_team(game["team_a"])
            tb = normalise_team(game["team_b"])
            players_a = [p for p in game["all_players"] if normalise_team(p["team"]) == ta]
            players_b = [p for p in game["all_players"] if normalise_team(p["team"]) == tb]

            def add_scores(players, opponent_team):
                for p in players:
                    sc = p["score"]; pname = p["player"]
                    pavg = player_avg(pname)
                    if pavg and len(player_all_scores[pname]) >= 2:
                        ratio = sc / pavg
                        conceded_all[opponent_team].append((ratio, w, sc))
                    positions = pos_lookup.get(pname, [])
                    for ap in ALL_POSITIONS:
                        if any(ap in pos for pos in positions):
                            pp_avg = player_pos_avg(pname, ap)
                            if pp_avg and len(player_pos_scores[ap][pname]) >= 2:
                                ratio_pos = sc / pp_avg
                                conceded_pos[ap][opponent_team].append((ratio_pos, w, sc))

            add_scores(players_a, tb)
            add_scores(players_b, ta)

    def build_rating_list(conceded_dict):
        if not conceded_dict: return [], 80.0

        def wavg_ratio(items):
            total_w  = sum(w for _, w, _ in items)
            total_wv = sum(r * w for r, w, _ in items)
            return total_wv / total_w if total_w else 1.0

        team_wavg = {team: wavg_ratio(items) for team, items in conceded_dict.items()}
        all_items = [item for items in conceded_dict.values() for item in items]
        league_wavg = wavg_ratio(all_items) if all_items else 1.0

        result = []
        for team in sorted(conceded_dict.keys()):
            wavg   = team_wavg[team]
            rating = round((wavg / league_wavg) * 100, 1) if league_wavg else 100.0
            raw_scores = [sc for _, _, sc in conceded_dict[team]]
            avg_raw    = round(sum(raw_scores)/len(raw_scores), 1) if raw_scores else 0.0
            result.append({
                "team": team,
                "avg_conceded": avg_raw,
                "rating": rating,
                "games": len(raw_scores)
            })

        result.sort(key=lambda x: x["rating"], reverse=True)
        all_raw = [sc for items in conceded_dict.values() for _, _, sc in items]
        afl_avg = round(sum(all_raw)/len(all_raw), 1) if all_raw else 80.0
        return result, afl_avg

    overall, afl_avg = build_rating_list(conceded_all)
    pos_results = {}
    for pos in ALL_POSITIONS:
        if conceded_pos[pos]:
            pos_results[pos], _ = build_rating_list(conceded_pos[pos])
        else:
            pos_results[pos] = []

    return overall, pos_results, afl_avg


def build_upcoming_fixture_difficulty(fixture, all_rounds, players_registry, current_round):
    """
    Returns upcoming fixture difficulty per team with predicted avg pts added.
    predicted_avg = opponent's avg_conceded * (team_difficulty_rating / 100)
    This estimates how many pts a typical player from this team would score vs that opponent.
    """
    DECAY_FUTURE = 0.80

    ALL_POSITIONS = ["DEF", "MID", "RUC", "FWD"]
    pos_lookup = {}
    for p in players_registry:
        pos_lookup[p["name"]] = p["positions"] if p["positions"] else []

    sorted_rounds = sorted(all_rounds.keys())
    total_rounds  = len(sorted_rounds)
    DECAY = 0.85
    def round_weight(rn):
        idx = sorted_rounds.index(rn)
        rounds_from_end = total_rounds - 1 - idx
        return DECAY ** rounds_from_end

    player_all_scores  = defaultdict(list)
    player_pos_scores  = {pos: defaultdict(list) for pos in ALL_POSITIONS}
    for rn in sorted_rounds:
        for game in all_rounds[rn]["games"]:
            for p in game["all_players"]:
                player_all_scores[p["player"]].append(p["score"])
                positions = pos_lookup.get(p["player"], [])
                for ap in ALL_POSITIONS:
                    if any(ap in pos for pos in positions):
                        player_pos_scores[ap][p["player"]].append(p["score"])

    def player_avg(pname):
        s = player_all_scores.get(pname, [])
        return sum(s)/len(s) if s else None
    def player_pos_avg(pname, pos):
        s = player_pos_scores[pos].get(pname, [])
        return sum(s)/len(s) if s else None

    conceded_all = defaultdict(list)
    conceded_pos = {pos: defaultdict(list) for pos in ALL_POSITIONS}
    for rn in sorted_rounds:
        w = round_weight(rn)
        for game in all_rounds[rn]["games"]:
            ta = normalise_team(game["team_a"])
            tb = normalise_team(game["team_b"])
            players_a = [p for p in game["all_players"] if normalise_team(p["team"]) == ta]
            players_b = [p for p in game["all_players"] if normalise_team(p["team"]) == tb]
            def add_s(players, opp):
                for p in players:
                    sc = p["score"]; pname = p["player"]
                    pavg = player_avg(pname)
                    if pavg and len(player_all_scores[pname]) >= 2:
                        conceded_all[opp].append((sc/pavg, w, sc))
                    positions = pos_lookup.get(pname, [])
                    for ap in ALL_POSITIONS:
                        if any(ap in pos for pos in positions):
                            pp_avg = player_pos_avg(pname, ap)
                            if pp_avg and len(player_pos_scores[ap][pname]) >= 2:
                                conceded_pos[ap][opp].append((sc/pp_avg, w, sc))
            add_s(players_a, tb)
            add_s(players_b, ta)

    def wavg_ratio(items):
        tw = sum(w for _,w,_ in items)
        return sum(r*w for r,w,_ in items)/tw if tw else 1.0

    all_items = [item for items in conceded_all.values() for item in items]
    league_wavg = wavg_ratio(all_items) if all_items else 1.0

    pos_league_wavg = {}
    for pos in ALL_POSITIONS:
        pi = [item for items in conceded_pos[pos].values() for item in items]
        pos_league_wavg[pos] = wavg_ratio(pi) if pi else 1.0

    # avg raw conceded per team (weighted)
    def team_avg_conceded(team, conceded_dict):
        items = conceded_dict.get(team, [])
        if not items: return None
        raw = [sc for _,_,sc in items]
        return round(sum(raw)/len(raw), 1)

    def team_rating(team, conceded_dict, league_w):
        items = conceded_dict.get(team, [])
        if not items: return 100.0
        return round((wavg_ratio(items) / league_w) * 100, 1)

    pos_avg_conceded = {}
    for pos in ALL_POSITIONS:
        pos_avg_conceded[pos] = {team: team_avg_conceded(team, conceded_pos[pos])
                                  for team in conceded_pos[pos]}

    overall_avg_conceded = {team: team_avg_conceded(team, conceded_all)
                             for team in conceded_all}

    # AFL-wide average conceded per position
    afl_avg_all = None
    all_raw_all = [sc for items in conceded_all.values() for _,_,sc in items]
    if all_raw_all: afl_avg_all = round(sum(all_raw_all)/len(all_raw_all), 1)

    afl_avg_pos = {}
    for pos in ALL_POSITIONS:
        all_raw_pos = [sc for items in conceded_pos[pos].values() for _,_,sc in items]
        afl_avg_pos[pos] = round(sum(all_raw_pos)/len(all_raw_pos), 1) if all_raw_pos else None

    all_future_rounds = sorted(r for r in fixture.keys() if r > current_round)

    team_upcoming = defaultdict(list)
    for rn in all_future_rounds:
        for ta, tb in fixture[rn]:
            team_upcoming[ta].append((rn, tb))
            team_upcoming[tb].append((rn, ta))

    all_teams = set(conceded_all.keys())
    for rn, games in fixture.items():
        for ta, tb in games:
            all_teams.add(ta); all_teams.add(tb)

    result = []
    for team in sorted(all_teams):
        upcoming = team_upcoming.get(team, [])
        if not upcoming: continue

        weighted_ratings = {"overall": [], **{pos: [] for pos in ALL_POSITIONS}}
        game_details = []

        for i, (rn, opp) in enumerate(upcoming):
            w = DECAY_FUTURE ** i
            opp_rating_overall = team_rating(opp, conceded_all, league_wavg)
            weighted_ratings["overall"].append((opp_rating_overall, w))

            # Predicted avg: opponent's historical avg conceded * our difficulty adjustment
            # (A team with rating 105 playing vs an opponent that concedes 90 avg
            #  would predict ~94.5 pts for players from that team)
            opp_avg_conc = overall_avg_conceded.get(opp)
            predicted_overall = round(opp_avg_conc * opp_rating_overall / 100, 1) if opp_avg_conc else None

            pos_ratings = {}
            predicted_pos = {}
            for pos in ALL_POSITIONS:
                r = team_rating(opp, conceded_pos[pos], pos_league_wavg[pos])
                weighted_ratings[pos].append((r, w))
                pos_ratings[pos] = r
                opp_pos_avg = pos_avg_conceded[pos].get(opp)
                predicted_pos[pos] = round(opp_pos_avg * r / 100, 1) if opp_pos_avg else None

            game_details.append({
                "round": rn,
                "opponent": opp,
                "overall": opp_rating_overall,
                "predicted_avg": predicted_overall,
                "pos": pos_ratings,
                "predicted_pos": predicted_pos,
            })

        def calc_weighted(pairs):
            tw = sum(w for _, w in pairs)
            return round(sum(r*w for r,w in pairs)/tw, 1) if tw else 100.0

        overall_score = calc_weighted(weighted_ratings["overall"])
        pos_scores = {pos: calc_weighted(weighted_ratings[pos]) for pos in ALL_POSITIONS}

        # Weighted predicted avg (overall)
        valid_pred = [(gd["predicted_avg"], DECAY_FUTURE**i)
                      for i, gd in enumerate(game_details) if gd["predicted_avg"] is not None]
        if valid_pred:
            tw = sum(w for _,w in valid_pred)
            weighted_predicted = round(sum(v*w for v,w in valid_pred)/tw, 1) if tw else None
        else:
            weighted_predicted = None

        # Weighted predicted avg per position
        weighted_predicted_pos = {}
        for pos in ALL_POSITIONS:
            vp = [(gd["predicted_pos"].get(pos), DECAY_FUTURE**i)
                  for i, gd in enumerate(game_details) if gd["predicted_pos"].get(pos) is not None]
            if vp:
                tw = sum(w for _,w in vp)
                weighted_predicted_pos[pos] = round(sum(v*w for v,w in vp)/tw, 1) if tw else None
            else:
                weighted_predicted_pos[pos] = None

        result.append({
            "team": team,
            "upcoming_score": overall_score,
            "upcoming_pos": pos_scores,
            "predicted_avg": weighted_predicted,
            "predicted_avg_pos": weighted_predicted_pos,
            "games": game_details
        })

    result.sort(key=lambda x: x["upcoming_score"], reverse=True)
    return result, afl_avg_all, afl_avg_pos


def build_leaderboard_history(all_rounds):
    """
    BUGFIX: Previously, dt_totals was accumulated inside the round loop without
    per-round deduplication, causing players who appeared in multiple game records
    to have their scores double-counted, and cumulative totals to grow incorrectly.

    Fix: maintain a running cumulative DT total (cum_dt_totals) updated once per
    round using a seen set, separate from the snapshot being built each round.
    """
    vote_totals  = defaultdict(lambda: {"team":"","votes":0,"name":""})
    cum_dt_totals = defaultdict(int)   # correct running total, updated once per round
    history = []
    round_scores = {}
    round_prices = {}

    for rn in sorted(all_rounds.keys()):
        round_scores[rn] = {}
        round_prices[rn] = {}
        for game in all_rounds[rn]["games"]:
            for p in game["all_players"]:
                key = make_player_key(p["player"], p["team"])
                round_scores[rn][key] = p["score"]
                if p.get("price"): round_prices[rn][key] = p["price"]
        for v in all_rounds[rn]["votes"]:
            key = make_player_key(v["player"], v["team"])
            round_scores[rn][key] = v["score"]

    for rn in sorted(all_rounds.keys()):
        data = all_rounds[rn]

        # Update vote totals
        for e in data["votes"]:
            key = make_player_key(e["player"], e["team"])
            vote_totals[key]["team"]  = e["team"]
            vote_totals[key]["name"]  = e["player"]
            vote_totals[key]["votes"] += e["votes"]

        # Update cumulative DT — deduplicated per round
        seen_this_round = set()
        for game in data["games"]:
            for p in game["all_players"]:
                key = make_player_key(p["player"], p["team"])
                if key not in seen_this_round:
                    seen_this_round.add(key)
                    cum_dt_totals[key] += p["score"]
                    if not vote_totals[key]["team"]:
                        vote_totals[key]["team"] = p["team"]
                        vote_totals[key]["name"] = p["player"]

        # Build snapshot using the correct cumulative totals
        snapshot = []
        for key, d in vote_totals.items():
            if d["votes"] == 0: continue
            round_votes = 0
            for v in data["votes"]:
                if make_player_key(v["player"], v["team"]) == key:
                    round_votes = v["votes"]; break
            snapshot.append({
                "player": d["name"], "team": d["team"], "key": key,
                "votes": d["votes"],
                "round_votes": round_votes,
                "total_dt": cum_dt_totals[key],
                "round_score": round_scores.get(rn, {}).get(key),
                "round_price": round_prices.get(rn, {}).get(key),
            })
        snapshot.sort(key=lambda x: (x["votes"], x["total_dt"]), reverse=True)
        # Keep ALL vote-getters so position tracking in the race is accurate.
        # The JS trims display to top 25 but uses the full list for prevPos tracking.
        history.append({"round": rn, "rankings": snapshot})

    return history

def compute_form_rating(scores):
    # Form = recent weighted average vs the player's OWN season average, NOT vs price.
    # It used to divide weighted average by price ("value per $1K"), which meant a
    # premium player scoring brilliantly could show a LOWER form rating than a cheap
    # player doing the same, purely because they cost more — expensive players were
    # being penalised for being good (which is why they're expensive in the first
    # place). Form should mean "hot or cold right now relative to themselves", so a
    # $1.4M superstar and a $250K rookie both scoring at their own season average
    # both land at 50 (neutral); either scoring 20% above their own average lands
    # at 70, regardless of price.
    if not scores or len(scores) < 2: return None
    weights = [1.5**i for i in range(len(scores))]
    weighted_avg = sum(s*w for s,w in zip(scores, weights)) / sum(weights)
    season_avg = sum(scores) / len(scores)
    if season_avg <= 0: return 50
    raw = 50 + (weighted_avg/season_avg - 1) * 100
    return max(0, min(100, round(raw)))

def compute_consistency(scores):
    if len(scores) < 2: return None
    mean     = sum(scores) / len(scores)
    variance = sum((s-mean)**2 for s in scores) / len(scores)
    std      = math.sqrt(variance)
    return max(0, min(100, round(100 - (std * 2))))

# ── HTML Template ─────────────────────────────────────────────────────────────
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>AFL Fantasy Brownlow</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;600;700;800&family=Barlow:wght@400;500;600&display=swap');
:root {
  --bg:#0d0f1a; --surface:#141726; --surface2:#1c2035;
  --border:rgba(var(--overlay-rgb),0.07); --accent:#e8a020; --accent2:#3b82f6;
  --red:#f87171; --green:#34d399; --yellow:#fbbf24;
  --silver:#c0c0c0; --bronze:#cd7f32;
  --text:#e8eaf0; --muted:#6b7280;
  --pos-def:#93c5fd; --pos-mid:#6ee7b7; --pos-ruc:#fcd34d; --pos-fwd:#fca5a5;
  --radius-sm:6px; --radius-md:9px; --radius-lg:12px;
  --sp-1:4px; --sp-2:8px; --sp-3:12px; --sp-4:16px; --sp-5:20px;
  --shadow-sm:0 1px 2px rgba(0,0,0,.25);
  --shadow-md:0 10px 28px rgba(0,0,0,.4);
  --shadow-glow:0 0 0 1px rgba(232,160,32,.3), 0 8px 20px rgba(232,160,32,.1);
  --ease:cubic-bezier(.4,0,.2,1);
  --dur-fast:.15s; --dur:.25s; --dur-slow:.4s;
  --overlay-rgb:255,255,255;
  --header-bg:rgba(20,23,38,.85);
  --bg-wash-1:rgba(232,160,32,.11); --bg-wash-2:rgba(59,130,246,.09); --bg-wash-3:rgba(232,160,32,.06);
}
[data-theme="light"] {
  --bg:#f2f3f7; --surface:#ffffff; --surface2:#eceef3;
  --border:rgba(15,18,32,0.1);
  --text:#161927; --muted:#5b6170;
  --shadow-sm:0 1px 2px rgba(15,18,32,.07);
  --shadow-md:0 10px 24px rgba(15,18,32,.1);
  --shadow-glow:0 0 0 1px rgba(232,160,32,.35), 0 8px 20px rgba(232,160,32,.12);
  --overlay-rgb:15,18,32;
  --header-bg:rgba(var(--overlay-rgb),.85);
  --bg-wash-1:rgba(232,160,32,.09); --bg-wash-2:rgba(59,130,246,.07); --bg-wash-3:rgba(232,160,32,.05);
}
@keyframes fadeSlideUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
@keyframes popIn{from{opacity:0;transform:scale(.95) translateY(4px)}to{opacity:1;transform:scale(1) translateY(0)}}
@keyframes barFill{from{width:0}}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden}
body{background:radial-gradient(ellipse 900px 600px at 10% -10%,var(--bg-wash-1),transparent 60%),radial-gradient(ellipse 900px 700px at 100% 0%,var(--bg-wash-2),transparent 55%),radial-gradient(ellipse 1100px 800px at 50% 115%,var(--bg-wash-3),transparent 60%),var(--bg);color:var(--text);font-family:'Barlow',sans-serif;display:flex;flex-direction:column;transition:background-color var(--dur-slow) var(--ease),color var(--dur-slow) var(--ease)}
header{display:flex;align-items:center;background:var(--header-bg);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border-bottom:1px solid var(--border);box-shadow:0 4px 24px rgba(0,0,0,.35);flex-shrink:0;position:relative;z-index:10;transition:background-color var(--dur-slow) var(--ease)}
.logo{padding:0 20px;height:56px;display:flex;align-items:center;gap:10px;white-space:nowrap;border-right:1px solid var(--border)}
.logo-mark{flex-shrink:0;filter:drop-shadow(0 0 6px rgba(232,160,32,.45))}
.logo-text{display:flex;flex-direction:column;justify-content:center;line-height:1.2}
.logo-title{font-weight:800;font-size:1.05rem;letter-spacing:.06em;color:var(--accent);text-shadow:0 0 20px rgba(232,160,32,.35)}
.logo-sub{font-size:.6rem;color:var(--muted);letter-spacing:.02em;white-space:nowrap}
nav{display:flex;flex:1;position:relative}
.nav-btn{padding:0 12px;height:56px;border:none;background:transparent;color:var(--muted);font-weight:700;font-size:.88rem;letter-spacing:.05em;text-transform:uppercase;cursor:pointer;white-space:nowrap;border-bottom:3px solid transparent;transition:color var(--dur) var(--ease),background var(--dur) var(--ease);border-right:1px solid var(--border)}
.nav-btn:hover{color:var(--text);background:rgba(var(--overlay-rgb),.03)}
.nav-btn:active{transform:scale(.97)}
.nav-btn.active{color:var(--accent);background:rgba(232,160,32,.06)}
.nav-indicator{position:absolute;left:0;bottom:0;width:0;height:3px;background:var(--accent);border-radius:2px 2px 0 0;box-shadow:0 0 10px rgba(232,160,32,.7);transition:transform var(--dur-slow) var(--ease),width var(--dur-slow) var(--ease);pointer-events:none}
.theme-toggle-btn{flex-shrink:0;width:40px;height:40px;margin:0 12px;border-radius:50%;border:1px solid var(--border);background:var(--surface2);color:var(--text);font-size:1.05rem;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:transform var(--dur) var(--ease),background var(--dur) var(--ease),border-color var(--dur) var(--ease)}
.theme-toggle-btn:hover{border-color:var(--accent);transform:rotate(20deg) scale(1.08)}
.theme-toggle-btn:active{transform:scale(.92)}
.rounds-badge{margin-left:auto;padding:0 20px;height:56px;display:flex;align-items:center;font-size:.75rem;color:var(--muted);border-left:1px solid var(--border);white-space:nowrap}
main{flex:1;overflow:hidden;position:relative}
.page{position:absolute;inset:0;overflow-y:auto;padding:20px 24px;display:none}
.page.active{display:block;animation:fadeSlideUp var(--dur-slow) var(--ease) both}
#page-leaderboard{padding:14px 0}
.page-head{display:flex;align-items:center;gap:var(--sp-2);margin-bottom:var(--sp-4);flex-wrap:nowrap}
.page-head-title{font-weight:800;font-size:1.3rem;letter-spacing:.01em;color:var(--text);white-space:nowrap;display:flex;align-items:center;gap:10px;flex-shrink:0;padding-left:12px;border-left:3px solid var(--accent)}
.page-head-actions{display:flex;align-items:center;gap:8px;margin-left:auto;flex-wrap:nowrap;white-space:nowrap}
.std-table{width:100%;border-collapse:collapse}
.std-table th{text-align:left;padding:9px 12px;font-size:.7rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border);font-weight:600;white-space:nowrap}
.std-table td{padding:9px 12px;border-bottom:1px solid var(--border);font-size:.95rem}
.std-table tr:hover td{background:rgba(var(--overlay-rgb),.02)}
.ta-r{text-align:right}
.player-link{font-weight:700;cursor:pointer;color:var(--text)}
.player-link:hover{color:var(--accent);text-decoration:underline}
.team-tag{display:inline-block;padding:1px 6px;border-radius:3px;background:var(--surface2);font-size:.7rem;color:var(--muted);font-family:'Barlow',sans-serif}
.pos-badge{display:inline-block;padding:1px 6px;border-radius:3px;background:rgba(59,130,246,.18);font-size:.7rem;color:#93c5fd;font-weight:700}
.archetype-badge{display:inline-block;padding:2px 7px;border-radius:3px;font-size:.65rem;font-weight:700;margin:3px 6px 3px 0;cursor:pointer;user-select:none}
.archetype-badge:hover{filter:brightness(1.25)}
.archetype-badge.no-data{opacity:.5;cursor:default;color:var(--muted);background:var(--surface2)}
.archetype-conclusion{font-size:.78rem;color:var(--text);opacity:.85;line-height:1.5;margin-top:4px;max-width:520px}
.archetype-detail{font-size:.75rem;color:var(--muted);line-height:1.5;margin-top:6px;padding:8px 10px;background:var(--surface2);border-radius:6px;max-width:520px}
.archetype-detail-label{font-weight:700}
.archetype-team-notes{margin-top:6px;padding-top:6px;border-top:1px dashed rgba(var(--overlay-rgb),.15)}
.archetype-team-notes>div{margin-top:3px}
.adv-stats-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(100px,1fr));gap:8px;margin-top:8px}
.adv-stat-tile{background:var(--surface2);border-radius:6px;padding:8px 10px;text-align:center}
.adv-stat-tile .lbl{font-size:.62rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.adv-stat-tile .val{font-size:1.1rem;font-weight:800;color:var(--text)}
.votes-hl{font-weight:800;color:var(--accent)}
.pos-num{font-weight:800;color:var(--muted)}
.pos-num.p1{color:var(--accent)}.pos-num.p2{color:var(--silver)}.pos-num.p3{color:var(--bronze)}
.round-tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:20px}
.round-tab{padding:6px 14px;border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--muted);font-weight:700;font-size:.9rem;cursor:pointer;transition:all .15s}
.round-tab:hover{border-color:var(--accent);color:var(--accent)}
.round-tab.active{background:var(--accent);border-color:var(--accent);color:#000}
.games-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}
.game-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;overflow:hidden}
.game-header{padding:10px 14px;background:var(--surface2);border-bottom:1px solid var(--border);font-weight:700;font-size:.95rem}
.vs{color:var(--muted);margin:0 6px;font-weight:400}
.vote-row{display:flex;align-items:center;gap:8px;padding:9px 14px;border-bottom:1px solid var(--border)}
.vote-row:last-child{border-bottom:none}
.vote-badge{width:56px;flex-shrink:0;font-weight:800;font-size:.85rem}
.v3{color:var(--accent)}.v2{color:var(--silver)}.v1{color:var(--bronze)}
.vote-player{flex:1;font-weight:600;font-size:.9rem;cursor:pointer}
.vote-player:hover{color:var(--accent)}
.vote-team{font-size:.74rem;color:var(--muted)}
.vote-score{font-weight:700;color:var(--muted)}
.search-wrap{position:relative;max-width:480px;margin-bottom:24px}
.search-input{width:100%;padding:11px 16px 11px 40px;background:var(--surface);border:1px solid var(--border);border-radius:8px;color:var(--text);font-family:'Barlow',sans-serif;font-size:.95rem;outline:none;transition:border .2s}
.search-input:focus{border-color:var(--accent2)}
.search-icon{position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--muted);font-size:1rem}
.search-results{position:absolute;top:calc(100% + 5px);left:0;right:0;background:var(--surface2);border:1px solid var(--border);border-radius:8px;max-height:240px;overflow-y:auto;z-index:100;display:none}
.search-result{padding:9px 14px;cursor:pointer;font-size:.9rem;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--border)}
.search-result:last-child{border-bottom:none}
.search-result:hover{background:rgba(var(--overlay-rgb),.05);color:var(--accent)}
.search-result .sr-sub{font-size:.74rem;color:var(--muted)}
.player-card{display:none}
.player-card.active{display:block}
.pc-header{margin-bottom:16px;display:flex;align-items:center;gap:14px}
.pc-avatar{width:58px;height:58px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:1.5rem;font-family:'Barlow Condensed',sans-serif;color:#000;background:var(--muted);box-shadow:var(--shadow-md)}
.pc-name{font-weight:800;font-size:1.9rem;line-height:1.1}
.pc-sub{color:var(--muted);font-size:.85rem;margin-top:4px}
.pc-rank-badge{display:inline-block;margin-top:6px;padding:3px 10px;border-radius:20px;border:1px solid;font-size:.72rem;font-weight:700}

/* ── Season Awards ── */
#awardsGrid{display:flex;flex-direction:column;gap:24px}
.award-group-title{font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:1.05rem;letter-spacing:.04em;color:var(--text);padding-bottom:6px;border-bottom:1px solid var(--border)}
.awards-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:14px}
.award-card{position:relative;overflow:hidden;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:18px;transition:transform var(--dur) var(--ease),box-shadow var(--dur) var(--ease);animation:fadeSlideUp .4s var(--ease) both}
.award-card:hover{transform:translateY(-4px);box-shadow:var(--shadow-md)}
.award-card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,var(--accent),var(--accent2))}
.award-icon{font-size:1.5rem;margin-bottom:6px}
.award-title{font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:.76rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin-bottom:12px}
.award-player{display:flex;align-items:center;gap:10px}
.award-avatar{width:38px;height:38px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:1.05rem;font-family:'Barlow Condensed',sans-serif;color:#0d0f1a}
.award-name{font-weight:700;font-size:.92rem;cursor:pointer}
.award-name:hover{color:var(--accent)}
.award-stat{margin-top:12px;font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:1.7rem;line-height:1}
.award-stat-sub{font-size:.7rem;color:var(--muted);margin-top:3px}
.award-tied-note{font-size:.66rem;color:var(--accent);font-weight:700;margin-top:2px}
.bookmark-btn{background:none;border:none;cursor:pointer;padding:4px;display:flex;align-items:center;opacity:.4;transition:opacity .15s,filter .15s;flex-shrink:0;margin-top:6px}
.bookmark-btn:hover{opacity:.75}
.bookmark-btn.bookmarked{opacity:1;filter:drop-shadow(0 0 5px var(--accent))}
.bookmark-btn svg{width:28px;height:28px}
.stats-row{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:20px}
.stat-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:10px 8px;position:relative;flex:1 1 92px;min-width:92px}
.stat-rank{position:absolute;bottom:5px;right:7px;font-size:.56rem;color:var(--muted);font-weight:700}
.stat-card-proj{border-style:dashed}
.stat-label{font-size:.64rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px;white-space:normal}
.stat-value{font-weight:800;font-size:1.3rem;overflow:hidden;text-overflow:ellipsis}
.rating-bar-wrap{margin-top:4px;height:3px;background:var(--surface2);border-radius:2px;overflow:hidden}
.rating-bar{height:100%;border-radius:2px}
.chart-section{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:20px;margin-bottom:14px}
.chart-title{font-weight:700;font-size:.75rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:14px}
.cba-corr{text-transform:none;letter-spacing:normal;font-weight:800;font-size:.72rem}
.chart-group-head{font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:.92rem;letter-spacing:.04em;color:var(--text);padding-bottom:6px;margin-bottom:12px;border-bottom:1px solid var(--border)}
.chart-group-head-ahead{color:var(--accent2)}
.player-charts-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start}
.chart-col{display:flex;flex-direction:column;min-width:0}
.chart-section-ahead{border-color:rgba(59,130,246,.25);background:linear-gradient(180deg,rgba(59,130,246,.05),transparent 40%),var(--surface)}
canvas{max-height:340px}
.race-key{display:flex;gap:20px;flex-wrap:wrap;margin-bottom:16px;padding:12px 16px;background:var(--surface);border:1px solid var(--border);border-radius:8px;font-size:.8rem;color:var(--muted)}
.race-key span{display:flex;align-items:center;gap:5px}
.race-controls{display:flex;align-items:center;gap:10px;margin-bottom:16px;flex-wrap:wrap}
.race-btn{padding:7px 16px;border-radius:7px;border:1px solid var(--border);background:var(--surface);color:var(--text);font-weight:700;font-size:.9rem;cursor:pointer;transition:all .15s}
.race-btn:hover{border-color:var(--accent);color:var(--accent)}
.race-btn.playing{background:var(--accent);border-color:var(--accent);color:#000}
.race-round-label{font-size:.95rem;color:var(--muted)}
.race-slider{flex:1;min-width:160px;accent-color:var(--accent)}
.move-up{color:var(--green)}.move-down{color:var(--red)}.move-same{color:var(--muted)}
.diff-tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:18px}
.diff-tab{padding:6px 14px;border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--muted);font-weight:700;font-size:.9rem;cursor:pointer;transition:all .15s}
.diff-tab:hover{border-color:var(--accent);color:var(--accent)}
.diff-tab.active{background:var(--accent);border-color:var(--accent);color:#000}
.diff-grid,.upcoming-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}
@media(max-width:1100px){.diff-grid,.upcoming-grid{grid-template-columns:repeat(4,1fr)}}
@media(max-width:700px){.diff-grid,.upcoming-grid{grid-template-columns:repeat(2,1fr)}}
.diff-card,.upcoming-card{border:1px solid var(--border);border-radius:var(--radius-md);padding:13px 16px;animation:fadeSlideUp .45s var(--ease) both}
.expand-toggle{margin-top:5px;font-size:.65rem;color:var(--accent2);cursor:pointer;transition:color var(--dur-fast) var(--ease)}
.expand-toggle:hover{color:var(--accent)}
.diff-team{font-weight:800;font-size:1.05rem;margin-bottom:4px}
.diff-meta{font-size:.75rem;color:var(--muted);margin-bottom:5px}
.diff-rating-num{font-weight:800;font-size:1.25rem}
.diff-legend{display:flex;gap:16px;margin-bottom:14px;font-size:.78rem}
.upcoming-games-list{margin-top:5px;display:none;font-size:.7rem;color:var(--muted)}
.upcoming-games-list.open{display:block}
.upcoming-game-row{display:flex;justify-content:space-between;padding:2px 0;border-bottom:1px solid rgba(var(--overlay-rgb),.04)}
.upcoming-game-row:last-child{border-bottom:none}

/* ── Trading Centre ── */
.trade-layout{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:800px){.trade-layout{grid-template-columns:1fr}}
.trade-panel{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px}
.trade-panel-title{font-weight:800;font-size:1rem;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.trade-list{list-style:none;display:flex;flex-direction:column;gap:5px;min-height:50px}

/* Upgraded trade item */
.trade-item{display:flex;align-items:flex-start;gap:7px;padding:10px 11px;background:var(--surface2);border-radius:8px;border:1px solid var(--border);transition:border-color .15s}
.trade-item:hover{border-color:rgba(var(--overlay-rgb),.14)}
.trade-item-body{flex:1;min-width:0}
.trade-item-name{font-weight:700;font-size:.88rem;display:flex;align-items:center;gap:5px;flex-wrap:wrap}
.trade-item-sub{display:flex;align-items:center;gap:6px;margin-top:3px;flex-wrap:wrap}
.trade-item-price{font-weight:700;font-size:.82rem;color:var(--text)}
.trade-item-remove{background:none;border:none;color:var(--muted);cursor:pointer;font-size:.85rem;padding:2px 4px;margin-top:1px;flex-shrink:0;border-radius:3px;transition:color .15s,background .15s}
.trade-item-remove:hover{color:var(--red);background:rgba(248,113,113,.1)}
.trade-budget{background:var(--surface2);border:1px solid var(--border);border-radius:9px;padding:13px 16px;margin-bottom:16px}
.trade-budget-label{font-size:.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin-bottom:4px}
.trade-budget-row{display:flex;align-items:center;gap:7px}
.trade-budget-input{background:var(--bg);border:1px solid var(--border);border-radius:5px;color:var(--text);font-weight:700;font-size:1.05rem;padding:5px 9px;width:110px;outline:none}
.trade-budget-input:focus{border-color:var(--accent2)}
.trade-summary{background:var(--surface2);border:1px solid var(--border);border-radius:9px;padding:13px 16px;margin-top:0}
.trade-summary-row{display:flex;justify-content:space-between;font-size:.85rem;padding:2px 0}
.trade-summary-row.total{font-weight:700;font-size:.9rem;border-top:1px solid var(--border);margin-top:5px;padding-top:6px}
.trade-result{margin-top:9px;padding:9px 13px;border-radius:6px;font-weight:700;font-size:.95rem;text-align:center}
.trade-result.ok{background:rgba(52,211,153,.15);color:var(--green);border:1px solid rgba(52,211,153,.3)}
.trade-result.over{background:rgba(248,113,113,.15);color:var(--red);border:1px solid rgba(248,113,113,.3)}
.trade-error{font-size:.74rem;color:var(--red);margin-top:3px;min-height:14px}
.trade-limit-badge{font-size:.68rem;color:var(--muted);margin-left:auto}
.pill-btn{padding:3px 8px;border-radius:4px;font-size:.7rem;font-weight:700;cursor:pointer;border:1px solid}
.pill-in{background:rgba(52,211,153,.1);color:var(--green);border-color:rgba(52,211,153,.3)}
.pill-out{background:rgba(248,113,113,.1);color:var(--red);border-color:rgba(248,113,113,.3)}
.pill-rm{background:none;color:var(--muted);border-color:var(--border)}
.pill-btn:hover{opacity:.8}

/* Position color badges */
.pos-def{background:rgba(59,130,246,.2);color:#93c5fd;border:1px solid rgba(59,130,246,.3)}
.pos-mid{background:rgba(52,211,153,.15);color:#6ee7b7;border:1px solid rgba(52,211,153,.25)}
.pos-ruc{background:rgba(251,191,36,.15);color:#fcd34d;border:1px solid rgba(251,191,36,.25)}
.pos-fwd{background:rgba(248,113,113,.15);color:#fca5a5;border:1px solid rgba(248,113,113,.25)}
.pos-chip{display:inline-block;padding:0 5px;border-radius:3px;font-size:.65rem;font-weight:700}

/* Mini stat chips on trade items */
.mini-stat{font-size:.68rem;color:var(--muted);display:inline-flex;align-items:center;gap:2px}
.mini-stat b{color:var(--text);font-weight:700}
.mini-stat.good b{color:var(--green)}
.mini-stat.bad b{color:var(--red)}

/* Stats compare in summary */
.stats-compare-strip{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px}
.scs-card{background:var(--surface2);border:1px solid var(--border);border-radius:7px;padding:9px 11px}
.scs-label{font-size:.6rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px;font-weight:700}
.scs-row{display:flex;justify-content:space-between;font-size:.78rem;padding:1px 0}
.scs-val{font-weight:700}
.net-arrow{font-size:.8rem;font-weight:800;padding:4px 10px;border-radius:5px;text-align:center;margin-top:6px}
.net-arrow.pos{background:rgba(52,211,153,.12);color:var(--green)}
.net-arrow.neg{background:rgba(248,113,113,.12);color:var(--red)}
.net-arrow.neu{background:rgba(var(--overlay-rgb),.05);color:var(--muted)}

/* Bookmark section improvements */
.bm-item{display:flex;align-items:center;gap:7px;padding:8px 10px;background:var(--surface2);border-radius:7px;border:1px solid var(--border);margin-bottom:5px}
.bm-name{font-weight:700;font-size:.84rem;cursor:pointer;flex:1;min-width:0}
.bm-name:hover{color:var(--accent)}
.bm-sub{font-size:.7rem;color:var(--muted);margin-top:1px}
.bm-price{font-weight:700;font-size:.82rem;color:var(--text);flex-shrink:0}
.bm-actions{display:flex;gap:3px;flex-shrink:0}
/* Fixture table in player card */
.fix-table{width:100%;border-collapse:collapse;font-size:.82rem;margin-top:4px}
.fix-table th{font-size:.62rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;padding:4px 8px;border-bottom:1px solid var(--border);font-weight:600;text-align:left}
.fix-table td{padding:5px 8px;border-bottom:1px solid rgba(var(--overlay-rgb),.04)}
.fix-table tr:last-child td{border-bottom:none}
.fix-proj{font-weight:800}
/* Price support/resistance label */
.price-level-label{font-size:.68rem;font-style:italic}
/* Leaderboard form boxes */
.form-boxes{display:flex;gap:3px;align-items:center}
.form-box{width:20px;height:20px;border-radius:3px;display:inline-flex;align-items:center;justify-content:center;font-size:.65rem;font-weight:800;border:1px solid rgba(var(--overlay-rgb),.07);cursor:pointer;transition:transform var(--dur-fast) var(--ease),border-color var(--dur-fast) var(--ease)}
.form-box:hover{transform:translateY(-2px) scale(1.12);border-color:var(--accent2)}
.inj-tag{display:inline-block;background:rgba(248,113,113,.2);color:var(--red);font-size:.6rem;font-weight:700;padding:1px 5px;border-radius:3px;vertical-align:middle;margin-left:2px}
.sus-tag{background:rgba(251,191,36,.2);color:var(--yellow)}
.form-box-0{background:rgba(var(--overlay-rgb),.04);color:transparent}
.form-box-1{background:rgba(251,191,36,.25);color:#fbbf24;border-color:rgba(251,191,36,.4)}
.form-box-2{background:rgba(163,230,53,.25);color:#a3e635;border-color:rgba(163,230,53,.4)}
.form-box-3{background:rgba(52,211,153,.3);color:#34d399;border-color:rgba(52,211,153,.5)}

.section-title{font-weight:800;font-size:1.25rem;letter-spacing:.04em;margin-bottom:14px;color:var(--text)}
/* Scenario overlay */
.scenario-overlay{position:fixed;inset:0;background:var(--bg);z-index:500;display:none;flex-direction:column}
.scenario-overlay.active{display:flex}
.scenario-overlay-header{display:flex;align-items:center;gap:14px;padding:14px 24px;background:var(--surface);border-bottom:1px solid var(--border);flex-shrink:0}
.scenario-overlay-title{font-weight:800;font-size:1.2rem;flex:1}
.overlay-close-btn{padding:7px 16px;border-radius:7px;border:1px solid var(--border);background:transparent;color:var(--muted);font-weight:700;font-size:.9rem;cursor:pointer}
.overlay-close-btn:hover{color:var(--red);border-color:var(--red)}
.scenario-overlay-body{flex:1;overflow-y:auto;padding:28px;background:radial-gradient(ellipse 900px 500px at 50% -10%,rgba(232,160,32,.06),transparent 60%)}
.scenarios-compare-grid{display:grid;gap:16px;max-width:1400px;margin:0 auto}
/* Scenario card matches trading panel style */
.scenario-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:18px}
.sc-net-hero{border-radius:var(--radius-md);padding:14px 16px;margin:12px 0 14px;text-align:center;position:relative;overflow:hidden}
.sc-net-hero.pos{background:linear-gradient(135deg,rgba(52,211,153,.18),rgba(52,211,153,.03));border:1px solid rgba(52,211,153,.4)}
.sc-net-hero.neg{background:linear-gradient(135deg,rgba(248,113,113,.18),rgba(248,113,113,.03));border:1px solid rgba(248,113,113,.4)}
.sc-net-hero.neu{background:var(--surface2);border:1px solid var(--border)}
.sc-net-hero-val{font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:2.5rem;line-height:1}
.sc-net-hero.pos .sc-net-hero-val{color:var(--green);text-shadow:0 0 24px rgba(52,211,153,.35)}
.sc-net-hero.neg .sc-net-hero-val{color:var(--red);text-shadow:0 0 24px rgba(248,113,113,.35)}
.sc-net-hero-val span{font-size:.62rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-left:4px}
.sc-net-hero-sub{font-size:.76rem;color:var(--muted);margin-top:4px}
.sc-net-hero-pos{margin-top:8px;font-size:.72rem}
.sc-side{border-radius:var(--radius-md);padding:12px 12px 8px;margin-bottom:10px}
.sc-side-in{background:rgba(52,211,153,.05);border:1px solid rgba(52,211,153,.2)}
.sc-side-out{background:rgba(248,113,113,.05);border:1px solid rgba(248,113,113,.2)}
.sc-side-head{font-weight:800;font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px}
.sc-side-in .sc-side-head{color:var(--green)}
.sc-side-out .sc-side-head{color:var(--red)}
.sc-tile-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:10px}
.sc-tile{background:rgba(0,0,0,.16);border-radius:7px;padding:7px 4px;text-align:center}
.sc-tile-val{font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:1.02rem}
.sc-tile-lbl{font-size:.55rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-top:1px}
.sc-empty{font-size:.78rem;color:var(--muted);padding:6px 0}
.sc-more-toggle{font-size:.68rem;color:var(--muted);margin-top:8px;padding:5px 0}
.scenario-card:hover{border-color:rgba(var(--overlay-rgb),.12)}
.scenario-card-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid var(--border)}
.scenario-name-input{background:transparent;border:none;border-bottom:1px solid var(--border);color:var(--text);font-weight:800;font-size:1.05rem;outline:none;width:180px}
.scenario-name-input:focus{border-bottom-color:var(--accent)}
.scenario-section-label{font-size:.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin:10px 0 5px}
.scenario-tags{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:4px}
.stag{display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:5px;font-size:.78rem;font-weight:600}
.stag-in{background:rgba(52,211,153,.12);border:1px solid rgba(52,211,153,.3);color:var(--green)}
.stag-out{background:rgba(248,113,113,.12);border:1px solid rgba(248,113,113,.3);color:var(--red)}
.stag-rm{background:none;border:none;cursor:pointer;color:inherit;font-size:.75rem;opacity:.6;padding:0}
.sc-search{width:100%;padding:6px 10px;background:var(--surface2);border:1px solid var(--border);border-radius:6px;color:var(--text);font-family:'Barlow',sans-serif;font-size:.82rem;outline:none;margin-top:5px}
.sc-search:focus{border-color:var(--accent2)}
.sc-dropdown{position:absolute;left:0;right:0;top:calc(100% + 3px);background:var(--surface2);border:1px solid var(--border);border-radius:7px;max-height:160px;overflow-y:auto;z-index:600;display:none}
.sc-dropdown-item{padding:7px 11px;cursor:pointer;font-size:.82rem;display:flex;justify-content:space-between;border-bottom:1px solid var(--border)}
.sc-dropdown-item:last-child{border-bottom:none}
.sc-dropdown-item:hover{background:rgba(var(--overlay-rgb),.05);color:var(--accent)}
.sc-rel{position:relative}
.stats-compare-box{margin-top:12px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;overflow:hidden}
.stats-collapse-header{display:flex;align-items:center;justify-content:space-between;padding:10px 13px;cursor:pointer;user-select:none;font-size:.82rem;font-weight:700}
.stats-collapse-header:hover{background:rgba(var(--overlay-rgb),.03)}
.stats-collapse-arrow{font-size:.7rem;transition:transform .2s;color:var(--muted)}
.stats-collapse-arrow.open{transform:rotate(180deg)}
.stats-collapse-body{display:none;padding:0 13px 13px}
.stats-collapse-body.open{display:block}
.scb-row{display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid rgba(var(--overlay-rgb),.04)}
.scb-row:last-child{border-bottom:none}
.scb-label{color:var(--muted)}
.scb-val{font-weight:700}
.winner-crown{background:linear-gradient(135deg,#ffe08a,var(--accent));color:#2a1c00;font-weight:800;font-size:.66rem;letter-spacing:.04em;padding:4px 10px;border-radius:20px;margin-left:6px;box-shadow:0 2px 10px rgba(232,160,32,.5);white-space:nowrap}
.scenario-winner{border-color:var(--accent) !important;box-shadow:var(--shadow-glow);position:relative}
.scenario-winner::before{content:'';position:absolute;top:-1px;left:-1px;right:-1px;height:3px;background:linear-gradient(90deg,var(--accent),#ffe08a,var(--accent));border-radius:var(--radius-lg) var(--radius-lg) 0 0}
.add-scenario-btn{padding:8px 18px;border-radius:8px;border:1px solid var(--accent);background:transparent;color:var(--accent);font-weight:700;font-size:.9rem;cursor:pointer}
.add-scenario-btn:hover{background:var(--accent);color:#000}
.add-scenario-btn:disabled{opacity:.35;cursor:not-allowed;border-color:var(--muted);color:var(--muted)}
.open-scenarios-btn{padding:8px 18px;border-radius:8px;border:1px solid var(--accent);background:transparent;color:var(--accent);font-weight:700;font-size:.9rem;cursor:pointer;margin-top:14px}
.open-scenarios-btn:hover{background:var(--accent);color:#000}
.info-btn{padding:5px 11px;border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--muted);font-weight:700;font-size:.8rem;cursor:pointer;transition:all .15s;white-space:nowrap}
.info-btn:hover{border-color:var(--accent2);color:var(--accent2)}
.info-btn.open{border-color:var(--accent2);color:var(--accent2);background:rgba(59,130,246,.08)}
.info-panel{display:none;background:var(--surface);border:1px solid var(--accent2);border-radius:8px;padding:14px 18px;margin-bottom:18px;font-size:.82rem;color:var(--muted);line-height:1.7}
.info-panel.open{display:block}
.info-panel b{color:var(--text)}
.info-panel .info-heading{font-weight:800;font-size:.95rem;color:var(--accent2);margin-bottom:6px}
.info-panel ul{padding-left:16px;margin-top:4px}
.info-panel li{margin-bottom:3px}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
/* My Team & Rolling 22 */
.myteam-budget-box{background:var(--surface2);border:1px solid var(--border);border-radius:7px}
.myteam-budget-label{font-size:.58rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:2px}
.myteam-budget-val{font-weight:800;font-size:1rem}
.analyse-btn{padding:8px 16px;border-radius:7px;border:none;background:var(--accent);color:#000;font-weight:800;font-size:.88rem;cursor:pointer}
.analyse-btn:hover{opacity:.85}
.analyse-btn:disabled{opacity:.35;cursor:not-allowed}
/* Position section headers */
.pos-section{margin-bottom:14px}
.pos-section-label{font-weight:800;font-size:.72rem;letter-spacing:.12em;text-transform:uppercase;padding:4px 10px 4px 0;margin-bottom:6px;display:inline-flex;align-items:center;gap:6px}
.pos-section-label.def{color:#93c5fd}.pos-section-label.mid{color:#6ee7b7}.pos-section-label.ruc{color:#fcd34d}.pos-section-label.fwd{color:#fca5a5}.pos-section-label.bench{color:var(--muted)}
.pos-row{display:grid;gap:7px;margin-bottom:4px}
/* Player card in team grid */
.squad-card{background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:8px 9px;position:relative;cursor:default;transition:border-color .15s;min-height:88px;display:flex;flex-direction:column;gap:3px}
.squad-card:hover{border-color:rgba(var(--overlay-rgb),.18)}
.squad-card.bench-card{background:rgba(var(--overlay-rgb),.025);opacity:.85}
.squad-card.empty-card{border:1px dashed rgba(var(--overlay-rgb),.12);background:transparent;cursor:pointer;display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:.75rem}
.squad-card.empty-card:hover{border-color:var(--accent2);color:var(--accent2)}
.squad-card-pos{position:absolute;top:6px;left:7px;font-size:.58rem;font-weight:800;padding:1px 4px;border-radius:3px}
.squad-card-name{font-weight:700;font-size:.8rem;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:14px}
.squad-card-name:hover{color:var(--accent)}
.squad-card-team{font-size:.65rem;color:var(--muted)}
.squad-card-avg{font-weight:800;font-size:1.05rem}
.squad-card-price{font-size:.68rem;color:var(--muted)}
.squad-card-sig{position:absolute;top:6px;right:7px;font-size:.6rem;font-weight:800;padding:1px 5px;border-radius:3px}
.squad-card-remove{position:absolute;bottom:5px;right:6px;background:none;border:none;color:rgba(var(--overlay-rgb),.2);cursor:pointer;font-size:.75rem;padding:1px 3px;border-radius:2px}
.squad-card-remove:hover{color:var(--red)}
.squad-card-trend{font-size:.62rem;font-weight:700}
/* Upgrade cards */
.upgrade-card{background:var(--surface);border:1px solid var(--border);border-radius:9px;padding:12px 15px;margin-bottom:8px}
.upgrade-card.urgent{border-left:3px solid var(--green)}
.upgrade-card.mild{border-left:3px solid var(--yellow)}
.upgrade-card.monitor{border-left:3px solid var(--muted)}
.upgrade-rank{font-weight:800;font-size:1.4rem;min-width:36px;text-align:center}
.trade-pair{display:flex;align-items:center;gap:8px;padding:8px 10px;background:var(--surface2);border:1px solid var(--border);border-radius:7px;margin-top:8px;flex-wrap:wrap}
.trade-arrow{color:var(--muted);font-size:1.1rem;flex-shrink:0}
/* Rolling 22 */
.r22-section{margin-bottom:16px}
.r22-label{font-weight:800;font-size:.75rem;letter-spacing:.1em;text-transform:uppercase;margin-bottom:6px;padding:3px 0}
.r22-row{display:grid;gap:6px;margin-bottom:4px}
.r22-card{background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:8px 10px}
.r22-card-name{font-weight:700;font-size:.82rem;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.r22-card-name:hover{color:var(--accent)}
.r22-card-team{font-size:.64rem;color:var(--muted)}
.r22-card-score{font-weight:800;font-size:1.1rem}
.r22-card-price{font-size:.64rem;color:var(--muted)}

/* ── Design-system enhancements: motion, hover, consistency ── */
.round-tab,.diff-tab{border-radius:var(--radius-sm)}
.round-tab:hover,.diff-tab:hover{transform:translateY(-1px)}
.round-tab.active,.diff-tab.active{box-shadow:var(--shadow-glow)}
.rating-bar{animation:barFill .8s var(--ease) both}
.games-grid,.r22-row,.pos-row,.pitch-cards,.scenarios-compare-grid{animation:fadeSlideUp var(--dur-slow) var(--ease) both}
.pitch-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(108px,1fr));gap:6px}
.pitch-row-flex{display:flex;gap:14px;align-items:flex-start}
.pitch-bench-col{flex:0 0 232px;padding-left:14px;border-left:1px dashed rgba(var(--overlay-rgb),.1)}
.mt-tips-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px}
.r22-bubble{margin-top:8px;padding-top:8px;border-top:1px dashed rgba(var(--overlay-rgb),.08);display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.r22-bubble-label{font-size:.6rem;color:rgba(var(--overlay-rgb),.25);text-transform:uppercase;letter-spacing:.08em;font-weight:700;flex-shrink:0}
.r22-bubble-chip{font-size:.72rem;color:var(--muted);cursor:pointer;background:rgba(var(--overlay-rgb),.03);border:1px solid var(--border);border-radius:20px;padding:3px 10px;transition:all var(--dur-fast) var(--ease)}
.r22-bubble-chip:hover{border-color:var(--accent2);color:var(--accent2)}
.r22-bubble-chip b{color:var(--text);font-weight:700;margin-left:2px}
.pitch-bench-col .pitch-cards{grid-template-columns:repeat(2,1fr)}
.pitch-starters-col{flex:1;min-width:0}
.pitch-bench-label{font-size:.56rem;color:rgba(var(--overlay-rgb),.2);text-transform:uppercase;letter-spacing:.1em;margin-bottom:4px;font-weight:700}
@media(max-width:720px){.pitch-row-flex{flex-direction:column}.pitch-bench-col{flex:none;width:100%;padding-left:0;padding-top:10px;border-left:none;border-top:1px dashed rgba(var(--overlay-rgb),.1)}}

/* ── Upgrade recommendations ── */
.rec-summary{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
.rec-summary-chip{background:var(--surface2);border:1px solid var(--border);border-radius:7px;padding:6px 12px;font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:1.05rem}
.rec-summary-chip span{font-size:.6rem;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.06em;margin-left:3px}
.rec-item{background:var(--surface);border:1px solid var(--border);border-radius:9px;margin-bottom:6px;overflow:hidden}
.rec-row{display:flex;align-items:center;gap:10px;padding:9px 12px;cursor:pointer}
.rec-row:hover{background:rgba(var(--overlay-rgb),.02)}
.rec-score{flex-shrink:0;width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:.9rem;color:#0d0f1a}
.rec-main{flex:1;min-width:0}
.rec-name{font-weight:700;font-size:.86rem;display:flex;align-items:center;gap:6px}
.rec-sub{font-size:.68rem;color:var(--muted);font-weight:700;display:inline-block;margin-right:8px}
.rec-ring-sm{flex-shrink:0;width:34px;height:34px;border-radius:50%;display:flex;align-items:center;justify-content:center}
.rec-ring-sm span{width:26px;height:26px;border-radius:50%;background:var(--surface2);display:flex;align-items:center;justify-content:center;font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:.72rem}
.rec-priority-label{font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:.85rem;letter-spacing:.04em;margin:14px 0 8px;color:var(--text)}
.rec-priority-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px;margin-bottom:18px}
.rec-priority-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:14px;transition:transform var(--dur) var(--ease),box-shadow var(--dur) var(--ease)}
.rec-priority-card:hover{transform:translateY(-3px);box-shadow:var(--shadow-md)}
.rec-priority-head{display:flex;align-items:center;gap:8px;margin-bottom:10px}
.rec-priority-trade{display:flex;align-items:center;gap:10px}
.rec-priority-trade>div{flex:1;min-width:0}
.rec-priority-tag{font-size:.56rem;font-weight:800;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.rec-priority-name{font-weight:700;font-size:.85rem;margin-top:1px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rec-priority-meta{font-size:.68rem;color:var(--muted);margin-top:1px}
.rec-priority-arrow{color:var(--muted);font-size:1.1rem;flex-shrink:0}
.rec-priority-foot{display:flex;align-items:center;justify-content:space-between;margin-top:10px;padding-top:10px;border-top:1px solid var(--border);font-size:.75rem}

/* ── Fixtures sortable tables ── */
.sortable-table th.sortable{cursor:pointer;user-select:none;transition:color var(--dur-fast) var(--ease)}
.sortable-table th.sortable:hover{color:var(--accent)}
.sortable-table th.sortable::after{content:'';display:inline-block;width:8px}
.sortable-table th.sortable.sort-asc::after{content:'\25B2';color:var(--accent);font-size:.6rem;margin-left:3px}
.sortable-table th.sortable.sort-desc::after{content:'\25BC';color:var(--accent);font-size:.6rem;margin-left:3px}

/* ── Fixtures game strip ── */
.fixture-games-strip{display:flex;gap:10px;overflow-x:auto;padding:2px 2px 10px;margin-bottom:16px}
.fx-game-card{flex:0 0 232px;border:1px solid var(--border);border-radius:var(--radius-md);padding:16px;cursor:pointer;transition:transform var(--dur) var(--ease),box-shadow var(--dur) var(--ease),border-color var(--dur) var(--ease);animation:fadeSlideUp .4s var(--ease) both}
.fx-game-card:hover{transform:translateY(-3px);box-shadow:var(--shadow-md)}
.fx-game-card.active{border-width:2px;box-shadow:var(--shadow-glow)}
.fx-game-teams{display:flex;align-items:center;justify-content:center;gap:8px;font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:1rem;text-align:center;white-space:nowrap}
.fx-game-vs{color:var(--muted);font-size:.62rem;font-weight:700;text-transform:uppercase;flex-shrink:0}
.fx-game-teaser{margin-top:10px;font-size:.68rem;color:var(--text);text-align:center;line-height:1.4}
.fx-game-teaser-muted{color:var(--muted);opacity:.55}
.fx-game-votes{margin-top:10px;display:flex;flex-direction:column;gap:5px}
.fx-game-vote-row{display:flex;align-items:center;gap:6px;font-size:.66rem}
.fx-game-vote-name{flex:1;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.fx-game-vote-score{color:var(--muted);font-weight:700;flex-shrink:0}
.round-tab-future{border-style:dashed;opacity:.85}
.game-card,.stat-card,.diff-card,.upcoming-card,.scenario-card,.upgrade-card,.squad-card,.r22-card,.bm-item,.trade-item{transition:transform var(--dur) var(--ease),box-shadow var(--dur) var(--ease),border-color var(--dur) var(--ease)}
.game-card:hover,.stat-card:hover,.diff-card:hover,.upcoming-card:hover,.scenario-card:hover,.upgrade-card:hover,.squad-card:hover:not(.empty-card),.r22-card:hover,.bm-item:hover,.trade-item:hover{transform:translateY(-3px);box-shadow:var(--shadow-md)}
.nav-btn,.tab-btn,.round-tab,.diff-tab,.race-btn,.info-btn,.analyse-btn,.pill-btn,.add-scenario-btn,.open-scenarios-btn,.overlay-close-btn{transition-property:all;transition-duration:var(--dur-fast);transition-timing-function:var(--ease)}
.nav-btn:active,.tab-btn:active,.round-tab:active,.diff-tab:active,.race-btn:active,.info-btn:active,.analyse-btn:active,.pill-btn:active,.add-scenario-btn:active,.open-scenarios-btn:active,.overlay-close-btn:active{transform:scale(.95)}
.scenario-overlay.active{animation:fadeIn var(--dur) var(--ease)}
.scenario-card{animation:popIn var(--dur-slow) var(--ease) both}
::-webkit-scrollbar-thumb{transition:background var(--dur)}
::-webkit-scrollbar-thumb:hover{background:var(--muted)}

/* ── Leaderboard podium ── */
.podium{display:grid;grid-template-columns:1fr 1.15fr 1fr;gap:16px;align-items:end;margin:4px 0 26px}
.podium-card{position:relative;overflow:hidden;text-align:center;border-radius:var(--radius-lg);border:1px solid var(--border);background:var(--surface);padding:20px 14px 18px;opacity:0;animation:fadeSlideUp .5s var(--ease) both;transition:transform var(--dur) var(--ease),box-shadow var(--dur) var(--ease)}
.podium-card:hover{transform:translateY(-4px);box-shadow:var(--shadow-md)}
.podium-card.rank-1{padding-top:26px;background:linear-gradient(165deg,rgba(232,160,32,.18),rgba(232,160,32,.02) 65%);border-color:rgba(232,160,32,.4);box-shadow:var(--shadow-glow)}
.podium-card.rank-2{background:linear-gradient(165deg,rgba(192,192,192,.14),rgba(192,192,192,.02) 65%);border-color:rgba(192,192,192,.3)}
.podium-card.rank-3{background:linear-gradient(165deg,rgba(205,127,50,.14),rgba(205,127,50,.02) 65%);border-color:rgba(205,127,50,.3)}
.podium-rankno{position:absolute;top:2px;right:10px;font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:2.4rem;color:rgba(var(--overlay-rgb),.05);line-height:1;pointer-events:none}
.podium-medal{font-size:1.5rem;margin-bottom:4px}
.podium-avatar{width:54px;height:54px;border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto 10px;font-weight:800;font-size:1.3rem;font-family:'Barlow Condensed',sans-serif;color:#000;background:var(--muted)}
.podium-card.rank-1 .podium-avatar{width:66px;height:66px;font-size:1.6rem;background:var(--accent)}
.podium-card.rank-2 .podium-avatar{background:var(--silver)}
.podium-card.rank-3 .podium-avatar{background:var(--bronze)}
.podium-name{font-weight:800;font-size:1rem;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.podium-name:hover{color:var(--accent)}
.podium-team{margin:4px 0 12px}
.podium-votes{font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:2rem;line-height:1;color:var(--text)}
.podium-card.rank-1 .podium-votes{font-size:2.5rem;color:var(--accent)}
.podium-card.rank-2 .podium-votes{color:var(--silver)}
.podium-card.rank-3 .podium-votes{color:var(--bronze)}
.podium-votes span{display:block;font-size:.6rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin-top:2px}
.podium-sub{font-size:.72rem;color:var(--muted);margin-top:8px}
@media(max-width:820px){.podium{grid-template-columns:1fr 1fr 1fr}.podium-card.rank-1{padding-top:20px}.podium-card.rank-1 .podium-avatar{width:54px;height:54px;font-size:1.3rem}.podium-card.rank-1 .podium-votes{font-size:2rem}}

/* ── Pitch backdrop (My Team / Rolling 22) ── */
.pitch-panel{position:relative;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:20px;overflow:hidden}
.pitch-panel::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,var(--accent),var(--accent2) 55%,transparent)}
.pitch-pos-row{margin-bottom:20px}
.pitch-pos-row:last-child{margin-bottom:0}
.pitch-pos-label{display:inline-flex;align-items:center;font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:.82rem;letter-spacing:.08em;text-transform:uppercase;color:#0d0f1a;padding:5px 16px;border-radius:6px;margin-bottom:10px}
.pitch-pos-meta{font-size:.6rem;color:rgba(var(--overlay-rgb),.22);margin-bottom:6px;display:flex;gap:8px;font-weight:700}
.pitch-pos-meta span{color:rgba(var(--overlay-rgb),.13);font-weight:400}

/* ── Trade quality gauge ── */
.score-ring{width:62px;height:62px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;transition:background .6s var(--ease)}
.score-ring-inner{width:48px;height:48px;border-radius:50%;background:var(--surface2);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:1.15rem;font-family:'Barlow Condensed',sans-serif}

/* ── My Team slot drag & drop ── */
.dragging{opacity:.32}
.drag-target{outline:2px dashed var(--accent2);outline-offset:-2px;background:rgba(59,130,246,.1) !important}
.card-swap-flash{animation:popIn .45s var(--ease)}
.pos-row-reject{animation:rejectShake .35s var(--ease)}
@keyframes rejectShake{0%,100%{transform:translateX(0)}25%{transform:translateX(-5px)}75%{transform:translateX(5px)}}

/* ── Matchup Difficulty callout ── */
.matchup-callout{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px}
.callout-chip{border-radius:var(--radius-md);padding:10px 14px;display:flex;flex-direction:column;gap:2px}
.callout-chip.good{background:rgba(52,211,153,.08);border:1px solid rgba(52,211,153,.3)}
.callout-chip.bad{background:rgba(248,113,113,.08);border:1px solid rgba(248,113,113,.3)}
.callout-eyebrow{font-size:.62rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);font-weight:700}
.callout-chip b{font-size:1.1rem;font-weight:800}
.callout-chip.good b{color:var(--green)}
.callout-chip.bad b{color:var(--red)}
.callout-sub{font-size:.68rem;color:var(--muted)}
@media(max-width:600px){.matchup-callout{grid-template-columns:1fr}}

/* ── Leaderboard stats strip ── */
.lb-stats-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:24px;animation:fadeSlideUp .5s var(--ease) both;animation-delay:.15s}
.lbs-item{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-md);padding:10px 14px;text-align:center}
.lbs-val{font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:1.4rem;color:var(--text)}
.lbs-lbl{font-size:.62rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-top:2px}
@media(max-width:700px){.lb-stats-strip{grid-template-columns:1fr 1fr}}

/* ── Targets ── */
.tf-dropdown-toggle{display:flex;align-items:center;gap:8px;width:100%;margin-bottom:16px;padding:12px 16px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);color:var(--text);font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:1rem;letter-spacing:.02em;cursor:pointer;transition:border-color var(--dur) var(--ease)}
.tf-dropdown-toggle:hover{border-color:var(--accent)}
.tf-dropdown-toggle #tfDropdownArrow{margin-left:auto;transition:transform var(--dur) var(--ease)}
.tf-dropdown-toggle.open #tfDropdownArrow{transform:rotate(180deg)}
.targets-filter-wrap{display:none}
.targets-filter-wrap.open{display:block;margin-bottom:20px;animation:fadeSlideUp var(--dur-slow) var(--ease) both}
.targets-filter-bar{display:flex;align-items:end;gap:14px;flex-wrap:wrap;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:14px 16px;margin-bottom:16px}
.tf-field{display:flex;flex-direction:column;gap:4px}
.tf-field label{font-size:.64rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;font-weight:700}
.tf-field input,.tf-field select{background:var(--surface2);border:1px solid var(--border);border-radius:6px;color:var(--text);padding:7px 10px;font-family:'Barlow',sans-serif;font-size:.85rem;outline:none;width:130px;transition:border-color .15s}
.tf-field input:focus,.tf-field select:focus{border-color:var(--accent2)}
.tf-count{margin-left:auto;font-size:.78rem;color:var(--muted);align-self:center}
.targets-columns{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;align-items:start}
.targets-col{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);overflow:hidden;display:flex;flex-direction:column}
.targets-col-head{display:flex;align-items:baseline;justify-content:space-between;gap:8px;padding:12px 14px;font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:1rem;letter-spacing:.02em;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--surface2);z-index:1}
.targets-col-head.tier-premiums{color:var(--accent)}
.targets-col-head.tier-midprice{color:var(--accent2)}
.targets-col-head.tier-rookies{color:var(--green)}
.targets-col-sub{font-size:.68rem;font-weight:600;color:var(--muted);letter-spacing:.02em}
.targets-col-list{max-height:70vh;overflow-y:auto}
.target-row{display:flex;align-items:center;gap:10px;padding:8px 14px;border-bottom:1px solid var(--border);cursor:pointer;transition:background var(--dur-fast) var(--ease)}
.target-row:last-child{border-bottom:none}
.target-row:hover{background:rgba(var(--overlay-rgb),.04)}
.target-rank{flex-shrink:0;width:22px;text-align:center;font-family:'Barlow Condensed',sans-serif;font-weight:800;color:var(--muted);font-size:.85rem}
.target-info{flex:1;min-width:0;display:flex;flex-direction:column;gap:1px}
.target-name{font-weight:700;font-size:.86rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.target-sub{font-size:.66rem;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.target-metric{flex-shrink:0;text-align:right;font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:.92rem}
.target-metric-sub{font-size:.6rem;color:var(--muted);font-weight:600}

/* ── Mobile ── */
.table-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
@media(max-width:860px){
  .stats-row{flex-wrap:wrap}
  .stat-card{flex:0 1 100px;min-width:88px}
  .targets-columns{grid-template-columns:1fr}
  .tf-count{margin-left:0;width:100%}
  .tf-field input,.tf-field select{width:110px}
  .targets-col-list{max-height:50vh}
  .logo{padding:0 12px;gap:8px}
  .logo-sub{display:none}
  header{flex-wrap:nowrap}
  nav{overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none}
  nav::-webkit-scrollbar{display:none}
  .nav-btn{flex-shrink:0;padding:0 10px;font-size:.78rem}
  .theme-toggle-btn{width:34px;height:34px;margin:0 8px;font-size:.9rem}
  .page{padding:14px 12px}
  .page-head{flex-wrap:wrap;row-gap:8px}
  .page-head-title{font-size:1.1rem;padding-left:9px}
  .page-head-actions{margin-left:0;flex-wrap:wrap}
  .std-table{min-width:640px}
  .pitch-panel{padding:12px}
  .games-grid{grid-template-columns:repeat(auto-fill,minmax(240px,1fr))}
  .awards-grid{grid-template-columns:repeat(auto-fill,minmax(200px,1fr))}
  .diff-grid,.upcoming-grid{grid-template-columns:1fr!important}
  .trade-layout{grid-template-columns:1fr!important}
  .mt-tips-grid{grid-template-columns:1fr}
  .search-wrap{max-width:none}
  .pc-name{font-size:1.4rem}
  .podium{grid-template-columns:1fr!important}
  .chart-section{padding:12px}
  .chart-group-head{font-size:.82rem}
  .player-charts-grid{grid-template-columns:1fr}
}
@media(max-width:480px){
  .pitch-cards{grid-template-columns:repeat(auto-fill,minmax(84px,1fr))}
  .lb-stats-strip{grid-template-columns:1fr 1fr!important}
  .games-grid{grid-template-columns:1fr}
  .awards-grid{grid-template-columns:1fr}
}
</style>
</head>
<body>
<header>
  <div class="logo">
    <svg class="logo-mark" width="30" height="34" viewBox="0 0 30 34" xmlns="http://www.w3.org/2000/svg">
      <path d="M9 19 L4 32 L11 28.5 L15 33 L19 28.5 L26 32 L21 19" fill="var(--accent)" opacity=".5"/>
      <circle cx="15" cy="13" r="12" fill="url(#logoMedalGrad)"/>
      <circle cx="15" cy="13" r="8.6" fill="none" stroke="#0d0f1a" stroke-width="1" stroke-opacity=".3"/>
      <text x="15" y="18" text-anchor="middle" font-family="'Barlow Condensed',sans-serif" font-weight="800" font-size="13" fill="#0d0f1a">3</text>
      <defs><linearGradient id="logoMedalGrad" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#ffe08a"/><stop offset="1" stop-color="#e8a020"/>
      </linearGradient></defs>
    </svg>
    <div class="logo-text">
      <div class="logo-title">THE COUNT</div>
      <div class="logo-sub">Updated __LAST_UPDATED__</div>
    </div>
  </div>
  <nav>
    <button class="nav-btn active"  onclick="showPage('leaderboard',this)">&#127942; Leaderboard</button>
    <button class="nav-btn"         onclick="showPage('fixtures',this)">&#128197; Fixtures</button>
    <button class="nav-btn"         onclick="showPage('myteam',this)">&#127945; My Team</button>
    <button class="nav-btn"         onclick="showPage('difficulty',this)">&#128737; Matchups</button>
    <button class="nav-btn"         onclick="showPage('players',this)">&#128200; Players</button>
    <button class="nav-btn"         onclick="showPage('targets',this)">&#127919; Targets</button>
    <button class="nav-btn"         onclick="showPage('trading',this)">&#128176; Trades</button>
    <button class="nav-btn"         onclick="showPage('rolling22',this)">&#127942; Rolling 22</button>
    <button class="nav-btn"         onclick="showPage('awards',this)">&#127941; Awards</button>
    <div class="nav-indicator" id="navIndicator"></div>
  </nav>
  <button class="theme-toggle-btn" id="themeToggleBtn" onclick="toggleTheme()" title="Toggle light/dark mode">&#9728;&#65039;</button>
</header>
<main>

<!-- LEADERBOARD PAGE -->
<div class="page active" id="page-leaderboard">
  <div class="page-head">
    <div class="page-head-title">&#127942; Leaderboard</div>
    <button class="info-btn" id="infoBtn-leaderboard" onclick="toggleInfo('leaderboard')">&#9432; How it works</button>
    <div class="page-head-actions">
      <button class="race-btn" id="voteRaceToggleBtn" onclick="toggleVoteRace()">&#127885; Vote Race</button>
    </div>
  </div>
  <div class="info-panel" id="info-leaderboard">
    <div class="info-heading">&#127942; Leaderboard &amp; Brownlow Votes</div>
    <b>AFL Fantasy Brownlow</b> simulates the Brownlow Medal using Fantasy scores &mdash; the top 3 scorers in each game each round receive <b>3, 2 and 1 votes</b> respectively.<br><br>
    <b>Columns explained:</b>
    <ul>
      <li><b>Current Price</b> &mdash; the player&apos;s current AFL Fantasy price.</li>
      <li><b>Avg FP</b> &mdash; average Fantasy Points scored per round played.</li>
      <li><b>Total FP</b> &mdash; cumulative Fantasy Points across all rounds loaded.</li>
      <li><b>Votes</b> &mdash; total simulated Brownlow votes. Ties broken by Total FP.</li>
    </ul>
    Click any player name to jump to their full stats in the Player Stats tab.
  </div>
  <div id="lbPodium"></div>
  <div id="lbSection">
    <div class="table-scroll">
    <table class="std-table">
      <thead><tr>
        <th>Pos</th><th>Player</th><th>Club</th>
        <th class="ta-r">Current Price</th><th class="ta-r">Avg FP</th>
        <th class="ta-r">Total FP</th><th class="ta-r">Votes</th>
        <th>Form (L5)</th>
      </tr></thead>
      <tbody id="lbBody"></tbody>
    </table>
    </div>
  </div>
  <div id="raceSection" style="display:none">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px">
      <div style="font-weight:800;font-size:1.05rem;color:var(--text)">&#127885; Vote Race</div>
      <button class="info-btn" id="infoBtn-race" onclick="toggleInfo('race')">&#9432; How it works</button>
    </div>
    <div class="info-panel" id="info-race">
      <div class="info-heading">&#127885; Brownlow Vote Race</div>
      Shows the cumulative vote leaderboard building round by round.<br><br>
      <b>Controls:</b> Play/Pause animates automatically. Prev/Next step one round. Slider jumps directly.
    </div>
    <div class="race-controls">
      <button class="race-btn" id="playBtn" onclick="togglePlay()">&#9654; Play</button>
      <button class="race-btn" onclick="raceStep(-1)">&#9664; Prev</button>
      <button class="race-btn" onclick="raceStep(1)">Next &#9654;</button>
      <input type="range" class="race-slider" id="raceSlider" min="0" value="0" oninput="goToFrame(+this.value)">
      <span class="race-round-label" id="raceLabel"></span>
    </div>
    <div class="table-scroll">
    <table class="std-table" id="raceTable">
      <thead><tr>
        <th>Pos</th><th>Player</th><th>Club</th>
        <th class="ta-r">Move</th><th class="ta-r">Price</th>
        <th class="ta-r">Score</th><th class="ta-r">Round Votes</th><th class="ta-r">Total Votes</th>
      </tr></thead>
      <tbody id="raceBody"></tbody>
    </table>
    </div>
  </div>
</div>

<!-- FIXTURES PAGE (Round Scores + Fixtures combined) -->
<div class="page" id="page-fixtures">
  <div class="page-head">
    <div class="page-head-title">&#128197; Fixtures</div>
    <button class="info-btn" id="infoBtn-fixtures" onclick="toggleInfo('fixtures')">&#9432; How it works</button>
  </div>
  <div class="info-panel" id="info-fixtures">
    <div class="info-heading">&#128197; Fixtures</div>
    One timeline &mdash; pick any round, played or upcoming. Click a game to focus on it; click again to clear.<br><br>
    <b>Played rounds:</b> every player&apos;s result &mdash; score, price change, votes, and how far above/below their season average they landed.<br><br>
    <b>Upcoming rounds:</b> projected score, position matchup difficulty, and an estimated price change. Price change is a rough model (score vs breakeven &times; a fixed value per point) &mdash; treat it as a guide, not gospel.<br><br>
    Click any column heading to sort by that stat.
  </div>
  <div class="round-tabs" id="fixRoundTabs"></div>
  <div class="fixture-games-strip" id="fixGames"></div>
  <div id="fixPastSection">
    <div style="overflow-x:auto">
    <table class="std-table sortable-table" id="fixPastTable">
      <thead><tr>
        <th class="sortable" data-key="name" onclick="sortFixTable('past','name')">Player</th>
        <th class="sortable" data-key="team" onclick="sortFixTable('past','team')">Team</th>
        <th class="sortable" data-key="pos" onclick="sortFixTable('past','pos')">Pos</th>
        <th class="sortable" data-key="opponent" onclick="sortFixTable('past','opponent')">Opponent</th>
        <th class="sortable ta-r" data-key="score" onclick="sortFixTable('past','score')">Score</th>
        <th class="sortable ta-r" data-key="vsExpected" onclick="sortFixTable('past','vsExpected')">+/&minus; Expected</th>
        <th class="sortable ta-r" data-key="priceChange" onclick="sortFixTable('past','priceChange')">Price &Delta;</th>
        <th class="sortable ta-r" data-key="votes" onclick="sortFixTable('past','votes')">Votes</th>
        <th class="sortable ta-r" data-key="cba" onclick="sortFixTable('past','cba')">CBA%</th>
        <th class="sortable ta-r" data-key="disposals" onclick="sortFixTable('past','disposals')" title="Disposals (Kicks+Handballs), Marks and Tackles are literal AFL Fantasy scoring inputs (worth 2-3, 3 and 4 points respectively) — picked as the 3 real formula components most correlated with total score while staying non-redundant with each other">Disp.</th>
        <th class="sortable ta-r" data-key="marks" onclick="sortFixTable('past','marks')">Marks</th>
        <th class="sortable ta-r" data-key="tackles" onclick="sortFixTable('past','tackles')">Tackles</th>
      </tr></thead>
      <tbody id="fixPastBody"></tbody>
    </table>
    </div>
  </div>
  <div id="fixUpcomingSection" style="display:none">
    <div style="overflow-x:auto">
    <table class="std-table sortable-table" id="fixUpTable">
      <thead><tr>
        <th class="sortable" data-key="name" onclick="sortFixTable('up','name')">Player</th>
        <th class="sortable" data-key="team" onclick="sortFixTable('up','team')">Team</th>
        <th class="sortable" data-key="pos" onclick="sortFixTable('up','pos')">Pos</th>
        <th class="sortable" data-key="opponent" onclick="sortFixTable('up','opponent')">Opponent</th>
        <th class="sortable ta-r" data-key="difficulty" onclick="sortFixTable('up','difficulty')">Difficulty</th>
        <th class="sortable ta-r" data-key="projected" onclick="sortFixTable('up','projected')">Projected</th>
        <th class="sortable ta-r" data-key="price" onclick="sortFixTable('up','price')">Price</th>
        <th class="sortable ta-r" data-key="predPriceChange" onclick="sortFixTable('up','predPriceChange')">Pred. Price &Delta;</th>
        <th class="sortable ta-r" data-key="cba" onclick="sortFixTable('up','cba')">CBA% (Szn)</th>
      </tr></thead>
      <tbody id="fixUpBody"></tbody>
    </table>
    </div>
  </div>
</div>

<!-- PLAYER STATS PAGE -->
<div class="page" id="page-players">
  <div class="page-head">
    <div class="page-head-title">&#128200; Player Stats</div>
    <button class="info-btn" id="infoBtn-players" onclick="toggleInfo('players')">&#9432; How it works</button>
  </div>
  <div class="info-panel" id="info-players">
    <div class="info-heading">&#128200; Player Stats</div>
    Search any player to see their full Fantasy season. Chart shows score bars and price line.<br><br>
    Use the <b>bookmark icon</b> to save players to the Trading Centre watchlist.
  </div>
  <div class="search-wrap">
    <span class="search-icon">&#128269;</span>
    <input class="search-input" id="searchInput" placeholder="Search player&hellip;" autocomplete="off">
    <div class="search-results" id="searchResults"></div>
  </div>
  <div class="player-card" id="playerCard">
    <div class="pc-header">
      <div class="pc-avatar" id="pcAvatar"></div>
      <div>
        <div class="pc-name" id="pcName"></div>
        <div class="pc-sub" id="pcSub"></div>
        <div id="pcRank"></div>
        <div id="pcArchetypes" style="margin-top:6px"></div>
      </div>
      <button class="bookmark-btn" id="bookmarkBtn" onclick="toggleBookmark()" title="Bookmark player">
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path id="bookmarkPath" d="M5 3h14a1 1 0 011 1v17l-8-4-8 4V4a1 1 0 011-1z" stroke="#e8a020" stroke-width="2" stroke-linejoin="round" fill="none"/>
        </svg>
      </button>
    </div>
    <div class="stats-row" id="pcStats"></div>
    <!-- Player Report -->
    <div id="playerReportWrap" style="margin-bottom:14px;display:none">
      <button id="reportBtn" onclick="generatePlayerReport()" style="padding:8px 18px;border-radius:8px;border:1px solid var(--accent2);background:transparent;color:var(--accent2);font-weight:700;font-size:.9rem;cursor:pointer;margin-bottom:10px">&#128203; Generate Trade Report</button>
      <div id="playerReport" style="display:none;background:var(--surface);border:1px solid var(--accent2);border-radius:10px;padding:18px;font-size:.85rem;line-height:1.7;color:var(--text)"></div>
    </div>
    <div class="player-charts-grid">
      <div class="chart-col">
        <div class="chart-group-head">&#128202; Performance History</div>
        <div class="chart-section">
          <div class="chart-title">Score, Price &amp; CBA% History <span id="cbaCorrelation" class="cba-corr"></span></div>
          <canvas id="mainChart"></canvas>
        </div>
        <div class="chart-section" id="advStatsSection" style="display:none">
          <div class="chart-title">Latest Round Advanced Stats</div>
          <div class="adv-stats-grid" id="advStatsGrid"></div>
        </div>
        <div class="chart-section" id="valueSection" style="display:none">
          <div class="chart-title">Value vs Expectation (Score &minus; Price &divide; 10,490)</div>
          <canvas id="valueChart"></canvas>
        </div>
      </div>
      <div class="chart-col">
        <div class="chart-group-head chart-group-head-ahead" id="outlookGroupHead" style="display:none">&#128302; Outlook</div>
        <div class="chart-section chart-section-ahead" id="distSection" style="display:none">
          <div class="chart-title">Score Distribution (Ceiling / Floor)</div>
          <canvas id="distChart"></canvas>
        </div>
        <div class="chart-section chart-section-ahead" id="fixtureSection" style="display:none">
          <div class="chart-title">Upcoming Fixture Difficulty &amp; Projected Price</div>
          <div class="lb-stats-strip" id="fixtureSummary" style="margin-bottom:16px"></div>
          <canvas id="fixtureChart"></canvas>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- MATCHUP DIFFICULTY PAGE -->
<div class="page" id="page-difficulty">
  <div class="page-head">
    <div class="page-head-title">&#128737; Matchup Difficulty</div>
    <button class="info-btn" id="infoBtn-difficulty" onclick="toggleInfo('difficulty')">&#9432; How it works</button>
  </div>
  <div class="info-panel" id="info-difficulty">
    <div class="info-heading">&#128737; Matchup Difficulty Rating</div>
    <b>Historical tab:</b> How do players score vs their own average when facing each team? Rating 100 = league average. Above 100 = easier.<br><br>
    <b>Upcoming Fixture tab:</b> Predicted avg pts your players will score in each upcoming game, based on the opponent&apos;s historical concede rating. Weighted so closer games count more.
  </div>
  <div class="diff-tabs">
    <button class="diff-tab active" id="diffSubHistorical" onclick="showDiffSub('historical')">&#128202; Historical</button>
    <button class="diff-tab" id="diffSubUpcoming" onclick="showDiffSub('upcoming')">&#128197; Upcoming Fixture</button>
  </div>
  <div id="diffHistoricalSection">
    <div class="diff-legend">
      <span style="color:var(--green)">&#9679; Easiest to score against</span>
      <span style="color:var(--yellow)">&#9679; Average difficulty</span>
      <span style="color:var(--red)">&#9679; Hardest to score against</span>
    </div>
    <div id="diffCallout"></div>
    <div class="diff-tabs" id="diffTabs"></div>
    <div id="diffContent"></div>
  </div>
  <div id="diffUpcomingSection" style="display:none">
    <div class="diff-legend">
      <span style="color:var(--green)">&#9679; Easiest upcoming schedule</span>
      <span style="color:var(--yellow)">&#9679; Average schedule</span>
      <span style="color:var(--red)">&#9679; Toughest upcoming schedule</span>
    </div>
    <div id="upcomingCallout"></div>
    <div class="diff-tabs" id="upcomingPosTabs"></div>
    <div id="upcomingContent"></div>
  </div>
</div>

<!-- TRADING CENTRE PAGE -->
<div class="page" id="page-trading">
  <div class="page-head">
    <div class="page-head-title">&#128176; Trading Centre</div>
    <button class="info-btn" id="infoBtn-trading" onclick="toggleInfo('trading')">&#9432; How it works</button>
  </div>
  <div class="info-panel" id="info-trading">
    <div class="info-heading">&#128176; Trading Centre</div>
    Plan trades and compare the stats impact side by side.<br><br>
    <ul>
      <li>Enter your <b>available budget ($K)</b>, then search to add players to Trade In / Trade Out.</li>
      <li>Player chips show <b>position</b>, <b>avg FP</b>, <b>last 3 avg</b>, and <b>form rating</b> for quick comparison.</li>
      <li>The <b>Summary panel</b> shows how the trade changes your avg FP and budget position.</li>
      <li><b>Bookmarks:</b> star any player in Player Stats to quick-add them here.</li>
    </ul>
  </div>
  <div class="trade-budget">
    <div class="trade-budget-label">Available budget ($K)</div>
    <div class="trade-budget-row">
      <input class="trade-budget-input" id="budgetInput" type="number" placeholder="0" oninput="saveBudget();updateSummary()">
      <span style="color:var(--muted);font-size:.82rem">$K available</span>
    </div>
  </div>
  <div class="trade-layout">
    <div>
      <div class="trade-panel">
        <div class="trade-panel-title">&#11014; Trade In <span class="trade-limit-badge" id="tradeInBadge"></span></div>
        <ul class="trade-list" id="tradeInList"></ul>
        <div class="trade-error" id="tradeInError"></div>
        <div style="margin-top:9px">
          <div class="search-wrap" style="margin-bottom:0">
            <span class="search-icon">&#128269;</span>
            <input class="search-input" id="tradeInSearch" placeholder="Add player&hellip;" autocomplete="off">
            <div class="search-results" id="tradeInResults"></div>
          </div>
        </div>
      </div>
      <div class="trade-panel" style="margin-top:12px">
        <div class="trade-panel-title">&#11015; Trade Out <span class="trade-limit-badge" id="tradeOutBadge"></span></div>
        <ul class="trade-list" id="tradeOutList"></ul>
        <div class="trade-error" id="tradeOutError"></div>
        <div style="margin-top:9px">
          <div class="search-wrap" style="margin-bottom:0">
            <span class="search-icon">&#128269;</span>
            <input class="search-input" id="tradeOutSearch" placeholder="Add player&hellip;" autocomplete="off">
            <div class="search-results" id="tradeOutResults"></div>
          </div>
        </div>
      </div>
    </div>
    <div>
      <div class="trade-panel">
        <div class="trade-panel-title">&#128202; Trade Summary</div>
        <div class="trade-summary">
          <div class="trade-summary-row"><span>Trade In Cost</span><span id="sumIn">$0K</span></div>
          <div class="trade-summary-row"><span>Trade Out Value</span><span id="sumOut">$0K</span></div>
          <div class="trade-summary-row"><span>Available Budget</span><span id="sumBudget">$0K</span></div>
          <div class="trade-summary-row total"><span>Net Position</span><span id="sumNet">$0K</span></div>
        </div>
        <div class="trade-result" id="tradeResult" style="display:none"></div>
        <!-- Stats comparison strip -->
        <div id="statsCompareSection" style="display:none">
          <div style="font-size:.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin:12px 0 6px;font-weight:700">Stats Comparison</div>
          <div class="stats-compare-strip">
            <div class="scs-card">
              <div class="scs-label">&#11014; Trading In</div>
              <div class="scs-row"><span style="color:var(--muted)">Avg FP</span><span class="scs-val" id="sc-in-avg">—</span></div>
              <div class="scs-row"><span style="color:var(--muted)">L3 Avg</span><span class="scs-val" id="sc-in-l3">—</span></div>
              <div class="scs-row"><span style="color:var(--muted)">L5 Avg</span><span class="scs-val" id="sc-in-l5">—</span></div>
              <div class="scs-row"><span style="color:var(--muted)">Form</span><span class="scs-val" id="sc-in-fr">—</span></div>
              <div class="scs-row"><span style="color:var(--muted)">Consistency</span><span class="scs-val" id="sc-in-cons">—</span></div>
              <div class="scs-row"><span style="color:var(--muted)">Fixture</span><span class="scs-val" id="sc-in-fix">—</span></div>
              <div class="scs-row"><span style="color:var(--muted)">Price trend</span><span class="scs-val" id="sc-in-ptrend">—</span></div>
              <div class="scs-row"><span style="color:var(--muted)">Votes</span><span class="scs-val" id="sc-in-votes">—</span></div>
            </div>
            <div class="scs-card">
              <div class="scs-label">&#11015; Trading Out</div>
              <div class="scs-row"><span style="color:var(--muted)">Avg FP</span><span class="scs-val" id="sc-out-avg">—</span></div>
              <div class="scs-row"><span style="color:var(--muted)">L3 Avg</span><span class="scs-val" id="sc-out-l3">—</span></div>
              <div class="scs-row"><span style="color:var(--muted)">L5 Avg</span><span class="scs-val" id="sc-out-l5">—</span></div>
              <div class="scs-row"><span style="color:var(--muted)">Form</span><span class="scs-val" id="sc-out-fr">—</span></div>
              <div class="scs-row"><span style="color:var(--muted)">Consistency</span><span class="scs-val" id="sc-out-cons">—</span></div>
              <div class="scs-row"><span style="color:var(--muted)">Fixture</span><span class="scs-val" id="sc-out-fix">—</span></div>
              <div class="scs-row"><span style="color:var(--muted)">Price trend</span><span class="scs-val" id="sc-out-ptrend">—</span></div>
              <div class="scs-row"><span style="color:var(--muted)">Votes</span><span class="scs-val" id="sc-out-votes">—</span></div>
            </div>
          </div>
          <!-- Composite trade score -->
          <div id="tradeScoreBar" style="display:none;margin-top:10px;background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius-md);padding:12px">
            <div style="font-size:.62rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;font-weight:700">&#127919; Trade Quality Score</div>
            <div style="display:flex;align-items:center;gap:14px">
              <div class="score-ring" id="tradeScoreRing"><div class="score-ring-inner" id="tradeScoreLabel"></div></div>
              <div style="flex:1;min-width:0" id="tradeScoreBreakdown"></div>
            </div>
          </div>
          <div class="net-arrow neu" id="sc-net-label">Add players to both sides to compare</div>
        </div>
        <button class="open-scenarios-btn" onclick="openScenarioOverlay()">&#128260; Compare Trade Scenarios</button>
      </div>
      <div class="trade-panel" style="margin-top:12px">
        <div class="trade-panel-title">&#128278; Watchlist</div>
        <div id="starredList"></div>
        <div style="margin-top:5px;font-size:.75rem;color:var(--muted)">Bookmark players in Player Stats &#9733; to save here.</div>
      </div>
    </div>
  </div>
</div>

<!-- MY TEAM PAGE -->
<div class="page" id="page-myteam">
  <div class="page-head">
    <div class="page-head-title">&#127945; My Team</div>
    <button class="info-btn" id="infoBtn-myteam" onclick="toggleInfo('myteam')">&#9432; How it works</button>
    <div class="page-head-actions">
      <div class="myteam-budget-box" style="padding:6px 12px">
        <div class="myteam-budget-label">Budget ($K)</div>
        <input id="myteamBudget" type="number" placeholder="0" style="background:transparent;border:none;color:var(--text);font-weight:800;font-size:1rem;width:80px;outline:none" oninput="saveMyTeamBudget()">
      </div>
      <div class="myteam-budget-box" id="myteamTeamValue" style="display:none;padding:6px 12px">
        <div class="myteam-budget-label">Team value</div>
        <div class="myteam-budget-val" id="myteamValueNum">—</div>
      </div>
      <div class="myteam-budget-box" id="myteamTeamAvg" style="display:none;padding:6px 12px">
        <div class="myteam-budget-label">Team avg FP</div>
        <div class="myteam-budget-val" id="myteamAvgNum">—</div>
      </div>
      <button class="analyse-btn" onclick="analyseMyTeam()">&#128269; Analyse</button>
      <button class="analyse-btn" onclick="clearMyTeam()" style="background:transparent;border:1px solid var(--border);color:var(--muted)">Clear</button>
    </div>
  </div>
  <div class="info-panel" id="info-myteam">
    <div class="info-heading">&#127945; My Team Analyser</div>
    Add your 22-player squad. Players go into their position groups — DEF, MID, RUC, FWD — with the last 4 in each being bench (shaded). Add up to 30 players total.<br><br>
    Click <b>Analyse</b> for ranked upgrade suggestions with trade pairs, using form, fixture, value, consistency, and bench context. Each card shows signal, avg FP, price trend, fixture, and best available replacement.
  </div>
  <!-- Search -->
  <div style="position:relative;max-width:400px;margin-bottom:14px">
    <span class="search-icon">&#128269;</span>
    <input class="search-input" id="myteamSearch" placeholder="Search to add player to squad&hellip;" autocomplete="off">
    <div class="search-results" id="myteamResults"></div>
  </div>
  <!-- Report card -->
  <div id="mtReportCard"></div>
  <!-- Team grid by position -->
  <div id="myteamFieldGrid"></div>
  <!-- Analysis -->
  <div id="myteamAnalysis" style="margin-top:18px;display:none">
    <div style="font-weight:800;font-size:1rem;margin-bottom:10px;color:var(--text)">&#127919; Upgrade Recommendations — ranked by impact</div>
    <div id="myteamAnalysisBody"></div>
  </div>
</div>

<!-- ROLLING 22 PAGE -->
<div class="page" id="page-rolling22">
  <div class="page-head">
    <div class="page-head-title">&#127942; Rolling 22 &mdash; Best Projected Team</div>
    <button class="info-btn" id="infoBtn-rolling22" onclick="toggleInfo('rolling22')">&#9432; How it works</button>
  </div>
  <div class="info-panel" id="info-rolling22">
    <div class="info-heading">&#127942; Rolling 22</div>
    Shows the best projected 22-man AFL Fantasy team from your loaded data, laid out in DEF/MID/RUC/FWD formation, ranked by the same projected average used everywhere else in the app (recent form + fixture difficulty for the rest of the season).<br><br>
    DPP players are placed into whichever eligible position is scarcest rather than always their first-listed position. Bench spots show the next-best available.
  </div>
  <div id="rolling22Grid" class="pitch-panel"></div>
</div>

<!-- SEASON AWARDS PAGE -->
<div class="page" id="page-awards">
  <div class="page-head">
    <div class="page-head-title">&#127941; Season Awards</div>
    <button class="info-btn" id="infoBtn-awards" onclick="toggleInfo('awards')">&#9432; How it works</button>
  </div>
  <div class="info-panel" id="info-awards">
    <div class="info-heading">&#127941; Season Awards</div>
    A quick season-long records board, pulled from every round loaded so far. "Best value" and "Best bargain" both use price &mdash; value is against today&apos;s price, bargain is against the price they started the season at.
  </div>
  <div class="awards-grid" id="awardsGrid"></div>
</div>

<!-- TARGETS PAGE -->
<div class="page" id="page-targets">
  <div class="page-head">
    <div class="page-head-title">&#127919; Targets</div>
    <button class="info-btn" id="infoBtn-targets" onclick="toggleInfo('targets')">&#9432; How it works</button>
  </div>
  <div class="info-panel" id="info-targets">
    <div class="info-heading">&#127919; Targets</div>
    Every eligible player, grouped by price tier and ranked by what actually matters for that tier &mdash; best target at the top of each column.<br><br>
    <b>Premiums ($800K+):</b> pure scoring output &mdash; projected average for the rest of the season, fixture-adjusted across every remaining game.<br><br>
    <b>Mid Price ($350K&ndash;$800K):</b> a blend of season average and near-term matchup ease, weighted heavily toward the next few games &mdash; these are short-term trade targets.<br><br>
    <b>Rookies (under $350K):</b> projected cumulative price growth for the rest of the season &mdash; best cash-generation targets.<br><br>
    Every priced player with at least one game falls into one of the three columns; injured/suspended players are left out since they're not real trade targets right now.<br><br>
    <b>Find Players</b> ignores the tier boundaries &mdash; set any price range, position, or team and it ranks everyone who matches by projected average for the rest of the season.
  </div>

  <button class="tf-dropdown-toggle" id="tfDropdownBtn" onclick="toggleTargetFilters()">&#128269; Find Players <span id="tfDropdownArrow">&#9662;</span></button>
  <div class="targets-filter-wrap" id="tfDropdownPanel">
    <div class="targets-filter-bar">
      <div class="tf-field"><label>Min Price</label><input type="number" id="tfMinPrice" placeholder="$0" step="10000" onkeydown="if(event.key==='Enter')renderFilteredTargets()"></div>
      <div class="tf-field"><label>Max Price</label><input type="number" id="tfMaxPrice" placeholder="No limit" step="10000" onkeydown="if(event.key==='Enter')renderFilteredTargets()"></div>
      <div class="tf-field"><label>Position</label><select id="tfPosition">
        <option value="">All</option><option value="DEF">DEF</option><option value="MID">MID</option><option value="RUC">RUC</option><option value="FWD">FWD</option>
      </select></div>
      <div class="tf-field"><label>Team</label><select id="tfTeam"><option value="">All</option></select></div>
      <button class="race-btn" onclick="renderFilteredTargets()">&#128269; Find Players</button>
      <button class="race-btn" onclick="resetTargetFilters()">Reset</button>
      <div class="tf-count" id="tfCount"></div>
    </div>
    <div class="table-scroll">
    <table class="std-table sortable-table" id="targetsFilteredTable">
      <thead><tr>
        <th>Rank</th>
        <th class="sortable" data-key="name" onclick="sortFilteredTargets('name')">Player</th>
        <th class="sortable" data-key="team" onclick="sortFilteredTargets('team')">Team</th>
        <th class="sortable" data-key="pos" onclick="sortFilteredTargets('pos')">Pos</th>
        <th class="sortable ta-r" data-key="price" onclick="sortFilteredTargets('price')">Price</th>
        <th class="sortable ta-r" data-key="metric" onclick="sortFilteredTargets('metric')">Proj Avg</th>
        <th class="sortable ta-r" data-key="seasonAvg" onclick="sortFilteredTargets('seasonAvg')">Season Avg</th>
        <th class="sortable ta-r" data-key="l3" onclick="sortFilteredTargets('l3')">L3 Avg</th>
        <th class="sortable" data-key="nextRating" onclick="sortFilteredTargets('nextRating')">Next Game</th>
        <th class="sortable ta-r" data-key="be" onclick="sortFilteredTargets('be')">BE</th>
        <th class="sortable ta-r" data-key="projDelta" onclick="sortFilteredTargets('projDelta')">Proj &Delta;</th>
      </tr></thead>
      <tbody id="targetsFilteredBody"></tbody>
    </table>
    </div>
  </div>

  <div class="targets-columns">
    <div class="targets-col">
      <div class="targets-col-head tier-premiums"><span>&#128142; Premiums</span><span class="targets-col-sub">$800K+</span></div>
      <div class="targets-col-list" id="targetsList-premiums"></div>
    </div>
    <div class="targets-col">
      <div class="targets-col-head tier-midprice"><span>&#9878;&#65039; Mid Price</span><span class="targets-col-sub">$350K&ndash;$800K</span></div>
      <div class="targets-col-list" id="targetsList-midprice"></div>
    </div>
    <div class="targets-col">
      <div class="targets-col-head tier-rookies"><span>&#127793; Rookies</span><span class="targets-col-sub">Under $350K</span></div>
      <div class="targets-col-list" id="targetsList-rookies"></div>
    </div>
  </div>
</div>

</main>

<!-- SCENARIO OVERLAY -->
<div class="scenario-overlay" id="scenarioOverlay">
  <div class="scenario-overlay-header">
    <span class="scenario-overlay-title">&#128260; Trade Scenario Comparison</span>
    <button class="add-scenario-btn" id="addScenarioBtn" onclick="addScenario()">+ Add Scenario</button>
    <button class="overlay-close-btn" onclick="closeScenarioOverlay()">&#10005; Close</button>
  </div>
  <div class="scenario-overlay-body">
    <div class="scenarios-compare-grid" id="scenariosGrid"></div>
  </div>
</div>

<script>
(function() {
  var saved = null;
  try { saved = localStorage.getItem('afl_theme'); } catch(e) {}
  var theme = saved === 'light' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', theme);
  var btn = document.getElementById('themeToggleBtn');
  if (btn) btn.textContent = theme === 'light' ? '\u{1F319}' : '\u{2600}\u{FE0F}';
})();
function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function chartGridColor() { return 'rgba(' + cssVar('--overlay-rgb') + ',.06)'; }
function toggleTheme() {
  var next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', next);
  try { localStorage.setItem('afl_theme', next); } catch(e) {}
  var btn = document.getElementById('themeToggleBtn');
  if (btn) btn.textContent = next === 'light' ? '\u{1F319}' : '\u{2600}\u{FE0F}';
  if (currentPlayerKey && typeof showPlayer === 'function') showPlayer(currentPlayerKey);
}
const LEADERBOARD      = __LEADERBOARD__;
const ROUNDS_DATA      = __ROUNDS_DATA__;
const PLAYERS_DATA     = __PLAYERS_DATA__;
const ARCHETYPE_TEAM_NOTES = __ARCHETYPE_TEAM_NOTES__;
const ROUNDS_LOADED    = __ROUNDS_LOADED__;
const OVERALL_DIFF     = __OVERALL_DIFF__;
const POS_DIFF         = __POS_DIFF__;
const AFL_AVG          = __AFL_AVG__;
const LB_HISTORY       = __LB_HISTORY__;
const UPCOMING_DIFF    = __UPCOMING_DIFF__;
const UPCOMING_AFL_AVG = __UPCOMING_AFL_AVG__;
const UPCOMING_AFL_AVG_POS = __UPCOMING_AFL_AVG_POS__;
const CURRENT_ROUND    = __CURRENT_ROUND__;
const INJURED_SET      = new Set(__INJURED_SET__);
const SUSPENDED_SET    = new Set(__SUSPENDED_SET__);
// Empirically-fit breakeven model coefficients — see breakeven()/weighted3() below for
// how they were derived. Declared this early (not next to those functions) because
// renderTargets() runs during initial page load and reaches this via
// restOfSeasonPriceChange() -> breakeven(); a `const` referenced before its own
// declaration line throws (temporal dead zone), even though function declarations
// don't have that problem.
const BE_COEF_PRICE = 2.51, BE_COEF_FORM = -1.32, BE_COEF_INTERCEPT = 2.58;

let mainChartInst = null, valueChartInst = null, fixtureChartInst = null, distChartInst = null, currentPlayerKey = null;
let raceFrame = 0, raceTimer = null;
let currentArchetypeHits = [], openArchetypeDetailIdx = -1;

function hexToRgba(hex, alpha) {
  const h = hex.replace('#','');
  const r = parseInt(h.substring(0,2),16), g = parseInt(h.substring(2,4),16), b = parseInt(h.substring(4,6),16);
  return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
}

// Click-to-toggle archetype detail — a native `title` tooltip was tried first and
// dropped: it's unreliable (delayed/invisible depending on hover timing, doesn't
// work on touch at all), so a badge click instead shows/hides that tag's own
// rationale in a fixed on-page panel. Clicking the same badge again closes it.
function toggleArchetypeDetail(i) {
  const el = document.getElementById('pcArchetypeDetail');
  if (!el) return;
  if (openArchetypeDetailIdx === i) {
    openArchetypeDetailIdx = -1;
    el.style.display = 'none';
    el.innerHTML = '';
    return;
  }
  const a = currentArchetypeHits[i];
  if (!a) return;
  openArchetypeDetailIdx = i;
  el.style.display = '';
  var html = '<span class="archetype-detail-label" style="color:' + a.color + '">' + a.label + '</span> — ' + a.rationale;
  const teamNotes = ARCHETYPE_TEAM_NOTES[a.key];
  if (teamNotes && teamNotes.length) {
    html += '<div class="archetype-team-notes">' + teamNotes.map(function(n){
      const verb = n.direction === 'weak' ? 'give up extra points to' : 'defend unusually well against';
      return '<div>' + teamTagHtml(n.team) + ' tend to ' + verb + ' ' + a.label.toLowerCase() + ' players (' +
        (n.specialization >= 0 ? '+' : '') + n.specialization + ' pts vs their own defensive baseline, across ' + n.n_players + ' players this season).</div>';
    }).join('') + '</div>';
  }
  el.innerHTML = html;
}

const duplicateNames = new Set(
  PLAYERS_DATA.filter((p,_,arr) => arr.filter(x => x.name === p.name).length > 1).map(p => p.name)
);
const TEAM_COLORS = {
  Swans:'#E4003A', Hawks:'#C99B3F', Blues:'#2541B2', Cats:'#4A90D9', Lions:'#9D2235',
  Magpies:'#E8EAF0', Bombers:'#CC2028', Dockers:'#8E44AD', Suns:'#FF6B35', Giants:'#FF7F11',
  Demons:'#B71C3C', Kangaroos:'#1E5AA8', Power:'#00A9A5', Tigers:'#FFD200', Saints:'#E4312B',
  Eagles:'#F5B301', Bulldogs:'#C41230', Crows:'#D4AF37'
};
function teamColor(team) { return TEAM_COLORS[team] || 'var(--muted)'; }
function teamTagHtml(team) { return '<span class="team-tag" style="border-left:3px solid ' + teamColor(team) + '">' + team + '</span>'; }

const POS_ORDER = ['DEF','MID','RUC','FWD'];
// DEF/MID/RUC/FWD, always in that order regardless of how the source data listed them.
function posOrdered(positions) {
  if (!positions || !positions.length) return '';
  return POS_ORDER.filter(function(p){ return positions.includes(p); }).join('/');
}
// DPP players get one colored chip per position (in DEF/MID/RUC/FWD order) instead of
// a single "MID/FWD" chip stuck in just one position's color.
function posChipsHtml(positions) {
  if (!positions || !positions.length) return '<span class="pos-chip" style="opacity:.5">&mdash;</span>';
  return POS_ORDER.filter(function(p){ return positions.includes(p); })
    .map(function(p){ return '<span class="pos-chip pos-' + p.toLowerCase() + '">' + p + '</span>'; })
    .join(' ');
}

// Suspended is a subset of "unavailable" (INJURED_SET) — check it first so the label
// reads SUS instead of the more general INJ when that's what's actually going on.
function statusLabel(name) {
  if (SUSPENDED_SET && SUSPENDED_SET.has(name)) return 'SUS';
  if (INJURED_SET && INJURED_SET.has(name)) return 'INJ';
  return null;
}

function getDisplayName(name, team) {
  return duplicateNames.has(name) ? name + ' (' + team + ')' : name;
}
function findByKey(key) { return PLAYERS_DATA.find(p => p.key === key); }
function findByNameTeam(name, team) { return PLAYERS_DATA.find(p => p.name === name && p.team === team); }

function fmtPrice(p) {
  if (p == null) return '\u2014';
  const k = Math.round(p / 1000);
  if (k >= 1000) return '$' + (p/1000000).toFixed(3) + 'M';
  return '$' + k + 'K';
}
function fmtBudgetK(k) {
  if (!k && k !== 0) return '\u2014';
  if (k >= 1000) return '$' + (k/1000).toFixed(2) + 'M';
  return '$' + Math.round(k) + 'K';
}
function ratingColor(r) {
  if (r == null) return 'var(--muted)';
  return r >= 70 ? 'var(--green)' : r >= 40 ? 'var(--accent)' : 'var(--red)';
}
function posPillClass(pos) {
  if (pos==='DEF') return 'pos-def';
  if (pos==='MID') return 'pos-mid';
  if (pos==='RUC') return 'pos-ruc';
  if (pos==='FWD') return 'pos-fwd';
  return '';
}
function posPills(positions) {
  if (!positions || !positions.length) return '';
  return positions.map(p => '<span class="pos-chip ' + posPillClass(p) + '">' + p + '</span>').join('');
}

function moveNavIndicator(btn) {
  var ind = document.getElementById('navIndicator');
  if (!ind || !btn) return;
  ind.style.width     = btn.offsetWidth + 'px';
  ind.style.transform = 'translateX(' + btn.offsetLeft + 'px)';
}
function showPage(id, btn) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  var pageEl = document.getElementById('page-' + id);
  if (!pageEl) return;
  pageEl.classList.add('active');
  if (btn) { btn.classList.add('active'); moveNavIndicator(btn); }
  if (id === 'trading') renderTradeLists();
  if (id === 'myteam') renderMyTeam();
  if (id === 'rolling22') renderRolling22();
}
moveNavIndicator(document.querySelector('.nav-btn.active'));
window.addEventListener('resize', function() { moveNavIndicator(document.querySelector('.nav-btn.active')); });

var voteRaceVisible = false;
function toggleInfo(pageId) {
  var panel = document.getElementById('info-' + pageId);
  var btn   = document.getElementById('infoBtn-' + pageId);
  if (!panel) return;
  var open = panel.classList.toggle('open');
  if (btn) btn.classList.toggle('open', open);
}
function toggleVoteRace() {
  voteRaceVisible = !voteRaceVisible;
  const lb = document.getElementById('lbSection');
  const race = document.getElementById('raceSection');
  const btn = document.getElementById('voteRaceToggleBtn');
  if (voteRaceVisible) {
    lb.style.display = 'none'; race.style.display = 'block';
    btn.textContent = '\u25C0 Back to Leaderboard'; btn.classList.add('playing');
    initRace();
  } else {
    lb.style.display = 'block'; race.style.display = 'none';
    btn.textContent = '\u{1F3C5} Vote Race'; btn.classList.remove('playing');
    if (raceTimer) { clearInterval(raceTimer); raceTimer = null; }
  }
}

// Rounds loaded: available via ROUNDS_LOADED array if needed

// ── Leaderboard ───────────────────────────────────────────────────────────────
(function() {
  const podium = document.getElementById('lbPodium');
  if (podium && LEADERBOARD.length >= 3) {
    const order = [1, 0, 2];
    const medal = ['\u{1f947}', '\u{1f948}', '\u{1f949}'];
    let html = '<div class="podium">';
    order.forEach(function(idx) {
      const e = LEADERBOARD[idx];
      const dn = e.display_name || getDisplayName(e.player, e.team);
      const safeKey = e.key.replace(/'/g, "\\'");
      html += '<div class="podium-card rank-' + (idx + 1) + '" style="animation-delay:' + (idx * 0.06) + 's">' +
        '<div class="podium-rankno">' + (idx + 1) + '</div>' +
        '<div class="podium-medal">' + medal[idx] + '</div>' +
        '<div class="podium-avatar">' + dn.charAt(0).toUpperCase() + '</div>' +
        '<div class="podium-name" onclick="searchAndShowPlayer(\'' + safeKey + '\')">' + dn + '</div>' +
        '<div class="podium-team">' + teamTagHtml(e.team) + '</div>' +
        '<div class="podium-votes">' + e.votes + '<span>votes</span></div>' +
        '<div class="podium-sub">Avg ' + e.avg + ' &middot; ' + fmtPrice(e.price) + '</div>' +
      '</div>';
    });
    html += '</div>';
    const margin = LEADERBOARD[0].votes - LEADERBOARD[1].votes;
    const totalVotes = LEADERBOARD.reduce(function(s, e) { return s + e.votes; }, 0);
    html += '<div class="lb-stats-strip">' +
      '<div class="lbs-item"><div class="lbs-val">' + CURRENT_ROUND + '</div><div class="lbs-lbl">Current Round</div></div>' +
      '<div class="lbs-item"><div class="lbs-val">' + ROUNDS_LOADED.length + '</div><div class="lbs-lbl">Rounds Tracked</div></div>' +
      '<div class="lbs-item"><div class="lbs-val">' + totalVotes + '</div><div class="lbs-lbl">Total Votes Cast</div></div>' +
      '<div class="lbs-item"><div class="lbs-val" style="color:' + (margin <= 2 ? 'var(--red)' : 'var(--text)') + '">' + (margin === 0 ? 'TIED' : '+' + margin) + '</div><div class="lbs-lbl">Vote Margin</div></div>' +
    '</div>';
    podium.innerHTML = html;
  }

  const tbody = document.getElementById('lbBody');
  let pos = 1, prevVotes = null;
  LEADERBOARD.forEach((e, i) => {
    if (e.votes !== prevVotes) pos = i + 1;
    prevVotes = e.votes;
    const pc = pos===1?'p1':pos===2?'p2':pos===3?'p3':'';
    const dn = e.display_name || getDisplayName(e.player, e.team);
    const safeKey = e.key.replace(/'/g,"\\'");
    // Form boxes: last 5 rounds' votes — click one to jump to that game in Fixtures
    var formHtml = '<div class="form-boxes">';
    (e.form_history || []).forEach(function(f) {
      const lbl = f.r === 0 ? 'Op' : 'R' + f.r;
      const oc = 'onclick="goToFixtureGame(\'' + safeKey + '\',' + f.r + ')"';
      if (f.v === 0) formHtml += '<div class="form-box form-box-0" ' + oc + ' title="' + lbl + ': no votes — click to view this game">&nbsp;</div>';
      else formHtml += '<div class="form-box form-box-' + f.v + '" ' + oc + ' title="' + lbl + ': ' + f.v + ' vote' + (f.v>1?'s':'') + ' — click to view this game">' + f.v + '</div>';
    });
    formHtml += '</div>';
    const tr = document.createElement('tr');
    tr.innerHTML =
      '<td class="pos-num ' + pc + '">' + pos + '</td>' +
      '<td><span class="player-link" onclick="searchAndShowPlayer(\'' + safeKey + '\')">' + dn + '</span>' + (e.is_suspended ? ' <span class="inj-tag sus-tag" title="Suspended">SUS</span>' : e.is_injured ? ' <span class="inj-tag" title="Injured">INJ</span>' : '') + '</td>' +
      '<td>' + teamTagHtml(e.team) + '</td>' +
      '<td class="ta-r" style="color:#fff;font-family:\'Barlow Condensed\',sans-serif">' + fmtPrice(e.price) + '</td>' +
      '<td class="ta-r" style="font-family:\'Barlow Condensed\',sans-serif;font-weight:700">' + e.avg + '</td>' +
      '<td class="ta-r" style="color:var(--muted);font-family:\'Barlow Condensed\',sans-serif">' + e.total_dt + '</td>' +
      '<td class="ta-r votes-hl">' + e.votes + '</td>' +
      '<td>' + formHtml + '</td>';
    tbody.appendChild(tr);
  });
})();

// ── Fixtures — one continuous round timeline, played + upcoming ───────────────
(function() {
  var pastSort = {key:'score', dir:-1};
  var upSort   = {key:'projected', dir:-1};
  var pastRowsAll = [], upRowsAll = [];
  var pastSelectedGame = null, upSelectedGame = null; // {team_a,team_b} or null
  var currentRound = null, currentIsPast = true;

  function gameCardHtml(teamA, teamB, teaser, selected) {
    const colA = teamColor(teamA), colB = teamColor(teamB);
    return '<div class="fx-game-card' + (selected ? ' active' : '') + '" ' +
        'onclick="toggleFixGame(this,\'' + teamA.replace(/'/g,"\\'") + '\',\'' + teamB.replace(/'/g,"\\'") + '\')" ' +
        'style="background:linear-gradient(135deg,' + colA + '40 0%,' + colA + '12 38%,var(--surface) 50%,' + colB + '12 62%,' + colB + '40 100%);border-color:' + (selected ? 'var(--accent)' : 'var(--border)') + '">' +
      '<div class="fx-game-teams"><span style="color:' + colA + '">' + teamA + '</span><span class="fx-game-vs">vs</span><span style="color:' + colB + '">' + teamB + '</span></div>' +
      (teaser || '<div class="fx-game-teaser fx-game-teaser-muted">Click to focus this game</div>') +
    '</div>';
  }

  function voteGettersHtml(votes) {
    if (!votes || !votes.length) return '';
    return '<div class="fx-game-votes">' + votes.map(function(v) {
      return '<div class="fx-game-vote-row"><span class="vote-badge v' + v.votes + '" style="width:auto;padding:0 5px;border-radius:3px;font-size:.6rem">' + v.votes + '</span>' +
        '<span class="fx-game-vote-name">' + getDisplayName(v.player, v.team) + '</span>' +
        '<span class="fx-game-vote-score">' + v.score + '</span></div>';
    }).join('') + '</div>';
  }

  function renderGames(round, isPast) {
    const wrap = document.getElementById('fixGames');
    if (isPast) {
      const rd = ROUNDS_DATA.find(function(r){ return r.round === round; });
      wrap.innerHTML = !rd ? '' : rd.games.map(function(game) {
        const teaser = voteGettersHtml(game.votes);
        const sel = pastSelectedGame && pastSelectedGame.team_a === game.team_a && pastSelectedGame.team_b === game.team_b;
        return gameCardHtml(game.team_a, game.team_b, teaser, sel);
      }).join('');
    } else {
      const games = upcomingGamesForRound(round);
      wrap.innerHTML = games.map(function(game) {
        const sel = upSelectedGame && upSelectedGame.team_a === game.team_a && upSelectedGame.team_b === game.team_b;
        return gameCardHtml(game.team_a, game.team_b, '', sel);
      }).join('');
    }
  }

  function upcomingGamesForRound(round) {
    const seen = {}, games = [];
    (UPCOMING_DIFF||[]).forEach(function(d) {
      (d.games||[]).forEach(function(g) {
        if (g.round !== round) return;
        const pair = [d.team, g.opponent].sort();
        const key = pair.join('|');
        if (seen[key]) return;
        seen[key] = true;
        games.push({team_a: pair[0], team_b: pair[1]});
      });
    });
    return games;
  }

  window.toggleFixGame = function(el, teamA, teamB) {
    if (currentIsPast) {
      const cur = pastSelectedGame;
      const same = cur && cur.team_a === teamA && cur.team_b === teamB;
      pastSelectedGame = same ? null : {team_a: teamA, team_b: teamB};
      renderGames(currentRound, true);
      renderPastTable();
    } else {
      const cur = upSelectedGame;
      const same = cur && cur.team_a === teamA && cur.team_b === teamB;
      upSelectedGame = same ? null : {team_a: teamA, team_b: teamB};
      renderGames(currentRound, false);
      renderUpTable();
    }
  };

  function buildPastRows(round) {
    const rows = [];
    PLAYERS_DATA.forEach(function(p) {
      if (!p.history || !p.history.length) return;
      const seasonAvg = p.history.reduce(function(s,h){return s+h.score;},0) / p.history.length;
      p.history.forEach(function(h) {
        if (h.round !== round) return;
        const priceChange = (h.post_price != null && h.pre_price != null) ? h.post_price - h.pre_price : null;
        rows.push({
          key: p.key,
          name: p.display_name || getDisplayName(p.name, p.team),
          team: p.team,
          pos: (p.positions && p.positions[0]) || '—',
          positions: p.positions,
          opponent: h.opponent || '—',
          score: h.score,
          vsExpected: +(h.score - seasonAvg).toFixed(1),
          priceChange: priceChange,
          votes: h.votes || 0,
          cba: p.cba_history ? p.cba_history[h.round] : null,
          disposals: (p.advanced_history && p.advanced_history[h.round]) ? p.advanced_history[h.round].Disposals : null,
          marks: (p.advanced_history && p.advanced_history[h.round]) ? p.advanced_history[h.round].Marks : null,
          tackles: (p.advanced_history && p.advanced_history[h.round]) ? p.advanced_history[h.round].Tackles : null
        });
      });
    });
    return rows;
  }

  function buildUpRows(round) {
    const rows = [];
    PLAYERS_DATA.forEach(function(p) {
      if (INJURED_SET && INJURED_SET.has(p.name)) return; // injured players sit out future fixtures entirely
      const teamFix = (UPCOMING_DIFF||[]).find(function(d){ return d.team === p.team; });
      if (!teamFix || !teamFix.games) return;
      const game = teamFix.games.find(function(g){ return g.round === round; });
      if (!game) return;
      const pos = p.positions && p.positions.length ? p.positions[0] : null;
      const diffRating = (pos && game.pos && game.pos[pos] != null) ? game.pos[pos] : game.overall;
      const posPred = (pos && game.predicted_pos && game.predicted_pos[pos] != null) ? game.predicted_pos[pos] : game.predicted_avg;
      const projected = calcProjectedScore(p.key) || posPred;
      const price = p.current_price;
      const predPriceChange = predictedPriceChange(p, priceProjectedScore(p.key));
      rows.push({
        key: p.key,
        name: p.display_name || getDisplayName(p.name, p.team),
        team: p.team,
        pos: pos || '—',
        positions: p.positions,
        opponent: game.opponent,
        difficulty: diffRating,
        projected: projected,
        price: price,
        predPriceChange: predPriceChange,
        cba: p.cba_avg != null ? p.cba_avg : null
      });
    });
    return rows;
  }

  function sortRows(rows, key, dir) {
    return rows.slice().sort(function(a, b) {
      var av = a[key], bv = b[key];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === 'string') return dir * av.localeCompare(bv);
      return dir * (av - bv);
    });
  }

  function updateSortIndicators(tableId, key, dir) {
    const table = document.getElementById(tableId);
    if (!table) return;
    table.querySelectorAll('th.sortable').forEach(function(th) {
      th.classList.remove('sort-asc', 'sort-desc');
      if (th.dataset.key === key) th.classList.add(dir > 0 ? 'sort-asc' : 'sort-desc');
    });
  }

  function renderPastTable() {
    var rows = pastRowsAll;
    if (pastSelectedGame) rows = rows.filter(function(r){ return r.team === pastSelectedGame.team_a || r.team === pastSelectedGame.team_b; });
    rows = sortRows(rows, pastSort.key, pastSort.dir);
    document.getElementById('fixPastBody').innerHTML = rows.map(function(r) {
      const pcCol = r.priceChange == null ? 'var(--muted)' : r.priceChange >= 0 ? 'var(--green)' : 'var(--red)';
      const pcStr = r.priceChange == null ? '—' : (r.priceChange>=0?'+':'-') + fmtPrice(Math.abs(r.priceChange));
      const veCol = r.vsExpected >= 0 ? 'var(--green)' : 'var(--red)';
      const voteBadge = r.votes > 0 ? '<span class="vote-badge v' + r.votes + '" style="width:auto;padding:1px 7px;border-radius:3px;font-size:.68rem">' + r.votes + '</span>' : '<span style="color:var(--muted)">—</span>';
      return '<tr>' +
        '<td><span class="player-link" onclick="searchAndShowPlayer(\'' + r.key.replace(/'/g,"\\'") + '\')">' + r.name + '</span></td>' +
        '<td>' + teamTagHtml(r.team) + '</td>' +
        '<td>' + posChipsHtml(r.positions) + '</td>' +
        '<td>' + r.opponent + '</td>' +
        '<td class="ta-r votes-hl">' + r.score + '</td>' +
        '<td class="ta-r" style="color:' + veCol + '">' + (r.vsExpected>=0?'+':'') + r.vsExpected + '</td>' +
        '<td class="ta-r" style="color:' + pcCol + '">' + pcStr + '</td>' +
        '<td class="ta-r">' + voteBadge + '</td>' +
        '<td class="ta-r">' + (r.cba != null ? r.cba + '%' : '—') + '</td>' +
        '<td class="ta-r">' + (r.disposals != null ? r.disposals : '—') + '</td>' +
        '<td class="ta-r">' + (r.marks != null ? r.marks : '—') + '</td>' +
        '<td class="ta-r">' + (r.tackles != null ? r.tackles : '—') + '</td>' +
      '</tr>';
    }).join('') || '<tr><td colspan="12" style="color:var(--muted);padding:16px;text-align:center">No data for this round.</td></tr>';
    updateSortIndicators('fixPastTable', pastSort.key, pastSort.dir);
  }

  function renderUpTable() {
    var rows = upRowsAll;
    if (upSelectedGame) rows = rows.filter(function(r){ return r.team === upSelectedGame.team_a || r.team === upSelectedGame.team_b; });
    rows = sortRows(rows, upSort.key, upSort.dir);
    document.getElementById('fixUpBody').innerHTML = rows.map(function(r) {
      const dCol = gradientText(r.difficulty);
      const pcCol = r.predPriceChange == null ? 'var(--muted)' : r.predPriceChange >= 0 ? 'var(--green)' : 'var(--red)';
      const pcStr = r.predPriceChange == null ? '—' : (r.predPriceChange>=0?'+':'-') + fmtPrice(Math.abs(r.predPriceChange));
      return '<tr>' +
        '<td><span class="player-link" onclick="searchAndShowPlayer(\'' + r.key.replace(/'/g,"\\'") + '\')">' + r.name + '</span></td>' +
        '<td>' + teamTagHtml(r.team) + '</td>' +
        '<td>' + posChipsHtml(r.positions) + '</td>' +
        '<td>' + r.opponent + '</td>' +
        '<td class="ta-r" style="color:' + dCol + ';font-weight:700">' + r.difficulty.toFixed(1) + '</td>' +
        '<td class="ta-r votes-hl">' + (r.projected!=null?r.projected.toFixed(0):'—') + '</td>' +
        '<td class="ta-r">' + fmtPrice(r.price) + '</td>' +
        '<td class="ta-r" style="color:' + pcCol + '">' + pcStr + '</td>' +
        '<td class="ta-r">' + (r.cba != null ? r.cba + '%' : '—') + '</td>' +
      '</tr>';
    }).join('') || '<tr><td colspan="9" style="color:var(--muted);padding:16px;text-align:center">No upcoming data for this round.</td></tr>';
    updateSortIndicators('fixUpTable', upSort.key, upSort.dir);
  }

  function loadRound(round, isPast, btn) {
    currentRound = round;
    currentIsPast = isPast;
    document.getElementById('fixPastSection').style.display     = isPast ? 'block' : 'none';
    document.getElementById('fixUpcomingSection').style.display = isPast ? 'none' : 'block';
    document.querySelectorAll('#fixRoundTabs .round-tab').forEach(function(t){ t.classList.toggle('active', t === btn); });
    if (isPast) {
      pastSelectedGame = null;
      pastRowsAll = buildPastRows(round);
      renderGames(round, true);
      renderPastTable();
    } else {
      upSelectedGame = null;
      upRowsAll = buildUpRows(round);
      renderGames(round, false);
      renderUpTable();
    }
  }

  window.sortFixTable = function(which, key) {
    const s = which === 'past' ? pastSort : upSort;
    const textCol = key==='name'||key==='team'||key==='pos'||key==='opponent';
    s.dir = (s.key === key) ? -s.dir : (textCol ? 1 : -1);
    s.key = key;
    if (which === 'past') renderPastTable(); else renderUpTable();
  };

  // One continuous timeline: played rounds oldest→newest, then upcoming rounds.
  const tabsEl = document.getElementById('fixRoundTabs');
  const loadedRounds = ROUNDS_LOADED.slice();
  var upcomingRounds = [];
  (UPCOMING_DIFF||[]).forEach(function(d){ (d.games||[]).forEach(function(g){ if(upcomingRounds.indexOf(g.round)===-1) upcomingRounds.push(g.round); }); });
  upcomingRounds.sort(function(a,b){return a-b;});

  var defaultBtn = null;
  loadedRounds.forEach(function(rn) {
    const btn = document.createElement('button');
    btn.className = 'round-tab';
    btn.dataset.round = rn;
    btn.textContent = rn === 0 ? 'Opening' : 'R' + rn;
    btn.onclick = function(){ loadRound(rn, true, btn); };
    tabsEl.appendChild(btn);
    if (rn === loadedRounds[loadedRounds.length-1]) defaultBtn = btn; // most recent played round
  });
  var firstUpcomingBtn = null;
  upcomingRounds.forEach(function(rn) {
    const btn = document.createElement('button');
    btn.className = 'round-tab round-tab-future';
    btn.dataset.round = rn;
    btn.textContent = 'R' + rn;
    btn.onclick = function(){ loadRound(rn, false, btn); };
    tabsEl.appendChild(btn);
    if (!firstUpcomingBtn) firstUpcomingBtn = btn;
  });

  if (defaultBtn) loadRound(loadedRounds[loadedRounds.length-1], true, defaultBtn);
  else if (firstUpcomingBtn) loadRound(upcomingRounds[0], false, firstUpcomingBtn);

  // Jump here from anywhere (e.g. a Leaderboard form box) straight to a specific
  // player's game for a specific round, with that game already focused.
  window.goToFixtureGame = function(playerKey, round) {
    const p = getP(playerKey);
    const h = p && p.history ? p.history.find(function(x){ return x.round === round; }) : null;
    showPage('fixtures', document.querySelectorAll('.nav-btn')[1]);
    const btn = tabsEl.querySelector('.round-tab[data-round="' + round + '"]');
    if (btn) btn.click();
    if (p && h && h.opponent) {
      const pair = [p.team, h.opponent].sort();
      pastSelectedGame = {team_a: pair[0], team_b: pair[1]};
      renderGames(round, true);
      renderPastTable();
    }
  };
})();

// ── Season Awards ──────────────────────────────────────────────────────────────
function renderAwards() {
  const grid = document.getElementById('awardsGrid');
  if (!grid) return;
  const eligible = PLAYERS_DATA.filter(function(p){ return p.history && p.history.length >= 3; });

  function best(list, scoreFn) {
    var top = null, topScore = -Infinity;
    list.forEach(function(p) {
      const s = scoreFn(p);
      if (s != null && !isNaN(s) && s > topScore) { topScore = s; top = p; }
    });
    return top ? {p: top, val: topScore} : null;
  }
  // Like best(), but returns every player tied for the top score rather than
  // silently picking whichever one happened to appear first in PLAYERS_DATA —
  // used for the Season Leaders group, where "most votes"/"most BOGs" ties are
  // common enough (small integer counts) that dropping the other tied players
  // was misleading. tiedPlayers is always the full list, length 1 when no tie.
  function bestTied(list, scoreFn) {
    var topScore = -Infinity, tied = [];
    list.forEach(function(p) {
      const s = scoreFn(p);
      if (s == null || isNaN(s)) return;
      if (s > topScore) { topScore = s; tied = [p]; }
      else if (s === topScore) { tied.push(p); }
    });
    return tied.length ? {p: tied[0], val: topScore, tiedPlayers: tied} : null;
  }
  function seasonPriceChange(p) {
    const posts = (p.history || []).map(function(h){ return h.post_price; }).filter(function(x){ return x != null; });
    return posts.length >= 2 ? posts[posts.length - 1] - posts[0] : null;
  }

  var awards = [];

  const voteWinner = bestTied(PLAYERS_DATA, function(p){
    return p.history ? p.history.reduce(function(s,h){ return s + (h.votes || 0); }, 0) : null;
  });
  if (voteWinner) awards.push({group:'leaders', icon:'\u{1F3C5}', title:'Vote Machine', p:voteWinner.p, stat:voteWinner.val, sub:'Brownlow votes this season', tiedPlayers:voteWinner.tiedPlayers});

  var hiScore = null, hiEntries = [];
  PLAYERS_DATA.forEach(function(p){
    (p.history || []).forEach(function(h){
      if (hiScore === null || h.score > hiScore) { hiScore = h.score; hiEntries = [{p:p, round:h.round}]; }
      else if (h.score === hiScore) { hiEntries.push({p:p, round:h.round}); }
    });
  });
  if (hiEntries.length) {
    const seenKeys = new Set(), hiPlayers = [];
    hiEntries.forEach(function(e){ if (!seenKeys.has(e.p.key)) { seenKeys.add(e.p.key); hiPlayers.push(e.p); } });
    const hiRound = hiEntries[0].round;
    awards.push({group:'leaders', icon:'\u{1F680}', title:'Highest Single-Game Score', p:hiPlayers[0], stat:hiScore, sub:(hiRound === 0 ? 'Opening round' : 'Round ' + hiRound), tiedPlayers:hiPlayers});
  }

  const judgesPet = bestTied(PLAYERS_DATA, function(p){
    return p.history ? p.history.filter(function(h){ return h.votes === 3; }).length : null;
  });
  if (judgesPet && judgesPet.val > 0) awards.push({group:'leaders', icon:'\u{1F31F}', title:'Best on Ground', p:judgesPet.p, stat:judgesPet.val + ' BOG' + (judgesPet.val>1?'s':''), sub:'games with the full 3 votes', tiedPlayers:judgesPet.tiedPlayers});

  const valueWinner = best(eligible.filter(function(p){ return p.current_price; }), function(p){
    const st = playerStats(p.key); return st && st.n ? st.avg / (p.current_price / 1000) : null;
  });
  if (valueWinner) {
    const st = playerStats(valueWinner.p.key);
    awards.push({group:'money', icon:'\u{1F48E}', title:'Best Value', p:valueWinner.p, stat:valueWinner.val.toFixed(2), sub:'pts per $1K · avg ' + st.avg.toFixed(1) + ' at ' + fmtPrice(valueWinner.p.current_price)});
  }

  const bargainWinner = best(eligible.filter(function(p){ return p.starting_price; }), function(p){
    const st = playerStats(p.key); return st && st.n ? st.avg / (p.starting_price / 1000) : null;
  });
  if (bargainWinner) {
    const st = playerStats(bargainWinner.p.key);
    awards.push({group:'money', icon:'\u{1F3E6}', title:'Best Bargain', p:bargainWinner.p, stat:fmtPrice(bargainWinner.p.starting_price), sub:'started here · now avg ' + st.avg.toFixed(1)});
  }

  const riser = best(eligible, seasonPriceChange);
  if (riser) awards.push({group:'money', icon:'\u{1F4C8}', title:'Biggest Price Riser', p:riser.p, stat:(riser.val >= 0 ? '+' : '') + fmtPrice(riser.val), sub:'this season'});

  const faller = best(eligible, function(p){ const v = seasonPriceChange(p); return v != null ? -v : null; });
  if (faller) awards.push({group:'money', icon:'\u{1F4C9}', title:'Biggest Price Faller', p:faller.p, stat:fmtPrice(seasonPriceChange(faller.p)), sub:'this season'});

  const consistWinner = best(eligible.filter(function(p){ return p.consistency != null; }), function(p){ return p.consistency; });
  if (consistWinner) awards.push({group:'form', icon:'\u{1F3AF}', title:'Most Consistent', p:consistWinner.p, stat:consistWinner.val + '/100', sub:'consistency rating'});

  const hotWinner = best(eligible, function(p){
    const st = playerStats(p.key); return (st && st.n >= 3) ? st.l3 - st.avg : null;
  });
  if (hotWinner) {
    const st = playerStats(hotWinner.p.key);
    awards.push({group:'form', icon:'\u{1F525}', title:'Hottest Streak', p:hotWinner.p, stat:'+' + hotWinner.val.toFixed(1), sub:'L3 avg ' + st.l3.toFixed(1) + ' vs season ' + st.avg.toFixed(1)});
  }

  function stddev(scores) {
    const n = scores.length; if (!n) return 0;
    const m = scores.reduce(function(a,b){return a+b;},0)/n;
    return Math.sqrt(scores.reduce(function(a,b){return a+Math.pow(b-m,2);},0)/n);
  }
  const wellSampled = eligible.filter(function(p){ return p.history.length >= 5; });

  const coldWinner = best(eligible, function(p){
    const st = playerStats(p.key); return (st && st.n >= 3) ? -(st.l3 - st.avg) : null;
  });
  if (coldWinner) {
    const st = playerStats(coldWinner.p.key);
    awards.push({group:'form', icon:'\u{1F9CA}', title:'Coldest Streak', p:coldWinner.p, stat:'-' + coldWinner.val.toFixed(1), sub:'L3 avg ' + st.l3.toFixed(1) + ' vs season ' + st.avg.toFixed(1)});
  }

  function firstLastSplit(p) {
    const scores = p.history.map(function(h){ return h.score; });
    if (scores.length < 6) return null;
    const first3 = scores.slice(0,3).reduce(function(a,b){return a+b;},0)/3;
    const last3 = scores.slice(-3).reduce(function(a,b){return a+b;},0)/3;
    return last3 - first3;
  }
  const improved = best(eligible.filter(function(p){return p.history.length>=6;}), firstLastSplit);
  if (improved) awards.push({group:'form', icon:'\u{1F331}', title:'Most Improved', p:improved.p, stat:'+' + improved.val.toFixed(1), sub:'points better late season vs early'});

  const declined = best(eligible.filter(function(p){return p.history.length>=6;}), function(p){ const v = firstLastSplit(p); return v != null ? -v : null; });
  if (declined) awards.push({group:'form', icon:'\u{1F4C9}', title:'Biggest Decline', p:declined.p, stat:'-' + declined.val.toFixed(1), sub:'points worse late season vs early'});

  const volatile = best(wellSampled, function(p){ return stddev(p.history.map(function(h){return h.score;})); });
  if (volatile) awards.push({group:'form', icon:'\u{1F3A2}', title:'Most Volatile', p:volatile.p, stat:'±' + volatile.val.toFixed(1), sub:'biggest score swings week to week'});

  const metronome = best(wellSampled, function(p){ return -stddev(p.history.map(function(h){return h.score;})); });
  if (metronome) awards.push({group:'form', icon:'\u{1F3B5}', title:'Metronome', p:metronome.p, stat:'±' + (-metronome.val).toFixed(1), sub:'lowest score swings · same score every week'});

  const highFloor = best(wellSampled, function(p){ const st = playerStats(p.key); return st.worst; });
  if (highFloor) {
    const st = playerStats(highFloor.p.key);
    awards.push({group:'form', icon:'\u{1F6E1}\u{FE0F}', title:'Highest Floor', p:highFloor.p, stat:st.worst, sub:'worst score all season'});
  }

  const boomOrBust = best(wellSampled, function(p){ const st = playerStats(p.key); return st.best - st.worst; });
  if (boomOrBust) {
    const st = playerStats(boomOrBust.p.key);
    awards.push({group:'form', icon:'\u{1F4A3}', title:'Boom or Bust', p:boomOrBust.p, stat:st.best + ' / ' + st.worst, sub:'best vs worst · anything can happen'});
  }

  const underRadar = best(eligible.filter(function(p){
    const totalV = (p.history||[]).reduce(function(s,h){return s+(h.votes||0);},0);
    return totalV === 0;
  }), function(p){ const st = playerStats(p.key); return st.avg; });
  if (underRadar) {
    const st = playerStats(underRadar.p.key);
    awards.push({group:'form', icon:'\u{1F977}', title:'Under the Radar', p:underRadar.p, stat:st.avg.toFixed(1) + ' avg', sub:'zero votes, still puts up big scores'});
  }

  const POS_AWARD_META = {
    MID: {icon:'\u{1F3C9}', title:'Best Midfielder'},
    DEF: {icon:'\u{1F6E1}\u{FE0F}', title:'Best Defender'},
    RUC: {icon:'\u{1F5FC}', title:'Best Ruck'},
    FWD: {icon:'\u{1F3AF}', title:'Best Forward'}
  };
  ['MID','DEF','RUC','FWD'].forEach(function(pos) {
    const contenders = eligible.filter(function(p){ return p.positions && p.positions.includes(pos); });
    const posBest = best(contenders, function(p){ const st = playerStats(p.key); return st.avg; });
    if (posBest) {
      const st = playerStats(posBest.p.key);
      const meta = POS_AWARD_META[pos];
      awards.push({group:'position', icon:meta.icon, title:meta.title, p:posBest.p, stat:st.avg.toFixed(1) + ' avg', sub:'#1 ranked ' + pos + ' this season'});
    }
  });

  const GROUP_META = {
    leaders: {title:'\u{1F3C5} Season Leaders'},
    money: {title:'\u{1F4B0} Money Movers'},
    form: {title:'\u{1F4CA} Form & Consistency'},
    position: {title:'\u{1F3C6} Best By Position'}
  };
  var html = '';
  var idx = 0;
  ['leaders','money','form','position'].forEach(function(g) {
    const groupAwards = awards.filter(function(a){ return a.group === g; });
    if (!groupAwards.length) return;
    html += '<div class="award-group-title">' + GROUP_META[g].title + '</div><div class="awards-grid">';
    html += groupAwards.map(function(a) {
      const dn = a.p.display_name || getDisplayName(a.p.name, a.p.team);
      const tCol = teamColor(a.p.team);
      const safeKey = a.p.key.replace(/'/g,"\\'");
      idx++;
      const tied = a.tiedPlayers && a.tiedPlayers.length > 1 ? a.tiedPlayers : null;
      const playerBlock = tied
        ? '<div class="award-avatar" style="background:' + tCol + '">×' + tied.length + '</div>' +
          '<div><div class="award-name">' + tied.map(function(tp){
              const tdn = tp.display_name || getDisplayName(tp.name, tp.team);
              const tk = tp.key.replace(/'/g,"\\'");
              return '<span class="player-link" onclick="searchAndShowPlayer(\'' + tk + '\')">' + tdn + '</span>';
            }).join(', ') + '</div><div class="award-tied-note">' + tied.length + '-way tie</div></div>'
        : '<div class="award-avatar" style="background:' + tCol + '">' + dn.charAt(0).toUpperCase() + '</div>' +
          '<div><div class="award-name" onclick="searchAndShowPlayer(\'' + safeKey + '\')">' + dn + '</div>' + teamTagHtml(a.p.team) + '</div>';
      return '<div class="award-card" style="animation-delay:' + (Math.min(idx,12) * 0.04) + 's">' +
        '<div class="award-icon">' + a.icon + '</div>' +
        '<div class="award-title">' + a.title + '</div>' +
        '<div class="award-player">' + playerBlock + '</div>' +
        '<div class="award-stat" style="color:' + tCol + '">' + a.stat + '</div>' +
        '<div class="award-stat-sub">' + a.sub + '</div>' +
      '</div>';
    }).join('');
    html += '</div>';
  });
  grid.innerHTML = html;
}
renderAwards();

// ── Targets ──────────────────────────────────────────────────────────────────
function playerTier(price) {
  if (price == null) return null;
  if (price < 350000) return 'rookies';
  if (price <= 800000) return 'midprice';
  return 'premiums';
}

// Premiums: pure scoring output. Player's own current-form baseline (same weighting
// as calcProjectedScore), averaged across the fixture-adjusted projection for every
// remaining game this season — not just the next one.
function restOfSeasonAvg(p) {
  const scores = opponentAdjustedScores(p);
  const n = scores.length; if (!n) return null;
  const seasonAvg = scores.reduce(function(a,b){return a+b;},0)/n;
  const l3 = scores.slice(-3).reduce(function(a,b){return a+b;},0)/Math.min(3,n);
  const l5 = scores.slice(-5).reduce(function(a,b){return a+b;},0)/Math.min(5,n);
  const baseProj = (l3*0.50 + l5*0.30 + seasonAvg*0.20) * cbaTrendMultiplier(p);
  const teamFix = (UPCOMING_DIFF||[]).find(function(d){ return d.team === p.team; });
  const games = (teamFix && teamFix.games) ? teamFix.games : [];
  const form = l3 > seasonAvg + 5 ? 'trending up' : l3 < seasonAvg - 5 ? 'trending down' : 'steady form';
  if (!games.length) return {avg: baseProj, games: 0, seasonAvg: seasonAvg, form: form, nextOpponent: null, nextRating: null};
  const pos = p.positions && p.positions.length ? p.positions[0] : null;
  var total = 0;
  games.forEach(function(g){
    const rating = (pos && g.pos && g.pos[pos] != null) ? g.pos[pos] : g.overall;
    total += baseProj * (0.4 + rating/166.7);
  });
  const next = games[0];
  return {avg: total/games.length, games: games.length, seasonAvg: seasonAvg, form: form,
    nextOpponent: next.opponent, nextRating: (pos && next.pos && next.pos[pos] != null) ? next.pos[pos] : next.overall};
}

// Rookies: cumulative predicted price growth for the rest of the season. Simulates
// round by round — each remaining game's fixture-adjusted projected score is compared
// against the fitted breakeven model (see breakeven() above), recomputed each round
// from the evolving simulated price and rolling scores, then that projection rolls
// into the next round's baseline before moving on, so it compounds like real cash
// generation does instead of just multiplying one round's delta by games remaining.
function restOfSeasonPriceChange(p) {
  const teamFix = (UPCOMING_DIFF||[]).find(function(d){ return d.team === p.team; });
  const games = (teamFix && teamFix.games) ? teamFix.games : [];
  if (!games.length || !p.history || !p.history.length) return null;
  const pos = p.positions && p.positions.length ? p.positions[0] : null;
  var rolling = p.history.slice(-3).map(function(h){return h.score;});
  var simPrice = p.current_price;
  var total = 0;
  const trajectory = [{round: 'Now', opponent: null, price: Math.round(simPrice)}];
  games.forEach(function(g){
    const rating = (pos && g.pos && g.pos[pos] != null) ? g.pos[pos] : g.overall;
    const mult = 0.4 + rating/166.7;
    const rollAvg = rolling.reduce(function(a,b){return a+b;},0)/rolling.length;
    const projScore = rollAvg * mult;
    const be = breakeven(simPrice, rolling);
    const magic = priceChangeMagicNumber(simPrice);
    var change = Math.round(magic * (projScore - be));
    const cap = Math.round((simPrice||1)*0.15);
    change = Math.max(-cap, Math.min(cap, change));
    total += change;
    simPrice = (simPrice||0) + change;
    rolling.push(projScore);
    if (rolling.length > 5) rolling.shift();
    trajectory.push({round: 'R' + g.round, opponent: g.opponent, price: Math.round(simPrice)});
  });
  return {total: Math.round(total), games: games.length, endPrice: Math.round(simPrice), nextOpponent: games[0].opponent, trajectory: trajectory};
}

// Mid price: season avg as the baseline (their whole body of work), scaled by how
// friendly their next few matchups are — weighted heavily toward the very next game
// and decaying after that, since mid-pricers are typically short-term trade targets
// rather than season-long holds.
function midPriceTargetScore(p) {
  const scores = p.history.map(function(h){return h.score;});
  const n = scores.length; if (n < 3) return null;
  const seasonAvg = scores.reduce(function(a,b){return a+b;},0)/n;
  const teamFix = (UPCOMING_DIFF||[]).find(function(d){ return d.team === p.team; });
  const games = (teamFix && teamFix.games) ? teamFix.games : [];
  const pos = p.positions && p.positions.length ? p.positions[0] : null;
  const nearTerm = games.slice(0,3);
  var matchupRating = 100;
  if (nearTerm.length) {
    var tw=0, ws=0;
    nearTerm.forEach(function(g,i){
      const w = Math.pow(0.75,i);
      const rating = (pos && g.pos && g.pos[pos] != null) ? g.pos[pos] : g.overall;
      ws += rating*w; tw += w;
    });
    matchupRating = ws/tw;
  }
  return {score: seasonAvg*(0.4+matchupRating/166.7), seasonAvg: seasonAvg, matchupRating: matchupRating, games: nearTerm.length,
    nextOpponent: nearTerm.length ? nearTerm[0].opponent : null};
}

function renderTargetsTier(tier) {
  // Every priced player with at least one game goes in one of the three price
  // bands — no top-N cutoff, so nobody who qualifies for a tier is hidden.
  const pool = PLAYERS_DATA.filter(function(p){
    if (!p.current_price || playerTier(p.current_price) !== tier) return false;
    if (INJURED_SET && INJURED_SET.has(p.name)) return false;
    if (!p.history || p.history.length < 1) return false;
    return true;
  });

  var rows = [];
  if (tier === 'premiums') {
    rows = pool.map(function(p){
      const r = restOfSeasonAvg(p);
      if (!r) return null;
      const sub = 'season avg ' + r.seasonAvg.toFixed(1) + ' · ' + r.form + (r.nextOpponent ? ' · next: ' + r.nextOpponent + ' (' + r.nextRating.toFixed(0) + ')' : '');
      return {p:p, metric:r.avg, sub: sub};
    }).filter(Boolean).sort(function(a,b){return b.metric-a.metric;});
  } else if (tier === 'rookies') {
    rows = pool.map(function(p){
      const r = restOfSeasonPriceChange(p);
      if (!r) return null;
      const sub = fmtPrice(p.current_price) + ' → ' + fmtPrice(r.endPrice) + (r.nextOpponent ? ' · next: ' + r.nextOpponent : '');
      return {p:p, metric:r.total, sub: sub};
    }).filter(Boolean).sort(function(a,b){return b.metric-a.metric;});
  } else {
    rows = pool.map(function(p){
      const r = midPriceTargetScore(p);
      if (!r) return null;
      const sub = 'season avg ' + r.seasonAvg.toFixed(1) + (r.nextOpponent ? ' · next: ' + r.nextOpponent + ' (' + r.matchupRating.toFixed(0) + ')' : '');
      return {p:p, metric:r.score, sub: sub};
    }).filter(Boolean).sort(function(a,b){return b.metric-a.metric;});
  }

  const list = document.getElementById('targetsList-' + tier);
  if (!list) return;
  list.innerHTML = rows.map(function(row, i) {
    const p = row.p;
    const dn = p.display_name || getDisplayName(p.name, p.team);
    const safeKey = p.key.replace(/'/g,"\\'");
    const metricStr = tier === 'rookies' ? ((row.metric>=0?'+':'-') + fmtPrice(Math.abs(row.metric))) : row.metric.toFixed(1);
    const metricCol = tier === 'rookies' ? (row.metric>=0?'var(--green)':'var(--red)') : 'var(--accent)';
    return '<div class="target-row" onclick="searchAndShowPlayer(\'' + safeKey + '\')">' +
      '<div class="target-rank">' + (i+1) + '</div>' +
      '<div class="target-info">' +
        '<div class="target-name">' + dn + '</div>' +
        '<div class="target-sub">' + p.team + ' · ' + posChipsHtml(p.positions) + ' · ' + fmtPrice(p.current_price) + ' · ' + row.sub + '</div>' +
      '</div>' +
      '<div class="target-metric" style="color:' + metricCol + '">' + metricStr + '</div>' +
    '</div>';
  }).join('') || '<div style="color:var(--muted);font-size:.8rem;padding:16px;text-align:center">No eligible players in this tier.</div>';
}
function renderTargets() {
  ['premiums','midprice','rookies'].forEach(renderTargetsTier);
}
renderTargets();

// ── Targets: free-form price/position/team filter ─────────────────────────────
const TEAM_ORDER = ['Crows','Lions','Blues','Magpies','Bombers','Dockers','Cats','Suns','Giants','Hawks','Demons','Kangaroos','Power','Tigers','Saints','Swans','Eagles','Bulldogs'];
(function() {
  const teamSel = document.getElementById('tfTeam');
  if (!teamSel) return;
  const present = new Set(PLAYERS_DATA.map(function(p){ return p.team; }));
  const teams = TEAM_ORDER.filter(function(t){ return present.has(t); });
  present.forEach(function(t){ if (TEAM_ORDER.indexOf(t) === -1) teams.push(t); });
  teamSel.innerHTML = '<option value="">All</option>' + teams.map(function(t){ return '<option value="' + t + '">' + t + '</option>'; }).join('');
})();

function toggleTargetFilters() {
  const panel = document.getElementById('tfDropdownPanel');
  const btn = document.getElementById('tfDropdownBtn');
  if (!panel) return;
  const open = panel.classList.toggle('open');
  if (btn) btn.classList.toggle('open', open);
}
function resetTargetFilters() {
  document.getElementById('tfMinPrice').value = '';
  document.getElementById('tfMaxPrice').value = '';
  document.getElementById('tfPosition').value = '';
  document.getElementById('tfTeam').value = '';
  renderFilteredTargets();
}

var tfSort = {key:'seasonAvg', dir:-1};
const TF_TEXT_KEYS = ['name','team','pos'];
function sortFilteredTargets(key) {
  if (tfSort.key === key) { tfSort.dir = -tfSort.dir; }
  else { tfSort.key = key; tfSort.dir = TF_TEXT_KEYS.includes(key) ? 1 : -1; }
  renderFilteredTargets();
}

function renderFilteredTargets() {
  const minEl = document.getElementById('tfMinPrice'), maxEl = document.getElementById('tfMaxPrice');
  const min = minEl.value !== '' ? +minEl.value : null;
  const max = maxEl.value !== '' ? +maxEl.value : null;
  const pos = document.getElementById('tfPosition').value;
  const team = document.getElementById('tfTeam').value;

  const pool = PLAYERS_DATA.filter(function(p){
    if (!p.current_price || !p.history || !p.history.length) return false;
    if (INJURED_SET && INJURED_SET.has(p.name)) return false;
    if (min != null && p.current_price < min) return false;
    if (max != null && p.current_price > max) return false;
    if (pos && !(p.positions && p.positions.includes(pos))) return false;
    if (team && p.team !== team) return false;
    return true;
  });

  var rows = pool.map(function(p){
    const r = restOfSeasonAvg(p);
    if (!r) return null;
    const scores = p.history.map(function(h){return h.score;});
    const l3 = scores.slice(-3).reduce(function(a,b){return a+b;},0) / Math.min(3, scores.length);
    const be = playerBreakeven(p);
    const projDelta = predictedPriceChange(p, priceProjectedScore(p.key));
    return {p:p, name:(p.display_name||getDisplayName(p.name,p.team)), team:p.team,
      pos:(p.positions&&p.positions[0])||'', price:p.current_price,
      metric:r.avg, seasonAvg:r.seasonAvg, l3:l3, nextOpponent:r.nextOpponent,
      nextRating:r.nextRating, be:be, projDelta:projDelta};
  }).filter(Boolean);

  rows.sort(function(a,b){
    var av = a[tfSort.key], bv = b[tfSort.key];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === 'string') return tfSort.dir * av.localeCompare(bv);
    return tfSort.dir * (av - bv);
  });

  document.getElementById('tfCount').textContent = rows.length + ' player' + (rows.length===1?'':'s') + ' match';
  document.querySelectorAll('#targetsFilteredTable th.sortable').forEach(function(th){
    th.classList.remove('sort-asc','sort-desc');
    if (th.dataset.key === tfSort.key) th.classList.add(tfSort.dir > 0 ? 'sort-asc' : 'sort-desc');
  });
  document.getElementById('targetsFilteredBody').innerHTML = rows.map(function(row, i) {
    const p = row.p;
    const dn = row.name;
    const safeKey = p.key.replace(/'/g,"\\'");
    const beCol = (row.be != null && row.l3 >= row.be) ? 'var(--green)' : 'var(--red)';
    const pdCol = row.projDelta == null ? 'var(--muted)' : row.projDelta >= 0 ? 'var(--green)' : 'var(--red)';
    const pdStr = row.projDelta == null ? '—' : (row.projDelta>=0?'+':'-') + fmtPrice(Math.abs(row.projDelta));
    return '<tr>' +
      '<td class="pos-num ' + (i===0?'p1':i===1?'p2':i===2?'p3':'') + '">' + (i+1) + '</td>' +
      '<td><span class="player-link" onclick="searchAndShowPlayer(\'' + safeKey + '\')">' + dn + '</span></td>' +
      '<td>' + teamTagHtml(p.team) + '</td>' +
      '<td>' + posChipsHtml(p.positions) + '</td>' +
      '<td class="ta-r">' + fmtPrice(p.current_price) + '</td>' +
      '<td class="ta-r" style="font-weight:800;color:var(--accent)">' + row.metric.toFixed(1) + '</td>' +
      '<td class="ta-r">' + row.seasonAvg.toFixed(1) + '</td>' +
      '<td class="ta-r">' + row.l3.toFixed(1) + '</td>' +
      '<td>' + (row.nextOpponent ? row.nextOpponent + ' (' + row.nextRating.toFixed(0) + ')' : '—') + '</td>' +
      '<td class="ta-r" style="color:' + beCol + '">' + (row.be != null ? row.be : '—') + '</td>' +
      '<td class="ta-r" style="color:' + pdCol + '">' + pdStr + '</td>' +
    '</tr>';
  }).join('') || '<tr><td colspan="11" style="color:var(--muted);padding:16px;text-align:center">No players match these filters.</td></tr>';
}
renderFilteredTargets();

// ── Player search ─────────────────────────────────────────────────────────────
const searchInput = document.getElementById('searchInput');
const searchResults = document.getElementById('searchResults');
searchInput.addEventListener('input', function() {
  const q = searchInput.value.toLowerCase().trim();
  if (!q) { searchResults.style.display = 'none'; return; }
  const matches = PLAYERS_DATA.filter(p =>
    (p.display_name||p.name).toLowerCase().includes(q) || p.name.toLowerCase().includes(q)
  ).slice(0, 12);
  if (!matches.length) { searchResults.style.display = 'none'; return; }
  searchResults.innerHTML = matches.map(p =>
    '<div class="search-result" onclick="showPlayer(\'' + p.key.replace(/'/g,"\\'") + '\')">' +
    '<span>' + (p.display_name || getDisplayName(p.name, p.team)) + '</span>' +
    '<span class="sr-sub">' + p.team + (p.positions && p.positions.length ? ' &middot; ' + posOrdered(p.positions) : '') + '</span>' +
    '</div>'
  ).join('');
  searchResults.style.display = 'block';
});
document.addEventListener('click', function(e) {
  if (!e.target.closest('#searchInput') && !e.target.closest('#searchResults'))
    searchResults.style.display = 'none';
});

function searchAndShowPlayer(key) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('page-players').classList.add('active');
  document.querySelectorAll('.nav-btn')[4].classList.add('active');
  showPlayer(key);
}
function searchAndShowPlayerByNameTeam(name, team) {
  const p = findByNameTeam(name, team);
  if (p) searchAndShowPlayer(p.key);
}

function showPlayer(key) {
  searchResults.style.display = 'none';
  const p = findByKey(key); if (!p) return;
  currentPlayerKey = key;
  const h = p.history;
  const rounds = h.map(x => x.round), scores = h.map(x => x.score), votes = h.map(x => x.votes);
  const postPrices = h.map(x => x.post_price != null ? x.post_price : null);
  const prePrices  = h.map(x => x.pre_price  != null ? x.pre_price  : null);
  const labels = rounds.map(r => r === 0 ? 'Opening' : 'R' + r), n = scores.length;
  const avg = n ? scores.reduce(function(a,b){return a+b;},0)/n : 0;
  const best = n ? Math.max.apply(null, scores) : 0;
  const totalV = votes.reduce(function(a,b){return a+b;},0);
  const last3 = scores.slice(-3).reduce(function(a,b){return a+b;},0) / Math.min(3, n||1);
  const last5 = scores.slice(-5).reduce(function(a,b){return a+b;},0) / Math.min(5, n||1);
  const currentPrice = p.current_price != null ? p.current_price : null;
  const validPost = postPrices.filter(x => x != null);
  const priceChange = validPost.length >= 2 ? validPost[validPost.length-1] - validPost[0] : null;
  const minP = validPost.length ? Math.min.apply(null, validPost) - 10000 : 0;
  const maxP = validPost.length ? Math.max.apply(null, validPost) + 10000 : 0;
  const vdiff = prePrices.map(function(pr,i) { return pr != null ? +(scores[i] - pr/10490).toFixed(1) : null; });
  const hasValue = vdiff.some(function(v) { return v != null; });
  const fr = p.form_rating, cs = p.consistency;

  let pcLabel = '\u2014', pcColor = 'var(--muted)';
  if (priceChange !== null) {
    const absAmt = fmtPrice(Math.abs(priceChange));
    pcLabel = priceChange >= 0 ? '+' + absAmt : '-' + absAmt;
    pcColor = priceChange >= 0 ? 'var(--green)' : 'var(--red)';
  }

  const bookmarked = lsGet('starred', []).includes(key);
  document.getElementById('bookmarkBtn').classList.toggle('bookmarked', bookmarked);
  document.getElementById('bookmarkPath').setAttribute('fill', bookmarked ? 'var(--accent)' : 'none');
  const dn = p.display_name || getDisplayName(p.name, p.team);
  const isInjured = INJURED_SET && INJURED_SET.has(p.name);
  const playerStatTag = statusLabel(p.name);
  const statusIcon = playerStatTag === 'SUS' ? ' \u{1F6AB}' : isInjured ? ' \u{1F691}' : '';
  document.getElementById('pcName').textContent = '\u{1F3C9} ' + dn + statusIcon;
  document.getElementById('pcName').title = playerStatTag === 'SUS' ? 'Reported suspended — check official team lists' : isInjured ? 'Reported injured — check official team lists' : '';
  const pcAv = document.getElementById('pcAvatar');
  if (pcAv) { pcAv.textContent = dn.charAt(0).toUpperCase(); pcAv.style.background = teamColor(p.team); }
  const posTxt = p.positions && p.positions.length ? posOrdered(p.positions) + ' · ' : '';
  document.getElementById('pcSub').textContent = posTxt + p.team + (n ? ' · Rounds: ' + rounds.map(r => r===0?'Opening':'R'+r).join(', ') : ' · No game data');
  const pcRankEl = document.getElementById('pcRank');
  if (pcRankEl) {
    const rk = positionRank(key);
    if (rk) {
      const rkCol = rk.percentile <= 10 ? 'var(--accent)' : rk.percentile <= 25 ? 'var(--green)' : rk.percentile <= 50 ? 'var(--accent2)' : 'var(--muted)';
      pcRankEl.innerHTML = '<span class="pc-rank-badge" style="color:' + rkCol + ';border-color:' + rkCol + '">\u{1F3C5} #' + rk.rank + ' of ' + rk.total + ' ' + rk.pos + ' · top ' + rk.percentile + '%</span>';
    } else {
      pcRankEl.innerHTML = '';
    }
  }

  const pcArchEl = document.getElementById('pcArchetypes');
  if (pcArchEl) {
    currentArchetypeHits = p.archetypes || [];
    openArchetypeDetailIdx = -1;
    if (p.archetypes && p.archetypes.length) {
      const badges = p.archetypes.map(function(a, i){
        return '<span class="archetype-badge" style="color:' + a.color + ';background:' + hexToRgba(a.color, .18) + '" onclick="toggleArchetypeDetail(' + i + ')">' + a.label + '</span>';
      }).join('');
      const conclusion = p.archetype_conclusion ? '<div class="archetype-conclusion">\u{1F4A1} ' + p.archetype_conclusion + '</div>' : '';
      pcArchEl.innerHTML = badges + conclusion + '<div id="pcArchetypeDetail" class="archetype-detail" style="display:none"></div>';
    } else if (p.advanced_coverage === 'none') {
      pcArchEl.innerHTML = '<span class="archetype-badge no-data">No archetype data yet</span>';
    } else {
      pcArchEl.innerHTML = p.archetype_conclusion ? '<div class="archetype-conclusion">' + p.archetype_conclusion + '</div>' : '';
    }
  }

  const advSection = document.getElementById('advStatsSection');
  const advGrid = document.getElementById('advStatsGrid');
  const latestAdvRound = h.length ? h[h.length - 1].round : null;
  const latestAdv = (p.advanced_history && latestAdvRound != null) ? p.advanced_history[latestAdvRound] : null;
  if (advSection && advGrid) {
    if (latestAdv) {
      const ADV_DISPLAY_STATS = [
        ["Disposals","Disp"], ["Tackles","Tackles"], ["TotalClearances","Clear."],
        ["ContestedPossessions","CP"], ["Inside50s","I50"], ["Intercepts","Int."],
        ["Marks","Marks"], ["Goals","Goals"], ["ScoreInvolvements","Sc.Inv"],
      ];
      advGrid.innerHTML = ADV_DISPLAY_STATS.map(function(pair){
        const v = latestAdv[pair[0]];
        return '<div class="adv-stat-tile"><div class="lbl">' + pair[1] + '</div><div class="val">' + (v != null ? v : '—') + '</div></div>';
      }).join('');
      advSection.style.display = '';
    } else {
      advSection.style.display = 'none';
    }
  }

  const projScore = calcProjectedScore(key);
  const priceProj = (!isInjured) ? restOfSeasonPriceChange(p) : null;
  const projDeltaNextRound = (!isInjured) ? predictedPriceChange(p, priceProjectedScore(key)) : null;
  let s = '';
  // Order: durability/context -> price -> scoring track record -> forward scoring
  // estimate -> the full price-movement story (breakeven, then actual-so-far, then
  // both forward projections) -> the two 0-100 ratings last as a summary.
  // All league-rank comparisons use the same "played at least one game" population,
  // so the "#N" badges are comparable card to card. A stricter n>=3 gate used to
  // silently exclude anyone with 1-2 games from every ranked stat (not just the
  // averages where a tiny sample is genuinely noisy) — Games Played, Votes, Price,
  // Breakeven and the price deltas don't need 3 games to be meaningful, and someone
  // like a 2-game debutant deserves a rank rather than nothing everywhere.
  function rankOf(valueFn, lowerBetter) {
    return leagueRank(key, function(pp){ const h=pp.history; return (h&&h.length>=1) ? valueFn(pp,h) : null; }, lowerBetter);
  }
  if (n) {
    s += '<div class="stat-card"><div class="stat-label">Games Played</div><div class="stat-value">' + n + '</div>' + rankTagHtml(rankOf(function(pp,h){ return h.length; })) + '</div>';
    s += '<div class="stat-card"><div class="stat-label">Votes</div><div class="stat-value">' + totalV + '</div>' + rankTagHtml(rankOf(function(pp,h){ return h.reduce(function(a,x){return a+(x.votes||0);},0); })) + '</div>';
  }
  if (currentPrice != null)
    s += '<div class="stat-card"><div class="stat-label">Price</div><div class="stat-value" style="color:var(--text)">' + fmtPrice(currentPrice) + '</div>' + rankTagHtml(rankOf(function(pp){ return pp.current_price; })) + '</div>';
  if (n) {
    s += '<div class="stat-card"><div class="stat-label">Season Avg</div><div class="stat-value">' + avg.toFixed(1) + '</div>' + rankTagHtml(rankOf(function(pp,h){ return h.reduce(function(a,x){return a+x.score;},0)/h.length; })) + '</div>';
    s += '<div class="stat-card"><div class="stat-label">L3 Avg</div><div class="stat-value">' + last3.toFixed(1) + '</div>' + rankTagHtml(rankOf(function(pp,h){ const w=h.slice(-3); return w.reduce(function(a,x){return a+x.score;},0)/w.length; })) + '</div>';
    s += '<div class="stat-card"><div class="stat-label">L5 Avg</div><div class="stat-value">' + last5.toFixed(1) + '</div>' + rankTagHtml(rankOf(function(pp,h){ const w=h.slice(-5); return w.reduce(function(a,x){return a+x.score;},0)/w.length; })) + '</div>';
    s += '<div class="stat-card"><div class="stat-label">Season High</div><div class="stat-value">' + best + '</div>' + rankTagHtml(rankOf(function(pp,h){ return Math.max.apply(null,h.map(function(x){return x.score;})); })) + '</div>';
    if (projScore != null) s += '<div class="stat-card stat-card-proj" style="border-color:rgba(59,130,246,.3);background:rgba(59,130,246,.08)"><div class="stat-label" style="color:var(--accent2)">Projected</div><div class="stat-value" style="color:var(--accent2)">' + projScore + '</div>' + rankTagHtml(rankOf(function(pp){ return (INJURED_SET&&INJURED_SET.has(pp.name)) ? null : calcProjectedScore(pp.key); })) + '</div>';
  }
  // Breakeven/Season Δ/Next Δ/Rest Δ all share one consistent rule: green = price moving
  // (or projected to move) up, red = down. Breakeven's color reflects whether recent form
  // (L3) currently clears it, since that's what actually drives the next move. Next Δ and
  // Rest Δ get a dashed border (like Projected above) marking them as forward estimates —
  // Season Δ alone is real, already-happened price movement, so it stays solid.
  const be = playerBreakeven(p);
  if (be != null) {
    const beCol = last3 >= be ? 'var(--green)' : 'var(--red)';
    s += '<div class="stat-card"><div class="stat-label">Breakeven</div><div class="stat-value" style="color:' + beCol + '">' + be + '</div>' + rankTagHtml(rankOf(function(pp){ return playerBreakeven(pp); }, true)) + '</div>';
  }
  if (priceChange !== null)
    s += '<div class="stat-card"><div class="stat-label">Season &Delta;</div><div class="stat-value" style="color:' + pcColor + '">' + pcLabel + '</div>' + rankTagHtml(rankOf(function(pp,h){ const vp=h.map(function(x){return x.post_price;}).filter(function(x){return x!=null;}); return vp.length>=2 ? vp[vp.length-1]-vp[0] : null; })) + '</div>';
  if (projDeltaNextRound != null) {
    const pdCol = projDeltaNextRound >= 0 ? 'var(--green)' : 'var(--red)';
    const pdLabel = (projDeltaNextRound>=0?'+':'-') + fmtPrice(Math.abs(projDeltaNextRound));
    s += '<div class="stat-card stat-card-proj"><div class="stat-label">Next Proj &Delta;</div><div class="stat-value" style="color:' + pdCol + '">' + pdLabel + '</div>' + rankTagHtml(rankOf(function(pp){ return (INJURED_SET&&INJURED_SET.has(pp.name)) ? null : predictedPriceChange(pp, priceProjectedScore(pp.key)); })) + '</div>';
  }
  if (priceProj != null) {
    const ppCol = priceProj.total >= 0 ? 'var(--green)' : 'var(--red)';
    const ppLabel = (priceProj.total>=0?'+':'-') + fmtPrice(Math.abs(priceProj.total));
    s += '<div class="stat-card stat-card-proj"><div class="stat-label">Szn Proj &Delta;</div><div class="stat-value" style="color:' + ppCol + '">' + ppLabel + '</div>' + rankTagHtml(rankOf(function(pp){ if(INJURED_SET&&INJURED_SET.has(pp.name)) return null; const r=restOfSeasonPriceChange(pp); return r?r.total:null; })) + '</div>';
  }
  if (fr != null)
    s += '<div class="stat-card"><div class="stat-label">Form</div><div class="stat-value" style="color:' + ratingColor(fr) + '">' + fr + '<span style="font-size:.7rem;color:var(--muted)">/100</span></div><div class="rating-bar-wrap"><div class="rating-bar" style="width:' + fr + '%;background:' + ratingColor(fr) + '"></div></div></div>';
  if (cs != null)
    s += '<div class="stat-card"><div class="stat-label">Consistency</div><div class="stat-value" style="color:' + ratingColor(cs) + '">' + cs + '<span style="font-size:.7rem;color:var(--muted)">/100</span></div><div class="rating-bar-wrap"><div class="rating-bar" style="width:' + cs + '%;background:' + ratingColor(cs) + '"></div></div></div>';

  document.getElementById('pcStats').innerHTML = s;
  document.getElementById('playerCard').classList.add('active');
  // Show report button, reset any previous report
  document.getElementById('playerReportWrap').style.display = 'block';
  document.getElementById('playerReport').style.display = 'none';
  document.getElementById('playerReport').innerHTML = '';
  document.getElementById('reportBtn').textContent = '\u{1F4CB} Generate Trade Report';
  document.getElementById('reportBtn').disabled = false;
  if (mainChartInst) { mainChartInst.destroy(); mainChartInst = null; }
  if (valueChartInst) { valueChartInst.destroy(); valueChartInst = null; }
  if (fixtureChartInst) { fixtureChartInst.destroy(); fixtureChartInst = null; }
  if (distChartInst) { distChartInst.destroy(); distChartInst = null; }

  if (n) {
    const votePlugin = {id:'vp', afterDatasetsDraw: function(chart) {
      const meta = chart.getDatasetMeta(0); if (!meta || meta.type !== 'bar') return;
      const ctx = chart.ctx;
      meta.data.forEach(function(bar, i) {
        const v = votes[i]; if (v > 0) {
          ctx.save(); ctx.font = 'bold 11px Barlow,sans-serif';
          ctx.fillStyle = v===3?'#e8a020':v===2?'#c0c0c0':'#cd7f32';
          ctx.textAlign = 'center'; ctx.fillText(v + (v===1?' vote':' votes'), bar.x, bar.y - 8);
          ctx.restore();
        }
      });
    }};

    // CBA% folded into the same chart as a 3rd dataset/axis rather than a separate
    // graph, aligned round-for-round with the score bars. The correlation readout
    // in the title only uses rounds where both a score and a CBA% exist.
    const cbaAligned = rounds.map(function(r){ return (p.cba_history && p.cba_history[r] != null) ? p.cba_history[r] : null; });
    const hasCba = cbaAligned.some(function(v){ return v != null; });
    const corrEl = document.getElementById('cbaCorrelation');
    if (hasCba) {
      const pairedScores = [], pairedCba = [];
      cbaAligned.forEach(function(v,i){ if (v != null) { pairedCba.push(v); pairedScores.push(scores[i]); } });
      const corr = pairedScores.length >= 2 ? pearsonCorrelation(pairedCba, pairedScores) : null;
      if (corr != null) {
        const absCorr = Math.abs(corr);
        const strength = absCorr >= 0.7 ? 'strong' : absCorr >= 0.4 ? 'moderate' : absCorr >= 0.2 ? 'weak' : 'no clear';
        const direction = absCorr >= 0.2 ? (corr >= 0 ? ' positive' : ' negative') : '';
        corrEl.style.color = absCorr >= 0.4 ? (corr >= 0 ? 'var(--green)' : 'var(--red)') : 'var(--muted)';
        corrEl.textContent = 'CBA r = ' + corr.toFixed(2) + ' (' + strength + direction + ')';
      } else {
        corrEl.textContent = '';
      }
    } else {
      corrEl.textContent = '';
    }

    const mainDatasets = [
      {type:'bar',label:'Fantasy Score',data:scores,yAxisID:'scoreAxis',backgroundColor:'rgba(59,130,246,.75)',borderRadius:4},
      {type:'line',label:'Price',data:postPrices,yAxisID:'priceAxis',tension:.3,borderWidth:2.5,borderColor:'#f87171',backgroundColor:'transparent',pointBackgroundColor:'#f87171',pointRadius:3,spanGaps:false}
    ];
    const mainScales = {
      scoreAxis: {type:'linear',position:'left',afterFit:function(a){a.width=26;},ticks:{color:cssVar('--text'),font:{size:10}},grid:{color:chartGridColor()},title:{display:false}},
      priceAxis: {type:'linear',position:'right',suggestedMin:minP,suggestedMax:maxP,afterFit:function(a){a.width=60;},grid:{drawOnChartArea:false},ticks:{color:'#f87171',callback:function(v){return fmtPrice(v);}},title:{display:true,text:'Price',color:'#f87171'}},
      x: {ticks:{color:cssVar('--text')}}
    };
    if (hasCba) {
      mainDatasets.push({type:'line',label:'CBA%',data:cbaAligned,yAxisID:'cbaAxis',tension:.3,borderWidth:2,borderColor:'#e8a020',backgroundColor:'transparent',pointBackgroundColor:'#e8a020',pointRadius:3,spanGaps:false});
      mainScales.cbaAxis = {type:'linear',position:'right',min:0,max:100,afterFit:function(a){a.width=44;},grid:{drawOnChartArea:false},ticks:{color:'#e8a020',callback:function(v){return v+'%';}},title:{display:true,text:'CBA%',color:'#e8a020'}};
    }

    mainChartInst = new Chart(document.getElementById('mainChart'), {
      data: { labels: labels, datasets: mainDatasets },
      options: { responsive:true, interaction:{mode:'index',intersect:false},
        plugins: {
          tooltip: {callbacks: {label: function(ctx) {
            if (ctx.dataset.label==='Price') { var v=ctx.parsed.y; return v==null?null:'Price: '+fmtPrice(v); }
            if (ctx.dataset.label==='CBA%') { var v=ctx.parsed.y; return v==null?null:'CBA: '+v+'%'; }
            var v = votes[ctx.dataIndex]; return 'Score: '+ctx.parsed.y+(v>0?' ('+v+' vote'+(v>1?'s':'')+')'  :'');
          }}},
          legend: {display:hasCba, labels:{color:cssVar('--text'),boxWidth:12,font:{size:10}}}
        },
        // Fixed axis widths (not just matching label colors) so this chart's plot area
        // lines up pixel-for-pixel with the Value chart below — same round sits at the
        // same x position in both.
        scales: mainScales
      }, plugins:[votePlugin]
    });

    if (hasValue) {
      document.getElementById('valueSection').style.display = 'block';
      valueChartInst = new Chart(document.getElementById('valueChart'), {
        type:'bar',
        data: {labels:labels, datasets:[{label:'Score vs Expected',data:vdiff,
          backgroundColor:vdiff.map(function(v){return v==null?'transparent':v>=0?'rgba(52,211,153,.8)':'rgba(248,113,113,.8)';}),borderRadius:3}]},
        options: {responsive:true,
          plugins: {legend:{display:false},tooltip:{callbacks:{label:function(ctx) {
            var v=ctx.parsed.y; if(v==null) return null;
            var pre=prePrices[ctx.dataIndex], exp=pre!=null?(pre/10490).toFixed(1):'?';
            return ['Actual: '+scores[ctx.dataIndex], 'Expected: '+exp, 'Diff: '+(v>=0?'+':'')+v.toFixed(1)];
          }}}},
          // Same afterFit widths as the Score & Price & CBA% chart above (46px left,
          // invisible mirrors on the right in place of its price/CBA axes) so both plot
          // areas are identically sized and a given round lines up vertically between them.
          scales: (function(){
            const sc = {
              y:{afterFit:function(a){a.width=26;},ticks:{color:cssVar('--text'),font:{size:10}},grid:{color:chartGridColor()},title:{display:false}},
              yMirror:{type:'linear',position:'right',afterFit:function(a){a.width=60;},ticks:{display:false},grid:{drawOnChartArea:false},title:{display:false}},
              x:{ticks:{color:cssVar('--text')}}
            };
            if (hasCba) sc.yMirror2 = {type:'linear',position:'right',afterFit:function(a){a.width=44;},ticks:{display:false},grid:{drawOnChartArea:false},title:{display:false}};
            return sc;
          })()
        }
      });
    } else document.getElementById('valueSection').style.display = 'none';

    var showOutlook = false;

    if (n >= 3) {
      showOutlook = true;
      document.getElementById('distSection').style.display = 'block';
      const buckets = [{lo:0,hi:39,label:'0-39'},{lo:40,hi:59,label:'40-59'},{lo:60,hi:79,label:'60-79'},
        {lo:80,hi:99,label:'80-99'},{lo:100,hi:119,label:'100-119'},{lo:120,hi:9999,label:'120+'}];
      const counts = buckets.map(function(b){ return scores.filter(function(s){ return s >= b.lo && s <= b.hi; }).length; });
      // Normal-distribution overlay: fit a bell curve to this player's own mean/stddev,
      // evaluated at each bucket's midpoint and scaled to expected-games-per-bucket, so
      // you can see how "normal" (vs skewed/bimodal) their scoring actually is.
      const distMean = scores.reduce(function(a,b){return a+b;},0)/n;
      const distSd = Math.sqrt(scores.reduce(function(a,b){return a+Math.pow(b-distMean,2);},0)/n) || 1;
      const bucketWidth = 30;
      const normalCurve = buckets.map(function(b){
        const mid = (b.lo + Math.min(b.hi,150))/2;
        const pdf = (1/(distSd*Math.sqrt(2*Math.PI))) * Math.exp(-0.5*Math.pow((mid-distMean)/distSd,2));
        return +(pdf * n * bucketWidth).toFixed(2);
      });
      distChartInst = new Chart(document.getElementById('distChart'), {
        data: { labels: buckets.map(function(b){return b.label;}), datasets: [
          {type:'bar', label: 'Games', data: counts,
            backgroundColor: buckets.map(function(b){ return gradientBg((b.lo+Math.min(b.hi,150))/2, 40, 130); }),
            borderColor: buckets.map(function(b){ return gradientBorder((b.lo+Math.min(b.hi,150))/2, 40, 130); }),
            borderWidth: 2, borderRadius: 4, order: 2},
          {type:'line', label: 'Normal distribution', data: normalCurve, tension:.4, borderWidth:2,
            borderColor:'#e8a020', backgroundColor:'transparent', pointRadius:2, pointBackgroundColor:'#e8a020', order:1}
        ] },
        options: { responsive: true,
          plugins: { legend: { display: true, labels: {color: cssVar('--text'), boxWidth:12, font:{size:10}} },
            tooltip: { callbacks: { label: function(ctx) {
              return ctx.dataset.type === 'line' ? 'Expected (normal fit): ' + ctx.parsed.y.toFixed(1)
                : ctx.parsed.y + ' game' + (ctx.parsed.y===1?'':'s') + ' in this range';
          }}}},
          scales: {
            y: { ticks: { color: cssVar('--text'), precision: 0 }, grid: { color: chartGridColor() }, title: { display: true, text: 'Games', color: cssVar('--text') } },
            x: { ticks: { color: cssVar('--text') }, title: { display: true, text: 'Score Range', color: cssVar('--text') } }
          }
        }
      });
    } else {
      document.getElementById('distSection').style.display = 'none';
    }

    const fixTeam = (UPCOMING_DIFF||[]).find(function(d){ return d.team === p.team; });
    const fixGames = (fixTeam && fixTeam.games) ? fixTeam.games : [];

    if (fixGames.length && !isInjured) {
      showOutlook = true;
      document.getElementById('fixtureSection').style.display = 'block';
      const fixPos = p.positions && p.positions.length ? p.positions[0] : null;
      // Leading "Now" category so the price line has a real starting dot at today's
      // price (sitting right on the y-axis) with a line connecting it through each
      // round's projected price. The score bars have nothing to plot at "Now", so
      // that slot is left null — Chart.js just skips drawing a bar there.
      const fixLabels = ['Now'].concat(fixGames.map(function(g){ return 'R' + g.round + ' vs ' + g.opponent; }));
      const fixRatings = fixGames.map(function(g){ return (fixPos && g.pos && g.pos[fixPos] != null) ? g.pos[fixPos] : g.overall; });
      const fixBase = projScore != null ? projScore : avg;
      const fixProj = [null].concat(fixGames.map(function(g, i){
        const posPred = (fixPos && g.predicted_pos && g.predicted_pos[fixPos] != null) ? g.predicted_pos[fixPos] : g.predicted_avg;
        return fixBase != null ? Math.round(fixBase * (0.4 + fixRatings[i]/166.7)) : posPred;
      }));
      const fixPrices = (priceProj && priceProj.trajectory) ? priceProj.trajectory.map(function(t){return t.price;}) : [];
      const avgRating = fixRatings.reduce(function(a,b){return a+b;},0) / fixRatings.length;
      const avgFixProj = fixProj.slice(1).reduce(function(a,b){return a+b;},0) / (fixProj.length-1);
      document.getElementById('fixtureSummary').innerHTML =
        '<div class="lbs-item"><div class="lbs-val">' + fixGames.length + '</div><div class="lbs-lbl">Games Left</div></div>' +
        '<div class="lbs-item"><div class="lbs-val">' + fixGames[0].opponent + '</div><div class="lbs-lbl">Next Opponent</div></div>' +
        '<div class="lbs-item"><div class="lbs-val" style="color:' + gradientText(avgRating) + '">' + avgRating.toFixed(0) + '</div><div class="lbs-lbl">Avg Matchup Rating</div></div>' +
        (priceProj ? '<div class="lbs-item"><div class="lbs-val" style="color:' + (priceProj.total>=0?'var(--green)':'var(--red)') + '">' + (priceProj.total>=0?'+':'') + fmtPrice(priceProj.total) + '</div><div class="lbs-lbl">Proj Price &Delta;</div></div>' : '');
      const hasPriceLine = fixPrices.length === fixLabels.length;
      const fixDatasets = [{type:'bar', label:'Projected Score', data:fixProj, yAxisID:'fixScoreAxis',
        backgroundColor: [null].concat(fixRatings.map(function(r){ return gradientBg(r); })),
        borderColor: [null].concat(fixRatings.map(function(r){ return gradientBorder(r); })),
        borderWidth: 2, borderRadius: 4}];
      if (hasPriceLine) {
        fixDatasets.push({type:'line', label:'Projected Price', data:fixPrices, yAxisID:'fixPriceAxis',
          tension:.3, borderWidth:2.5, borderColor:'#f87171', backgroundColor:'transparent',
          pointBackgroundColor:'#f87171', pointRadius:3});
      }
      const priceVals = hasPriceLine ? fixPrices : [p.current_price];
      const fixPriceMin = Math.min.apply(null, priceVals) - 10000, fixPriceMax = Math.max.apply(null, priceVals) + 10000;
      fixtureChartInst = new Chart(document.getElementById('fixtureChart'), {
        data: { labels: fixLabels, datasets: fixDatasets },
        options: { responsive: true, interaction:{mode:'index',intersect:false},
          plugins: {
            legend: { display: hasPriceLine, labels: {color: cssVar('--text'), boxWidth:12, font:{size:10}} },
            tooltip: { callbacks: { label: function(ctx) {
              if (ctx.dataset.label === 'Projected Price') return (ctx.dataIndex===0?'Current: ':'Projected: ') + fmtPrice(ctx.parsed.y);
              if (ctx.parsed.y == null) return null;
              const r = fixRatings[ctx.dataIndex-1];
              return ['Projected: ' + ctx.parsed.y, 'Matchup rating: ' + r.toFixed(0) + (r >= 108 ? ' (easy)' : r <= 92 ? ' (hard)' : ' (avg)')];
            }}}
          },
          scales: {
            fixScoreAxis: { position:'left', ticks: { color: cssVar('--text') }, grid: { color: chartGridColor() }, title: { display: true, text: 'Projected Score', color: cssVar('--text') } },
            fixPriceAxis: { position:'right', display: hasPriceLine, suggestedMin: fixPriceMin, suggestedMax: fixPriceMax, grid:{drawOnChartArea:false}, ticks: { color: '#f87171', callback: function(v){ return fmtPrice(v); } }, title: { display: true, text: 'Price', color: '#f87171' } },
            x: { ticks: { color: cssVar('--text') } }
          }
        }
      });
    } else {
      document.getElementById('fixtureSection').style.display = 'none';
    }

    document.getElementById('outlookGroupHead').style.display = showOutlook ? 'block' : 'none';
  }

  searchInput.value = '';
}

function toggleBookmark() {
  if (!currentPlayerKey) return;
  var starred = lsGet('starred', []);
  if (starred.includes(currentPlayerKey)) starred = starred.filter(function(x){return x !== currentPlayerKey;});
  else starred.push(currentPlayerKey);
  lsSet('starred', starred);
  const bm = starred.includes(currentPlayerKey);
  document.getElementById('bookmarkBtn').classList.toggle('bookmarked', bm);
  document.getElementById('bookmarkPath').setAttribute('fill', bm ? 'var(--accent)' : 'none');
  renderStarredList();
}

function lsGet(k, d) { try { var v = localStorage.getItem('afl_'+k); return v ? JSON.parse(v) : d; } catch(e) { return d; } }
function lsSet(k, v) { try { localStorage.setItem('afl_'+k, JSON.stringify(v)); } catch(e) {} }

async function generatePlayerReport() {
  if (!currentPlayerKey) return;
  const p = findByKey(currentPlayerKey); if (!p) return;
  const btn = document.getElementById('reportBtn');
  const reportDiv = document.getElementById('playerReport');
  btn.textContent = '\u23F3 Generating...'; btn.disabled = true;
  reportDiv.style.display = 'block';
  reportDiv.innerHTML = '<span style="color:var(--muted)">Analysing player data...</span>';

  // Gather stats
  const h = p.history;
  const scores = h.map(function(x){return x.score;});
  const n = scores.length;
  if (!n) {
    reportDiv.innerHTML = '<span style="color:var(--muted)">No game data available for this player.</span>';
    btn.textContent = '\u{1F4CB} Generate Trade Report'; btn.disabled = false;
    return;
  }
  const avg    = scores.reduce(function(a,b){return a+b;},0)/n;
  const l3avg  = scores.slice(-3).reduce(function(a,b){return a+b;},0)/Math.min(3,n);
  const l5avg  = scores.slice(-5).reduce(function(a,b){return a+b;},0)/Math.min(5,n);
  const best   = Math.max.apply(null, scores);
  const worst  = Math.min.apply(null, scores);
  const price  = p.current_price;
  const beScore = price ? price/10490 : null;
  const posts  = h.map(function(x){return x.post_price;}).filter(function(x){return x!=null;});
  const priceTrend = getPlayerPriceTrend(currentPlayerKey);
  const priceChange = posts.length >= 2 ? posts[posts.length-1] - posts[0] : null;
  const fr     = p.form_rating;
  const cs     = p.consistency;
  const totalVotes = h.map(function(x){return x.votes;}).reduce(function(a,b){return a+b;},0);
  const pos    = p.positions && p.positions.length ? p.positions[0] : null;
  const recentScores = scores.slice(-5);

  // Trend: is last 3 avg higher than season avg?
  const formTrend = l3avg > avg + 5 ? 'trending up strongly' :
    l3avg > avg + 1 ? 'slightly trending up' :
    l3avg < avg - 5 ? 'trending down sharply' :
    l3avg < avg - 1 ? 'slightly trending down' : 'stable';

  // BE analysis
  const beStr = beScore ? beScore.toFixed(1) : null;
  const beatsBE = beScore ? recentScores.filter(function(s){return s >= beScore;}).length : null;
  const beContext = beScore
    ? (beatsBE + '/' + recentScores.length + ' recent scores beat break-even of ' + beStr + ' pts')
    : 'No price data';

  // Ceiling/floor analysis
  const ceilingLabel = best >= 140 ? 'elite ceiling (' + best + ')' : best >= 120 ? 'good ceiling (' + best + ')' : best >= 100 ? 'moderate ceiling (' + best + ')' : 'low ceiling (' + best + ')';
  const floorLabel = worst <= 40 ? 'dangerous floor (' + worst + ')' : worst <= 60 ? 'concerning floor (' + worst + ')' : worst <= 80 ? 'acceptable floor (' + worst + ')' : 'solid floor (' + worst + ')';
  const csLabel = cs != null ? (cs >= 75 ? 'very consistent' : cs >= 55 ? 'reasonably consistent' : cs >= 35 ? 'inconsistent' : 'very inconsistent') : '';

  // Fixture
  var fixtureLines = [];
  var fixRating = null;
  if (UPCOMING_DIFF && p.team) {
    const teamFix = UPCOMING_DIFF.find(function(d){return d.team === p.team;});
    if (teamFix && teamFix.games && teamFix.games.length) {
      fixRating = pos ? (teamFix.upcoming_pos[pos] || teamFix.upcoming_score) : teamFix.upcoming_score;
      teamFix.games.slice(0,4).forEach(function(g,i){
        const rat = pos && g.pos[pos] != null ? g.pos[pos] : g.overall;
        const proj = +(avg * rat / 100).toFixed(0);
        const diff = rat > 103 ? '🟢' : rat < 97 ? '🔴' : '🟡';
        const rLabel = g.round === 0 ? 'Open' : 'R' + g.round;
        fixtureLines.push(diff + ' ' + rLabel + ' vs ' + g.opponent + ' — projected ' + proj + ' pts (rating ' + rat.toFixed(1) + ')');
      });
    }
  }
  const fixtureSummary = fixRating != null
    ? (fixRating >= 105 ? 'very favourable' : fixRating >= 102 ? 'slightly favourable' : fixRating <= 95 ? 'very tough' : fixRating <= 98 ? 'slightly tough' : 'average')
    : 'unknown';

  // Find better alternatives (same pos, ±$100K, higher avg)
  var alts = [];
  if (price && pos) {
    PLAYERS_DATA.filter(function(op){
      if (op.key === currentPlayerKey) return false;
      if (!op.positions || !op.positions.includes(pos)) return false;
      if (!op.current_price || Math.abs(op.current_price - price) > 120000) return false;
      if (!op.history || op.history.length < 3) return false;
      const opS = op.history.map(function(x){return x.score;});
      return opS.reduce(function(a,b){return a+b;},0)/opS.length > avg + 3;
    }).sort(function(a,b){
      const aS=a.history.map(function(x){return x.score;}); const bS=b.history.map(function(x){return x.score;});
      return bS.reduce(function(x,y){return x+y;},0)/bS.length - aS.reduce(function(x,y){return x+y;},0)/aS.length;
    }).slice(0,3).forEach(function(op){
      const opS = op.history.map(function(x){return x.score;});
      const opAvg = +(opS.reduce(function(a,b){return a+b;},0)/opS.length).toFixed(1);
      const priceDiff = op.current_price - price;
      const pStr = priceDiff >= 0 ? '+' + fmtPrice(priceDiff) : '-' + fmtPrice(Math.abs(priceDiff));
      alts.push('<b style="color:var(--text)">' + (op.display_name||op.name) + '</b> (' + op.team + ') — avg <b style="color:var(--green)">' + opAvg + '</b> pts, ' + fmtPrice(op.current_price) + ' (' + pStr + ')');
    });
  }

  // Overall verdict
  var score = 50; // neutral
  if (fr != null) score += (fr - 50) * 0.3;
  if (cs != null) score += (cs - 50) * 0.15;
  if (l3avg > avg + 5) score += 8; else if (l3avg < avg - 5) score -= 8;
  if (fixRating != null) score += (fixRating - 100) * 0.4;
  if (priceTrend === 'rising') score += 6; else if (priceTrend === 'falling') score -= 6;
  if (beatsBE != null) score += (beatsBE/Math.max(recentScores.length,1) - 0.5) * 10;
  score = Math.max(0, Math.min(100, score));
  const verdict = score >= 65 ? '✅ BUY' : score >= 50 ? '🟡 HOLD' : score >= 35 ? '⚠️ CONSIDER SELLING' : '🔴 SELL';
  const verdictCol = score >= 65 ? 'var(--green)' : score >= 50 ? 'var(--yellow)' : 'var(--red)';

  // Build report HTML
  function section(emoji, title, body) {
    return '<div style="margin-bottom:14px">' +
      '<div style="font-family:\'Barlow Condensed\',sans-serif;font-weight:800;font-size:1rem;color:var(--accent2);margin-bottom:4px">' + emoji + ' ' + title + '</div>' +
      '<div style="color:var(--text);line-height:1.65">' + body + '</div>' +
    '</div>';
  }

  var html = '';

  // Overview
  html += section('📊', 'OVERVIEW',
    'Trade verdict: <b style="color:' + verdictCol + ';font-size:1.1em">' + verdict + '</b> &nbsp;·&nbsp; Score: <b>' + score.toFixed(0) + '/100</b><br>' +
    '<span style="color:var(--muted);font-size:.85rem">' + (p.display_name||p.name) + ' · ' + (pos||'Unknown pos') + ' · ' + p.team + ' · ' + fmtPrice(price) + '</span>');

  // Form & scoring
  var formBody = 'Season avg <b>' + avg.toFixed(1) + '</b> pts · L3 avg <b>' + l3avg.toFixed(1) + '</b> pts · L5 avg <b>' + l5avg.toFixed(1) + '</b> pts.<br>' +
    'Form is <b>' + formTrend + '</b>. ' + beContext + '.<br>' +
    'Recent scores: <b>' + recentScores.join(', ') + '</b>.' +
    (fr != null ? '<br>Form rating <b style="color:' + ratingColor(fr) + '">' + fr + '/100</b> — ' + (fr >= 70 ? 'scoring well above price expectations.' : fr >= 45 ? 'roughly matching price value.' : 'underperforming his price tag.') : '');
  html += section('📈', 'FORM & SCORING', formBody);

  // Ceiling & floor
  html += section('🎯', 'CEILING & FLOOR',
    'Best score: <b>' + best + '</b> (' + ceilingLabel + ') · Worst: <b>' + worst + '</b> (' + floorLabel + ').<br>' +
    (cs != null ? 'Consistency <b style="color:' + ratingColor(cs) + '">' + cs + '/100</b> — ' + csLabel + '. ' + (cs < 40 ? 'High variance means he could be a match-winner one week and a liability the next.' : cs >= 70 ? 'You can count on him for a reliable score most weeks.' : 'A reasonable option but he does have some big swings.') : 'Consistency data unavailable.') +
    '<br>Brownlow votes: <b>' + totalVotes + '</b> this season (' + (totalVotes >= 10 ? 'strong vote-getter' : totalVotes >= 5 ? 'picks up votes regularly' : 'limited Brownlow impact') + ').');

  // Fixture
  if (fixtureLines.length) {
    html += section('🏟️', 'UPCOMING FIXTURE',
      'Fixture is <b>' + fixtureSummary + '</b> (overall rating ' + (fixRating||'?').toFixed(1) + ').<br>' +
      fixtureLines.join('<br>'));
  } else {
    html += section('🏟️', 'UPCOMING FIXTURE', 'No fixture data loaded. Add fixture.txt to see upcoming projections.');
  }

  // Price analysis
  var priceBody = price ? 'Current price <b>' + fmtPrice(price) + '</b>. Break-even score: <b>' + (beStr||'?') + '</b> pts.<br>' : 'Price data unavailable.<br>';
  if (priceChange != null) {
    const pcStr = priceChange >= 0 ? '<b style="color:var(--green)">+' + fmtPrice(priceChange) + '</b>' : '<b style="color:var(--red)">−' + fmtPrice(Math.abs(priceChange)) + '</b>';
    priceBody += 'Season price change: ' + pcStr + '. Recent trend: <b>' + (priceTrend||'unknown') + '</b>.<br>';
    priceBody += priceTrend === 'rising' ? 'Price is climbing — buy now before he gets more expensive.' :
      priceTrend === 'falling' ? 'Price is dropping — if you\'re buying, wait another round for a cheaper entry.' :
      'Price is stable — no urgency either way from a price perspective.';
  }
  html += section('💰', 'PRICE ANALYSIS', priceBody);

  // Trade verdict
  var verdictBody = score >= 65
    ? 'Strong candidate to trade in. Good form, ' + (fixtureSummary !== 'very tough' ? 'favourable fixture,' : '') + ' and scoring above his break-even. Act sooner rather than later if his price is rising.'
    : score >= 50
    ? 'Worth holding if you have him. Not a must-trade-in right now — monitor his form over the next 1-2 rounds before committing.'
    : score >= 35
    ? 'Consider offloading. His form or value is declining. There may be better uses of the cash depending on your squad needs.'
    : 'Strong sell signal. Poor form, ' + (fixtureSummary === 'very tough' ? 'tough fixture,' : '') + ' and falling price make him a liability to hold. Move on if you can.';
  html += section('🔄', 'TRADE VERDICT', verdictBody);

  // Better options
  if (alts.length) {
    html += section('🏆', 'BETTER OPTIONS AT SIMILAR PRICE',
      'These ' + pos + 's score higher on average within $120K of ' + (p.display_name||p.name) + ':<br>' + alts.join('<br>'));
  } else {
    html += section('🏆', 'ALTERNATIVES', 'No clearly superior options found at a similar price in this dataset. He may be among the best value at his price point for his position.');
  }

  reportDiv.innerHTML = '<div style="border-bottom:1px solid var(--border);margin-bottom:14px;padding-bottom:10px;font-size:.72rem;color:var(--muted)">Generated from season data — R' + Math.min.apply(null,h.map(function(x){return x.round;})) + ' to R' + Math.max.apply(null,h.map(function(x){return x.round;})) + '</div>' + html;
  btn.textContent = '\u{1F504} Regenerate Report'; btn.disabled = false;
}

// ── Matchup Difficulty ────────────────────────────────────────────────────────
var diffSubMode = 'historical';
function showDiffSub(mode) {
  diffSubMode = mode;
  document.getElementById('diffHistoricalSection').style.display = mode === 'historical' ? 'block' : 'none';
  document.getElementById('diffUpcomingSection').style.display   = mode === 'upcoming'   ? 'block' : 'none';
  document.getElementById('diffSubHistorical').classList.toggle('active', mode === 'historical');
  document.getElementById('diffSubUpcoming').classList.toggle('active', mode === 'upcoming');
}

// ── Matchup Difficulty: one shared colour scale for Historical + Upcoming ─────
// Gradient: green (easy, score>108) → yellow-green → yellow → orange → red (hard, score<92)
function gradientColor(score, alpha, lo, hi) {
  alpha = alpha || 1;
  lo = lo != null ? lo : 85; hi = hi != null ? hi : 115;
  // Map score to 0-1 across the ACTUAL spread being displayed, so colour differences
  // between teams stay visible even when ratings cluster in a narrow band.
  const t = Math.max(0, Math.min(1, (score - lo) / Math.max(1e-6, hi - lo)));
  var r, g, b;
  if (t >= 0.67) {
    const u = (t - 0.67) / 0.33;
    r = Math.round(20  + u * 10);
    g = Math.round(200 + u * 11);
    b = Math.round(100 + u * 53);
  } else if (t >= 0.33) {
    const u = (t - 0.33) / 0.34;
    r = Math.round(240 - u * 220);
    g = Math.round(180 + u * 31);
    b = Math.round(30  + u * 70);
  } else {
    const u = t / 0.33;
    r = Math.round(220 - u * 20);
    g = Math.round(60  + u * 120);
    b = Math.round(20  + u * 10);
  }
  return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
}
function gradientBg(score, lo, hi) { return gradientColor(score, 0.17, lo, hi); }
function gradientBorder(score, lo, hi) { return gradientColor(score, 0.65, lo, hi); }
function gradientText(score, lo, hi) { return gradientColor(score, 1, lo, hi); }
function ratingDomain(values) {
  var lo = Math.min.apply(null, values), hi = Math.max.apply(null, values);
  if (hi - lo < 6) { const mid = (hi + lo) / 2; lo = mid - 3; hi = mid + 3; }
  return [lo, hi];
}
function matchupCalloutHtml(best, worst, field) {
  return '<div class="matchup-callout">' +
    '<div class="callout-chip good"><span class="callout-eyebrow">&#9650; Best matchup</span><b>' + best.team + '</b><span class="callout-sub">' + best[field] + ' rating</span></div>' +
    '<div class="callout-chip bad"><span class="callout-eyebrow">&#9660; Toughest matchup</span><b>' + worst.team + '</b><span class="callout-sub">' + worst[field] + ' rating</span></div>' +
  '</div>';
}

(function() {
  var ALL_DIFFS = Object.assign({ 'Overall': OVERALL_DIFF }, POS_DIFF);
  const tabs = document.getElementById('diffTabs');
  const content = document.getElementById('diffContent');
  var activeTab = 'Overall';

  function renderDiffTab(key) {
    activeTab = key;
    tabs.querySelectorAll('.diff-tab').forEach(function(t) { t.classList.toggle('active', t.dataset.key === key); });
    const data = ALL_DIFFS[key] || [];
    const calloutEl = document.getElementById('diffCallout');
    if (calloutEl) calloutEl.innerHTML = data.length >= 2 ? matchupCalloutHtml(data[0], data[data.length-1], 'rating') : '';
    if (!data.length) { content.innerHTML = '<div style="color:var(--muted);padding:20px">No data for this position yet.</div>'; return; }
    content.innerHTML = '';
    const grid = document.createElement('div'); grid.className = 'diff-grid';
    const domain = ratingDomain(data.map(function(d) { return d.rating; }));
    data.forEach(function(d, i) {
      const col    = gradientText(d.rating, domain[0], domain[1]);
      const bgCol  = gradientBg(d.rating, domain[0], domain[1]);
      const bdCol  = gradientBorder(d.rating, domain[0], domain[1]);
      const barCol = gradientColor(d.rating, 0.85, domain[0], domain[1]);
      const barW   = Math.min(100, Math.max(0, ((d.rating - 80) / 40) * 100));
      const card = document.createElement('div');
      card.className = 'diff-card';
      card.style.cssText = 'background:' + bgCol + ';border-color:' + bdCol + ';animation-delay:' + (i * 0.03) + 's';
      card.innerHTML =
        '<div class="diff-team" style="color:' + col + '">' + d.team + '</div>' +
        '<div class="diff-meta">' + d.games + ' player-games · league avg: ' + AFL_AVG.toFixed(1) + ' pts</div>' +
        '<div style="display:flex;justify-content:space-between;align-items:flex-end">' +
          '<div><div style="font-size:.62rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em">Avg pts conceded</div>' +
          '<div class="diff-rating-num" style="color:' + col + '">' + d.avg_conceded + ' pts</div></div>' +
          '<div style="text-align:right"><div style="font-size:.62rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em">Difficulty rating</div>' +
          '<div class="diff-rating-num" style="color:' + col + '">' + d.rating + '</div></div>' +
        '</div>' +
        '<div style="font-size:.65rem;color:var(--muted);margin-top:4px">' +
          (d.rating > 100 ? '▲ Players score ' + (d.rating - 100).toFixed(1) + '% above their avg here' :
           d.rating < 100 ? '▼ Players score ' + (100 - d.rating).toFixed(1) + '% below their avg here' :
           'Exactly league average difficulty') +
        '</div>' +
        '<div class="rating-bar-wrap" style="margin-top:6px"><div class="rating-bar" style="width:' + barW + '%;background:' + barCol + '"></div></div>';
      grid.appendChild(card);
    });
    content.appendChild(grid);
  }

  Object.keys(ALL_DIFFS).forEach(function(key) {
    const btn = document.createElement('button');
    btn.className = 'diff-tab' + (key==='Overall'?' active':'');
    btn.textContent = key; btn.dataset.key = key;
    btn.onclick = function() { renderDiffTab(key); };
    tabs.appendChild(btn);
  });
  renderDiffTab('Overall');
})();

// ── Upcoming Fixture Difficulty — shares the Historical card system exactly ───
(function() {
  const ALL_POS = ['Overall', 'DEF', 'MID', 'RUC', 'FWD'];
  const tabs = document.getElementById('upcomingPosTabs');
  const content = document.getElementById('upcomingContent');

  function getAflAvg(posKey) {
    if (posKey === 'Overall') return UPCOMING_AFL_AVG;
    return UPCOMING_AFL_AVG_POS && UPCOMING_AFL_AVG_POS[posKey] != null ? UPCOMING_AFL_AVG_POS[posKey] : null;
  }

  function renderUpcomingTab(posKey) {
    tabs.querySelectorAll('.diff-tab').forEach(function(t) { t.classList.toggle('active', t.dataset.key === posKey); });

    if (!UPCOMING_DIFF || !UPCOMING_DIFF.length) {
      content.innerHTML = '<div style="color:var(--muted);padding:20px">No upcoming fixture data. Make sure fixture.txt is present.</div>';
      return;
    }

    const sorted = UPCOMING_DIFF.slice().sort(function(a, b) {
      const sa = posKey === 'Overall' ? a.upcoming_score : (a.upcoming_pos[posKey] || 100);
      const sb = posKey === 'Overall' ? b.upcoming_score : (b.upcoming_pos[posKey] || 100);
      return sb - sa;
    });

    const scoreOf = function(d) { return posKey === 'Overall' ? d.upcoming_score : (d.upcoming_pos[posKey] || 100); };

    const upCalloutEl = document.getElementById('upcomingCallout');
    if (upCalloutEl) {
      if (sorted.length >= 2) {
        const bestD = sorted[0], worstD = sorted[sorted.length - 1];
        upCalloutEl.innerHTML = matchupCalloutHtml(
          { team: bestD.team, rating: scoreOf(bestD).toFixed(1) },
          { team: worstD.team, rating: scoreOf(worstD).toFixed(1) },
          'rating'
        );
      } else { upCalloutEl.innerHTML = ''; }
    }

    const aflAvg = getAflAvg(posKey);
    content.innerHTML = '';
    const grid = document.createElement('div');
    grid.className = 'upcoming-grid';
    const domain = ratingDomain(sorted.map(scoreOf));

    sorted.forEach(function(d, i) {
      const score = scoreOf(d);
      const predAvg = posKey === 'Overall'
        ? d.predicted_avg
        : (d.predicted_avg_pos && d.predicted_avg_pos[posKey] != null ? d.predicted_avg_pos[posKey] : null);

      const col    = gradientText(score, domain[0], domain[1]);
      const bgCol  = gradientBg(score, domain[0], domain[1]);
      const bdCol  = gradientBorder(score, domain[0], domain[1]);
      const barW   = Math.min(100, Math.max(0, ((score - 80) / 40) * 100));
      const barCol = gradientColor(score, 0.85, domain[0], domain[1]);
      const detailId = 'updet_' + i + '_' + posKey.replace(/[^a-z]/gi,'');

      let descriptor = 'Average upcoming schedule';
      if (score > 100) descriptor = '▲ Players score ' + (score - 100).toFixed(1) + '% above their avg';
      else if (score < 100) descriptor = '▼ Players score ' + (100 - score).toFixed(1) + '% below their avg';

      var gamesHtml = '';
      (d.games || []).forEach(function(g, gi) {
        const gScore = posKey === 'Overall' ? g.overall : (g.pos[posKey] || 100);
        const gPred  = posKey === 'Overall' ? g.predicted_avg : (g.predicted_pos && g.predicted_pos[posKey] != null ? g.predicted_pos[posKey] : null);
        const gCol   = gradientText(gScore);
        const rLabel = g.round === 0 ? 'Open' : 'R' + g.round;
        const proximity = gi === 0 ? ' (next)' : '';
        const predTxt = gPred != null ? ' • ~' + gPred.toFixed(1) + ' pts' : '';
        gamesHtml += '<div class="upcoming-game-row">' +
          '<span>' + rLabel + proximity + ': vs ' + g.opponent + predTxt + '</span>' +
          '<span style="color:' + gCol + ';font-weight:700">' + gScore.toFixed(1) + '</span>' +
        '</div>';
      });

      const numGames = (d.games || []).length;
      const avgLine = aflAvg != null ? 'league avg: ' + aflAvg.toFixed(1) + ' pts' : numGames + ' upcoming games';

      const card = document.createElement('div');
      card.className = 'upcoming-card';
      card.style.cssText = 'background:' + bgCol + ';border-color:' + bdCol + ';animation-delay:' + (i * 0.03) + 's';
      card.innerHTML =
        '<div class="diff-team" style="color:' + col + '">' + d.team + '</div>' +
        '<div class="diff-meta">' + numGames + ' upcoming · ' + avgLine + '</div>' +
        '<div style="display:flex;justify-content:space-between;align-items:flex-end">' +
          (predAvg != null
            ? '<div><div style="font-size:.58rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em">Pred avg pts</div>' +
              '<div class="diff-rating-num" style="color:' + col + '">' + predAvg.toFixed(1) + '</div></div>'
            : '<div></div>') +
          '<div style="text-align:right"><div style="font-size:.58rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em">Rating</div>' +
          '<div class="diff-rating-num" style="color:' + col + '">' + score.toFixed(1) + '</div></div>' +
        '</div>' +
        '<div style="font-size:.62rem;color:var(--muted);margin-top:3px">' + descriptor + '</div>' +
        '<div class="rating-bar-wrap" style="margin-top:5px"><div class="rating-bar" style="width:' + barW + '%;background:' + barCol + '"></div></div>' +
        '<div class="expand-toggle" onclick="toggleUpcomingGames(\'' + detailId + '\')">▼ Show games</div>' +
        '<div class="upcoming-games-list" id="' + detailId + '">' + gamesHtml + '</div>';

      grid.appendChild(card);
    });
    content.appendChild(grid);
  }

  ALL_POS.forEach(function(key) {
    const btn = document.createElement('button');
    btn.className = 'diff-tab' + (key==='Overall'?' active':'');
    btn.textContent = key; btn.dataset.key = key;
    btn.onclick = function() { renderUpcomingTab(key); };
    tabs.appendChild(btn);
  });
  renderUpcomingTab('Overall');
})();

function toggleUpcomingGames(detailId) {
  const el = document.getElementById(detailId); if (!el) return;
  el.classList.toggle('open');
  const toggle = el.previousElementSibling;
  if (toggle) toggle.textContent = el.classList.contains('open') ? '\u25b2 Hide games' : '\u25bc Show games';
}

// ── Vote Race ─────────────────────────────────────────────────────────────────
function initRace() {
  const slider = document.getElementById('raceSlider');
  slider.max = LB_HISTORY.length - 1;
  slider.value = raceFrame;
  renderRaceFrame(raceFrame);
}
function renderRaceFrame(i) {
  raceFrame = i;
  const frame = LB_HISTORY[i];
  document.getElementById('raceLabel').textContent = frame.round === 0 ? 'Opening Round' : 'After Round ' + frame.round;
  document.getElementById('raceSlider').value = i;
  var prevPos = {};
  // Use FULL rankings list for position tracking (prevents "ghost jump" bug when
  // a player was outside top-25 in a prior round but had accumulated votes).
  if (i > 0) LB_HISTORY[i-1].rankings.forEach(function(e, idx) { prevPos[e.key] = idx + 1; });
  const tbody = document.getElementById('raceBody'); tbody.innerHTML = '';
  // Only display top 25 but position numbers reflect full ranking
  frame.rankings.slice(0, 25).forEach(function(entry, idx) {
    const pos = idx + 1;
    const pc = pos===1?'p1':pos===2?'p2':pos===3?'p3':'';
    const prev = prevPos[entry.key];
    var moveHtml = '<span class="move-same">\u2014</span>';
    if (prev !== undefined) {
      const diff = prev - pos;
      if (diff > 0)      moveHtml = '<span class="move-up">\u25b2' + diff + '</span>';
      else if (diff < 0) moveHtml = '<span class="move-down">\u25bc' + Math.abs(diff) + '</span>';
    }
    const dn = getDisplayName(entry.player, entry.team);
    const tr = document.createElement('tr');
    tr.innerHTML =
      '<td class="pos-num ' + pc + '">' + pos + '</td>' +
      '<td><span class="player-link" onclick="searchAndShowPlayer(\'' + entry.key.replace(/'/g,"\\'") + '\')">' + dn + '</span></td>' +
      '<td>' + teamTagHtml(entry.team) + '</td>' +
      '<td class="ta-r">' + moveHtml + '</td>' +
      '<td class="ta-r" style="color:var(--muted)">' + (entry.round_price != null ? fmtPrice(entry.round_price) : '\u2014') + '</td>' +
      '<td class="ta-r" style="font-family:\'Barlow Condensed\',sans-serif;font-weight:700">' + (entry.round_score != null ? entry.round_score : '\u2014') + '</td>' +
      '<td class="ta-r" style="color:var(--accent);font-weight:700">' + (entry.round_votes > 0 ? entry.round_votes : '\u2014') + '</td>' +
      '<td class="ta-r votes-hl">' + entry.votes + '</td>';
    tbody.appendChild(tr);
  });
}
function raceStep(dir) { renderRaceFrame(Math.max(0, Math.min(LB_HISTORY.length - 1, raceFrame + dir))); }
function goToFrame(i) { renderRaceFrame(+i); }
function togglePlay() {
  const btn = document.getElementById('playBtn');
  if (raceTimer) { clearInterval(raceTimer); raceTimer = null; btn.textContent = '\u25b6 Play'; btn.classList.remove('playing'); return; }
  btn.textContent = '\u23f8 Pause'; btn.classList.add('playing');
  if (raceFrame >= LB_HISTORY.length - 1) raceFrame = 0;
  raceTimer = setInterval(function() {
    if (raceFrame >= LB_HISTORY.length - 1) {
      clearInterval(raceTimer); raceTimer = null;
      btn.textContent = '\u25b6 Play'; btn.classList.remove('playing'); return;
    }
    renderRaceFrame(raceFrame + 1);
  }, 1400);
}

// ── Trading Centre ─────────────────────────────────────────────────────────────
const MAX_TRADE = 3;
function getP(key) { return PLAYERS_DATA.find(function(x){return x.key === key;}); }
function getPrice(key) { const p = getP(key); return p ? p.current_price : null; }

function playerQuickStats(key) {
  const p = getP(key); if (!p) return null;
  const h = p.history;
  if (!h.length) return null;
  const scores = h.map(function(x){return x.score;});
  const n = scores.length;
  const avg  = n ? +(scores.reduce(function(a,b){return a+b;},0)/n).toFixed(1) : 0;
  const last3 = +(scores.slice(-3).reduce(function(a,b){return a+b;},0)/Math.min(3,n)).toFixed(1);
  return { avg, last3, formRating: p.form_rating, positions: p.positions || [] };
}

function tradeItemHtml(key, listKey) {
  const pd = getP(key);
  const dn = pd ? (pd.display_name || getDisplayName(pd.name, pd.team)) : key;
  const teamTxt = pd ? pd.team : '';
  const price = getPrice(key);
  const qs = playerQuickStats(key);
  const safeKey = key.replace(/'/g,"\\'");

  const posHtml = qs && qs.positions.length ? posPills(qs.positions) : '';
  let statsHtml = '';
  if (qs) {
    const frCol = qs.formRating != null ? ratingColor(qs.formRating) : 'var(--muted)';
    statsHtml =
      '<span class="mini-stat"><b>' + qs.avg + '</b> avg</span>' +
      '<span class="mini-stat" style="color:var(--muted)">·</span>' +
      '<span class="mini-stat"><b>' + qs.last3 + '</b> L3</span>' +
      (qs.formRating != null
        ? '<span class="mini-stat" style="color:var(--muted)">·</span>' +
          '<span class="mini-stat"><b style="color:' + frCol + '">' + qs.formRating + '</b> form</span>'
        : '');
  }

  return '<div class="trade-item-name">' + dn + posHtml + '</div>' +
    '<div class="trade-item-sub">' +
      teamTagHtml(teamTxt) +
      '<span class="trade-item-price">' + fmtPrice(price) + '</span>' +
      (statsHtml ? '<span style="margin-left:2px">' + statsHtml + '</span>' : '') +
    '</div>';
}

function renderTradeLists() {
  renderTradeList('tradeIn', 'tradeInList');
  renderTradeList('tradeOut', 'tradeOutList');
  renderStarredList();
  updateSummary();
  document.getElementById('budgetInput').value = lsGet('budget', 0) || '';
}

function renderTradeList(key, listId) {
  const items = lsGet(key, []);
  const ul = document.getElementById(listId); ul.innerHTML = '';
  document.getElementById(key==='tradeIn'?'tradeInBadge':'tradeOutBadge').textContent = items.length + '/' + MAX_TRADE;
  if (!items.length) { ul.innerHTML = '<li style="color:var(--muted);font-size:.82rem;padding:7px 4px">None yet — search below to add</li>'; return; }
  items.forEach(function(pkey) {
    const safeKey = pkey.replace(/'/g,"\\'");
    const li = document.createElement('li'); li.className = 'trade-item';
    li.innerHTML =
      '<div class="trade-item-body">' + tradeItemHtml(pkey, key) + '</div>' +
      '<button class="trade-item-remove" onclick="removeFromList(\'' + key + '\',\'' + safeKey + '\')" title="Remove">&#10005;</button>';
    ul.appendChild(li);
  });
}

function renderStarredList() {
  const starred = lsGet('starred', []);
  const container = document.getElementById('starredList'); container.innerHTML = '';
  if (!starred.length) {
    container.innerHTML = '<div style="color:var(--muted);font-size:.82rem;padding:7px 0">No bookmarks yet</div>';
    return;
  }
  starred.forEach(function(pkey) {
    const pd = getP(pkey);
    const dn = pd ? (pd.display_name || getDisplayName(pd.name, pd.team)) : pkey;
    const teamTxt = pd ? pd.team : '';
    const price = getPrice(pkey);
    const qs = playerQuickStats(pkey);
    const posHtml = qs && qs.positions.length ? posPills(qs.positions) : '';
    const safeKey = pkey.replace(/'/g,"\\'");
    const div = document.createElement('div'); div.className = 'bm-item';
    div.innerHTML =
      '<div style="flex:1;min-width:0">' +
        '<div class="bm-name" onclick="searchAndShowPlayer(\'' + safeKey + '\')">' + dn + ' ' + posHtml + '</div>' +
        '<div class="bm-sub">' + teamTxt + (qs ? ' · avg ' + qs.avg + ' · L3 ' + qs.last3 : '') + '</div>' +
      '</div>' +
      '<span class="bm-price">' + fmtPrice(price) + '</span>' +
      '<div class="bm-actions">' +
        '<button class="pill-btn pill-in" onclick="addToList(\'tradeIn\',\'' + safeKey + '\')">+In</button>' +
        '<button class="pill-btn pill-out" onclick="addToList(\'tradeOut\',\'' + safeKey + '\')">+Out</button>' +
        '<button class="pill-btn pill-rm" onclick="removeBookmark(\'' + safeKey + '\')" title="Remove bookmark">&#10005;</button>' +
      '</div>';
    container.appendChild(div);
  });
}

function removeBookmark(key) {
  lsSet('starred', lsGet('starred',[]).filter(function(x){return x !== key;}));
  renderStarredList();
}

function validateTrades() {
  const inItems = lsGet('tradeIn',[]), outItems = lsGet('tradeOut',[]);
  const inErr = document.getElementById('tradeInError'), outErr = document.getElementById('tradeOutError');
  const overlap = inItems.filter(function(k){return outItems.includes(k);});
  if (overlap.length) {
    const names = overlap.map(function(k){var p=getP(k);return p?(p.display_name||getDisplayName(p.name,p.team)):k;});
    inErr.textContent = '\u26a0 Same player in both lists: ' + names.join(', ');
    outErr.textContent = '\u26a0 Same player in both lists: ' + names.join(', ');
  } else {
    inErr.textContent = '';
    if (inItems.length && outItems.length && inItems.length !== outItems.length)
      outErr.textContent = '\u26a0 Trade In (' + inItems.length + ') and Trade Out (' + outItems.length + ') must be equal';
    else outErr.textContent = '';
  }
}

function addToList(key, pkey) {
  const other = key === 'tradeIn' ? 'tradeOut' : 'tradeIn';
  const otherItems = lsGet(other, []);
  if (otherItems.includes(pkey)) { alert('This player is in your ' + (other==='tradeIn'?'Trade In':'Trade Out') + ' list. Remove them first.'); return; }
  var items = lsGet(key, []);
  if (items.length >= MAX_TRADE) { alert('Maximum ' + MAX_TRADE + ' players per side.'); return; }
  if (!items.includes(pkey)) { items.push(pkey); lsSet(key, items); }
  renderTradeLists();
}

function removeFromList(key, pkey) {
  lsSet(key, lsGet(key,[]).filter(function(x){return x !== pkey;}));
  renderTradeLists();
}

function saveBudget() {
  lsSet('budget', parseFloat(document.getElementById('budgetInput').value) || 0);
}

function getPlayerFixtureScore(key) {
  const p = getP(key); if (!p || !UPCOMING_DIFF) return null;
  const teamFix = UPCOMING_DIFF.find(function(d){ return d.team === p.team; });
  if (!teamFix) return null;
  const pos = p.positions && p.positions.length ? p.positions[0] : null;
  return pos ? (teamFix.upcoming_pos[pos] || teamFix.upcoming_score) : teamFix.upcoming_score;
}

// More centre bounce attendances generally means more midfield time and more scoring
// opportunity, so a player whose CBA% has been trending UP recently is a genuine
// leading indicator for their next score — not just noise. Heavily recency-weighted
// (last 3 rounds vs their whole-season CBA average) since a role change shows up in
// CBA% before it shows up in the score itself. Capped at +/-8% so it nudges the
// projection rather than dominating it — it's a secondary signal, not the main one.
function cbaTrendMultiplier(p) {
  if (!p.cba_history) return 1.0;
  const rounds = Object.keys(p.cba_history).map(Number).sort(function(a,b){return a-b;});
  if (rounds.length < 2) return 1.0;
  const values = rounds.map(function(r){ return p.cba_history[r]; });
  const recent = values.slice(-3);
  const recentAvg = recent.reduce(function(a,b){return a+b;},0) / recent.length;
  const seasonAvg = p.cba_avg != null ? p.cba_avg : (values.reduce(function(a,b){return a+b;},0) / values.length);
  if (!seasonAvg) return 1.0;
  const ratio = recentAvg / seasonAvg;
  return Math.max(0.92, Math.min(1.08, 1 + (ratio - 1) * 0.4));
}

// Adjusts each past score for how hard/easy that round's opponent was, so a player's
// "form" isn't just an artifact of a soft or brutal run of fixtures. 100 = league avg
// difficulty; a score against a 110-rated (easy) opponent is scaled down, and a score
// against a 90-rated (hard) opponent is scaled up, before it feeds into the projection.
function opponentAdjustedScores(p) {
  const pos = p.positions && p.positions.length ? p.positions[0] : null;
  const diffList = (pos && POS_DIFF && POS_DIFF[pos] && POS_DIFF[pos].length) ? POS_DIFF[pos] : OVERALL_DIFF;
  const ratingByTeam = {};
  (diffList || []).forEach(function(d) { ratingByTeam[d.team] = d.rating; });
  return p.history.map(function(h) {
    const oppRating = h.opponent ? ratingByTeam[h.opponent] : null;
    return (oppRating && oppRating > 0) ? h.score * (100 / oppRating) : h.score;
  });
}

function calcProjectedScore(key) {
  // Weighted projection: 50% L3 avg, 30% L5 avg, 20% season avg (each opponent-adjusted,
  // see opponentAdjustedScores), then a further adjustment for the specific upcoming fixture.
  const p = getP(key); if (!p) return null;
  if (INJURED_SET && INJURED_SET.has(p.name)) return null; // injured = no projection
  const scores = opponentAdjustedScores(p);
  const n = scores.length; if (!n) return null;
  const seasonAvg = scores.reduce(function(a,b){return a+b;},0)/n;
  const l3 = scores.slice(-3).reduce(function(a,b){return a+b;},0)/Math.min(3,n);
  const l5 = scores.slice(-5).reduce(function(a,b){return a+b;},0)/Math.min(5,n);
  // Weight: recent form matters most
  const baseProj = l3*0.50 + l5*0.30 + seasonAvg*0.20;
  // Fixture adjustment: if rating is 110 → multiply by 1.10; if 90 → multiply by 0.90
  const fix = getPlayerFixtureScore(key);
  const fixMult = fix != null ? (0.4 + fix/166.7) : 1.0; // dampened: 90→0.94, 100→1.0, 110→1.06
  return Math.round(baseProj * fixMult * cbaTrendMultiplier(p));
}

// Magic number: $ per point above/below breakeven. Calibrated against this dataset's
// own pre_price/post_price history — clusters around 950 for $300K+ players and
// ~1500 for sub-$300K players (cheap/rookie prices swing harder per point).
function priceChangeMagicNumber(price) {
  return (price != null && price < 300000) ? 1500 : 950;
}
// Empirically-fit breakeven model. A player's TRUE breakeven each round can be backed
// out of real data: BE = score - (post_price - pre_price) / magicNumber. Doing that
// for every pre/post price transition in this dataset (8,400+ player-rounds) and then
// regressing that empirical BE against candidate predictors found price/10490 alone
// gets to ~17.5pts RMSE, and blending in recent form roughly halves the error again:
// weighting the last 3 scores 1:2:3 (most recent heaviest) and combining with price
// via ordinary least squares lands at BE = 2.51*(price/10490) - 1.32*weighted3 + 2.58,
// RMSE ~5.4pts — far tighter than comparing a projected score to a plain rolling
// average, which is what caused the old model to predict FALLING prices for players
// on a hot streak (their season/L5-blended projection always looked low next to their
// own red-hot recent average, even though real breakeven eases for in-form players).
function weighted3(scores) {
  const w = scores.slice(-3);
  if (!w.length) return 0;
  if (w.length < 3) return w.reduce(function(a,b){return a+b;},0) / w.length;
  return (w[0]*1 + w[1]*2 + w[2]*3) / 6;
}
function pearsonCorrelation(xs, ys) {
  const n = xs.length;
  if (n < 2) return null;
  const mx = xs.reduce(function(a,b){return a+b;},0)/n, my = ys.reduce(function(a,b){return a+b;},0)/n;
  var num=0, dx2=0, dy2=0;
  for (var i=0;i<n;i++) {
    const dx=xs[i]-mx, dy=ys[i]-my;
    num += dx*dy; dx2 += dx*dx; dy2 += dy*dy;
  }
  const denom = Math.sqrt(dx2*dy2);
  return denom ? num/denom : null;
}
function breakeven(price, scores) {
  if (price == null || !scores || !scores.length) return null;
  return Math.round(BE_COEF_PRICE*(price/10490) + BE_COEF_FORM*weighted3(scores) + BE_COEF_INTERCEPT);
}
function playerBreakeven(p) {
  if (!p || !p.current_price || !p.history || !p.history.length) return null;
  return breakeven(p.current_price, p.history.map(function(h){return h.score;}));
}
// Where a player ranks league-wide (every player in the dataset, not just their
// position) for a given stat. valueFn returns null to exclude a player from the
// comparison entirely (e.g. not enough games played).
function leagueRank(playerKey, valueFn, lowerBetter) {
  const rows = [];
  PLAYERS_DATA.forEach(function(pp){
    const v = valueFn(pp);
    if (v == null || isNaN(v)) return;
    rows.push({key: pp.key, v: v});
  });
  rows.sort(function(a,b){ return lowerBetter ? a.v-b.v : b.v-a.v; });
  const idx = rows.findIndex(function(x){ return x.key === playerKey; });
  if (idx < 0) return null;
  return {rank: idx+1, total: rows.length};
}
function rankTagHtml(r) {
  return r ? '<div class="stat-rank" title="#' + r.rank + ' of ' + r.total + ' league-wide">#' + r.rank + '</div>' : '';
}
// Score to feed into predictedPriceChange — deliberately NOT calcProjectedScore().
// calcProjectedScore blends in season average, which is right for a general "how
// good are they" expectation but wrong for a single round's price move: recent form,
// fixture-adjusted, is what actually drives next round's score for pricing purposes.
function priceProjectedScore(key) {
  const p = getP(key); if (!p || !p.history || !p.history.length) return null;
  if (INJURED_SET && INJURED_SET.has(p.name)) return null;
  const recent = p.history.slice(-3).map(function(h){return h.score;});
  const rollAvg = recent.reduce(function(a,b){return a+b;},0) / recent.length;
  const fix = getPlayerFixtureScore(key);
  const fixMult = fix != null ? (0.4 + fix/166.7) : 1.0;
  return rollAvg * fixMult;
}
function predictedPriceChange(p, projectedScore) {
  if (projectedScore == null || !p.history || !p.history.length) return null;
  const be = playerBreakeven(p);
  if (be == null) return null;
  const magic = priceChangeMagicNumber(p.current_price);
  var change = Math.round(magic * (projectedScore - be));
  if (p.current_price) { // real single-round moves essentially never exceed ~15% of price
    const cap = Math.round(p.current_price * 0.15);
    change = Math.max(-cap, Math.min(cap, change));
  }
  return change;
}

function getPlayerPriceTrend(key) {
  // Returns 'rising', 'falling', 'flat', or null
  const p = getP(key); if (!p) return null;
  const prices = p.history.map(function(h){return h.post_price;}).filter(function(x){return x!=null;});
  if (prices.length < 2) return null;
  const recent = prices.slice(-3);
  const first = recent[0], last = recent[recent.length-1];
  const diff = last - first;
  if (diff > 10000) return 'rising';
  if (diff < -10000) return 'falling';
  return 'flat';
}

function calcSideStats(keys) {
  var avgSum=0, l3Sum=0, l5Sum=0, frSum=0, frCount=0, csSum=0, csCount=0,
      fixSum=0, fixCount=0, votes=0, count=0, risingCount=0, fallingCount=0;
  keys.forEach(function(key) {
    const p = getP(key); if (!p) return;
    const h = p.history;
    const scores = h.map(function(x){return x.score;});
    const n = scores.length; if (!n) return;
    avgSum += scores.reduce(function(a,b){return a+b;},0)/n;
    l3Sum  += scores.slice(-3).reduce(function(a,b){return a+b;},0)/Math.min(3,n);
    l5Sum  += scores.slice(-5).reduce(function(a,b){return a+b;},0)/Math.min(5,n);
    votes  += h.map(function(x){return x.votes;}).reduce(function(a,b){return a+b;},0);
    if (p.form_rating  != null) { frSum += p.form_rating;  frCount++; }
    if (p.consistency  != null) { csSum += p.consistency;  csCount++; }
    const fix = getPlayerFixtureScore(key);
    if (fix != null) { fixSum += fix; fixCount++; }
    const trend = getPlayerPriceTrend(key);
    if (trend === 'rising')  risingCount++;
    if (trend === 'falling') fallingCount++;
    count++;
  });
  if (!count) return null;
  const avgFix = fixCount ? +(fixSum/fixCount).toFixed(1) : null;
  const fixLabel = avgFix == null ? null :
    avgFix >= 105 ? '🟢 Easy' : avgFix <= 95 ? '🔴 Hard' : '🟡 Avg';
  const trendLabel = risingCount > fallingCount ? '↑ Rising' :
    fallingCount > risingCount ? '↓ Falling' : '→ Mixed';
  const trendCol = risingCount > fallingCount ? 'var(--green)' :
    fallingCount > risingCount ? 'var(--red)' : 'var(--muted)';
  return {
    avg:  +(avgSum).toFixed(1), l3: +(l3Sum).toFixed(1), l5: +(l5Sum).toFixed(1),
    fr:   frCount ? Math.round(frSum/frCount) : null,
    cons: csCount ? Math.round(csSum/csCount) : null,
    fix: avgFix, fixLabel, votes,
    trendLabel, trendCol
  };
}

function updateSummary() {
  const inP = lsGet('tradeIn',[]), outP = lsGet('tradeOut',[]);
  const budgetK = parseFloat(document.getElementById('budgetInput').value) || 0;
  const budgetDollars = budgetK * 1000;
  const inCost = inP.reduce(function(s,k){return s+(getPrice(k)||0);},0);
  const outVal = outP.reduce(function(s,k){return s+(getPrice(k)||0);},0);
  const net = budgetDollars + outVal - inCost;
  document.getElementById('sumIn').textContent = fmtPrice(inCost);
  document.getElementById('sumOut').textContent = fmtPrice(outVal);
  document.getElementById('sumBudget').textContent = fmtBudgetK(budgetK);
  document.getElementById('sumNet').textContent = (net>=0?'+':'-') + fmtBudgetK(Math.abs(net/1000));
  document.getElementById('sumNet').style.color = net >= 0 ? 'var(--green)' : 'var(--red)';
  const res = document.getElementById('tradeResult');
  if (inP.length || outP.length) {
    res.style.display = 'block';
    const overlap = inP.filter(function(k){return outP.includes(k);});
    const unequal = inP.length && outP.length && inP.length !== outP.length;
    if (overlap.length) { res.className='trade-result over'; res.textContent='\u274c Same player in both lists'; }
    else if (unequal)   { res.className='trade-result over'; res.textContent='\u26a0\ufe0f Unequal ('+inP.length+' in, '+outP.length+' out)'; }
    else if (net>=0)    { res.className='trade-result ok';   res.textContent='\u2705 Affordable \u2014 '+fmtBudgetK(net/1000)+' remaining'; }
    else                { res.className='trade-result over'; res.textContent='\u274c Over budget by '+fmtBudgetK(Math.abs(net/1000)); }
  } else res.style.display = 'none';

  const sc = document.getElementById('statsCompareSection');
  const inStats = calcSideStats(inP), outStats = calcSideStats(outP);
  if (inStats || outStats) {
    sc.style.display = 'block';
    function sv(id, val, col) {
      const el = document.getElementById(id); if (!el) return;
      el.textContent = val != null ? val : '—';
      if (col) el.style.color = col;
    }
    sv('sc-in-avg',    inStats ? inStats.avg : null);
    sv('sc-in-l3',     inStats ? inStats.l3  : null);
    sv('sc-in-l5',     inStats ? inStats.l5  : null);
    sv('sc-in-fr',     inStats ? (inStats.fr  != null ? inStats.fr  + '/100' : '—') : null, inStats&&inStats.fr!=null?ratingColor(inStats.fr):null);
    sv('sc-in-cons',   inStats ? (inStats.cons!= null ? inStats.cons + '/100' : '—') : null, inStats&&inStats.cons!=null?ratingColor(inStats.cons):null);
    sv('sc-in-fix',    inStats ? (inStats.fixLabel || '—') : null);
    sv('sc-in-ptrend', inStats ? inStats.trendLabel : null, inStats?inStats.trendCol:null);
    sv('sc-in-votes',  inStats ? inStats.votes : null);
    sv('sc-out-avg',   outStats ? outStats.avg : null);
    sv('sc-out-l3',    outStats ? outStats.l3  : null);
    sv('sc-out-l5',    outStats ? outStats.l5  : null);
    sv('sc-out-fr',    outStats ? (outStats.fr  != null ? outStats.fr  + '/100' : '—') : null, outStats&&outStats.fr!=null?ratingColor(outStats.fr):null);
    sv('sc-out-cons',  outStats ? (outStats.cons!= null ? outStats.cons + '/100' : '—') : null, outStats&&outStats.cons!=null?ratingColor(outStats.cons):null);
    sv('sc-out-fix',   outStats ? (outStats.fixLabel || '—') : null);
    sv('sc-out-ptrend',outStats ? outStats.trendLabel : null, outStats?outStats.trendCol:null);
    sv('sc-out-votes', outStats ? outStats.votes : null);

    const netLabel = document.getElementById('sc-net-label');
    const scoreBar = document.getElementById('tradeScoreBar');

    if (inStats && outStats) {
      const netAvg = +(inStats.avg - outStats.avg).toFixed(1);
      const sign = netAvg >= 0 ? '+' : '';

      // Composite trade quality score (0-100)
      // Weights: avg FP 35%, form 20%, consistency 15%, fixture 20%, price trend 10%
      var scoreComponents = [], scoreTotal = 0, wTotal = 0;
      function addComponent(label, inVal, outVal, w, higherBetter) {
        if (inVal == null || outVal == null) return;
        const diff = higherBetter ? (inVal - outVal) : (outVal - inVal);
        const maxDiff = higherBetter ? Math.max(Math.abs(inVal), Math.abs(outVal), 1) : 100;
        const normalised = Math.max(-1, Math.min(1, diff / maxDiff));
        scoreTotal += normalised * w;
        wTotal += w;
        scoreComponents.push({label, diff: +(diff).toFixed(1), good: diff >= 0});
      }
      addComponent('Avg FP',       inStats.avg,  outStats.avg,  35, true);
      addComponent('Form',         inStats.fr,   outStats.fr,   20, true);
      addComponent('Consistency',  inStats.cons, outStats.cons, 15, true);
      addComponent('Fixture',      inStats.fix,  outStats.fix,  20, true);
      if (inStats.trendLabel && outStats.trendLabel) {
        const trendScore = function(t){ return t.includes('Rising')?1:t.includes('Falling')?-1:0; };
        const tDiff = trendScore(inStats.trendLabel) - trendScore(outStats.trendLabel);
        scoreTotal += tDiff * 10;
        wTotal += 10;
        scoreComponents.push({label:'Price trend', diff: tDiff, good: tDiff >= 0});
      }
      const rawScore = wTotal > 0 ? scoreTotal / wTotal : 0; // -1 to 1
      const tradeScore = Math.round((rawScore + 1) / 2 * 100); // 0-100
      const tCol = tradeScore >= 65 ? 'var(--green)' : tradeScore >= 40 ? 'var(--accent)' : 'var(--red)';
      const tLabel = tradeScore >= 65 ? 'Strong upgrade' : tradeScore >= 55 ? 'Slight upgrade' :
        tradeScore >= 45 ? 'Even trade' : tradeScore >= 35 ? 'Slight downgrade' : 'Downgrade';

      if (scoreBar) {
        scoreBar.style.display = 'block';
        const ring = document.getElementById('tradeScoreRing');
        const lbl  = document.getElementById('tradeScoreLabel');
        const bkdn = document.getElementById('tradeScoreBreakdown');
        if (ring) { ring.style.background = 'conic-gradient(' + tCol + ' ' + (tradeScore * 3.6) + 'deg, var(--border) 0deg)'; }
        if (lbl)  { lbl.textContent = tradeScore; lbl.style.color = tCol; }
        if (bkdn) {
          bkdn.innerHTML = '<div style="font-weight:800;font-size:.92rem;color:' + tCol + ';margin-bottom:3px">' + tLabel + '</div>' +
            '<div style="font-size:.7rem;color:var(--muted)">' + scoreComponents.map(function(c){
              return '<span style="color:' + (c.good?'var(--green)':'var(--red)') + '">' + c.label + ': ' + (c.diff>=0?'+':'') + c.diff + '</span>';
            }).join(' · ') + '</div>';
        }
      }

      netLabel.className = 'net-arrow ' + (netAvg > 0 ? 'pos' : netAvg < 0 ? 'neg' : 'neu');
      netLabel.textContent = sign + netAvg + ' avg FP · ' +
        (netAvg > 0 ? 'upgrade ▲' : netAvg < 0 ? 'downgrade ▼' : 'even swap');
    } else {
      if (scoreBar) scoreBar.style.display = 'none';
      netLabel.className = 'net-arrow neu';
      netLabel.textContent = 'Add players to both sides to compare';
    }
  } else {
    sc.style.display = 'none';
    const scoreBar = document.getElementById('tradeScoreBar');
    if (scoreBar) scoreBar.style.display = 'none';
  }
  validateTrades();
}

function setupTradeSearch(inputId, resultsId, listKey) {
  const input = document.getElementById(inputId), results = document.getElementById(resultsId);
  input.addEventListener('input', function() {
    const q = input.value.toLowerCase().trim();
    if (!q) { results.style.display='none'; return; }
    const other = listKey==='tradeIn'?'tradeOut':'tradeIn';
    const otherItems = lsGet(other,[]);
    const matches = PLAYERS_DATA.filter(function(p){
      return ((p.display_name||p.name).toLowerCase().includes(q) || p.name.toLowerCase().includes(q)) && !otherItems.includes(p.key);
    }).slice(0,10);
    results.innerHTML = matches.map(function(p){
      const posStr = p.positions && p.positions.length ? posOrdered(p.positions) + ' \u00b7 ' : '';
      return '<div class="search-result" onclick="addToList(\'' + listKey + '\',\'' + p.key.replace(/'/g,"\\'") + '\');document.getElementById(\'' + inputId + '\').value=\'\';document.getElementById(\'' + resultsId + '\').style.display=\'none\'">' +
        '<span>' + (p.display_name||getDisplayName(p.name,p.team)) + '</span>' +
        '<span class="sr-sub">' + posStr + p.team + ' \u00b7 ' + fmtPrice(p.current_price) + '</span>' +
        '</div>';
    }).join('');
    results.style.display = matches.length ? 'block' : 'none';
  });
  document.addEventListener('click', function(e) {
    if (!e.target.closest('#'+inputId) && !e.target.closest('#'+resultsId)) results.style.display='none';
  });
}
setupTradeSearch('tradeInSearch','tradeInResults','tradeIn');
setupTradeSearch('tradeOutSearch','tradeOutResults','tradeOut');
renderTradeLists();

// ── Scenario Comparison ───────────────────────────────────────────────────────
var scenarios = lsGet('scenarios2', []);
var scenarioCounter = scenarios.length ? Math.max.apply(null, scenarios.map(function(s){return s.id;})) + 1 : 1;

function saveScenarios() { lsSet('scenarios2', scenarios); }

function openScenarioOverlay() {
  document.getElementById('scenarioOverlay').classList.add('active');
  renderScenarios();
}
function closeScenarioOverlay() {
  document.getElementById('scenarioOverlay').classList.remove('active');
}

function addScenario() {
  if (scenarios.length >= 4) return;
  scenarios.push({ id: scenarioCounter, name: 'Scenario ' + scenarioCounter, in:[], out:[] });
  scenarioCounter++;
  saveScenarios(); renderScenarios();
}

function removeScenario(id) {
  scenarios = scenarios.filter(function(s){return s.id !== id;});
  saveScenarios(); renderScenarios();
}

function addPlayerToScenario(id, side, key) {
  const s = scenarios.find(function(x){return x.id === id;}); if (!s) return;
  const other = side === 'in' ? 'out' : 'in';
  if (s[other].includes(key)) { alert('Player already in the ' + (side==='in'?'Out':'In') + ' side of this scenario.'); return; }
  if (!s[side].includes(key)) { s[side].push(key); saveScenarios(); renderScenarios(); }
}

function removeFromScenario(id, side, key) {
  const s = scenarios.find(function(x){return x.id === id;}); if (!s) return;
  s[side] = s[side].filter(function(x){return x !== key;});
  saveScenarios(); renderScenarios();
}

function getPlayerStatsObj(key) {
  const p = findByKey(key); if (!p) return null;
  const scores = p.history.map(function(h){return h.score;});
  const votes  = p.history.map(function(h){return h.votes;});
  const prices  = p.history.map(function(h){return h.pre_price;}).filter(Boolean);
  const n = scores.length;
  const firstPrice = prices.length ? prices[0] : null;
  const lastPrice  = p.current_price || (prices.length ? prices[prices.length-1] : null);
  const priceChange = (firstPrice && lastPrice) ? lastPrice - firstPrice : null;
  return {
    name: p.display_name || getDisplayName(p.name, p.team),
    team: p.team,
    positions: p.positions || [],
    avg:        n ? scores.reduce(function(a,b){return a+b;},0)/n : 0,
    best:       n ? Math.max.apply(null,scores) : 0,
    totalFP:    scores.reduce(function(a,b){return a+b;},0),
    totalVotes: votes.reduce(function(a,b){return a+b;},0),
    last3:      scores.slice(-3).reduce(function(a,b){return a+b;},0)/Math.min(3,n||1),
    last5:      scores.slice(-5).reduce(function(a,b){return a+b;},0)/Math.min(5,n||1),
    formRating:  p.form_rating,
    consistency: p.consistency,
    price:       p.current_price,
    priceChange: priceChange,
    rounds:      n
  };
}

function combinedStatsObj(keys) {
  const all = keys.map(getPlayerStatsObj).filter(Boolean);
  if (!all.length) return null;
  const posCounts = {};
  all.forEach(function(p){p.positions.forEach(function(pos){posCounts[pos]=(posCounts[pos]||0)+1;});});
  const frItems = all.filter(function(x){return x.formRating!=null;});
  const csItems = all.filter(function(x){return x.consistency!=null;});
  const pcItems = all.filter(function(x){return x.priceChange!=null;});
  return {
    avg:         all.reduce(function(s,x){return s+x.avg;},0),
    best:        all.reduce(function(s,x){return s+x.best;},0),
    totalFP:     all.reduce(function(s,x){return s+x.totalFP;},0),
    totalVotes:  all.reduce(function(s,x){return s+x.totalVotes;},0),
    last3:       all.reduce(function(s,x){return s+x.last3;},0),
    last5:       all.reduce(function(s,x){return s+x.last5;},0),
    formRating:  frItems.length ? frItems.reduce(function(s,x){return s+(x.formRating||0);},0)/frItems.length : null,
    consistency: csItems.length ? csItems.reduce(function(s,x){return s+(x.consistency||0);},0)/csItems.length : null,
    price:       all.reduce(function(s,x){return s+(x.price||0);},0),
    priceChange: pcItems.length ? pcItems.reduce(function(s,x){return s+(x.priceChange||0);},0) : null,
    posCounts:   posCounts,
    count:       all.length,
    rounds:      all.reduce(function(s,x){return s+x.rounds;},0),
    players:     all
  };
}

function toggleCollapse(headerId) {
  const body = document.getElementById(headerId + '_body');
  const arrow = document.getElementById(headerId + '_arrow');
  if (!body) return;
  body.classList.toggle('open');
  if (arrow) arrow.classList.toggle('open', body.classList.contains('open'));
}

function renderScenarios() {
  const grid = document.getElementById('scenariosGrid');
  const addBtn = document.getElementById('addScenarioBtn');
  addBtn.disabled = scenarios.length >= 4;
  const cols = scenarios.length <= 2 ? scenarios.length : 2;
  grid.style.gridTemplateColumns = 'repeat(' + (cols||1) + ', 1fr)';
  grid.innerHTML = '';

  const inStats  = scenarios.map(function(s){return combinedStatsObj(s.in);});
  const outStats = scenarios.map(function(s){return combinedStatsObj(s.out);});
  const netAvgs  = scenarios.map(function(s,i){return inStats[i] && outStats[i] ? inStats[i].avg - outStats[i].avg : null;});
  const validNets = netAvgs.filter(function(v){return v!=null;});
  const bestNetAvg = validNets.length ? Math.max.apply(null, validNets) : null;

  scenarios.forEach(function(s, si) {
    const iSt = inStats[si], oSt = outStats[si];
    const netAvg   = iSt && oSt ? iSt.avg   - oSt.avg   : null;
    const netL3    = iSt && oSt ? iSt.last3  - oSt.last3  : null;
    const netL5    = iSt && oSt ? iSt.last5  - oSt.last5  : null;
    const netVotes = iSt && oSt ? iSt.totalVotes - oSt.totalVotes : null;
    const netFR    = (iSt && iSt.formRating != null && oSt && oSt.formRating != null) ? iSt.formRating - oSt.formRating : null;
    const netCS    = (iSt && iSt.consistency != null && oSt && oSt.consistency != null) ? iSt.consistency - oSt.consistency : null;
    const netPrice = iSt && oSt ? iSt.price - oSt.price : null;
    const netPriceChange = (iSt && iSt.priceChange != null && oSt && oSt.priceChange != null) ? iSt.priceChange - oSt.priceChange : null;
    const isWinner = netAvg !== null && netAvg === bestNetAvg && scenarios.length > 1;
    const card = document.createElement('div'); card.className = 'scenario-card' + (isWinner ? ' scenario-winner' : '');

    var posDeltaHtml = '';
    if (iSt && oSt) {
      const allPos = new Set(Object.keys(iSt.posCounts||{}).concat(Object.keys(oSt.posCounts||{})));
      allPos.forEach(function(pos) {
        const diff = (iSt.posCounts[pos]||0) - (oSt.posCounts[pos]||0);
        if (diff !== 0) {
          const col = diff > 0 ? 'var(--green)' : 'var(--red)';
          posDeltaHtml += '<span style="color:' + col + ';margin-right:8px">' + pos + ': ' + (diff>0?'+':'') + diff + '</span>';
        }
      });
    }

    function playerTags(keys, side) {
      return keys.map(function(key) {
        const p = findByKey(key);
        const dn = p ? (p.display_name || getDisplayName(p.name, p.team)) : key;
        const safeKey = key.replace(/'/g,"\\'");
        return '<span class="stag stag-' + side + '">' +
          '<span style="cursor:pointer" onclick="searchAndShowPlayer(\'' + safeKey + '\')">' + dn + '</span>' +
          '<button class="stag-rm" onclick="removeFromScenario(' + s.id + ',\'' + side + '\',\'' + safeKey + '\')">&#10005;</button>' +
          '</span>';
      }).join('');
    }

    function fmtNet(v, decimals) {
      decimals = decimals != null ? decimals : 1;
      if (v == null) return '\u2014';
      return (v >= 0 ? '+' : '-') + Math.abs(v).toFixed(decimals);
    }

    // Always-visible headline numbers \u2014 no click required to see the essentials.
    function statTiles(st) {
      if (!st || st.count === 0) return '<div class="sc-empty">No players added yet</div>';
      const pcStr = st.priceChange != null ? (st.priceChange>=0?'+':'-') + fmtPrice(Math.abs(st.priceChange)) : '\u2014';
      const pcCol = st.priceChange == null ? 'var(--text)' : st.priceChange >= 0 ? 'var(--green)' : 'var(--red)';
      return '<div class="sc-tile-grid">' +
        '<div class="sc-tile"><div class="sc-tile-val">' + st.avg.toFixed(1) + '</div><div class="sc-tile-lbl">Avg FP</div></div>' +
        '<div class="sc-tile"><div class="sc-tile-val">' + st.last3.toFixed(1) + '</div><div class="sc-tile-lbl">L3 Avg</div></div>' +
        '<div class="sc-tile"><div class="sc-tile-val">' + st.totalVotes + '</div><div class="sc-tile-lbl">Votes</div></div>' +
        '<div class="sc-tile"><div class="sc-tile-val" style="color:' + pcCol + '">' + pcStr + '</div><div class="sc-tile-lbl">Price &Delta;</div></div>' +
      '</div>';
    }

    // Secondary detail, tucked behind one click so the card stays scannable.
    function moreDetails(st, collapseId) {
      const arrowId = collapseId + '_arrow', bodyId = collapseId + '_body';
      if (!st || st.count === 0) return '';
      const avgFR = st.formRating  != null ? st.formRating.toFixed(0)  : '\u2014';
      const avgCS = st.consistency != null ? st.consistency.toFixed(0) : '\u2014';
      var html = '';
      if (st.players && st.players.length) {
        st.players.forEach(function(p) {
          html += '<div class="scb-row"><span class="scb-label">' + p.name + ' games</span><span class="scb-val">' + p.rounds + '</span></div>';
        });
      }
      html += '<div class="scb-row"><span class="scb-label">Last 5 Avg</span><span class="scb-val">' + st.last5.toFixed(1) + '</span></div>';
      html += '<div class="scb-row"><span class="scb-label">Total FP</span><span class="scb-val">' + st.totalFP + '</span></div>';
      html += '<div class="scb-row"><span class="scb-label">Avg Form Rating</span><span class="scb-val" style="color:' + ratingColor(st.formRating) + '">' + avgFR + (st.formRating!=null?'/100':'') + '</span></div>';
      html += '<div class="scb-row"><span class="scb-label">Avg Consistency</span><span class="scb-val" style="color:' + ratingColor(st.consistency) + '">' + avgCS + (st.consistency!=null?'/100':'') + '</span></div>';
      html += '<div class="scb-row"><span class="scb-label">Combined Price</span><span class="scb-val">' + fmtPrice(st.price) + '</span></div>';
      Object.entries(st.posCounts).forEach(function(e2){
        html += '<div class="scb-row"><span class="scb-label">' + e2[0] + ' players</span><span class="scb-val">' + e2[1] + '</span></div>';
      });
      return '<div class="stats-collapse-header sc-more-toggle" onclick="toggleCollapse(\'' + collapseId + '\')">' +
          '<span>More detail</span><span class="stats-collapse-arrow" id="' + arrowId + '">&#9660;</span>' +
        '</div>' +
        '<div class="stats-collapse-body" id="' + bodyId + '"><div style="padding-top:6px">' + html + '</div></div>';
    }

    const netClass = netAvg === null ? 'neu' : netAvg > 0 ? 'pos' : netAvg < 0 ? 'neg' : 'neu';
    const netHero = netAvg === null
      ? '<div class="sc-net-hero neu"><div class="sc-net-hero-val">&mdash;</div><div class="sc-net-hero-sub">Add players to both sides to compare</div></div>'
      : '<div class="sc-net-hero ' + netClass + '">' +
          '<div class="sc-net-hero-val">' + fmtNet(netAvg) + '<span>avg&nbsp;FP</span></div>' +
          '<div class="sc-net-hero-sub">' + (netAvg>0?'&#9650; Net upgrade':netAvg<0?'&#9660; Net downgrade':'Even swap') +
            (netVotes!=null?' &middot; ' + fmtNet(netVotes,0) + ' votes':'') +
            (netPriceChange!=null?' &middot; ' + (netPriceChange>=0?'+':'-') + fmtPrice(Math.abs(netPriceChange)) + ' price trend':'') +
          '</div>' +
          (posDeltaHtml ? '<div class="sc-net-hero-pos">' + posDeltaHtml + '</div>' : '') +
        '</div>';

    card.innerHTML =
      '<div class="scenario-card-header">' +
        '<input class="scenario-name-input" value="' + s.name.replace(/"/g,'&quot;') + '" onchange="renameScenario(' + s.id + ',this.value)">' +
        (isWinner ? '<span class="winner-crown" title="Best avg gain">&#127942; BEST TRADE</span>' : '') +
        '<button class="trade-item-remove" style="font-size:1rem" onclick="removeScenario(' + s.id + ')">&#10005;</button>' +
      '</div>' +
      netHero +
      '<div class="sc-side sc-side-in">' +
        '<div class="sc-side-head">&#11014; Trading In</div>' +
        '<div class="scenario-tags">' + playerTags(s.in,'in') + '</div>' +
        '<div class="sc-rel"><input class="sc-search" placeholder="Search to add in\u2026" id="sc_in_' + s.id + '" autocomplete="off"><div class="sc-dropdown" id="sc_dr_in_' + s.id + '"></div></div>' +
        statTiles(iSt) +
        moreDetails(iSt, 'sc_in_stats_' + s.id) +
      '</div>' +
      '<div class="sc-side sc-side-out">' +
        '<div class="sc-side-head">&#11015; Trading Out</div>' +
        '<div class="scenario-tags">' + playerTags(s.out,'out') + '</div>' +
        '<div class="sc-rel"><input class="sc-search" placeholder="Search to add out\u2026" id="sc_out_' + s.id + '" autocomplete="off"><div class="sc-dropdown" id="sc_dr_out_' + s.id + '"></div></div>' +
        statTiles(oSt) +
        moreDetails(oSt, 'sc_out_stats_' + s.id) +
      '</div>';

    grid.appendChild(card);
    setupScenarioSearch('sc_in_'+s.id, 'sc_dr_in_'+s.id, s.id, 'in');
    setupScenarioSearch('sc_out_'+s.id, 'sc_dr_out_'+s.id, s.id, 'out');
  });
}

function renameScenario(id, name) {
  const s = scenarios.find(function(x){return x.id === id;}); if (s) { s.name = name; saveScenarios(); }
}

function setupScenarioSearch(inputId, dropId, scenarioId, side) {
  const inp = document.getElementById(inputId), drp = document.getElementById(dropId);
  if (!inp || !drp) return;
  inp.addEventListener('input', function() {
    const q = inp.value.toLowerCase().trim();
    if (!q) { drp.style.display='none'; return; }
    const matches = PLAYERS_DATA.filter(function(p){
      return (p.display_name||p.name).toLowerCase().includes(q) || p.name.toLowerCase().includes(q);
    }).slice(0, 8);
    drp.innerHTML = matches.map(function(p){
      const posStr = p.positions && p.positions.length ? posOrdered(p.positions) + ' \u00b7 ' : '';
      return '<div class="sc-dropdown-item" onclick="addPlayerToScenario(' + scenarioId + ',\'' + side + '\',\'' + p.key.replace(/'/g,"\\'") + '\');document.getElementById(\'' + inputId + '\').value=\'\';document.getElementById(\'' + dropId + '\').style.display=\'none\'">' +
        '<span>' + (p.display_name||getDisplayName(p.name,p.team)) + '</span>' +
        '<span style="font-size:.72rem;color:var(--muted)">' + posStr + p.team + ' \u00b7 ' + fmtPrice(p.current_price) + '</span>' +
        '</div>';
    }).join('');
    drp.style.display = matches.length ? 'block' : 'none';
  });
  document.addEventListener('click', function(e) {
    if (!e.target.closest('#'+inputId) && !e.target.closest('#'+dropId)) drp.style.display='none';
  });
}

if (!scenarios.length) { addScenario(); }

// My Team & Rolling 22
// AFL Fantasy: DEF 6+2bench, MID 8+2bench, RUC 2+1bench, FWD 5+1bench, UTIL 1
const MT_POS_CONFIG = [
  {pos:'DEF', starters:6, bench:2, cls:'pos-def', color:'#93c5fd', label:'DEF'},
  {pos:'MID', starters:8, bench:2, cls:'pos-mid', color:'#6ee7b7', label:'MID'},
  {pos:'RUC', starters:2, bench:1, cls:'pos-ruc', color:'#fcd34d', label:'RUC'},
  {pos:'FWD', starters:6, bench:2, cls:'pos-fwd', color:'#fca5a5', label:'FWD'},
];
// DPP: assign to WEAKEST eligible position first (FWD < DEF < MID < RUC)
const DPP_PRIORITY = ['FWD','DEF','RUC','MID'];

function lsMyTeam() { return lsGet('myteam_squad', []); }
function lsMyTeamPositions() { return lsGet('myteam_positions', {}); }
function saveMyTeamBudget() { lsSet('myteam_budget', parseFloat(document.getElementById('myteamBudget').value)||0); }
function clearMyTeam() {
  lsSet('myteam_squad',[]); lsSet('myteam_positions',{}); lsSet('myteam_slot_order',{});
  renderMyTeam();
  document.getElementById('myteamAnalysis').style.display='none';
}

// ── Slot-precise drag & drop ────────────────────────────────────────────────
// groupSquadByPosition only decides WHICH position group each player falls into;
// it says nothing about on-screen order within that group. We layer an explicit,
// self-healing slot order on top so a drag-drop can target (and swap with) one
// specific card instead of "somewhere in this position".
function lsMyTeamSlotOrder() { return lsGet('myteam_slot_order', {}); }
function reconcileSlotOrder(grouped) {
  const stored = lsMyTeamSlotOrder();
  const result = {};
  ['DEF','MID','RUC','FWD'].forEach(function(pos) {
    const groupKeys = grouped[pos] || [];
    const inGroup = {};
    groupKeys.forEach(function(k) { inGroup[k] = true; });
    const prev = (stored[pos] || []).filter(function(k) { return k && inGroup[k]; });
    const seen = {};
    prev.forEach(function(k) { seen[k] = true; });
    groupKeys.forEach(function(k) { if (!seen[k]) { prev.push(k); seen[k] = true; } });
    result[pos] = prev;
  });
  return result;
}
function swapMyTeamSlots(fromPos, fromIdx, toPos, toIdx) {
  const grouped = groupSquadByPosition(lsMyTeam());
  const order = reconcileSlotOrder(grouped);
  const draggedKey = (order[fromPos] || [])[fromIdx] || null;
  const targetKey  = (order[toPos]   || [])[toIdx]   || null;
  if (!draggedKey || draggedKey === targetKey) return;

  if (fromPos !== toPos) {
    const dp = getP(draggedKey);
    const draggedEligible = dp && dp.positions && dp.positions.includes(toPos);
    if (!draggedEligible) { flashIneligible(toPos); return; }
    if (targetKey) {
      const tp = getP(targetKey);
      if (!(tp && tp.positions && tp.positions.includes(fromPos))) { flashIneligible(toPos); return; }
    }
    const overrides = lsMyTeamPositions();
    overrides[draggedKey] = toPos;
    if (targetKey) overrides[targetKey] = fromPos; else delete overrides[targetKey];
    lsSet('myteam_positions', overrides);
  }

  order[fromPos] = order[fromPos] || [];
  order[toPos]   = order[toPos]   || [];
  order[toPos][toIdx] = draggedKey;
  if (targetKey) order[fromPos][fromIdx] = targetKey;
  else order[fromPos].splice(fromIdx, 1);
  lsSet('myteam_slot_order', order);
  renderMyTeam([draggedKey, targetKey].filter(Boolean));
}
function flashIneligible(posKey) {
  const row = document.querySelector('[data-pos="' + posKey + '"]');
  if (!row) return;
  row.classList.add('pos-row-reject');
  setTimeout(function() { row.classList.remove('pos-row-reject'); }, 350);
}

function playerStats(key) {
  const p = getP(key); if (!p) return null;
  const scores = p.history.map(function(x){return x.score;});
  const n = scores.length;
  if (!n) return {avg:0,l3:0,l5:0,best:0,worst:0,n:0,price:p.current_price,fr:p.form_rating,cs:p.consistency};
  const avg = scores.reduce(function(a,b){return a+b;},0)/n;
  const l3  = scores.slice(-3).reduce(function(a,b){return a+b;},0)/Math.min(3,n);
  const l5  = scores.slice(-5).reduce(function(a,b){return a+b;},0)/Math.min(5,n);
  return {avg,l3,l5,best:Math.max.apply(null,scores),worst:Math.min.apply(null,scores),n,price:p.current_price,fr:p.form_rating,cs:p.consistency};
}

// Where a player ranks among everyone eligible for their primary position, by season
// average. Requires a 3+ game sample on both sides so a one-game cameo can't skew it.
// DPP players are ranked in every position they're eligible for, and the badge
// shows whichever position they rank best in — a MID/FWD player only ranking
// #180 of 230 in MID but #3 of 90 in FWD should be shown as the FWD result.
function positionRank(key) {
  const p = getP(key);
  if (!p || !p.positions || !p.positions.length) return null;
  const myStats = playerStats(key);
  if (!myStats || myStats.n < 3) return null;
  var best = null;
  p.positions.forEach(function(pos) {
    const peers = [];
    PLAYERS_DATA.forEach(function(op) {
      if (!op.positions || !op.positions.includes(pos)) return;
      const st = playerStats(op.key);
      if (st && st.n >= 3) peers.push({key: op.key, avg: st.avg});
    });
    peers.sort(function(a,b){ return b.avg - a.avg; });
    const rank = peers.findIndex(function(x){ return x.key === key; }) + 1;
    if (rank <= 0) return;
    const total = peers.length;
    // "top X%" — rank 1 of 230 -> top 1%, rank 230 of 230 -> top 100%. Lower is better.
    const percentile = Math.max(1, Math.round((rank/total) * 100));
    if (!best || rank < best.rank) best = {pos: pos, rank: rank, total: total, percentile: percentile};
  });
  return best;
}

function playerSignal(key, isBench) {
  const p = getP(key); if (!p) return {label:'—',col:'var(--muted)',score:50,reasons:[]};
  const st = playerStats(key);
  const isInj = INJURED_SET && INJURED_SET.has(p.name);
  const sTag = statusLabel(p.name);
  if (sTag === 'SUS') return {label:'SUS',col:'var(--yellow)',score:5,reasons:['Reported suspended']};
  if (isInj) return {label:'INJ',col:'var(--red)',score:5,reasons:['Reported injured']};
  if (!st || st.n === 0) return {label:'DNP',col:'var(--red)',score:10,reasons:['No game data']};
  const price = st.price;
  const beScore = price ? price/10490 : null;
  const trend = getPlayerPriceTrend(key);
  const fix = getPlayerFixtureScore(key);
  const recent = p.history.slice(-3).map(function(x){return x.score;});
  const recentAvg = recent.length ? recent.reduce(function(a,b){return a+b;},0)/recent.length : st.avg;
  var score = 50, reasons = [];
  if (st.avg >= 130) score += 30;
  else if (st.avg >= 115) score += 22;
  else if (st.avg >= 100) score += 13;
  else if (st.avg >= 85)  score += 4;
  else if (st.avg < 70)   score -= 13;
  const fd = recentAvg - st.avg;
  if (fd > 15)       { score += 10; reasons.push('L3 +'+fd.toFixed(0)+' above avg'); }
  else if (fd > 5)   { score += 5; }
  else if (fd < -15) { score -= 12; reasons.push('L3 '+fd.toFixed(0)+' below avg'); }
  else if (fd < -5)  { score -= 5;  reasons.push('form dipping'); }
  if (beScore) {
    const hits = recent.filter(function(s){return s>=beScore;}).length;
    if (hits===0&&recent.length>0) { score -= 10; reasons.push('missing BE ('+beScore.toFixed(0)+') every game'); }
    else if (hits===recent.length&&recent.length>0) { score += 6; reasons.push('beating BE consistently'); }
  }
  if (trend==='rising')  { score += 5; reasons.push('price rising'); }
  if (trend==='falling') { score -= 8; reasons.push('price falling'); }
  if (fix!=null) {
    if (fix>=108)      { score += 7; reasons.push('easy fixture'); }
    else if (fix>=104) { score += 3; }
    else if (fix<=92)  { score -= 8; reasons.push('tough fixture'); }
    else if (fix<=96)  { score -= 4; }
  }
  if (st.cs!=null&&st.cs<35) { score -= 5; reasons.push('inconsistent'); }
  if (isBench&&price&&price>900000) { score -= 8; reasons.push('expensive bench'); }
  if (st.n===1) { score -= 4; reasons.push('1 game only'); }
  score = Math.max(0, Math.min(100, score));
  var label, col;
  if (st.avg >= 120)    { label='🔒LOCK'; col='var(--green)'; }
  else if (score >= 65) { label='✓HOLD';  col='var(--green)'; }
  else if (score >= 50) { label='HOLD';   col='#86efac'; }
  else if (score >= 38) { label='WATCH';  col='var(--yellow)'; }
  else                  { label='SELL';   col='var(--red)'; }
  return {label, col, score, reasons, avg:st.avg, l3:recentAvg, price, trend, fix};
}

function groupSquadByPosition(squad) {
  // Respect manual overrides first, then DPP_PRIORITY for auto-placement
  const overrides = lsMyTeamPositions(); // {key: 'DEF'|'MID'|'RUC'|'FWD'|'UTIL'}
  const capacity = {};
  MT_POS_CONFIG.forEach(function(cfg){ capacity[cfg.pos] = cfg.starters + cfg.bench; });
  const grouped = {DEF:[],MID:[],RUC:[],FWD:[],UTIL:[],UNKNOWN:[]};
  const used = new Set();

  // Pass 1: manual position overrides
  squad.forEach(function(key) {
    const manualPos = overrides[key];
    if (!manualPos) return;
    const p = getP(key);
    const eligibleForPos = p && p.positions && (p.positions.includes(manualPos) || manualPos === 'UTIL');
    if (eligibleForPos || manualPos === 'UTIL') {
      if (manualPos === 'UTIL') { grouped.UTIL.push(key); used.add(key); }
      else if (grouped[manualPos] && grouped[manualPos].length < capacity[manualPos]) {
        grouped[manualPos].push(key); used.add(key);
      }
    }
  });

  // Pass 2: single-position players
  squad.forEach(function(key) {
    if (used.has(key)) return;
    const p = getP(key); if (!p || !p.positions) return;
    const eligPos = DPP_PRIORITY.filter(function(pos){ return p.positions.includes(pos); });
    if (eligPos.length === 1) {
      const pos = eligPos[0];
      if (grouped[pos].length < capacity[pos]) { grouped[pos].push(key); used.add(key); }
    }
  });

  // Pass 3: DPP players - use DPP_PRIORITY (FWD first)
  squad.forEach(function(key) {
    if (used.has(key)) return;
    const p = getP(key); if (!p || !p.positions) return;
    const eligPos = DPP_PRIORITY.filter(function(pos){ return p.positions.includes(pos); });
    for (var i=0; i<eligPos.length; i++) {
      const pos = eligPos[i];
      if (grouped[pos].length < capacity[pos]) { grouped[pos].push(key); used.add(key); break; }
    }
  });

  // Pass 4: overflow → UTIL
  squad.forEach(function(key) {
    if (used.has(key)) { return; }
    if (grouped.UTIL.length < 1) { grouped.UTIL.push(key); used.add(key); }
    else { grouped.UNKNOWN.push(key); used.add(key); }
  });
  return grouped;
}

function setPlayerPosition(key, pos) {
  const overrides = lsMyTeamPositions();
  if (pos === null) { delete overrides[key]; }
  else { overrides[key] = pos; }
  lsSet('myteam_positions', overrides);
  renderMyTeam();
}

function renderMyTeam(highlightKeys) {
  highlightKeys = highlightKeys || [];
  const squad = lsMyTeam();
  const grouped = groupSquadByPosition(squad);
  const order = reconcileSlotOrder(grouped);
  lsSet('myteam_slot_order', order);
  const fieldDiv = document.getElementById('myteamFieldGrid');
  if (!fieldDiv) return;
  fieldDiv.innerHTML = '';

  // Full-width field, tips panel stretches beneath (matches Rolling 22's layout)
  const wrap = document.createElement('div');
  wrap.style.cssText = 'display:flex;flex-direction:column;gap:16px';
  const leftCol = document.createElement('div');
  leftCol.className = 'pitch-panel';
  const rightCol = document.createElement('div');
  rightCol.id = 'mtTipsPanel';
  rightCol.className = 'mt-tips-wide';

  // ── Render each position section ─────────────────────────────────────────
  const posOrder = ['DEF','MID','RUC','FWD'];
  posOrder.forEach(function(posKey) {
    const cfg = MT_POS_CONFIG.find(function(c){return c.pos===posKey;});
    const players = order[posKey] || [];
    const total = cfg.starters + cfg.bench;

    const posFullNames = {DEF:'DEFENDERS', MID:'MIDFIELDERS', RUC:'RUCKS', FWD:'FORWARDS'};
    const sec = document.createElement('div');
    sec.className = 'pitch-pos-row';
    sec.dataset.pos = posKey;
    const lbl = document.createElement('div');
    lbl.className = 'pitch-pos-label';
    lbl.style.background = cfg.color;
    lbl.textContent = posFullNames[posKey] || cfg.label;
    sec.appendChild(lbl);

    const rowWrap = document.createElement('div');
    const meta = document.createElement('div');
    meta.className = 'pitch-pos-meta';
    meta.innerHTML = players.length + '/' + total;
    rowWrap.appendChild(meta);

    const startersGrid = document.createElement('div');
    startersGrid.className = 'pitch-cards';
    const benchGrid = document.createElement('div');
    benchGrid.className = 'pitch-cards pitch-bench';

    for (var i=0; i<total; i++) {
      const isBench = i >= cfg.starters;
      const key = players[i];
      const card = makePlayerCard(key, posKey, isBench, cfg);
      card.dataset.pos = posKey;
      card.dataset.idx = i;
      if (key && highlightKeys.indexOf(key) !== -1) card.classList.add('card-swap-flash');
      if (key) {
        card.draggable = true;
        card.addEventListener('dragstart', function(e) {
          e.dataTransfer.setData('fromPos', this.dataset.pos);
          e.dataTransfer.setData('fromIdx', this.dataset.idx);
          e.currentTarget.classList.add('dragging');
        });
        card.addEventListener('dragend', function(e) { e.currentTarget.classList.remove('dragging'); });
      }
      // Every slot — filled or empty — is a valid drop target so a player can be
      // swapped with (or moved into) the exact card that was dropped on.
      card.addEventListener('dragover', function(e) { e.preventDefault(); e.currentTarget.classList.add('drag-target'); });
      card.addEventListener('dragleave', function(e) { e.currentTarget.classList.remove('drag-target'); });
      card.addEventListener('drop', function(e) {
        e.preventDefault();
        e.currentTarget.classList.remove('drag-target');
        const fromPos = e.dataTransfer.getData('fromPos');
        const fromIdx = parseInt(e.dataTransfer.getData('fromIdx'), 10);
        if (!fromPos || isNaN(fromIdx)) return;
        swapMyTeamSlots(fromPos, fromIdx, this.dataset.pos, parseInt(this.dataset.idx, 10));
      });
      (isBench ? benchGrid : startersGrid).appendChild(card);
    }

    rowWrap.className = 'pitch-row-flex';
    const startersCol = document.createElement('div');
    startersCol.className = 'pitch-starters-col';
    startersCol.appendChild(startersGrid);
    rowWrap.appendChild(startersCol);
    if (cfg.bench > 0) {
      const benchCol = document.createElement('div');
      benchCol.className = 'pitch-bench-col';
      const benchLbl = document.createElement('div');
      benchLbl.className = 'pitch-bench-label';
      benchLbl.textContent = 'Bench';
      benchCol.appendChild(benchLbl);
      benchCol.appendChild(benchGrid);
      rowWrap.appendChild(benchCol);
    }
    sec.appendChild(rowWrap);
    leftCol.appendChild(sec);
  });

  // ── UTIL + bench overflow ─────────────────────────────────────────────────
  const utilPlayers = (grouped.UTIL||[]).concat(grouped.UNKNOWN||[]);
  const utilSlots = 1;
  const utilSec = document.createElement('div');
  utilSec.style.cssText = 'margin-bottom:8px';
  const utilLbl = document.createElement('div');
  utilLbl.style.cssText = 'font-family:"Barlow Condensed",sans-serif;font-weight:800;font-size:.68rem;letter-spacing:.1em;color:var(--muted);margin-bottom:4px';
  utilLbl.textContent = 'UTILITY / EXTRA';
  utilSec.appendChild(utilLbl);
  const utilRow = document.createElement('div');
  utilRow.className = 'pitch-cards';
  for (var ui=0; ui<utilSlots; ui++) {
    const ukey = utilPlayers[ui];
    const cfg0 = {color:'var(--muted)',cls:'',pos:'UTIL'};
    utilRow.appendChild(makePlayerCard(ukey||null, 'UTIL', true, cfg0));
  }
  // Drop to UTIL
  utilRow.addEventListener('dragover', function(e){ e.preventDefault(); utilRow.style.outline='1px dashed var(--muted)'; });
  utilRow.addEventListener('dragleave', function(){ utilRow.style.outline=''; });
  utilRow.addEventListener('drop', function(e){
    e.preventDefault(); utilRow.style.outline='';
    const dragKey = e.dataTransfer.getData('key');
    if (dragKey) setPlayerPosition(dragKey, 'UTIL');
  });
  utilSec.appendChild(utilRow);
  leftCol.appendChild(utilSec);

  wrap.appendChild(leftCol);
  wrap.appendChild(rightCol);
  fieldDiv.appendChild(wrap);

  // Stats row update
  const reportCardEl = document.getElementById('mtReportCard');
  if (squad.length > 0) {
    var tv=0,as=0,ac=0,startTv=0,startCount=0,l3Sum=0,l3Count=0,votesTotal=0,injCount=0;
    squad.forEach(function(k){
      const p=getP(k); if(!p)return;
      if(p.current_price) tv+=p.current_price;
      if(p.starting_price){ startTv+=p.starting_price; startCount++; }
      const st=playerStats(k);
      if(st&&st.n){ as+=st.avg; ac++; l3Sum+=st.l3; l3Count++; }
      if(p.history) votesTotal += p.history.reduce(function(s,h){return s+(h.votes||0);},0);
      if(INJURED_SET&&INJURED_SET.has(p.name)) injCount++;
    });
    document.getElementById('myteamTeamValue').style.display='block';
    document.getElementById('myteamValueNum').textContent=fmtPrice(tv);
    document.getElementById('myteamTeamAvg').style.display='block';
    document.getElementById('myteamAvgNum').textContent=ac?(as/ac).toFixed(1)+' pts':'—';
    if(reportCardEl){
      const gain = startCount ? tv-startTv : null;
      const l3Avg = l3Count ? l3Sum/l3Count : null;
      const seasonAvg = ac ? as/ac : null;
      const trendDiff = (l3Avg!=null&&seasonAvg!=null) ? l3Avg-seasonAvg : null;
      reportCardEl.innerHTML = '<div class="lb-stats-strip" style="margin-bottom:16px">' +
        '<div class="lbs-item"><div class="lbs-val">'+fmtPrice(tv)+'</div><div class="lbs-lbl">Squad Value</div></div>' +
        '<div class="lbs-item"><div class="lbs-val" style="color:'+(gain==null?'var(--text)':gain>=0?'var(--green)':'var(--red)')+'">'+(gain==null?'—':(gain>=0?'+':'')+fmtPrice(gain))+'</div><div class="lbs-lbl">Gain vs Draft Price</div></div>' +
        '<div class="lbs-item"><div class="lbs-val">'+(seasonAvg!=null?seasonAvg.toFixed(1):'—')+'</div><div class="lbs-lbl">Squad Avg FP</div></div>' +
        '<div class="lbs-item"><div class="lbs-val" style="color:'+(trendDiff==null?'var(--text)':trendDiff>=0?'var(--green)':'var(--red)')+'">'+(trendDiff==null?'—':(trendDiff>=0?'+':'')+trendDiff.toFixed(1))+'</div><div class="lbs-lbl">L3 Form Trend</div></div>' +
        '<div class="lbs-item"><div class="lbs-val">'+votesTotal+'</div><div class="lbs-lbl">Total Votes Earned</div></div>' +
        '<div class="lbs-item"><div class="lbs-val" style="color:'+(injCount?'var(--red)':'var(--text)')+'">'+injCount+'</div><div class="lbs-lbl">Injured</div></div>' +
      '</div>';
    }
    buildTipsPanel(squad, grouped);
  } else {
    if(reportCardEl) reportCardEl.innerHTML='';
    document.getElementById('myteamTeamValue').style.display='none';
    document.getElementById('myteamTeamAvg').style.display='none';
    document.getElementById('myteamAnalysis').style.display='none';
    rightCol.innerHTML='<div style="color:var(--muted);font-size:.8rem;padding:8px">Add players to see tips.</div>';
  }
  var b=lsGet('myteam_budget',0); if(b) document.getElementById('myteamBudget').value=b;
}

function makePlayerCard(key, posKey, isBench, cfg) {
  const card = document.createElement('div');
  if (!key) {
    card.style.cssText = 'border:1px dashed rgba(var(--overlay-rgb),.08);border-radius:6px;display:flex;align-items:center;justify-content:center;min-height:70px;color:rgba(var(--overlay-rgb),.15);font-size:.65rem;font-family:"Barlow Condensed",sans-serif;cursor:pointer;background:'+(isBench?'rgba(var(--overlay-rgb),.01)':'transparent');
    card.textContent = isBench ? (posKey==='UTIL'?'util':'bench') : '+ '+posKey;
    card.onclick = function(){document.getElementById('myteamSearch').focus();};
    return card;
  }
  const p = getP(key);
  const dn = p ? (p.display_name||getDisplayName(p.name,p.team)) : key;
  const st = playerStats(key);
  const sig = playerSignal(key, isBench);
  const proj = calcProjectedScore(key);
  const safeKey = key.replace(/'/g,"\\'");
  const isInj = p && INJURED_SET && INJURED_SET.has(p.name);
  const statTag = p ? statusLabel(p.name) : null;
  const avgNum = st&&st.avg ? st.avg : 0;
  const avgCol = avgNum>=115?'var(--green)':avgNum>=95?'var(--text)':'var(--muted)';
  const trendSym = sig.trend==='rising'?'↑':sig.trend==='falling'?'↓':'';
  const trendCol = sig.trend==='rising'?'var(--green)':'var(--red)';
  // DPP badge - show other eligible positions
  const otherPos = p&&p.positions?p.positions.filter(function(pp){return pp!==posKey;}).join('/'):'';

  const tCol = p ? teamColor(p.team) : 'var(--muted)';
  card.classList.add('squad-card');
  card.style.cssText = 'background:'+(isBench?'rgba(var(--overlay-rgb),.025)':'var(--surface2)')+
    ';border:1px solid '+(statTag==='SUS'?'rgba(251,191,36,.5)':statTag==='INJ'?'rgba(248,113,113,.5)':isBench?'rgba(var(--overlay-rgb),.07)':'var(--border)')+
    ';border-radius:8px;padding:9px 7px 6px;position:relative;overflow:hidden;min-height:76px;display:flex;flex-direction:column;gap:1px;transition:border-color .15s,transform var(--dur) var(--ease),box-shadow var(--dur) var(--ease);cursor:grab';

  // Right-click context menu for manual position override
  card.addEventListener('contextmenu', function(e){
    e.preventDefault();
    if (!p||!p.positions) return;
    const menu = document.createElement('div');
    menu.style.cssText = 'position:fixed;top:'+e.clientY+'px;left:'+e.clientX+'px;background:var(--surface2);border:1px solid var(--border);border-radius:7px;padding:5px;z-index:9999;min-width:140px';
    menu.innerHTML = '<div style="font-size:.65rem;color:var(--muted);padding:3px 8px;font-weight:700;text-transform:uppercase">Move to position</div>';
    const allPos = ['DEF','MID','RUC','FWD','UTIL'];
    allPos.forEach(function(pp){
      const eligible = pp==='UTIL' || (p.positions&&p.positions.includes(pp));
      if (!eligible) return;
      const item = document.createElement('div');
      item.style.cssText = 'padding:5px 10px;cursor:pointer;font-size:.8rem;border-radius:4px;color:'+(pp===posKey?'var(--accent)':'var(--text)');
      item.textContent = pp + (pp===posKey?' (current)':'');
      item.onmouseover = function(){item.style.background='rgba(var(--overlay-rgb),.06)';};
      item.onmouseout  = function(){item.style.background='';};
      item.onclick = function(){ setPlayerPosition(key, pp); document.body.removeChild(menu); };
      menu.appendChild(item);
    });
    const clearItem = document.createElement('div');
    clearItem.style.cssText = 'padding:5px 10px;cursor:pointer;font-size:.8rem;color:var(--muted);border-top:1px solid var(--border);margin-top:3px;border-radius:4px';
    clearItem.textContent = 'Auto-place';
    clearItem.onclick = function(){ setPlayerPosition(key, null); document.body.removeChild(menu); };
    menu.appendChild(clearItem);
    document.body.appendChild(menu);
    setTimeout(function(){ document.addEventListener('click', function rm(){ if(document.body.contains(menu)) document.body.removeChild(menu); document.removeEventListener('click',rm); }); }, 10);
  });

  card.innerHTML =
    '<div style="position:absolute;top:0;left:0;right:0;height:3px;background:'+tCol+'"></div>'+
    '<div style="display:flex;align-items:center;gap:5px">' +
      '<div style="width:19px;height:19px;border-radius:50%;flex-shrink:0;background:'+tCol+';display:flex;align-items:center;justify-content:center;font-size:.58rem;font-weight:800;font-family:\'Barlow Condensed\',sans-serif;color:#0d0f1a">'+dn.charAt(0).toUpperCase()+'</div>'+
      '<span style="font-size:.5rem;font-weight:800;font-family:\'Barlow Condensed\',sans-serif;color:'+(cfg.color||'var(--muted)')+';opacity:.95">'+(posKey+(isBench?'·B':''))+(otherPos?'<span style="opacity:.6">/'+otherPos+'</span>':'')+'</span>'+
      '<span style="margin-left:auto;font-size:.52rem;font-weight:800;font-family:\'Barlow Condensed\',sans-serif;color:'+sig.col+'">'+sig.label+'</span>'+
    '</div>'+
    '<div style="font-weight:700;font-size:.76rem;cursor:pointer;color:'+(isInj?'var(--red)':'var(--text)')+';overflow:hidden;text-overflow:ellipsis;white-space:nowrap;line-height:1.2;margin-top:4px" onclick="searchAndShowPlayer(\''+safeKey+'\')" title="'+dn+'">'+dn+'</div>'+
    '<div style="font-size:.58rem;color:var(--muted)">'+(p?p.team:'')+(statTag==='SUS'?' 🚫 SUS':statTag==='INJ'?' 🚑 INJ':'')+'</div>'+
    '<div style="display:flex;align-items:baseline;gap:2px;margin-top:2px">'+
      '<span style="font-family:\'Barlow Condensed\',sans-serif;font-weight:800;font-size:1.05rem;color:'+avgCol+'">'+(st&&st.avg?st.avg.toFixed(0):'—')+'</span>'+
      (proj!=null?'<span style="font-family:\'Barlow Condensed\',sans-serif;font-size:.72rem;color:var(--accent2)">→'+proj+'</span>':'')+
      (trendSym?'<span style="font-size:.62rem;color:'+trendCol+'">'+trendSym+'</span>':'')+
    '</div>'+
    '<div style="font-size:.57rem;color:var(--muted)">'+(st&&st.price?fmtPrice(st.price):'')+'</div>'+
    '<button onclick="removeFromMyTeam(\''+safeKey+'\')" style="position:absolute;top:5px;right:4px;background:none;border:none;color:rgba(var(--overlay-rgb),.15);cursor:pointer;font-size:.62rem;padding:1px;line-height:1">✕</button>';
  return card;
}

function starters(pos, grouped) {
  const cfg = MT_POS_CONFIG.find(function(c){return c.pos===pos;});
  return (grouped[pos]||[]).slice(0, cfg?cfg.starters:0);
}
function benchPlayers(pos, grouped) {
  const cfg = MT_POS_CONFIG.find(function(c){return c.pos===pos;});
  return (grouped[pos]||[]).slice(cfg?cfg.starters:0);
}

function buildTipsPanel(squad, grouped) {
  const panel = document.getElementById('mtTipsPanel');
  if (!panel) return;
  var tips = [];

  // ── 1. Injury / suspension alerts ────────────────────────────────────────
  squad.forEach(function(key){
    const p=getP(key); if(!p||!INJURED_SET||!INJURED_SET.has(p.name)) return;
    const onField = ['DEF','MID','RUC','FWD'].some(function(pos){return starters(pos,grouped).includes(key);});
    // Cheap injured/suspended players on the bench aren't costing you anything —
    // no need to flag a trade for a $200K bench spot that's just sitting there.
    if (!onField && p.current_price != null && p.current_price <= 300000) return;
    const isSus = SUSPENDED_SET && SUSPENDED_SET.has(p.name);
    tips.push({pri:1,icon:isSus?'🚫':'🚑',title:(p.name)+(isSus?' — SUSPENDED':' — INJURED'),col:isSus?'var(--yellow)':'var(--red)',
      body:(onField?'🚨 On your FIELD — urgent trade out needed. ':'On bench. ')+
        'Check official team announcements. Trade out for available replacement.'});
  });


  // ── 3. VC pick ───────────────────────────────────────────────────────────
  var vcKey=null,vcScore=-1;
  ['DEF','MID','RUC','FWD'].forEach(function(pos){
    starters(pos,grouped).forEach(function(key){
      if(key===bestCap) return;
      const p=getP(key); if(!p||INJURED_SET&&INJURED_SET.has(p.name)) return;
      const proj=calcProjectedScore(key); if(!proj) return;
      const s=proj+(getPlayerFixtureScore(key)||100)*0.3;
      if(s>vcScore){vcScore=s;vcKey=key;}
    });
  });
  if(vcKey){
    const vcp=getP(vcKey); const vcproj=calcProjectedScore(vcKey);
    tips.push({pri:3,icon:'🅥',title:'Vice-Captain: '+(vcp?vcp.name:'?'),col:'var(--accent)',
      body:'Projected '+vcproj+' pts. Loop VC → captain if your C scores a donut.'});
  }

  // ── 4. DPP opportunity ───────────────────────────────────────────────────
  squad.forEach(function(key){
    const p=getP(key); if(!p||!p.positions||p.positions.length<2) return;
    // Find where they currently are
    var curPos=null;
    ['DEF','MID','RUC','FWD'].forEach(function(pos){if((grouped[pos]||[]).includes(key)) curPos=pos;});
    if(!curPos) return;
    // Check if moving to a weaker/different position helps
    const eligOther = DPP_PRIORITY.filter(function(pp){return pp!==curPos&&p.positions.includes(pp);});
    eligOther.forEach(function(altPos){
      const altGroup = grouped[altPos]||[];
      const altCfg = MT_POS_CONFIG.find(function(c){return c.pos===altPos;});
      const altBench = altGroup.slice(altCfg?altCfg.starters:0);
      // If their current pos has strong alternatives but alt pos is thin
      const curGroup = grouped[curPos]||[];
      const curCfg = MT_POS_CONFIG.find(function(c){return c.pos===curPos;});
      const curStarters = curGroup.slice(0, curCfg?curCfg.starters:0);
      if (altGroup.length < (altCfg?(altCfg.starters+altCfg.bench):8)*0.7 && curStarters.length >= (curCfg?curCfg.starters:6)) {
        tips.push({pri:2,icon:'🔄',title:'DPP: Move '+(p.display_name||p.name)+' to '+altPos,col:'var(--accent2)',
          body:'Has '+altPos+' eligibility. Your '+altPos+' is thin — moving them there opens up a '+curPos+' spot. Right-click the card to move.'});
      }
    });
  });

  // ── 5. Expensive bench: dead cash vs. still-growing cash cows ────────────
  var benchVal=0, deadCash=[], growingCash=[];
  ['DEF','MID','RUC','FWD'].forEach(function(pos){
    benchPlayers(pos,grouped).forEach(function(key){
      const st=playerStats(key); if(!st||!st.price) return;
      benchVal+=st.price;
      if(st.price>700000){
        const name=getP(key)?.name||key;
        if(getPlayerPriceTrend(key)==='rising') growingCash.push(name); else deadCash.push(name);
      }
    });
  });
  if(deadCash.length){
    tips.push({pri:3,icon:'💰',title:'Dead cash on bench',col:'var(--red)',
      body:deadCash.join(', ')+' — expensive ('+fmtPrice(benchVal)+' total bench value) but not gaining value. '+
        'Not scoring for you and not making you money either. Prime downgrade targets to fund a starter upgrade.'});
  }
  if(growingCash.length){
    tips.push({pri:8,icon:'📈',title:'Cash cows still growing',col:'var(--green)',
      body:growingCash.join(', ')+' — expensive but still rising. Worth holding a little longer to squeeze out more value before cashing in.'});
  }

  // ── 6. Weak emergency cover ──────────────────────────────────────────────
  ['DEF','MID','RUC','FWD'].forEach(function(pos){
    const bp=benchPlayers(pos,grouped);
    var bestBenchAvg=0;
    bp.forEach(function(key){const st=playerStats(key);if(st&&st.avg>bestBenchAvg)bestBenchAvg=st.avg;});
    if(bp.length===0){
      tips.push({pri:4,icon:'⚠️',title:'No '+pos+' bench cover',col:'var(--red)',
        body:'You have no '+pos+' bench player. If a '+pos+' starter gets injured, you will score 0 — this is a critical risk.'});
    } else if(bestBenchAvg<65&&bp.length>0){
      tips.push({pri:5,icon:'⚠️',title:pos+' emergency is weak (avg '+bestBenchAvg.toFixed(0)+')',col:'var(--yellow)',
        body:'Your best '+pos+' bench player averages '+bestBenchAvg.toFixed(0)+'. If needed as emergency, expect a poor score. Consider upgrading bench cover.'});
    }
  });

  // ── 7. SELL candidates on field ──────────────────────────────────────────
  ['DEF','MID','RUC','FWD'].forEach(function(pos){
    starters(pos,grouped).forEach(function(key){
      const p=getP(key); if(!p) return;
      const sig=playerSignal(key,false);
      if(sig.score<35){
        tips.push({pri:6,icon:'📉',title:'Trade out: '+(p.display_name||p.name),col:'var(--red)',
          body:pos+' · Avg '+(sig.avg?sig.avg.toFixed(0):'?')+' pts · '+sig.reasons.slice(0,3).join(' · ')+'. Look for a '+pos+' upgrade.'});
      }
    });
  });

  // ── 8. Lock these in (elite scorers) ────────────────────────────────────
  var locks=[];
  ['DEF','MID','RUC','FWD'].forEach(function(pos){
    starters(pos,grouped).forEach(function(key){
      const st=playerStats(key); if(st&&st.avg>=115&&!(INJURED_SET&&INJURED_SET.has(getP(key)?.name||'')))locks.push(getP(key)?.name||key);
    });
  });
  if(locks.length){
    tips.push({pri:7,icon:'🔒',title:'Keep these starters',col:'var(--green)',
      body:locks.join(', ')+' — elite scorers (avg 115+). Don\'t trade unless injured.'});
  }

  // ── 9. Rising price — hold for value ────────────────────────────────────
  var rising=[];
  squad.forEach(function(key){if(getPlayerPriceTrend(key)==='rising'){const p=getP(key);if(p)rising.push(p.name);}});
  if(rising.length){
    tips.push({pri:8,icon:'📈',title:'Price rising — hold',col:'var(--green)',
      body:rising.join(', ')+'. Hold while price climbs, then sell at peak if form dips.'});
  }

  // ── 10. Falling price — trade soon ───────────────────────────────────────
  var falling=[];
  ['DEF','MID','RUC','FWD'].forEach(function(pos){
    starters(pos,grouped).forEach(function(key){if(getPlayerPriceTrend(key)==='falling'){const p=getP(key);if(p)falling.push(p.name);}});
  });
  if(falling.length){
    tips.push({pri:9,icon:'📉',title:'Price falling on field',col:'var(--yellow)',
      body:falling.join(', ')+' losing value each week. Trade soon if replacing anyway — don\'t hold a falling-price player you plan to trade.'});
  }

  // ── 11. Position balance ─────────────────────────────────────────────────
  var posAvgs={};
  ['DEF','MID','RUC','FWD'].forEach(function(pos){
    var s=0,c=0;
    starters(pos,grouped).forEach(function(key){const st=playerStats(key);if(st&&st.n){s+=st.avg;c++;}});
    if(c) posAvgs[pos]=s/c;
  });
  var weakPos=null,weakAvg=999;
  Object.keys(posAvgs).forEach(function(pos){if(posAvgs[pos]<weakAvg){weakAvg=posAvgs[pos];weakPos=pos;}});
  if(weakPos&&weakAvg<90){
    tips.push({pri:10,icon:'⚖️',title:'Weakest position: '+weakPos+' (avg '+weakAvg.toFixed(0)+')',col:'var(--muted)',
      body:'Your '+weakPos+' starters average '+weakAvg.toFixed(0)+' pts — below target (90+). Prioritise upgrading '+weakPos+' over other positions.'});
  }

  // ── 11b. Value pickup — cheap, rising, in-form player not in your squad ────
  var valuePick=null, valuePickL3=-1;
  PLAYERS_DATA.forEach(function(p){
    if(squad.includes(p.key)) return;
    if(!p.current_price||p.current_price>500000) return;
    if(INJURED_SET&&INJURED_SET.has(p.name)) return;
    const st=playerStats(p.key); if(!st||st.n<2) return;
    if(getPlayerPriceTrend(p.key)!=='rising') return;
    if(st.l3<75) return;
    if(st.l3>valuePickL3){valuePickL3=st.l3;valuePick=p;}
  });
  if(valuePick){
    const vst=playerStats(valuePick.key);
    const vpos=valuePick.positions&&valuePick.positions.length?posOrdered(valuePick.positions):'';
    tips.push({pri:2,icon:'💎',title:'Value pickup: '+(valuePick.display_name||getDisplayName(valuePick.name,valuePick.team)),col:'var(--accent)',
      body:fmtPrice(valuePick.current_price)+' · L3 avg '+vst.l3.toFixed(0)+' · price still rising. Cheap and in-form'+(vpos?' ('+vpos+')':'')+' — a strong cash-generation target for a bench slot.'});
  }

  // ── 12. Upcoming fixture alerts ──────────────────────────────────────────
  var hardFix=[], easyFix=[];
  squad.forEach(function(key){
    const p=getP(key); if(!p) return;
    const fix=getPlayerFixtureScore(key); if(fix==null) return;
    if(fix>=110) easyFix.push((p.display_name||p.name)+' ('+fix.toFixed(0)+')');
    if(fix<=90)  hardFix.push((p.display_name||p.name)+' ('+fix.toFixed(0)+')');
  });
  if(easyFix.length){
    tips.push({pri:11,icon:'🟢',title:'Easy fixture this week',col:'var(--green)',
      body:easyFix.join(', ')+'. Great captain options and likely to score above their avg.'});
  }
  if(hardFix.length){
    tips.push({pri:12,icon:'🔴',title:'Tough fixture',col:'var(--red)',
      body:hardFix.join(', ')+'. May score below avg. Avoid captaining — consider bench if possible.'});
  }

  // Sort and render
  tips.sort(function(a,b){return a.pri-b.pri;});
  panel.innerHTML = '<div style="font-family:\'Barlow Condensed\',sans-serif;font-weight:800;font-size:.9rem;letter-spacing:.06em;text-transform:uppercase;color:var(--text);margin-bottom:10px">💡 Team Tips</div>';
  const tipsGrid = document.createElement('div');
  tipsGrid.className = 'mt-tips-grid';
  panel.appendChild(tipsGrid);
  tips.forEach(function(tip){
    const d=document.createElement('div');
    d.style.cssText='background:var(--surface);border:1px solid var(--border);border-left:3px solid '+tip.col+';border-radius:7px;padding:10px 12px';
    d.innerHTML='<div style="font-family:\'Barlow Condensed\',sans-serif;font-weight:800;font-size:.82rem;color:'+tip.col+';margin-bottom:2px">'+tip.icon+' '+tip.title+'</div>'+
      '<div style="font-size:.73rem;color:var(--muted);line-height:1.5">'+tip.body+'</div>';
    tipsGrid.appendChild(d);
  });
  if(!tips.length){
    panel.innerHTML+='<div style="color:var(--muted);font-size:.78rem">Team looks solid — no major issues found.</div>';
  }
}

function addToMyTeam(key) {
  var squad=lsMyTeam();
  if(squad.includes(key)) return;
  if(squad.length>=30){alert('Max 30 players.');return;}
  squad.push(key); lsSet('myteam_squad',squad);
  renderMyTeam();
  document.getElementById('myteamAnalysis').style.display='none';
}

function removeFromMyTeam(key) {
  var overrides=lsMyTeamPositions();
  delete overrides[key]; lsSet('myteam_positions',overrides);
  lsSet('myteam_squad',lsMyTeam().filter(function(k){return k!==key;}));
  renderMyTeam();
  document.getElementById('myteamAnalysis').style.display='none';
}

function analyseMyTeam() {
  const squad=lsMyTeam();
  if(!squad.length){alert('Add players first.');return;}
  const budgetK=parseFloat(document.getElementById('myteamBudget').value)||0;
  const budgetDollars=budgetK*1000;
  const bodyDiv=document.getElementById('myteamAnalysisBody');
  document.getElementById('myteamAnalysis').style.display='block';
  bodyDiv.innerHTML='';
  const grouped=groupSquadByPosition(squad);

  // If no in-budget trade covers an URGENT player, check whether a squad-mate's
  // DPP (dual position) eligibility could plug the gap for free instead.
  function findDppAlternative(troublePos, troubleKey) {
    var found=null;
    squad.forEach(function(k){
      if(k===troubleKey||found) return;
      const pl=getP(k); if(!pl||!pl.positions||pl.positions.length<2) return;
      if(!pl.positions.includes(troublePos)) return;
      var curPos=null;
      ['DEF','MID','RUC','FWD'].forEach(function(pp){ if((grouped[pp]||[]).includes(k)) curPos=pp; });
      if(!curPos||curPos===troublePos) return;
      const curCfg=MT_POS_CONFIG.find(function(c){return c.pos===curPos;});
      const curGroupLen=(grouped[curPos]||[]).length;
      // Only worth suggesting if their current position has some depth to spare.
      if(curCfg&&curGroupLen<=curCfg.starters) return;
      found={key:k,player:pl,fromPos:curPos};
    });
    return found;
  }

  function findBestTrade(cfg,key,st,sig,ignoreBudget){
    var best=null,bestScore=0;
    PLAYERS_DATA.forEach(function(op){
      if(squad.includes(op.key)) return;
      if(!op.positions||!op.positions.includes(cfg.pos)) return;
      if(INJURED_SET&&INJURED_SET.has(op.name)) return; // don't suggest injured targets
      const opSt=playerStats(op.key); if(!opSt||opSt.avg<=st.avg) return;
      const cost=(opSt.price||0)-(st.price||0);
      if(!ignoreBudget&&cost>budgetDollars+20000) return;
      const gain=opSt.avg-st.avg;
      const opSig=playerSignal(op.key,false);
      const opFix=getPlayerFixtureScore(op.key);
      const myFix=getPlayerFixtureScore(key);
      var us=gain*3+(opSig.score-sig.score)*0.4;
      if(opFix!=null&&myFix!=null) us+=(opFix-myFix)*0.5;
      if(cost<=0) us+=5;
      if(us>bestScore){bestScore=us;best={player:op,opSt,cost,gain,opSig,opFix,overBudget:ignoreBudget&&cost>budgetDollars+20000};}
    });
    return best;
  }

  var recs=[];
  MT_POS_CONFIG.forEach(function(cfg){
    const players=grouped[cfg.pos]||[];
    players.forEach(function(key,idx){
      const isBench=idx>=cfg.starters;
      const p=getP(key); if(!p) return;
      const st=playerStats(key); if(!st) return;
      const sig=playerSignal(key,isBench);
      const isInj=INJURED_SET&&INJURED_SET.has(p.name);
      var urgency=100-sig.score;
      if(isBench&&st.price>900000) urgency+=15;
      if(isInj) urgency+=35;
      if(st.n===0) urgency+=30;
      urgency=Math.max(0,Math.min(100,Math.round(urgency)));
      var best=findBestTrade(cfg,key,st,sig,false);
      // Urgent and stuck for cash? Widen the search past budget so there's always
      // a concrete target to react to, rather than a dead end.
      if(!best&&urgency>=75) best=findBestTrade(cfg,key,st,sig,true);
      var dppAlt=(urgency>=75)?findDppAlternative(cfg.pos,key):null;
      if(isInj||sig.score<65||isBench||best) recs.push({key,pos:cfg.pos,cfg,isBench,p,st,sig,isInj,urgency,best,dppAlt});
    });
  });
  recs.sort(function(a,b){return b.urgency-a.urgency;});
  if(!recs.length){
    bodyDiv.innerHTML='<div style="padding:12px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;color:var(--muted)">✓ All starters look solid. No urgent changes flagged within budget.</div>';
    return;
  }
  function grade(u){
    if(u>=75) return {label:'URGENT',col:'var(--red)'};
    if(u>=55) return {label:'HIGH',col:'var(--yellow)'};
    if(u>=35) return {label:'MEDIUM',col:'var(--accent2)'};
    return {label:'LOW',col:'var(--muted)'};
  }
  const counts={URGENT:0,HIGH:0,MEDIUM:0,LOW:0};
  recs.forEach(function(r){counts[grade(r.urgency).label]++;});
  var summaryHtml='<div class="rec-summary">';
  ['URGENT','HIGH','MEDIUM','LOW'].forEach(function(g){
    if(!counts[g]) return;
    summaryHtml+='<div class="rec-summary-chip" style="color:'+grade(g==='URGENT'?100:g==='HIGH'?60:g==='MEDIUM'?40:0).col+'">'+counts[g]+' <span>'+g+'</span></div>';
  });
  summaryHtml+='<div class="rec-summary-chip" style="margin-left:auto;color:var(--text)">'+recs.length+' <span>reviewed</span></div>';
  summaryHtml+='</div>';

  // Top-priority trades: the highest-impact swaps surfaced up front, full detail, no click required.
  const topTrades=recs.filter(function(r){return r.best;}).slice(0,3);
  if(topTrades.length){
    summaryHtml+='<div class="rec-priority-label">&#9889; Top priority trades</div>';
    summaryHtml+='<div class="rec-priority-grid">';
    topTrades.forEach(function(r){
      const g=grade(r.urgency);
      const op=r.best.player,safeOp=op.key.replace(/'/g,"\\'"),opSt=r.best.opSt,safeKey=r.key.replace(/'/g,"\\'");
      const costStr=r.best.cost<=0?'<span style="color:var(--green)">saves '+fmtPrice(Math.abs(r.best.cost))+'</span>':'<span style="color:var(--muted)">+'+fmtPrice(r.best.cost)+'</span>';
      summaryHtml+='<div class="rec-priority-card">'+
        '<div class="rec-priority-head"><span class="rec-ring-sm" style="background:conic-gradient('+g.col+' '+(r.urgency*3.6)+'deg,var(--border) 0deg)"><span>'+r.urgency+'</span></span>'+
        '<span class="pos-chip '+r.cfg.cls+'">'+r.pos+(r.isBench?' B':'')+'</span><span style="margin-left:auto;font-size:.62rem;color:'+g.col+';font-weight:800;text-transform:uppercase">'+g.label+'</span></div>'+
        '<div class="rec-priority-trade">'+
          '<div><div class="rec-priority-tag">OUT</div><div class="rec-priority-name">'+(r.p.display_name||r.p.name)+'</div><div class="rec-priority-meta">avg '+r.st.avg.toFixed(1)+' · '+fmtPrice(r.st.price)+'</div></div>'+
          '<div class="rec-priority-arrow">&#8594;</div>'+
          '<div><div class="rec-priority-tag" style="color:var(--green)">IN</div><div class="rec-priority-name" style="color:var(--green);cursor:pointer" onclick="searchAndShowPlayer(\''+safeOp+'\')">'+(op.display_name||op.name)+'</div><div class="rec-priority-meta">avg '+opSt.avg.toFixed(1)+' <span style="color:var(--green)">+'+r.best.gain.toFixed(1)+'</span></div></div>'+
        '</div>'+
        '<div class="rec-priority-foot">'+costStr+'<button class="pill-btn pill-in" onclick="addToList(\'tradeIn\',\''+safeOp+'\');addToList(\'tradeOut\',\''+safeKey+'\');showPage(\'trading\',document.querySelectorAll(\'.nav-btn\')[6])">&#8594; Trade</button></div>'+
      '</div>';
    });
    summaryHtml+='</div>';
  }
  bodyDiv.innerHTML=summaryHtml;

  recs.forEach(function(r,rank){
    const g=grade(r.urgency);
    const safeKey=r.key.replace(/'/g,"\\'");
    const trendCol=r.sig.trend==='rising'?'var(--green)':r.sig.trend==='falling'?'var(--red)':'var(--muted)';
    const trendTxt=r.sig.trend==='rising'?'↑ rising':r.sig.trend==='falling'?'↓ falling':'→ stable';
    const rowId='rec_'+rank;
    var summary='<div class="rec-item">';
    summary+='<div class="rec-row" onclick="toggleCollapse(\''+rowId+'\')">';
    summary+='<span class="rec-ring-sm" style="background:conic-gradient('+g.col+' '+(r.urgency*3.6)+'deg,var(--border) 0deg)"><span>'+r.urgency+'</span></span>';
    summary+='<div class="rec-main">';
    summary+='<div class="rec-name">'+(r.p.display_name||r.p.name)+' <span class="pos-chip '+r.cfg.cls+'">'+r.pos+(r.isBench?' B':'')+'</span></div>';
    summary+='<div class="rec-sub" style="color:'+g.col+'">'+g.label+'</div><div class="rec-sub">'+r.sig.label+(r.best?(r.best.overBudget?' · upgrade found (over budget)':' · upgrade found'):'')+(r.dppAlt?' · 🔄 DPP fix':'')+'</div>';
    summary+='</div>';
    summary+='<span class="stats-collapse-arrow" id="'+rowId+'_arrow">&#9660;</span>';
    summary+='</div>';

    var detail='<div class="stats-collapse-body" id="'+rowId+'_body"><div style="padding:10px 0 2px">';
    detail+='<div style="display:flex;align-items:center;gap:5px;flex-wrap:wrap;margin-bottom:5px">';
    detail+='<span style="font-weight:700;font-size:.9rem;cursor:pointer" onclick="searchAndShowPlayer(\''+safeKey+'\')">'+(r.p.display_name||r.p.name)+'</span>';
    detail+=teamTagHtml(r.p.team);
    if(r.isInj){
      const rTag = statusLabel(r.p.name);
      detail += rTag==='SUS' ? '<span style="color:var(--yellow);font-weight:700;font-size:.72rem">🚫 SUSPENDED</span>' : '<span style="color:var(--red);font-weight:700;font-size:.72rem">🚑 INJURED</span>';
    }
    detail+='</div>';
    detail+='<div style="display:flex;gap:8px;flex-wrap:wrap;font-size:.77rem;margin-bottom:3px">';
    detail+='<span>Avg <b>'+r.st.avg.toFixed(1)+'</b></span><span>L3 <b style="color:'+(r.st.l3>r.st.avg+5?'var(--green)':r.st.l3<r.st.avg-5?'var(--red)':'var(--text)')+'">'+r.st.l3.toFixed(1)+'</b></span>';
    detail+='<span>'+fmtPrice(r.st.price)+'</span>';
    if(r.st.fr!=null) detail+='<span>Form <b style="color:'+ratingColor(r.st.fr)+'">'+r.st.fr+'/100</b></span>';
    detail+='<span style="color:'+trendCol+'">'+trendTxt+'</span>';
    detail+='</div>';
    if(r.sig.reasons&&r.sig.reasons.length) detail+='<div style="font-size:.7rem;color:var(--muted);margin-bottom:5px">'+r.sig.reasons.map(function(s){return '• '+s;}).join('  ')+'</div>';
    if(r.isBench&&r.st.price>900000){
      const trend=getPlayerPriceTrend(r.key);
      const stillGrowing=trend==='rising';
      detail+='<div style="font-size:.7rem;color:var(--yellow);margin-bottom:5px">⚠ '+fmtPrice(r.st.price)+' on the bench'+(stillGrowing?' — still rising, but ask if it will out-earn a scoring upgrade.':' and not gaining value — dead cash. Prime downgrade target.')+'</div>';
    }
    if(r.best){
      const op=r.best.player,safeOp=op.key.replace(/'/g,"\\'"),opSt=r.best.opSt;
      const myFix=getPlayerFixtureScore(r.key),opFixN=r.best.opFix;
      const fixNote=opFixN!=null&&myFix!=null?' · fix '+(opFixN>myFix+2?'<span style="color:var(--green)">easier ↑</span>':opFixN<myFix-2?'<span style="color:var(--red)">harder ↓</span>':'similar'):'';
      const costStr=r.best.cost<=0?'<span style="color:var(--green)">saves '+fmtPrice(Math.abs(r.best.cost))+'</span>':'<span style="color:var(--muted)">+'+fmtPrice(r.best.cost)+'</span>';
      if(r.best.overBudget) detail+='<div style="font-size:.68rem;color:var(--yellow);margin-top:4px">⚠ Best available upgrade exceeds your entered budget — shown anyway since this is urgent.</div>';
      detail+='<div style="display:flex;align-items:center;gap:6px;padding:7px 9px;background:var(--surface2);border:1px solid var(--border);border-radius:6px;margin-top:5px;flex-wrap:wrap">';
      detail+='<div style="flex:1;min-width:100px"><div style="font-size:.57rem;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.04em">OUT</div><div style="font-weight:700;font-size:.82rem">'+(r.p.display_name||r.p.name)+'</div><div style="font-size:.68rem;color:var(--muted)">'+fmtPrice(r.st.price)+' · avg '+r.st.avg.toFixed(1)+'</div></div>';
      detail+='<div style="color:var(--muted);font-size:1rem">→</div>';
      detail+='<div style="flex:1;min-width:100px"><div style="font-size:.57rem;color:var(--green);font-weight:700;text-transform:uppercase;letter-spacing:.04em">IN</div><div style="font-weight:700;font-size:.82rem;cursor:pointer;color:var(--green)" onclick="searchAndShowPlayer(\''+safeOp+'\')">'+(op.display_name||op.name)+'</div><div style="font-size:.68rem;color:var(--muted)">'+fmtPrice(opSt.price)+' · avg '+opSt.avg.toFixed(1)+' <span style="color:var(--green)">+'+r.best.gain.toFixed(1)+'</span>'+fixNote+'</div></div>';
      detail+='<div style="display:flex;flex-direction:column;align-items:flex-end;gap:3px;flex-shrink:0">'+costStr+'<button class="pill-btn pill-in" onclick="event.stopPropagation();addToList(\'tradeIn\',\''+safeOp+'\');addToList(\'tradeOut\',\''+safeKey+'\');showPage(\'trading\',document.querySelectorAll(\'.nav-btn\')[6])" style="font-size:.6rem;white-space:nowrap">→ Trade</button></div>';
      detail+='</div>';
    } else if(r.urgency>=40){
      detail+='<div style="font-size:.72rem;color:var(--muted);padding:5px 8px;background:var(--surface2);border-radius:5px;margin-top:4px">No upgrade target found anywhere in the player pool — consider downgrade to free cash.</div>';
    }
    if(r.dppAlt){
      const dp=r.dppAlt.player,safeDp=dp.key.replace(/'/g,"\\'");
      detail+='<div style="display:flex;align-items:center;gap:8px;padding:7px 9px;background:rgba(59,130,246,.08);border:1px solid rgba(59,130,246,.25);border-radius:6px;margin-top:6px;flex-wrap:wrap">'+
        '<span style="font-size:1rem">🔄</span>'+
        '<div style="flex:1;min-width:140px;font-size:.72rem;color:var(--text)">Free fix: <b style="cursor:pointer;color:var(--accent2)" onclick="searchAndShowPlayer(\''+safeDp+'\')">'+(dp.display_name||dp.name)+'</b> is DPP-eligible for '+r.pos+' and currently sits in '+r.dppAlt.fromPos+', which has spare depth. Right-click their card on the field to move them here — no trade needed.</div>'+
      '</div>';
    }
    detail+='</div></div>';
    bodyDiv.innerHTML+=summary+detail+'</div>';
  });
}

// Rolling 22
function renderRolling22() {
  const grid=document.getElementById('rolling22Grid');
  if(!grid) return;
  grid.innerHTML='';
  const POS=[
    {pos:'DEF',starters:6,bench:2,color:'#93c5fd',label:'Defenders'},
    {pos:'MID',starters:8,bench:2,color:'#6ee7b7',label:'Midfielders'},
    {pos:'RUC',starters:2,bench:1,color:'#fcd34d',label:'Rucks'},
    {pos:'FWD',starters:6,bench:2,color:'#fca5a5',label:'Forwards'},
  ];
  // Same "projected average for the rest of the season" used by Targets -> Premiums
  // and the Player Stats fixture chart — Rolling 22 used to have its own bespoke
  // Overall/Form-weighted/Fixture-adjusted scoring that didn't match those, which is
  // why the numbers looked inconsistent across the app. One shared metric now.
  function r22Score(p) {
    if(!p.history||!p.history.length) return -1;
    if(INJURED_SET&&INJURED_SET.has(p.name)) return -1;
    const r=restOfSeasonAvg(p);
    return r?r.avg:-1;
  }
  // DPP-aware selection, in ONE pass ordered by score (highest first): each player —
  // single-position or dual — grabs a slot in whichever eligible position is scarcest
  // at the moment they're reached. Single-position players used to get an unconditional
  // first pass ahead of ALL dual-position players regardless of score, which meant a
  // mediocre single-position player could fill the last spot in a position before a much
  // better dual-position player (like a red-hot MID/FWD) ever got a chance to compete —
  // that player then had nowhere left to go in EITHER position and vanished off the team
  // entirely (not even bench), which is why hot players were showing up only "on the
  // bubble" instead of selected. Processing everyone together by score fixes that.
  const eligPool=PLAYERS_DATA.filter(function(p){
    return p.positions&&p.positions.length&&p.history&&p.history.length>=1&&r22Score(p)>=0;
  });
  eligPool.forEach(function(p){ p._r22ms=r22Score(p); });
  const slotsFor={}; POS.forEach(function(cfg){ slotsFor[cfg.pos]=cfg.starters+cfg.bench; });
  const assignedMap={}; POS.forEach(function(cfg){ assignedMap[cfg.pos]=[]; });
  const used=new Set();

  eligPool.slice().sort(function(a,b){return b._r22ms-a._r22ms;}).forEach(function(p){
    const open=p.positions.filter(function(pos){return assignedMap[pos].length<slotsFor[pos];});
    if(!open.length) return;
    var chosen=open[0];
    if(open.length>1){
      var bestScarcity=Infinity;
      open.forEach(function(pos){
        const remainingSupply=eligPool.filter(function(x){
          return x.positions.includes(pos)&&!used.has(x.key)&&x.key!==p.key;
        }).length;
        const remainingNeed=slotsFor[pos]-assignedMap[pos].length;
        const scarcity=remainingSupply-remainingNeed;
        if(scarcity<bestScarcity){bestScarcity=scarcity;chosen=pos;}
      });
    }
    assignedMap[chosen].push(p);used.add(p.key);
  });

  // Improvement pass: the scarcity heuristic above picks a position for a dual-eligible
  // player in isolation, but that's not always the best spot for the TEAM overall. If
  // moving a dual-position player to their other position lets a stronger player
  // backfill the slot they left, the swap is worth it even if it doesn't look like it
  // from that one player's perspective alone — e.g. a MID/FWD player sitting in MID
  // should move to FWD if a better replacement is waiting to take their MID spot,
  // since that upgrades MID for free and doesn't cost FWD anything but a bench-level
  // player who was barely making the cut. The player's own score cancels out of the
  // ledger either way, so the swap is worth it exactly when: (best available backfill
  // for their old position) > (weakest player they'd bump out of the new position, or
  // nothing if that position has a spare slot).
  function currentPosOf(pkey) {
    for (var pos in assignedMap) { if (assignedMap[pos].some(function(x){return x.key===pkey;})) return pos; }
    return null;
  }
  var swapped=true, guard=0;
  while (swapped && guard<200) {
    swapped=false; guard++;
    var dualPlayers=eligPool.filter(function(p){return p.positions.length>1&&used.has(p.key);})
      .sort(function(a,b){return b._r22ms-a._r22ms;});
    for (var di=0; di<dualPlayers.length && !swapped; di++) {
      var p=dualPlayers[di];
      var curPos=currentPosOf(p.key);
      if (!curPos) continue;
      var altPositions=p.positions.filter(function(pos){return pos!==curPos;});
      for (var ai=0; ai<altPositions.length && !swapped; ai++) {
        var altPos=altPositions[ai];
        var backfill=eligPool.filter(function(x){
          return x.positions.includes(curPos)&&!used.has(x.key)&&x.key!==p.key;
        }).sort(function(a,b){return b._r22ms-a._r22ms;})[0];
        if (!backfill) continue;
        var altGroup=assignedMap[altPos];
        var altFull=altGroup.length>=slotsFor[altPos];
        var worstInAlt=altFull?altGroup.reduce(function(min,x){return x._r22ms<min._r22ms?x:min;}):null;
        var bumpedScore=worstInAlt?worstInAlt._r22ms:-Infinity;
        if (backfill._r22ms>bumpedScore) {
          assignedMap[curPos]=assignedMap[curPos].filter(function(x){return x.key!==p.key;});
          assignedMap[curPos].push(backfill); used.add(backfill.key);
          if (worstInAlt) { assignedMap[altPos]=assignedMap[altPos].filter(function(x){return x.key!==worstInAlt.key;}); used.delete(worstInAlt.key); }
          assignedMap[altPos].push(p);
          swapped=true;
        }
      }
    }
  }

  var totalAvg=0,totalCount=0;
  POS.forEach(function(cfg){
    const total=cfg.starters+cfg.bench;
    const elig=assignedMap[cfg.pos].slice().sort(function(a,b){return b._r22ms-a._r22ms;});
    const bubble=eligPool.filter(function(p){
      return p.positions.includes(cfg.pos)&&!used.has(p.key);
    }).sort(function(a,b){return b._r22ms-a._r22ms;}).slice(0,2); // just missed the cut for this position

    const sec=document.createElement('div'); sec.className='pitch-pos-row';
    const lbl=document.createElement('div');
    lbl.className='pitch-pos-label';
    lbl.style.background=cfg.color;
    lbl.textContent=cfg.label;
    sec.appendChild(lbl);

    const rowWrap=document.createElement('div');
    const meta=document.createElement('div');
    meta.className='pitch-pos-meta';
    meta.innerHTML=Math.min(elig.length,total)+'/'+total;
    rowWrap.appendChild(meta);

    const startersGrid=document.createElement('div'); startersGrid.className='pitch-cards';
    const benchGrid=document.createElement('div'); benchGrid.className='pitch-cards pitch-bench';

    elig.forEach(function(p,i){
      const isBench=i>=cfg.starters;
      const row=isBench?benchGrid:startersGrid;
      const sc=p.history.map(function(x){return x.score;}); const n=sc.length;
      const avg=n?+(sc.reduce(function(a,b){return a+b;},0)/n).toFixed(1):0;
      const ms=p._r22ms;
      const msDisp=+ms.toFixed(1);
      const safeKey=p.key.replace(/'/g,"\\'");
      const avgCol='var(--text)';
      if(!isBench&&n){totalAvg+=ms>0?ms:avg;totalCount++;}
      const card=document.createElement('div');
      card.classList.add('r22-card');
      const tCol2=teamColor(p.team);
      card.style.cssText='background:'+(isBench?'rgba(var(--overlay-rgb),.02)':'var(--surface2)')+';border:1px solid '+(isBench?'rgba(var(--overlay-rgb),.07)':'var(--border)')+';border-radius:8px;padding:9px 8px 7px;position:relative;overflow:hidden;min-height:78px;display:flex;flex-direction:column;gap:1px;transition:transform var(--dur) var(--ease),box-shadow var(--dur) var(--ease),border-color var(--dur) var(--ease)';
      const isWatched = lsGet('starred',[]).includes(p.key);
      card.innerHTML='<div style="position:absolute;top:0;left:0;right:0;height:3px;background:'+tCol2+'"></div>'+
        '<div style="display:flex;align-items:center;gap:5px">' +
          '<div style="width:19px;height:19px;border-radius:50%;flex-shrink:0;background:'+tCol2+';display:flex;align-items:center;justify-content:center;font-size:.58rem;font-weight:800;font-family:\'Barlow Condensed\',sans-serif;color:#0d0f1a">'+(p.display_name||p.name).charAt(0).toUpperCase()+'</div>'+
          '<div style="font-size:.52rem;font-weight:800;font-family:\'Barlow Condensed\',sans-serif;color:'+cfg.color+';opacity:.95">'+cfg.pos+(isBench?' B':'')+'</div>'+
          '<button onclick="toggleR22Watch(\''+safeKey+'\',this)" style="margin-left:auto;background:none;border:none;cursor:pointer;font-size:.75rem;opacity:'+(isWatched?'1':'0.3')+';line-height:1" title="Add to Watchlist">'+(isWatched?'★':'☆')+'</button>'+
        '</div>'+
        '<div style="font-weight:700;font-size:.78rem;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:4px" onclick="searchAndShowPlayer(\''+safeKey+'\')" title="'+(p.display_name||p.name)+'">'+(p.display_name||p.name)+'</div>'+
        '<div style="font-size:.6rem;color:var(--muted)">'+p.team+'</div>'+
        '<div style="display:flex;align-items:baseline;gap:3px;margin-top:2px">'+
          '<span style="font-family:\'Barlow Condensed\',sans-serif;font-weight:800;font-size:1.05rem;color:'+avgCol+'">'+msDisp+'</span>'+
          '<span style="font-size:.6rem;color:var(--muted)">season '+avg+'</span>'+
        '</div>'+
        '<div style="font-size:.58rem;color:var(--muted)">'+fmtPrice(p.current_price)+'</div>';
      row.appendChild(card);
    });
    for(var i=elig.length;i<total;i++){
      const isBench2=i>=cfg.starters;
      const e=document.createElement('div');
      e.style.cssText='border:1px dashed rgba(var(--overlay-rgb),.08);border-radius:7px;display:flex;align-items:center;justify-content:center;min-height:72px;color:rgba(var(--overlay-rgb),.15);font-size:.68rem;font-family:"Barlow Condensed",sans-serif';
      e.textContent='No data';
      (isBench2?benchGrid:startersGrid).appendChild(e);
    }
    rowWrap.className = 'pitch-row-flex';
    const startersCol=document.createElement('div'); startersCol.className='pitch-starters-col';
    startersCol.appendChild(startersGrid);
    rowWrap.appendChild(startersCol);
    if (cfg.bench > 0) {
      const benchCol=document.createElement('div'); benchCol.className='pitch-bench-col';
      const benchLbl=document.createElement('div'); benchLbl.className='pitch-bench-label'; benchLbl.textContent='Bench';
      benchCol.appendChild(benchLbl);
      benchCol.appendChild(benchGrid);
      rowWrap.appendChild(benchCol);
    }
    sec.appendChild(rowWrap);

    if (bubble.length) {
      const bw = document.createElement('div');
      bw.className = 'r22-bubble';
      bw.innerHTML = '<span class="r22-bubble-label">On the bubble</span>' + bubble.map(function(bp) {
        const bsc = bp.history.map(function(x){return x.score;}); const bn = bsc.length;
        const bavg = bn ? (bsc.reduce(function(a,b){return a+b;},0)/bn).toFixed(1) : '0';
        const safeBKey = bp.key.replace(/'/g,"\\'");
        return '<span class="r22-bubble-chip" onclick="searchAndShowPlayer(\''+safeBKey+'\')">'+(bp.display_name||bp.name)+' <b>'+bavg+'</b></span>';
      }).join('');
      sec.appendChild(bw);
    }
    grid.appendChild(sec);
  });
}

function toggleR22Watch(key, btn) {
  var starred = lsGet('starred', []);
  if (starred.includes(key)) {
    starred = starred.filter(function(k){ return k !== key; });
    if(btn){ btn.textContent='☆'; btn.style.opacity='0.3'; }
  } else {
    starred.push(key);
    if(btn){ btn.textContent='★'; btn.style.opacity='1'; }
  }
  lsSet('starred', starred);
  if(typeof renderStarredList === 'function') renderStarredList();
}

// My Team search
(function(){
  const inp=document.getElementById('myteamSearch');
  const res=document.getElementById('myteamResults');
  if(!inp) return;
  inp.addEventListener('input',function(){
    const q=inp.value.toLowerCase().trim();
    if(!q){res.style.display='none';return;}
    const squad=lsMyTeam();
    const matches=PLAYERS_DATA.filter(function(p){
      return ((p.display_name||p.name).toLowerCase().includes(q)||p.name.toLowerCase().includes(q))&&!squad.includes(p.key);
    }).slice(0,10);
    res.innerHTML=matches.map(function(p){
      const posStr=p.positions&&p.positions.length?posOrdered(p.positions)+' · ':'';
      const st=playerStats(p.key);
      const avgStr=st&&st.n?' · avg '+st.avg.toFixed(1):'';
      const injBadge=INJURED_SET&&INJURED_SET.has(p.name)?' 🚑 INJ':'';
      return '<div class="search-result" onclick="addToMyTeam(\''+p.key.replace(/'/g,"\\'")+'\');this.closest(\'.search-results\').style.display=\'none\';document.getElementById(\'myteamSearch\').value=\'\'">'+
        '<span>'+(p.display_name||getDisplayName(p.name,p.team))+injBadge+'</span>'+
        '<span class="sr-sub">'+posStr+p.team+avgStr+' · '+fmtPrice(p.current_price)+'</span>'+
      '</div>';
    }).join('');
    res.style.display=matches.length?'block':'none';
  });
  document.addEventListener('click',function(e){
    if(!e.target.closest('#myteamSearch')&&!e.target.closest('#myteamResults')) res.style.display='none';
  });
})();
</script>
</body>
</html>"""


def generate_app_html(all_rounds, players_registry, fixture, current_round):
    current_prices, injured_set, suspended_set = parse_current_round(CURRENT_ROUND_FILE)
    leaderboard      = build_leaderboard(all_rounds, current_prices)
    rounds_data      = build_rounds_data(all_rounds)
    players_data     = build_players_data(all_rounds, current_prices, players_registry)
    cba_rows = parse_cba_file(CBA_FILE)
    if cba_rows: attach_cba_data(players_data, cba_rows)
    champion_by_round = load_champion_round_data(CHAMPION_DATA_FOLDER)
    if champion_by_round: attach_round_stats(players_data, champion_by_round)
    compute_advanced_averages(players_data)
    compute_player_archetypes(players_data)
    archetype_team_notes = compute_archetype_team_weaknesses(players_data)
    overall_diff, pos_diff, afl_avg = build_team_difficulty(all_rounds, players_registry)
    lb_history       = build_leaderboard_history(all_rounds)
    upcoming_diff, upcoming_afl_avg, upcoming_afl_avg_pos = build_upcoming_fixture_difficulty(
        fixture, all_rounds, players_registry, current_round
    )

    name_counts = defaultdict(int)
    for p in players_data: name_counts[p["name"]] += 1
    duplicate_names_set = {n for n,c in name_counts.items() if c > 1}
    for p in players_data:
        p["display_name"] = f"{p['name']} ({p['team']})" if p["name"] in duplicate_names_set else p["name"]
        scores = [h["score"] for h in p["history"]]
        p["form_rating"]   = compute_form_rating(scores)
        p["consistency"]   = compute_consistency(scores)
        p["is_injured"]    = p["name"] in injured_set
        p["is_suspended"]  = p["name"] in suspended_set

    # Mark injured/suspended in leaderboard
    lb_name_counts = defaultdict(int)
    for e in leaderboard: lb_name_counts[e["player"]] += 1
    for e in leaderboard:
        e["display_name"] = f"{e['player']} ({e['team']})" if lb_name_counts[e["player"]] > 1 else e["player"]
        e["is_injured"]   = e["player"] in injured_set
        e["is_suspended"] = e["player"] in suspended_set

    html = HTML_TEMPLATE
    html = html.replace('__LEADERBOARD__',        json.dumps(leaderboard))
    html = html.replace('__ROUNDS_DATA__',        json.dumps(rounds_data))
    html = html.replace('__PLAYERS_DATA__',       json.dumps(players_data))
    html = html.replace('__ARCHETYPE_TEAM_NOTES__', json.dumps(archetype_team_notes))
    html = html.replace('__ROUNDS_LOADED__',      json.dumps(sorted(all_rounds.keys())))
    html = html.replace('__OVERALL_DIFF__',       json.dumps(overall_diff))
    html = html.replace('__POS_DIFF__',           json.dumps(pos_diff))
    html = html.replace('__AFL_AVG__',            json.dumps(afl_avg))
    html = html.replace('__LB_HISTORY__',         json.dumps(lb_history))
    html = html.replace('__UPCOMING_DIFF__',      json.dumps(upcoming_diff))
    html = html.replace('__UPCOMING_AFL_AVG__',   json.dumps(upcoming_afl_avg))
    html = html.replace('__UPCOMING_AFL_AVG_POS__', json.dumps(upcoming_afl_avg_pos))
    html = html.replace('__CURRENT_ROUND__',      json.dumps(current_round))
    html = html.replace('__INJURED_SET__',        json.dumps(list(injured_set)))
    html = html.replace('__SUSPENDED_SET__',      json.dumps(list(suspended_set)))
    html = html.replace('__LAST_UPDATED__',       datetime.now().strftime('%d %b %Y, %I:%M %p'))
    return html


def main():
    fixture = parse_fixture_file(FIXTURE_FILE)
    if not fixture:
        print(f"\n⚠️  No fixture loaded. Make sure '{FIXTURE_FILE}' exists.\n")

    all_rounds = load_all_rounds(ROUNDS_FOLDER, fixture)
    if not all_rounds:
        print("\n⚠️  No rounds loaded. Add .txt files to the 'rounds/' folder.\n")
        return

    # Auto-detect current round: the highest round number with data loaded.
    # Upcoming fixture starts from the round AFTER this.
    auto_current_round = max(all_rounds.keys())
    print(f"ℹ️  Auto-detected current round: {auto_current_round} (override CURRENT_ROUND constant to force a different value)")

    players_registry = parse_players_file(PLAYERS_FILE)
    if not players_registry:
        print("ℹ️  No players.txt found — position-based difficulty and registry players unavailable.")

    html = generate_app_html(all_rounds, players_registry, fixture, auto_current_round)
    with open("index.html","w",encoding="utf-8") as f: f.write(html)
    try:
        import webbrowser
        webbrowser.open("index.html")
    except Exception:
        pass
    print(f"\n✅  Generated index.html (Current Round: {auto_current_round}).\n")


if __name__ == "__main__":
    main()