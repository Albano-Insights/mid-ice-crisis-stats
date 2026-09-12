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

async function renderOverview() {
  const view = document.getElementById("view-overview");
  view.innerHTML = "";
  view.appendChild(
    pageIntro([
      "The team at a glance. The cards up top are ", strong("all-time"),
      " across every season we've played together. ",
      strong("Trends"), " re-buckets every completed game by week, month, or season — use the toggle to zoom out. ",
      strong("Rising Now"), " is who's heating up this season, hottest first.",
    ])
  );
  const [summary, ourLb] = await Promise.all([loadJSON("team_summary.json"), loadJSON("player_leaderboards.json")]);
  const o = summary.overall;
  const streak = summary.current_streak;
  const form = summary.recent_form || {};

  const kpis = el("div", { class: "kpi-grid grid" }, [
    kpiCard("Record", `${o.w}-${o.l}${o.t ? "-" + o.t : ""}`),
    kpiCard("Points", o.pts),
    kpiCard("Goal Diff", o.gf - o.ga >= 0 ? `+${o.gf - o.ga}` : String(o.gf - o.ga), form.goal_diff),
    kpiCard("Form", streak.result ? `${streak.length}${streak.result}` : "—", form.points_pace),
    kpiCard("PIM", o.pims),
  ]);
  view.appendChild(el("div", { class: "card" }, [el("div", { class: "sec" }, "All-Time (since Fall 2025)"), kpis]));

  await renderTrendsCard(view);

  // "Rising Now" strip: our top-momentum players right now, horizontally scrolling cards.
  const latestSeasonKey = Object.keys(ourLb.by_season).sort((a, b) => Number(b) - Number(a))[0];
  const risingRows = [...(ourLb.by_season[latestSeasonKey] || [])]
    .filter((r) => r.games_played >= 3)
    .sort((a, b) => b.momentum.value - a.momentum.value)
    .slice(0, 8);
  if (risingRows.length) {
    view.appendChild(
      el("div", { class: "card" }, [
        el("div", { class: "sec" }, "Rising Now"),
        el(
          "div",
          { class: "rstrip" },
          risingRows.map((r) =>
            el("div", { class: "rcard" }, [
              el("div", { class: "name" }, r.name),
              el("div", { class: "team" }, `${r.points} pts · ${r.games_played} GP`),
              el("div", { class: "spark-wrap" }, [sparkSpan(r.spark_svg), " ", momentumBadge(r.momentum, { compact: true })]),
            ])
          )
        ),
      ])
    );
  }

  const seasonRows = Object.entries(summary.by_season).sort((a, b) => Number(a[0]) - Number(b[0]));
  const table = el("table", {}, [
    el("thead", {}, el("tr", {}, ["Season", "Name", "Level", "GP", "W", "L", "OT", "GF", "GA", "PTS", "PIM"].map((h) => el("th", {}, h)))),
  ]);
  const tbody = el("tbody");
  for (const [seasonId, s] of seasonRows) {
    if (s.gp == null) continue;
    tbody.appendChild(
      el("tr", {}, [
        el("td", {}, s.season_label || `Season ${seasonId}`),
        el("td", {}, s.name),
        el("td", {}, s.level_label),
        el("td", {}, String(s.gp)),
        el("td", {}, String(s.w)),
        el("td", {}, String(s.l)),
        el("td", {}, String((s.otw || 0) + (s.otl || 0))),
        el("td", {}, String(s.gf)),
        el("td", {}, String(s.ga)),
        el("td", {}, String(s.pts)),
        el("td", {}, String(s.pims)),
      ])
    );
  }
  view.appendChild(el("div", { class: "card" }, [el("div", { class: "sec" }, "Season by Season"), el("div", { class: "table-scroll" }, table)]));
  table.appendChild(tbody);

  const upcoming = seasonRows.find(([, s]) => s.gp == null);
  if (upcoming) {
    view.appendChild(
      el("div", { class: "card" }, [
        el("h2", {}, `${upcoming[1].season_label} is upcoming`),
        el("p", { class: "empty-state" }, "No games played yet this season — check the Scouting Report for what's next."),
      ])
    );
  }
}

// ---------------------------------------------------------------------------
// Insights
// ---------------------------------------------------------------------------

const INSIGHT_ICON = {
  hot_streak: "🔥", cold_streak: "❄️", scoring_leader: "🏆",
  goal_diff: "📊", win_streak: "🚀", pim_leader: "🥊", our_rank: "📍",
};

