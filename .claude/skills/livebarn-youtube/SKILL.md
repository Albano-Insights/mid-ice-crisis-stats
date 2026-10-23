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

2. **Get the segments** — `node $LB fetch --game <id>` (or `--date YYYY-MM-DD` for one of ours). Any game id on the league site works — other divisions, the C3/C4 teams, opponents — it reads the scoresheet header for date/time/rink when the game is not in `data/derived/games_index.json`. Starts at :15/:45 get a 4th safety block (`--segments 3` to skip) — but **think before buying it**: LiveBarn download minutes are a capped monthly budget (1800/month on this user's plan) and a block is 30 of them. Three blocks were ample for a `:45` start on game 8846: the game ran 22:45→23:44 and the buzzer landed with **16 minutes of tape to spare**. The 4th block is only really earned by a **D1 stop-time** game on a `:15`/`:45` start, which runs ~82 min gate-to-gate (8818) against ~77 min for running-clock C3U. More importantly, **LiveBarn retains footage for days** — 8846 was downloaded three days after it was played — so the safety block never has to be bought up front. Download three, confirm the buzzer is in the last block, and only then buy a fourth. It maps the schedule's rink to the LiveBarn camera (`data/livebarn.json`: Rink 1 = South Rink, LiveBarn surface 3852; Rink 2 = North Rink, surface 3851), lists the three 30-minute windows (the block containing the scheduled time plus the next two), opens LiveBarn there, then watches `Downloads` and moves the segments into `~/Videos/LiveBarn/<date> <rink>` once they've finished (`--then detect` runs detection straight away). The user still clicks Download on each segment — LiveBarn has no public API, its sign-in is captcha-gated, and its terms forbid automated downloading, so **do not try to script the download itself or extract its auth secrets** (an investigation on 2026-09-19 confirmed this is the line). If a rink is missing from `data/livebarn.json`, add it (file_prefix = how LiveBarn names that camera's downloads). Filling in a rink's `surface_id` (the number in a `watch.livebarn.com/en/video/<id>/...` URL) makes `fetch` open the exact camera and time.
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
   - **1440p is the default.** `build` upscales to 2560×1440 unless you pass `--no-boost`.
     The source is 1080p so this adds no real detail, but YouTube gives ≥1440p uploads its
     VP9 / higher-bitrate ladder instead of AVC, and that is the single most effective fix for
     "the video looks blurry on YouTube" — the master is not sharper, the delivered stream is.
     Costs ~1.8× the encode time and ~1.7× the file size. Use `--no-boost` only when the extra
     hours matter more than the playback quality.
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
re-matching. On the south rink pano the board is at **`crop=300:130:3170:330`** (w:h:x:y), and at
that size the clock, period, both scores and the penalty countdown are legible once scaled up ~1.3×.
Cache that strip once per segment and reading becomes nearly free.

> **The board is on the right-hand wall, under the "Baptist Health RINK" sign.** An earlier version
> of this file put it at `x=646, y=406, 145×52` (and a variant crop `330:210:595:375`). **That is the
> Panthers ad videoboard on the *opposite* wall**, which cycles through advertising all game and
> never shows a clock — on 2026-10-07 it was showing a "PAHL" promo at every sample, which reads as
> random wall art and wasted a chunk of the session. Verified correct on game 8846 across all three
> blocks. If a crop comes back showing ads or masonry, you are on the wrong wall — dump a full frame
> scaled to 1632×544 and find the board before sampling anything else.

**The fastest way to map a game is one tiled board sheet per 30-minute block**, then a fine sweep
only around each event:

```
ffmpeg -i <pano block>.mp4 -vf "fps=1/60,crop=300:130:3170:330,scale=400:173,\
drawtext=text='%{eif\:n\:d}':x=4:y=4:fontsize=30:fontcolor=yellow:box=1:boxcolor=black@0.8,tile=5x6" \
  -frames:v 1 sheet.png
```

That is 30 board readings per block in one image and one decode — enough to place the warm-up
countdown, the opening faceoff, every goal to ±30 s and the final buzzer. Then re-sample at 5 s
around each event to pin it. **Do not trust a coarse 60 s reading of a goal**: on 8846 a tile read as
"3:06, score 0-2" was actually 3:35 at 0-1, and the real freeze was 29 s later. Every anchor must come
off a 5 s sweep.

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


