# Mid Ice Crisis Dashboard — Design Spec

2026-09-18 · Alex Albano · Source of truth: this file. The Claude Doc it was drafted in: https://claude.ai/code/artifact/ab27939d-9abb-45b7-807e-f69dbbddf100

## Purpose & scope

This spec re-skins the live dashboard at [albano-insights.github.io/mid-ice-crisis-stats](https://albano-insights.github.io/mid-ice-crisis-stats/) in Mid Ice Crisis colors and lettering, without changing its layout, views or data. Colors and lettering come from the actual home and away jerseys (photos supplied 2026-09-18). Everything the current `docs/styles.css` does structurally (four layout primitives, three elevation levels, fixed semantic colors, `.sec` micro-headers, hover = accent border) stays; only the token values, the font stack and the chart series change.

It covers `docs/index.html`, `docs/styles.css`, `docs/v2.css` and the Chart.js calls in `docs/app.js`. It does not cover the logo, the YouTube descriptions, or the GitHub issue templates.

## Brand foundation

The palette comes from the jerseys themselves, with the crest in `docs/logo.jpg` as the secondary source. Home is a bright royal-blue body with a black back panel and red/white/blue stripe and star trim; away is white with the same royal and red trim and a blue captain's C. The crest's navy is not a jersey color, so it is out; black is in.

| Role | Where it is on the jersey | Hex | Dashboard use |
| --- | --- | --- | --- |
| Royal blue (primary) | Home body, away trim and C | #1f5fd6 | Interactive accent, "us" series |
| Black | Home back panel behind the nameplate | #0b0e14 | Dark-mode field |
| White | Away body, nameplate letters, stripe | #f4f6fa | Light-mode field |
| Jersey red | Stripes, number outlines, collar | #c8102e | Brand stripe (`--team`), never a data color |
| Ice blue | Crest lettering only | #61a7e0 | Light-mode tints, sequential ramp |
| Amber | Crest beer | #eb910d | Caution only |

**Lettering.** The nameplates are a wide, heavy block with slightly rounded corners, white with a red-then-black outline (tackle-twill style); numbers match. It is not condensed, so the earlier Oswald pick is dropped. The closest freely hosted face is [Bowlby One SC](https://fonts.google.com/specimen/Bowlby+One+SC) for the nameplate moments (page title, player names in the Spotlight and Rising Now), with the outline reproduced in CSS. Tabs, section headers and KPI values use Inter 800 uppercase with tracking so they stay legible at small sizes. If the supplier can name the jersey font, swap it in as `--font-display` and nothing else changes.

## Color tokens

Dark mode is the home jersey (black nameplate panel as the field, royal blue as the accent); light mode is the away jersey (white field, royal accent). The token names and their fixed semantic meanings are unchanged from today's stylesheet, so no selector needs to be touched.

| Token | Meaning (fixed, never varies by view) | Light (away) | Dark (home) |
| --- | --- | --- | --- |
| `--bg` | Page field | #f4f6fa | #0b0e14 |
| `--bg2` | Card surface | #ffffff | #141924 |
| `--bg3` | Tile / inset surface | #e9eef7 | #1e2533 |
| `--bd` | Border | #cfd8e8 | #2b3446 |
| `--tx` | Primary text | #0b0e14 | #f4f6fa |
| `--mu` | Muted text, no-signal | #5a6579 | #8d97a8 |
| `--ac` | Interactive only (active tab, hover border, selection) | #1f5fd6 | #6f9ff0 |
| `--ac-ink` | Text on `--ac` | #ffffff | #0b0e14 |
| `--bl` | Elite / neutral-positive | #1f5fd6 | #6f9ff0 |
| `--gn` | Improving / good | #1a7f45 | #3fb950 |
| `--rd` | Declining / bad | #b5121b | #f0625a |
| `--or` | Caution / cooling | #a85c08 | #eb910d |
| `--pu` | Reserved (UAT banner, misc) | #7a4fd6 | #a892e6 |
| `--team` | Brand-only: stripe, "us" row tint, nameplate outline | #c8102e | #e03a3e |

Two rules keep the jersey colors from fighting the data colors:

- Red is both the brand stripe and the "declining" signal. Brand red (`--team`) appears only in static chrome: the top bar's bottom border, the `.row-us` tint at 10 % mix, the Spotlight header band. It is never used on a metric, a delta or a chart series, so red on a number always means "bad".
- Amber (`--or`) is the beer. It stays the caution color and the fourth chart series; it is not decorative.

All text/surface pairs above meet WCAG AA at 4.5:1 for body text (`--mu` on `--bg2` is 5.9:1 light, 6.0:1 dark; `--ac` on white is 5.7:1 and on the dark card 6.6:1; `--gn` and `--or` on white are 5.0:1). Dark-mode `--ac-ink` is black on royal at 7.3:1, so an active tab reads like a jersey number on the blue body. `--team` red on the black field is 4.5:1, enough for the 3 px stripe and outlines but not for small text, so brand red never carries a label.

## Typography

Three roles: a nameplate face for the few places that should look like the back of the jersey, a wide uppercase sans for the chrome (tabs, section headers, KPI values), and a neutral sans for everything people read. The nameplate face is a display font and is never used below 1.2 rem.

| Token | Face | Where |
| --- | --- | --- |
| `--font-nameplate` | Bowlby One SC 400, uppercase, white with a 2-layer outline (`--team` then `--tx`) via `text-shadow` | Top-bar `h1`, Spotlight player name, Rising Now card name |
| `--font-display` | Inter 800, uppercase, `letter-spacing: 0.08em` | `nav.tabs` buttons, card `h2`, `.sec`, `.stat-tile .value`, `.kpi-card .value`, grade badges |
| `--font-body` | Inter 400/600, `font-feature-settings: "tnum"` | Prose, table cells, filters, tooltips |
| `--font-mono` | ui-monospace, SFMono-Regular, Menlo, Consolas | Formula text on the Metrics tab (unchanged) |

Type scale (base 15 px, unchanged):

| Element | Size | Face | Notes |
| --- | --- | --- | --- |
| Top-bar title | 1.5 rem | Nameplate | White letters, red + black outline on both themes, like the twill |
| Spotlight player name | 2 rem | Nameplate | Same treatment; the player's number, if known, sits beside it in the same face |
| Tab buttons | 0.82 em | Display | Uppercase, tracked; active tab = royal fill |
| Card `h2` | 1 rem | Display | Uppercase |
| `.sec` micro-header | 0.68 em | Display | Already uppercase with 0.1em tracking |
| KPI / stat value | 1.5 em | Display | Up from 1.15 em; Inter has tabular figures so wide values need no fallback |
| Body, table cells | 15 px / 0.86 em | Body | `tnum` so columns of numbers align |
| Labels, stamps | 0.72 em | Body | Muted `--mu` |

The nameplate outline is two stacked `text-shadow` rings (1 px `--team`, then 2 px `--tx` on light / `#000` on dark) rather than `-webkit-text-stroke`, so it renders the same in every browser and does not thin the letterforms.

Both faces load from Google Fonts with `display=swap` and `preconnect`; Bowlby One SC is a single weight (about 20 KB) and Inter 400/600/800 about 45 KB. The page currently loads no webfont.

## Chart & data-viz palette

Five categorical series, assigned in fixed order and never cycled; a sixth entity folds into "Other" or a small multiple. Both sets were run through a colorblind-separation validator (OKLab lightness band, chroma floor, deutan/protan/tritan adjacent-pair distance, 3:1 contrast against the chart surface) and pass every check. Adjacent series are ordered so that red never sits next to amber, which was the pair that failed in dark mode.

| Slot | Entity (fixed) | Light (surface #ffffff) | Dark (surface #0b0e14) |
| --- | --- | --- | --- |
| 1 | Us (Mid Ice Crisis) | #1f5fd6 | #4a86e8 |
| 2 | Opponent / comparison | #c8102e | #e0483f |
| 3 | Division average | #2a8fc9 | #2d9bd6 |
| 4 | League average | #d97b06 | #c4841a |
| 5 | Second player / line | #7a4fd6 | #8f6fe0 |

- **Sequential (magnitude)**: one hue, pale → royal, for the schedule heatmap and percentile cells. Light: #e9eef7 → #b8cdf3 → #6f9ff0 → #1f5fd6 → #0f3a8f. Dark: #1e2533 → #1f3d75 → #2f63c2 → #6f9ff0 → #b8cdf3.
- **Diverging (polarity)**: `--rd` ↔ `--mu` ↔ `--gn` for the +/- column, momentum, and recent-vs-baseline deltas; the midpoint is neutral gray, never a hue.
- **Status**: `--gn` good, `--or` caution, `--rd` bad, `--bl` elite — the existing semantic tokens, and they are never reused as a series color.
- **Sparklines**: line color is the trend itself (`--gn` up, `--rd` down, `--mu` flat), generated server-side as today; the series palette does not apply.
- **Quadrant scatter**: dots in slot 1 for our roster, `--mu` at 55 % opacity for everyone else; the four quadrant labels sit inside the plot in the display face, uppercase, `--mu`.

Mark rules stay as in the current build: 2 px lines, ≥ 8 px markers, 4 px rounded bar ends anchored to the baseline, a 2 px surface gap between adjacent bars, grid lines at `--bd`, axis text in `--mu`. Legend text and value labels are always `--tx`/`--mu`, never the series color.

## Components

The brand shows up in four places: the top bar, the tab strip, the KPI tiles and the "us" row. Everything else stays neutral so the data colors keep their meaning.

| Component | Change | Unchanged |
| --- | --- | --- |
| Top bar | Title in the nameplate face with the red + black outline; a 3 px `--team` red bottom border replaces the 1 px `--bd` line, like the stripe under the nameplate. Crest stays 40 px, round; its border becomes `--ac` | Sticky, height, Copy link pill, stamp |
| Tab strip | Display face, uppercase, tracked. Active tab = `--ac` royal fill with `--ac-ink` text (white on light, black on dark). Hover = `--ac` border only | Pill shape, horizontal scroll, order |
| Cards | No change; `--bg2` surface, `--bd` border, `--radius` 8 px | All |
| `.sec` micro-header | Display face | Size, tracking, `--mu` |
| KPI / stat tiles | Value in display face at 1.5 em; a 2 px `--ac` left border so a row of tiles reads like a scoreboard strip | `--bg3` surface, label style, hover = border turns `--ac` |
| Rising Now strip | Player name in the nameplate face at 1.2 rem; delta chip keeps `--gn`/`--rd` | Card width, scroll |
| Player Spotlight header | Name in the nameplate face at 2 rem on a `--bg3` band with a 3 px `--team` bottom border, the closest thing on the site to the back of the jersey | KPI cards, chart, log |
| Standings `.row-us` | Tint = `--ac` at 10 % mix (royal, the home body); the name cell gets a 3 px `--team` left border | Bold weight |
| Badges (corrected, grade letters) | Grade badges D→A use the sequential royal ramp above, letter in display face; "corrected" badge stays `--or` outline | Size, tooltip |
| Selection state | White border + ring + checkmark, per the template; on dark the ring is `--ac` at 40 % | Behavior |
| Help dialog, UAT banner (`v2.css`) | Banner keeps `--pu`; dialog inherits the new tokens | Layout |

Elevation stays at three levels (`--bg`, `--bg2`, `--bg3`) and hover never changes a background, only a border, exactly as the template requires.

## Implementation notes

The whole change is one token block swapped at the top of `docs/styles.css`, two `<link>` lines in `docs/index.html` and `docs/v2.html`, one series array in `docs/app.js`, and about a dozen selector tweaks. No view, data file or script changes.

```css
:root {
  --font-nameplate: "Bowlby One SC", Impact, "Arial Black", sans-serif;
  --font-display: "Inter", -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --font-body: "Inter", -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;

  --bg: #f4f6fa;  --bg2: #ffffff;  --bg3: #e9eef7;  --bd: #cfd8e8;
  --tx: #0b0e14;  --mu: #5a6579;
  --ac: #1f5fd6;  --ac-ink: #ffffff;
  --bl: #1f5fd6;  --gn: #1a7f45;  --rd: #b5121b;  --or: #a85c08;  --pu: #7a4fd6;
  --team: #c8102e;  --plate-ink: #ffffff;  --plate-edge: #0b0e14;
  --s1: #1f5fd6; --s2: #c8102e; --s3: #2a8fc9; --s4: #d97b06; --s5: #7a4fd6;
  --shadow: 0 1px 2px rgba(11, 14, 20, 0.06), 0 4px 12px rgba(11, 14, 20, 0.06);
  --radius: 8px;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #0b0e14;  --bg2: #141924;  --bg3: #1e2533;  --bd: #2b3446;
    --tx: #f4f6fa;  --mu: #8d97a8;
    --ac: #6f9ff0;  --ac-ink: #0b0e14;
    --bl: #6f9ff0;  --gn: #3fb950;  --rd: #f0625a;  --or: #eb910d;  --pu: #a892e6;
    --team: #e03a3e;  --plate-edge: #000000;
    --s1: #4a86e8; --s2: #e0483f; --s3: #2d9bd6; --s4: #c4841a; --s5: #8f6fe0;
  }
}
:root[data-theme="dark"] { /* same block as above, verbatim */ }

body { font-family: var(--font-body); font-feature-settings: "tnum"; }

/* Nameplate: white twill with a red-then-black outline */
.nameplate {
  font-family: var(--font-nameplate);
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--plate-ink);
  text-shadow:
    -1px -1px 0 var(--team),  1px -1px 0 var(--team), -1px 1px 0 var(--team),  1px 1px 0 var(--team),
    -2px -2px 0 var(--plate-edge), 2px -2px 0 var(--plate-edge), -2px 2px 0 var(--plate-edge), 2px 2px 0 var(--plate-edge);
}
.topbar h1 { font-size: 1.5rem; }                 /* add class="nameplate" in the markup */
.spotlight-name { font-size: 2rem; }              /* also .nameplate */
.rcard .name { font-size: 1.2rem; }               /* also .nameplate */

/* Chrome: wide uppercase sans */
nav.tabs button, .card h2, .sec, .stat-tile .value, .kpi-card .value, .grade {
  font-family: var(--font-display); font-weight: 800;
  text-transform: uppercase; letter-spacing: 0.08em;
}
.topbar { border-bottom: 3px solid var(--team); }
.topbar .brand img { border-color: var(--ac); }
.stat-tile, .kpi-card { border-left: 2px solid var(--ac); }
.stat-tile .value, .kpi-card .value { font-size: 1.5em; letter-spacing: 0.02em; }
tr.row-us td { background: color-mix(in srgb, var(--ac) 10%, transparent); }
tr.row-us td:first-child { border-left: 3px solid var(--team); }
```

Font loading, in `<head>` before `styles.css`:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bowlby+One+SC&family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
```

In `app.js`, every Chart.js dataset color comes from one array read off the computed style, so light/dark and any future re-brand need no JS edit:

```js
const css = getComputedStyle(document.documentElement);
const SERIES = ['--s1','--s2','--s3','--s4','--s5'].map(v => css.getPropertyValue(v).trim());
```

Migration order, each step shippable on its own:

1. Add the font links and `--font-*` tokens; put `class="nameplate"` on `.topbar h1` and apply the display face to `nav.tabs`. Visual change is contained to the header.
2. Swap the color token block (both modes). Every existing selector picks it up; check the standings tint and the UAT banner.
3. Replace hard-coded series colors in `app.js` with `SERIES`, and re-order datasets so "us" is always slot 1.
4. Apply the tile, `.row-us` and badge changes; bump KPI value size; add `.nameplate` to the Spotlight header and Rising Now names in `app.js`.
5. Run `python -m http.server --directory docs 8000`, screenshot every tab in both modes at 390 px and 1200 px, and check the tab strip: Inter 800 with 0.08em tracking is wider than today's Segoe UI, so the strip will scroll at narrower widths than before. Shorten "Head-to-Head" to "H2H" and "League Outliers" to "Outliers" on phones if it gets tight.

Open items: the exact jersey font, if the supplier can name it (the spec works without it), and whether the crest's amber should stay caution-only or also colour the Insights tab's beer-themed callouts.