function latestSeasonWithContent(dataBySeasonId, isEmptyFn) {
  const ids = Object.keys(dataBySeasonId).filter((id) => !isEmptyFn(dataBySeasonId[id])).sort((a, b) => Number(b) - Number(a));
  return ids[0] || Object.keys(dataBySeasonId).sort((a, b) => Number(b) - Number(a))[0];
}

async function renderInsights() {
  const view = document.getElementById("view-insights");
  view.innerHTML = "";
  view.appendChild(
    pageIntro([
      "Plain-language notes on what's happening in our division this season — hot and cold streaks, ",
      "who's scoring, where we sit. Switch seasons with the picker. ",
      "Everything here is computed from the scoresheets, not written by anyone.",
    ])
  );
  const data = await loadJSON("league_insights.json");

  const seasonIds = Object.keys(data).sort((a, b) => Number(b) - Number(a));
  const defaultSeason = latestSeasonWithContent(data, (s) => !s.insights || s.insights.length === 0);
  const selector = el(
    "select",
    {},
    seasonIds.map((id) => {
      const attrs = { value: id };
      if (id === defaultSeason) attrs.selected = "selected";
      return el("option", attrs, data[id].season_label);
    })
  );

  const feed = el("div", { class: "card" }, [el("div", { class: "sec" }, "Division Quick Insights")]);
  const feedBody = el("div");
  feed.appendChild(el("div", { class: "fbar" }, [el("label", {}, "Season"), selector]));
  feed.appendChild(feedBody);
  view.appendChild(feed);

  function draw(seasonId) {
    const season = data[seasonId];
    feedBody.innerHTML = "";
    if (!season || !season.insights.length) {
      feedBody.appendChild(el("p", { class: "empty-state" }, "No insights yet — not enough games played this season."));
      return;
    }
    for (const insight of season.insights) {
      feedBody.appendChild(
        el("div", { class: "insight-card", style: "display:flex;gap:0.7rem;padding:0.7rem 0;border-bottom:1px solid var(--bd)" }, [
          el("div", { style: "font-size:1.3rem;line-height:1" }, INSIGHT_ICON[insight.kind] || "•"),
          el("div", {}, [
            el("div", { style: "font-weight:600;margin-bottom:0.15rem" }, insight.headline),
            el("div", { style: "color:var(--mu);font-size:0.88em" }, insight.detail),
          ]),
        ])
      );
    }
  }

  selector.addEventListener("change", () => draw(selector.value));
  draw(defaultSeason);
}

// ---------------------------------------------------------------------------
// Leaderboards (Our Team / Whole Division toggle)
// ---------------------------------------------------------------------------

function leaderboardColumns(showTeam) {
  const cols = [
    { label: "Player", key: "name", render: (r) => el("span", { class: r.team && isUs(r.team) ? "is-us" : "" }, r.name) },
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
      label: "Momentum", key: "_momentum", tip: TIPS.Momentum,
      sortValue: (r) => r.momentum.value,
      render: (r) => el("span", {}, [sparkSpan(r.spark_svg), " ", momentumBadge(r.momentum, { compact: true })]),
    }
  );
  return cols;
}