### Always confirm the proposed cut against the board — `detect` gets it wrong at this rink

At Baptist Health IcePlex South Rink the **buzzer is not reliably picked up by the audio
classifier**, so `detect`'s proposal can be confidently wrong in both directions. On game 8818
(2026-10-03) it produced no `horn` event for either the warm-up-end buzzer or the final buzzer, and
so:

- it took the **first goal horn** (0:17:21) for the warm-up horn and proposed a start of 0:18:26 —
  **5:49 late, cutting off the opening minutes and the game's first goal**;
- it took a **post-game horn** (1:22:37, after the board had already reverted to the time of day) for
  the final horn and proposed an end of 1:24:19, about 50 s of empty ice.

The tell is in the event list: between the whistles at 0:09:12 and the horn at 0:17:21 there was no
horn at all, yet whistles mean play has started. **Whistles before the "first horn" mean the horn is
not the warm-up horn.** Read the panoramic board rather than arguing with the audio.

Reading the board settled it in a few frames (crop `300:130:3170:330` on the 4080×1360 south-rink
pano): faceoff **0:15:31**, final buzzer **≈1:21:27**, handshake done by **1:23:00**. Cut used:
`--start 0:15:20 --end 1:23:10`.

**It happened again, worse, on game 8846 (2026-10-07).** `detect` proposed `--start 0:20:12 --end
1:30:00`, i.e. it ran the cut to the literal end of the tape, **12½ minutes past the final buzzer**.
It had locked onto a cluster of **low-frequency horns (188–336 Hz) at 1:25:35–1:27:19 belonging to
the next game's warm-up**, and reported `Could not see the ice empty; end = final horn + 3:00`. The
board put the real buzzer at **1:14:08**. Two tells worth internalising:

- **A "could not see the ice empty" note plus a proposed end at or near the tape end is a failure,
  not a cut.** Check the board before believing it.
- **The next game's warm-up horns are much lower in pitch than the game buzzer** — 188–336 Hz against
  641–797 Hz for the real horns in the same game. When the horn list ends in a tight cluster of
  sub-400 Hz events, those are the next game, not yours.
- The cheapest confirmation of all: the board **reverts to time of day and date** (`11:45 OCT 7TH
  WEDNESDAY`) within a minute of the buzzer. One board sheet of the last block shows exactly where
  the game stopped being a game.

**Board states that are easy to misread:**

- **Before the game** the board runs a **warm-up countdown** — seconds with tenths (`40.7`) and *no*
  period label. It is not a game clock.
- **Between the countdown and the opening faceoff** the board shows the period clock **parked at its
  full value with the period label already lit** (`14:00  1ST`). A stopped clock is not a started
  game: on 8818 it read `14:00 1ST` from 12:50 through 15:00 while the teams were still lining up.
  Two identical readings a minute apart mean the clock is stopped, which is the single cheapest
  check available.
- **After the final buzzer** the board reverts to the **time of day and date** (`Saturday Oct 3rd
  10:22`), which reads like a clock and is not one.

**Periods in this league are 14:00, not 15:00.** Verified twice on 8818 — the board parks at `14:00
1ST` before the opening faceoff and at `14:00 2ND` at the start of the second. Note that
`scripts/film_sync.py` hard-codes `PERIOD_LEN_S = 15 * 60`, so its `_elapsed_s` and the learned clock
model are skewed for every game here; that only affects `estimate` timings, which are never
published, but it should be fixed before anyone trusts an estimate.

### Step 1 — measure the offset between the two feeds (never infer it)

Times are read on the pano but must land on the auto-follow master's timeline.

- **Do not trust the filenames.** On 2026-09-27 both feeds were named `T215956`, implying a zero
  offset; the true offset was **5.88 s**, the pano running ahead. Assuming zero would have put every
  link ~6 s late — opening on the celebration instead of the shot, and subtle enough to ship
  unnoticed. (On the Sep 19 games the filenames differed by 2 s, so they are not merely imprecise.)
  **The filenames can even get the *sign* wrong.** On 2026-10-07 the pano was named `T222953` and the
  auto-follow `T222958`, implying the pano led by 5 s; measurement said the pano started **7.02 s
  after** the auto-follow (r = 0.977, neighbouring lags falling to 0.68). That is a 12 s error in the
  wrong direction — enough to put every published link on the wrong side of the play. Measure every
  time; never reason from the names, not even for the sign.
