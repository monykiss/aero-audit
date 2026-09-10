/* aero-audit app: hash router, shared store, pages. Add a page: pages.name = {title, render(el), tick(app, state)}. */
(function () {
  const API = '/api/v1';
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const fmtTs = t => t ? new Date(t * 1000).toISOString().replace('T', ' ').substr(0, 19) + 'Z' : '-';
  const ago = t => t ? Math.round((Date.now() / 1000 - t) / 60) + ' min ago' : '-';
  async function api(path, method = 'GET', body) {
    const r = await fetch(API + path, {method, headers: body ? {'Content-Type': 'application/json'} : {}, body: body ? JSON.stringify(body) : undefined});
    const j = await r.json().catch(() => ({})); if (!r.ok && j.error) throw new Error(j.error); return j;
  }
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
  const sevPill = s => `<span class="sev ${s}">${s}</span>`;
  const findingRow = f => `<tr class="click" data-id="${f.id}"><td>${sevPill(f.severity)}</td><td>${f.rule}</td><td>${esc(f.callsign || '')}<br><span class="note">${f.icao24 || ''}${f.injected ? ' · <span style="color:#ff5cf0">injected</span>' : ''}</span></td><td>${fmtTs(f.ts)}</td><td>${f.risk}</td><td>${f.occurrences}</td><td>${esc(f.title)}</td></tr>`;
  function jobCard(j) { const pct = j.progress != null ? Math.round(j.progress * 100) : (j.status === 'done' ? 100 : 0); const res = j.result ? Object.entries(j.result).filter(([k]) => !['log'].includes(k)).slice(0, 6).map(([k, v]) => `${k}: ${typeof v === 'object' ? esc(JSON.stringify(v)).slice(0, 80) : esc(v)}`).join(' · ') : '';
    return `<div class="job"><div class="row"><b>${j.type}</b><span class="note">${j.status}${j.error ? ' · <span class="bad">' + esc(j.error) + '</span>' : ''}</span><span class="grow"></span>${j.status === 'running' ? `<button class="small" onclick="App.cancelJob('${j.id}')">cancel</button>` : ''}<button class="small ghost" onclick="App.toggleLog('${j.id}')">log</button></div>
<div class="bar"><i style="width:${pct}%"></i></div><div class="note">${esc(res)}</div><pre id="log-${j.id}" hidden>${esc((j.log || []).join('\n'))}</pre></div>`; }

  const pages = {
    home: { title: 'Home', async render(el) {
      const [regs, recs] = await Promise.all([api('/regions'), api('/recordings')]); const a = store.app; const src = a.source;
      const civil = recs.filter(r => !r.special);
      el.innerHTML = `<h1>Welcome</h1><p class="lead">aero-audit watches real aircraft, checks every position report against physics, integrity, and safety rules, and tells you what to look at first. Pick a source to begin.</p>
${src.active ? '' : `<div class="steps"><div class="step"><b>1 · Choose a source</b>Replay a recording on disk, or go live on a region.</div><div class="step"><b>2 · Watch the live picture</b>Aircraft colour by their worst finding; click any for details and playbook steps.</div><div class="step"><b>3 · Try an injection</b>Teleport, hijack code, ghost: see detection, escalation, trust.</div></div>`}
${src.active ? `<div class="card" style="margin-bottom:14px"><h2>Running: ${esc(src.label)}</h2><p>${src.tracked} aircraft in the last poll · ${src.findings} findings · ${src.batches} polls · last poll ${src.last_ingest_age_s ?? '-'} s ago${src.errors.length ? ' · <span class="bad">' + esc(src.errors.at(-1)) + '</span>' : ''}</p><div class="row"><a class="btn primary" href="#/live">Open the live picture</a><button id="hstop">Stop</button></div></div>` : ''}
<div class="cards"><div class="card"><h2>Replay a recording</h2><p>Deterministic, works offline. Loops when it reaches the end.</p>
<div class="row"><select id="rsel" style="max-width:420px">${civil.map(r => `<option value="${esc(r.path)}">${esc(r.file)} · ${r.provider} ${r.regions.join('+')} · ${r.polls} polls · ${r.aircraft} aircraft · ${r.span_min} min</option>`).join('')}</select></div>
<div class="row"><label>speed <b id="spv">8</b>×</label><input type="range" id="rspeed" min="1" max="40" value="8"><label><input type="checkbox" id="rdemo" ${a.settings.demo ? 'checked' : ''}> demo controls</label></div>
<div class="row"><button class="primary" id="rstart" ${civil.length ? '' : 'disabled'}>Start replay</button>${civil.length ? '' : '<span class="note">no recordings yet: capture one on the Data page or go live</span>'}</div></div>
<div class="card"><h2>Go live</h2><p>Polls a public feed, records everything for later audit, refreshes weather every 10 minutes.</p>
<div class="row"><label>feed</label><select id="lprov"><option value="adsblol">adsb.lol (integrity fields, 250 nm)</option><option value="opensky">OpenSky (slower, no integrity fields)</option></select>
<label>region</label><select id="lreg">${regs.filter(r => !r.endpoint).map(r => `<option value="${r.key}">${esc(r.name)} (${r.key})</option>`).join('')}</select></div>
<div class="row"><label>radius nm</label><input type="number" id="lrad" value="150" min="20" max="250" style="width:80px"><label>poll every</label><input type="number" id="lint" value="12" min="10" max="120" style="width:70px"><label>s</label><label><input type="checkbox" id="ldemo" ${a.settings.demo ? 'checked' : ''}> demo controls</label></div>
<div class="row"><button class="primary" id="lstart">Go live</button><span class="note">one live source per machine: the feed rate-limits parallel pollers</span></div></div></div>
<h2>On this machine</h2><div class="tiles"><div class="tile"><b>${a.recordings}</b><span>recordings</span></div><div class="tile"><b>${a.reports}</b><span>reports</span></div><div class="tile"><b>${a.model ? (a.model.rows / 1000).toFixed(0) + 'k' : '—'}</b><span>model rows</span></div><div class="tile"><b>${a.model ? (a.model.holdout_flag_rate * 100).toFixed(2) + '%' : '—'}</b><span>holdout flag rate</span></div><div class="tile"><b>${a.model && a.model.evaluation ? Math.round(Object.values(a.model.evaluation.recall).filter((v, i, arr) => i < 6).reduce((x, y) => x + y, 0) / 6 * 100) + '%' : '—'}</b><span>mean recall (6 attacks)</span></div><div class="tile"><b>${a.jobs_running}</b><span>jobs running</span></div></div>
<p class="note">Manage recordings, capture new data, train and evaluate on the <a href="#/data">Data &amp; model</a> page. Thresholds and demo mode are in <a href="#/settings">Settings</a>.</p>`;
      el.querySelector('#rspeed').oninput = e => el.querySelector('#spv').textContent = e.target.value;
      el.querySelector('#rstart').onclick = () => App.startSource({mode: 'replay', recording: el.querySelector('#rsel').value, speed: +el.querySelector('#rspeed').value, demo: el.querySelector('#rdemo').checked});
      el.querySelector('#lstart').onclick = () => App.startSource({mode: 'live', provider: el.querySelector('#lprov').value, region: el.querySelector('#lreg').value, radius: +el.querySelector('#lrad').value, interval: +el.querySelector('#lint').value, demo: el.querySelector('#ldemo').checked});
      const hs = el.querySelector('#hstop'); if (hs) hs.onclick = App.stopSource;
    } },
    live: { title: 'Live picture', full: true, async render(el) {
      if (!store.app.source.active) { el.classList.remove('full'); el.innerHTML = `<div class="empty"><h2>No source running</h2><p class="note">Start a replay or go live from the Home page.</p><a class="btn primary" href="#/">Choose a source</a></div>`; return; }
      LivePage.render(el, store.app); if (store.state) LivePage.update(store.state);
    }, tick(a, s) { if (a.source.active && s) LivePage.update(s); else if (!a.source.active) pages.live.render(store.el); } },
    findings: { title: 'Findings', async render(el) {
      if (!store.app.source.active) { el.innerHTML = `<h1>Findings</h1><div class="empty">No source running. <a href="#/">Choose a source</a> to see findings.</div>`; return; }
      const q = store.query; const d = await api(`/findings?severity=${q.severity || ''}&rule=${q.rule || ''}&q=${encodeURIComponent(q.q || '')}&limit=400`);
      el.innerHTML = `<h1>Findings <span class="note">${d.total} this session</span></h1><p class="lead">Ranked by risk score: severity × persistence × evidence quality × measured rule precision. Click a row for evidence and the playbook.</p>
<div class="row"><select id="fsev"><option value="">any severity</option>${d.severities.map(s => `<option ${q.severity === s ? 'selected' : ''}>${s}</option>`).join('')}</select><select id="frule"><option value="">any rule</option>${d.rules.map(r => `<option ${q.rule === r ? 'selected' : ''}>${r}</option>`).join('')}</select><input type="text" id="fq" placeholder="callsign, ICAO, text" value="${esc(q.q || '')}"><button id="fgo">Filter</button><a class="btn ghost" href="${API}/findings.csv" download>Export CSV</a></div>
<table><tr><th>severity</th><th>rule</th><th>aircraft</th><th>time</th><th>risk</th><th>×</th><th>finding</th></tr>${d.items.map(findingRow).join('') || '<tr><td colspan="7" class="note">nothing matches</td></tr>'}</table><div id="fdetail"></div>`;
      const items = Object.fromEntries(d.items.map(f => [f.id, f]));
      el.querySelector('#fgo').onclick = () => { location.hash = `#/findings?severity=${el.querySelector('#fsev').value}&rule=${el.querySelector('#frule').value}&q=${encodeURIComponent(el.querySelector('#fq').value)}`; };
      el.querySelector('#fq').onkeydown = e => { if (e.key === 'Enter') el.querySelector('#fgo').click(); };
      el.querySelector('table').addEventListener('click', async e => { const tr = e.target.closest('tr[data-id]'); if (!tr) return; const f = items[tr.dataset.id]; const pb = await api('/playbook/' + f.rule).catch(() => null);
        el.querySelector('#fdetail').innerHTML = `<div class="card" style="margin-top:14px"><h2>${sevPill(f.severity)} ${f.rule} · ${esc(f.title)}</h2><p>${esc(f.callsign || '')} ${f.icao24 || ''} · ${fmtTs(f.ts)} · risk ${f.risk} · seen ${f.occurrences}×${f.injected ? ' · <b style="color:#ff5cf0">demo injection</b>' : ''}</p>
<div class="row">${f.icao24 ? `<a class="btn small" href="#/live" onclick="setTimeout(()=>LivePage.focus('${f.icao24}'),600)">Show on map</a>` : ''}</div><h3>Evidence</h3><table>${Object.entries(f.evidence).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(typeof v === 'object' ? JSON.stringify(v) : v)}</td></tr>`).join('')}</table>
${pb ? `<h3>Playbook · triage within ${pb.sla_minutes} min</h3><ol>${pb.triage.map(s => `<li>${esc(s)}</li>`).join('')}</ol><h3>Verify</h3><ul>${pb.verify.map(s => `<li>${esc(s)}</li>`).join('')}</ul><p><b>Escalate:</b> ${esc(pb.escalate)}</p><h3>Contain</h3><ul>${pb.contain.map(s => `<li>${esc(s)}</li>`).join('')}</ul>` : ''}</div>`;
        el.querySelector('#fdetail').scrollIntoView({behavior: 'smooth'}); });
    } },
    risk: { title: 'Risk', async render(el) {
      const [risk, threats, imp] = await Promise.all([api('/risk'), api('/threats'), api('/impact')]); const active = store.app.source.active;
      el.innerHTML = `<h1>Risk</h1><p class="lead">${active ? 'Register re-scored from this session\'s evidence.' : 'Baseline register (no source running). Start a source to see evidence-adjusted likelihoods.'} Likelihood moves on precision-weighted hits at the Wilson 95% lower bound; residual = inherent × (1 − detective control effectiveness).</p>
<table><tr><th>id</th><th>risk</th><th>L base→obs</th><th>I</th><th>inherent</th><th>residual</th><th>evidence</th></tr>${risk.map(r => `<tr><td>${r.id}</td><td>${esc(r.title)}</td><td>${r.baseline_L}→${r.L}</td><td>${r.I}</td><td class="rat-${r.rating}">${r.score} ${r.rating}</td><td class="rat-${r.residual_rating}">${r.residual} ${r.residual_rating}</td><td>${r.observed_hits} hits (${r.rate_lb_per_1000}/1k)</td></tr>`).join('')}</table>
<h2>Threat coverage with measured recall</h2><table><tr><th>id</th><th>threat</th><th>coverage</th><th>rules</th><th>measured recall</th></tr>${threats.map(t => `<tr><td>${t.id}</td><td>${esc(t.threat)}</td><td class="rat-${t.coverage === 'covered' ? 'low' : (t.coverage === 'partial' ? 'medium' : 'critical')}">${t.coverage}</td><td>${esc(t.rules)}</td><td>${esc(t.measured)}</td></tr>`).join('')}</table>
<h2>Operational cost of holding this session</h2><div class="tiles"><div class="tile"><b>${imp.holds}</b><span>holds</span></div><div class="tile"><b>${imp.observed_minutes}</b><span>minutes</span></div><div class="tile"><b>${imp.fuel_kg}</b><span>kg fuel</span></div><div class="tile"><b>${(imp.co2_kg / 1000).toFixed(1)} t</b><span>CO2</span></div><div class="tile"><b>€${imp.delay_cost}</b><span>delay cost</span></div></div>`;
    } },
    reports: { title: 'Reports', async render(el) {
      const [reps, jobs, recs] = await Promise.all([api('/reports'), api('/jobs'), api('/recordings')]); const active = store.app.source.active;
      el.innerHTML = `<h1>Reports</h1><p class="lead">Every audit writes JSON (machine-readable), Markdown (executive summary, ranked findings, playbook steps) and a self-contained HTML page you can email.</p>
<div class="row"><button class="primary" id="rsess" ${active ? '' : 'disabled'}>Generate report from the current session</button><select id="rrec">${recs.map(r => `<option value="${esc(r.path)}">${esc(r.file)}</option>`).join('')}</select><button id="rrun">Audit this recording</button></div>
<div class="jobs" id="rjobs">${jobs.filter(j => ['audit_session', 'audit_recording'].includes(j.type)).slice(0, 5).map(jobCard).join('')}</div>
<h2>On disk (${reps.length})</h2><table><tr><th>report</th><th>kind</th><th>when</th><th>open</th></tr>${reps.map(r => `<tr><td>${esc(r.name)}</td><td>${r.kind}</td><td>${ago(r.mtime)}</td><td>${r.files.html ? `<a href="${r.files.html}" target="_blank">html</a> · ` : ''}${r.files.md ? `<a href="${r.files.md}" target="_blank">md</a> · ` : ''}${r.files.json ? `<a href="${r.files.json}" target="_blank">json</a>` : ''}${r.files.html ? ` · <a href="#" data-view="${r.files.html}">view here</a>` : ''}</td></tr>`).join('')}</table><div id="rview"></div>`;
      el.querySelector('#rsess').onclick = () => App.runJob('audit_session', {}, 'reports');
      el.querySelector('#rrun').onclick = () => App.runJob('audit_recording', {recording: el.querySelector('#rrec').value}, 'reports');
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
<div class="row"><label>model</label><input type="text" id="smodel" value="${esc(s.app.model || '')}" style="width:280px"><label>watchlist</label><input type="text" id="swl" value="${esc(s.app.watchlist || '')}" style="width:220px"></div><div class="row"><button class="primary" id="ssave">Save app settings</button></div></div>
<h2>Detection thresholds</h2><p class="note">Change a value and press Apply. Names match the constants in the code; the Help page explains each rule.</p>
${Object.entries(bySec).map(([sec, rows]) => `<h3>${sec}</h3><table>${rows.map(t => `<tr><td style="width:40%">${t.key}${t.overridden ? ' <span class="warn">(overridden)</span>' : ''}</td><td>${t.editable ? `<input type="number" step="any" data-sec="${sec}" data-key="${t.key}" value="${t.value}" style="width:140px">` : `<span class="note">${esc(JSON.stringify(t.value)).slice(0, 90)}</span>`}</td></tr>`).join('')}</table>`).join('')}
<div class="row"><button class="primary" id="sapply">Apply thresholds</button></div>`;
      el.querySelector('#ssave').onclick = async () => { await api('/settings', 'POST', {app: {demo: el.querySelector('#sdemo').checked, retention_days: +el.querySelector('#sret').value, alert_log: el.querySelector('#slog').value, alert_webhook: el.querySelector('#shook').value, model: el.querySelector('#smodel').value, watchlist: el.querySelector('#swl').value}}); toast('Saved'); refresh(); };
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
    const b = document.getElementById('banner'); if (store.state && store.state.injections && store.state.injections.length) { b.hidden = false; b.textContent = 'DEMO INJECTION: ' + store.state.injections.map(i => i.label + (i.icao24 ? ' [' + i.icao24 + ']' : '')).join(' · '); } else b.hidden = true;
  }
  async function refresh() {
    try { store.app = await api('/app'); store.state = store.app.source.active ? await api('/state') : null; updateTop(); const p = pages[store.page]; if (p && p.tick) p.tick(store.app, store.state); }
    catch (e) { document.getElementById('srcinfo').textContent = 'server unreachable'; }
  }
  window.App = {
    toast, refresh,
    async startSource(body) { try { toast('Starting…'); await api('/source/start', 'POST', body); await refresh(); location.hash = '#/live'; } catch (e) { toast('Could not start: ' + e.message, 6000); } },
    async stopSource() { await api('/source/stop', 'POST', {}); await refresh(); if (store.page === 'live') navigate(); toast('Source stopped'); },
    async runJob(type, params, page) { try { const j = await api('/jobs', 'POST', {type, params}); toast(`Started ${type} (${j.id})`); setTimeout(() => { if (store.page === page) navigate(); }, 800); } catch (e) { toast(e.message, 6000); } },
    async cancelJob(id) { await api(`/jobs/${id}/cancel`, 'POST', {}); toast('Cancel requested'); },
    toggleLog(id) { const p = document.getElementById('log-' + id); if (p) p.hidden = !p.hidden; },
  };
  document.getElementById('btnStop').onclick = App.stopSource;
  document.getElementById('search').addEventListener('keydown', e => { if (e.key !== 'Enter') return; const q = e.target.value.trim(); if (!q) return; if (!store.app.source.active) { toast('Start a source first'); return; }
    const hit = (store.state && store.state.aircraft || []).find(a => (a.callsign || '').toLowerCase().startsWith(q.toLowerCase()) || a.icao24 === q.toLowerCase());
    if (!hit) { toast('No aircraft matching "' + q + '" in the current picture'); return; } if (store.page !== 'live') { location.hash = '#/live'; setTimeout(() => LivePage.focus(hit.icao24), 700); } else LivePage.focus(hit.icao24); });
  window.addEventListener('hashchange', navigate);
  refresh().then(navigate); setInterval(refresh, 3000);
})();
