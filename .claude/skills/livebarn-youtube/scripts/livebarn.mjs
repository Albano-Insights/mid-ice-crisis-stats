#!/usr/bin/env node
// LiveBarn -> YouTube pipeline.
//   doctor | probe | sheet | detect | build | upload
// Run `node livebarn.mjs help` for usage. No dependencies except ffmpeg/ffprobe
// (bundled in ../bin by setup.ps1) and `googleapis` for the upload command.

import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import http from 'node:http';
import { fileURLToPath } from 'node:url';
import { describeGame, DEFAULT_REPO } from './describe.mjs';

const SCRIPT_PATH = fileURLToPath(import.meta.url);
const SCRIPT_DIR = path.dirname(SCRIPT_PATH);
const ROOT = path.resolve(SCRIPT_DIR, '..');
const BIN = path.join(ROOT, 'bin');
// Credentials live outside the skill folder so they can never end up in a git working tree.
const SECRETS = path.join(process.env.LOCALAPPDATA || path.join(os.homedir(), '.local', 'share'), 'livebarn-youtube', 'secrets');
const IS_WIN = process.platform === 'win32';

// ---------------------------------------------------------------- utilities

function findTool(name) {
  const local = path.join(BIN, name + (IS_WIN ? '.exe' : ''));
  if (fs.existsSync(local)) return local;
  const r = spawnSync(IS_WIN ? 'where' : 'which', [name], { encoding: 'utf8' });
  if (r.status === 0 && r.stdout.trim()) return r.stdout.split(/\r?\n/)[0].trim();
  return null;
}
const FFMPEG = findTool('ffmpeg');
const FFPROBE = findTool('ffprobe');

function needFfmpeg() {
  if (!FFMPEG || !FFPROBE) {
    console.error('ffmpeg/ffprobe not found. Run:  powershell -ExecutionPolicy Bypass -File "' + path.join(SCRIPT_DIR, 'setup.ps1') + '"');
    process.exit(2);
  }
}

function parseArgs(argv) {
  const pos = [], opt = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const k = a.slice(2);
      const next = argv[i + 1];
      if (next !== undefined && !next.startsWith('--')) { opt[k] = next; i++; } else opt[k] = true;
    } else pos.push(a);
  }
  return { pos, opt };
}

function runCapture(cmd, args, { binary = false } = {}) {
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    const chunks = []; let err = '';
    p.stdout.on('data', c => chunks.push(c));
    p.stderr.on('data', c => { err += c; if (err.length > 20000) err = err.slice(-10000); });
    p.on('error', reject);
    p.on('close', code => {
      const buf = Buffer.concat(chunks);
      if (code !== 0) reject(new Error(`${path.basename(cmd)} exited ${code}\n${err.slice(-2000)}`));
      else resolve(binary ? buf : buf.toString('utf8'));
    });
  });
}

function runLive(cmd, args) {
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, args, { stdio: 'inherit' });
    p.on('error', reject);
    p.on('close', code => code === 0 ? resolve() : reject(new Error(`${path.basename(cmd)} exited ${code}`)));
  });
}