- **A usable envelope correlation needs no scipy.** 180 s of mono 8 kHz audio from each feed, a
  100 Hz absolute-value energy envelope, z-scored, FFT cross-correlated, restricted to ±30 s, gives a
  peak sharp enough to read to the centisecond. Python 3.12 with numpy alone is enough
  (`%LOCALAPPDATA%\Programs\Python\Python312`).
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

**Check which clock the division runs before assuming anything.** The two are not the same and the
method differs:

- **D1 (Mid Ice Crisis) plays stop time** — the clock stops on every whistle, so both goals *and*
  penalties show up as a freeze at the scoresheet value. Periods are 14:00.
- **C3 Upper (Globo Gym) plays a largely running clock** — verified on game 8846 at exactly 1 s of
  clock per 1 s of video across all three periods. It stops **only for goals**, not for penalties.
  Periods are also 14:00. C4 (Skateful Dead) has not been checked; verify before relying on either.

So on a running-clock game a **goal** is still a freeze (and the score digits flip 5–15 s later —
on 8846 the gap ran 5 s to 11 s), but a **penalty** never freezes anything. Read a penalty off the
running clock instead, and cross-check it against the **penalty countdown**, which ticks down in
lockstep with the game clock and is the single best confirmation available: on 8846 the board read
`9:54` with `28  1:47` left, and 2:00 − 1:47 = 13 s back up the clock gives 10:07, the scoresheet
time to the second. The countdown also tells you when a goal was *not* on the power play — Arroyo's
minor expired at 8:07 and the goal landed at 8:06, one second after, correctly unmarked `PP`.

Sample the board strip around the expected region and find the freeze (or, for a running clock, the
exact reading).

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

## Deriving our own auto-pan from the panoramic feed (`scripts/pano_autopan.py`)

LiveBarn bills download minutes **per feed**, so publishing a game today costs two buys
(auto-follow + panoramic) = 180 min against a 1800 min/month cap. `scripts/pano_autopan.py`
renders a broadcast-style 1080p pan **out of the panoramic feed alone**, so one 90-min buy
covers both the published video and the scoreboard/anchor work.

```
python scripts/pano_autopan.py "<pano segment>.mp4" --start <s> --dur <s> --out out.mp4
```

Validated against LiveBarn's own auto-follow on game 8846: the derived pan is tighter
(players noticeably larger, jersey numbers legible), geometrically straighter, and level.

**How it frames.** Track play by background subtraction inside an auto-derived ice mask, then
frame on the **goalie-excluded** skater span -- drop the outermost blob at each end. That one
choice is what makes everything else work:

| framing target | median span | what it costs |
|---|---|---|
| all players | 81.6 deg | forces ~95 deg fov, no better than LiveBarn |
| p5..p95 | 53.0 deg | still too wide |
| **drop the goalie each end** | **40.0 deg** | camera lives near 60 deg -> 99.9% of skaters in frame |

Geometric crease zones were tried for goalie detection and failed (occupancy peaks only
0.38 / 0.25, and a deep forechecker stands where a goalie stands). Dropping the outermost blob
is cruder and far more robust.

**The ice mask must exclude the seats, and brightness alone does not.** The near glass is
transparent, so bright ice shows through it and joins the ice region to the bright walkway
behind it and then to the first rows of seating -- spectators then register as skaters. Measured
on game 9643: one frame carried 26 "players", five of them sitting in the stands, which
stretched the span to 83.1 deg and put the tracked centre at -3.6 deg (centre ice) while play
was in fact in the left end. So the camera framed the whole rink AND the zone bias never fired,
because |centre| never approached ZONE_KNEE. Both complaints -- "too wide" and "not enough bias
for the end play" -- were this one bug. Fixed by requiring ice to be bright AND smooth (seating,
railings and people are textured), using that only to find the BOUNDARY, which is smooth in x so
narrow downward spikes are glass leaks that a wide median removes, then filling solid between the
smoothed top and bottom -- a texture mask used directly carves holes at the centre-ice logo and
the painted lines, where a player would go undetected. Same frame after: 15 blobs, span 23.4 deg,
centre -32.6 deg.

