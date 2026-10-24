// node tests/test_roster_add_link.js -- the on-ice tag grid is built from the scoresheet roster, so
// a sub the sheet left off cannot be ticked there at all. Every bench must therefore carry the way
// out: a "Someone missing?" link that pre-fills the roster-add issue for THAT team.
const fs = require("fs");
const src = fs.readFileSync(__dirname + "/../docs/app.js", "utf8");
const start = src.indexOf("// A scoresheet that left a sub off entirely");
const body = src.slice(start, src.indexOf("\nfunction onIceSummary(", start));

const el = (tag, attrs = {}, children = []) => ({
  tag, attrs, children: [].concat(children).filter((c) => c != null),
  append(...c) { this.children.push(...c.filter((x) => x != null)); },
  addEventListener() {}, querySelectorAll: () => [], querySelector: () => null,
  classList: { toggle() {}, add() {} },
});
const CONFIG = { repo: "Albano-Insights/mid-ice-crisis-stats", ourNames: ["Mid Ice Crisis"] };
const isUs = (n) => CONFIG.ourNames.includes(n);
const sharedNumbers = () => new Set();
const rosterSkaterToken = (p) => (p.number == null ? p.name : p.number);
const parseVideoTime = () => null;
const buildOnIceIssueUrl = () => "";
const scope = new Function("el", "CONFIG", "isUs", "sharedNumbers", "rosterSkaterToken", "parseVideoTime",
  "buildOnIceIssueUrl", "URLSearchParams", body + "\nreturn { buildRosterAddIssueUrl, onIceForm };");
const { buildRosterAddIssueUrl, onIceForm } =
  scope(el, CONFIG, isUs, sharedNumbers, rosterSkaterToken, parseVideoTime, buildOnIceIssueUrl, URLSearchParams);

const box = {
  home_name: "Mid Ice Crisis", away_name: "Broward Barracudas",
  rosters: {
    "Mid Ice Crisis": [{ number: 11, position: null, name: "Jared Chase" }],
    "Broward Barracudas": [{ number: 43, position: "C", name: "Shawn Cash" }],
  },
};

const url = new URL(buildRosterAddIssueUrl(8908, box, "Mid Ice Crisis"));
const q = url.searchParams;
const fail = (msg) => { console.error("FAIL:", msg); process.exit(1); };
if (q.get("template") !== "roster-add.yml") fail("wrong issue template: " + q.get("template"));
if (q.get("game_id") !== "8908") fail("game id not pre-filled");
// The processor works the bench out from this name against the two team names -- all three have to
// be there or it can't tell which side the sub dressed on.
if (q.get("team_name") !== "Mid Ice Crisis") fail("team not pre-filled");
if (q.get("home_team_name") !== "Mid Ice Crisis" || q.get("away_team_name") !== "Broward Barracudas") fail("sides not pre-filled");

const links = [];
(function walk(n) {
  if (!n || typeof n !== "object") return;
  if (n.attrs && n.attrs.class === "onice-missing") links.push(n);
  (n.children || []).forEach(walk);
})(onIceForm(8908, { team: "home", period: "2", time: "11:20" }, box, null));
if (links.length !== 2) fail(`expected one "Someone missing?" link per bench, got ${links.length}`);
const teams = links.map((l) => new URL(l.attrs.href).searchParams.get("team_name")).sort();
if (teams.join() !== "Broward Barracudas,Mid Ice Crisis") fail("links don't cover both benches: " + teams.join());

console.log("ok: both benches offer a pre-filled roster-add link");