function fmtTime(t) {
  t = Math.max(0, Math.round(t));
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
  return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

// "1:23:45", "83:45", "5025", or "2@12:30" (file #2, 12:30 into that file)
function parseTime(input, offsets) {
  let s = String(input).trim();
  let base = 0;
  const m = s.match(/^(\d+)@(.+)$/);
  if (m) {
    const idx = Number(m[1]) - 1;
    if (!offsets || offsets[idx] === undefined) throw new Error(`No file #${m[1]} for time "${input}"`);
    base = offsets[idx]; s = m[2];
  }
  const parts = s.split(':').map(Number);
  if (!parts.length || parts.some(Number.isNaN)) throw new Error(`Bad time "${input}" (use H:MM:SS, MM:SS, seconds, or N@MM:SS)`);
  let sec = 0; for (const p of parts) sec = sec * 60 + p;
  return base + sec;
}

const mean = a => a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0;
function median(a) { if (!a.length) return 0; const s = [...a].sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; }
function smooth(a, w) {
  const out = new Array(a.length).fill(0);
  for (let i = 0; i < a.length; i++) {
    const lo = Math.max(0, i - w), hi = Math.min(a.length - 1, i + w);
    let acc = 0; for (let j = lo; j <= hi; j++) acc += a[j];
    out[i] = acc / (hi - lo + 1);
  }
  return out;
}

// ------------------------------------------------------------- input files

const VIDEO_EXT = new Set(['.mp4', '.mov', '.mkv', '.ts', '.m4v']);
function listInputs(pos) {
  if (!pos.length) throw new Error('Give a folder of LiveBarn segments (or the files themselves).');
  let files;
  if (pos.length === 1 && fs.existsSync(pos[0]) && fs.statSync(pos[0]).isDirectory()) {
    files = fs.readdirSync(pos[0])
      .filter(f => VIDEO_EXT.has(path.extname(f).toLowerCase()) && !/_youtube\.mp4$/i.test(f))
      .map(f => path.join(pos[0], f));
  } else {
    files = pos;
  }
  files = files.map(f => path.resolve(f));
  for (const f of files) if (!fs.existsSync(f)) throw new Error(`Missing file: ${f}`);
  if (!files.length) throw new Error('No video files found.');
  // LiveBarn names carry the timestamp, so a natural sort puts segments in order.
  files.sort((a, b) => path.basename(a).localeCompare(path.basename(b), undefined, { numeric: true, sensitivity: 'base' }));
  return files;
}

function workDir(files) { return path.dirname(files[0]); }

async function probeFile(f) {
  const j = JSON.parse(await runCapture(FFPROBE, ['-v', 'error', '-print_format', 'json', '-show_streams', '-show_format', f]));
  const v = j.streams.find(s => s.codec_type === 'video');
  const a = j.streams.find(s => s.codec_type === 'audio');
  if (!v) throw new Error(`No video stream in ${f}`);
  const rate = (v.avg_frame_rate && v.avg_frame_rate !== '0/0') ? v.avg_frame_rate : (v.r_frame_rate || '30/1');
  const [n, d] = rate.split('/').map(Number);
  return {
    file: f, name: path.basename(f),
    duration: parseFloat(j.format.duration) || parseFloat(v.duration) || 0,
    width: v.width, height: v.height, fps: n / (d || 1), vcodec: v.codec_name,
    hasAudio: !!a, acodec: a ? a.codec_name : null, channels: a ? (Number(a.channels) || 2) : 0, sizeMB: Math.round((Number(j.format.size) || 0) / 1048576),
  };
}

async function probeAll(files) {
  const info = [];
  let offset = 0;
  for (const f of files) {
    const p = await probeFile(f);
    p.offset = offset; offset += p.duration;
    info.push(p);
  }
  return { info, total: offset, offsets: info.map(i => i.offset) };
}

function printProbe({ info, total }) {
  console.log('#  starts at  duration  res        fps    audio  size    file');
  info.forEach((p, i) => {
    console.log(`${String(i + 1).padEnd(2)} ${fmtTime(p.offset).padEnd(10)} ${fmtTime(p.duration).padEnd(9)} ${`${p.width}x${p.height}`.padEnd(10)} ${p.fps.toFixed(2).padEnd(6)} ${(p.hasAudio ? p.acodec : 'NONE').padEnd(6)} ${(p.sizeMB + 'MB').padEnd(7)} ${p.name}`);
  });
  console.log(`Total stitched length: ${fmtTime(total)}`);
  const res = new Set(info.map(p => `${p.width}x${p.height}`));
  if (res.size > 1) console.log('WARNING: segments have different resolutions; the build will scale them all to the output size.');
}

function writeConcatList(files) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'livebarn-'));
  const p = path.join(dir, 'list.txt');
  const esc = f => path.resolve(f).replace(/\\/g, '/').replace(/'/g, "'\\''");
  fs.writeFileSync(p, files.map(f => `file '${esc(f)}'`).join('\n') + '\n');
  return p;
}

// ------------------------------------------------------------ audio events

// in-place iterative radix-2 FFT
function fft(re, im) {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) { [re[i], re[j]] = [re[j], re[i]]; [im[i], im[j]] = [im[j], im[i]]; }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = -2 * Math.PI / len, wr = Math.cos(ang), wi = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let cr = 1, ci = 0;
      for (let k = 0; k < len / 2; k++) {
        const a = i + k, b = i + k + len / 2;
        const br = re[b] * cr - im[b] * ci, bi = re[b] * ci + im[b] * cr;
        re[b] = re[a] - br; im[b] = im[a] - bi;
        re[a] += br; im[a] += bi;
        const ncr = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = ncr;
      }
    }
  }
}

// spectral flatness (0 = pure tone, 1 = white noise) and dominant frequency over a sample range
function tonalStats(pcm, from, to, sr) {
  const N = 1024, hop = 512;
  const re = new Float64Array(N), im = new Float64Array(N);
  const flat = [], peaks = [];
  for (let s = from; s + N <= to; s += hop) {
    for (let i = 0; i < N; i++) { re[i] = (pcm[s + i] / 32768) * (0.5 - 0.5 * Math.cos(2 * Math.PI * i / (N - 1))); im[i] = 0; }
    fft(re, im);
    let sumLog = 0, sum = 0, maxP = 0, maxK = 0;
    const lo = 3, hi = N / 2;
    for (let k = lo; k < hi; k++) {
      const p = re[k] * re[k] + im[k] * im[k] + 1e-12;
      sumLog += Math.log(p); sum += p;
      if (p > maxP) { maxP = p; maxK = k; }
    }
    const cnt = hi - lo;
    flat.push(Math.exp(sumLog / cnt) / (sum / cnt));
    peaks.push(maxK * sr / N);
  }
  if (!flat.length) return null;
  const medPeak = median(peaks);
  const sd = Math.sqrt(mean(peaks.map(p => (p - medPeak) ** 2)));
  return { flatness: mean(flat), peakHz: medPeak, peakSd: sd };
}

async function decodeAudio(file, sr) {
  const buf = await runCapture(FFMPEG, ['-v', 'error', '-i', file, '-vn', '-ac', '1', '-ar', String(sr), '-f', 's16le', '-'], { binary: true });
  const aligned = Buffer.from(buf); // fresh copy so byteOffset is 0
  return new Int16Array(aligned.buffer, aligned.byteOffset, Math.floor(aligned.length / 2));
}

