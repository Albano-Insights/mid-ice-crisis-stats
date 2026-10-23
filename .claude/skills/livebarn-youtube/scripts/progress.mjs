// Pipeline progress: one shared state file per job, a terminal view, and a local web view.
//
// Publishing a game is a long chain -- encode, upload, then the data writes that make the
// dashboard link it -- and almost all of it runs detached for hours. Before this, the only way to
// know where a job sat was to grep a 1.5 MB ffmpeg log by hand. Each command now reports into one
// JSON state file, so `status` can answer "where is it" from any shell, and `status --serve` can
// answer it without a terminal at all.
//
// WHY FRAMES, NOT TIME, IS THE PRIMARY NUMBER. On 2026-10-18 the build wrote 61,697 of 156,690
// frames while ffmpeg reported `time=01:27:03  dup=1 drop=0` and exited 0 -- time said 100% done
// and was wrong. A time-based bar would have shown a full bar and taught us nothing. Tracking
// frames against the frames the cut implies makes that divergence visible WHILE IT HAPPENS, so
// `warn` is set whenever the two disagree by more than a rounding error.

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import http from 'node:http';

const STATE_DIR = path.join(process.env.LOCALAPPDATA || os.homedir(), 'livebarn-youtube', 'state');
const STATE = path.join(STATE_DIR, 'current.json');

// Relative wall-clock weight of each stage, so "2 of 3 done" does not read as 67% when the last
// two stages are minutes against an hour. Measured on the 2026-10-18 game.
const WEIGHT = {
  video: 100, audio: 4, mux: 2,
  upload: 25, link: 1, film: 12, describe: 1, update: 1, refresh: 8,
};

const LABEL = {
  video: 'encode video', audio: 'encode audio', mux: 'mux',
  upload: 'upload to YouTube', link: 'link video to game', film: 'film-sync anchors',
  describe: 'write description', update: 'push description', refresh: 'refresh dashboard',
};

function load() {
  try { return JSON.parse(fs.readFileSync(STATE, 'utf8')); } catch { return null; }
}

// Anchors are the thing the pipeline exists to produce, and they are invisible in the stage list:
// `film` reports "done" whether it published nine hand-keyed anchors or four linear guesses. On
// 2026-10-18 that is exactly what happened -- the chain completed green while the dashboard showed
// "no scoreboard sync for this game yet", because only `method: "manual"` entries are real.
// So read the repo directly and say how many anchors exist and how many chapters would publish.
// Computed on every request rather than written by the job, so it stays true between runs.
function anchorState(s) {
  if (!s || !s.repo || !s.game_id) return null;
  const gid = String(s.game_id);
  const read = p => { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return null; } };
  const a = read(path.join(s.repo, 'data', 'film_anchors', `${gid}.json`));
  const sync = read(path.join(s.repo, 'data', 'derived', 'film_sync.json'));
  const e = sync && sync[gid];
  const goals = (a && a.by_goal) || [];
  const pens = (a && a.by_penalty) || [];
  const vt = goals.map(g => g.video_t);
  // describe publishes chapters all-or-nothing: the manual anchors must ascend in scoresheet order.
  const ascends = vt.length > 0 && vt.every((v, i) => i === 0 || v >= vt[i - 1]);
  const methods = e ? [...new Set((e.goals || []).map(g => g.method))] : [];
  return {
    game_id: gid,
    goals: goals.length, penalties: pens.length,
    published: e ? (e.goals || []).length : 0,
    manual: e ? (e.goals || []).filter(g => g.method === 'manual').length : 0,
    methods,
    chapters: ascends ? goals.length : 0,
    blocked: vt.length > 0 && !ascends,
    estimate_only: methods.length > 0 && methods.every(m => m === 'estimate'),
  };
}

function save(s) {
  try {
    fs.mkdirSync(STATE_DIR, { recursive: true });
    s.updated = Date.now();
    fs.writeFileSync(STATE, JSON.stringify(s, null, 2));
  } catch { /* progress reporting must never break the job it reports on */ }
}

export function startJob(title, stageNames, extra = {}) {
  save({
    title, started: Date.now(), pid: process.pid, done: false, failed: null, ...extra,
    stages: stageNames.map(n => ({ name: n, label: LABEL[n] || n, status: 'pending' })),
  });
}

