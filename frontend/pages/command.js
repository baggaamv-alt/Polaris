/* COMMAND CENTER: Supply Chain Resilience Index, operational metrics, telemetry pipeline, at-risk shipments, events. */
"use strict";
const RI = (() => {
  const ORDER = ["route_redundancy", "supplier_dependency", "warehouse_capacity", "recovery_time", "disruption_exposure", "inventory_buffer", "fleet_flexibility", "data_reliability", "weather_exposure"];
  let history = [], lastIdx = null, built = "";
  const cls = (score) => (score >= 0.85 ? "ok" : score >= 0.65 ? "info" : score >= 0.45 ? "warn" : "bad");
  const COL = { ok: "var(--green)", info: "var(--primary)", warn: "var(--amber)", bad: "var(--red)" };

  function build(res) {
    $("#riCard").innerHTML = `
      <div class="card-h"><h2>Supply chain resilience</h2></div>
      <div class="ri2">
        <div class="ri2-score"><b id="riNum">—</b><span class="of">/ 100</span><span class="band" id="riBand"></span><span class="ri2-d" id="riDelta"></span></div>
        <div class="ri2-scale" aria-hidden="true"><div class="zones"><i class="z bad"></i><i class="z warn"></i><i class="z info"></i><i class="z ok"></i></div><i class="mk" id="riMark"></i>
          <div class="ticks"><span style="left:0">0</span><span style="left:45%">45</span><span style="left:65%">65</span><span style="left:85%">85</span><span style="left:100%">100</span></div></div>
        <div class="ri2-trend"><svg class="spark" id="riSpark" viewBox="0 0 300 34" preserveAspectRatio="none" aria-hidden="true"></svg><div class="xs muted" id="riSparkLbl"></div></div>
      </div>
      <div class="ri-why" id="riWhy"></div>
      <h3 class="ri2-h">Components</h3>
      <div class="ri2-seg" id="riSeg" role="img" aria-label="Weighted components of the resilience score"></div>
      <table class="table ri2-t" id="riComps"></table>`;
    built = "1";
  }

  function render(res) {
    if (!res) return;
    if (!built || !$("#riNum")) build(res);
    const idx = res.index, ORD = ORDER.filter((k) => res.components[k]);
    countTo($("#riNum"), idx, (x) => x.toFixed(0), 1200);
    const band = $("#riBand"); band.textContent = res.band; band.className = `band band-${res.band}`;
    $("#riMark").style.left = `${Math.max(0, Math.min(100, idx))}%`;
    const ch = res.last_change;
    const dl = $("#riDelta");
    if (ch) { const d = ch.to - ch.from; dl.textContent = `${d < 0 ? "▼" : "▲"} ${Math.abs(d).toFixed(0)} since ${dayclock(ch.t)}`; dl.style.color = d < 0 ? "var(--red)" : "var(--green)"; } else dl.textContent = "";
    // segmented bar: width = weight, fill = score
    const sorted = [...ORD].sort((a, b) => res.components[a].score - res.components[b].score);
    $("#riSeg").innerHTML = ORD.map((k) => { const c = res.components[k], q = cls(c.score);
      return `<div class="sg" style="flex:${c.weight}" data-tip="<b>${esc(c.label)}</b> · ${(c.score * 100).toFixed(0)}/100 · weight ${(c.weight * 100).toFixed(0)}%<br>${esc(c.detail)}"><i class="${q}" style="width:${(c.score * 100).toFixed(1)}%"></i></div>`; }).join("");
    $("#riComps").innerHTML = `<tr><th>Component</th><th style="width:34%"></th><th class="num">Score</th><th class="num">Weight</th><th class="num">Lost</th></tr>` + sorted.map((k) => { const c = res.components[k], q = cls(c.score);
      return `<tr data-tip="${esc(c.detail)}"><td>${esc(c.label)}</td><td>${meter(c.score, q === "info" ? "ai" : q === "ok" ? "ok" : q === "warn" ? "warn" : "bad")}</td><td class="num mono">${(c.score * 100).toFixed(0)}</td><td class="num mono muted">${(c.weight * 100).toFixed(0)}%</td><td class="num mono" style="color:${(1 - c.score) * c.weight * 100 >= 3 ? COL[q] : "var(--muted)"}">−${((1 - c.score) * c.weight * 100).toFixed(1)}</td></tr>`; }).join("");
    const whyKey = ch ? `${ch.t}|${ch.to}` : "none";
    if ($("#riWhy").dataset.k !== whyKey) {
      $("#riWhy").dataset.k = whyKey;
      if (ch && ch.drivers && ch.drivers.length) {
        const d = ch.to - ch.from;
        $("#riWhy").innerHTML = `<h3>What changed <span class="delta" style="color:${d < 0 ? "var(--red)" : "var(--green)"}">${ch.from.toFixed(0)} → ${ch.to.toFixed(0)}</span><span class="xs muted" style="margin-left:auto">at ${dayclock(ch.t)}</span></h3>
          <ul>${ch.drivers.slice(0, 4).map((x, i) => `<li style="animation-delay:${i * 90}ms"><b class="${x.delta < 0 ? "dn" : "up"}">${x.delta > 0 ? "+" : ""}${x.delta.toFixed(1)}</b><span>${esc(x.text)}</span></li>`).join("")}</ul>`;
      } else $("#riWhy").innerHTML = `<h3>What changed</h3><p class="xs muted" style="margin:0">No significant change.</p>`;
    }
    if (lastIdx != null && Math.abs(lastIdx - idx) >= 1) flash($("#riCard"));
    lastIdx = idx;
    spark();
  }
  function spark() {
    const svg = $("#riSpark"); if (!svg || history.length < 2) return;
    const xs = history.slice(-240), lo = Math.min(...xs.map((h) => h.index)) - 2, hi = Math.max(...xs.map((h) => h.index)) + 2;
    const pts = xs.map((h, i) => `${(i / (xs.length - 1)) * 300},${34 - ((h.index - lo) / Math.max(1, hi - lo)) * 30 - 2}`).join(" ");
    svg.innerHTML = `<polyline points="${pts}" fill="none" stroke="var(--primary)" stroke-width="1.5" vector-effect="non-scaling-stroke"/>`;
    $("#riSparkLbl").textContent = `Last ${Math.round((xs[xs.length - 1].t - xs[0].t) / 3600 * 10) / 10} h · ${Math.round(lo + 2)}–${Math.round(hi - 2)}`;
  }
  async function loadHistory() { try { const r = await api("/api/resilience"); history = r.history; spark(); } catch { /* retry later */ } }
  on("state", ({ s }) => { if (s.resilience) { const last = history[history.length - 1]; if (!last || last.t !== s.resilience.t) history.push({ t: s.resilience.t, index: s.resilience.index }); } });
  return { render, loadHistory };
})();

