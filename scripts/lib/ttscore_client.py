"""HTTP + HTML parsing helpers for stats.panthers.timetoscore.com (TimeToScore).

The site is plain server-rendered HTML with no auth. Pages used:
  - display-stats?season=S&league=4&stat_class=1        -> season standings tree (every team_id/name/level + W/L/GF/GA/etc)
  - display-schedule?team=T&season=S&league=4&stat_class=1 -> that team's games for the season, plus (if any games
    were played) that team's season player/goalie/situational-team stat tables
  - oss-scoresheet?game_id=G&mode=display                -> full box score: rosters, goal-by-goal, penalties
  - display-league-stats?stat_class=1&league=4&season=S&level=L&conf=0 -> every player in that division/season
    (used for league-wide outlier leaderboards, not just our own team's roster)
  - display-player-stats.php?player=P                 -> one player's career: every team-season in every league on
    the site, plus a game-by-game log (needs the .php suffix; the bare path serves an empty page)

All functions here are pure parsing (take html text, return plain dicts/lists) except `fetch`, which is the only
thing that touches the network. Keeping parsing pure makes it easy to test against cached HTML fixtures.
"""
from __future__ import annotations

import re
import time
import urllib.parse as urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://stats.panthers.timetoscore.com/"
USER_AGENT = (
    "MidIceCrisisStatsBot/1.0 (+https://github.com/; small beer-league hockey team stats project; "
    "contact: albano0731@gmail.com)"
)
REQUEST_DELAY_SECONDS = 0.75
MAX_RETRIES = 4
RETRY_BACKOFF_SECONDS = 2.0

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


def fetch(path: str, **params) -> str:
    """GET a page under BASE_URL with the given query params, politely rate-limited.

    Retries a few times with backoff on transient connection errors -- this hits a small
    volunteer-run site a couple hundred times per run, and it occasionally drops a connection.
    """
    url = urlparse.urljoin(BASE_URL, path)
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = _session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            time.sleep(REQUEST_DELAY_SECONDS)
            return resp.text
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_error = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise last_error


def _normalize_broken_markup(html: str) -> str:
    """The site's own HTML has consistent tag-mismatch bugs that trip up a real parser:
    a <td> that opens a cell but is closed with </th>, and an <a> inside a cell whose
    </td> appears before its own </a>. Both patterns are unambiguous, so fix them globally
    before parsing rather than trying to recover a tree from the broken version.
    """
    html = re.sub(r"(<td[^>]*>)([^<]*)</th>", r"\1\2</td>", html, flags=re.IGNORECASE)
    html = html.replace("</td></a>", "</a></td>")
    return html


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(_normalize_broken_markup(html), "html.parser")


def _text(node) -> str:
    if node is None:
        return ""
    raw = node.get_text(strip=True).replace("\xa0", "").strip()
    return re.sub(r"\s+", " ", raw)  # the source data itself sometimes has double spaces in names


def _int_or_none(s: str):
    s = (s or "").strip()
    if s == "" or s == "&nbsp;":
        return None
    try:
        return int(s)
    except ValueError:
        return None


_SCORE_RE = re.compile(r"^(\d+)\s*([A-Za-z]{1,2})?$")


def _score(s: str) -> tuple[int | None, str | None]:
    """A schedule score cell: '3', or '2 O' -- the league marks the side that lost in overtime
    (or a shootout, 'S') with a letter after the score. Returns (goals, marker)."""
    m = _SCORE_RE.match((s or "").replace("\xa0", " ").strip())
    if not m:
        return None, None
    return int(m.group(1)), (m.group(2).upper() if m.group(2) else None)


def _team_id_from_href(href: str):
    if not href:
        return None
    qs = urlparse.parse_qs(urlparse.urlparse(href).query)
    vals = qs.get("team")
    return int(vals[0]) if vals else None