function detectAudioEvents(pcm, sr) {
  const frame = Math.round(sr * 0.05);
  const n = Math.floor(pcm.length / frame);
  if (n < 20) return { usable: false, reason: 'too short', events: [] };
  const db = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    let acc = 0; const o = i * frame;
    for (let j = 0; j < frame; j++) { const v = pcm[o + j]; acc += v * v; }
    db[i] = 20 * Math.log10(Math.sqrt(acc / frame) / 32768 + 1e-9);
  }
  const sorted = Float32Array.from(db).sort();
  const q = p => sorted[Math.min(n - 1, Math.floor(p * n))];
  const med = q(0.5), p99 = q(0.99), max = sorted[n - 1];
  const stats = { medianDb: med, p99Db: p99, maxDb: max };
  if (max < -40) return { usable: false, reason: `audio is effectively silent (peak ${max.toFixed(0)} dBFS)`, events: [], stats };
  if (max - med < 12) return { usable: false, reason: `audio has no dynamics (flat noise/hum, peak only ${(max - med).toFixed(1)} dB above the floor)`, events: [], stats };

  const thr = Math.max(med + 15, p99 - 6, -38);
  const gapFrames = 6; // merge loud runs separated by <= 0.3 s (pulsed horns)
  const runs = [];
  let start = -1, lastLoud = -1;
  for (let i = 0; i <= n; i++) {
    const loud = i < n && db[i] > thr;
    if (loud) { if (start < 0) start = i; lastLoud = i; }
    else if (start >= 0 && (i - lastLoud > gapFrames || i === n)) { runs.push([start, lastLoud + 1]); start = -1; }
  }
  const events = [];
  for (const [a, b] of runs) {
    const dur = (b - a) * frame / sr;
    if (dur < 0.25 || dur > 12) continue;
    const ts = tonalStats(pcm, a * frame, b * frame, sr);
    if (!ts) continue;
    let level = 0; for (let i = a; i < b; i++) level += db[i]; level /= (b - a);
    let type = 'noise';
    if (ts.flatness < 0.25 && ts.peakHz >= 100 && ts.peakHz <= 1500 && ts.peakSd < 200 && dur >= 0.6) type = 'horn';
    else if (ts.flatness < 0.3 && ts.peakHz > 1500 && ts.peakHz <= 4000 && dur <= 2.5) type = 'whistle';
    events.push({ t: a * frame / sr, end: b * frame / sr, dur, type, db: level, peakHz: ts.peakHz, flatness: ts.flatness });
  }
  return { usable: true, events, stats: { ...stats, thresholdDb: thr } };
}

// ------------------------------------------------------------- video motion

async function motionSeries(listPath, startSec, durSec) {
  const W = 160, H = 90, fl = W * H;
  const buf = await runCapture(FFMPEG, ['-v', 'error', '-ss', String(Math.max(0, startSec)), '-t', String(durSec),
    '-f', 'concat', '-safe', '0', '-i', listPath, '-vf', `fps=1,scale=${W}:${H},format=gray`, '-f', 'rawvideo', '-'], { binary: true });
  const n = Math.floor(buf.length / fl);
  const m = [];
  for (let i = 1; i < n; i++) {
    let acc = 0; const a = (i - 1) * fl, b = i * fl;
    for (let j = 0; j < fl; j++) acc += Math.abs(buf[b + j] - buf[a + j]);
    m.push(acc / fl);
  }
  return m; // m[k] = motion between second k and k+1 after startSec
}

// After the final horn, the handshake line keeps players on the ice; cut when motion collapses.
function findHandshakeEnd(m, minAfter, maxAfter) {
  if (m.length < 60) return null;
  const baseline = mean(m.slice(15, Math.min(90, m.length)));
  if (baseline <= 0) return null;
  const sm = smooth(m, 7);
  for (let t = minAfter; t < m.length; t++) {
    if (sm[t] < 0.35 * baseline) return Math.min(maxAfter, t + 5);
  }
  return null;
}

// After the warm-up horn the ice empties (trough), then play starts (motion returns).
function findPlayStart(m) {
  if (m.length < 120) return null;
  const sm = smooth(m, 5);
  const later = median(sm.slice(-120));
  let trough = 0;
  for (let t = 0; t < Math.min(300, sm.length); t++) if (sm[t] < sm[trough]) trough = t;
  if (later <= 0 || sm[trough] / later > 0.7) return null; // no clear empty-ice trough
  for (let t = trough; t < sm.length - 10; t++) {
    let ok = true;
    for (let k = 0; k < 10; k++) if (sm[t + k] < 0.6 * later) { ok = false; break; }
    if (ok) return Math.max(0, t - 5);
  }
  return null;
}

// -------------------------------------------------------------- commands

async function cmdDoctor() {
  console.log(`skill root : ${ROOT}`);
  console.log(`ffmpeg     : ${FFMPEG || 'MISSING'}`);
  console.log(`ffprobe    : ${FFPROBE || 'MISSING'}`);
  if (FFMPEG) {
    const ver = spawnSync(FFMPEG, ['-version'], { encoding: 'utf8' }).stdout.split('\n')[0];
    console.log(`version    : ${ver}`);
    const enc = spawnSync(FFMPEG, ['-hide_banner', '-encoders'], { encoding: 'utf8' }).stdout;
    console.log(`libx264    : ${/libx264/.test(enc) ? 'yes' : 'NO'}`);
    console.log(`h264_nvenc : ${/h264_nvenc/.test(enc) ? 'listed (GPU availability is checked at encode time)' : 'no'}`);
  }
  console.log(`googleapis : ${fs.existsSync(path.join(ROOT, 'node_modules', 'googleapis')) ? 'installed' : 'NOT installed (npm install in skill root; only needed for upload)'}`);
  console.log(`OAuth      : client_secret.json ${fs.existsSync(path.join(SECRETS, 'client_secret.json')) ? 'present' : 'MISSING (needed for upload)'}, token ${fs.existsSync(path.join(SECRETS, 'token.json')) ? 'present' : 'not yet authorized'}`);
}