export function stage(name, patch) {
  const s = load();
  if (!s) return;
  const st = s.stages.find(x => x.name === name);
  if (!st) return;
  Object.assign(st, patch);
  if (patch.status === 'running') {
    for (const o of s.stages) if (o !== st && o.status === 'running') o.status = 'done';
    st.started = st.started || Date.now();
  }
  if (patch.status === 'done' || patch.status === 'failed') st.ended = Date.now();
  save(s);
}

// The game id is only known after `link` resolves it, so it is set separately from startJob.
export function setGame(gameId, repo) {
  const s = load();
  if (!s) return;
  s.game_id = gameId; s.repo = repo;
  save(s);
}

export function finishJob(failed = null) {
  const s = load();
  if (!s) return;
  s.done = true; s.failed = failed;
  for (const st of s.stages) if (st.status === 'running') st.status = failed ? 'failed' : 'done';
  save(s);
}

// ffmpeg -progress emits `key=value` lines ending in `progress=continue|end`. Feed chunks here.
export function ffmpegProgress(expectedFrames, targetSeconds, onUpdate) {
  let buf = '';
  const cur = {};
  return chunk => {
    buf += chunk;
    let i;
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
      const eq = line.indexOf('=');
      if (eq < 0) continue;
      cur[line.slice(0, eq)] = line.slice(eq + 1);
      if (!line.startsWith('progress=')) continue;
      const frames = Number(cur.frame) || 0;
      const t = (Number(cur.out_time_us) || 0) / 1e6;
      const speed = parseFloat(cur.speed) || 0;
      // frames the elapsed output time implies, vs frames actually written
      const implied = expectedFrames && targetSeconds ? (t / targetSeconds) * expectedFrames : 0;
      const behind = implied && frames ? (implied - frames) / expectedFrames : 0;
      onUpdate({
        frames, expected: expectedFrames, t, target: targetSeconds, speed,
        pct: expectedFrames ? Math.min(1, frames / expectedFrames) : (targetSeconds ? t / targetSeconds : 0),
        eta_s: speed > 0 && targetSeconds ? Math.max(0, (targetSeconds - t) / speed) : null,
        // the 2026-10-18 signature: output time complete, frames nowhere near it
        warn: behind > 0.02 ? `${Math.round(behind * 100)}% of frames missing vs elapsed time` : null,
      });
    }
  };
}

// ---------------------------------------------------------------- rendering

const fmtHMS = t => {
  t = Math.max(0, Math.round(t || 0));
  return `${Math.floor(t / 3600)}:${String(Math.floor((t % 3600) / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`;
};
const fmtEta = s => s == null ? '--' : s < 60 ? `${Math.round(s)}s` : s < 3600 ? `${Math.round(s / 60)}m` : `${Math.floor(s / 3600)}h${String(Math.round((s % 3600) / 60)).padStart(2, '0')}m`;
const bar = (p, w = 30) => '#'.repeat(Math.round((p || 0) * w)) + '.'.repeat(w - Math.round((p || 0) * w));

function overall(s) {
  let got = 0, tot = 0;
  for (const st of s.stages) {
    const w = WEIGHT[st.name] ?? 5;
    tot += w;
    got += st.status === 'done' ? w : st.status === 'running' ? w * (st.pct || 0) : 0;
  }
  return tot ? got / tot : 0;
}

