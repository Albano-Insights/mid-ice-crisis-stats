const CONFIG = {
  repo: "Albano-Insights/mid-ice-crisis-stats",
  ourNames: ["Mid Ice Crisis", "Globo Gym King Cobras D"],
};

const state = {};

async function loadJSON(path) {
  const res = await fetch(`data/${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`failed to load ${path}: ${res.status}`);
  return res.json();
}

function isUs(teamName) {
  return CONFIG.ourNames.includes(teamName);
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c == null) continue;
    node.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
  }
  return node;
}

// A span whose content is a pre-rendered SVG string built server-side (design template 4.8) --
// no client-side chart instance, no layout cost, works inside a table cell.
function sparkSpan(svg) {
  return el("span", { html: svg || "" });
}

function statTile(label, value) {
  return el("div", { class: "stat-tile" }, [
    el("div", { class: "value" }, String(value)),
    el("div", { class: "label" }, label),
  ]);
}

// Every view opens with one of these: what the page is for and how to drive it, in a couple of
// lines. Kept deliberately short -- it's orientation for a teammate landing here cold, not docs.
function pageIntro(children) {
  return el("div", { class: "page-intro" }, children);
}

function strong(text) {
  return el("strong", {}, text);
}

// ---------------------------------------------------------------------------
// Tooltip system -- one delegated listener, a central TIPS map (design template section 3)
// ---------------------------------------------------------------------------

const TIPS = {
  PTS: "Points = Goals + Assists.",
  G: "Goals scored.",
  A: "Total assists (primary + secondary).",
  A1: "Primary assist -- the pass immediately before the goal.",
  A2: "Secondary assist -- the pass before that. Awarded less often than a primary assist.",
  "P/GP": "Points per game played. The rate stat that's fair to compare across players who've missed games.",
  PIM: "Penalty minutes. League median is modest -- 20+ for a season is a real habit, not bad luck.",
  Hat: "Hat tricks -- games with 3+ goals by that player.",
  GP: "Games played.",
  Momentum: "Half-split trend (2nd half of the window minus 1st half) in Points, plus a lower-weighted "
    + "trend in Goals. This is the default sort: positive means heating up lately, negative means cooling off, "
    + "near zero means steady.",
  "SV%": "Save Percentage = saves / shots faced. .900 is a rough replacement level in this league; .910+ is strong.",
  GAA: "Goals Against Average -- goals allowed per 60 minutes. Lower is better.",
  "W-L": "Goalie win-loss record in games they started.",
  Streak: "Consecutive games with the same result (win, loss, or tie), most recent first.",
  "Goal Diff": "Goals for minus goals against, cumulative across all tracked seasons.",
  Form: "Recent points-pace trend: 2 points for a win, 1 for a tie, 0 for a loss, half-split over the last games.",
  Caliber: "Caliber grade, from every team and league this player has played in. Each stint is placed on the "
    + "D→C3→C2→C1→B→A ladder by its division, pulled up or down by where the player's P/GP ranked in that division, "
    + "then averaged by games played. 'Top-end D' ≈ 'Entry-level C3'.",
  Confidence: "How many graded games back the grade: L = under 10, M = 10-29, H = 30+.",
  Fit: "Grade vs. the division they're in right now: 'plays up' = grading at least half a rung above it, "
    + "'depth' = at least half a rung below, 'level' = in between.",
  "Div. Rank": "Percentile of this player's P/GP among every skater with 3+ GP in that division that season "
    + "(higher is better), and their rank in it.",
  Tenure: "Time in the league site's system: first game anywhere to now, and how many seasons (any league) they've been rostered in.",
  "D %": "Share of all their games played in a D division (either adult league). Low = most of their hockey is at a higher level.",
  Trajectory: "Caliber over the last 12 months vs. everything before: rising / fading if it moved a quarter rung or more.",
  WOWY: "With-or-without-you: the team's goal differential per game with this player dressed minus without (game grain, our division only). Feeds the grade at up to ±0.25 rungs.",
  Persistence: "Being kept on a roster at your top level season after season is evidence a points-only grade can't see. +0.15 per extra season, capped at +0.30.",
  "vs Us": "This player's line against our team specifically, and our record in those games.",
  Clutch: "Points on third-period or OT goals while the game was within one — 'late & close'.",
  "+/-": "True plus/minus from on-ice tags: +1 on the ice for an even-strength or shorthanded goal for, −1 against; power-play goals count for nobody. Only goals someone has tagged from the film count — hover for coverage. For opponents it comes from our games only, i.e. their +/− against us.",
  Position: "F or D, hand-entered in data/positions.json -- the league site doesn't record positions. "
    + "Grades are still production-based, so a stay-at-home defenseman grades low; compare D against D.",
};

function initTooltipSystem() {
  const el_ = document.createElement("div");
  el_.id = "gTip";
  document.body.appendChild(el_);
  let on = false;

  document.addEventListener("mouseover", (e) => {
    const t = e.target.closest("[data-tip]");
    if (!t) return;
    el_.textContent = t.dataset.tip;
    el_.style.opacity = "1";
    on = true;
  });
  document.addEventListener("mousemove", (e) => {
    if (!on) return;
    const x = e.clientX, y = e.clientY, w = el_.offsetWidth, h = el_.offsetHeight;
    const vw = window.innerWidth, vh = window.innerHeight;
    el_.style.left = (x + 14 + w > vw - 8 ? x - w - 14 : x + 14) + "px";
    el_.style.top = (y - h - 8 < 0 ? y + 14 : y - h - 8) + "px";
  });
  document.addEventListener("mouseout", (e) => {
    if (!e.target.closest("[data-tip]")) return;
    el_.style.opacity = "0";
    on = false;
  });
}

function tipTh(label, tipKey) {
  return el("th", { "data-tip": TIPS[tipKey] || TIPS[label] || "" }, label);
}

// ---------------------------------------------------------------------------
// Momentum badges (the composite score's 3 visual bands)
// ---------------------------------------------------------------------------

function momentumBadge(momentum, { compact = false } = {}) {
  if (!momentum) return null;
  const band = momentum.direction === "hot" ? "mb-hi" : momentum.direction === "cold" ? "mb-lo" : "mb-md";
  const arrow = momentum.direction === "hot" ? "▲" : momentum.direction === "cold" ? "▼" : "►";
  return el("span", { class: `mb ${band}`, "data-tip": TIPS.Momentum }, compact ? arrow : `${arrow} ${momentum.label}`);
}

// ---------------------------------------------------------------------------
// Simple + diverging bar charts (counts, and +/- series like goal differential)
// ---------------------------------------------------------------------------

function barChart(rows, valueKey, labelKey, max) {
  const container = el("div");
  const top = max ?? Math.max(1, ...rows.map((r) => r[valueKey] || 0));
  for (const row of rows) {
    const pct = Math.max(2, Math.round(((row[valueKey] || 0) / top) * 100));
    container.appendChild(
      el("div", { class: "bar-row" }, [
        el("div", { class: "name" }, row[labelKey]),
        el("div", { class: "bar-track" }, [el("div", { class: "bar-fill", style: `width:${pct}%` })]),
        el("div", {}, String(row[valueKey] ?? 0)),
      ])
    );
  }
  return container;
}

function divergingBarChart(rows, valueKey, labelKey) {
  const container = el("div");
  const maxAbs = Math.max(1, ...rows.map((r) => Math.abs(r[valueKey])));
  for (const row of rows) {
    const v = row[valueKey];
    const pct = Math.min(50, (Math.abs(v) / maxAbs) * 50);
    container.appendChild(
      el("div", { class: "diverging-row" }, [
        el("div", { class: `name${row.is_us ? " is-us" : ""}` }, row[labelKey]),
        el("div", { class: "diverging-track" }, [
          el("div", { class: "diverging-center" }),
          el("div", { class: `diverging-fill ${v >= 0 ? "pos" : "neg"}`, style: `width:${pct}%` }),
        ]),
        el("div", {}, v >= 0 ? `+${v}` : String(v)),
      ])
    );
  }
  return container;
}

// ---------------------------------------------------------------------------
// Sortable-but-formatted table helper -- click a header to sort by its key
// ---------------------------------------------------------------------------

function sortableTable(columns, rows, defaultKey, defaultDir = -1) {
  // columns: [{label, key, tip, render(row) -> Node|string, sortValue?(row) -> comparable}]
  // `sortValue` is for columns whose displayed value isn't a plain row[key] (e.g. momentum, which
  // is nested at row.momentum.value) -- falls back to row[key] when not given.
  let sortKey = defaultKey, sortDir = defaultDir; // 1 = asc, -1 = desc
  const colByKey = Object.fromEntries(columns.filter((c) => c.key).map((c) => [c.key, c]));
  const valueOf = (row, key) => {
    const col = colByKey[key];
    return col && col.sortValue ? col.sortValue(row) : row[key];
  };
  const thead = el("tr");
  const tbody = el("tbody");
  const table = el("table", {}, [el("thead", {}, thead), tbody]);

  function draw() {
    const sorted = [...rows].sort((a, b) => {
      const av = valueOf(a, sortKey), bv = valueOf(b, sortKey);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return av < bv ? sortDir : av > bv ? -sortDir : 0;
    });
    tbody.replaceChildren(
      ...sorted.map((r) => el("tr", {}, columns.map((c) => el("td", {}, c.render(r)))))
    );
    thead.querySelectorAll("th").forEach((th, i) => {
      th.classList.toggle("sort-active", columns[i].key === sortKey);
      const arrow = th.querySelector(".sort-arrow");
      if (arrow) arrow.textContent = columns[i].key === sortKey ? (sortDir === 1 ? "↑" : "↓") : "";
    });
  }

  thead.replaceChildren(
    ...columns.map((c) =>
      el(
        "th",
        { "data-tip": c.tip || "", onclick: c.key ? () => { sortDir = sortKey === c.key ? -sortDir : -1; sortKey = c.key; draw(); } : null },
        [c.label, c.key ? el("span", { class: "sort-arrow" }) : null]
      )
    )
  );
  draw();
  return table;
}

// ---------------------------------------------------------------------------
// Chart.js trend charts (Overview) -- bar+line combo per the design template,
// destroy-before-recreate discipline so switching granularity doesn't leak instances.
// ---------------------------------------------------------------------------

const CH = {};

function destroyChart(key) {
  if (CH[key]) {
    CH[key].destroy();
    delete CH[key];
  }
}

function rollingAvg(values, window) {
  const out = [];
  for (let i = 0; i < values.length; i++) {
    const lo = Math.max(0, i - window + 1);
    const chunk = values.slice(lo, i + 1);
    out.push(chunk.reduce((a, b) => a + b, 0) / chunk.length);
  }
  return out;
}

let chartDefaultsSet = false;
function ensureChartDefaults() {
  if (chartDefaultsSet || typeof Chart === "undefined") return;
  const muted = getComputedStyle(document.body).getPropertyValue("--mu").trim() || "#8b949e";
  Chart.defaults.color = muted;
  Chart.defaults.font.size = 10;
  chartDefaultsSet = true;
}

function buildTrendChart(canvasId, buckets, metricKey, { title, color = "#1d6fd6", avgWindow = 1 } = {}) {
  destroyChart(canvasId);
  const canvasEl = document.getElementById(canvasId);
  if (!canvasEl || typeof Chart === "undefined") return;
  ensureChartDefaults();

  const labels = buckets.map((b) => b.label);
  const raw = buckets.map((b) => b[metricKey]);
  const datasets = [
    { type: "bar", data: raw, backgroundColor: "rgba(128,128,128,0.35)", borderRadius: 2, order: 2 },
  ];
  if (avgWindow > 1 && raw.length > 1) {
    datasets.push({
      type: "line", data: rollingAvg(raw, avgWindow), borderColor: color, backgroundColor: color,
      borderWidth: 2.5, pointRadius: 0, tension: 0.3, order: 1,
    });
  }

  CH[canvasId] = new Chart(canvasEl.getContext("2d"), {
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: false }, title: { display: true, text: title || "", font: { size: 10 } } },
      scales: {
        x: { ticks: { maxTicksLimit: 8, autoSkip: true, font: { size: 9 } }, grid: { display: false } },
        y: { beginAtZero: true, ticks: { font: { size: 9 }, precision: 0 } },
      },
    },
  });
}

async function renderTrendsCard(view) {
  const ts = await loadJSON("team_timeseries.json");
  const grains = ["week", "month", "season"];
  let gran = "month";

  const toggle = el(
    "div",
    { class: "scope-toggle" },
    grains.map((g, i) => el("button", { class: i === 1 ? "active" : "", onclick: () => setGran(g) }, g[0].toUpperCase() + g.slice(1)))
  );

  const card = el("div", { class: "card" }, [
    el("div", { class: "sec" }, "Trends"),
    el("div", { class: "fbar" }, [toggle]),
    el("div", { class: "grid" }, [
      el("div", { class: "cw" }, el("canvas", { id: "tGF" })),
      el("div", { class: "cw" }, el("canvas", { id: "tGA" })),
      el("div", { class: "cw" }, el("canvas", { id: "tPIM" })),
      el("div", { class: "cw" }, el("canvas", { id: "tWins" })),
    ]),
  ]);
  view.appendChild(card);

  function draw() {
    const buckets = ts[gran] || [];
    const avgWindow = gran === "season" ? 1 : gran === "month" ? 2 : 3;
    if (!buckets.length) return;
    buildTrendChart("tGF", buckets, "gf", { title: "Goals For", color: "#1c8a4b", avgWindow });
    buildTrendChart("tGA", buckets, "ga", { title: "Goals Against", color: "#c0392b", avgWindow });
    buildTrendChart("tPIM", buckets, "pims", { title: "PIM", color: "#b06a10", avgWindow });
    buildTrendChart("tWins", buckets, "w", { title: "Wins", color: "#1d6fd6", avgWindow });
  }

  function setGran(next) {
    gran = next;
    toggle.querySelectorAll("button").forEach((b, i) => b.classList.toggle("active", grains[i] === gran));
    draw();
  }

  draw();
}

// ---------------------------------------------------------------------------
// Overview
// ---------------------------------------------------------------------------

function kpiCard(label, value, trendData) {
  const children = [el("div", { class: "label" }, label), el("div", { class: "value-row" }, [el("div", { class: "value" }, String(value))])];
  if (trendData) {
    children.push(el("div", { class: "spark-wrap" }, [sparkSpan(trendData.spark_svg), " ", momentumBadge(trendData.momentum, { compact: true })]));
  }
  return el("div", { class: "kpi-card" }, children);
}

// ---------------------------------------------------------------------------
// Insights
// ---------------------------------------------------------------------------


const INSIGHT_ICON = {
  hot_streak: "🔥", cold_streak: "❄️", scoring_leader: "🏆",
  goal_diff: "📊", win_streak: "🚀", pim_leader: "🥊", our_rank: "📍", rising: "📈", plus_minus: "🛡️",
};

function latestSeasonWithContent(dataBySeasonId, isEmptyFn) {
  const ids = Object.keys(dataBySeasonId).filter((id) => !isEmptyFn(dataBySeasonId[id])).sort((a, b) => Number(b) - Number(a));
  return ids[0] || Object.keys(dataBySeasonId).sort((a, b) => Number(b) - Number(a))[0];
}

function last5Dots(results) {
  return el("span", { class: "dots", "data-tip": results.length ? `Last ${results.length}: ${results.join(" ")}` : "No games yet" },
    results.map((r) => el("span", { class: r === "W" ? "w" : r === "L" ? "l" : "o" })));
}

// Standings: the league's own table for our division, our row highlighted; a team name scouts
// that team (Players tab, filtered). OTL is a point, exactly as the league counts it.
function standingsCard(standings, seasonId) {
  const s = standings[seasonId];
  if (!s) return null;
  const cols = [
    { key: "_rank", label: "#", sortable: false },
    { key: "name", label: "Team", render: (r) => el("a", { class: "plink", href: `#players?scope=league&team=${encodeURIComponent(r.name)}`,
        onclick: (e) => { e.preventDefault(); location.hash = `#players?scope=league&team=${encodeURIComponent(r.name)}`; } }, r.name) },
    { key: "gp", label: "GP" }, { key: "w", label: "W" }, { key: "l", label: "L" },
    { key: "otl", label: "OTL", tip: "OTL" }, { key: "pts", label: "PTS" },
    { key: "gf", label: "GF" }, { key: "ga", label: "GA" },
    { key: "diff", label: "Diff", render: (r) => r.diff == null ? "—" : (r.diff > 0 ? "+" : "") + r.diff },
    { key: "pims", label: "PIM" },
    { key: "last5", label: "Last 5", sortable: false, render: (r) => last5Dots(r.last5 || []) },
  ];
  const rows = s.rows.map((r, i) => ({ ...r, _rank: i + 1 }));
  const table = el("table", { class: "standings" }, [
    el("thead", {}, el("tr", {}, cols.map((c) => c.tip ? tipTh(c.label, c.tip) : el("th", {}, c.label)))),
    el("tbody", {}, rows.map((r) => el("tr", { class: r.is_us ? "row-us" : "" }, cols.map((c) =>
      el("td", {}, c.render ? c.render(r) : r[c.key] == null ? "—" : String(r[c.key])))))),
  ]);
  return el("div", { class: "table-scroll" }, table);
}

