/* INCIDENT SIMULATOR: physical incidents (live injection into the simulated world + 72-hour forecast with the
 * OR-Tools LP and Monte Carlo engine), Resilience Engine signal convergence, cascade, weather chain, reallocation,
 * and the Attack Center (defensive data-attack simulation, quarantine, raw-vs-trusted). */
"use strict";
// [kind, sprite, title, description, default target, live?, default start (h), default duration (h), magnitude]
const INC_TYPES = [
  ["link_closure", "truck", "Road closure", "One corridor closes", "L053", true, 0, 8, 0.6],
  ["storm", "bolt", "Severe storm", "Road and rail close", "L053", true, 0, 12, 0.6],
  ["port_closure", "port", "Port closure", "Port stops handling", "P-JNP", true, 6, 48, 0.6],
  ["warehouse_failure", "warehouse", "Hub failure", "Warehouse stops shipping", "W-VGA", true, 6, 36, 0.6],
  ["supplier_failure", "supplier", "Supplier outage", "Supplier loses output", "S02", true, 6, 48, 0.9],
  ["demand_spike", "pin", "Demand spike", "Orders surge", "all", false, 6, 36, 0.6],
];
const SCN_LABEL = Object.fromEntries(INC_TYPES.map((x) => [x[0], x[2]]));