**The span figures in the table above were measured with the leaking mask and are inflated.** The
choice they justify still stands -- dropping the outermost blob at each end is what keeps the
camera tight -- but do not treat 40.0 deg as the reference span. With the mask corrected, game
9643 ran medians of 22-33 deg over five sampled windows, p90 32-56, and 12-14 tracked blobs per
frame, which is the physical count (10 skaters, 2 goalies, 2-3 officials). FOV_MIN = 48 was fitted
against the inflated spans. It still breathes at roughly the documented rate on four of those five
windows (58 deg/min travel, 6.0 reversals/min against the 64 / 7.7 reference), but it now sits at
its tightest 31% of the time; FOV_MIN 44 halves that to 17%, 40 cuts it to 8%. Not changed yet --
tightening the floor trades breathing against skaters leaving frame, and that needs eyes on a
render, not a statistic.

**Two motion rules, do not confuse them.** Choppy zoom is a BUG -- it came from caching
sampling maps quantised to 0.25 deg of fov, so the zoom held ~20 frames then jumped 3.2 px.
Build the map exactly every frame. Zoom *breathing* is WANTED: do not suppress it, and use no
deadband (a deadband causes stick-slip, which reads as choppy even with exact maps).

**Calibration is PER RINK and the script refuses to run without it.** `ih_fov`, `rig_tilt`,
`roll` and the ice-edge elevations all describe how one specific camera is mounted; borrowing
another rink's numbers yields a silently tilted, bowed video. **Only South Rink (Rink 1) is
calibrated.** North Rink (Rink 2) must be calibrated before this can be used there -- the
procedure is in the `CALIBRATION` block at the top of the script.

**The tilt lesson, because it cost three attempts.** The pano camera is mounted angled DOWN
(~12 deg at South Rink), so the panorama's rows are not lines of true elevation. Panning by
adding to the panorama yaw rotates about that tilted axis and the horizon rocks ~0.22 deg per
degree of pan. A roll constant cannot fix it, because the error is a *function* of pan --
measuring tilt only at pan 0 reports 0.16 deg and looks solved while the real swing is 7.7 deg.
Compose the rotations instead: Rx(pitch), Ry(pan) **about the true vertical**, Rx(rig_tilt).
Diagnostic: near and far boards tilting the SAME way is an orientation error and is
correctable; tilting OPPOSITE ways is perspective convergence and is correct, leave it alone.

**Proven on a full game as of 2026-10-22** (game 9643, 1:27:35 including a shootout and the
handshake), but read *Tuning it* below before rendering one: the first attempt at that game had
to be thrown away and re-rendered, which is 3h44m each time on this laptop.

## Tuning the auto-pan, and the three traps

**A SHORT RENDER IS NOT A SAMPLE OF A LONG ONE.** The background model, the ice mask, the goalie
anchors (percentiles over the tracked window) and the path smoothing are all derived from
whatever range is tracked. Render 30 s on its own and you get a *different camera* than the same
30 s inside a 30-minute chunk -- same code, different inputs. A 60 s sample of game 9643 came out
visibly tighter than the full chunk and was used to approve settings; the full render then did
not match it. Use `--dump-track` once per chunk and `--use-track` with `--clip-start/--clip-dur`
for every comparison after that. Tracking does not depend on any framing constant, so one track
serves every variant, and clips then cost ~90 s each instead of hours.

**SWEEP A CONSTANT BEFORE YOU RENDER IT.** The path maths is pure arithmetic over the cached
track, so the effect of a constant can be computed in seconds. Do that first and only render
what the sweep says will move. Two cases from 9643 that justify the habit:
- A `FOV_MIN` sweep predicted 58.3 deg/min of zoom travel and 6.0 reversals/min; the real
  renders came in at 56.0-56.2 and 6.3-6.7. Within ~5%, for free.
- A `zone_gain` A/B was rendered *without* sweeping first and produced byte-identical files,
  because the pan was already saturated (below). Twelve renders, two of them wasted.