async function renderOverview() {
  const view = document.getElementById("view-overview");
  view.innerHTML = "";
  const [summary, ourLb, standings, insights, outliers, teamPace] = await Promise.all([
    loadJSON("team_summary.json"), loadJSON("player_leaderboards.json"), loadJSON("standings.json"),
    loadJSON("league_insights.json"), loadJSON("league_outliers.json"), loadJSON("team_pace.json"),
  ]);
  await ensureSpotlightIds();
  const o = summary.overall;
  const streak = summary.current_streak;
  const form = summary.recent_form || {};

  // Season picker drives standings, notable and (as its Season grain) trends. Default: the latest
  // season with any games; pre-season, the table still lists the division.
  const seasonIds = Object.keys(standings).sort((a, b) => Number(b) - Number(a));
  let seasonId = seasonIds.find((id) => standings[id].rows.some((r) => r.gp)) || seasonIds[0];
  const seasonSel = el("select", { id: "ov-season" }, seasonIds.map((id) => el("option", { value: id }, standings[id].season_label)));
  seasonSel.value = seasonId;

  const thisSeason = (id) => summary.by_season[id] || {};
  const kpis = el("div", { class: "kpi-grid grid" });
  const standingsBody = el("div");
  const card = el("div", { class: "card" }, [
    el("div", { class: "sec", id: "ov-title" }),
    el("div", { class: "fbar" }, [el("label", {}, "Season"), seasonSel, el("span", { class: "muted small" }, "Standings are the league's official table; OTL counts as a point.")]),
    kpis, standingsBody,
  ]);
  view.appendChild(card);

  // Trends + pace share one card: the same grains, and the division's cumulative goal diff sits
  // beside ours so "are we on pace" is one look.
  await renderTrendsCard(view);
  const trendsCard = view.lastElementChild;
  const paceBody = el("div", { style: "margin-top:0.6rem" });
  trendsCard.appendChild(paceBody);

  const notableBody = el("div");
  view.appendChild(el("div", { class: "card" }, [
    el("div", { class: "sec" }, "Notable right now"),
    el("p", { class: "muted small" }, "One list, ours and theirs: streaks, leaders, who's rising, and who's carrying the tagged +/−. Everything is computed from the scoresheets."),
    notableBody,
  ]));

  function draw() {
    const st = standings[seasonId];
    const rank = st.rows.findIndex((r) => r.is_us) + 1;
    const mine = st.rows.find((r) => r.is_us) || {};
    document.getElementById("ov-title").replaceChildren(`${st.season_label} · ${st.level_label || "Division"}`);
    kpis.replaceChildren(
      kpiCard("This season", mine.gp ? `${mine.w}-${mine.l}-${mine.otl || 0}` : "—"),
      kpiCard("Place", mine.gp ? `${ordinal(rank)} of ${st.rows.length}` : `${st.rows.length} teams`),
      kpiCard("All-time", `${o.w}-${o.l}-${o.otl || 0}`),
      kpiCard("Goal diff", o.gf - o.ga >= 0 ? `+${o.gf - o.ga}` : String(o.gf - o.ga), form.goal_diff),
      kpiCard("Form", streak.result ? `${streak.length}${streak.result}` : "—", form.points_pace),
    );
    standingsBody.replaceChildren(standingsCard(standings, seasonId) || el("p", { class: "empty-state" }, "No standings for this season."));

    const teams = (teamPace[seasonId] || []).filter((t) => t.games.length);
    if (teams.length) {
      const paceRows = teams.map((t) => ({ name: t.name, is_us: t.is_us, diff: t.games[t.games.length - 1].cume_diff })).sort((a, b) => b.diff - a.diff);
      paceBody.replaceChildren(el("div", { class: "sec", style: "margin-top:0.4rem" }, "Cumulative goal differential, whole division"), divergingBarChart(paceRows, "diff", "name"));
    } else paceBody.replaceChildren();

    // Notable: the insight feed + our risers + tagged +/- leaders, de-duplicated by headline.
    const items = [];
    for (const i of (insights[seasonId] || {}).insights || []) items.push({ icon: INSIGHT_ICON[i.kind] || "•", head: i.headline, detail: i.detail });
    const lb = ourLb.by_season[seasonId] || [];
    for (const r of [...lb].filter((r) => r.games_played >= 3 && r.momentum.value > 0.3).sort((a, b) => b.momentum.value - a.momentum.value).slice(0, 3))
      items.push({ icon: "📈", head: `${r.name} is rising`, detail: `Momentum +${r.momentum.value.toFixed(2)}/gm · ${r.points} pts in ${r.games_played} GP`, pid: r.player_id });
    for (const r of [...lb].filter((r) => r.plus_minus_tagged != null && r.plus_minus_tagged > 0).sort((a, b) => b.plus_minus_tagged - a.plus_minus_tagged).slice(0, 2))
      items.push({ icon: "🛡️", head: `${r.name} is +${r.plus_minus_tagged} in tagged goals`, detail: "Best on the team where someone has tagged the film.", pid: r.player_id });
    const seen = new Set();
    notableBody.replaceChildren(...items.filter((i) => !seen.has(i.head) && seen.add(i.head)).map((i) =>
      el("div", { class: `insight-card${i.pid && state.spotlightIds.has(i.pid) ? " rcard-link" : ""}`, style: "display:flex;gap:0.7rem;padding:0.6rem 0;border-bottom:1px solid var(--bd)",
          onclick: i.pid && state.spotlightIds.has(i.pid) ? () => goSpotlight(i.pid, "overview") : null }, [
        el("div", { style: "font-size:1.2rem;line-height:1" }, i.icon),
        el("div", {}, [el("div", { style: "font-weight:600" }, i.head), el("div", { class: "muted", style: "font-size:0.88em" }, i.detail)]),
      ])));
    if (!items.length) notableBody.replaceChildren(el("p", { class: "empty-state" }, "Nothing yet — not enough games this season."));
    syncHash("overview");
  }
  seasonSel.addEventListener("change", () => { seasonId = seasonSel.value; draw(); });
  state.routes.overview = {
    params: () => ({ season: seasonId === seasonIds[0] ? "" : seasonId }),
    apply: (p) => { if (p.season && standings[p.season]) { seasonId = p.season; seasonSel.value = seasonId; } draw(); },
  };
  draw();
}

function ordinal(n) { const s = ["th", "st", "nd", "rd"], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); }

// ---------------------------------------------------------------------------
// Leaderboards (Our Team / Whole Division toggle)
// ---------------------------------------------------------------------------

function playerNameCell(r, fromView) {
  const cls = r.team && isUs(r.team) ? "is-us" : "";
  if (state.spotlightIds && state.spotlightIds.has(r.player_id)) {
    return el("a", { href: "#", class: `plink ${cls}`, "data-tip": "Open Player Spotlight",
      onclick: (e) => { e.preventDefault(); e.stopPropagation(); goSpotlight(r.player_id, fromView); } }, r.name);
  }
  return el("span", { class: cls }, r.name);
}

function leaderboardColumns(showTeam) {
  const cols = [
    { label: "Player", key: "name", render: (r) => playerNameCell(r, "leaderboards") },
  ];
  if (showTeam) cols.push({ label: "Team", key: "team", render: (r) => r.team || "" });
  cols.push(
    { label: "GP", key: "games_played", tip: TIPS.GP, render: (r) => String(r.games_played) },
    { label: "G", key: "goals", tip: TIPS.G, render: (r) => String(r.goals) },
    { label: "A1", key: "primary_assists", tip: TIPS.A1, render: (r) => String(r.primary_assists) },
    { label: "A2", key: "secondary_assists", tip: TIPS.A2, render: (r) => String(r.secondary_assists) },
    { label: "A", key: "assists", tip: TIPS.A, render: (r) => String(r.assists) },
    { label: "PTS", key: "points", tip: TIPS.PTS, render: (r) => String(r.points) },
    { label: "P/GP", key: "points_per_game", tip: TIPS["P/GP"], render: (r) => String(r.points_per_game) },
    { label: "Hat", key: "hat_tricks", tip: TIPS.Hat, render: (r) => String(r.hat_tricks) },
    { label: "PIM", key: "pims", tip: TIPS.PIM, render: (r) => String(r.pims) },
    {
      label: "+/−", key: "_pm", tip: TIPS["+/-"], sortValue: (r) => (r.plus_minus_tagged ? r.plus_minus_tagged.plus_minus : null),
      render: (r) => r.plus_minus_tagged
        ? el("span", { class: r.plus_minus_tagged.plus_minus > 0 ? "pct-hi" : r.plus_minus_tagged.plus_minus < 0 ? "pct-lo" : "", "data-tip": `${r.plus_minus_tagged.plus} for / ${r.plus_minus_tagged.minus} against over ${r.plus_minus_tagged.goals_tagged} tagged goals` },
            `${r.plus_minus_tagged.plus_minus > 0 ? "+" : ""}${r.plus_minus_tagged.plus_minus}`)
        : el("span", { class: "muted" }, "—"),
    },
    {
      label: "Momentum", key: "_momentum", tip: TIPS.Momentum,
      sortValue: (r) => r.momentum.value,
      render: (r) => el("span", {}, [sparkSpan(r.spark_svg), " ", momentumBadge(r.momentum, { compact: true })]),
    }
  );
  return cols;
}

// ---------------------------------------------------------------------------
// Games (with box score viewer + correction form)
// ---------------------------------------------------------------------------

function pillFor(us, them, decidedIn) {
  // decidedIn: "OT" / "SO" from the schedule's score marker -- an OT loss is still an L in the
  // standings, but it's a point and worth seeing at a glance.
  const suffix = decidedIn ? ` (${decidedIn})` : "";
  if (us > them) return el("span", { class: "pill win", "data-tip": decidedIn ? `Won in ${decidedIn === "SO" ? "a shootout" : "overtime"}` : null }, `W${suffix}`);
  if (us < them) return el("span", { class: decidedIn ? "pill tie" : "pill loss", "data-tip": decidedIn ? `Lost in ${decidedIn === "SO" ? "a shootout" : "overtime"} — a point in the standings` : null }, `L${suffix}`);
  return el("span", { class: "pill tie" }, "T");
}

function buildCorrectionIssueUrl(gameId, goal, box) {
  // Team names rather than home/away: GitHub won't reliably pre-fill a dropdown, and the processor
  // works the side out from "Who scored" vs the two team names.
  const base = `https://github.com/${CONFIG.repo}/issues/new`;
  const scorer = goal.team === "home" ? box.home_name : box.away_name;
  const params = new URLSearchParams({
    template: "stat-correction.yml",
    title: `Stat correction: game ${gameId} — ${scorer} goal, P${goal.period} ${goal.time}`,
    game_id: String(gameId), scoring_team_name: scorer, home_team_name: box.home_name, away_team_name: box.away_name,
    period: goal.period, time: goal.time,
  });
  return `${base}?${params.toString()}`;
}

// Film deep links: data/film_sync.json maps each scoresheet goal to a video timestamp (found by
// watching the scoreboard's score change on the game film -- see scripts/film_sync.py). Loaded
// once, shared by the box score and every Spotlight game log.
async function ensureFilmSync() {
  if (state.filmSync) return state.filmSync;
  try { state.filmSync = await loadJSON("film_sync.json"); } catch { state.filmSync = {}; }
  return state.filmSync;
}

function youtubeAt(url, seconds) {
  const u = new URL(url);
  u.searchParams.set("t", `${Math.max(0, Math.round(seconds))}s`);
  return u.toString();
}

function filmLinkForGoal(gameId, goal) {
  const sync = state.filmSync && state.filmSync[String(gameId)];
  if (!sync) return null;
  const match = sync.goals.find((g) => g.team === goal.team && g.period === goal.period && g.time === goal.time);
  if (!match || match.video_t == null) return null;
  const mm = Math.floor(match.video_t / 60), ss = String(match.video_t % 60).padStart(2, "0");
  const approx = match.method === "estimate";
  const tip = match.method === "manual" ? "Hand-anchored timestamp"
    : approx ? "Approximate — no scoreboard sync for this game yet, so this is a linear guess. Scrub forward a few minutes; when you find it, use “Tag on-ice” to pin the exact second."
    : `Found from the scoreboard changing on film (between ${Math.round(match.bracket[0])}s and ${Math.round(match.bracket[1])}s) — link starts a little early.`;
  return el("a", { class: `film-link${approx ? " film-approx" : ""}`, href: youtubeAt(sync.url, match.video_t), target: "_blank", rel: "noopener", "data-tip": tip, onclick: (e) => e.stopPropagation() }, `${approx ? "~" : ""}▶ ${mm}:${ss}`);
}

// One tiny ▶ per goal, right next to the score, ours or theirs -- click to watch that goal.
function goalLinks(g, ours) {
  const sync = state.filmSync && state.filmSync[String(g.game_id)];
  if (!sync) return null;
  const side = (g.is_home === ours) ? "home" : "away";
  const links = sync.goals.filter((x) => x.team === side && x.video_t != null).map((x) =>
    el("a", { class: `goal-dot ${ours ? "ours" : "theirs"}${x.method === "estimate" ? " approx" : ""}`, href: youtubeAt(sync.url, x.video_t), target: "_blank", rel: "noopener",
      "data-tip": `P${x.period} ${x.time}${x.scorer_number != null ? " · #" + x.scorer_number : ""} — ${x.method === "estimate" ? "approximate spot on film (scrub nearby)" : "watch this goal"}`, onclick: (e) => e.stopPropagation() }, "▶"));
  return links.length ? el("span", { class: "goal-dots" }, links) : null;
}

