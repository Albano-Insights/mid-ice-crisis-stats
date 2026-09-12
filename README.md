# Mid Ice Crisis Stats

Self-updating stats dashboard for our beer-league hockey team (BH Adult League, Division D), formerly
"Globo Gym King Cobras D". Live at: **https://albano-insights.github.io/mid-ice-crisis-stats/**

## How it works

- `scripts/scrape.py` pulls every season, schedule, box score, and division standings for our team(s)
  from the league's stats site (stats.panthers.timetoscore.com) into `data/raw/`.
- `scripts/build_site_data.py` layers any manual corrections on top and computes everything the
  dashboard shows (leaderboards, head-to-head records, schedule heatmap, league leaders) into
  `data/derived/`, which is copied into `docs/data/` for the live page.
- `.github/workflows/refresh-data.yml` runs both scripts daily (and on demand) and commits any changes,
  so the site updates itself with no one needing to run anything.
- `docs/` is a plain static page (no build step, no framework) published via GitHub Pages
  (GitHub Pages only serves `/` or `/docs` from a branch, hence the folder name).

## Syncing the schedule to Bench App

The Schedule tab has a "Sync to Bench App" card with a link to `docs/data/schedule.ics` -- a live
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
