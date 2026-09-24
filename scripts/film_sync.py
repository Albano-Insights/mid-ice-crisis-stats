"""Syncs game film to the scoresheet: a video timestamp for every goal, so the dashboard can deep-link
"▶ watch" straight to the moment.

How (and why not the obvious way): the rink camera pans and zooms with play, the upload is
compressed, and the scoreboard's clock digits are ~14 px -- unreadable even to a person. The SCORE
digits are twice that and bright red, and a score change IS the event we want. So this never reads
digits at all: it locates the scoreboard in each sampled frame (multi-scale template match), takes a
small fingerprint of each side's score box, and flags sustained changes. Each change is a goal,
bracketed between the last frame with the old score and the first with the new one; the ordered
changes are matched to the scoresheet's ordered goals per side. Camera-away gaps make the bracket
wider, never wrong.

Hand overrides: data/film_anchors/<game_id>.json ({"goals": {"<index>": <video seconds>}}) beats
the automatic bracket for that goal -- for the film-tag form's "that's the wrong moment" case.

Cost: one 1080p download + decode per NEW video (results cached in data/raw/film/<video_id>.json),
so the nightly run only pays for fresh uploads. Needs yt-dlp, imageio-ffmpeg, opencv, numpy.

Usage: python scripts/film_sync.py [--max-new 2] [--game 8627]
Writes data/derived/film_sync.json.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
DATA_RAW = ROOT / "data" / "raw"
FILM_RAW = DATA_RAW / "film"
ANCHORS_DIR = ROOT / "data" / "film_anchors"
TEMPLATES_DIR = ROOT / "data" / "film" / "templates"   # one <rink>.png (+ optional <rink>.json) per scoreboard
OUT = ROOT / "data" / "derived" / "film_sync.json"
VIDEOS = DATA_RAW / "youtube_videos.json"

FRAME_STEP_S = 5          # sample every N seconds; the bracket can't be tighter than this
TOP_ROWS = 520            # the board is always in the top part of a 1080p frame
MIN_MATCH = 0.62          # template score below which the board is "not in frame"
LEAD_IN_S = 20            # deep links start this far before the bracket's end
# Where the two score readouts sit inside a matched template, as fractions of its width/height.
# The default is the SeatGeek Rink board; a template's sidecar .json can override ("score_boxes").
SCORE_BOXES = {"home_or_left": (0.400, 0.40, 0.470, 0.58), "away_or_right": (0.630, 0.40, 0.700, 0.58)}
SCALES = (0.7, 0.85, 1.0, 1.2, 1.45, 1.75, 2.1)
DETECT_SHRINK = 2         # locate the board on a half-size frame (16x cheaper), crop at full size


def _load_json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Frame analysis (opencv/numpy imported lazily so the build never needs them)
# ---------------------------------------------------------------------------

def _analyze_video(mp4: Path) -> dict:
    import cv2
    import numpy as np

    # One template per rink scoreboard: <name>.png plus an optional <name>.json sidecar with that
    # board's "score_boxes". Every frame is matched against all of them and the best wins, so a
    # game can be on any rink we've cropped a board for.
    templates = []
    for png in sorted(TEMPLATES_DIR.glob("*.png")):
        img = cv2.imread(str(png), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        meta = _load_json(png.with_suffix(".json"), {}) or {}
        boxes = {k: tuple(v) for k, v in (meta.get("score_boxes") or SCORE_BOXES).items()}
        templates.append({"name": png.stem, "img": img, "boxes": boxes, "min_match": float(meta.get("min_match", MIN_MATCH))})
    if not templates:
        raise SystemExit(f"no scoreboard templates in {TEMPLATES_DIR}")

    def locate(gray):
        """Multi-scale match of every template on a shrunken frame; returns (confidence, rectangle in
        full-size pixel coordinates, template)."""
        small = cv2.resize(gray, None, fx=1 / DETECT_SHRINK, fy=1 / DETECT_SHRINK, interpolation=cv2.INTER_AREA)
        best = (0.0, None, None)
        for tp in templates:
            tpl = tp["img"]
            for scale in SCALES:
                t = cv2.resize(tpl, None, fx=scale / DETECT_SHRINK, fy=scale / DETECT_SHRINK)
                if t.shape[0] >= small.shape[0] or t.shape[1] >= small.shape[1] or min(t.shape) < 8:
                    continue
                r = cv2.matchTemplate(small, t, cv2.TM_CCOEFF_NORMED)
                _, mx, _, loc = cv2.minMaxLoc(r)
                if mx > best[0]:
                    best = (mx, (loc[0] * DETECT_SHRINK, loc[1] * DETECT_SHRINK, int(tpl.shape[1] * scale), int(tpl.shape[0] * scale)), tp)
        return best

    def fingerprint(board, frac):
        h, w = board.shape[:2]
        fx0, fy0, fx1, fy1 = frac
        sub = board[int(fy0 * h):int(fy1 * h), int(fx0 * w):int(fx1 * w)]
        if sub.size == 0:
            return None
        b, g, r = [sub[..., i].astype(float) for i in range(3)]
        red = cv2.resize(r - (g + b) / 2, (12, 16), interpolation=cv2.INTER_AREA)
        red -= red.min()
        return np.zeros((16, 12)) if red.max() < 8 else red / red.max()

    cap = cv2.VideoCapture(str(mp4))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    obs = []
    used: dict[str, int] = {}
    for frame_no in range(0, total, int(fps * FRAME_STEP_S)):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
        ok, bgr = cap.read()
        if not ok:
            break
        if bgr.shape[0] > 1080:  # a local 1440p master: bring it to the 1080p geometry the constants assume
            bgr = cv2.resize(bgr, (round(bgr.shape[1] * 1080 / bgr.shape[0]), 1080), interpolation=cv2.INTER_AREA)
        top = bgr[:TOP_ROWS]
        conf, rect, tp = locate(cv2.cvtColor(top, cv2.COLOR_BGR2GRAY))
        if rect is None or conf < tp["min_match"]:
            continue
        x, y, w, h = rect
        board = top[y:y + h, x:x + w]
        fps_ = {k: fingerprint(board, v) for k, v in tp["boxes"].items()}
        used[tp["name"]] = used.get(tp["name"], 0) + 1
        if any(v is None for v in fps_.values()):
            continue
        # A real board always shows lit red score digits (a "0" included); a wall or ceiling that
        # happens to match the template shape has none -- drop it, whatever its match score.
        if all(not v.any() for v in fps_.values()):
            continue
        obs.append({"t": frame_no / fps, "conf": float(conf), **fps_})
        if len(obs) % 100 == 0:
            print(f"[film]   {frame_no / fps:.0f}s: board seen in {len(obs)} samples so far", flush=True)
    cap.release()

    # Cache the raw fingerprints, not a verdict: segmentation needs the scoresheet (how many
    # changes to expect), and keeping these means re-syncing never costs another decode.
    samples = [{"t": round(o["t"], 1), "conf": round(o["conf"], 3),
                **{side: [round(float(v), 3) for v in o[side].ravel()] for side in SCORE_BOXES}} for o in obs]
    return {"frames_sampled": total // int(fps * FRAME_STEP_S), "frames_with_board": len(obs),
            "duration_s": round(total / fps, 1), "templates": used, "samples": samples}


def _download(video_id: str, dest: Path) -> Path:
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    out = dest / f"{video_id}.mp4"
    cmd = [sys.executable, "-m", "yt_dlp", "--quiet", "--no-warnings", "--ffmpeg-location", ff,
           "-f", "bv*[height=1080][ext=mp4]/bv*[height<=1080]", "-o", str(out),
           f"https://www.youtube.com/watch?v={video_id}"]
    subprocess.run(cmd, check=True)
    return out


DURATIONS = FILM_RAW / "durations.json"


def duration_cached(video_id: str) -> float | None:
    """Video length without downloading it -- enough for the approximate links on games whose
    full analysis hasn't run yet."""
    cache = _load_json(DURATIONS, {})
    if video_id in cache:
        return cache[video_id]
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as y:
            info = y.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        cache[video_id] = float(info.get("duration") or 0)
    except Exception as exc:  # network hiccup, private video: just no links for now
        print(f"[film] could not read duration of {video_id}: {exc}")
        return None
    _save_json(DURATIONS, cache)
    return cache[video_id]


