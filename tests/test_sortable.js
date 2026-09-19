// node tests/test_sortable.js -- sortableTable's default direction must be descending (biggest
// first). The comparator's sign was once inverted, so "sort by points" showed 0-point players
// at the top of the leaderboard.
const fs = require("fs");
const src = fs.readFileSync(__dirname + "/../docs/app.js", "utf8");
const start = src.indexOf("function sortableTable(");
const body = src.slice(start, src.indexOf("\n// ----", start));
const el = (tag, attrs = {}, children = []) => ({
  tag, attrs, children: [].concat(children).filter((c) => c != null),
  replaceChildren(...c) { this.children = c; },
  querySelectorAll: () => [], querySelector: () => null, classList: { toggle() {} },
});
const sortableTable = new Function("el", body + "\nreturn sortableTable;")(el);
const rows = [{ name: "a", points: 1 }, { name: "b", points: 9 }, { name: "c", points: 4 }];
const cols = [{ label: "Player", key: "name", render: (r) => r.name }, { label: "PTS", key: "points", render: (r) => String(r.points) }];
const table = sortableTable(cols, rows, "points");
const tbody = table.children[1];
const order = tbody.children.map((tr) => tr.children[0].children[0]);
if (order.join() !== "b,c,a") { console.error("FAIL: default sort is not descending:", order); process.exit(1); }
console.log("ok: default sort descending", order.join(" > "));
