/* aero-audit app: hash router, shared store, pages. Add a page: pages.name = {title, render(el), tick(app, state)}. */
(function () {
  const API = '/api/v1';
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const fmtTs = t => t ? new Date(t * 1000).toISOString().replace('T', ' ').substr(0, 19) + 'Z' : '-';
  const ago = t => t ? Math.round((Date.now() / 1000 - t) / 60) + ' min ago' : '-';
  /* Every request carries X-Aero-Token: the per-process CSRF token the server hands out on /app (loopback mode),
     or the shared access token the operator typed (remote mode). A custom header is what forces browsers to
     preflight cross-site calls, which this server never answers. */
  let TOKEN = null; try { TOKEN = sessionStorage.getItem('aeroToken'); } catch (e) { /* storage unavailable */ }
  const headers = () => { const h = {}; if (TOKEN) h['X-Aero-Token'] = TOKEN; return h; };
  async function api(path, method = 'GET', body, retry = true) {
    const h = headers(); if (body) h['Content-Type'] = 'application/json';
    const r = await fetch(API + path, {method, headers: h, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 401 && retry) { const t = window.prompt('This aero-audit instance requires an access token (printed in the terminal where it was started):'); if (t) { TOKEN = t.trim(); try { sessionStorage.setItem('aeroToken', TOKEN); } catch (e) { /* ignore */ } return api(path, method, body, false); } }
    const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j;
  }
  /* Audible alerts: off, tones (Web Audio, no files), or voice (speech synthesis). Only NEW high/critical findings sound. */
  let sound = 'off'; try { sound = localStorage.getItem('aeroSound') || 'off'; } catch (e) { /* ignore */ }
  let audioCtx = null, lastEventId = null, seenEvents = false;
  function beep(freq, dur, when = 0, gain = 0.07) { try { audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)(); const o = audioCtx.createOscillator(), g = audioCtx.createGain(); o.type = 'square'; o.frequency.value = freq; g.gain.value = gain; o.connect(g); g.connect(audioCtx.destination); const t = audioCtx.currentTime + when; o.start(t); o.stop(t + dur); } catch (e) { /* no audio */ } }
  function say(text) { try { if (!window.speechSynthesis) return; const u = new SpeechSynthesisUtterance(text); u.rate = 1.05; u.pitch = 0.9; window.speechSynthesis.cancel(); window.speechSynthesis.speak(u); } catch (e) { /* no speech */ } }
  function alertSounds(s) {
    const ev = s && s.events ? s.events : []; if (!ev.length) { if (!s) seenEvents = false; return; }
    if (!seenEvents) { seenEvents = true; lastEventId = ev[0].id; return; }
    const fresh = []; for (const f of ev) { if (f.id === lastEventId) break; fresh.push(f); } lastEventId = ev[0].id;
    if (sound === 'off' || !fresh.length) return;
    const worst = fresh.find(f => f.severity === 'critical') || fresh.find(f => f.severity === 'high'); if (!worst) return;
    if (worst.severity === 'critical') { beep(880, .12); beep(880, .12, .18); beep(1175, .28, .36); } else beep(660, .2);
    if (sound === 'voice') say(`${worst.severity}. ${worst.rule.replace('-', ' ')}. ${worst.callsign || worst.icao24 || 'unknown aircraft'}. ${worst.title}`);
  }
  function setSound(level, announce = true) { sound = ['off', 'tones', 'voice'].includes(level) ? level : 'off'; try { localStorage.setItem('aeroSound', sound); } catch (e) { /* ignore */ }
    const b = document.getElementById('btnSound'); if (b) { b.textContent = {off: '🔇 SND OFF', tones: '🔔 SND TONES', voice: '🗣 SND VOICE'}[sound]; b.classList.toggle('on', sound !== 'off'); }
    if (announce && sound !== 'off') beep(660, .08); if (announce && sound === 'voice') say('Voice alerts on'); }
  const store = {app: null, state: null, page: null, el: null, timer: null, query: {}};
  function toast(msg, ms = 3500) { const t = document.getElementById('toast'); t.textContent = msg; t.hidden = false; clearTimeout(t._h); t._h = setTimeout(() => t.hidden = true, ms); }
  function md(text) { // minimal markdown: headings, fences, tables, lists, paragraphs, inline code/bold/links
    const lines = text.split('\n'); let out = [], i = 0, inList = null;
    const inline = s => esc(s).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
    const closeList = () => { if (inList) { out.push(`</${inList}>`); inList = null; } };
    while (i < lines.length) { const l = lines[i];
      if (l.startsWith('```')) { closeList(); const buf = []; i++; while (i < lines.length && !lines[i].startsWith('```')) buf.push(lines[i++]); out.push('<pre>' + esc(buf.join('\n')) + '</pre>'); i++; continue; }
      if (l.startsWith('|')) { closeList(); const rows = []; while (i < lines.length && lines[i].startsWith('|')) rows.push(lines[i++]); const cells = r => r.split('|').slice(1, -1).map(c => c.trim());
        const body = rows.filter(r => !/^\|[\s\-:|]+\|$/.test(r)); out.push('<table>' + body.map((r, k) => '<tr>' + cells(r).map(c => `<${k ? 'td' : 'th'}>${inline(c)}</${k ? 'td' : 'th'}>`).join('') + '</tr>').join('') + '</table>'); continue; }
      const h = l.match(/^(#{1,4})\s+(.*)/); if (h) { closeList(); out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); i++; continue; }
      const li = l.match(/^\s*([-*]|\d+\.)\s+(.*)/); if (li) { const kind = /\d/.test(li[1]) ? 'ol' : 'ul'; if (inList !== kind) { closeList(); out.push(`<${kind}>`); inList = kind; } out.push(`<li>${inline(li[2])}</li>`); i++; continue; }
      if (!l.trim()) { closeList(); i++; continue; }
      closeList(); const buf = [l]; i++; while (i < lines.length && lines[i].trim() && !/^(#|\||```|\s*[-*]\s|\s*\d+\.\s)/.test(lines[i])) buf.push(lines[i++]); out.push(`<p>${inline(buf.join(' '))}</p>`); }
    closeList(); return out.join('\n');
  }
  const sevPill = s => s ? `<span class="sev ${s}">${s}</span>` : '';
  const n0 = (v, d = 0) => (v === null || v === undefined || v === '' || isNaN(v)) ? '' : Number(v).toFixed(d);
  const phaseCell = ph => ph ? `<span class="phase-${ph}">${ph}</span>` : '';
  const faaBadge = f => `<span class="badge ${f.kind === 'ground stop' ? 'gs' : (f.kind === 'ground delay program' ? 'gd' : 'cl')}" title="${esc(f.reason || '')}">${esc(f.kind)}${f.avg ? ' ' + esc(f.avg) : ''}${f.min ? ' ' + esc(f.min) : ''}</span>`;
  /* sortable grid: cols = [{k, label, num?, fmt?}] ; rows = objects ; onRow(row) */
  function grid(el, cols, rows, opts = {}) {
    let sortK = opts.sort || cols[0].k, asc = !!opts.asc;
    const draw = () => { const r = [...rows].sort((a, b) => { const x = a[sortK], y = b[sortK]; if (x == null && y == null) return 0; if (x == null) return 1; if (y == null) return -1; return (typeof x === 'number' ? x - y : String(x).localeCompare(String(y))) * (asc ? 1 : -1); });
      el.innerHTML = `<div class="tablewrap"><table><thead><tr>${cols.map(c => `<th data-k="${c.k}" class="${c.k === sortK ? 'sorted' + (asc ? ' asc' : '') : ''}">${c.label}</th>`).join('')}</tr></thead><tbody>${r.map((row, i) => `<tr class="click" data-i="${i}">${cols.map(c => `<td class="${c.num ? 'num' : ''} ${c.cls ? c.cls(row) : ''}">${c.fmt ? c.fmt(row) : esc(row[c.k] ?? '')}</td>`).join('')}</tr>`).join('') || `<tr><td colspan="${cols.length}" class="note">nothing matches</td></tr>`}</tbody></table></div>`;
      el.querySelector('thead').onclick = e => { const th = e.target.closest('th'); if (!th) return; if (sortK === th.dataset.k) asc = !asc; else { sortK = th.dataset.k; asc = false; } draw(); };
      el.querySelector('tbody').onclick = e => { const tr = e.target.closest('tr[data-i]'); if (tr && opts.onRow) opts.onRow(r[+tr.dataset.i]); };
    }; draw();
  }
  const sel = (id, label, options, cur, all = 'all') => `<label>${label}</label><select id="${id}"><option value="">${all}</option>${options.map(o => Array.isArray(o) ? `<option value="${esc(o[0])}" ${cur === o[0] ? 'selected' : ''}>${esc(o[1])}</option>` : `<option ${cur === o ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
  const qs = o => Object.entries(o).filter(([, v]) => v).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');
  const inactive = (el, what) => { el.innerHTML = `<h1>${what}</h1><div class="empty">No source running. <a href="#/">Choose a source</a> to populate this view.</div>`; };
  const findingRow = f => `<tr class="click s-${f.severity}" data-id="${f.id}"><td>${sevPill(f.severity)}</td><td>${f.rule}</td><td>${esc(f.callsign || '')} <span class="note">${esc(f.operator_code || '')}${f.phase ? ' · ' + f.phase : ''}${f.airport ? ' · ' + f.airport : ''}</span><br><span class="note">${f.icao24 || ''}${f.injected ? ' · <span style="color:#ff5cf0">injected</span>' : ''}</span></td><td>${fmtTs(f.ts)}</td><td>${f.risk}</td><td>${f.occurrences}</td><td>${esc(f.title)}</td></tr>`;
  function jobCard(j) { const pct = j.progress != null ? Math.round(j.progress * 100) : (j.status === 'done' ? 100 : 0); const res = j.result ? Object.entries(j.result).filter(([k]) => !['log'].includes(k)).slice(0, 6).map(([k, v]) => `${k}: ${typeof v === 'object' ? esc(JSON.stringify(v)).slice(0, 80) : esc(v)}`).join(' · ') : '';
    return `<div class="job"><div class="row"><b>${j.type}</b><span class="note">${j.status}${j.error ? ' · <span class="bad">' + esc(j.error) + '</span>' : ''}</span><span class="grow"></span>${j.status === 'running' ? `<button class="small" data-act="cancelJob" data-arg="${j.id}">cancel</button>` : ''}<button class="small ghost" data-act="toggleLog" data-arg="${j.id}">log</button></div>
<div class="bar"><i style="width:${pct}%"></i></div><div class="note">${esc(res)}</div><pre id="log-${j.id}" hidden>${esc((j.log || []).join('\n'))}</pre></div>`; }

  const pages = {
    home: { title: 'Home', async render(el) {
      const [regs, recs] = await Promise.all([api('/regions'), api('/recordings')]); const a = store.app; const src = a.source;
      const civil = recs.filter(r => !r.special); const byKind = k => regs.filter(r => r.kind === k);
      const opt = r => `<option value="${r.key}" data-int="${r.interval}" data-prov="${r.providers.join(',')}">${esc(r.name)}${r.kind === 'group' ? '' : ' (' + r.key + ')'}</option>`;
      const groups = [['🇺🇸 Whole country', [...byKind('group').filter(r => r.key === 'usa-hubs'), ...byKind('box').filter(r => r.key === 'conus')]], ['🌎 Continent / world', [...byKind('box').filter(r => r.key !== 'conus'), ...byKind('group').filter(r => r.key !== 'usa-hubs')]], ['🇺🇸 US hubs', byKind('us')], ['🌍 International hubs', byKind('world')], ['📡 Global feeds', byKind('global')]];
      el.innerHTML = `<div class="hero"><div><h1>Watch the sky, audit every message</h1><p>aero-audit follows real aircraft, checks each position report against physics, integrity and safety rules, and tells you what to look at first.</p>
<div class="row"><button class="primary big" id="qtour" ${civil.length ? '' : 'disabled'}>🎬 Run the demo tour</button><button class="big" id="qusa">🇺🇸 Show me America live</button><button class="big" id="qreplay" ${civil.length ? '' : 'disabled'}>▶ Replay the newest recording</button>${src.active ? '<a class="btn big" href="#/live">◎ Back to the live picture</a>' : ''}</div>
<div class="note">The demo tour replays the bundled sample (15 US hubs, 3,900 real aircraft, works offline) and injects eight attack scenarios on a timeline; turn on <b>SND</b> in the header to hear alerts.</div>
<div class="note">America live uses OpenSky over the contiguous states (about 5,000 aircraft per poll, one poll a minute; anonymous access allows ~100 national polls a day, add OpenSky credentials in .env for more).</div></div></div>
${src.active ? `<div class="card accent-green" style="margin:14px 0"><h2>Running: ${esc(src.label)}</h2><p>${src.tracked} aircraft in the last poll · ${src.findings} findings · ${src.batches} polls · last poll ${src.last_ingest_age_s ?? '-'} s ago${src.errors.length ? ' · <span class="bad">' + esc(src.errors.at(-1)) + '</span>' : ''}</p><div class="row"><a class="btn primary" href="#/live">Open the live picture</a><button id="hstop">Stop</button></div></div>` :
`<div class="steps"><div class="step s1"><b>1 · Choose a source</b>Replay a recording on disk, or go live on a region, a whole country, or a continent.</div><div class="step s2"><b>2 · Watch the live picture</b>Aircraft coloured by their worst finding, altitude, speed or trust; click any for details and playbook steps.</div><div class="step s3"><b>3 · Try an injection</b>Teleport, hijack code, ghost: see detection, escalation and trust erosion in seconds.</div></div>`}
<div class="cards"><div class="card accent-blue"><h2>▶ Replay a recording</h2><p>Deterministic, works offline. Loops when it reaches the end.</p>
<div class="row"><select id="rsel" style="max-width:440px">${civil.map(r => `<option value="${esc(r.path)}">${r.sample ? '★ bundled sample · ' : ''}${esc(r.file)} · ${r.provider} ${r.regions.join('+')} · ${r.polls} polls · ${r.aircraft} aircraft · ${r.span_min} min</option>`).join('')}</select></div>
<div class="row"><label>speed <b id="spv">8</b>×</label><input type="range" id="rspeed" min="1" max="40" value="8"><label><input type="checkbox" id="rdemo" ${a.settings.demo ? 'checked' : ''}> demo controls</label></div>
<div class="row"><button class="primary" id="rstart" ${civil.length ? '' : 'disabled'}>Start replay</button>${civil.length ? '' : '<span class="note">no recordings yet: capture one on the Data page or go live</span>'}</div></div>
<div class="card accent-green"><h2>● Go live</h2><p>Polls a public feed, records everything for later audit, refreshes weather every 10 minutes.</p>
<div class="row"><label>feed</label><select id="lprov"><option value="opensky">OpenSky (whole-country boxes, no integrity fields)</option><option value="adsblol">adsb.lol (integrity fields, hubs up to 250 nm)</option></select></div>
<div class="row"><label>where</label><select id="lreg" style="max-width:420px">${groups.map(([g, rs]) => `<optgroup label="${g}">${rs.map(opt).join('')}</optgroup>`).join('')}</select></div>
<div class="row"><label>radius nm</label><input type="number" id="lrad" value="250" min="20" max="250" style="width:80px"><label>poll every</label><input type="number" id="lint" value="60" min="8" max="600" style="width:70px"><label>s</label><label><input type="checkbox" id="ldemo" ${a.settings.demo ? 'checked' : ''}> demo controls</label></div>
<div class="row"><button class="primary" id="lstart">Go live</button><span class="note" id="lhint"></span></div></div></div>
<h2>On this machine</h2><div class="tiles"><div class="tile c-blue"><b>${a.recordings}</b><span>recordings</span></div><div class="tile c-teal"><b>${a.reports}</b><span>reports</span></div><div class="tile c-violet"><b>${a.model ? (a.model.rows / 1000).toFixed(0) + 'k' : '—'}</b><span>model rows</span></div><div class="tile c-green"><b>${a.model ? (a.model.holdout_flag_rate * 100).toFixed(2) + '%' : '—'}</b><span>holdout flag rate</span></div><div class="tile c-amber"><b>${a.model && a.model.evaluation ? Math.round(Object.values(a.model.evaluation.recall).slice(0, 6).reduce((x, y) => x + y, 0) / 6 * 100) + '%' : '—'}</b><span>mean recall (6 attacks)</span></div><div class="tile c-grey"><b>${a.jobs_running}</b><span>jobs running</span></div></div>
<p class="note">Manage recordings, capture new data, train and evaluate on the <a href="#/data">Data &amp; model</a> page. Thresholds and demo mode are in <a href="#/settings">Settings</a>.</p>`;
      const regSel = el.querySelector('#lreg'), provSel = el.querySelector('#lprov'), hint = el.querySelector('#lhint');
      const syncRegion = () => { const prov = provSel.value; [...regSel.options].forEach(o => { o.disabled = !o.dataset.prov.split(',').includes(prov); });
        if (regSel.selectedOptions[0]?.disabled || !regSel.value) regSel.value = prov === 'opensky' ? 'conus' : 'usa-hubs'; syncInterval(); };
      const syncInterval = () => { const o = regSel.selectedOptions[0]; if (!o) return; el.querySelector('#lint').value = o.dataset.int; const r = regs.find(x => x.key === o.value);
        hint.textContent = r.kind === 'group' ? `${r.members.length} regions polled in turn, each revisited every ~${r.members.length * r.interval} s` : r.kind === 'box' ? 'one big box per poll (OpenSky charges 4 credits per national poll)' : r.kind === 'global' ? 'worldwide feed, adsb.lol only' : 'single region; one live poller per machine'; };
      provSel.onchange = syncRegion; regSel.onchange = syncInterval; syncRegion();
      el.querySelector('#rspeed').oninput = e => el.querySelector('#spv').textContent = e.target.value;
      el.querySelector('#rstart').onclick = () => App.startSource({mode: 'replay', recording: el.querySelector('#rsel').value, speed: +el.querySelector('#rspeed').value, demo: el.querySelector('#rdemo').checked});
      el.querySelector('#lstart').onclick = () => App.startSource({mode: 'live', provider: provSel.value, region: regSel.value, radius: +el.querySelector('#lrad').value, interval: +el.querySelector('#lint').value, demo: el.querySelector('#ldemo').checked});
      el.querySelector('#qusa').onclick = () => App.startSource({mode: 'live', provider: 'opensky', region: 'conus', interval: 60, demo: a.settings.demo});
      el.querySelector('#qreplay').onclick = () => { if (civil.length) App.startSource({mode: 'replay', recording: civil[0].path, speed: 8, demo: a.settings.demo}); };
      el.querySelector('#qtour').onclick = async () => { const rec = civil.find(r => r.sample) || civil[0]; if (!rec) return; await App.startSource({mode: 'replay', recording: rec.path, speed: 10, demo: true}); await App.tour('start'); };
      const hs = el.querySelector('#hstop'); if (hs) hs.onclick = App.stopSource;
    } },
    flights: { title: 'Flights', async render(el) {
      if (!store.app.source.active) return inactive(el, 'Flights');
      const q = store.query; const d = await api('/flights?' + qs({...q, limit: 1500})); const f = d.facets;
      el.innerHTML = `<h1>Flights <span class="note">${d.total} in the current picture · poll ${fmtTs(d.batch_ts)} · ${esc(d.provider)}</span></h1>
<div class="filters">${sel('fop', 'operator', f.operators || [], q.operator)}${sel('fcat', 'op category', f.categories || [], q.category)}${sel('ftc', 'type class', f.type_cats || [], q.type_cat)}${sel('fph', 'phase', f.phases || [], q.phase)}${sel('fap', 'airport', f.airports || [], q.airport)}${sel('falt', 'altitude', [['ground', 'on ground'], ['low', '< 10,000 ft'], ['mid', '10-25,000'], ['high', '25,000+']], q.altband)}${sel('fsev', 'finding', f.severities || [], q.severity)}${sel('fsrc', 'source', f.sources || [], q.source)}<input type="text" id="fq" placeholder="callsign / icao / reg / type" value="${esc(q.q || '')}" style="width:190px"><button class="primary" id="fgo">Apply</button><button class="ghost" id="fclr">Clear</button><span class="grow"></span><a class="btn" href="${API}/flights.csv?${qs(q)}" download>CSV</a></div>
<div class="split"><div id="fgrid"></div><div class="detail" id="fdet"><span class="note">click a flight for its record, findings and playbooks</span></div></div>`;
      const cols = [{k: 'callsign', label: 'Callsign', fmt: r => `<b>${esc(r.callsign || '')}</b><br><span class="note">${r.icao24}</span>`}, {k: 'operator', label: 'Operator', fmt: r => esc(r.operator || '')}, {k: 'type', label: 'Type', fmt: r => `${esc(r.type || '')} <span class="note">${esc(r.type_cat || '')}</span>`},
        {k: 'phase', label: 'Phase', fmt: r => phaseCell(r.phase)}, {k: 'airport', label: 'Airport', fmt: r => r.airport ? `${r.airport} <span class="note">${n0(r.airport_nm, 0)} nm</span>` : ''}, {k: 'alt', label: 'Alt ft', num: true, fmt: r => n0(r.alt)}, {k: 'gs', label: 'GS kt', num: true, fmt: r => n0(r.gs)}, {k: 'track', label: 'Trk', num: true, fmt: r => n0(r.track)}, {k: 'vrate', label: 'V/S', num: true, fmt: r => n0(r.vrate), cls: r => (r.vrate || 0) > 300 ? 'pos' : ((r.vrate || 0) < -300 ? 'neg' : '')},
        {k: 'squawk', label: 'Sqk', cls: r => ['7500', '7600', '7700'].includes(r.squawk) ? 'neg' : ''}, {k: 'src', label: 'Src'}, {k: 'trust', label: 'Trust', num: true, cls: r => r.trust < .5 ? 'neg' : 'pos'}, {k: 'sev', label: 'Worst', fmt: r => sevPill(r.sev)}, {k: 'age', label: 'Age s', num: true}];
      grid(el.querySelector('#fgrid'), cols, d.items, {sort: q.sort || 'alt', onRow: r => showFlight(el.querySelector('#fdet'), r.icao24)});
      const go = () => { location.hash = '#/flights?' + qs({operator: el.querySelector('#fop').value, category: el.querySelector('#fcat').value, type_cat: el.querySelector('#ftc').value, phase: el.querySelector('#fph').value, airport: el.querySelector('#fap').value, altband: el.querySelector('#falt').value, severity: el.querySelector('#fsev').value, source: el.querySelector('#fsrc').value, q: el.querySelector('#fq').value}); };
      el.querySelector('#fgo').onclick = go; el.querySelector('#fclr').onclick = () => location.hash = '#/flights'; el.querySelector('#fq').onkeydown = e => { if (e.key === 'Enter') go(); };
      if (q.icao) showFlight(el.querySelector('#fdet'), q.icao);
    }, tick(a, s) { if (a.source.active && store.el) { const t = store.el.querySelector('h1 .note'); if (t && s) t.textContent = `${s.kpis.tracked} in the current picture · poll ${fmtTs(s.batch_ts)} · ${s.provider}`; } } },
    airports: { title: 'Airports', async render(el) {
      const q = store.query; const d = await api('/airports?' + qs({country: q.country})); const active = d.active;
      const withTraffic = d.items.filter(r => r.nearby > 0).length; const faa = d.items.filter(r => r.faa && r.faa.length);
      el.innerHTML = `<h1>Airports <span class="note">${d.items.length} known · ${withTraffic} with traffic now · FAA status ${d.faa_updated ? 'updated ' + esc(d.faa_updated) : 'not loaded (live mode fetches it every 5 min)'}</span></h1>
<div class="filters">${sel('acty', 'country', ['US', 'CA', 'MX', 'PR', 'BS', 'JM', 'PA', 'CU', 'DO', 'GT', 'CR', 'SX'], q.country)}<label><input type="checkbox" id="atraf" ${q.traffic === '0' ? '' : 'checked'}> only with traffic</label><button class="primary" id="ago">Apply</button><span class="grow"></span><button id="afaa" class="ghost">Refresh FAA status</button></div>
${faa.length ? `<div class="card accent-amber" style="margin-bottom:8px"><b class="amb">FAA programmes in effect:</b> ${faa.map(r => `<b>${r.iata}</b> ${r.faa.map(faaBadge).join(' ')}`).join(' · ')}</div>` : ''}
<div class="split"><div id="agrid"></div><div class="detail" id="adet"><span class="note">click an airport for its traffic, weather and status</span></div></div>`;
      const rows = (q.traffic === '0' || !active) ? d.items : d.items.filter(r => r.nearby > 0);
      const cols = [{k: 'iata', label: 'IATA', fmt: r => `<b>${r.iata}</b><br><span class="note">${r.icao}</span>`}, {k: 'name', label: 'Airport', fmt: r => `${esc(r.name)}<br><span class="note">${esc(r.city)}, ${r.country} · ${r.elev_ft} ft</span>`}, {k: 'nearby', label: 'Nearby', num: true}, {k: 'ground', label: 'Ground', num: true}, {k: 'departing', label: 'Dep', num: true, cls: () => 'pos'}, {k: 'arriving', label: 'Arr', num: true, cls: () => 'amb'}, {k: 'approach', label: 'Final', num: true}, {k: 'terminal', label: 'Term', num: true}, {k: 'overhead', label: 'Over', num: true},
        {k: 'holds', label: 'Holds', num: true, cls: r => r.holds ? 'neg' : ''}, {k: 'emergencies', label: 'Emerg', num: true, cls: r => r.emergencies ? 'neg' : ''}, {k: 'findings', label: 'Find', num: true}, {k: 'worst', label: 'Worst', fmt: r => sevPill(r.worst)}, {k: 'faa', label: 'FAA', fmt: r => (r.faa || []).map(faaBadge).join(' ')}, {k: 'metar', label: 'Wx', fmt: r => r.metar ? `${esc(r.metar.wind)} kt · vis ${esc(r.metar.visib)} · ${esc(r.metar.cover || '')}` : ''}];
      grid(el.querySelector('#agrid'), cols, rows, {sort: 'nearby', onRow: r => showAirport(el.querySelector('#adet'), r.icao)});
      el.querySelector('#ago').onclick = () => location.hash = '#/airports?' + qs({country: el.querySelector('#acty').value, traffic: el.querySelector('#atraf').checked ? '' : '0'});
      el.querySelector('#afaa').onclick = async () => { const r = await api('/faa'); toast(r.error ? r.error : `FAA status ${r.updated}: ${r.entries.length} entries`); navigate(); };
      if (q.icao) showAirport(el.querySelector('#adet'), q.icao);
    } },
    operators: { title: 'Operators', async render(el) {
      if (!store.app.source.active) return inactive(el, 'Operators');
      const q = store.query; const d = await api('/operators?' + qs({category: q.category})); const eco = await api('/ecosystem');
      const ph = eco.phases || {}, cats = eco.categories || {};
      el.innerHTML = `<h1>Operators <span class="note">${d.items.length} operators in the picture</span></h1>
<div class="tiles">${['ground', 'departure', 'climb', 'cruise', 'descent', 'arrival', 'approach'].map(k => `<div class="tile c-${{ground: 'grey', departure: 'teal', climb: 'blue', cruise: 'violet', descent: 'amber', arrival: 'amber', approach: 'red'}[k]}"><b>${ph[k] || 0}</b><span>${k}</span></div>`).join('')}</div>
<div class="filters">${sel('ocat', 'category', ['airline', 'regional', 'cargo', 'business', 'ga', 'military', 'charter', 'unknown'], q.category)}<button class="primary" id="ogo">Apply</button><span class="grow"></span><span class="note">fleet mix: ${Object.entries(cats).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k} ${v}`).join(' · ')}</span></div>
<div class="split"><div id="ogrid"></div><div class="detail" id="odet"><h2>Aircraft types in the picture</h2><div id="tgrid"></div></div></div>`;
      const cols = [{k: 'name', label: 'Operator', fmt: r => `<b>${esc(r.name)}</b><br><span class="note">${r.code} · ${r.country} · ${r.category}</span>`}, {k: 'aircraft', label: 'Acft', num: true}, {k: 'airborne', label: 'Airb', num: true}, {k: 'ground', label: 'Gnd', num: true}, {k: 'mean_alt', label: 'Mean alt', num: true, fmt: r => n0(r.mean_alt)},
        {k: 'types', label: 'Types', fmt: r => esc((r.types || []).join(' '))}, {k: 'phases', label: 'Phases', fmt: r => Object.entries(r.phases || {}).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([k, v]) => `<span class="phase-${k}">${k} ${v}</span>`).join(' ')}, {k: 'compliance', label: 'Integrity', num: true, fmt: r => r.compliance == null ? '' : (r.compliance * 100).toFixed(1) + '%', cls: r => r.compliance == null ? '' : (r.compliance >= .98 ? 'pos' : 'neg')}, {k: 'findings', label: 'Find', num: true}, {k: 'worst', label: 'Worst', fmt: r => sevPill(r.worst)}];
      grid(el.querySelector('#ogrid'), cols, d.items, {sort: 'aircraft', onRow: r => location.hash = '#/flights?operator=' + r.code});
      grid(el.querySelector('#tgrid'), [{k: 'code', label: 'Type', fmt: r => `<b>${r.code}</b> <span class="note">${esc(r.name)}</span>`}, {k: 'category', label: 'Class'}, {k: 'aircraft', label: 'Acft', num: true}, {k: 'mean_alt', label: 'Alt', num: true, fmt: r => n0(r.mean_alt)}, {k: 'mean_gs', label: 'GS', num: true, fmt: r => n0(r.mean_gs)}, {k: 'findings', label: 'Find', num: true}], d.types.slice(0, 60), {sort: 'aircraft', onRow: r => location.hash = '#/flights?q=' + r.code});
      el.querySelector('#ogo').onclick = () => location.hash = '#/operators?' + qs({category: el.querySelector('#ocat').value});
    } },
    auditlog: { title: 'Audit log', async render(el) {
      const q = store.query; const [d, v] = await Promise.all([api('/audit?' + qs({action: q.action, actor: q.actor, q: q.q, limit: 400})), api('/audit/verify')]);
      const chain = v.ok ? `<span class="chain ok">CHAIN VERIFIED · ${v.chained} linked${v.legacy ? ' · ' + v.legacy + ' legacy' : ''} · head ${(v.head || '').slice(0, 12)}</span>` : `<span class="chain bad">CHAIN BROKEN · ${esc(v.error || '')}</span>`;
      el.innerHTML = `<h1>Audit log <span class="note">${d.total} entries · append-only · hash-chained · data/app/audit.jsonl</span></h1><p class="lead">Every source change, injection, settings edit and job, with who did it and when. Each entry carries the SHA-256 of the previous one; editing, deleting or reordering a line breaks the chain. ${chain}</p>
<div class="filters">${sel('laction', 'action', d.actions, q.action)}${sel('lactor', 'actor', ['user', 'system'], q.actor)}<input type="text" id="lq" placeholder="search details" value="${esc(q.q || '')}"><button class="primary" id="lgo">Apply</button><span class="grow"></span><a class="btn" href="${API}/audit.csv" download>CSV</a></div><div id="lgrid"></div>`;
      grid(el.querySelector('#lgrid'), [{k: 'seq', label: '#', num: true}, {k: 'ts', label: 'Time (UTC)', fmt: r => fmtTs(r.ts)}, {k: 'actor', label: 'Actor', cls: r => r.actor === 'system' ? 'amb' : (r.actor === 'tour' ? 'pos' : '')}, {k: 'action', label: 'Action'}, {k: 'details', label: 'Details', fmt: r => esc(JSON.stringify(r.details)).slice(0, 200)}, {k: 'hash', label: 'Hash', fmt: r => `<span class="note">${(r.hash || '').slice(0, 10)}</span>`}], d.items, {sort: 'seq'});
      el.querySelector('#lgo').onclick = () => location.hash = '#/auditlog?' + qs({action: el.querySelector('#laction').value, actor: el.querySelector('#lactor').value, q: el.querySelector('#lq').value});
    } },
    live: { title: 'Live picture', full: true, async render(el) {
      if (!store.app.source.active) { el.classList.remove('full'); el.innerHTML = `<div class="empty"><h2>No source running</h2><p class="note">Start a replay or go live from the Home page.</p><a class="btn primary" href="#/">Choose a source</a></div>`; return; }
      LivePage.render(el, store.app); if (store.state) LivePage.update(store.state);
    }, tick(a, s) { if (a.source.active && s) LivePage.update(s); else if (!a.source.active) pages.live.render(store.el); } },
    findings: { title: 'Findings', async render(el) {
      if (!store.app.source.active) { el.innerHTML = `<h1>Findings</h1><div class="empty">No source running. <a href="#/">Choose a source</a> to see findings.</div>`; return; }
      const q = store.query; const d = await api(`/findings?severity=${q.severity || ''}&rule=${q.rule || ''}&category=${q.category || ''}&q=${encodeURIComponent(q.q || '')}&limit=400`);
      el.innerHTML = `<h1>Findings <span class="note">${d.total} this session</span></h1><p class="lead">Ranked by risk score: severity × persistence × evidence quality × measured rule precision. Click a row for evidence and the playbook.</p>
<div class="filters">${sel('fsev', 'severity', d.severities, q.severity)}${sel('frule', 'rule', d.rules, q.rule)}${sel('fcat2', 'category', ['security', 'safety', 'operations', 'data-quality', 'ml'], q.category)}<input type="text" id="fq" placeholder="callsign, ICAO, operator, text" value="${esc(q.q || '')}"><button class="primary" id="fgo">Apply</button><button class="ghost" data-act="hash" data-arg="#/findings">Clear</button><span class="grow"></span><a class="btn" href="${API}/findings.csv" download>CSV</a></div>
<table><tr><th>severity</th><th>rule</th><th>aircraft</th><th>time</th><th>risk</th><th>×</th><th>finding</th></tr>${d.items.map(findingRow).join('') || '<tr><td colspan="7" class="note">nothing matches</td></tr>'}</table><div id="fdetail"></div>`;
      const items = Object.fromEntries(d.items.map(f => [f.id, f]));
      el.querySelector('#fgo').onclick = () => { location.hash = `#/findings?severity=${el.querySelector('#fsev').value}&rule=${el.querySelector('#frule').value}&category=${el.querySelector('#fcat2').value}&q=${encodeURIComponent(el.querySelector('#fq').value)}`; };
      el.querySelector('#fq').onkeydown = e => { if (e.key === 'Enter') el.querySelector('#fgo').click(); };
      el.querySelector('table').addEventListener('click', async e => { const tr = e.target.closest('tr[data-id]'); if (!tr) return; const f = items[tr.dataset.id]; const pb = await api('/playbook/' + f.rule).catch(() => null);
        el.querySelector('#fdetail').innerHTML = `<div class="card" style="margin-top:14px"><h2>${sevPill(f.severity)} ${f.rule} · ${esc(f.title)}</h2><p>${esc(f.callsign || '')} ${f.icao24 || ''} · ${fmtTs(f.ts)} · risk ${f.risk} · seen ${f.occurrences}×${f.injected ? ' · <b style="color:#ff5cf0">demo injection</b>' : ''}</p>
<div class="row">${f.icao24 ? `<a class="btn small" href="#/live" data-act="focus" data-arg="${f.icao24}">Show on map</a>` : ''}</div><h3>Evidence</h3><table>${Object.entries(f.evidence).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(typeof v === 'object' ? JSON.stringify(v) : v)}</td></tr>`).join('')}</table>
${pb ? `<h3>Playbook · triage within ${pb.sla_minutes} min</h3><ol>${pb.triage.map(s => `<li>${esc(s)}</li>`).join('')}</ol><h3>Verify</h3><ul>${pb.verify.map(s => `<li>${esc(s)}</li>`).join('')}</ul><p><b>Escalate:</b> ${esc(pb.escalate)}</p><h3>Contain</h3><ul>${pb.contain.map(s => `<li>${esc(s)}</li>`).join('')}</ul>` : ''}</div>`;
        el.querySelector('#fdetail').scrollIntoView({behavior: 'smooth'}); });
    } },
    risk: { title: 'Risk', async render(el) {
      const [risk, threats, imp] = await Promise.all([api('/risk'), api('/threats'), api('/impact')]); const active = store.app.source.active;
      el.innerHTML = `<h1>Risk</h1><p class="lead">${active ? 'Register re-scored from this session\'s evidence.' : 'Baseline register (no source running). Start a source to see evidence-adjusted likelihoods.'} Likelihood moves on precision-weighted hits at the Wilson 95% lower bound; residual = inherent × (1 − detective control effectiveness).</p>
<table><tr><th>id</th><th>risk</th><th>L base→obs</th><th>I</th><th>inherent</th><th>residual</th><th>evidence</th></tr>${risk.map(r => `<tr><td>${r.id}</td><td>${esc(r.title)}</td><td>${r.baseline_L}→${r.L}</td><td>${r.I}</td><td class="rat-${r.rating}">${r.score} ${r.rating}</td><td class="rat-${r.residual_rating}">${r.residual} ${r.residual_rating}</td><td>${r.observed_hits} hits (${r.rate_lb_per_1000}/1k)</td></tr>`).join('')}</table>
<h2>Threat coverage with measured recall</h2><table><tr><th>id</th><th>threat</th><th>coverage</th><th>rules</th><th>measured recall</th></tr>${threats.map(t => `<tr><td>${t.id}</td><td>${esc(t.threat)}</td><td class="rat-${t.coverage === 'covered' ? 'low' : (t.coverage === 'partial' ? 'medium' : 'critical')}">${t.coverage}</td><td>${esc(t.rules)}</td><td>${esc(t.measured)}</td></tr>`).join('')}</table>
<h2>Operational cost of holding this session</h2><div class="tiles"><div class="tile c-amber"><b>${imp.holds}</b><span>holds</span></div><div class="tile c-amber"><b>${imp.observed_minutes}</b><span>minutes</span></div><div class="tile c-teal"><b>${imp.fuel_kg}</b><span>kg fuel</span></div><div class="tile c-teal"><b>${(imp.co2_kg / 1000).toFixed(1)} t</b><span>CO2</span></div><div class="tile c-red"><b>€${imp.delay_cost}</b><span>delay cost</span></div></div>`;
    } },
    reports: { title: 'Reports', async render(el) {
      const [reps, jobs, recs] = await Promise.all([api('/reports'), api('/jobs'), api('/recordings')]); const active = store.app.source.active;
      el.innerHTML = `<h1>Reports</h1><p class="lead">Every audit writes JSON (machine-readable), Markdown (executive summary, ranked findings, playbook steps), a self-contained HTML page you can email, and a manifest with the SHA-256 of each file plus full provenance (code commit, input hash, model hash, thresholds).</p>
<div class="row"><button class="primary" id="rsess" ${active ? '' : 'disabled'}>Generate report from the current session</button><select id="rrec">${recs.map(r => `<option value="${esc(r.path)}">${esc(r.file)}</option>`).join('')}</select><button id="rrun">Audit this recording</button></div>
<div class="jobs" id="rjobs">${jobs.filter(j => ['audit_session', 'audit_recording'].includes(j.type)).slice(0, 5).map(jobCard).join('')}</div>
<h2>On disk (${reps.length})</h2><table><tr><th>report</th><th>kind</th><th>when</th><th>open</th></tr>${reps.map(r => `<tr><td>${esc(r.name)}</td><td>${r.kind}</td><td>${ago(r.mtime)}</td><td>${r.files.html ? `<a href="${r.files.html}" target="_blank">html</a> · ` : ''}${r.files.md ? `<a href="${r.files.md}" target="_blank">md</a> · ` : ''}${r.files.json ? `<a href="${r.files.json}" target="_blank">json</a>` : ''}${r.files.html ? ` · <a href="#" data-view="${r.files.html}">view here</a>` : ''}${r.files.manifest ? ` · <a href="${r.files.manifest}" target="_blank">manifest</a> · <a href="#" data-verify="${esc(r.name)}">verify</a>` : ''}</td></tr>`).join('')}</table><div id="rview"></div>`;
      el.querySelector('#rsess').onclick = () => App.runJob('audit_session', {}, 'reports');
      el.querySelector('#rrun').onclick = () => App.runJob('audit_recording', {recording: el.querySelector('#rrec').value}, 'reports');
      el.addEventListener('click', async e => { const v = e.target.closest('a[data-verify]'); if (v) { e.preventDefault(); const r = await api('/reports/' + encodeURIComponent(v.dataset.verify) + '/manifest').catch(err => ({error: err.message})); toast(r.error ? r.error : (r.ok ? 'Verified: every report file matches its manifest hash' : 'MISMATCH: ' + Object.entries(r.files).filter(([, f]) => !f.ok).map(([k]) => k).join(', ') + ' changed since the report was written'), 6000); return; } });
      el.addEventListener('click', e => { const a = e.target.closest('a[data-view]'); if (!a) return; e.preventDefault(); el.querySelector('#rview').innerHTML = `<h2>${esc(a.dataset.view.split('/').pop())}</h2><iframe src="${a.dataset.view}" style="width:100%;height:70vh;border:1px solid var(--line);border-radius:8px;background:#fff"></iframe>`; });
    } },
    data: { title: 'Data & model', async render(el) {
      const [recs, regs, jobs, ev, model] = await Promise.all([api('/recordings'), api('/regions'), api('/jobs'), api('/evaluation'), api('/model')]);
      el.innerHTML = `<h1>Data &amp; model</h1><p class="lead">Recordings are the ground truth: every audit is replayable from them. Capture more, train the anomaly model, and measure detection with injected attacks.</p>
<div class="cards"><div class="card"><h2>Capture live traffic</h2><p>Records to data/recordings for later audits and training. One capture at a time.</p><div class="row"><select id="cprov"><option value="adsblol">adsb.lol</option><option value="opensky">OpenSky</option></select><select id="creg">${regs.map(r => `<option value="${r.key}">${esc(r.name)} (${r.key})${r.endpoint ? ' · global feed' : ''}</option>`).join('')}</select></div><div class="row"><label>radius</label><input type="number" id="crad" value="250" style="width:70px"><label>every</label><input type="number" id="cint" value="12" style="width:60px"><label>s for</label><input type="number" id="csec" value="600" style="width:70px"><label>s</label><button class="primary" id="cgo">Start capture</button></div></div>
<div class="card"><h2>Anomaly model</h2><p>${model && model.rows ? `${model.rows} rows from ${model.aircraft} aircraft · holdout flag rate ${(model.holdout_flag_rate * 100).toFixed(2)}% · trained ${esc(model.trained_at)}` : 'No model trained yet.'}</p><div class="row"><label>contamination</label><input type="number" id="tcont" value="0.01" step="0.005" min="0.001" max="0.1" style="width:80px"><button id="ttrain">Train on all civil recordings</button><button id="teval">Evaluate detection</button></div>
${ev.scenarios ? `<table><tr><th>scenario</th><th>recall</th><th>TTD</th></tr>${ev.scenarios.map(r => `<tr><td>${r.name}${r.known_gap ? ' <span class="note">(known gap)</span>' : ''}</td><td class="${r.recall >= .8 ? 'rat-low' : (r.recall >= .5 ? 'rat-medium' : 'rat-critical')}">${(r.recall * 100).toFixed(0)}%</td><td>${r.median_ttd_s == null ? '-' : r.median_ttd_s.toFixed(0) + ' s'}</td></tr>`).join('')}</table><p class="note">precision: ${Object.entries(ev.rule_precision || {}).map(([k, v]) => `${k} ${v == null ? 'n/a' : v.toFixed(2)}`).join(' · ')}</p>` : '<p class="note">no evaluation yet</p>'}</div></div>
<h2>Recordings (${recs.length})</h2><div class="row"><label>retention</label><input type="number" id="pdays" value="${store.app.settings.retention_days}" style="width:70px"><label>days</label><button id="pdry">Preview prune</button><button id="papply" class="danger">Prune now</button></div>
<table><tr><th>file</th><th>feed</th><th>regions</th><th>polls</th><th>aircraft</th><th>span</th><th>size</th><th>actions</th></tr>${recs.map(r => `<tr><td>${esc(r.file)}${r.special ? ' <span class="note">(special: not trained on)</span>' : ''}</td><td>${r.provider}</td><td>${r.regions.join('+')}</td><td>${r.polls}</td><td>${r.aircraft}</td><td>${r.span_min} min</td><td>${r.size_mb} MB</td><td><button class="small" data-replay="${esc(r.path)}">replay</button> <button class="small" data-audit="${esc(r.path)}">audit</button> <button class="small" data-eval="${esc(r.path)}">evaluate</button></td></tr>`).join('')}</table>
<h2>Jobs</h2><div class="jobs" id="djobs">${jobs.slice(0, 12).map(jobCard).join('') || '<div class="note">none yet</div>'}</div>`;
      el.querySelector('#cgo').onclick = () => App.runJob('capture', {provider: el.querySelector('#cprov').value, region: el.querySelector('#creg').value, radius: +el.querySelector('#crad').value, interval: +el.querySelector('#cint').value, seconds: +el.querySelector('#csec').value}, 'data');
      el.querySelector('#ttrain').onclick = () => App.runJob('train', {contamination: +el.querySelector('#tcont').value}, 'data');
      el.querySelector('#teval').onclick = () => App.runJob('evaluate', {}, 'data');
      el.querySelector('#pdry').onclick = () => App.runJob('prune', {days: +el.querySelector('#pdays').value, apply: false}, 'data');
      el.querySelector('#papply').onclick = () => { if (confirm('Delete recordings older than ' + el.querySelector('#pdays').value + ' days?')) App.runJob('prune', {days: +el.querySelector('#pdays').value, apply: true}, 'data'); };
      el.addEventListener('click', e => { const b = e.target.closest('button[data-replay],button[data-audit],button[data-eval]'); if (!b) return;
        if (b.dataset.replay) App.startSource({mode: 'replay', recording: b.dataset.replay, speed: 8}); else if (b.dataset.audit) App.runJob('audit_recording', {recording: b.dataset.audit}, 'data'); else App.runJob('evaluate', {recording: b.dataset.eval}, 'data'); });
    }, tick() { if (store.el && store.el.querySelector('#djobs')) api('/jobs').then(j => { store.el.querySelector('#djobs').innerHTML = j.slice(0, 12).map(jobCard).join(''); }); } },
    settings: { title: 'Settings', async render(el) {
      const s = await api('/settings'); const bySec = {}; s.tunables.forEach(t => (bySec[t.section] = bySec[t.section] || []).push(t));
      el.innerHTML = `<h1>Settings</h1><p class="lead">App settings are saved to data/app/settings.json; threshold overrides are written to ${esc(s.aero_toml)} and applied immediately to the running engine.</p>
<div class="card"><h2>App</h2><div class="row"><label><input type="checkbox" id="sdemo" ${s.app.demo ? 'checked' : ''}> demo controls (injection buttons) on new sources</label></div>
<div class="row"><label>retention days</label><input type="number" id="sret" value="${s.app.retention_days}" style="width:80px"><label>alert log</label><input type="text" id="slog" value="${esc(s.app.alert_log || '')}"><label>alert webhook</label><input type="text" id="shook" value="${esc(s.app.alert_webhook || '')}" placeholder="https://hooks.example/…"></div>
<div class="row"><label>model</label><input type="text" id="smodel" value="${esc(s.app.model || '')}" style="width:280px"><label>watchlist</label><input type="text" id="swl" value="${esc(s.app.watchlist || '')}" style="width:220px"></div>
<div class="row"><span class="note">model integrity: ${s.model_integrity ? (s.model_integrity.exists ? (s.model_integrity.match ? '<span class="pos">verified against models/registry.json</span>' : '<span class="neg">NOT VERIFIED (no matching registry entry: retrain, or allow below)</span>') : 'no model file') : 'none'}</span></div>
<div class="row"><label><input type="checkbox" id="sunv" ${s.app.allow_unverified_model ? 'checked' : ''}> allow loading a model that is not in the registry (a model file is a pickle: only do this for files you produced)</label></div>
<div class="row"><span class="note">Paths are confined: recordings under data/, models under models/, logs under logs/; webhooks must be http(s).</span></div><div class="row"><button class="primary" id="ssave">Save app settings</button></div></div>
<h2>Detection thresholds</h2><p class="note">Change a value and press Apply. Names match the constants in the code; the Help page explains each rule.</p>
${Object.entries(bySec).map(([sec, rows]) => `<h3>${sec}</h3><table>${rows.map(t => `<tr><td style="width:40%">${t.key}${t.overridden ? ' <span class="warn">(overridden)</span>' : ''}</td><td>${t.editable ? `<input type="number" step="any" data-sec="${sec}" data-key="${t.key}" value="${t.value}" style="width:140px">` : `<span class="note">${esc(JSON.stringify(t.value)).slice(0, 90)}</span>`}</td></tr>`).join('')}</table>`).join('')}
<div class="row"><button class="primary" id="sapply">Apply thresholds</button></div>`;
      el.querySelector('#ssave').onclick = async () => { await api('/settings', 'POST', {app: {demo: el.querySelector('#sdemo').checked, retention_days: +el.querySelector('#sret').value, alert_log: el.querySelector('#slog').value, alert_webhook: el.querySelector('#shook').value, model: el.querySelector('#smodel').value, watchlist: el.querySelector('#swl').value, allow_unverified_model: el.querySelector('#sunv').checked}}).then(() => { toast('Saved'); refresh(); }).catch(e => toast('Not saved: ' + e.message, 6000)); };
      el.querySelector('#sapply').onclick = async () => { const t = {}; el.querySelectorAll('input[data-sec]').forEach(i => { (t[i.dataset.sec] = t[i.dataset.sec] || {})[i.dataset.key] = +i.value; });
        try { await api('/settings', 'POST', {tunables: t}); toast('Thresholds applied and written to aero.toml'); pages.settings.render(el); } catch (e) { toast(e.message); } };
    } },
    help: { title: 'Help', async render(el) {
      const [docs, rules] = await Promise.all([api('/docs'), api('/rules')]);
      el.innerHTML = `<h1>Help</h1><p class="lead">What the rules mean, what to do when one fires, and the full documentation.</p>
<h2>Rules</h2><table><tr><th>rule</th><th>category</th><th>what it means</th><th></th></tr>${rules.map(r => `<tr><td>${r.rule}</td><td>${r.category}</td><td>${esc(r.description)}</td><td>${r.playbook ? `<a href="#" data-pb="${r.rule}">playbook</a>` : ''}</td></tr>`).join('')}</table><div id="hpb"></div>
<h2>Documentation</h2><div class="row"><select id="hdoc">${docs.map(d => `<option value="${esc(d.name)}">${esc(d.title)}</option>`).join('')}</select><button id="hopen">Open</button></div><div class="md card" id="hbody"><p class="note">choose a document</p></div>`;
      const open = async name => { const d = await api('/docs/' + encodeURIComponent(name)); el.querySelector('#hbody').innerHTML = md(d.text); };
      el.querySelector('#hopen').onclick = () => open(el.querySelector('#hdoc').value);
      el.addEventListener('click', async e => { const a = e.target.closest('a[data-pb]'); if (!a) return; e.preventDefault(); const pb = await api('/playbook/' + a.dataset.pb);
        el.querySelector('#hpb').innerHTML = `<div class="card"><h2>${pb.rule_id} · ${esc(pb.title)} <span class="note">triage within ${pb.sla_minutes} min</span></h2><h3>Triage</h3><ol>${pb.triage.map(s => `<li>${esc(s)}</li>`).join('')}</ol><h3>Verify</h3><ul>${pb.verify.map(s => `<li>${esc(s)}</li>`).join('')}</ul><p><b>Escalate:</b> ${esc(pb.escalate)}</p><h3>Contain</h3><ul>${pb.contain.map(s => `<li>${esc(s)}</li>`).join('')}</ul></div>`; el.querySelector('#hpb').scrollIntoView({behavior: 'smooth'}); });
      const first = docs.find(d => d.name.endsWith('DEMO.md')); if (first) { el.querySelector('#hdoc').value = first.name; open(first.name); }
    } },
  };

  async function showFlight(el, icao) {
    const d = await api('/aircraft/' + icao).catch(() => null); if (!d) { el.innerHTML = '<span class="note">not in the picture</span>'; return; }
    const st = d.state || {}, e = d.enrichment || {};
    el.innerHTML = `<h2>${esc(st.callsign || icao)}</h2><div class="kv2"><div>icao24</div><div>${icao}${d.injected ? ' <span style="color:#ff5cf0">INJECTED</span>' : ''}</div><div>operator</div><div>${esc(e.operator || '-')} <span class="note">${esc(e.operator_cat || '')}</span></div><div>type</div><div>${esc(e.type_name || st.aircraft_type || '-')} <span class="note">${esc(e.type_cat || '')}</span></div><div>registration</div><div>${esc(st.registration || '-')}</div><div>phase</div><div>${phaseCell(e.phase)}${e.airport ? ` near <b>${e.airport}</b> ${n0(e.airport_nm)} nm` : ''}</div>
<div>altitude</div><div>${n0(st.baro_alt_ft)} ft${e.agl_ft != null ? ` <span class="note">(${n0(e.agl_ft)} AGL)</span>` : ''}</div><div>speed / track</div><div>${n0(st.gs_kt)} kt / ${n0(st.track_deg)}°</div><div>vertical</div><div>${n0(st.vrate_fpm)} fpm</div><div>squawk</div><div>${esc(st.squawk || '-')}</div><div>source</div><div>${esc(st.position_source || '-')} · NIC/NACp/SIL ${st.nic ?? '-'}/${st.nac_p ?? '-'}/${st.sil ?? '-'}</div><div>position</div><div>${n0(st.lat, 4)}, ${n0(st.lon, 4)} @ ${fmtTs(st.ts)}</div><div>trust</div><div class="${d.trust < .5 ? 'neg' : 'pos'}">${d.trust}</div></div>
<div class="row"><a class="btn small" href="#/live" data-act="focus" data-arg="${icao}">Show on map</a><a class="btn small" href="#/findings?q=${icao}">Findings</a></div>
<h3>Findings (${d.findings.length})</h3>${d.findings.slice(0, 12).map(f => `<div class="f s-${f.severity}"><span class="sev ${f.severity}">${f.severity}</span><span class="t">${f.rule} ${esc(f.title)}<small>${fmtTs(f.ts)} · risk ${f.risk}${f.playbook ? ' · ' + esc(f.playbook) : ''}</small></span><span class="r"></span></div>`).join('') || '<div class="note ok">none</div>'}`;
  }
  async function showAirport(el, icao) {
    const d = await api('/airports/' + icao).catch(() => null); if (!d) return; const a = d.airport, act = d.activity, m = d.metar;
    el.innerHTML = `<h2>${a.iata} · ${esc(a.name)}</h2><div class="kv2"><div>location</div><div>${esc(a.city)}, ${a.country} · ${a.lat.toFixed(3)}, ${a.lon.toFixed(3)} · elev ${a.elev_ft} ft</div>
<div>FAA</div><div>${d.faa.length ? d.faa.map(faaBadge).join(' ') + '<br>' + d.faa.map(f => esc(f.reason || '')).join('; ') : '<span class="ok">no programme in effect</span>'}</div>
<div>weather</div><div>${m ? esc(m.raw || m.summary) : '<span class="note">no METAR loaded</span>'}</div>
${act ? `<div>traffic</div><div>${act.nearby} within 40 nm · ${act.ground} ground · <span class="pos">${act.departing} departing</span> · <span class="amb">${act.arriving} arriving</span> (${act.approach} on final) · ${act.terminal} terminal · ${act.overhead} overhead · ${act.holds} holds · ${act.emergencies} emergencies · ${act.findings} findings</div>` : '<div>traffic</div><div class="note">none within 40 nm in the current picture</div>'}</div>
<div class="row"><a class="btn small" href="#/flights?airport=${icao}">Flights here</a><a class="btn small" href="#/live" data-act="goto" data-arg="${a.lat},${a.lon},9">Show on map</a></div>
<h3>Flights near ${a.iata} (${d.flights.length})</h3><div class="tablewrap" style="max-height:38vh"><table><tr><th>callsign</th><th>operator</th><th>type</th><th>phase</th><th>alt</th><th>gs</th><th>nm</th></tr>${d.flights.slice(0, 80).map(f => `<tr class="click" data-act="hash" data-arg="#/flights?icao=${f.icao24}"><td>${esc(f.callsign || f.icao24)}</td><td>${esc(f.operator_code || '')}</td><td>${esc(f.type || '')}</td><td>${phaseCell(f.phase)}</td><td class="num">${n0(f.alt)}</td><td class="num">${n0(f.gs)}</td><td class="num">${n0(f.airport_nm)}</td></tr>`).join('')}</table></div>`;
  }
  function parseHash() { const h = location.hash.replace(/^#\/?/, ''); const [name, qs] = h.split('?'); store.query = Object.fromEntries(new URLSearchParams(qs || '')); return pages[name] ? name : 'home'; }
  async function navigate() {
    const name = parseHash(); const el = document.getElementById('page');
    if (store.page === 'live' && name !== 'live') LivePage.destroy();
    store.page = name; store.el = el; el.className = pages[name].full ? 'full' : '';
    document.querySelectorAll('#nav a[data-p]').forEach(a => a.classList.toggle('on', a.dataset.p === name));
    document.title = pages[name].title + ' · aero-audit';
    try { await pages[name].render(el); } catch (e) { el.innerHTML = `<div class="empty">Could not load this page: ${esc(e.message)}</div>`; }
  }
  function updateTop() {
    const a = store.app, src = a.source, pill = document.getElementById('srcpill');
    pill.className = 'pill ' + (src.active ? src.mode : 'off'); pill.textContent = src.active ? src.mode : 'no source';
    document.getElementById('srcinfo').textContent = src.active ? `${src.label} · ${src.tracked} aircraft · ${src.findings} findings · last poll ${src.last_ingest_age_s ?? '-'} s ago` : 'Start a replay or go live to see aircraft';
    document.getElementById('btnStop').hidden = !src.active; document.getElementById('btnStart').hidden = src.active;
    document.getElementById('ver').textContent = 'v' + a.version; document.getElementById('navfoot').textContent = `${a.recordings} recordings · ${a.reports} reports · ${a.jobs_running} jobs running`;
    const b = document.getElementById('banner'), tour = a.tour, inj = store.state && store.state.injections ? store.state.injections : [];
    if (tour && tour.running) { b.hidden = false; b.className = 'tour'; b.innerHTML = `<b>DEMO TOUR</b> step ${tour.step}/${tour.steps}${tour.next_kind ? ` · next <b>${esc(tour.next_kind)}</b> in ${Math.round(tour.next_in_s || 0)} s` : ''}${tour.last && tour.last.narration ? ` · <span class="narr">${esc(tour.last.narration)}</span>` : ''}${inj.length ? ` · active: ${inj.map(i => i.kind + (i.icao24 ? ' [' + i.icao24 + ']' : '')).join(', ')}` : ''} <a href="#" data-act="tourStop">stop tour</a>`; }
    else if (inj.length) { b.hidden = false; b.className = ''; b.textContent = 'DEMO INJECTION: ' + inj.map(i => i.label + (i.icao24 ? ' [' + i.icao24 + ']' : '')).join(' · '); } else b.hidden = true;
  }
  async function refresh() {
    try { store.app = await api('/app'); if (store.app.security && store.app.security.csrf) TOKEN = store.app.security.csrf; store.state = store.app.source.active ? await api('/state') : null; updateTop(); ticker(store.state); alertSounds(store.state); document.getElementById('fkstatus').textContent = store.state ? `${store.state.kpis.tracked} ACFT · ${store.state.kpis.findings_total} FINDINGS · ${Object.entries(store.state.phases || {}).filter(([k]) => ['departure', 'arrival', 'cruise'].includes(k)).map(([k, v]) => k.toUpperCase() + ' ' + v).join(' · ')}` : 'IDLE'; const p = pages[store.page]; if (p && p.tick) p.tick(store.app, store.state); }
    catch (e) { document.getElementById('srcinfo').textContent = 'server unreachable'; }
  }
  window.App = {
    toast, refresh,
    async startSource(body) { try { toast('Starting…'); await api('/source/start', 'POST', body); await refresh(); location.hash = '#/live'; } catch (e) { toast('Could not start: ' + e.message, 6000); } },
    async stopSource() { await api('/source/stop', 'POST', {}); await refresh(); if (store.page === 'live') navigate(); toast('Source stopped'); },
    async runJob(type, params, page) { try { const j = await api('/jobs', 'POST', {type, params}); toast(`Started ${type} (${j.id})`); setTimeout(() => { if (store.page === page) navigate(); }, 800); } catch (e) { toast(e.message, 6000); } },
    async cancelJob(id) { await api(`/jobs/${id}/cancel`, 'POST', {}); toast('Cancel requested'); },
    toggleLog(id) { const p = document.getElementById('log-' + id); if (p) p.hidden = !p.hidden; },
    async tour(action) { try { const t = await api('/tour', 'POST', {action}); toast(action === 'start' ? 'Demo tour started: eight scenarios on a timeline, loops until stopped' : 'Demo tour stopped'); await refresh(); return t; } catch (e) { toast(e.message, 6000); } },
    headers, setSound, tourRunning: () => !!(store.app && store.app.tour && store.app.tour.running),
  };
  document.addEventListener('click', e => { const t = e.target.closest('[data-act]'); if (!t) return; const act = t.dataset.act, arg = t.dataset.arg;
    if (act === 'cancelJob') { e.preventDefault(); App.cancelJob(arg); } else if (act === 'toggleLog') { e.preventDefault(); App.toggleLog(arg); }
    else if (act === 'hash') { e.preventDefault(); location.hash = arg; } else if (act === 'focus') { setTimeout(() => LivePage.focus(arg), 600); }
    else if (act === 'focusNow') { e.preventDefault(); LivePage.focus(arg); } else if (act === 'zoomTo') { e.preventDefault(); LivePage.zoomTo(arg); } else if (act === 'closeDrawer') LivePage.closeDrawer();
    else if (act === 'goto') { const [la, lo, z] = arg.split(',').map(Number); setTimeout(() => LivePage.goto(la, lo, z), 600); }
    else if (act === 'tourStop') { e.preventDefault(); App.tour('stop'); } else if (act === 'tourStart') { e.preventDefault(); App.tour('start'); } });
  document.getElementById('btnSound').onclick = () => setSound({off: 'tones', tones: 'voice', voice: 'off'}[sound]); setSound(sound, false);
  const MNEMONICS = {HOME: '#/', LIVE: '#/live', FLT: '#/flights', AIRP: '#/airports', OPS: '#/operators', FIND: '#/findings', RISK: '#/risk', RPT: '#/reports', DATA: '#/data', LOG: '#/auditlog', SET: '#/settings', HELP: '#/help'};
  function runCommand(text) {
    const [m, ...rest] = text.trim().toUpperCase().split(/\s+/); const arg = rest.join(' '); if (!m) return;
    if (m === 'STOP') return App.stopSource(); if (m === 'USA') return App.startSource({mode: 'live', provider: 'opensky', region: 'conus', interval: 60});
    if (m === 'TOUR') return App.tour(store.app && store.app.tour && store.app.tour.running ? 'stop' : 'start'); if (m === 'SND') return setSound(arg ? arg.toLowerCase() : {off: 'tones', tones: 'voice', voice: 'off'}[sound]);
    if (!MNEMONICS[m]) { toast('Unknown mnemonic ' + m + '. Try: ' + Object.keys(MNEMONICS).join(' ') + ' STOP USA TOUR SND'); return; }
    let h = MNEMONICS[m];
    if (arg) { if (m === 'FLT') h += '?' + (/^[A-Z]{3}$/.test(arg) ? 'operator=' + arg : 'q=' + encodeURIComponent(arg)); else if (m === 'AIRP') h += '?icao=' + (arg.length === 3 ? 'K' + arg : arg) + '&traffic=0'; else if (m === 'FIND') h += '?' + (/^[A-Z]+-\d+$/.test(arg) ? 'rule=' + arg : (['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'].includes(arg) ? 'severity=' + arg.toLowerCase() : 'q=' + encodeURIComponent(arg))); else if (m === 'OPS') h += '?category=' + arg.toLowerCase(); else if (m === 'LOG') h += '?q=' + encodeURIComponent(arg); }
    if (location.hash === h) navigate(); else location.hash = h;
  }
  const cmd = document.getElementById('cmd');
  cmd.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === 'Return' || e.keyCode === 13) { e.preventDefault(); runCommand(cmd.value); cmd.value = ''; } });
  document.addEventListener('keydown', e => { const fk = {F1: 'HELP', F2: 'LIVE', F3: 'FLT', F4: 'AIRP', F5: 'OPS', F6: 'FIND', F7: 'RISK', F8: 'LOG'}[e.key]; if (fk) { e.preventDefault(); runCommand(fk); } if (e.key === '/' && document.activeElement !== cmd && document.activeElement.tagName !== 'INPUT') { e.preventDefault(); cmd.focus(); } });
  document.getElementById('fkeys').addEventListener('click', e => { const t = e.target.closest('span'); if (t && /^F\d/.test(t.textContent)) runCommand(t.textContent.split(' ')[1]); });
  setInterval(() => { document.getElementById('clock').textContent = new Date().toISOString().replace('T', ' ').substr(0, 19) + 'Z'; }, 1000);
  function ticker(s) { const t = document.getElementById('tickerTrack'); if (!s || !s.events || !s.events.length) { t.innerHTML = '<span class="ti note">no findings yet</span>'; return; }
    const html = s.events.slice(0, 30).map(f => `<span class="ti"><b>${f.rule}</b> <span class="sev ${f.severity}">${f.severity}</span> ${esc(f.callsign || f.icao24 || '')}${f.operator_code ? ' ' + esc(f.operator_code) : ''}${f.airport ? ' @' + f.airport : ''} · ${esc(f.title).slice(0, 60)}</span>`).join('');
    if (t.dataset.sig !== html.length + ':' + (s.events[0] && s.events[0].id)) { t.dataset.sig = html.length + ':' + (s.events[0] && s.events[0].id); t.innerHTML = html; } }
  document.getElementById('btnStop').onclick = App.stopSource;
  window.addEventListener('hashchange', navigate);
  refresh().then(navigate); setInterval(refresh, 3000);
})();