def analyze_cached(video_id: str, refresh: bool = False, local_file: Path | None = None) -> dict | None:
    """`local_file`: analyze this mp4 (the master we uploaded) instead of downloading from YouTube --
    the way to run this on a laptop now that YouTube bot-blocks the GitHub runner's downloads. The
    file must be the same cut as the upload, or every timestamp is off by the difference."""
    path = FILM_RAW / f"{video_id}.json"
    cached = None if refresh else _load_json(path)
    if cached is not None:
        return cached
    if local_file is not None:
        result = _analyze_video(local_file)
    else:
        tmp = Path(tempfile.mkdtemp(prefix="film_"))
        try:
            mp4 = _download(video_id, tmp)
            result = _analyze_video(mp4)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    _save_json(path, result)
    return result


# ---------------------------------------------------------------------------
# Matching score changes to the scoresheet
# ---------------------------------------------------------------------------

def _goals_in_order(game: dict) -> list[dict]:
    def key(g):
        per = ["1", "2", "3"].index(g["period"]) if g["period"] in ("1", "2", "3") else 3
        try:
            m, s = g["time"].split(":")
            clock = int(m) * 60 + int(s)
        except (ValueError, AttributeError):
            clock = 0
        return (per, -clock)  # the clock counts down within a period
    return sorted(game["goals"], key=key)


