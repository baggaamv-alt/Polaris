/* DIGITAL TWIN: entity inspector (Trust Engine verdict + animated check pipeline, quarantine path, sensor fusion,
 * vehicle health), trust distribution, search + cinematic camera, vehicle health watchlist. */
"use strict";
PAGES.twin = (() => {
  let cur = null, lastKey = "", timer = null, health = [];
  const CHECK_LABEL = { road: "Road-network match", physics: "Physically possible", kinematic: "Consistent motion", route: "On assigned route",
    temporal: "Fresh, in order", schema: "Complete message", reconcile: "Matches recorded flows", context: "Agrees with context", statistical: "Statistical pattern" };
  const FICON = { gps: ico("pin", 14), telemetry: ico("signal", 14), road: ico("route", 14), nearby: ico("network", 14), weather: ico("cloud", 14), history: ico("compass", 14), observations: ico("eye", 14) };

  function checksHTML(checks) {
    return `<div class="checks">${Object.entries(checks || {}).map(([k, v], i) => `<span>${esc(CHECK_LABEL[k] || k)}</span>${meter(v, stateOf(v))}<b>${v.toFixed(2)}</b>`).join("")}</div>`;
  }
  function trend(canvas, hist) {
    const W = (canvas.width = canvas.clientWidth * 2), H = (canvas.height = 96), c = canvas.getContext("2d");
    c.clearRect(0, 0, W, H);
    c.strokeStyle = css("--line-2"); c.lineWidth = 1; c.setLineDash([4, 4]);
    [0.8, 0.5].forEach((y) => { c.beginPath(); c.moveTo(0, H - y * (H - 8) - 4); c.lineTo(W, H - y * (H - 8) - 4); c.stroke(); });
    c.setLineDash([]);
    if (!hist.length) return;
    const grad = c.createLinearGradient(0, 0, W, 0); grad.addColorStop(0, css("--primary")); grad.addColorStop(1, css("--violet"));
    c.strokeStyle = grad; c.lineWidth = 3; c.beginPath();
    hist.forEach((h, i) => { const x = (i / Math.max(1, hist.length - 1)) * W, y = H - h[2] * (H - 8) - 4; i ? c.lineTo(x, y) : c.moveTo(x, y); });
    c.stroke();
  }
  function fmtRaw(raw) {
    if (raw == null) return "—";
    if (typeof raw !== "object") return esc(String(raw).slice(0, 120));
    return Object.entries(raw).filter(([k]) => !["shipment_id", "inbound", "outbound"].includes(k)).slice(0, 6)
      .map(([k, v]) => `${esc(k)}: <b>${esc(typeof v === "object" ? JSON.stringify(v).slice(0, 60) : v)}</b>`).join("<br>");
  }

  async function renderVehicle(id, first) {
    const [t, f] = await Promise.all([api(`/api/trust/${encodeURIComponent(id)}`), api(`/api/fusion/${encodeURIComponent(id)}`).catch(() => null)]);
    const v = STATE && STATE.vehicles.find((x) => x.id === id);
    const h = health.find((x) => x.vehicle === id);
    const bad = t.cls === "quarantined";
    const lb = t.last_anomaly;
    const anim = first ? "" : "animation:none;opacity:1";
    $("#twinEntity").innerHTML = `
      <div class="card ${bad ? "" : "glow"}">
        <div class="row" style="gap:12px">${pxImg("truck", { scale: 3, c: stateColors()[t.cls] })}
          <div><div class="mono" style="font-size:15px;font-weight:600">${esc(id)}</div><div class="xs muted">${esc(v ? `${v.speed} km/h · heading ${v.heading}° · ${v.load ? `${v.load} pallets ${v.sku}` : "empty"}` : "not reporting")}</div></div>
          <span class="spacer"></span><span class="verdict ${t.cls}">${CLS_ICON[t.cls]} ${CLS_LABEL[t.cls]}</span></div>
        <div class="divider"></div>
        <div class="eyebrow" style="margin-bottom:6px">Trust Engine</div>
        <div class="tpipe ${bad ? "bad" : ""}">
          <div class="box row"><h5 style="margin:0">Incoming reading</h5><span class="raw">${v ? `lat <b>${v.lat.toFixed(4)}</b> · lon <b>${v.lon.toFixed(4)}</b> · <b>${v.speed}</b> km/h · age <b>${v.age_s}s</b>` : "—"}</span></div>
          <div class="arrow"></div>
          <div class="box"><h5>${Object.keys(t.checks || {}).length} independent checks</h5>${checksHTML(t.checks)}</div>
          <div class="arrow"></div>
          <div class="box row"><h5 style="margin:0">Verdict</h5><span class="verdict ${t.cls}" style="padding:3px 9px">${CLS_ICON[t.cls]} ${CLS_LABEL[t.cls]}</span><span style="font:700 20px var(--display)">τ ${t.tau.toFixed(2)}</span><span class="xs muted" style="margin-left:auto">${t.readings.toLocaleString()} readings · ${t.anomalies} flagged</span></div>
        </div>
        ${t.reasons && t.reasons.length ? `<ul class="xs" style="margin:8px 0 0;padding-left:16px;color:var(--text-2)">${t.reasons.slice(0, 3).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
        ${lb ? `<div class="eyebrow" style="margin:12px 0 4px">Last suspicious reading · ${clock(lb.t)}</div>
          <div class="qpath" style="${anim}"><div style="${anim}"><b>Reading</b><span class="raw">${fmtRaw(lb.raw)}</span></div><div style="${anim}"><b>Trust engine</b>ρ ${lb.rho.toFixed(2)}<br><span class="xs muted">${esc((lb.reasons || [])[0] || lb.action)}</span></div>
            <div style="${anim}"><b>${lb.action === "quarantine" ? "Quarantine" : cap(lb.action)}</b>excluded</div><div style="${anim}"><b>Last trusted state</b>${v ? `${v.lat.toFixed(3)}, ${v.lon.toFixed(3)}<br><span class="xs muted">uncertainty ${v.unc_km} km</span>` : "held"}</div></div>` : ""}
        <canvas class="trend" style="width:100%;height:48px;margin-top:10px"></canvas><div class="xxs muted">Trust over time</div>
      </div>
      ${f ? `<div class="card ai"><div class="card-h"><h2>Sensor fusion</h2></div>
        <div class="fusion">${f.sources.map((x, i) => `<div class="fsrc ${x.available ? "" : "na"}" style="animation-delay:${first ? i * 90 : 0}ms;${first ? "" : "opacity:1;animation:none"}"><span>${FICON[x.key] || "•"}</span><span>${esc(x.label)}</span>
          ${x.available ? meter(x.confidence, stateOf(x.confidence)) : `<div class="meter na"><i></i></div>`}<b>${x.available ? pct(x.confidence, 0) : "n/a"}</b><span class="d">${esc(x.detail)}</span></div>`).join("")}</div>
        <div class="fused" style="${first ? "" : "animation:none"}">${pxImg("robot", { scale: 2 })}<div><div class="eyebrow">Fused state</div><b>${esc(f.fused_state)}</b><div class="xs muted">${esc(f.why)}</div></div><div class="cf">${pct(f.confidence, 0)}</div></div>
        </div>` : ""}
      ${h ? `<div class="card"><div class="card-h"><h2>Vehicle health</h2><span class="tag ${h.tier}">${h.tier} risk</span><span class="right mono xs">${(h.risk * 100).toFixed(0)}/100</span></div>
        ${meter(h.risk, h.tier === "HIGH" ? "bad" : h.tier === "ELEVATED" ? "warn" : "ok")}
        <p class="xs" style="margin:8px 0 0">${h.reasons.length ? esc(h.reasons.join(" · ")) : "No risk signals."}</p>
        <p class="note">Fuel ${h.fuel_pct != null ? `${h.fuel_pct.toFixed(0)}%` : "n/a"} · unavailable: ${esc(h.unavailable.join(", "))}</p></div>` : ""}`;
    trend($("#twinEntity canvas.trend"), t.history);
  }

  async function renderNode(id, first) {
    const n = NODE[id];
    const isWh = n.type === "Warehouse";
    let t = null; if (isWh) t = await api(`/api/trust/wh:${encodeURIComponent(id)}`).catch(() => null);
    const blast = await api(`/api/graph/blast/${encodeURIComponent(id)}`).catch(() => null);
    const st = (STATE && STATE.node_state[id]) || "unknown";
    const w = STATE && STATE.warehouses[id];
    const inc = (STATE.incidents || []).find((i) => i.nodes.includes(id));
    $("#twinEntity").innerHTML = `
      <div class="card glow"><div class="row" style="gap:12px">${pxImg(TYPE_SPRITE[n.type], { scale: 3, c: PX_PALETTE.n })}<div><div class="mono" style="font-size:15px;font-weight:600">${esc(id)}</div><div class="xs muted">${esc(n.name)} · ${esc(n.type === "CustomerCluster" ? "Customer cluster" : n.type)}</div></div>
        <span class="spacer"></span><span class="tag ${st}">${esc(st.toUpperCase())}</span></div>
        ${inc ? `<div class="callout bad" style="margin-top:10px">${pxImg("warning", { scale: 2 })}<div><h3>${esc(inc.label)}</h3><p>${inc.remaining_h.toFixed(1)} h remaining</p></div></div>` : ""}
        ${t ? `<div class="divider"></div><div class="eyebrow" style="margin-bottom:6px">Feed trust · can I trust this stock count?</div>
          <div class="row"><span class="verdict ${t.cls}">${CLS_ICON[t.cls]} ${CLS_LABEL[t.cls]}</span><span class="xs muted">τ ${t.tau.toFixed(2)} · ${t.readings} reports · ${t.anomalies} flagged</span></div>
          <div style="margin-top:8px">${checksHTML(t.checks)}</div>${t.reasons.length ? `<p class="xs" style="color:var(--text-2)">${esc(t.reasons.slice(0, 2).join("; "))}</p>` : ""}` : ""}
        ${w ? `<div class="divider"></div><table class="table"><tr><th>SKU</th><th class="num">Trusted stock</th><th>Confidence</th></tr>${Object.keys(w.inv).map((s) =>
          `<tr><td class="mono">${s}</td><td class="num">${w.inv[s] == null ? "—" : w.inv[s].toLocaleString("en-IN")}</td><td><span class="tag ${w.conf[s] === "verified" ? "ok" : w.conf[s] ? "warn" : ""}">${esc(w.conf[s] || "no report")}</span></td></tr>`).join("")}</table>` : ""}
        ${blast ? `<div class="divider"></div><div class="xs"><b>Ships to</b> ${blast.direct.map((d) => `<span class="mono">${esc(d)}</span>`).join(", ") || "—"}<br>
          ${blast.customers_cut_off_if_failed.length ? `<span style="color:var(--red)">If it fails, <b>${blast.customers_cut_off_if_failed.join(", ")}</b> lose all supply.</span>` : "Every downstream customer has another path if it fails."}</div>` : ""}
        <div class="row" style="margin-top:10px"><a class="btn ghost sm" href="#/incident" data-inc="${esc(id)}">Simulate its failure →</a><a class="btn quiet sm" href="#/proof">Dependencies →</a></div>
      </div>`;
    const a = $("#twinEntity [data-inc]"); if (a) a.addEventListener("click", () => { sessionStorage.setItem("pnt1.incTarget", id); });
  }

  async function render(first = false) {
    if (!cur) { $("#twinEntity").innerHTML = `<div class="card">${empty("radar", "Select a truck or facility on the map")}</div>`; return; }
    try { cur.kind === "vehicle" ? await renderVehicle(cur.id, first) : await renderNode(cur.id, first); }
    catch (e) { $("#twinEntity").innerHTML = `<div class="card"><p class="muted small">${esc(cur.id)} has not reported yet.</p></div>`; }
  }
  function dist(s) {
    const c = { trusted: 0, estimated: 0, quarantined: 0 };
    s.vehicles.forEach((v) => c[v.cls]++);
    Object.values(s.warehouses).forEach((w) => { if (w.cls) c[w.cls]++; });
    $("#trustDist").innerHTML = ["trusted", "estimated", "quarantined"].map((k) => `<div class="stat"><div class="v" style="color:var(--${k === "trusted" ? "green" : k === "estimated" ? "amber" : "red"})" data-k="${k}"></div><div class="l">${CLS_ICON[k]} ${CLS_LABEL[k]}</div></div>`).join("");
    ["trusted", "estimated", "quarantined"].forEach((k) => countTo($(`#trustDist [data-k=${k}]`), c[k]));
  }
  async function watchlist() {
    try { health = await api("/api/fleet/health"); } catch { return; }
    const top = health.slice(0, 7);
    $("#healthList").innerHTML = `<div class="list">${top.map((h) => `<div class="li click" data-v="${esc(h.vehicle)}"><span class="tag ${h.tier}">${h.tier}</span><span class="mono">${esc(h.vehicle)}</span>
      <span class="xs muted" style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(h.reasons.join(" · ") || "no signals")}</span><span class="mono xs">${(h.risk * 100).toFixed(0)}</span></div>`).join("")}</div>
      `;
    $$("#healthList .li").forEach((el) => el.addEventListener("click", () => { TWIN.select("vehicle", el.dataset.v, { fly: true }); show({ kind: "vehicle", id: el.dataset.v }); }));
  }
  function show(sel) { cur = sel; lastKey = sel ? `${sel.kind}:${sel.id}` : ""; render(true); }

  on("select", (sel) => { if (PAGE === "twin" || PAGE === "command") show(sel); });
  on("state", ({ s }) => { if (PAGE === "twin") dist(s); });

  function search() {
    const q = $("#twinSearch").value.trim(); if (!q) return;
    const id = q.replace(/^wh:/, "");
    if (NODE[id]) { TWIN.select("node", id, { fly: true }); show({ kind: "node", id }); return; }
    const v = STATE && STATE.vehicles.find((x) => x.id.toLowerCase() === q.toLowerCase());
    if (v) { TWIN.select("vehicle", v.id, { fly: true }); show({ kind: "vehicle", id: v.id }); return; }
    toast(`No truck or facility called ${q}`, "err");
  }
  function init() {
    $("#twinGo").addEventListener("click", search);
    $("#twinSearch").addEventListener("keydown", (e) => { if (e.key === "Enter") search(); });
  }
  return {
    init,
    enter() {
      $("#twinList").innerHTML = [...NET.nodes.map((n) => n.id), ...(STATE ? STATE.vehicles.map((v) => v.id) : [])].map((x) => `<option value="${esc(x)}">`).join("");
      const sel = TWIN.selected; if (sel) { cur = sel; }
      render(true); if (STATE) dist(STATE); watchlist();
      clearInterval(timer); timer = setInterval(() => { if (PAGE === "twin") { render(false); } }, 2000);
      this._h = setInterval(() => PAGE === "twin" && watchlist(), 8000);
      TWIN.ready.then(() => { TWIN.clearRoutes(); TWIN.clearHighlight(); });
    },
    leave() { clearInterval(timer); clearInterval(this._h); },
  };
})();
