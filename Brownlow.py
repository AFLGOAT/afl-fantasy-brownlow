"""
AFL Fantasy Brownlow Calculator - FIXED VERSION
Changes from previous:
- BUGFIX: Vote Race showed incorrect cumulative DT (e.g. John Noble +6 votes R9→R10)
  Root cause: build_leaderboard_history accumulated dt_totals inside the round loop
  without a per-round deduplication guard, so past scores were re-added each round.
  Fix: use a seen set per round, only add each player's score once per round.
- Upcoming Fixture: now matches Historical card format with predicted avg pts and
  ▲/▼ difficulty descriptor. 6-column grid (minmax 160px).
- Trading Centre: visual overhaul — position color badges, inline stats on player
  chips, smarter summary panel, improved bookmarks UX.
"""

import os, re, json, math
from collections import defaultdict

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
    "RIC":"Tigers","STK":"Saints","WCE":"Eagles","WB":"Bulldogs","WBD":"Bulldogs",
    "ADE":"Crows","ADEL":"Crows",
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
    """Parse players.txt. Supports two formats:
    Format A (team-grouped):
      TEAM NAME
      Player Name  POSITION  $PRICE
    Format B (header row):
      PLAYER  POSITION  STARTING PRICE
      Player Name  POSITION  $PRICE  (team detected from separate team headers)
    Also handles MID/FWD dual-position entries.
    """
    if not os.path.exists(filepath): return []
    players = []
    current_team = None
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            parts = [p.strip() for p in line.split("\t")]
            # Skip empty lines
            if not parts[0]: continue
            # Skip header rows
            if parts[0].upper() in ("PLAYER", "NAME"): continue
            # Detect team line: single non-empty cell with no price/position
            if len(parts) == 1 or (len(parts) >= 1 and not parts[1] if len(parts) > 1 else True):
                maybe_team = normalise_team(parts[0])
                if maybe_team != parts[0] or parts[0].upper() == parts[0]:
                    current_team = normalise_team(parts[0])
                    continue
            if len(parts) >= 1 and parts[0]:
                name = parts[0].strip()
                pos_str   = parts[1].strip() if len(parts) > 1 else ""
                price_str = parts[2].strip() if len(parts) > 2 else ""
                # Skip if pos_str looks like a team name (no slash, all caps, short)
                positions = []
                if pos_str and not pos_str.startswith("$"):
                    positions = [p.strip() for p in re.split(r"[/,]", pos_str) if p.strip()]
                    # Validate positions are AFL positions
                    valid_pos = {"DEF","MID","RUC","FWD","FWD/MID","MID/FWD","DEF/MID","MID/DEF","RUC/FWD","FWD/RUC"}
                    positions = [p for p in positions if p.upper() in {"DEF","MID","RUC","FWD"}]
                price = None
                if price_str:
                    try: price = int(price_str.replace("$","").replace(",","").strip())
                    except: pass
                if not price and pos_str.startswith("$"):
                    try: price = int(pos_str.replace("$","").replace(",","").strip())
                    except: pass
                if name and current_team:
                    players.append({"name":name,"team":current_team,"positions":positions,"starting_price":price})
    return players

def detect_format(lines):
    for line in lines:
        line = line.strip()
        if re.match(r"^(.+?):\s*\d+\.\d+\.\d+\s*$", line): return "fanfooty"
        if line.upper() == "FIXTURE": return "footywire_old"
        if re.match(r"^\d+\t.+\t.+\t\$[\d,]+\t\$[\d,]+\t\d+\t[\d.]+$", line): return "footywire"
    return None

def clean_name(name):
    return re.sub(r'\s+(INJ|Injured|Susp|Suspended|Out|Omitted)$', '', name.strip(), flags=re.IGNORECASE).strip()

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
    """Returns (current_prices dict, injured_set).
    Injured players have 'INJ', 'Injured', 'Susp', 'Suspended', or 'Out'
    appended to their name in the raw data before clean_name strips it."""
    current_prices = {}
    injured_set = set()
    if not os.path.exists(filepath): return current_prices, injured_set
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
        # Detect injury flag BEFORE cleaning name
        if re.search(r'\s+(INJ|Injured|Susp|Suspended|Out|Omitted)$', raw_name, re.IGNORECASE):
            injured_set.add(clean_name(raw_name))
        name = clean_name(raw_name)
        price = parse_price(parts[4].strip())
        if name and price: current_prices[name] = price
    return current_prices, injured_set

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
    pos_lookup = {}
    sp_lookup  = {}
    for p in players_registry:
        pos_lookup[p["name"]]  = p["positions"]
        sp_lookup[p["name"]]   = p["starting_price"]
    pre_prices = {}
    for rn in sorted_rounds:
        for p in all_rounds[rn]["all_players"]:
            key = make_player_key(p["player"], p["team"])
            if key not in pre_prices: pre_prices[key] = {}
            pre_prices[key][rn] = p.get("price")
    player_data = {}
    for rn in sorted_rounds:
        for p in all_rounds[rn]["all_players"]:
            key = make_player_key(p["player"], p["team"])
            if key not in player_data:
                player_data[key] = {
                    "name":p["player"],"team":p["team"],"key":key,
                    "history":[],"current_price":current_prices.get(p["player"]),
                    "positions": pos_lookup.get(p["player"], []),
                    "starting_price": sp_lookup.get(p["player"])
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
            player_data[key]["history"].append({
                "round":rn,"score":p["score"],
                "pre_price":pre_price,"post_price":post_price,"votes":votes
            })
    existing_names = {v["name"] for v in player_data.values()}
    for rp in players_registry:
        if rp["name"] not in existing_names:
            key = make_player_key(rp["name"], rp["team"])
            if key not in player_data:
                player_data[key] = {
                    "name":rp["name"],"team":rp["team"],"key":key,
                    "history":[],"current_price":current_prices.get(rp["name"]),
                    "positions":rp["positions"],
                    "starting_price":rp["starting_price"]
                }
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

def compute_form_rating(scores, current_price):
    if not scores or current_price is None or current_price == 0: return None
    weights = [1.5**i for i in range(len(scores))]
    weighted_avg = sum(s*w for s,w in zip(scores, weights)) / sum(weights)
    value_per_k  = weighted_avg / (current_price / 1000)
    baseline     = 0.1
    raw          = (value_per_k / baseline) * 50
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
<title>AFL Fantasy Brownlow</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;600;700;800&family=Barlow:wght@400;500;600&display=swap');
:root {
  --bg:#0d0f1a; --surface:#141726; --surface2:#1c2035;
  --border:rgba(255,255,255,0.07); --accent:#e8a020; --accent2:#3b82f6;
  --red:#f87171; --green:#34d399; --yellow:#fbbf24;
  --silver:#c0c0c0; --bronze:#cd7f32;
  --text:#e8eaf0; --muted:#6b7280;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden}
body{background:var(--bg);color:var(--text);font-family:'Barlow',sans-serif;display:flex;flex-direction:column}
header{display:flex;align-items:center;background:var(--surface);border-bottom:1px solid var(--border);flex-shrink:0}
.logo{padding:0 24px;height:56px;display:flex;align-items:center;gap:8px;font-weight:800;font-size:1.15rem;letter-spacing:.04em;color:var(--accent);white-space:nowrap;border-right:1px solid var(--border)}
.logo span{color:var(--text);font-weight:600}
nav{display:flex;flex:1}
.nav-btn{padding:0 12px;height:56px;border:none;background:transparent;color:var(--muted);font-weight:700;font-size:.88rem;letter-spacing:.05em;text-transform:uppercase;cursor:pointer;border-bottom:3px solid transparent;transition:all .2s;border-right:1px solid var(--border)}
.nav-btn:hover{color:var(--text);background:rgba(255,255,255,.03)}
.nav-btn.active{color:var(--accent);border-bottom-color:var(--accent);background:rgba(232,160,32,.06)}
.rounds-badge{margin-left:auto;padding:0 20px;height:56px;display:flex;align-items:center;font-size:.75rem;color:var(--muted);border-left:1px solid var(--border);white-space:nowrap}
main{flex:1;overflow:hidden;position:relative}
.page{position:absolute;inset:0;overflow-y:auto;padding:20px 24px;display:none}
.page.active{display:block}
#page-leaderboard{padding:14px 0}
.std-table{width:100%;border-collapse:collapse}
.std-table th{text-align:left;padding:9px 12px;font-size:.7rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border);font-weight:600;white-space:nowrap}
.std-table td{padding:9px 12px;border-bottom:1px solid var(--border);font-size:.95rem}
.std-table tr:hover td{background:rgba(255,255,255,.02)}
.ta-r{text-align:right}
.player-link{font-weight:700;cursor:pointer;color:var(--text)}
.player-link:hover{color:var(--accent);text-decoration:underline}
.team-tag{display:inline-block;padding:1px 6px;border-radius:3px;background:var(--surface2);font-size:.7rem;color:var(--muted);font-family:'Barlow',sans-serif}
.pos-badge{display:inline-block;padding:1px 6px;border-radius:3px;background:rgba(59,130,246,.18);font-size:.7rem;color:#93c5fd;font-weight:700}
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
.search-result:hover{background:rgba(255,255,255,.05);color:var(--accent)}
.search-result .sr-sub{font-size:.74rem;color:var(--muted)}
.player-card{display:none}
.player-card.active{display:block}
.pc-header{margin-bottom:16px;display:flex;align-items:flex-start;gap:14px}
.pc-name{font-weight:800;font-size:1.9rem;line-height:1.1}
.pc-sub{color:var(--muted);font-size:.85rem;margin-top:4px}
.bookmark-btn{background:none;border:none;cursor:pointer;padding:4px;display:flex;align-items:center;opacity:.4;transition:opacity .15s,filter .15s;flex-shrink:0;margin-top:6px}
.bookmark-btn:hover{opacity:.75}
.bookmark-btn.bookmarked{opacity:1;filter:drop-shadow(0 0 5px var(--accent))}
.bookmark-btn svg{width:28px;height:28px}
.stats-row{display:flex;gap:8px;margin-bottom:20px;overflow-x:auto;padding-bottom:2px}
.stat-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:9px 12px;flex:1;min-width:88px}
.stat-label{font-size:.6rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin-bottom:2px;white-space:nowrap}
.stat-value{font-weight:800;font-size:1.35rem;white-space:nowrap}
.rating-bar-wrap{margin-top:4px;height:3px;background:var(--surface2);border-radius:2px;overflow:hidden}
.rating-bar{height:100%;border-radius:2px}
.chart-section{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:20px;margin-bottom:14px}
.chart-title{font-weight:700;font-size:.75rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:14px}
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
.diff-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}
@media(max-width:1100px){.diff-grid{grid-template-columns:repeat(4,1fr)}}
@media(max-width:700px){.diff-grid{grid-template-columns:repeat(2,1fr)}}
.diff-card{border:1px solid var(--border);border-radius:9px;padding:13px 16px}
.diff-card.easy{background:rgba(52,211,153,.07);border-color:rgba(52,211,153,.3)}
.diff-card.medium{background:rgba(251,191,36,.07);border-color:rgba(251,191,36,.3)}
.diff-card.hard{background:rgba(248,113,113,.07);border-color:rgba(248,113,113,.3)}
.diff-team{font-weight:800;font-size:1.05rem;margin-bottom:4px}
.diff-meta{font-size:.75rem;color:var(--muted);margin-bottom:5px}
.diff-rating-num{font-weight:800;font-size:1.25rem}
.diff-legend{display:flex;gap:16px;margin-bottom:14px;font-size:.78rem}
/* Upcoming fixture difficulty — 6-per-row, matches historical card layout */
.upcoming-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-top:4px}
@media(max-width:1100px){.upcoming-grid{grid-template-columns:repeat(4,1fr)}}
@media(max-width:700px){.upcoming-grid{grid-template-columns:repeat(2,1fr)}}
.upcoming-card{border:1px solid var(--border);border-radius:9px;padding:10px 12px}
.upcoming-card.easy{background:rgba(52,211,153,.07);border-color:rgba(52,211,153,.3)}
.upcoming-card.medium{background:rgba(251,191,36,.07);border-color:rgba(251,191,36,.3)}
.upcoming-card.hard{background:rgba(248,113,113,.07);border-color:rgba(248,113,113,.3)}
.upcoming-games-list{margin-top:5px;display:none;font-size:.7rem;color:var(--muted)}
.upcoming-games-list.open{display:block}
.upcoming-game-row{display:flex;justify-content:space-between;padding:2px 0;border-bottom:1px solid rgba(255,255,255,.04)}
.upcoming-game-row:last-child{border-bottom:none}

/* ── Trading Centre ── */
.trade-layout{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:800px){.trade-layout{grid-template-columns:1fr}}
.trade-panel{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px}
.trade-panel-title{font-weight:800;font-size:1rem;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.trade-list{list-style:none;display:flex;flex-direction:column;gap:5px;min-height:50px}

/* Upgraded trade item */
.trade-item{display:flex;align-items:flex-start;gap:7px;padding:10px 11px;background:var(--surface2);border-radius:8px;border:1px solid var(--border);transition:border-color .15s}
.trade-item:hover{border-color:rgba(255,255,255,.14)}
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
.net-arrow.neu{background:rgba(255,255,255,.05);color:var(--muted)}

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
.fix-table td{padding:5px 8px;border-bottom:1px solid rgba(255,255,255,.04)}
.fix-table tr:last-child td{border-bottom:none}
.fix-proj{font-weight:800}
/* Price support/resistance label */
.price-level-label{font-size:.68rem;font-style:italic}
/* Leaderboard form boxes */
.form-boxes{display:flex;gap:3px;align-items:center}
.form-box{width:20px;height:20px;border-radius:3px;display:inline-flex;align-items:center;justify-content:center;font-size:.65rem;font-weight:800;border:1px solid rgba(255,255,255,.07)}
.form-box-0{background:rgba(255,255,255,.04);color:transparent}
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
.scenario-overlay-body{flex:1;overflow-y:auto;padding:24px}
.scenarios-compare-grid{display:grid;gap:14px}
/* Scenario card matches trading panel style */
.scenario-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px}
.scenario-card:hover{border-color:rgba(255,255,255,.12)}
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
.sc-dropdown-item:hover{background:rgba(255,255,255,.05);color:var(--accent)}
.sc-rel{position:relative}
.stats-compare-box{margin-top:12px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;overflow:hidden}
.stats-collapse-header{display:flex;align-items:center;justify-content:space-between;padding:10px 13px;cursor:pointer;user-select:none;font-size:.82rem;font-weight:700}
.stats-collapse-header:hover{background:rgba(255,255,255,.03)}
.stats-collapse-arrow{font-size:.7rem;transition:transform .2s;color:var(--muted)}
.stats-collapse-arrow.open{transform:rotate(180deg)}
.stats-collapse-body{display:none;padding:0 13px 13px}
.stats-collapse-body.open{display:block}
.scb-row{display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid rgba(255,255,255,.04)}
.scb-row:last-child{border-bottom:none}
.scb-label{color:var(--muted)}
.scb-val{font-weight:700}
.winner-crown{color:var(--accent);font-size:.75rem;margin-left:4px}
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
.squad-card:hover{border-color:rgba(255,255,255,.18)}
.squad-card.bench-card{background:rgba(255,255,255,.025);opacity:.85}
.squad-card.empty-card{border:1px dashed rgba(255,255,255,.12);background:transparent;cursor:pointer;display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:.75rem}
.squad-card.empty-card:hover{border-color:var(--accent2);color:var(--accent2)}
.squad-card-pos{position:absolute;top:6px;left:7px;font-size:.58rem;font-weight:800;padding:1px 4px;border-radius:3px}
.squad-card-name{font-weight:700;font-size:.8rem;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:14px}
.squad-card-name:hover{color:var(--accent)}
.squad-card-team{font-size:.65rem;color:var(--muted)}
.squad-card-avg{font-weight:800;font-size:1.05rem}
.squad-card-price{font-size:.68rem;color:var(--muted)}
.squad-card-sig{position:absolute;top:6px;right:7px;font-size:.6rem;font-weight:800;padding:1px 5px;border-radius:3px}
.squad-card-remove{position:absolute;bottom:5px;right:6px;background:none;border:none;color:rgba(255,255,255,.2);cursor:pointer;font-size:.75rem;padding:1px 3px;border-radius:2px}
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
</style>
</head>
<body>
<header>
  <div class="logo">&#127945; AFL <span>Fantasy Brownlow</span></div>
  <nav>
    <button class="nav-btn active"  onclick="showPage('leaderboard',this)">&#127942; Leaderboard</button>
    <button class="nav-btn"         onclick="showPage('rounds',this)">&#128203; Round Scores</button>
    <button class="nav-btn"         onclick="showPage('players',this)">&#128200; Player Stats</button>
    <button class="nav-btn"         onclick="showPage('difficulty',this)">&#128737; Matchup Difficulty</button>
    <button class="nav-btn"         onclick="showPage('trading',this)">&#128176; Trading Centre</button>
    <button class="nav-btn"         onclick="showPage('myteam',this)">&#127945; My Team</button>
    <button class="nav-btn"         onclick="showPage('rolling22',this)">&#127942; Rolling 22</button>
  </nav>
</header>
<main>