async function cmdProbe(pos) {
  needFfmpeg();
  const files = listInputs(pos);
  printProbe(await probeAll(files));
}

async function cmdSheet(pos, opt) {
  needFfmpeg();
  const files = listInputs(pos);
  const every = Number(opt.every || 60);
  const cols = 6;
  const pr = await probeAll(files);
  const font = IS_WIN ? 'C\\:/Windows/Fonts/arial.ttf' : '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf';
  for (let i = 0; i < files.length; i++) {
    const p = pr.info[i];
    const rows = Math.max(1, Math.ceil(p.duration / every / cols));
    const out = path.join(path.dirname(p.file), `${path.parse(p.name).name}_sheet.png`);
    const draw = `drawtext=fontfile='${font}':text='#${i + 1}  %{pts\\:hms}':fontsize=26:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=6:x=10:y=10`;
    const vf = `fps=1/${every},${draw},scale=400:-2,tile=${cols}x${rows}:padding=4:margin=4`;
    try {
      await runCapture(FFMPEG, ['-y', '-v', 'error', '-i', p.file, '-vf', vf, '-frames:v', '1', out]);
    } catch (e) {
      // fall back without timestamps if drawtext/font is unavailable
      await runCapture(FFMPEG, ['-y', '-v', 'error', '-i', p.file, '-vf', `fps=1/${every},scale=400:-2,tile=${cols}x${rows}:padding=4:margin=4`, '-frames:v', '1', out]);
    }
    console.log(`#${i + 1} ${p.name}  (starts at ${fmtTime(p.offset)} in the stitched video)  ->  ${out}`);
  }
  console.log(`\nEach thumbnail is ${every}s apart, ${cols} per row (row r, col c => (r*${cols}+c)*${every}s into that file).`);
  console.log('Give times as N@MM:SS (file number @ time within that file) or as a global H:MM:SS.');
}

async function cmdDetect(pos, opt) {
  needFfmpeg();
  const files = listInputs(pos);
  const pr = await probeAll(files);
  printProbe(pr);
  const sr = 8000;
  const handshakeMin = Number(opt['handshake-min'] || 60);
  const handshakeMax = Number(opt['handshake-max'] || 300);
  const startOffset = Number(opt['start-offset'] || 0);
  const refine = !opt['no-refine'];

  console.log('\nAnalysing audio...');
  const all = [];
  const reasons = [];
  for (const p of pr.info) {
    if (!p.hasAudio) { reasons.push(`${p.name}: no audio track`); continue; }
    const pcm = await decodeAudio(p.file, sr);
    const r = detectAudioEvents(pcm, sr);
    if (!r.usable) { reasons.push(`${p.name}: ${r.reason}`); continue; }
    for (const e of r.events) all.push({ ...e, t: e.t + p.offset, end: e.end + p.offset, file: p.name });
  }
  const horns = all.filter(e => e.type === 'horn');
  const whistles = all.filter(e => e.type === 'whistle');
  const result = { files: pr.info.map(p => ({ name: p.name, offset: p.offset, duration: p.duration })), total: pr.total, audioUsable: horns.length > 0 || whistles.length > 0, events: all, proposal: null, notes: [] };

  if (reasons.length) { console.log('Audio problems:'); for (const r of reasons) console.log('  - ' + r); }
  if (!all.length) {
    console.log('\nNO USABLE AUDIO EVENTS. Ask for the start and end manually.');
    console.log(`Run:  node "${SCRIPT_PATH}" sheet "${pos.join('" "')}"   to make thumbnail sheets, then build with --start/--end.`);
    result.notes.push('no usable audio');
  } else {
    console.log(`\nDetected ${horns.length} horn(s), ${whistles.length} whistle(s):`);
    for (const e of all.filter(e => e.type !== 'noise')) {
      console.log(`  ${fmtTime(e.t).padEnd(9)} ${e.type.padEnd(8)} ${e.dur.toFixed(1)}s  ${e.db.toFixed(0)} dB  ${e.peakHz.toFixed(0)} Hz  flat=${e.flatness.toFixed(2)}  (${e.file})`);
    }
    if (!horns.length) {
      console.log('\nNo horns found (only whistles). Cannot propose a cut; ask for start/end manually.');
    } else {
      const first = horns[0], last = horns[horns.length - 1];
      let start = first.end + startOffset;
      let end = last.end + 180;
      const notes = [];
      if (horns.length > 8) notes.push(`Many horns (${horns.length}) - some may be goal horns or the next game's warm-up; check the list.`);
      if (last.t - first.t < 20 * 60) notes.push(`First and last horn are only ${fmtTime(last.t - first.t)} apart - unusual for a full game.`);
      if (first.t < 60) notes.push('First horn is within the first minute; the recording may have started after warm-up.');
      if (refine) {
        const list = writeConcatList(files);
        try {
          console.log('\nRefining start from video motion (warm-up horn -> faceoff)...');
          const m = await motionSeries(list, first.end, 480);
          const ps = findPlayStart(m);
          if (ps !== null) { start = first.end + ps + startOffset; notes.push(`Start refined to first sustained play ${fmtTime(ps)} after the warm-up horn.`); }
          else notes.push('Could not see an empty-ice gap after the warm-up horn; start = warm-up horn.');
          console.log('Refining end from video motion (final horn -> handshake line -> empty ice)...');
          const m2 = await motionSeries(list, last.end, handshakeMax + 5);
          const he = findHandshakeEnd(m2, handshakeMin, handshakeMax);
          if (he !== null) { end = last.end + he; notes.push(`End set ${fmtTime(he)} after the final horn (ice emptied).`); }
          else { end = last.end + Math.min(180, handshakeMax); notes.push('Could not see the ice empty; end = final horn + 3:00.'); }
        } catch (e) {
          notes.push('Motion refinement failed: ' + e.message.split('\n')[0]);
        }
      }
      end = Math.min(end, pr.total);
      result.proposal = { start, end, startHMS: fmtTime(start), endHMS: fmtTime(end), warmupHorn: first.t, finalHorn: last.t };
      result.notes.push(...notes);
      console.log('\nPROPOSED CUT');
      console.log(`  start : ${fmtTime(start)}   (warm-up horn at ${fmtTime(first.t)})`);
      console.log(`  end   : ${fmtTime(end)}   (final horn at ${fmtTime(last.t)}, keeps the handshake line)`);
      console.log(`  length: ${fmtTime(end - start)}`);
      for (const n of notes) console.log('  note  : ' + n);
      console.log(`\nConfirm or adjust, then build:\n  node "${SCRIPT_PATH}" build "${pos.join('" "')}" --start ${fmtTime(start)} --end ${fmtTime(end)}`);
    }
  }
  const outJson = path.join(workDir(files), 'livebarn-detect.json');
  fs.writeFileSync(outJson, JSON.stringify(result, null, 2));
  console.log(`\nWrote ${outJson}`);
}