function filmLinkForGame(gameId) {
  const sync = state.filmSync && state.filmSync[String(gameId)];
  if (!sync) return null;
  return el("a", { class: "film-link", href: sync.url, target: "_blank", rel: "noopener", "data-tip": `${sync.matched}/${sync.total} goals linked on film`, onclick: (e) => e.stopPropagation() }, "🎬");
}

// "13:33" -> 813, "1:02:15" -> 3735, "813" -> 813. null if it doesn't parse.
function parseVideoTime(text) {
  const t = String(text || "").trim();
  if (!t) return null;
  if (/^\d+$/.test(t)) return Number(t);
  const parts = t.split(":").map((x) => x.trim());
  if (parts.length < 2 || parts.length > 3 || parts.some((x) => !/^\d{1,2}$/.test(x))) return null;
  return parts.reduce((acc, x) => acc * 60 + Number(x), 0);
}

function buildOnIceIssueUrl(gameId, goal, box, sides, videoT) {
  const scorer = goal.team === "home" ? box.home_name : box.away_name;
  const params = new URLSearchParams({
    template: "on-ice-tag.yml", title: `On-ice tag: game ${gameId} — ${scorer} goal, P${goal.period} ${goal.time}`,
    game_id: String(gameId), scoring_team_name: scorer, period: goal.period, time: goal.time,
    home_team_name: box.home_name, away_team_name: box.away_name,
  });
  if (sides.home) params.set("on_ice_home", sides.home.join(", "));
  if (sides.away) params.set("on_ice_away", sides.away.join(", "));
  if (videoT != null && videoT !== "") params.set("video_t", String(videoT));
  return `https://github.com/${CONFIG.repo}/issues/new?${params.toString()}`;
}

function onIceForm(gameId, goal, box, existing) {
  // Both benches side by side, one submit. Tagging the opponent too is what gives THEM a +/- in
  // our games (their "vs us" line). Team names only -- nobody thinks in home/away at the rink.
  const ourSide = isUs(box.home_name) ? "home" : isUs(box.away_name) ? "away" : null;
  const wrap = el("div", { class: "correction-form onice-form" });
  const videoIn = el("input", { type: "text", placeholder: "e.g. 13:33", style: "width:8rem", inputmode: "numeric" });
  const videoEcho = el("span", { class: "muted small" });
  videoIn.addEventListener("input", () => {
    const secs = parseVideoTime(videoIn.value);
    videoEcho.textContent = videoIn.value.trim() ? (secs == null ? "  ← use mm:ss" : `  = ${secs}s`) : "";
  });
  const cols = {}, counts = {};
  for (const side of ["home", "away"]) {
    const teamName = side === "home" ? box.home_name : box.away_name;
    const roster = (box.rosters[teamName] || []).filter((p) => p.number != null && p.position !== "G").sort((a, b) => a.number - b.number);
    const pre = new Set(((existing && existing.on_ice && existing.on_ice[side]) || []));
    counts[side] = el("span", { class: "muted small" }, pre.size ? `${pre.size} selected` : "");
    cols[side] = el("div", { class: "onice-col" }, [
      el("div", { class: "onice-head" }, [
        el("span", { class: side === ourSide ? "is-us" : "" }, [teamName, side === goal.team ? el("span", { class: "muted" }, " · scored") : null]),
        counts[side],
      ]),
      el("div", { class: "onice-grid" }, roster.map((p) => el("label", { class: "onice-player" }, [
        el("input", { type: "checkbox", value: String(p.number), checked: pre.has(p.number) ? "" : null }),
        el("span", { class: "num" }, `#${p.number}`), " ", p.name,
      ]))),
    ]);
  }
  const msg = el("span", { class: "muted small" });
  const picked = (side) => [...cols[side].querySelectorAll("input[type=checkbox]:checked")].map((c) => Number(c.value));
  wrap.addEventListener("change", () => {
    for (const side of ["home", "away"]) { const n = picked(side).length; counts[side].textContent = n ? `${n} selected` : ""; }
  });
  const submit = el("button", { onclick: () => {
    const sides = {};
    for (const side of ["home", "away"]) {
      const nums = picked(side);
      if (nums.length) {
        if (nums.length < 3 || nums.length > 6) { msg.textContent = `${side === "home" ? box.home_name : box.away_name}: pick 3-6 skaters (or none).`; return; }
        sides[side] = nums;
      }
    }
    if (!Object.keys(sides).length) { msg.textContent = "Pick the skaters on the ice for at least one team."; return; }
    const secs = parseVideoTime(videoIn.value);
    if (videoIn.value.trim() && secs == null) { msg.textContent = "Video time should look like 13:33."; return; }
    window.open(buildOnIceIssueUrl(gameId, goal, box, sides, secs), "_blank");
  } }, "Open GitHub issue to submit");
  wrap.append(
    el("label", {}, "Skaters on the ice when it went in — both benches if you can, ours at minimum"),
    el("div", { class: "onice-cols" }, ourSide === "away" ? [cols.away, cols.home] : [cols.home, cols.away]),
    el("label", {}, "▶ link landed on the wrong moment? Time in the video where it went in (optional)"), el("div", {}, [videoIn, videoEcho]),
    el("div", { style: "margin-top:0.4rem" }, [submit, " ", msg]),
  );
  return wrap;
}

function onIceSummary(goal, box, existing) {
  if (!existing || !existing.on_ice) return null;
  const parts = [];
  for (const [side, nums] of Object.entries(existing.on_ice)) {
    const teamName = side === "home" ? box.home_name : box.away_name;
    const sign = side === goal.team ? "+" : "−";
    parts.push(el("span", { class: `onice-tag ${side === goal.team ? "plus" : "minus"}`, "data-tip": `${teamName}: ${nums.map((n) => "#" + n).join(" ")} — each gets a ${sign}1 (unless it was a PP goal)` },
      `${sign} ${teamName}: ${nums.map((n) => "#" + n).join(" ")}`));
  }
  return el("div", { class: "onice-summary" }, parts);
}

function renderGoal(gameId, goal, rosterByNumber, box) {
  const scorer = goal.scorer_number != null ? rosterByNumber[goal.scorer_number] || `#${goal.scorer_number}` : "Unknown";
  const a1 = goal.assist1_number != null ? rosterByNumber[goal.assist1_number] || `#${goal.assist1_number}` : null;
  const a2 = goal.assist2_number != null ? rosterByNumber[goal.assist2_number] || `#${goal.assist2_number}` : null;
  const corrections = goal._corrections || {};

  const badge = (field, label) =>
    corrections[field]
      ? el("span", { class: "corrected-badge", title: `Was ${corrections[field].original}. ${corrections[field].reason || ""}` }, ` ✎ ${label} corrected`)
      : null;

  const detailLine = el("div", {}, [
    filmLinkForGoal(gameId, goal), filmLinkForGoal(gameId, goal) ? " " : "",
    el("strong", {}, scorer), badge("scorer_number", "scorer"),
    a1 ? "  (assist: " : "", a1, badge("assist1_number", "assist"),
    a2 ? ", " : "", a2, a2 ? badge("assist2_number", "assist") : "",
    a1 ? ")" : "", goal.situation ? ` [${goal.situation}]` : "",
  ]);

  const existingTag = (box && box.on_ice_tags || []).find((t) => t.team === goal.team && t.period === goal.period && t.time === goal.time);
  const tagBtn = el("button", { class: "suggest-fix-link" }, existingTag ? "Edit on-ice tag" : "Tag on-ice");
  const tagForm = box ? onIceForm(gameId, goal, box, existingTag) : null;
  if (tagForm) tagBtn.addEventListener("click", () => tagForm.classList.toggle("open"));

  const formId = `fix-${gameId}-${goal.period}-${goal.time}`.replace(/[^a-zA-Z0-9-]/g, "");
  const toggleBtn = el("button", { class: "suggest-fix-link" }, "Suggest a fix");
  const form = el("div", { class: "correction-form", id: formId }, [
    el("label", {}, "Field to correct"),
    el("select", { id: `${formId}-field` }, [
      el("option", { value: "scorer_number" }, "Scorer"),
      el("option", { value: "assist1_number" }, "Primary assist"),
      el("option", { value: "assist2_number" }, "Secondary assist"),
    ]),
    el("label", {}, "Corrected jersey #"),
    el("input", { id: `${formId}-value`, type: "number" }),
    el("label", {}, "Reason"),
    el("textarea", { id: `${formId}-reason`, rows: "2" }),
    el(
      "button",
      {
        onclick: () => {
          const field = document.getElementById(`${formId}-field`).value;
          const value = document.getElementById(`${formId}-value`).value;
          const reason = document.getElementById(`${formId}-reason`).value;
          const original = field === "scorer_number" ? goal.scorer_number : field === "assist1_number" ? goal.assist1_number : goal.assist2_number;
          const url = new URL(buildCorrectionIssueUrl(gameId, goal, box));
          url.searchParams.set("field", field.replace("_number", ""));
          url.searchParams.set("original", original ?? "");
          url.searchParams.set("corrected", value);
          url.searchParams.set("reason", reason);
          window.open(url.toString(), "_blank");
        },
      },
      "Open GitHub issue to submit"
    ),
  ]);
  toggleBtn.addEventListener("click", () => form.classList.toggle("open"));

  return el("div", { class: "box-score-goal" }, [el("div", {}, `P${goal.period}`), el("div", {}, goal.time),
    el("div", {}, [detailLine, onIceSummary(goal, box, existingTag), tagBtn, " ", toggleBtn, tagForm, form])]);
}

async function openBoxScore(gameId, container) {
  const [box] = await Promise.all([loadJSON(`games/${gameId}.json`), ensureFilmSync()]);
  container.innerHTML = "";
  const awayRoster = Object.fromEntries((box.rosters[box.away_name] || []).filter((p) => p.number != null).map((p) => [p.number, p.name]));
  const homeRoster = Object.fromEntries((box.rosters[box.home_name] || []).filter((p) => p.number != null).map((p) => [p.number, p.name]));
  const goalsByTeam = { away: box.goals.filter((g) => g.team === "away"), home: box.goals.filter((g) => g.team === "home") };

  if (box.tag_coverage || state.filmSync[String(gameId)]) {
    const cov = box.tag_coverage;
    const sync = state.filmSync[String(gameId)];
    container.appendChild(el("p", { class: "muted small", style: "margin:0 0 0.5rem" }, [
      sync ? `🎬 ${sync.matched}/${sync.total} goals linked on film${sync.goals.some((g) => g.method === "estimate") ? " (approximate — pin exact times with Tag on-ice)" : ""}. ` : "",
      cov ? `${cov.tagged}/${cov.total} goals have on-ice tags (+/−). ` : "No on-ice tags yet — click ▶ on a goal, then “Tag on-ice”. ",
    ]));
  }
  container.appendChild(
    el("div", { class: "grid" }, [
      el("div", {}, [
        el("h3", {}, `${box.away_name} (${box.away_final})`),
        ...goalsByTeam.away.map((g) => renderGoal(gameId, g, awayRoster, box)),
        goalsByTeam.away.length ? null : el("p", { class: "empty-state" }, "No goals."),
      ]),
      el("div", {}, [
        el("h3", {}, `${box.home_name} (${box.home_final})`),
        ...goalsByTeam.home.map((g) => renderGoal(gameId, g, homeRoster, box)),
        goalsByTeam.home.length ? null : el("p", { class: "empty-state" }, "No goals."),
      ]),
    ])
  );
}

function gameResultLetter(g) {
  if (!g.is_final || g.home_final == null) return null;
  const us = g.is_home ? g.home_final : g.away_final;
  const them = g.is_home ? g.away_final : g.home_final;
  return us > them ? "W" : us < them ? "L" : "T";
}

function seasonGamesTable(games) {
  // games: one season's rows, chronological. Ends in a totals row summing GF/GA/PIM and W-L-T.
  const totals = { gf: 0, ga: 0, pims: 0, w: 0, l: 0, t: 0 };
  const tbody = el("tbody");

  for (const g of games) {
    const us = g.is_home ? g.home_final : g.away_final;
    const them = g.is_home ? g.away_final : g.home_final;
    const result = gameResultLetter(g);
    if (result) {
      totals.gf += us; totals.ga += them; totals.pims += g.pims || 0;
      totals.w += result === "W" ? 1 : 0; totals.l += result === "L" ? 1 : 0; totals.t += result === "T" ? 1 : 0;
    }

    // pims is only ever set when a box score was actually loaded for this game (build_games skips it
    // otherwise) -- use that, not just is_final, to decide whether there's a box score to expand.
    // A handful of "final" games on the league site have no scoresheet at all (a data-entry gap),
    // and treating those as clickable would 404 silently when openBoxScore fetches a file that
    // was never generated for them.
    const hasBoxScore = g.pims != null;
    const detail = el("div", { class: "card", style: "display:none;" });
    const detailRow = el("tr", {}, el("td", { colspan: "7" }, detail));
    const row = el(
      "tr",
      { class: hasBoxScore ? "row-clickable" : "" },
      [
        el("td", {}, g.date),
        el("td", {}, [g.is_home ? "" : "@ ", g.opponent]),
        el("td", {}, result ? pillFor(us, them, g.decided_in) : el("span", { style: "color:var(--mu)" }, "—")),
        el("td", {}, result ? [String(us), goalLinks(g, true)] : "—"),
        el("td", {}, result ? [String(them), goalLinks(g, false)] : "—"),
        el("td", {}, g.pims != null ? String(g.pims) : "—"),
        el("td", {}, g.video ? el("a", { href: g.video.url, target: "_blank", rel: "noopener", onclick: (e) => e.stopPropagation() }, "🎬") : ""),
      ]
    );
    if (hasBoxScore) {
      const toggle = async (force) => {
        const showing = detail.style.display !== "none";
        const open = force == null ? !showing : force;
        if (open === showing) return;
        detail.style.display = open ? "block" : "none";
        if (open && !detail.dataset.loaded) {
          await openBoxScore(g.game_id, detail);
          detail.dataset.loaded = "1";
        }
        if (open) state.openGame = g.game_id;
        else if (state.openGame === g.game_id) state.openGame = null;
        syncHash("games");
      };
      row.addEventListener("click", () => toggle());
      state.gameRows = state.gameRows || {};
      state.gameRows[g.game_id] = { row, toggle };
    }
    tbody.appendChild(row);
    tbody.appendChild(detailRow);
  }

  tbody.appendChild(
    el("tr", { style: "font-weight:700;border-top:2px solid var(--bd)" }, [
      el("td", {}, "Total"),
      el("td", {}),
      el("td", {}, `${totals.w}-${totals.l}${totals.t ? "-" + totals.t : ""}`),
      el("td", {}, String(totals.gf)),
      el("td", {}, String(totals.ga)),
      el("td", {}, String(totals.pims)),
      el("td", {}),
    ])
  );

  return el("table", {}, [
    el("thead", {}, el("tr", {}, ["Date", "Opponent", "Result", "GF", "GA", "PIM", "Film"].map((h) => el("th", {}, h)))),
    tbody,
  ]);
}

