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

async function renderGames() {
  const view = document.getElementById("view-games");
  view.innerHTML = "";
  view.appendChild(
    el("div", { class: "info-note", style: "background:var(--bg3);border-radius:10px;padding:0.7rem 0.9rem;font-size:0.85em;color:var(--mu);margin-bottom:0.9rem" }, [
      el("strong", { style: "color:var(--tx)" }, "Spot a wrong goal or assist? "),
      "Expand any game below, then click ",
      el("strong", { style: "color:var(--tx)" }, "“Suggest a fix”"),
      " under the goal in question. That opens a pre-filled GitHub issue — submit it and the site corrects itself automatically within a minute or two, with your reason kept as a note on the goal.",
    ])
  );

  const index = await loadJSON("games_index.json");
  const sorted = [...index].sort((a, b) => b.game_id - a.game_id);
  const list = el("div", { class: "card" }, [el("div", { class: "sec" }, "Games (most recent first)")]);
  for (const g of sorted) {
    const usHome = isUs(g.home_name);
    const us = usHome ? g.home_final : g.away_final;
    const them = usHome ? g.away_final : g.home_final;
    const opp = usHome ? g.away_name : g.home_name;
    const detail = el("div", { class: "card", style: "display:none;" });
    const item = el(
      "div",
      {
        class: "game-list-item",
        onclick: async () => {
          const showing = detail.style.display !== "none";
          detail.style.display = showing ? "none" : "block";
          if (!showing && !detail.dataset.loaded) {
            await openBoxScore(g.game_id, detail);
            detail.dataset.loaded = "1";
          }
        },
      },
      [el("div", {}, [`${g.date} · ${g.season_label} vs ${opp}`]), el("div", {}, [pillFor(us, them), ` ${us}-${them}`])]
    );
    list.appendChild(item);
    list.appendChild(detail);
  }
  view.appendChild(list);
}

// ---------------------------------------------------------------------------
// Head-to-head
// ---------------------------------------------------------------------------

async function renderHeadToHead() {
  const view = document.getElementById("view-head-to-head");
  view.innerHTML = "";
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

async function renderSchedule() {
  const view = document.getElementById("view-schedule");
  view.innerHTML = "";
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
  const [outliers, teamPace] = await Promise.all([loadJSON("league_outliers.json"), loadJSON("team_pace.json")]);
  const seasonIds = Object.keys(outliers).sort((a, b) => Number(b) - Number(a));
  for (const seasonId of seasonIds) {
    const season = outliers[seasonId];
    const card = el("div", { class: "card" }, [el("div", { class: "sec" }, `${season.season_label} — ${season.level_label || "Division"} Leaders`)]);
    const grid = el("div", { class: "grid" });
    grid.appendChild(el("div", {}, [el("h3", {}, "Goals"), leaderList(season.leaders.goals, (p) => p.goals)]));
    grid.appendChild(el("div", {}, [el("h3", {}, "Assists"), leaderList(season.leaders.assists, (p) => p.assists)]));
    grid.appendChild(el("div", {}, [el("h3", {}, "Points"), leaderList(season.leaders.points, (p) => p.points)]));
    grid.appendChild(el("div", {}, [el("h3", {}, "PIM"), leaderList(season.leaders.pims, (p) => p.pims)]));
    card.appendChild(grid);
    view.appendChild(card);

    const teams = teamPace[seasonId] || [];
    if (teams.length) {
      const paceRows = teams.filter((t) => t.games.length).map((t) => ({ name: t.name, is_us: t.is_us, diff: t.games[t.games.length - 1].cume_diff })).sort((a, b) => b.diff - a.diff);
      view.appendChild(el("div", { class: "card" }, [el("div", { class: "sec" }, "Team Pace: Cumulative Goal Differential"), divergingBarChart(paceRows, "diff", "name")]));
    }
  }
}

// ---------------------------------------------------------------------------
// Scouting Report
// ---------------------------------------------------------------------------

async function renderScouting() {
  const view = document.getElementById("view-scouting");
  view.innerHTML = "";
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