export function renderText(s) {
  if (!s) return 'No job has run yet.';
  const age = (Date.now() - s.started) / 1000;
  const out = [];
  out.push(`${s.title}${s.done ? (s.failed ? '  [FAILED]' : '  [done]') : `  (pid ${s.pid}, running ${fmtEta(age)})`}`);
  if (s.out) out.push(`  output : ${s.out}`);
  if (s.cut) out.push(`  cut    : ${s.cut}`);
  out.push('');
  for (const st of s.stages) {
    const mark = { done: 'done', running: '', pending: 'pending', failed: 'FAILED', skipped: 'skipped' }[st.status] ?? st.status;
    if (st.status === 'running') {
      out.push(`  ${st.label.padEnd(20)} ${bar(st.pct)} ${String(Math.round((st.pct || 0) * 100)).padStart(3)}%`);
      const bits = [];
      if (st.frames) bits.push(`${st.frames}/${st.expected} frames`);
      if (st.t != null && st.target) bits.push(`${fmtHMS(st.t)} / ${fmtHMS(st.target)}`);
      if (st.speed) bits.push(`${st.speed.toFixed(2)}x`);
      if (st.eta_s != null) bits.push(`ETA ${fmtEta(st.eta_s)}`);
      if (st.detail) bits.push(st.detail);
      if (bits.length) out.push(`  ${''.padEnd(20)} ${bits.join('  ')}`);
      if (st.warn) out.push(`  ${''.padEnd(20)} *** ${st.warn} ***`);
    } else {
      out.push(`  ${st.label.padEnd(20)} ${mark}${st.detail ? '  ' + st.detail : ''}`);
    }
  }
  const a = anchorState(s);
  if (a) {
    out.push('');
    out.push(`  ${('anchors (game ' + a.game_id + ')').padEnd(20)} ${a.goals} goal + ${a.penalties} penalty keyed`);
    out.push(`  ${'chapters'.padEnd(20)} ${a.blocked ? 'BLOCKED - anchors do not ascend, none will publish'
      : a.chapters ? a.chapters + ' will publish' : 'none yet (needs hand-keyed anchors)'}`);
    if (a.published) out.push(`  ${'published links'.padEnd(20)} ${a.manual}/${a.published} manual${a.estimate_only ? '  (ESTIMATES ONLY - dashboard will say "no scoreboard sync")' : ''}`);
  }
  const ov = overall(s);
  out.push('');
  out.push(`  ${'overall'.padEnd(20)} ${bar(ov)} ${String(Math.round(ov * 100)).padStart(3)}%`);
  if (s.failed) out.push(`\n  FAILED: ${s.failed}`);
  return out.join('\n');
}

