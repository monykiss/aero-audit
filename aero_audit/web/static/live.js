/* Live picture page: map + KPIs + side panels + demo controls. Exposes window.LivePage. */
(function () {
  const PLANE = '<svg viewBox="0 0 24 24" class="CLS" style="transform:rotate(ROTdeg)"><path d="M12 2l2 7 8 4v2l-8-2v5l3 2v2l-5-1-5 1v-2l3-2v-5l-8 2v-2l8-4z"/></svg>';
  let map = null, markers = {}, trail = null, selected = null, tab = 'feed', S = null, slow = {at: 0, impact: null, risk: null};
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const fmtTs = t => t ? new Date(t * 1000).toISOString().substr(11, 8) + 'Z' : '-';
  const num = (v, d = 0) => (v === null || v === undefined || isNaN(v)) ? '-' : Number(v).toFixed(d);
  const HELP = {
    tracked: 'Aircraft in the latest poll of the active region', airborne: 'Tracked aircraft not on the ground', seen: 'Unique aircraft since the source started',
    findings: 'Every finding this session (rules + model)', ch: 'Critical and high severity findings this session', med: 'Medium severity findings',
    comp: 'Share of airborne ADS-B fixes meeting NIC>=7, NACp>=8, SIL=3 (14 CFR 91.227). n/a when the feed lacks integrity fields', lt: 'Aircraft whose trust score fell below 0.5'
  };

  function planeIcon(a) {
    let cls = 'pl-normal'; if (a.ground) cls = 'pl-ground'; else if (a.sev) cls = 'pl-' + a.sev; if (a.trust < 0.5) cls = 'pl-lowtrust';
    const extra = (a.injected ? ' pl-injected' : '') + (a.emergency ? ' pl-emerg' : '');
    return L.divIcon({className: 'plane', html: PLANE.replace('CLS', cls + extra).replace('ROT', a.track || 0), iconSize: [22, 22], iconAnchor: [11, 11]});
  }
  function initMap(c) {
    map = L.map('map', {zoomControl: true}).setView(c || [40.7, -74], 7);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 12, className: 'dark-tiles', attribution: '&copy; OpenStreetMap contributors'}).addTo(map);
  }
  function updateMap(ac) {
    const seen = new Set();
    for (const a of ac) {
      seen.add(a.icao24); let m = markers[a.icao24]; const ll = [a.lat, a.lon];
      if (!m) { m = L.marker(ll, {icon: planeIcon(a)}).addTo(map); m.on('click', () => select(a.icao24)); markers[a.icao24] = m; }
      else { m.setLatLng(ll); m.setIcon(planeIcon(a)); }
      m.bindTooltip(`${a.callsign || a.icao24} · ${num(a.alt)} ft · ${num(a.gs)} kt${a.sev ? ' · ' + a.sev.toUpperCase() : ''}${a.injected ? ' · INJECTED' : ''}`, {direction: 'top', offset: [0, -8]});
    }
    for (const k of Object.keys(markers)) if (!seen.has(k)) { map.removeLayer(markers[k]); delete markers[k]; }
  }
  async function select(icao) {
    selected = icao; const r = await fetch('/api/v1/aircraft/' + icao); if (!r.ok) return; const d = await r.json(); const st = d.state || {};
    if (trail) { map.removeLayer(trail); trail = null; }
    if (d.trail.length > 1) trail = L.polyline(d.trail.map(p => [p.lat, p.lon]), {color: d.injected ? '#ff5cf0' : '#4ea1ff', weight: 2, opacity: .8, dashArray: d.injected ? '4 4' : null}).addTo(map);
    const fs = d.findings.map(f => `<div class="f ${f.injected ? 'inj' : ''}"><span class="sev ${f.severity}">${f.severity}</span><span class="t">${f.rule} ${esc(f.title)}<small>${fmtTs(f.ts)} · risk ${f.risk} · ×${f.occurrences}${f.playbook ? ' · ' + esc(f.playbook) : ''}</small></span><span class="r"></span></div>`).join('') || '<div class="note">no findings for this aircraft</div>';
    document.getElementById('drawerBody').innerHTML = `<h2>${esc(st.callsign || '')} <span class="note">${icao}${d.injected ? ' · <span style="color:#ff5cf0">INJECTED</span>' : ''}</span></h2>
<div class="kv"><div>registration <b>${esc(st.registration || '-')}</b></div><div>type <b>${esc(st.aircraft_type || '-')}</b></div><div>altitude <b>${num(st.baro_alt_ft)} ft</b></div><div>speed <b>${num(st.gs_kt)} kt</b></div><div>track <b>${num(st.track_deg)}°</b></div><div>v/s <b>${num(st.vrate_fpm)} fpm</b></div><div>squawk <b>${esc(st.squawk || '-')}</b></div><div>source <b>${esc(st.position_source || '-')}</b></div><div>NIC/NACp/SIL <b>${st.nic ?? '-'}/${st.nac_p ?? '-'}/${st.sil ?? '-'}</b></div><div>trust <b>${d.trust}</b></div></div>
<div class="row"><a class="btn small" href="#/findings?q=${icao}">All findings</a></div><h3>Findings (${d.findings.length})</h3>${fs}`;
    document.getElementById('drawer').style.display = 'block';
  }
  function closeDrawer() { document.getElementById('drawer').style.display = 'none'; selected = null; if (trail) { map.removeLayer(trail); trail = null; } }
  function focusAc(icao) { if (!icao) return; const m = markers[icao]; if (m) map.panTo(m.getLatLng()); select(icao); }
  const sc = (k, s) => s.kpis.by_severity[k] || 0;
  function kpis(s) {
    const k = s.kpis; const comp = k.compliance == null ? 'n/a' : (k.compliance * 100).toFixed(1) + '%';
    document.getElementById('lkpis').innerHTML = [[k.tracked, 'aircraft now', HELP.tracked], [k.airborne, 'airborne', HELP.airborne], [k.unique_aircraft, 'seen total', HELP.seen], [k.findings_total, 'findings', HELP.findings],
      [sc('critical', s) + sc('high', s), 'critical + high', HELP.ch], [sc('medium', s), 'medium', HELP.med], [comp, 'integrity compliance', HELP.comp], [k.low_trust.length, 'low trust', HELP.lt]]
      .map(([v, l, h]) => `<div class="tile" title="${esc(h)}"><b>${v}</b><span>${l}</span></div>`).join('');
  }
  function row(f) { return `<div class="f ${f.injected ? 'inj' : ''}" onclick="LivePage.focus('${f.icao24 || ''}')"><span class="sev ${f.severity}">${f.severity}</span><span class="t">${f.rule} · ${esc(f.callsign || f.icao24 || '-')}<small>${esc(f.title)}</small>${f.playbook ? `<small>→ ${esc(f.playbook)}</small>` : ''}</span><span class="r">${fmtTs(f.ts)}<br>risk ${f.risk}</span></div>`; }
  function spark(pts, w = 410, h = 56) { if (pts.length < 2) return ''; const ys = pts.map(p => p.n); const mx = Math.max(...ys) || 1, mn = Math.min(...ys); const path = pts.map((p, i) => `${(i / (pts.length - 1)) * w},${h - ((p.n - mn) / (mx - mn || 1)) * (h - 8) - 4}`).join(' '); return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${path}" fill="none" stroke="#4ea1ff" stroke-width="1.5"/></svg><div class="note">aircraft per poll: min ${mn}, max ${mx}, last ${ys[ys.length - 1]}</div>`; }
  const ev = (s, ids) => s.events.filter(f => ids.includes(f.rule));
  const P = {
    feed(s) { const inj = s.injections.length ? `<div class="note" style="color:#ffb3fa;margin-bottom:6px">active injections: ${s.injections.map(i => i.kind + (i.icao24 ? ' → ' + i.icao24 : '') + ' (' + i.remaining + ' polls left)').join('; ')}</div>` : '';
      return inj + `<h3>Latest findings</h3>${s.events.slice(0, 25).map(row).join('') || '<div class="note">none yet: the rules fire as polls arrive</div>'}<h3>Highest risk this session</h3>${s.ranked.slice(0, 15).map(row).join('')}`; },
    safety(s) { const em = s.kpis.emergencies; const met = s.metars.length ? `<h3>Weather (METAR)</h3><table>${s.metars.map(m => `<tr><td>${m.station}</td><td>wind ${m.wind} kt</td><td>vis ${m.visib}</td><td>${m.cover || ''}</td><td>${m.temp}°C</td></tr>`).join('')}</table>` : '<h3>Weather</h3><div class="note">no METAR (replay mode, or stations unavailable)</div>';
      return `<h3>Emergency / interference codes now (${em.length})</h3>${em.length ? em.map(a => `<div class="f" onclick="LivePage.focus('${a.icao24}')"><span class="sev critical">${a.squawk}</span><span class="t">${esc(a.callsign || a.icao24)}<small>${num(a.alt)} ft · ${num(a.gs)} kt · ${a.src}</small></span><span class="r">trust ${a.trust}</span></div>`).join('') : '<div class="note ok">none: no 7500 / 7600 / 7700 in the current picture</div>'}
<h3>Separation screen (SAF-004)</h3>${ev(s, ['SAF-004']).slice(0, 8).map(row).join('') || '<div class="note">no pairs inside 3 nm / 900 ft above 3,000 ft</div>'}
<h3>Vertical profile (SAF-003, OPS-004)</h3>${ev(s, ['SAF-003', 'OPS-004']).slice(0, 8).map(row).join('') || '<div class="note">none</div>'}
<h3>Emergency squawks this session</h3>${ev(s, ['SEC-001', 'SEC-002', 'SEC-003', 'SEC-004']).slice(0, 6).map(row).join('') || '<div class="note">none</div>'}${met}`; },
    security(s) { const k = s.kpis, rc = k.by_rule, lt = k.low_trust; const stream = (rc['SEC-016'] || rc['SEC-017']) ? `<div class="f"><span class="sev high">stream</span><span class="t">address bursts: ${rc['SEC-016'] || 0} · coverage collapses: ${rc['SEC-017'] || 0}</span><span class="r"></span></div>` : '<div class="note ok">no address burst or coverage collapse this session</div>';
      return `<h3>Spoofing / injection indicators</h3>${ev(s, ['SEC-010', 'SEC-011', 'SEC-014', 'SEC-015', 'SEC-018']).slice(0, 10).map(row).join('') || '<div class="note ok">none: kinematics consistent for every tracked aircraft</div>'}
<h3>Stream health</h3>${stream}<h3>Integrity (SEC-012)</h3><div class="note">compliance ${k.compliance == null ? 'n/a on this feed' : (k.compliance * 100).toFixed(1) + '% of ' + k.compliance_fixes + ' airborne ADS-B fixes'} · ${rc['SEC-012'] || 0} aircraft below 91.227 minimums</div>
<h3>Low-trust aircraft (${lt.length})</h3>${lt.length ? `<table><tr><th>icao</th><th>trust</th><th>findings</th></tr>${lt.map(r => `<tr class="click" onclick="LivePage.focus('${r[0]}')"><td>${r[0]}</td><td>${r[1].toFixed(2)}</td><td>${r[2]}</td></tr>`).join('')}</table>` : '<div class="note">none below 0.5</div>'}
<h3>Identity (SEC-013, SEC-020)</h3>${ev(s, ['SEC-013', 'SEC-020']).slice(0, 6).map(row).join('') || '<div class="note">none</div>'}`; },
    ops(s) { const rc = s.kpis.by_rule, imp = slow.impact; const regions = [...new Set(s.counts.map(c => c.region))];
      return `<h3>Holding (OPS-002) and its cost</h3>${imp ? `<div class="kpi-row"><div class="tile"><b>${imp.holds}</b><span>holds</span></div><div class="tile"><b>${imp.observed_minutes}</b><span>minutes</span></div><div class="tile"><b>${imp.fuel_kg}</b><span>kg fuel</span></div><div class="tile"><b>${(imp.co2_kg / 1000).toFixed(1)} t</b><span>CO2</span></div><div class="tile"><b>€${imp.delay_cost}</b><span>delay cost</span></div></div><div class="note">observed minutes are a floor; defaults 40 kg/min, 3.16 kg CO2/kg, €100/min</div>` : ''}
${ev(s, ['OPS-002']).slice(0, 6).map(row).join('')}<h3>Airspace density</h3><div class="note">pattern work / low orbits (OPS-003): ${rc['OPS-003'] || 0} · coverage gaps (OPS-001): ${rc['OPS-001'] || 0} · VFR code above FL180 (OPS-005): ${rc['OPS-005'] || 0}</div>
<h3>Traffic per poll</h3>${regions.map(r => `<div class="note"><b>${r}</b></div>` + spark(s.counts.filter(c => c.region === r))).join('') || '<div class="note">waiting for data</div>'}
<h3>Feed health</h3><div class="note">${s.provider} · ${s.batches} polls · data age ${s.feed_latency_ms == null ? 'n/a' : (s.feed_latency_ms / 1000).toFixed(0) + ' s'} · last poll ${s.last_ingest_age_s ?? '-'} s ago${s.errors.length ? '<br><span class="bad">' + esc(s.errors[s.errors.length - 1]) + '</span>' : ''}</div>`; }
  };
  function renderPanel() { if (!S) return; const p = document.getElementById('lpanel'); if (p) p.innerHTML = P[tab](S); }
  async function slowRefresh() { const t = Date.now(); if (t - slow.at < 20000) return; slow.at = t; try { slow.impact = await (await fetch('/api/v1/impact')).json(); } catch (e) {} }

  window.LivePage = {
    render(el, app) {
      el.innerHTML = `<div class="live"><div class="kpis" id="lkpis"></div>
<div class="mapwrap"><div id="map"></div><div id="drawer"><span class="x" onclick="LivePage.closeDrawer()">✕</span><div id="drawerBody"></div></div>
<div class="legend"><i style="background:#7fb3ff"></i>normal <i style="background:#ffc53d"></i>medium <i style="background:#ff4d4f"></i>high/critical <i style="background:#b47bff"></i>low trust <i style="background:#5a6472"></i>ground <i style="border:2px solid #ff5cf0;background:none"></i>injected</div></div>
<aside><div class="demo" id="ldemo" hidden><span class="lbl">DEMO · inject an attack into the stream and watch detection (select an aircraft first to target it)</span>
<button data-k="teleport" title="Shift the target 30 nm north from the next poll">Teleport 30 nm</button><button data-k="squawk_7500" class="danger" title="Hijack code on the target: unconfirmed on the first poll, critical on the second">Squawk 7500</button>
<button data-k="altitude_forge" title="Altitude +6,000 ft with the vertical rate untouched">Altitude +6,000 ft</button><button data-k="velocity_forge" title="Reported speed halved">Speed halved</button>
<button data-k="ghost_jumpy" title="Fabricated aircraft that jumps 20 nm every third poll">Ghost (jumpy)</button><button data-k="ghost_perfect" title="Fabricated aircraft with consistent physics: nothing fires (known gap)">Ghost (perfect)</button>
<button data-k="flood" title="Sixty never-seen addresses at once">Flood</button><button data-k="collapse" title="60% of the picture vanishes for two polls">Collapse</button><button id="lclear" class="ghost small">Clear</button></div>
<div class="tabs" id="ltabs"><div data-t="feed" class="on">Findings</div><div data-t="safety">Safety</div><div data-t="security">Security</div><div data-t="ops">Operations</div></div><div class="panel" id="lpanel"></div></aside></div>`;
      map = null; markers = {}; trail = null; selected = null;
      el.querySelector('#ltabs').addEventListener('click', e => { const d = e.target.closest('div[data-t]'); if (!d) return; tab = d.dataset.t; [...el.querySelectorAll('#ltabs div')].forEach(x => x.classList.toggle('on', x === d)); renderPanel(); });
      el.querySelector('#ldemo').addEventListener('click', async e => { const b = e.target.closest('button'); if (!b) return;
        if (b.id === 'lclear') { await fetch('/api/v1/clear', {method: 'POST'}); return; }
        const body = {kind: b.dataset.k}; if (selected && ['teleport', 'squawk_7500', 'altitude_forge', 'velocity_forge'].includes(b.dataset.k)) body.icao24 = selected;
        const r = await fetch('/api/v1/inject', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)}); const j = await r.json();
        if (j.error) window.App.toast(j.error); else { window.App.toast('Injected: ' + j.label); if (j.icao24) setTimeout(() => focusAc(j.icao24), 1500); } });
    },
    update(s) { S = s; if (!s || s.active === false) return; if (!map) initMap(s.center); document.getElementById('ldemo').hidden = !s.demo; kpis(s); updateMap(s.aircraft); slowRefresh().then(renderPanel); renderPanel(); },
    focus: focusAc, closeDrawer, destroy() { map = null; markers = {}; trail = null; selected = null; }
  };
})();
