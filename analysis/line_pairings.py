"""Line pairings lab -- who produces together, and who the team is better with on the ice together.

NOT part of the site build or the nightly workflow. Run it by hand, read the report, and if a
metric earns its keep it can graduate into scripts/build_site_data.py + a dashboard view later.

What it computes, from our own corrected box scores (every season, both team names):

  * Pair / trio "co-credits": how often two (three) players are credited on the SAME goal
    (scorer + assists), per game they dressed together.
  * Chemistry: co-credits per shared game vs. what you'd expect if the two were independent
    (team GF/game together x A's share of team goals x B's share). > 1.0 means they find each
    other more than their individual production predicts; < 1.0 means they don't.
  * WOWY (with-or-without-you) at game grain: the team's GF, GA and goal-diff per game with
    both dressed vs. with exactly one of them. We have no shift or TOI data, so "together" means
    "both on the roster that night" -- it's a proxy, and it's noisiest for guys who never miss.

Positions are almost never filled in on the scoresheets, so this can't split forwards from
defense; the groupings at the end are purely production-driven and should be read that way.

Usage:
    python analysis/line_pairings.py [--min-games 5] [--season 18] [--season 19]
Writes analysis/output/line_pairings.json and analysis/output/line_pairings.html.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_site_data import SeasonData, discover_seasons, load_franchises, season_label  # noqa: E402

OUT_DIR = ROOT / "analysis" / "output"


def our_side(box: dict, our_name: str, known_names: set[str]) -> str | None:
    if box["home_name"] == our_name:
        return "home"
    if box["away_name"] == our_name:
        return "away"
    home_roster = {p["name"] for p in box["rosters"].get(box["home_name"], [])}
    away_roster = {p["name"] for p in box["rosters"].get(box["away_name"], [])}
    if known_names & home_roster:
        return "home"
    if known_names & away_roster:
        return "away"
    return None


def collect_games(season_ids: list[int] | None) -> list[dict]:
    """One record per game we have a box score for: our dressed skaters, each of our goals as the
    set of credited names, and the final score from our side."""
    franchises = load_franchises()
    games = []
    for sid in discover_seasons():
        if season_ids and sid not in season_ids:
            continue
        season = SeasonData(sid, franchises)
        for team_id, page in season.our_team_pages.items():
            our_name = season.team_name_by_id.get(team_id)
            known = set(season.name_to_player_id.get(team_id, {}))
            goalies = {g["name"] for g in page["goalie_stats"]}
            for g in page["games"]:
                if not (g["is_final"] and g["has_boxscore"]):
                    continue
                box = season.load_corrected_boxscore(g["game_id"])
                if box is None:
                    continue
                side = our_side(box, our_name, known)
                if side is None:
                    continue
                side_name = box["home_name"] if side == "home" else box["away_name"]
                roster = {p["number"]: p["name"] for p in box["rosters"].get(side_name, [])
                          if p["number"] is not None and p["name"]}
                dressed = {n for n in roster.values() if n not in goalies and (p_pos(box, side_name, n) != "G")}
                goals = []
                for goal in box["goals"]:
                    if goal["team"] != side:
                        continue
                    credited = {roster.get(goal[k]) for k in ("scorer_number", "assist1_number", "assist2_number")
                                if goal[k] is not None}
                    credited.discard(None)
                    goals.append(sorted(credited))
                gf = box["home_final"] if side == "home" else box["away_final"]
                ga = box["away_final"] if side == "home" else box["home_final"]
                games.append({
                    "game_id": g["game_id"], "season_id": sid, "season_label": season_label(sid),
                    "date": g["iso_date"], "opponent": box["away_name"] if side == "home" else box["home_name"],
                    "dressed": sorted(dressed), "goals": goals, "gf": gf or 0, "ga": ga or 0,
                })
    games.sort(key=lambda x: (x["date"], x["game_id"]))
    return games


def p_pos(box: dict, side_name: str, name: str) -> str | None:
    for p in box["rosters"].get(side_name, []):
        if p["name"] == name:
            return p["position"]
    return None


def _rate(num: float, den: int) -> float | None:
    return round(num / den, 2) if den else None


def _record(gs: list[dict]) -> str:
    w = sum(1 for g in gs if g["gf"] > g["ga"])
    l = sum(1 for g in gs if g["gf"] < g["ga"])
    t = len(gs) - w - l
    return f"{w}-{l}" + (f"-{t}" if t else "")


def _summ(gs: list[dict]) -> dict:
    n = len(gs)
    gf = sum(g["gf"] for g in gs)
    ga = sum(g["ga"] for g in gs)
    return {"gp": n, "gf_per_gp": _rate(gf, n), "ga_per_gp": _rate(ga, n), "diff_per_gp": _rate(gf - ga, n),
            "record": _record(gs) if n else None}


def analyze(games: list[dict], min_games: int) -> dict:
    players: dict[str, dict] = defaultdict(lambda: {"gp": 0, "points": 0, "team_gf": 0})
    pair_games: dict[tuple, list[dict]] = defaultdict(list)
    pair_goals: dict[tuple, int] = defaultdict(int)
    trio_games: dict[tuple, int] = defaultdict(int)
    trio_goals: dict[tuple, int] = defaultdict(int)
    solo_games: dict[str, list[dict]] = defaultdict(list)  # name -> games dressed

    for g in games:
        d = g["dressed"]
        for n in d:
            players[n]["gp"] += 1
            players[n]["team_gf"] += g["gf"]
            solo_games[n].append(g)
        for goal in g["goals"]:
            for n in goal:
                if n in players:
                    players[n]["points"] += 1
        for a, b in combinations(d, 2):
            pair_games[(a, b)].append(g)
        for goal in g["goals"]:
            for a, b in combinations(goal, 2):
                pair_goals[tuple(sorted((a, b)))] += 1
            if len(goal) >= 3:
                for tri in combinations(goal, 3):
                    trio_goals[tuple(sorted(tri))] += 1
        for tri in combinations(d, 3):
            pass  # trio games are derived from pair games below to keep this O(n^2)

    for n, p in players.items():
        p["involvement"] = round(p["points"] / p["team_gf"], 3) if p["team_gf"] else 0.0  # share of team goals credited on
        p["ppg"] = _rate(p["points"], p["gp"])

    pairs = []
    for (a, b), gs in pair_games.items():
        n = len(gs)
        if n < min_games:
            continue
        together = _summ(gs)
        ids = {g["game_id"] for g in gs}
        a_without = [g for g in solo_games[a] if g["game_id"] not in ids]
        b_without = [g for g in solo_games[b] if g["game_id"] not in ids]
        co = pair_goals.get((a, b), 0)
        gf_together = sum(g["gf"] for g in gs)
        expected = gf_together * players[a]["involvement"] * players[b]["involvement"]
        chemistry = round(co / expected, 2) if expected > 0 else None
        pairs.append({
            "a": a, "b": b, "games_together": n, "co_credits": co,
            "co_credits_per_gp": _rate(co, n), "expected_co_credits": round(expected, 2), "chemistry": chemistry,
            "together": together,
            "a_without_b": _summ(a_without), "b_without_a": _summ(b_without),
            "wowy_diff": (round(together["diff_per_gp"] - max(
                x for x in [(_summ(a_without)["diff_per_gp"] or 0), (_summ(b_without)["diff_per_gp"] or 0)]), 2)
                if (a_without or b_without) and together["diff_per_gp"] is not None else None),
        })

    trios = []
    for tri, co in trio_goals.items():
        a, b, c = tri
        shared = [g for g in pair_games.get((a, b), []) if c in g["dressed"]]
        n = len(shared)
        if n < min_games or co < 2:
            continue
        trios.append({"players": list(tri), "games_together": n, "co_credits": co,
                      "co_credits_per_gp": _rate(co, n), "together": _summ(shared)})

    by_co = sorted(pairs, key=lambda p: (p["co_credits"], p["chemistry"] or 0), reverse=True)
    by_chem = sorted([p for p in pairs if p["chemistry"] is not None and p["co_credits"] >= 3],
                     key=lambda p: p["chemistry"], reverse=True)
    by_wowy = sorted([p for p in pairs if p["wowy_diff"] is not None], key=lambda p: p["wowy_diff"], reverse=True)
    trios.sort(key=lambda t: (t["co_credits"], t["co_credits_per_gp"] or 0), reverse=True)

    best_partners: dict[str, list[dict]] = {}
    for n in players:
        mine = [p for p in pairs if n in (p["a"], p["b"]) and p["co_credits"] >= 2]
        mine.sort(key=lambda p: (p["co_credits_per_gp"] or 0, p["chemistry"] or 0), reverse=True)
        best_partners[n] = [{"partner": p["b"] if p["a"] == n else p["a"], "co_credits": p["co_credits"],
                             "games_together": p["games_together"], "chemistry": p["chemistry"]} for p in mine[:3]]

    groupings = suggest_groupings(pairs, players, min_games)

    return {
        "min_games": min_games, "games_analyzed": len(games),
        "seasons": sorted({g["season_label"] for g in games}),
        "players": dict(sorted(players.items(), key=lambda kv: kv[1]["points"], reverse=True)),
        "pairs_by_co_credits": by_co[:25], "pairs_by_chemistry": by_chem[:25], "pairs_by_wowy": by_wowy[:25],
        "trios": trios[:15], "best_partners": best_partners, "suggested_groupings": groupings,
        "all_pairs": pairs,
    }


def suggest_groupings(pairs: list[dict], players: dict, min_games: int) -> list[dict]:
    """Greedy, production-only trios: repeatedly take the strongest unused pair (chemistry weighted
    by how much evidence backs it) and attach the unused third who fits both best. A starting point
    for a whiteboard, not a lineup card -- it knows nothing about positions or who's a defenseman."""
    def strength(p):
        if p["chemistry"] is None:
            return 0.0
        return p["chemistry"] * (p["co_credits"] ** 0.5)

    lookup = {(p["a"], p["b"]): p for p in pairs}
    def pair_of(x, y):
        return lookup.get((x, y)) or lookup.get((y, x))

    used: set[str] = set()
    ranked = sorted([p for p in pairs if p["co_credits"] >= 2], key=strength, reverse=True)
    eligible = {n for n, p in players.items() if p["gp"] >= min_games}
    out = []
    for p in ranked:
        a, b = p["a"], p["b"]
        if a in used or b in used or a not in eligible or b not in eligible:
            continue
        best_c, best_s = None, 0.0
        for c in eligible - used - {a, b}:
            pa, pb = pair_of(a, c), pair_of(b, c)
            s = sum(strength(x) for x in (pa, pb) if x)
            if s > best_s:
                best_c, best_s = c, s
        group = [a, b] + ([best_c] if best_c else [])
        used.update(group)
        out.append({"players": group, "anchor_pair": [a, b], "anchor_chemistry": p["chemistry"],
                    "anchor_co_credits": p["co_credits"], "third_fit": round(best_s, 2)})
        if len(out) >= 4:
            break
    return out


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _fmt(v, nd=2):
    if v is None:
        return "—"
    return f"{v:.{nd}f}" if isinstance(v, float) else str(v)


