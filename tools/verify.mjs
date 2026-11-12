/**
 * Headless verification for docs/. Run before shipping a skin change:
 *
 *   node tools/verify.mjs            # both themes, all four tabs
 *   node tools/verify.mjs --shots    # also write PNGs to tools/_shots/
 *
 * Why this exists: a contrast failure can look merely "dim" in a screenshot while being
 * unreadable in fact. So every colour claim here is read back out of `getComputedStyle` on the
 * real rendered node and run through the WCAG formula -- never eyeballed, never taken from the
 * stylesheet's source text (which says nothing about what actually won the cascade).
 *
 * It serves docs/ itself over loopback, because file:// blocks the fetch() calls app.js makes.
 */
import { createServer } from "node:http";
import { readFile, mkdir, access } from "node:fs/promises";
import { extname, join, resolve, normalize } from "node:path";
import puppeteer from "puppeteer-core";

const ROOT = resolve(import.meta.dirname, "..", "docs");
const SHOTS = resolve(import.meta.dirname, "_shots");
const WANT_SHOTS = process.argv.includes("--shots");

const CHROME_CANDIDATES = [
  "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
];
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css",
               ".json": "application/json", ".svg": "image/svg+xml", ".jpg": "image/jpeg",
               ".png": "image/png", ".ics": "text/calendar" };

async function findChrome() {
  for (const p of CHROME_CANDIDATES) {
    try { await access(p); return p; } catch {}
  }
  throw new Error(`Chrome not found. Tried:\n  ${CHROME_CANDIDATES.join("\n  ")}`);
}

function serve() {
  const server = createServer(async (req, res) => {
    const rel = decodeURIComponent(req.url.split("?")[0]).replace(/^\/+/, "") || "index.html";
    // Containment: a request must resolve to something inside docs/, whatever it spells.
    const full = normalize(join(ROOT, rel));
    if (!full.startsWith(ROOT)) { res.writeHead(403).end("forbidden"); return; }
    try {
      const body = await readFile(full);
      res.writeHead(200, { "content-type": MIME[extname(full)] ?? "application/octet-stream" }).end(body);
    } catch {
      res.writeHead(404).end("not found");
    }
  });
  return new Promise(ok => server.listen(0, "127.0.0.1", () => ok(server)));
}

/* --- WCAG, computed in the page against the node's real effective background --------------- */
const PAGE_HELPERS = () => {
  const parse = s => {
    const m = String(s).match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[,\s/]+/).filter(Boolean).map(Number);
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const lin = c => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
  const lum = ({ r, g, b }) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  const over = (fg, bg) => ({ r: fg.r * fg.a + bg.r * (1 - fg.a),
                              g: fg.g * fg.a + bg.g * (1 - fg.a),
                              b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1 });
  // An element's own background is usually transparent, so walk ancestors until something paints.
  const effectiveBg = node => {
    let n = node, acc = null;
    while (n && n !== document.documentElement.parentNode) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c && c.a > 0) { acc = acc ? over(acc, c) : c; if (acc.a >= 1 || c.a >= 1) return acc; }
      n = n.parentElement;
    }
    return acc ?? { r: 255, g: 255, b: 255, a: 1 };
  };
  window.__contrast = node => {
    const fgRaw = parse(getComputedStyle(node).color);
    if (!fgRaw) return null;
    const bg = effectiveBg(node);
    const fg = fgRaw.a < 1 ? over(fgRaw, bg) : fgRaw;
    const [a, b] = [lum(fg), lum(bg)].sort((x, y) => y - x);
    return (a + 0.05) / (b + 0.05);
  };
  // Only nodes that actually show text, are visible, and carry a real glyph.
  window.__textNodes = () => [...document.querySelectorAll("body *")].filter(n => {
    if (!n.offsetParent && getComputedStyle(n).position !== "fixed") return false;
    const st = getComputedStyle(n);
    if (st.visibility === "hidden" || st.display === "none" || +st.opacity === 0) return false;
    const own = [...n.childNodes].filter(c => c.nodeType === 3).map(c => c.textContent.trim()).join("");
    return /[A-Za-z0-9]/.test(own);
  });
};

const FLOOR = 4.5;      // WCAG AA, body text
const LARGE_FLOOR = 3.0; // >= 24px, or >= 18.66px bold

