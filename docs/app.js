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
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return node;
}

function statTile(label, value) {
  return el("div", { class: "stat-tile" }, [
    el("div", { class: "value" }, String(value)),
    el("div", { class: "label" }, label),
  ]);
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
// Overview
// ---------------------------------------------------------------------------

async function renderOverview() {
  const view = document.getElementById("view-overview");
  view.innerHTML = "";
  const summary = await loadJSON("team_summary.json");
  const o = summary.overall;
  const streak = summary.current_streak;

  const card = el("div", { class: "card" }, [
    el("h2", {}, "All-Time (since Fall 2025)"),
    el("div", { class: "grid" }, [
      statTile("Record", `${o.w}-${o.l}${o.t ? "-" + o.t : ""}`),
      statTile("Points", o.pts),
      statTile("Goals For", o.gf),
      statTile("Goals Against", o.ga),
      statTile("Goal Diff", o.gf - o.ga >= 0 ? `+${o.gf - o.ga}` : o.gf - o.ga),
      statTile("PIM", o.pims),
      statTile(
        "Current Streak",
        streak.result ? `${streak.length}${streak.result}` : "—"
      ),
    ]),
  ]);
  view.appendChild(card);

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
// Leaderboards
// ---------------------------------------------------------------------------

async function renderLeaderboards() {
  const view = document.getElementById("view-leaderboards");
  view.innerHTML = "";
  const data = await loadJSON("player_leaderboards.json");

  const seasonKeys = Object.keys(data.by_season).sort((a, b) => Number(a) - Number(b));
  const selector = el("select", { id: "leaderboard-scope" }, [
    el("option", { value: "career" }, "All-Time (Career)"),
    ...seasonKeys.map((k) => el("option", { value: k }, `Season ${k}`)),
  ]);

  const card = el("div", { class: "card" }, [
    el("h2", {}, "Top Scorers"),
    el("div", {}, [el("label", {}, "Scope: "), selector]),
    el("div", { id: "top-scorers-chart" }),
  ]);
  const tableCard = el("div", { class: "card" }, [
    el("h2", {}, "Full Leaderboard"),
    el("div", { class: "table-scroll", id: "leaderboard-table" }),
  ]);
  view.appendChild(card);
  view.appendChild(tableCard);

  function draw(scope) {
    const rows = scope === "career" ? data.career : data.by_season[scope];
    const sorted = [...rows].sort((a, b) => b.points - a.points);
    document.getElementById("top-scorers-chart").replaceChildren(barChart(sorted.slice(0, 10), "points", "name"));

    const table = el("table", {}, [
      el(
        "thead",
        {},
        el(
          "tr",
          {},
          ["Player", "GP", "G", "A1", "A2", "A", "PTS", "P/GP", "Hat", "PIM"].map((h) => el("th", {}, h))
        )
      ),
    ]);
    const tbody = el("tbody");
    for (const r of sorted) {
      tbody.appendChild(
        el("tr", {}, [
          el("td", {}, r.name),
          el("td", {}, String(r.games_played)),
          el("td", {}, String(r.goals)),
          el("td", {}, String(r.primary_assists)),
          el("td", {}, String(r.secondary_assists)),
          el("td", {}, String(r.assists)),
          el("td", {}, String(r.points)),
          el("td", {}, String(r.points_per_game)),
          el("td", {}, String(r.hat_tricks)),
          el("td", {}, String(r.pims)),
        ])
      );
    }
    table.appendChild(tbody);
    document.getElementById("leaderboard-table").replaceChildren(table);
  }

  selector.addEventListener("change", () => draw(selector.value));
  draw("career");
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
  const title = encodeURIComponent(`Stat correction: game ${gameId}, ${goal.period}/${goal.time}`);
  const base = `https://github.com/${CONFIG.repo}/issues/new`;
  const params = new URLSearchParams({
    template: "stat-correction.yml",
    title: `Stat correction: game ${gameId}, ${goal.period}/${goal.time}`,
    "game_id": String(gameId),
    "team": goal.team,
    "period": goal.period,
    "time": goal.time,
  });
  return `${base}?${params.toString()}`;
}

function renderGoal(gameId, goal, rosterByNumber) {
  const scorer = rosterByNumber[goal.scorer_number] || `#${goal.scorer_number}`;
  const a1 = goal.assist1_number != null ? rosterByNumber[goal.assist1_number] || `#${goal.assist1_number}` : null;
  const a2 = goal.assist2_number != null ? rosterByNumber[goal.assist2_number] || `#${goal.assist2_number}` : null;
  const corrections = goal._corrections || {};

  const badge = (field, label) =>
    corrections[field]
      ? el(
          "span",
          {
            class: "corrected-badge",
            title: `Was ${corrections[field].original}. ${corrections[field].reason || ""}`,
          },
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

  const awayRoster = Object.fromEntries((box.rosters[box.away_name] || []).map((p) => [p.number, p.name]));
  const homeRoster = Object.fromEntries((box.rosters[box.home_name] || []).map((p) => [p.number, p.name]));

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
    el(
      "thead",
      {},
      el("tr", {}, ["Opponent", "Record", "GF", "GA", "Last Meeting"].map((h) => el("th", {}, h)))
    ),
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
  const dayRows = dayOrder
    .filter((d) => data.by_day_of_week[d])
    .map((d) => ({ name: d, count: data.by_day_of_week[d] }));

  const hourRows = Object.entries(data.by_hour).map(([h, c]) => ({ name: h, count: c }));

  const rinkRows = Object.entries(data.by_rink)
    .sort((a, b) => b[1] - a[1])
    .map(([r, c]) => ({ name: r, count: c }));

  view.appendChild(
    el("div", { class: "card" }, [el("h2", {}, "Games by Day of Week"), barChart(dayRows, "count", "name")])
  );
  view.appendChild(
    el("div", { class: "card" }, [el("h2", {}, "Games by Start Time"), barChart(hourRows, "count", "name")])
  );
  view.appendChild(
    el("div", { class: "card" }, [el("h2", {}, "Games by Rink"), barChart(rinkRows, "count", "name")])
  );
}

// ---------------------------------------------------------------------------
// League outliers
// ---------------------------------------------------------------------------

async function renderLeague() {
  const view = document.getElementById("view-league");
  view.innerHTML = "";
  const data = await loadJSON("league_outliers.json");

  const seasonIds = Object.keys(data).sort((a, b) => Number(b) - Number(a));
  for (const seasonId of seasonIds) {
    const season = data[seasonId];
    const card = el("div", { class: "card" }, [
      el("h2", {}, `${season.season_label} — ${season.level_label || "Division"} Leaders`),
    ]);
    const grid = el("div", { class: "grid" });
    for (const [label, key] of [
      ["Goals", "goals"],
      ["Assists", "assists"],
      ["Points", "points"],
      ["PIM", "pims"],
    ]) {
      const box = el("div", {}, [el("h3", {}, label)]);
      for (const p of season.leaders[key]) {
        const value = key === "goals" ? p.goals : key === "assists" ? p.assists : key === "points" ? p.pts : p.pims;
        const mine = isUs(p.team);
        box.appendChild(
          el("div", { class: "bar-row" }, [
            el("div", { class: "name", style: mine ? "font-weight:700;color:var(--accent)" : "" }, `${p.name} (${p.team})`),
            el("div", {}, ""),
            el("div", {}, String(value)),
          ])
        );
      }
      grid.appendChild(box);
    }
    card.appendChild(grid);
    view.appendChild(card);
  }
}

// ---------------------------------------------------------------------------
// Tab wiring
// ---------------------------------------------------------------------------

const renderers = {
  overview: renderOverview,
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
