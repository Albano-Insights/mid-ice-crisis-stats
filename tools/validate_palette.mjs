/**
 * Re-runnable palette gate for docs/design/DESIGN_SPEC.md.
 *
 * The spec's numbers come from here, not from eyeballing: the predecessor repo shipped a 10-colour
 * ramp in which orange and green measured dE 1.8 for protanopes -- i.e. "improving" and "cooling",
 * the two most load-bearing states in the system, were the same colour. Re-run this after ANY token
 * change and paste the output into the spec.
 *
 *   node tools/validate_palette.mjs
 *
 * Checks, per mode: OKLCH lightness band, chroma floor, adjacent-pair CVD separation (protan/deutan/
 * tritan), the normal-vision floor, and >= 3:1 contrast against that mode's chart surface. The
 * scatter block re-runs the first three slots under --pairs all, because a scatter compares every
 * pair at once, not just neighbours.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { validate, contrast } from "./validate_palette_lib.js";

// The palette is READ from the stylesheet, never restated here. This gate shipped with the tokens
// hardcoded, and because the two sibling repos share token *names* but not token *values*, copying
// it across reported a clean pass for the other skin's colours -- it printed --ac #1a4fbf while
// this stylesheet said #1f5fd6. A gate that can be right about the wrong file is not a gate.
const CSS = readFileSync(resolve(import.meta.dirname, "..", "docs", "styles.css"), "utf8");

// Tokens are declared three times: :root (light), the prefers-color-scheme block, and
// [data-theme="dark"]. The light values are whatever :root sets before the first dark block; the
// dark values are the last declaration of each token, since both dark blocks agree.
function tokens() {
  const firstDark = CSS.search(/@media \(prefers-color-scheme: dark\)/);
  const lightSrc = CSS.slice(0, firstDark === -1 ? CSS.length : firstDark);
  const darkSrc = CSS.slice(firstDark === -1 ? 0 : firstDark);
  const read = (src) => {
    const out = {};
    for (const m of src.matchAll(/(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\s*;/g)) out[m[1]] = m[2];
    return out;
  };
  const light = read(lightSrc);
  const dark = { ...light, ...read(darkSrc) };
  return { light, dark };
}

const T = tokens();

function mode(t) {
  const need = (k) => {
    const v = t[k];
    if (!v) throw new Error(`docs/styles.css declares no ${k}`);
    return v;
  };
  return {
    // Charts and cards both sit on --bg2, which is the surface a mark is actually drawn against.
    surface: need("--bg2"),
    card: need("--bg2"),
    series: ["--s1", "--s2", "--s3", "--s4", "--s5"].map(need),
    text: Object.fromEntries(["--tx", "--mu", "--ac", "--gn", "--rd", "--or", "--pu", "--team"]
      .map((k) => [k, need(k)])),
  };
}

const MODES = { light: mode(T.light), dark: mode(T.dark) };

const SLOTS = ["1 Us", "2 Opponent", "3 Division avg", "4 League avg", "5 2nd player/line"];
let failed = false;

for (const [mode, cfg] of Object.entries(MODES)) {
  console.log(`\n=== ${mode.toUpperCase()}  (chart surface ${cfg.surface}) ===`);
  cfg.series.forEach((c, i) => console.log(`   s${i + 1}  ${c}   ${SLOTS[i]}`));

  const r = validate(cfg.series, { mode, surface: cfg.surface });
  for (const [name, state, detail] of r.report) {
    console.log(`  [${String(state).toUpperCase().padEnd(6)}] ${String(name).padEnd(22)} ${detail}`);
  }
  if (!r.ok) failed = true;

  // A scatter shows all five at once with no adjacency, so neighbours-only is the wrong pairlist.
  const sc = validate(cfg.series.slice(0, 3), { mode, surface: cfg.surface, pairs: "all" });
  console.log(`  scatter (slots 1-3, --pairs all): ${sc.ok ? "ALL PASS" : "FAILED"}`);
  for (const [name, state, detail] of sc.report) {
    if (String(state) === "fail" || state === false) console.log(`      [FAIL] ${name} ${detail}`);
  }
  if (!sc.ok) failed = true;

  // Text tokens are not series colours; they answer to WCAG against the card surface instead.
  console.log("  text tokens vs surface (WCAG, 4.5:1 for body text):");
  for (const [tok, hex] of Object.entries(cfg.text)) {
    const cr = contrast(hex, cfg.surface);
    const verdict = cr >= 4.5 ? "ok" : cr >= 3.0 ? "LARGE/CHROME ONLY" : "TOO LOW";
    console.log(`      ${tok.padEnd(7)} ${hex}  ${cr.toFixed(2)}:1  ${verdict}`);
  }
}
/* ---------------------------------------------------------------------------------------------
 * Tinted components: the trap a plain token-vs-surface check cannot see.
 *
 * .mb-hi/.mb-lo and .cal-badge paint their text in a token AND their background in 12-18% of that
 * SAME token. Light --gn measured a comfortable 5.28:1 against the bare card while being only
 * 4.11:1 on its own 18% tint -- a real AA failure on the Players tab, caught by tools/verify.mjs
 * and not by anything above. So every token that can land on a tint of itself is checked here, at
 * both strengths the stylesheet uses.
 * ------------------------------------------------------------------------------------------- */
