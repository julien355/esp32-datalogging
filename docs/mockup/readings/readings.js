// ------------------------------------------------------------------ meter readings entered by hand (PROPOSAL, docs/mockup/readings/README.md)
// Meters the logger does not read (the water meter, power meter 2): someone reads the meter's total on site and types it in with the time.
// The server keeps every reading and works out the use of each hotel day (00:00 to 24:00) from them, so this page, the CSV and a second
// dashboard all get the same figures:
//   GET  /api/v1/manual/<site>?days=N (or ?from=&to=)   the meters, their readings, the use per day and between readings
//   POST /api/v1/manual/<site>/<meter>                  {time, value, note, reset, old}: a new reading (every login of the site)
//   POST /api/v1/manual/<site>/<meter>/<id>             {time, value, note, reason} or {delete: true, reason}: its author or an admin
// The meters are a list in site.json ("manual_meters"): a third one (gas, a solar meter) needs no code.
// In this mockup the block "if (MOCK && FX.manual)" plays the server, with the same rules.
const MM_SPREAD_H = 30, MM_GAP_D = 7;   // readings more than 30 h apart: their use is spread evenly over the days between them;
                                        // more than 7 days apart: no figure per day (the readings table still has the total)
const MM0 = (MOCK && FX.live.profile.manual_meters) || [];   // on the server: the site profile's "manual_meters"
Object.assign(IC, {
  pen: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
  water: '<path d="M12 3s4.5 5 4.5 8.5a4.5 4.5 0 0 1-9 0C7.5 8 12 3 12 3z"/><path d="M3 20.5c1.5 0 1.5-1 3-1s1.5 1 3 1 1.5-1 3-1 1.5 1 3 1 1.5-1 3-1 1.5 1 3 1"/>',
  meter: '<rect x="4" y="3" width="16" height="18" rx="2"/><rect x="7" y="6" width="10" height="4" rx="1"/><path d="M12.5 12.5 10.5 16h3l-2 3.5"/>',
});
const mmIcon = m => m.kind === 'water' ? 'water' : 'meter';
VIEWS.splice(VIEWS.findIndex(v => v.id === 'quality'), 0,
  {id: 'readings', name: 'Enter readings', short: 'Readings', ic: 'pen', grp: 'Meter readings', note: 'by hand: ' + MM0.map(m => m.name.toLowerCase()).join(', ')},
  ...MM0.map(m => ({id: m.id, name: m.name, short: m.short || m.name, ic: mmIcon(m), note: `${m.unit} per day, from the readings`})));

// Figures: a narrow space between thousands (never a comma or a point, so 18 921.334 cannot be misread), a point before the decimals
const fv = (v, d = 0) => { if (v === null || v === undefined || !isFinite(v)) return '–';
  const [i, f] = Math.abs(v).toFixed(d).split('.'); return (v < 0 ? '−' : '') + i.replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + (f ? '.' + f : ''); };