/* ---------------------------------------------------------------- 72-hour timeline (shared with Proof/time machine) */
const TIMELINE = (() => {
  let res = null, plan = "do_nothing", h = 0, playing = null;
  function frameOf(key, hour) { const fr = (res.frames[key] || res.frames.do_nothing).frames; return fr[Math.min(hour, fr.length - 1)]; }
  function stateFromRatio(r) { return r <= 0.05 ? "critical" : r < 1 ? "warning" : "healthy"; }
  function apply() {
    if (!res) return;
    const key = plan === "rec" ? res.recommended : "do_nothing";
    const f = frameOf(key, h), period = Math.min(11, Math.floor(h / 6));
    const links = {}; f.blocked.forEach((l) => (links[l] = { status: "blocked" }));
    const nodes = {}; const stock = {};
    Object.entries(f.wh).forEach(([w, v]) => { nodes[w] = stateFromRatio(v.ratio); stock[w] = v.inv; });
    const inp = res.input;
    const active = h >= inp.start_h && h < inp.start_h + inp.duration_h;
    const rippleNodes = active && NODE[inp.target] ? [inp.target] : [];
    if (active && NODE[inp.target]) nodes[inp.target] = "critical";
    TWIN.setScenarioFrame({ links, nodes, stock, rippleNodes });
    const lf = (res.frames[key] || res.frames.do_nothing).link_flows || {};
    TWIN.setFlows(Object.fromEntries(Object.entries(lf).map(([l, arr]) => [l, (arr[period] || 0) * 4])), "scenario");
    TWIN.chips();
    // dock readout
    const atRisk = Object.values(f.wh).filter((v) => v.ratio < 1).length, out = Object.values(f.wh).filter((v) => v.ratio <= 0.05).length;
    $("#tlH").innerHTML = `${h === 0 ? "NOW" : `+${h}h`}<small>${plan === "rec" ? NAMES[res.recommended] : "no response"}</small>`;
    $("#tlFill").style.width = `${(h / 71) * 100}%`;
    $$("#tl .mk").forEach((m) => m.classList.toggle("on", +m.dataset.h <= h));
    $("#tlRead").innerHTML = `<span class="tag ${active ? "bad" : "ok"}">${active ? "disruption active" : h < inp.start_h ? "before" : "after"}</span>
      <span class="tag ${out ? "bad" : atRisk ? "warn" : "ok"}">${atRisk} hubs below safety · ${out} out</span><span class="tag sim">unmet ${Math.round(f.unmet_cum).toLocaleString("en-IN")} units</span>`;
    const card = $("#tlMetrics");
    if (card) card.innerHTML = [["Hour", h === 0 ? "NOW" : `T+${h}h`], ["Hubs below safety", atRisk], ["Hubs out of stock", out], ["Links blocked", f.blocked.length], ["Unmet units (cum.)", Math.round(f.unmet_cum).toLocaleString("en-IN")]]
      .map(([l, v]) => `<div class="stat"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("");
  }
  function mount(r) {
    res = r; h = 0; plan = "rec";
    const inp = r.input;
    const marks = [0, 6, 12, 24, 48, 71];
    const pctH = (x) => `${(x / 71) * 100}%`;
    const fr = r.frames.do_nothing.frames;
    const firstBelow = fr.findIndex((f) => Object.values(f.wh).some((v) => v.ratio < 1));
    const so = Object.values(r.frames.do_nothing.first_stockout_h || {}); const firstOut = so.length ? Math.min(...so) : -1;
    const tr = (r.plan_diff && r.plan_diff.transfers[0]) ? Math.min(...r.plan_diff.transfers.map((t) => t.start_h)) : -1;
    const evs = [[inp.start_h, "bad", "Disruption starts"], firstBelow >= 0 && [firstBelow, "", "First hub below safety stock"], firstOut >= 0 && [firstOut, "bad", "First stockout (no response)"],
      tr >= 0 && [tr, "ai", "AI plan: stock transfer starts"], [Math.min(71, inp.start_h + inp.duration_h), "ok", "Disruption window ends"]].filter(Boolean);
    const dock = $("#dock"); dock.hidden = false; $("#mapwrap").classList.add("docked");
    dock.innerHTML = `<div class="tlabel" id="tlH">NOW</div>
      <div class="tline" id="tl"><div class="track"></div><div class="dis" style="left:${pctH(inp.start_h)};width:${pctH(Math.min(71 - inp.start_h, inp.duration_h))}"></div><div class="fill" id="tlFill"></div>
        ${marks.map((m) => `<span class="mk" data-h="${m}" style="left:${pctH(m)}">${m === 0 ? "NOW" : `+${m === 71 ? 72 : m}H`}</span>`).join("")}
        ${evs.map(([x, c, t]) => `<span class="ev ${c}" style="left:${pctH(Math.min(71, x))}" data-tip="${esc(t)} · T+${x}h"></span>`).join("")}
        <input type="range" id="tlR" min="0" max="71" value="0" aria-label="Forecast hour"></div>
      <div class="dm-row"><span class="seg" id="tlPlan"><button data-v="do_nothing">No response</button><button data-v="rec" class="on">AI plan</button></span>
        <button class="btn sm" id="tlPlay">${ico("play")} Play</button><button class="btn ghost sm" id="tlClose" title="Back to live">Live</button></div>
      <div></div><div class="row wrap" id="tlRead" style="gap:6px"></div><div></div>`;
    $("#tlR").addEventListener("input", (e) => { h = +e.target.value; stop(); apply(); });
    $$("#tl .mk").forEach((m) => m.addEventListener("click", () => { h = Math.min(71, +m.dataset.h); $("#tlR").value = h; stop(); apply(); }));
    $$("#tlPlan button").forEach((b) => b.addEventListener("click", () => { plan = b.dataset.v; $$("#tlPlan button").forEach((x) => x.classList.toggle("on", x === b)); apply(); }));
    $("#tlPlay").addEventListener("click", () => (playing ? stop() : play()));
    $("#tlClose").addEventListener("click", unmount);
    const coords = [...r.blocked_links.filter((l) => LINK[l]).flatMap((l) => LINK[l].coords), ...(NODE[inp.target] ? [[NODE[inp.target].lon, NODE[inp.target].lat]] : [])];
    if (coords.length) TWIN.camera.fit(coords, { pitch: 40, maxZoom: 6.2, padding: 120 });
    apply();
  }
  function play(from = null) {
    if (from != null) h = from;
    $("#tlPlay").innerHTML = ico("pause") + " Pause";
    playing = setInterval(() => { h = (h + 1) % 72; $("#tlR").value = h; apply(); if (h === 71) stop(); }, REDUCED ? 400 : 140);
  }
  function stop() { clearInterval(playing); playing = null; const b = $("#tlPlay"); if (b) b.innerHTML = ico("play") + " Play"; }
  function unmount() { stop(); res = null; $("#dock").hidden = true; $("#mapwrap").classList.remove("docked"); TWIN.clearScenario(); TWIN.chips(); }
  function goto(hour) { if (!res) return; stop(); h = hour; $("#tlR").value = h; apply(); }
  return { mount, unmount, play, goto, get active() { return !!res; } };
})();

PAGES.incident = (() => {
  let kind = "link_closure", prio = null, watchId = null, CATALOG = null;

  /* ------------------------------------------------------------ physical incidents */
  function tiles() {
    $("#incTiles").innerHTML = INC_TYPES.map(([k, spr, t, d, , live]) => `<button type="button" class="tile ${k === kind ? "on" : ""}" data-k="${k}">${pxImg(spr, { scale: 2, c: PX_PALETTE.n })}<b>${t}</b><span>${d}</span>${live ? "" : '<span class="xs muted">forecast only</span>'}</button>`).join("");
    $$("#incTiles .tile").forEach((b) => b.addEventListener("click", () => { kind = b.dataset.k; tiles(); targets(); defaults(); }));
    hint();
  }
  function defaults() { const t = INC_TYPES.find((x) => x[0] === kind); $("#incStart").value = t[6]; $("#incDur").value = t[7]; $("#incMag").value = t[8]; hint(); }
  function hint() {
    const live = INC_TYPES.find((x) => x[0] === kind)[5], st = +$("#incStart").value;
    $("#incLive").disabled = !live;
    $("#incLive").innerHTML = !live ? "Live not available" : st > 0 ? `${ico("clock")} Schedule live in ${st} h + forecast` : `${ico("bolt")} Inject live + forecast`;
    $("#incHint").textContent = !live ? "Forecast only." : st > 0
      ? `Starts in ${st} h.` : "";
  }
  function targets(def) {
    const d = def || INC_TYPES.find((x) => x[0] === kind)[4];
    let list;
    if (kind === "storm" || kind === "link_closure") list = NET.links.filter((l) => l.mode === "road").map((l) => [l.id, `${l.id} · ${l.corridor} (${l.from}→${l.to})`]);
    else { const type = { port_closure: "Port", warehouse_failure: "Warehouse", supplier_failure: "Supplier", demand_spike: "CustomerCluster" }[kind];
      list = NET.nodes.filter((n) => n.type === type).map((n) => [n.id, `${n.id} · ${n.name}`]); if (kind === "demand_spike") list.unshift(["all", "All customer clusters"]); }
    $("#incTarget").innerHTML = list.map(([v, t]) => `<option value="${v}" ${v === d ? "selected" : ""}>${esc(t)}</option>`).join("");
    previewTarget();
  }
  function previewTarget() {
    const v = $("#incTarget").value;
    if (LINK[v]) TWIN.highlight({ links: [v] }, false); else if (NODE[v]) TWIN.highlight({ nodes: [v] }, false); else TWIN.clearHighlight();
  }

  async function runForecast(btn, live) {
    const target = $("#incTarget").value, dur = +$("#incDur").value;
    busy(btn, true);
    try {
      if (live) {
        const inc = await post("/api/incidents", { kind, target, duration_h: dur, start_in_h: +$("#incStart").value, note: "Incident Simulator" });
        toast(inc.status === "scheduled" ? `${inc.label} scheduled in ${$("#incStart").value} h` : `${inc.label} injected into the live world`, "err");
      }
      $("#forecast").innerHTML = `<div class="card">${loading(`Running forecast…`, 4)}</div>`;
      const body = { kind, target, start_h: +$("#incStart").value, duration_h: dur, magnitude: +$("#incMag").value, probability: +$("#incProb").value,
        preset: "balanced", weights: shares(prio.get()), runs: +$("#incRuns").value };
      SCN = await post("/api/scenarios/run", body);
      renderForecast(SCN, true); causalLine();
      emit("scenario", SCN);
    } catch (e) { toast(e.message, "err"); $("#forecast").innerHTML = `<div class="card"><p class="error">Could not run: ${esc(e.message)}</p></div>`; }
    finally { busy(btn, false); }
  }

  function cascadeSteps(r) {
    const inp = r.input, dn = r.frames.do_nothing.frames, S = r.strategies, rec = r.recommended;
    const firstBlocked = dn.findIndex((f) => f.blocked.length);
    const below0 = Object.values(dn[0].wh).filter((v) => v.ratio < 1).length;
    const below = dn.findIndex((f, h) => h >= inp.start_h && Object.values(f.wh).filter((v) => v.ratio < 1).length > below0);
    const belowW = below >= 0 ? Object.entries(dn[below].wh).filter(([w, v]) => v.ratio < 1 && !(dn[0].wh[w].ratio < 1)).map(([w]) => w) : [];
    const so = r.frames.do_nothing.first_stockout_h || {}; const soE = Object.entries(so).sort((a, b) => a[1] - b[1]);
    const u0 = dn[Math.max(0, inp.start_h)].unmet_cum, uEnd = dn[dn.length - 1].unmet_cum;
    const back = dn.findIndex((f, h) => h > inp.start_h && f.unmet_cum - u0 > Math.max(20, 0.1 * (uEnd - u0)));
    const tr = r.plan_diff.transfers, rr = r.plan_diff.rerouted_links;
    const serv0 = S.do_nothing.if_disrupted.service_mean, servR = S[rec].if_disrupted.service_mean;
    return [
      ["warning", SCN_LABEL[inp.kind] || inp.kind, `T+${inp.start_h}h`, inp.target, "bad"],
      ["truck", "Transport delay", firstBlocked >= 0 ? `T+${firstBlocked}h` : "—", firstBlocked >= 0 ? `${dn[firstBlocked].blocked.length} links blocked` : "no links blocked", firstBlocked >= 0 ? "bad" : "ok"],
      ["warehouse", "Inventory drop", below >= 0 ? `T+${below}h` : "none", belowW.length ? `${belowW.slice(0, 2).join(", ")} below safety` : "stock holds", below >= 0 ? "warn" : "ok"],
      ["package", "Order backlog", soE.length ? `T+${soE[0][1]}h` : back >= 0 ? `T+${back}h` : "none", soE.length ? `${soE[0][0]} runs out` : back >= 0 ? `${Math.round(uEnd - u0).toLocaleString("en-IN")} units unmet by 72 h` : "no backlog", soE.length || back >= 0 ? "bad" : "ok"],
      ["robot", "Fleet rebalance", tr.length ? `T+${Math.min(...tr.map((t) => t.start_h))}h` : rr.length ? "replan" : "—", tr.length ? `${tr.length} AI transfers` : rr.length ? `${rr.length} lanes re-planned` : "network absorbs it", "ai"],
      ["radar", "Network impact", pct(serv0, 1), `service · AI plan ${pct(servR, 1)}`, servR > serv0 + 0.001 ? "ok" : "warn"],
    ];
  }
  function mcHTML(r) {
    const S = r.strategies, rec = r.recommended, mc = r.monte_carlo;
    const keys = [...new Set(["do_nothing", rec])];
    const maxBin = Math.max(1, ...keys.flatMap((k) => mc.cost_hist[k] || []));
    const col = { do_nothing: "var(--red)", [rec]: "var(--violet)" };
    return `<div class="stats">
        <div class="stat"><div class="v">${r.runs}</div><div class="l">futures simulated per plan</div></div>
        <div class="stat"><div class="v">${lakh(S[rec].expected_cost)}</div><div class="l">expected cost (${esc(NAMES[rec])})</div></div>
        <div class="stat"><div class="v">${pct(S[rec].if_disrupted.service_mean)}</div><div class="l">service level if it happens</div></div>
        <div class="stat"><div class="v">${Math.round(S[rec].if_disrupted.unmet_units_mean).toLocaleString("en-IN")}</div><div class="l">unmet units (mean)</div></div>
        <div class="stat"><div class="v">${lakh(S[rec].if_disrupted.cost_p10)}–${lakh(S[rec].if_disrupted.cost_p90)}</div><div class="l">P10–P90 cost range</div></div>
        <div class="stat"><div class="v">±${lakh(S[rec].if_disrupted.cost_std)}</div><div class="l">std deviation · ${pct(S[rec].if_disrupted.robustness, 0)} futures ≥95% service</div></div></div>
      <div class="eyebrow" style="margin:12px 0 6px">72 h cost distribution</div>
      <div style="position:relative">${keys.map((k, j) => `<div class="hist" style="${j ? "position:absolute;inset:0;" : ""}">${(mc.cost_hist[k] || []).map((c) => `<i style="height:${(c / maxBin) * 100}%;background:${col[k]};opacity:${j ? 0.55 : 0.4}"></i>`).join("")}</div>`).join("")}</div>
      <div class="row xs muted" style="justify-content:space-between;margin-top:4px"><span>${lakh(mc.cost_range[0])}</span><span>${keys.map((k) => `<span style="color:${col[k]}">■</span> ${esc(NAMES[k])}`).join(" &nbsp; ")}</span><span>${lakh(mc.cost_range[1])}</span></div>`;
  }
  function weatherHTML(r) {
    if (r.input.kind !== "storm") return "";
    const dn = r.frames.do_nothing.frames, below = dn.findIndex((f) => Object.values(f.wh).some((v) => v.ratio < 1));
    const lk = r.blocked_links.map((l) => LINK[l]).filter(Boolean);
    const extraH = lk.reduce((a, l) => a + l.base_time_h, 0) / Math.max(1, lk.length);
    return `<div class="card"><div class="card-h"><h2>Weather impact chain</h2></div>
      <div class="chain">${[["bolt", "Weather", "storm", "simulated scenario", "bad"], ["truck", "Road risk", `${lk.length} links`, "road + rail closed", "bad"],
        ["clock", "ETA", `+${extraH.toFixed(0)} h`, "detour vs corridor time", "warn"], ["warehouse", "Inventory", below >= 0 ? `T+${below}h` : "holds", "first hub below safety", "warn"],
        ["radar", "Network risk", pct(r.strategies.do_nothing.if_disrupted.service_mean), "service with no response", "warn"], ["robot", "Recovery option", NAMES[r.recommended], "AI recommendation", "ai"]]
        .map(([s, b, v, sm, c], i) => `<div class="ch ${c}" data-i="${i}"><div class="ic">${pxImg(s, { scale: 2, c: PX_PALETTE.n })}</div><b>${b}</b><span>${esc(v)}</span><small>${esc(sm)}</small></div>`).join("")}</div></div>`;
  }

  function renderForecast(r, animate) {
    const S = r.strategies, keys = ["do_nothing", "reroute", "transfer", "hybrid"], rec = r.recommended, inp = r.input;
    const be = (v) => (v.break_even_p == null ? "—" : v.break_even_p > 1 ? "never" : pct(v.break_even_p, 1));
    const steps = cascadeSteps(r);
    $("#forecast").innerHTML = `
      <div class="card ai"><div class="callout ai" style="border:0;background:none;padding:0">${pxImg("robot", { scale: 3 })}<div style="flex:1">
        <div class="eyebrow" style="color:var(--violet)">AI recommendation · ${r.runs} futures × 4 plans · ${esc(r.optimizer)} · ${r.runtime_s}s</div>
        <h3 style="font-size:17px;margin:3px 0">${esc(NAMES[rec])}</h3><p>${esc(r.recommendation_reason)}. ${esc(SCN_LABEL[inp.kind] || inp.kind)} at <span class="mono">${esc(inp.target)}</span>, T+${inp.start_h}h for ${inp.duration_h}h, ${pct(r.probability, 0)} chance.</p></div></div>
        ${rec === "do_nothing" ? `<p class="xs" style="margin:8px 0 0;color:var(--text-2)">The network absorbs this. Trucks heading into it may still need a reroute: <a href="#/recovery" id="toHeal">Self-healing →</a></p>` : ""}
        <div class="row wrap" style="margin-top:10px"><button class="btn good" id="approve">${ico("user")} Approve</button><button class="btn ghost" id="reject">Reject</button>
          <span class="xs muted">Logged to the audit chain.</span></div></div>
      <div class="card"><div class="card-h"><h2>Cascading failure</h2><div class="right"><button class="btn quiet sm" id="replayCascade">${ico("replay")} Replay</button></div></div>
        <div class="chain" id="cascade">${steps.map(([s, b, v, sm, c], i) => `<div class="ch ${c}" data-i="${i}"><div class="ic">${pxImg(s, { scale: 2, c: PX_PALETTE.n })}</div><b>${esc(b)}</b><span>${esc(v)}</span><small>${esc(sm)}</small></div>`).join("")}</div>
        <div class="stats" id="tlMetrics" style="margin-top:8px"></div></div>
      ${weatherHTML(r)}
      <div class="card"><div class="card-h"><h2>Four responses compared</h2></div>
        <div class="tscroll" style="max-height:none"><table class="table"><tr><th>72-hour outlook</th>${keys.map((k) => `<th class="${k === rec ? "rec" : ""}" style="${k === rec ? "color:var(--violet)" : ""}">${NAMES[k]}${k === rec ? " (recommended)" : ""}</th>`).join("")}</tr>
          ${[["Expected cost", (v) => `<b>${lakh(v.expected_cost)}</b>`], ["Action cost (paid anyway)", (v, k) => (k === "do_nothing" ? "—" : lakh(v.action_cost))],
            ["Loss if it happens", (v) => lakh(v.loss_if_disrupted)], ["Expected loss avoided", (v, k) => (k === "do_nothing" ? "—" : lakh(v.expected_loss_avoided))],
            ["Break-even chance", (v, k) => (k === "do_nothing" ? "—" : be(v))], ["Service if it happens", (v) => pct(v.if_disrupted.service_mean)],
            ["Critical cargo (SKU-B) unmet", (v) => Math.round((v.if_disrupted.unmet_by_sku_mean || {})["SKU-B"] || 0).toLocaleString("en-IN")],
            ["Futures ≥95% service", (v) => pct(v.if_disrupted.robustness, 0)], ["Solver", (v) => `<span class="tag">${esc(v.plan_status)}</span>`]]
            .map(([l, fn]) => `<tr><td class="xs">${l}</td>${keys.map((k) => `<td style="${k === rec ? "background:var(--violet-soft)" : ""}">${fn(S[k], k)}</td>`).join("")}</tr>`).join("")}</table></div>
        <p class="note">Priorities: ${Object.entries(r.input.weights || {}).map(([k, v]) => `${k} ${Math.round(v * 100)}%`).join(" · ") || "balanced"}</p></div>
      <div class="card"><div class="card-h"><h2>Monte Carlo</h2></div>${mcHTML(r)}</div>
      <div class="card">${reallocHTML(r)}</div>`;
    $("#approve").onclick = () => decide(r, "approve"); $("#reject").onclick = () => decide(r, "reject");
    const th = $("#toHeal"); if (th) th.onclick = () => sessionStorage.setItem("pnt1.healTab", "1");
    bindRealloc(r);
    TIMELINE.mount(r);
    const seq = () => { $$("#cascade .ch").forEach((c) => c.classList.remove("on"));
      const hours = steps.map(([, , v]) => (/T\+(\d+)/.exec(v) || [])[1]).map((x) => (x == null ? null : +x));
      $$("#cascade .ch").forEach((c, i) => setTimeout(() => { c.classList.add("on"); if (hours[i] != null) TIMELINE.goto(Math.min(71, hours[i])); }, REDUCED ? 0 : 450 + i * 700)); };
    $("#replayCascade").onclick = seq;
    if (animate) seq(); else $$("#cascade .ch").forEach((c) => c.classList.add("on"));
    if (r.input.kind === "storm") $$("#forecast .chain:not(#cascade) .ch").forEach((c, i) => setTimeout(() => c.classList.add("on"), REDUCED ? 0 : 300 + i * 350));
  }
  async function decide(r, action) {
    try { const d = await post("/api/decisions", { scenario_id: r.id, strategy: r.recommended, action });
      toast(`${action === "approve" ? "Approved" : "Rejected"}: ${NAMES[r.recommended]} · audit #${d.audit_seq}`, action === "approve" ? "ok" : "");
      if (action === "approve") { decided = r.id; causalLine(); $("#approve").innerHTML = ico("check") + " Approved"; $("#approve").disabled = true; }
    } catch (e) { toast(e.message, "err"); }
  }

  /* ------------------------------------------------------------ active incidents + resilience engine convergence */
  function activeCard(s) {
    const inc = [...(s.incidents || []), ...(s.scheduled || [])];
    $("#incActive").innerHTML = inc.length ? `<div class="card"><div class="card-h"><h2>Live incidents</h2></div><div class="list">${inc.map((i) => `
        <div class="li"><span class="sev ${i.status === "scheduled" ? "warning" : "critical"}"></span><div style="flex:1"><b>${esc(i.label)}</b><div class="xs muted">${i.status === "scheduled" ? `<b style="color:var(--amber)">starts in ${hrs(i.starts_in_h)}</b> · ${i.duration_h} h` : `${i.links.length} links · ${i.remaining_h.toFixed(1)} h remaining`} · ${esc(i.id)}</div></div>
        <button class="btn ghost sm" data-fly="${esc(i.id)}">Show</button>${i.status === "scheduled" ? "" : `<a class="btn ai sm" href="#/recovery" data-heal="1">Self-heal →</a>`}<button class="btn quiet sm" data-res="${esc(i.id)}">Resolve</button></div>`).join("")}</div></div>` : "";
    $$("#incActive [data-res]").forEach((b) => b.addEventListener("click", async () => { await post(`/api/incidents/${b.dataset.res}/resolve`); toast("Incident resolved", "ok"); }));
    $$("#incActive [data-heal]").forEach((a) => a.addEventListener("click", () => sessionStorage.setItem("pnt1.healTab", "1")));
    $$("#incActive [data-fly]").forEach((b) => b.addEventListener("click", () => { const i = inc.find((x) => x.id === b.dataset.fly);
      TWIN.highlight({ links: i.links, nodes: i.nodes }); }));
  }
  let lastConvKey = "";
  async function convergence() {
    let inf; try { inf = await api("/api/inference"); } catch { return; }
    const ev = inf.active.sort((a, b) => b.t - a.t)[0] || inf.log.find((e) => e.status !== "open");
    const host = $("#convergence");
    if (!ev) { host.innerHTML = `<div class="card"><div class="card-h"><h2>Resilience Engine</h2></div>
      ${empty("radar", "No converging signals")}</div>`; lastConvKey = ""; return; }
    const key = `${ev.id}|${ev.status}|${ev.confidence}`;
    if (key === lastConvKey) return; lastConvKey = key;
    const byFleet = {}; (ev.vehicles || []).forEach((v) => { const f = `FLEET-${v.split("-")[1]}`; byFleet[f] = (byFleet[f] || 0) + 1; });
    const sig = [
      ...Object.entries(byFleet).map(([f, n]) => ["for", `${ico("route")} ${f.replace("FLEET-", "Fleet ")} · ${n} trucks stopped ≥15 min`, "trusted"]),
      [ev.alert ? "for" : "none", `${ico("signal")} Road alert: ${ev.alert ? `“${ev.alert}”` : "none"}`, ev.alert_mode || "—"],
      [ev.independence >= 1 ? "for" : "against", `${ico("branch")} Independent fleets: ${(ev.fleets || []).length} (need ${2})`, pct(ev.independence, 0)],
      [ev.contradiction > 0.2 ? "against" : "for", `${ico("swap")} Traffic moving through the point`, `x ${ev.contradiction.toFixed(2)}`],
      ["for", `${ico("scale")} Trust-weighted quorum`, pct(ev.quorum, 0)],
    ];
    const verdict = ev.coordinated_anomaly ? ["bad", "POSSIBLE COORDINATED SPOOF", "stopped trucks contradicted by moving traffic"]
      : ev.status === "blocked_inferred" ? ["bad", "HIGH-CONFIDENCE DISRUPTION", "independently corroborated"]
        : ev.status === "suspected" ? ["warn", "SUSPECTED · HUMAN CHECK", "no independent corroboration"] : ["ok", "CLEARED", "traffic flowing again"];
    host.innerHTML = `<div class="card"><div class="card-h"><h2>Resilience Engine · <span class="mono">${esc(ev.link_id)}</span></h2><div class="right"></div></div>
      <div class="conv"><div class="sig">${sig.map(([c, t, v], i) => `<div class="${c}" style="animation-delay:${i * 130}ms">${esc(t)}<b>${esc(v)}</b></div>`).join("")}</div>
        <div class="out ${verdict[0]}"><b>${verdict[1]}</b><div class="c">${pct(ev.confidence, 0)}</div><div class="xs muted">${verdict[2]}</div></div>
        <svg id="convSvg"></svg></div>
      <div class="row" style="margin-top:8px"><button class="btn ghost sm" id="convFly">Show on map</button>${ev.needs_human ? '<span class="tag warn">needs human confirmation</span>' : ""}${ev.alert_mode ? dm("mock", "alert feed mock") : ""}</div></div>`;
    $("#convFly").onclick = () => TWIN.highlight({ links: [ev.link_id] });
    requestAnimationFrame(() => { // connectors from each signal to the conclusion
      const svg = $("#convSvg"), box = svg.getBoundingClientRect(), out = $("#convergence .out").getBoundingClientRect();
      const ox = out.left - box.left, oy = out.top - box.top + out.height / 2;
      svg.innerHTML = $$("#convergence .sig div").map((d, i) => { const r = d.getBoundingClientRect(); const x = r.right - box.left, y = r.top - box.top + r.height / 2;
        const c = d.classList.contains("against") ? "var(--red)" : d.classList.contains("for") ? "var(--green)" : "var(--line-2)";
        return `<path d="M${x} ${y} C ${x + 30} ${y}, ${ox - 30} ${oy}, ${ox} ${oy}" fill="none" stroke="${c}" stroke-width="1.5" stroke-dasharray="200" stroke-dashoffset="200" opacity=".8"><animate attributeName="stroke-dashoffset" from="200" to="0" dur=".8s" begin="${0.2 + i * 0.13}s" fill="freeze"/></path>`; }).join("");
    });
  }

  /* ------------------------------------------------------------ attack center */
  const LIB = [
    ["Vehicle telemetry", "truck", [["gps_spoof_teleport", "GPS teleport", "Position jumps into the sea"], ["gps_spoof_drift", "GPS drift", "Position drifts off route slowly"], ["speed_spike", "Impossible speed", "Reports 780–812 km/h"]]],
    ["Facility feeds", "warehouse", [["inventory_fake", "Falsified inventory", "+40% SKU-B that is not there"], ["feed_corrupt", "Corrupted feed", "Garbled types or units ×1000"]]],
    ["Fleet-wide", "package", [["payload_incomplete", "Missing fields", "30% of a fleet's messages lose fields"], ["duplicate_replay", "Replayed messages", "Old messages re-sent"]]],
    ["Source loss", "warning", [["entity_blackout", "Blackout", "One truck or warehouse goes silent"], ["mass_blackout", "Mass blackout", "70% of all sources go silent"]]],
    ["Road events", "container", [["coordinated_stop_spoof", "Coordinated stop", "One fleet fakes a queue on a road"], ["real_blockage", "Real blockage", "The road is really blocked (MOCK alert)"]]],
  ];
  const ATK_NAME = Object.fromEntries(LIB.flatMap(([, , it]) => it.map(([k, n]) => [k, n])));
  async function loadCatalog() {
    CATALOG = await api("/api/attacks/catalog");
    const by = Object.fromEntries(CATALOG.injectors.map((i) => [i.kind, i]));
    const opts = (list, d) => list.map((x) => `<option ${x === d ? "selected" : ""}>${esc(x)}</option>`).join("");
    const target = (t, k) => ({ vehicle: `<select class="sm">${opts(CATALOG.vehicles, "truck-A-020")}</select>`, warehouse: `<select class="sm">${opts(CATALOG.warehouses, k === "feed_corrupt" ? "W-PNQ" : "W-HYD")}</select>`,
      fleet: `<select class="sm">${opts(CATALOG.fleets, k === "duplicate_replay" ? "FLEET-A" : "FLEET-C")}</select>`, link: `<select class="sm">${opts(CATALOG.road_links, "L053")}</select>`,
      vehicle_or_warehouse: `<select class="sm">${opts([...CATALOG.warehouses, ...CATALOG.vehicles], "W-VGA")}</select>` }[t] || `<span class="xs muted">all sources</span>`);
    $("#library").innerHTML = LIB.map(([g, spr, items]) => `<div class="lib-group">${g}</div>` + items.map(([k, n, d]) => { const i = by[k]; if (!i) return "";
      return `<div class="atk" data-kind="${k}" data-target="${i.target}">${pxImg(spr, { scale: 2, c: PX_PALETTE.a })}<div><b>${n}</b><span>${d}</span></div>${target(i.target, k)}<button class="btn ${k === "real_blockage" ? "danger" : "ghost"} sm">Inject</button></div>`; }).join("")).join("");
    $$("#library .atk button").forEach((b) => b.addEventListener("click", () => inject(b)));
  }
  async function inject(b) {
    const row = b.closest(".atk"), k = row.dataset.kind, sel = $("select", row), targets = sel ? [sel.value] : [];
    const params = {};
    if (k === "coordinated_stop_spoof") Object.assign(params, { link: targets[0], fleet: "FLEET-A", n: 8 });
    if (k === "inventory_fake") Object.assign(params, { sku: "SKU-B", pct: 0.4 });
    busy(b, true);
    try {
      const r = await post("/api/attacks", { kind: k, targets: k === "mass_blackout" ? [] : targets, params });
      const first = r.targets[0];
      if (["vehicle", "vehicle_or_warehouse", "warehouse"].includes(row.dataset.target) && first) {
        watchId = CATALOG.warehouses.includes(first) ? `wh:${first}` : first; $("#watching").textContent = watchId.replace("wh:", "");
        watchStart = STATE ? STATE.t : 0; watchKind = k;
        if (!first.startsWith("W-")) TWIN.select("vehicle", first, { fly: true }); else TWIN.select("node", first, { fly: true });
      } else { watchId = null; $("#watching").textContent = ""; watchKind = k; watchStart = STATE ? STATE.t : 0;
        $("#watch").innerHTML = empty("radar", k === "mass_blackout" ? "Watch the data mode (top bar)" : "Watch the Resilience Engine", "");
        if (LINK[targets[0]]) TWIN.highlight({ links: [targets[0]] }); }
      toast(`Injected: ${ATK_NAME[k]}`, "err");
      refreshAttack();
    } catch (e) { toast(e.message, "err"); } finally { busy(b, false); }
  }
  let watchStart = 0, watchKind = null;
  async function refreshAttack() {
    if (PAGE !== "incident" || !$('.tabp[data-t="data"]').classList.contains("on")) return;
    let t = null;
    if (watchId) { try { t = await api(`/api/trust/${encodeURIComponent(watchId)}`); } catch { t = null; } }
    const act = STATE ? STATE.active_attacks : [];
    const running = watchKind && act.some((a) => a.kind === watchKind);
    const detected = t && t.last_anomaly && t.last_anomaly.t >= watchStart;
    const steps = [["bolt", "Attack", watchKind ? ATK_NAME[watchKind] : "choose below", !!watchKind, "bad"], ["radar", "Detection", detected ? `ρ ${t.last_anomaly.rho.toFixed(2)}` : "watching", !!detected, "warn"],
      ["shield", "Trust check", t ? `τ ${t.tau.toFixed(2)}` : "—", t && t.cls !== "trusted", "warn"], ["warning", "Quarantine", t && t.cls === "quarantined" ? "held back" : "—", t && t.cls === "quarantined", "bad"],
      ["check", "Recovery", t && !running && detected && t.cls === "trusted" ? "trusted again" : running ? "attack running" : "—", t && !running && detected && t.cls === "trusted", "ok"]];
    $("#atkChain").innerHTML = steps.map(([s, b, v, on, c]) => `<div class="ch ${on ? `on ${c}` : ""}"><div class="ic">${pxImg(s, { scale: 2, c: PX_PALETTE.a })}</div><b>${b}</b><span>${esc(v)}</span></div>`).join("");
    if (t) {
      const lb = t.last_anomaly;
      $("#watch").innerHTML = `<div class="row"><span class="verdict ${t.cls}">${CLS_ICON[t.cls]} ${CLS_LABEL[t.cls]}</span><span class="mono xs">τ ${t.tau.toFixed(2)} · ${t.anomalies} flagged / ${t.readings}</span></div>
        <div style="margin-top:8px" class="checks">${Object.entries(t.checks || {}).map(([k, v]) => `<span>${esc(k)}</span>${meter(v, stateOf(v))}<b>${v.toFixed(2)}</b>`).join("")}</div>
        ${lb ? `<div class="qpath" style="margin-top:10px"><div><b>Incoming</b><span class="raw">${Object.entries(lb.raw || {}).slice(0, 3).map(([k, v]) => `${esc(k)}: ${esc(typeof v === "object" ? "…" : v)}`).join("<br>")}</span></div>
          <div><b>Anomaly</b>ρ ${lb.rho.toFixed(2)}<br><span class="xs muted">${esc((lb.reasons || [])[0] || "")}</span></div><div><b>${esc(cap(lb.action))}</b>not applied to the twin</div><div><b>Last trusted</b>twin keeps the previous state</div></div>` : ""}`;
    } else if (!watchKind) $("#watch").innerHTML = empty("shield", "Nothing watched");
    const q = await api("/api/quarantine");
    $("#quarantine").innerHTML = q.length ? `<div class="tscroll"><table class="table"><tr><th>Time</th><th>Entity</th><th>Why it was held back</th><th class="num">ρ</th><th>Review</th></tr>${q.slice(0, 40).map((x) =>
      `<tr><td class="mono">${clock(x.t)}</td><td class="mono">${esc(x.entity.replace("wh:", ""))}</td><td class="xs">${esc((x.reasons || []).slice(0, 2).join("; "))}</td><td class="num">${x.rho.toFixed(2)}</td>
       <td>${x.review === "open" ? `<button class="btn quiet sm rv" data-id="${x.id}" data-v="confirmed_attack">Confirm</button><button class="btn quiet sm rv" data-id="${x.id}" data-v="false_positive">False +</button>` : `<span class="tag ${x.review === "confirmed_attack" ? "bad" : ""}">${esc(cap(x.review))}</span>`}</td></tr>`).join("")}</table></div>`
      : empty("shield", "Nothing quarantined");
    $$("#quarantine .rv").forEach((b) => b.addEventListener("click", async () => { await post(`/api/quarantine/${b.dataset.id}/review`, { verdict: b.dataset.v }); toast("Review recorded", "ok"); refreshAttack(); }));
    $("#activeAttacks").textContent = act.length ? "Active: " + act.map((a) => `${ATK_NAME[a.kind] || a.kind} (${a.targets.slice(0, 2).join(", ")}${a.targets.length > 2 ? "…" : ""}, ${Math.max(0, Math.round(a.ends_in_s / 60))} sim-min left)`).join("; ") : "No injections running.";
  }
  async function rawVsTrusted(e) {
    busy(e.target, true); $("#rvt").innerHTML = loading("Planning twice and running 400 futures");
    try {
      const r = await post("/api/compare/raw-vs-trusted", {});
      const diffs = r.inventory_differences;
      $("#rvt").innerHTML = `${diffs.length ? `<p class="xs">${diffs.slice(0, 5).map((x) => `<span class="mono">${esc(x.node)} ${esc(x.sku)}</span>: feed claims <b>${x.claimed.toLocaleString("en-IN")}</b>, trusted <b>${x.trusted.toLocaleString("en-IN")}</b>`).join("<br>")}</p>`
        : `<p class="xs muted">Feeds and trusted inventory agree.</p>`}
        <table class="table"><tr><th></th><th>Plan from raw feeds</th><th>Plan from trusted data</th></tr>
        <tr><td>Expected cost, 72 h</td><td>${lakh(r.from_raw.cost_mean)}</td><td>${lakh(r.from_trusted.cost_mean)}</td></tr>
        <tr><td>Service level</td><td>${pct(r.from_raw.service_mean)}</td><td>${pct(r.from_trusted.service_mean)}</td></tr>
        <tr><td>Unmet units</td><td>${Math.round(r.from_raw.unmet_units_mean).toLocaleString("en-IN")}</td><td>${Math.round(r.from_trusted.unmet_units_mean).toLocaleString("en-IN")}</td></tr></table>
        <div class="callout ${r.extra_cost_if_raw_trusted > 0 ? "warn" : ""}" style="margin-top:10px">${pxImg("shield", { scale: 2 })}<div><h3>${r.extra_cost_if_raw_trusted > 0 ? `Trusting the raw feeds would cost ${lakh(r.extra_cost_if_raw_trusted)} more` : "No cost difference from the raw feeds right now"}</h3></div></div>`;
    } catch (err) { $("#rvt").innerHTML = `<p class="error">${esc(err.message)}</p>`; } finally { busy(e.target, false); }
  }

  /* ------------------------------------------------------------ lifecycle */
  let decided = null;
  function causalLine() {
    const s = STATE, r = SCN, inc = s && s.incidents ? s.incidents : [], o = s && s.ops, res = s && s.resilience;
    const wx = res && res.components.weather_exposure;
    const dn = r ? r.frames.do_nothing.frames : null, below = dn ? dn.findIndex((f) => Object.values(f.wh).some((v) => v.ratio < 1)) : -1;
    causal("#incLine", [
      ["1 · Incident", inc.length ? (inc[0].label || inc[0].kind) : r ? (SCN_LABEL[r.input.kind] || r.input.kind) : "none declared", inc.length ? `${inc.length} active · simulated` : r ? "forecast only" : "choose one below", inc.length ? "bad" : r ? "warn" : null],
      ["2 · Network impact", o && o.active_disruptions ? `${o.active_disruptions} disruption${o.active_disruptions > 1 ? "s" : ""}` : r ? `${r.blocked_links.length} links blocked` : "normal", o ? `${o.network_capacity_pct}% link capacity open` : "", (o && o.active_disruptions) || r ? "warn" : "ok"],
      ["3 · Weather and resilience", res ? `index ${res.index.toFixed(0)}` : "—", wx ? `weather exposure ${(wx.score * 100).toFixed(0)}/100` : "weather not included", res ? (res.index >= 85 ? "ok" : res.index >= 65 ? "warn" : "bad") : null],
      ["4 · Cascade", r ? (below >= 0 ? `T+${below} h` : "holds") : "after forecast", r ? (below >= 0 ? "first hub below safety stock" : "safety stock covers it") : "", r ? (below >= 0 ? "warn" : "ok") : null],
      ["5 · Forecast", r ? `${r.runs} futures` : "not run", r ? `service ${pct(r.strategies.do_nothing.if_disrupted.service_mean, 0)} if unanswered` : "", r ? "ai" : null],
      ["6 · Recovery", r ? (decided === r.id ? "approved" : NAMES[r.recommended]) : "—", r ? (decided === r.id ? "written to the audit trail" : "awaiting approval") : "", r ? (decided === r.id ? "ok" : "ai") : null],
    ]);
  }
  on("state", () => { if (PAGE === "incident") causalLine(); });
  function init() {
    tiles(); targets(); causalLine();
    $("#incTarget").addEventListener("change", previewTarget);
    $("#incStart").addEventListener("input", hint);
    prio = prioSliders($("#incPrio"), { money: 30, time: 30, fuel: 15, distance: 10, carbon: 15 }, () => {}, { compact: true });
    $("#incLive").addEventListener("click", (e) => runForecast(e.currentTarget, true));
    $("#incForecast").addEventListener("click", (e) => runForecast(e.currentTarget, false));
    $("#stopAll").addEventListener("click", async () => { await post("/api/attacks/stop"); toast("Stopped", "ok"); watchKind = null; });
    $$("#incTabs button").forEach((b) => b.addEventListener("click", () => { $$("#incTabs button").forEach((x) => x.classList.toggle("on", x === b));
      $$('#panel [data-page="incident"] .tabp').forEach((p) => p.classList.toggle("on", p.dataset.t === b.dataset.t));
      if (b.dataset.t === "data") { TIMELINE.unmount(); refreshAttack(); } else if (SCN && !TIMELINE.active) TIMELINE.mount(SCN); }));
    $("#rawVsTrusted").addEventListener("click", rawVsTrusted);
    loadCatalog();
    setInterval(() => { if (PAGE === "incident") { refreshAttack(); convergence(); } }, 2000);
    on("state", ({ s }) => { if (PAGE === "incident") activeCard(s); });
    on("select", ({ kind: k, id }) => { // click a facility on the map to make it the incident target
      if (PAGE !== "incident" || k !== "node") return;
      const want = { Warehouse: "warehouse_failure", Port: "port_closure", Supplier: "supplier_failure", CustomerCluster: "demand_spike" }[NODE[id].type];
      if (!want) return;
      kind = want; tiles(); targets(id); defaults(); toast(`Target set to ${id}`);
    });
  }
  return {
    init,
    enter() {
      causalLine();
      const t = sessionStorage.getItem("pnt1.incTarget");
      if (t && NODE[t]) { sessionStorage.removeItem("pnt1.incTarget"); kind = { Warehouse: "warehouse_failure", Port: "port_closure", Supplier: "supplier_failure" }[NODE[t].type] || kind; tiles(); targets(t); defaults(); }
      else previewTarget();
      if (STATE) activeCard(STATE);
      convergence();
      if (SCN && !$("#forecast").innerHTML) renderForecast(SCN, false);
      else if (SCN && !TIMELINE.active) TIMELINE.mount(SCN);
      TWIN.ready.then(() => TWIN.clearRoutes());
    },
    leave() { TIMELINE.unmount(); TWIN.clearHighlight(); },
  };
})();

