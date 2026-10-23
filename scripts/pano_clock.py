"""Read the game clock off the panoramic scoreboard, and turn it into anchors.

Every published chapter and every play stamp comes from a hand-keyed anchor, and every anchor comes
from the game clock on the PANORAMIC feed. This script is the mechanical half of that job: it
measures the master/pano alignment, renders the clock at any list of times so it can be read, and
cross-checks finished anchors against an independent signal. The reading itself is done by eye --
see WHY AUTOMATING THE READ FAILS below before trying to replace that part.

Three subcommands:

  offset <master.mp4> <pano1.mp4> [pano2 ...]
      Measure master_t = PANO_T - K by audio-envelope cross-correlation. ALWAYS measure; never
      derive the mapping from filenames or from a remembered cut point. LiveBarn's two feeds are
      separate recordings and their filename timestamps get both the SIZE and the SIGN of the
      offset wrong. Trust the result only if it prints STRONG.

  probe --dir <pano folder> <out.png> <t1> <t2> ...
  probe --dir <pano folder> <out.png> range A B STEP
      Render the clock at those PANO_T values as one labelled montage, to be read by eye.

  check <master.mp4> <anchors.json>
      Score each finished anchor against the MASTER's own audio: every anchor is a stoppage, so a
      whistle should be audible within a few seconds. This catches a bad offset or a misread digit
      using a signal completely independent of the board. It also checks the ascending order that
      the all-or-nothing publish guard requires.

PANO_T is seconds from the start of pano block 1: block_index*1800 + time_within_file.

WHY AUTOMATING THE READ FAILS. Detecting "the clock froze" by differencing the board looks obvious
and does not work. Three independent reasons, each measured on 2026-10-21:
  1. The board strip holds both the LED panel and the static building around it. They respond to
     light completely differently, so no single normalisation fits both, and a whole-strip metric
     carries NO signal -- freeze and live play gave identical distributions at every threshold.
  2. Codec noise moves every pixel ~3 gray levels, which swamps the few dozen pixels a digit stroke
     occupies. Per-pixel mean one-second change is a flat 2-4 across the entire strip with no peak
     on the digits at all, so mean-absolute-difference cannot see a tick at any crop.
  3. The panel beats against the camera's exposure over ~10-20 s, so for several seconds at a time
     the digits are captured almost black. Normalising those near-empty crops amplifies pure noise,
     which made a known 44 s freeze score as MORE changed than live play.
Hence `probe` keeps the BRIGHTEST of PHASE frames rather than averaging: that reads straight
through the dark stretches, which is what makes the eye-read practical.
"""
import sys
import json
import glob
import subprocess
import numpy as np
import cv2

FFMPEG = "C:/Users/alban/.claude/skills/livebarn-youtube/bin/ffmpeg.exe"

# Per-rink geometry on the 4080x1360 panoramic frame. The full board strip on the South Rink is
# 300x130 at 3170,330; the game clock alone is the tighter crop below, measured off a gridded dump.
CLOCK = {"south_rink": (3268, 352, 48, 40)}
PHASE, ZOOM, COLS = 26, 9, 4
BLOCK_S = 1800.0
PANO_DIR = None


def _envelope(path, sr=100):
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", path, "-vn", "-ac", "1",
                          "-ar", "8000", "-f", "s16le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32)
    k = 8000 // sr
    n = len(a) // k
    e = np.abs(a[:n * k]).reshape(n, k).mean(1)
    return (e - e.mean()) / (e.std() + 1e-9)


def cmd_offset(argv):
    sr = 100
    m = _envelope(argv[0], sr)
    p = np.concatenate([_envelope(x, sr) for x in argv[1:]])
    print("master %.0f s; pano %.0f s (%d blocks)" % (len(m) / sr, len(p) / sr, len(argv) - 1))
    n = 1 << int(np.ceil(np.log2(len(p) + len(m))))
    cc = np.fft.irfft(np.fft.rfft(p, n) * np.conj(np.fft.rfft(m, n)), n)[:len(p)]
    lag = int(np.argmax(cc))
    ratio = cc[lag] / max(np.median(np.abs(cc)), 1e-9)
    print("lag %.2f s, peak/median %.0fx -> %s"
          % (lag / sr, ratio, "STRONG" if ratio > 20 else "WEAK, do not trust"))
    print("master_t = PANO_T - %.2f" % (lag / sr))