const mmDec = m => m.kind === 'water' ? 1 : 0;   // decimals of a day's use
// What was typed: "18921.334", "18921,334", "18 921,334", "18.921,334" (Indonesian) all read 18921.334. One point or one comma = the decimals.
function mmNum(s) {
  if (s === null || s === undefined) return null;
  if (typeof s === 'number') return {v: s, dec: (String(s).split('.')[1] || '').length, s: String(s)};
  s = String(s).trim().replace(/[\s  ']/g, '');
  if (!s) return null;
  const c = s.lastIndexOf(','), d = s.lastIndexOf('.');
  if (c >= 0 && d >= 0) s = c > d ? s.replace(/\./g, '').replace(',', '.') : s.replace(/,/g, '');
  else if (c >= 0) s = s.split(',').length > 2 ? s.replace(/,/g, '') : s.replace(',', '.');
  else if (s.split('.').length > 2) s = s.replace(/\./g, '');
  if (!/^\d+(\.\d+)?$/.test(s)) return {v: NaN, dec: 0, s};
  return {v: +s, dec: (s.split('.')[1] || '').length, s};
}
const mmOff = () => PROF.utc_offset_h ?? (MOCK ? FX.live.profile.utc_offset_h : 8) ?? 8;
const mmLoc = ms => new Date(ms + mmOff() * 36e5).toISOString().slice(0, 16).replace('T', ' ');   // UTC ms -> "YYYY-MM-DD HH:MM" hotel time
const mmMs = local => /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/.test(local) ? tp(local) - mmOff() * 36e5 : NaN;
const fwhen = local => `${fdate(tp(local))} ${local.slice(11, 16)}`;                           // "Tue 10 Nov 08:05"
const fshort = local => `${DAYS[new Date(tp(local)).getUTCDay()]} ${local.slice(11, 16)}`;     // "Tue 08:05"
const fdur = ms => { const m = Math.round(ms / 6e4), d = Math.floor(m / 1440), h = Math.floor(m % 1440 / 60), mi = m % 60;
  return d ? `${d} day${d > 1 ? 's' : ''} ${h} h` : h ? `${h} h ${String(mi).padStart(2, '0')} min` : `${mi} min`; };

// The checks of a reading, the same on the page (as it is typed) and on the server (before it is saved).
// rs: the meter's readings, oldest first, as {id, ms, local, value, reset}. Red (crit) stops the save; amber (warn) asks to check.
function mmCheck(m, rs, tMs, raw, {skip = null, reset = false, old = null, usual = null} = {}) {
  const u = m.unit, n = mmNum(raw), R = (cls, text, x = {}) => ({cls, text, ok: cls !== 'crit', ...x});
  if (n === null) return R('muted', 'Leave empty to skip this meter.', {empty: true});
  if (Number.isNaN(n.v)) return R('crit', 'Not a number. Type the figures of the meter, with a point or a comma before the decimals.');
  if (!isFinite(tMs)) return R('crit', 'Choose the date and the time of the reading.');
  if (tMs > nowMs() + 5 * 6e4) return R('crit', 'The time is in the future.');
  const v = n.v, o = mmNum(old), oldV = o && !Number.isNaN(o.v) ? o.v : null, x = {v, s: n.s, old: oldV};
  const list = rs.filter(r => r.id !== skip), prev = [...list].reverse().find(r => r.ms < tMs), next = list.find(r => r.ms > tMs);
  const same = list.find(r => Math.abs(r.ms - tMs) < 6e4), shown = r => `${fwhen(r.local)} (${fv(r.value, m.decimals)} ${u})`;
  if (same) return R('crit', `There is already a reading at that time: ${shown(same)}.`);
  if (reset && prev && oldV !== null && oldV < prev.value) return R('crit', `The old meter's last figure is lower than its reading of ${shown(prev)}.`);
  if (!reset && prev && v < prev.value) return R('crit', `Lower than the reading of ${shown(prev)}. Check the figure, or tick “Meter replaced or reset”.`);
  if (next && !next.reset && v > next.value) return R('crit', `Higher than the later reading of ${shown(next)}. Check the figure and the time.`);
  const more = n.dec > m.decimals ? ` The meter shows ${m.decimals} decimal${m.decimals === 1 ? '' : 's'}: check the figure.` : '';
  if (reset) return R('warn', `Starts a new count at ${fv(v, m.decimals)} ${u}. ${!prev ? '' : oldV !== null ? `The old meter's use since ${fwhen(prev.local)}: ${
    fv(oldV - prev.value, m.decimals)} ${u}.` : `The use from ${fwhen(prev.local)} to the change is not known: those days get no figure.`}${more}`, x);
  if (!prev) return R(more ? 'warn' : 'good', `First reading of this meter.${more}`, x);
  const use = v - prev.value, dt = tMs - prev.ms, pd = use / dt * 864e5, dd = mmDec(m);
  let t = `+${fv(use, m.decimals)} ${u} since ${fwhen(prev.local)} (${fdur(dt)})`;
  if (dt < 12 * 36e5 || !usual) return R(more ? 'warn' : 'good', t + '.' + more, x);   // a few hours say little about a day
  t += `, ${fv(pd, dd)} ${u} a day`;
  const range = `usual ${fv(usual.lo, dd)}–${fv(usual.hi, dd)}`;
  if (pd > usual.hi * 1.5) return R('warn', `${t}: ${(pd / usual.median).toFixed(1)} × the usual (${range}). Check the figure; if it is right, say why in the note.`, x);
  if (pd < usual.lo * 0.5) return R('warn', `${t}: much less than usual (${range}). Check the figure: meter stuck, or supply cut?`, x);
  return R(more ? 'warn' : 'good', `${t}, ${range}.${more}`, x);
}

// ------------------------------------------------------------------ mockup: the server's side, with the server's rules
if (MOCK && FX.manual) {
  const MS = FX.manual, f0 = window.fetch;
  const J = (body, status = 200) => Promise.resolve({ok: status < 400, status, json: async () => JSON.parse(JSON.stringify(body))});
  const isoZ = ms => new Date(ms).toISOString().slice(0, 19) + 'Z';
  const sorted = id => (MS.readings[id] || []).filter(r => !r.deleted).map(r => ({...r, ms: Date.parse(r.t), local: mmLoc(Date.parse(r.t))}))
    .sort((a, b) => a.ms - b.ms);
  // From one reading to the next: the use, and whether it is spread (over 30 h) or not counted per day (over 7 days, or a reset without the old figure)
  const intervals = rs => rs.slice(1).map((b, i) => { const a = rs[i], dt = b.ms - a.ms;
    let use = b.reset ? (b.old === undefined || b.old === null ? null : b.old - a.value) : b.value - a.value;
    if (use !== null && use < 0) use = null;
    return {from: a.local, to: b.local, t0: a.ms, t1: b.ms, a: a.id, b: b.id, use, h: dt / 36e5, per_day: use === null ? null : use / dt * 864e5,
      spread: dt > MM_SPREAD_H * 36e5, gap: use === null || dt > MM_GAP_D * 864e5}; });
  // One hotel day: the counter at both midnights on the straight line between the readings around them
  function dayUse(segs, d, today) {
    const d0 = tp(d + ' 00:00') - mmOff() * 36e5, d1 = d0 + 864e5;
    let use = 0, cov = 0, spread = false, s0 = null, s1 = null, span = 0;
    const via = [];
    for (const s of segs) {
      if (s.gap) continue;
      const o0 = Math.max(d0, s.t0), o1 = Math.min(d1, s.t1);
      if (o1 <= o0) continue;
      use += s.use * (o1 - o0) / (s.t1 - s.t0); cov += o1 - o0; spread = spread || s.spread; span = Math.max(span, s.h);
      if (!via.length) via.push(s.from);
      via.push(s.to);
      s0 = s0 === null ? o0 : Math.min(s0, o0); s1 = Math.max(s1 ?? o1, o1);
    }
    const how = cov >= 864e5 - 6e4 ? (spread ? 'spread' : 'measured')
      : d === today && cov > 0 && s0 <= d0 + 6e4 && Math.abs(s1 - s0 - cov) < 6e4 ? 'so_far' : 'none';
    return {date: d, use: how === 'none' ? null : +use.toFixed(3), how, via: how === 'none' ? [] : via, span_h: +span.toFixed(2),
      until: how === 'so_far' ? mmLoc(s1) : null};
  }
  function meter(m, from, to) {
    const rs = sorted(m.id), segs = intervals(rs), today = todayH(), bySeg = new Map(segs.map(s => [s.b, s]));
    const days = [];
    for (let d = from; d <= to; d = addD(d, 1)) days.push(dayUse(segs, d, today));
    const recent = [];   // "usual": the measured days of the last 28 days, 10th to 90th percentile
    for (let d = addD(today, -28); d < today; d = addD(d, 1)) { const x = dayUse(segs, d, today); if (x.how === 'measured') recent.push(x.use); }
    recent.sort((a, b) => a - b);
    const q = p => recent[Math.min(recent.length - 1, Math.floor(p * recent.length))];
    const usual = recent.length >= 5 ? {lo: q(0.1), hi: q(0.9), median: q(0.5), days: recent.length} : null;
    const inP = r => r.local.slice(0, 10) >= from && r.local.slice(0, 10) <= to;
    const pick = r => r && {id: r.id, t: r.t, local: r.local, value: r.value, user: r.user, reset: !!r.reset};
    const readings = rs.filter(inP).map(r => { const s = bySeg.get(r.id);
      return {...pick(r), entered: r.entered, entered_local: mmLoc(Date.parse(r.entered)), note: r.note || '', old: r.old ?? null, hist: r.hist || null,
        use: s ? s.use : null, h: s ? s.h : null, per_day: s ? s.per_day : null,
        high: !!(s && usual && s.h >= 12 && s.per_day > usual.hi * 1.5)}; }).reverse();
    const last = rs[rs.length - 1] || null, ago = last ? (nowMs() - last.ms) / 36e5 : null;
    return {...m, readings, before: pick([...rs].reverse().find(r => r.local.slice(0, 10) < from)) || null, last: pick(last),
      due: ago !== null && ago > m.due_h, ago_h: ago, days, usual, first_day: rs.length ? rs[0].local.slice(0, 10) : null,
      intervals: segs.filter(s => s.to.slice(0, 10) >= from && s.to.slice(0, 10) <= to).map(({t0, t1, ...s}) => s)};
  }
  function serve(u) {
    const q = new URLSearchParams(u.split('?')[1] || ''), today = todayH();
    let from = q.get('from'), to = q.get('to') || today;
    if (!from) { to = today; from = addD(today, 1 - (+q.get('days') || 14)); }
    return {site, now: mmLoc(nowMs()), from, to, meters: MS.meters.map(m => meter(m, from, to))};
  }
  function post(id, rid, b) {
    const m = MS.meters.find(x => x.id === id), list = MS.readings[id], now = isoZ(nowMs());
    if (!m) return {ok: false, error: 'No such meter'};
    const ms = b.time ? mmMs(String(b.time).replace('T', ' ')) : NaN, usual = meter(m, todayH(), todayH()).usual;
    if (rid) {   // a correction or a deletion: the reading's author or an admin, and a reason; the first figure stays in the history
      const r = list.find(x => x.id === rid && !x.deleted);
      if (!r) return {ok: false, error: 'No such reading'};
      if (r.user !== ME.user && !ME.admin) return {ok: false, error: 'Only the person who entered it, or an admin, can change it'};
      if (!String(b.reason || '').trim()) return {ok: false, error: 'Say why'};
      r.hist = r.hist || [{at: r.entered, user: r.user, what: 'entered', value: r.value}];
      if (b.delete) { r.deleted = true; r.hist.push({at: now, user: ME.user, what: 'deleted', reason: b.reason}); return {ok: true}; }
      const c = mmCheck(m, sorted(id), ms, b.value, {skip: rid, reset: !!r.reset, usual});
      if (!c.ok || c.empty) return {ok: false, error: c.text};
      r.hist.push({at: now, user: ME.user, what: 'corrected', value: c.v, was: r.value, reason: b.reason, ...(ms !== Date.parse(r.t) ? {t: isoZ(ms), was_t: r.t} : {})});
      Object.assign(r, {t: isoZ(ms), value: c.v, note: b.note ?? r.note});
      return {ok: true, reading: r};
    }
    const c = mmCheck(m, sorted(id), ms, b.value, {reset: !!b.reset, old: b.old, usual});
    if (!c.ok || c.empty) return {ok: false, error: c.text};
    const r = {id: id[0] + String(list.length + 1).padStart(4, '0'), t: isoZ(ms), value: c.v, user: ME.user, entered: now, note: String(b.note || '')};
    if (b.reset) { r.reset = true; if (c.old !== null) r.old = c.old; }
    list.push(r);
    return {ok: true, reading: r, warning: c.cls === 'warn' ? c.text : ''};
  }
  window.fetch = (url, opt = {}) => {
    const u = String(url); let m;
    if ((opt.method || 'GET') === 'GET' && /^\/api\/v1\/manual\/[a-z0-9-]+(\?|$)/.test(u)) return J(serve(u));
    if (opt.method === 'POST' && (m = u.match(/^\/api\/v1\/manual\/[a-z0-9-]+\/([a-z0-9-]+)(?:\/([a-z0-9]+))?$/))) {
      const r = post(m[1], m[2], JSON.parse(opt.body)); return J(r, r.ok ? 200 : 400);
    }
    return f0(url, opt);
  };
}

// ------------------------------------------------------------------ the pages
let MMJ = null, MMV = null, MME = null, mmMode = 'day';
const mmEntered = [];   // readings saved from this browser: highlighted in the lists
const mmGet = async p => { const j = await getJ(`/api/v1/manual/${site}?${pq(p)}`); if (!j.meters) throw new Error(j.error || 'no meters'); return j; };
const mmPost = (url, body) => fetch(url, {method: 'POST', cache: 'no-store', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'arkan'},
  body: JSON.stringify(body)}).then(r => r.json()).catch(() => ({ok: false, error: 'server not reachable'}));