def _table(headers: list[str], rows: list[list], cls: str = "") -> str:
    h = "".join(f"<th>{html.escape(x)}</th>" for x in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="scroll"><table class="{cls}"><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table></div>'


def _pair_rows(pairs: list[dict]) -> list[list]:
    rows = []
    for p in pairs:
        t, aw, bw = p["together"], p["a_without_b"], p["b_without_a"]
        rows.append([
            html.escape(p["a"]), html.escape(p["b"]), p["games_together"], p["co_credits"], _fmt(p["co_credits_per_gp"]),
            _fmt(p["expected_co_credits"]), _chem(p["chemistry"]),
            f"{_fmt(t['gf_per_gp'])} / {_fmt(t['ga_per_gp'])}", _diff(t["diff_per_gp"]), t["record"] or "—",
            f"{_diff(aw['diff_per_gp'])} ({aw['gp']})", f"{_diff(bw['diff_per_gp'])} ({bw['gp']})", _diff(p["wowy_diff"]),
        ])
    return rows


def _chem(v):
    if v is None:
        return "—"
    cls = "hi" if v >= 1.3 else "lo" if v <= 0.7 else ""
    return f'<span class="{cls}">{v:.2f}×</span>'


def _diff(v):
    if v is None:
        return "—"
    cls = "hi" if v > 0 else "lo" if v < 0 else ""
    return f'<span class="{cls}">{v:+.2f}</span>'


def _matrix(pairs: list[dict], players: dict, top_n: int = 16) -> str:
    names = [n for n, _ in sorted(players.items(), key=lambda kv: kv[1]["points"], reverse=True)[:top_n]]
    co = {}
    for p in pairs:
        co[(p["a"], p["b"])] = co[(p["b"], p["a"])] = p["co_credits_per_gp"] or 0
    mx = max(co.values(), default=0) or 1
    head = "<th></th>" + "".join(f'<th class="rot"><div>{html.escape(n.split()[0])}</div></th>' for n in names)
    rows = ""
    for a in names:
        cells = ""
        for b in names:
            if a == b:
                cells += '<td class="diag"></td>'
                continue
            v = co.get((a, b))
            if v is None:
                cells += '<td class="na">·</td>'
            else:
                alpha = 0.08 + 0.72 * (v / mx)
                cells += f'<td style="background:rgba(29,111,214,{alpha:.2f})" title="{html.escape(a)} + {html.escape(b)}: {v:.2f} co-credits/GP">{v:.2f}</td>'
        rows += f"<tr><th>{html.escape(a)}</th>{cells}</tr>"
    return f'<div class="scroll"><table class="matrix"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>'


def render_html(r: dict) -> str:
    pair_headers = ["A", "B", "GP tog.", "Co-credits", "Co/GP", "Expected", "Chemistry", "GF/GA per GP tog.",
                    "Diff/GP tog.", "Record tog.", "A w/o B diff (GP)", "B w/o A diff (GP)", "WOWY Δ"]
    player_rows = [[html.escape(n), p["gp"], p["points"], _fmt(p["ppg"]), f"{p['involvement']*100:.0f}%",
                    ", ".join(f"{html.escape(x['partner'])} ({x['co_credits']})" for x in r["best_partners"].get(n, [])) or "—"]
                   for n, p in r["players"].items()]
    trio_rows = [[" + ".join(html.escape(x) for x in t["players"]), t["games_together"], t["co_credits"],
                  _fmt(t["co_credits_per_gp"]), _diff(t["together"]["diff_per_gp"]), t["together"]["record"]] for t in r["trios"]]
    group_rows = [[" + ".join(html.escape(x) for x in g["players"]), " + ".join(html.escape(x) for x in g["anchor_pair"]),
                   _chem(g["anchor_chemistry"]), g["anchor_co_credits"], _fmt(g["third_fit"])] for g in r["suggested_groupings"]]

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Line Pairings Lab</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{{--bg:#f5f6f8;--bg2:#fff;--bg3:#eef0f3;--bd:#dde1e6;--tx:#14171a;--mu:#5b6470;--gn:#1c8a4b;--rd:#c0392b;--ac:#1d6fd6}}
@media(prefers-color-scheme:dark){{:root{{--bg:#0d1117;--bg2:#161b22;--bg3:#21262d;--bd:#30363d;--tx:#e6edf3;--mu:#8b949e;--gn:#3fb950;--rd:#f85149;--ac:#1f6feb}}}}
body{{margin:0;background:var(--bg);color:var(--tx);font:15px -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;padding:1rem 1rem 3rem}}
main{{max-width:1200px;margin:0 auto}} h1{{font-size:1.3rem;margin:0 0 .25rem}} .sub{{color:var(--mu);font-size:.85em;margin-bottom:1rem}}
.card{{background:var(--bg2);border:1px solid var(--bd);border-radius:8px;padding:1rem 1.1rem;margin-bottom:1rem}}
.sec{{font-size:.68em;text-transform:uppercase;letter-spacing:.1em;color:var(--mu);font-weight:700;margin-bottom:.5rem}}
p.note{{color:var(--mu);font-size:.85em;margin:.2rem 0 .6rem}} .lab{{display:inline-block;background:color-mix(in srgb,var(--rd) 15%,transparent);color:var(--rd);border-radius:999px;padding:.1rem .6rem;font-size:.75em;font-weight:700;margin-left:.5rem;vertical-align:middle}}
.scroll{{overflow-x:auto}} table{{width:100%;border-collapse:collapse;font-size:.8em}} th,td{{text-align:left;padding:3px 6px;border-bottom:1px solid var(--bd);white-space:nowrap}}
th{{color:var(--mu);font-weight:600;font-size:.78em;text-transform:uppercase;letter-spacing:.03em}} tbody tr:hover{{background:var(--bg3)}}
.hi{{color:var(--gn);font-weight:600}} .lo{{color:var(--rd)}}
.matrix td{{text-align:center;font-size:.9em;padding:2px 4px}} .matrix th.rot{{height:80px;vertical-align:bottom;padding:0}} .matrix th.rot div{{writing-mode:vertical-rl;transform:rotate(180deg);font-size:.85em}}
.matrix td.diag{{background:var(--bg3)}} .matrix td.na{{color:var(--mu)}}
ul.keys{{margin:.3rem 0 0;padding-left:1.1rem;font-size:.88em;line-height:1.5}}
</style></head><body><main>
<h1>Line Pairings Lab <span class="lab">not on the site</span></h1>
<div class="sub">{r['games_analyzed']} games with box scores · {html.escape(', '.join(r['seasons']))} · pairs need {r['min_games']}+ games together</div>

<div class="card"><div class="sec">How to read this</div><ul class="keys">
<li><b>Co-credits</b>: goals where both players are on the scoring line (scorer or an assist). <b>Co/GP</b> is that per game they dressed together.</li>
<li><b>Expected</b>: co-credits you'd get if the two were independent — team GF while together × A's share of team goals × B's share. <b>Chemistry</b> = actual ÷ expected: above 1.3× they find each other; below 0.7× they don't.</li>
<li><b>WOWY</b>: team goal differential per game with both dressed vs. the better of "A without B" / "B without A". Game-grain only — no shift data exists — so it's a proxy, weakest for players who never miss a game.</li>
<li>Positions are blank on nearly every scoresheet, so nothing here knows who plays D. Treat the groupings as a whiteboard starting point.</li>
</ul></div>

<div class="card"><div class="sec">Suggested groupings (greedy, production-only)</div>
{_table(["Group", "Anchor pair", "Anchor chemistry", "Anchor co-credits", "Third-man fit"], group_rows) if group_rows else '<p class="note">Not enough evidence yet.</p>'}</div>

<div class="card"><div class="sec">Most productive pairs (by co-credits)</div>{_table(pair_headers, _pair_rows(r['pairs_by_co_credits']))}</div>
<div class="card"><div class="sec">Best chemistry (3+ co-credits)</div>{_table(pair_headers, _pair_rows(r['pairs_by_chemistry']))}</div>
<div class="card"><div class="sec">Best WOWY (team is better with both dressed)</div>{_table(pair_headers, _pair_rows(r['pairs_by_wowy']))}</div>
<div class="card"><div class="sec">Trios on the same goal (2+ times)</div>{_table(["Trio", "GP tog.", "Co-credits", "Co/GP", "Diff/GP tog.", "Record"], trio_rows) if trio_rows else '<p class="note">No trio has connected twice yet.</p>'}</div>
<div class="card"><div class="sec">Co-credits per game, top scorers</div><p class="note">Darker = more goals together per shared game. Hover a cell.</p>{_matrix(r['all_pairs'], r['players'])}</div>
<div class="card"><div class="sec">Players</div>{_table(["Player", "GP", "PTS", "P/GP", "Share of team goals", "Best partners (co-credits)"], player_rows)}</div>
</main></body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-games", type=int, default=5, help="minimum games dressed together for a pair to count")
    ap.add_argument("--season", type=int, action="append", help="restrict to these season ids (repeatable)")
    args = ap.parse_args()

    games = collect_games(args.season)
    if not games:
        raise SystemExit("No games with box scores found -- run scripts/scrape.py first.")
    result = analyze(games, args.min_games)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "line_pairings.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (OUT_DIR / "line_pairings.html").write_text(render_html(result), encoding="utf-8")
    print(f"{len(games)} games, {len(result['all_pairs'])} pairs with {args.min_games}+ games together")
    print(f"wrote {OUT_DIR / 'line_pairings.html'}")
    print("\nTop pairs by co-credits:")
    for p in result["pairs_by_co_credits"][:8]:
        print(f"  {p['a']} + {p['b']}: {p['co_credits']} together in {p['games_together']} GP "
              f"(chemistry {p['chemistry']}x, WOWY {p['wowy_diff']:+.2f})" if p["wowy_diff"] is not None else
              f"  {p['a']} + {p['b']}: {p['co_credits']} together in {p['games_together']} GP (chemistry {p['chemistry']}x)")


if __name__ == "__main__":
    main()