async function renderGames() {
  const view = document.getElementById("view-games");
  view.innerHTML = "";
  const panes = { results: el("div"), h2h: el("div"), upcoming: el("div") };
  let pane = "results";
  const seg = el("div", { class: "scope-toggle", id: "games-seg" }, [
    el("button", { class: "active", onclick: () => setPane("results") }, "Results"),
    el("button", { onclick: () => setPane("h2h") }, "Head-to-Head"),
    el("button", { onclick: () => setPane("upcoming") }, "Upcoming"),
  ]);
  view.appendChild(el("div", { class: "card", style: "padding-bottom:0.4rem" }, [
    el("div", { class: "fbar", style: "margin:0" }, [seg, el("span", { class: "muted small" }, "Click a game for its box score; “Suggest a fix” and “Tag on-ice” live there.")]),
  ]));
  for (const p of Object.values(panes)) view.appendChild(p);

  const [index, h2h] = await Promise.all([loadJSON("games_index.json"), loadJSON("head_to_head.json"), ensureFilmSync()]);

  // --- Results: every game by season, newest first, each ending in a Total row.
  const bySeason = new Map();
  for (const g of [...index].sort((a, b) => (a.iso_date < b.iso_date ? -1 : a.iso_date > b.iso_date ? 1 : a.game_id - b.game_id))) {
    if (!bySeason.has(g.season_id)) bySeason.set(g.season_id, []);
    bySeason.get(g.season_id).push(g);
  }
  [...bySeason.keys()].sort((a, b) => b - a).forEach((seasonId, i) => {
    const games = bySeason.get(seasonId);
    panes.results.appendChild(el("details", { class: "card season-games", open: i === 0 ? "" : undefined }, [
      el("summary", { class: "sec" }, `${games[0].season_label} (${games.length} games)`),
      el("div", { class: "table-scroll", style: "margin-top:0.6rem" }, seasonGamesTable(games)),
    ]));
  });

  // --- Head-to-Head: one row per opponent, expandable to the meetings; "Next" bridges to Upcoming.
  const nextVs = {};
  for (const g of index) if (!g.is_final && !nextVs[g.opponent]) nextVs[g.opponent] = g;
  const rows = Object.entries(h2h).sort((a, b) => b[1].meetings.length - a[1].meetings.length);
  const h2hTable = el("table", {}, [el("thead", {}, el("tr", {}, ["Opponent", "GP", "Record", "GF", "GA", "Last 5", "Last meeting", "Next"].map((h) => el("th", {}, h))))]);
  const tb = el("tbody");
  for (const [opp, r] of rows) {
    const last = r.meetings[r.meetings.length - 1];
    const nxt = nextVs[opp];
    const detail = el("tr", { style: "display:none" }, el("td", { colspan: "8" }, el("div", { class: "table-scroll" }, el("table", {}, [
      el("thead", {}, el("tr", {}, ["Date", "Season", "Result", "Type"].map((h) => el("th", {}, h)))),
      el("tbody", {}, [...r.meetings].reverse().map((m) => el("tr", {}, [el("td", {}, m.date), el("td", {}, m.season_label), el("td", {}, [pillFor(m.us, m.them), ` ${m.us}-${m.them}`]), el("td", {}, m.game_type || "")]))),
    ]))));
    const row = el("tr", { class: "row-clickable", onclick: () => { detail.style.display = detail.style.display === "none" ? "" : "none"; } }, [
      el("td", {}, [opp, " ", el("a", { class: "muted small", href: `#players?scope=league&team=${encodeURIComponent(opp)}`, onclick: (e) => e.stopPropagation() }, "scout →")]),
      el("td", {}, String(r.meetings.length)),
      el("td", {}, `${r.w}-${r.l}${r.t ? "-" + r.t : ""}`),
      el("td", {}, String(r.gf)), el("td", {}, String(r.ga)),
      el("td", {}, last5Dots(r.meetings.slice(-5).map((m) => (m.us > m.them ? "W" : m.us < m.them ? "L" : "T")))),
      el("td", {}, last ? `${last.date} (${last.season_label}) ${last.us}-${last.them}` : "—"),
      el("td", {}, nxt ? `${nxt.date}` : el("span", { class: "muted" }, "—")),
    ]);
    tb.appendChild(row); tb.appendChild(detail);
  }
  h2hTable.appendChild(tb);
  panes.h2h.appendChild(el("div", { class: "card" }, [el("div", { class: "sec" }, "Head-to-Head, all seasons and both team names"), el("div", { class: "table-scroll" }, h2hTable)]));

  // --- Upcoming: the next games as a list, then the calendar (games + rink skates) and the sync link.
  const upcoming = index.filter((g) => !g.is_final).slice(0, 8);
  const upTable = el("table", {}, [el("thead", {}, el("tr", {}, ["Date", "Time", "Opponent", "Rink", "All-time vs them"].map((h) => el("th", {}, h))))]);
  upTable.appendChild(el("tbody", {}, upcoming.map((g) => {
    const r = h2h[g.opponent];
    return el("tr", {}, [
      el("td", {}, g.date), el("td", {}, g.time || ""), el("td", {}, [g.is_home ? "" : "@ ", g.opponent]), el("td", {}, (g.rink || "").replace("Baptist Health Iceplex ", "")),
      el("td", {}, r ? [`${r.w}-${r.l}${r.t ? "-" + r.t : ""}`, " ", el("a", { class: "muted small", href: `#players?scope=league&team=${encodeURIComponent(g.opponent)}` }, "scout →")] : el("span", { class: "muted" }, "never played")),
    ]);
  })));
  panes.upcoming.appendChild(el("div", { class: "card" }, [el("div", { class: "sec" }, "Next up"), upcoming.length ? el("div", { class: "table-scroll" }, upTable) : el("p", { class: "empty-state" }, "Nothing on the schedule yet.")]));
  panes.upcoming.appendChild(await calendarCard());
  panes.upcoming.appendChild(benchSyncCard());

  function setPane(next) {
    pane = next;
    seg.querySelectorAll("button").forEach((b, i) => b.classList.toggle("active", ["results", "h2h", "upcoming"][i] === next));
    for (const [k, p] of Object.entries(panes)) p.style.display = k === next ? "" : "none";
    syncHash("games");
  }
  state.routes.games = {
    params: () => ({ tab: pane === "results" ? "" : pane, game: pane === "results" && state.openGame ? state.openGame : "" }),
    apply: async (p) => {
      setPane(["h2h", "upcoming"].includes(p.tab) ? p.tab : "results");
      const target = state.gameRows && state.gameRows[Number(p.game)];
      if (!target) return;
      target.row.closest("details").open = true;
      await target.toggle(true);
      target.row.scrollIntoView({ block: "start", behavior: "smooth" });
    },
  };
  setPane("results");
}

// ---------------------------------------------------------------------------
// Head-to-head
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Schedule heatmap
// ---------------------------------------------------------------------------

function benchSyncCard() {
  const icsUrl = new URL("data/schedule.ics", location.href).href;
  const input = el("input", { type: "text", readonly: "", value: icsUrl, onclick: (e) => e.target.select() });
  const copyBtn = el("button", { class: "copy-ics-btn" }, "Copy link");
  copyBtn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(icsUrl);
      copyBtn.textContent = "Copied!";
    } catch {
      input.select();
      document.execCommand("copy");
      copyBtn.textContent = "Copied!";
    }
    setTimeout(() => (copyBtn.textContent = "Copy link"), 1500);
  });
  return el("div", { class: "card bench-sync" }, [
    el("div", { class: "sec" }, "Sync to Bench App"),
    el("p", { class: "muted" },
      "This link is a live calendar feed of our schedule, rebuilt daily straight from the league site -- " +
      "point Bench App at it once and new games, time changes, and rink changes show up automatically."),
    el("div", { class: "bench-sync-row" }, [input, copyBtn]),
    el("p", { class: "muted small" }, [
      "In Bench App: Schedule → Add → ",
      el("strong", {}, "Sync Schedule"),
      " → paste this link → Start Syncing (or Preview Syncing without PRO). ",
      el("a", { href: "https://help.benchapp.com/en/articles/7876954-sync-your-schedule-from-your-league", target: "_blank", rel: "noopener" }, "Bench App help →"),
    ]),
  ]);
}

