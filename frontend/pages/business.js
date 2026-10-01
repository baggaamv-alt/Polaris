/* BUSINESS FLOW: supplier → manufacturer → warehouse → transport → distribution → customer, the order book with
 * ETA / delay / owner / next step, support tickets (written to the audit chain), and the driver-assignment
 * prototype (clearly labelled future scope, synthetic roster). */
"use strict";
PAGES.business = (() => {
  let orders = [], cur = null, timer = null, flowAnim = null;
  const STAGES = [["SUPPLIER", "supplier", "Suppliers & ports"], ["MANUFACTURER", "factory", "Factories"], ["WAREHOUSE", "warehouse", "Hubs"], ["TRANSPORT", "truck", "In transit"], ["DISTRIBUTION", "container", "Hub → customer"], ["CUSTOMER", "pin", "Demand clusters"]];

  function bflow() {
    const n = (t) => NET.nodes.filter((x) => t.includes(x.type)).length;
    const stock = STATE ? Object.values(STATE.warehouses).reduce((a, w) => a + Object.values(w.inv).reduce((x, y) => x + (y || 0), 0), 0) : 0;
    const dist = NET.links.filter((l) => NODE[l.to] && NODE[l.to].type === "CustomerCluster").length;
    const vals = { SUPPLIER: [n(["Supplier", "Port"]), "sources"], MANUFACTURER: [n(["Factory"]), "plants"], WAREHOUSE: [stock ? `${(stock / 1000).toFixed(1)}k` : "—", "trusted units"],
      TRANSPORT: [orders.length, `${orders.filter((o) => o.status !== "IN_TRANSIT" && o.status !== "ARRIVING" && o.status !== "LOADING").length} need attention`], DISTRIBUTION: [dist, "delivery lanes"], CUSTOMER: [n(["CustomerCluster"]), "clusters"] };
    const onIdx = cur ? { SUPPLIER: 0, MANUFACTURER: 1, WAREHOUSE: 2 }[cur.origin_stage] ?? 0 : -1;
    const host = $("#bflow");
    if (!$("canvas", host)) { host.innerHTML = `<canvas></canvas>` + STAGES.map(([k, spr, l]) => `<div class="b" data-k="${k}"><div class="ic">${pxImg(spr, { scale: 2 })}</div><b>${cap(k)}</b><span></span><small>${l}</small></div>`).join(""); startFlow(); }
    STAGES.forEach(([k], i) => { const el = $(`.b[data-k=${k}]`, host); $("span", el).textContent = vals[k][0]; $("small", el).textContent = vals[k][1];
      el.classList.toggle("on", cur ? (i === onIdx || k === "WAREHOUSE" && cur.dest_type === "Warehouse" && i > onIdx) : false); el.classList.toggle("cur", !!cur && k === "TRANSPORT"); });
  }
  function startFlow() {
    const cv = $("#bflow canvas"), ctx = cv.getContext("2d"); flowAnim = { parts: [] }; let last = performance.now();
    const step = (now) => {
      flowAnim.raf = requestAnimationFrame(step);
      if (PAGE !== "business" || REDUCED) return;
      const W = (cv.width = cv.clientWidth * 2), H = (cv.height = cv.clientHeight * 2), dt = Math.min(0.05, (now - last) / 1000); last = now;
      if (Math.random() < dt * 6) flowAnim.parts.push({ x: W * 0.05, v: W * (0.1 + Math.random() * 0.05) });
      ctx.clearRect(0, 0, W, H); const c = css("--primary");
      flowAnim.parts = flowAnim.parts.filter((p) => { p.x += p.v * dt; if (p.x > W * 0.95) return false; ctx.fillStyle = c; ctx.globalAlpha = 0.85; ctx.fillRect(Math.round(p.x) - 2, 24 * 2 - 2, 4, 4); ctx.globalAlpha = 1; return true; });
    };
    flowAnim.raf = requestAnimationFrame(step);
  }

  async function load() {
    try { orders = await api("/api/orders"); } catch { return; }
    if (cur) cur = orders.find((o) => o.vehicle === cur.vehicle) || cur;
    table(); bflow(); if (cur) detail(cur, false);
  }
  function table() {
    const f = $("#ordFilter").value, q = $("#ordSearch").value.trim().toLowerCase();
    const rows = orders.filter((o) => (!f || (f === "risk" ? ["AT_RISK", "STOPPED", "DELAYED", "UNVERIFIED"].includes(o.status) : o.priority === f))
      && (!q || [o.id, o.vehicle, o.origin, o.destination, o.sku, o.sku_class].join(" ").toLowerCase().includes(q)));
    $("#ordTable").innerHTML = rows.length ? `<div class="tscroll" style="max-height:420px"><table class="table"><tr><th>Order</th><th>Cargo</th><th>Lane</th><th>Status</th><th class="num">ETA</th></tr>${rows.slice(0, 120).map((o) => `
      <tr class="click ${cur && cur.vehicle === o.vehicle ? "hl" : ""}" data-v="${esc(o.vehicle)}"><td class="mono">${esc(o.id)}</td><td>${esc(o.sku)} <span class="tag ${o.priority}" style="height:18px">${o.priority[0]}</span></td>
      <td class="mono xs">${esc(o.origin)} → ${esc(o.destination)}</td><td><span class="tag ${o.status}">${esc(cap(o.status))}</span></td><td class="num mono xs">${clock(o.eta_t)}${o.delay_h > 0.05 ? `<br><span style="color:var(--amber)">+${hrs(o.delay_h)}</span>` : ""}</td></tr>`).join("")}</table></div>
      <p class="note">${rows.length} of ${orders.length} loaded shipments.</p>`
      : empty("package", "No matching orders", "Try another filter.");
    $$("#ordTable tr.click").forEach((tr) => tr.addEventListener("click", () => { cur = orders.find((o) => o.vehicle === tr.dataset.v); table(); bflow(); detail(cur, true); drivers(true); TWIN.select("vehicle", cur.vehicle, { fly: true }); }));
  }
  function detail(o, first) {
    if (!o) { $("#ordDetail").innerHTML = `<div class="card-h"><h2>Order inspector</h2></div>${empty("package", "Select an order")}`; return; }
    const chain = [["Origin", o.origin, NODE[o.origin]?.name, "done"], ["Transport", o.current_link, `${km(o.remaining_km)} to go · ${Math.round(o.speed)} km/h`, "now"], ["Destination", o.destination, NODE[o.destination]?.name, ""],
      ["Customers", o.customers.slice(0, 3).join(", ") || "—", "served by the destination hub", ""]];
    $("#ordDetail").innerHTML = `<div class="card-h"><h2>Order <span class="mono">${esc(o.id)}</span></h2><div class="right"><span class="tag ${o.status}">${esc(cap(o.status))}</span></div></div>
      <div class="row" style="gap:10px">${pxImg("truck", { scale: 3, c: stateColors()[o.trust] || "#3b8cff" })}<div><b>${o.units} pallets ${esc(o.sku)}</b> <span class="muted">${esc(o.sku_class)}</span> <span class="tag ${o.priority}">${o.priority}</span>
        <div class="xs muted">${esc(o.vehicle)} · ${esc(o.fleet)} · value ${lakh(o.value_inr)}${o.reroutes ? ` · <b style="color:var(--violet)">rerouted ×${o.reroutes}</b>` : ""}</div></div></div>
      <div class="flow" style="margin-top:10px">${chain.map(([b, v, p, st]) => `<div class="fs ${st}"><span class="dot">${st === "done" ? ico("check", 12) : st === "now" ? "" : ""}</span><div><b>${b} · <span class="mono">${esc(v)}</span></b><p>${esc(p || "")}</p></div></div>`).join("")}</div>
      <div class="grid2" style="margin-top:8px"><div class="stat"><div class="v">${clock(o.eta_t)}</div><div class="l">ETA (sim) · ${hrs(o.remaining_h)} left</div></div>
        <div class="stat"><div class="v" style="color:${o.delay_h > 0.5 ? "var(--amber)" : "var(--green)"}">${o.delay_h > 0.05 ? `+${hrs(o.delay_h)}` : "on time"}</div><div class="l">vs plan ${clock(o.planned_eta_t)}</div></div></div>
      <div class="callout ${o.status === "AT_RISK" ? "bad" : "ai"}" style="margin-top:10px">${pxImg(o.status === "AT_RISK" ? "warning" : "flag", { scale: 2 })}<div><h3>Next step</h3><p>${esc(o.next_step)}</p><p class="xs muted">Responsible: <b class="mono">${esc(o.responsible)}</b> operations desk</p></div></div>
      <div class="row wrap" style="margin-top:10px"><button class="btn ghost sm" id="oFly">Show on map</button><button class="btn ghost sm" id="oSupport">Support &amp; Contact</button><button class="btn ai sm" id="oPlan">Plan alternatives</button>${o.status === "AT_RISK" ? '<button class="btn danger sm" id="oHeal">Self-heal now</button>' : ""}</div>`;
    $("#oFly").onclick = () => TWIN.select("vehicle", o.vehicle, { fly: true });
    $("#oSupport").onclick = () => openSupport(o);
    $("#oPlan").onclick = () => { sessionStorage.setItem("pnt1.planOrder", o.vehicle); location.hash = "#/recovery"; };
    const h = $("#oHeal"); if (h) h.onclick = () => { sessionStorage.setItem("pnt1.healVehicle", o.vehicle); location.hash = "#/recovery"; };
    if (first) support(o);
  }
  /* ------------------------------------------------------------ Support & Contact (drawer; tickets use /api/support/tickets) */
  let drawerOrder = null, lastFocus = null, newTicket = null;
  const CATS = [["delay", "Delay"], ["reroute", "Reroute request"], ["damage", "Damage"], ["documentation", "Documentation"], ["other", "Other"]];
  async function openSupport(o) {
    lastFocus = document.activeElement;
    drawerOrder = o || cur || orders.find((x) => x.status === "AT_RISK") || orders[0] || null;
    $("#supportDrawer").hidden = false; $("#supportScrim").hidden = false; $("#openSupport").setAttribute("aria-expanded", "true");
    await drawer();
    const first = $("#tkOrder"); if (first) first.focus();
  }
  function closeSupport() {
    $("#supportDrawer").hidden = true; $("#supportScrim").hidden = true; $("#openSupport").setAttribute("aria-expanded", "false");
    if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
  }
  async function drawer() {
    const host = $("#supportDrawer"), o = drawerOrder;
    let tickets = [], audit = [];
    try { [tickets, audit] = await Promise.all([api("/api/support/tickets"), api("/api/audit?entry_type=support_ticket&limit=60")]); } catch { /* shown as empty */ }
    const hashOf = {}; audit.forEach((a) => { hashOf[a.seq] = a.hash; });
    const fac = o ? NODE[o.responsible] : null;
    const scope = host.dataset.scope || "order";
    const shown = tickets.filter((t) => scope === "all" || !o || t.order_id === o.id);
    host.innerHTML = `<div class="dh"><h2 id="supportTitle">Support &amp; Contact</h2><button class="iconbtn x" id="tkClose" aria-label="Close support panel">${ico("x", 14)}</button></div>
      <p class="xs muted" style="margin:0">Tickets are audit-logged and cannot be edited.</p>
      <h3>Order</h3>
      <label class="field">Select order<select id="tkOrder">${orders.length ? orders.map((x) => `<option value="${esc(x.id)}" ${o && x.id === o.id ? "selected" : ""}>${esc(x.id)} · ${esc(x.sku)} · ${esc(x.origin)} → ${esc(x.destination)}${x.status === "AT_RISK" ? " · at risk" : ""}</option>`).join("") : '<option value="">No loaded shipments yet</option>'}</select></label>
      ${o ? `<dl class="ctx"><dt>Status</dt><dd><span class="tag ${o.status}">${esc(cap(o.status))}</span> ${o.priority === "CRITICAL" ? '<span class="tag CRITICAL">Critical cargo</span>' : ""}</dd>
        <dt>Cargo</dt><dd>${o.units} pallets ${esc(o.sku)} · ${esc(o.sku_class)}</dd>
        <dt>Lane</dt><dd class="mono">${esc(o.origin)} → ${esc(o.destination)} · ${esc(o.vehicle)}</dd>
        <dt>ETA</dt><dd>${clock(o.eta_t)}${o.delay_h > 0.05 ? ` · <b style="color:var(--amber)">+${hrs(o.delay_h)}</b>` : " · on time"}${o.weather_delay_h > 0.05 ? ` · ${hrs(o.weather_delay_h)} from weather` : ""}</dd>
        <dt>Owner</dt><dd>${esc(fac ? fac.name : o.responsible)} operations desk <span class="muted">(${esc(o.responsible)}) · fleet dispatch ${esc(o.fleet)}</span></dd></dl>
      <h3>New ticket</h3>
      <div class="form-grid" style="grid-template-columns:1fr"><label class="field">Category<select id="tkCat">${CATS.map(([v, l]) => `<option value="${v}" ${o.status === "AT_RISK" && v === "reroute" ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label class="field">Message<textarea id="tkMsg" rows="3" maxlength="600" placeholder="Message" style="width:100%;resize:vertical"></textarea></label></div>
      <div class="row" style="margin-top:8px"><button class="btn sm" id="tkSend">Raise ticket</button><span class="xs muted" id="tkHint">Goes to the ${esc(o.responsible)} desk</span></div>` : `<p class="xs muted">No orders in transit.</p>`}
      <h3>Tickets <span class="chips" style="display:inline-flex;margin-left:8px"><button class="chip ${scope !== "all" ? "on" : ""}" data-sc="order">This order</button><button class="chip ${scope === "all" ? "on" : ""}" data-sc="all">All (${tickets.length})</button></span></h3>
      ${shown.length ? shown.slice(0, 12).map((t) => `<div class="tk-row ${newTicket === t.id ? "new" : ""}"><span class="tag">${esc(cap(t.category))}</span><span><b class="mono">${esc(t.id)}</b> <span class="muted">· order ${esc(t.order_id)}</span> <span class="tag ${t.status === "open" ? "warn" : "ok"}">${esc(t.status)}</span></span>
        <span class="m" style="grid-column:1/-1">${esc(t.message)}</span><span class="m mono" style="grid-column:1/-1">opened ${dayclock(t.t)} · audit #${t.audit_seq}${hashOf[t.audit_seq] ? ` · hash ${hashOf[t.audit_seq]}…` : ""}</span></div>`).join("") : `<p class="xs muted">No tickets ${scope === "all" ? "yet" : "for this order"}.</p>`}`;
    newTicket = null;
    $("#tkClose").onclick = closeSupport;
    const sel = $("#tkOrder"); if (sel) sel.onchange = () => { drawerOrder = orders.find((x) => x.id === sel.value) || null; drawer(); };
    $$("#supportDrawer .chip[data-sc]").forEach((c) => (c.onclick = () => { host.dataset.scope = c.dataset.sc; drawer(); }));
    const btn = $("#tkSend");
    if (btn) btn.onclick = async () => {
      const msg = $("#tkMsg").value.trim(); if (msg.length < 3) { toast("Write a short message first", "err"); $("#tkMsg").focus(); return; }
      busy(btn, true);
      try { const t = await post("/api/support/tickets", { order_id: o.id, category: $("#tkCat").value, message: msg, contact: "operator" }); newTicket = t.id; toast(`Ticket ${t.id} raised`, "ok"); host.dataset.scope = "order"; await drawer(); }
      catch (e) { toast(e.message, "err"); busy(btn, false); }
    };
  }
  function support(o) { if (o) drawerOrder = o; if (!$("#supportDrawer").hidden) drawer(); }

  /* ------------------------------------------------------------ driver assignment: PROTOTYPE */
  function roster() { // deterministic synthetic roster (NOT real people)
    const bases = ["W-HYD", "W-VGA", "W-DEL", "W-BOM", "W-BLR", "W-CHE", "W-KOL", "W-NAG", "W-PNQ", "W-AMD"];
    return Array.from({ length: 12 }, (_, i) => { const x = Math.sin(i * 12.9898 + 78.233) * 43758.5453, r = x - Math.floor(x);
      return { id: `DRV-${String(i + 1).padStart(2, "0")}`, base: bases[i % bases.length], driven: Math.round(r * 9 * 10) / 10, cls: i % 3 === 0 ? "HGV · night shift" : "HGV" }; });
  }
  async function drivers(animate) {
    const DUTY = 11;
    const o = cur || orders.find((x) => x.priority === "CRITICAL") || orders[0];
    const host = $("#drivers");
    if (!o) { host.innerHTML = ""; return; }
    let health = null; try { health = (await api("/api/fleet/health")).find((h) => h.vehicle === o.vehicle); } catch { /* optional */ }
    const need = o.remaining_h, list = roster();
    const near = (d) => d.base === o.origin || d.base === o.destination || d.base === o.responsible;
    const scored = list.map((d) => ({ ...d, left: Math.max(0, DUTY - d.driven), ok: DUTY - d.driven >= need }))
      .map((d) => ({ ...d, score: (d.ok ? 0 : 10) + (near(d) ? 0 : 2) + d.driven / DUTY })).sort((a, b) => a.score - b.score);
    const best = scored[0];
    const vehOk = !health || !(o.priority === "CRITICAL" && health.tier === "HIGH");
    host.innerHTML = `<div class="card-h"><h2>${pxImg("driver", { scale: 1 })} Driver assignment</h2><span class="dm proto">prototype · future scope</span><span class="sub">synthetic roster, not connected to rostering/HR</span></div>
      <div class="chain" id="drvChain">${[["driver", "Available drivers", `${list.length}`, "synthetic roster"], ["flag", "Route requirements", hrs(need), `${esc(o.origin)} → ${esc(o.destination)} · ${o.priority}`],
        ["robot", "Matching", `${scored.filter((d) => d.ok).length} fit`, "hours left ≥ route time · near base"], ["check", "Assignment", best.ok ? best.id : "none", best.ok ? `base ${best.base}` : "split the route"],
        ["truck", "Driver on route", esc(o.vehicle), vehOk ? `vehicle health ${health ? health.tier : "n/a"}` : "vehicle risk too high for critical cargo"], ["clock", "Road time", `${(best.driven + Math.min(need, best.left)).toFixed(1)} / ${DUTY} h`, "after this trip"]]
        .map(([s, b, v, sm], i) => `<div class="ch" data-i="${i}"><div class="ic">${pxImg(s, { scale: 2, c: PX_PALETTE.n })}</div><b>${b}</b><span>${v}</span><small>${sm}</small></div>`).join("")}</div>
      <div class="grid2" style="margin-top:8px">${scored.slice(0, 6).map((d) => `<div class="drv ${d.id === best.id && d.ok ? "match" : d.ok ? "" : "out"}">${pxImg("driver", { scale: 2 })}<div><b class="mono">${d.id}</b> <span class="xs muted">${d.cls} · base ${d.base}</span>
        <div class="row" style="gap:6px;margin-top:3px"><div class="hours"><i style="width:${(d.driven / DUTY) * 100}%;background:var(--amber)"></i><i style="width:${(Math.min(need, d.left) / DUTY) * 100}%;background:${d.ok ? "var(--violet)" : "var(--red)"}"></i></div><span class="xs mono">${d.left.toFixed(1)} h left</span></div></div>
        <span class="tag ${d.ok ? "ok" : "bad"}">${d.ok ? "fits" : "short"}</span></div>`).join("")}</div>
      <p class="note">Illustrative ${DUTY} h driving limit; no duty-hour data in the backend.</p>`;
    if (animate) $$("#drvChain .ch").forEach((c, i) => setTimeout(() => c.classList.add("on", i === 3 ? "ai" : i === 4 && !vehOk ? "bad" : "ok"), REDUCED ? 0 : 200 + i * 380));
    else $$("#drvChain .ch").forEach((c) => c.classList.add("on"));
  }

  function init() {
    $("#ordFilter").addEventListener("change", table);
    $("#ordSearch").addEventListener("input", table);
    $("#openSupport").addEventListener("click", () => openSupport(cur));
    $("#supportScrim").addEventListener("click", closeSupport);
    document.addEventListener("keydown", (e) => { const d = $("#supportDrawer"); if (d.hidden) return; if (e.key === "Escape") closeSupport(); if (e.key === "Tab") { const f = $$("button, select, textarea, input, [tabindex]", d).filter((x) => !x.disabled); if (!f.length) return; const i = f.indexOf(document.activeElement); if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus(); } else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); f[0].focus(); } } });
    on("select", ({ kind, id }) => { if (PAGE !== "business" || kind !== "vehicle") return; const o = orders.find((x) => x.vehicle === id); if (o) { cur = o; table(); bflow(); detail(o, true); drivers(true); } });
  }
  return {
    init,
    async enter() { await load(); detail(cur, true); drivers(true); clearInterval(timer); timer = setInterval(() => PAGE === "business" && load(), 5000); TWIN.ready.then(() => { TWIN.clearRoutes(); TWIN.clearHighlight(); }); },
    leave() { clearInterval(timer); if ($("#supportDrawer") && !$("#supportDrawer").hidden) closeSupport(); },
  };
})();
