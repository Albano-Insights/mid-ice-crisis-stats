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

function statTile(label, value) {
  return el("div", { class: "stat-tile" }, [
    el("div", { class: "value" }, String(value)),
    el("div", { class: "label" }, label),
  ]);
}

function divergingBarChart(rows, valueKey, labelKey) {
  // For series that cross zero (e.g. goal differential) -- barChart assumes a 0..max scale and would
  // misrepresent negative values, so this draws bars growing left/right from a center line instead.
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

// ---------------------------------------------------------------------------
// Sparklines + trend badges (shared by Overview, Leaderboards, League Outliers)
// ---------------------------------------------------------------------------

const SVG_NS = "http://www.w3.org/2000/svg";

function sparkline(values, { width = 100, height = 28, strokeWidth = 2 } = {}) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", "sparkline");
  svg.setAttribute("width", width);
  svg.setAttribute("height", height);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

  if (!values || values.length < 2) {
    const line = document.createElementNS(SVG_NS, "line");
    line.setAttribute("x1", 0);
    line.setAttribute("x2", width);
    line.setAttribute("y1", height / 2);
    line.setAttribute("y2", height / 2);
    line.setAttribute("stroke", "var(--border)");
    line.setAttribute("stroke-width", 1);
    svg.appendChild(line);
    return svg;
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const pad = strokeWidth;
  const stepX = (width - pad * 2) / (values.length - 1);
  const points = values.map((v, i) => {
    const x = pad + i * stepX;
    const y = pad + (1 - (v - min) / range) * (height - pad * 2);
    return [x, y];
  });

  const linePath = points.map((p) => p.join(",")).join(" ");
  const areaPath = `${pad},${height} ${linePath} ${width - pad},${height}`;

  const area = document.createElementNS(SVG_NS, "polygon");
  area.setAttribute("points", areaPath);
  area.setAttribute("fill", "var(--chart-bar-2)");
  area.setAttribute("opacity", "0.35");
  svg.appendChild(area);

  const polyline = document.createElementNS(SVG_NS, "polyline");
  polyline.setAttribute("points", linePath);
  polyline.setAttribute("fill", "none");
  polyline.setAttribute("stroke", "var(--chart-bar)");
  polyline.setAttribute("stroke-width", strokeWidth);
  polyline.setAttribute("stroke-linecap", "round");
  polyline.setAttribute("stroke-linejoin", "round");
  svg.appendChild(polyline);

  const [lastX, lastY] = points[points.length - 1];
  const dot = document.createElementNS(SVG_NS, "circle");
  dot.setAttribute("cx", lastX);
  dot.setAttribute("cy", lastY);
  dot.setAttribute("r", strokeWidth + 0.5);
  dot.setAttribute("fill", "var(--chart-bar)");
  svg.appendChild(dot);

  return svg;
}

const TREND_ARROW = { hot: "▲", cold: "▼", steady: "►" };

function trendBadge(trend, { compact = false } = {}) {
  if (!trend) return null;
  const arrow = TREND_ARROW[trend.direction] || "►";
  const text = compact ? arrow : `${arrow} ${trend.label}`;
  return el("span", { class: `trend-badge ${trend.direction}`, title: trend.label }, text);
}

// ---------------------------------------------------------------------------
// Overview
// ---------------------------------------------------------------------------

function kpiCard(label, value, trendData) {
  const children = [el("div", { class: "label" }, label), el("div", { class: "value-row" }, [el("div", { class: "value" }, String(value))])];
  if (trendData) {
    children.push(sparkline(trendData.sparkline));
    children.push(trendBadge(trendData.trend));
  }
  return el("div", { class: "kpi-card" }, children);
}

async function renderOverview() {
  const view = document.getElementById("view-overview");
  view.innerHTML = "";
  const summary = await loadJSON("team_summary.json");
  const o = summary.overall;
  const streak = summary.current_streak;
  const form = summary.recent_form || {};

  const kpis = el("div", { class: "kpi-grid" }, [
    kpiCard("Record", `${o.w}-${o.l}${o.t ? "-" + o.t : ""}`),
    kpiCard("Points", o.pts),
    kpiCard("Goal Diff", o.gf - o.ga >= 0 ? `+${o.gf - o.ga}` : String(o.gf - o.ga), form.goal_diff),
    kpiCard("Form (last games)", streak.result ? `${streak.length}${streak.result}` : "—", form.points_pace),
    kpiCard("PIM", o.pims),
  ]);

  view.appendChild(el("div", { class: "card" }, [el("h2", {}, "All-Time (since Fall 2025)"), kpis]));

  const seasonRows = Object.entries(summary.by_season).sort((a, b) => Number(a[0]) - Number(b[0]));
  const table = el("table", {}, [
    el("thead", {}, el("tr", {}, ["Season", "Name", "Level", "GP", "W", "L", "OT", "GF", "GA", "PTS", "PIM"].map((h) => el("th", {}, h)))),
  ]);
  const tbody = el("tbody");
  for (const [seasonId, s] of seasonRows) {
    if (s.gp == null) continue; // season not played yet
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
  view.appendChild(
    el("div", { class: "card" }, [el("h2", {}, "Season by Season"), el("div", { class: "table-scroll" }, table)])
  );
  table.appendChild(tbody);

  const upcoming = seasonRows.find(([, s]) => s.gp == null);
  if (upcoming) {
    view.appendChild(
      el("div", { class: "card" }, [
        el("h2", {}, `${upcoming[1].season_label} is upcoming`),
        el("p", { class: "empty-state" }, "No games played yet this season — check back after the puck drops."),
      ])
    );
  }
}

// ---------------------------------------------------------------------------
// Insights
// ---------------------------------------------------------------------------

const INSIGHT_ICON = {
  hot_streak: "🔥",
  cold_streak: "❄️",
  scoring_leader: "🏆",
  goal_diff: "📊",
  win_streak: "🚀",
  pim_leader: "🥊",
  our_rank: "📍",
};

function latestSeasonWithContent(dataBySeasonId, isEmptyFn) {
  const ids = Object.keys(dataBySeasonId)
    .filter((id) => !isEmptyFn(dataBySeasonId[id]))
    .sort((a, b) => Number(b) - Number(a));
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
      if (id === defaultSeason) attrs.selected = "selected"; // omit entirely when false -- setAttribute(_, undefined) would stringify to "undefined" and select every option
      return el("option", attrs, data[id].season_label);
    })
  );

  const feed = el("div", { class: "card" }, [el("h2", {}, "Division Quick Insights")]);
  const feedBody = el("div");
  feed.appendChild(el("div", {}, [el("label", {}, "Season: "), selector]));
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
        el("div", { class: "insight-card" }, [
          el("div", { class: "insight-icon" }, INSIGHT_ICON[insight.kind] || "•"),
          el("div", {}, [
            el("div", { class: "insight-headline" }, insight.headline),
            el("div", { class: "insight-detail" }, insight.detail),
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

function leaderboardTable(rows, { showTeam = false } = {}) {
  const headers = ["#", "Player"];
  if (showTeam) headers.push("Team");
  headers.push("GP", "G", "A1", "A2", "A", "PTS", "P/GP", "Hat", "PIM", "Trend");

  const table = el("table", {}, [el("thead", {}, el("tr", {}, headers.map((h) => el("th", {}, h))))]);
  const tbody = el("tbody");
  rows.forEach((r, i) => {
    const cells = [
      el("td", {}, el("span", { class: "rank-badge" }, String(i + 1))),
      el("td", {}, el("span", { class: r.team && isUs(r.team) ? "is-us" : "" }, r.name)),
    ];
    if (showTeam) cells.push(el("td", {}, r.team || ""));
    cells.push(
      el("td", {}, String(r.games_played)),
      el("td", {}, String(r.goals)),
      el("td", {}, String(r.primary_assists)),
      el("td", {}, String(r.secondary_assists)),
      el("td", {}, String(r.assists)),
      el("td", {}, String(r.points)),
      el("td", {}, String(r.points_per_game)),
      el("td", {}, String(r.hat_tricks)),
      el("td", {}, String(r.pims)),
      el("td", {}, [sparkline(r.sparkline, { width: 60, height: 20 }), trendBadge(r.trend, { compact: true })])
    );
    tbody.appendChild(el("tr", {}, cells));
  });
  table.appendChild(tbody);
  return table;
}

async function renderLeaderboards() {
  const view = document.getElementById("view-leaderboards");
  view.innerHTML = "";
  const [ourData, divisionData] = await Promise.all([
    loadJSON("player_leaderboards.json"),
    loadJSON("division_leaderboards.json"),
  ]);

  let scope = "our"; // "our" | "division"

  const scopeToggle = el("div", { class: "scope-toggle" }, [
    el("button", { class: "active", onclick: () => setScope("our") }, "Our Team"),
    el("button", { onclick: () => setScope("division") }, "Whole Division"),
  ]);

  const seasonKeys = Object.keys(ourData.by_season).sort((a, b) => Number(a) - Number(b));
  const divisionSeasonKeys = Object.keys(divisionData).sort((a, b) => Number(a) - Number(b));

  const seasonSelector = el("select", {}, []);
  function refreshSeasonOptions() {
    const keys = scope === "our" ? seasonKeys : divisionSeasonKeys;
    seasonSelector.replaceChildren(
      el("option", { value: "career" }, "All-Time (Career)"),
      ...keys.map((k) => el("option", { value: k }, `Season ${k}`))
    );
  }
  refreshSeasonOptions();

  const card = el("div", { class: "card" }, [
    el("h2", {}, "Leaderboards"),
    scopeToggle,
    el("div", {}, [el("label", {}, "Scope: "), seasonSelector]),
    el("div", { id: "top-scorers-chart" }),
  ]);
  const tableCard = el("div", { class: "card" }, [
    el("h2", {}, "Full Leaderboard"),
    el("div", { class: "table-scroll", id: "leaderboard-table" }),
  ]);
  view.appendChild(card);
  view.appendChild(tableCard);

  function currentRows() {
    if (scope === "our") {
      return seasonSelector.value === "career" ? ourData.career : ourData.by_season[seasonSelector.value] || [];
    }
    return seasonSelector.value === "career" ? [] : divisionData[seasonSelector.value] || [];
  }

  function draw() {
    const rows = [...currentRows()].sort((a, b) => b.points - a.points);
    document.getElementById("top-scorers-chart").replaceChildren(barChart(rows.slice(0, 10), "points", "name"));
    document.getElementById("leaderboard-table").replaceChildren(leaderboardTable(rows, { showTeam: scope === "division" }));
  }

  function setScope(next) {
    scope = next;
    for (const btn of scopeToggle.querySelectorAll("button")) btn.classList.remove("active");
    scopeToggle.querySelector(`button:nth-child(${next === "our" ? 1 : 2})`).classList.add("active");

    const previousValue = seasonSelector.value;
    refreshSeasonOptions(); // rebuilds <option>s, which resets .value -- so set it AFTER, not before
    const keys = scope === "our" ? seasonKeys : divisionSeasonKeys;
    if (scope === "division" && previousValue === "career") {
      seasonSelector.value = keys[keys.length - 1] || "career";
    } else if (keys.includes(previousValue)) {
      seasonSelector.value = previousValue;
    }
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
    game_id: String(gameId),
    team: goal.team,
    period: goal.period,
    time: goal.time,
  });
  return `${base}?${params.toString()}`;
}

function renderGoal(gameId, goal, rosterByNumber) {
  // goal.scorer_number/assist*_number can genuinely be null (unattributed goal, unassisted goal) --
  // must check that explicitly rather than doing rosterByNumber[null], since JS stringifies a null
  // key to "null" for property access, which would wrongly match a real roster entry whose own
  // jersey number is missing (e.g. a backup goalie with no number recorded).
  const scorer = goal.scorer_number != null ? rosterByNumber[goal.scorer_number] || `#${goal.scorer_number}` : "Unknown";
  const a1 = goal.assist1_number != null ? rosterByNumber[goal.assist1_number] || `#${goal.assist1_number}` : null;
  const a2 = goal.assist2_number != null ? rosterByNumber[goal.assist2_number] || `#${goal.assist2_number}` : null;
  const corrections = goal._corrections || {};

  const badge = (field, label) =>
    corrections[field]
      ? el(
          "span",
          { class: "corrected-badge", title: `Was ${corrections[field].original}. ${corrections[field].reason || ""}` },
          ` ✎ ${label} corrected`
        )
      : null;

  const detailLine = el("div", {}, [
    el("strong", {}, scorer),
    badge("scorer_number", "scorer"),
    a1 ? "  (assist: " : "",
    a1,
    badge("assist1_number", "assist"),
    a2 ? ", " : "",
    a2,
    a2 ? badge("assist2_number", "assist") : "",
    a1 ? ")" : "",
    goal.situation ? ` [${goal.situation}]` : "",
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
          const original =
            field === "scorer_number" ? goal.scorer_number : field === "assist1_number" ? goal.assist1_number : goal.assist2_number;
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

  return el("div", { class: "box-score-goal" }, [
    el("div", {}, `P${goal.period}`),
    el("div", {}, goal.time),
    el("div", {}, [detailLine, toggleBtn, form]),
  ]);
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
    el("div", { class: "info-note" }, [
      el("strong", {}, "Spot a wrong goal or assist? "),
      "Expand any game below, then click ",
      el("strong", {}, "“Suggest a fix”"),
      " under the goal in question. That opens a pre-filled GitHub issue — submit it and the site " +
        "corrects itself automatically within a minute or two, with your reason kept as a note on the goal.",
    ])
  );

  const index = await loadJSON("games_index.json");
  const sorted = [...index].sort((a, b) => b.game_id - a.game_id);

  const list = el("div", { class: "card" }, [el("h2", {}, "Games (most recent first)")]);
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
      [
        el("div", {}, [`${g.date} · ${g.season_label} vs ${opp}`]),
        el("div", {}, [pillFor(us, them), ` ${us}-${them}`]),
      ]
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

  const rows = Object.entries(data).sort((a, b) => (b[1].w + b[1].l + b[1].t) - (a[1].w + a[1].l + a[1].t));
  const table = el("table", {}, [
    el("thead", {}, el("tr", {}, ["Opponent", "Record", "GF", "GA", "Last Meeting"].map((h) => el("th", {}, h)))),
  ]);
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
  view.appendChild(
    el("div", { class: "card" }, [el("h2", {}, "Head-to-Head Records"), el("div", { class: "table-scroll" }, table)])
  );
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

  view.appendChild(el("div", { class: "card" }, [el("h2", {}, "Games by Day of Week"), barChart(dayRows, "count", "name")]));
  view.appendChild(el("div", { class: "card" }, [el("h2", {}, "Games by Start Time"), barChart(hourRows, "count", "name")]));
  view.appendChild(el("div", { class: "card" }, [el("h2", {}, "Games by Rink"), barChart(rinkRows, "count", "name")]));
}

// ---------------------------------------------------------------------------
// League outliers (division leaders + team pace)
// ---------------------------------------------------------------------------

function leaderList(rows, key, valueKey) {
  const box = el("div");
  for (const p of rows) {
    const mine = isUs(p.team);
    box.appendChild(
      el("div", { class: "bar-row" }, [
        el("div", { class: `name${mine ? " is-us" : ""}` }, `${p.name} (${p.team})`),
        sparkline(p.sparkline, { width: 60, height: 18 }),
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
    const card = el("div", { class: "card" }, [
      el("h2", {}, `${season.season_label} — ${season.level_label || "Division"} Leaders`),
    ]);
    const grid = el("div", { class: "grid" });
    grid.appendChild(el("div", {}, [el("h3", {}, "Goals"), leaderList(season.leaders.goals, "goals", (p) => p.goals)]));
    grid.appendChild(el("div", {}, [el("h3", {}, "Assists"), leaderList(season.leaders.assists, "assists", (p) => p.assists)]));
    grid.appendChild(el("div", {}, [el("h3", {}, "Points"), leaderList(season.leaders.points, "points", (p) => p.points)]));
    grid.appendChild(el("div", {}, [el("h3", {}, "PIM"), leaderList(season.leaders.pims, "pims", (p) => p.pims)]));
    card.appendChild(grid);
    view.appendChild(card);

    const teams = teamPace[seasonId] || [];
    if (teams.length) {
      const paceRows = teams
        .filter((t) => t.games.length)
        .map((t) => ({ name: t.name, is_us: t.is_us, diff: t.games[t.games.length - 1].cume_diff }))
        .sort((a, b) => b.diff - a.diff);
      view.appendChild(
        el("div", { class: "card" }, [
          el("h2", {}, "Team Pace: Cumulative Goal Differential"),
          divergingBarChart(paceRows, "diff", "name"),
        ])
      );
    }
  }
}

// ---------------------------------------------------------------------------
// Tab wiring
// ---------------------------------------------------------------------------

const renderers = {
  overview: renderOverview,
  insights: renderInsights,
  leaderboards: renderLeaderboards,
  games: renderGames,
  "head-to-head": renderHeadToHead,
  schedule: renderSchedule,
  league: renderLeague,
};

function activateTab(name) {
  for (const btn of document.querySelectorAll("nav.tabs button")) {
    btn.classList.toggle("active", btn.dataset.view === name);
  }
  for (const section of document.querySelectorAll("section.view")) {
    section.classList.toggle("active", section.id === `view-${name}`);
  }
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

activateTab("overview");