function formatEventTime(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

// True month-grid calendar: our games plotted on their date, public rink events (Stick & Puck /
// pick-up hockey, already filtered server-side to just those) overlaid with a link back to the
// facility's own booking dashboard. Paged month-by-month rather than a flat list per the user's ask.

function localDateKey(d) {
  // yyyy-mm-dd in the viewer's own local calendar day -- never toISOString/slice, which is UTC and
  // can land a late-night game or event on the wrong day for anyone west of Greenwich.
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function calendarEntryForGame(g) {
  const result = gameResultLetter(g);
  const us = g.is_home ? g.home_final : g.away_final;
  const them = g.is_home ? g.away_final : g.home_final;
  const cls = result === "W" ? "win" : result === "L" ? "loss" : result === "T" ? "tie" : "upcoming";
  const label = result ? `${result} ${us}-${them}` : g.time || "TBD";
  const tip = `${g.is_home ? "vs" : "@"} ${g.opponent} · ${g.date}${g.time ? " " + g.time : ""}${g.rink ? " · " + g.rink : ""}`;
  return el("div", { class: `cal-entry game ${cls}`, "data-tip": tip }, `${g.is_home ? "" : "@"}${g.opponent} ${label}`);
}

function calendarEntryForEvent(e) {
  const text = `${formatEventTime(e.start)} ${e.title}`;
  const tip = `${e.title}${e.label ? " · " + e.label : ""} · ${formatEventTime(e.start)}–${formatEventTime(e.end)}`;
  if (e.dashboard_url) {
    return el("a", { class: "cal-entry event", href: e.dashboard_url, target: "_blank", rel: "noopener", "data-tip": tip }, text);
  }
  return el("div", { class: "cal-entry event", "data-tip": tip }, text);
}

function buildCalendarGrid(year, month, gamesByDate, eventsByDate) {
  const first = new Date(year, month, 1);
  const startOffset = first.getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const todayKey = localDateKey(new Date());

  const grid = el("div", { class: "cal-grid" });
  ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].forEach((d) => grid.appendChild(el("div", { class: "cal-dow" }, d)));
  for (let i = 0; i < startOffset; i++) grid.appendChild(el("div", { class: "cal-day other-month" }));

  for (let day = 1; day <= daysInMonth; day++) {
    const dateKey = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const cell = el("div", { class: `cal-day${dateKey === todayKey ? " today" : ""}` });
    cell.appendChild(el("div", { class: "cal-daynum" }, String(day)));
    for (const g of gamesByDate.get(dateKey) || []) cell.appendChild(calendarEntryForGame(g));
    for (const e of eventsByDate.get(dateKey) || []) cell.appendChild(calendarEntryForEvent(e));
    grid.appendChild(cell);
  }

  const trailing = (7 - ((startOffset + daysInMonth) % 7)) % 7;
  for (let i = 0; i < trailing; i++) grid.appendChild(el("div", { class: "cal-day other-month" }));
  return grid;
}

function monthAgendaList(year, month, gamesByDate) {
  const prefix = `${year}-${String(month + 1).padStart(2, "0")}`;
  const rows = [];
  for (const [dateKey, games] of gamesByDate) {
    if (dateKey.startsWith(prefix)) rows.push(...games);
  }
  rows.sort((a, b) => (a.iso_date < b.iso_date ? -1 : a.iso_date > b.iso_date ? 1 : a.game_id - b.game_id));
  if (!rows.length) return el("p", { class: "muted small" }, "No games this month.");

  const box = el("div");
  for (const g of rows) {
    const result = gameResultLetter(g);
    const us = g.is_home ? g.home_final : g.away_final;
    const them = g.is_home ? g.away_final : g.home_final;
    box.appendChild(
      el("div", { class: "game-list-item", style: "cursor:default" }, [
        el("div", {}, [`${g.date} · `, g.is_home ? "" : "@ ", g.opponent]),
        el("div", {}, result ? [pillFor(us, them, g.decided_in), ` ${us}-${them}`, g.pims != null ? ` · ${g.pims} PIM` : ""] : el("span", { class: "muted" }, g.time || "Upcoming")),
      ])
    );
  }
  return box;
}

async function calendarCard() {
  const index = await loadJSON("games_index.json");
  const gamesByDate = new Map();
  const chronological = [...index].filter((g) => g.iso_date).sort((a, b) => (a.iso_date < b.iso_date ? -1 : a.iso_date > b.iso_date ? 1 : a.game_id - b.game_id));
  for (const g of chronological) {
    if (!gamesByDate.has(g.iso_date)) gamesByDate.set(g.iso_date, []);
    gamesByDate.get(g.iso_date).push(g);
  }

  let events = [];
  try {
    events = await loadJSON("rink_events.json");
  } catch {
    /* no rink calendar configured -- games-only calendar is still useful */
  }
  const eventsByDate = new Map();
  for (const e of events) {
    const dateKey = e.start.slice(0, 10);
    if (!eventsByDate.has(dateKey)) eventsByDate.set(dateKey, []);
    eventsByDate.get(dateKey).push(e);
  }

  const today = new Date();
  const todayKey = localDateKey(today);
  const next = chronological.find((g) => g.iso_date >= todayKey);
  const anchorKey = next ? next.iso_date : chronological.length ? chronological[chronological.length - 1].iso_date : todayKey;
  const anchor = new Date(anchorKey + "T00:00:00");
  const cursor = { year: anchor.getFullYear(), month: anchor.getMonth() };

  const label = el("div", { class: "cal-month-label" });
  const gridWrap = el("div");
  const agendaWrap = el("div", { style: "margin-top:0.75rem" });

  function draw() {
    label.textContent = new Date(cursor.year, cursor.month, 1).toLocaleDateString([], { month: "long", year: "numeric" });
    gridWrap.innerHTML = "";
    gridWrap.appendChild(buildCalendarGrid(cursor.year, cursor.month, gamesByDate, eventsByDate));
    agendaWrap.innerHTML = "";
    agendaWrap.appendChild(el("div", { class: "sec" }, "This Month"));
    agendaWrap.appendChild(monthAgendaList(cursor.year, cursor.month, gamesByDate));
  }

  const prevBtn = el("button", { class: "cal-nav-btn" }, "‹ Prev");
  const nextBtn = el("button", { class: "cal-nav-btn" }, "Next ›");
  const todayBtn = el("button", { class: "cal-nav-btn" }, "Today");
  prevBtn.addEventListener("click", () => {
    cursor.month -= 1;
    if (cursor.month < 0) { cursor.month = 11; cursor.year -= 1; }
    draw();
  });
  nextBtn.addEventListener("click", () => {
    cursor.month += 1;
    if (cursor.month > 11) { cursor.month = 0; cursor.year += 1; }
    draw();
  });
  todayBtn.addEventListener("click", () => {
    cursor.year = today.getFullYear();
    cursor.month = today.getMonth();
    draw();
  });
  draw();

  return el("div", { class: "card" }, [
    el("div", { class: "cal-head" }, [el("div", { class: "sec" }, "Schedule Calendar"), el("div", { class: "cal-nav" }, [prevBtn, label, nextBtn, todayBtn])]),
    gridWrap,
    agendaWrap,
  ]);
}

// ---------------------------------------------------------------------------
// League outliers (division leaders + team pace)
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Scouting Report
// ---------------------------------------------------------------------------

async function renderScouting() {
  const view = document.getElementById("view-scouting");
  view.innerHTML = "";
  view.appendChild(
    pageIntro([
      "Auto-built for our ", strong("next scheduled game"),
      " — their form, who to watch, their whole roster graded on everything they've ever played, their goalie, and film of past meetings. ",
      "It rebuilds itself every night, so check it the day of. No one has to write it.",
    ])
  );
  const r = await loadJSON("scouting_report.json");
  await ensureSpotlightIds();

  if (!r.has_upcoming_game) {
    view.appendChild(el("div", { class: "card" }, el("p", { class: "empty-state" }, "No upcoming game found on the schedule right now.")));
    return;
  }

  const rec = r.opponent_record;
  const recStr = rec && rec.gp != null ? `${rec.w}-${rec.l}${rec.t ? "-" + rec.t : ""}${rec.otw || rec.otl ? ` (${rec.otw || 0}/${rec.otl || 0} OT)` : ""}` : "no record yet";

  view.appendChild(
    el("div", { class: "card" }, [
      el("div", { class: "scout-header" }, [
        el("div", { class: "opp-name" }, `vs ${r.opponent.name}`),
        el("div", { class: "meta" }, `${r.game.date} · ${r.game.time} · ${r.game.rink} · ${r.game.is_home ? "Home" : "Away"} · ${r.game.game_type}`),
      ]),
      r.stats_note ? el("p", { class: "empty-state", style: "margin-top:0.5rem" }, r.stats_note) : null,
      el("div", { class: "kpi-grid grid", style: "margin-top:0.75rem" }, [
        kpiCard("Their Record", recStr),
        kpiCard("Recent Form", r.recent_form.length ? r.recent_form.join(" ") : "—"),
        kpiCard("All-Time vs Us", r.head_to_head ? `${r.head_to_head.w}-${r.head_to_head.l}${r.head_to_head.t ? "-" + r.head_to_head.t : ""}` : "First meeting"),
        kpiCard("Level", r.opponent.level_label || "—"),
      ]),
    ])
  );

  if (r.keys_to_game && r.keys_to_game.length) {
    view.appendChild(
      el("div", { class: "card" }, [
        el("div", { class: "sec" }, "Keys to the Game"),
        el("ul", { class: "keys-list" }, [
          ...r.keys_to_game.map((k) => el("li", {}, k)),
          r.pim_leader ? el("li", {}, [strong("Discipline: "), `${r.pim_leader.name} leads ${r.opponent.name} with ${r.pim_leader.pims} PIM this tracked season.`]) : null,
          ...(r.goalies || []).map((g) => el("li", {}, [strong("Goalie: "), `${g.name} — ${g.gp} GP, ${g.w || 0}-${g.l || 0}, ${g.gaa ?? "—"} GAA, ${g.save_pct ?? "—"} SV%.`])),
        ]),
      ])
    );
  }

  if (r.top_threats && r.top_threats.length) {
    view.appendChild(
      el("div", { class: "card" }, [
        el("div", { class: "sec" }, "Players to Watch"),
        el(
          "div",
          {},
          r.top_threats.map((t, i) =>
            el("div", { class: "threat-row" }, [
              el("div", { class: "rank" }, String(i + 1)),
              el("div", {}, [
                el("div", {}, playerNameCell({ ...t, team: r.opponent.name }, "scouting")),
                el("div", { style: "color:var(--mu);font-size:0.85em" }, `${t.goals}G ${t.assists}A · ${t.games_played} GP`),
              ]),
              el("div", {}, String(t.points) + " pts"),
              el("div", {}, [sparkSpan(t.spark_svg), " ", momentumBadge(t.momentum, { compact: true })]),
            ])
          )
        ),
      ])
    );
  }

  const when = await whenGoalsHappenCard([r.opponent.name], `When ${r.opponent.name} Score (and Get Scored On)`);
  if (when) view.appendChild(when);
  view.appendChild(await opponentRosterCard(r.opponent.name));

  if (r.head_to_head && r.head_to_head.meetings && r.head_to_head.meetings.length) {
    const table = el("table", {}, [el("thead", {}, el("tr", {}, ["Date", "Season", "Result"].map((h) => el("th", {}, h))))]);
    const tbody = el("tbody");
    for (const m of [...r.head_to_head.meetings].reverse()) {
      tbody.appendChild(el("tr", {}, [el("td", {}, m.date), el("td", {}, m.season_label), el("td", {}, [pillFor(m.us, m.them), ` ${m.us}-${m.them}`])]));
    }
    table.appendChild(tbody);
    view.appendChild(el("div", { class: "card" }, [el("div", { class: "sec" }, "Past Meetings"), el("div", { class: "table-scroll" }, table)]));
  }

  if (r.past_films && r.past_films.length) {
    view.appendChild(
      el("div", { class: "card" }, [
        el("div", { class: "sec" }, "Game Film vs This Opponent"),
        el(
          "div",
          { class: "rstrip" },
          [...r.past_films].reverse().map((f) =>
            el("a", { class: "rcard film-card", href: f.url, target: "_blank", rel: "noopener" }, [
              el("div", {}, [pillFor(f.us, f.them), ` ${f.us}-${f.them}`]),
              el("div", { class: "name" }, `${f.date} · ${f.season_label}`),
              el("div", { class: "team" }, "🎬 Watch"),
            ])
          )
        ),
      ])
    );
  }
}

// ---------------------------------------------------------------------------
// Players (roster grid) -> Player Spotlight drill-in
//
// The Spotlight is the one destination every player name on the site leads to. It pulls a
// skater's stats from EVERY league and team on the league site (not just our division), places
// each stint in its division, and rolls that up into a caliber grade -- "what level of hockey
// player is this, really?" -- per the design template's single-entity detail layout: window KPI
// cards, one combo chart, small multiples, a stint table, and a recent log.
// ---------------------------------------------------------------------------

// Tier -> theme token, so bars and badges match the palette in both light and dark mode. Resolved
// to literal colors at draw time because Chart.js can't read CSS variables itself.
const TIER_VAR = { D: "--mu", C3: "--bl", C2: "--gn", C1: "--or", B: "--pu", A: "--rd" };
const TIER_ORDER = Object.keys(TIER_VAR);

function tierColor(tier) {
  const v = TIER_VAR[tier];
  if (!v) return "rgba(128,128,128,0.35)";
  return getComputedStyle(document.body).getPropertyValue(v).trim() || "#8b949e";
}

function caliberBadge(caliber, { compact = false } = {}) {
  if (!caliber) return el("span", { class: "cal-badge cal-none", "data-tip": TIPS.Caliber }, "Ungraded");
  const cls = `cal-${caliber.tier.replace("/", "")}`;
  const text = compact ? caliber.tier : caliber.label;
  return el("span", { class: `cal-badge ${cls}`, "data-tip": TIPS.Caliber, style: `--tier:${tierColor(caliber.tier)}` }, [
    text,
    el("span", { class: "cal-conf", "data-tip": TIPS.Confidence }, caliber.confidence[0].toUpperCase()),
  ]);
}

function trajectoryBadge(traj) {
  if (!traj || traj.direction === "flat") return null;
  const up = traj.direction === "rising";
  return el("span", { class: `mb ${up ? "mb-hi" : "mb-lo"}`, "data-tip": `${TIPS.Trajectory} Here: ${traj.earlier.toFixed(2)} → ${traj.recent.toFixed(2)}.` }, up ? "↗ rising" : "↘ fading");
}

function vsUsLine(v) {
  if (!v || !v.gp) return null;
  const rec = `${v.our_w}-${v.our_l}${v.our_t ? "-" + v.our_t : ""}`;
  const hot = v.points_per_game >= 1;
  return el("div", { class: `vsus${hot ? " vsus-hot" : ""}`, "data-tip": TIPS["vs Us"] }, [
    strong("vs us: "), `${v.goals}G ${v.assists}A in ${v.gp} GP (${v.points_per_game.toFixed(2)} P/GP) · we're ${rec}`,
  ]);
}

function fitBadge(fit) {
  if (!fit) return null;
  const cls = fit.direction === "above" ? "mb-hi" : fit.direction === "below" ? "mb-lo" : "mb-md";
  const arrow = fit.direction === "above" ? "▲" : fit.direction === "below" ? "▼" : "►";
  const label = fit.direction === "above" ? "plays up" : fit.direction === "below" ? "depth" : "level";
  return el("span", { class: `mb ${cls}`, "data-tip": TIPS.Fit }, `${arrow} ${label}`);
}

function teamChips(teams) {
  return el("div", { class: "chips" }, teams.map((t) =>
    el("span", { class: `chip${t.is_us ? " chip-us" : ""}` }, [
      t.team,
      t.level_label ? el("span", { class: "chip-mu" }, ` · ${t.level_label.replace("Adult ", "")}`) : null,
      t.league_label ? el("span", { class: "chip-mu" }, ` · ${t.league_label}`) : null,
    ])
  ));
}

function positionChip(position) {
  if (!position) return null;
  return el("span", { class: `pos-chip pos-${position}`, "data-tip": TIPS.Position }, position);
}

function monthYear(iso) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString([], { month: "short", year: "numeric" });
}

function tenureLine(r) {
  // "Since Oct 2024 · 5 seasons · 72% BH Adult · 55% D"
  const t = r.tenure, m = r.league_mix;
  if (!t || !m) return null;
  const leagueName = Object.keys(m.by_league)[0] || "";
  const mixTip = "Share of all their games, every league: " + Object.entries(m.by_league).map(([l, n]) => `${l} ${Math.round(100 * n / m.games)}%`).join(" · ");
  return el("div", { class: "tenure" }, [
    el("span", { "data-tip": TIPS.Tenure }, `Since ${monthYear(t.first_date)} · ${t.seasons} season${t.seasons === 1 ? "" : "s"}`),
    " · ",
    el("span", { "data-tip": mixTip }, `${m.our_league_pct}% our league`),
    " · ",
    el("span", { "data-tip": TIPS["D %"] }, `${m.d_pct}% in D`),
    el("span", { class: "mix-bar", "data-tip": mixTip }, [
      el("span", { class: "mix-ours", style: `width:${m.our_league_pct}%` }),
    ]),
  ]);
}

function playerCard(r, fromView, rank) {
  const card = el("div", { class: `pcard scard${r.is_ours ? " pcard-ours" : ""}`, onclick: () => goSpotlight(r.player_id, fromView) }, [
    el("div", { class: "pcard-top" }, [
      el("div", { class: "name" }, [rank ? el("span", { class: "rank" }, `#${rank} `) : null, r.name, " ", positionChip(r.position)]),
      caliberBadge(r.caliber, { compact: true }),
    ]),
    el("div", { class: "team" }, r.current_teams.length
      ? r.current_teams.map((t) => `${t.team}${t.level_label ? " (" + t.level_label.replace("Adult ", "") + ")" : ""}`).join(" · ")
      : "No current team"),
    el("div", { class: "pcard-stats" }, [
      el("span", {}, [strong(String(r.points_per_game.toFixed(2))), " P/GP"]),
      el("span", { class: "muted" }, `${r.points} pts · ${r.gp} GP`),
    ]),
    tenureLine(r),
    vsUsLine(r.vs_us),
    r.plus_minus ? el("div", { class: `vsus${r.plus_minus.plus_minus < 0 ? " vsus-hot" : ""}`, "data-tip": TIPS["+/-"] }, [
      strong(`${r.is_ours ? "+/−" : "+/− vs us"}: `), `${r.plus_minus.plus_minus > 0 ? "+" : ""}${r.plus_minus.plus_minus}`,
      el("span", { class: "muted" }, ` (${r.plus_minus.plus} for / ${r.plus_minus.minus} against, ${r.plus_minus.goals_tagged} tagged)`),
    ]) : null,
    el("div", { class: "spark-wrap" }, [sparkSpan(r.spark_svg), " ", momentumBadge(r.momentum, { compact: true }), " ", fitBadge(r.fit), " ", trajectoryBadge(r.trajectory)]),
  ]);
  return card;
}

