"""Derive a broadcast-style 16:9 auto-pan video from the LiveBarn PANORAMIC feed.

WHY. LiveBarn bills download minutes per 30-minute block PER FEED. Publishing a game today
costs two feeds (auto-follow + panoramic) = 180 min. If the pan can be derived from the pano,
one 90-min buy covers both the published video and the scoreboard/anchor analysis.

GEOMETRY / CALIBRATION  (measured against the far dasher boards, a straight horizontal 3D line)

  PROJECTION  RECTILINEAR, not cylindrical. In a cylindrical mapping, horizontal lines off the
              camera's own elevation MUST bow -- that is a property of the projection, and it
              was the visible "distortion". Rectilinear keeps every straight 3D line straight.
              It costs some vertical field, which the tighter goalie-excluded zoom can afford.
  IH_FOV 155  the panorama's true horizontal coverage. 180 was an assumption and it was wrong:
              it placed the ice at +/-55.5 deg, but a 200 ft rink seen from 85-105 ft can only
              subtend +/-44..50. At 155 the ice spans +/-47.8 deg, and straightness agrees.
  ROLL +0.73  the camera is not level. Correcting it drops the fitted slope of the boards from
              0.647 deg to 0.007 deg.

  Combined effect, same frame: tilt 1.505 -> 0.159 deg, bow ratio 0.0800 -> 0.0477.

  OPEN: the panorama may also be vertically ANISOTROPIC (vertical deg-per-pixel ~1.35x the
  horizontal, i.e. ~155 x 38 deg rather than the equirect-implied ~52). A scale-invariant bow
  metric has a real minimum there and it implies a camera ~6 ft above the ice and ~20 ft back,
  which matches the viewpoint. It is NOT applied, because: (a) measuring bow in raw pixels is
  biased -- stretching the vertical axis shrinks any pixel deviation, so that sweep ran away to
  absurd values; (b) adopting 1.35 cuts usable elevation coverage to +/-19.2 deg, so the camera
  samples past the top of the source and smears; (c) it would undo the seating result, which
  depends on the vertical stretch. SETTLE IT WITH RINK GEOMETRY, not image heuristics: blue
  lines are 50 ft apart, goal line to blue line is 64 ft, centre circle is 30 ft across. A
  correct dewarp must reproduce those ratios on the ice plane.

TILT -- the one that took three attempts.

  The pano camera is mounted angled DOWN (~12 deg) to cover the ice, so the panorama's rows are
  NOT lines of true elevation: its equator is tilted. Panning by simply adding to the panorama
  yaw therefore rotates about the TILTED axis, and the horizon rocks as the camera pans --
  measured ~0.22 deg of image rotation per degree of pan.

  A single ROLL constant cannot fix this, because the error is a FUNCTION of pan. Measuring
  tilt only at pan 0 (as an earlier pass did) reports 0.16 deg and looks solved, while the
  real swing across a +/-18 deg pan is 7.7 deg.

  Distinguishing the causes, by watching how the near and far boards move together:
      near and far tilt the SAME way   -> camera orientation error  -> correctable (this case)
      near and far tilt OPPOSITE ways  -> perspective convergence   -> correct, leave alone
  Beware also that at |pan| > ~25 deg with a wide window the ice boundary being traced is the
  ROUNDED CORNER, not the straight far boards; that produced a spurious 23 deg "swing" reading.

  FIX: compose the rotations properly -- Rx(pitch), then Ry(pan) about the true vertical, then
  Rx(RIG_TILT) into the panorama frame. Fitted by minimising the pan swing:

      rig  0 deg (naive)  pan swing 7.66 deg, mean |tilt| 2.64 deg
      rig 12 deg          pan swing 1.86 deg, mean |tilt| 0.52 deg, worst 1.38 deg

FRAMING POLICY -- exclude the goalies, and everything else gets better.
Measured on game 8846, 1800 frames, median 14 tracked blobs per frame (calibrated degrees):

    span of ALL players            median 81.6 deg (uncalibrated units)
    span DROPPING THE OUTERMOST
    BLOB AT EACH END (the goalies) median 34.4 deg, p90 49.6   <- used

  Chasing the goalies forces a very wide field and throws away the magnification advantage over
  LiveBarn. Dropping the outermost blob per end is a more robust goalie filter than geometric
  crease zones -- those were tried and failed (occupancy peaks only 0.38 / 0.25, and a deep
  forechecker occupies the same ground as a goalie). In production: 99.9 pct of skaters in frame.

MOTION QUALITY -- two DIFFERENT problems, do not confuse them:

  a) CHOPPY ZOOM was a bug. An earlier version cached sampling maps quantised to 0.25 deg of
     fov, so the zoom held ~20 frames then jumped, shifting the frame edge 3.2 px instantly --
     only ~20 distinct zoom values across 1800 frames. FIX: build the map exactly every frame.
     Now ~1775/1800 frames carry their own zoom value; largest step 0.10 deg.
  b) ZOOM BREATHING -- the camera opening and tightening with play -- is WANTED. Do not
     suppress it. An envelope follower (widen fast, tighten slowly) kills it almost entirely
     (5 deg travel per minute) and looks dead. Use a symmetric damped follower with NO
     deadband; a deadband causes stick-slip, which reads as choppy even with exact maps.
     Tuned: sigma 50, vmax 3 deg/s -> ~64 deg travel, 7 reversals per minute.

EMPTY SEATING. The ice band subtends only ~17 deg vertically because the camera is low and
close, so a 16:9 frame wide enough for the play holds a lot of non-ice. Two levers:
  1. Zoom tighter -- which the goalie exclusion makes possible (ice fill 40-61 pct).
  2. Pitch coupled to zoom, pinning the near boards at NEAR_AT of frame height so the seat
     strip stays thin and CONSTANT at every zoom level. Do not exceed ~0.98 or players along
     the near boards get cut. Note this interacts with the open vertical-scale question above.

USAGE
    python scripts/pano_autopan.py <pano.mp4> --start 1245 --dur 60 --out out.mp4

LIMITS
  - calibration is for South Rink; North Rink needs its own pass.
  - the tracker follows the skater cluster, not the puck, so it lags a breakaway.
  - validated on one 60 s window of open play; corner battles are untested.
"""
import argparse, math, os, subprocess
import cv2, numpy as np

