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
# Chosen on A/B clips of game 9643 (2026-10-22), each cut from one cached track so the clips
# are faithful to a full render. See "Tuning the auto-pan" in SKILL.md for the method.
FOV_MIN, FOV_MAX = 40.0, 72.0
OW, OH, NEAR_AT = 1920, 1080, 0.97
# Residual seat-strip growth at deep pan, after the measured near-edge profile is applied.
# Degrees of extra pitch per pan^2. Fitted: holds the strip at 2.0-3.9% across +/-34 deg of
# pan, where a fixed pitch let it run 1.8% -> 16.3%.
SEAT_C2 = 0.0018
# Seconds of gaussian smoothing on the pitch. Solving the pitch exactly every frame pins the
# near boards but welds the frame's vertical position to the ZOOM: on a rush the fov opens
# ~30 deg and the pitch swings ~9 deg at up to 10 deg/s, which reads as the camera bouncing.
# 0.5 s takes that to 2.5 deg/s; the cost is the near edge wandering to ~1.03 of frame height
# instead of a pinned 0.97. Do not push this far: at 1.0 s it reaches 1.05, and past 1.0 a
# player skating the near boards loses his skates.
PITCH_SMOOTH_S = 0.5
# Rush behaviour: lead the play, and drive toward the goalie once play is in the zone.
LEAD_S = 0.6        # seconds of anticipation along the cluster's velocity
ZONE_GAIN = 0.85    # how far toward the goalie to bias when deep
ZONE_KNEE = 10.0    # deg of play depth where the bias starts
ZONE_WIDTH = 6.0    # deg over which it ramps in -- narrow, so entry STEPS the target
# deg. This is the knob that puts the camera IN the end, and it has saturated twice: 28 pinned
# the pan 60% of the time, then 34 pinned it 31% (gain 0.60) / 54% (gain 0.85) once the ice-mask
# fix deepened the tracked centres. While it saturates, ZONE_GAIN does nothing at all -- the
# target is simply clipped. At 42 saturation is ~0%. The goalie anchors measure -42.3 / +38.4,
# so ~42 is the principled ceiling: look at the goalie, no further.
PAN_LIMIT = 42.0

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


def calibration_for(pano_path, rink=None):
    """Pick the calibration from the LiveBarn filename (or an explicit --rink), or fail loudly.

    --rink only SELECTS an existing calibration; it can never invent one. It exists because a
    stitched multi-block input loses the rink name from its filename.
    """
    if rink:
        for key, cal in CALIBRATION.items():
            if key.lower() == rink.lower():
                return key, cal
        raise SystemExit("No calibration named %r. Calibrated rinks: %s."
                         % (rink, ", ".join(CALIBRATION) or "(none)"))
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
        "If this is a stitched multi-block file, name the rink explicitly with --rink.",
    ]))


class VCam:
    """Rectilinear camera that pans about the TRUE VERTICAL. Exact map per frame."""

    def set_near_profile(self, az, phi):
        """Measured elevation of the near ice edge by azimuth (see _near_profile)."""
        self._az, self._phi = az, phi

    def __init__(self, Win, Hin, cal, ow=OW, oh=OH, near_at=NEAR_AT, mw=960):
        self.Win, self.Hin, self.ow, self.oh, self.near_at = Win, Hin, ow, oh, near_at
        self.cal = cal
        self._az = self._phi = None
        self.mw = mw
        self.mh = int(round(mw * oh / float(ow)))
        cx, cy = (self.mw - 1) / 2.0, (self.mh - 1) / 2.0
        u = np.arange(self.mw, dtype=np.float32)[None, :].repeat(self.mh, 0)
        v = np.arange(self.mh, dtype=np.float32)[:, None].repeat(self.mw, 1)
        self.du, self.dv = u - cx, v - cy
        self.ppd = Win / cal['ih_fov']

    def vfov(self, hfov):
        return 2 * math.degrees(math.atan(math.tan(math.radians(hfov) / 2) * self.oh / self.ow))

    def pitch_for(self, hfov, pan=0.0):
        """Pitch that pins the near boards at near_at of frame height AT THIS PAN ANGLE.

        The near ice edge sits at a different elevation at every azimuth -- the rink has
        rounded corners and the camera is not at centre ice, so the error is asymmetric. A
        pan-independent pitch therefore only excludes the seats near centre: measured, the
        strip grew 1.8% at pan 0 to 16.3% at pan -34. Look the elevation up from the measured
        profile, then take out the symmetric residual with SEAT_C2.
        """
        f = (self.mw / 2.0) / math.tan(math.radians(hfov) / 2.0)
        phi = (self.cal['phi_near'] if self._az is None
               else float(np.interp(pan, self._az, self._phi)))
        return (math.degrees(math.atan((self.near_at * self.mh - self.mh / 2.0) / f))
                - phi + SEAT_C2 * pan * pan)

    def fill_for(self, hfov):
        vf = self.vfov(hfov)
        return (self.cal['phi_near'] - self.cal['phi_far']) / vf, vf

    def render(self, frame, pan_deg, hfov, pitch_deg=None):
        f = (self.mw / 2.0) / math.tan(math.radians(hfov) / 2.0)
        # pitch_deg lets the caller pass a temporally smoothed pitch. Solving it per frame pins
        # the near boards exactly, but it also welds the frame's vertical position to the ZOOM:
        # on a rush the fov opens ~30 deg and the pitch tilts ~9 deg with it at up to 10 deg/s,
        # which reads as the camera bouncing. Smoothing trades a thicker seat strip -- and,
        # transiently, the near boards sitting just below the frame -- for a steady horizon.
        pitch = (self.pitch_for(hfov, pan_deg) if pitch_deg is None else pitch_deg) \
            - self.cal['rig_tilt']     # virtual tilt, less what the rig already gives
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