function encoderArgs(kind, fps, boost, preset, crf) {
  // CRF 20 at 1440p / 18 at 1080p lands ~12-18 Mbps: visually identical after YouTube's transcode, half the upload of CRF 17.
  crf = String(crf || (boost ? 20 : 18));
  const g = String(Math.max(1, Math.round(fps / 2))); // YouTube: closed GOP of half the frame rate
  const common = ['-pix_fmt', 'yuv420p', '-g', g, '-keyint_min', g, '-bf', '2', '-profile:v', 'high'];
  if (kind === 'nvenc') {
    return ['-c:v', 'h264_nvenc', '-preset', preset || 'slow', '-rc', 'vbr', '-cq', crf, '-b:v', boost ? '28M' : '18M',
      '-maxrate', boost ? '40M' : '26M', '-bufsize', boost ? '60M' : '40M', '-spatial_aq', '1', '-aq-strength', '8', ...common];
  }
  return ['-c:v', 'libx264', '-preset', preset || 'medium', '-crf', crf, '-maxrate', boost ? '40M' : '24M', '-bufsize', boost ? '60M' : '40M',
    '-sc_threshold', '0', '-flags', '+cgop', '-x264-params', 'open-gop=0', ...common];
}

async function cmdBuild(pos, opt) {
  needFfmpeg();
  const files = listInputs(pos);
  const pr = await probeAll(files);
  const start = opt.start !== undefined ? parseTime(opt.start, pr.offsets) : 0;
  const end = opt.end !== undefined ? parseTime(opt.end, pr.offsets) : pr.total;
  if (end <= start) throw new Error(`end (${fmtTime(end)}) must be after start (${fmtTime(start)})`);
  if (end > pr.total + 1) throw new Error(`end (${fmtTime(end)}) is past the total length (${fmtTime(pr.total)})`);

  const dir = workDir(files);
  const out = opt.out ? path.resolve(opt.out) : path.join(dir, `${path.basename(dir)}_youtube.mp4`);
  const boost = !!opt.boost;
  const first = pr.info[0];
  const fps = first.fps || 30;
  const allAudio = pr.info.every(p => p.hasAudio), anyAudio = pr.info.some(p => p.hasAudio);
  const list = writeConcatList(files);

  const vf = [];
  if (boost) vf.push('scale=2560:1440:flags=lanczos', 'unsharp=5:5:0.5:5:5:0.0');
  else if (first.height < 1080 || first.width < 1920) vf.push('scale=1920:1080:flags=lanczos', 'unsharp=5:5:0.5:5:5:0.0');
  else if (pr.info.some(p => p.width !== first.width || p.height !== first.height)) vf.push(`scale=${first.width}:${first.height}:flags=lanczos`);
  vf.push('format=yuv420p');

  const abr = pr.info.every(p => p.channels >= 2) ? '384k' : '192k'; // YouTube: 384k stereo, mono needs far less
  const audioArgs = allAudio ? ['-map', '0:a:0', '-c:a', 'aac', '-b:a', abr, '-ar', '48000'] : ['-an'];
  if (!allAudio && anyAudio) console.log('WARNING: some segments lack audio; the output will have NO audio track so the concat stays in sync.');

  let kind = opt.encoder || 'x264';
  const build = k => ['-y', '-hide_banner', '-loglevel', 'warning', '-stats',
    '-ss', start.toFixed(3), '-t', (end - start).toFixed(3), '-f', 'concat', '-safe', '0', '-i', list,
    '-map', '0:v:0', ...audioArgs, '-vf', vf.join(','), '-fps_mode', 'cfr',
    ...encoderArgs(k, fps, boost, opt.preset, opt.crf), '-movflags', '+faststart', out];

  console.log(`Input  : ${files.length} segment(s), ${fmtTime(pr.total)} total, ${first.width}x${first.height} @ ${fps.toFixed(2)} fps`);
  console.log(`Cut    : ${fmtTime(start)} -> ${fmtTime(end)}  (${fmtTime(end - start)})`);
  console.log(`Output : ${out}  [${boost ? '2560x1440 (YouTube VP9 tier)' : (vf[0].startsWith('scale=1920') ? '1920x1080 upscaled' : 'native')}, ${kind}, ${allAudio ? 'AAC ' + abr : 'no audio'}]`);
  if (opt['dry-run']) { console.log('\n' + [FFMPEG, ...build(kind)].map(a => /\s/.test(a) ? `"${a}"` : a).join(' ')); return; }

  const t0 = Date.now();
  try {
    await runLive(FFMPEG, build(kind));
  } catch (e) {
    if (kind === 'nvenc') {
      console.log('\nNVENC encode failed (' + e.message.split('\n')[0] + '); retrying with libx264...');
      kind = 'x264';
      await runLive(FFMPEG, build(kind));
    } else throw e;
  }
  const mins = ((Date.now() - t0) / 60000).toFixed(1);
  const o = await probeFile(out);
  console.log(`\nDone in ${mins} min: ${out}`);
  console.log(`  ${o.width}x${o.height} @ ${o.fps.toFixed(2)} fps, ${fmtTime(o.duration)}, ${o.vcodec}/${o.acodec || 'no audio'}, ${o.sizeMB} MB (~${(o.sizeMB * 8 / o.duration).toFixed(1)} Mbps)`);
}