def _player_id_from_href(href: str):
    """Extract the player id from a display-player-stats.php?player=NNN href.

    Some pages (league-wide stats) render this with trailing template garbage after the
    number (e.g. `player=6282]}`), so pull the leading digits rather than trusting parse_qs.
    """
    if not href:
        return None
    qs = urlparse.parse_qs(urlparse.urlparse(href).query)
    vals = qs.get("player")
    if not vals:
        return None
    m = re.match(r"\d+", vals[0])
    return int(m.group()) if m else None


def _level_id_from_href(href: str):
    if not href:
        return None
    qs = urlparse.parse_qs(urlparse.urlparse(href).query)
    vals = qs.get("level")
    return int(vals[0]) if vals else None


# ---------------------------------------------------------------------------
# Standings page: display-stats
# ---------------------------------------------------------------------------

def parse_season_options(html: str) -> dict[str, str]:
    """The <select name=season> on display-stats only ever lists a recent rolling window, but every
    page load includes whatever labels are currently visible -- callers accumulate these into a
    persistent {season_id: label} map across runs so labels for older seasons aren't lost once the
    site stops listing them."""
    soup = _soup(html)
    select = soup.find("select", attrs={"name": "season"})
    if select is None:
        return {}
    out = {}
    for option in select.find_all("option"):
        value = option.get("value")
        if value and value != "0":
            out[value] = _text(option)
    return out


def parse_standings(html: str) -> list[dict]:
    """Returns a flat list of team-season rows across every division in the league.

    Each row: {team_id, name, level_id, level_label, rank, gp, w, l, t, otw, otl, gf, ga, plus_minus, pts, pims}
    """
    soup = _soup(html)
    rows: list[dict] = []
    current_level_id = None
    current_level_label = None

    all_trs = soup.find_all("tr")
    for tr in all_trs:
        header_th = tr.find("th", attrs={"colspan": True})
        if header_th is not None:
            link = header_th.find("a", href=re.compile(r"display-schedule"))
            if link is not None and "Schedule" in _text(link):
                current_level_label = _text(link).replace(" Schedule", "").strip()
                current_level_id = _level_id_from_href(link.get("href", ""))
            continue  # header/separator row (division title, "Division Player Stats", or column headers)

        team_link = tr.find("a", href=re.compile(r"display-schedule\?team="))
        if team_link is None:
            continue

        tds = tr.find_all("td")
        if len(tds) < 12:
            continue

        team_id = _team_id_from_href(team_link.get("href", ""))
        name = _text(team_link)
        # tds layout: [rank, team(link), GP, W, L, T, OTW, OTL, GF, GA, +/-, PTS, PIMs]
        stat_cells = tds[-11:]
        gp, w, l, t, otw, otl, gf, ga, plus_minus, pts, pims = [_int_or_none(_text(c)) for c in stat_cells]

        rows.append({
            "team_id": team_id,
            "name": name,
            "level_id": current_level_id,
            "level_label": current_level_label,
            "gp": gp, "w": w, "l": l, "t": t, "otw": otw, "otl": otl,
            "gf": gf, "ga": ga, "plus_minus": plus_minus, "pts": pts, "pims": pims,
        })
    return rows


# ---------------------------------------------------------------------------
# Team schedule + season stat tables: display-schedule
# ---------------------------------------------------------------------------

def _table_header_text(table) -> str:
    first_tr = table.find("tr")
    if first_tr is None:
        return ""
    th = first_tr.find("th")
    return _text(th)


