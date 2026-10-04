---
name: livebarn-youtube
description: Stitch downloaded LiveBarn 30-minute hockey segments into one game video, auto-detect the game start (cut warm-up) and end (keep the handshake line), encode at YouTube's recommended quality, and upload via the YouTube API. Use when the user mentions LiveBarn, stitching game clips, hockey game video for YouTube, or trimming warm-up/handshake.
---

# LiveBarn → YouTube

All work goes through one script: `node <skill dir>/scripts/livebarn.mjs <command>`.
The skill's home is the stats repo (`mid-ice-crisis-stats/.claude/skills/livebarn-youtube/`, so it is a project skill whenever the repo is the working directory); on the user's laptop `~/.claude/skills/livebarn-youtube` is a junction to that same folder, so either path works.
Define `$LB = "$HOME\.claude\skills\livebarn-youtube\scripts\livebarn.mjs"` and use `node $LB ...` in PowerShell.
Quote every path — game folders usually contain spaces.

## Workflow (follow in order)

1. **Check tooling**: `node $LB doctor`. If ffmpeg is MISSING, run
   `powershell -ExecutionPolicy Bypass -File "$HOME\.claude\skills\livebarn-youtube\scripts\setup.ps1"`
   (downloads a static ffmpeg into the skill's `bin/`, npm-installs `googleapis`). Tell the user it is a one-time ~90 MB download.

2. **Get the segments** — `node $LB fetch --game <id>` (or `--date YYYY-MM-DD` for one of ours). Any game id on the league site works — other divisions, the C3/C4 teams, opponents — it reads the scoresheet header for date/time/rink when the game is not in `data/derived/games_index.json`. Starts at :15/:45 get a 4th safety block (`--segments 3` to skip). It maps the schedule's rink to the LiveBarn camera (`data/livebarn.json`: Rink 1 = South Rink, LiveBarn surface 3852; Rink 2 = North Rink, surface 3851), lists the three 30-minute windows (the block containing the scheduled time plus the next two), opens LiveBarn there, then watches `Downloads` and moves the segments into `~/Videos/LiveBarn/<date> <rink>` once they've finished (`--then detect` runs detection straight away). The user still clicks Download on each segment — LiveBarn has no public API, its sign-in is captcha-gated, and its terms forbid automated downloading, so **do not try to script the download itself or extract its auth secrets** (an investigation on 2026-09-19 confirmed this is the line). If a rink is missing from `data/livebarn.json`, add it (file_prefix = how LiveBarn names that camera's downloads). Filling in a rink's `surface_id` (the number in a `watch.livebarn.com/en/video/<id>/...` URL) makes `fetch` open the exact camera and time.
   If the user already has the files, just ask where they are.

3. **Identify the game**: `node $LB whichgame "<folder>"` — resolves the camera and block times from the LiveBarn filenames and matches them to the league schedule, so the game id comes from the tape rather than from memory. It also separates the panoramic from the auto-follow segments (same naming, timestamps within a second; told apart by width) and warns if both are in one folder. Everything downstream — the cut, the description, the anchors — must be read against this game's scoresheet.

4. **Probe**: `node $LB probe "<folder>"`. Segments are ordered by filename (natural sort — LiveBarn names carry the timestamp). Show the table; if the order looks wrong (files with odd names), pass the files explicitly in the right order instead of the folder.

5. **Detect the cut**: `node $LB detect "<folder>"`. Takes a few minutes (decodes all audio, then samples video motion around the horns).
   - It classifies loud tonal events as **horn** (100–1500 Hz, ≥0.6 s) or **whistle**. Proposed start = end of the first horn (end of warm-up), refined forward to the first sustained play if the ice visibly empties first. Proposed end = last horn + the handshake line, cut when motion on the ice collapses (60 s min, 5 min max after the horn; falls back to +3:00).
   - **Always show the user the horn list and the proposed start/end and ask them to confirm or adjust** before building. Point out any `note:` lines (e.g. too many horns → a goal horn or the next game's warm-up may have been picked as "last horn"; in that case pick the right horn from the list yourself and propose that).
   - **No usable audio** (about half of this user's games — the rink's north camera has an audio problem): the script says so. Then run `node $LB sheet "<folder>"` which writes `<segment>_sheet.png` next to each file (one thumbnail per minute, timestamp burned in, 6 per row) and ask the user for the start and end. Accept times as `H:MM:SS` on the stitched timeline or `N@MM:SS` (file number @ time within that file) — both are passed straight to `--start/--end`. Offer `--every 30` for finer sheets.
   - Even when audio works, `sheet` is a good way for the user to sanity-check a proposed cut.

6. **Build**: `node $LB build "<folder>" --start <T> --end <T>`. Output defaults to `<folder>\<folder name>_youtube.mp4`. Run it in the background (it is a full re-encode: with the default `libx264 -preset medium` on this i7-6700HQ expect roughly real-time to 1.5× real-time, i.e. 60–100 min for a 75-min game) and report when done. Options:
   - `--preset slow` — a bit better quality per bit, ~2× slower.
   - `--encoder nvenc` — GPU (GTX 960M), 3–5× faster but softer image; falls back to x264 automatically if NVENC fails. As of Sep 2026 it fails on this laptop ("Cannot load cuMemAllocAsync": the NVIDIA driver is too old for ffmpeg 9). Updating the GeForce driver should enable it; only worth it if the user asks for speed.
   - `--boost` — upscale to 2560×1440. YouTube gives ≥1440p uploads its VP9/higher-bitrate ladder, which is the single most effective fix for "the video looks blurry on YouTube". Encode takes ~1.8× longer and the file is ~1.7× bigger. Offer this if quality complaints persist after a normal 1080p upload.
   - `--dry-run` prints the ffmpeg command without running it.
   - Encoding settings follow YouTube's upload recommendations: H.264 High, yuv420p, CRF 17 capped at 24 Mbps (40 Mbps with `--boost`), closed GOP of half the frame rate, 2 B-frames, source frame rate kept (CFR), AAC-LC 384 kbps 48 kHz, `faststart`. Sources below 1080p are upscaled with Lanczos + light unsharp.
   - If any segment lacks an audio track the output is built without audio (mixed audio/no-audio segments cannot be concatenated in sync). Tell the user.
   - **Audio is rebuilt from the sample count, not the container timestamps.** LiveBarn segments carry garbage audio PTS (thousands of repeated/backwards timestamps per file) while the samples are complete; trusting them makes AAC drop/repeat frames — the "choppy audio" the user used to fix with HandBrake. `build` uses `asetpts=N/SR/TB` + filter-graph trims and pins each segment's concat offset to its video length. Verified: output audio correlates 1.00 with the source with 0–3 ms lag across seams, no dup/drop frames.

7. **Upload** (user asked for this): `node $LB upload "<file>" --title "..." [--desc "..." | --desc-file notes.txt] [--tags a,b] [--privacy unlisted|private|public] [--playlist <id>|none] [--refresh]`.
   - The video is added to the team's game-film playlist by default (the id comes from `data/franchises.json`'s `youtube_playlist_id`); the dashboard only ever sees videos in that playlist. `--playlist none` opts out.
   - Ask for the title (and privacy, default `unlisted`) before uploading; don't invent a title.
   - First run needs `%LOCALAPPDATA%\livebarn-youtube\secrets\client_secret.json` (see setup below) and opens a browser for Google sign-in once; the token is cached next to it as `token.json`. Credentials deliberately live outside the skill/repo folder.
   - Print the `https://youtu.be/<id>` link back. YouTube's own processing of a 1080p/1440p upload takes a while — HD renditions appear some minutes after the upload finishes.

## Title + description from the stats repo (and re-syncing after corrections)

The team's stats live in `C:\Users\alban\code\mid-ice-crisis-stats` (see its README). Two commands turn that data into the video's text and keep it current:

- **Games that aren't in the dashboard data** (another division, the C3/C4 teams): `describe --game <id> --us "<Team Name>"` pulls the scoresheet from the league site via `scripts/boxscore_json.py` (needs the local Python) — scoring summary, penalties, game notes and notes.txt work; standings, +/- and leaders don't exist for it. These games get their own playlists: `playlist list`, `playlist create "<title>"`, then `upload --playlist <id>`. Existing: Globo Gym King Cobras C3U = `PLHaXYMurzneY`, Skateful Dead = `PLHXbcn4qN9w4`; the Mid Ice Crisis one is in `data/franchises.json`. Don't `link`/`film` these — the dashboard only tracks our division.
- `node $LB describe "<game folder>" --game <id>` (or `--date YYYY-MM-DD`; if two games that day it lists them and asks for `--game`). It `git pull`s the repo, then writes `youtube-title.txt` and `youtube-description.txt` into the game folder: scoring summary with running score (corrected goals marked `*`), penalties, standings context, GAME NOTES (only the rule-based insights that are true: multi-goal games, PP goal timing, GWG, ties, discipline vs season average, season series / all-time H2H), **+/- for this game when its goals are on-ice tagged** (same NHL rules as the repo: PP goals move nobody; coverage shown), season +/- totals, scoring leaders, site link, hashtags.
- `notes.txt` in the game folder is the hand-written narrative ("THE STORY"). It is inserted verbatim on every regeneration, so write the juicy stuff there, never into `youtube-description.txt` (that file is overwritten each time). Offer to draft `notes.txt` from the data, then let the user edit it.
- `youtube-title.txt` is generated once and then kept (the user may have tuned it); `--force-title` regenerates it.
- `node $LB update <videoId|url> --dir "<game folder>"` pushes the title + description to the existing video. **It is a full rewrite of the description, never an append.** `--dry-run` shows what would be sent; `--privacy public` can flip visibility at the same time. Costs ~50 quota units, so it can be run freely.

### Goal and penalty deep links (the ▶ stamps and the YouTube chapters)

`describe` puts a `▶ m:ss` on each goal line in SCORING SUMMARY and on each PENALTIES line, and emits a `CHAPTERS` block (`0:00 Puck drop`, then one ascending line per goal) that YouTube renders as a clickable chapter list on the scrubber.

- **Every published link is backdated 20 seconds** — `LEAD_IN_S` in the repo's `scripts/film_sync.py`. An anchor records the instant the puck crossed the line (that is what the tagging form asks for), but `video_t` is where playback *starts*, so the link opens on the play that produced the goal rather than on the celebration, and on the infraction rather than on the player already sitting in the box. The subtraction happens **once**, inside `film_sync.py`, and is already baked into `video_t` in `data/derived/film_sync.json`. `describe` reads `video_t` as-is and must never subtract again — doing so would double it to 40 s. (Verified on game 8786: raw anchor 162 s → published 142 s, exactly 20 s on all 8 goals and all 8 penalties.)
- **Only hand-keyed anchors (`method: "manual"`) are published.** The scoreboard analysis's own timings (`method: "estimate"`, backed off by `EST_LEAD_IN_S = 75` since a guess is coarse and the goal should still be ahead of the viewer) are deliberately excluded from the description: on game 8786 they were out by up to 67 s, and on 8750 one landed at 51:55 while the board still read 8:40 left in the period. They are good enough for the dashboard's ▶ button, not for a published chapter list.
- **Penalties are anchor-only and never estimated** — nothing on the board changes when a penalty is called, so no anchor means no link.
- Anchors live in `data/film_anchors/<game_id>.json` (`by_goal` / `by_penalty`, keyed by team + period + the scoresheet's time), not written by `film`. **Goal** anchors have a UI: the box score's on-ice tag form takes a `mm:ss` video time, which opens a GitHub issue that `process-on-ice-issue.yml` turns into a `by_goal` entry. **Penalty** anchors have none — nothing writes `by_penalty`, so they are hand-edited into that JSON and committed. Both kinds of time are produced by the clock-freeze procedure in *Exact goal + penalty times* below, which is the only method that has ever placed a penalty accurately. As of Oct 2026 only 7 of 28 games have any anchors, and only 8786 and 9634 have penalty ones.
- **All-or-nothing guard**: read in scoresheet order the manual anchors must ascend, or *none* are published for that game (`trustedGoals` in `scripts/describe.mjs`). An empty chapter list on a game you know you tagged means one anchor is mistimed, not that the data is missing.
- Practical consequence for the order of work: `film` does **not** produce publishable links, so a fresh upload ships without chapters. Run build → upload → `link` → `film` → key the anchors on the box score → `describe` → `update`. `update` is a cheap (~50 unit) full rewrite, so re-running it once the anchors exist is the normal path, not a correction.

**After a stat correction or new +/- tags** (the repo's GitHub workflows commit those): run `describe` (pulls) then `update`. That is the whole loop. Use `--no-pull` only when offline.

Typical new-game flow: build → `describe --game <id>` → upload (`--title-file youtube-title.txt --desc-file youtube-description.txt`) → **`link <videoId>`** → **`film <videoId> <master.mp4>`** → `refresh --wait` → **key the anchors** (goals: the box score's on-ice tag form, with the video time in `mm:ss`; penalties: hand-edit `by_penalty` in `data/film_anchors/<id>.json`) — see *Exact goal + penalty times* for how the times are actually derived → `describe` again → `update` → `refresh`. The last four steps are what put the `▶` stamps and the YouTube chapter list into the description; skip them and the video is published without chapters, since `film`'s own timings are estimates and are never published (see *Goal and penalty deep links* above). The game id is in `data/derived/games_index.json` (`game_id`, `iso_date`); the video id comes back from `upload`. If you uploaded with a hand-written description instead, follow with `describe` → `update`, then `link`.

## Linking the video to the dashboard and timestamping the goals (laptop-side, since Sep 2026)

YouTube bot-blocks GitHub's runner: the nightly scrape gets an empty description for a new upload and `yt-dlp` can't download for film sync. The laptop is not blocked, so two commands hand the repo what the runner can't fetch, as data commits pushed straight to `main` (the same way the tag/correction workflows commit):

- `node $LB link <videoId>` — reads the description (must contain `Game #<id>`, which `describe` writes) and duration via the Data API, writes `data/raw/youtube/<id>.json` + `data/raw/film/durations.json`, pushes. This is what makes the box score's ▶ button point at the video.
- `node $LB film <videoId> "<game folder>\<name>_youtube.mp4"` — runs the repo's `scripts/film_sync.py` on the local master (`--local-file`), i.e. the scoreboard analysis that estimates a video time for every goal (`method: "estimate"`, each backed off by `EST_LEAD_IN_S = 75`). Prints each goal's video time; commits `data/raw/film/<id>.json` + `data/derived/film_sync.json`; pushes. **Sanity-check the output**: goal times must be in game order and minutes apart — if the board was "seen" in fewer than ~20% of samples or the times are bunched together, the rink's scoreboard probably has no template yet: crop one into `data/film/templates/<rink>.png` with a `<rink>.json` giving `score_boxes` (fractions of the crop where the two red score digits sit) and `min_match`, then re-run. Existing: `seatgeek_rink`, `south_rink` (Baptist Health IcePlex). These estimates drive the dashboard's ▶ button only; they are **not** published as description links or chapters (see *Goal and penalty deep links* above) — that needs hand-keyed anchors from the clock-freeze procedure below.
- Then `refresh --wait` publishes both. Needs Python 3.12 with `pip install -r requirements-film.txt` (python.org installer; `winget` is not on this laptop) — `film` finds it under `%LOCALAPPDATA%\Programs\Python`.


## Linking the video to the dashboard (how the sync works, and `refresh`)

The dashboard never stores video ids by hand. Its nightly workflow (`.github/workflows/refresh-data.yml`, 12:30 AM Eastern) runs `scripts/scrape.py`, which

1. reads the **game-film playlist** page (`youtube_playlist_id` in `data/franchises.json`) -- a video not in that playlist is invisible to it;
2. fetches each new video's **description** once (cached in `data/raw/youtube/<video_id>.json`; never re-read) and takes the game id from the first `Game #<id>` it finds (`scripts/lib/youtube_client.py`, `GAME_ID_RE`);
3. writes `data/raw/youtube_videos.json` (`video_id` → `game_id`), which `build_site_data.py` uses for the ▶ film links and `film_sync.py` uses to find the goal timestamps (one ~10 min download+decode per new video, max 2 per run).

So the two things a video needs are: **in the playlist** (`upload` does this by default) and **`Game #<id>` in its description** (`describe` writes it on the first line -- do not delete it; if the user hand-writes a description, make sure it contains `Game #<id>`).

`node $LB refresh [--wait]` fires that workflow right away via `gh workflow run refresh-data.yml` (GitHub CLI must be logged in: `gh auth status`), so the video shows up on the dashboard within ~15 minutes instead of the next morning. `--wait` streams the run and reports when it finished. `upload --refresh` and `update --refresh` do the same as a final step. Since the description is cached after the first scrape, get `Game #<id>` right **before** the first refresh; if a video was scraped with a wrong/missing id, delete `data/raw/youtube/<video_id>.json` in the repo, commit, and refresh again.

## One-time YouTube API setup (tell the user if `doctor` shows client_secret.json MISSING)

1. console.cloud.google.com → create/select a project → **APIs & Services → Library → YouTube Data API v3 → Enable**.
2. **Google Auth Platform → Branding**: app name, support email, developer contact email, plus a home page URL and privacy policy URL (the stats site `https://albano-insights.github.io/mid-ice-crisis-stats/` works for both). Audience: External.
3. **Audience → Publish app** (unverified is fine). Do not rely on *Test users*: adding the owner's Gmail fails with "ineligible account", and Testing mode expires the login every 7 days.
4. **Credentials → Create credentials → OAuth client ID → Desktop app** → Download JSON.
5. Save it as `%LOCALAPPDATA%\livebarn-youtube\secrets\client_secret.json` (i.e. `C:\Users\<you>\AppData\Local\livebarn-youtube\secrets\`).
The first login shows "Google hasn't verified this app" → **Advanced → Go to LiveBarn Uploads** → allow. The token is cached afterwards. (Already done on this machine as of Sep 2026.)
The default quota (10,000 units/day) allows ~6 uploads per day (1,600 units each).


## Exact goal + penalty times: the clock-freeze method on the panoramic board

This is how every published `▶` link and chapter actually gets made. It is a **hand-run procedure
with model vision in the loop, not a script** — nothing in the repo automates it yet. It has been
done end to end once (game 9634, Skateful Dead, 4/4 goals and 10/10 penalties verified) and it is
the only method that has ever produced trustworthy penalty times. Read this before proposing
anything else; the obvious alternatives below have each been tried and have each failed.

**Why not the automatic path.** `film_sync.py` watches the *score* digits on the auto-follow master
and never reads the clock, because on that feed the camera pans and zooms, so the board matches at a
different scale every frame and the clock digits are ~14 px — unreadable. That produces phantom
score changes and timings out by up to 67 s. Those are the `method: "estimate"` entries, fine for
the dashboard's `~▶` button and never published to a description. A penalty changes nothing on the
board, so the automatic path cannot place one at all, at any accuracy.

**Why the panoramic works.** The pano feed is 4080×1360 and the camera is *provably* static —
sampled across 24 minutes, horizontal and vertical offset were 0 px every time, alignment
confidence 0.98–1.00. So the board sits in identical pixels all game: one crop, no rescaling, no
re-matching. On the south rink pano the board is at **x=646, y=406, 145×52**, and at that size the
clock, period and both scores are plainly legible. Cache that strip once per segment and reading
becomes nearly free.

### Step 0 — resolve the game from the filenames, and read everything against that scoresheet

Every time below is only meaningful against the scoresheet of the game actually on the tape, so
establish which game that is **from the files themselves** before reading a single frame:

```
node $LB whichgame "<folder>"
```

LiveBarn names each download `<venue>_<surface>_<YYYY-MM-DD>T<HHMMSS>.mp4`, which carries the camera
and the block's real start (a few seconds before the half hour — `22:29:56` is the `22:30` block).
`data/livebarn.json` maps that camera back to the schedule's rink name, so camera + block times are
enough to find the game in `data/derived/games_index.json`: the first downloaded block is the one
containing the scheduled start, so a real match starts inside it. Verified against three games on
disk — 9/26 → 8786, 9/17 → 8750 (correctly rolling past midnight), 9/03 → 8627 (a 9:15 PM start
inside the 21:00 block).

Then take the goal and penalty times — period and clock — from **that** game's scoresheet, and treat
them as the targets the clock-freeze search has to hit. Do not work from a recollection of the game.

- **A game that isn't ours** (another division, the C3/C4 teams) is not in `games_index.json`, so
  `whichgame` says so rather than guessing. Its id is only on the league site; pass `--game <id>` and
  confirm the scoresheet header's date/time/rink against the block times `whichgame` printed. That is
  the case for game 9634, the one this whole procedure was proven on.
- **Never tell the feeds apart by filename.** A block's panoramic and auto-follow downloads are named
  the same way and their timestamps are at best a second apart: on 2026-09-27 they were identical
  (`T215956` for both), while on 2026-10-03 the panoramic arrived a second earlier (`T205954` against
  `T205955`). Size is no guide either — the panoramic was the *smaller* file on 9/27 (789 MB vs 880 MB)
  and the *larger* one on 10/03 (923 MB vs 789 MB). `whichgame` classifies by **width** (≥3000 px is
  panoramic), the only stable signal. When the names do collide the browser renames the second
  `" (1)"`, which breaks the natural sort `probe`/`build` depend on and leaves a file whose block
  cannot be parsed.
  Keep the panoramic in its own `<date> <rink> pano` folder; `whichgame` warns when it sees both.

### Step 1 — measure the offset between the two feeds (never infer it)

Times are read on the pano but must land on the auto-follow master's timeline.

- **Do not trust the filenames.** On 2026-09-27 both feeds were named `T215956`, implying a zero
  offset; the true offset was **5.88 s**, the pano running ahead. Assuming zero would have put every
  link ~6 s late — opening on the celebration instead of the shot, and subtle enough to ship
  unnoticed. (On the Sep 19 games the filenames differed by 2 s, so they are not merely imprecise.)
- **Use audio cross-correlation**, not motion. Motion was the wrong tool and said so: r = 0.24, no
  peak, because the auto-follow camera's frame differences track the camera, not the play. Audio
  gave r = 0.987, with the five loudest events landing 5.88 s apart to the centisecond.
- Then, with `cut_start` the `--start` used for `build` and `pano_lead` the measured amount the pano
  runs ahead:

  ```
  t_master = t_pano − (cut_start − pano_lead)
  ```

  Worked example, game 9634: `1005 − 5.88` → `t_master = t_pano − 999.12`.

### Step 2 — find each event by where the clock freezes

This league plays stop time, so **the clock stops when play stops**. A goal or a penalty is a
whistle, so the scoresheet's time appears on the board as the moment the clock *freezes* at it.
Sample the board strip around the expected region and find that freeze.

Sampling is coarser than a second, so interpolate from how much clock elapsed across the gap:

- Klein, 2nd 5:54 — clock ran 6:41→5:59 across pano 3150–3192, then froze at 5:54 by 3198: 5 s of
  clock across 6 s of video, so the freeze was ~1 s early → pano ≈3197 → **master 2198** ✓
- the 2:10 double minor — 2:14 at pano 3516, 2:10 at 3522: 4 s of clock across 6 s of video → pano
  ≈3520 → **master 2521** ✓

### Step 3 — verify every time against the master, and weight the evidence correctly

Pull the frame at the computed `t_master` and confirm. The strongest confirmation available is the
board being readable *in the master itself*: on game 9634's third goal it read Bandits 1, Skateful 0
with 17.0 left in the 1st — exactly the clock predicted from the pano, with players clustered at the
net and spectators' arms up.

**The clock freeze is the reliable signal; what the play looks like is corroboration at best.** One
penalty (Kagan, 1st 4:46) was nearly discarded because the frame "looked like live play" — that read
was simply wrong, since at the instant of a whistle players are still spread out mid-stride. Do not
treat a visual impression as evidence against a clean clock freeze.

### Step 4 — write the anchors

Write every confirmed time into `data/film_anchors/<game_id>.json` as `by_goal` / `by_penalty`
entries, keyed by team + period + the scoresheet's time, with `video_t` in **master seconds**:

```json
"by_goal":    [{ "team": "away", "period": "1", "time": "13:25", "video_t": 63 }],
"by_penalty": [{ "team": "home", "period": "2", "time": "5:54",  "video_t": 2198 }]
```

`video_t` is the instant of the event — `film_sync.py` subtracts `LEAD_IN_S = 20` itself, so do
**not** pre-subtract. These become `method: "manual"`, the only kind `describe` publishes. Then
`describe` → `update`. League-site games (outside our division) read film data too since `dec267b`.

**Not yet built, and worth building:** the mechanical parts of this — audio offset measurement and
dumping a per-segment board strip — are scriptable; only the digit reading needs vision. Until then
budget roughly one board-strip lookup per event, and note that a penalty anchor has no UI at all,
so this procedure is the *only* way penalty links ever get made.

## Territorial / pressure analysis (the panoramic feed)

LiveBarn has a second feed per surface: a **panoramic** 4080x1360 camera that never moves. Keep publishing the auto-follow feed — it is what people want to watch — but for analysis have the user also download the panoramic block, because the auto-follow camera pans and zooms so nothing can be measured from it.

- `python scripts/pano_flow.py <panoramic.mp4> --out flow.json` — one pass over the segment, writing per-second player positions (empty-rink background model + flood-filled ice mask). ~5 min per 30-minute segment.
- `python scripts/pano_report.py flow.json` — live play vs stoppages, how tightly players bunch, zone split, sustained-pressure spells.

Needs the local Python (`pip install -r requirements-film.txt`). **Bound the window to actual play** before quoting numbers — warm-up and the post-game handshake both sit at centre ice and distort the split; use the same start/end you used for `build`.

Two limits to state plainly rather than paper over: output is **left end / right end, not per team** (goalies are found, but both jerseys average to grey at this distance — one known goal time would fix it), and play location is the **median skater position, not the puck** (four pixels, untrackable), so it is least reliable during line changes and neutral-zone play.

## Notes / troubleshooting

- Detection heuristics are tuned for hockey (warm-up horn → game → final horn → handshake line). They are a proposal, not ground truth — always confirm with the user.
- If the recording started after warm-up, the "first horn" will be the end of period 1; the script warns when the first horn is inside the first minute. Use `--start 0` or a manual time.
- If the last segment includes the next game's warm-up horn, the wrong "last horn" gets picked; choose the correct one from the printed list.
- `--handshake-max 420` extends the window for long handshake lines / team photos; `--start-offset -30` (or positive) shifts the start.
- `livebarn-detect.json` is written into the game folder with all events and the proposal.
- The build prints `could not seek to position ...` from the concat demuxer. It is harmless — ffmpeg decodes from the start and discards frames up to `--start`; the cut has been verified accurate to the second.
- Never delete the user's source segments.
