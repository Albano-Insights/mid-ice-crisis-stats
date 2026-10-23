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
const body = src.slice(start, src.indexOf("// A <details> section", start));
const { lowdownWeekHeading, lowdownMovers, lowdownHeadline, lowdownLeagueHeadline } =
  new Function(body + "\nreturn { lowdownWeekHeading, lowdownMovers, lowdownHeadline, lowdownLeagueHeadline };")();

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

// --- headline ---------------------------------------------------------------------------------
// The Lowdown now leads Overview, so this is the first prose anyone reads. It has to hold up both
// in a week we played and a week the division played without us.

const gm = (id, headline, hf, af, is_ours = false) => ({ game_id: id, headline, hf, af, is_ours });
// The build writes "over this week"; the card trims it because the title row already says so.
const ourWeekNote = { kind: "our_week", headline: "We went 1-0-1 over this week", detail: "10 for, 4 against across 2 games." };
const moverNote = { kind: "mover", headline: "Rink Ratz D1 climbed to 2nd", detail: "Up from 5th on 6 points this week." };

check("our own result leads, even when another game had a wider margin",
  (() => {
    const h = lowdownHeadline({
      games: [gm(1, "Someone thrash Someone Else 9-0", 9, 0), gm(2, "Mid Ice Crisis beat X 4-3", 4, 3, true)],
      notes: [ourWeekNote],
    });
    return [h.line, h.usedGameId];
  })(),
  ["Mid Ice Crisis beat X 4-3", 2]);

check("of our own games the widest margin leads",
  lowdownHeadline({
    games: [gm(1, "Mid Ice Crisis edge X 3-2", 3, 2, true), gm(2, "Mid Ice Crisis rout Y 8-1", 8, 1, true)],
    notes: [ourWeekNote],
  }).line,
  "Mid Ice Crisis rout Y 8-1");

check("our record is the sub-line",
  lowdownHeadline({ games: [gm(1, "Mid Ice Crisis beat X 4-3", 4, 3, true)], notes: [ourWeekNote] }).sub,
  "We went 1-0-1, 10 for, 4 against across 2 games.");

check("a week we sat out leads with the division's widest margin and a mover sub-line",
  (() => {
    const h = lowdownHeadline({
      games: [gm(1, "A edge B 3-2", 3, 2), gm(2, "C rout D 7-1", 7, 1)],
      notes: [moverNote],
    });
    return [h.line, h.sub, h.usedKind];
  })(),
  ["C rout D 7-1", "Rink Ratz D1 climbed to 2nd. Up from 5th on 6 points this week.", "mover"]);

check("a week with no games at all has no headline rather than an empty one",
  [lowdownHeadline({ games: [], notes: [] }), lowdownHeadline(null)], [null, null]);

check("a headline with nothing to say in support still gives a line",
  (() => { const h = lowdownHeadline({ games: [gm(1, "A beat B 2-1", 2, 1)], notes: [] }); return [h.line, h.sub]; })(),
  ["A beat B 2-1", null]);

// --- league headline --------------------------------------------------------------------------

check("the league headline prefers the note about our own division",
  lowdownLeagueHeadline({ notes: [
    { kind: "scoring_leader", headline: "S" }, { kind: "our_rank", headline: "OURS" },
  ] }).headline, "OURS");

check("it falls down the order when the preferred kinds are absent",
  lowdownLeagueHeadline({ notes: [
    { kind: "best_record", headline: "BR" }, { kind: "tightest", headline: "T" },
  ] }).headline, "T");

check("an unrecognised note is still better than no headline",
  lowdownLeagueHeadline({ notes: [{ kind: "something_new", headline: "N" }] }).headline, "N");

check("no notes means no league headline",
  [lowdownLeagueHeadline({ notes: [] }), lowdownLeagueHeadline(null)], [null, null]);

if (failures) { console.error(`\n${failures} check(s) failed`); process.exit(1); }
console.log("\nall lowdown checks passed");
