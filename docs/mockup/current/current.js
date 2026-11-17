// ------------------------------------------------------------------ current per phase and balance (PROPOSAL, docs/mockup/current/README.md)
// One page in the menu group Power quality, between Voltage and Power factor: #current. From the server (proposed: server/app/quality.py,
// the same pass over the day files and the same cache as the other power quality pages):
//   GET /api/v1/quality/<site>/current?days=N (or ?from=&to=)   one row per hotel hour: each phase's current (mean, lowest and highest
//       15-second sample, highest 15-minute mean), its active power, kWh and power factor; the estimated neutral current; the current
//       unbalance (mean, highest minute, minutes counted, minutes above A10); the minutes with a sample above A37 (90 % of the PLN phase
//       limit) and with a phase without current; the lowest power of each phase; two sums that check the meter's registers. With the
//       limits of the alarm register, the PLN phase limit (contracted_kva / 3 / contract_v_ln) and the current lines of the alarm log.
//   GET /api/v1/quality/<site>/current/day/<date>                the currents, neutral, phase powers and unbalance of one hotel day,
//       minute by minute
// Nothing new is recorded: every figure comes from the columns the logger already writes (i1..i3, p1..p3, v1..v3, p, s, with their
// 15-second lowest and highest).
const CCACHE = {}, BUSY_Q = 0.75;   // the busy hours: the hours whose heaviest phase is in the top quarter of the period
let cDay = null;
Object.assign(IC, {amp: '<path d="M2.5 12c2-5.5 3.4-7 4.7-7 2.4 0 2.4 14 4.8 14s2.4-14 4.8-14c1.3 0 2.7 1.5 4.7 7"/>'});
VIEWS.splice(VIEWS.findIndex(v => v.id === 'pf'), 0, {id: 'current', name: 'Current & balance', short: 'Current', ic: 'amp', note: 'per phase, unbalance, neutral'});

async function cHourly(p = per()) {
  const k = pq(p), c = CCACHE[k];
  if (c && Date.now() - c.at < 120e3) return c.j;
  const j = await getJ(`/api/v1/quality/${site}/current?${k}`);
  if (!j.hours) throw new Error(j.error || 'no hours');
  if (j.first_day) FIRST = j.first_day;
  CCACHE[k] = {at: Date.now(), j};
  return j;
}
const PHN = ['L1', 'L2', 'L3'];
const swl = n => `<span class="swl" style="background:${C[n]}"></span>`;
const limTag = l => `${esc(l.id)}${l.proposed ? ' (proposed)' : l.enabled ? '' : ' (alarm off)'}`;
const hourOf = t => `${fdate(tp(t))}, ${t.slice(11)} hour`;
const fA = (v, d = 0) => v === null || v === undefined ? '–' : (+v).toFixed(d);
const nf = v => v === null || v === undefined ? '–' : Math.round(v).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ');   // 1 412

