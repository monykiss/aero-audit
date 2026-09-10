/* Live picture page: canvas aircraft layer (scales to 10k aircraft), colour modes, KPIs, panels, demo controls. */
(function () {
  let map = null, layer = null, trail = null, selected = null, hoverId = null, tab = 'feed', S = null, mode = 'findings', slow = {at: 0, impact: null};
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const fmtTs = t => t ? new Date(t * 1000).toISOString().substr(11, 8) + 'Z' : '-';
  const num = (v, d = 0) => (v === null || v === undefined || isNaN(v)) ? '-' : Number(v).toFixed(d);
  const SEV = {critical: '#ff4d4f', high: '#ff7a45', medium: '#ffc53d', low: '#4ea1ff', info: '#8b96a8'};
  const MODES = {
    findings: {label: 'findings', legend: [['#7fb3ff', 'normal'], ['#ffc53d', 'medium'], ['#ff4d4f', 'high / critical'], ['#b47bff', 'low trust'], ['#5a6472', 'on ground']],
      color(a) { if (a.ground) return '#5a6472'; if (a.trust < 0.5) return '#b47bff'; return a.sev ? SEV[a.sev] : '#7fb3ff'; }},
    altitude: {label: 'altitude', legend: [['#5a6472', 'ground'], ['#ffd166', '< 2,000 ft'], ['#ff9f43', '< 10,000'], ['#4ecdc4', '< 20,000'], ['#48a9ff', '< 30,000'], ['#b388ff', '30,000+']],
      color(a) { if (a.ground) return '#5a6472'; const h = a.alt || 0; return h < 2000 ? '#ffd166' : h < 10000 ? '#ff9f43' : h < 20000 ? '#4ecdc4' : h < 30000 ? '#48a9ff' : '#b388ff'; }},
    speed: {label: 'speed', legend: [['#5a6472', 'ground'], ['#9be7a3', '< 150 kt'], ['#4ecdc4', '< 300'], ['#48a9ff', '< 450'], ['#ff6b81', '450+']],
      color(a) { if (a.ground) return '#5a6472'; const g = a.gs || 0; return g < 150 ? '#9be7a3' : g < 300 ? '#4ecdc4' : g < 450 ? '#48a9ff' : '#ff6b81'; }},
    trust: {label: 'trust', legend: [['#3ddc97', '1.0 trusted'], ['#ffc53d', '0.5'], ['#ff4d4f', '0 eroded']],
      color(a) { const t = Math.max(0, Math.min(1, a.trust ?? 1)); const r = t < .5 ? 255 : Math.round(255 * (1 - t) * 2), g = t < .5 ? Math.round(220 * t * 2) : 220; return `rgb(${r},${g},80)`; }},
  };
  const HELP = {tracked: 'Aircraft in the latest poll', airborne: 'Tracked aircraft not on the ground', seen: 'Unique aircraft since the source started', findings: 'Every finding this session (rules + model)',
    ch: 'Critical and high severity findings', med: 'Medium severity findings', comp: 'Share of airborne ADS-B fixes meeting NIC>=7, NACp>=8, SIL=3 (14 CFR 91.227). n/a when the feed lacks integrity fields', lt: 'Aircraft whose trust score fell below 0.5'};

  /* ---- canvas layer: one <canvas> over the map, redrawn on every move ---- */
  const AircraftLayer = L.Layer.extend({
    onAdd(m) { this._map = m; this._c = L.DomUtil.create('canvas', 'ac-canvas', m.getContainer()); this._ctx = this._c.getContext('2d'); this._ac = []; this._pts = [];
      this._h = () => this._draw(); m.on('move zoom viewreset resize', this._h); this._draw(); },
    onRemove(m) { m.off('move zoom viewreset resize', this._h); L.DomUtil.remove(this._c); },
    setData(ac) { this._ac = ac; this._draw(); },
    _draw() { const m = this._map; if (!m) return; const el = m.getContainer(); const size = L.point(el.clientWidth, el.clientHeight), dpr = window.devicePixelRatio || 1;
      if (!size.x || !size.y) return; if (!m.getSize().equals(size)) { m.invalidateSize({pan: false}); }
      if (this._c.width !== size.x * dpr || this._c.height !== size.y * dpr) { this._c.width = size.x * dpr; this._c.height = size.y * dpr; this._c.style.width = size.x + 'px'; this._c.style.height = size.y + 'px'; }
      const ctx = this._ctx; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, size.x, size.y);
      const z = m.getZoom(), r = z <= 4 ? 4 : z <= 6 ? 6 : z <= 8 ? 8 : 11; const colorOf = MODES[mode].color; this._pts = [];
      for (const a of this._ac) { const p = m.latLngToContainerPoint([a.lat, a.lon]); if (p.x < -20 || p.y < -20 || p.x > size.x + 20 || p.y > size.y + 20) continue;
        this._pts.push([p.x, p.y, a]); const th = ((a.track || 0) - 90) * Math.PI / 180; ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(th);
        if (a.emergency || a.injected || a.icao24 === selected) { ctx.beginPath(); ctx.arc(0, 0, r + 6, 0, Math.PI * 2); ctx.strokeStyle = a.emergency ? '#ff4d4f' : (a.injected ? '#ff5cf0' : '#ffffff'); ctx.lineWidth = 2; ctx.stroke(); }
        ctx.beginPath(); ctx.moveTo(r * 1.3, 0); ctx.lineTo(-r * .9, r * .8); ctx.lineTo(-r * .5, 0); ctx.lineTo(-r * .9, -r * .8); ctx.closePath();
        ctx.fillStyle = colorOf(a); ctx.fill(); ctx.strokeStyle = 'rgba(0,0,0,.55)'; ctx.lineWidth = 1; ctx.stroke(); ctx.restore(); }
    },
    nearest(pt, maxPx) { let best = null, bd = maxPx * maxPx; for (const [x, y, a] of this._pts) { const d = (x - pt.x) ** 2 + (y - pt.y) ** 2; if (d < bd) { bd = d; best = a; } } return best; }
  });

  function initMap(c) {
    map = L.map('map', {zoomControl: true, preferCanvas: true}).setView(c || [39, -96], 5);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 12, className: 'dark-tiles', attribution: '&copy; OpenStreetMap contributors'}).addTo(map);
    layer = new AircraftLayer().addTo(map);
    const tip = document.getElementById('ltip');
    map.on('mousemove', e => { const a = layer.nearest(e.containerPoint, 10); if (!a) { tip.hidden = true; hoverId = null; return; } hoverId = a.icao24;
      tip.hidden = false; tip.style.left = (e.containerPoint.x + 14) + 'px'; tip.style.top = (e.containerPoint.y + 14) + 'px';
      tip.innerHTML = `<b>${esc(a.callsign || a.icao24)}</b> ${a.type ? esc(a.type) : ''} <span style="color:#8d8d8d">${esc(a.operator || '')}</span><br>${num(a.alt)} ft · ${num(a.gs)} kt · ${num(a.track)}°${a.squawk ? ' · sq ' + a.squawk : ''}<br><span class="phase-${a.phase}">${a.phase || ''}</span>${a.airport ? ' · ' + a.airport + ' ' + num(a.airport_nm) + ' nm' : ''}${a.sev ? `<br><span style="color:${SEV[a.sev]}">${a.sev.toUpperCase()} · ${a.rules.join(', ')}</span>` : ''}${a.injected ? '<br><span style="color:#ff5cf0">INJECTED (demo)</span>' : ''}`; });
    map.on('click', e => { const a = layer.nearest(e.containerPoint, 12); if (a) select(a.icao24); else closeDrawer(); });
  }
  async function select(icao) {
    selected = icao; layer && layer._draw(); const r = await fetch('/api/v1/aircraft/' + icao); if (!r.ok) return; const d = await r.json(); const st = d.state || {};
    if (trail) { map.removeLayer(trail); trail = null; }
    if (d.trail.length > 1) trail = L.polyline(d.trail.map(p => [p.lat, p.lon]), {color: d.injected ? '#ff5cf0' : '#ffd166', weight: 2, opacity: .9, dashArray: d.injected ? '4 4' : null}).addTo(map);
    const e = d.enrichment || {};
    const fs = d.findings.map(f => `<div class="f s-${f.severity} ${f.injected ? 'inj' : ''}"><span class="sev ${f.severity}">${f.severity}</span><span class="t">${f.rule} ${esc(f.title)}<small>${fmtTs(f.ts)} · risk ${f.risk} · ×${f.occurrences}${f.playbook ? ' · ' + esc(f.playbook) : ''}</small></span><span class="r"></span></div>`).join('') || '<div class="note ok">no findings for this aircraft</div>';
    document.getElementById('drawerBody').innerHTML = `<h2>${esc(st.callsign || '')} <span class="note">${icao}${d.injected ? ' · <span style="color:#ff5cf0">INJECTED</span>' : ''}</span></h2>
<div class="kv"><div>operator <b>${esc(e.operator || '-')}</b></div><div>phase <b class="phase-${e.phase}">${esc(e.phase || '-')}${e.airport ? ' · ' + e.airport : ''}</b></div><div>registration <b>${esc(st.registration || '-')}</b></div><div>type <b>${esc(e.type_name || st.aircraft_type || '-')}</b></div><div>altitude <b>${num(st.baro_alt_ft)} ft</b></div><div>speed <b>${num(st.gs_kt)} kt</b></div><div>track <b>${num(st.track_deg)}°</b></div><div>v/s <b>${num(st.vrate_fpm)} fpm</b></div><div>squawk <b>${esc(st.squawk || '-')}</b></div><div>source <b>${esc(st.position_source || '-')}</b></div><div>NIC/NACp/SIL <b>${st.nic ?? '-'}/${st.nac_p ?? '-'}/${st.sil ?? '-'}</b></div><div>trust <b class="${d.trust < .5 ? 'bad' : 'ok'}">${d.trust}</b></div></div>
<div class="row"><a class="btn small" href="#/findings?q=${icao}">All findings</a><button class="small" onclick="LivePage.zoomTo('${icao}')">Zoom</button></div><h3>Findings (${d.findings.length})</h3>${fs}`;
    document.getElementById('drawer').style.display = 'block';
  }
  function closeDrawer() { document.getElementById('drawer').style.display = 'none'; selected = null; if (trail) { map.removeLayer(trail); trail = null; } layer && layer._draw(); }
  function focusAc(icao) { if (!icao || !S) return; const a = S.aircraft.find(x => x.icao24 === icao); if (a) map.panTo([a.lat, a.lon]); select(icao); }
  function zoomTo(icao) { const a = S && S.aircraft.find(x => x.icao24 === icao); if (a) map.setView([a.lat, a.lon], Math.max(map.getZoom(), 9)); }
  const sc = (k, s) => s.kpis.by_severity[k] || 0;
  function kpis(s) { const k = s.kpis; const comp = k.compliance == null ? 'n/a' : (k.compliance * 100).toFixed(1) + '%'; const ch = sc('critical', s) + sc('high', s);
    const tiles = [[k.tracked, 'aircraft now', HELP.tracked, 'c-blue'], [k.airborne, 'airborne', HELP.airborne, 'c-teal'], [k.unique_aircraft, 'seen total', HELP.seen, 'c-violet'], [k.findings_total, 'findings', HELP.findings, 'c-amber'],
      [ch, 'critical + high', HELP.ch, ch ? 'c-red' : 'c-green'], [sc('medium', s), 'medium', HELP.med, 'c-amber'], [comp, 'integrity compliance', HELP.comp, k.compliance == null ? 'c-grey' : (k.compliance >= .98 ? 'c-green' : 'c-amber')], [k.low_trust.length, 'low trust', HELP.lt, k.low_trust.length ? 'c-purple' : 'c-green']];
    document.getElementById('lkpis').innerHTML = tiles.map(([v, l, h, c]) => `<div class="tile ${c}" title="${esc(h)}"><b>${v}</b><span>${l}</span></div>`).join(''); }
  function legend() { document.getElementById('llegend').innerHTML = `<div class="lgmode">colour by ${Object.keys(MODES).map(k => `<a href="#" data-m="${k}" class="${k === mode ? 'on' : ''}">${MODES[k].label}</a>`).join(' ')}</div>` + MODES[mode].legend.map(([c, l]) => `<i style="background:${c}"></i>${l} `).join('') + `<i style="border:2px solid #ff5cf0;background:none"></i>injected <i style="border:2px solid #ff4d4f;background:none"></i>emergency`; }
  function row(f) { return `<div class="f s-${f.severity} ${f.injected ? 'inj' : ''}" onclick="LivePage.focus('${f.icao24 || ''}')"><span class="sev ${f.severity}">${f.severity}</span><span class="t">${f.rule} · ${esc(f.callsign || f.icao24 || '-')}<small>${esc(f.title)}</small>${f.playbook ? `<small>→ ${esc(f.playbook)}</small>` : ''}</span><span class="r">${fmtTs(f.ts)}<br>risk ${f.risk}</span></div>`; }
  function spark(pts, w = 410, h = 56) { if (pts.length < 2) return ''; const ys = pts.map(p => p.n); const mx = Math.max(...ys) || 1, mn = Math.min(...ys); const path = pts.map((p, i) => `${(i / (pts.length - 1)) * w},${h - ((p.n - mn) / (mx - mn || 1)) * (h - 8) - 4}`).join(' '); return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${path}" fill="none" stroke="#4ecdc4" stroke-width="1.5"/></svg><div class="note">aircraft per poll: min ${mn}, max ${mx}, last ${ys[ys.length - 1]}</div>`; }
  const ev = (s, ids) => s.events.filter(f => ids.includes(f.rule));
  const P = {
    feed(s) { const inj = s.injections.length ? `<div class="note" style="color:#ffb3fa;margin-bottom:6px">active injections: ${s.injections.map(i => i.kind + (i.icao24 ? ' → ' + i.icao24 : '') + ' (' + i.remaining + ' polls left)').join('; ')}</div>` : '';
      return inj + `<h3>Latest findings</h3>${s.events.slice(0, 25).map(row).join('') || '<div class="note">none yet: the rules fire as polls arrive</div>'}<h3>Highest risk this session</h3>${s.ranked.slice(0, 15).map(row).join('')}`; },
    safety(s) { const em = s.kpis.emergencies; const met = s.metars.length ? `<h3>Weather (METAR)</h3><table>${s.metars.map(m => `<tr><td>${m.station}</td><td>wind ${m.wind} kt</td><td>vis ${m.visib}</td><td>${m.cover || ''}</td><td>${m.temp}°C</td></tr>`).join('')}</table>` : '<h3>Weather</h3><div class="note">no METAR (replay mode, or stations unavailable)</div>';
      return `<h3>Emergency / interference codes now (${em.length})</h3>${em.length ? em.map(a => `<div class="f s-critical" onclick="LivePage.focus('${a.icao24}')"><span class="sev critical">${a.squawk}</span><span class="t">${esc(a.callsign || a.icao24)}<small>${num(a.alt)} ft · ${num(a.gs)} kt · ${a.src}</small></span><span class="r">trust ${a.trust}</span></div>`).join('') : '<div class="note ok">none: no 7500 / 7600 / 7700 in the current picture</div>'}
<h3>Separation screen (SAF-004)</h3>${ev(s, ['SAF-004']).slice(0, 8).map(row).join('') || '<div class="note">no pairs inside 3 nm / 900 ft above 3,000 ft</div>'}
<h3>Vertical profile (SAF-003, OPS-004)</h3>${ev(s, ['SAF-003', 'OPS-004']).slice(0, 8).map(row).join('') || '<div class="note">none</div>'}
<h3>Emergency squawks this session</h3>${ev(s, ['SEC-001', 'SEC-002', 'SEC-003', 'SEC-004']).slice(0, 6).map(row).join('') || '<div class="note">none</div>'}${met}`; },
    security(s) { const k = s.kpis, rc = k.by_rule, lt = k.low_trust; const stream = (rc['SEC-016'] || rc['SEC-017']) ? `<div class="f s-high"><span class="sev high">stream</span><span class="t">address bursts: ${rc['SEC-016'] || 0} · coverage collapses: ${rc['SEC-017'] || 0}</span><span class="r"></span></div>` : '<div class="note ok">no address burst or coverage collapse this session</div>';
      return `<h3>Spoofing / injection indicators</h3>${ev(s, ['SEC-010', 'SEC-011', 'SEC-014', 'SEC-015', 'SEC-018']).slice(0, 10).map(row).join('') || '<div class="note ok">none: kinematics consistent for every tracked aircraft</div>'}
<h3>Stream health</h3>${stream}<h3>Integrity (SEC-012)</h3><div class="note">compliance ${k.compliance == null ? 'n/a on this feed' : (k.compliance * 100).toFixed(1) + '% of ' + k.compliance_fixes + ' airborne ADS-B fixes'} · ${rc['SEC-012'] || 0} aircraft below 91.227 minimums</div>
<h3>Low-trust aircraft (${lt.length})</h3>${lt.length ? `<table><tr><th>icao</th><th>trust</th><th>findings</th></tr>${lt.map(r => `<tr class="click" onclick="LivePage.focus('${r[0]}')"><td>${r[0]}</td><td>${r[1].toFixed(2)}</td><td>${r[2]}</td></tr>`).join('')}</table>` : '<div class="note">none below 0.5</div>'}
<h3>Identity (SEC-013, SEC-020)</h3>${ev(s, ['SEC-013', 'SEC-020']).slice(0, 6).map(row).join('') || '<div class="note">none</div>'}`; },
    ops(s) { const rc = s.kpis.by_rule, imp = slow.impact; const regions = [...new Set(s.counts.map(c => c.region))];
      return `<h3>Holding (OPS-002) and its cost</h3>${imp ? `<div class="kpi-row"><div class="tile c-amber"><b>${imp.holds}</b><span>holds</span></div><div class="tile c-amber"><b>${imp.observed_minutes}</b><span>minutes</span></div><div class="tile c-teal"><b>${imp.fuel_kg}</b><span>kg fuel</span></div><div class="tile c-teal"><b>${(imp.co2_kg / 1000).toFixed(1)} t</b><span>CO2</span></div><div class="tile c-red"><b>€${imp.delay_cost}</b><span>delay cost</span></div></div><div class="note">observed minutes are a floor; defaults 40 kg/min, 3.16 kg CO2/kg, €100/min</div>` : ''}
${ev(s, ['OPS-002']).slice(0, 6).map(row).join('')}<h3>Airspace density</h3><div class="note">pattern work / low orbits (OPS-003): ${rc['OPS-003'] || 0} · coverage gaps (OPS-001): ${rc['OPS-001'] || 0} · VFR code above FL180 (OPS-005): ${rc['OPS-005'] || 0}</div>
<h3>Traffic per poll</h3>${regions.slice(0, 8).map(r => `<div class="note"><b>${r}</b></div>` + spark(s.counts.filter(c => c.region === r))).join('') || '<div class="note">waiting for data</div>'}
<h3>Feed health</h3><div class="note">${s.provider} · ${s.batches} polls · data age ${s.feed_latency_ms == null ? 'n/a' : (s.feed_latency_ms / 1000).toFixed(0) + ' s'} · last poll ${s.last_ingest_age_s ?? '-'} s ago${s.errors.length ? '<br><span class="bad">' + esc(s.errors[s.errors.length - 1]) + '</span>' : ''}</div>`; }
  };
  function renderPanel() { if (!S) return; const p = document.getElementById('lpanel'); if (p) p.innerHTML = P[tab](S); }
  async function slowRefresh() { const t = Date.now(); if (t - slow.at < 20000) return; slow.at = t; try { slow.impact = await (await fetch('/api/v1/impact')).json(); } catch (e) {} }

  window.LivePage = {
    render(el) {
      el.innerHTML = `<div class="live"><div class="kpis" id="lkpis"></div>
<div class="mapwrap"><div id="map"></div><div id="ltip" class="ltip" hidden></div><div id="drawer"><span class="x" onclick="LivePage.closeDrawer()">✕</span><div id="drawerBody"></div></div>
<div class="legend" id="llegend"></div><div class="whatis" id="lwhat" hidden><b>What am I looking at?</b> Every arrow is an aircraft from the feed, pointing along its track. Colour shows the worst finding on that aircraft in the last 10 minutes (switch to altitude, speed or trust in the legend). Hover for details, click for the full record and playbook steps. Rings: red = emergency code, magenta = demo injection, white = selected.<br><a href="#" id="lwhatx">got it</a></div><button class="qbtn" id="lq" title="What am I looking at?">?</button></div>
<aside><div class="demo" id="ldemo" hidden><span class="lbl">DEMO · inject an attack into the stream and watch detection (click an aircraft first to target it)</span>
<button data-k="teleport" title="Shift the target 30 nm north from the next poll">Teleport 30 nm</button><button data-k="squawk_7500" class="danger" title="Hijack code on the target: unconfirmed on the first poll, critical on the second">Squawk 7500</button>
<button data-k="altitude_forge" title="Altitude +6,000 ft with the vertical rate untouched">Altitude +6,000 ft</button><button data-k="velocity_forge" title="Reported speed halved">Speed halved</button>
<button data-k="ghost_jumpy" title="Fabricated aircraft that jumps 20 nm every third poll">Ghost (jumpy)</button><button data-k="ghost_perfect" title="Fabricated aircraft with consistent physics: nothing fires (known gap)">Ghost (perfect)</button>
<button data-k="flood" title="Sixty never-seen addresses at once">Flood</button><button data-k="collapse" title="60% of the picture vanishes for two polls">Collapse</button><button id="lclear" class="ghost small">Clear</button></div>
<div class="tabs" id="ltabs"><div data-t="feed" class="on">Findings</div><div data-t="safety">Safety</div><div data-t="security">Security</div><div data-t="ops">Operations</div></div><div class="panel" id="lpanel"></div></aside></div>`;
      map = null; layer = null; trail = null; selected = null;
      el.querySelector('#ltabs').addEventListener('click', e => { const d = e.target.closest('div[data-t]'); if (!d) return; tab = d.dataset.t; [...el.querySelectorAll('#ltabs div')].forEach(x => x.classList.toggle('on', x === d)); renderPanel(); });
      el.querySelector('#llegend').addEventListener('click', e => { const a = e.target.closest('a[data-m]'); if (!a) return; e.preventDefault(); mode = a.dataset.m; legend(); layer && layer._draw(); });
      el.querySelector('#lq').onclick = () => { el.querySelector('#lwhat').hidden = false; }; el.querySelector('#lwhatx').onclick = e => { e.preventDefault(); el.querySelector('#lwhat').hidden = true; };
      el.querySelector('#ldemo').addEventListener('click', async e => { const b = e.target.closest('button'); if (!b) return;
        if (b.id === 'lclear') { await fetch('/api/v1/clear', {method: 'POST'}); return; }
        const body = {kind: b.dataset.k}; if (selected && ['teleport', 'squawk_7500', 'altitude_forge', 'velocity_forge'].includes(b.dataset.k)) body.icao24 = selected;
        const r = await fetch('/api/v1/inject', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)}); const j = await r.json();
        if (j.error) window.App.toast(j.error); else { window.App.toast('Injected: ' + j.label); if (j.icao24) setTimeout(() => focusAc(j.icao24), 1500); } });
      legend();
    },
    update(s) { S = s; if (!s || s.active === false) return; if (!map) { initMap(s.center); requestAnimationFrame(() => map && map.invalidateSize()); } document.getElementById('ldemo').hidden = !s.demo; kpis(s); layer.setData(s.aircraft); slowRefresh().then(renderPanel); renderPanel(); },
    focus: focusAc, zoomTo, closeDrawer, goto(lat, lon, z) { if (map) map.setView([lat, lon], z || 8); }, destroy() { map = null; layer = null; trail = null; selected = null; }
  };
})();