async function renderLeaderboards() {
  const view = document.getElementById("view-leaderboards");
  view.innerHTML = "";
  view.appendChild(
    pageIntro([
      "Full skater stats. Toggle ", strong("Our Team / Whole Division"), " and pick a season or All-Time. ",
      "Sorted by ", strong("Momentum"), " by default — who's trending up right now, not who's piled up the most points. ",
      "Click any column header to re-sort; hover a header for what it means.",
    ])
  );
  const [ourData, divisionData] = await Promise.all([loadJSON("player_leaderboards.json"), loadJSON("division_leaderboards.json")]);

  let scope = "our";
  const scopeToggle = el("div", { class: "scope-toggle" }, [
    el("button", { class: "active", onclick: () => setScope("our") }, "Our Team"),
    el("button", { onclick: () => setScope("division") }, "Whole Division"),
  ]);

  const seasonKeys = Object.keys(ourData.by_season).sort((a, b) => Number(a) - Number(b));
  const divisionSeasonKeys = Object.keys(divisionData).sort((a, b) => Number(a) - Number(b));
  const seasonSelector = el("select", {}, []);

  function refreshSeasonOptions() {
    const keys = scope === "our" ? seasonKeys : divisionSeasonKeys;
    seasonSelector.replaceChildren(el("option", { value: "career" }, "All-Time (Career)"), ...keys.map((k) => el("option", { value: k }, `Season ${k}`)));
  }
  refreshSeasonOptions();

  const card = el("div", { class: "card" }, [
    el("div", { class: "sec" }, "Leaderboards"),
    el("div", { class: "fbar" }, [scopeToggle, el("label", {}, "Season"), seasonSelector]),
    el("div", { id: "top-scorers-chart" }),
  ]);
  const tableCard = el("div", { class: "card" }, [el("div", { class: "sec" }, "Full Leaderboard"), el("div", { class: "table-scroll", id: "leaderboard-table" })]);
  view.appendChild(card);
  view.appendChild(tableCard);

  function currentRows() {
    if (scope === "our") return seasonSelector.value === "career" ? ourData.career : ourData.by_season[seasonSelector.value] || [];
    return seasonSelector.value === "career" ? [] : divisionData[seasonSelector.value] || [];
  }

  function draw() {
    const rows = [...currentRows()].sort((a, b) => b.points - a.points);
    document.getElementById("top-scorers-chart").replaceChildren(barChart(rows.slice(0, 10), "points", "name"));
    document.getElementById("leaderboard-table").replaceChildren(sortableTable(leaderboardColumns(scope === "division"), rows, "_momentum"));
  }

  function setScope(next) {
    scope = next;
    for (const btn of scopeToggle.querySelectorAll("button")) btn.classList.remove("active");
    scopeToggle.querySelector(`button:nth-child(${next === "our" ? 1 : 2})`).classList.add("active");
    const previousValue = seasonSelector.value;
    refreshSeasonOptions();
    const keys = scope === "our" ? seasonKeys : divisionSeasonKeys;
    if (scope === "division" && previousValue === "career") seasonSelector.value = keys[keys.length - 1] || "career";
    else if (keys.includes(previousValue)) seasonSelector.value = previousValue;
    draw();
  }

  seasonSelector.addEventListener("change", draw);
  draw();
}

// ---------------------------------------------------------------------------
// Games (with box score viewer + correction form)
// ---------------------------------------------------------------------------

function pillFor(us, them) {
  if (us > them) return el("span", { class: "pill win" }, "W");
  if (us < them) return el("span", { class: "pill loss" }, "L");
  return el("span", { class: "pill tie" }, "T");
}

function buildCorrectionIssueUrl(gameId, goal) {
  const base = `https://github.com/${CONFIG.repo}/issues/new`;
  const params = new URLSearchParams({
    template: "stat-correction.yml",
    title: `Stat correction: game ${gameId}, ${goal.period}/${goal.time}`,
    game_id: String(gameId), team: goal.team, period: goal.period, time: goal.time,
  });
  return `${base}?${params.toString()}`;
}

function renderGoal(gameId, goal, rosterByNumber) {
  const scorer = goal.scorer_number != null ? rosterByNumber[goal.scorer_number] || `#${goal.scorer_number}` : "Unknown";
  const a1 = goal.assist1_number != null ? rosterByNumber[goal.assist1_number] || `#${goal.assist1_number}` : null;
  const a2 = goal.assist2_number != null ? rosterByNumber[goal.assist2_number] || `#${goal.assist2_number}` : null;
  const corrections = goal._corrections || {};

  const badge = (field, label) =>
    corrections[field]
      ? el("span", { class: "corrected-badge", title: `Was ${corrections[field].original}. ${corrections[field].reason || ""}` }, ` ✎ ${label} corrected`)
      : null;

  const detailLine = el("div", {}, [
    el("strong", {}, scorer), badge("scorer_number", "scorer"),
    a1 ? "  (assist: " : "", a1, badge("assist1_number", "assist"),
    a2 ? ", " : "", a2, a2 ? badge("assist2_number", "assist") : "",
    a1 ? ")" : "", goal.situation ? ` [${goal.situation}]` : "",
  ]);

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
          const url = new URL(buildCorrectionIssueUrl(gameId, goal));
          url.searchParams.set("field", field);
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

  return el("div", { class: "box-score-goal" }, [el("div", {}, `P${goal.period}`), el("div", {}, goal.time), el("div", {}, [detailLine, toggleBtn, form])]);
}