PAGES.command = (() => {
  let pipeAnim = null;
  function kpis(o) {
    const tiles = [
      ["health", "Network health", o.network_health_pct, (x) => `${x.toFixed(0)}<small>%</small>`, o.network_health_pct >= 85 ? "ok" : o.network_health_pct >= 65 ? "warn" : "bad", "", "radar"],
      ["dis", "Active disruptions", o.active_disruptions, (x) => Math.round(x), o.active_disruptions ? "bad" : "ok", `${o.disruptions.incidents} incident · ${o.disruptions.inferred_links} inferred · ${o.disruptions.data_attacks} data`, "warning"],
      ["orders", "Orders at risk", o.orders_at_risk, (x) => `${Math.round(x)}<small>/ ${o.orders_total}</small>`, o.orders_at_risk ? (o.critical_at_risk ? "bad" : "warn") : "ok", `${o.critical_at_risk} critical`, "package"],
      ["inv", "Inventory at risk", o.inventory_at_risk_inr, (x) => lakh(x), o.inventory_at_risk_inr > 0 ? "warn" : "ok", `${o.hub_skus_below_safety} below safety stock`, "container"],
      ["eta", "Recovery ETA", o.recovery_eta_h, (x) => (x > 0 ? `${x.toFixed(1)}<small>h</small>` : "—"), o.recovery_eta_h > 0 ? "warn" : "ok", o.recovery_eta_h > 0 ? "" : "", "clock"],
      ["cap", "Network capacity", o.network_capacity_pct, (x) => `${x.toFixed(1)}<small>%</small>`, o.network_capacity_pct >= 99 ? "ok" : "warn", "", "truck"],
      ["util", "Fleet utilization", o.fleet_utilization_pct, (x) => `${x.toFixed(0)}<small>%</small>`, "ai", `${o.trucks_reporting} reporting`, "gear"],
    ];
    const host = $("#opsKpis");
    if (!host.children.length) host.innerHTML = tiles.map(([k, l, , , , , spr]) => `<div class="kpi" data-k="${k}"><div class="l">${pxImg(spr, { scale: 1 })}${l}</div><div class="v"></div><div class="s"></div></div>`).join("");
    for (const [k, , v, fmt, cls, sub] of tiles) {
      const el = $(`.kpi[data-k=${k}]`, host), vEl = $(".v", el);
      const prevCls = el.className;
      el.className = `kpi ${cls}`; if (prevCls !== el.className && prevCls !== "kpi") flash(el);
      const from = vEl.dataset.v === undefined ? v : +vEl.dataset.v; vEl.dataset.v = v;
      if (REDUCED || from === v) vEl.innerHTML = fmt(v);
      else { const t0 = performance.now(); const st = (t) => { const q = Math.min(1, (t - t0) / 800); vEl.innerHTML = fmt(from + (v - from) * (1 - Math.pow(1 - q, 3))); if (q < 1) requestAnimationFrame(st); }; requestAnimationFrame(st); }
      $(".s", el).textContent = sub;
    }
  }
  function pipe(s) {
    const host = $("#pipe"), k = s.kpis;
    if (!$("canvas", host)) {
      host.innerHTML = `<canvas></canvas>` + [["truck", "Vehicles", "pVeh"], ["radar", "Telemetry", "pTel"], ["shield", "Trust engine", "pTrust"], ["container", "Digital twin", "pTwin"]]
        .map(([spr, n, id]) => `<div class="st" id="${id}"><div class="ic">${pxImg(spr, { scale: 2 })}</div><b>${n}</b><span></span></div>`).join("");
      startPipe();
    }
    $("#pVeh span").textContent = `${s.ops ? s.ops.trucks_reporting : s.vehicles.length} live`;
    $("#pTel span").textContent = `${k.events_per_min.toLocaleString()}/min`;
    $("#pTrust span").textContent = `${k.valid_pct}% valid · ${k.anomalies_5min.hard + k.anomalies_5min.soft} flags`;
    $("#pTwin span").textContent = `${k.trusted_coverage_pct}% trusted`;
    $("#pTrust").classList.toggle("bad", k.quarantined_entities > 0);
    $("#pTrust").classList.toggle("hot", !k.quarantined_entities);
    pipeAnim.rate = Math.min(3, k.events_per_min / 400);
    pipeAnim.bad = Math.min(0.5, (k.anomalies_5min.hard + k.anomalies_5min.soft) / Math.max(1, k.events_per_min / 12));
  }
  function startPipe() {
    const cv = $("#pipe canvas"); const ctx = cv.getContext("2d");
    pipeAnim = { rate: 1, bad: 0, parts: [] };
    let last = performance.now();
    const step = (now) => {
      if (PAGE !== "command") { pipeAnim.raf = requestAnimationFrame(step); return; }
      const W = (cv.width = cv.clientWidth * 2), H = (cv.height = cv.clientHeight * 2);
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      if (!REDUCED && Math.random() < pipeAnim.rate * dt * 14) pipeAnim.parts.push({ x: W * 0.12, y: H * (0.34 + Math.random() * 0.06), v: W * (0.22 + Math.random() * 0.1), bad: Math.random() < pipeAnim.bad });
      ctx.clearRect(0, 0, W, H);
      ctx.strokeStyle = css("--line-2"); ctx.lineWidth = 2; ctx.setLineDash([6, 6]); ctx.beginPath(); ctx.moveTo(W * 0.12, H * 0.37); ctx.lineTo(W * 0.88, H * 0.37); ctx.stroke(); ctx.setLineDash([]);
      const g = css("--cyan"), r = css("--red"), gr = css("--green");
      pipeAnim.parts = pipeAnim.parts.filter((p) => {
        p.x += p.v * dt;
        const stop = W * 0.62;
        if (p.bad && p.x > stop) { p.x = stop; p.fade = (p.fade || 1) - dt * 1.5; if (p.fade <= 0) return false; }
        if (p.x > W * 0.88) return false;
        ctx.globalAlpha = p.fade ?? 1; ctx.fillStyle = p.bad && p.x > W * 0.55 ? r : p.x > W * 0.62 ? gr : g;
        ctx.fillRect(Math.round(p.x) - 3, Math.round(p.y) - 3, 6, 6); ctx.globalAlpha = 1;
        return true;
      });
      pipeAnim.raf = requestAnimationFrame(step);
    };
    pipeAnim.raf = requestAnimationFrame(step);
  }
  function risk(s) {
    const list = s.at_risk_orders || [];
    $("#riskList").innerHTML = list.length ? `<div class="list">${list.slice(0, 6).map((o) => `<div class="li click" data-v="${esc(o.vehicle)}">
        <span class="tag ${o.status}">${esc(cap(o.status))}</span><span class="mono">${esc(o.vehicle)}</span><span class="xs muted">${esc(o.sku)} → ${esc(o.destination)}${o.blocked_ahead && o.blocked_ahead.length ? ` · blocked at ${esc(o.blocked_ahead[0])}` : o.delay_h > 0 ? ` · +${hrs(o.delay_h)}` : ""}</span>
        <span class="spacer"></span>${o.priority === "CRITICAL" ? '<span class="tag CRITICAL">CRITICAL</span>' : ""}</div>`).join("")}</div>`
      : empty("check", "No shipment at risk");
    $$("#riskList .li").forEach((el) => el.addEventListener("click", () => { TWIN.select("vehicle", el.dataset.v, { fly: true }); }));
  }
  const eventLi = (a) => `<li><time>${clock(a.t)}</time><i class="sev ${a.severity}"></i><span>${esc(a.text)}</span></li>`;
  let lastAlert = 0;
  function events(s) {
    const top = s.alerts[0] ? s.alerts[0].id : 0;
    if (top === lastAlert && $("#events").children.length) return;
    lastAlert = top;
    $("#events").innerHTML = s.alerts.length ? s.alerts.slice(0, 16).map(eventLi).join("") : `<li style="display:block">${empty("truck", "All quiet")}</li>`;
  }
  function incidents(s) {
    const inc = s.incidents || [], host = $("#incNow"); if (!host) return;
    host.innerHTML = inc.length ? `<table class="table"><tr><th>Incident</th><th>Target</th><th>Started</th><th class="num">Remaining</th></tr>${inc.map((i) => `<tr class="click" data-i="${esc(i.id)}" tabindex="0"><td>${esc(i.label || i.kind)}</td><td class="mono">${esc((i.nodes.concat(i.links)).slice(0, 3).join(", "))}</td><td class="mono">${dayclock(i.start_t)}</td><td class="num mono">${hrs(i.remaining_h)}</td></tr>`).join("")}</table>` : "";
    $$("#incNow tr.click").forEach((tr) => { const go = () => { const i = inc.find((x) => x.id === tr.dataset.i); if (i) TWIN.highlight({ nodes: i.nodes, links: i.links }); }; tr.onclick = go; tr.onkeydown = (e) => { if (e.key === "Enter") go(); }; });
  }
  function render(s) {
    if (s.resilience) RI.render(s.resilience);
    incidents(s);
    if (s.ops) kpis(s.ops);
    pipe(s); risk(s); events(s);
  }
  on("state", ({ s }) => { if (PAGE === "command") render(s); });
  on("weather", () => { if (PAGE === "command") WX.draw(); });
  on("select", () => { if (PAGE === "command") location.hash = "#/twin"; });
  return { enter() { WX.draw(); RI.loadHistory(); lastAlert = -1; if (STATE) render(STATE); TWIN.ready.then(() => { TWIN.clearHighlight(); TWIN.clearRoutes(); }); } };
})();