async function renderPlayers() {
  const view = document.getElementById("view-players");
  view.innerHTML = "";
  const grid = el("div", { id: "players-grid" });
  const detail = el("div", { id: "players-detail", style: "display:none" });
  view.appendChild(grid);
  view.appendChild(detail);

  grid.appendChild(
    pageIntro([
      "Every skater who's ever appeared in our division — us, every opponent, one-night fill-ins — graded on ",
      strong("everything they've played"), ": every team, in both adult leagues on the league site. ",
      "The badge is the ", strong("caliber grade"), " (D → C3 → C2 → C1 → B → A): where their production ranks in each division they've played in, ",
      "rolled up across all of it. Sorted best-first. Filter by ", strong("position"), " to rank defensemen against defensemen ",
      "(positions are hand-entered — the league site doesn't record them). Pick a ", strong("team"),
      " to scout it: their roster this season, each player graded on everything they've ever played.",
    ])
  );

  const index = await loadJSON("players_index.json");
  if (!index.length) {
    grid.appendChild(el("div", { class: "card" }, el("p", { class: "empty-state" }, "No player profiles yet — re-run scrape.py and build_site_data.py.")));
    return;
  }

  let scope = "current";
  let sortKey = "caliber";
  let query = "";
  const scopes = ["current", "ours", "league"];
  const scopeToggle = el("div", { class: "scope-toggle" }, [
    el("button", { class: "active", onclick: () => setScope("current") }, "Our Roster"),
    el("button", { onclick: () => setScope("ours") }, "Ever Ours"),
    el("button", { onclick: () => setScope("league") }, "Whole League"),
  ]);
  const search = el("input", { type: "search", id: "player-search", placeholder: "Search a name…",
    oninput: (e) => { query = e.target.value.trim().toLowerCase(); draw(); } });
  const count = el("span", { class: "muted small" });

  // Position + team filters. Positions are hand-maintained in data/positions.json (the league site
  // records none), so "Unknown" is a real bucket, not an error state. Picking a position re-ranks
  // the grid within that position -- the # on each card is its rank in the current view.
  let posFilter = "all";
  let teamFilter = "all";
  let teamNow = true;  // scouting default: the team's roster this season, not everyone who ever wore the jersey
  const posSel = el("select", { id: "player-pos", onchange: (e) => { posFilter = e.target.value; draw(); } }, [
    el("option", { value: "all" }, "All positions"),
    el("option", { value: "F" }, "Forwards"),
    el("option", { value: "D" }, "Defense"),
    el("option", { value: "none" }, "Unknown"),
  ]);
  // Only teams in our division: a player's C3 / other-league stints are on their Spotlight, but the
  // filter is for "who has skated for X in our league".
  const teamCounts = new Map();
  for (const r of index) for (const t of r.division_teams || []) teamCounts.set(t, (teamCounts.get(t) || 0) + 1);
  const teamSel = el("select", { id: "player-team", onchange: (e) => {
    teamFilter = e.target.value;
    if (teamFilter !== "all" && scope !== "league") setScope("league");  // scouting a team means looking past our own roster
    else draw();
  } }, [
    el("option", { value: "all" }, "All division teams"),
    ...[...teamCounts.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([t, n]) => el("option", { value: t }, `${t} (${n})`)),
  ]);
  const nowBox = el("input", { type: "checkbox", id: "player-team-now", checked: "", onchange: (e) => { teamNow = e.target.checked; draw(); } });
  const nowLabel = el("label", { for: "player-team-now", "data-tip": "On: only that team's roster this season. Off: everyone who has ever skated for them in our division." }, [nowBox, " this season"]);
  const sortSel = el("select", { onchange: (e) => { sortKey = e.target.value; draw(); } }, [
    el("option", { value: "caliber" }, "Caliber"),
    el("option", { value: "ppg" }, "P/GP (all leagues)"),
    el("option", { value: "l10" }, "P/GP last 10"),
    el("option", { value: "momentum" }, "Momentum"),
    el("option", { value: "gp" }, "Games played"),
  ]);
  // Cards (caliber, all-time, from players_index) or Table (the season leaderboards -- every
  // column, sortable). Same scope buttons drive both; Season applies to the table.
  let viewMode = "cards";
  const [ourLb, divisionLb] = await Promise.all([loadJSON("player_leaderboards.json"), loadJSON("division_leaderboards.json")]);
  const seasonKeys = Object.keys(ourLb.by_season).sort((a, b) => Number(b) - Number(a));
  const seasonSel = el("select", { id: "player-season", onchange: () => draw() }, [
    el("option", { value: "career" }, "All-time"),
    ...seasonKeys.map((k) => el("option", { value: k }, (ourLb.by_season[k][0] && ourLb.by_season[k][0].season_label) || `Season ${k}`)),
  ]);
  const modeToggle = el("div", { class: "scope-toggle", id: "player-mode", style: "margin-left:auto" }, [
    el("button", { class: "active", onclick: () => setMode("cards") }, "Cards"),
    el("button", { onclick: () => setMode("table") }, "Table"),
  ]);
  const body = el("div", { class: "pgrid" });
  const tableBody = el("div", { class: "table-scroll", style: "display:none" });
  grid.appendChild(el("div", { class: "card" }, [
    el("div", { class: "sec" }, "Players"),
    el("div", { class: "fbar" }, [scopeToggle, el("label", {}, "Position"), posSel, el("label", {}, "Team"), teamSel, nowLabel, el("label", {}, "Season"), seasonSel, el("label", {}, "Sort"), sortSel, search, count, modeToggle]),
    body, tableBody,
  ]));
  function setMode(next) {
    viewMode = next;
    modeToggle.querySelectorAll("button").forEach((b, i) => b.classList.toggle("active", ["cards", "table"][i] === next));
    body.style.display = next === "cards" ? "" : "none";
    tableBody.style.display = next === "table" ? "" : "none";
    draw();
  }
  function tableRows() {
    // Table = leaderboard rows (per season or career), narrowed by the same scope/team/position/search.
    const division = scope === "league";
    const season = seasonSel.value;
    let rows = division ? (season === "career" ? [] : divisionLb[season] || [])
      : season === "career" ? ourLb.career : ourLb.by_season[season] || [];
    const byId = new Map(index.map((r) => [r.player_id, r]));
    return rows.filter((r) => {
      const p = byId.get(r.player_id);
      if (posFilter === "F" && (!p || p.position !== "F")) return false;
      if (posFilter === "D" && (!p || p.position !== "D")) return false;
      if (posFilter === "none" && p && p.position) return false;
      if (teamFilter !== "all" && !(p && ((teamNow ? p.division_teams_now : p.division_teams) || []).includes(teamFilter))) return false;
      if (query && !r.name.toLowerCase().includes(query)) return false;
      if (!division && scope === "current" && p && !p.on_our_roster_now) return false;
      return true;
    });
  }

  const sorters = {
    caliber: (a, b) => (b.caliber ? b.caliber.score : -1) - (a.caliber ? a.caliber.score : -1) || b.points_per_game - a.points_per_game,
    ppg: (a, b) => b.points_per_game - a.points_per_game,
    l10: (a, b) => b.l10_points_per_game - a.l10_points_per_game,
    momentum: (a, b) => b.momentum.value - a.momentum.value,
    gp: (a, b) => b.gp - a.gp,
  };

  function inScope(r) {
    if (posFilter === "F" && r.position !== "F") return false;
    if (posFilter === "D" && r.position !== "D") return false;
    if (posFilter === "none" && r.position) return false;
    if (teamFilter !== "all" && !((teamNow ? r.division_teams_now : r.division_teams) || []).includes(teamFilter)) return false;
    if (query) return r.name.toLowerCase().includes(query);  // a search looks across every scope
    if (scope === "current") return r.on_our_roster_now;
    if (scope === "ours") return r.is_ours;
    return true;
  }

  function draw() {
    syncHash("players");
    if (viewMode === "table") {
      const rows = tableRows();
      count.textContent = `${rows.length} player${rows.length === 1 ? "" : "s"}`;
      tableBody.replaceChildren(rows.length ? sortableTable(leaderboardColumns(scope === "league"), rows, "_momentum")
        : el("p", { class: "empty-state" }, scope === "league" && seasonSel.value === "career" ? "Pick a season for the whole-league table." : "No players in this scope."));
      return;
    }
    const rows = index.filter(inScope).sort(sorters[sortKey]);
    count.textContent = `${rows.length} player${rows.length === 1 ? "" : "s"}`;
    if (!rows.length) {
      body.replaceChildren(el("p", { class: "empty-state" }, query ? `No one matching “${query}”.` : "No players in this scope."));
      return;
    }
    body.replaceChildren(...rows.map((r, i) => {
      try { return playerCard(r, "players", i + 1); }
      catch (e) { console.error("playerCard failed for", r.name, e); return el("div", { class: "card", style: "color:var(--rd)" }, `Error rendering ${r.name}: ${e.message}`); }
    }));
  }
  function setScope(next) {
    scope = next;
    scopeToggle.querySelectorAll("button").forEach((b, i) => b.classList.toggle("active", scopes[i] === next));
    draw();
  }
  state.routes.players = {
    params: () => ({ scope: scope === "current" ? "" : scope, pos: posFilter === "all" ? "" : posFilter,
      team: teamFilter === "all" ? "" : teamFilter, now: teamFilter !== "all" && !teamNow ? "0" : "",
      sort: sortKey === "caliber" ? "" : sortKey, q: query, view: viewMode === "cards" ? "" : viewMode,
      season: seasonSel.value === "career" ? "" : seasonSel.value }),
    apply: (p) => {
      scope = scopes.includes(p.scope) ? p.scope : "current";
      scopeToggle.querySelectorAll("button").forEach((b, i) => b.classList.toggle("active", scopes[i] === scope));
      posFilter = ["F", "D", "none"].includes(p.pos) ? p.pos : "all"; posSel.value = posFilter;
      teamFilter = p.team && teamCounts.has(p.team) ? p.team : "all"; teamSel.value = teamFilter;
      teamNow = p.now !== "0"; nowBox.checked = teamNow;
      sortKey = sorters[p.sort] ? p.sort : "caliber"; sortSel.value = sortKey;
      query = (p.q || "").trim().toLowerCase(); search.value = p.q || "";
      seasonSel.value = p.season && seasonKeys.includes(p.season) ? p.season : "career";
      setMode(p.view === "table" ? "table" : "cards");
    },
  };
  draw();
}

// Drill-down with breadcrumb return: callers pass their own view id so Back goes where the
// user actually came from (design template 5). Grid -> detail inside the Players view is two
// sibling divs toggled with display:none, which preserves the grid's scroll position.
async function goSpotlight(playerId, fromView) {
  state.spotlightFrom = fromView || state.spotlightFrom || "players";
  writeHash(`player/${playerId}`, {}, { push: true });
  await activateTab("players");
  const grid = document.getElementById("players-grid");
  const detail = document.getElementById("players-detail");
  grid.style.display = "none";
  detail.style.display = "block";
  detail.innerHTML = "";
  window.scrollTo({ top: 0 });
  try {
    await buildSpotlight(playerId, detail);
  } catch (err) {
    detail.appendChild(el("div", { class: "card empty-state" }, `Couldn't load this player: ${err.message}`));
  }
}

function leaveSpotlight(silent = false) {
  const detail = document.getElementById("players-detail");
  if (!detail || detail.style.display === "none") return;
  detail.style.display = "none";
  document.getElementById("players-grid").style.display = "block";
  if (silent) return;  // the router is already taking us somewhere
  const back = state.spotlightFrom && state.spotlightFrom !== "players" ? state.spotlightFrom : "players";
  if (back !== "players") activateTab(back);
  syncHash(back);
}

function windowCard(label, w, baseline) {
  // Border tint vs the All card: instant "is this recent form or normal for them?"
  const diff = w.points_per_game - baseline.points_per_game;
  const cls = label === "All" ? "" : diff > 0.15 ? " scard-up" : diff < -0.15 ? " scard-dn" : "";
  return el("div", { class: `kpi-card scard${cls}` }, [
    el("div", { class: "label" }, label === "All" ? "All games" : `Last ${label.slice(1)}`),
    el("div", { class: "value-row" }, [el("div", { class: "value" }, w.points_per_game.toFixed(2)), el("span", { class: "muted small" }, "P/GP")]),
    el("div", { class: "muted small" }, `${w.goals}G ${w.assists}A · ${w.points} pts · ${w.gp} GP`),
  ]);
}

// The grade, decomposed: base (percentile-in-division, recency weighted) + persistence + WOWY.
function caliberBreakdown(c) {
  const row = (label, value, tip) => el("div", { class: "cb-row", "data-tip": tip || "" }, [el("span", { class: "muted" }, label), el("span", { class: "cb-val" }, value)]);
  const w = c.wowy;
  return el("div", { class: "cb" }, [
    row("Base (production in division, recency-weighted)", c.base_score.toFixed(2), TIPS.Caliber),
    row(`Persistence (${c.seasons_at_top_tier} season${c.seasons_at_top_tier === 1 ? "" : "s"} at top level)`, `+${c.persistence_bonus.toFixed(2)}`, TIPS.Persistence),
    row(w && c.wowy_adjustment != null ? `WOWY (${w.with_diff >= 0 ? "+" : ""}${w.with_diff.toFixed(2)} dressed / ${w.without_diff >= 0 ? "+" : ""}${w.without_diff.toFixed(2)} without, ${w.with_gp}/${w.without_gp} GP)` : "WOWY (not enough games without them)",
        c.wowy_adjustment != null ? `${c.wowy_adjustment >= 0 ? "+" : ""}${c.wowy_adjustment.toFixed(2)}` : "—", TIPS.WOWY),
    row("Caliber", strong(c.score.toFixed(2))),
  ]);
}

function vsUsCard(v) {
  if (!v || !v.games || !v.games.length) return null;
  const table = el("table", {}, [
    el("thead", {}, el("tr", {}, ["Date", "Season", "G", "A", "PTS", "Our result"].map((h) => el("th", {}, h)))),
    el("tbody", {}, [...v.games].reverse().map((g) => el("tr", { class: g.points >= 2 ? "row-hot" : g.points === 1 ? "row-warm" : "" }, [
      el("td", {}, g.date), el("td", {}, g.season_label), el("td", {}, String(g.goals)), el("td", {}, String(g.assists)),
      el("td", {}, strong(String(g.points))), el("td", {}, el("span", { class: `pill ${g.our_result === "W" ? "win" : g.our_result === "L" ? "loss" : "tie"}` }, g.our_result)),
    ]))),
  ]);
  return el("div", { class: "card" }, [el("div", { class: "sec" }, "Against Us"), el("div", { class: "table-scroll" }, table)]);
}

function situationalCard(sit) {
  if (!sit) return null;
  const per = sit.points_by_period;
  const rows = ["1", "2", "3", "OT"].filter((k) => k !== "OT" || per.OT).map((k) => ({ name: k === "OT" ? "OT" : `Period ${k}`, count: per[k] }));
  return el("div", { class: "card" }, [
    el("div", { class: "sec" }, "When they produce"),
    el("div", { class: "grid" }, [
      el("div", {}, [el("h3", {}, "Points by period"), barChart(rows, "count", "name")]),
      el("div", { class: "kpi-grid grid" }, [
        kpiCard("Late & close pts", String(sit.late_close_points)),
        kpiCard("PP points", String(sit.pp_points)),
        kpiCard("Game-winners", String(sit.game_winners)),
      ]),
    ]),
  ]);
}

function buildSpotlightChart(canvasId, log) {
  destroyChart(canvasId);
  const canvasEl = document.getElementById(canvasId);
  if (!canvasEl || typeof Chart === "undefined") return;
  ensureChartDefaults();
  // One bar per game, colored by the division it was played in, with a 10-game rolling P/GP
  // line on top. Every league's games are merged onto a single date-ordered axis (design
  // template: align onto one shared axis before charting).
  const labels = log.map((g) => g.date.slice(5));
  const pts = log.map((g) => g.pts);
  CH[canvasId] = new Chart(canvasEl.getContext("2d"), {
    data: {
      labels,
      datasets: [
        { type: "bar", data: pts, backgroundColor: log.map((g) => tierColor(g.tier)), borderRadius: 2, order: 2, label: "Points" },
        { type: "line", data: rollingAvg(pts, 10), borderColor: "#1d6fd6", backgroundColor: "#1d6fd6", borderWidth: 2.5, pointRadius: 0, tension: 0.3, order: 1, label: "10-game P/GP" },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        title: { display: true, text: "Points per game, every league (bars colored by division)", font: { size: 10 } },
        tooltip: { callbacks: { title: (items) => { const g = log[items[0].dataIndex]; return `${g.date} · ${g.team} vs ${g.opponent}${g.level_label ? " · " + g.level_label : ""}`; } } },
      },
      scales: {
        x: { ticks: { maxTicksLimit: 10, autoSkip: true, font: { size: 9 } }, grid: { display: false } },
        y: { beginAtZero: true, ticks: { font: { size: 9 }, precision: 0 } },
      },
    },
  });
}

function buildLevelChart(canvasId, levels) {
  destroyChart(canvasId);
  const canvasEl = document.getElementById(canvasId);
  if (!canvasEl || typeof Chart === "undefined") return;
  ensureChartDefaults();
  CH[canvasId] = new Chart(canvasEl.getContext("2d"), {
    type: "bar",
    data: {
      labels: levels.map((l) => `${l.tier} (${l.gp} GP)`),
      datasets: [
        { label: "Player P/GP", data: levels.map((l) => l.points_per_game), backgroundColor: levels.map((l) => tierColor(l.tier)), borderRadius: 2 },
        { label: "Division avg", data: levels.map((l) => l.division_avg_ppg ?? 0), backgroundColor: "rgba(128,128,128,0.35)", borderRadius: 2 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: true, labels: { boxWidth: 10, font: { size: 9 } } }, title: { display: true, text: "P/GP by division vs. that division's average", font: { size: 10 } } },
      scales: { x: { grid: { display: false }, ticks: { font: { size: 9 } } }, y: { beginAtZero: true, ticks: { font: { size: 9 } } } },
    },
  });
}

function buildSeasonChart(canvasId, seasons) {
  destroyChart(canvasId);
  const canvasEl = document.getElementById(canvasId);
  if (!canvasEl || typeof Chart === "undefined") return;
  ensureChartDefaults();
  CH[canvasId] = new Chart(canvasEl.getContext("2d"), {
    data: {
      labels: seasons.map((s) => s.season_label),
      datasets: [
        { type: "bar", data: seasons.map((s) => s.points), backgroundColor: "rgba(128,128,128,0.35)", borderRadius: 2, order: 2, label: "Points", yAxisID: "y" },
        { type: "line", data: seasons.map((s) => s.points_per_game), borderColor: "#1c8a4b", backgroundColor: "#1c8a4b", borderWidth: 2.5, pointRadius: 3, tension: 0.2, order: 1, label: "P/GP", yAxisID: "y1" },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: true, labels: { boxWidth: 10, font: { size: 9 } } }, title: { display: true, text: "Season by season (all teams that season)", font: { size: 10 } } },
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 9 }, maxTicksLimit: 8 } },
        y: { beginAtZero: true, position: "left", ticks: { font: { size: 9 }, precision: 0 } },
        y1: { beginAtZero: true, position: "right", grid: { display: false }, ticks: { font: { size: 9 } } },
      },
    },
  });
}

