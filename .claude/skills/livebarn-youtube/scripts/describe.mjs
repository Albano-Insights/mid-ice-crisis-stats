// Builds a YouTube title + description for one game from the mid-ice-crisis-stats repo's derived
// data, so a stat correction or a new on-ice tag can be pushed to the video by re-running it.
// Everything numeric is regenerated from data; the hand-written narrative lives in notes.txt
// next to the game files and is merged in verbatim under THE STORY.

import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

import { fileURLToPath } from 'node:url';

// When the skill lives inside the stats repo (.claude/skills/livebarn-youtube/scripts), the repo is
// four levels up; otherwise fall back to the usual checkout location.
const HERE = path.dirname(fileURLToPath(import.meta.url));
const IN_REPO = path.resolve(HERE, '..', '..', '..', '..');
export const DEFAULT_REPO = fs.existsSync(path.join(IN_REPO, 'data', 'derived', 'games_index.json'))
  ? IN_REPO
  : 'C:\\Users\\alban\\code\\mid-ice-crisis-stats';
const SITE = 'https://albano-insights.github.io/mid-ice-crisis-stats/';

const readJson = p => JSON.parse(fs.readFileSync(p, 'utf8'));
const clockSec = t => { const s = String(t); return s.includes(':') ? s.split(':').reduce((a, b) => a * 60 + Number(b), 0) : Number(s); };
const periodRank = p => ({ '1': 1, '2': 2, '3': 3 })[p] ?? 4; // OT/SO after regulation
const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
const fmtPM = n => (n > 0 ? '+' : '') + n;

export function pullRepo(repo) {
  const r = spawnSync('git', ['-C', repo, 'pull', '--ff-only', '--quiet'], { encoding: 'utf8' });
  return r.status === 0 ? 'pulled latest' : 'git pull failed: ' + (r.stderr || '').trim().split('\n').pop();
}

export function findGame(repo, { game, date }) {
  const index = readJson(path.join(repo, 'data', 'derived', 'games_index.json'));
  let hits = [];
  if (game) hits = index.filter(g => String(g.game_id) === String(game));
  else if (date) hits = index.filter(g => g.iso_date === date);
  if (!hits.length) throw new Error(`No game found for ${game ? 'id ' + game : 'date ' + date} in ${repo}`);
  if (hits.length > 1) throw new Error(`${hits.length} games on ${date}: ${hits.map(g => `${g.game_id} (${g.time} vs ${g.opponent})`).join(', ')} -- use --game`);
  return hits[0];
}

function loadContext(repo, meta) {
  const d = path.join(repo, 'data', 'derived');
  const game = readJson(path.join(d, 'games', `${meta.game_id}.json`));
  const season = String(game.season_id);
  const lb = readJson(path.join(d, 'player_leaderboards.json')).by_season[season] || [];
  const teamSeason = (readJson(path.join(d, 'team_summary.json')).by_season || {})[season] || null;
  const h2h = (readJson(path.join(d, 'head_to_head.json')) || {})[game.opponent] || null;
  const franchises = readJson(path.join(repo, 'data', 'franchises.json'));
  const current = Object.values(franchises).find(f => f && f.team_ids)?.name || null;
  let standings = [];
  const sp = path.join(repo, 'data', 'raw', 'seasons', season, 'standings.json');
  if (fs.existsSync(sp) && teamSeason) standings = readJson(sp).filter(t => t.level_label === teamSeason.level_label);
  const index = readJson(path.join(d, 'games_index.json'));
  const seasonOver = !index.some(g => g.season_id === game.season_id && !g.is_final);
  return { game, lb, teamSeason, h2h, standings, currentName: current, seasonOver };
}

