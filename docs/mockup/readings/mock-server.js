// ------------------------------------------------------------------ mockup only: the server's side (server/app/manual.py), in the page
// Put into the page by docs/mockup/readings/build.py, after the readings pages of live.html and before the page starts.
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