<!-- LEADERBOARD PAGE -->
<div class="page active" id="page-leaderboard">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;flex-wrap:wrap;padding:0 8px">
    <div style="font-weight:800;font-size:1.1rem;color:var(--text)">&#127942; Leaderboard</div>
    <button class="info-btn" id="infoBtn-leaderboard" onclick="toggleInfo('leaderboard')">&#9432; How it works</button>
    <button class="race-btn" id="voteRaceToggleBtn" onclick="toggleVoteRace()" style="margin-left:auto">&#127885; Vote Race</button>
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
  <div id="lbSection">
    <table class="std-table">
      <thead><tr>
        <th>Pos</th><th>Player</th><th>Club</th>
        <th class="ta-r">Current Price</th><th class="ta-r">Avg FP</th>
        <th class="ta-r">Total FP</th><th class="ta-r">Votes</th>
        <th>Form (L5)</th>
        <th>Status</th>
      </tr></thead>
      <tbody id="lbBody"></tbody>
    </table>
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

<!-- ROUNDS PAGE -->
<div class="page" id="page-rounds">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px">
    <div style="font-weight:800;font-size:1.1rem;color:var(--text)">&#128203; Round Scores</div>
    <button class="info-btn" id="infoBtn-rounds" onclick="toggleInfo('rounds')">&#9432; How it works</button>
  </div>
  <div class="info-panel" id="info-rounds">
    <div class="info-heading">&#128203; Round Scores</div>
    Displays each game for the selected round, showing the <b>3 vote-getters per match</b>.<br><br>
    Click a player name to view their full history in Player Stats.
  </div>
  <div class="round-tabs" id="roundTabs"></div>
  <div class="games-grid" id="gamesGrid"></div>
</div>

<!-- PLAYER STATS PAGE -->
<div class="page" id="page-players">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px">
    <div style="font-weight:800;font-size:1.1rem;color:var(--text)">&#128200; Player Stats</div>
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
      <div>
        <div class="pc-name" id="pcName"></div>
        <div class="pc-sub" id="pcSub"></div>
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
    <div class="chart-section">
      <div class="chart-title">Score &amp; Price History</div>
      <canvas id="mainChart"></canvas>
    </div>
    <div class="chart-section" id="valueSection" style="display:none">
      <div class="chart-title">Value vs Expectation (Score &minus; Price &divide; 10,490)</div>
      <canvas id="valueChart"></canvas>
    </div>
  </div>
</div>

<!-- MATCHUP DIFFICULTY PAGE -->
<div class="page" id="page-difficulty">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px">
    <div style="font-weight:800;font-size:1.1rem;color:var(--text)">&#128737; Matchup Difficulty</div>
    <button class="info-btn" id="infoBtn-difficulty" onclick="toggleInfo('difficulty')">&#9432; How it works</button>
  </div>
  <div class="info-panel" id="info-difficulty">
    <div class="info-heading">&#128737; Matchup Difficulty Rating</div>
    <b>Historical tab:</b> How do players score vs their own average when facing each team? Rating 100 = league average. Above 100 = easier.<br><br>
    <b>Upcoming Fixture tab:</b> Predicted avg pts your players will score in each upcoming game, based on the opponent&apos;s historical concede rating. Weighted so closer games count more.
  </div>
  <div style="display:flex;gap:8px;margin-bottom:18px">
    <button class="diff-tab active" id="diffSubHistorical" onclick="showDiffSub('historical')">&#128202; Historical</button>
    <button class="diff-tab" id="diffSubUpcoming" onclick="showDiffSub('upcoming')">&#128197; Upcoming Fixture</button>
  </div>
  <div id="diffHistoricalSection">
    <div class="diff-legend">
      <span style="color:var(--green)">&#9679; Easiest to score against</span>
      <span style="color:var(--yellow)">&#9679; Average difficulty</span>
      <span style="color:var(--red)">&#9679; Hardest to score against</span>
    </div>
    <div class="diff-tabs" id="diffTabs"></div>
    <div id="diffContent"></div>
  </div>
  <div id="diffUpcomingSection" style="display:none">
    <div class="diff-legend">
      <span style="color:var(--green)">&#9679; Easiest upcoming schedule</span>
      <span style="color:var(--yellow)">&#9679; Average schedule</span>
      <span style="color:var(--red)">&#9679; Toughest upcoming schedule</span>
    </div>
    <div class="diff-tabs" id="upcomingPosTabs"></div>
    <div id="upcomingContent"></div>
  </div>
</div>

<!-- TRADING CENTRE PAGE -->
<div class="page" id="page-trading">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px">
    <div style="font-weight:800;font-size:1.1rem;color:var(--text)">&#128176; Trading Centre</div>
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
          <div id="tradeScoreBar" style="display:none;margin-top:10px;background:var(--surface2);border:1px solid var(--border);border-radius:7px;padding:9px 12px">
            <div style="font-size:.62rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:5px;font-weight:700">&#127919; Trade Quality Score</div>
            <div style="display:flex;align-items:center;gap:8px">
              <div style="flex:1;height:6px;background:var(--border);border-radius:3px;overflow:hidden">
                <div id="tradeScoreFill" style="height:100%;border-radius:3px;transition:width .4s,background .4s"></div>
              </div>
              <span id="tradeScoreLabel" style="font-weight:800;font-size:1.05rem;min-width:36px;text-align:right"></span>
            </div>
            <div id="tradeScoreBreakdown" style="margin-top:5px;font-size:.68rem;color:var(--muted)"></div>
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
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap">
    <div style="font-weight:800;font-size:1.1rem">&#127945; My Team</div>
    <button class="info-btn" id="infoBtn-myteam" onclick="toggleInfo('myteam')">&#9432; How it works</button>
    <div style="margin-left:auto;display:flex;gap:8px;flex-wrap:wrap">
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
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px;flex-wrap:wrap">
    <div style="font-weight:800;font-size:1.1rem">&#127942; Rolling 22 — Best Projected Team</div>
    <button class="info-btn" id="infoBtn-rolling22" onclick="toggleInfo('rolling22')">&#9432; How it works</button>
    <div style="margin-left:auto;display:flex;gap:6px">
      <button class="race-btn" onclick="renderRolling22('overall')">Overall</button>
      <button class="race-btn" onclick="renderRolling22('form')">Form-weighted</button>
      <button class="race-btn" onclick="renderRolling22('fixture')">Fixture-adjusted</button>
    </div>
  </div>
  <div class="info-panel" id="info-rolling22">
    <div class="info-heading">&#127942; Rolling 22</div>
    Shows the best projected 22-man AFL Fantasy team from your loaded data, laid out in DEF/MID/RUC/FWD formation.<br><br>
    <b>Overall</b> — ranked by season avg FP. <b>Form-weighted</b> — weighted heavily on last-3 scores. <b>Fixture-adjusted</b> — accounts for upcoming opponent difficulty.<br><br>
    The number shows <b>avg FP → projected score</b> (e.g. 107.1→115 means season avg is 107, projected this week is 115 based on form &amp; fixture).<br><br>
    ★ = add to Trading Centre watchlist. Injured players excluded. Bench spots = next-best available.
  </div>
  <div id="rolling22Grid"></div>
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
const LEADERBOARD      = __LEADERBOARD__;
const ROUNDS_DATA      = __ROUNDS_DATA__;
const PLAYERS_DATA     = __PLAYERS_DATA__;
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

let mainChartInst = null, valueChartInst = null, currentPlayerKey = null;
let raceFrame = 0, raceTimer = null;

const duplicateNames = new Set(
  PLAYERS_DATA.filter((p,_,arr) => arr.filter(x => x.name === p.name).length > 1).map(p => p.name)
);
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

function showPage(id, btn) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  var pageEl = document.getElementById('page-' + id);
  if (!pageEl) return;
  pageEl.classList.add('active');
  if (btn) btn.classList.add('active');
  if (id === 'trading') renderTradeLists();
  if (id === 'myteam') renderMyTeam();
  if (id === 'rolling22') renderRolling22('overall');
}

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
  const tbody = document.getElementById('lbBody');
  let pos = 1, prevVotes = null;
  LEADERBOARD.forEach((e, i) => {
    if (e.votes !== prevVotes) pos = i + 1;
    prevVotes = e.votes;
    const pc = pos===1?'p1':pos===2?'p2':pos===3?'p3':'';
    const dn = e.display_name || getDisplayName(e.player, e.team);
    // Form boxes: last 5 rounds' votes
    var formHtml = '<div class="form-boxes">';
    (e.form_history || []).forEach(function(f) {
      const lbl = f.r === 0 ? 'Op' : 'R' + f.r;
      if (f.v === 0) formHtml += '<div class="form-box form-box-0" title="' + lbl + ': no votes">&nbsp;</div>';
      else formHtml += '<div class="form-box form-box-' + f.v + '" title="' + lbl + ': ' + f.v + ' vote' + (f.v>1?'s':'') + '">' + f.v + '</div>';
    });
    formHtml += '</div>';
    const tr = document.createElement('tr');
    tr.innerHTML =
      '<td class="pos-num ' + pc + '">' + pos + '</td>' +
      '<td><span class="player-link" onclick="searchAndShowPlayer(\'' + e.key.replace(/'/g,"\\'") + '\')">' + dn + '</span></td>' +
      '<td><span class="team-tag">' + e.team + '</span></td>' +
      '<td class="ta-r" style="color:#fff;font-family:\'Barlow Condensed\',sans-serif">' + fmtPrice(e.price) + '</td>' +
      '<td class="ta-r" style="font-family:\'Barlow Condensed\',sans-serif;font-weight:700">' + e.avg + '</td>' +
      '<td class="ta-r" style="color:var(--muted);font-family:\'Barlow Condensed\',sans-serif">' + e.total_dt + '</td>' +
      '<td class="ta-r votes-hl">' + e.votes + '</td>' +
      '<td>' + formHtml + '</td>' +
      (e.is_injured ? '<td><span style="background:rgba(248,113,113,.2);color:var(--red);font-size:.65rem;font-weight:700;padding:1px 5px;border-radius:3px">INJ</span></td>' : '<td></td>');
    tbody.appendChild(tr);
  });
})();

// ── Round browser ─────────────────────────────────────────────────────────────
let activeRound = ROUNDS_DATA.length ? ROUNDS_DATA[0].round : null;
function renderRoundTabs() {
  const tabs = document.getElementById('roundTabs'); tabs.innerHTML = '';
  ROUNDS_DATA.forEach(rd => {
    const btn = document.createElement('button');
    btn.className = 'round-tab' + (rd.round === activeRound ? ' active' : '');
    btn.textContent = rd.round === 0 ? 'Opening' : 'Round ' + rd.round;
    btn.onclick = function() { activeRound = rd.round; renderRoundTabs(); renderGames(); };
    tabs.appendChild(btn);
  });
}
function renderGames() {
  const grid = document.getElementById('gamesGrid'); grid.innerHTML = '';
  const rd = ROUNDS_DATA.find(r => r.round === activeRound); if (!rd) return;
  rd.games.forEach(game => {
    const card = document.createElement('div'); card.className = 'game-card';
    const vClasses = ['','v1','v2','v3'], vLabels = ['','1 vote','2 votes','3 votes'];
    let rows = '';
    game.votes.forEach(v => {
      const dn = getDisplayName(v.player, v.team);
      rows += '<div class="vote-row">' +
        '<div class="vote-badge ' + vClasses[v.votes] + '">' + vLabels[v.votes] + '</div>' +
        '<div style="flex:1"><div class="vote-player" onclick="searchAndShowPlayerByNameTeam(\'' +
          v.player.replace(/'/g,"\\'") + '\',\'' + v.team.replace(/'/g,"\\'") + '\')">' + dn + '</div>' +
        '<div class="vote-team">' + v.team + '</div></div>' +
        '<div class="vote-score">' + v.score + '</div></div>';
    });
    card.innerHTML = '<div class="game-header">' + game.team_a + '<span class="vs">vs</span>' + game.team_b + '</div>' + rows;
    grid.appendChild(card);
  });
}
renderRoundTabs(); renderGames();

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
    '<span class="sr-sub">' + p.team + (p.positions && p.positions.length ? ' &middot; ' + p.positions.join('/') : '') + '</span>' +
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
  document.querySelectorAll('.nav-btn')[2].classList.add('active');
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
  document.getElementById('pcName').textContent = '\u{1F3C9} ' + dn;
  const posTxt = p.positions && p.positions.length ? p.positions.join('/') + ' \u00b7 ' : '';
  document.getElementById('pcSub').textContent = posTxt + p.team + (n ? ' \u00b7 Rounds: ' + rounds.map(r => r===0?'Opening':'R'+r).join(', ') : ' \u00b7 No game data');

  const projScore = calcProjectedScore(key);
  const isInjured = INJURED_SET && INJURED_SET.has(p.name);
  let s = '';
  // Injury warning at top
  if (isInjured) {
    s += '<div style="grid-column:1/-1;background:rgba(248,113,113,.12);border:1px solid rgba(248,113,113,.3);border-radius:7px;padding:6px 12px;font-size:.8rem;color:var(--red);font-weight:700;margin-bottom:4px">⚠️ Reported as INJURED — check official team lists before trading in</div>';
  }
  if (n) {
    s += '<div class="stat-card"><div class="stat-label">Avg FP</div><div class="stat-value">' + avg.toFixed(1) + '</div></div>';
    s += '<div class="stat-card"><div class="stat-label">L3 Avg</div><div class="stat-value">' + last3.toFixed(1) + '</div></div>';
    s += '<div class="stat-card"><div class="stat-label">L5 Avg</div><div class="stat-value">' + last5.toFixed(1) + '</div></div>';
    if (projScore != null) s += '<div class="stat-card" style="border-color:rgba(59,130,246,.3);background:rgba(59,130,246,.08)"><div class="stat-label" style="color:var(--accent2)">Projected</div><div class="stat-value" style="color:var(--accent2)">' + projScore + '</div></div>';
    s += '<div class="stat-card"><div class="stat-label">High</div><div class="stat-value">' + best + '</div></div>';
    s += '<div class="stat-card"><div class="stat-label">Votes</div><div class="stat-value">' + totalV + '</div></div>';
    s += '<div class="stat-card"><div class="stat-label">Rounds</div><div class="stat-value">' + n + '</div></div>';
  }
  if (currentPrice != null)
    s += '<div class="stat-card"><div class="stat-label">Price</div><div class="stat-value" style="color:#fff">' + fmtPrice(currentPrice) + '</div></div>';
  if (priceChange !== null)
    s += '<div class="stat-card"><div class="stat-label">Δ Price</div><div class="stat-value" style="color:' + pcColor + '">' + pcLabel + '</div></div>';
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

    mainChartInst = new Chart(document.getElementById('mainChart'), {
      data: { labels: labels, datasets: [
        {type:'bar',label:'Fantasy Score',data:scores,yAxisID:'scoreAxis',backgroundColor:'rgba(59,130,246,.75)',borderRadius:4},
        {type:'line',label:'Price',data:postPrices,yAxisID:'priceAxis',tension:.3,borderWidth:2.5,borderColor:'#f87171',backgroundColor:'transparent',pointBackgroundColor:'#f87171',pointRadius:4,spanGaps:false}
      ]},
      options: { responsive:true, interaction:{mode:'index',intersect:false},
        plugins: {
          tooltip: {callbacks: {label: function(ctx) {
            if (ctx.dataset.label==='Price') { var v=ctx.parsed.y; return v==null?null:'Price: '+fmtPrice(v); }
            var v = votes[ctx.dataIndex]; return 'Score: '+ctx.parsed.y+(v>0?' ('+v+' vote'+(v>1?'s':'')+')'  :'');
          }}},
          legend: {labels: {color:'#e8eaf0'}}
        },
        scales: {
          scoreAxis: {type:'linear',position:'left',ticks:{color:'#e8eaf0'},grid:{color:'rgba(255,255,255,.06)'},title:{display:true,text:'Fantasy Score',color:'#e8eaf0'}},
          priceAxis: {type:'linear',position:'right',suggestedMin:minP,suggestedMax:maxP,grid:{drawOnChartArea:false},ticks:{color:'#f87171',callback:function(v){return fmtPrice(v);}},title:{display:true,text:'Price',color:'#f87171'}},
          x: {ticks:{color:'#e8eaf0'}}
        }
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
          scales:{y:{ticks:{color:'#e8eaf0'},grid:{color:'rgba(255,255,255,.06)'},title:{display:true,text:'Points Above/Below Expected',color:'#e8eaf0'}},x:{ticks:{color:'#e8eaf0'}}}
        }
      });
    } else document.getElementById('valueSection').style.display = 'none';
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