function stintTable(stints) {
  const cols = [
    { label: "Team", key: "team", render: (s) => el("span", { class: s.is_us ? "is-us" : "" }, s.team) },
    { label: "Season", key: "season_label", render: (s) => s.season_label },
    { label: "League", key: "league_label", render: (s) => s.league_label || "—" },
    { label: "Division", key: "_tier", sortValue: (s) => (s.tier ? s.tier.rung : -1), render: (s) => s.level_label ? el("span", { class: "tier-dot", style: `--tier:${tierColor(s.tier && s.tier.name)}` }, s.level_label.replace("Adult ", "")) : el("span", { class: "muted" }, "unranked") },
    { label: "GP", key: "gp", tip: TIPS.GP, render: (s) => String(s.gp) },
    { label: "G", key: "goals", tip: TIPS.G, render: (s) => String(s.goals) },
    { label: "A", key: "assists", tip: TIPS.A, render: (s) => String(s.assists) },
    { label: "PTS", key: "points", tip: TIPS.PTS, render: (s) => String(s.points) },
    { label: "P/GP", key: "points_per_game", tip: TIPS["P/GP"], render: (s) => s.points_per_game.toFixed(2) },
    { label: "PIM", key: "pims", tip: TIPS.PIM, render: (s) => String(s.pims) },
    {
      label: "Div. Rank", key: "_pct", tip: TIPS["Div. Rank"], sortValue: (s) => (s.rank ? s.rank.pct : -1),
      render: (s) => s.rank
        ? el("span", { class: `pct ${s.rank.pct >= 75 ? "pct-hi" : s.rank.pct < 25 ? "pct-lo" : ""}` }, `${Math.round(s.rank.pct)}th · #${s.rank.rank}/${s.rank.of}`)
        : el("span", { class: "muted" }, s.gp < 3 ? "< 3 GP" : "—"),
    },
  ];
  return sortableTable(cols, stints, "_first", -1);
}

async function buildSpotlight(playerId, container) {
  const p = await loadJSON(`players/${playerId}.json`);
  const c = p.caliber;

  container.appendChild(
    el("div", { class: "card" }, [
      el("div", { class: "bc" }, [
        el("a", { href: "#", onclick: (e) => { e.preventDefault(); leaveSpotlight(); } }, "‹ Back"),
        el("span", { class: "muted" }, " / Player Spotlight"),
      ]),
      el("div", { class: "sp-head" }, [
        el("div", {}, [
          el("div", { class: "sp-name" }, [p.name, " ", positionChip(p.position)]),
          teamChips(p.current_teams),
          tenureLine(p),
        ]),
        el("div", { class: "sp-grade" }, [
          el("div", { class: "sec" }, "Caliber"),
          el("div", {}, [caliberBadge(c), " ", c ? trajectoryBadge(c.trajectory) : null]),
          c ? el("div", { class: "muted small" }, `score ${c.score.toFixed(2)} · ${c.graded_gp} graded GP · ${c.confidence} confidence`) : null,
        ]),
      ]),
      el("p", { class: "verdict" }, p.verdict),
      c ? el("details", { class: "cb-details" }, [el("summary", { class: "muted small" }, "How the grade is built"), caliberBreakdown(c)]) : null,
      p.is_ours ? null : vsUsLine(p.vs_us),
    ])
  );

  const w = p.windows;
  container.appendChild(
    el("div", { class: "card" }, [
      el("div", { class: "sec" }, "Production by level"),
      el("div", { class: "grid" }, [
        el("div", { class: "cw" }, el("canvas", { id: "spLevels" })),
        el("div", { class: "cw" }, el("canvas", { id: "spSeasons" })),
      ]),
      el("div", { class: "table-scroll", style: "margin-top:0.6rem" }, stintTable(p.stints.map((s) => ({ ...s, _first: s.first_date || "" })))),
      el("p", { class: "muted small" }, "Div. Rank is this player's P/GP percentile among every skater (3+ GP) in that division that season. Stints under 3 GP or in an unranked event don't count toward the grade."),
      el("div", { class: "sec", style: "margin-top:0.6rem" }, "Form — every league combined"),
      el("div", { class: "kpi-grid grid" }, [
        ...["L5", "L10", "L20", "All"].map((k) => windowCard(k, w[k], w.All)),
        p.plus_minus ? el("div", { class: "kpi-card", "data-tip": TIPS["+/-"] }, [
          el("div", { class: "label" }, "+/− (tagged)"),
          el("div", { class: "value-row" }, [el("div", { class: "value" }, `${p.plus_minus.plus_minus > 0 ? "+" : ""}${p.plus_minus.plus_minus}`)]),
          el("div", { class: "muted small" }, `${p.plus_minus.plus} for / ${p.plus_minus.minus} against · ${p.plus_minus.goals_tagged} goals tagged`),
        ]) : null,
      ]),
      el("div", { class: "spark-wrap", style: "margin-top:0.5rem" }, ["Momentum: ", momentumBadge(p.trend.momentum), " ", sparkSpan(p.trend.spark_svg)]),
    ])
  );

  const vs = p.is_ours ? null : vsUsCard(p.vs_us);
  if (vs) container.appendChild(vs);
  const sc = situationalCard(p.situational);
  if (sc) container.appendChild(sc);

  await ensureFilmSync();
  let showAll = false;
  const logWrap = el("div", { class: "table-scroll" });
  const logCard = el("div", { class: "card" }, [
    el("div", { class: "sec" }, "Game log"),
    el("div", { class: "legend" }, TIER_ORDER.filter((t) => p.levels.some((l) => l.tier === t)).map((t) =>
      el("span", { class: "legend-item" }, [el("span", { class: "legend-swatch", style: `background:${tierColor(t)}` }), t]))),
    el("div", { class: "cw cw-tall" }, el("canvas", { id: "spGames" })),
    logWrap,
  ]);
  const drawLog = () => {
  const recent = [...p.log].slice(showAll ? 0 : -15).reverse();
  const logTable = el("table", {}, [
    el("thead", {}, el("tr", {}, ["Date", "Team", "Opponent", "Division", "G", "A", "PTS", "PIM", "Film"].map((h) => el("th", {}, h)))),
    el("tbody", {}, recent.map((g) =>
      el("tr", { class: g.pts >= 2 ? "row-hot" : g.pts === 1 ? "row-warm" : "" }, [
        el("td", {}, g.date), el("td", { class: g.is_us ? "is-us" : "" }, g.team), el("td", {}, g.opponent),
        el("td", {}, g.level_label ? g.level_label.replace("Adult ", "") : el("span", { class: "muted" }, g.season_label)),
        el("td", {}, String(g.goals)), el("td", {}, String(g.assists)), el("td", {}, strong(String(g.pts))), el("td", {}, String(g.pims)),
        el("td", {}, filmLinkForGame(g.game_id) || ""),
      ]))),
  ]);
  logWrap.replaceChildren(logTable, p.log.length > 15 ? el("a", { href: "#", class: "small", style: "display:inline-block;margin-top:0.4rem", onclick: (e) => { e.preventDefault(); showAll = !showAll; drawLog(); } }, showAll ? "Show last 15" : `Show all ${p.log.length} games`) : null);
  };
  drawLog();
  container.appendChild(logCard);

  buildSpotlightChart("spGames", p.log);
  buildLevelChart("spLevels", p.levels);
  buildSeasonChart("spSeasons", p.seasons);
}

// Which players have a Spotlight file -- loaded once, shared by every view that links names.
async function ensureSpotlightIds() {
  if (state.spotlightIds) return;
  try {
    const index = await loadJSON("players_index.json");
    state.spotlightIds = new Set(index.map((r) => r.player_id));
  } catch {
    state.spotlightIds = new Set();
  }
}

// GF / GA by period, PP share, late-and-close record -- from situational.json, pooled over the
// team's seasons (name-matched, so a rename is handled by passing every alias).
async function whenGoalsHappenCard(teamNames, title) {
  let sit;
  try { sit = await loadJSON("situational.json"); } catch { return null; }
  const names = [].concat(teamNames);
  const acc = { games: 0, gf: { 1: 0, 2: 0, 3: 0, OT: 0 }, ga: { 1: 0, 2: 0, 3: 0, OT: 0 }, pp_gf: 0, pp_ga: 0, sh_gf: 0,
    lc_gf: 0, lc_ga: 0, lc_w: 0, lc_l: 0, fg_games: 0, fg_w: 0 };
  for (const teams of Object.values(sit)) for (const n of names) {
    const t = teams[n]; if (!t) continue;
    acc.games += t.games;
    for (const k of ["1", "2", "3", "OT"]) { acc.gf[k] += t.gf_by_period[k]; acc.ga[k] += t.ga_by_period[k]; }
    acc.pp_gf += t.pp_gf; acc.pp_ga += t.pp_ga; acc.sh_gf += t.sh_gf;
    acc.lc_gf += t.late_close_gf; acc.lc_ga += t.late_close_ga; acc.lc_w += t.late_close_w; acc.lc_l += t.late_close_l;
    acc.fg_games += t.first_goal_games; acc.fg_w += t.first_goal_w;
  }
  if (!acc.games) return null;
  const totalGf = Object.values(acc.gf).reduce((a, b) => a + b, 0), totalGa = Object.values(acc.ga).reduce((a, b) => a + b, 0);
  const rows = ["1", "2", "3", "OT"].filter((k) => k !== "OT" || acc.gf.OT || acc.ga.OT).map((k) => ({ name: k === "OT" ? "OT" : `Period ${k}`, gf: acc.gf[k], ga: acc.ga[k], diff: acc.gf[k] - acc.ga[k] }));
  const max = Math.max(1, ...rows.map((r) => Math.max(r.gf, r.ga)));
  const worst = [...rows].sort((a, b) => a.diff - b.diff)[0];
  const best = [...rows].sort((a, b) => b.diff - a.diff)[0];
  return el("div", { class: "card" }, [
    el("div", { class: "sec" }, title),
    el("div", { class: "grid" }, [
      el("div", {}, [
        el("h3", {}, "Goals for / against by period"),
        ...rows.map((r) => el("div", { class: "period-row" }, [
          el("div", { class: "name" }, r.name),
          el("div", { class: "period-bars" }, [
            el("div", { class: "bar-track" }, [el("div", { class: "bar-fill gf", style: `width:${Math.round(100 * r.gf / max)}%` })]),
            el("div", { class: "bar-track" }, [el("div", { class: "bar-fill ga", style: `width:${Math.round(100 * r.ga / max)}%` })]),
          ]),
          el("div", { class: "period-nums" }, [el("span", { class: "gf-n" }, String(r.gf)), " / ", el("span", { class: "ga-n" }, String(r.ga))]),
        ])),
        el("div", { class: "muted small", style: "margin-top:0.3rem" }, `Best period: ${best.name} (${best.diff >= 0 ? "+" : ""}${best.diff}) · worst: ${worst.name} (${worst.diff >= 0 ? "+" : ""}${worst.diff})`),
      ]),
      el("div", { class: "kpi-grid grid" }, [
        kpiCard("Late & close", `${acc.lc_w}-${acc.lc_l}`),
        kpiCard("Late & close goals", `${acc.lc_gf} for / ${acc.lc_ga} against`),
        kpiCard("Score first → win", acc.fg_games ? `${acc.fg_w}/${acc.fg_games}` : "—"),
        kpiCard("PP share of goals", totalGf ? `${Math.round(100 * acc.pp_gf / totalGf)}%` : "—"),
        kpiCard("PP share allowed", totalGa ? `${Math.round(100 * acc.pp_ga / totalGa)}%` : "—"),
      ]),
    ]),
  ]);
}

// The opponent's roster this season, graded -- the Players tab's scouting lens, dropped straight
// into the report for the next game so nobody has to go set the filters themselves.
async function opponentRosterCard(oppName) {
  let index = [];
  try { index = await loadJSON("players_index.json"); } catch { /* no spotlights built yet */ }
  let rows = index.filter((p) => (p.division_teams_now || []).includes(oppName));
  let note = "Everyone rostered for them this season, graded on everything they've ever played. Ranked by caliber — click a player for their full Spotlight.";
  if (!rows.length) {
    rows = index.filter((p) => (p.division_teams || []).includes(oppName));
    note = "No roster posted for this season yet — this is everyone who has skated for them in our division before.";
  }
  rows.sort((a, b) => (b.caliber ? b.caliber.score : -1) - (a.caliber ? a.caliber.score : -1) || b.points_per_game - a.points_per_game);

  const card = el("div", { class: "card" }, [el("div", { class: "sec" }, `Their Roster, Graded — ${oppName}`)]);
  if (!rows.length) {
    card.appendChild(el("p", { class: "empty-state" }, "No graded players found for this team yet."));
    return card;
  }

  const graded = rows.filter((p) => p.caliber);
  const avgScore = graded.length ? graded.reduce((a, p) => a + p.caliber.score, 0) / graded.length : null;
  const aboveD = graded.filter((p) => p.caliber.tier !== "D");
  const ringers = rows.filter((p) => p.league_mix && p.league_mix.d_pct < 50);
  const playsUp = rows.filter((p) => p.fit && p.fit.direction === "above");
  const killers = rows.filter((p) => p.vs_us && p.vs_us.gp >= 2 && p.vs_us.points_per_game >= 1).sort((a, b) => b.vs_us.points - a.vs_us.points);
  const summary = el("div", { class: "kpi-grid grid" }, [
    kpiCard("Skaters", String(rows.length)),
    kpiCard("Avg Caliber", avgScore != null ? `${avgScore.toFixed(2)} · ${caliberLabelFor(avgScore)}` : "—"),
    kpiCard("Grade C3 or better", String(aboveD.length)),
    kpiCard("Play mostly above D", String(ringers.length)),
    kpiCard("Producing above D", String(playsUp.length)),
  ]);
  card.appendChild(summary);
  card.appendChild(el("p", { class: "muted small" }, note));
  if (aboveD.length) {
    card.appendChild(el("p", { class: "verdict" }, [
      strong("Key on: "),
      aboveD.slice(0, 4).map((p) => `${p.name} (${p.caliber.label}${p.league_mix ? `, ${p.league_mix.d_pct}% in D` : ""})`).join(" · "),
    ]));
  }
  if (killers.length) {
    card.appendChild(el("p", { class: "verdict" }, [
      strong("They've hurt us: "),
      killers.slice(0, 4).map((p) => `${p.name} (${p.vs_us.goals}G ${p.vs_us.assists}A in ${p.vs_us.gp} vs us)`).join(" · "),
    ]));
  }
  card.appendChild(el("div", { class: "pgrid", style: "margin-top:0.6rem" }, rows.map((p, i) => {
    try { return playerCard(p, "scouting", i + 1); }
    catch (e) { console.error("playerCard failed for", p.name, e); return el("div", { class: "card", style: "color:var(--rd)" }, `Error rendering ${p.name}: ${e.message}`); }
  })));
  return card;
}

