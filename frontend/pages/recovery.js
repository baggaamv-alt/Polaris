/* AI RECOVERY: route intelligence (alternative routes drawn on the map, user priorities, explanation of why the
 * winner changes), the multimodal cost engine (animated waterfall), and the self-healing reroute workflow
 * (disruption → alternatives → comparison → human approval → truck physically reroutes in the simulated world). */
"use strict";
PAGES.recovery = (() => {
  let costOpen = false, prio = null, plan = null, selRoute = null, prevW = null, reqId = 0;
  let heal = { vid: null, opts: null, approved: null, recovered: false };
  const METRIC_COL = { money: "var(--amber)", time: "var(--primary)", fuel: "var(--red)", distance: "var(--cyan)", carbon: "var(--green)", risk: "var(--violet)" };
  const LANES = [["W-HYD", "W-VGA", "HYD → VGA · truck vs rail"], ["P-JNP", "W-DEL", "JNPT → Delhi · ship + rail"], ["W-HYD", "W-KOL", "HYD → Kolkata · 3 modes"], ["S02", "W-DEL", "Pharma → Delhi"]];

  function recLine() {
    const cur = plan && plan.routes && plan.routes[0], rec = plan && plan.routes.find((x) => x.id === plan.recommended);
    const c = plan && plan.current;
    causal("#recLine", [
      ["1 · Current route", plan ? `${plan.origin} → ${plan.destination}` : "choose a shipment", plan ? `${plan.units} pallets · ${plan.priority}${plan.closed_links.length ? ` · avoiding ${plan.closed_links.length} closed` : ""}` : "", plan ? "ok" : null],
      ["2 · Alternatives", plan ? `${plan.routes.length} routes` : "—", plan ? plan.routes.map((x) => x.label).join(" · ") : "", plan ? "ok" : null],
      ["3 · Trade-offs", plan ? (rec ? `${hrs(rec.time_h)} · ${inr(rec.total_cost)}` : "—") : "—", plan ? "set the weights on the sliders" : "", plan ? "ai" : null],
      ["4 · Recommended", rec ? `Route ${rec.label}` : "—", rec ? esc(rec.mode_label) : "", rec ? "ai" : null],
      ["5 · Human approval", heal.approved ? "approved" : "waiting", heal.approved ? `audit #${heal.approved.audit_seq}` : "approve in Self-healing", heal.approved ? "ok" : plan ? "warn" : null],
      ["6 · Recovery", heal.recovered ? "recovered" : heal.approved ? "rerouting" : "—", heal.approved ? "truck is on the new path" : "", heal.recovered ? "ok" : heal.approved ? "warn" : null],
    ]);
  }
  /* ------------------------------------------------------------ route intelligence */
  function odInit() {
    const opts = NET.nodes.filter((n) => n.type !== "CustomerCluster").map((n) => `<option value="${n.id}">${n.id} · ${esc(n.name)}</option>`).join("");
    $("#odFrom").innerHTML = opts; $("#odTo").innerHTML = opts + NET.nodes.filter((n) => n.type === "CustomerCluster").map((n) => `<option value="${n.id}">${n.id} · ${esc(n.name)}</option>`).join("");
    $("#odFrom").value = "W-HYD"; $("#odTo").value = "W-VGA";
    $("#odChips").innerHTML = LANES.map(([a, b, l]) => `<button class="chip" data-a="${a}" data-b="${b}">${esc(l)}</button>`).join("") + `<button class="chip" data-order="1">${ico("route")} From an at-risk order</button>`;
    $$("#odChips .chip").forEach((c) => c.addEventListener("click", () => {
      if (c.dataset.order) { const o = STATE && STATE.at_risk_orders && STATE.at_risk_orders[0]; if (!o) { toast("No order is at risk right now"); return; } loadOrder(o.vehicle); return; }
      $("#odFrom").value = c.dataset.a; $("#odTo").value = c.dataset.b; $("#odPrio").value = c.dataset.a === "S02" ? "CRITICAL" : "NORMAL"; $("#odHint").textContent = ""; replan(true); }));
    ["odFrom", "odTo", "odUnits", "odPrio"].forEach((id) => $(`#${id}`).addEventListener("change", () => replan(true)));
  }
  async function loadOrder(vid) {
    try { const orders = await api("/api/orders"); const o = orders.find((x) => x.vehicle === vid); if (!o) { toast(`${vid} carries no cargo right now`); return; }
      $("#odFrom").value = o.origin; $("#odTo").value = o.destination; $("#odUnits").value = o.units || 40; $("#odPrio").value = o.priority;
      $("#odHint").innerHTML = `order <b class="mono">${esc(o.id)}</b> · ${esc(o.sku)} ${esc(o.sku_class)} · <span class="tag ${o.priority}">${o.priority}</span>`;
      replan(true); } catch (e) { toast(e.message, "err"); }
  }
  async function replan(fresh = false) {
    const id = ++reqId;
    const w = prio.get();
    $("#routeCard").innerHTML = plan && !fresh ? $("#routeCard").innerHTML : loading("Finding routes…", 3);
    try {
      const body = { origin: $("#odFrom").value, destination: $("#odTo").value, units: +$("#odUnits").value || 40, priority: $("#odPrio").value, weights: shares(w) };
      if (!fresh && prevW) body.prev_weights = prevW;
      const r = await post("/api/routes/plan", body);
      if (id !== reqId) return;
      const oldRec = plan && !fresh ? plan.recommended : null;
      plan = r; prevW = shares(w);
      if (fresh || !selRoute || !r.routes.find((x) => x.id === selRoute)) selRoute = r.recommended;
      else if (oldRec !== r.recommended) selRoute = r.recommended;
      renderRoutes(r, fresh); recLine();
      TWIN.showRoutes(r.routes, r.recommended, { animate: fresh ? true : oldRec !== r.recommended ? "rec" : false, fit: fresh });
      renderCost(r.routes.find((x) => x.id === selRoute));
      if (!fresh && r.change && r.change.changed) toast(r.change.text, "ai");
    } catch (e) { if (id === reqId) $("#routeCard").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
  }
  function scorebar(r) {
    const c = r.contrib || {}; const tot = Object.values(c).reduce((a, b) => a + b, 0) || 1;
    return `<div class="scorebar" data-tip="Weighted score (lower is better): ${Object.entries(c).map(([k, v]) => `${k} ${v.toFixed(2)}`).join(" · ")}">${Object.entries(c).map(([k, v]) => `<i style="width:${(v / tot) * 100}%;background:${METRIC_COL[k]}"></i>`).join("")}</div>`;
  }
  function renderRoutes(r, fresh) {
    const rec = r.routes.find((x) => x.id === r.recommended);
    const ch = r.change && r.change.changed ? (() => { const from = r.routes.find((x) => x.id === r.change.from), to = r.routes.find((x) => x.id === r.change.to);
      return `<div class="change">${pxImg("robot", { scale: 2 })}<div class="sw"><span style="color:${ROUTE_COLORS[r.routes.indexOf(from)]}">${from.label}</span><i>→</i><span style="color:var(--violet)">${to.label}</span></div><div>${esc(r.change.text)}</div></div>`; })() : "";
    $("#routeCard").innerHTML = `<div class="card-h"><h2>Alternative routes</h2><span class="sub">${esc(r.origin)} → ${esc(r.destination)} · ${r.units} pallets · <span class="tag ${r.priority}">${r.priority}</span></span>
        <div class="right">${r.closed_links.length ? `<span class="tag bad" data-tip="Closed links avoided: ${esc(r.closed_links.join(", "))}">avoiding ${r.closed_links.length} closed</span>` : ""}<span class="xs muted">simulated costs</span></div></div>
      <div class="routes">${r.routes.map((x, i) => `<div class="rcard ${x.id === r.recommended ? "rec" : ""} ${x.id === selRoute ? "sel" : ""} ${x.sla_ok ? "" : "late"}" data-id="${x.id}" style="--rc:${ROUTE_COLORS[i]};animation-delay:${fresh ? i * 120 : 0}ms">
          <div class="lt">${x.label}</div>
          <div><div class="nm">${esc(x.mode_label)} ${x.sla_ok ? "" : '<span class="tag bad">misses SLA</span>'} ${x.risk >= 0.2 ? `<span class="tag warn">risk ${pct(x.risk, 0)}</span>` : ""}</div>
            <div class="mt"><span>${hrs(x.time_h)}</span><span>${km(x.distance_km)}</span><span>${Math.round(x.co2_kg).toLocaleString("en-IN")} kg CO₂</span><span><i>fuel</i> ${inr(x.energy_cost)}</span><span><i>cap</i> ${x.capacity_units_day.toLocaleString("en-IN")}/d</span></div>
            ${scorebar(x)}</div>
          <div class="pr"><b>${inr(x.total_cost)}</b><span>${(x.risk * 100).toFixed(0)}% risk · ${(x.exposure * 100).toFixed(0)}% exposed</span></div></div>`).join("")}</div>
      ${ch}
      <div class="why"><h4>${pxImg("robot", { scale: 1 })} Why route ${rec.label}?</h4><ul>${r.why.map((l) => `<li>${esc(l)}</li>`).join("")}</ul></div>
      <div class="row xs muted" style="gap:10px;margin-top:8px;flex-wrap:wrap">${Object.entries(METRIC_COL).map(([k, c]) => `<span><span style="color:${c}">■</span> ${k}</span>`).join("")}<span>· bar = weighted score contribution (shorter wins)</span></div>`;
    $$("#routeCard .rcard").forEach((el) => el.addEventListener("click", () => { selRoute = el.dataset.id; $$("#routeCard .rcard").forEach((x) => x.classList.toggle("sel", x === el));
      const i = plan.routes.findIndex((x) => x.id === selRoute); TWIN.focusRoute(i); renderCost(plan.routes[i]); }));
  }
  on("select", ({ kind, id }) => {
    if (PAGE !== "recovery" || kind !== "vehicle") return;
    if ($('#recTabs button.on').dataset.t === "routes") loadOrder(id); else options(id);
  });
  on("routeclick", (i) => { if (PAGE !== "recovery" || !plan || !plan.routes[i]) return; const el = $(`#routeCard .rcard[data-id="${plan.routes[i].id}"]`); if (el) el.click(); });

  /* ------------------------------------------------------------ multimodal cost engine */
  function renderCost(r) {
    if (!r) { $("#costCard").innerHTML = ""; return; }
    const energy = r.energy.map((e) => `${Math.round(e.qty).toLocaleString("en-IN")} ${e.unit}`).join(" + ");
    const parts = [["Fuel / energy cost", r.energy_cost, "var(--red)", ico("fuel")], ["Tolls", r.tolls, "var(--amber)", ico("route")], ["Operating (crew, fixed)", r.operating, "var(--primary)", ico("gear")],
      ["Maintenance", r.maintenance, "var(--cyan)", ico("wrench")], ["Handling / terminals", r.handling, "var(--violet)", ico("box")]];
    const tot = r.total_cost || 1;
    let cum = 0;
    const rows = parts.map(([l, v, c, ic]) => { const left = (cum / tot) * 100; cum += v; return `<div class="w" style="--wc:${c}"><span class="lb">${ic} ${l}</span><div class="bar"><i data-l="${left}" data-w="${(v / tot) * 100}"></i></div><span class="val">${inr(v)}</span></div>`; }).join("");
    const byMix = {};
    plan.routes.forEach((x) => { if (!byMix[x.mode_label] || byMix[x.mode_label].total_cost > x.total_cost) byMix[x.mode_label] = x; });
    const mixes = Object.values(byMix);
    const mx = { c: Math.max(...mixes.map((x) => x.total_cost)), t: Math.max(...mixes.map((x) => x.time_h)), e: Math.max(...mixes.map((x) => x.co2_kg)) };
    const tr = r.transfers.map((t) => `${esc(t.at)} ${t.from_mode}→${t.to_mode} (${esc(t.note)}, +${t.hours} h)`).join("; ");
    $("#costCard").innerHTML = `<div class="card-h"><h2>Multimodal cost engine</h2><span class="sub">route ${r.label} · ${esc(r.nodes[0])} → ${esc(r.nodes[r.nodes.length - 1])}</span><div class="right">${dm("sim", "simulated assumptions")}</div></div>
      <div class="wf" id="wf">
        <div class="w meta"><span class="lb">${ico("ruler")} Distance</span><div class="bar">${esc(r.legs.map((l) => `${l.mode} ${Math.round(l.distance_km)} km`).join(" + "))}</div><span class="val">${km(r.distance_km)}</span></div>
        <div class="w meta"><span class="lb">${ico("fuel")} Fuel / energy use</span><div class="bar">${esc(energy)}</div><span class="val">${hrs(r.time_h)}</span></div>
        ${rows}
        <div class="w total"><span class="lb"><b>TOTAL</b></span><div class="bar"><i data-l="0" data-w="100" style="--wc:linear-gradient(90deg,var(--primary),var(--violet))"></i></div><span class="val" id="wfTot">${inr(r.total_cost)}</span></div>
      </div>
      <p class="note">${inr(r.cost_per_unit)} per pallet · ${Math.round(r.co2_kg).toLocaleString("en-IN")} kg CO₂${tr ? ` · transfers: ${tr}` : ""}</p>
      <div class="divider"></div><div class="eyebrow" style="margin-bottom:6px">Best option per mode</div>
      <div class="modecmp">${mixes.map((x) => { const i = plan.routes.indexOf(x); return `<div class="m"><span><b style="color:${ROUTE_COLORS[i]}">${x.label}</b> ${esc(x.mode_label)}</span>
        <div style="display:grid;gap:3px"><div class="b"><i data-w="${(x.total_cost / mx.c) * 100}" style="background:var(--amber)"></i></div><div class="b"><i data-w="${(x.time_h / mx.t) * 100}" style="background:var(--primary)"></i></div><div class="b"><i data-w="${(x.co2_kg / mx.e) * 100}" style="background:var(--green)"></i></div></div>
        <span class="mono xs" style="text-align:right">${inr(x.total_cost)}<br>${hrs(x.time_h)}<br>${Math.round(x.co2_kg)} kg</span></div>`; }).join("")}</div>
      <div class="row xs muted" style="gap:10px;margin-top:4px"><span><span style="color:var(--amber)">■</span> cost</span><span><span style="color:var(--primary)">■</span> time</span><span><span style="color:var(--green)">■</span> CO₂</span></div>
      <details style="margin-top:8px" id="costAss"><summary class="xs muted" style="cursor:pointer">Assumptions (${esc(plan.assumptions.label)}) · editable</summary>
        <div class="form-grid" style="margin-top:8px">${[["road_fuel_inr_per_l", "Diesel ₹/L", plan.assumptions.road.fuel_inr_per_l], ["road_km_per_l", "Truck km/L", plan.assumptions.road.km_per_l], ["road_toll_inr_per_km", "Toll ₹/km", plan.assumptions.road.toll_inr_per_km],
          ["road_crew_inr_per_h", "Crew ₹/h", plan.assumptions.road.crew_inr_per_h], ["rail_inr_per_kwh", "Rail ₹/kWh", plan.assumptions.rail.inr_per_kwh], ["sea_fuel_inr_per_l", "Marine fuel ₹/L", plan.assumptions.sea.fuel_inr_per_l]]
          .map(([k, l, v]) => `<label class="field">${l}<input type="number" step="0.1" data-cost="${k}" value="${v}"></label>`).join("")}</div>
        <div class="row" style="margin-top:6px"><button class="btn ghost sm" id="costApply">Apply &amp; re-plan</button><button class="btn quiet sm" id="costReset">Reset to defaults</button></div>
        <div class="xs mono" style="margin-top:6px;line-height:1.7;color:var(--text-2)">Road: diesel ₹${plan.assumptions.road.fuel_inr_per_l}/L · ${plan.assumptions.road.km_per_l} km/L · toll ₹${plan.assumptions.road.toll_inr_per_km}/km · crew ₹${plan.assumptions.road.crew_inr_per_h}/h · operating ₹${plan.assumptions.road.operating_inr_per_km}/km · maintenance ₹${plan.assumptions.road.maintenance_inr_per_km}/km · ${plan.assumptions.road.truck_units} pallets/truck<br>
          Rail: ${plan.assumptions.rail.kwh_per_tkm} kWh/t·km at ₹${plan.assumptions.rail.inr_per_kwh}/kWh · operating ₹${plan.assumptions.rail.operating_inr_per_tkm}/t·km · maintenance ₹${plan.assumptions.rail.maintenance_inr_per_tkm}/t·km<br>
          Sea: ${plan.assumptions.sea.fuel_l_per_tkm} L/t·km at ₹${plan.assumptions.sea.fuel_inr_per_l}/L · operating ₹${plan.assumptions.sea.operating_inr_per_tkm}/t·km<br>
          Transfers: ${plan.assumptions.transfer.map((t) => `${t.from}→${t.to} ₹${t.inr_per_tonne}/t +${t.hours}h`).join(" · ")} · ${plan.assumptions.pallet_tonnes} t/pallet<br>Carbon: ${esc(plan.assumptions.carbon)}</div></details>`;
    if (costOpen) $("#costAss").open = true;
    $("#costAss").addEventListener("toggle", (e) => (costOpen = e.target.open));
    const applyCost = async (reset) => {
      const body = reset ? { reset: true } : Object.fromEntries($$("#costAss [data-cost]").map((i) => [i.dataset.cost, +i.value]));
      try { await post("/api/cost/assumptions", body); toast(reset ? "Cost assumptions reset" : "Cost assumptions applied · routes re-priced", "ok"); replan(true); } catch (e) { toast(e.message, "err"); }
    };
    $("#costApply").addEventListener("click", () => applyCost(false)); $("#costReset").addEventListener("click", () => applyCost(true));
    // sequential waterfall reveal
    const rowsEl = $$("#wf .w");
    rowsEl.forEach((el, i) => setTimeout(() => { el.classList.add("on"); const b = $(".bar i", el); if (b) { b.style.left = `${b.dataset.l}%`; b.style.width = `${b.dataset.w}%`; } }, REDUCED ? 0 : 120 + i * 230));
    $("#wfTot").dataset.v = 0;
    countTo($("#wfTot"), r.total_cost, (x) => inr(x), REDUCED ? 0 : 1800);
    setTimeout(() => $$("#costCard .modecmp .b i").forEach((i) => (i.style.width = `${i.dataset.w}%`)), 60);
  }

  /* ------------------------------------------------------------ self-healing workflow */
  const HEAL = [['<i class="dot ok"></i>', "Route active", "trucks on planned routes"], ['<i class="dot warn"></i>', "Route degrading", "suspected blockage or declared incident"], ['<i class="dot bad"></i>', "Disruption detected", "closure confirmed on a route ahead"],
    [ico("spark"), "Alternative route generated", "k-shortest open paths from the pivot node"], [ico("sliders"), "Options compared", "cost · time · fuel · distance · CO₂ · risk"], [ico("user"), "Operator approval", "nothing moves without a human"],
    [ico("route"), "Rerouting", "the truck drives the new path in the simulated world"], [ico("check"), "Recovered", "off the closure, moving, telemetry still trusted"]];
  function healFlow() {
    const s = STATE || {};
    const degr = Object.values(s.links || {}).some((l) => l.status === "suspected") || (s.incidents || []).length > 0;
    const det = Object.values(s.links || {}).some((l) => l.status !== "open" && l.status !== "suspected") || (s.at_risk_orders || []).some((o) => o.status === "AT_RISK");
    const st = [true, degr || det, det, !!heal.opts, !!heal.opts, !!heal.approved, !!heal.approved, heal.recovered];
    let nowIdx = st.findIndex((x) => !x); if (nowIdx < 0) nowIdx = 8;
    $("#healFlow").innerHTML = HEAL.map(([ic, b, p], i) => `<div class="fs ${st[i] ? "done" : i === nowIdx ? "now" : ""} ${i === 2 && st[i] && !heal.approved ? "bad" : ""} ${(i === 3 || i === 4) && st[i] && !heal.approved ? "ai" : ""}">
      <span class="dot">${st[i] ? ico("check", 12) : ic}</span><div><b>${b}</b><p>${p}</p></div><span class="t">${i === 6 && heal.approved ? `audit #${heal.approved.audit_seq}` : i === 3 && heal.opts ? `${heal.opts.routes.length} options` : ""}</span></div>`).join("");
  }
  async function healList() {
    let aff = [];
    try { aff = await api("/api/recovery/affected"); } catch { /* retry */ }
    if (heal.vid && heal.approved && !aff.find((a) => a.vehicle === heal.vid)) {
      const v = STATE && STATE.vehicles.find((x) => x.id === heal.vid);
      if (v && v.speed > 5 && !heal.recovered) { heal.recovered = true; recLine(); toast(`${heal.vid} recovered: moving on its new route`, "ok"); }
    }
    healFlow();
    const pr = { CRITICAL: 0, HIGH: 1, NORMAL: 2 };
    aff.sort((a, b) => pr[a.priority] - pr[b.priority]);
    $("#healList").innerHTML = aff.length ? `<div class="row" style="margin-bottom:8px"><span class="xs muted">${aff.length} truck${aff.length > 1 ? "s" : ""} will reach a closure${aff.some((a) => a.cause === "weather") ? " or severe real weather" : ""}</span><span class="spacer"></span><button class="btn ai sm" id="healAll">${ico("spark")} Generate &amp; approve AI plan for all (${aff.length})</button></div>
      <div class="list">${aff.slice(0, 10).map((o) => `<div class="li click ${o.vehicle === heal.vid ? "on" : ""}" data-v="${esc(o.vehicle)}"><span class="tag ${o.priority}">${o.priority}</span><span class="mono">${esc(o.vehicle)}</span>
        <span class="xs muted" style="flex:1">${o.units ? `${o.units} pallets ${esc(o.sku)}` : "empty"} → ${esc(o.destination)} · ${o.cause === "weather" ? `<span class="tag warn">weather</span> ${esc(o.weather_ahead[0].level.toLowerCase())} on <b class="mono">${esc(o.weather_ahead[0].link)}</b> in ~${o.weather_ahead[0].in_h} h · +${o.weather_delay_h} h (real forecast)` : `blocked at <b class="mono">${esc(o.blocked_ahead[0])}</b>${o.turnaround_needed ? " · must turn back" : ""}`}</span><button class="btn sm">Alternatives</button></div>`).join("")}</div>`
      : empty("check", "No truck is heading into a closure", "", '<a class="btn ghost sm" href="#/incident" style="margin-top:6px">Incident Simulator</a>');
    $$("#healList .li").forEach((el) => el.addEventListener("click", () => options(el.dataset.v)));
    const all = $("#healAll"); if (all) all.addEventListener("click", () => approveAll(aff, all));
  }
  async function options(vid) {
    heal = { vid, opts: null, approved: null, recovered: false };
    healFlow();
    $$("#healList .li").forEach((x) => x.classList.toggle("on", x.dataset.v === vid));
    TWIN.select("vehicle", vid, { fly: false });
    $("#healOptions").innerHTML = loading("Finding alternatives…", 3);
    try {
      const r = await post("/api/recovery/options", { vehicle_id: vid, weights: shares(prio.get()) });
      if (r.error) { $("#healOptions").innerHTML = `<p class="muted small">${esc(r.error)}</p>`; return; }
      heal.opts = r; healFlow();
      const health = await api("/api/fleet/health").then((l) => l.find((x) => x.vehicle === vid)).catch(() => null);
      const o = r.order, rec = r.routes.find((x) => x.id === r.recommended);
      $("#healOptions").innerHTML = `<div class="card-h"><h2>Recovery options · <span class="mono">${esc(vid)}</span></h2><span class="sub">${o.units ? `${o.units} pallets ${esc(o.sku)} (${esc(o.sku_class)})` : "empty"} → ${esc(o.destination)}</span><div class="right"><span class="tag ${o.priority}">${o.priority}</span></div></div>
        <div class="callout bad" style="margin-bottom:8px">${pxImg("warning", { scale: 2 })}<div><h3>Current route blocked at ${esc(r.current.blocked.join(", "))}</h3><p>${r.pivot.turnaround ? `Turn back to <b>${esc(r.pivot.pivot)}</b>.` : `Continue to <b>${esc(r.pivot.pivot)}</b>, then divert.`}</p></div></div>
        ${health && health.tier !== "LOW" && o.priority === "CRITICAL" ? `<div class="callout warn" style="margin-bottom:8px">${pxImg("gear", { scale: 2 })}<div><h3>Critical cargo on a ${health.tier.toLowerCase()}-risk vehicle</h3><p>${esc(health.reasons.join(" · "))}. Consider a cross-dock at ${esc(r.pivot.pivot)}.</p></div></div>` : ""}
        <div class="routes">${r.routes.map((x, i) => `<div class="rcard ${x.id === r.recommended ? "rec" : ""} ${x.sla_ok ? "" : "late"}" style="--rc:${ROUTE_COLORS[i]};animation-delay:${i * 120}ms" data-id="${x.id}">
          <div class="lt">${x.label}</div><div><div class="nm">${esc(x.hops.map((h) => h[0]).join(" → "))} ${x.sla_ok ? "" : '<span class="tag bad">misses SLA</span>'}</div>
          <div class="mt"><span>${hrs(x.time_h)}</span><span>${km(x.distance_km)}</span><span>${Math.round(x.co2_kg)} kg CO₂</span><span>risk ${pct(x.risk, 0)}</span></div>${scorebar(x)}</div>
          <div class="pr"><b>${inr(x.total_cost)}</b><span>incl. lead-in leg</span></div></div>`).join("")}</div>
        <div class="why"><h4>${pxImg("robot", { scale: 1 })} Why route ${rec.label}?</h4><ul>${r.why.map((l) => `<li>${esc(l)}</li>`).join("")}</ul></div>
        <div class="row wrap" style="margin-top:10px"><button class="btn good" id="healApprove">${ico("user")} Approve route ${rec.label}</button><span class="xs muted">Logged to the audit chain.</span></div>`;
      let chosen = rec;
      $$("#healOptions .rcard").forEach((el) => el.addEventListener("click", () => { chosen = r.routes.find((x) => x.id === el.dataset.id); $$("#healOptions .rcard").forEach((x) => x.classList.toggle("sel", x === el));
        TWIN.focusRoute(r.routes.indexOf(chosen)); $("#healApprove").innerHTML = `${ico("user")} Approve route ${chosen.label}`; }));
      $("#healApprove").addEventListener("click", (e) => approve(vid, chosen, e.currentTarget));
      TWIN.highlight({ links: r.current.blocked }, false);
      TWIN.showRoutes(r.routes, r.recommended, { animate: true, fit: true });
    } catch (e) { $("#healOptions").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
  }
  async function approve(vid, route, btn) {
    busy(btn, true);
    try {
      const rec = await post("/api/recovery/approve", { vehicle_id: vid, route_id: route.id, hops: route.hops, approver: "operator", note: `route ${route.label}` });
      heal.approved = rec; healFlow(); recLine();
      toast(`Approved · ${vid} rerouting via ${rec.new_route.slice(1, 3).join(" → ")} (audit #${rec.audit_seq})`, "ok");
      busy(btn, false); btn.disabled = true; btn.innerHTML = ico("check") + " Approved · rerouting";
      TWIN.showRoutes([route], route.id, { animate: "rec", fit: false });
      TWIN.select("vehicle", vid); TWIN.camera.go("vehicle");
      setTimeout(healList, 2500);
    } catch (e) { toast(e.message, "err"); busy(btn, false); }
  }
  async function approveAll(aff, btn) {
    busy(btn, true);
    let ok = 0;
    for (const o of aff.slice(0, 25)) {
      try { const r = await post("/api/recovery/options", { vehicle_id: o.vehicle, weights: shares(prio.get()) }); if (r.error || !r.routes || !r.routes.length) continue;
        const rec = r.routes.find((x) => x.id === r.recommended);
        await post("/api/recovery/approve", { vehicle_id: o.vehicle, route_id: rec.id, hops: rec.hops, approver: "operator (batch)", note: "batch AI plan" }); ok++;
        btn.textContent = `Rerouting… ${ok}/${aff.length}`;
      } catch { /* a truck may have moved on; skip */ }
    }
    toast(`${ok} trucks rerouted after approval · each decision is in the audit chain`, "ok");
    heal = { vid: null, opts: { routes: [] }, approved: { audit_seq: "batch" }, recovered: false };
    busy(btn, false); healList();
  }

  function init() {
    odInit();
    prio = prioSliders($("#recPrio"), { money: 40, time: 25, fuel: 15, distance: 10, carbon: 10 }, () => { if (PAGE === "recovery" && $('#recTabs button.on').dataset.t === "routes") replan(false); });
    $$("#recTabs button").forEach((b) => b.addEventListener("click", () => { $$("#recTabs button").forEach((x) => x.classList.toggle("on", x === b));
      $$('#panel [data-page="recovery"] .tabp').forEach((p) => p.classList.toggle("on", p.dataset.t === b.dataset.t));
      if (b.dataset.t === "heal") { TWIN.clearRoutes(); healList(); $("#reallocCard").innerHTML = reallocHTML(SCN); bindRealloc(SCN); if (!heal.opts) $("#healOptions").innerHTML = empty("robot", "Pick a truck"); }
      else if (plan) TWIN.showRoutes(plan.routes, plan.recommended, { animate: true, fit: true }); }));
    $("#healRefresh").addEventListener("click", healList);
    setInterval(() => { if (PAGE === "recovery" && $('#recTabs button.on').dataset.t === "heal") healList(); }, 4000);
    on("state", () => { if (PAGE === "recovery") healFlow(); });
  }
  return {
    init,
    enter() {
      recLine();
      const o = sessionStorage.getItem("pnt1.planOrder"); if (o) { sessionStorage.removeItem("pnt1.planOrder"); $$("#recTabs button")[0].click(); loadOrder(o); return; }
      if (sessionStorage.getItem("pnt1.healTab")) { sessionStorage.removeItem("pnt1.healTab"); $$("#recTabs button")[1].click(); return; }
      const hv = sessionStorage.getItem("pnt1.healVehicle"); if (hv) { sessionStorage.removeItem("pnt1.healVehicle"); $$("#recTabs button")[1].click(); options(hv); return; }
      if ($('#recTabs button.on').dataset.t === "routes") { if (plan) TWIN.ready.then(() => TWIN.showRoutes(plan.routes, plan.recommended, { animate: true, fit: true })); else replan(true); }
      else { healList(); $("#reallocCard").innerHTML = reallocHTML(SCN); bindRealloc(SCN); }
      healFlow();
    },
    leave() { TWIN.clearRoutes(); TWIN.clearHighlight(); },
  };
})();