function openBrowser(url) {
  // rundll32 passes the URL verbatim; `cmd /c start` would split it at every '&'.
  if (IS_WIN) spawn('rundll32', ['url.dll,FileProtocolHandler', url], { stdio: 'ignore', detached: true }).unref();
  else spawn(process.platform === 'darwin' ? 'open' : 'xdg-open', [url], { stdio: 'ignore', detached: true }).unref();
}

async function getAuth() {
  let google;
  try { ({ google } = await import('googleapis')); }
  catch { throw new Error(`googleapis is not installed. Run:  npm install   in ${ROOT}`); }
  const secretPath = path.join(SECRETS, 'client_secret.json');
  const tokenPath = path.join(SECRETS, 'token.json');
  if (!fs.existsSync(secretPath)) {
    throw new Error(`Missing ${secretPath}\n` +
      'Create an OAuth "Desktop app" client in Google Cloud Console (YouTube Data API v3 enabled), download the JSON, and save it there.');
  }
  fs.mkdirSync(SECRETS, { recursive: true });
  const cs = JSON.parse(fs.readFileSync(secretPath, 'utf8'));
  const c = cs.installed || cs.web;
  const port = 8089, redirect = `http://127.0.0.1:${port}/`;
  const oauth = new google.auth.OAuth2(c.client_id, c.client_secret, redirect);
  const save = t => fs.writeFileSync(tokenPath, JSON.stringify({ ...(fs.existsSync(tokenPath) ? JSON.parse(fs.readFileSync(tokenPath, 'utf8')) : {}), ...t }, null, 2));
  oauth.on('tokens', save);
  if (fs.existsSync(tokenPath)) { oauth.setCredentials(JSON.parse(fs.readFileSync(tokenPath, 'utf8'))); return { google, oauth }; }

  const url = oauth.generateAuthUrl({ access_type: 'offline', prompt: 'consent', scope: ['https://www.googleapis.com/auth/youtube.upload', 'https://www.googleapis.com/auth/youtube'] });
  console.log('Authorize this app in the browser (opening it now):\n' + url + '\n');
  openBrowser(url);
  const code = await new Promise((resolve, reject) => {
    const srv = http.createServer((req, res) => {
      const u = new URL(req.url, redirect);
      const code = u.searchParams.get('code');
      res.setHeader('Content-Type', 'text/html');
      res.end(code ? '<h2>Authorized. You can close this tab.</h2>' : '<h2>No code received.</h2>');
      if (code) { srv.close(); resolve(code); }
    });
    srv.on('error', reject);
    srv.listen(port, '127.0.0.1');
  });
  const { tokens } = await oauth.getToken(code);
  oauth.setCredentials(tokens); save(tokens);
  console.log('Authorization saved to ' + tokenPath);
  return { google, oauth };
}