def _segment(series: list[list[float]], k: int) -> list[int]:
    """Split a sequence of fingerprints into k+1 contiguous runs minimizing within-run variance --
    change-point detection with the number of changes KNOWN (from the scoresheet). Returns the k
    change indices (first sample of each new run). O(k n^2); n is a few hundred."""
    import numpy as np
    x = np.asarray(series, dtype=float)
    n = len(x)
    if n == 0 or k == 0:
        return []
    cs = np.vstack([np.zeros((1, x.shape[1])), np.cumsum(x, axis=0)])
    cs2 = np.concatenate([[0.0], np.cumsum((x * x).sum(axis=1))])

    def cost(i, j):  # samples i..j-1
        m = j - i
        s1 = cs[j] - cs[i]
        return float(cs2[j] - cs2[i] - (s1 * s1).sum() / m)

    INF = float("inf")
    best = np.full((k + 1, n + 1), INF)
    arg = np.zeros((k + 1, n + 1), dtype=int)
    for j in range(1, n + 1):
        best[0][j] = cost(0, j)
    for c in range(1, k + 1):
        for j in range(c + 1, n + 1):
            for i in range(c, j):
                v = best[c - 1][i] + cost(i, j)
                if v < best[c][j]:
                    best[c][j], arg[c][j] = v, i
    cuts, j = [], n
    for c in range(k, 0, -1):
        i = int(arg[c][j])
        cuts.append(i)
        j = i
    return sorted(cuts)


def _changes(analysis: dict, side: str, k: int) -> list[dict]:
    samples = analysis.get("samples", [])
    if not samples or k == 0:
        return []
    try:
        cuts = _segment([s[side] for s in samples], k)
    except ImportError:  # no numpy (tag workflow): hand anchors + estimates still apply
        return []
    return [{"side": side, "before_t": samples[i - 1]["t"], "after_t": samples[i]["t"]} for i in cuts]


def _side_orientation(analysis: dict, goals: list[dict]) -> dict[str, str]:
    """Which score box is home? Unknown per rink: try both mappings and keep the one whose change
    points interleave in the scoresheet's order (ties -> left is home, the common convention)."""
    n_home = sum(1 for g in goals if g["team"] == "home")
    n_away = len(goals) - n_home
    order = [g["team"] for g in goals]
    best = None
    for mapping in ({"home_or_left": "home", "away_or_right": "away"}, {"home_or_left": "away", "away_or_right": "home"}):
        ev = []
        for box, team in mapping.items():
            for e in _changes(analysis, box, n_home if team == "home" else n_away):
                ev.append((e["after_t"], team))
        seq = [t for _, t in sorted(ev)]
        agree = sum(1 for a, b in zip(seq, order) if a == b)
        if best is None or agree > best[0]:
            best = (agree, mapping)
    return best[1]


PERIOD_LEN_S = 15 * 60      # this league's periods, stop time
EST_LEAD_IN_S = 75          # an estimate is coarse: start well before the guess so the goal is ahead
# Defaults for the learned clock model (video seconds = lead + stretch * game-clock elapsed +
# intermission * periods completed). Re-fit from hand anchors whenever there are enough of them.
DEFAULT_CLOCK_MODEL = {"lead": -140.0, "stretch": 1.34, "intermission": 130.0, "anchors": 0}
MIN_ANCHORS_TO_FIT = 5


