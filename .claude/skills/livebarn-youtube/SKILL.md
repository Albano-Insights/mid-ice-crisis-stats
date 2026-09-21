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

3. **Probe**: `node $LB probe "<folder>"`. Segments are ordered by filename (natural sort — LiveBarn names carry the timestamp). Show the table; if the order looks wrong (files with odd names), pass the files explicitly in the right order instead of the folder.

4. **Detect the cut**: `node $LB detect "<folder>"`. Takes a few minutes (decodes all audio, then samples video motion around the horns).
   - It classifies loud tonal events as **horn** (100–1500 Hz, ≥0.6 s) or **whistle**. Proposed start = end of the first horn (end of warm-up), refined forward to the first sustained play if the ice visibly empties first. Proposed end = last horn + the handshake line, cut when motion on the ice collapses (60 s min, 5 min max after the horn; falls back to +3:00).
   - **Always show the user the horn list and the proposed start/end and ask them to confirm or adjust** before building. Point out any `note:` lines (e.g. too many horns → a goal horn or the next game's warm-up may have been picked as "last horn"; in that case pick the right horn from the list yourself and propose that).
   - **No usable audio** (about half of this user's games — the rink's north camera has an audio problem): the script says so. Then run `node $LB sheet "<folder>"` which writes `<segment>_sheet.png` next to each file (one thumbnail per minute, timestamp burned in, 6 per row) and ask the user for the start and end. Accept times as `H:MM:SS` on the stitched timeline or `N@MM:SS` (file number @ time within that file) — both are passed straight to `--start/--end`. Offer `--every 30` for finer sheets.
   - Even when audio works, `sheet` is a good way for the user to sanity-check a proposed cut.

5. **Build**: `node $LB build "<folder>" --start <T> --end <T>`. Output defaults to `<folder>\<folder name>_youtube.mp4`. Run it in the background (it is a full re-encode: with the default `libx264 -preset medium` on this i7-6700HQ expect roughly real-time to 1.5× real-time, i.e. 60–100 min for a 75-min game) and report when done. Options:
   - `--preset slow` — a bit better quality per bit, ~2× slower.
   - `--encoder nvenc` — GPU (GTX 960M), 3–5× faster but softer image; falls back to x264 automatically if NVENC fails. As of Sep 2026 it fails on this laptop ("Cannot load cuMemAllocAsync": the NVIDIA driver is too old for ffmpeg 9). Updating the GeForce driver should enable it; only worth it if the user asks for speed.
   - `--boost` — upscale to 2560×1440. YouTube gives ≥1440p uploads its VP9/higher-bitrate ladder, which is the single most effective fix for "the video looks blurry on YouTube". Encode takes ~1.8× longer and the file is ~1.7× bigger. Offer this if quality complaints persist after a normal 1080p upload.
   - `--dry-run` prints the ffmpeg command without running it.
   - Encoding settings follow YouTube's upload recommendations: H.264 High, yuv420p, CRF 17 capped at 24 Mbps (40 Mbps with `--boost`), closed GOP of half the frame rate, 2 B-frames, source frame rate kept (CFR), AAC-LC 384 kbps 48 kHz, `faststart`. Sources below 1080p are upscaled with Lanczos + light unsharp.
   - If any segment lacks an audio track the output is built without audio (mixed audio/no-audio segments cannot be concatenated in sync). Tell the user.
   - **Audio is rebuilt from the sample count, not the container timestamps.** LiveBarn segments carry garbage audio PTS (thousands of repeated/backwards timestamps per file) while the samples are complete; trusting them makes AAC drop/repeat frames — the "choppy audio" the user used to fix with HandBrake. `build` uses `asetpts=N/SR/TB` + filter-graph trims and pins each segment's concat offset to its video length. Verified: output audio correlates 1.00 with the source with 0–3 ms lag across seams, no dup/drop frames.

6. **Upload** (user asked for this): `node $LB upload "<file>" --title "..." [--desc "..." | --desc-file notes.txt] [--tags a,b] [--privacy unlisted|private|public] [--playlist <id>|none] [--refresh]`.
   - The video is added to the team's game-film playlist by default (the id comes from `data/franchises.json`'s `youtube_playlist_id`); the dashboard only ever sees videos in that playlist. `--playlist none` opts out.
   - Ask for the title (and privacy, default `unlisted`) before uploading; don't invent a title.
   - First run needs `%LOCALAPPDATA%\livebarn-youtube\secrets\client_secret.json` (see setup below) and opens a browser for Google sign-in once; the token is cached next to it as `token.json`. Credentials deliberately live outside the skill/repo folder.
   - Print the `https://youtu.be/<id>` link back. YouTube's own processing of a 1080p/1440p upload takes a while — HD renditions appear some minutes after the upload finishes.