async function cmdUpload(pos, opt) {
  const file = pos[0];
  if (!file || !fs.existsSync(file)) throw new Error('Give the video file to upload.');
  if (!opt.title) throw new Error('--title is required.');
  const desc = opt['desc-file'] ? fs.readFileSync(String(opt['desc-file']), 'utf8') : String(opt.desc || '');
  const { google, oauth } = await getAuth();
  const yt = google.youtube({ version: 'v3', auth: oauth });
  const size = fs.statSync(file).size;
  console.log(`Uploading ${path.basename(file)} (${(size / 1048576).toFixed(0)} MB) as "${opt.title}" [${opt.privacy || 'unlisted'}]...`);
  let lastPct = -1;
  const res = await yt.videos.insert({
    part: 'snippet,status',
    notifySubscribers: !!opt.notify,
    requestBody: {
      snippet: { title: String(opt.title), description: desc, tags: opt.tags ? String(opt.tags).split(',').map(s => s.trim()).filter(Boolean) : undefined, categoryId: '17' },
      status: { privacyStatus: opt.privacy || 'unlisted', selfDeclaredMadeForKids: false },
    },
    media: { body: fs.createReadStream(file) },
  }, {
    onUploadProgress: ev => { const pct = Math.floor(ev.bytesRead / size * 100); if (pct !== lastPct && pct % 5 === 0) { lastPct = pct; process.stdout.write(`\r  ${pct}%`); } },
  });
  const id = res.data.id;
  console.log(`\nUploaded: https://youtu.be/${id}`);
  // The stats repo only sees videos that are in the game-film playlist (scripts/scrape.py reads
  // franchises.json's youtube_playlist_id), so default to it; --playlist none skips.
  const playlist = opt.playlist === undefined ? defaultPlaylistId() : opt.playlist;
  if (playlist && playlist !== 'none') {
    await yt.playlistItems.insert({ part: 'snippet', requestBody: { snippet: { playlistId: String(playlist), resourceId: { kind: 'youtube#video', videoId: id } } } });
    console.log(`Added to playlist ${playlist}`);
  }
  console.log(`Video ID: ${id}`);
  if (opt.refresh) await cmdRefresh([], opt);
}

function defaultPlaylistId() {
  try {
    const fr = JSON.parse(fs.readFileSync(path.join(DEFAULT_REPO, 'data', 'franchises.json'), 'utf8'));
    return Object.values(fr).find(f => f && f.youtube_playlist_id)?.youtube_playlist_id || null;
  } catch { return null; }
}

// Kick the stats repo's "Refresh stats data" GitHub workflow so a freshly uploaded / re-described
// video is linked to its game (and its goals film-synced) now instead of at the 12:30 AM run.
// The scrape reads the playlist page + each video's description, so the video must be in the
// playlist and its description must carry "Game #<id>" (describe writes it) before this is useful.
async function cmdRefresh(pos, opt) {
  const repo = opt.repo || DEFAULT_REPO;
  const gh = args => spawnSync('gh', args, { cwd: repo, encoding: 'utf8', shell: IS_WIN });
  const run = gh(['workflow', 'run', 'refresh-data.yml']);
  if (run.status !== 0) throw new Error('gh workflow run failed (is GitHub CLI installed and logged in? `gh auth login`): ' + (run.stderr || run.stdout || '').trim());
  console.log('Triggered the stats refresh workflow (Refresh stats data): scrape -> link video to game -> film-sync goals (~10 min per new video) -> commit.');
  if (!opt.wait) { console.log('Follow it with: node livebarn.mjs refresh --wait   (or: gh run list --workflow refresh-data.yml)'); return; }
  // `workflow run` doesn't return the run id; give GitHub a moment to register it, then take the newest
  await new Promise(r => setTimeout(r, 8000));
  const list = gh(['run', 'list', '--workflow', 'refresh-data.yml', '--limit', '1', '--json', 'databaseId,status,url']);
  const latest = list.status === 0 ? JSON.parse(list.stdout)[0] : null;
  if (!latest) { console.log('Could not find the run to watch; check: gh run list --workflow refresh-data.yml'); return; }
  console.log(`Watching ${latest.url} ...`);
  const w = spawnSync('gh', ['run', 'watch', String(latest.databaseId), '--exit-status'], { cwd: repo, stdio: 'inherit', shell: IS_WIN });
  console.log(w.status === 0 ? 'Refresh finished: the dashboard now links this video (GitHub Pages redeploys within a minute or two).' : 'Refresh run did not succeed; see the URL above.');
}

// Regenerate title + description from the stats repo (full rewrite every time; notes.txt is merged in).
async function cmdDescribe(pos, opt) {
  const outDir = path.resolve(opt.out || pos[0] || '.');
  const notesPath = opt.notes ? path.resolve(opt.notes) : path.join(outDir, 'notes.txt');
  const r = describeGame({ repo: opt.repo || DEFAULT_REPO, game: opt.game, date: opt.date, notesPath, pull: !opt['no-pull'] });
  fs.mkdirSync(outDir, { recursive: true });
  const descPath = path.join(outDir, 'youtube-description.txt');
  const titlePath = path.join(outDir, 'youtube-title.txt');
  fs.writeFileSync(descPath, r.description + '\n');
  if (!fs.existsSync(titlePath) || opt['force-title']) fs.writeFileSync(titlePath, r.title + '\n');
  else console.log('(kept existing youtube-title.txt; pass --force-title to regenerate it)');
  console.log(`Game ${r.meta.game_id}: ${r.meta.date} ${r.meta.time} vs ${r.meta.opponent} (${r.meta.game_type}) -- repo ${r.pulled}`);
  console.log(`Notes: ${r.notesUsed ? notesPath : 'none (create ' + notesPath + ' for THE STORY section)'}`);
  console.log(`+/-  : ${r.pmGame ? `this game (${r.pmGame.tagged}/${r.pmGame.total} goals tagged)` : 'no on-ice tags for this game'}${r.pmSeason.length ? ', season totals included' : ''}`);
  if (r.meta.video) console.log(`Linked video in repo: ${r.meta.video.url}`);
  console.log(`\nTitle: ${fs.readFileSync(titlePath, 'utf8').trim()}`);
  console.log(`Wrote ${descPath}`);
  console.log('\n' + r.description);
}