FFMPEG = r"C:\Users\alban\.claude\skills\livebarn-youtube\bin\ffmpeg.exe"
FOV_MIN, FOV_MAX = 48.0, 72.0
OW, OH, NEAR_AT = 1920, 1080, 0.97

# ---------------------------------------------------------------------------
# PER-RINK CALIBRATION. Every one of these is a property of how that specific
# panoramic camera is mounted, so a rink that has not been calibrated CANNOT be
# rendered correctly -- the output would be silently tilted and bowed. Running
# an uncalibrated rink is therefore a hard error, never a fallback.
#
# To calibrate a new rink, against the far dasher boards (straight + horizontal
# in the world, so any bow or tilt after dewarping is error by definition):
#   ih_fov    sweep for the straightest fit; cross-check against rink geometry
#             (a 200 ft rink seen from 85-105 ft must subtend +/-44..50 deg)
#   rig_tilt  sweep to MINIMISE PAN SWING (slope measured at several pan angles,
#             narrow window, |pan| <= 18 deg so you stay off the rounded corners)
#   roll      the residual constant slope once rig_tilt is right
#   phi_far / phi_near   elevation of the far and near ice edges, in calibrated
#             degrees: (row - Hin/2) / (Win / ih_fov)
# ---------------------------------------------------------------------------
CALIBRATION = {
    # Baptist Health IcePlex, Rink 1. Calibrated on game 8846 (2026-10-07).
    "South_Rink": dict(ih_fov=155.0, roll=0.56, rig_tilt=12.0,
                       phi_far=-9.88, phi_near=7.22),
    # Baptist Health IcePlex, Rink 2 -- NOT CALIBRATED YET.
    # "North_Rink": dict(...),
}


def calibration_for(pano_path):
    """Pick the calibration from the LiveBarn filename, or fail loudly."""
    name = os.path.basename(pano_path)
    for key, cal in CALIBRATION.items():
        if key.lower() in name.lower():
            return key, cal
    known = ", ".join(CALIBRATION) or "(none)"
    raise SystemExit("\n".join([
        "REFUSING TO RENDER: no calibration for %r." % name,
        "Calibrated rinks: %s." % known,
        "Every rink needs its own ih_fov / rig_tilt / roll / phi_* -- they describe how that",
        "camera is mounted. Borrowing another rink's numbers produces a silently tilted, bowed",
        "video, which is worse than no video. See CALIBRATION in this file for the procedure.",
    ]))