const mmRs = mt => [...(mt.before ? [mt.before] : []), ...[...mt.readings].reverse()].map(r => ({...r, ms: Date.parse(r.t)}));
const mmCan = r => isAdmin() || r.user === ME.user;   // a correction: the reading's author, or an admin (the server checks it too)
const mmCsv = (mt, what, d) => `<a class="btn small" href="/api/v1/manual/${esc(site)}/${esc(mt.id)}.csv?what=${what}&amp;from=${d.from}&amp;to=${d.to}" download${
  MOCK ? ` data-ui-toast="On the real site this downloads the ${what === 'days' ? 'use per day' : 'readings'} as CSV"` : ''}>${icon('down', 'sm')}${what === 'days' ? 'CSV' : 'CSV of the readings'}</a>`;
function mmHist(r, dec = 3) {
  return (r.hist || []).map(h => `${h.what === 'entered' ? 'Entered' : h.what === 'deleted' ? 'Deleted' : 'Corrected'}${h.value !== undefined ? ' ' + fv(h.value, dec) : ''}` +
    ` by ${h.user}, ${fwhen(mmLoc(Date.parse(h.at)))}${h.reason ? ': ' + h.reason : ''}`).join(' · ');
}

// Enter readings: one time for the round, one field per meter, checked as it is typed
const mmCard = m => `<section class="card mmcard" data-mm="${esc(m.id)}">
  <div class="card-head"><h2>${icon(mmIcon(m))}${esc(m.long || m.name)}</h2><a class="link small" href="#${esc(m.id)}">Use per day</a></div>
  <div class="mmlast">${m.last ? `Last reading <b>${fv(m.last.value, m.decimals)} ${esc(m.unit)}</b> · ${fwhen(m.last.local)} · ${esc(m.last.user)}` : 'No reading yet'}${
    m.due ? ' <span class="pill warn">due</span>' : ''}${m.where ? `<br>${esc(m.where)}` : ''}</div>
  <div class="mmin"><input type="text" inputmode="decimal" autocomplete="off" spellcheck="false" id="mmv-${esc(m.id)}" aria-label="${esc(m.name)}: reading in ${esc(m.unit)}"><span class="u">${esc(m.unit)}</span></div>
  <div class="mmcheck muted" id="mmc-${esc(m.id)}" aria-live="polite"></div>
  <input type="text" id="mmn-${esc(m.id)}" placeholder="Note (optional): pool topped up, meter glass dirty…" aria-label="${esc(m.name)}: note">
  <label class="mmreset"><input type="checkbox" id="mmr-${esc(m.id)}">Meter replaced or reset: the count starts again</label>
  <div class="field" id="mmow-${esc(m.id)}" hidden><label for="mmo-${esc(m.id)}">Last figure of the old meter, if known (${esc(m.unit)})</label><input type="text" inputmode="decimal" id="mmo-${esc(m.id)}"></div>
</section>`;
function mmLatest(j) {
  const rows = j.meters.flatMap(m => m.readings.map(r => ({m, r}))).sort((a, b) => a.r.entered < b.r.entered ? 1 : -1).slice(0, 8);
  return tableCard(`<tr><th>Meter</th><th>Read at</th><th class="num">Reading</th><th class="num">Since the previous</th><th>By</th><th>Entered</th></tr>` +
    rows.map(({m, r}) => `<tr${mmEntered.includes(r.id) ? ' class="cur"' : ''}><td><a href="#${esc(m.id)}">${esc(m.name)}</a></td><td>${fwhen(r.local)}</td>
      <td class="num">${fv(r.value, m.decimals)} ${esc(m.unit)}</td><td class="num">${r.use === null ? '–' : '+' + fv(r.use, m.decimals) + ' ' + esc(m.unit)}</td>
      <td>${esc(r.user)}</td><td>${fwhen(r.entered_local)}</td></tr>`).join(''));
}
async function mmEnterView(box) {
  const j = await mmGet({days: 31}), today = todayH(), nowL = mmLoc(nowMs()), due = j.meters.filter(m => m.due);
  MMJ = j;
  box.innerHTML = head('Enter meter readings', `Type the figures as each meter shows them. Every reading is saved with your login (<b>${esc(ME.user || '…')}</b>) and the time below.`) +
    (due.length ? `<div class="banner warn">${icon('alert')}<div><b>Reading due.</b> ${due.map(m => `${esc(m.name)}: last read ${fwhen(m.last.local)}, ${fdur(m.ago_h * 36e5)} ago`).join(' · ')}</div></div>` : '') +
    `<section class="card"><div class="card-head"><h2>Time of the reading</h2><span class="muted small">hotel time (${esc(PROF.timezone || 'UTC+8')})</span></div>
      <div class="mmwhen"><input type="date" id="mmDate" value="${nowL.slice(0, 10)}" min="${addD(today, -30)}" max="${today}" aria-label="Date of the reading">
      <input type="time" id="mmTime" value="${nowL.slice(11, 16)}" aria-label="Time of the reading"><button type="button" class="btn small" id="mmNow">Now</button>
      <span class="muted small">Read at about the same time every day (08:00 suggested): the daily figures are then measured, not spread.</span></div></section>
    <div class="mmgrid mt-16">${j.meters.map(mmCard).join('')}</div>
    <div class="mmsave"><span class="muted small">Saved as <b>${esc(ME.user || '…')}</b>. A wrong figure can be corrected on the meter's page; every change is kept.</span>
      <button type="button" class="btn primary" id="mmSave" disabled>Save</button></div>` +
    sec('Latest entries', 'every meter, newest first') + mmLatest(j);
  mmRecheck();
}
function mmRecheck() {
  if (!MMJ || !el('mmSave')) return;
  const tMs = el('mmDate').value && el('mmTime').value ? mmMs(`${el('mmDate').value} ${el('mmTime').value}`) : NaN;
  let n = 0, bad = 0;
  for (const m of MMJ.meters) {
    const reset = el('mmr-' + m.id).checked;
    el('mmow-' + m.id).hidden = !reset;
    const c = mmCheck(m, mmRs(m), tMs, el('mmv-' + m.id).value, {reset, old: el('mmo-' + m.id).value, usual: m.usual}), box = el('mmc-' + m.id);
    box.className = 'mmcheck ' + c.cls;
    box.innerHTML = (c.cls === 'muted' ? '' : icon(c.cls === 'good' ? 'check' : 'alert')) + esc(c.text);
    const card = box.closest('.mmcard');
    card.classList.toggle('crit', c.cls === 'crit'); card.classList.toggle('warn', c.cls === 'warn');
    if (!c.empty) { n++; if (!c.ok) bad++; }
  }
  const b = el('mmSave');
  b.disabled = !n || bad > 0;
  b.textContent = bad ? 'Check the figure in red' : n ? `Save ${n} reading${n > 1 ? 's' : ''}` : 'Save';
}
async function mmSaveAll() {
  const time = `${el('mmDate').value}T${el('mmTime').value}`, done = [], fail = [];   // hotel time; the server knows the site's time zone
  el('mmSave').disabled = true;
  for (const m of MMJ.meters) {
    const n = mmNum(el('mmv-' + m.id).value);
    if (n === null) continue;
    const reset = el('mmr-' + m.id).checked, o = mmNum(el('mmo-' + m.id).value);
    const r = await mmPost(`/api/v1/manual/${site}/${m.id}`, {time, value: n.s, note: el('mmn-' + m.id).value.trim(), reset,
      old: reset && o && !Number.isNaN(o.v) ? o.s : null});
    if (r.ok) { done.push(`${m.name} ${fv(n.v, m.decimals)} ${m.unit}`); if (r.reading) mmEntered.push(r.reading.id); }
    else fail.push(`${m.name}: ${r.error}`);
  }
  toast(fail.length ? 'Not saved: ' + fail.join(' · ') : `Saved: ${done.join(', ')}${MOCK ? ' (mockup: kept in this page only)' : ''}`);
  if (fail.length) return mmRecheck();
  show('readings');
}

