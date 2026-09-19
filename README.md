# Mid Ice Crisis Stats

Self-updating stats dashboard for our beer-league hockey team (BH Adult League, Division D), formerly
"Globo Gym King Cobras D". Live at: **https://albano-insights.github.io/mid-ice-crisis-stats/**

## The four tabs

Each tab answers one question:

- **Overview** — *how are we doing*: the division standings (official table, OTL = a point), a
  standings outlook (every team's remaining schedule, strength of schedule, rating and projected
  finish), trends and the division's cumulative goal differential, and one "notable right now" list.
- **Games** — *what happened, what's coming*: Results (with box scores, recaps, corrections and
  on-ice tagging), Head-to-Head, and Upcoming (calendar, rink skates, Bench App sync).
- **Scouting** — *who's next*: the upcoming opponent, film, keys to the game, their roster graded.
- **Players** — *who is this guy*: a sortable leaderboard (points first; our team or the whole
  division, per season or all-time) and every skater graded on their whole career; click through to
  a Player Spotlight. The **?** in the tab strip is the glossary.

## How it works

- `scripts/scrape.py` pulls every season, schedule, box score, and division standings for our team(s)
  from the league's stats site (stats.panthers.timetoscore.com) into `data/raw/`, plus each roster
  player's cross-league career page and the other adult league's standings (for the Player Spotlight).
- `scripts/build_site_data.py` layers any manual corrections on top and computes everything the
  dashboard shows (leaderboards, head-to-head records, schedule heatmap, league leaders) into
  `data/derived/`, which is copied into `docs/data/` for the live page.
- `.github/workflows/refresh-data.yml` runs the parser tests, both scripts, and the film sync daily
  (and on demand) and commits any changes, so the site updates itself with no one needing to run
  anything. `tests/` pins every parser to real cached pages so a markup change on the league site
  fails the run loudly instead of silently producing empty data.
- `docs/` is a plain static page (no build step, no framework) published via GitHub Pages
  (GitHub Pages only serves `/` or `/docs` from a branch, hence the folder name).

## Player Spotlight (cross-league caliber grades)

The **Players** tab grades every skater who has ever appeared in our division -- our roster, every
opponent's, one-night fill-ins -- on *everything* they've played, not just our division.
`scripts/scrape.py` pulls each such player's career page from the league site
(the one page there that spans every league it hosts), plus the standings and division player tables
for every configured adult league (`player_lookup_leagues` in `data/franchises.json`, currently BH
Adult and ID Adult) for each season those careers touch. `build_site_data.py` then pins each stint to
its division, percentile-ranks its P/GP against every skater in that division-season, and rolls that
into a caliber grade on the shared D → C3 → C2 → C1 → B → A ladder -- see `scripts/lib/spotlight.py`
for the method and the ? glossary for the formulas. Player names on the leaderboard, the Scouting
Report and the Overview's notable list all link into the same Spotlight.
Career pages are only re-fetched for players active somewhere this season, so the nightly run (12:30 AM Eastern) stays
cheap even with a few hundred players.

The league site records no positions, so `data/positions.json` is hand-maintained: set `"pos"` to
`"F"` or `"D"` for any player id (our roster is pre-listed; any id from
`data/derived/players_index.json` can be added, opponents included). The Players tab's position filter
then ranks defensemen against defensemen -- grades are production-based, so that's the fair comparison.

Adding a league to grade against is one line in `franchises.json` (`"<league id>": "<label>"`);
league ids are the `league=` parameter on the site's standings pages.

## Design source of truth

`docs/design/DESIGN_SPEC.md` is the design spec: the jersey-derived palette, the fixed meaning of
every color token, typography (nameplate / display / body faces), the chart series slots and the
component rules. `docs/styles.css` implements it; change the spec first, then the stylesheet.

## Game recaps

Every completed game of ours carries a written recap at the top of its box score (`recap` in
`docs/data/games/<id>.json`): headline, the scoring in order with lead changes, our scorers, the
game-winner, penalties, and the head-to-head record after the game. It's generated from the
corrected box score by `build_site_data.py` on every run -- nightly, and again within minutes of
any stat correction or on-ice tag -- so the words always match the numbers. Templates, not a
language model: deterministic and checkable. A ✎ marks a goal that was corrected.