**`zone_gain` IS INERT WHILE THE PAN IS SATURATED.** The bias drives `pan_t` toward the
defending goalie, but `pan` is then clipped to `PAN_LIMIT`. On 9643 at `PAN_LIMIT = 34` the pan
sat on its limit 31% of the time at gain 0.60 and 54% at gain 0.85 -- raising the gain only
drove the target into the wall harder and changed nothing on screen. The knob that moves the
camera into the end is `PAN_LIMIT`, not `zone_gain`. At 42 the saturation goes to ~0% and the
gain starts doing its job (mean |pan| 22.4 -> 26.2 deg). Note the goalie anchors measured
-42.3 and +38.4 deg, so ~42 is the principled ceiling: "you may look at the goalie, no further".
This has bitten twice -- the 2026-10-19 commit already raised it 28 -> 34 for the same reason,
and then the ice-mask fix deepened the tracked centres and re-saturated it.

**PITCH IS WELDED TO ZOOM, AND THAT IS THE BOUNCE.** `pitch_for()` pins the near boards at
`NEAR_AT` of frame height, so when the fov opens the frame must tilt down to keep that pin. On a
rush the fov opens ~30 deg and the pitch swings ~9 deg at up to 10 deg/s -- 30% of frame height,
which reads as the camera bouncing vertically. It is not the mask and not the pan: on the cycle
window, where the pan is steady, the swing is 0.39 deg. `--pitch-smooth SECONDS` decouples them.
The cost is that the near boards stop being pinned exactly; the script prints where the near
edge actually lands, as a fraction of frame height, and **above 1.0 means a player skating the
near boards loses his skates**. Measured on 9643's rush:

| `--pitch-smooth` | max pitch rate | near edge |
|---|---|---|
| 0 (solve every frame) | 10.0 deg/s | 0.970, pinned |
| **0.5 s (chosen)** | **2.5 deg/s** | 0.920 - 1.030 |
| 1.0 s | 1.7 deg/s | 0.921 - 1.053 |

0.5 s removes three quarters of the bounce for a crop you have to look for. Cycle and neutral
windows are unaffected (their pitch rate is already < 0.7 deg/s), so it costs nothing where
there is no bounce.

**TRIED AND REJECTED: framing all the players in the zone.** When play is deep, keep the
play-side outermost blob instead of dropping it, on the theory that the dropped blob is then a
skater behind the net rather than the goalie. It sounds right and it is not worth having. The
sweep moved the fov by **0.3 deg** on the cycle window it was meant to fix (19.4 -> 21.1 deg of
span) and 0.8 deg on the rush. The motivating evidence was also bad: "the span reaches 41.7 deg
while the goalie anchor is 38.4" is circular, because the dropped blob is *by construction* the
outermost one and so always beyond the kept edge. Tested properly, during deep play the dropped
blob sits within 3 deg of the goalie anchor 44-54% of the time, with a median gap of 2.2 deg to
the kept edge -- there is no clean separation to exploit, which is exactly why geometric crease
zones failed too. What actually puts the zone's players on screen is `PAN_LIMIT`, not the span
rule.

**Settings chosen for 9643 on A/B clips, by eye, and now the defaults in the script:**
`FOV_MIN 40, PAN_LIMIT 42, ZONE_GAIN 0.85, ZONE_KNEE 10, PITCH_SMOOTH_S 0.5`.
Build the comparisons as labelled 2x2 or stacked grids of the SAME 30 s with game audio, from
one cached track, and pick the moments from the tracking rather than by eye -- a deep cycle
(high mean |centre|, low spread), a rush (biggest centre swing), and neutral ice as a control.
If a change alters the control clip, the change is firing when it should not: that control is
what confirmed the pan bias correctly does nothing at centre ice.

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
- **Keep derived files out of the game folder.** `probe`/`detect`/`build` take every video in the folder, and anything that is not a segment sorts after them, so the stitched total grows and the cut shifts with no error. A goal clip saved there on 2026-10-03 turned a 1:30:00 input into 1:31:35 mid-encode. They now ignore files that do not match the LiveBarn name pattern `_<YYYY-MM-DD>T<HHMMSS>.<ext>` and print what they skipped, but only when the folder also holds real segments; put clips in `~/Videos/LiveBarn/clips` regardless. Passing files explicitly still works for deliberately odd names.
- **A killed encode leaves an unplayable file.** ffmpeg writes the `moov` atom at the end, so a crash mid-build yields `moov atom not found` and nothing is salvageable -- there is no resume. Delete the partial and re-run from the start. A laptop crash at 02:08 on 2026-10-03 lost 26:23 of a 1:07:50 encode.
- Never delete the user's source segments.
