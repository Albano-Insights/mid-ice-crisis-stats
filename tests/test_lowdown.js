// node tests/test_lowdown.js -- the two pure decisions behind the League Lowdown's week card.
//
// lowdownWeekHeading has to be honest about which week it is showing: an archived season's card is
// history and must say so rather than read as current, and a window that reached back past 7 days
// because the division was quiet must say that too instead of calling four scattered games "this
// week". lowdownMovers decides which teams earn a row -- a team that held its place while banking
// points is the "still top, pulling away" case and belongs there, while one that neither moved nor
// scored is noise.
const fs = require("fs");
const src = fs.readFileSync(__dirname + "/../docs/app.js", "utf8");
const start = src.indexOf("// Pure: the week card's heading.");
const body = src.slice(start, src.indexOf("const MOVER_ARROW", start));
const { lowdownWeekHeading, lowdownMovers } =
  new Function(body + "\nreturn { lowdownWeekHeading, lowdownMovers };")();

let failures = 0;
const check = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) { console.error(`FAIL ${name}\n  got  ${g}\n  want ${w}`); failures++; }
  else console.log(`ok: ${name}`);
};

// --- headings ---------------------------------------------------------------------------------

const week = (over = {}) =>
  ({ label: "Oct 15 – Oct 22", games: 4, is_final_week: false, widened: false, ...over });

check("a normal week reads as this week",
  lowdownWeekHeading(week()), "This week · Oct 15 – Oct 22");

check("an archived season says final week, never this week",
  lowdownWeekHeading(week({ is_final_week: true, label: "Jan 25 – Feb 1" })),
  "Final week · Jan 25 – Feb 1");

check("a widened window says how many games it had to reach for",
  lowdownWeekHeading(week({ widened: true, games: 3 })),
  "Last 3 division games · Oct 15 – Oct 22");

check("final week wins over widened, because the season being over is the bigger caveat",
  lowdownWeekHeading(week({ is_final_week: true, widened: true, label: "Jan 25 – Feb 1" })),
  "Final week · Jan 25 – Feb 1");

check("no week block renders no heading rather than throwing",
  lowdownWeekHeading(null), null);

// --- movers -----------------------------------------------------------------------------------

const mover = (name, from_rank, to_rank, pts_gained) => ({ name, from_rank, to_rank, pts_gained });
const shape = (rows) => rows.map((m) => [m.name, m.dir, m.pts_gained]);

check("a climb, a fall and a hold-with-points all earn a row, tagged with direction",
  shape(lowdownMovers([
    mover("Rink Ratz D1", 5, 4, 4),
    mover("Mid Ice Crisis", 1, 1, 3),
    mover("Broward Barracudas", 2, 3, 0),
  ])),
  [["Rink Ratz D1", "up", 4], ["Mid Ice Crisis", "flat", 3], ["Broward Barracudas", "down", 0]]);

check("a team that neither moved nor scored is dropped as noise",
  shape(lowdownMovers([mover("Idle", 6, 6, 0), mover("Busy", 3, 2, 2)])),
  [["Busy", "up", 2]]);

check("the list is capped so the strip can't run away",
  lowdownMovers([
    mover("a", 8, 1, 2), mover("b", 8, 2, 2), mover("c", 8, 3, 2),
    mover("d", 8, 4, 2), mover("e", 8, 5, 2), mover("f", 8, 6, 2),
  ]).length, 5);

check("an empty or missing mover list is handled",
  [lowdownMovers([]).length, lowdownMovers(undefined).length], [0, 0]);

check("input is not mutated -- the caller's objects gain no dir field",
  (() => { const rows = [mover("x", 2, 1, 2)]; lowdownMovers(rows); return rows[0].dir; })(),
  undefined);

if (failures) { console.error(`\n${failures} check(s) failed`); process.exit(1); }
console.log("\nall lowdown checks passed");