function html() {
  return `<!doctype html><html><head><meta charset="utf-8"><title>LiveBarn pipeline</title>
<style>
:root{--bg:#0e1116;--fg:#e6edf3;--dim:#8b949e;--ok:#3fb950;--run:#58a6ff;--warn:#f85149;--line:#21262d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 ui-monospace,Menlo,Consolas,monospace;padding:24px}
h1{font-size:16px;margin:0 0 4px}.meta{color:var(--dim);margin-bottom:18px;font-size:12px}
.s{margin:10px 0;padding:10px 12px;border:1px solid var(--line);border-radius:6px}
.s.pending{opacity:.45}.s.running{border-color:var(--run)}.s.done{border-color:var(--ok)}.s.failed{border-color:var(--warn)}
.row{display:flex;justify-content:space-between;align-items:center;gap:12px}
.lbl{font-weight:600}.pct{color:var(--dim)}
.track{height:8px;background:#161b22;border-radius:4px;margin-top:8px;overflow:hidden}
.fill{height:100%;background:var(--run);transition:width .4s}
.done .fill{background:var(--ok)}.failed .fill{background:var(--warn)}
.d{color:var(--dim);font-size:12px;margin-top:6px}
.warn{color:var(--warn);font-weight:700;margin-top:6px}
.ov{margin-top:22px;padding-top:16px;border-top:1px solid var(--line)}
.anc{margin-top:18px;padding:12px;border:1px solid var(--line);border-radius:6px}
.anc h2{font-size:13px;margin:0 0 8px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em}
.kv{display:flex;justify-content:space-between;padding:3px 0}
.kv b{font-weight:600}.good{color:var(--ok)}.bad{color:var(--warn)}.pend{color:var(--dim)}
@media(max-width:520px){body{padding:14px}}
</style></head><body>
<h1 id="t">...</h1><div class="meta" id="m"></div><div id="st"></div><div id="anc"></div>
<div class="ov"><div class="row"><span class="lbl">overall</span><span class="pct" id="op"></span></div>
<div class="track"><div class="fill" id="of" style="width:0"></div></div></div>
<script>
const hms=t=>{t=Math.max(0,Math.round(t||0));return Math.floor(t/3600)+':'+String(Math.floor(t%3600/60)).padStart(2,'0')+':'+String(t%60).padStart(2,'0')};
const eta=s=>s==null?'--':s<60?Math.round(s)+'s':s<3600?Math.round(s/60)+'m':Math.floor(s/3600)+'h'+String(Math.round(s%3600/60)).padStart(2,'0')+'m';
async function tick(){
 let s;try{s=await (await fetch('/state.json',{cache:'no-store'})).json()}catch{return}
 if(!s){document.getElementById('t').textContent='No job has run yet.';return}
 document.getElementById('t').textContent=s.title+(s.done?(s.failed?'  [FAILED]':'  [done]'):'');
 document.getElementById('m').textContent=[s.out,s.cut,s.done?'':'pid '+s.pid].filter(Boolean).join('  |  ');
 document.getElementById('st').innerHTML=s.stages.map(st=>{
  const p=Math.round((st.pct||0)*100), b=[];
  if(st.frames)b.push(st.frames.toLocaleString()+' / '+st.expected.toLocaleString()+' frames');
  if(st.t!=null&&st.target)b.push(hms(st.t)+' / '+hms(st.target));
  if(st.speed)b.push(st.speed.toFixed(2)+'x');
  if(st.eta_s!=null)b.push('ETA '+eta(st.eta_s));
  if(st.detail)b.push(st.detail);
  return '<div class="s '+st.status+'"><div class="row"><span class="lbl">'+st.label+'</span>'+
   '<span class="pct">'+(st.status==='running'?p+'%':st.status)+'</span></div>'+
   (st.status==='running'||st.status==='done'?'<div class="track"><div class="fill" style="width:'+(st.status==='done'?100:p)+'%"></div></div>':'')+
   (b.length?'<div class="d">'+b.join(' &middot; ')+'</div>':'')+
   (st.warn?'<div class="warn">*** '+st.warn+' ***</div>':'')+'</div>';
 }).join('');
 const a=s.anchors;const A=document.getElementById('anc');
 if(!a){A.innerHTML=''}else{
  const chap=a.blocked?['BLOCKED - anchors do not ascend, none publish','bad']
   :a.chapters?[a.chapters+' will publish','good']:['none yet - needs hand-keyed anchors','pend'];
  const pub=a.published?(a.manual+'/'+a.published+' manual'+(a.estimate_only?' - ESTIMATES ONLY':'')):'none published';
  A.innerHTML='<div class="anc"><h2>anchors &amp; chapters &middot; game '+a.game_id+'</h2>'+
   '<div class="kv"><span>keyed</span><b>'+a.goals+' goal &middot; '+a.penalties+' penalty</b></div>'+
   '<div class="kv"><span>chapters</span><b class="'+chap[1]+'">'+chap[0]+'</b></div>'+
   '<div class="kv"><span>dashboard links</span><b class="'+(a.estimate_only?'bad':a.manual?'good':'pend')+'">'+pub+'</b></div>'+
   (a.estimate_only?'<div class="warn">dashboard will show "no scoreboard sync for this game yet"</div>':'')+
   '</div>'}
 const W={video:100,audio:4,mux:2,upload:25,link:1,film:12,describe:1,update:1,refresh:8};
 let g=0,t=0;for(const st of s.stages){const w=W[st.name]??5;t+=w;g+=st.status==='done'?w:st.status==='running'?w*(st.pct||0):0}
 const ov=t?g/t:0;
 document.getElementById('op').textContent=Math.round(ov*100)+'%';
 document.getElementById('of').style.width=(ov*100)+'%';
 document.title=(s.done?'':Math.round(ov*100)+'% - ')+'LiveBarn pipeline';
}
tick();setInterval(tick,2000);
</script></body></html>`;
}

export function serve(port = 8787) {
  const srv = http.createServer((req, res) => {
    if (req.url.startsWith('/state.json')) {
      res.writeHead(200, { 'content-type': 'application/json', 'cache-control': 'no-store' });
      const st = load();
      res.end(JSON.stringify(st ? { ...st, anchors: anchorState(st) } : null));
    } else {
      res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
      res.end(html());
    }
  });
  srv.listen(port, () => {
    console.log(`Pipeline status: http://localhost:${port}   (Ctrl+C to stop)`);
    console.log('Leave this open; it follows whatever build/upload is running.');
  });
  return srv;
}

export { load as readState, STATE as STATE_PATH };