def _parse_game_rows(table) -> list[dict]:
    games = []
    trs = table.find_all("tr")
    for tr in trs[1:]:  # skip the "Game Results" title row (column-header row is trs[1])
        tds = tr.find_all("td")
        if len(tds) < 13:
            continue
        game_link = tds[0].find("a", href=re.compile(r"game_id="))
        if game_link is not None:
            qs = urlparse.parse_qs(urlparse.urlparse(game_link.get("href", "")).query)
            game_id = int(qs["game_id"][0])
            has_boxscore = True
        else:
            raw = _text(tds[0]).rstrip("*")
            if not raw.isdigit():
                continue
            game_id = int(raw)
            has_boxscore = False

        away_goals, away_mark = _score(_text(tds[7]))
        home_goals, home_mark = _score(_text(tds[9]))
        marker = away_mark or home_mark
        scoresheet_link = tds[11].find("a", href=True)

        games.append({
            "game_id": game_id,
            "date": _text(tds[1]),
            "time": _text(tds[2]),
            "rink": _text(tds[3]),
            "league_label": _text(tds[4]),
            "level_label": _text(tds[5]),
            "away_name": _text(tds[6]),
            "away_goals": away_goals,
            "home_name": _text(tds[8]),
            "home_goals": home_goals,
            "game_type": _text(tds[10]),
            "has_boxscore": has_boxscore,
            "is_final": away_goals is not None and home_goals is not None,
            "decided_in": {"O": "OT", "S": "SO"}.get(marker, marker) if marker else None,
            "scoresheet_url": scoresheet_link.get("href") if scoresheet_link else None,
        })
    return games


_SKATER_STAT_KEYS = [
    "number", "gp", "goals", "assists", "ppg", "ppa", "shg", "sha", "gwg", "gwa",
    "psg", "eng", "uag", "ig", "ia", "tg", "ta", "fg", "sog", "soa", "shots",
    "pims", "plus_minus", "hat", "pts",
]

_GOALIE_STAT_KEYS = [
    "number", "gp", "shots", "ga", "gaa", "save_pct", "goals", "assists", "pims",
    "pts", "so", "toi", "w", "l", "otl", "sol", "rw", "otw", "sow", "tie",
]


def _parse_player_stat_table(table, stat_keys) -> list[dict]:
    players = []
    trs = table.find_all("tr")
    for tr in trs[2:]:  # skip title row + column-header row
        player_link = tr.find("a", href=re.compile(r"display-player-stats"))
        if player_link is None:
            continue
        player_id = _player_id_from_href(player_link.get("href", ""))
        name = _text(player_link)

        cells = tr.find_all(["td", "TD"])
        # first cell holds the name+link; the rest line up with stat_keys
        values = [_text(c) for c in cells[1:1 + len(stat_keys)]]
        row = {"player_id": player_id, "name": name}
        for key, val in zip(stat_keys, values):
            row[key] = _int_or_none(val) if key not in ("gaa", "save_pct", "toi") else (val or None)
        players.append(row)
    return players


def parse_team_page(html: str) -> dict:
    """Parses a display-schedule page: games + (if played) this team's season stat tables."""
    soup = _soup(html)
    result = {"games": [], "player_stats": [], "goalie_stats": []}

    for table in soup.find_all("table"):
        header = _table_header_text(table)
        if header == "Game Results":
            result["games"] = _parse_game_rows(table)
        elif header == "Player Stats":
            result["player_stats"] = _parse_player_stat_table(table, _SKATER_STAT_KEYS)
        elif header == "Goalie Stats":
            result["goalie_stats"] = _parse_player_stat_table(table, _GOALIE_STAT_KEYS)
    return result


_LEAGUE_STAT_KEYS = ["number", "team", "gp", "goals", "assists", "hat", "pims", "pts_per_game", "pts"]


def parse_league_player_stats(html: str) -> list[dict]:
    """Parses display-league-stats?...&level=L (every player in one division/season)."""
    soup = _soup(html)
    for table in soup.find_all("table"):
        if _table_header_text(table) != "Player Stats":
            continue
        players = []
        for tr in table.find_all("tr")[2:]:
            player_link = tr.find("a", href=re.compile(r"display-player-stats"))
            if player_link is None:
                continue
            cells = tr.find_all(["td", "TD"])
            values = [_text(c) for c in cells[1:1 + len(_LEAGUE_STAT_KEYS)]]
            row = {"player_id": _player_id_from_href(player_link.get("href", "")), "name": _text(player_link)}
            for key, val in zip(_LEAGUE_STAT_KEYS, values):
                row[key] = val if key in ("team", "pts_per_game") else _int_or_none(val)
            players.append(row)
        return players
    return []