def _elapsed_s(goal: dict) -> float:
    """Game-clock seconds elapsed since the opening faceoff (clock counts down; '30.6' = seconds)."""
    per = ["1", "2", "3"].index(goal["period"]) if goal["period"] in ("1", "2", "3") else 3
    t = str(goal.get("time") or "")
    try:
        remaining = (int(t.split(":")[0]) * 60 + float(t.split(":")[1])) if ":" in t else float(t)
    except ValueError:
        remaining = PERIOD_LEN_S / 2
    return per * PERIOD_LEN_S + (PERIOD_LEN_S - min(remaining, PERIOD_LEN_S))


def _period_index(goal: dict) -> int:
    return ["1", "2", "3"].index(goal["period"]) if goal["period"] in ("1", "2", "3") else 3


def _lstsq3(rows: list[tuple[float, float, float]], ys: list[float]) -> list[float] | None:
    """Tiny normal-equations solve (3 unknowns) so the tag workflow needs no numpy."""
    n = 3
    A = [[sum(r[i] * r[j] for r in rows) for j in range(n)] for i in range(n)]
    b = [sum(r[i] * y for r, y in zip(rows, ys)) for i in range(n)]
    for c in range(n):  # Gaussian elimination with partial pivoting
        piv = max(range(c, n), key=lambda r: abs(A[r][c]))
        if abs(A[piv][c]) < 1e-9:
            return None
        A[c], A[piv], b[c], b[piv] = A[piv], A[c], b[piv], b[c]
        for r in range(n):
            if r != c:
                f = A[r][c] / A[c][c]
                A[r] = [x - f * y for x, y in zip(A[r], A[c])]
                b[r] -= f * b[c]
    return [b[i] / A[i][i] for i in range(n)]


def _anchor_points(game: dict, anchors: dict | None) -> list[tuple[float, int, int]]:
    """(elapsed, period_index, video_t) for every hand-anchored goal in a game."""
    goals = _goals_in_order(game)
    pts = []
    for idx, g in enumerate(goals):
        v = (anchors or {}).get("goals", {}).get(str(idx))
        if v is None:
            for a in (anchors or {}).get("by_goal", []):
                if (a["team"], a["period"], a["time"]) == (g["team"], g["period"], g["time"]):
                    v = a["video_t"]
        if v is not None:
            pts.append((_elapsed_s(g), _period_index(g), int(v)))
    return sorted(pts)


def learn_clock_model(games_with_anchors: list[tuple[dict, dict]]) -> dict:
    """Fit lead / stretch / intermission across every hand-anchored goal in every game. Each game's
    video starts at its own moment, so the fit is on per-game-demeaned points when there is more than
    one game (a fixed effect per game) and the lead is the mean residual."""
    pts_by_game = [_anchor_points(g, a) for g, a in games_with_anchors]
    pts_by_game = [p for p in pts_by_game if p]
    n = sum(len(p) for p in pts_by_game)
    if n < MIN_ANCHORS_TO_FIT:
        return dict(DEFAULT_CLOCK_MODEL)
    rows, ys = [], []
    for pts in pts_by_game:
        for el, per, v in pts:
            rows.append((1.0, el, float(per))); ys.append(float(v))
    fit = _lstsq3(rows, ys)
    if fit is None or not (1.0 <= fit[1] <= 2.0):
        return dict(DEFAULT_CLOCK_MODEL)
    res = [y - (fit[0] + fit[1] * r[1] + fit[2] * r[2]) for r, y in zip(rows, ys)]
    return {"lead": round(fit[0], 1), "stretch": round(fit[1], 3), "intermission": round(fit[2], 1),
            "anchors": n, "games": len(pts_by_game), "mae_s": round(sum(abs(x) for x in res) / n)}


