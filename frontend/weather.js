/* REAL WEATHER (Open-Meteo via the backend) — a first-class data source.
 * One module feeds: the persistent weather strip in the app shell, the map overlay, the Command Center situation
 * panel, the Incident Simulator's weather chain and the AI Recovery hand-off.
 * States: LIVE · STALE (last good reading kept and labelled) · UNAVAILABLE (nothing is invented) · REPLAY (recorded file).
 * Every value displayed here comes from /api/weather; the client never produces a weather number. */
"use strict";
const WX = (() => {
  let data = null, timer = null, tick = null, recvAt = 0, open = false, failedLoads = 0, diag = null, diagBusy = false, sel = null, selData = null;
  const KIND = { LIVE: "live", STALE: "mock", REPLAY: "replay", UNAVAILABLE: "static" };
  const LVL_CLASS = { CALM: "ok", MODERATE: "info", SEVERE: "warn", EXTREME: "bad" };
  const fmt1 = (v) => (v == null ? "—" : Number(v).toFixed(1));
  const nm = (id) => (id && NODE[id] ? id : id || "—");
  const chip = () => { const m = data && data.meta; return m ? dm(KIND[m.status] || "static", m.status === "UNAVAILABLE" ? "Weather · unavailable" : `Weather · ${m.status}`) : ""; };

  /* age in minutes, ticking client-side between fetches */
  const ageMin = () => { const m = data && data.meta; if (!m || m.age_min == null) return null; return m.age_min + (performance.now() - recvAt) / 60000; };
  const ageText = () => { const a = ageMin(); if (a == null) return "never"; if (a < 1) return "just now"; if (a < 90) return `${Math.round(a)} min ago`; return `${(a / 60).toFixed(1)} h ago`; };

  async function load() {
    try { data = await api("/api/weather"); recvAt = performance.now(); failedLoads = 0; }
    catch { failedLoads++; if (!data) { data = { meta: { status: "UNAVAILABLE", error: "The twin API did not answer", age_min: null, points: 0 }, summary: null, hazards: [], chain: null, cells: [] }; recvAt = performance.now(); } else { data.meta.status = "STALE"; data.meta.error = "The twin API did not answer"; } }
    emit("weather", data);
    try { TWIN.ready.then(() => TWIN.setWeather(data.cells)); } catch { /* map not ready */ }
    draw();
  }

  /* ---------------------------------------------------------------- forecast timeline (from summary.timeline) */
  function bars(tl, { h = 22, w = 4, gap = 2 } = {}) {
    if (!tl || !tl.length) return "";
    const W = tl.length * (w + gap) - gap;
    const col = (l) => ({ CALM: "var(--green)", MODERATE: "var(--primary)", SEVERE: "var(--amber)", EXTREME: "var(--red)" }[l]);
    return `<svg class="wx-bars" viewBox="0 0 ${W} ${h}" width="${W}" height="${h}" preserveAspectRatio="none" role="img" aria-label="Worst weather severity anywhere on the network, next 48 hours">${tl.map((t, i) => {
      const bh = Math.max(2, Math.round(t.sev * (h - 2)) + 2);
      return `<rect x="${i * (w + gap)}" y="${h - bh}" width="${w}" height="${bh}" fill="${col(t.level)}" opacity="${t.level === "CALM" ? 0.45 : 1}"><title>+${t.h} h · ${t.level.toLowerCase()} · ${t.affected} facilities</title></rect>`; }).join("")}</svg>`;
  }

  /* ---------------------------------------------------------------- persistent strip */
  function stripHTML() {
    const m = data.meta, s = data.summary, st = m.status;
    const stCls = { LIVE: "ok", STALE: "warn", UNAVAILABLE: "bad", REPLAY: "info" }[st] || "neutral";
    const state = `<span class="wx-state ${stCls}"><i class="dot ${stCls === "info" ? "" : stCls}"></i>${st === "UNAVAILABLE" ? "Unavailable" : st}</span>${m.provider && st !== "UNAVAILABLE" ? `<span class="wx-prov">${esc(m.provider)}</span>` : ""}`;
    const label = `<span class="wx-k">Weather</span>${state}`;
    if (st === "UNAVAILABLE" || !s) {
      return `<div class="wx-row">${label}<span class="wx-msg">Live weather could not be retrieved${Object.keys(m.provider_errors || {}).length ? ` from ${Object.keys(m.provider_errors).map(esc).join(" or ")}` : ""}. Excluded from resilience, routes and ETAs until it returns.</span>
        <span class="wx-sp"></span><button class="wx-btn" id="wxMore" aria-expanded="${open}" aria-controls="wxPop">Why?</button><button class="wx-btn" id="wxRefresh" aria-label="Retry weather feed">${ico("refresh", 13)} Retry</button></div>`;
    }
    const lvl = s.level_worst, worstCls = LVL_CLASS[lvl];
    const stale = st === "STALE" ? ` <span class="wx-stale">last reading ${esc(m.fetched_label || "")} · ${ageText()}${m.error ? ` · refresh failing` : ""}</span>` : "";
    const cell = (k, v, sub = "") => `<span class="wx-c"><span class="wx-ck">${k}</span><b>${v}</b>${sub ? `<em>${sub}</em>` : ""}</span>`;
    return `<div class="wx-row">${label}${stale}
      <span class="wx-c temp"><span class="wx-ck">Temp</span><b>${Math.round(s.temp_mean)}°C</b></span>
      ${cell("Rain", `${fmt1(s.precip_max_mm_h)} mm/h`, `peak ${esc(nm(s.precip_at))}`)}
      ${cell("Gusts", `${s.gust_max_kmh} km/h`)}
      <span class="wx-c wsev ${worstCls}"><span class="wx-ck">Severity</span><b>${lvl.toLowerCase()}</b><em>at ${esc(nm(s.worst_at))}</em></span>
      <span class="wx-c affects"><span class="wx-ck">Affected</span><b>${s.nodes_affected} <small>facilities</small></b><em>${s.corridors_at_risk} corridors · ${s.shipments_delayed} shipments</em></span>
      ${s.wave_max_m != null ? cell("Waves", `${fmt1(s.wave_max_m)} m`, esc(nm(s.wave_at))) : ""}
      ${m.alerts ? `<span class="wx-c alerts"><span class="wx-ck">Alerts</span><b>${m.alerts}</b><em>hazards in region</em></span>` : ""}
      <span class="wx-c wfc"><span class="wx-ck">48 h</span>${bars(s.timeline)}</span>
      <span class="wx-c upd" title="${esc(m.fetched_label || "")}"><span class="wx-ck">Updated</span><b>${ageText()}</b></span>
      <span class="wx-sp"></span>
      <button class="wx-btn" id="wxMore" aria-expanded="${open}" aria-controls="wxPop">Details ${ico(open ? "up" : "down", 12)}</button>
      <button class="wx-btn" id="wxRefresh" aria-label="Refresh weather now">${ico("refresh", 13)}</button></div>`;
  }

  /* ---------------------------------------------------------------- details popover */
  /* facility forecast: temperature line, rain bars and gust line for the next 48 h, from /api/weather/point/{id} */
  function pointChart(d) {
    const H = d.hourly, W = 480, Ht = 96, n = H.length, x = (i) => (i / (n - 1)) * W;
    const tmin = Math.min(...H.map((r) => r.temp ?? 99)), tmax = Math.max(...H.map((r) => r.temp ?? -99)), tr = Math.max(1, tmax - tmin);
    const pmax = Math.max(5, ...H.map((r) => r.precip_mm_h || 0)), gmax = Math.max(60, ...H.map((r) => r.gust_kmh || 0));
    const rain = H.map((r, i) => { const h = ((r.precip_mm_h || 0) / pmax) * 40; return `<rect x="${(x(i) - 3).toFixed(1)}" y="${Ht - h}" width="5" height="${h.toFixed(1)}" fill="var(--primary)" opacity=".55"/>`; }).join("");
    const line = (key, lo, rg, col, dash = "") => `<polyline fill="none" stroke="${col}" stroke-width="1.5" ${dash ? `stroke-dasharray="${dash}"` : ""} points="${H.map((r, i) => `${x(i).toFixed(1)},${(Ht - 6 - (((r[key] ?? lo) - lo) / rg) * (Ht - 20)).toFixed(1)}`).join(" ")}"/>`;
    const sev = H.map((r, i) => r.sev >= 0.25 ? `<rect x="${(x(i) - 3).toFixed(1)}" y="0" width="6" height="4" fill="${r.sev >= 0.75 ? "var(--red)" : r.sev >= 0.5 ? "var(--amber)" : "var(--primary)"}"/>` : "").join("");
    return `<svg class="wx-pc" viewBox="0 0 ${W} ${Ht}" preserveAspectRatio="none" role="img" aria-label="48 hour forecast for ${esc(d.id)}">${rain}${line("gust_kmh", 0, gmax, "var(--amber)", "4 3")}${line("temp", tmin, tr, "var(--text)")}${sev}</svg>
      <div class="wx-pl"><span><i style="background:var(--text)"></i>Temperature ${Math.round(tmin)}–${Math.round(tmax)}°C</span><span><i style="background:var(--primary)"></i>Rain (max ${fmt1(pmax)} mm/h)</span><span><i style="background:var(--amber)"></i>Gusts (max ${Math.round(gmax)} km/h)</span><span>severity marks on top</span></div>`;
  }
  function pointHTML() {
    if (!sel) return `<p class="wx-note">Select a facility for its 48 h forecast.</p>`;
    if (!selData) return `<p class="wx-note">Loading…</p>`;
    const n = selData.now;
    const f = (k, u = "", dig = 0) => (n[k] != null ? `${Number(n[k]).toFixed(dig)}${u}` : "—");
    return `<div class="wx-pt"><b class="mono">${esc(selData.id)}</b> ${selData.name ? esc(selData.name) : ""} <span class="muted">· ${selData.lat.toFixed(2)}, ${selData.lon.toFixed(2)} · ${esc(selData.provider)}</span></div>
      <div class="wx-kv"><span>Temp <b>${f("temp", "°C", 1)}</b></span><span>Feels <b>${f("apparent_c", "°C", 1)}</b></span><span>Humidity <b>${f("humidity", "%")}</b></span><span>Pressure <b>${f("pressure_hpa", " hPa")}</b></span><span>Cloud <b>${f("cloud_pct", "%")}</b></span><span>Wind <b>${f("wind_kmh", " km/h")}${n.wind_dir != null ? ` ${Math.round(n.wind_dir)}°` : ""}</b></span><span>Visibility <b>${n.visibility_m != null ? (n.visibility_m / 1000).toFixed(1) + " km" : "—"}</b></span></div>${pointChart(selData)}`;
  }
  function diagHTML() {
    if (diagBusy) return `<p class="wx-note">Testing…</p>`;
    if (!diag) return `<button class="wx-btn" id="wxDiag">Test connection</button>`;
    return `<table class="table wx-t"><tr><th>Service</th><th>Host</th><th>Result</th><th>Detail</th></tr>${diag.results.map((r) => `<tr><td>${esc(r.name)}</td><td class="mono">${esc(r.host)}</td><td><i class="dot ${r.ok ? "ok" : "bad"}"></i>${r.ok ? `ok · ${r.ms} ms` : esc(r.kind)}</td><td class="wx-wrap">${r.ok ? "" : esc(r.error)}</td></tr>`).join("")}</table>
      ${[...new Set(diag.results.filter((r) => !r.ok).map((r) => r.hint))].map((h) => `<p class="wx-note"><b>Fix:</b> ${esc(h)}</p>`).join("")}
      <p class="wx-note">Python ${esc(diag.environment.python)} · ${esc(diag.environment.openssl)} · certifi ${diag.environment.certifi ? "installed" : "missing"}${diag.environment.proxy_env.length ? ` · proxy: ${diag.environment.proxy_env.join(", ")}` : ""}${diag.environment.insecure_ssl ? " · TLS relaxed" : ""}</p>
      <button class="wx-btn" id="wxDiag">Run again</button>`;
  }
  function alertsHTML() {
    const al = data.alerts || [], st = data.meta.alert_status || {};
    const fails = Object.entries(st).filter(([, v]) => !v.ok);
    return `${al.length ? `<table class="table wx-t"><tr><th>Source</th><th>Type</th><th>Event</th><th>Near</th></tr>${al.slice(0, 8).map((a, i) => `<tr class="click" data-a="${i}" tabindex="0"><td>${esc(a.source)}</td><td>${esc(a.type)}</td><td class="wx-wrap">${esc(a.title)}</td><td class="mono">${a.near && a.near.length ? a.near.slice(0, 2).map((x) => `${esc(x.id)} ${x.km} km`).join(", ") : "—"}</td></tr>`).join("")}</table>` : `<p class="wx-note">No earthquake, storm, flood or cyclone alert is active in the region right now.</p>`}
      ${fails.length ? `<p class="wx-note">Unreachable: ${fails.map(([k, v]) => `${esc(k)} (${esc(v.error)})`).join("; ")}.</p>` : ""}`;
  }
  function popHTML() {
    const m = data.meta, s = data.summary;
    const pe = Object.entries(m.provider_errors || {});
    const errs = pe.length ? `<p class="wx-note"><b>Provider problems:</b> ${pe.map(([k, v]) => `${esc(k)}: ${esc(v.error)}`).join("; ")}.</p>` : "";
    const diagBox = `<h3>Connection</h3>${m.status === "UNAVAILABLE" || m.status === "STALE" || m.error ? `<p class="wx-note">${esc(m.error || "")}</p>` : ""}${errs}<div id="wxDiagBox">${diagHTML()}</div>`;
    if (!s) return `<div class="wx-pop-in one"><div class="wx-col"><h3>Weather unavailable</h3>${diagBox}</div><div class="wx-col"><h3>Regional hazard alerts · ${(data.alerts || []).length}</h3>${alertsHTML()}</div></div>`;
    const tl = s.timeline;
    const axis = [0, 12, 24, 36, 48].map((h) => `<span style="left:${(h / 48) * 100}%">+${h} h</span>`).join("");
    const hz = data.hazards.slice(0, 6).map((h) => { const worst = Math.max(h.sev_now, h.peak_sev), lv = worst >= 0.75 ? "extreme" : "severe";
      return `<tr class="click" data-l="${esc(h.link)}" tabindex="0"><td><i class="dot ${lv === "extreme" ? "bad" : "warn"}"></i>${lv}</td><td class="mono">${esc(h.from)}→${esc(h.to)}</td><td>${esc(h.mode)}</td>
        <td>${h.sev_now >= 0.5 ? "now" : `+${h.peak_in_h} h`}</td><td>${esc(h.text || "rain / wind")}${h.precip_mm_h ? ` · ${fmt1(h.precip_mm_h)} mm/h` : ""}${h.gust_kmh ? ` · ${h.gust_kmh} km/h` : ""}</td><td class="num">×${h.time_factor}</td></tr>`; }).join("");
    const cells = data.cells.filter((c) => c.kind === "node").sort((a, b) => b.sev - a.sev).slice(0, 8);
    const extra = [s.humidity_mean != null ? `humidity ${s.humidity_mean}%` : "", s.pressure_mean != null ? `pressure ${s.pressure_mean} hPa` : "", s.wind_mean_kmh != null ? `wind ${s.wind_mean_kmh} km/h` : "", s.visibility_min_m != null ? `lowest visibility ${(s.visibility_min_m / 1000).toFixed(1)} km` : "", s.wave_max_m != null ? `highest port waves ${s.wave_max_m} m` : ""].filter(Boolean).join(" · ");
    return `<div class="wx-pop-in">
      <div class="wx-col">
        <h3>Forecast</h3>
        <div class="wx-tl">${bars(tl, { h: 46, w: 12, gap: 4 })}<div class="wx-axis">${axis}</div></div>
        <p class="wx-note">${extra ? `Network averages: ${extra}` : ""}</p>
        <h3>Facilities</h3>
        <table class="table wx-t"><tr><th>Facility</th><th>Level</th><th class="num">Temp</th><th class="num">Rain</th><th class="num">Gusts</th><th class="num">Hum.</th><th class="num">Peak 48 h</th></tr>${cells.map((c) => `<tr class="click ${sel === c.id ? "hl" : ""}" data-n="${esc(c.id)}" tabindex="0"><td class="mono">${esc(c.id)}</td><td><i class="dot ${c.level === "EXTREME" ? "bad" : c.level === "SEVERE" ? "warn" : c.level === "MODERATE" ? "" : "ok"}"></i>${c.level.toLowerCase()}</td>
          <td class="num">${c.temp != null ? fmt1(c.temp) + "°" : "—"}</td><td class="num">${fmt1(c.precip_mm_h)}</td><td class="num">${c.gust_kmh}</td><td class="num">${c.humidity != null ? Math.round(c.humidity) + "%" : "—"}</td><td class="num">${Math.round(c.peak48 * 100)}</td></tr>`).join("")}</table>
        <div id="wxPt" style="margin-top:10px">${pointHTML()}</div>
      </div>
      <div class="wx-col">
        <h3>Corridors at risk · ${s.corridors_at_risk}</h3>
        ${hz ? `<table class="table wx-t"><tr><th>Level</th><th>Corridor</th><th>Mode</th><th>When</th><th>Conditions</th><th class="num">Time</th></tr>${hz}</table>` : `<p class="wx-note">No corridor reaches severe level in the next 48 h.</p>`}
        <h3>Regional hazard alerts · ${(data.alerts || []).length}</h3>${alertsHTML()}
        ${diagBox}
        <h3>Source</h3>
        <p class="wx-note">${esc(data.meta.provider || data.meta.source)}${data.meta.marine_points ? ` + marine (${data.meta.marine_points} ports)` : ""} · every ${data.meta.refresh_min} min${data.meta.error ? ` · <b>${esc(data.meta.error)}</b>` : ""}.</p>
      </div></div>`;
  }

  async function runDiag() { diagBusy = true; mountShell(); try { diag = await api("/api/weather/diagnostics"); } catch (e) { diag = { results: [{ name: "Twin API", host: location.host, ok: false, kind: "other", error: e.message, hint: "The twin server did not answer." }], environment: { python: "?", openssl: "", certifi: false, proxy_env: [], insecure_ssl: false }, mode: "?" }; } diagBusy = false; mountShell(); }
  async function pickPoint(id) { sel = id; selData = null; const box = $("#wxPt"); if (box) box.innerHTML = pointHTML(); try { selData = await api(`/api/weather/point/${encodeURIComponent(id)}`); } catch { selData = null; sel = null; } const b2 = $("#wxPt"); if (b2) b2.innerHTML = pointHTML(); $$("#wxPop tr[data-n]").forEach((tr) => tr.classList.toggle("hl", tr.dataset.n === sel)); }

  function mountShell() {
    const bar = $("#wxbar"); if (!bar || !data) return;
    bar.dataset.state = data.meta.status;
    bar.innerHTML = stripHTML();
    const pop = $("#wxPop");
    pop.innerHTML = open ? popHTML() : ""; pop.hidden = !open;
    const r = $("#wxRefresh"); if (r) r.onclick = () => refresh(r);
    const more = $("#wxMore"); if (more) more.onclick = () => { open = !open; if (open && data.meta.status === "UNAVAILABLE" && !diag) runDiag(); mountShell(); };
    const dg = $("#wxDiag"); if (dg) dg.onclick = runDiag;
    $$("#wxPop tr[data-l]").forEach((tr) => { const go = () => { const h = data.hazards.find((x) => x.link === tr.dataset.l); if (h) { TWIN.highlight({ links: [h.link], nodes: [] }); } }; tr.onclick = go; tr.onkeydown = (e) => { if (e.key === "Enter") go(); }; });
    $$("#wxPop tr[data-n]").forEach((tr) => { const go = () => { pickPoint(tr.dataset.n); TWIN.select("node", tr.dataset.n, { fly: true }); }; tr.onclick = go; tr.onkeydown = (e) => { if (e.key === "Enter") go(); }; });
    $$("#wxPop tr[data-a]").forEach((tr) => { const go = () => { const a = data.alerts[+tr.dataset.a]; if (a && a.near) TWIN.highlight({ nodes: a.near.map((x) => x.id), links: [] }); }; tr.onclick = go; tr.onkeydown = (e) => { if (e.key === "Enter") go(); }; });
    document.documentElement.style.setProperty("--wxh", `${bar.offsetHeight}px`);
  }
  async function refresh(btn) {
    busy(btn, true);
    try { const r = await post("/api/weather/refresh"); await load(); toast(r.ok ? "Weather refreshed" : "Refresh failed; showing last reading", r.ok ? "ok" : "err"); }
    catch (err) { toast(err.message, "err"); }
    busy($("#wxRefresh"), false);
  }

  /* ---------------------------------------------------------------- Command Center situation panel */
  function situation() {
    const m = data.meta, s = data.summary;
    if (m.status === "UNAVAILABLE" || !s) {
      return `<p class="wx-headline">Weather unavailable.</p><p class="xs muted">Excluded from resilience, routes and ETAs.</p>`;
    }
    const n = s.nodes_affected, cr = s.corridors_at_risk;
    const head = cr || n ? `${n} facilit${n === 1 ? "y" : "ies"} and ${cr} corridor${cr === 1 ? "" : "s"} at risk in the next 48 h.` : "No severe weather in the next 48 h.";
    const ex = data.cells.filter((c) => c.kind === "node" && c.sev >= 0.25).length;
    const res = STATE && STATE.resilience && STATE.resilience.components.weather_exposure;
    return `<p class="wx-headline">${esc(head)}</p>
      <div class="wx-flow"><div><span class="k">Situation</span><b>${esc(s.level_worst.toLowerCase())}</b><em>${fmt1(s.precip_max_mm_h)} mm/h rain · ${s.gust_max_kmh} km/h gusts at ${esc(nm(s.worst_at))}</em></div>
        <div><span class="k">Affects</span><b>${cr} corridors</b><em>${ex} facilities now · ${s.shipments_delayed} loaded shipments delayed</em></div>
        <div><span class="k">Consequence</span><b>${s.delay_total_h ? `+${s.delay_total_h} h delay` : "none yet"}</b><em>${res ? `weather exposure ${(res.score * 100).toFixed(0)}/100` : "applied to ETAs"}</em></div></div>
      ${data.hazards.length ? `<table class="table wx-t" id="wxHaz"><tr><th>Level</th><th>Corridor</th><th>When</th><th class="num">Travel time</th></tr>${data.hazards.slice(0, 4).map((h) => { const worst = Math.max(h.sev_now, h.peak_sev), lv = worst >= 0.75 ? "extreme" : "severe";
        return `<tr class="click" data-l="${esc(h.link)}" tabindex="0"><td><i class="dot ${lv === "extreme" ? "bad" : "warn"}"></i>${lv}</td><td class="mono">${esc(h.from)}→${esc(h.to)} <span class="muted">${esc(h.mode)}</span></td><td>${h.sev_now >= 0.5 ? "now" : `in ~${h.peak_in_h} h`} · ${esc(h.text || "rain / wind")}</td><td class="num">×${h.time_factor}</td></tr>`; }).join("")}</table>` : ""}
      <div class="row wrap" style="margin-top:8px"><button class="btn quiet sm" id="wxOpen">${ico(open ? "up" : "down", 12)} ${open ? "Hide" : "Show"} forecast and facility detail</button><a class="btn quiet sm" href="#/incident">See the weather impact chain →</a></div>`;
  }

  function chainHTML(c) {
    if (!c) return `<p class="xs muted" style="margin:0">No severe weather forecast on any corridor.</p>`;
    const h = c.hazard, r = c.recovery, inv = Object.keys(c.inventory_risk || {});
    const steps = [
      ["Weather", `${h.peak_level.toLowerCase()}`, `${h.from}→${h.to} · ${h.text || "rain / wind"} · ${h.sev_now >= 0.5 ? "now" : `in ~${h.peak_in_h} h`}`, "bad"],
      ["Road risk", `+${Math.round((h.time_factor - 1) * 100)}% time`, `route risk +${Math.round(h.risk_add * 100)} pts`, "warn"],
      ["ETA", c.shipments_total ? `+${c.delay_total_h} h` : "no shipment", `${c.shipments_total} loaded shipment${c.shipments_total === 1 ? "" : "s"} delayed`, c.shipments_total ? "warn" : "ok"],
      ["Inventory", inv.length ? `${inv.length} hub-SKU` : "holds", inv.length ? inv.slice(0, 2).join(", ") + " below safety" : "safety stock covers the delay", inv.length ? "warn" : "ok"],
      ["Network risk", c.network.points_lost != null ? `−${c.network.points_lost} pts` : "—", "on the Resilience Index", "warn"],
      ["Recovery option", r ? (r.better ? `${r.route} · −${(r.current_time_h - r.time_h).toFixed(1)} h` : "hold course") : "none yet", r ? (r.better ? `${r.mode} for ${r.vehicle}` : "no reroute beats the delayed route") : "needs a delayed loaded truck", "ai"],
    ];
    return `<div class="chain">${steps.map(([b, v, sm, cl], i) => `<div class="ch ${cl}" data-i="${i}"><b>${b}</b><span>${esc(v)}</span><small>${esc(sm)}</small></div>`).join("")}</div>
      ${c.shipments.length ? `<div class="xs muted" style="margin-top:6px">Most delayed: ${c.shipments.slice(0, 3).map((o) => `<a href="#/recovery" data-v="${esc(o.vehicle)}" class="wxv mono">${esc(o.vehicle)}</a> +${o.weather_delay_h} h`).join(" · ")}</div>` : ""}`;
  }

  function draw() {
    if (!data) return;
    mountShell();
    const card = $("#wxCard");
    if (card) {
      card.innerHTML = `<div class="card-h"><h2>Weather situation</h2><div class="right"><button class="btn quiet sm" id="wxRefresh2">${ico("refresh", 13)} Refresh</button></div></div>${situation()}`;
      $("#wxRefresh2").onclick = (e) => refresh(e.currentTarget);
      const o = $("#wxOpen"); if (o) o.onclick = () => { open = !open; draw(); };
      $$("#wxHaz tr[data-l]").forEach((tr) => { const go = () => { const h = data.hazards.find((x) => x.link === tr.dataset.l); if (h) TWIN.highlight({ links: [h.link], nodes: [] }); }; tr.onclick = go; tr.onkeydown = (e) => { if (e.key === "Enter") go(); }; });
    }
    const ch = $("#wxChain");
    if (ch) {
      ch.innerHTML = `<div class="card-h"><h2>Weather impact chain</h2>${chip()}</div>${data.meta.status === "UNAVAILABLE" ? `<p class="xs muted">Weather unavailable.</p>` : chainHTML(data.chain)}`;
      $$("#wxChain .wxv").forEach((a) => a.addEventListener("click", () => { sessionStorage.setItem("pnt1.healVehicle", a.dataset.v); }));
    }
  }
  on("page", () => setTimeout(draw, 30));
  addEventListener("resize", () => { const bar = $("#wxbar"); if (bar) document.documentElement.style.setProperty("--wxh", `${bar.offsetHeight}px`); });
  function start() {
    load(); clearInterval(timer); timer = setInterval(load, 60000);
    clearInterval(tick); tick = setInterval(() => { if (data && data.meta && !document.hidden) { const u = $(".wx-c.upd b"), s = $(".wx-stale"); if (u) u.textContent = ageText(); if (s) s.innerHTML = `last reading ${esc(data.meta.fetched_label || "")} · ${ageText()}${data.meta.error ? " · refresh failing" : ""}`; } }, 15000);
  }
  return { start, load, draw, chip, get data() { return data; }, get meta() { return data && data.meta; } };
})();