# ---------------------------------------------------------------------------
# Box score: oss-scoresheet
# ---------------------------------------------------------------------------

def parse_boxscore(html: str, game_id: int) -> dict:
    soup = _soup(html)

    # Final score / team names table: has a header row with "Team Name"
    away_name = home_name = None
    away_final = home_final = None
    for table in soup.find_all("table"):
        header_row = table.find("tr")
        if header_row and "Team Name" in _text(header_row):
            trs = table.find_all("tr")
            for tr in trs:
                th = tr.find("th")
                label = _text(th)
                if label == "Visitor":
                    tds = tr.find_all("td")
                    away_name = _text(tds[0])
                    away_final = _int_or_none(_text(tds[-2]))
                elif label == "Home":
                    tds = tr.find_all("td")
                    home_name = _text(tds[0])
                    home_final = _int_or_none(_text(tds[-2]))
            break

    # Rosters: tables headed "<Team Name> Players in Game <id>" or "...in game <id>"
    rosters = {}  # team_name -> [{number, position, name}]
    for table in soup.find_all("table"):
        header_th = table.find("th", attrs={"colspan": True})
        if header_th is None:
            continue
        htext = _text(header_th)
        m = re.match(r"^(.*?) Players in [Gg]ame (\d+)$", htext)
        if not m:
            continue
        team_name = m.group(1).strip()
        roster = []
        # The header table wraps a nested data table (# / P / Name x2); find that one specifically
        # rather than skipping a fixed number of rows, since the outer table's own rows are just
        # the title and a single wrapper cell around the nested table.
        data_table = None
        for nested in table.find_all("table"):
            first_row_cells = nested.find("tr")
            if first_row_cells and _text(first_row_cells.find("th")) == "#":
                data_table = nested
                break
        if data_table is None:
            continue
        inner_rows = data_table.find_all("tr")[1:]
        for tr in inner_rows:
            cells = tr.find_all("td")
            for i in (0, 3):
                if i + 2 >= len(cells):
                    continue
                num = _text(cells[i])
                pos = _text(cells[i + 1])
                name = _text(cells[i + 2])
                if num == "" and name == "":
                    continue
                roster.append({"number": _int_or_none(num), "position": pos or None, "name": name})
        rosters[team_name] = roster

    # Scoring + Penalties: two side-by-side (away, home) pairs of tables, in document order.
    scoring_tables = []
    penalty_tables = []
    for table in soup.find_all("table"):
        header_th = table.find("th", attrs={"colspan": True})
        htext = _text(header_th) if header_th is not None else ""
        if htext == "Scoring":
            scoring_tables.append(table)
        elif htext == "Penalties":
            penalty_tables.append(table)

    def parse_scoring(table) -> list[dict]:
        goals = []
        for tr in table.find_all("tr")[2:]:
            cells = tr.find_all("td")
            if len(cells) < 6:
                continue
            goals.append({
                "period": _text(cells[0]),
                "time": _text(cells[1]),
                "situation": _text(cells[2]) or None,
                "scorer_number": _int_or_none(_text(cells[3])),
                "assist1_number": _int_or_none(_text(cells[4])),
                "assist2_number": _int_or_none(_text(cells[5])),
            })
        return goals

    def parse_penalties(table) -> list[dict]:
        pens = []
        for tr in table.find_all("tr")[2:]:
            cells = tr.find_all("td")
            if len(cells) < 8:
                continue
            pens.append({
                "period": _text(cells[0]),
                "number": _int_or_none(_text(cells[1])),
                "infraction": _text(cells[2]),
                "minutes": _int_or_none(_text(cells[3])),
                "off_ice": _text(cells[4]),
                "start": _text(cells[5]),
                "end": _text(cells[6]),
                "on_ice": _text(cells[7]),
            })
        return pens

    away_goals = parse_scoring(scoring_tables[0]) if len(scoring_tables) > 0 else []
    home_goals = parse_scoring(scoring_tables[1]) if len(scoring_tables) > 1 else []
    away_penalties = parse_penalties(penalty_tables[0]) if len(penalty_tables) > 0 else []
    home_penalties = parse_penalties(penalty_tables[1]) if len(penalty_tables) > 1 else []

    for g in away_goals:
        g["team"] = "away"
    for g in home_goals:
        g["team"] = "home"

    return {
        "game_id": game_id,
        "away_name": away_name,
        "home_name": home_name,
        "away_final": away_final,
        "home_final": home_final,
        "rosters": rosters,  # team_name -> [{number, position, name}]
        "goals": away_goals + home_goals,
        "penalties": {"away": away_penalties, "home": home_penalties},
    }