function cSum(H) {   // totals of a list of hours
  const o = {minutes: 0, n: 0, inW: 0, inMax: null, inAt: null, iuW: 0, iuN: 0, iuMax: null, iuHour: null, iuHourAt: null, iuHi: 0,
    iHi: 0, iHiAt: null, zero: 0, zeroAt: null, zeroPh: '', zeroH: null, psW: 0, ssW: 0, ldN: 0,
    ph: [0, 1, 2].map(() => ({w: 0, n: 0, lo: null, hi: null, hiAt: null, d15: null, d15At: null, e: 0, pW: 0, pfW: 0, pfN: 0, pmin: null, pminAt: null, hiN: 0}))};
  for (const r of H) {
    o.minutes += r.minutes; o.n += r.n || 0;
    o.ph.forEach((P, k) => {
      const s = k + 1, i = r[`i${s}`];
      if (i === undefined) return;
      P.w += i * r.n; P.n += r.n; P.e += r[`e${s}`] || 0; P.pW += (r[`p${s}`] || 0) * r.n; P.hiN += r[`i${s}_hi`] || 0;
      if (r[`i${s}_max`] !== undefined && (P.hi === null || r[`i${s}_max`] > P.hi)) { P.hi = r[`i${s}_max`]; P.hiAt = r.t; }
      if (r[`i${s}_d15`] !== undefined && (P.d15 === null || r[`i${s}_d15`] > P.d15)) { P.d15 = r[`i${s}_d15`]; P.d15At = r.t; }
      if (r[`pf${s}`] !== undefined) { P.pfW += r[`pf${s}`] * r.n; P.pfN += r.n; }
      if (r[`p${s}_min`] !== undefined && (P.pmin === null || r[`p${s}_min`] < P.pmin)) { P.pmin = r[`p${s}_min`]; P.pminAt = r.t; }
    });
    if (r.in !== undefined) { o.inW += r.in * r.n; if (o.inMax === null || r.in_max > o.inMax) { o.inMax = r.in_max; o.inAt = r.t; } }
    if (r.iu !== undefined) {
      o.iuW += r.iu * r.iu_n; o.iuN += r.iu_n; o.iuHi += r.iu_hi || 0;
      if (o.iuMax === null || r.iu_max > o.iuMax) o.iuMax = r.iu_max;
      if (o.iuHour === null || r.iu > o.iuHour) { o.iuHour = r.iu; o.iuHourAt = r.t; }
    }
    const hiN = (r.i1_hi || 0) + (r.i2_hi || 0) + (r.i3_hi || 0);
    if (hiN) { o.iHi += hiN; o.iHiAt ??= r.t; }
    if (r.i_zero) { o.zero += r.i_zero; if (!o.zeroAt) { o.zeroAt = r.t.slice(0, 11) + r.i_zero_at; o.zeroPh = r.i_zero_ph; o.zeroH = r; } }
    if (r.psum !== undefined) { o.psW += r.psum * r.n; o.ssW += r.sratio * r.n; o.ldN += r.n; }
  }
  o.ph.forEach(P => { P.mean = P.n ? P.w / P.n : null; P.pf = P.pfN ? P.pfW / P.pfN : null; P.p = P.n ? P.pW / P.n : null; });
  const e = o.ph.reduce((a, P) => a + P.e, 0);
  o.ph.forEach(P => { P.share = e > 0 ? P.e / e * 100 : null; });
  o.e = e;
  o.in = o.n ? o.inW / o.n : null;
  o.iu = o.iuN ? o.iuW / o.iuN : null;
  o.psum = o.ldN ? o.psW / o.ldN : null;
  o.sratio = o.ldN ? o.ssW / o.ldN : null;
  return o;
}
function cByDay(H) {
  const g = {};
  for (const r of H) (g[r.t.slice(0, 10)] ??= []).push(r);
  return Object.fromEntries(Object.entries(g).map(([k, rows]) => [k, cSum(rows)]));
}
// The busy hours: the hours whose heaviest phase is in the top quarter of the period. Their mean current per phase, and the one move of
// single-phase load from the heaviest phase to the lightest that balances them best: half the difference between the two, which leaves
// the middle phase's deviation as the unbalance after the move.
function cBalance(H, j) {
  const rows = H.filter(r => r.n >= 30 && r.i1 !== undefined && r.i2 !== undefined && r.i3 !== undefined);
  if (rows.length < 4) return null;
  const mx = r => Math.max(r.i1, r.i2, r.i3), cut = rows.map(mx).sort((a, b) => a - b)[Math.floor(rows.length * BUSY_Q)];
  const busy = rows.filter(r => mx(r) >= cut);
  const a = [1, 2, 3].map(k => busy.reduce((s, r) => s + r[`i${k}`], 0) / busy.length), M = (a[0] + a[1] + a[2]) / 3;
  const ord = [0, 1, 2].sort((x, y) => a[y] - a[x]), [hv, md, lt] = ord, d = (a[hv] - a[lt]) / 2;
  const after = a.slice(); after[hv] -= d; after[lt] += d;
  const u = v => Math.max(...v.map(x => Math.abs(x - M))) / M * 100;
  const pf = busy.reduce((s, r) => s + (r[`pf${hv + 1}`] ?? 0.9), 0) / busy.length;
  const cnt = {}; for (const r of busy) cnt[+r.t.slice(11, 13)] = (cnt[+r.t.slice(11, 13)] || 0) + 1;
  const top = Math.max(...Object.values(cnt)), hrs = Object.keys(cnt).map(Number).filter(h => cnt[h] >= Math.max(2, top / 3)).sort((x, y) => x - y);
  const spans = []; for (const h of hrs) { const s = spans[spans.length - 1]; if (s && h === s[1] + 1) s[1] = h; else spans.push([h, h]); }
  const hh = h => String(h % 24).padStart(2, '0') + ':00';
  return {a, M, hv, md, lt, d, after, before: u(a), afterU: u(after), kw: d * (j.nominal_v || 230) * pf / 1000, n: busy.length,
    when: spans.sort((x, y) => (y[1] - y[0]) - (x[1] - x[0])).slice(0, 2).sort((x, y) => x[0] - y[0]).map(s => `${hh(s[0])} to ${hh(s[1] + 1)}`).join(' and ')};
}
// The checks of the measurement: is what the page shows right? [state, title, text, what went wrong (for the banner)];
// state good | warn | crit | neutral
function cChecks(t, j) {
  const L = j.limits, out = [], ph = t.ph;
  const pmin = ph.map(P => P.pmin), neg = pmin.some(v => v !== null && v < L.pneg.v);
  out.push([neg ? 'crit' : 'good', 'CT direction', neg
    ? `A phase's power went below ${L.pneg.v} kW (${limTag(L.pneg)}): its CT is fitted backwards (or power was exported). Lowest 1-minute power: ${pmin.map((v, k) => `${PHN[k]} ${fA(v, 1)}`).join(' · ')} kW.`
    : `The power of every phase stayed positive. Lowest 1-minute power: ${pmin.map((v, k) => `${PHN[k]} ${fA(v, 1)}`).join(' · ')} kW. A CT fitted backwards gives a negative power on its phase (${limTag(L.pneg)}).`,
    'a phase with negative power (CT backwards?)']);
  const pfs = ph.map(P => P.pf), okPf = pfs.every(v => v !== null && v >= 0.5 && v <= 1.0) && Math.max(...pfs) - Math.min(...pfs) <= 0.2;
  out.push([pfs.some(v => v === null) ? 'neutral' : okPf ? 'good' : 'crit', 'Each CT on its own phase', `Power factor of each phase under load: ${
    pfs.map((v, k) => `${PHN[k]} ${fA(v, 2)}`).join(' · ')}. ${okPf ? 'All between 0.5 and 1 and close to each other.' : '<b>Far apart or below 0.5: a CT is on another phase than its voltage (the phases are crossed between the CTs and the voltage wires).</b>'} ` +
    'A crossed CT reads its current 120° away from its voltage: its power factor falls near 0.5 or below zero.', 'the power factors of the phases far apart (CTs crossed?)']);
  const ps = t.psum, okPs = ps !== null && Math.abs(ps - 100) <= 2;
  out.push([ps === null ? 'neutral' : okPs ? 'good' : 'warn', 'The phases add up to the total',
    `P1 + P2 + P3 = ${fA(ps, 1)} % of the meter's total kW (mean of the minutes with 1 kW or more). More than 2 % off: the scale or the register of one value is wrong (Meter registers).`,
    `the phase powers add up to ${fA(ps, 1)} % of the total`]);
  const sr = t.sratio, ratio = sr ? sr / 100 : null, ctOff = ratio && (Math.abs(ratio - 50) < 5 || Math.abs(1 / ratio - 50) < 5);
  out.push([sr === null ? 'neutral' : ctOff ? 'crit' : Math.abs(sr - 100) <= 5 ? 'good' : 'warn', 'The currents agree with the kVA',
    `V1·I1 + V2·I2 + V3·I3 = ${fA(sr, 1)} % of the meter's kVA. ${ctOff ? '<b>About 50 times off: ct_mult is applied to the currents and not to the powers, or the other way round.</b> ' : ''}` +
    'This catches a current scale or a ct_mult different from the one of the powers (Meter registers, Meter link settings).', `V·I of the phases = ${fA(sr, 1)} % of the kVA`]);
  out.push([t.zero ? 'warn' : 'good', 'A current on every phase', t.zero
    ? `<b>${esc(t.zeroPh)} read under ${L.izero.v} A for ${t.zero} minute${t.zero > 1 ? 's' : ''} while the two others carried load</b>, first on ${fdate(tp(t.zeroAt))} at ${esc(t.zeroAt.slice(11))}. ` +
      'Either its CT is shorted or disconnected (the meter then counts too few kWh), or every load of that phase was off (a fuse, a sub-board breaker). ' +
      `<a href="#current" data-cday="${t.zeroAt.slice(0, 10)}">Show that day</a> · ${limTag(L.izero)} would report it.`
    : `No minute with one phase under ${L.izero.v} A while the two others carried 10 A or more (${limTag(L.izero)}).`,
    t.zero ? `${esc(t.zeroPh)} read under ${L.izero.v} A for ${t.zero} min while the others carried load (${fdate(tp(t.zeroAt))} ${esc(t.zeroAt.slice(11))})` : '']);
  const chk = PROF.meter_checked;
  out.push([chk ? 'good' : 'warn', 'Checked against the meter and a clamp meter', chk
    ? `Register table and CT ratio checked on site on ${esc(chk)}.`
    : 'Not yet. The amperes and kW are not trusted until the register check of the first site visit: each value within 1 % of the meter\'s display, one phase cable with a clamp meter, the CT label (250/5 A) read (docs/meter/README.md, section 4).']);
  return out;
}