// A meter's page: use per hotel day (or between readings), the day by day table and the readings
const mmHowTip = d => d.how === 'measured' ? `Measured: readings ${d.via.map(fshort).join(' → ')}`
  : d.how === 'spread' ? `Spread evenly: readings ${d.via.map(fwhen).join(' → ')}, ${fdur(d.span_h * 36e5)} apart`
  : d.how === 'so_far' ? `So far: 00:00 to ${d.until.slice(11)} (the last reading)` : 'No reading covers this day';
function mmHowCell(d, mt) {
  if (d.how === 'measured') return `Measured <span class="dimtxt">${d.via.map(fshort).join(' → ')}</span>`;
  if (d.how === 'spread') return `<span class="pill neutral">Spread</span> <span class="dimtxt">readings ${fdur(d.span_h * 36e5)} apart: ${d.via.map(fwhen).join(' → ')}</span>`;
  if (d.how === 'so_far') return `So far <span class="dimtxt">00:00 to ${d.until.slice(11)}</span>`;
  return mt.last && d.date >= mt.last.local.slice(0, 10) ? 'Waiting for the next reading' : 'Not covered by readings';
}
// Bars with gaps: one per day (or per reading), lighter for spread or "so far", the mean of the full days as a dashed line
function mmBars(box, bars, unit, {xName = 'Day (hotel time)', mean = null, digits = 1} = {}) {
  sizeTo(box);
  const vals = bars.map(b => b.v).filter(v => v !== null);
  if (!vals.length) { box.innerHTML = '<div class="empty">No readings for this period.</div>'; return; }
  const yt = nice(0, Math.max(...vals, mean ?? 0) || 1), y1 = yt[yt.length - 1], bw = (CW - CM.l - CM.r) / bars.length;
  const Y = v => CH - CM.b - v / y1 * (CH - CM.t - CM.b);
  let g = '', b = '';
  for (const v of yt) g += `<line class="grid" x1="${CM.l}" x2="${CW - CM.r}" y1="${Y(v)}" y2="${Y(v)}"/><text class="ax" x="${CM.l - 6}" y="${Y(v) + 4}" text-anchor="end">${v}</text>`;
  bars.forEach((d, i) => {
    const w = Math.max(2, Math.min(bw - 2, bw * 0.82)), x = CM.l + i * bw + (bw - w) / 2;
    if (d.v === null) b += `<text class="mmno" x="${x + w / 2}" y="${CH - CM.b - 5}" text-anchor="middle">–</text>`;
    else { const y = Y(d.v), r = Math.max(0, Math.min(4, w / 2, CH - CM.b - y));
      b += `<path d="M${x},${CH - CM.b}V${y + r}q0,${-r} ${r},${-r}h${w - 2 * r}q${r},0 ${r},${r}V${CH - CM.b}Z" style="fill:var(--s1)${d.light ? ';opacity:.45' : ''}"/>`; }
    if (i % Math.ceil(40 / bw) === 0) b += `<text class="ax" x="${x + w / 2}" y="${CH - CM.b + 14}" text-anchor="middle">${esc(d.l1)}</text><text class="ax" x="${x + w / 2}" y="${CH - CM.b + 27}" text-anchor="middle">${esc(d.l2)}</text>`;
    b += `<rect data-i="${i}" x="${CM.l + i * bw}" y="${CM.t}" width="${bw}" height="${CH - CM.t - CM.b}" fill="transparent"/>`;
  });
  const ref = mean === null ? '' : `<line class="mmmean" x1="${CM.l}" x2="${CW - CM.r}" y1="${Y(mean).toFixed(1)}" y2="${Y(mean).toFixed(1)}"/>` +
    `<text class="ax liml" x="${CW - CM.r - 4}" y="${(Y(mean) - 5).toFixed(1)}" text-anchor="end">mean ${fv(mean, digits)}</text>`;
  box.innerHTML = `<div class="legend"><span><i class="mmfull"></i>${xName.startsWith('Day') ? 'Measured: readings about a day apart' : 'About a day since the reading before'}</span>
    <span><i class="mmlight"></i>${xName.startsWith('Day') ? 'Spread: readings more than 30 h apart · today so far' : 'More than 30 h since the reading before'}</span>${mean === null ? '' : '<span><i class="mmref"></i>Mean of the full days</span>'}</div>
    <svg viewBox="0 0 ${CW} ${CH}" role="img" aria-label="${esc(unit)} per bar">${g}
    <text class="ax" x="12" y="${(CH - CM.b + CM.t) / 2}" transform="rotate(-90 12 ${(CH - CM.b + CM.t) / 2})" text-anchor="middle">${esc(unit)}</text>${axes(xName)}${b}${ref}</svg>`;
  const svg = box.querySelector('svg');
  svg.addEventListener('mousemove', ev => { const i = ev.target.dataset && ev.target.dataset.i; if (i === undefined) return hideTip(); showTip(ev, bars[i].tip); });
  svg.addEventListener('mouseleave', hideTip);
}
function mmReadTable(mt, d) {
  const u = esc(mt.unit), dd = mmDec(mt);
  const rows = mt.readings.map(r => {
    const late = Date.parse(r.entered) - Date.parse(r.t) > 2 * 36e5, corr = (r.hist || []).some(h => h.what === 'corrected');
    const pills = [r.reset ? `<span class="pill neutral" title="${esc(r.old !== null ? 'Last figure of the old meter: ' + fv(r.old, mt.decimals) : 'Old meter\'s last figure not known')}">new count</span>` : '',
      corr ? `<span class="pill info" title="${esc(mmHist(r, mt.decimals))}">corrected</span>` : '', r.high ? `<span class="pill warn" title="More than 1.5 × the usual use per day">high</span>` : ''].filter(Boolean).join(' ');
    return `<tr${mmEntered.includes(r.id) ? ' class="cur"' : ''}><td>${fwhen(r.local)}</td><td class="num"><b>${fv(r.value, mt.decimals)}</b></td>
      <td class="num">${r.use === null ? '–' : '+' + fv(r.use, mt.decimals)}${r.h === null ? '' : `<br><small class="muted">in ${fdur(r.h * 36e5)}</small>`}</td>
      <td class="num">${r.per_day === null || r.h < 12 ? '–' : fv(r.per_day, dd)}</td>
      <td>${esc(r.user)}${late ? `<br><small class="muted">entered ${fwhen(r.entered_local)}</small>` : ''}</td><td class="wrap">${pills}${pills && r.note ? ' ' : ''}${esc(r.note)}</td>
      <td>${mmCan(r) ? `<button type="button" class="icon-btn mmedit" data-mmedit="${esc(r.id)}" aria-label="Correct the reading of ${fwhen(r.local)}" title="Correct this reading">${icon('pen')}</button>` : ''}</td></tr>`;
  }).join('');
  return `<section class="card"><div class="card-head"><h2>Readings</h2><div class="inline"><span class="muted small">${mt.readings.length} in the period, newest first</span>
      <a class="btn small" href="#readings">${icon('pen', 'sm')}Enter a reading</a>${mmCsv(mt, 'readings', d)}</div></div>
    <div class="tablewrap"><table class="data"><tr><th>Read at</th><th class="num">Reading (${u})</th><th class="num">Since the previous</th>
      <th class="num">Per day</th><th>By</th><th>Note</th><th></th></tr>${rows || '<tr><td colspan="7" class="muted">No reading in this period.</td></tr>'}</table></div></section>`;
}
async function mmMeterView(box, id) {
  const j = await mmGet(per()), mt = j.meters.find(m => m.id === id), d = pDates();
  if (!mt) { box.innerHTML = head(id, '') + '<section class="card"><div class="empty">This meter is not in the site\'s manual_meters.</div></section>'; return; }
  MMV = mt;
  let main = null;   // the main meter of the logger, per hotel day, for a meter that names it ("compare")
  if (mt.compare) try { main = byDay((await hourly()).hours); } catch (e) { main = null; }
  const u = mt.unit, dd = mmDec(mt), today = todayH(), y = mt.days.find(x => x.date === addD(today, -1));
  const full = mt.days.filter(x => x.how === 'measured' || x.how === 'spread'), nSpread = full.filter(x => x.how === 'spread').length;
  const mean = full.length ? full.reduce((a, x) => a + x.use, 0) / full.length : null;
  const top = full.reduce((a, x) => (!a || x.use > a.use ? x : a), null);
  const both = main ? full.filter(x => main[x.date] && main[x.date].minutes >= 1430) : [];
  const share = both.length ? both.reduce((a, x) => a + x.use, 0) / both.reduce((a, x) => a + main[x.date].kwh, 0) * 100 : null;
  const yNote = !y ? '' : y.how === 'none' ? (mt.last && mt.last.local < today + ' 00:00' ? 'waiting for today\'s reading' : 'no reading') : y.how === 'spread' ? 'spread over readings ' + fdur(y.span_h * 36e5) + ' apart' : 'measured';
  box.innerHTML = head(mt.long || mt.name, `Read by hand${mt.where ? ', ' + esc(mt.where) : ''}. Use per hotel day (00:00 to 24:00), worked out from the readings. ${cap(pText())}.`,
      periodPicker(mmCsv(mt, 'days', d))) +
    tiles([range ? statTile('Total of the period', fv(full.reduce((a, x) => a + x.use, 0), dd), u, `${full.length} full day${full.length === 1 ? '' : 's'}`)
        : statTile('Yesterday', y && y.use !== null ? fv(y.use, dd) : '–', u, yNote),
      statTile('Mean per day', mean === null ? '–' : fv(mean, dd), u, `${full.length} full day${full.length === 1 ? '' : 's'}${nSpread ? `, ${nSpread} spread` : ''}`),
      share !== null ? statTile(`Share of the main meter ${mt.compare}`, share.toFixed(0), '%', `${both.length} day${both.length === 1 ? '' : 's'} with both meters`)
        : statTile('Highest day', top ? fv(top.use, dd) : '–', u, top ? fday(top.date) + (top.how === 'spread' ? ', spread' : '') : ''),
      statTile('Last reading', mt.last ? `<span class="mmlong">${fv(mt.last.value, mt.decimals)}</span>` : '–', u, mt.last ? `${fwhen(mt.last.local)} · ${esc(mt.last.user)}${
        mt.due ? ` · <span class="warnc">due, ${fdur(mt.ago_h * 36e5)} ago</span>` : ''}` : 'no reading yet')]) +
    `<section class="card mt-16"><div class="card-head"><h2>${mmMode === 'day' ? 'Use per hotel day' : 'Use between readings'}</h2>
      <div class="seg" role="group" aria-label="How the use is shown">${segBtn('data-mmmode="day"', mmMode === 'day', 'Per hotel day')}${segBtn('data-mmmode="read"', mmMode === 'read', 'Between readings')}</div></div>
      <div class="chart" id="ch"></div>
      <p class="mmrule">${mmMode === 'day' ? `<b>How a day's use is worked out.</b> A reading gives the meter's total at the time it was read. The total at midnight is taken on the
        straight line between the readings just before and after it, and a day's use runs from midnight to midnight, as on Energy per day. Readings about a day apart
        give a measured day. Lighter bars: readings more than ${MM_SPREAD_H} h apart (a Sunday or a holiday without a round), their use is spread evenly over the
        days between them; and today so far. No bar: no reading after that day yet, or more than ${MM_GAP_D} days between two readings.`
        : `<b>Between readings.</b> Each bar is the use from one reading to the next, on the day and time of the later reading: the way a paper round sheet counts it.
        Lighter: more than ${MM_SPREAD_H} h since the reading before, so the bar holds more than a day.`}</p></section>` +
    (mmMode === 'day' ? sec('Day by day', 'newest first') + tableCard(`<tr><th>Day</th><th class="num">Use</th><th>From the readings</th>${main ? `<th class="num">Main meter ${esc(mt.compare)}</th><th class="num">Share</th>` : ''}</tr>` +
      [...mt.days].reverse().map(x => { const mm = main && main[x.date], mok = mm && mm.minutes >= 1430;
        return `<tr class="${x.how === 'none' ? 'mmnone' : x.how !== 'measured' ? 'mmlight' : ''}"><td>${fday(x.date)}</td><td class="num use">${x.use === null ? '–' : fv(x.use, dd) + ' ' + esc(u)}</td><td>${mmHowCell(x, mt)}</td>${
          main ? `<td class="num">${mm ? fv(mm.kwh, 0) + ' kWh' + (mok ? '' : ' <span class="dimtxt">part</span>') : '–'}</td><td class="num">${mok && x.use !== null && x.how !== 'so_far' ? (x.use / mm.kwh * 100).toFixed(0) + ' %' : ''}</td>` : ''}</tr>`; }).join('')) : '') +
    sec('Readings') + mmReadTable(mt, d);
  if (mmMode === 'day') mmBars(el('ch'), mt.days.map(x => { const ms = tp(x.date + ' 00:00'), dt = new Date(ms);
    return {v: x.use, light: x.how !== 'measured', l1: DAYS[dt.getUTCDay()], l2: `${dt.getUTCDate()} ${MONS[dt.getUTCMonth()]}`,
      tip: `<b>${fdate(ms)}</b>${x.use === null ? 'no figure' : fv(x.use, dd) + ' ' + esc(u) + (x.how === 'so_far' ? ' so far' : '')}` +
        `${main && main[x.date] && x.use !== null ? `<div class="dim">main meter ${esc(mt.compare)}: ${fv(main[x.date].kwh, 0)} kWh</div>` : ''}<div class="dim">${esc(mmHowTip(x))}</div>`}; }),
    u, {mean, digits: dd});
  else mmBars(el('ch'), mt.intervals.map(s => ({v: s.use, light: s.spread, l1: `${DAYS[new Date(tp(s.to)).getUTCDay()]} ${+s.to.slice(8, 10)}`, l2: s.to.slice(11, 16),
    tip: `<b>${fwhen(s.from)} → ${fwhen(s.to)}</b>${s.use === null ? 'not counted (meter replaced or reset)' : `+${fv(s.use, mt.decimals)} ${esc(u)} in ${fdur(s.h * 36e5)}`}` +
      (s.h >= 12 && s.per_day !== null ? `<div class="dim">${fv(s.per_day, dd)} ${esc(u)} a day</div>` : '')})), u, {xName: 'Reading (hotel time)', digits: dd});
}

