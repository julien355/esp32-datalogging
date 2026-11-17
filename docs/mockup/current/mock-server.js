// ------------------------------------------------------------------ current per phase: the server's answers in the mockup (docs/mockup/current/)
// Mockup only. Plays the two requests of server/app/quality.py (current_hourly, current_minutes), with the same fields and rules:
//   GET /api/v1/quality/<site>/current?days=N (or ?from=&to=)   one row per hotel hour
//   GET /api/v1/quality/<site>/current/day/<date>                one row per minute of one hotel day
// from simulated 1-minute records made out of the saved hours of the Arkan mockup: the total power, power factor and voltages of each
// hour stay those of the other pages; only their split between the three phases is simulated. The simulated hotel:
//   - the kitchen on L1 (breakfast, lunch, dinner; dinner busier on Friday and Saturday), the restaurant lights on L1 in the evening;
//   - the laundry on L2 (weekdays 9:00 to 16:00, Saturday morning);
//   - the rooms' air conditioning a little more on L3 (afternoon and night);
//   - the pool pump (starts at 08:00 and 16:30) and the lift on all three phases.
// Two events: Sat 7 Nov 19:38 to 19:44 the kitchen's ovens and dishwasher together on L1 (two 15-second samples above 90 % of the PLN
// phase limit); Thu 5 Nov 14:10 to 14:51 L3 reads under 1 A while L1 and L2 carry their load (its CT shorted during work in the panel).
// The current imbalance of the power quality overview (A10, counted from 25 A of mean current since v0.10.0) is replaced by the one
// of these minutes, so both pages agree.
if (MOCK && FX.quality) (() => {
  const Q = FX.quality, prof = FX.live.profile;
  const PLN = prof.contracted_kva * 1000 / 3 / (prof.contract_v_ln || 220);   // the PLN limiter of one phase: 125 A at Adab
  Q.i_floor_a = 25;   // A10's floor since v0.10.0 (site.json i_imbalance_floor_a)
  const LOADED = 10;  // A40: the two other phases carry this or more
  const LIM = {...Q.limits,
    pln: {id: 'A37', name: 'Phase current near the PLN limit', v: 90, enabled: true, delay: 5},
    rated: {id: 'A29', name: 'Phase current near the rating', v: 90, enabled: true, delay: 5},
    pneg: {id: 'A30', name: 'Negative power on a phase', v: -0.5, enabled: true, delay: 5},
    izero: {id: 'A40', name: 'Phase without current', v: 1, enabled: true, delay: 5}};
  let seed = 20261117;   // the same simulated minutes at every opening
  const R = () => { seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
  const U = (a, b) => a + (b - a) * R();
  const win = (h, a, b, r = 0.5) => Math.max(0, Math.min(1, (h - a) / r + 0.5, (b - h) / r + 0.5));   // 1 from a to b (hours), ramps of r
  const unb = (v, floor) => { const m = (v[0] + v[1] + v[2]) / 3; return m < floor ? null : Math.max(...v.map(x => Math.abs(x - m))) / m * 100; };
  const r1 = (x, d = 2) => x === null || x === undefined ? undefined : +x.toFixed(d);

  // ---- 1. the minutes
  const MIN = [], dayN = {};
  Q.hours.forEach((r, n) => {
    const nx = Q.hours[n + 1] && tp(Q.hours[n + 1].t) - tp(r.t) === 36e5 ? Q.hours[n + 1] : r, t0 = tp(r.t);
    for (let m = 60 - Math.min(60, r.minutes); m < 60; m++) {
      const ms = t0 + m * 6e4, d = new Date(ms), dow = d.getUTCDay(), h = d.getUTCHours() + m / 60, day = isoDay(ms), x = m / 60;
      const t = `${day} ${d.toISOString().slice(11, 16)}`;
      const dn = dayN[day] ??= [U(-.03, .03), U(-.03, .03), U(-.03, .03)];
      const P = ((r.p ?? 25) * (1 - x) + (nx.p ?? 25) * x) * U(0.98, 1.02), pf = (r.pf ?? .9) * (1 - x) + (nx.pf ?? .9) * x;
      const busy = dow === 5 || dow === 6;
      const kitchen = 0.16 * win(h, 6.5, 10) + 0.14 * win(h, 11.5, 14) + (busy ? 0.40 : 0.12) * win(h, 17.5, 22);
      const lights = 0.06 * win(h, 18, 23.5);
      const laundry = dow >= 1 && dow <= 5 ? 0.38 * win(h, 9, 16) : dow === 6 ? 0.22 * win(h, 9, 13) : 0;
      const ac = 0.10 * win(h, 13, 17.5) + 0.08 * (win(h, 21, 24.5) + win(h, -0.5, 7));
      const w = [1 + kitchen + lights + dn[0], 1 + laundry + dn[1], 1.02 + ac + dn[2]].map(y => y * U(0.98, 1.02)), sw = w[0] + w[1] + w[2];
      const p = w.map(y => P * y / sw);
      const v = [1, 2, 3].map(k => (r[`v${k}`] ?? 230) + U(-0.4, 0.4));
      const pfk = [Math.min(0.99, pf + 0.045), Math.min(0.99, pf + 0.01), Math.max(0.6, pf - 0.055)];   // kitchen heaters; compressors
      if (t >= '2026-11-07 19:38' && t <= '2026-11-07 19:44') p[0] += 6.5 + U(-.3, .3);
      const i = p.map((pk, k) => pk * 1000 / (v[k] * pfk[k]));
      const lo = i.map(y => y * U(0.96, 0.99));
      let hi = i.map(y => y * U(1.01, 1.05));
      if (t.endsWith(' 08:00') || t.endsWith(' 16:30')) hi = hi.map(y => y + U(28, 36));                  // the pool pump starts
      else if (h >= 7 && h < 23 && R() < 0.08) { const s = U(10, 16); hi = hi.map(y => y + s); }          // the lift
      if (kitchen > 0.1 && R() < 0.1) hi[0] += U(6, 12);
      if (t === '2026-11-07 19:41') hi[0] = 114.2;
      if (t === '2026-11-07 19:42') hi[0] = 113.6;
      if (t >= '2026-11-05 14:10' && t <= '2026-11-05 14:51') {
        i[2] = U(0.2, 0.4); lo[2] = i[2] * 0.9; hi[2] = i[2] * 1.1; p[2] = i[2] * v[2] * pfk[2] / 1000;
      }
      const pt = (p[0] + p[1] + p[2]) * U(0.998, 1.004);                                     // the meter's total kW
      const st = (v[0] * i[0] + v[1] * i[1] + v[2] * i[2]) / 1000 * U(1.0, 1.02);            // the meter's total kVA
      MIN.push({ms, t, i, lo, hi, p, v, pt, st});
    }
  });

  // ---- 2. per minute: the power factor of each phase, the imbalance, the 15-minute means; then the hours
  const HRS = new Map(), ring = [[], [], []];
  let prev = null;
  const near = PLN * LIM.pln.v / 100;
  for (const m of MIN) {
    if (prev !== null && m.ms - prev > 6e4) ring.forEach(q => { q.length = 0; });
    prev = m.ms;
    m.pf = m.p.map((pk, k) => pk >= 0.3 && m.i[k] >= 1 ? pk * 1000 / (m.v[k] * m.i[k]) : null);
    m.iu = unb(m.i, Q.i_floor_a);
    m.d15 = m.i.map((y, k) => { ring[k].push(y); if (ring[k].length > 15) ring[k].shift(); return ring[k].length === 15 ? ring[k].reduce((a, b) => a + b) / 15 : null; });
    const lowK = m.i.indexOf(Math.min(...m.i));
    m.zero = m.i[lowK] < LIM.izero.v && m.i.every((y, k) => k === lowK || y >= LOADED) ? lowK : undefined;
    const key = m.t.slice(0, 13) + ':00';
    let o = HRS.get(key);
    if (!o) HRS.set(key, o = {t: key, minutes: 0, n: 0, i: [0, 0, 0], lo: [null, null, null], hi: [null, null, null], d15: [null, null, null],
      p: [0, 0, 0], pmin: [null, null, null], pfs: [0, 0, 0], pfn: [0, 0, 0], iu: 0, iun: 0, iumax: null, iuhi: 0,
      ihi: [0, 0, 0], izero: 0, izeroPh: '', izeroAt: '', ps: 0, ss: 0, ld: 0});
    o.minutes++; o.n++;
    for (let k = 0; k < 3; k++) {
      o.i[k] += m.i[k]; o.p[k] += m.p[k];
      o.lo[k] = o.lo[k] === null ? m.lo[k] : Math.min(o.lo[k], m.lo[k]);
      o.hi[k] = o.hi[k] === null ? m.hi[k] : Math.max(o.hi[k], m.hi[k]);
      if (m.d15[k] !== null) o.d15[k] = o.d15[k] === null ? m.d15[k] : Math.max(o.d15[k], m.d15[k]);
      o.pmin[k] = o.pmin[k] === null ? m.p[k] : Math.min(o.pmin[k], m.p[k]);
      if (m.pf[k] !== null) { o.pfs[k] += m.pf[k]; o.pfn[k]++; }
      o.ihi[k] += m.hi[k] > near;
    }
    if (m.iu !== null) { o.iu += m.iu; o.iun++; o.iumax = Math.max(o.iumax ?? 0, m.iu); o.iuhi += m.iu > LIM.iu.v; }
    if (m.zero !== undefined) { o.izero++; o.izeroPh = 'L' + (m.zero + 1); o.izeroAt ||= m.t.slice(11); }
    if (m.pt >= 1) { o.ps += (m.p[0] + m.p[1] + m.p[2]) / m.pt; o.ss += (m.v[0] * m.i[0] + m.v[1] * m.i[1] + m.v[2] * m.i[2]) / 1000 / m.st; o.ld++; }
  }
  const HOURS = [...HRS.values()].map(o => {
    const r = {t: o.t, minutes: o.minutes, n: o.n};
    for (let k = 0; k < 3; k++) {
      const s = k + 1;
      Object.assign(r, {[`i${s}`]: r1(o.i[k] / o.n), [`i${s}_min`]: r1(o.lo[k]), [`i${s}_max`]: r1(o.hi[k]), [`i${s}_d15`]: r1(o.d15[k]),
        [`p${s}`]: r1(o.p[k] / o.n, 3), [`e${s}`]: r1(o.p[k] / 60, 3), [`p${s}_min`]: r1(o.pmin[k], 3),
        [`pf${s}`]: o.pfn[k] ? r1(o.pfs[k] / o.pfn[k], 3) : undefined, [`i${s}_hi`]: o.ihi[k]});
    }
    Object.assign(r, {iu: o.iun ? r1(o.iu / o.iun) : undefined, iu_max: r1(o.iumax), iu_n: o.iun, iu_hi: o.iuhi,
      i_zero: o.izero, i_zero_ph: o.izeroPh || undefined, i_zero_at: o.izeroAt || undefined,
      psum: o.ld ? r1(o.ps / o.ld * 100, 1) : undefined, sratio: o.ld ? r1(o.ss / o.ld * 100, 1) : undefined});
    return r;
  });
  // the overview's current imbalance (A10) from the same minutes
  for (const r of Q.hours) { const c = HRS.get(r.t); if (c && c.iun) { r.iu = r1(c.iu / c.iun); r.iu_max = r1(c.iumax); } }

  // ---- 3. the alarm lines these minutes give (A10, A40), as server/app/alarms.py writes them
  const EVENTS = [];
  const off = (prof.utc_offset_h ?? 8) * 36e5, utc = t => new Date(tp(t) - off).toISOString().slice(0, 19) + 'Z';
  const line = (a, state, t, value, unit, dur, message) => EVENTS.push({ts_utc: utc(t), local_time: t, id: a.id, name: a.name,
    severity: 'warning', state, value: String(value), unit, duration_min: dur === null ? '' : String(dur), message});
  function replay(a, test, clear, delay, unit, valueOf, text, low = false) {
    let run = 0, open = null, worst = null, prevMs = null;
    MIN.forEach((m, n) => {
      if (prevMs !== null && m.ms - prevMs > 5 * 6e4) run = 0;   // a gap of more than 5 minutes restarts the delay
      prevMs = m.ms;
      const v = valueOf(m);
      if (open) {
        worst = v === null ? worst : low ? Math.min(worst, v) : Math.max(worst, v);
        if (clear(m)) { const dur = Math.round((m.ms - open.ms) / 6e4);
          line(a, 'clear', m.t, r1(worst, 1), unit, dur, `cleared after ${dur} min; worst value ${r1(worst, 1)}`); open = null; }
      } else if (test(m)) {
        if (++run >= delay) { const s = MIN[n - delay + 1]; open = s; worst = v; line(a, 'start', s.t, r1(v, 1), unit, null, text); run = 0; }
      } else run = 0;
    });
  }
  replay(LIM.iu, m => m.iu !== null && m.iu > LIM.iu.v, m => m.iu !== null && m.iu < 15, 15, '%', m => m.iu,
    'largest phase current deviation from the mean above 20 % for 15 min while the mean current is 25 A or more');
  replay(LIM.izero, m => m.zero !== undefined, m => m.zero === undefined, 5, 'A', m => m.zero === undefined ? null : m.i[m.zero],
    'a phase current below 1 A while the two others carry 10 A or more for 5 min', true);
  EVENTS.sort((a, b) => (a.ts_utc < b.ts_utc ? -1 : a.ts_utc > b.ts_utc ? 1 : a.state === 'start' ? -1 : 1));

  // ---- 4. the answers
  const ANS = (body, status = 200) => Promise.resolve({ok: status < 400, status, json: async () => JSON.parse(JSON.stringify(body))});
  const COLS = ['t', 'i1', 'i1_min', 'i1_max', 'i2', 'i2_min', 'i2_max', 'i3', 'i3_min', 'i3_max', 'p1', 'p2', 'p3', 'iu'];
  const today = FX.history.now.slice(0, 10), base = window.fetch;
  window.fetch = (url, opt = {}) => {
    const u = String(url);
    let m = u.match(/^\/api\/v1\/quality\/[a-z0-9-]+\/current\/day\/(\d{4}-\d{2}-\d{2})$/);
    if (m) return ANS({site: FX.site, device: 'LOG-0001', meter: 'EM01', day: m[1], cols: COLS,
      rows: MIN.filter(x => x.t.startsWith(m[1])).map(x => [x.t.slice(11), ...x.i.flatMap((y, k) => [r1(y), r1(x.lo[k]), r1(x.hi[k])]),
        ...x.p.map(y => r1(y, 3)), x.iu === null ? null : r1(x.iu)])});
    if (/^\/api\/v1\/quality\/[a-z0-9-]+\/current\?/.test(u)) {
      const q = new URLSearchParams(u.split('?')[1]);
      const from = q.get('from') || addD(today, 1 - (+q.get('days') || 7)), to = q.get('to') || today;
      const ok = t => t.slice(0, 10) >= from && t.slice(0, 10) <= to;
      return ANS({site: FX.site, device: 'LOG-0001', meter: 'EM01', utc_offset_h: prof.utc_offset_h ?? 8, from: from + ' 00:00', to,
        now: FX.history.now, first_day: HOURS[0].t.slice(0, 10), nominal_v: prof.nominal_v || 230, pln_a: +PLN.toFixed(1), rated_a: prof.rated_a,
        i_floor_a: Q.i_floor_a, i_loaded_a: LOADED, pf_load_kw: 0.3, limits: LIM, hours: HOURS.filter(r => ok(r.t)), events: EVENTS.filter(e => ok(e.local_time))});
    }
    return base(url, opt);
  };
})();