(function() {
  var ALL_DIFFS = Object.assign({ 'Overall': OVERALL_DIFF }, POS_DIFF);
  const tabs = document.getElementById('diffTabs');
  const content = document.getElementById('diffContent');
  var activeTab = 'Overall';

  function renderDiffTab(key) {
    activeTab = key;
    tabs.querySelectorAll('.diff-tab').forEach(function(t) { t.classList.toggle('active', t.dataset.key === key); });
    const data = ALL_DIFFS[key] || [];
    if (!data.length) { content.innerHTML = '<div style="color:var(--muted);padding:20px">No data for this position yet.</div>'; return; }
    const n = data.length;
    const easyCount = Math.ceil(n/3), hardStart = Math.floor(2*n/3);
    content.innerHTML = '';
    const grid = document.createElement('div'); grid.className = 'diff-grid';
    data.forEach(function(d, i) {
      const tier = i < easyCount ? 'easy' : i >= hardStart ? 'hard' : 'medium';
      const col  = tier==='easy' ? 'var(--green)' : tier==='medium' ? 'var(--yellow)' : 'var(--red)';
      const card = document.createElement('div'); card.className = 'diff-card ' + tier;
      const barW = Math.min(100, Math.max(0, ((d.rating - 80) / 40) * 100));
      card.innerHTML =
        '<div class="diff-team" style="color:' + col + '">' + d.team + '</div>' +
        '<div class="diff-meta">' + d.games + ' player-games \u00b7 league avg: ' + AFL_AVG.toFixed(1) + ' pts</div>' +
        '<div style="display:flex;justify-content:space-between;align-items:flex-end">' +
          '<div><div style="font-size:.62rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em">Avg pts conceded</div>' +
          '<div class="diff-rating-num" style="color:' + col + '">' + d.avg_conceded + ' pts</div></div>' +
          '<div style="text-align:right"><div style="font-size:.62rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em">Difficulty rating</div>' +
          '<div class="diff-rating-num" style="color:' + col + '">' + d.rating + '</div></div>' +
        '</div>' +
        '<div style="font-size:.65rem;color:var(--muted);margin-top:4px">' +
          (d.rating > 100 ? '\u25b2 Players score ' + (d.rating - 100).toFixed(1) + '% above their avg here' :
           d.rating < 100 ? '\u25bc Players score ' + (100 - d.rating).toFixed(1) + '% below their avg here' :
           'Exactly league average difficulty') +
        '</div>' +
        '<div class="rating-bar-wrap" style="margin-top:6px;height:4px"><div class="rating-bar" style="width:' + barW + '%;background:' + col + '"></div></div>';
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

// ── Upcoming Fixture Difficulty — matches historical card layout ──────────────
(function() {
  const ALL_POS = ['Overall', 'DEF', 'MID', 'RUC', 'FWD'];
  const tabs = document.getElementById('upcomingPosTabs');
  const content = document.getElementById('upcomingContent');

  function getAflAvg(posKey) {
    if (posKey === 'Overall') return UPCOMING_AFL_AVG;
    return UPCOMING_AFL_AVG_POS && UPCOMING_AFL_AVG_POS[posKey] != null ? UPCOMING_AFL_AVG_POS[posKey] : null;
  }

  // Gradient: green (easy, score>108) → yellow-green → yellow → orange → red (hard, score<92)
  // Using explicit colour stops for maximum visual contrast
  function gradientColor(score, alpha) {
    alpha = alpha || 1;
    // Map score to 0-1: 85=hard=0, 115=easy=1
    const t = Math.max(0, Math.min(1, (score - 85) / 30));
    var r, g, b;
    if (t >= 0.67) {
      // Green zone: 100→ hue 100-120
      const u = (t - 0.67) / 0.33;
      r = Math.round(20  + u * 10);
      g = Math.round(200 + u * 11);
      b = Math.round(100 + u * 53);
    } else if (t >= 0.33) {
      // Yellow zone: hue 45-80
      const u = (t - 0.33) / 0.34;
      r = Math.round(240 - u * 220);
      g = Math.round(180 + u * 31);
      b = Math.round(30  + u * 70);
    } else {
      // Red-orange zone
      const u = t / 0.33;
      r = Math.round(220 - u * 20);
      g = Math.round(60  + u * 120);
      b = Math.round(20  + u * 10);
    }
    return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
  }
  function gradientBg(score) { return gradientColor(score, 0.13); }
  function gradientBorder(score) { return gradientColor(score, 0.55); }
  function gradientText(score) { return gradientColor(score, 1); }

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

    const aflAvg = getAflAvg(posKey);
    content.innerHTML = '';
    const grid = document.createElement('div');
    grid.className = 'upcoming-grid';
    const n_teams = sorted.length;

    sorted.forEach(function(d, i) {
      const score = posKey === 'Overall' ? d.upcoming_score : (d.upcoming_pos[posKey] || 100);
      const predAvg = posKey === 'Overall'
        ? d.predicted_avg
        : (d.predicted_avg_pos && d.predicted_avg_pos[posKey] != null ? d.predicted_avg_pos[posKey] : null);

      // Fixed bands: top 6=green, middle 6=yellow, bottom 6=red (regardless of absolute value)
      var col, bgCol, bdCol, barCol;
      if (i < 6) {
        col='var(--green)'; bgCol='rgba(52,211,153,.1)'; bdCol='rgba(52,211,153,.4)'; barCol='rgba(52,211,153,.8)';
      } else if (i < 12) {
        col='var(--yellow)'; bgCol='rgba(251,191,36,.08)'; bdCol='rgba(251,191,36,.35)'; barCol='rgba(251,191,36,.7)';
      } else {
        col='var(--red)'; bgCol='rgba(248,113,113,.08)'; bdCol='rgba(248,113,113,.35)'; barCol='rgba(248,113,113,.7)';
      }
      const barW = Math.min(100, Math.max(0, ((score - 80) / 40) * 100));
      const detailId = 'updet_' + i + '_' + posKey.replace(/[^a-z]/gi,'');

      let descriptor = 'Average upcoming schedule';
      if (score > 100) descriptor = '\u25b2 Players score ' + (score - 100).toFixed(1) + '% above their avg';
      else if (score < 100) descriptor = '\u25bc Players score ' + (100 - score).toFixed(1) + '% below their avg';

      var gamesHtml = '';
      (d.games || []).forEach(function(g, gi) {
        const gScore = posKey === 'Overall' ? g.overall : (g.pos[posKey] || 100);
        const gPred  = posKey === 'Overall' ? g.predicted_avg : (g.predicted_pos && g.predicted_pos[posKey] != null ? g.predicted_pos[posKey] : null);
        const gCol   = gradientText(gScore);
        const rLabel = g.round === 0 ? 'Open' : 'R' + g.round;
        const proximity = gi === 0 ? ' (next)' : '';
        const predTxt = gPred != null ? ' \u2022 ~' + gPred.toFixed(1) + ' pts' : '';
        gamesHtml += '<div class="upcoming-game-row">' +
          '<span>' + rLabel + proximity + ': vs ' + g.opponent + predTxt + '</span>' +
          '<span style="color:' + gCol + ';font-weight:700">' + gScore.toFixed(1) + '</span>' +
        '</div>';
      });

      const numGames = (d.games || []).length;
      const avgLine = aflAvg != null ? 'league avg: ' + aflAvg.toFixed(1) + ' pts' : numGames + ' upcoming games';

      const card = document.createElement('div');
      card.className = 'upcoming-card';
      card.style.cssText = 'background:' + bgCol + ';border-color:' + bdCol;
      card.innerHTML =
        '<div class="diff-team" style="color:' + col + '">' + d.team + '</div>' +
        '<div class="diff-meta">' + numGames + ' upcoming \u00b7 ' + avgLine + '</div>' +
        '<div style="display:flex;justify-content:space-between;align-items:flex-end">' +
          (predAvg != null
            ? '<div><div style="font-size:.58rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em">Pred avg pts</div>' +
              '<div class="diff-rating-num" style="color:' + col + '">' + predAvg.toFixed(1) + '</div></div>'
            : '<div></div>') +
          '<div style="text-align:right"><div style="font-size:.58rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em">Rating</div>' +
          '<div class="diff-rating-num" style="color:' + col + '">' + score.toFixed(1) + '</div></div>' +
        '</div>' +
        '<div style="font-size:.62rem;color:var(--muted);margin-top:3px">' + descriptor + '</div>' +
        '<div class="rating-bar-wrap" style="margin-top:5px;height:4px"><div class="rating-bar" style="width:' + barW + '%;background:' + barCol + '"></div></div>' +
        '<div style="margin-top:5px;font-size:.65rem;color:var(--accent2);cursor:pointer" onclick="toggleUpcomingGames(\'' + detailId + '\')">\u25bc Show games</div>' +
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
      '<td><span class="team-tag">' + entry.team + '</span></td>' +
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
      '<span class="team-tag">' + teamTxt + '</span>' +
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

function calcProjectedScore(key) {
  // Weighted projection: 50% L3 avg, 30% L5 avg, 20% season avg, then fixture adjustment
  // This ensures elite recent form (like Wanganeen-Milera 138 L3) drives the projection
  const p = getP(key); if (!p) return null;
  if (INJURED_SET && INJURED_SET.has(p.name)) return null; // injured = no projection
  const scores = p.history.map(function(x){return x.score;});
  const n = scores.length; if (!n) return null;
  const seasonAvg = scores.reduce(function(a,b){return a+b;},0)/n;
  const l3 = scores.slice(-3).reduce(function(a,b){return a+b;},0)/Math.min(3,n);
  const l5 = scores.slice(-5).reduce(function(a,b){return a+b;},0)/Math.min(5,n);
  // Weight: recent form matters most
  const baseProj = l3*0.50 + l5*0.30 + seasonAvg*0.20;
  // Fixture adjustment: if rating is 110 → multiply by 1.10; if 90 → multiply by 0.90
  const fix = getPlayerFixtureScore(key);
  const fixMult = fix != null ? (0.4 + fix/166.7) : 1.0; // dampened: 90→0.94, 100→1.0, 110→1.06
  return Math.round(baseProj * fixMult);
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
        const fill = document.getElementById('tradeScoreFill');
        const lbl  = document.getElementById('tradeScoreLabel');
        const bkdn = document.getElementById('tradeScoreBreakdown');
        if (fill) { fill.style.width = tradeScore + '%'; fill.style.background = tCol; }
        if (lbl)  { lbl.textContent = tradeScore + '/100'; lbl.style.color = tCol; }
        if (bkdn) {
          bkdn.innerHTML = '<b style="color:' + tCol + '">' + tLabel + '</b> · ' +
            scoreComponents.map(function(c){
              return '<span style="color:' + (c.good?'var(--green)':'var(--red)') + '">' + c.label + ': ' + (c.diff>=0?'+':'') + c.diff + '</span>';
            }).join(' · ');
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
      const posStr = p.positions && p.positions.length ? p.positions.join('/') + ' \u00b7 ' : '';
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
    const card = document.createElement('div'); card.className = 'scenario-card';
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

    function statsBlock(st, label, collapseId) {
      const arrowId = collapseId + '_arrow';
      const bodyId  = collapseId + '_body';
      const headerHtml =
        '<div class="stats-collapse-header" onclick="toggleCollapse(\'' + collapseId + '\')">' +
          '<span>' + label + (st && st.count ? ' (' + st.count + ' player' + (st.count>1?'s':'') + ')' : '') + '</span>' +
          '<span class="stats-collapse-arrow" id="' + arrowId + '">&#9660;</span>' +
        '</div>';
      if (!st || st.count === 0) {
        return headerHtml + '<div class="stats-collapse-body" id="' + bodyId + '"><div style="color:var(--muted);font-size:.78rem;padding:4px 0">No players added</div></div>';
      }
      const avgFR = st.formRating  != null ? st.formRating.toFixed(0)  : '\u2014';
      const avgCS = st.consistency != null ? st.consistency.toFixed(0) : '\u2014';
      const pcStr = st.priceChange != null ? (st.priceChange>=0?'+':'-') + fmtPrice(Math.abs(st.priceChange)) : '\u2014';
      const pcCol = st.priceChange == null ? 'var(--muted)' : st.priceChange >= 0 ? 'var(--green)' : 'var(--red)';
      var html = '';
      if (st.players && st.players.length) {
        st.players.forEach(function(p) {
          html += '<div class="scb-row"><span class="scb-label">' + p.name + ' games</span><span class="scb-val">' + p.rounds + '</span></div>';
        });
      }
      html += '<div class="scb-row"><span class="scb-label">Combined Avg FP</span><span class="scb-val">' + st.avg.toFixed(1) + '</span></div>';
      html += '<div class="scb-row"><span class="scb-label">Last 3 Avg</span><span class="scb-val">' + st.last3.toFixed(1) + '</span></div>';
      html += '<div class="scb-row"><span class="scb-label">Last 5 Avg</span><span class="scb-val">' + st.last5.toFixed(1) + '</span></div>';
      html += '<div class="scb-row"><span class="scb-label">Total Votes</span><span class="scb-val">' + st.totalVotes + '</span></div>';
      html += '<div class="scb-row"><span class="scb-label">Total FP</span><span class="scb-val">' + st.totalFP + '</span></div>';
      html += '<div class="scb-row"><span class="scb-label">Avg Form Rating</span><span class="scb-val" style="color:' + ratingColor(st.formRating) + '">' + avgFR + (st.formRating!=null?'/100':'') + '</span></div>';
      html += '<div class="scb-row"><span class="scb-label">Avg Consistency</span><span class="scb-val" style="color:' + ratingColor(st.consistency) + '">' + avgCS + (st.consistency!=null?'/100':'') + '</span></div>';
      html += '<div class="scb-row"><span class="scb-label">Combined Price</span><span class="scb-val">' + fmtPrice(st.price) + '</span></div>';
      html += '<div class="scb-row"><span class="scb-label">Season Price Change</span><span class="scb-val" style="color:' + pcCol + '">' + pcStr + '</span></div>';
      Object.entries(st.posCounts).forEach(function(e2){
        html += '<div class="scb-row"><span class="scb-label">' + e2[0] + ' players</span><span class="scb-val">' + e2[1] + '</span></div>';
      });
      return headerHtml + '<div class="stats-collapse-body" id="' + bodyId + '"><div style="padding-top:6px">' + html + '</div></div>';
    }

    function fmtNet(v, decimals) {
      decimals = decimals != null ? decimals : 1;
      if (v == null) return '\u2014';
      return (v >= 0 ? '+' : '-') + Math.abs(v).toFixed(decimals);
    }

    var netBodyHtml = '';
    if (netAvg !== null) {
      netBodyHtml += '<div class="scb-row"><span class="scb-label">Avg FP</span><span class="scb-val" style="color:' + (netAvg>=0?'var(--green)':'var(--red)') + '">' + fmtNet(netAvg) + '</span></div>';
      netBodyHtml += '<div class="scb-row"><span class="scb-label">Last 3 Avg</span><span class="scb-val" style="color:' + ((netL3||0)>=0?'var(--green)':'var(--red)') + '">' + fmtNet(netL3) + '</span></div>';
      netBodyHtml += '<div class="scb-row"><span class="scb-label">Last 5 Avg</span><span class="scb-val" style="color:' + ((netL5||0)>=0?'var(--green)':'var(--red)') + '">' + fmtNet(netL5) + '</span></div>';
      netBodyHtml += '<div class="scb-row"><span class="scb-label">Votes</span><span class="scb-val" style="color:' + ((netVotes||0)>=0?'var(--green)':'var(--red)') + '">' + fmtNet(netVotes,0) + '</span></div>';
      if (netFR !== null) netBodyHtml += '<div class="scb-row"><span class="scb-label">Form Rating</span><span class="scb-val" style="color:' + (netFR>=0?'var(--green)':'var(--red)') + '">' + fmtNet(netFR,1) + '/100</span></div>';
      if (netCS !== null) netBodyHtml += '<div class="scb-row"><span class="scb-label">Consistency</span><span class="scb-val" style="color:' + (netCS>=0?'var(--green)':'var(--red)') + '">' + fmtNet(netCS,1) + '/100</span></div>';
      if (netPriceChange !== null) netBodyHtml += '<div class="scb-row"><span class="scb-label">Price Change</span><span class="scb-val" style="color:' + (netPriceChange>=0?'var(--green)':'var(--red)') + '">' + (netPriceChange>=0?'+':'-') + fmtPrice(Math.abs(netPriceChange)) + '</span></div>';
      if (netPrice !== null) netBodyHtml += '<div class="scb-row"><span class="scb-label">Price Diff</span><span class="scb-val" style="color:' + (netPrice<=0?'var(--green)':'var(--red)') + '">' + (netPrice>=0?'+':'-') + fmtPrice(Math.abs(netPrice)) + '</span></div>';
      if (posDeltaHtml) netBodyHtml += '<div class="scb-row" style="flex-direction:column;gap:3px"><span class="scb-label">Position changes</span><span style="margin-top:3px">' + posDeltaHtml + '</span></div>';
    }

    const netCollapseId = 'sc_net_' + s.id;
    const netSection = netAvg !== null ?
      '<div class="stats-compare-box" style="margin-top:10px">' +
        '<div class="stats-collapse-header" onclick="toggleCollapse(\'' + netCollapseId + '\')" style="color:var(--accent)">' +
          '<span>&#128202; Net Gain (In \u2212 Out)</span>' +
          '<span class="stats-collapse-arrow" id="' + netCollapseId + '_arrow">&#9660;</span>' +
        '</div>' +
        '<div class="stats-collapse-body" id="' + netCollapseId + '_body"><div style="padding-top:6px">' + netBodyHtml + '</div></div>' +
      '</div>' : '';

    card.innerHTML =
      '<div class="scenario-card-header">' +
        '<input class="scenario-name-input" value="' + s.name.replace(/"/g,'&quot;') + '" onchange="renameScenario(' + s.id + ',this.value)">' +
        (isWinner ? '<span class="winner-crown" title="Best avg gain">&#127942; Best</span>' : '') +
        '<button class="trade-item-remove" style="font-size:1rem" onclick="removeScenario(' + s.id + ')">&#10005;</button>' +
      '</div>' +
      '<div class="scenario-section-label">&#11014; Trading In</div>' +
      '<div class="scenario-tags">' + playerTags(s.in,'in') + '</div>' +
      '<div class="sc-rel"><input class="sc-search" placeholder="Search to add in\u2026" id="sc_in_' + s.id + '" autocomplete="off"><div class="sc-dropdown" id="sc_dr_in_' + s.id + '"></div></div>' +
      '<div class="scenario-section-label">&#11015; Trading Out</div>' +
      '<div class="scenario-tags">' + playerTags(s.out,'out') + '</div>' +
      '<div class="sc-rel"><input class="sc-search" placeholder="Search to add out\u2026" id="sc_out_' + s.id + '" autocomplete="off"><div class="sc-dropdown" id="sc_dr_out_' + s.id + '"></div></div>' +
      '<div class="stats-compare-box" style="margin-top:12px">' + statsBlock(iSt, '\u{1F4E5} Trading In Stats', 'sc_in_stats_' + s.id) + '</div>' +
      '<div class="stats-compare-box" style="margin-top:8px">' + statsBlock(oSt, '\u{1F4E4} Trading Out Stats', 'sc_out_stats_' + s.id) + '</div>' +
      netSection;

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
      const posStr = p.positions && p.positions.length ? p.positions.join('/') + ' \u00b7 ' : '';
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
  lsSet('myteam_squad',[]); lsSet('myteam_positions',{});
  renderMyTeam();
  document.getElementById('myteamAnalysis').style.display='none';
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

function playerSignal(key, isBench) {
  const p = getP(key); if (!p) return {label:'—',col:'var(--muted)',score:50,reasons:[]};
  const st = playerStats(key);
  const isInj = INJURED_SET && INJURED_SET.has(p.name);
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

function renderMyTeam() {
  const squad = lsMyTeam();
  const grouped = groupSquadByPosition(squad);
  const fieldDiv = document.getElementById('myteamFieldGrid');
  if (!fieldDiv) return;
  fieldDiv.innerHTML = '';

  // Two-column layout: narrow field cards | tips panel
  const wrap = document.createElement('div');
  wrap.style.cssText = 'display:grid;grid-template-columns:1fr 300px;gap:14px;align-items:start';
  const leftCol = document.createElement('div');
  const rightCol = document.createElement('div');
  rightCol.id = 'mtTipsPanel';

  // ── Render each position section ─────────────────────────────────────────
  const posOrder = ['DEF','MID','RUC','FWD'];
  posOrder.forEach(function(posKey) {
    const cfg = MT_POS_CONFIG.find(function(c){return c.pos===posKey;});
    const players = grouped[posKey] || [];
    const total = cfg.starters + cfg.bench;

    const sec = document.createElement('div');
    sec.style.cssText = 'margin-bottom:8px';
    const lbl = document.createElement('div');
    lbl.style.cssText = 'font-family:"Barlow Condensed",sans-serif;font-weight:800;font-size:.68rem;letter-spacing:.1em;color:'+cfg.color+';margin-bottom:4px;display:flex;align-items:center;gap:5px';
    lbl.innerHTML = cfg.label + '<span style="color:var(--muted);font-weight:400;font-size:.6rem">'+players.length+'/'+total+'</span>'+
      '<span style="color:rgba(255,255,255,.15);font-size:.58rem;margin-left:auto">drag to reorder</span>';
    sec.appendChild(lbl);

    const row = document.createElement('div');
    row.style.cssText = 'display:grid;gap:4px;grid-template-columns:repeat('+cfg.starters+',1fr) 4px repeat('+cfg.bench+',minmax(0,0.68fr))';
    row.dataset.pos = posKey;

    for (var i=0; i<total; i++) {
      // Divider between starters and bench
      if (i === cfg.starters) {
        const dvd = document.createElement('div');
        dvd.style.cssText = 'background:rgba(255,255,255,.06);border-radius:2px;align-self:stretch';
        row.appendChild(dvd);
      }
      const isBench = i >= cfg.starters;
      const key = players[i];
      const card = makePlayerCard(key, posKey, isBench, cfg);
      // Drag and drop
      if (key) {
        card.draggable = true;
        card.addEventListener('dragstart', function(e){ e.dataTransfer.setData('key', key); e.dataTransfer.setData('fromPos', posKey); });
      }
      row.appendChild(card);
    }
    // Drop target for this row
    row.addEventListener('dragover', function(e){ e.preventDefault(); row.style.outline='1px dashed var(--accent2)'; });
    row.addEventListener('dragleave', function(){ row.style.outline=''; });
    row.addEventListener('drop', function(e){
      e.preventDefault(); row.style.outline='';
      const dragKey = e.dataTransfer.getData('key');
      if (!dragKey) return;
      setPlayerPosition(dragKey, posKey);
    });

    sec.appendChild(row);
    leftCol.appendChild(sec);
  });

  // ── UTIL + bench overflow ─────────────────────────────────────────────────
  const utilPlayers = (grouped.UTIL||[]).concat(grouped.UNKNOWN||[]);
  const utilSec = document.createElement('div');
  utilSec.style.cssText = 'margin-bottom:8px';
  const utilLbl = document.createElement('div');
  utilLbl.style.cssText = 'font-family:"Barlow Condensed",sans-serif;font-weight:800;font-size:.68rem;letter-spacing:.1em;color:var(--muted);margin-bottom:4px';
  utilLbl.textContent = 'UTILITY / EXTRA';
  utilSec.appendChild(utilLbl);
  const utilRow = document.createElement('div');
  utilRow.style.cssText = 'display:grid;grid-template-columns:repeat(4,1fr);gap:4px'; const maxUtil=1;
  for (var ui=0; ui<1; ui++) {
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
  if (squad.length > 0) {
    var tv=0,as=0,ac=0;
    squad.forEach(function(k){
      const p=getP(k); if(!p)return;
      if(p.current_price) tv+=p.current_price;
      const st=playerStats(k); if(st&&st.n){as+=st.avg;ac++;}
    });
    document.getElementById('myteamTeamValue').style.display='block';
    document.getElementById('myteamValueNum').textContent=fmtPrice(tv);
    document.getElementById('myteamTeamAvg').style.display='block';
    document.getElementById('myteamAvgNum').textContent=ac?(as/ac).toFixed(1)+' pts':'—';
    buildTipsPanel(squad, grouped);
  } else {
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
    card.style.cssText = 'border:1px dashed rgba(255,255,255,.08);border-radius:6px;display:flex;align-items:center;justify-content:center;min-height:70px;color:rgba(255,255,255,.15);font-size:.65rem;font-family:"Barlow Condensed",sans-serif;cursor:pointer;background:'+(isBench?'rgba(255,255,255,.01)':'transparent');
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
  const avgNum = st&&st.avg ? st.avg : 0;
  const avgCol = avgNum>=115?'var(--green)':avgNum>=95?'var(--text)':'var(--muted)';
  const trendSym = sig.trend==='rising'?'↑':sig.trend==='falling'?'↓':'';
  const trendCol = sig.trend==='rising'?'var(--green)':'var(--red)';
  // DPP badge - show other eligible positions
  const otherPos = p&&p.positions?p.positions.filter(function(pp){return pp!==posKey;}).join('/'):'';

  card.style.cssText = 'background:'+(isBench?'rgba(255,255,255,.025)':'var(--surface2)')+
    ';border:1px solid '+(isInj?'rgba(248,113,113,.5)':isBench?'rgba(255,255,255,.07)':'var(--border)')+
    ';border-radius:6px;padding:5px 6px;position:relative;min-height:70px;display:flex;flex-direction:column;gap:1px;transition:border-color .15s;cursor:grab';

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
      item.onmouseover = function(){item.style.background='rgba(255,255,255,.06)';};
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
    '<div style="display:flex;justify-content:space-between;align-items:center">' +
      '<span style="font-size:.5rem;font-weight:800;font-family:\'Barlow Condensed\',sans-serif;color:'+(cfg.color||'var(--muted)')+';opacity:.9">'+(posKey+(isBench?'·B':''))+(otherPos?'<span style="opacity:.6">/'+otherPos+'</span>':'')+'</span>'+
      '<span style="font-size:.52rem;font-weight:800;font-family:\'Barlow Condensed\',sans-serif;color:'+sig.col+'">'+sig.label+'</span>'+
    '</div>'+
    '<div style="font-weight:700;font-size:.74rem;cursor:pointer;color:'+(isInj?'var(--red)':'var(--text)')+';overflow:hidden;text-overflow:ellipsis;white-space:nowrap;line-height:1.2" onclick="searchAndShowPlayer(\''+safeKey+'\')" title="'+dn+'">'+dn+'</div>'+
    '<div style="font-size:.58rem;color:var(--muted)">'+(p?p.team:'')+(isInj?' 🚑':'')+'</div>'+
    '<div style="display:flex;align-items:baseline;gap:2px;margin-top:1px">'+
      '<span style="font-family:\'Barlow Condensed\',sans-serif;font-weight:800;font-size:.9rem;color:'+avgCol+'">'+(st&&st.avg?st.avg.toFixed(0):'—')+'</span>'+
      (proj!=null?'<span style="font-family:\'Barlow Condensed\',sans-serif;font-size:.72rem;color:var(--accent2)">→'+proj+'</span>':'')+
      (trendSym?'<span style="font-size:.62rem;color:'+trendCol+'">'+trendSym+'</span>':'')+
    '</div>'+
    '<div style="font-size:.57rem;color:var(--muted)">'+(st&&st.price?fmtPrice(st.price):'')+'</div>'+
    '<button onclick="removeFromMyTeam(\''+safeKey+'\')" style="position:absolute;top:2px;right:3px;background:none;border:none;color:rgba(255,255,255,.13);cursor:pointer;font-size:.62rem;padding:1px;line-height:1">✕</button>';
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

  // ── 1. Injury alerts ─────────────────────────────────────────────────────
  squad.forEach(function(key){
    const p=getP(key); if(!p||!INJURED_SET||!INJURED_SET.has(p.name)) return;
    const onField = ['DEF','MID','RUC','FWD'].some(function(pos){return starters(pos,grouped).includes(key);});
    tips.push({pri:1,icon:'🚑',title:(p.name)+' — INJURED',col:'var(--red)',
      body:(onField?'🚨 On your FIELD — urgent trade out needed. ':'On bench. ')+
        'Check official team announcements. Trade out for available replacement.'});
  });
AFL Fantasy Brownlow Calculator - FIXED VERSION
Changes from previous:
- BUGFIX: Vote Race showed incorrect cumulative DT (e.g. John Noble +6 votes R9→R10)
  Root cause: build_leaderboard_history accumulated dt_totals inside the round loop
  without a per-round deduplication guard, so past scores were re-added each round.
  Fix: use a seen set per round, only add each player's score once per round.
- Upcoming Fixture: now matches Historical card format with predicted avg pts and
  ▲/▼ difficulty descriptor. 6-column grid (minmax 160px).
- Trading Centre: visual overhaul — position color badges, inline stats on player
  chips, smarter summary panel, improved bookmarks UX.
"""

import os, re, json, math
from collections import defaultdict

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
    "RIC":"Tigers","STK":"Saints","WCE":"Eagles","WB":"Bulldogs","WBD":"Bulldogs",
    "ADE":"Crows","ADEL":"Crows",
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

def detect_format(lines):
    for line in lines:
        line = line.strip()
        if re.match(r"^(.+?):\s*\d+\.\d+\.\d+\s*$", line): return "fanfooty"
        if line.upper() == "FIXTURE": return "footywire_old"
        if re.match(r"^\d+\t.+\t.+\t\$[\d,]+\t\$[\d,]+\t\d+\t[\d.]+$", line): return "footywire"
    return None

def clean_name(name):
    return re.sub(r'\s+(INJ|Injured|Susp|Suspended|Out|Omitted)$', '', name.strip(), flags=re.IGNORECASE).strip()

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
    """Returns (current_prices dict, injured_set).
    Injured players have 'INJ', 'Injured', 'Susp', 'Suspended', or 'Out'
    appended to their name in the raw data before clean_name strips it."""
    current_prices = {}
    injured_set = set()
    if not os.path.exists(filepath): return current_prices, injured_set
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
        # Detect injury flag BEFORE cleaning name
        if re.search(r'\s+(INJ|Injured|Susp|Suspended|Out|Omitted)$', raw_name, re.IGNORECASE):
            injured_set.add(clean_name(raw_name))
        name = clean_name(raw_name)
        price = parse_price(parts[4].strip())
        if name and price: current_prices[name] = price
    return current_prices, injured_set

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
    pos_lookup = {}
    sp_lookup  = {}
    for p in players_registry:
        pos_lookup[p["name"]]  = p["positions"]
        sp_lookup[p["name"]]   = p["starting_price"]
    pre_prices = {}
    for rn in sorted_rounds:
        for p in all_rounds[rn]["all_players"]:
            key = make_player_key(p["player"], p["team"])
            if key not in pre_prices: pre_prices[key] = {}
            pre_prices[key][rn] = p.get("price")
    player_data = {}
    for rn in sorted_rounds:
        for p in all_rounds[rn]["all_players"]:
            key = make_player_key(p["player"], p["team"])
            if key not in player_data:
                player_data[key] = {
                    "name":p["player"],"team":p["team"],"key":key,
                    "history":[],"current_price":current_prices.get(p["player"]),
                    "positions": pos_lookup.get(p["player"], []),
                    "starting_price": sp_lookup.get(p["player"])
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
            player_data[key]["history"].append({
                "round":rn,"score":p["score"],
                "pre_price":pre_price,"post_price":post_price,"votes":votes
            })
    existing_names = {v["name"] for v in player_data.values()}
    for rp in players_registry:
        if rp["name"] not in existing_names:
            key = make_player_key(rp["name"], rp["team"])
            if key not in player_data:
                player_data[key] = {
                    "name":rp["name"],"team":rp["team"],"key":key,
                    "history":[],"current_price":current_prices.get(rp["name"]),
                    "positions":rp["positions"],
                    "starting_price":rp["starting_price"]
                }
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

def compute_form_rating(scores, current_price):
    if not scores or current_price is None or current_price == 0: return None
    weights = [1.5**i for i in range(len(scores))]
    weighted_avg = sum(s*w for s,w in zip(scores, weights)) / sum(weights)
    value_per_k  = weighted_avg / (current_price / 1000)
    baseline     = 0.1
    raw          = (value_per_k / baseline) * 50
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
<title>AFL Fantasy Brownlow</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;600;700;800&family=Barlow:wght@400;500;600&display=swap');
:root {
  --bg:#0d0f1a; --surface:#141726; --surface2:#1c2035;
  --border:rgba(255,255,255,0.07); --accent:#e8a020; --accent2:#3b82f6;
  --red:#f87171; --green:#34d399; --yellow:#fbbf24;
  --silver:#c0c0c0; --bronze:#cd7f32;
  --text:#e8eaf0; --muted:#6b7280;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden}
body{background:var(--bg);color:var(--text);font-family:'Barlow',sans-serif;display:flex;flex-direction:column}
header{display:flex;align-items:center;background:var(--surface);border-bottom:1px solid var(--border);flex-shrink:0}
.logo{padding:0 24px;height:56px;display:flex;align-items:center;gap:8px;font-weight:800;font-size:1.15rem;letter-spacing:.04em;color:var(--accent);white-space:nowrap;border-right:1px solid var(--border)}
.logo span{color:var(--text);font-weight:600}
nav{display:flex;flex:1}
.nav-btn{padding:0 12px;height:56px;border:none;background:transparent;color:var(--muted);font-weight:700;font-size:.88rem;letter-spacing:.05em;text-transform:uppercase;cursor:pointer;border-bottom:3px solid transparent;transition:all .2s;border-right:1px solid var(--border)}
.nav-btn:hover{color:var(--text);background:rgba(255,255,255,.03)}
.nav-btn.active{color:var(--accent);border-bottom-color:var(--accent);background:rgba(232,160,32,.06)}
.rounds-badge{margin-left:auto;padding:0 20px;height:56px;display:flex;align-items:center;font-size:.75rem;color:var(--muted);border-left:1px solid var(--border);white-space:nowrap}
main{flex:1;overflow:hidden;position:relative}
.page{position:absolute;inset:0;overflow-y:auto;padding:20px 24px;display:none}
.page.active{display:block}
#page-leaderboard{padding:14px 0}
.std-table{width:100%;border-collapse:collapse}
.std-table th{text-align:left;padding:9px 12px;font-size:.7rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border);font-weight:600;white-space:nowrap}
.std-table td{padding:9px 12px;border-bottom:1px solid var(--border);font-size:.95rem}
.std-table tr:hover td{background:rgba(255,255,255,.02)}
.ta-r{text-align:right}
.player-link{font-weight:700;cursor:pointer;color:var(--text)}
.player-link:hover{color:var(--accent);text-decoration:underline}
.team-tag{display:inline-block;padding:1px 6px;border-radius:3px;background:var(--surface2);font-size:.7rem;color:var(--muted);font-family:'Barlow',sans-serif}
.pos-badge{display:inline-block;padding:1px 6px;border-radius:3px;background:rgba(59,130,246,.18);font-size:.7rem;color:#93c5fd;font-weight:700}
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
.search-result:hover{background:rgba(255,255,255,.05);color:var(--accent)}
.search-result .sr-sub{font-size:.74rem;color:var(--muted)}
.player-card{display:none}
.player-card.active{display:block}
.pc-header{margin-bottom:16px;display:flex;align-items:flex-start;gap:14px}
.pc-name{font-weight:800;font-size:1.9rem;line-height:1.1}
.pc-sub{color:var(--muted);font-size:.85rem;margin-top:4px}
.bookmark-btn{background:none;border:none;cursor:pointer;padding:4px;display:flex;align-items:center;opacity:.4;transition:opacity .15s,filter .15s;flex-shrink:0;margin-top:6px}
.bookmark-btn:hover{opacity:.75}
.bookmark-btn.bookmarked{opacity:1;filter:drop-shadow(0 0 5px var(--accent))}
.bookmark-btn svg{width:28px;height:28px}
.stats-row{display:flex;gap:8px;margin-bottom:20px;overflow-x:auto;padding-bottom:2px}
.stat-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:9px 12px;flex:1;min-width:88px}
.stat-label{font-size:.6rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin-bottom:2px;white-space:nowrap}
.stat-value{font-weight:800;font-size:1.35rem;white-space:nowrap}
.rating-bar-wrap{margin-top:4px;height:3px;background:var(--surface2);border-radius:2px;overflow:hidden}
.rating-bar{height:100%;border-radius:2px}
.chart-section{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:20px;margin-bottom:14px}
.chart-title{font-weight:700;font-size:.75rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:14px}
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
.diff-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}
@media(max-width:1100px){.diff-grid{grid-template-columns:repeat(4,1fr)}}
@media(max-width:700px){.diff-grid{grid-template-columns:repeat(2,1fr)}}
.diff-card{border:1px solid var(--border);border-radius:9px;padding:13px 16px}
.diff-card.easy{background:rgba(52,211,153,.07);border-color:rgba(52,211,153,.3)}
.diff-card.medium{background:rgba(251,191,36,.07);border-color:rgba(251,191,36,.3)}
.diff-card.hard{background:rgba(248,113,113,.07);border-color:rgba(248,113,113,.3)}
.diff-team{font-weight:800;font-size:1.05rem;margin-bottom:4px}
.diff-meta{font-size:.75rem;color:var(--muted);margin-bottom:5px}
.diff-rating-num{font-weight:800;font-size:1.25rem}
.diff-legend{display:flex;gap:16px;margin-bottom:14px;font-size:.78rem}
/* Upcoming fixture difficulty — 6-per-row, matches historical card layout */
.upcoming-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-top:4px}
@media(max-width:1100px){.upcoming-grid{grid-template-columns:repeat(4,1fr)}}
@media(max-width:700px){.upcoming-grid{grid-template-columns:repeat(2,1fr)}}
.upcoming-card{border:1px solid var(--border);border-radius:9px;padding:10px 12px}
.upcoming-card.easy{background:rgba(52,211,153,.07);border-color:rgba(52,211,153,.3)}
.upcoming-card.medium{background:rgba(251,191,36,.07);border-color:rgba(251,191,36,.3)}
.upcoming-card.hard{background:rgba(248,113,113,.07);border-color:rgba(248,113,113,.3)}
.upcoming-games-list{margin-top:5px;display:none;font-size:.7rem;color:var(--muted)}
.upcoming-games-list.open{display:block}
.upcoming-game-row{display:flex;justify-content:space-between;padding:2px 0;border-bottom:1px solid rgba(255,255,255,.04)}
.upcoming-game-row:last-child{border-bottom:none}

/* ── Trading Centre ── */
.trade-layout{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:800px){.trade-layout{grid-template-columns:1fr}}
.trade-panel{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px}
.trade-panel-title{font-weight:800;font-size:1rem;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.trade-list{list-style:none;display:flex;flex-direction:column;gap:5px;min-height:50px}

/* Upgraded trade item */
.trade-item{display:flex;align-items:flex-start;gap:7px;padding:10px 11px;background:var(--surface2);border-radius:8px;border:1px solid var(--border);transition:border-color .15s}
.trade-item:hover{border-color:rgba(255,255,255,.14)}
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
.net-arrow.neu{background:rgba(255,255,255,.05);color:var(--muted)}

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
.fix-table td{padding:5px 8px;border-bottom:1px solid rgba(255,255,255,.04)}
.fix-table tr:last-child td{border-bottom:none}
.fix-proj{font-weight:800}
/* Price support/resistance label */
.price-level-label{font-size:.68rem;font-style:italic}
/* Leaderboard form boxes */
.form-boxes{display:flex;gap:3px;align-items:center}
.form-box{width:20px;height:20px;border-radius:3px;display:inline-flex;align-items:center;justify-content:center;font-size:.65rem;font-weight:800;border:1px solid rgba(255,255,255,.07)}
.form-box-0{background:rgba(255,255,255,.04);color:transparent}
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
.scenario-overlay-body{flex:1;overflow-y:auto;padding:24px}
.scenarios-compare-grid{display:grid;gap:14px}
/* Scenario card matches trading panel style */
.scenario-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px}
.scenario-card:hover{border-color:rgba(255,255,255,.12)}
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
.sc-dropdown-item:hover{background:rgba(255,255,255,.05);color:var(--accent)}
.sc-rel{position:relative}
.stats-compare-box{margin-top:12px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;overflow:hidden}
.stats-collapse-header{display:flex;align-items:center;justify-content:space-between;padding:10px 13px;cursor:pointer;user-select:none;font-size:.82rem;font-weight:700}
.stats-collapse-header:hover{background:rgba(255,255,255,.03)}
.stats-collapse-arrow{font-size:.7rem;transition:transform .2s;color:var(--muted)}
.stats-collapse-arrow.open{transform:rotate(180deg)}
.stats-collapse-body{display:none;padding:0 13px 13px}
.stats-collapse-body.open{display:block}
.scb-row{display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid rgba(255,255,255,.04)}
.scb-row:last-child{border-bottom:none}
.scb-label{color:var(--muted)}
.scb-val{font-weight:700}
.winner-crown{color:var(--accent);font-size:.75rem;margin-left:4px}
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
.squad-card:hover{border-color:rgba(255,255,255,.18)}
.squad-card.bench-card{background:rgba(255,255,255,.025);opacity:.85}
.squad-card.empty-card{border:1px dashed rgba(255,255,255,.12);background:transparent;cursor:pointer;display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:.75rem}
.squad-card.empty-card:hover{border-color:var(--accent2);color:var(--accent2)}
.squad-card-pos{position:absolute;top:6px;left:7px;font-size:.58rem;font-weight:800;padding:1px 4px;border-radius:3px}
.squad-card-name{font-weight:700;font-size:.8rem;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:14px}
.squad-card-name:hover{color:var(--accent)}
.squad-card-team{font-size:.65rem;color:var(--muted)}
.squad-card-avg{font-weight:800;font-size:1.05rem}
.squad-card-price{font-size:.68rem;color:var(--muted)}
.squad-card-sig{position:absolute;top:6px;right:7px;font-size:.6rem;font-weight:800;padding:1px 5px;border-radius:3px}
.squad-card-remove{position:absolute;bottom:5px;right:6px;background:none;border:none;color:rgba(255,255,255,.2);cursor:pointer;font-size:.75rem;padding:1px 3px;border-radius:2px}
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
</style>
</head>
<body>
<header>
  <div class="logo">&#127945; AFL <span>Fantasy Brownlow</span></div>
  <nav>
    <button class="nav-btn active"  onclick="showPage('leaderboard',this)">&#127942; Leaderboard</button>
    <button class="nav-btn"         onclick="showPage('rounds',this)">&#128203; Round Scores</button>
    <button class="nav-btn"         onclick="showPage('players',this)">&#128200; Player Stats</button>
    <button class="nav-btn"         onclick="showPage('difficulty',this)">&#128737; Matchup Difficulty</button>
    <button class="nav-btn"         onclick="showPage('trading',this)">&#128176; Trading Centre</button>
    <button class="nav-btn"         onclick="showPage('myteam',this)">&#127945; My Team</button>
    <button class="nav-btn"         onclick="showPage('rolling22',this)">&#127942; Rolling 22</button>
  </nav>
</header>
<main>

<!-- LEADERBOARD PAGE -->
<div class="page active" id="page-leaderboard">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;flex-wrap:wrap;padding:0 8px">
    <div style="font-weight:800;font-size:1.1rem;color:var(--text)">&#127942; Leaderboard</div>
    <button class="info-btn" id="infoBtn-leaderboard" onclick="toggleInfo('leaderboard')">&#9432; How it works</button>
    <button class="race-btn" id="voteRaceToggleBtn" onclick="toggleVoteRace()" style="margin-left:auto">&#127885; Vote Race</button>
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
  <div id="lbSection">
    <table class="std-table">
      <thead><tr>
        <th>Pos</th><th>Player</th><th>Club</th>
        <th class="ta-r">Current Price</th><th class="ta-r">Avg FP</th>
        <th class="ta-r">Total FP</th><th class="ta-r">Votes</th>
        <th>Form (L5)</th>
        <th>Status</th>
      </tr></thead>
      <tbody id="lbBody"></tbody>
    </table>
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

<!-- ROUNDS PAGE -->
<div class="page" id="page-rounds">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px">
    <div style="font-weight:800;font-size:1.1rem;color:var(--text)">&#128203; Round Scores</div>
    <button class="info-btn" id="infoBtn-rounds" onclick="toggleInfo('rounds')">&#9432; How it works</button>
  </div>
  <div class="info-panel" id="info-rounds">
    <div class="info-heading">&#128203; Round Scores</div>
    Displays each game for the selected round, showing the <b>3 vote-getters per match</b>.<br><br>
    Click a player name to view their full history in Player Stats.
  </div>
  <div class="round-tabs" id="roundTabs"></div>
  <div class="games-grid" id="gamesGrid"></div>
</div>

<!-- PLAYER STATS PAGE -->
<div class="page" id="page-players">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px">
    <div style="font-weight:800;font-size:1.1rem;color:var(--text)">&#128200; Player Stats</div>
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
      <div>
        <div class="pc-name" id="pcName"></div>
        <div class="pc-sub" id="pcSub"></div>
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
    <div class="chart-section">
      <div class="chart-title">Score &amp; Price History</div>
      <canvas id="mainChart"></canvas>
    </div>
    <div class="chart-section" id="valueSection" style="display:none">
      <div class="chart-title">Value vs Expectation (Score &minus; Price &divide; 10,490)</div>
      <canvas id="valueChart"></canvas>
    </div>
  </div>
</div>

<!-- MATCHUP DIFFICULTY PAGE -->
<div class="page" id="page-difficulty">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px">
    <div style="font-weight:800;font-size:1.1rem;color:var(--text)">&#128737; Matchup Difficulty</div>
    <button class="info-btn" id="infoBtn-difficulty" onclick="toggleInfo('difficulty')">&#9432; How it works</button>
  </div>
  <div class="info-panel" id="info-difficulty">
    <div class="info-heading">&#128737; Matchup Difficulty Rating</div>
    <b>Historical tab:</b> How do players score vs their own average when facing each team? Rating 100 = league average. Above 100 = easier.<br><br>
    <b>Upcoming Fixture tab:</b> Predicted avg pts your players will score in each upcoming game, based on the opponent&apos;s historical concede rating. Weighted so closer games count more.
  </div>
  <div style="display:flex;gap:8px;margin-bottom:18px">
    <button class="diff-tab active" id="diffSubHistorical" onclick="showDiffSub('historical')">&#128202; Historical</button>
    <button class="diff-tab" id="diffSubUpcoming" onclick="showDiffSub('upcoming')">&#128197; Upcoming Fixture</button>
  </div>
  <div id="diffHistoricalSection">
    <div class="diff-legend">
      <span style="color:var(--green)">&#9679; Easiest to score against</span>
      <span style="color:var(--yellow)">&#9679; Average difficulty</span>
      <span style="color:var(--red)">&#9679; Hardest to score against</span>
    </div>
    <div class="diff-tabs" id="diffTabs"></div>
    <div id="diffContent"></div>
  </div>
  <div id="diffUpcomingSection" style="display:none">
    <div class="diff-legend">
      <span style="color:var(--green)">&#9679; Easiest upcoming schedule</span>
      <span style="color:var(--yellow)">&#9679; Average schedule</span>
      <span style="color:var(--red)">&#9679; Toughest upcoming schedule</span>
    </div>
    <div class="diff-tabs" id="upcomingPosTabs"></div>
    <div id="upcomingContent"></div>
  </div>
</div>

<!-- TRADING CENTRE PAGE -->
<div class="page" id="page-trading">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px">
    <div style="font-weight:800;font-size:1.1rem;color:var(--text)">&#128176; Trading Centre</div>
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
          <div id="tradeScoreBar" style="display:none;margin-top:10px;background:var(--surface2);border:1px solid var(--border);border-radius:7px;padding:9px 12px">
            <div style="font-size:.62rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:5px;font-weight:700">&#127919; Trade Quality Score</div>
            <div style="display:flex;align-items:center;gap:8px">
              <div style="flex:1;height:6px;background:var(--border);border-radius:3px;overflow:hidden">
                <div id="tradeScoreFill" style="height:100%;border-radius:3px;transition:width .4s,background .4s"></div>
              </div>
              <span id="tradeScoreLabel" style="font-weight:800;font-size:1.05rem;min-width:36px;text-align:right"></span>
            </div>
            <div id="tradeScoreBreakdown" style="margin-top:5px;font-size:.68rem;color:var(--muted)"></div>
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
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap">
    <div style="font-weight:800;font-size:1.1rem">&#127945; My Team</div>
    <button class="info-btn" id="infoBtn-myteam" onclick="toggleInfo('myteam')">&#9432; How it works</button>
    <div style="margin-left:auto;display:flex;gap:8px;flex-wrap:wrap">
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
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px;flex-wrap:wrap">
    <div style="font-weight:800;font-size:1.1rem">&#127942; Rolling 22 — Best Projected Team</div>
    <button class="info-btn" id="infoBtn-rolling22" onclick="toggleInfo('rolling22')">&#9432; How it works</button>
    <div style="margin-left:auto;display:flex;gap:6px">
      <button class="race-btn" onclick="renderRolling22('overall')">Overall</button>
      <button class="race-btn" onclick="renderRolling22('form')">Form-weighted</button>
      <button class="race-btn" onclick="renderRolling22('fixture')">Fixture-adjusted</button>
    </div>
  </div>
  <div class="info-panel" id="info-rolling22">
    <div class="info-heading">&#127942; Rolling 22</div>
    Shows the best projected 22-man AFL Fantasy team from your loaded data, laid out in DEF/MID/RUC/FWD formation.<br><br>
    <b>Overall</b> — ranked by season avg FP. <b>Form-weighted</b> — last-3 avg vs price value. <b>Fixture-adjusted</b> — projected scores using upcoming opponent difficulty ratings.<br><br>
    Players only appear once (their primary position is used). Bench spots show the next-best available.
  </div>
  <div id="rolling22Grid"></div>
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
const LEADERBOARD      = __LEADERBOARD__;
const ROUNDS_DATA      = __ROUNDS_DATA__;
const PLAYERS_DATA     = __PLAYERS_DATA__;
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

let mainChartInst = null, valueChartInst = null, currentPlayerKey = null;
let raceFrame = 0, raceTimer = null;

const duplicateNames = new Set(
  PLAYERS_DATA.filter((p,_,arr) => arr.filter(x => x.name === p.name).length > 1).map(p => p.name)
);
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

function showPage(id, btn) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  var pageEl = document.getElementById('page-' + id);
  if (!pageEl) return;
  pageEl.classList.add('active');
  if (btn) btn.classList.add('active');
  if (id === 'trading') renderTradeLists();
  if (id === 'myteam') renderMyTeam();
  if (id === 'rolling22') renderRolling22('overall');
}

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
  const tbody = document.getElementById('lbBody');
  let pos = 1, prevVotes = null;
  LEADERBOARD.forEach((e, i) => {
    if (e.votes !== prevVotes) pos = i + 1;
    prevVotes = e.votes;
    const pc = pos===1?'p1':pos===2?'p2':pos===3?'p3':'';
    const dn = e.display_name || getDisplayName(e.player, e.team);
    // Form boxes: last 5 rounds' votes
    var formHtml = '<div class="form-boxes">';
    (e.form_history || []).forEach(function(f) {
      const lbl = f.r === 0 ? 'Op' : 'R' + f.r;
      if (f.v === 0) formHtml += '<div class="form-box form-box-0" title="' + lbl + ': no votes">&nbsp;</div>';
      else formHtml += '<div class="form-box form-box-' + f.v + '" title="' + lbl + ': ' + f.v + ' vote' + (f.v>1?'s':'') + '">' + f.v + '</div>';
    });
    formHtml += '</div>';
    const tr = document.createElement('tr');
    tr.innerHTML =
      '<td class="pos-num ' + pc + '">' + pos + '</td>' +
      '<td><span class="player-link" onclick="searchAndShowPlayer(\'' + e.key.replace(/'/g,"\\'") + '\')">' + dn + '</span></td>' +
      '<td><span class="team-tag">' + e.team + '</span></td>' +
      '<td class="ta-r" style="color:#fff;font-family:\'Barlow Condensed\',sans-serif">' + fmtPrice(e.price) + '</td>' +
      '<td class="ta-r" style="font-family:\'Barlow Condensed\',sans-serif;font-weight:700">' + e.avg + '</td>' +
      '<td class="ta-r" style="color:var(--muted);font-family:\'Barlow Condensed\',sans-serif">' + e.total_dt + '</td>' +
      '<td class="ta-r votes-hl">' + e.votes + '</td>' +
      '<td>' + formHtml + '</td>' +
      (e.is_injured ? '<td><span style="background:rgba(248,113,113,.2);color:var(--red);font-size:.65rem;font-weight:700;padding:1px 5px;border-radius:3px">INJ</span></td>' : '<td></td>');
    tbody.appendChild(tr);
  });
})();

// ── Round browser ─────────────────────────────────────────────────────────────
let activeRound = ROUNDS_DATA.length ? ROUNDS_DATA[0].round : null;
function renderRoundTabs() {
  const tabs = document.getElementById('roundTabs'); tabs.innerHTML = '';
  ROUNDS_DATA.forEach(rd => {
    const btn = document.createElement('button');
    btn.className = 'round-tab' + (rd.round === activeRound ? ' active' : '');
    btn.textContent = rd.round === 0 ? 'Opening' : 'Round ' + rd.round;
    btn.onclick = function() { activeRound = rd.round; renderRoundTabs(); renderGames(); };
    tabs.appendChild(btn);
  });
}
function renderGames() {
  const grid = document.getElementById('gamesGrid'); grid.innerHTML = '';
  const rd = ROUNDS_DATA.find(r => r.round === activeRound); if (!rd) return;
  rd.games.forEach(game => {
    const card = document.createElement('div'); card.className = 'game-card';
    const vClasses = ['','v1','v2','v3'], vLabels = ['','1 vote','2 votes','3 votes'];
    let rows = '';
    game.votes.forEach(v => {
      const dn = getDisplayName(v.player, v.team);
      rows += '<div class="vote-row">' +
        '<div class="vote-badge ' + vClasses[v.votes] + '">' + vLabels[v.votes] + '</div>' +
        '<div style="flex:1"><div class="vote-player" onclick="searchAndShowPlayerByNameTeam(\'' +
          v.player.replace(/'/g,"\\'") + '\',\'' + v.team.replace(/'/g,"\\'") + '\')">' + dn + '</div>' +
        '<div class="vote-team">' + v.team + '</div></div>' +
        '<div class="vote-score">' + v.score + '</div></div>';
    });
    card.innerHTML = '<div class="game-header">' + game.team_a + '<span class="vs">vs</span>' + game.team_b + '</div>' + rows;
    grid.appendChild(card);
  });
}
renderRoundTabs(); renderGames();

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
    '<span class="sr-sub">' + p.team + (p.positions && p.positions.length ? ' &middot; ' + p.positions.join('/') : '') + '</span>' +
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
  document.querySelectorAll('.nav-btn')[2].classList.add('active');
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
  document.getElementById('pcName').textContent = '\u{1F3C9} ' + dn;
  const posTxt = p.positions && p.positions.length ? p.positions.join('/') + ' \u00b7 ' : '';
  document.getElementById('pcSub').textContent = posTxt + p.team + (n ? ' \u00b7 Rounds: ' + rounds.map(r => r===0?'Opening':'R'+r).join(', ') : ' \u00b7 No game data');

  const projScore = calcProjectedScore(key);
  const isInjured = INJURED_SET && INJURED_SET.has(p.name);
  let s = '';
  // Injury warning at top
  if (isInjured) {
    s += '<div style="grid-column:1/-1;background:rgba(248,113,113,.12);border:1px solid rgba(248,113,113,.3);border-radius:7px;padding:6px 12px;font-size:.8rem;color:var(--red);font-weight:700;margin-bottom:4px">⚠️ Reported as INJURED — check official team lists before trading in</div>';
  }
  if (n) {
    s += '<div class="stat-card"><div class="stat-label">Avg FP</div><div class="stat-value">' + avg.toFixed(1) + '</div></div>';
    s += '<div class="stat-card"><div class="stat-label">L3 Avg</div><div class="stat-value">' + last3.toFixed(1) + '</div></div>';
    s += '<div class="stat-card"><div class="stat-label">L5 Avg</div><div class="stat-value">' + last5.toFixed(1) + '</div></div>';
    if (projScore != null) s += '<div class="stat-card" style="border-color:rgba(59,130,246,.3);background:rgba(59,130,246,.08)"><div class="stat-label" style="color:var(--accent2)">Projected</div><div class="stat-value" style="color:var(--accent2)">' + projScore + '</div></div>';
    s += '<div class="stat-card"><div class="stat-label">High</div><div class="stat-value">' + best + '</div></div>';
    s += '<div class="stat-card"><div class="stat-label">Votes</div><div class="stat-value">' + totalV + '</div></div>';
    s += '<div class="stat-card"><div class="stat-label">Rounds</div><div class="stat-value">' + n + '</div></div>';
  }
  if (currentPrice != null)
    s += '<div class="stat-card"><div class="stat-label">Price</div><div class="stat-value" style="color:#fff">' + fmtPrice(currentPrice) + '</div></div>';
  if (priceChange !== null)
    s += '<div class="stat-card"><div class="stat-label">Δ Price</div><div class="stat-value" style="color:' + pcColor + '">' + pcLabel + '</div></div>';
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

    mainChartInst = new Chart(document.getElementById('mainChart'), {
      data: { labels: labels, datasets: [
        {type:'bar',label:'Fantasy Score',data:scores,yAxisID:'scoreAxis',backgroundColor:'rgba(59,130,246,.75)',borderRadius:4},
        {type:'line',label:'Price',data:postPrices,yAxisID:'priceAxis',tension:.3,borderWidth:2.5,borderColor:'#f87171',backgroundColor:'transparent',pointBackgroundColor:'#f87171',pointRadius:4,spanGaps:false}
      ]},
      options: { responsive:true, interaction:{mode:'index',intersect:false},
        plugins: {
          tooltip: {callbacks: {label: function(ctx) {
            if (ctx.dataset.label==='Price') { var v=ctx.parsed.y; return v==null?null:'Price: '+fmtPrice(v); }
            var v = votes[ctx.dataIndex]; return 'Score: '+ctx.parsed.y+(v>0?' ('+v+' vote'+(v>1?'s':'')+')'  :'');
          }}},
          legend: {labels: {color:'#e8eaf0'}}
        },
        scales: {
          scoreAxis: {type:'linear',position:'left',ticks:{color:'#e8eaf0'},grid:{color:'rgba(255,255,255,.06)'},title:{display:true,text:'Fantasy Score',color:'#e8eaf0'}},
          priceAxis: {type:'linear',position:'right',suggestedMin:minP,suggestedMax:maxP,grid:{drawOnChartArea:false},ticks:{color:'#f87171',callback:function(v){return fmtPrice(v);}},title:{display:true,text:'Price',color:'#f87171'}},
          x: {ticks:{color:'#e8eaf0'}}
        }
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
          scales:{y:{ticks:{color:'#e8eaf0'},grid:{color:'rgba(255,255,255,.06)'},title:{display:true,text:'Points Above/Below Expected',color:'#e8eaf0'}},x:{ticks:{color:'#e8eaf0'}}}
        }
      });
    } else document.getElementById('valueSection').style.display = 'none';
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

(function() {
  var ALL_DIFFS = Object.assign({ 'Overall': OVERALL_DIFF }, POS_DIFF);
  const tabs = document.getElementById('diffTabs');
  const content = document.getElementById('diffContent');
  var activeTab = 'Overall';

  function renderDiffTab(key) {
    activeTab = key;
    tabs.querySelectorAll('.diff-tab').forEach(function(t) { t.classList.toggle('active', t.dataset.key === key); });
    const data = ALL_DIFFS[key] || [];
    if (!data.length) { content.innerHTML = '<div style="color:var(--muted);padding:20px">No data for this position yet.</div>'; return; }
    const n = data.length;
    const easyCount = Math.ceil(n/3), hardStart = Math.floor(2*n/3);
    content.innerHTML = '';
    const grid = document.createElement('div'); grid.className = 'diff-grid';
    data.forEach(function(d, i) {
      const tier = i < easyCount ? 'easy' : i >= hardStart ? 'hard' : 'medium';
      const col  = tier==='easy' ? 'var(--green)' : tier==='medium' ? 'var(--yellow)' : 'var(--red)';
      const card = document.createElement('div'); card.className = 'diff-card ' + tier;
      const barW = Math.min(100, Math.max(0, ((d.rating - 80) / 40) * 100));
      card.innerHTML =
        '<div class="diff-team" style="color:' + col + '">' + d.team + '</div>' +
        '<div class="diff-meta">' + d.games + ' player-games \u00b7 league avg: ' + AFL_AVG.toFixed(1) + ' pts</div>' +
        '<div style="display:flex;justify-content:space-between;align-items:flex-end">' +
          '<div><div style="font-size:.62rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em">Avg pts conceded</div>' +
          '<div class="diff-rating-num" style="color:' + col + '">' + d.avg_conceded + ' pts</div></div>' +
          '<div style="text-align:right"><div style="font-size:.62rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em">Difficulty rating</div>' +
          '<div class="diff-rating-num" style="color:' + col + '">' + d.rating + '</div></div>' +
        '</div>' +
        '<div style="font-size:.65rem;color:var(--muted);margin-top:4px">' +
          (d.rating > 100 ? '\u25b2 Players score ' + (d.rating - 100).toFixed(1) + '% above their avg here' :
           d.rating < 100 ? '\u25bc Players score ' + (100 - d.rating).toFixed(1) + '% below their avg here' :
           'Exactly league average difficulty') +
        '</div>' +
        '<div class="rating-bar-wrap" style="margin-top:6px;height:4px"><div class="rating-bar" style="width:' + barW + '%;background:' + col + '"></div></div>';
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

// ── Upcoming Fixture Difficulty — matches historical card layout ──────────────
(function() {
  const ALL_POS = ['Overall', 'DEF', 'MID', 'RUC', 'FWD'];
  const tabs = document.getElementById('upcomingPosTabs');
  const content = document.getElementById('upcomingContent');

  function getAflAvg(posKey) {
    if (posKey === 'Overall') return UPCOMING_AFL_AVG;
    return UPCOMING_AFL_AVG_POS && UPCOMING_AFL_AVG_POS[posKey] != null ? UPCOMING_AFL_AVG_POS[posKey] : null;
  }

  // Gradient: green (easy, score>108) → yellow-green → yellow → orange → red (hard, score<92)
  // Using explicit colour stops for maximum visual contrast
  function gradientColor(score, alpha) {
    alpha = alpha || 1;
    // Map score to 0-1: 85=hard=0, 115=easy=1
    const t = Math.max(0, Math.min(1, (score - 85) / 30));
    var r, g, b;
    if (t >= 0.67) {
      // Green zone: 100→ hue 100-120
      const u = (t - 0.67) / 0.33;
      r = Math.round(20  + u * 10);
      g = Math.round(200 + u * 11);
      b = Math.round(100 + u * 53);
    } else if (t >= 0.33) {
      // Yellow zone: hue 45-80
      const u = (t - 0.33) / 0.34;
      r = Math.round(240 - u * 220);
      g = Math.round(180 + u * 31);
      b = Math.round(30  + u * 70);
    } else {
      // Red-orange zone
      const u = t / 0.33;
      r = Math.round(220 - u * 20);
      g = Math.round(60  + u * 120);
      b = Math.round(20  + u * 10);
    }
    return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
  }
  function gradientBg(score) { return gradientColor(score, 0.13); }
  function gradientBorder(score) { return gradientColor(score, 0.55); }
  function gradientText(score) { return gradientColor(score, 1); }

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

    const aflAvg = getAflAvg(posKey);
    content.innerHTML = '';
    const grid = document.createElement('div');
    grid.className = 'upcoming-grid';

    sorted.forEach(function(d, i) {
      const score = posKey === 'Overall' ? d.upcoming_score : (d.upcoming_pos[posKey] || 100);
      const predAvg = posKey === 'Overall'
        ? d.predicted_avg
        : (d.predicted_avg_pos && d.predicted_avg_pos[posKey] != null ? d.predicted_avg_pos[posKey] : null);

      const col    = gradientText(score);
      const bgCol  = gradientBg(score);
      const bdCol  = gradientBorder(score);
      const barW   = Math.min(100, Math.max(0, ((score - 80) / 40) * 100));
      const barCol = gradientColor(score, 0.85);
      const detailId = 'updet_' + i + '_' + posKey.replace(/[^a-z]/gi,'');

      let descriptor = 'Average upcoming schedule';
      if (score > 100) descriptor = '\u25b2 Players score ' + (score - 100).toFixed(1) + '% above their avg';
      else if (score < 100) descriptor = '\u25bc Players score ' + (100 - score).toFixed(1) + '% below their avg';

      var gamesHtml = '';
      (d.games || []).forEach(function(g, gi) {
        const gScore = posKey === 'Overall' ? g.overall : (g.pos[posKey] || 100);
        const gPred  = posKey === 'Overall' ? g.predicted_avg : (g.predicted_pos && g.predicted_pos[posKey] != null ? g.predicted_pos[posKey] : null);
        const gCol   = gradientText(gScore);
        const rLabel = g.round === 0 ? 'Open' : 'R' + g.round;
        const proximity = gi === 0 ? ' (next)' : '';
        const predTxt = gPred != null ? ' \u2022 ~' + gPred.toFixed(1) + ' pts' : '';
        gamesHtml += '<div class="upcoming-game-row">' +
          '<span>' + rLabel + proximity + ': vs ' + g.opponent + predTxt + '</span>' +
          '<span style="color:' + gCol + ';font-weight:700">' + gScore.toFixed(1) + '</span>' +
        '</div>';
      });

      const numGames = (d.games || []).length;
      const avgLine = aflAvg != null ? 'league avg: ' + aflAvg.toFixed(1) + ' pts' : numGames + ' upcoming games';

      const card = document.createElement('div');
      card.className = 'upcoming-card';
      card.style.cssText = 'background:' + bgCol + ';border-color:' + bdCol;
      card.innerHTML =
        '<div class="diff-team" style="color:' + col + '">' + d.team + '</div>' +
        '<div class="diff-meta">' + numGames + ' upcoming \u00b7 ' + avgLine + '</div>' +
        '<div style="display:flex;justify-content:space-between;align-items:flex-end">' +
          (predAvg != null
            ? '<div><div style="font-size:.58rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em">Pred avg pts</div>' +
              '<div class="diff-rating-num" style="color:' + col + '">' + predAvg.toFixed(1) + '</div></div>'
            : '<div></div>') +
          '<div style="text-align:right"><div style="font-size:.58rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em">Rating</div>' +
          '<div class="diff-rating-num" style="color:' + col + '">' + score.toFixed(1) + '</div></div>' +
        '</div>' +
        '<div style="font-size:.62rem;color:var(--muted);margin-top:3px">' + descriptor + '</div>' +
        '<div class="rating-bar-wrap" style="margin-top:5px;height:4px"><div class="rating-bar" style="width:' + barW + '%;background:' + barCol + '"></div></div>' +
        '<div style="margin-top:5px;font-size:.65rem;color:var(--accent2);cursor:pointer" onclick="toggleUpcomingGames(\'' + detailId + '\')">\u25bc Show games</div>' +
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
      '<td><span class="team-tag">' + entry.team + '</span></td>' +
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
      '<span class="team-tag">' + teamTxt + '</span>' +
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

function calcProjectedScore(key) {
  // Weighted projection: 50% L3 avg, 30% L5 avg, 20% season avg, then fixture adjustment
  // This ensures elite recent form (like Wanganeen-Milera 138 L3) drives the projection
  const p = getP(key); if (!p) return null;
  if (INJURED_SET && INJURED_SET.has(p.name)) return null; // injured = no projection
  const scores = p.history.map(function(x){return x.score;});
  const n = scores.length; if (!n) return null;
  const seasonAvg = scores.reduce(function(a,b){return a+b;},0)/n;
  const l3 = scores.slice(-3).reduce(function(a,b){return a+b;},0)/Math.min(3,n);
  const l5 = scores.slice(-5).reduce(function(a,b){return a+b;},0)/Math.min(5,n);
  // Weight: recent form matters most
  const baseProj = l3*0.50 + l5*0.30 + seasonAvg*0.20;
  // Fixture adjustment: if rating is 110 → multiply by 1.10; if 90 → multiply by 0.90
  const fix = getPlayerFixtureScore(key);
  const fixMult = fix != null ? (0.4 + fix/166.7) : 1.0; // dampened: 90→0.94, 100→1.0, 110→1.06
  return Math.round(baseProj * fixMult);
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
        const fill = document.getElementById('tradeScoreFill');
        const lbl  = document.getElementById('tradeScoreLabel');
        const bkdn = document.getElementById('tradeScoreBreakdown');
        if (fill) { fill.style.width = tradeScore + '%'; fill.style.background = tCol; }
        if (lbl)  { lbl.textContent = tradeScore + '/100'; lbl.style.color = tCol; }
        if (bkdn) {
          bkdn.innerHTML = '<b style="color:' + tCol + '">' + tLabel + '</b> · ' +
            scoreComponents.map(function(c){
              return '<span style="color:' + (c.good?'var(--green)':'var(--red)') + '">' + c.label + ': ' + (c.diff>=0?'+':'') + c.diff + '</span>';
            }).join(' · ');
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
      const posStr = p.positions && p.positions.length ? p.positions.join('/') + ' \u00b7 ' : '';
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
    const card = document.createElement('div'); card.className = 'scenario-card';
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

    function statsBlock(st, label, collapseId) {
      const arrowId = collapseId + '_arrow';
      const bodyId  = collapseId + '_body';
      const headerHtml =
        '<div class="stats-collapse-header" onclick="toggleCollapse(\'' + collapseId + '\')">' +
          '<span>' + label + (st && st.count ? ' (' + st.count + ' player' + (st.count>1?'s':'') + ')' : '') + '</span>' +
          '<span class="stats-collapse-arrow" id="' + arrowId + '">&#9660;</span>' +
        '</div>';
      if (!st || st.count === 0) {
        return headerHtml + '<div class="stats-collapse-body" id="' + bodyId + '"><div style="color:var(--muted);font-size:.78rem;padding:4px 0">No players added</div></div>';
      }
      const avgFR = st.formRating  != null ? st.formRating.toFixed(0)  : '\u2014';
      const avgCS = st.consistency != null ? st.consistency.toFixed(0) : '\u2014';
      const pcStr = st.priceChange != null ? (st.priceChange>=0?'+':'-') + fmtPrice(Math.abs(st.priceChange)) : '\u2014';
      const pcCol = st.priceChange == null ? 'var(--muted)' : st.priceChange >= 0 ? 'var(--green)' : 'var(--red)';
      var html = '';
      if (st.players && st.players.length) {
        st.players.forEach(function(p) {
          html += '<div class="scb-row"><span class="scb-label">' + p.name + ' games</span><span class="scb-val">' + p.rounds + '</span></div>';
        });
      }
      html += '<div class="scb-row"><span class="scb-label">Combined Avg FP</span><span class="scb-val">' + st.avg.toFixed(1) + '</span></div>';
      html += '<div class="scb-row"><span class="scb-label">Last 3 Avg</span><span class="scb-val">' + st.last3.toFixed(1) + '</span></div>';
      html += '<div class="scb-row"><span class="scb-label">Last 5 Avg</span><span class="scb-val">' + st.last5.toFixed(1) + '</span></div>';
      html += '<div class="scb-row"><span class="scb-label">Total Votes</span><span class="scb-val">' + st.totalVotes + '</span></div>';
      html += '<div class="scb-row"><span class="scb-label">Total FP</span><span class="scb-val">' + st.totalFP + '</span></div>';
      html += '<div class="scb-row"><span class="scb-label">Avg Form Rating</span><span class="scb-val" style="color:' + ratingColor(st.formRating) + '">' + avgFR + (st.formRating!=null?'/100':'') + '</span></div>';
      html += '<div class="scb-row"><span class="scb-label">Avg Consistency</span><span class="scb-val" style="color:' + ratingColor(st.consistency) + '">' + avgCS + (st.consistency!=null?'/100':'') + '</span></div>';
      html += '<div class="scb-row"><span class="scb-label">Combined Price</span><span class="scb-val">' + fmtPrice(st.price) + '</span></div>';
      html += '<div class="scb-row"><span class="scb-label">Season Price Change</span><span class="scb-val" style="color:' + pcCol + '">' + pcStr + '</span></div>';
      Object.entries(st.posCounts).forEach(function(e2){
        html += '<div class="scb-row"><span class="scb-label">' + e2[0] + ' players</span><span class="scb-val">' + e2[1] + '</span></div>';
      });
      return headerHtml + '<div class="stats-collapse-body" id="' + bodyId + '"><div style="padding-top:6px">' + html + '</div></div>';
    }

    function fmtNet(v, decimals) {
      decimals = decimals != null ? decimals : 1;
      if (v == null) return '\u2014';
      return (v >= 0 ? '+' : '-') + Math.abs(v).toFixed(decimals);
    }

    var netBodyHtml = '';
    if (netAvg !== null) {
      netBodyHtml += '<div class="scb-row"><span class="scb-label">Avg FP</span><span class="scb-val" style="color:' + (netAvg>=0?'var(--green)':'var(--red)') + '">' + fmtNet(netAvg) + '</span></div>';
      netBodyHtml += '<div class="scb-row"><span class="scb-label">Last 3 Avg</span><span class="scb-val" style="color:' + ((netL3||0)>=0?'var(--green)':'var(--red)') + '">' + fmtNet(netL3) + '</span></div>';
      netBodyHtml += '<div class="scb-row"><span class="scb-label">Last 5 Avg</span><span class="scb-val" style="color:' + ((netL5||0)>=0?'var(--green)':'var(--red)') + '">' + fmtNet(netL5) + '</span></div>';
      netBodyHtml += '<div class="scb-row"><span class="scb-label">Votes</span><span class="scb-val" style="color:' + ((netVotes||0)>=0?'var(--green)':'var(--red)') + '">' + fmtNet(netVotes,0) + '</span></div>';
      if (netFR !== null) netBodyHtml += '<div class="scb-row"><span class="scb-label">Form Rating</span><span class="scb-val" style="color:' + (netFR>=0?'var(--green)':'var(--red)') + '">' + fmtNet(netFR,1) + '/100</span></div>';
      if (netCS !== null) netBodyHtml += '<div class="scb-row"><span class="scb-label">Consistency</span><span class="scb-val" style="color:' + (netCS>=0?'var(--green)':'var(--red)') + '">' + fmtNet(netCS,1) + '/100</span></div>';
      if (netPriceChange !== null) netBodyHtml += '<div class="scb-row"><span class="scb-label">Price Change</span><span class="scb-val" style="color:' + (netPriceChange>=0?'var(--green)':'var(--red)') + '">' + (netPriceChange>=0?'+':'-') + fmtPrice(Math.abs(netPriceChange)) + '</span></div>';
      if (netPrice !== null) netBodyHtml += '<div class="scb-row"><span class="scb-label">Price Diff</span><span class="scb-val" style="color:' + (netPrice<=0?'var(--green)':'var(--red)') + '">' + (netPrice>=0?'+':'-') + fmtPrice(Math.abs(netPrice)) + '</span></div>';
      if (posDeltaHtml) netBodyHtml += '<div class="scb-row" style="flex-direction:column;gap:3px"><span class="scb-label">Position changes</span><span style="margin-top:3px">' + posDeltaHtml + '</span></div>';
    }

    const netCollapseId = 'sc_net_' + s.id;
    const netSection = netAvg !== null ?
      '<div class="stats-compare-box" style="margin-top:10px">' +
        '<div class="stats-collapse-header" onclick="toggleCollapse(\'' + netCollapseId + '\')" style="color:var(--accent)">' +
          '<span>&#128202; Net Gain (In \u2212 Out)</span>' +
          '<span class="stats-collapse-arrow" id="' + netCollapseId + '_arrow">&#9660;</span>' +
        '</div>' +
        '<div class="stats-collapse-body" id="' + netCollapseId + '_body"><div style="padding-top:6px">' + netBodyHtml + '</div></div>' +
      '</div>' : '';

    card.innerHTML =
      '<div class="scenario-card-header">' +
        '<input class="scenario-name-input" value="' + s.name.replace(/"/g,'&quot;') + '" onchange="renameScenario(' + s.id + ',this.value)">' +
        (isWinner ? '<span class="winner-crown" title="Best avg gain">&#127942; Best</span>' : '') +
        '<button class="trade-item-remove" style="font-size:1rem" onclick="removeScenario(' + s.id + ')">&#10005;</button>' +
      '</div>' +
      '<div class="scenario-section-label">&#11014; Trading In</div>' +
      '<div class="scenario-tags">' + playerTags(s.in,'in') + '</div>' +
      '<div class="sc-rel"><input class="sc-search" placeholder="Search to add in\u2026" id="sc_in_' + s.id + '" autocomplete="off"><div class="sc-dropdown" id="sc_dr_in_' + s.id + '"></div></div>' +
      '<div class="scenario-section-label">&#11015; Trading Out</div>' +
      '<div class="scenario-tags">' + playerTags(s.out,'out') + '</div>' +
      '<div class="sc-rel"><input class="sc-search" placeholder="Search to add out\u2026" id="sc_out_' + s.id + '" autocomplete="off"><div class="sc-dropdown" id="sc_dr_out_' + s.id + '"></div></div>' +
      '<div class="stats-compare-box" style="margin-top:12px">' + statsBlock(iSt, '\u{1F4E5} Trading In Stats', 'sc_in_stats_' + s.id) + '</div>' +
      '<div class="stats-compare-box" style="margin-top:8px">' + statsBlock(oSt, '\u{1F4E4} Trading Out Stats', 'sc_out_stats_' + s.id) + '</div>' +
      netSection;

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
      const posStr = p.positions && p.positions.length ? p.positions.join('/') + ' \u00b7 ' : '';
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
  lsSet('myteam_squad',[]); lsSet('myteam_positions',{});
  renderMyTeam();
  document.getElementById('myteamAnalysis').style.display='none';
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

function playerSignal(key, isBench) {
  const p = getP(key); if (!p) return {label:'—',col:'var(--muted)',score:50,reasons:[]};
  const st = playerStats(key);
  const isInj = INJURED_SET && INJURED_SET.has(p.name);
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

function renderMyTeam() {
  const squad = lsMyTeam();
  const grouped = groupSquadByPosition(squad);
  const fieldDiv = document.getElementById('myteamFieldGrid');
  if (!fieldDiv) return;
  fieldDiv.innerHTML = '';

  // Two-column layout: narrow field cards | tips panel
  const wrap = document.createElement('div');
  wrap.style.cssText = 'display:grid;grid-template-columns:1fr 300px;gap:14px;align-items:start';
  const leftCol = document.createElement('div');
  const rightCol = document.createElement('div');
  rightCol.id = 'mtTipsPanel';

  // ── Render each position section ─────────────────────────────────────────
  const posOrder = ['DEF','MID','RUC','FWD'];
  posOrder.forEach(function(posKey) {
    const cfg = MT_POS_CONFIG.find(function(c){return c.pos===posKey;});
    const players = grouped[posKey] || [];
    const total = cfg.starters + cfg.bench;

    const sec = document.createElement('div');
    sec.style.cssText = 'margin-bottom:8px';
    const lbl = document.createElement('div');
    lbl.style.cssText = 'font-family:"Barlow Condensed",sans-serif;font-weight:800;font-size:.68rem;letter-spacing:.1em;color:'+cfg.color+';margin-bottom:4px;display:flex;align-items:center;gap:5px';
    lbl.innerHTML = cfg.label + '<span style="color:var(--muted);font-weight:400;font-size:.6rem">'+players.length+'/'+total+'</span>'+
      '<span style="color:rgba(255,255,255,.15);font-size:.58rem;margin-left:auto">drag to reorder</span>';
    sec.appendChild(lbl);

    const row = document.createElement('div');
    row.style.cssText = 'display:grid;gap:4px;grid-template-columns:repeat('+cfg.starters+',1fr) 4px repeat('+cfg.bench+',minmax(0,0.68fr))';
    row.dataset.pos = posKey;

    for (var i=0; i<total; i++) {
      // Divider between starters and bench
      if (i === cfg.starters) {
        const dvd = document.createElement('div');
        dvd.style.cssText = 'background:rgba(255,255,255,.06);border-radius:2px;align-self:stretch';
        row.appendChild(dvd);
      }
      const isBench = i >= cfg.starters;
      const key = players[i];
      const card = makePlayerCard(key, posKey, isBench, cfg);
      // Drag and drop
      if (key) {
        card.draggable = true;
        card.addEventListener('dragstart', function(e){ e.dataTransfer.setData('key', key); e.dataTransfer.setData('fromPos', posKey); });
      }
      row.appendChild(card);
    }
    // Drop target for this row
    row.addEventListener('dragover', function(e){ e.preventDefault(); row.style.outline='1px dashed var(--accent2)'; });
    row.addEventListener('dragleave', function(){ row.style.outline=''; });
    row.addEventListener('drop', function(e){
      e.preventDefault(); row.style.outline='';
      const dragKey = e.dataTransfer.getData('key');
      if (!dragKey) return;
      setPlayerPosition(dragKey, posKey);
    });

    sec.appendChild(row);
    leftCol.appendChild(sec);
  });

  // ── UTIL + bench overflow ─────────────────────────────────────────────────
  const utilPlayers = (grouped.UTIL||[]).concat(grouped.UNKNOWN||[]);
  const utilSec = document.createElement('div');
  utilSec.style.cssText = 'margin-bottom:8px';
  const utilLbl = document.createElement('div');
  utilLbl.style.cssText = 'font-family:"Barlow Condensed",sans-serif;font-weight:800;font-size:.68rem;letter-spacing:.1em;color:var(--muted);margin-bottom:4px';
  utilLbl.textContent = 'UTILITY / EXTRA';
  utilSec.appendChild(utilLbl);
  const utilRow = document.createElement('div');
  utilRow.style.cssText = 'display:grid;grid-template-columns:repeat(4,1fr);gap:4px';
  for (var ui=0; ui<4; ui++) {
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
  if (squad.length > 0) {
    var tv=0,as=0,ac=0;
    squad.forEach(function(k){
      const p=getP(k); if(!p)return;
      if(p.current_price) tv+=p.current_price;
      const st=playerStats(k); if(st&&st.n){as+=st.avg;ac++;}
    });
    document.getElementById('myteamTeamValue').style.display='block';
    document.getElementById('myteamValueNum').textContent=fmtPrice(tv);
    document.getElementById('myteamTeamAvg').style.display='block';
    document.getElementById('myteamAvgNum').textContent=ac?(as/ac).toFixed(1)+' pts':'—';
    buildTipsPanel(squad, grouped);
  } else {
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
    card.style.cssText = 'border:1px dashed rgba(255,255,255,.08);border-radius:6px;display:flex;align-items:center;justify-content:center;min-height:70px;color:rgba(255,255,255,.15);font-size:.65rem;font-family:"Barlow Condensed",sans-serif;cursor:pointer;background:'+(isBench?'rgba(255,255,255,.01)':'transparent');
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
  const avgNum = st&&st.avg ? st.avg : 0;
  const avgCol = avgNum>=115?'var(--green)':avgNum>=95?'var(--text)':'var(--muted)';
  const trendSym = sig.trend==='rising'?'↑':sig.trend==='falling'?'↓':'';
  const trendCol = sig.trend==='rising'?'var(--green)':'var(--red)';
  // DPP badge - show other eligible positions
  const otherPos = p&&p.positions?p.positions.filter(function(pp){return pp!==posKey;}).join('/'):'';

  card.style.cssText = 'background:'+(isBench?'rgba(255,255,255,.025)':'var(--surface2)')+
    ';border:1px solid '+(isInj?'rgba(248,113,113,.5)':isBench?'rgba(255,255,255,.07)':'var(--border)')+
    ';border-radius:6px;padding:5px 6px;position:relative;min-height:70px;display:flex;flex-direction:column;gap:1px;transition:border-color .15s;cursor:grab';

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
      item.onmouseover = function(){item.style.background='rgba(255,255,255,.06)';};
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
    '<div style="display:flex;justify-content:space-between;align-items:center">' +
      '<span style="font-size:.5rem;font-weight:800;font-family:\'Barlow Condensed\',sans-serif;color:'+(cfg.color||'var(--muted)')+';opacity:.9">'+(posKey+(isBench?'·B':''))+(otherPos?'<span style="opacity:.6">/'+otherPos+'</span>':'')+'</span>'+
      '<span style="font-size:.52rem;font-weight:800;font-family:\'Barlow Condensed\',sans-serif;color:'+sig.col+'">'+sig.label+'</span>'+
    '</div>'+
    '<div style="font-weight:700;font-size:.74rem;cursor:pointer;color:'+(isInj?'var(--red)':'var(--text)')+';overflow:hidden;text-overflow:ellipsis;white-space:nowrap;line-height:1.2" onclick="searchAndShowPlayer(\''+safeKey+'\')" title="'+dn+'">'+dn+'</div>'+
    '<div style="font-size:.58rem;color:var(--muted)">'+(p?p.team:'')+(isInj?' 🚑':'')+'</div>'+
    '<div style="display:flex;align-items:baseline;gap:2px;margin-top:1px">'+
      '<span style="font-family:\'Barlow Condensed\',sans-serif;font-weight:800;font-size:.9rem;color:'+avgCol+'">'+(st&&st.avg?st.avg.toFixed(0):'—')+'</span>'+
      (proj!=null?'<span style="font-family:\'Barlow Condensed\',sans-serif;font-size:.72rem;color:var(--accent2)">→'+proj+'</span>':'')+
      (trendSym?'<span style="font-size:.62rem;color:'+trendCol+'">'+trendSym+'</span>':'')+
    '</div>'+
    '<div style="font-size:.57rem;color:var(--muted)">'+(st&&st.price?fmtPrice(st.price):'')+'</div>'+
    '<button onclick="removeFromMyTeam(\''+safeKey+'\')" style="position:absolute;top:2px;right:3px;background:none;border:none;color:rgba(255,255,255,.13);cursor:pointer;font-size:.62rem;padding:1px;line-height:1">✕</button>';
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

  // ── 1. Injury alerts ─────────────────────────────────────────────────────
  squad.forEach(function(key){
    const p=getP(key); if(!p||!INJURED_SET||!INJURED_SET.has(p.name)) return;
    const onField = ['DEF','MID','RUC','FWD'].some(function(pos){return starters(pos,grouped).includes(key);});
    tips.push({pri:1,icon:'🚑',title:(p.name)+' — INJURED',col:'var(--red)',
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

  // ── 5. Expensive bench warning ───────────────────────────────────────────
  var benchVal=0, expBench=[];
  ['DEF','MID','RUC','FWD'].forEach(function(pos){
    benchPlayers(pos,grouped).forEach(function(key){
      const st=playerStats(key); if(st&&st.price){benchVal+=st.price;if(st.price>700000)expBench.push(getP(key)?.name||key);}
    });
  });
  if(benchVal>2500000){
    tips.push({pri:3,icon:'💰',title:'Expensive bench ('+fmtPrice(benchVal)+')',col:'var(--yellow)',
      body:'Bench has '+fmtPrice(benchVal)+' locked up'+( expBench.length?': '+expBench.join(', '):'.')+'. '+
        'Bench players only score when starters are subbed. Downgrade bench to free cash for premium starters.'});
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
  panel.innerHTML = '<div style="font-family:\'Barlow Condensed\',sans-serif;font-weight:800;font-size:.78rem;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin-bottom:8px">💡 Team Tips</div>';
  tips.forEach(function(tip){
    const d=document.createElement('div');
    d.style.cssText='background:var(--surface);border:1px solid var(--border);border-left:3px solid '+tip.col+';border-radius:7px;padding:8px 10px;margin-bottom:6px';
    d.innerHTML='<div style="font-family:\'Barlow Condensed\',sans-serif;font-weight:800;font-size:.82rem;color:'+tip.col+';margin-bottom:2px">'+tip.icon+' '+tip.title+'</div>'+
      '<div style="font-size:.73rem;color:var(--muted);line-height:1.5">'+tip.body+'</div>';
    panel.appendChild(d);
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
      var best=null,bestScore=0;
      PLAYERS_DATA.forEach(function(op){
        if(squad.includes(op.key)) return;
        if(!op.positions||!op.positions.includes(cfg.pos)) return;
        if(INJURED_SET&&INJURED_SET.has(op.name)) return; // don't suggest injured targets
        const opSt=playerStats(op.key); if(!opSt||opSt.avg<=st.avg) return;
        const cost=(opSt.price||0)-(st.price||0);
        if(cost>budgetDollars+20000) return;
        const gain=opSt.avg-st.avg;
        const opSig=playerSignal(op.key,false);
        const opFix=getPlayerFixtureScore(op.key);
        const myFix=getPlayerFixtureScore(key);
        var us=gain*3+(opSig.score-sig.score)*0.4;
        if(opFix!=null&&myFix!=null) us+=(opFix-myFix)*0.5;
        if(cost<=0) us+=5;
        if(us>bestScore){bestScore=us;best={player:op,opSt,cost,gain,opSig,opFix};}
      });
      if(isInj||sig.score<65||isBench||best) recs.push({key,pos:cfg.pos,cfg,isBench,p,st,sig,isInj,urgency,best,bestScore});
    });
  });
  recs.sort(function(a,b){return b.urgency-a.urgency;});
  if(!recs.length){
    bodyDiv.innerHTML='<div style="padding:12px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;color:var(--muted)">✓ All starters look solid. No urgent changes flagged within budget.</div>';
    return;
  }
  recs.forEach(function(r,rank){
    const urgCol=r.urgency>=50?'var(--green)':r.urgency>=30?'var(--yellow)':'var(--muted)';
    const safeKey=r.key.replace(/'/g,"\\'");
    const trendCol=r.sig.trend==='rising'?'var(--green)':r.sig.trend==='falling'?'var(--red)':'var(--muted)';
    const trendTxt=r.sig.trend==='rising'?'↑ rising':r.sig.trend==='falling'?'↓ falling':'→ stable';
    var html='<div style="background:var(--surface);border:1px solid var(--border);border-left:3px solid '+urgCol+';border-radius:9px;padding:11px 13px;margin-bottom:8px;display:flex;gap:10px">';
    html+='<div style="min-width:34px"><div style="font-family:\'Barlow Condensed\',sans-serif;font-weight:800;font-size:1.2rem;color:'+urgCol+'">#'+(rank+1)+'</div></div>';
    html+='<div style="flex:1;min-width:0">';
    html+='<div style="display:flex;align-items:center;gap:5px;flex-wrap:wrap;margin-bottom:3px">';
    html+='<span style="font-weight:700;font-size:.9rem;cursor:pointer" onclick="searchAndShowPlayer(\''+safeKey+'\')">'+(r.p.display_name||r.p.name)+'</span>';
    html+='<span class="pos-chip '+r.cfg.cls+'">'+r.pos+(r.isBench?' B':'')+'</span>';
    html+='<span class="team-tag">'+r.p.team+'</span>';
    html+='<span style="color:'+r.sig.col+';font-size:.7rem;font-weight:700;background:rgba(0,0,0,.3);padding:1px 5px;border-radius:3px">'+r.sig.label+'</span>';
    if(r.isInj) html+='<span style="color:var(--red);font-weight:700;font-size:.72rem">🚑 INJURED</span>';
    html+='</div>';
    html+='<div style="display:flex;gap:8px;flex-wrap:wrap;font-size:.77rem;margin-bottom:3px">';
    html+='<span>Avg <b>'+r.st.avg.toFixed(1)+'</b></span><span>L3 <b style="color:'+(r.st.l3>r.st.avg+5?'var(--green)':r.st.l3<r.st.avg-5?'var(--red)':'var(--text)')+'">'+r.st.l3.toFixed(1)+'</b></span>';
    html+='<span>'+fmtPrice(r.st.price)+'</span>';
    if(r.st.fr!=null) html+='<span>Form <b style="color:'+ratingColor(r.st.fr)+'">'+r.st.fr+'/100</b></span>';
    html+='<span style="color:'+trendCol+'">'+trendTxt+'</span>';
    html+='</div>';
    if(r.sig.reasons&&r.sig.reasons.length) html+='<div style="font-size:.7rem;color:var(--muted);margin-bottom:5px">'+r.sig.reasons.map(function(s){return '• '+s;}).join('  ')+'</div>';
    if(r.isBench&&r.st.price>900000) html+='<div style="font-size:.7rem;color:var(--yellow);margin-bottom:5px">⚠ Expensive bench ('+fmtPrice(r.st.price)+') — cash could upgrade a starter.</div>';
    if(r.best){
      const op=r.best.player,safeOp=op.key.replace(/'/g,"\\'"),opSt=r.best.opSt;
      const myFix=getPlayerFixtureScore(r.key),opFixN=r.best.opFix;
      const fixNote=opFixN!=null&&myFix!=null?' · fix '+(opFixN>myFix+2?'<span style="color:var(--green)">easier ↑</span>':opFixN<myFix-2?'<span style="color:var(--red)">harder ↓</span>':'similar'):'';
      const costStr=r.best.cost<=0?'<span style="color:var(--green)">saves '+fmtPrice(Math.abs(r.best.cost))+'</span>':'<span style="color:var(--muted)">+'+fmtPrice(r.best.cost)+'</span>';
      html+='<div style="display:flex;align-items:center;gap:6px;padding:7px 9px;background:var(--surface2);border:1px solid var(--border);border-radius:6px;margin-top:5px;flex-wrap:wrap">';
      html+='<div style="flex:1;min-width:100px"><div style="font-size:.57rem;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.04em">OUT</div><div style="font-weight:700;font-size:.82rem">'+(r.p.display_name||r.p.name)+'</div><div style="font-size:.68rem;color:var(--muted)">'+fmtPrice(r.st.price)+' · avg '+r.st.avg.toFixed(1)+'</div></div>';
      html+='<div style="color:var(--muted);font-size:1rem">→</div>';
      html+='<div style="flex:1;min-width:100px"><div style="font-size:.57rem;color:var(--green);font-weight:700;text-transform:uppercase;letter-spacing:.04em">IN</div><div style="font-weight:700;font-size:.82rem;cursor:pointer;color:var(--green)" onclick="searchAndShowPlayer(\''+safeOp+'\')">'+(op.display_name||op.name)+'</div><div style="font-size:.68rem;color:var(--muted)">'+fmtPrice(opSt.price)+' · avg '+opSt.avg.toFixed(1)+' <span style="color:var(--green)">+'+r.best.gain.toFixed(1)+'</span>'+fixNote+'</div></div>';
      html+='<div style="display:flex;flex-direction:column;align-items:flex-end;gap:3px;flex-shrink:0">'+costStr+'<button class="pill-btn pill-in" onclick="addToList(\'tradeIn\',\''+safeOp+'\');addToList(\'tradeOut\',\''+safeKey+'\');showPage(\'trading\',document.querySelectorAll(\'.nav-btn\')[4])" style="font-size:.6rem;white-space:nowrap">→ Trade</button></div>';
      html+='</div>';
    } else if(r.urgency>=40){
      html+='<div style="font-size:.72rem;color:var(--muted);padding:5px 8px;background:var(--surface2);border-radius:5px;margin-top:4px">No affordable upgrade found — consider downgrade to free cash.</div>';
    }
    html+='</div></div>';
    bodyDiv.innerHTML+=html;
  });
  const uc=recs.filter(function(r){return r.urgency>=50;}).length;
  bodyDiv.innerHTML+='<div style="margin-top:8px;padding:8px 12px;background:var(--surface2);border:1px solid var(--border);border-radius:6px;font-size:.78rem;color:var(--muted)"><b style="color:var(--text)">'+recs.length+'</b> players reviewed'+(uc?' · <b style="color:var(--green)">'+uc+' urgent</b>':'')+(budgetK?' · Budget: <b>'+fmtBudgetK(budgetK)+'</b>':'')+'</div>';
}

// Rolling 22
function renderRolling22(mode) {
  mode=mode||'overall';
  const grid=document.getElementById('rolling22Grid');
  if(!grid) return;
  grid.innerHTML='';
  const POS=[
    {pos:'DEF',starters:6,bench:2,color:'#93c5fd',label:'Defenders'},
    {pos:'MID',starters:8,bench:2,color:'#6ee7b7',label:'Midfielders'},
    {pos:'RUC',starters:2,bench:1,color:'#fcd34d',label:'Rucks'},
    {pos:'FWD',starters:6,bench:2,color:'#fca5a5',label:'Forwards'},
  ];
  const UTIL_MAX=1;
  function modeScore(p) {
    const sc=p.history.map(function(x){return x.score;}); const n=sc.length; if(!n) return -1;
    // Exclude injured players from Rolling 22
    if(INJURED_SET&&INJURED_SET.has(p.name)) return -1;
    const avg=sc.reduce(function(a,b){return a+b;},0)/n;
    if(mode==='overall') return avg;
    const l3=sc.slice(-3).reduce(function(a,b){return a+b;},0)/Math.min(3,n);
    const l5=sc.slice(-5).reduce(function(a,b){return a+b;},0)/Math.min(5,n);
    const fr=p.form_rating||50;
    if(mode==='form') return l3*0.50+l5*0.30+avg*0.20+(fr-50)*0.5;
    if(mode==='fixture'){
      const fx=getPlayerFixtureScore(p.key);
      const proj=fx!=null?(l3*0.50+l5*0.30+avg*0.20)*(0.4+fx/166.7):avg;
      return proj;
    }
    return avg;
  }
  const used=new Set();
  var totalAvg=0,totalCount=0;
  POS.forEach(function(cfg){
    const total=cfg.starters+cfg.bench;
    // Sort highest to lowest projected score
    const elig=PLAYERS_DATA.filter(function(p){
      return p.positions&&p.positions.includes(cfg.pos)&&!used.has(p.key)&&p.history&&p.history.length>=1&&modeScore(p)>=0;
    }).sort(function(a,b){return modeScore(b)-modeScore(a);}).slice(0,total);
    elig.forEach(function(p){used.add(p.key);});

    const sec=document.createElement('div'); sec.style.cssText='margin-bottom:14px';
    const lbl=document.createElement('div');
    lbl.style.cssText='font-family:"Barlow Condensed",sans-serif;font-weight:800;font-size:.72rem;letter-spacing:.1em;text-transform:uppercase;color:'+cfg.color+';margin-bottom:6px';
    lbl.textContent=cfg.label;
    sec.appendChild(lbl);

    const row=document.createElement('div');
    row.style.cssText='display:grid;gap:5px;grid-template-columns:repeat('+cfg.starters+',1fr) 5px repeat('+cfg.bench+',0.72fr)';

    elig.forEach(function(p,i){
      if(i===cfg.starters){const d=document.createElement('div');d.style.cssText='background:rgba(255,255,255,.05);border-radius:2px';row.appendChild(d);}
      const isBench=i>=cfg.starters;
      const sc=p.history.map(function(x){return x.score;}); const n=sc.length;
      const avg=n?+(sc.reduce(function(a,b){return a+b;},0)/n).toFixed(1):0;
      const l3=n?+(sc.slice(-3).reduce(function(a,b){return a+b;},0)/Math.min(3,n)).toFixed(1):0;
      const ms=modeScore(p);
      const fx=getPlayerFixtureScore(p.key);
      const safeKey=p.key.replace(/'/g,"\\'");
      const avgNum=parseFloat(avg);
      const avgCol=avgNum>=115?'var(--green)':avgNum>=95?'var(--text)':'var(--muted)';
      if(!isBench&&n){totalAvg+=ms>0?ms:avgNum;totalCount++;}
      const card=document.createElement('div');
      card.style.cssText='background:'+(isBench?'rgba(255,255,255,.02)':'var(--surface2)')+';border:1px solid '+(isBench?'rgba(255,255,255,.07)':'var(--border)')+';border-radius:7px;padding:7px 8px;min-height:72px;display:flex;flex-direction:column;gap:1px';
      const projR22 = calcProjectedScore(p.key);
      const isWatched = lsGet('starred',[]).includes(p.key);
      card.innerHTML='<div style="display:flex;justify-content:space-between;align-items:center">' +
          '<div style="font-size:.52rem;font-weight:800;font-family:\'Barlow Condensed\',sans-serif;color:'+cfg.color+';opacity:.9">'+cfg.pos+(isBench?' B':'')+'</div>'+
          '<button onclick="toggleR22Watch(\''+safeKey+'\',this)" style="background:none;border:none;cursor:pointer;font-size:.75rem;opacity:'+(isWatched?'1':'0.3')+';line-height:1" title="Add to Watchlist">'+(isWatched?'★':'☆')+'</button>'+
        '</div>'+
        '<div style="font-weight:700;font-size:.76rem;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" onclick="searchAndShowPlayer(\''+safeKey+'\')" title="'+(p.display_name||p.name)+'">'+(p.display_name||p.name)+'</div>'+
        '<div style="font-size:.6rem;color:var(--muted)">'+p.team+'</div>'+
        '<div style="display:flex;align-items:baseline;gap:3px">'+
          '<span style="font-family:\'Barlow Condensed\',sans-serif;font-weight:800;font-size:.95rem;color:'+avgCol+'">'+avg+'</span>'+
          (projR22!=null?'<span style="font-size:.68rem;color:var(--accent2)">→'+projR22+'</span>':'')+
        '</div>'+
        '<div style="font-size:.58rem;color:var(--muted)">'+(fx!=null?'Fix '+fx.toFixed(0)+' · ':'')+fmtPrice(p.current_price)+'</div>';
      row.appendChild(card);
    });
    for(var i=elig.length;i<total;i++){
      if(i===cfg.starters){const d=document.createElement('div');d.style.cssText='background:rgba(255,255,255,.05);border-radius:2px';row.appendChild(d);}
      const e=document.createElement('div');
      e.style.cssText='border:1px dashed rgba(255,255,255,.08);border-radius:7px;display:flex;align-items:center;justify-content:center;min-height:72px;color:rgba(255,255,255,.15);font-size:.68rem;font-family:"Barlow Condensed",sans-serif';
      e.textContent='No data';
      row.appendChild(e);
    }
    sec.appendChild(row); grid.appendChild(sec);
  });
  // UTIL slot
  var utilBest = PLAYERS_DATA.filter(function(p){
    return !used.has(p.key) && p.history && p.history.length>=1 && modeScore(p)>=0;
  }).sort(function(a,b){return modeScore(b)-modeScore(a);});
  if(utilBest.length){
    var us=document.createElement('div'); us.style.cssText='margin-bottom:14px';
    var ul=document.createElement('div'); ul.style.cssText='font-family:"Barlow Condensed",sans-serif;font-weight:800;font-size:.72rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:6px'; ul.textContent='UTILITY';
    us.appendChild(ul);
    var ur=document.createElement('div'); ur.style.cssText='display:grid;gap:5px;grid-template-columns:repeat(3,1fr)';
    var up=utilBest[0];
    var usc=up.history.map(function(x){return x.score;}); var un=usc.length;
    var uavg=un?+(usc.reduce(function(a,b){return a+b;},0)/un).toFixed(1):0;
    var ufx=getPlayerFixtureScore(up.key); var uproj=calcProjectedScore(up.key);
    var uc2=document.createElement('div'); uc2.style.cssText='background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);border-radius:7px;padding:7px 8px;min-height:72px;display:flex;flex-direction:column;gap:2px';
    var uhl=document.createElement('div'); uhl.style.cssText='font-size:.52rem;font-weight:800;color:var(--muted)'; uhl.textContent='UTIL';
    var uhn=document.createElement('div'); uhn.style.cssText='font-weight:700;font-size:.76rem;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis'; uhn.textContent=(up.display_name||up.name); (function(k){uhn.onclick=function(){searchAndShowPlayer(k);};})(up.key);
    var uht=document.createElement('div'); uht.style.cssText='font-size:.6rem;color:var(--muted)'; uht.textContent=up.team;
    var uhs=document.createElement('div'); uhs.style.cssText='font-weight:800;font-size:.9rem'; uhs.textContent=uavg+(uproj?' →'+uproj:'');
    var uhp=document.createElement('div'); uhp.style.cssText='font-size:.58rem;color:var(--muted)'; uhp.textContent=fmtPrice(up.current_price);
    var uwb=document.createElement('button'); uwb.style.cssText='background:none;border:none;cursor:pointer;font-size:.9rem;margin-top:2px;text-align:left;color:var(--accent)'; uwb.textContent='☆ Watchlist';
    (function(k,b){b.onclick=function(){toggleR22Watch(k,b);};})(up.key,uwb);
    uc2.appendChild(uhl); uc2.appendChild(uhn); uc2.appendChild(uht); uc2.appendChild(uhs); uc2.appendChild(uhp); uc2.appendChild(uwb);
    ur.appendChild(uc2); us.appendChild(ur); grid.appendChild(us);
  }
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
      const posStr=p.positions&&p.positions.length?p.positions.join('/')+' · ':'';
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
    current_prices, injured_set = parse_current_round(CURRENT_ROUND_FILE)
    leaderboard      = build_leaderboard(all_rounds, current_prices)
    rounds_data      = build_rounds_data(all_rounds)
    players_data     = build_players_data(all_rounds, current_prices, players_registry)
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
        p["form_rating"]   = compute_form_rating(scores, p.get("current_price"))
        p["consistency"]   = compute_consistency(scores)
        p["is_injured"]    = p["name"] in injured_set

    # Mark injured in leaderboard
    lb_name_counts = defaultdict(int)
    for e in leaderboard: lb_name_counts[e["player"]] += 1
    for e in leaderboard:
        e["display_name"] = f"{e['player']} ({e['team']})" if lb_name_counts[e["player"]] > 1 else e["player"]
        e["is_injured"]   = e["player"] in injured_set

    html = HTML_TEMPLATE
    html = html.replace('__LEADERBOARD__',        json.dumps(leaderboard))
    html = html.replace('__ROUNDS_DATA__',        json.dumps(rounds_data))
    html = html.replace('__PLAYERS_DATA__',       json.dumps(players_data))
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