/* ---------------------------------------------------------------- inventory reallocation (shared with AI Recovery) */
function reallocHTML(r) {
  const tr = (r && r.plan_diff && r.plan_diff.transfers) || [];
  if (!r) return `<div class="card-h"><h2>Inventory reallocation</h2></div>${empty("warehouse", "No scenario yet")}`;
  if (!tr.length) return `<div class="card-h"><h2>Inventory reallocation</h2><span class="sub">${esc(NAMES[r.recommended])}</span></div>${empty("warehouse", "No hub transfers", r.plan_diff.rerouted_links.length ? `Rerouted: ${r.plan_diff.rerouted_links.slice(0, 4).map((x) => x.link).join(", ")}` : "")}`;
  return `<div class="card-h"><h2>Inventory reallocation</h2><div class="right"><button class="btn ai sm" id="reallocShow">Animate on map</button></div></div>
    <div class="list">${tr.slice(0, 5).map((t, i) => `<div class="li"><span style="width:10px;height:10px;border-radius:3px;background:${ROUTE_COLORS[i]}"></span>
      <div style="flex:1"><b class="mono">${esc(t.from)}</b> <span class="muted">excess</span> → <b class="mono">${esc(t.to)}</b> <span class="muted">shortage risk</span>
      <div class="xs muted">${Math.round(t.units).toLocaleString("en-IN")} units (${Object.entries(t.by_sku).map(([s, q]) => `${s} ${Math.round(q)}`).join(", ")}) · ${esc(t.mode)} · ETA ${hrs(t.eta_h)} · starts T+${t.start_h}h</div></div>
      <b class="mono xs">${inr(t.cost_inr)}</b></div>`).join("")}</div>`;
}
function bindRealloc(r) {
  const b = $("#reallocShow"); if (!b) return;
  b.onclick = () => {
    const routes = r.plan_diff.transfers.slice(0, 5).map((t, i) => ({ id: `t${i}`, coords: LINK[t.link].coords }));
    TWIN.showRoutes(routes, null, { animate: true });
    toast("Stock transfers drawn on the map", "ai");
  };
}