QVIEWS.current = async function (box) {
  const j = await cHourly(), H = j.hours, L = j.limits, t = cSum(H), today = j.now.slice(0, 10), pln = j.pln_a;
  const title = 'Current per phase and balance';
  const note = `Current of each phase from the 1-minute records (mean, lowest and highest 15-second sample), against the PLN phase limit ` +
    `(${fA(pln, 0)} A: ${esc(PROF.contracted_kva)} kVA / 3 / ${esc(PROF.contract_v_ln || 220)} V) and the alarm register; the share of the load each phase carries and the unbalance between them. Hotel time, ${pText()}.`;
  if (!t.n) return noMeter(box, title, note, H.length > 0);
  const d = pDates();
  if (cDay && (cDay < d.from || cDay > d.to)) cDay = null;
  const hiK = [0, 1, 2].reduce((a, k) => (t.ph[k].hi ?? -1) > (t.ph[a].hi ?? -1) ? k : a, 0), HI = t.ph[hiK];
  const dK = [0, 1, 2].reduce((a, k) => (t.ph[k].d15 ?? -1) > (t.ph[a].d15 ?? -1) ? k : a, 0), D15 = t.ph[dK];
  const nearA = pln * L.pln.v / 100;
  const checks = cChecks(t, j), bad = checks.filter(c => c[0] === 'crit' || (c[0] === 'warn' && c[1] !== 'Checked against the meter and a clamp meter'));
  const B = cBalance(H, j);

  let h = head(title, note, periodPicker(recCsv(true)));
  if (bad.length) h += `<div class="banner warn cban">${icon('alert', 'sm')}<span>To look at: ${bad.map(c => c[3]).join('; ')}. <a href="#cchecks" data-cjump>Measurement checks</a></span></div>`;
  h += `<div class="tiles qt">${[
    statTile('Highest phase current', flag(HI.hi > nearA, fA(HI.hi)), 'A', `15-second sample · ${PHN[hiK]}, ${hourOf(HI.hiAt)}` + capBar(HI.hi / pln, `of the ${fA(pln)} A PLN phase limit`)),
    statTile('Highest 15-minute mean', fA(D15.d15), 'A', `${PHN[dK]}, ${hourOf(D15.d15At)} · what warms the cables and the limiter` + capBar(D15.d15 / pln, 'of the PLN phase limit')),
    statTile('Near the PLN limit', flag(t.iHi > 0, t.iHi), 'minutes', `with a 15-second sample above ${L.pln.v} % of the limit (${fA(nearA, 1)} A) · ${limTag(L.pln)} starts after 5 minutes in a row` +
      (t.iHiAt ? ` · first ${hourOf(t.iHiAt)}` : '')),
    statTile('Current unbalance', flag(t.iuHour > L.iu.v, fA(t.iu, 1)), '%', `mean of the minutes with ${j.i_floor_a} A or more · highest hour ${fA(t.iuHour, 0)} % (${t.iuHourAt ? hourOf(t.iuHourAt) : '–'}) · ` +
      `${t.iuHi} min above ${L.iu.v} % (${limTag(L.iu)})` + (B ? ` · at the busy hours ${PHN[B.hv]} is ${fA(B.a[B.hv] - B.M)} A above the mean` : '')),
    statTile('Share of the energy', t.ph.map(P => fA(P.share, 0)).join(' · '), '%', `L1 · L2 · L3: ${t.ph.map(P => nf(P.e)).join(' · ')} kWh, from the power of each phase`),
    statTile('Neutral current, estimated', fA(t.in, 0), 'A', `mean · highest minute ${fA(t.inMax, 0)} A (${t.inAt ? hourOf(t.inAt) : '–'}) · from the three currents and their power factors, without harmonics`),
  ].join('')}</div>`;

  // Each phase: the figures side by side
  const best = (vals, hi = true) => { const v = vals.filter(x => x !== null); return v.length ? (hi ? Math.max(...v) : Math.min(...v)) : null; };
  const row = (label, vals, show, hiMark = true, cls = '') => { const b = best(vals, hiMark);
    return `<tr${cls}><td>${label}</td>${vals.map((v, k) => `<td class="num">${v !== null && v === b && hiMark !== null ? `<b>${show(v, k)}</b>` : show(v, k)}</td>`).join('')}</tr>`; };
  h += sec('Each phase', 'the highest figure of each line in bold; for the power factor, the lowest') + tableCard(`<tr><th></th>${PHN.map((p, k) => `<th class="num">${swl(k)}${p}</th>`).join('')}</tr>` +
    row('Mean current', t.ph.map(P => P.mean), v => `${fA(v, 1)} A`) +
    row('Highest 15-second sample', t.ph.map(P => P.hi), v => `${fA(v)} A <span class="dimtxt hide-s">${fA(v / pln * 100)} %</span>`) +
    row('Highest 15-minute mean', t.ph.map(P => P.d15), v => `${fA(v)} A <span class="dimtxt hide-s">${fA(v / pln * 100)} %</span>`) +
    row(`Minutes above ${L.pln.v} % of the PLN limit`, t.ph.map(P => P.hiN), v => flag(v > 0, String(v))) +
    row('Energy', t.ph.map(P => P.e), (v, k) => `${nf(v)} kWh <span class="dimtxt hide-s">${fA(t.ph[k].share)} %</span>`) +
    row('Mean power', t.ph.map(P => P.p), v => `${fA(v, 1)} kW`) +
    row('Power factor under load', t.ph.map(P => P.pf), v => fA(v, 2), false) +
    row('Lowest 1-minute power', t.ph.map(P => P.pmin), v => flag(v < L.pneg.v, `${fA(v, 1)} kW`), null), '',
    `PLN phase limit ${fA(pln)} A · main breaker ${esc(j.rated_a ?? '–')} A (${limTag(L.rated)} at ${L.rated.v} %)`).replace('<section class="card">', '<section class="card cphase">');

  // Balancing
  h += sec('Balancing the phases', `at the busy hours: the ${Math.round((1 - BUSY_Q) * 100)} % of the hours with the most current`);
  if (!B) h += '<section class="card"><div class="empty">Not enough complete hours in this period.</div></section>';
  else {
    const P3 = [0, 1, 2], top = Math.max(...B.a, ...B.after) * 1.12;
    const bar = (v, cls, k) => `<div class="cbar ${cls}"><span style="width:${(v / top * 100).toFixed(1)}%;${cls === 'now' ? `background:${C[k]}` : `border-color:${C[k]}`}"></span><b>${fA(v)} A</b></div>`;
    const balanced = B.before < 5;
    h += `<section class="card"><div class="cbal"><div class="cbal-t">
      <p>At the busy hours (mostly <b>${esc(B.when)}</b>, ${B.n} hours of the period), ${P3.map(k => `${k === B.hv ? '<b>' : ''}${PHN[k]} ${fA(B.a[k])} A${k === B.hv ? '</b>' : ''}`).join(', ')}: unbalance <b>${fA(B.before)} %</b>,
        the heaviest phase ${fA(B.a[B.hv] - B.M)} A above the mean.</p>
      ${balanced ? '<p>The phases are balanced at the busy hours: nothing to move.</p>' : `<p><b>Moving about ${fA(B.d)} A from ${PHN[B.hv]} to ${PHN[B.lt]}</b> (about ${fA(B.kw, 1)} kW of single-phase load at the busy hours)
        would bring them to ${P3.map(k => `${PHN[k]} ${fA(B.after[k])} A`).join(', ')}: unbalance about <b>${fA(B.afterU)} %</b>, and ${fA(B.d)} A more room on ${PHN[B.hv]} before the PLN limit.</p>`}
      <p class="muted small">An indication, as the capacitor size of the Power factor page. Which circuits to move comes from a survey of the main board: which circuit is on which phase, and when it runs.
        The order of the phases changes over the day: see <a href="#cbyhour" data-cjump>By hour of the day</a>.</p></div>
      <div class="cbal-b">${P3.map(k => `<div class="cph"><span class="cl">${swl(k)}${PHN[k]}</span>${bar(B.a[k], 'now', k)}${balanced ? '' : bar(B.after[k], 'after', k)}</div>`).join('')}
        <div class="legend cleg"><span><i class="cnow"></i>Busy hours now</span>${balanced ? '' : '<span><i class="cafter"></i>After the move</span>'}</div></div></div></section>`;
  }

  h += sec('Current per phase, hour by hour', 'mean of each hour; grey: lowest to highest 15-second sample') + chartCard('ch') +
    sec('Current unbalance, hour by hour', `minutes with ${j.i_floor_a} A or more of mean current`) + chartCard('ch2') +
    `<h2 class="eyebrow sec" id="cbyhour">By hour of the day <span>· mean current of each phase over the period: which phase carries the load, and when</span></h2>` + chartCard('ch3');

  const days = cByDay(H);
  h += sec('Day by day', 'click a day for its currents minute by minute') + tableCard(`<tr><th>Day</th><th class="hide-s">Recorded</th><th>Highest</th>
      <th class="hide-s">Mean L1 · L2 · L3</th><th>Energy share</th><th>Unbalance</th><th class="hide-s">Above ${L.iu.v} %</th><th class="hide-s">Near the limit</th><th class="hide-s">Neutral, est.</th></tr>` +
    Object.keys(days).sort().reverse().map(k => {
      const x = days[k], hk = [0, 1, 2].reduce((a, n) => (x.ph[n].hi ?? -1) > (x.ph[a].hi ?? -1) ? n : a, 0);
      return `<tr><td><a href="#current" data-cday="${k}">${fdate(tp(k + ' 00:00'))}</a>${x.zero ? ' <span class="pill warn">phase without current</span>' : ''}</td>
        <td class="hide-s">${k === today ? 'so far' : pctOf(x.minutes, 1440, 0) + ' %'}</td>
        <td>${flag(x.ph[hk].hi > nearA, `${fA(x.ph[hk].hi)} A`)} <span class="dimtxt">${PHN[hk]}</span></td>
        <td class="hide-s">${x.ph.map(P => fA(P.mean)).join(' · ')} A</td><td>${x.ph.map(P => fA(P.share)).join(' · ')} %</td>
        <td>${flag(x.iuHour > L.iu.v, `${fA(x.iu, 1)} %`)} <span class="dimtxt">hour ${fA(x.iuHour)} %</span></td>
        <td class="hide-s">${flag(x.iuHi > 0, `${x.iuHi} min`)}</td><td class="hide-s">${flag(x.iHi > 0, `${x.iHi} min`)}</td>
        <td class="hide-s">${fA(x.inMax)} A</td></tr>`; }).join(''));

  const ev = j.events.slice().reverse();
  h += sec('Current alarms', `${ev.length ? `${ev.length} line${ev.length === 1 ? '' : 's'}, ` : ''}${limTag(L.iu)}, ${limTag(L.pln)}, ${limTag(L.rated)}, ${limTag(L.pneg)}, ${limTag(L.izero)}; hotel time`);
  h += ev.length ? tableCard(`<tr><th>Time</th><th>Alarm</th><th>State</th><th>Value</th><th class="hide-s">Message</th></tr>${ev.slice(0, 200).map(e =>
      `<tr><td>${esc(e.local_time)}</td><td><span class="mono">${esc(e.id)}</span> ${esc(e.name)} ${sevPill(e.severity)}</td>
        <td>${esc(e.state)}${e.duration_min ? ` <span class="dimtxt">${esc(e.duration_min)} min</span>` : ''}</td>
        <td>${esc(e.value)} ${esc(e.unit)}</td><td class="hide-s wrap">${esc(e.message)}</td></tr>`).join('')}`)
    : '<section class="card"><div class="empty">No current alarm in this period.</div></section>';

  h += '<div id="cday"></div>';
  h += `<h2 class="eyebrow sec" id="cchecks">Measurement checks <span>· is what this page shows right?</span></h2><section class="card"><ul class="alist">${checks.map(([s, ti, tx]) =>
      `<li><span class="ai ${s}">${icon(s === 'good' ? 'check' : s === 'neutral' ? 'info' : 'alert')}</span><div><b>${esc(ti)}</b><small class="wrap">${tx}</small></div>${
        s === 'good' ? '<span class="pill good">fine</span>' : s === 'neutral' ? '<span class="pill neutral">no data</span>' : s === 'crit' ? '<span class="pill crit">wrong</span>' : ti.startsWith('Checked') ? '<span class="pill warn">to do</span>' : '<span class="pill warn">look at it</span>'}</li>`).join('')}</ul></section>`;
  h += `<div class="foot"><span>Unbalance: the largest deviation of a phase from the mean of the three, in % of the mean (as ${esc(L.iu.id)}), counted while the mean is ${j.i_floor_a} A or more.
    15-minute mean: the mean of 15 one-minute means in a row. Energy of a phase: its 1-minute power summed (the meter has no counter per phase).
    Neutral, estimated: the sum of the three currents as vectors, 120° apart, each behind its voltage by the angle of its power factor (lagging taken); it leaves out the harmonics
    (the third harmonic of LED drivers and computers adds up in the neutral), so the real neutral current is higher. PLN phase limit: contracted kVA / 3 / ${esc(PROF.contract_v_ln || 220)} V.</span></div>`;
  box.innerHTML = h;

  const bandOf = (r, s, f) => { const v = [1, 2, 3].map(k => r[`i${k}_${s}`]).filter(x => x !== undefined); return v.length ? f(...v) : null; };
  // room above the PLN line (an invisible line at 112 % of it), so that both labels sit above their lines
  const refs = [...qRefs([{v: +nearA.toFixed(1), label: `${limTag(L.pln)} ${L.pln.v} % of the PLN limit`}, {v: +pln.toFixed(1), label: 'PLN phase limit'}]),
    {v: +(pln * 1.12).toFixed(1), color: 'transparent'}];
  const byT = new Map(H.map(r => [tp(r.t), r]));
  const tipR = k => b => { const r = byT.get(b[0]); return r && r[`i${k}_max`] !== undefined ? ` <span class="dim">(${fA(r[`i${k}_min`])}–${fA(r[`i${k}_max`])})</span>` : ''; };
  lineChart(el('ch'), [...[1, 2, 3].map(k => ({name: 'L' + k, color: C[k - 1], pts: H.map(r => [tp(r.t), r[`i${k}`] ?? null]), extra: tipR(k)})),
      {name: 'Neutral, estimated', color: QUIET, width: 1.4, pts: H.map(r => [tp(r.t), r.in ?? null])}],
    {unit: 'A', axis: 'amperes', yZero: true, refs, bands: [{name: 'Lowest – highest 15-second sample', color: BAND, pts: H.map(r => [tp(r.t), bandOf(r, 'min', Math.min), bandOf(r, 'max', Math.max)])}]});
  lineChart(el('ch2'), [{name: 'Mean of the hour', color: C[0], pts: H.map(r => [tp(r.t), r.iu ?? null])},
      {name: 'Highest minute', color: C[1], width: 1.4, pts: H.map(r => [tp(r.t), r.iu_max ?? null])}],
    {unit: '%', yZero: true, digits: 1, refs: [{v: L.iu.v, label: limName(L.iu, 'current imbalance')}]});
  const T0 = Date.UTC(2000, 0, 1), hh = n => String(n).padStart(2, '0') + ':00';
  const hod = [...Array(24).keys()].map(hr => { const s = cSum(H.filter(r => +r.t.slice(11, 13) === hr)); return {hr, s}; });
  lineChart(el('ch3'), [...[0, 1, 2].map(k => ({name: PHN[k], color: C[k], pts: hod.map(o => [T0 + o.hr * 36e5, o.s.ph[k].mean]),
      extra: b => { const o = hod[Math.round((b[0] - T0) / 36e5)]; return o && o.s.ph[k].p !== null ? ` <span class="dim">${fA(o.s.ph[k].p, 1)} kW</span>` : ''; }}))],
    {unit: 'A', axis: 'amperes', yZero: true, xName: 'Hour of the day (hotel time)', title: ms => { const n = Math.round((ms - T0) / 36e5); return `${hh(n)}–${hh(n + 1)}, mean of the period`; }});
  await cDaySection(j, t);
};