// Correcting a reading: a sheet with the figure, the time, the note and why; or deleting it. The first figure stays in the history.
function mmOpenEdit(rid) {
  const mt = MMV, r = mt && mt.readings.find(x => x.id === rid);
  if (!r) return;
  if (!el('mmSheet')) document.body.insertAdjacentHTML('beforeend', `<div class="sheet-wrap" id="mmSheet" hidden><div class="sheet small" tabindex="-1" role="dialog" aria-labelledby="mmsT">
    <div class="sheet-top"><h2 id="mmsT"></h2><button class="icon-btn" data-ui-close aria-label="Close"><svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button></div>
    <div id="mmsBody"></div></div></div>`);
  MME = {mt, r};
  el('mmsT').textContent = `Correct a reading: ${mt.name}`;
  el('mmsBody').innerHTML = `<dl class="dl" style="padding-top:0"><dt>Entered</dt><dd>${fv(r.value, mt.decimals)} ${esc(mt.unit)}, read ${fwhen(r.local)}, by ${esc(r.user)} on ${fwhen(r.entered_local)}</dd>
      ${r.hist ? `<dt>Changes</dt><dd>${esc(mmHist(r, mt.decimals))}</dd>` : ''}</dl>
    <div class="fgrid mt-16"><div class="field"><label for="mmsV">Reading (${esc(mt.unit)})</label><input type="text" inputmode="decimal" id="mmsV" value="${r.value.toFixed(mt.decimals)}"></div>
      <div class="field"><label for="mmsD">Read at (hotel time)</label><div class="mmwhen"><input type="date" id="mmsD" value="${r.local.slice(0, 10)}" max="${todayH()}">
        <input type="time" id="mmsH" value="${r.local.slice(11, 16)}" aria-label="Time"></div></div>
      <div class="field"><label for="mmsN">Note</label><input type="text" id="mmsN" value="${esc(r.note)}"></div>
      <div class="field"><label for="mmsW">Why (kept with the change)</label><input type="text" id="mmsW" placeholder="e.g. typing error, checked on the meter"></div></div>
    <div class="mmcheck muted mt-8" id="mmsC"></div>
    <div class="mmsheet-acts"><button type="button" class="btn danger" id="mmsDel">Delete this reading</button><button type="button" class="btn primary" id="mmsSave">Save the correction</button></div>
    <p class="muted small mt-8">The reading as first entered and every change stay in the meter's file, with the login and the time.</p>`;
  ArkanUI.openSheet('mmSheet');
  mmsRecheck();
}
function mmsRecheck() {
  if (!MME || !el('mmsC')) return;
  const {mt, r} = MME, tMs = mmMs(`${el('mmsD').value} ${el('mmsH').value}`);
  const c = mmCheck(mt, mmRs(mt), tMs, el('mmsV').value, {skip: r.id, reset: r.reset, usual: mt.usual}), why = el('mmsW').value.trim();
  el('mmsC').className = 'mmcheck mt-8 ' + (c.empty ? 'crit' : c.cls);
  el('mmsC').innerHTML = c.empty ? icon('alert') + 'Type the figure, or delete the reading.' : (c.cls === 'muted' ? '' : icon(c.cls === 'good' ? 'check' : 'alert')) + esc(c.text);
  el('mmsSave').disabled = !c.ok || c.empty || !why;
  el('mmsDel').disabled = !why;
  el('mmsSave').title = el('mmsDel').title = why ? '' : 'Say why first';
}
async function mmsSend(del) {
  const {mt, r} = MME, why = el('mmsW').value.trim();
  if (del && !ask(`Delete the ${mt.name} reading of ${fwhen(r.local)} (${fv(r.value, mt.decimals)} ${mt.unit})? It stays in the history.`)) return;
  const n = mmNum(el('mmsV').value);
  const res = await mmPost(`/api/v1/manual/${site}/${mt.id}/${r.id}`, del ? {delete: true, reason: why}
    : {time: `${el('mmsD').value}T${el('mmsH').value}`, value: n && n.s, note: el('mmsN').value.trim(), reason: why});
  if (!res.ok) return toast('Not saved: ' + res.error);
  ArkanUI.closeSheets();
  toast(`${del ? 'Deleted' : 'Corrected'}${MOCK ? ' (mockup: in this page only)' : ''}`);
  renderHistory().catch(() => {});
}

const MVIEWS = {readings: mmEnterView};
for (const m of MM0) MVIEWS[m.id] = box => mmMeterView(box, m.id);
for (const type of ['input', 'change']) document.addEventListener(type, ev => {
  const id = ev.target.id || '';
  if (/^mm[vnro]-|^mmDate$|^mmTime$/.test(id)) mmRecheck();
  if (/^mms[VDHNW]$/.test(id)) mmsRecheck();
});
document.addEventListener('click', ev => {
  const b = ev.target.closest('[data-mmmode],[data-mmedit],#mmNow,#mmSave,#mmsSave,#mmsDel');
  if (!b || b.disabled) return;
  if (b.dataset.mmmode) { mmMode = b.dataset.mmmode; return renderHistory().catch(() => {}); }
  if (b.dataset.mmedit) return mmOpenEdit(b.dataset.mmedit);
  if (b.id === 'mmNow') { const l = mmLoc(nowMs()); el('mmDate').value = l.slice(0, 10); el('mmTime').value = l.slice(11, 16); return mmRecheck(); }
  if (b.id === 'mmSave') return mmSaveAll();
  if (b.id === 'mmsSave' || b.id === 'mmsDel') return mmsSend(b.id === 'mmsDel');
});