// Replace the title/description on an existing video (no re-upload). Full overwrite.
async function cmdUpdate(pos, opt) {
  const id = opt.video || pos[0];
  if (!id) throw new Error('Give the video id: update <videoId|url> [--dir folder] [--title-file f | --title t] [--desc-file f] [--privacy p]');
  const videoId = String(id).replace(/^.*(?:v=|youtu\.be\/)([\w-]{11}).*$/, '$1');
  const dir = path.resolve(opt.dir || '.');
  const titleFile = opt['title-file'] || (fs.existsSync(path.join(dir, 'youtube-title.txt')) ? path.join(dir, 'youtube-title.txt') : null);
  const descFile = opt['desc-file'] || (fs.existsSync(path.join(dir, 'youtube-description.txt')) ? path.join(dir, 'youtube-description.txt') : null);
  const title = opt.title ? String(opt.title) : titleFile ? fs.readFileSync(titleFile, 'utf8').trim() : null;
  const description = descFile ? fs.readFileSync(descFile, 'utf8').replace(/\s+$/, '') : null;
  if (!title && !description && !opt.privacy) throw new Error('Nothing to update: no youtube-title.txt / youtube-description.txt found and no --title/--desc-file/--privacy given.');
  const { google, oauth } = await getAuth();
  const yt = google.youtube({ version: 'v3', auth: oauth });
  const cur = await yt.videos.list({ part: 'snippet,status', id: videoId });
  const v = cur.data.items && cur.data.items[0];
  if (!v) throw new Error(`Video ${videoId} not found on this channel.`);
  const snippet = { ...v.snippet };
  if (title) snippet.title = title;
  if (description !== null) snippet.description = description;
  const body = { id: videoId, snippet: { title: snippet.title, description: snippet.description, categoryId: snippet.categoryId, tags: snippet.tags, defaultLanguage: snippet.defaultLanguage } };
  let part = 'snippet';
  if (opt.privacy) { body.status = { ...v.status, privacyStatus: String(opt.privacy) }; part = 'snippet,status'; }
  if (opt['dry-run']) { console.log(`Would update https://youtu.be/${videoId}\nTitle: ${body.snippet.title}\n\n${body.snippet.description}`); return; }
  await yt.videos.update({ part, requestBody: body });
  console.log(`Updated https://youtu.be/${videoId}`);
  console.log(`  title      : ${body.snippet.title}`);
  console.log(`  description: ${description !== null ? description.split('\n').length + ' lines, rewritten' : 'unchanged'}`);
  if (opt.privacy) console.log(`  privacy    : ${opt.privacy}`);
  if (opt.refresh) await cmdRefresh([], opt);
}

function help() {
  console.log(`LiveBarn -> YouTube pipeline

  node livebarn.mjs doctor
  node livebarn.mjs probe  <folder|files...>
  node livebarn.mjs sheet  <folder|files...> [--every 60]
  node livebarn.mjs detect <folder|files...> [--handshake-min 60] [--handshake-max 300] [--start-offset 0] [--no-refine]
  node livebarn.mjs build  <folder|files...> [--start T] [--end T] [--out file.mp4] [--encoder x264|nvenc] [--preset medium|slow] [--crf N] [--boost] [--dry-run]
  node livebarn.mjs describe [folder] --game ID | --date YYYY-MM-DD [--repo path] [--notes notes.txt] [--force-title] [--no-pull]
  node livebarn.mjs update <videoId|url> [--dir folder] [--title "..."] [--title-file f] [--desc-file f] [--privacy p] [--dry-run] [--refresh]
  node livebarn.mjs upload <file.mp4> --title "..." [--desc "..." | --desc-file file.txt] [--tags a,b] [--privacy unlisted|private|public] [--playlist ID|none] [--notify] [--refresh]
  node livebarn.mjs refresh [--wait] [--repo path]     trigger the stats repo's refresh workflow (links new videos to games)

Times: H:MM:SS, MM:SS, seconds, or N@MM:SS (file number @ time within that file).`);
}

const { pos, opt } = parseArgs(process.argv.slice(2));
const cmd = pos.shift();
const commands = { doctor: cmdDoctor, probe: cmdProbe, sheet: cmdSheet, detect: cmdDetect, build: cmdBuild, upload: cmdUpload, describe: cmdDescribe, update: cmdUpdate, refresh: cmdRefresh };
if (!cmd || cmd === 'help' || !commands[cmd]) { help(); process.exit(cmd && cmd !== 'help' ? 1 : 0); }
commands[cmd](pos, opt).catch(e => { console.error('\nERROR: ' + e.message); process.exit(1); });