# ---------------------------------------------------------------------------
# Player career page: display-player-stats?player=P
# ---------------------------------------------------------------------------

_PLAYER_SUMMARY_KEYS = ["team", "season_label", "gp", "goals", "assists", "pims", "pts", "ppg", "shg", "gwg"]
_PLAYER_GAME_KEYS = ["team", "season_label", "opponent", "date", "game_id", "goals", "assists", "pims", "pts",
                     "ppg", "shg", "gwg"]
_PLAYER_INT_KEYS = {"gp", "goals", "assists", "pims", "pts", "ppg", "shg", "gwg", "game_id"}


def parse_player_page(html: str) -> dict:
    """Parses a player's career page -- every team they've ever been rostered on, in EVERY league and
    season this TimeToScore instance hosts (not just our division), as one summary row per
    team-season plus a full game-by-game log. This is the only page on the site that crosses league
    boundaries, which is what makes a cross-league "what caliber of player is this" read possible.

    Returns {name, summary: [{team, season_label, gp, goals, assists, pims, pts, ppg, shg, gwg}],
             games: [{team, season_label, opponent, date (YYYY-MM-DD), game_id, goals, assists, pims, pts, ...}]}
    Note `ppg` here is the site's *power-play goals* column, not points per game.
    """
    soup = _soup(html)
    bio = soup.find("div", id="player_bio")
    name = _text(bio.find("th")) if bio else ""

    def rows_of(table, keys):
        out = []
        for tr in table.find_all("tr")[2:]:  # title row + column-header row
            cells = tr.find_all(["td", "TD"])
            if len(cells) < len(keys):
                continue
            row = {}
            for key, cell in zip(keys, cells):
                val = _text(cell)
                row[key] = _int_or_none(val) if key in _PLAYER_INT_KEYS else val
            out.append(row)
        return out

    summary, games = [], []
    for table in soup.find_all("table"):
        header = _table_header_text(table)
        if header == "Summary Stats":
            summary = rows_of(table, _PLAYER_SUMMARY_KEYS)
        elif header == "Detailed Stats":
            games = rows_of(table, _PLAYER_GAME_KEYS)
    return {"name": name, "summary": summary, "games": games}


def parse_current_season_id(html: str):
    """The standings page for `season=0` ("Current") never says which real season id that is, but
    every team link on it carries the resolved `season=N` -- read it off the first one."""
    soup = _soup(html)
    link = soup.find("a", href=re.compile(r"display-schedule\?team=\d+&season=\d+"))
    if link is None:
        return None
    qs = urlparse.parse_qs(urlparse.urlparse(link.get("href", "")).query)
    vals = qs.get("season")
    return int(vals[0]) if vals else None


def parse_league_label(html: str):
    """The league-wide 'X Schedule' header at the top of a standings page (e.g. 'BH Adult', 'ID Adult')."""
    soup = _soup(html)
    for th in soup.find_all("th", attrs={"colspan": True}):
        link = th.find("a", href=re.compile(r"display-schedule"))
        if link is not None and "Schedule" in _text(link) and _level_id_from_href(link.get("href", "")) is None:
            return _text(link).replace(" Schedule", "").strip()
    return None