// Per-game +/- from on-ice tags, same rules as build_site_data.py: PP goals count for nobody.
function gamePlusMinus(game, usSide) {
  const tags = game.on_ice_tags || [];
  if (!tags.length) return null;
  const byKey = new Map(tags.map(t => [`${t.team}|${t.period}|${t.time}`, t]));
  const sideName = { home: game.home_name, away: game.away_name };
  const roster = side => new Map((game.rosters[sideName[side]] || []).map(p => [p.number, p.name]));
  const rosters = { home: roster('home'), away: roster('away') };
  const acc = { home: new Map(), away: new Map() };
  let tagged = 0;
  for (const goal of game.goals) {
    const tag = byKey.get(`${goal.team}|${goal.period}|${goal.time}`);
    if (!tag) continue;
    tagged++;
    if (/PP/i.test(goal.situation || '')) continue;
    for (const [side, numbers] of Object.entries(tag.on_ice || {})) {
      const sign = side === goal.team ? 1 : -1;
      for (const num of numbers) {
        const name = rosters[side].get(num) || `#${num}`;
        const r = acc[side].get(name) || { plus: 0, minus: 0, pm: 0, n: 0 };
        if (sign > 0) r.plus++; else r.minus++;
        r.pm += sign; r.n++;
        acc[side].set(name, r);
      }
    }
  }
  const rows = [...acc[usSide].entries()].map(([name, r]) => ({ name, ...r })).sort((a, b) => b.pm - a.pm || b.plus - a.plus || a.name.localeCompare(b.name));
  return { rows, tagged, total: game.goals.length };
}