## Title + description from the stats repo (and re-syncing after corrections)

The team's stats live in `C:\Users\alban\code\mid-ice-crisis-stats` (see its README). Two commands turn that data into the video's text and keep it current:

- `node $LB describe "<game folder>" --game <id>` (or `--date YYYY-MM-DD`; if two games that day it lists them and asks for `--game`). It `git pull`s the repo, then writes `youtube-title.txt` and `youtube-description.txt` into the game folder: scoring summary with running score (corrected goals marked `*`), penalties, standings context, GAME NOTES (only the rule-based insights that are true: multi-goal games, PP goal timing, GWG, ties, discipline vs season average, season series / all-time H2H), **+/- for this game when its goals are on-ice tagged** (same NHL rules as the repo: PP goals move nobody; coverage shown), season +/- totals, scoring leaders, site link, hashtags.
- `notes.txt` in the game folder is the hand-written narrative ("THE STORY"). It is inserted verbatim on every regeneration, so write the juicy stuff there, never into `youtube-description.txt` (that file is overwritten each time). Offer to draft `notes.txt` from the data, then let the user edit it.
- `youtube-title.txt` is generated once and then kept (the user may have tuned it); `--force-title` regenerates it.
- `node $LB update <videoId|url> --dir "<game folder>"` pushes the title + description to the existing video. **It is a full rewrite of the description, never an append.** `--dry-run` shows what would be sent; `--privacy public` can flip visibility at the same time. Costs ~50 quota units, so it can be run freely.

**After a stat correction or new +/- tags** (the repo's GitHub workflows commit those): run `describe` (pulls) then `update`. That is the whole loop. Use `--no-pull` only when offline.

Typical new-game flow: build → `describe --game <id>` → upload (`--title-file youtube-title.txt --desc-file youtube-description.txt`) → **`link <videoId>`** → **`film <videoId> <master.mp4>`** → `refresh --wait`. The game id is in `data/derived/games_index.json` (`game_id`, `iso_date`); the video id comes back from `upload`. If you uploaded with a hand-written description instead, follow with `describe` → `update`, then `link`.

## Linking the video to the dashboard and timestamping the goals (laptop-side, since Sep 2026)

YouTube bot-blocks GitHub's runner: the nightly scrape gets an empty description for a new upload and `yt-dlp` can't download for film sync. The laptop is not blocked, so two commands hand the repo what the runner can't fetch, as data commits pushed straight to `main` (the same way the tag/correction workflows commit):

- `node $LB link <videoId>` — reads the description (must contain `Game #<id>`, which `describe` writes) and duration via the Data API, writes `data/raw/youtube/<id>.json` + `data/raw/film/durations.json`, pushes. This is what makes the box score's ▶ button point at the video.
- `node $LB film <videoId> "<game folder>\<name>_youtube.mp4"` — runs the repo's `scripts/film_sync.py` on the local master (`--local-file`), i.e. the scoreboard analysis that timestamps every goal. Prints each goal's video time; commits `data/raw/film/<id>.json` + `data/derived/film_sync.json`; pushes. **Sanity-check the output**: goal times must be in game order and minutes apart — if the board was "seen" in fewer than ~20% of samples or the times are bunched together, the rink's scoreboard probably has no template yet: crop one into `data/film/templates/<rink>.png` with a `<rink>.json` giving `score_boxes` (fractions of the crop where the two red score digits sit) and `min_match`, then re-run. Existing: `seatgeek_rink`, `south_rink` (Baptist Health IcePlex).
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

## Notes / troubleshooting

- Detection heuristics are tuned for hockey (warm-up horn → game → final horn → handshake line). They are a proposal, not ground truth — always confirm with the user.
- If the recording started after warm-up, the "first horn" will be the end of period 1; the script warns when the first horn is inside the first minute. Use `--start 0` or a manual time.
- If the last segment includes the next game's warm-up horn, the wrong "last horn" gets picked; choose the correct one from the printed list.
- `--handshake-max 420` extends the window for long handshake lines / team photos; `--start-offset -30` (or positive) shifts the start.
- `livebarn-detect.json` is written into the game folder with all events and the proposal.
- The build prints `could not seek to position ...` from the concat demuxer. It is harmless — ffmpeg decodes from the start and discards frames up to `--start`; the cut has been verified accurate to the second.
- Never delete the user's source segments.