class VCam:
    """Rectilinear camera that pans about the TRUE VERTICAL. Exact map per frame."""

    def __init__(self, Win, Hin, cal, ow=OW, oh=OH, near_at=NEAR_AT, mw=960):
        self.Win, self.Hin, self.ow, self.oh, self.near_at = Win, Hin, ow, oh, near_at
        self.cal = cal
        self.mw = mw
        self.mh = int(round(mw * oh / float(ow)))
        cx, cy = (self.mw - 1) / 2.0, (self.mh - 1) / 2.0
        u = np.arange(self.mw, dtype=np.float32)[None, :].repeat(self.mh, 0)
        v = np.arange(self.mh, dtype=np.float32)[:, None].repeat(self.mw, 1)
        self.du, self.dv = u - cx, v - cy
        self.ppd = Win / cal['ih_fov']

    def vfov(self, hfov):
        return 2 * math.degrees(math.atan(math.tan(math.radians(hfov) / 2) * self.oh / self.ow))

    def pitch_for(self, hfov):
        f = (self.mw / 2.0) / math.tan(math.radians(hfov) / 2.0)
        return math.degrees(math.atan((self.near_at * self.mh - self.mh / 2.0) / f)) - self.cal['phi_near']

    def fill_for(self, hfov):
        vf = self.vfov(hfov)
        return (self.cal['phi_near'] - self.cal['phi_far']) / vf, vf

    def render(self, frame, pan_deg, hfov):
        f = (self.mw / 2.0) / math.tan(math.radians(hfov) / 2.0)
        pitch = self.pitch_for(hfov) - self.cal['rig_tilt']     # virtual tilt, less what the rig already gives
        cr, sr = math.cos(math.radians(self.cal['roll'])), math.sin(math.radians(self.cal['roll']))
        x = (self.du * cr - self.dv * sr) / f
        y = (self.du * sr + self.dv * cr) / f
        z = np.ones_like(x)
        n = np.sqrt(x * x + y * y + z * z); x, y, z = x / n, y / n, z / n

        t = math.radians(pitch)                     # Rx(pitch): virtual tilt
        y1 = y * math.cos(t) - z * math.sin(t)
        z1 = y * math.sin(t) + z * math.cos(t)

        a = math.radians(pan_deg)                   # Ry(pan): about the TRUE VERTICAL
        x2 = x * math.cos(a) + z1 * math.sin(a)
        z2 = -x * math.sin(a) + z1 * math.cos(a)

        g = math.radians(self.cal['rig_tilt'])                  # Rx(rig): into the panorama's tilted frame
        y3 = y1 * math.cos(g) - z2 * math.sin(g)
        z3 = y1 * math.sin(g) + z2 * math.cos(g)

        yaw = np.degrees(np.arctan2(x2, z3))
        elev = np.degrees(np.arcsin(np.clip(y3, -1, 1)))
        mx = cv2.resize((self.Win / 2.0 + yaw * self.ppd).astype(np.float32), (self.ow, self.oh))
        my = cv2.resize((self.Hin / 2.0 + elev * self.ppd).astype(np.float32), (self.ow, self.oh))
        return cv2.remap(frame, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def _medfilt(a, n):
    b = np.pad(a, n // 2, mode="edge")
    return np.array([np.median(b[i:i + n]) for i in range(len(a))])


def _gauss(a, s):
    r = int(3 * s); x = np.arange(-r, r + 1)
    w = np.exp(-x * x / (2 * s * s)); w /= w.sum()
    return np.convolve(np.pad(a, r, mode="edge"), w, mode="valid")


def _follow(tgt, fps, vmax, amax, dead=0.0, k=5.0, c=4.4, lo=-1e9, hi=1e9):
    dt, pos, vel, out = 1.0 / fps, float(tgt[0]), 0.0, []
    for t in tgt:
        e = t - pos
        if dead > 0:
            e = 0.0 if abs(e) < dead else e - math.copysign(dead, e)
        vel = float(np.clip(vel + float(np.clip(k * e - c * vel, -amax, amax)) * dt, -vmax, vmax))
        pos = float(np.clip(pos + vel * dt, lo, hi))
        out.append(pos)
    return np.array(out)


def _ice_mask(bg):
    m = ((bg > 150).astype(np.uint8)) * 255
    band = np.zeros_like(m); band[380:900, 780:3300] = 255
    m = cv2.bitwise_and(m, band)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    _, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    return (lab == 1 + np.argmax(st[1:, cv2.CC_STAT_AREA])).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pano")
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--dur", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--crf", type=int, default=18)
    a = ap.parse_args()

    rink, cal = calibration_for(a.pano)
    IH_FOV = cal['ih_fov']
    print('rink %s | ih_fov %.0f rig_tilt %.1f roll %.2f' % (rink, IH_FOV, cal['rig_tilt'], cal['roll']))

    cap = cv2.VideoCapture(a.pano)
    fps = cap.get(cv2.CAP_PROP_FPS)
    N = int(round(a.dur * fps))

    sm = []
    for i in range(24):
        cap.set(cv2.CAP_PROP_POS_MSEC, (a.start + a.dur * i / 24.0) * 1000)
        ok, fr = cap.read()
        if ok:
            sm.append(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY))
    bg = np.median(np.stack(sm), 0).astype(np.uint8)
    Hin, Win = bg.shape
    mask = _ice_mask(bg)
    PPD = Win / IH_FOV

    cap.set(cv2.CAP_PROP_POS_MSEC, a.start * 1000)
    cen, span = [], []
    for _ in range(N):
        ok, fr = cap.read()
        if not ok:
            break
        d = (cv2.absdiff(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY), bg) > 34).astype(np.uint8) * mask
        d = cv2.morphologyEx(d, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        k, _, st, ct = cv2.connectedComponentsWithStats(d, 8)
        ys = np.sort(np.array([(ct[i][0] - Win / 2.0) / PPD
                               for i in range(1, k) if st[i, cv2.CC_STAT_AREA] >= 120]))
        if len(ys) >= 4:
            z = ys[1:-1]                 # drop the outermost blob each end = the two goalies
            lo, hi = z.min(), z.max()
        elif len(ys) >= 1:
            lo, hi = ys.min(), ys.max()
        else:
            lo = hi = (cen[-1] if cen else 0.0)
        cen.append((lo + hi) / 2.0)
        span.append(hi - lo)
    cen, span = np.array(cen), np.array(span)

    need = np.clip(span * 1.20 + 12.0, FOV_MIN, FOV_MAX)
    zoom = _follow(_gauss(_medfilt(need, 31), 50.0), fps, vmax=3.0, amax=4.0, dead=0.0,
                   lo=FOV_MIN, hi=FOV_MAX)
    pan = _follow(_gauss(_medfilt(cen, 31), 22.0), fps, vmax=9.0, amax=14.0, dead=1.2,
                  lo=-30, hi=30)
    pan = np.clip(pan, -(IH_FOV / 2 - 4 - zoom / 2), (IH_FOV / 2 - 4 - zoom / 2))

    vc = VCam(Win, Hin, cal)
    dz = np.diff(zoom); sg = np.sign(np.where(np.abs(dz) < 1e-6, 0, dz)); nz = sg[sg != 0]
    fl, _ = vc.fill_for(zoom.min()); fh, _ = vc.fill_for(zoom.max())
    print("skater span med %.1f p90 %.1f | zoom %.1f..%.1f travel %.1f reversals %d distinct %d/%d"
          % (np.median(span), np.percentile(span, 90), zoom.min(), zoom.max(), np.abs(dz).sum(),
             int((np.diff(nz) != 0).sum()) if len(nz) > 1 else 0,
             len(np.unique(np.round(zoom, 6))), len(zoom)))
    print("ice fill %.0f-%.0f%% | seats ~%.0f%% | pitch %.1f..%.1f"
          % (100 * fh, 100 * fl, 100 * (1 - NEAR_AT),
             vc.pitch_for(zoom.min()), vc.pitch_for(zoom.max())))

    cap.set(cv2.CAP_PROP_POS_MSEC, a.start * 1000)
    p = subprocess.Popen(
        [FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", "%dx%d" % (OW, OH), "-r", str(fps), "-i", "-",
         "-ss", str(a.start), "-t", str(a.dur), "-i", a.pano,
         "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-preset", "medium",
         "-crf", str(a.crf), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
         "-shortest", "-movflags", "+faststart", a.out], stdin=subprocess.PIPE)
    for i in range(len(pan)):
        ok, fr = cap.read()
        if not ok:
            break
        p.stdin.write(vc.render(fr, pan[i], zoom[i]).tobytes())
    cap.release()
    p.stdin.close()
    p.wait()
    print("wrote", a.out, "rc", p.returncode)


if __name__ == "__main__":
    main()
