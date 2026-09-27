"""Territorial / flow analysis from a LiveBarn PANORAMIC segment (the fixed wide camera).

Why the panoramic feed and not the auto-follow one: the auto-follow camera pans and zooms, so a
pixel means nothing from frame to frame. The panoramic camera never moves (measured: 0 px drift
over 24 minutes), the whole rink is in shot, and therefore x-position in the frame IS position
along the ice. That makes all of this a measurement rather than a proxy:

  - background model  : with a static camera the median frame is the empty rink, so anything that
                        differs from it is a person -- far cleaner than thresholding dark pixels
                        (85-122 false blobs per frame before, 18-37 real ones after).
  - ice mask          : flood fill out from centre ice, which stops at the boards, so the walkway,
                        the far wall and the spectators are all excluded.
  - zone time         : each player's x, normalised across the ice, bucketed into thirds.
  - live play         : enough skaters on the ice actually moving.
  - goalies           : the players who barely move and sit near an end; their jersey colour says
                        which team defends which end, so zone time can be named per team.

Usage: python scripts/pano_flow.py <panoramic.mp4> [--step 1.0] [--out result.json]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

SCALE = 2          # analyse at half resolution: 2040x680 is plenty and 4x faster
DIFF_THRESH = 45   # per-pixel difference from the empty-rink model that counts as "something here"
MIN_BLOB, MAX_BLOB = 25, 4000


def build_background(cap, fps, n=21):
    total = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    frames = []
    for t in np.linspace(0.05 * total, 0.95 * total, n):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t))
        ok, f = cap.read()
        if ok:
            frames.append(cv2.resize(f, None, fx=1 / SCALE, fy=1 / SCALE, interpolation=cv2.INTER_AREA))
    if not frames:
        raise SystemExit("could not read frames for the background model")
    return np.median(np.stack(frames), axis=0).astype(np.uint8)


def ice_mask_from(bg):
    """The playing surface, by flood fill from centre ice.

    Taking "the largest bright region" does not work: the ice, the white far wall and the bright
    concrete walkway all qualify, and any closing operation bridges them across the boards -- that
    version called 50% of the frame ice and swept in the spectators. Flooding out from centre ice
    instead stops at the boards' dark kickplate, which is exactly the boundary wanted (17.6%).
    """
    h, w = bg.shape[:2]
    hsv = cv2.cvtColor(bg, cv2.COLOR_BGR2HSV)
    bright = ((hsv[..., 2] > 130) & (hsv[..., 1] < 80)).astype(np.uint8)
    bright = cv2.morphologyEx(bright, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    seed = None
    for dy in range(0, 160, 4):
        for sy in (h // 2 - dy, h // 2 + dy):
            if 0 <= sy < h and bright[sy, w // 2]:
                seed = (w // 2, sy)
                break
        if seed:
            break
    if seed is None:
        raise SystemExit("could not find centre ice to seed the flood fill")
    ff = bright.copy()
    cv2.floodFill(ff, np.zeros((h + 2, w + 2), np.uint8), seed, 2, loDiff=0, upDiff=0, flags=4 | (255 << 8))
    m = (ff == 2).astype(np.uint8)
    inv = m.copy()  # fill interior holes: the centre logo and faceoff circles are not holes in the ice
    cv2.floodFill(inv, np.zeros((h + 2, w + 2), np.uint8), (0, 0), 1)
    m = (m | (1 - inv)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    return cv2.erode(m, np.ones((7, 7), np.uint8))


def players_in(frame, bg, ice):
    diff = cv2.absdiff(frame, bg).max(axis=2)
    m = (diff > DIFF_THRESH).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    m *= ice
    n, _, st, ce = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for i in range(1, n):
        a = st[i, cv2.CC_STAT_AREA]
        if MIN_BLOB < a < MAX_BLOB:
            x, y = float(ce[i][0]), float(ce[i][1])
            bx, by, bw, bh = (st[i, k] for k in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP,
                                                 cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
            patch = frame[by:by + bh, bx:bx + bw].reshape(-1, 3)
            out.append({"x": x, "y": y, "a": int(a), "bgr": [int(v) for v in patch.mean(axis=0)]})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--step", type=float, default=1.0, help="seconds between samples")
    ap.add_argument("--out", default=None)
    ap.add_argument("--debug-png", default=None, help="write an ice-mask / detection preview")
    args = ap.parse_args()

    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"{Path(args.video).name}: {W}x{H} @ {fps:.2f}, {total/fps/60:.1f} min")

    print("building the empty-rink model...", flush=True)
    bg = build_background(cap, fps)
    ice = ice_mask_from(bg)
    xs_ice = np.where(ice.any(axis=0))[0]
    x_lo, x_hi = int(xs_ice.min()), int(xs_ice.max())
    print(f"ice spans x {x_lo}..{x_hi} of {bg.shape[1]} ({ice.mean()*100:.1f}% of frame)")

    if args.debug_png:
        v = bg.copy()
        v[ice == 0] = (v[ice == 0] * 0.35).astype(np.uint8)
        for f in (x_lo, x_lo + (x_hi - x_lo) // 3, x_lo + 2 * (x_hi - x_lo) // 3, x_hi):
            cv2.line(v, (f, 0), (f, v.shape[0]), (0, 0, 255), 2)
        cv2.imwrite(args.debug_png, v)
        print("wrote", args.debug_png)

    stride = max(1, int(round(fps * args.step)))
    rows = []
    t0 = time.time()
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    idx = 0
    while True:
        if not cap.grab():
            break
        if idx % stride == 0:
            ok, f = cap.retrieve()
            if not ok:
                break
            small = cv2.resize(f, None, fx=1 / SCALE, fy=1 / SCALE, interpolation=cv2.INTER_AREA)
            pl = players_in(small, bg, ice)
            rows.append({"t": round(idx / fps, 2), "players": pl})
            if len(rows) % 200 == 0:
                print(f"  {idx/fps:6.0f}s  {idx/total*100:4.1f}%  {time.time()-t0:5.0f}s", flush=True)
        idx += 1
    cap.release()

    out = {"video": args.video, "fps": fps, "step_s": args.step, "scale": SCALE,
           "width": bg.shape[1], "height": bg.shape[0], "ice_x": [x_lo, x_hi],
           "duration_s": round(total / fps, 1), "samples": rows}
    dest = args.out or str(Path(args.video).with_suffix(".flow.json"))
    json.dump(out, open(dest, "w"))
    print(f"wrote {dest}: {len(rows)} samples in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
