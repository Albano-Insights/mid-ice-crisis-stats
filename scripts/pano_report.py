"""Turn a pano_flow.py sample file into flow / pressure numbers for a segment.

Everything here is a measurement off the fixed panoramic camera, not a proxy:

  where play is  the median x of the skaters on the ice (goalies dropped), normalised across the
                 ice, so 0.0 is one end and 1.0 the other. Hockey pulls players toward the puck,
                 so the skater median tracks the play far more stably than any single blob.
  live play      the skaters are actually moving: median skater speed above a threshold learned
                 from the segment itself. A whistle shows up as everyone coasting to a stop.
  pressure       a run of live play held in one end third for >= MIN_PRESSURE_S seconds.
  goalies        blobs that stay in the outer eighth of the ice and barely move. Their average
                 jersey colour is reported so each end can be attributed to a team.

Usage: python scripts/pano_report.py <flow.json> [--min-pressure 20] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

GOALIE_EDGE = 0.12       # within this fraction of an end...
GOALIE_MAX_SPREAD = 0.05  # ...and moving less than this fraction of the ice overall
MIN_PRESSURE_S = 20


def load(path):
    """Load samples and re-derive the ice mask from the video.

    The mask is recomputed here rather than trusted from extraction time so that a calibration fix
    does not mean re-decoding an hour of video: every blob keeps its x/y, so it can simply be
    re-tested against the correct ice.
    """
    import cv2
    from pano_flow import build_background, ice_mask_from

    d = json.load(open(path))
    cap = cv2.VideoCapture(d["video"])
    if not cap.isOpened():
        raise SystemExit(f"cannot open {d['video']} to rebuild the ice mask")
    bg = build_background(cap, cap.get(cv2.CAP_PROP_FPS) or 30)
    cap.release()
    ice = ice_mask_from(bg)
    xs = np.where(ice.any(axis=0))[0]
    x_lo, x_hi = int(xs.min()), int(xs.max())
    span = max(1.0, x_hi - x_lo)
    h, w = ice.shape
    kept = dropped = 0
    for s in d["samples"]:
        keep = []
        for p in s["players"]:
            xi, yi = int(round(p["x"])), int(round(p["y"]))
            if 0 <= xi < w and 0 <= yi < h and ice[yi, xi]:
                p["nx"] = (p["x"] - x_lo) / span
                keep.append(p)
            else:
                dropped += 1
        kept += len(keep)
        s["players"] = keep
    d["ice_x"] = [x_lo, x_hi]
    print(f"ice x {x_lo}..{x_hi} ({ice.mean()*100:.1f}% of frame); kept {kept} blobs, dropped {dropped} off-ice")
    return d


def find_goalies(samples):
    """Cluster persistent near-the-end blobs into (left, right) goalie tracks."""
    out = {}
    for end, lo, hi in (("left", 0.0, GOALIE_EDGE), ("right", 1.0 - GOALIE_EDGE, 1.0)):
        xs, cols = [], []
        for s in samples:
            near = [p for p in s["players"] if lo <= p["nx"] <= hi]
            if near:
                p = min(near, key=lambda q: abs(q["nx"] - (0.0 if end == "left" else 1.0)))
                xs.append(p["nx"]); cols.append(p["bgr"])
        if len(xs) > 20 and float(np.std(xs)) < GOALIE_MAX_SPREAD:
            b, g, r = np.median(np.array(cols), axis=0)
            out[end] = {"n": len(xs), "x": round(float(np.median(xs)), 3),
                        "bgr": [int(b), int(g), int(r)],
                        "shade": "dark" if (b + g + r) / 3 < 110 else "light"}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("flow")
    ap.add_argument("--min-pressure", type=float, default=MIN_PRESSURE_S)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    d = load(args.flow)
    S = d["samples"]
    step = d.get("step_s", 1.0)
    t = np.array([s["t"] for s in S])
    goalies = find_goalies(S)
    gx = {e: v["x"] for e, v in goalies.items()}

    def skaters(s):
        out = []
        for p in s["players"]:
            if any(abs(p["nx"] - v) < 0.035 for v in gx.values()):
                continue
            out.append(p)
        return out

    nsk = np.array([len(skaters(s)) for s in S], dtype=float)
    playx = np.array([np.median([p["nx"] for p in skaters(s)]) if skaters(s) else np.nan for s in S])

    # speed: median nearest-neighbour displacement between consecutive samples
    speed = np.full(len(S), np.nan)
    for i in range(1, len(S)):
        a = np.array([[p["nx"]] for p in skaters(S[i - 1])])
        b = np.array([[p["nx"]] for p in skaters(S[i])])
        if len(a) >= 3 and len(b) >= 3:
            dmin = [float(np.min(np.abs(a - bb))) for bb in b]
            speed[i] = float(np.median(dmin))

    ok = np.isfinite(speed)
    thr = np.nanpercentile(speed[ok], 40) if ok.sum() > 30 else 0.004
    live = ok & (speed > thr) & (nsk >= 6)
    for _ in range(2):  # bridge single-sample dropouts
        live = np.convolve(live.astype(float), np.ones(3) / 3, mode="same") > 0.4

    total_s = (t[-1] - t[0])
    live_s = live.sum() * step
    print(f"segment {t[0]:.0f}-{t[-1]:.0f}s ({total_s/60:.1f} min), {len(S)} samples")
    print(f"skaters on ice: median {np.nanmedian(nsk[live]) if live.any() else 0:.0f} during live play")
    if goalies:
        for e, v in goalies.items():
            print(f"goalie {e:>5} end: x={v['x']:.2f}  jersey {v['shade']} BGR{tuple(v['bgr'])}  seen {v['n']}x")
    else:
        print("goalies: not identified")
    print(f"live play: {live_s/60:.1f} min of {total_s/60:.1f} ({live_s/total_s*100:.0f}%)")

    runs, cur = [], None
    for i, v in enumerate(live):
        if v and cur is None:
            cur = i
        elif not v and cur is not None:
            runs.append((cur, i)); cur = None
    if cur is not None:
        runs.append((cur, len(live)))
    lens = sorted(((b - a) * step for a, b in runs if (b - a) * step >= 4), reverse=True)
    if lens:
        print(f"{len(lens)} runs of continuous play; median {np.median(lens):.0f}s, longest {lens[0]:.0f}s")

    sel = live & np.isfinite(playx)
    if sel.sum() > 30:
        px = playx[sel]
        L = float((px < 1 / 3).mean() * 100)
        M = float(((px >= 1 / 3) & (px <= 2 / 3)).mean() * 100)
        R = float((px > 2 / 3).mean() * 100)
        print(f"\nZONE TIME (live play, {sel.sum()} samples)")
        print(f"  left end {L:5.1f}%   neutral {M:5.1f}%   right end {R:5.1f}%")

        zone = np.where(px < 1 / 3, -1, np.where(px > 2 / 3, 1, 0))
        idx = np.flatnonzero(sel)
        spells, s0 = [], 0
        for i in range(1, len(zone) + 1):
            if i == len(zone) or zone[i] != zone[s0]:
                dur = (idx[i - 1] - idx[s0] + 1) * step
                if zone[s0] != 0 and dur >= args.min_pressure:
                    spells.append((dur, "left" if zone[s0] < 0 else "right", float(t[idx[s0]])))
                s0 = i
        spells.sort(reverse=True)
        if spells:
            print(f"\nSUSTAINED PRESSURE (>= {args.min_pressure:.0f}s held in one end)")
            for dur, end, when in spells[:8]:
                print(f"  {dur:5.0f}s in the {end:>5} end, from {int(when)//60}:{int(when)%60:02d}")
            tot = {e: sum(d_ for d_, ee, _ in spells if ee == e) for e in ("left", "right")}
            print(f"  totals: left {tot['left']:.0f}s in {sum(1 for s_ in spells if s_[1]=='left')} spells, "
                  f"right {tot['right']:.0f}s in {sum(1 for s_ in spells if s_[1]=='right')} spells")

    if args.json:
        json.dump({"live_pct": live_s / total_s, "zone": {"left": L, "mid": M, "right": R} if sel.sum() > 30 else None,
                   "goalies": goalies}, open(args.json, "w"), indent=2)
        print("wrote", args.json)


if __name__ == "__main__":
    main()