def cmd_probe(argv, rink="south_rink"):
    out, rest = argv[0], argv[1:]
    times = (list(np.arange(float(rest[1]), float(rest[2]), float(rest[3])))
             if rest[0] == "range" else [float(x) for x in rest])
    blocks = sorted(glob.glob(PANO_DIR + "/*.mp4")) if PANO_DIR else []
    if not blocks:
        sys.exit("pass --dir <pano folder>")
    x, y, w, h = CLOCK[rink]
    caps, rows = {}, []
    for t in times:
        bi = min(int(t // BLOCK_S), len(blocks) - 1)
        caps.setdefault(bi, cv2.VideoCapture(blocks[bi]))
        cap = caps[bi]
        cap.set(cv2.CAP_PROP_POS_MSEC, (t - bi * BLOCK_S) * 1000)
        best, bv = None, -1.0
        for _ in range(PHASE):                   # keep the brightest phase, never the average
            ok, f = cap.read()
            if not ok:
                break
            c = f[y:y + h, x:x + w]
            v = float(np.percentile(c[:, :, 2].astype(np.float32)
                                    - np.maximum(c[:, :, 1], c[:, :, 0]).astype(np.float32), 99.0))
            if v > bv:
                best, bv = c, v
        if best is None:
            continue
        big = cv2.resize(best, (w * ZOOM, h * ZOOM), interpolation=cv2.INTER_LANCZOS4)
        lab = np.zeros((h * ZOOM, 150, 3), np.uint8)
        cv2.putText(lab, "%.0f" % t, (4, h * ZOOM // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.85,
                    (0, 255, 0), 2)
        rows.append(np.hstack([lab, big]))
    for c in caps.values():
        c.release()
    per = (len(rows) + COLS - 1) // COLS
    cols = [np.vstack(rows[i:i + per]) for i in range(0, len(rows), per)]
    hh = max(c.shape[0] for c in cols)
    cols = [np.vstack([c, np.zeros((hh - c.shape[0], c.shape[1], 3), np.uint8)]) for c in cols]
    cv2.imwrite(out, np.hstack(cols))
    print("wrote %s (%d probes)" % (out, len(rows)))


def cmd_check(argv):
    master, anchors, sr, tol = argv[0], argv[1], 16000, 6.0
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", master, "-vn", "-ac", "1",
                          "-ar", str(sr), "-f", "s16le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32)
    win, hop = 1024, 512
    f = np.fft.rfftfreq(win, 1.0 / sr)
    band = (f >= 2000) & (f <= 4000)
    w = np.hanning(win)
    n = (len(a) - win) // hop
    E = np.empty(n, np.float32)
    for i in range(n):
        sp = np.abs(np.fft.rfft(a[i * hop:i * hop + win] * w))
        E[i] = sp[band].mean() / (sp.mean() + 1e-9)   # whistle = narrowband vs broadband energy
    t = np.arange(n) * hop / sr
    base = np.median(E)
    spread = np.percentile(E, 90) - base
    d = json.load(open(anchors))
    rows = [("goal", x) for x in d.get("by_goal", [])] + \
           [("pen", x) for x in d.get("by_penalty", [])]
    ok = 0
    print("%-5s %-4s %-6s %-8s %s" % ("kind", "per", "time", "video_t", "verdict"))
    for kind, x in rows:
        sel = (t >= x["video_t"] - tol) & (t <= x["video_t"] + tol)
        z = ((float(E[sel].max()) if sel.any() else 0.0) - base) / max(spread, 1e-9)
        ok += z >= 2.0
        print("%-5s %-4s %-6s %-8d %s z=%.1f"
              % (kind, x["period"], x["time"], x["video_t"],
                 "whistle" if z >= 2.0 else "none   ", z))
    for key in ("by_goal", "by_penalty"):
        v = [x["video_t"] for x in d.get(key, [])]
        print("%s %s" % (key, "ascending" if v == sorted(v)
                         else "NOT ASCENDING - nothing would publish"))
    print("%d/%d anchors land on a whistle" % (ok, len(rows)))


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--dir" in args:
        i = args.index("--dir")
        PANO_DIR = args[i + 1]
        del args[i:i + 2]
    cmd = args[0] if args else ""
    {"offset": cmd_offset, "probe": cmd_probe, "check": cmd_check}.get(
        cmd, lambda _a: sys.exit(__doc__))(args[1:])
