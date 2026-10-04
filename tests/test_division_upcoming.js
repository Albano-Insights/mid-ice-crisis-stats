// node tests/test_division_upcoming.js -- divisionUpcoming flattens every division team's schedule
// into one "what's next" list for the Overview strip. Three things have to hold or the strip is
// worse than nothing: every game appears on BOTH teams' schedules in outlook.json and must be
// deduped, a completed or out-of-division game must never appear, and the 7-day window needs a
// floor because this division plays about once a team per week and a quiet stretch would otherwise
// render an empty strip.
const fs = require("fs");
const src = fs.readFileSync(__dirname + "/../docs/app.js", "utf8");
const start = src.indexOf("function divisionUpcoming(");
const body = src.slice(start, src.indexOf("\n// ----", start));
const divisionUpcoming = new Function(body + "\nreturn divisionUpcoming;")();

let failures = 0;
const check = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) { console.error(`FAIL ${name}\n  got  ${g}\n  want ${w}`); failures++; }
  else console.log(`ok: ${name}`);
};

// Two teams, one shared game -- the shape outlook.json actually produces.
const game = (id, iso, opponent, { home = true, final = false, inDiv = true, regular = true } = {}) =>
  ({ game_id: id, iso_date: iso, date: iso, time: "10:45 PM", rink: "Rink 2",
     opponent, home, final, in_division: inDiv, regular });

const block = (teams) => ({ teams });
const ids = (rows) => rows.map((r) => r.game_id);

// --- dedup: the same game from both sides must collapse to one card
check("a game on both teams' schedules appears once",
  ids(divisionUpcoming(block([
    { name: "Night Raiders", current_rank: 7, is_us: false, games: [game(8821, "2026-10-05", "Puckaneers", { home: true })] },
    { name: "Puckaneers", current_rank: 6, is_us: false, games: [game(8821, "2026-10-05", "Night Raiders", { home: false })] },
  ]), "2026-10-04")),
  [8821]);

// --- home/away orientation must survive whichever side was seen first
const oriented = divisionUpcoming(block([
  { name: "Puckaneers", current_rank: 6, is_us: false, games: [game(8821, "2026-10-05", "Night Raiders", { home: false })] },
  { name: "Night Raiders", current_rank: 7, is_us: false, games: [game(8821, "2026-10-05", "Puckaneers", { home: true })] },
]), "2026-10-04")[0];
check("away team is the visitor regardless of iteration order",
  [oriented.away, oriented.home, oriented.away_rank, oriented.home_rank],
  ["Puckaneers", "Night Raiders", 6, 7]);

// --- exclusions
const excl = block([{ name: "A", current_rank: 1, is_us: false, games: [
  game(1, "2026-10-05", "B"),
  game(2, "2026-10-05", "B", { final: true }),
  game(3, "2026-10-05", "Other Level", { inDiv: false }),
  game(4, "2026-10-05", "B", { regular: false }),
  game(5, "2026-10-02", "B"),
]}]);
check("completed, cross-division, non-regular and past games are all excluded",
  ids(divisionUpcoming(excl, "2026-10-04")), [1]);

// --- a game today is still upcoming (it has not been played yet tonight)
check("today's game is included", ids(divisionUpcoming(
  block([{ name: "A", current_rank: 1, is_us: false, games: [game(9, "2026-10-04", "B")] }]), "2026-10-04")), [9]);

// --- window vs floor
const many = block([{ name: "A", current_rank: 1, is_us: false, games: [
  game(1, "2026-10-05", "B"), game(2, "2026-10-06", "B"), game(3, "2026-10-09", "B"),
  game(4, "2026-10-11", "B"), game(5, "2026-10-30", "B"), game(6, "2026-11-20", "B"),
]}]);
check("inside the 7-day window, only that week shows", ids(divisionUpcoming(many, "2026-10-04")), [1, 2, 3, 4]);
check("a sparse week falls back to the floor instead of rendering empty",
  ids(divisionUpcoming(many, "2026-10-12")), [5, 6]);
check("the floor is capped by what actually remains",
  divisionUpcoming(block([{ name: "A", current_rank: 1, is_us: false, games: [game(1, "2026-12-01", "B")] }]), "2026-10-04").length, 1);

// --- our own game is marked, others are not
const us = divisionUpcoming(block([
  { name: "Mid Ice Crisis", current_rank: 1, is_us: true, games: [game(1, "2026-10-05", "Oathe HC D", { home: false })] },
  { name: "Oathe HC D", current_rank: 4, is_us: false, games: [game(1, "2026-10-05", "Mid Ice Crisis", { home: true }), game(2, "2026-10-06", "B")] },
  { name: "B", current_rank: 8, is_us: false, games: [game(2, "2026-10-06", "Oathe HC D", { home: false })] },
]), "2026-10-04");
check("is_us marks only the game we are in", us.map((r) => [r.game_id, r.is_us]), [[1, true], [2, false]]);

// --- degrade gracefully: outlook.json built before `time` existed, and junk input
const noTime = block([{ name: "A", current_rank: 1, is_us: false, games: [{ ...game(1, "2026-10-05", "B"), time: undefined }] }]);
check("a row with no time still renders (time is null, not undefined)", divisionUpcoming(noTime, "2026-10-04")[0].time, null);
check("an unranked team yields a null rank rather than throwing",
  divisionUpcoming(block([{ name: "A", is_us: false, games: [game(1, "2026-10-05", "Ghost Team")] }]), "2026-10-04")[0].home_rank, null);
check("an archived season with nothing upcoming returns []", divisionUpcoming(block([
  { name: "A", current_rank: 1, is_us: false, games: [game(1, "2026-01-05", "B", { final: true })] }]), "2026-10-04"), []);
check("missing block returns []", divisionUpcoming(undefined, "2026-10-04"), []);
check("missing today returns []", divisionUpcoming(block([]), null), []);

if (failures) { console.error(`\n${failures} check(s) failed`); process.exit(1); }
console.log("\nall division-upcoming checks passed");

// --- within one night, order by puck drop, not by game id
const sameNight = block([{ name: "A", current_rank: 1, is_us: false, games: [
  { ...game(30, "2026-10-05", "B"), time: "10:45 PM" },
  { ...game(10, "2026-10-05", "B"), time: "6:15 PM" },
  { ...game(20, "2026-10-05", "B"), time: "10:00 PM" },
  { ...game(40, "2026-10-05", "B"), time: null },
  { ...game(5, "2026-10-05", "B"), time: "12:30 AM" },
]}]);
check("games on the same night sort by time, untimed last",
  ids(divisionUpcoming(sameNight, "2026-10-04")), [5, 10, 20, 30, 40]);
check("noon and midnight are not confused",
  ids(divisionUpcoming(block([{ name: "A", current_rank: 1, is_us: false, games: [
    { ...game(1, "2026-10-05", "B"), time: "12:00 PM" },
    { ...game(2, "2026-10-05", "B"), time: "12:00 AM" },
  ]}]), "2026-10-04")), [2, 1]);

if (failures) { console.error(`\n${failures} check(s) failed`); process.exit(1); }
console.log("all ordering checks passed too");