async function cDaySection(j, t) {   // one hotel day, minute by minute (redrawn alone by the day buttons)
  j ??= await cHourly(); t ??= cSum(j.hours);
  const L = j.limits, today = j.now.slice(0, 10), pln = j.pln_a, nearA = pln * L.pln.v / 100;
  cDay ??= range && range.to < today ? range.to : today;
  const box = el('cday');
  if (!box) return;
  const day = cDay, dj = await getJ(`/api/v1/quality/${site}/current/day/${day}`);
  if (el('cday') !== box || day !== cDay) return;   // redrawn (other period, page or day) while this day was loading
  const ci = Object.fromEntries(dj.cols.map((c, i) => [c, i])), R = dj.rows, ms = tp(day + ' 00:00');
  const hiK = [0, 1, 2].reduce((a, k) => (t.ph[k].hi ?? -1) > (t.ph[a].hi ?? -1) ? k : a, 0), hiDay = t.ph[hiK].hiAt ? t.ph[hiK].hiAt.slice(0, 10) : null;
  const zDay = t.zeroAt ? t.zeroAt.slice(0, 10) : null;
  const tools = `<div class="headtools"><div class="seg" role="group" aria-label="Day">${segBtn(`data-cday="${isoDay(ms - 864e5)}"`, false, '◀ ' + fdate(ms - 864e5))}${segBtn('', true, fdate(ms))}${
      segBtn(`data-cday="${isoDay(ms + 864e5)}"`, false, fdate(ms + 864e5) + ' ▶', day >= today)}</div>${dateIn('data-pick="cday"', day, 'Day')}` +
    (hiDay && hiDay !== day ? `<button class="btn small" data-cday="${hiDay}">Highest of the period: ${fdate(tp(hiDay + ' 00:00'))}</button>` : '') +
    (zDay && zDay !== day ? `<button class="btn small" data-cday="${zDay}">Phase without current: ${fdate(tp(zDay + ' 00:00'))}</button>` : '') + '</div>';
  let hi = null, nmax = null, iuS = 0, iuN = 0, near = 0, zero = 0;
  for (const r of R) {
    for (const k of [1, 2, 3]) { const v = r[ci[`i${k}_max`]] ?? r[ci[`i${k}`]]; if (v !== null && (!hi || v > hi.v)) hi = {v, t: r[0], k}; }
    if (r[ci.in] !== null && (!nmax || r[ci.in] > nmax.v)) nmax = {v: r[ci.in], t: r[0]};
    if (r[ci.iu] !== null) { iuS += r[ci.iu]; iuN++; }
    near += [1, 2, 3].some(k => r[ci[`i${k}_max`]] > nearA);
    const i = [1, 2, 3].map(k => r[ci[`i${k}`]]);
    zero += i.some((x, n) => x < L.izero.v && i.filter((_, m) => m !== n).every(y => y >= 10));
  }
  box.innerHTML = `<div class="page-head" style="margin-top:28px"><div><h2 style="font-size:19px;font-weight:800">One day, minute by minute: ${fdate(ms)}</h2>
      <div class="sub">Mean current of each phase per minute, and in grey the lowest to highest 15-second sample of the minute; the estimated neutral. Hover for each phase's range.</div></div>${tools}</div>` +
    tiles([statTile('Highest 15-second sample', hi ? flag(hi.v > nearA, fA(hi.v)) : '–', 'A', hi ? `L${hi.k} at ${hi.t} · ${fA(hi.v / pln * 100)} % of the PLN limit` : ''),
      statTile('Unbalance, mean', iuN ? fA(iuS / iuN, 1) : '–', '%', `minutes with ${j.i_floor_a} A or more · ${near} min near the PLN limit`),
      statTile('Neutral, estimated', nmax ? fA(nmax.v) : '–', 'A', nmax ? `highest minute, at ${nmax.t}` : ''),
      statTile(zero ? 'Phase without current' : 'Minutes recorded', zero ? flag(true, zero) : R.length, zero ? 'minutes' : day === today ? 'so far' : 'of 1440', zero ? `a phase under ${L.izero.v} A while the others carry load · ${limTag(L.izero)}` : '')]) +
    `<div class="mt-16">${chartCard('ch4')}</div>`;
  const at = new Map(R.map(r => [tp(`${day} ${r[0]}`), r]));
  const tipR = k => b => { const r = at.get(b[0]); return r && r[ci[`i${k}_min`]] !== null ? ` <span class="dim">(${fA(r[ci[`i${k}_min`]])}–${fA(r[ci[`i${k}_max`]])})</span>` : ''; };
  const ext = (r, s, f) => { const v = [1, 2, 3].map(k => r[ci[`i${k}_${s}`]] ?? r[ci[`i${k}`]]).filter(x => x !== null); return v.length ? f(...v) : null; };
  lineChart(el('ch4'), [...[1, 2, 3].map(k => ({name: 'L' + k, color: C[k - 1], width: 1.4, pts: R.map(r => [tp(`${day} ${r[0]}`), r[ci['i' + k]]]), extra: tipR(k)})),
      {name: 'Neutral, estimated', color: QUIET, width: 1.2, pts: R.map(r => [tp(`${day} ${r[0]}`), r[ci.in]])}],
    {unit: 'A', axis: 'amperes', yZero: true, gapMs: 3 * 6e4, step: 6e4,
     refs: [...qRefs([{v: +nearA.toFixed(1), label: `${limTag(L.pln)} ${L.pln.v} % of the PLN limit`}, {v: +pln.toFixed(1), label: 'PLN phase limit'}]),
       {v: +(pln * 1.12).toFixed(1), color: 'transparent'}],
     bands: [{name: 'Lowest – highest 15-second sample', color: BAND, pts: R.map(r => [tp(`${day} ${r[0]}`), ext(r, 'min', Math.min), ext(r, 'max', Math.max)])}]});
}
const cDayErr = () => { if (el('cday')) el('cday').innerHTML = '<section class="card"><div class="empty">Could not read that day from the server.</div></section>'; };
document.addEventListener('click', ev => {
  const j = ev.target.closest('a[data-cjump]');
  if (j) { ev.preventDefault(); return document.querySelector(j.getAttribute('href'))?.scrollIntoView({behavior: 'smooth', block: 'start'}); }
  const b = ev.target.closest('[data-cday]');
  if (!b || b.disabled || view !== 'current') return;
  ev.preventDefault();
  cDay = b.dataset.cday;
  cDaySection().then(() => { if (b.tagName === 'A') el('cday')?.scrollIntoView({behavior: 'smooth', block: 'start'}); }).catch(cDayErr);
});
document.addEventListener('change', ev => {
  if (ev.target.dataset?.pick !== 'cday') return;
  const v = ev.target.value;
  setTimeout(() => { if (view !== 'current' || !/^\d{4}-\d{2}-\d{2}$/.test(v) || v > todayH()) return; cDay = v; cDaySection().catch(cDayErr); }, 600);
});