export function buildDescription(ctx, notesText) {
  const { game, lb, teamSeason, h2h, standings, currentName } = ctx;
  const usSide = game.is_home ? 'home' : 'away';
  const themSide = game.is_home ? 'away' : 'home';
  const usName = game.is_home ? game.home_name : game.away_name;
  const themName = game.opponent;
  const usShort = usName.replace(/^Globo Gym /, '').replace(/ D$/, '');
  const themShort = themName;
  const usFinal = game.is_home ? game.home_final : game.away_final;
  const themFinal = game.is_home ? game.away_final : game.home_final;
  const won = usFinal > themFinal, tie = usFinal === themFinal;
  const nameOf = (side, num) => (game.rosters[side === 'home' ? game.home_name : game.away_name] || []).find(p => p.number === num)?.name || (num == null ? null : `#${num}`);
  const label = (side, num) => { const n = nameOf(side, num); return n ? `${n}${num != null ? ` (#${num})` : ''}` : null; };

  // scoring summary in game order (clock counts down within a period)
  const goals = [...game.goals].sort((a, b) => periodRank(a.period) - periodRank(b.period) || clockSec(b.time) - clockSec(a.time));
  let us = 0, them = 0;
  const lines = [];
  const scorerCount = new Map(), pointCount = new Map();
  for (const g of goals) {
    if (g.team === usSide) us++; else them++;
    const who = label(g.team, g.scorer_number);
    // #0 is the scoresheet's placeholder for "no assist"
    const assists = [g.assist1_number, g.assist2_number].filter(n => n != null && n !== 0).map(n => label(g.team, n)).filter(Boolean);
    const fixed = g._corrections ? ' *' : '';
    const teamTag = (g.team === usSide ? usShort : themShort).toUpperCase();
    const sit = g.situation ? ` ${g.situation}` : '';
    lines.push(`${periodLabel(g.period)} ${String(g.time).padStart(5)}  ${teamTag}${sit} - ${who}${assists.length ? ', assist' + (assists.length > 1 ? 's' : '') + ' ' + assists.join(', ') : ', unassisted'}${fixed}  [${us}-${them}]`);
    const key = `${g.team}|${g.scorer_number}`;
    scorerCount.set(key, (scorerCount.get(key) || 0) + 1);
    for (const n of [g.scorer_number, g.assist1_number, g.assist2_number]) if (n != null && n !== 0) { const k = `${g.team}|${n}`; pointCount.set(k, (pointCount.get(k) || 0) + 1); }
  }
  const corrected = goals.some(g => g._corrections);

  // penalties
  const pens = [];
  const penList = ['home', 'away'].flatMap(side => (game.penalties?.[side] || []).map(p => ({ ...p, side })))
    .sort((a, b) => periodRank(a.period) - periodRank(b.period) || clockSec(b.off_ice || b.start || '0') - clockSec(a.off_ice || a.start || '0'));
  for (const p of penList) {
    const side = p.side;
    pens.push(`${side === usSide ? usShort : themShort}: ${nameOf(side, p.number) || '#' + p.number}, ${p.infraction || 'minor'}, ${periodLabel(p.period)} ${p.off_ice || ''} (${p.minutes} min)`);
  }

  // ---- insights (only the ones that are true for this game)
  const insights = [];
  const usGoals = goals.filter(g => g.team === usSide), themGoals = goals.filter(g => g.team === themSide);
  for (const [key, n] of scorerCount) if (n >= 2) {
    const [side, num] = key.split('|'); const nm = nameOf(side, Number(num));
    const team = side === usSide ? usShort : themShort;
    insights.push(n >= 4 ? `${n}-GOAL GAME: ${nm} (${team}).` : n === 3 ? `HAT TRICK: ${nm} (${team}).` : `${nm} (${team}) scored twice.`);
  }
  for (const [key, n] of pointCount) if (n >= 3 && (scorerCount.get(key) || 0) < 2) {
    const [side, num] = key.split('|'); insights.push(`${nameOf(side, Number(num))} (${side === usSide ? usShort : themShort}) had a ${n}-point night.`);
  }
  const ppGoals = goals.filter(g => /PP/i.test(g.situation || ''));
  for (const g of ppGoals) {
    // the penalty that created this power play: same period, still running at the goal, nearest first
    const pen = (game.penalties?.[g.team === 'home' ? 'away' : 'home'] || [])
      .map(p => ({ p, gap: clockSec(p.off_ice || p.start || '0') - clockSec(g.time) }))
      .filter(x => x.p.period === g.period && x.gap >= 0 && x.gap <= (x.p.minutes || 2) * 60)
      .sort((x, y) => x.gap - y.gap)[0];
    if (pen) {
      const gap = pen.gap;
      const when = gap < 60 ? `${gap} second${gap === 1 ? '' : 's'}` : `${Math.floor(gap / 60)}:${String(gap % 60).padStart(2, '0')}`;
      insights.push(`${nameOf(g.team, g.scorer_number)} scored ${when} into the power play after ${nameOf(g.team === 'home' ? 'away' : 'home', pen.p.number)}'s ${(pen.p.infraction || 'minor').toLowerCase()}.`);
    }
  }
  if (!tie) {
    const winnerSide = won ? usSide : themSide, loserTotal = won ? themFinal : usFinal;
    const wg = goals.filter(g => g.team === winnerSide)[loserTotal];
    if (wg) insights.push(`Game-winner: ${nameOf(winnerSide, wg.scorer_number)}, ${periodLabel(wg.period)} ${wg.time}.`);
  }
  if (usFinal === 0 || themFinal === 0) {
    const side = usFinal === 0 ? themSide : usSide;
    const goalie = (game.rosters[side === 'home' ? game.home_name : game.away_name] || []).find(p => p.position === 'G' && !/^ALT\b/i.test(p.name));
    insights.push(goalie ? `SHUTOUT: ${goalie.name} (${side === usSide ? usShort : themShort}).` : `SHUTOUT for ${side === usSide ? usShort : themShort}.`);
  }
  const ties = []; let a = 0, b = 0;
  for (const g of goals) { if (g.team === usSide) a++; else b++; if (a === b && a > 0) ties.push(`${a}-${b}`); }
  if (ties.length) insights.push(`Tied ${ties.length} time${ties.length === 1 ? '' : 's'} (${ties.join(', ')}).`);
  const usPims = (game.penalties?.[usSide] || []).reduce((s, p) => s + (p.minutes || 0), 0);
  if (teamSeason && teamSeason.gp) {
    const avg = teamSeason.pims / teamSeason.gp;
    if (usPims === 0) insights.push(`Zero penalties for ${usShort} (season average ${avg.toFixed(1)} PIM/game).`);
    else if (usPims <= avg / 2) insights.push(`Disciplined night: ${usPims} PIM vs a ${avg.toFixed(1)} PIM/game season average.`);
    else if (usPims >= avg * 2) insights.push(`${usPims} PIM -- double the ${avg.toFixed(1)} PIM/game season average.`);
  }
  if (h2h) {
    const sm = h2h.meetings.filter(m => m.season_id === game.season_id);
    if (sm.length > 1) {
      const w = sm.filter(m => m.us > m.them).length, l = sm.filter(m => m.us < m.them).length;
      const gf = sm.reduce((s, m) => s + m.us, 0), ga = sm.reduce((s, m) => s + m.them, 0);
      insights.push(`Season series vs ${themShort}: ${w}-${l}${sm.length - w - l ? '-' + (sm.length - w - l) : ''} (goals ${gf}-${ga}).${w === 0 && l === sm.length ? ' A sweep.' : l === 0 && w === sm.length ? ' Swept them.' : ''}`);
    }
    insights.push(`All-time vs ${themShort}: ${h2h.w}-${h2h.l}${h2h.t ? '-' + h2h.t : ''} (goals ${h2h.gf}-${h2h.ga}).`);
  }

  // ---- standings context
  let standingsLine = null;
  // the league site posts null records until a few games are in; say nothing rather than "null-null"
  if (standings.length && standings.every(t => t.gp != null && t.pts != null && t.gp > 0)) {
    const sorted = [...standings].sort((x, y) => y.pts - x.pts || (y.gf - y.ga) - (x.gf - x.ga));
    const place = n => { const i = sorted.findIndex(t => t.name === n); return i < 0 ? null : i + 1; };
    const gfRank = n => [...standings].sort((x, y) => y.gf - x.gf).findIndex(t => t.name === n) + 1;
    const gaRank = n => [...standings].sort((x, y) => x.ga - y.ga).findIndex(t => t.name === n) + 1;
    const rec = t => `${t.w}-${t.l}${t.otl ? '-' + t.otl : ''}, ${t.pts} pts`;
    const usT = standings.find(t => t.name === usName), thT = standings.find(t => t.name === themName);
    const parts = [];
    const verb = ctx.seasonOver ? 'finished' : 'sits';
    if (usT) parts.push(`${usShort} ${verb} ${ordinal(place(usName))} of ${standings.length} (${rec(usT)}; GF ${usT.gf} #${gfRank(usName)} in the division, GA ${usT.ga} #${gaRank(usName)})`);
    if (thT) parts.push(`${themShort} ${verb} ${ordinal(place(themName))} (${rec(thT)}; GF ${thT.gf} #${gfRank(themName)}, GA ${thT.ga} #${gaRank(themName)})`);
    if (parts.length) standingsLine = parts.join('. ') + '.';
  }

  // ---- plus/minus
  const pmGame = gamePlusMinus(game, usSide);
  const pmSeason = lb.filter(p => p.plus_minus_tagged).map(p => ({ name: p.name, ...p.plus_minus_tagged })).sort((x, y) => y.plus_minus - x.plus_minus || x.name.localeCompare(y.name));

  // ---- season leaders (our roster this season)
  const leaders = [...lb].sort((x, y) => y.points - x.points || y.goals - x.goals).slice(0, 6);

  // ---- assemble
  const out = [];
  const typeLabel = /playoff/i.test(game.game_type) ? 'PLAYOFFS' : /final/i.test(game.game_type) ? 'FINAL' : game.game_type.toUpperCase();
  const nowNote = currentName && currentName !== usName ? ` (now ${currentName})` : '';
  out.push(`${typeLabel} | ${usName}${nowNote} vs ${themName}`);
  out.push(`${longDate(game.iso_date)} - ${game.time} - ${game.rink} - ${teamSeason ? teamSeason.season_label.replace(/^W/, '') + ', ' + teamSeason.level_label : game.season_label}`);
  out.push('');
  out.push(`FINAL: ${won ? usShort : themShort} ${Math.max(usFinal, themFinal)}, ${won ? themShort : usShort} ${Math.min(usFinal, themFinal)}${tie ? ' (tie)' : ''}`);
  if (standingsLine) { out.push(''); out.push(standingsLine); }
  out.push('');
  out.push('SCORING SUMMARY');
  out.push(...(lines.length ? lines : ['No goals.']));
  if (corrected) out.push('* corrected after film review (see the box score for details)');
  out.push('');
  out.push('PENALTIES');
  out.push(...(pens.length ? pens : ['None.']));
  if (notesText && notesText.trim()) { out.push(''); out.push('THE STORY'); out.push(notesText.trim()); }
  if (insights.length) { out.push(''); out.push('GAME NOTES'); out.push(...insights.map(s => '- ' + s)); }
  out.push('');
  if (pmGame) {
    out.push(`+/- THIS GAME (${usShort}, from on-ice tags of our film; ${pmGame.tagged} of ${pmGame.total} goals tagged, NHL rules -- PP goals count for nobody)`);
    out.push(...pmGame.rows.map(r => `${r.name.padEnd(20)} ${fmtPM(r.pm).padStart(3)}  (+${r.plus}/-${r.minus})`));
    if (pmGame.tagged < pmGame.total) out.push(`${pmGame.total - pmGame.tagged} goal${pmGame.total - pmGame.tagged === 1 ? '' : 's'} still untagged -- open it on the box score and click "Tag on-ice".`);
    out.push('');
  }
  if (pmSeason.length) {
    // the leaderboard's plus_minus_tagged is career-to-date across every tagged game, not per season
    out.push(`${usShort.toUpperCase()} +/- (all tagged games to date, from on-ice tagging of our film)`);
    out.push(...pmSeason.map(r => `${r.name.padEnd(20)} ${fmtPM(r.plus_minus).padStart(3)}  (${plural(r.goals_tagged, 'goal')} tagged)`));
    if (!pmGame) out.push(`This game's goals haven't been tagged yet -- open any goal on the box score and click "Tag on-ice".`);
    out.push('');
  }
  if (leaders.length && (teamSeason?.gp ?? 0) >= 3) { // one or two games in, "leaders" is just everyone with a point
    out.push(`${(teamSeason?.season_label || game.season_label).replace(/^W/, '').toUpperCase()} SCORING LEADERS (${usShort})`);
    out.push(...leaders.map(p => `${p.name}: ${p.goals} G, ${p.assists} A, ${p.points} PTS in ${p.games_played} GP`));
    out.push('');
  }
  out.push(`Box score, +/- tagging, head-to-head history and player grades: ${SITE}`);
  out.push('Filmed on LiveBarn. Full game from the opening faceoff through the handshake line.');
  out.push('');
  out.push(`#hockey #beerleague #adulthockey ${/playoff/i.test(game.game_type) ? '#playoffs ' : ''}#livebarn #${(currentName || usShort).replace(/\W/g, '')}`);

  // ---- title
  const score = `${won ? usShort : themShort} ${Math.max(usFinal, themFinal)}, ${won ? themShort : usShort} ${Math.min(usFinal, themFinal)}`;
  const hook = insights.find(s => /-GOAL GAME/.test(s)) || insights.find(s => /HAT TRICK/.test(s)) || insights.find(s => /scored twice/.test(s)) || insights.find(s => /shutout/i.test(s)) || insights.find(s => /into the power play/.test(s)) || insights.find(s => /Game-winner/.test(s)) || '';
  const hookShort = hook.replace(/ \((?:[^)]*)\)/, '').replace(/\.$/, '')
    .replace(/^(\d)-GOAL GAME: (.*)$/, '$2 scores $1').replace(/^HAT TRICK: (.*)$/, '$1 hat trick')
    .replace(/^(.*) scored twice$/, '$1 x2').replace(/^Game-winner: (.*), (.*)$/, 'GWG $1 at $2')
    .replace(/^SHUTOUT: (.*)$/, '$1 shutout').replace(/^SHUTOUT for .*$/, 'Shutout');
  const seasonName = (teamSeason?.season_label || game.season_label).replace(/^W/, '').toUpperCase();
  const prefix = typeLabel === 'PLAYOFFS' ? 'PLAYOFFS: ' : /^Regular 1$/i.test(game.game_type) ? `${seasonName} OPENER: ` : '';
  let title = `${prefix}${score}${hookShort ? ' | ' + hookShort : ''} | ${shortDate(game.iso_date)}`;
  if (title.length > 100) title = `${prefix}${score} | ${shortDate(game.iso_date)}`;
  return { title, description: out.join('\n'), game, pmGame, pmSeason };
}

function periodLabel(p) { return ({ '1': '1st', '2': '2nd', '3': '3rd' })[p] || p; }
function ordinal(n) { if (n == null) return '?'; const s = ['th', 'st', 'nd', 'rd'], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); }
function longDate(iso) { const d = new Date(iso + 'T12:00:00'); return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' }); }
function shortDate(iso) { const d = new Date(iso + 'T12:00:00'); return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }); }

export function describeGame({ repo = DEFAULT_REPO, game, date, notesPath, pull = true }) {
  if (!fs.existsSync(repo)) throw new Error(`Stats repo not found at ${repo} (use --repo)`);
  const pulled = pull ? pullRepo(repo) : 'not pulled';
  const meta = findGame(repo, { game, date });
  const ctx = loadContext(repo, meta);
  const notes = notesPath && fs.existsSync(notesPath) ? fs.readFileSync(notesPath, 'utf8') : '';
  return { ...buildDescription(ctx, notes), meta, pulled, notesUsed: !!notes };
}