async function openBoxScore(gameId, container) {
  const box = await loadJSON(`games/${gameId}.json`);
  container.innerHTML = "";
  const awayRoster = Object.fromEntries((box.rosters[box.away_name] || []).filter((p) => p.number != null).map((p) => [p.number, p.name]));
  const homeRoster = Object.fromEntries((box.rosters[box.home_name] || []).filter((p) => p.number != null).map((p) => [p.number, p.name]));
  const goalsByTeam = { away: box.goals.filter((g) => g.team === "away"), home: box.goals.filter((g) => g.team === "home") };

  container.appendChild(
    el("div", { class: "grid" }, [
      el("div", {}, [
        el("h3", {}, `${box.away_name} (${box.away_final})`),
        ...goalsByTeam.away.map((g) => renderGoal(gameId, g, awayRoster)),
        goalsByTeam.away.length ? null : el("p", { class: "empty-state" }, "No goals."),
      ]),
      el("div", {}, [
        el("h3", {}, `${box.home_name} (${box.home_final})`),
        ...goalsByTeam.home.map((g) => renderGoal(gameId, g, homeRoster)),
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
        el("td", {}, result ? pillFor(us, them) : el("span", { style: "color:var(--mu)" }, "—")),
        el("td", {}, result ? String(us) : "—"),
        el("td", {}, result ? String(them) : "—"),
        el("td", {}, g.pims != null ? String(g.pims) : "—"),
        el("td", {}, g.video ? el("a", { href: g.video.url, target: "_blank", rel: "noopener", onclick: (e) => e.stopPropagation() }, "🎬") : ""),
      ]
    );
    if (hasBoxScore) {
      row.addEventListener("click", async () => {
        const showing = detail.style.display !== "none";
        detail.style.display = showing ? "none" : "block";
        if (!showing && !detail.dataset.loaded) {
          await openBoxScore(g.game_id, detail);
          detail.dataset.loaded = "1";
        }
      });
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
  view.appendChild(
    pageIntro([
      "Every game, grouped by season, newest first — each season's table ends in a ",
      strong("Total"), " row summing GF, GA, PIM and our record. Click any game to open its box score. ",
      strong("Spot a wrong goal or assist?"),
      " Hit “Suggest a fix” under it: that files a correction, and the site rebuilds itself with your fix in a minute or two.",
    ])
  );

  const index = await loadJSON("games_index.json");
  const bySeason = new Map();
  for (const g of [...index].sort((a, b) => (a.iso_date < b.iso_date ? -1 : a.iso_date > b.iso_date ? 1 : a.game_id - b.game_id))) {
    if (!bySeason.has(g.season_id)) bySeason.set(g.season_id, []);
    bySeason.get(g.season_id).push(g);
  }
  const seasonIds = [...bySeason.keys()].sort((a, b) => b - a);

  seasonIds.forEach((seasonId, i) => {
    const games = bySeason.get(seasonId);
    const details = el(
      "details",
      { class: "card season-games", open: i === 0 ? "" : undefined },
      [
        el("summary", { class: "sec" }, `${games[0].season_label} (${games.length} games)`),
        el("div", { class: "table-scroll", style: "margin-top:0.6rem" }, seasonGamesTable(games)),
      ]
    );
    view.appendChild(details);
  });
}

// ---------------------------------------------------------------------------
// Head-to-head
// ---------------------------------------------------------------------------

async function renderHeadToHead() {
  const view = document.getElementById("view-head-to-head");
  view.innerHTML = "";
  view.appendChild(
    pageIntro([
      "Our all-time record against every team we've ever played, across all seasons and both team names, ",
      "with goals for and against and the last time we met. Sorted by who we've played most. ",
      "Short version: who we own, and who owns us.",
    ])
  );
  const data = await loadJSON("head_to_head.json");
  const rows = Object.entries(data).sort((a, b) => b[1].w + b[1].l + b[1].t - (a[1].w + a[1].l + a[1].t));
  const table = el("table", {}, [el("thead", {}, el("tr", {}, ["Opponent", "Record", "GF", "GA", "Last Meeting"].map((h) => el("th", {}, h))))]);
  const tbody = el("tbody");
  for (const [opp, r] of rows) {
    const last = r.meetings[r.meetings.length - 1];
    tbody.appendChild(
      el("tr", {}, [
        el("td", {}, opp),
        el("td", {}, `${r.w}-${r.l}${r.t ? "-" + r.t : ""}`),
        el("td", {}, String(r.gf)),
        el("td", {}, String(r.ga)),
        el("td", {}, last ? `${last.date} (${last.season_label}): ${last.us}-${last.them}` : "—"),
      ])
    );
  }
  table.appendChild(tbody);
  view.appendChild(el("div", { class: "card" }, [el("div", { class: "sec" }, "Head-to-Head Records"), el("div", { class: "table-scroll" }, table)]));
}

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
        el("div", {}, result ? [pillFor(us, them), ` ${us}-${them}`, g.pims != null ? ` · ${g.pims} PIM` : ""] : el("span", { class: "muted" }, g.time || "Upcoming")),
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

async function renderSchedule() {
  const view = document.getElementById("view-schedule");
  view.innerHTML = "";
  view.appendChild(
    pageIntro([
      "Our games on a real calendar, page month to month. Past games show the result and score; ",
      strong("purple"), " entries are public Stick & Puck and pick-up skates at the rink — click one to open its booking page. ",
      "The sync link below feeds the whole schedule into Bench App or your phone's calendar. Charts at the bottom show when we usually play.",
    ])
  );
  view.appendChild(benchSyncCard());
  view.appendChild(await calendarCard());
  const data = await loadJSON("schedule_heatmap.json");
  const dayOrder = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  const dayRows = dayOrder.filter((d) => data.by_day_of_week[d]).map((d) => ({ name: d, count: data.by_day_of_week[d] }));
  const hourRows = Object.entries(data.by_hour).map(([h, c]) => ({ name: h, count: c }));
  const rinkRows = Object.entries(data.by_rink).sort((a, b) => b[1] - a[1]).map(([r, c]) => ({ name: r, count: c }));
  view.appendChild(el("div", { class: "card" }, [el("div", { class: "sec" }, "Games by Day of Week"), barChart(dayRows, "count", "name")]));
  view.appendChild(el("div", { class: "card" }, [el("div", { class: "sec" }, "Games by Start Time"), barChart(hourRows, "count", "name")]));
  view.appendChild(el("div", { class: "card" }, [el("div", { class: "sec" }, "Games by Rink"), barChart(rinkRows, "count", "name")]));
}

// ---------------------------------------------------------------------------
// League outliers (division leaders + team pace)
// ---------------------------------------------------------------------------

function leaderList(rows, valueKey) {
  const box = el("div");
  for (const p of rows) {
    box.appendChild(
      el("div", { class: "bar-row" }, [
        el("div", { class: `name${isUs(p.team) ? " is-us" : ""}` }, `${p.name} (${p.team})`),
        el("span", {}, [sparkSpan(p.spark_svg)]),
        el("div", {}, String(valueKey(p))),
      ])
    );
  }
  return box;
}

async function renderLeague() {
  const view = document.getElementById("view-league");
  view.innerHTML = "";
  view.appendChild(
    pageIntro([
      "Who to measure ourselves against: the division's leaders in goals, assists, points and PIM for a chosen season — ",
      "our guys highlighted in ", strong("blue"), ". Below that, every team's cumulative goal differential: ",
      "how the standings actually got the way they are.",
    ])
  );
  const [outliers, teamPace] = await Promise.all([loadJSON("league_outliers.json"), loadJSON("team_pace.json")]);
  const seasonIds = Object.keys(outliers).sort((a, b) => Number(b) - Number(a));
  const defaultSeason = latestSeasonWithContent(outliers, (s) => !s.leaders || !s.leaders.points.length);

  const selector = el(
    "select",
    {},
    seasonIds.map((id) => {
      const attrs = { value: id };
      if (id === defaultSeason) attrs.selected = "selected";
      return el("option", attrs, outliers[id].season_label);
    })
  );
  const body = el("div");
  view.appendChild(el("div", { class: "card" }, [el("div", { class: "sec" }, "League Outliers"), el("div", { class: "fbar" }, [el("label", {}, "Season"), selector])]));
  view.appendChild(body);

  function draw(seasonId) {
    body.innerHTML = "";
    const season = outliers[seasonId];
    if (!season || !season.leaders.points.length) {
      body.appendChild(el("div", { class: "card" }, el("p", { class: "empty-state" }, "No games played yet this season.")));
      return;
    }
    const card = el("div", { class: "card" }, [el("div", { class: "sec" }, `${season.season_label} — ${season.level_label || "Division"} Leaders`)]);
    const grid = el("div", { class: "grid" });
    grid.appendChild(el("div", {}, [el("h3", {}, "Goals"), leaderList(season.leaders.goals, (p) => p.goals)]));
    grid.appendChild(el("div", {}, [el("h3", {}, "Assists"), leaderList(season.leaders.assists, (p) => p.assists)]));
    grid.appendChild(el("div", {}, [el("h3", {}, "Points"), leaderList(season.leaders.points, (p) => p.points)]));
    grid.appendChild(el("div", {}, [el("h3", {}, "PIM"), leaderList(season.leaders.pims, (p) => p.pims)]));
    card.appendChild(grid);
    body.appendChild(card);

    const teams = teamPace[seasonId] || [];
    if (teams.length) {
      const paceRows = teams.filter((t) => t.games.length).map((t) => ({ name: t.name, is_us: t.is_us, diff: t.games[t.games.length - 1].cume_diff })).sort((a, b) => b.diff - a.diff);
      if (paceRows.length) {
        body.appendChild(el("div", { class: "card" }, [el("div", { class: "sec" }, "Team Pace: Cumulative Goal Differential"), divergingBarChart(paceRows, "diff", "name")]));
      }
    }
  }

  selector.addEventListener("change", () => draw(selector.value));
  draw(defaultSeason);
}

// ---------------------------------------------------------------------------
// Scouting Report
// ---------------------------------------------------------------------------

async function renderScouting() {
  const view = document.getElementById("view-scouting");
  view.innerHTML = "";
  view.appendChild(
    pageIntro([
      "Auto-built for our ", strong("next scheduled game"),
      " — their form, who to watch, their goalie, and film of past meetings. ",
      "It rebuilds itself every night, so check it the day of. No one has to write it.",
    ])
  );
  const r = await loadJSON("scouting_report.json");

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
        el("ul", { class: "keys-list" }, r.keys_to_game.map((k) => el("li", {}, k))),
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
                el("div", {}, t.name),
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

  if (r.pim_leader) {
    view.appendChild(
      el("div", { class: "card" }, [
        el("div", { class: "sec" }, "Discipline Watch"),
        el("p", {}, `${r.pim_leader.name} leads ${r.opponent.name} with ${r.pim_leader.pims} PIM this tracked season.`),
      ])
    );
  }

  if (r.goalies && r.goalies.length) {
    const table = el("table", {}, [
      el("thead", {}, el("tr", {}, [tipTh("Goalie", "Goalie"), tipTh("GP", "GP"), tipTh("W-L", "W-L"), tipTh("GAA", "GAA"), tipTh("SV%", "SV%")])),
    ]);
    const tbody = el("tbody");
    for (const g of r.goalies) {
      tbody.appendChild(el("tr", {}, [el("td", {}, g.name), el("td", {}, String(g.gp)), el("td", {}, `${g.w || 0}-${g.l || 0}`), el("td", {}, g.gaa ?? "—"), el("td", {}, g.save_pct ?? "—")]));
    }
    table.appendChild(tbody);
    view.appendChild(el("div", { class: "card" }, [el("div", { class: "sec" }, "Goalies"), el("div", { class: "table-scroll" }, table)]));
  }

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
      { name: "Shots, +/−", means: "Shown only where the league bothered to fill them in.", formula: "as reported, never recomputed", read: "Usually blank — don't read into the gaps." },
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

async function renderMetrics() {
  const view = document.getElementById("view-metrics");
  view.innerHTML = "";
  view.appendChild(
    pageIntro([
      "Every number on this site: what it means, how it's actually calculated, and what counts as good. ",
      "If a stat anywhere looks wrong or surprising, start here — then check ", strong("How the data works"), " at the bottom.",
    ])
  );

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
        el("li", {}, [strong("Game film. "), "Videos come from our YouTube playlist, matched to games by the “Game #” tag in each description — so tagging a new upload is all it takes to make it show up here."]),
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
  insights: renderInsights,
  leaderboards: renderLeaderboards,
  games: renderGames,
  "head-to-head": renderHeadToHead,
  schedule: renderSchedule,
  league: renderLeague,
  metrics: renderMetrics,
};

function activateTab(name) {
  for (const btn of document.querySelectorAll("nav.tabs button")) btn.classList.toggle("active", btn.dataset.view === name);
  for (const section of document.querySelectorAll("section.view")) section.classList.toggle("active", section.id === `view-${name}`);
  if (!state[name]) {
    state[name] = true;
    renderers[name]().catch((err) => {
      document.getElementById(`view-${name}`).innerHTML = `<div class="card empty-state">Couldn't load data: ${err.message}</div>`;
    });
  }
}

document.getElementById("tabs").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-view]");
  if (btn) activateTab(btn.dataset.view);
});

initTooltipSystem();
activateTab("overview");

loadJSON("meta.json")
  .then((m) => {
    const d = new Date(m.generated_at);
    document.getElementById("stamp").textContent = `Updated ${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
  })
  .catch(() => {});