// Live now: one more line on the current card: the unbalance and the estimated neutral of the last snapshot, and the link to this page
function curLive(V, M) {
  const i = [1, 2, 3].map(k => V(`${M}_i${k}`)), p = [1, 2, 3].map(k => V(`${M}_p${k}`)), v = [1, 2, 3].map(k => V(`${M}_v${k}`));
  if (i.some(x => x === null)) return '';
  const m = (i[0] + i[1] + i[2]) / 3, u = m >= 5 ? Math.max(...i.map(x => Math.abs(x - m))) / m * 100 : null;
  let n = null;
  if (p.every(x => x !== null) && v.every(x => x !== null)) {
    let re = 0, im = 0;
    [0, -120, 120].forEach((a, k) => { const pf = i[k] >= 1 && p[k] >= 0.3 ? Math.min(1, p[k] * 1000 / (v[k] * i[k])) : 1, ang = a * Math.PI / 180 - Math.acos(pf);
      re += i[k] * Math.cos(ang); im += i[k] * Math.sin(ang); });
    n = Math.hypot(re, im);
  }
  return `<div class="sub">Unbalance ${u === null ? '–' : u.toFixed(0) + ' %'}${n === null ? '' : ` · neutral about ${n.toFixed(0)} A (estimated)`} · <a href="#current">Current &amp; balance</a></div>`;
}