const TINTS = [0.12, 0.18]; // .cal-badge background, .mb-hi/.mb-lo background
const parseHex = h => ({ r: parseInt(h.slice(1, 3), 16), g: parseInt(h.slice(3, 5), 16), b: parseInt(h.slice(5, 7), 16) });
const toHex = ({ r, g, b }) => "#" + [r, g, b].map(v => Math.round(v).toString(16).padStart(2, "0")).join("");
// color-mix(in srgb, C p%, transparent) composited over the card is a plain alpha blend.
const tintOver = (c, p, card) => {
  const a = parseHex(c), b = parseHex(card);
  return toHex({ r: a.r * p + b.r * (1 - p), g: a.g * p + b.g * (1 - p), b: a.b * p + b.b * (1 - p) });
};

for (const [mode, cfg] of Object.entries(MODES)) {
  console.log(`\n=== ${mode.toUpperCase()} tinted components (text on 12%/18% of its own token) ===`);
  for (const [tok, hex] of Object.entries(cfg.text)) {
    if (tok === "--tx" || tok === "--team") continue; // neither is ever painted on a tint of itself
    const rs = TINTS.map(p => contrast(hex, tintOver(hex, p, cfg.card)));
    const worst = Math.min(...rs);
    if (worst < 4.5) failed = true;
    console.log(`      ${tok.padEnd(7)} ${hex}  ` +
                rs.map((r, i) => `t${TINTS[i] * 100}=${r.toFixed(2)}`).join("  ") +
                `  ${worst >= 4.5 ? "ok" : "FAIL"}`);
  }
}

// The NOTE this used to print was prose, so it stayed "true" while the stylesheet disagreed.
// .cal-conf multiplies its own 12% tint by `opacity`, and at 0.75 no tier colour in this system
// clears 4.5:1 -- the best case measured is 4.30. So assert it, rather than mentioning it.
const calConf = (CSS.match(/\.cal-conf\s*\{[^}]*\}/) || [""])[0];
if (/\bopacity\s*:/.test(calConf)) {
  console.log("\n  [FAIL  ] .cal-conf carries `opacity`, which drops its 12% tint below 4.5:1");
  console.log("           (best case across tier colours measures 4.30). Use the border-left and");
  console.log("           the smaller size for separation instead.");
  failed = true;
} else {
  console.log("\n  [ok    ] .cal-conf carries no `opacity`");
}

console.log(failed ? "\nRESULT: FAILED - fix before shipping" : "\nRESULT: all checks pass");
process.exit(failed ? 1 : 0);