def _estimate_video_t(goal: dict, duration_s: float, model: dict | None = None, anchor_pts: list | None = None) -> int:
    """Where a goal probably is on film when nobody has anchored it. Best: interpolate between this
    game's own hand anchors (stoppages between two known goals are shared out evenly). Otherwise the
    clock model learned from every anchored game; the video duration is only a last resort."""
    el, per = _elapsed_s(goal), _period_index(goal)
    model = model or DEFAULT_CLOCK_MODEL
    predict = lambda e, p: model["lead"] + model["stretch"] * e + model["intermission"] * p
    pts = anchor_pts or []
    before = [p for p in pts if p[0] <= el]
    after = [p for p in pts if p[0] >= el]
    if before and after:
        (e0, p0, v0), (e1, p1, v1) = before[-1], after[0]
        if e1 == e0:
            guess = v0
        else:
            # Interpolate on the model's own scale so an intermission between the anchors lands in
            # the right place rather than being smeared across the game clock.
            m0, m1, m = predict(e0, p0), predict(e1, p1), predict(el, per)
            guess = v0 + (v1 - v0) * ((m - m0) / (m1 - m0) if m1 != m0 else 0.5)
    elif before or after:
        e0, p0, v0 = before[-1] if before else after[0]
        guess = v0 + (predict(el, per) - predict(e0, p0))
    elif model.get("anchors"):
        guess = predict(el, per)
    else:
        guess = el / (3 * PERIOD_LEN_S) * duration_s
    return max(0, int(guess) - EST_LEAD_IN_S)


