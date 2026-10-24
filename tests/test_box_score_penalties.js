// node tests/test_box_score_penalties.js -- the scoresheet's penalty table belongs in the box
// score: before this, only the PIM total survived, in the games list. Rows must name the player
// behind the number, keep chronological order within a period, and say so when there are none.
const fs = require("fs");
const src = fs.readFileSync(__dirname + "/../docs/app.js", "utf8");
const take = (from, to) => src.slice(src.indexOf(from), src.indexOf(to));
const body = take("// number -> display name for a goal line", "function buildRosterAddIssueUrl(")
  + take("// A scorer/assist field holds the jersey number", "function renderGoal(")
  + take("// The scoresheet's penalty table", "function recapCard(");

const el = (tag, attrs = {}, children = []) => ({
  tag, attrs, children: [].concat(children).filter((c) => c != null),
});
const { penaltyRows, penaltyTotal } = new Function("el", body + "\nreturn { penaltyRows, penaltyTotal };")(el);

const box = {
  home_name: "Mid Ice Crisis", away_name: "Broward Barracudas",
  rosters: {
    "Mid Ice Crisis": [
      { number: 3, position: null, name: "Gonzalo De La Cuba" },
      { number: null, wore: 13, position: null, name: "Brandon Freeland" },
    ],
    "Broward Barracudas": [{ number: 93, position: null, name: "Sean Arnts" }],
  },
  shared_numbers: {},
  penalties: {
    home: [
      { period: "2", number: 3, infraction: "Unsportsmanlike", minutes: 2, off_ice: "4:10" },
      { period: "1", number: 3, infraction: "Tripping", minutes: 2, off_ice: "9:40" },
      { period: "2", number: "Brandon Freeland", infraction: "Slashing", minutes: 2, off_ice: "11:02" },
    ],
    away: [],
  },
};
const text = (n) => (typeof n === "string" ? n : (n.children || []).map(text).join(""));
const fail = (msg) => { console.error("FAIL:", msg); process.exit(1); };

const rows = penaltyRows(box, "home").map((r) => r.children.map(text));
if (rows.length !== 3) fail(`expected 3 penalty rows, got ${rows.length}`);
if (rows[0][0] !== "P1") fail("periods out of order: " + JSON.stringify(rows.map((r) => r[0])));
// Within a period the clock counts down, so the earlier penalty has the LARGER off-ice time.
if (rows[1][1] !== "11:02" || rows[2][1] !== "4:10") fail("within-period order is wrong: " + JSON.stringify(rows));
if (!rows[0][2].startsWith("Gonzalo De La Cuba — Tripping")) fail("number not resolved to a name: " + rows[0][2]);
// A sub sharing a rostered number is carried by name on the sheet, here too.
if (!rows[1][2].startsWith("Brandon Freeland — Slashing")) fail("named penalty not rendered: " + rows[1][2]);
if (!rows[0][2].includes("(2)")) fail("minutes missing: " + rows[0][2]);

if (penaltyTotal(box, "home") !== "3 for 6 PIM") fail("wrong total: " + penaltyTotal(box, "home"));
if (penaltyTotal(box, "away") !== "none") fail("empty side should read none: " + penaltyTotal(box, "away"));
const empty = penaltyRows(box, "away");
if (empty.length !== 1 || text(empty[0]) !== "No penalties.") fail("empty side should say so");

console.log("ok: penalties render, resolve names and stay in clock order");