Every other division game gets one too (`docs/data/division_recaps/<season>.json`, neutral voice,
written from the winner's side): open a team in the Overview's Standings outlook and click a
completed game, or see the next opponent's "this season" card on the Scouting report.

## Sharing a view

The URL tracks what you're looking at — tab, filters, an open Player Spotlight or box score — so
**Copy link** in the top bar (or just the address bar) gives someone the exact view:

- `#players?scope=league&pos=D&team=Globo%20Gym%20King%20Cobras%20D` — that team's defensemen, graded
- `#player/1523` — a Spotlight
- `#games?game=7718` — a box score, opened and scrolled to; `#games?tab=h2h`, `#games?tab=upcoming`
- `#overview?season=18` — the standings and outlook for a past season

## Film deep links (▶ on every goal)

`scripts/film_sync.py` finds the video timestamp of every goal on our YouTube film so the box score
and each player's Spotlight log link straight to the moment. It never reads the clock -- on this
rink's feed the digits are unreadable -- it watches the **scoreboard's score change**, which is the
goal itself: locate the board in a frame every 5 s (it moves as the camera pans), fingerprint each
side's score box, flag sustained changes, and match them in order to the scoresheet. When the camera
is away from the board a link is early by up to that gap, never late. Results are cached per video
in `data/raw/film/`, so the nightly run only pays (a 1080p download + decode, ~10 min) for new
uploads, two per night at most. A wrong link can be pinned by hand in `data/film_anchors/<game_id>.json`
(`{"goals": {"<goal index>": <video seconds>}}`). The scoreboard template it looks for is
`data/film/templates/<rink>.png` (one per rink, with a `<rink>.json` sidecar giving that board's score-box positions) -- add one when a game is on a new rink.

**Estimated links learn from your tags.** Every hand-keyed video time is an anchor. `film_sync.py`
fits a clock model across all anchored games (lead-in, how much the video stretches per game-clock
second because of stoppages, intermission length) and, within a game, interpolates untagged goals
between that game's own anchors. The fitted numbers are in `film_sync.json` under `_clock_model`
(`mae_s` = mean error against the anchors). More tags -> tighter ▶ links everywhere.

## Getting the film onto YouTube (LiveBarn → YouTube skill)

`.claude/skills/livebarn-youtube/` is a Claude Code skill (plus a plain Node CLI) that turns the
30-minute LiveBarn downloads into the game film the ▶ links point at: it stitches the segments,
finds the game inside them (arena horns in the audio, or thumbnail sheets + a manual start/end when the
North Rink feed has no audio), trims the warm-up, keeps the handshake line, encodes at YouTube's
recommended settings (optionally 1440p so YouTube serves its higher-bitrate tier), and uploads through
the YouTube Data API. Two more commands close the loop with the stats: `describe` regenerates the
video's title and description straight from `data/derived/` (scoring summary, penalties, standings,
head-to-head, per-game +/- once the goals are tagged, season leaders), and `update` rewrites the
description on the existing video -- so a stat correction or a new on-ice tag is one `describe` +
`update` away from being on YouTube. Hand-written game notes go in a `notes.txt` next to the game
files and survive every regeneration. `describe` also stamps `Game #<id>` into the description -- that
is what the nightly scrape matches to link the video to its box score -- and `refresh` (or
`upload --refresh`) fires the refresh workflow right away so a new upload reaches the dashboard without
waiting for the 12:30 AM run.

Setup is `scripts/setup.ps1` (fetches ffmpeg, installs `googleapis`) plus a one-time OAuth client;
the credentials live in `%LOCALAPPDATA%\livebarn-youtube\secrets\`, never in the repo. Full workflow
in [`.claude/skills/livebarn-youtube/SKILL.md`](.claude/skills/livebarn-youtube/SKILL.md); run
`node .claude/skills/livebarn-youtube/scripts/livebarn.mjs help` for the CLI.

## Plus/minus from on-ice tags

The league site never records who was on the ice, so +/- comes from people tagging goals off the
film: on any box-score goal, click ▶ to watch it, then **Tag on-ice**, tick the skaters on the ice
for both benches (ours at minimum), optionally type the video time where it went in (`13:33`), and
submit. That files a pre-filled issue; `.github/workflows/process-on-ice-issue.yml` writes
`data/on_ice/<game_id>.json`, stores any video time as a film anchor, rebuilds, and closes the issue.
`build_site_data.py` turns tags into NHL-rules +/- (power-play goals count for nobody), shown on the
leaderboard, Spotlights and player cards, always next to how many goals were tagged (season rows use
that season's tagged goals; all-time pools them). Tagging the
opponent's bench gives their players a +/- *against us*, which the scouting roster shows.

## Line pairings lab (not on the site)

`analysis/line_pairings.py` is a by-hand analysis, deliberately kept out of the build and the
nightly workflow: who gets credited on the same goals, how that compares with what their individual
production predicts ("chemistry"), and how the team does with both dressed vs. one of them (WOWY,
game-grain only -- there's no shift data). It writes `analysis/output/line_pairings.html` (open it in a
browser) and `.json`; run it with `python analysis/line_pairings.py [--min-games 5] [--season 18]`.
Scoresheets almost never record positions, so it can't tell forwards from defense -- the suggested
groupings are a whiteboard starting point, not a lineup card.

## Syncing the schedule to Bench App

Games › Upcoming has a "Sync to Bench App" card with a link to `docs/data/schedule.ics` -- a live
calendar feed of every game (past and upcoming, every season), rebuilt daily by the same workflow that
refreshes the stats. Paste that link into Bench App's Schedule -> Add -> **Sync Schedule**, and Bench App
re-checks it on its own, so a new game, a rink change, or a time change on the league site shows up
there automatically with nothing to re-upload. `scripts/build_site_data.py`'s `build_schedule_ics`
generates it.

## Fixing a wrong stat

The league's own scoresheets sometimes get a goal or assist wrong. On any game's box score, click
**"Suggest a fix"** on the goal in question — it opens a pre-filled GitHub issue. Submit it, and
`.github/workflows/process-correction-issue.yml` picks it up automatically, writes the correction into
`data/corrections/<game_id>.json`, rebuilds the site, and closes the issue. Corrections never edit the
raw scraped data — they're applied on top at build time, and the dashboard shows a small "corrected"
badge (hover for why) on anything that's been fixed.

You can also hand-edit a `data/corrections/<game_id>.json` file directly and commit it if you'd rather
not go through the issue form; see `scripts/lib/corrections.py` for the file format.

## Local development

```
pip install -r requirements.txt
python scripts/scrape.py
python scripts/build_site_data.py
cp -r data/derived/* docs/data/
python -m http.server --directory docs 8000   # then open http://localhost:8000
```

## Adding a future team rename

If the team renames or re-registers under a new team id again, add it to `data/franchises.json` under
the same franchise entry — the scraper will pick up its history automatically on the next run.