def sync_game(game: dict, analysis: dict, anchors: dict | None, model: dict | None = None) -> dict:
    goals = _goals_in_order(game)
    anchor_pts = _anchor_points(game, anchors)
    side_of = _side_orientation(analysis, goals)
    n_by_team = {"home": sum(1 for g in goals if g["team"] == "home"), "away": sum(1 for g in goals if g["team"] == "away")}
    per_side = {team: _changes(analysis, box, n_by_team[team]) for box, team in side_of.items()}
    # Sanity: the change points, sorted by time, must follow the scoresheet's goal order -- if they
    # don't, the board flickered or the crop drifted and NONE of them are trusted; we fall back to
    # a coarse linear estimate instead of confidently linking the wrong moment.
    seq = [team for _, team in sorted((e["after_t"], team) for team, es in per_side.items() for e in es)]
    order_ok = seq == [g["team"] for g in goals]
    duration = analysis.get("duration_s") or 0
    used = {"home": 0, "away": 0}
    out = []
    for idx, g in enumerate(goals):
        team = g["team"]
        ev = per_side[team][used[team]] if (order_ok and used[team] < len(per_side[team])) else None
        used[team] += 1
        manual = (anchors or {}).get("goals", {}).get(str(idx))
        if manual is None:  # the tag form anchors by the goal's identity, not its index
            for a in (anchors or {}).get("by_goal", []):
                if (a["team"], a["period"], a["time"]) == (g["team"], g["period"], g["time"]):
                    manual = a["video_t"]
        if manual is not None:
            video_t, method, bracket = int(manual), "manual", None
        elif ev:
            video_t, method = max(0, int(ev["after_t"]) - LEAD_IN_S), "score-change"
            bracket = [ev["before_t"], ev["after_t"]]
        elif duration:
            video_t, bracket = _estimate_video_t(g, duration, model, anchor_pts), None
            method = "estimate"
        else:
            video_t, method, bracket = None, "unmatched", None
        out.append({"index": idx, "period": g["period"], "time": g["time"], "team": team,
                    "scorer_number": g.get("scorer_number"), "video_t": video_t, "method": method, "bracket": bracket})
    matched = sum(1 for o in out if o["video_t"] is not None)
    return {"goals": out, "matched": matched, "total": len(goals), "order_matches_scoresheet": order_ok,
            "frames_with_board": analysis.get("frames_with_board"), "frames_sampled": analysis.get("frames_sampled")}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-new", type=int, default=2, help="new videos to download+analyze this run")
    ap.add_argument("--game", type=int, action="append", help="only these game ids (repeatable)")
    ap.add_argument("--refresh", action="store_true", help="re-analyze even if cached")
    ap.add_argument("--local-file", action="append", default=[], metavar="VIDEO_ID=PATH",
                    help="analyze this local mp4 for that video id instead of downloading (repeatable)")
    ap.add_argument("--boxscore", metavar="GAME_JSON",
                    help="standalone mode: sync this game dict (scripts/boxscore_json.py output, i.e. any "
                         "league game, not just ours) against --video, and write --out. Nothing in data/ is touched.")
    ap.add_argument("--video", metavar="PATH", help="the local mp4 to analyze in --boxscore mode")
    ap.add_argument("--out", metavar="PATH", help="where to write the result in --boxscore mode")
    args = ap.parse_args()

    if args.boxscore:
        if not args.video or not args.out:
            raise SystemExit("--boxscore needs --video <file.mp4> and --out <result.json>")
        game = _load_json(Path(args.boxscore))
        if game is None:
            raise SystemExit(f"no such game json: {args.boxscore}")
        analysis = _analyze_video(Path(args.video))
        synced = sync_game(game, analysis, None, None)
        _save_json(Path(args.out), {"video": args.video, "game_id": game.get("game_id"), **synced})
        how = ("from the scoreboard" if any(g["method"] == "score-change" for g in synced["goals"])
               else "approximate (board analysis failed the order check)")
        print(f"[film] game {game.get('game_id')}: {synced['matched']}/{synced['total']} goals linked, {how}")
        print(f"[film] board seen in {synced['frames_with_board']}/{synced['frames_sampled']} samples -> {args.out}")
        return
    local_files: dict[str, Path] = {}
    for spec in args.local_file:
        vid, _, p = spec.partition("=")
        if not vid or not p or not Path(p).exists():
            raise SystemExit(f"--local-file expects VIDEO_ID=existing/path.mp4, got {spec!r}")
        local_files[vid] = Path(p)

    videos = [v for v in _load_json(VIDEOS, []) if v.get("game_id")]
    if args.game:
        videos = [v for v in videos if v["game_id"] in args.game]
    out = _load_json(OUT, {})
    # Learn the clock model from every anchored game (not just the ones being synced this run).
    anchored = []
    for f in sorted(ANCHORS_DIR.glob("*.json")):
        game = _load_json(ROOT / "data" / "derived" / "games" / f.name)
        if game:
            anchored.append((game, _load_json(f)))
    model = learn_clock_model(anchored)
    out["_clock_model"] = model
    print(f"[film] clock model: {model}")
    new_done = 0
    for v in videos:
        gid = str(v["game_id"])
        game = _load_json(ROOT / "data" / "derived" / "games" / f"{gid}.json")
        if game is None:
            continue
        cached = (FILM_RAW / f"{v['video_id']}.json").exists()
        local = local_files.get(v["video_id"])
        if not cached and not args.refresh and local is None and new_done >= args.max_new:
            # Not analyzed yet: approximate links from the duration alone, until its turn comes.
            d = duration_cached(v["video_id"])
            if not d:
                continue
            analysis = {"duration_s": d, "samples": [], "frames_with_board": 0, "frames_sampled": 0}
        else:
            if not cached or args.refresh:
                new_done += 1
                print(f"[film] analyzing {v['video_id']} for game {gid} ...")
            try:
                analysis = analyze_cached(v["video_id"], refresh=args.refresh, local_file=local)
            except Exception as exc:
                # YouTube bot-blocks the GitHub runner's downloads (Sep 2026). Don't lose the game:
                # fall back to duration-based estimates (durations.json is written by the
                # livebarn-youtube skill's `link`), and leave the analysis uncached so a later run
                # -- or a local one -- can still do it properly.
                d = duration_cached(v["video_id"])
                print(f"[film] could not analyze {v['video_id']}: {str(exc).splitlines()[0][:160]}"
                      f" -- {'using duration-based estimates' if d else 'no duration either; skipping'}")
                if not d:
                    continue
                analysis = {"duration_s": d, "samples": [], "frames_with_board": 0, "frames_sampled": 0}
        anchors = _load_json(ANCHORS_DIR / f"{gid}.json")
        synced = sync_game(game, analysis, anchors, model)
        out[gid] = {"video_id": v["video_id"], "url": v["url"], **synced}
        methods = {g["method"] for g in synced["goals"]}
        how = ("from the scoreboard" if "score-change" in methods
               else "approximate (board analysis failed the order check)" if synced["frames_sampled"]
               else "approximate (no board analysis yet)")
        print(f"[film] game {gid}: {synced['matched']}/{synced['total']} goals linked, {how}")
    _save_json(OUT, out)


if __name__ == "__main__":
    main()