async function auditTheme(page, theme, url) {
  await page.goto(url, { waitUntil: "networkidle2" });
  await page.evaluate(t => document.documentElement.setAttribute("data-theme", t), theme);
  await page.evaluate(PAGE_HELPERS);

  const problems = [];
  const tabs = await page.$$eval("nav.tabs button[data-view]", bs => bs.map(b => b.dataset.view));

  for (const view of tabs) {
    await page.click(`nav.tabs button[data-view="${view}"]`);
    await page.evaluate(PAGE_HELPERS);
    // Give the view's lazy build a moment to populate.
    await page.waitForFunction(v => {
      const el = document.querySelector(`#view-${v}`);
      return el && el.textContent.trim().length > 0;
    }, { timeout: 15000 }, view).catch(() => problems.push({ view, kind: "empty-view", detail: `#view-${view} never rendered content` }));

    const found = await page.evaluate(v => {
      const root = document.querySelector(`#view-${v}`);
      if (!root) return [];
      const out = [];
      for (const n of window.__textNodes()) {
        if (!root.contains(n)) continue;
        const cr = window.__contrast(n);
        if (cr == null) continue;
        const st = getComputedStyle(n);
        const px = parseFloat(st.fontSize);
        const bold = +st.fontWeight >= 700;
        const large = px >= 24 || (px >= 18.66 && bold);
        const floor = large ? 3.0 : 4.5;
        if (cr < floor) {
          out.push({ sel: n.tagName.toLowerCase() + (n.className ? "." + String(n.className).split(/\s+/).join(".") : ""),
                     text: n.textContent.trim().slice(0, 40), ratio: +cr.toFixed(2), floor, px: +px.toFixed(1), bold });
        }
      }
      // Dedupe by selector+ratio so one repeated row doesn't flood the report.
      const seen = new Set();
      return out.filter(o => { const k = o.sel + o.ratio; if (seen.has(k)) return false; seen.add(k); return true; });
    }, view);

    for (const f of found) problems.push({ view, kind: "contrast", detail: `${f.ratio}:1 (floor ${f.floor}) ${f.sel} "${f.text}" ${f.px}px${f.bold ? " bold" : ""}` });

    if (WANT_SHOTS) {
      await mkdir(SHOTS, { recursive: true });
      await page.screenshot({ path: join(SHOTS, `${theme}-${view}.png`), fullPage: true });
    }
  }

  // The team-colour rule under the header is the skin's one structural flourish; assert it is
  // actually painted. (The sibling repo paints a gradient band on ::after instead, so this check
  // reads the border rather than the pseudo-element -- a verifier copied between skins has to
  // assert this skin's flourish, not the other one's, or it fails on a difference by design.)
  const band = await page.evaluate(() => {
    const bar = document.querySelector(".topbar");
    if (!bar) return { ok: false, why: "no .topbar" };
    const st = getComputedStyle(bar);
    const w = parseFloat(st.borderBottomWidth);
    const c = st.borderBottomColor;
    const painted = w >= 2 && c && !/transparent|rgba\(0, 0, 0, 0\)/.test(c);
    return { ok: painted, why: `border-bottom=${w}px ${c}` };
  });
  if (!band.ok) problems.push({ view: "topbar", kind: "band", detail: `team colour rule missing: ${band.why}` });

  return problems;
}

// --url <origin> audits a DEPLOYED site instead of the working tree. The local server stays the
// default because that is what a pre-commit gate should check; pointing at GitHub Pages is how we
// confirm the thing people actually load -- a path correct on disk can still 404 live.
const liveArg = process.argv.indexOf("--url");
const live = liveArg !== -1 ? process.argv[liveArg + 1].replace(/[/]$/, "") : null;
const server = live ? null : await serve();
const url = live ? `${live}/index.html`
                 : `http://127.0.0.1:${server.address().port}/index.html`;
if (live) console.log(`auditing DEPLOYED site: ${url}`);
const browser = await puppeteer.launch({ executablePath: await findChrome(), headless: "new",
                                         args: ["--no-sandbox", "--force-color-profile=srgb"] });
let failed = false;
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900 });

  const noise = [];
  page.on("console", m => { if (m.type() === "error") noise.push(`console: ${m.text()}`); });
  page.on("pageerror", e => noise.push(`pageerror: ${e.message}`));
  page.on("requestfailed", r => noise.push(`requestfailed: ${r.url()} ${r.failure()?.errorText ?? ""}`));

  for (const theme of ["light", "dark"]) {
    const problems = await auditTheme(page, theme, url);
    console.log(`\n=== ${theme.toUpperCase()} ===`);
    if (!problems.length) console.log("  no contrast or render problems");
    for (const p of problems) console.log(`  [${p.kind}] ${p.view}: ${p.detail}`);
    if (problems.length) failed = true;
  }

  // Chart.js from a CDN is expected to be absent offline; that is not a page defect.
  const real = noise.filter(n => !/cdn\.jsdelivr\.net|fonts\.g(oogleapis|static)\.com/.test(n));
  console.log(`\n=== PAGE ERRORS (${real.length}) ===`);
  for (const n of [...new Set(real)]) console.log(`  ${n}`);
  if (real.length) failed = true;
  const skipped = noise.length - real.length;
  if (skipped) console.log(`  (${skipped} CDN/font fetch message(s) ignored)`);
} finally {
  await browser.close();
  server?.close();
}
console.log(failed ? "\nRESULT: FAILED" : "\nRESULT: pass");
process.exit(failed ? 1 : 0);