// Same band logic as spotlight.py's caliber_label, for a roster-average score computed client-side.
function caliberLabelFor(score) {
  const names = ["D", "C3", "C2", "C1", "B", "A"];
  let idx = 0;
  for (let i = 0; i < names.length; i++) if (Math.abs(i + 1 - score) < Math.abs(idx + 1 - score)) idx = i;
  const frac = score - (idx + 0.5);
  return `${frac < 0.33 ? "Entry-level" : frac < 0.67 ? "Solid" : "Top-end"} ${names[idx]}`;
}

// ---------------------------------------------------------------------------
// Metrics appendix -- every number on the site: what it means, how it's actually
// computed, and how to read it. Per the design template, a definition is not done
// until it carries the formula AND an interpretive benchmark, not just a name.
// ---------------------------------------------------------------------------

const METRIC_GROUPS = [
  {
    title: "Skater Stats",
    note: "Recomputed here from individual goals on each scoresheet — so a filed correction changes these.",
    rows: [
      { name: "GP", means: "Games this player was on the scoresheet roster for.", formula: "count of games", read: "Trend math needs at least 3." },
      { name: "G", means: "Goals scored.", formula: "count", read: "Compare against the division on League Outliers." },
      { name: "A1", means: "Primary assist — the pass that directly set up the goal.", formula: "count", read: "The cleaner read on playmaking." },
      { name: "A2", means: "Secondary assist — the pass before the primary.", formula: "count", read: "Noisier; awarded inconsistently." },
      { name: "A", means: "All assists.", formula: "A1 + A2", read: "Split it out when you care who actually made the play." },
      { name: "PTS", means: "Points — the standard scoring currency.", formula: "G + A1 + A2", read: "Counts a goal and an assist the same." },
      { name: "P/GP", means: "Points per game. The fair comparison when someone's missed nights.", formula: "PTS ÷ GP", read: "Around 1.00 is a point a night — strong at this level." },
      { name: "Hat", means: "Hat tricks.", formula: "games with 3 or more goals", read: "Rare enough that any at all is notable." },
      { name: "PIM", means: "Penalty minutes.", formula: "sum of this player's penalties", read: "20+ in a season is a habit, not bad luck." },
      { name: "+/−", means: "True plus/minus, from goals someone tagged on the film.", formula: "+1 on ice for an ES/SH goal for, −1 against; PP goals count for nobody", read: "Hover for coverage: a +3 over 6 tagged goals is a lot less than a +3 over 40." },
      { name: "Shots", means: "Shown only where the league bothered to fill them in.", formula: "as reported, never recomputed", read: "Usually blank — don't read into the gaps." },
    ],
  },
  {
    title: "Goalie Stats",
    note: "Taken straight from the league's own goalie table. Not recomputed here, and not touched by corrections.",
    rows: [
      { name: "GP", means: "Games played in net.", formula: "as reported", read: "Who's actually been carrying the crease." },
      { name: "W-L", means: "Record in games they started.", formula: "as reported", read: "Team-dependent — read it next to SV%." },
      { name: "GAA", means: "Goals against average — goals allowed per full game.", formula: "as reported", read: "Lower is better." },
      { name: "SV%", means: "Save percentage — share of shots stopped.", formula: "as reported", read: ".900 is roughly replacement here; .910+ is a problem for us." },
    ],
  },
  {
    title: "Team Stats",
    note: "These come from the league's standings table, not from our own goal-by-goal math — which is why a corrected goal moves a player's line but never the team's record.",
    rows: [
      { name: "W-L-T", means: "Record, with OT results split out where the league tracks them.", formula: "league standings", read: "The official version." },
      { name: "GF / GA", means: "Goals for and goals against.", formula: "league standings", read: "—" },
      { name: "Goal Diff", means: "The best single-number read on a team.", formula: "GF − GA", read: "Positive means we're outscoring the division." },
      { name: "PTS", means: "Standings points.", formula: "as the league awards them", read: "What actually decides position." },
      { name: "Streak", means: "Consecutive games with the same result, most recent first.", formula: "walk backward from the last game", read: "3+ either way is a real run." },
      { name: "Form", means: "Recent results pace — are we climbing or sliding?", formula: "W=2, T=1, L=0, then half-split", read: "Positive means trending up." },
    ],
  },
  {
    title: "Player Spotlight & Caliber",
    note: "Built from the league site's per-player career pages, which span every team and league on the site — so these include games played for other teams, in the other rink's adult league, and are NOT touched by our scoresheet corrections.",
    rows: [
      { name: "Stint", means: "One player on one team for one season.", formula: "a row of the career page, matched to a division via that season's standings", read: "The unit everything else is built from." },
      { name: "Ladder", means: "The one scale both adult leagues share.", formula: "D = 1, C3 = 2, C2 = 3, C1 = 4, B = 5, A = 6; Upper/Lower/Gold/Bronze splits ±0.25", read: "Combined divisions (A/B) sit halfway." },
      { name: "Div. Rank", means: "How the stint's P/GP ranked in its division that season.", formula: "percentile among every skater with 3+ GP in that division-season", read: "75th+ is a top-quarter producer there; under 25th is depth." },
      { name: "Stint rung", means: "What one stint says about caliber.", formula: "division rung + (percentile − 50) ÷ 50 × 0.75", read: "Dominating D (90th pct) ≈ a mid-C3 player; bottom of C3 ≈ a strong D player." },
      { name: "Caliber", means: "The grade on the badge.", formula: "GP-weighted mean of stint rungs, over stints with 3+ GP in a ranked division", read: "Bands are centered on each rung: Entry-level / Solid / Top-end say where in the band it lands." },
      { name: "Recency", means: "Newer stints count more.", formula: "stint weight = GP × 0.5^(age in days ÷ 730)", read: "A stint from two seasons ago counts half; the grade follows the player, not their history." },
      { name: "Persistence", means: "Kept on a roster at your top level, season after season.", formula: "+0.15 per extra season at the top tier, capped +0.30", read: "The only credit a stay-at-home D-man gets from a points-based grade — small on purpose." },
      { name: "WOWY", means: "With-or-without-you, from our division's games.", formula: "(team goal diff/GP dressed − without) clamped ±2, × 0.125", read: "Up to ±0.25 rungs. Needs 3+ games on each side; noisiest for players who never miss." },
      { name: "Trajectory", means: "Is their level moving?", formula: "caliber over last 365 days − caliber before that", read: "↗ / ↘ at a quarter rung or more." },
      { name: "vs Us", means: "Their line against our team only.", formula: "from our own box scores, corrections applied", read: "1+ P/GP over 2+ games is someone to shadow." },
      { name: "Late & close", means: "Goals with the game on the line.", formula: "3rd period or OT goals while the score was within one", read: "For teams: the record in games that had one. For players: points on them." },
      { name: "Confidence", means: "How much evidence is behind the grade.", formula: "graded GP: < 10 low · 10–29 medium · 30+ high", read: "A 'low' Top-end C3 is a hunch; a 'high' one is a fact." },
      { name: "Fit", means: "Grade vs. the division they're playing in now.", formula: "caliber − current division's rung; ≥ +0.5 plays up · ≤ −0.5 depth", read: "'Plays up' is your promotion list; 'depth' is who's still finding it at this level." },
      { name: "Windows", means: "Form over the last 5 / 10 / 20 games, every league merged.", formula: "trailing counts on the date-ordered game log", read: "A card tinted green/red is more than 0.15 P/GP off their all-games rate." },
      { name: "Tenure", means: "How long they've been in the system.", formula: "first game date → latest, any league; seasons = distinct seasons rostered", read: "A 1-season player's grade is thin evidence, whatever the confidence letter says." },
      { name: "League %", means: "How much of their hockey is our league / D.", formula: "games in BH Adult ÷ all games; games in any D division ÷ all games", read: "A low D% on a D roster is a ringer — check the Spotlight." },
      { name: "Position", means: "F or D.", formula: "hand-entered in data/positions.json — the league site records none", read: "Grades are production-based, so rank D against D with the position filter; 'Unknown' means nobody has filled it in yet." },
    ],
  },
  {
    title: "Trend & Momentum",
    note: "The analytical core. Every trend on the site is self-referential — a player is measured against their own recent self, never against a league baseline.",
    rows: [
      { name: "Window", means: "How far back every trend on this site looks.", formula: "last 10 completed games", read: "Under 3 games it says “not enough games yet”." },
      { name: "Sparkline", means: "The little line next to a name.", formula: "the same 10-game window", read: "Green rising, red falling, grey flat." },
      { name: "Half-split", means: "Is this player improving inside that window?", formula: "mean(2nd half) − mean(1st half)", read: "Needs no baseline and no model." },
      { name: "Momentum", means: "The composite that sorts every leaderboard by default.", formula: "half-split(PTS) + 0.25 × half-split(G)", read: "Points lead; finishing is a lower-weight support signal." },
      { name: "Hot / Steady / Cold", means: "The three badge bands.", formula: "≥ +0.50 hot · ≤ −0.50 cold · between = steady", read: "Half a point per game is a real swing at this level." },
    ],
  },
];

function metricRow(m) {
  return el("div", { class: "metric-row" }, [
    el("div", { class: "m-name" }, m.name),
    el("div", {}, [el("span", { class: "ml" }, "Means"), m.means]),
    el("div", { class: "m-formula" }, [el("span", { class: "ml" }, "Formula"), m.formula]),
    el("div", {}, [el("span", { class: "ml" }, "Read it as"), m.read]),
  ]);
}

function renderMetrics() {
  const view = document.getElementById("help-body");
  if (view.childElementCount) return;

  for (const group of METRIC_GROUPS) {
    const card = el("div", { class: "card" }, [
      el("div", { class: "sec" }, group.title),
      group.note ? el("p", { class: "muted small" }, group.note) : null,
      el("div", { class: "metric-row metric-head" }, [
        el("div", {}, "Metric"), el("div", {}, "Means"), el("div", {}, "Formula"), el("div", {}, "Read it as"),
      ]),
      ...group.rows.map(metricRow),
    ]);
    view.appendChild(card);
  }

  view.appendChild(
    el("div", { class: "card" }, [
      el("div", { class: "sec" }, "How the Data Works"),
      el("ul", { class: "keys-list", style: "margin-top:0.5rem" }, [
        el("li", {}, [strong("Source. "), "Every number starts as a scrape of the league's own scoresheets and standings, refreshed automatically each night. Nobody types anything in."]),
        el("li", {}, [strong("Two different ledgers. "), "Skater stats are rebuilt goal by goal from the scoresheets. Team records, PIM totals and goalie lines are shown exactly as the league's standings report them. The two can disagree — the league's table is the official one."]),
        el("li", {}, [strong("Corrections. "), "The scoresheets have mistakes in them: wrong scorer, missing assist. “Suggest a fix” on the Games tab files one, and it's applied as a layer on top of the raw scrape, which is never edited. That means every fix is reversible, and a corrected goal carries a ✎ marker with the reason."]),
        el("li", {}, [strong("Game film. "), "Videos come from our YouTube playlist, matched to games by the “Game #” tag in each description — so tagging a new upload is all it takes to make it show up here. The ▶ links on goals come from watching the scoreboard on the film: the score changing is the goal, so each link starts just before the change. The camera pans away from the board at times, so a link can be early by up to the length of that gap, never late."]),
        el("li", {}, [strong("Rink sessions. "), "Stick & Puck and adult pick-up on the Schedule calendar come from the rink's own booking system, filtered to just the skates you can actually show up to."]),
      ]),
    ])
  );
}

// ---------------------------------------------------------------------------
// Tab wiring
// ---------------------------------------------------------------------------

const renderers = {
  overview: renderOverview,
  scouting: renderScouting,
  players: renderPlayers,
  games: renderGames,
};

function activateTab(name) {
  for (const btn of document.querySelectorAll("nav.tabs button")) btn.classList.toggle("active", btn.dataset.view === name);
  for (const section of document.querySelectorAll("section.view")) section.classList.toggle("active", section.id === `view-${name}`);
  if (!state[name]) {
    // Lazy-build on first visit; keep the promise so a drill-in (goSpotlight) can await the build.
    state[name] = renderers[name]().catch((err) => {
      document.getElementById(`view-${name}`).innerHTML = `<div class="card empty-state">Couldn't load data: ${err.message}</div>`;
    });
  }
  return state[name];
}

// ---------------------------------------------------------------------------
// URL router: the hash IS the view, so a copied link lands someone on the same tab, with the same
// filters, spotlight or box score open. Forms: #players?scope=league&pos=D&team=X&now=0&sort=ppg&q=
// #player/1523 (spotlight) · #games?game=7718 (box score) · #leaderboards?scope=division&season=12
// Each renderer that has state registers state.routes[view] = { apply(params), params() }.
// ---------------------------------------------------------------------------
state.routes = {};
state.routing = false;  // true while applying a URL, so the views' own writes don't fight it

function parseHash() {
  const raw = location.hash.replace(/^#/, "");
  if (!raw) return { view: "overview", params: {} };
  const [path, query = ""] = raw.split("?");
  const params = Object.fromEntries(new URLSearchParams(query));
  const m = path.match(/^player\/(\d+)$/);
  if (m) return { view: "player", params: { id: m[1] } };
  return { view: renderers[path] ? path : "overview", params };
}

function writeHash(view, params = {}, { push = false } = {}) {
  if (state.routing) return;
  const clean = Object.entries(params).filter(([, v]) => v != null && v !== "" && v !== false);
  const q = new URLSearchParams(clean.map(([k, v]) => [k, v === true ? "1" : String(v)])).toString();
  const next = `#${view}${q ? "?" + q : ""}`;
  if (next === location.hash) return;
  (push ? history.pushState : history.replaceState).call(history, null, "", next);
}

// Views call this after any filter change; the hash tracks the live state of whichever tab is up.
function syncHash(view) {
  const r = state.routes[view];
  if (r && r.params) writeHash(view, r.params());
}

async function route() {
  const { view, params } = parseHash();
  state.routing = true;
  try {
    if (view === "player") {
      await goSpotlight(Number(params.id), state.spotlightFrom || "players");
    } else {
      leaveSpotlight(true);
      await activateTab(view);
      const r = state.routes[view];
      if (r && r.apply) await r.apply(params);
    }
  } finally {
    state.routing = false;
  }
}

document.getElementById("tabs").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-view]");
  if (!btn) return;
  leaveSpotlight(true);
  activateTab(btn.dataset.view);
  const r = state.routes[btn.dataset.view];
  writeHash(btn.dataset.view, r && r.params ? r.params() : {}, { push: true });
});
window.addEventListener("hashchange", route);

// "Copy link": the URL already describes the view, so sharing is one click.
const shareBtn = document.getElementById("share-link");
if (shareBtn) shareBtn.addEventListener("click", async () => {
  const url = location.href;
  try { await navigator.clipboard.writeText(url); } catch { window.prompt("Copy this link:", url); return; }
  const was = shareBtn.textContent;
  shareBtn.textContent = "Link copied ✓";
  shareBtn.classList.add("done");
  setTimeout(() => { shareBtn.textContent = was; shareBtn.classList.remove("done"); }, 1600);
});

initTooltipSystem();
document.getElementById("help-btn").addEventListener("click", () => { renderMetrics(); document.getElementById("help").showModal(); });
route();

loadJSON("meta.json")
  .then((m) => {
    const d = new Date(m.generated_at);
    document.getElementById("stamp").textContent = `Updated ${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
  })
  .catch(() => {});