def _near_profile(mask, Win, Hin, ih_fov, step=8, smooth=41):
    """Elevation of the near (bottom) ice edge by azimuth, in calibrated degrees."""
    ppd = Win / ih_fov
    az, phi = [], []
    for x in range(0, Win, step):
        r = np.where(mask[:, x])[0]
        if len(r) > 30:
            az.append((x - Win / 2.0) / ppd)
            phi.append((r.max() - Hin / 2.0) / ppd)
    if len(az) < 10:
        return None, None
    phi = np.convolve(np.pad(np.array(phi), smooth // 2, mode="edge"),
                      np.ones(smooth) / smooth, mode="valid")
    return np.array(az), phi


def _follow_adaptive(tgt, fps, vbase, vrush, amax, dead, e_ref=3.0, k=5.0, c=4.4,
                     lo=-1e9, hi=1e9):
    """Pan harder the further behind it is: a sudden catch-up, then a gentle settle."""
    dt, pos, vel, out = 1.0 / fps, float(tgt[0]), 0.0, []
    for t in tgt:
        e = t - pos; ae = abs(e)
        vmax = vbase + (vrush - vbase) * min(1.0, ae / e_ref)
        if dead > 0:
            e = 0.0 if ae < dead else e - math.copysign(dead, e)
        vel = float(np.clip(vel + float(np.clip(k * e - c * vel, -amax, amax)) * dt, -vmax, vmax))
        pos = float(np.clip(pos + vel * dt, lo, hi)); out.append(pos)
    return np.array(out)


def _med1d(a, n):
    pad = np.pad(a, n // 2, mode="edge")
    return np.array([np.median(pad[i:i + n]) for i in range(len(a))])


def _ice_mask(bg, vthr=18.0, smooth_cols=201):
    """Ice = the big BRIGHT and SMOOTH region, then filled inside a smoothed boundary.

    Brightness alone leaks: the near glass is transparent, so bright ice shows through it and
    joins the ice region to the bright walkway and the first rows of seats -- spectators then
    register as skaters, which inflates the span and pulls the tracked centre to centre ice.
    Texture separates them (ice is smooth, seating/railings/people are not), but a texture mask
    also carves holes where the centre-ice logo and the painted lines are, and a player standing
    on the logo would go undetected. So texture is used only to find the BOUNDARY, which is
    smooth in x; narrow downward spikes are glass leaks and a wide median removes them. The
    region between the smoothed top and bottom is then filled solid.
    """
    f = bg.astype(np.float32)
    mu = cv2.blur(f, (15, 15))
    sd = cv2.sqrt(cv2.blur((f - mu) ** 2, (15, 15)))
    m = (((bg > 150) & (sd < vthr)).astype(np.uint8)) * 255
    band = np.zeros_like(m); band[380:900, 780:3300] = 255
    m = cv2.bitwise_and(m, band)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    _, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    core = (lab == 1 + np.argmax(st[1:, cv2.CC_STAT_AREA]))
    H, W = core.shape
    top = np.full(W, -1.0); bot = np.full(W, -1.0)
    for x in range(W):
        r = np.where(core[:, x])[0]
        if len(r):
            top[x] = r.min(); bot[x] = r.max()
    valid = bot >= 0
    ts, bs = top.copy(), bot.copy()
    ts[valid] = _med1d(top[valid], smooth_cols)
    bs[valid] = _med1d(bot[valid], smooth_cols)
    out = np.zeros_like(core, dtype=np.uint8)
    ys = np.arange(H)[:, None]
    cols = np.where(valid)[0]
    out[:, cols] = ((ys >= ts[cols][None, :]) & (ys <= bs[cols][None, :])).astype(np.uint8)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pano")
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--dur", type=float, required=True)
    ap.add_argument("--out")
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--rink", default=None,
                    help="select a calibration explicitly (for stitched files whose name "
                         "no longer carries the rink)")
    ap.add_argument("--track-every", type=int, default=3,
                    help="measure play every Nth frame (path is heavily smoothed anyway)")
    # A SHORT RENDER IS NOT A SAMPLE OF A LONG ONE. The background model, the ice mask, the
    # goalie anchors (percentiles over the tracked window) and the path smoothing are all
    # derived from whatever range is tracked, so rendering 30 s on its own produces a
    # DIFFERENT camera than the same 30 s inside a 30-minute chunk. To compare settings
    # honestly: track the whole chunk once (--dump-track), then render short clips out of it
    # (--use-track with --clip-start/--clip-dur). Tracking does not depend on any framing
    # constant, so one track serves every variant.
    ap.add_argument("--dump-track", default=None,
                    help="measure the window, write the tracking arrays there, and stop")
    ap.add_argument("--use-track", default=None,
                    help="reuse tracking arrays from --dump-track instead of measuring")
    ap.add_argument("--clip-start", type=float, default=None,
                    help="render only from here (source seconds); must sit inside the tracked window")
    ap.add_argument("--clip-dur", type=float, default=None,
                    help="how much to render from --clip-start")
    # Framing constants, exposed so an A/B costs one flag rather than an edit.
    ap.add_argument("--fov-min", type=float, default=FOV_MIN)
    ap.add_argument("--fov-max", type=float, default=FOV_MAX)
    ap.add_argument("--zone-gain", type=float, default=ZONE_GAIN)
    ap.add_argument("--zone-knee", type=float, default=ZONE_KNEE)
    ap.add_argument("--lead-s", type=float, default=LEAD_S)
    ap.add_argument("--pan-limit", type=float, default=PAN_LIMIT)
    ap.add_argument("--pitch-smooth", type=float, default=PITCH_SMOOTH_S,
                    help="seconds of gaussian smoothing on the pitch; 0 solves it exactly every "
                         "frame (pins the near boards, but bounces when the zoom moves fast)")
    a = ap.parse_args()
    if not a.out and not a.dump_track:
        raise SystemExit("--out is required unless you are only dumping a track with --dump-track")

    rink, cal = calibration_for(a.pano, a.rink)
    IH_FOV = cal['ih_fov']
    print('rink %s | ih_fov %.0f rig_tilt %.1f roll %.2f' % (rink, IH_FOV, cal['rig_tilt'], cal['roll']))

    cap = cv2.VideoCapture(a.pano)
    paz = pphi = None

    if a.use_track:
        d = np.load(a.use_track)
        if abs(float(d['start']) - a.start) > 1e-3 or abs(float(d['dur']) - a.dur) > 1e-3:
            raise SystemExit("that track was measured over start=%.3f dur=%.3f -- pass those, or "
                             "re-dump. The arrays are indexed from the tracked window, so a "
                             "mismatch silently shifts the camera."
                             % (float(d['start']), float(d['dur'])))
        fps = float(d['fps']); N = int(d['N'])
        cen, span = d['cen'], d['span']
        GL, GR = float(d['GL']), float(d['GR'])
        Win, Hin = int(d['Win']), int(d['Hin'])
        if d['paz'].size:
            paz, pphi = d['paz'], d['pphi']
        print("reusing track %s (%d frames)" % (a.use_track, N))
    else:
        fps = cap.get(cv2.CAP_PROP_FPS)
        N = int(round(a.dur * fps))

        # Background = temporal median of empty ice. Scale the sample count with duration: 24 is
        # fine for a minute, but a full game needs more to stay robust across resurfacing,
        # lighting drift and long stretches where play sits in one end.
        nbg = int(min(60, max(24, a.dur / 60.0)))
        sm = []
        for i in range(nbg):
            cap.set(cv2.CAP_PROP_POS_MSEC, (a.start + a.dur * i / nbg) * 1000)
            ok, fr = cap.read()
            if ok:
                sm.append(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY))
        bg = np.median(np.stack(sm), 0).astype(np.uint8)
        Hin, Win = bg.shape
        mask = _ice_mask(bg)
        PPD = Win / IH_FOV
        print("background from %d samples; tracking %d frames at every %d"
              % (len(sm), N, a.track_every))

        cap.set(cv2.CAP_PROP_POS_MSEC, a.start * 1000)
        idx, cen_s, span_s, gl_s, gr_s = [], [], [], [], []
        for i in range(N):
            if i % a.track_every:
                if not cap.grab():
                    break
                continue
            ok, fr = cap.read()
            if not ok:
                break
            dd = (cv2.absdiff(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY), bg) > 34).astype(np.uint8) * mask
            dd = cv2.morphologyEx(dd, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
            k, _, st, ct = cv2.connectedComponentsWithStats(dd, 8)
            ys = np.sort(np.array([(ct[j][0] - Win / 2.0) / PPD
                                   for j in range(1, k) if st[j, cv2.CC_STAT_AREA] >= 120]))
            if len(ys) >= 4:
                z = ys[1:-1]                 # drop the outermost blob each end = the two goalies
                lo, hi = z.min(), z.max()
                gl_s.append(ys[0]); gr_s.append(ys[-1])
            elif len(ys) >= 1:
                lo, hi = ys.min(), ys.max()
                gl_s.append(ys.min()); gr_s.append(ys.max())
            else:
                lo = hi = (cen_s[-1] if cen_s else 0.0)
                gl_s.append(gl_s[-1] if gl_s else -40.0); gr_s.append(gr_s[-1] if gr_s else 40.0)
            idx.append(i); cen_s.append((lo + hi) / 2.0); span_s.append(hi - lo)
        full = np.arange(N)
        cen = np.interp(full, idx, cen_s)
        span = np.interp(full, idx, span_s)
        gl = np.interp(full, idx, gl_s)
        gr = np.interp(full, idx, gr_s)
        # Goalie anchors: the outermost blob at each end, robustly. They barely move.
        GL, GR = float(np.percentile(gl_s, 20)), float(np.percentile(gr_s, 80))
        paz, pphi = _near_profile(mask.astype(bool), Win, Hin, IH_FOV)
        if paz is not None:
            print("near-edge profile: %d samples, phi_near %.2f..%.2f deg"
                  % (len(paz), pphi.min(), pphi.max()))
        if a.dump_track:
            # gl/gr are the per-frame dropped blobs. Nothing in the path uses them -- they are
            # kept because offline analysis of them is what killed the zone-span idea above,
            # and the next framing question will probably want them too.
            np.savez(a.dump_track, fps=fps, N=N, start=a.start, dur=a.dur,
                     cen=cen, span=span, gl=gl, gr=gr, GL=GL, GR=GR, Win=Win, Hin=Hin,
                     paz=(paz if paz is not None else np.array([])),
                     pphi=(pphi if pphi is not None else np.array([])))
            print("wrote track %s" % a.dump_track)
            if not a.out:
                return

    cs = _gauss(_medfilt(cen, 31), 22.0)
    vel = np.gradient(cs) * fps

    # TRIED AND REJECTED (2026-10-22): keeping the play-side outermost blob when play is deep,
    # on the theory that the dropped blob is then a skater behind the net rather than the goalie.
    # Measured on 9643: it moves the fov by 0.3 deg on the very window it was meant to fix, and
    # during deep play the dropped blob sits within 3 deg of the goalie anchor 44-54% of the
    # time with a median gap of 2.2 deg to the kept edge -- there is no clean separation to
    # exploit, which is the same reason geometric crease zones failed. Do not re-add it.
    need = np.clip(span * 1.20 + 12.0, a.fov_min, a.fov_max)
    zoom = _follow(_gauss(_medfilt(need, 31), 50.0), fps, vmax=3.0, amax=4.0, dead=0.0,
                   lo=a.fov_min, hi=a.fov_max)
    # Lead the play, then bias toward the defending goalie once it is in the zone. The ramp is
    # deliberately narrow so crossing the line STEPS the target, which is what makes the move
    # read as decisive rather than as drift.
    w = np.clip((np.abs(cs) - a.zone_knee) / ZONE_WIDTH, 0, 1) * a.zone_gain
    pan_t = cs + a.lead_s * vel + w * (np.where(cs < 0, GL, GR) - cs)
    pan = _follow_adaptive(pan_t, fps, vbase=9.0, vrush=20.0, amax=30.0, dead=1.0,
                           lo=-a.pan_limit, hi=a.pan_limit)
    pan = np.clip(pan, -(IH_FOV / 2 - 4 - zoom / 2), (IH_FOV / 2 - 4 - zoom / 2))

    vc = VCam(Win, Hin, cal)
    if paz is not None:
        vc.set_near_profile(paz, pphi)
    dz = np.diff(zoom); sg = np.sign(np.where(np.abs(dz) < 1e-6, 0, dz)); nz = sg[sg != 0]
    fl, _ = vc.fill_for(zoom.min()); fh, _ = vc.fill_for(zoom.max())
    print("fov %.0f..%.0f zone_gain %.2f zone_knee %.0f lead %.2f pan_limit %.0f"
          % (a.fov_min, a.fov_max, a.zone_gain, a.zone_knee, a.lead_s, a.pan_limit))
    print("skater span med %.1f p90 %.1f | zoom %.1f..%.1f travel %.1f reversals %d distinct %d/%d"
          % (np.median(span), np.percentile(span, 90), zoom.min(), zoom.max(), np.abs(dz).sum(),
             int((np.diff(nz) != 0).sum()) if len(nz) > 1 else 0,
             len(np.unique(np.round(zoom, 6))), len(zoom)))
    print("ice fill %.0f-%.0f%% | seats ~%.0f%% | pitch %.1f..%.1f"
          % (100 * fh, 100 * fl, 100 * (1 - NEAR_AT),
             vc.pitch_for(zoom.min()), vc.pitch_for(zoom.max())))

    # Pitch: solved per frame by default. Smoothing it decouples the frame's vertical position
    # from fast zoom moves (see VCam.render). Report what it costs rather than hiding it: where
    # the near ice edge actually lands, as a fraction of frame height. 0.97 is the design pin;
    # above 1.0 the near boards fall below the frame and a player skating them loses his skates.
    pitch_s = np.array([vc.pitch_for(zoom[i], pan[i]) for i in range(len(pan))])
    if a.pitch_smooth > 0:
        pitch_s = _gauss(pitch_s, a.pitch_smooth * fps)
        fp = (vc.mw / 2.0) / np.tan(np.radians(zoom) / 2.0)
        phi_at = (np.interp(pan, vc._az, vc._phi) if vc._az is not None
                  else np.full(len(pan), cal['phi_near']))
        na = 0.5 + (fp / vc.mh) * np.tan(np.radians(pitch_s + phi_at - SEAT_C2 * pan * pan))
        dps = np.abs(np.diff(pitch_s)) * fps
        print("pitch smoothed %.2f s: max %.1f deg/s (was %.1f) | near edge %.3f..%.3f of frame"
              % (a.pitch_smooth, dps.max(),
                 (np.abs(np.diff([vc.pitch_for(zoom[i], pan[i]) for i in range(len(pan))])) * fps).max(),
                 na.min(), na.max()))

    # Render either the whole tracked window or just a clip out of it. The clip indexes into the
    # same pan/zoom arrays, so it is exactly the footage the full render would have produced --
    # which is the entire point of comparing settings on clips.
    r_start = a.start if a.clip_start is None else a.clip_start
    r_dur = a.dur if a.clip_dur is None else a.clip_dur
    if r_start < a.start - 1e-6 or r_start + r_dur > a.start + a.dur + 1e-6:
        raise SystemExit("clip %.1f..%.1f falls outside the tracked window %.1f..%.1f"
                         % (r_start, r_start + r_dur, a.start, a.start + a.dur))
    off = int(round((r_start - a.start) * fps))
    cnt = min(int(round(r_dur * fps)), len(pan) - off)

    cap.set(cv2.CAP_PROP_POS_MSEC, r_start * 1000)
    p = subprocess.Popen(
        [FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", "%dx%d" % (OW, OH), "-r", str(fps), "-i", "-",
         "-ss", str(r_start), "-t", str(r_dur), "-i", a.pano,
         "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-preset", "medium",
         "-crf", str(a.crf), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
         "-shortest", "-movflags", "+faststart", a.out], stdin=subprocess.PIPE)
    for i in range(off, off + cnt):
        ok, fr = cap.read()
        if not ok:
            break
        p.stdin.write(vc.render(fr, pan[i], zoom[i],
                                pitch_s[i] if a.pitch_smooth > 0 else None).tobytes())
    cap.release()
    p.stdin.close()
    p.wait()
    print("wrote", a.out, "rc", p.returncode)


if __name__ == "__main__":
    main()
