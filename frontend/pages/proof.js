/* RESILIENCE & PROOF: Supply Chain Doctor (fragility + resilience findings that light up the map), technical proof
 * against hidden ground truth, Monte Carlo evidence, anomaly model card, the digital-twin time machine and the
 * hash-chained audit trail with decision replay. */
"use strict";
PAGES.proof = (() => {
  let FR = null, RES = null, AUDIT = [], tmTimer = null;
  const AUDIT_LABEL = { system: "System", quarantine: "Quarantine", mode_change: "Mode change", inference: "Inference", attack_injected: "Injection", recommendation: "Recommendation",
    decision: "Decision", quarantine_review: "Review", incident: "Incident", reroute_approved: "Reroute", support_ticket: "Support" };
  const AUDIT_TAG = { quarantine: "bad", decision: "ok", recommendation: "ai", attack_injected: "warn", mode_change: "", inference: "warn", incident: "bad", reroute_approved: "ok", support_ticket: "sim" };

  /* ------------------------------------------------------------ doctor */
  function linksBetween(u, v) { return NET.links.filter((l) => l.from === u && l.to === v).map((l) => l.id); }
  async function doctor() {
    if (!FR) $("#findings").innerHTML = loading("Examining the network graph…");
    [FR, RES] = await Promise.all([api("/api/graph/fragility"), api("/api/resilience")]);
    const C = RES.current.components, F = [];
    Object.entries(C.supplier_dependency.facts.per_sku).forEach(([sku, v]) => { if (v.effective < 1.5)
      F.push({ sev: "bad", icon: "supplier", title: `Single-source supplier · ${sku}`, text: `${sku} depends on ${v.sources.join(", ") || "no available source"} (effective sources ${v.effective}).`, nodes: v.sources, links: NET.links.filter((l) => v.sources.includes(l.from)).map((l) => l.id) }); });
    const single = C.route_redundancy.facts.single_hub_customers;
    if (single.length) F.push({ sev: single.length > 6 ? "bad" : "warn", icon: "pin", title: "Low route redundancy", text: `${single.length} of 15 customer clusters are served by one open hub: ${single.slice(0, 6).join(", ")}${single.length > 6 ? "…" : ""}.`,
      nodes: single, links: NET.links.filter((l) => single.includes(l.to)).map((l) => l.id) });
    FR.critical_nodes.filter((c) => c.single_point_for.length).slice(0, 3).forEach((c) => F.push({ sev: "bad", icon: "warehouse", title: `Critical dependency · ${c.node}`, text: `Only path to ${c.single_point_for.join(", ")}. ${c.articulation_point ? "Articulation point. " : ""}Betweenness ${c.betweenness.toFixed(2)}.`,
      nodes: [c.node, ...c.single_point_for], links: NET.links.filter((l) => l.from === c.node && c.single_point_for.includes(l.to)).map((l) => l.id), dep: c.node }));
    const mc = FR.weakest_min_cuts[0];
    if (mc) { const lk = mc.cut_edges.flatMap((e) => linksBetween(...e.split("->")));
      F.push({ sev: "warn", icon: "truck", title: `High-risk corridor into ${mc.customer}`, text: `Everything reaching ${mc.customer} crosses ${mc.cut_edges.join(", ")}: ${mc.min_cut_capacity_per_day.toLocaleString("en-IN")} units/day of capacity.`, nodes: [mc.customer], links: lk }); }
    const low = C.inventory_buffer.facts.below_safety;
    if (low.length) { const hubs = [...new Set(low.map((x) => x.split(" ")[0]))];
      F.push({ sev: low.length > 6 ? "bad" : "warn", icon: "container", title: "Low inventory buffer", text: `${low.length} hub-SKUs below ${2} days of safety stock: ${low.slice(0, 5).join(", ")}${low.length > 5 ? "…" : ""}.`, nodes: hubs, links: [] }); }
    const top = [...FR.critical_nodes].sort((a, b) => b.betweenness - a.betweenness)[0];
    if (top) F.push({ sev: "warn", icon: "radar", title: `Traffic concentration · ${top.node}`, text: `Highest betweenness (${top.betweenness.toFixed(2)}): the most flow paths pass through ${top.name}.`, nodes: [top.node], links: NET.links.filter((l) => l.from === top.node || l.to === top.node).map((l) => l.id), dep: top.node });
    $("#findings").innerHTML = F.map((f, i) => `<div class="find sev-${f.sev}" data-i="${i}" style="animation-delay:${i * 80}ms">${pxImg(f.icon, { scale: 2, c: PX_PALETTE.n })}<div><b>${esc(f.title)}</b><span>${esc(f.text)}</span></div><span class="sv">${f.sev === "bad" ? "!!" : "!"}</span></div>`).join("");
    $$("#findings .find").forEach((el) => el.addEventListener("click", () => { $$("#findings .find").forEach((x) => x.classList.toggle("on", x === el)); const f = F[+el.dataset.i];
      TWIN.highlight({ nodes: f.nodes, links: f.links }); if (f.dep) showDeps(f.dep); }));
    critical();
    if (!$("#dep").innerHTML) showDeps(FR.critical_nodes[0].node);
  }
  function critical() {
    $("#critical").innerHTML = `<div class="tscroll"><table class="table"><tr><th>#</th><th>Facility</th><th>Why it matters</th><th>Betweenness</th></tr>${FR.critical_nodes.map((c, i) =>
      `<tr class="click" data-n="${c.node}"><td class="num muted">${i + 1}</td><td><b class="mono">${esc(c.node)}</b><div class="xs muted">${esc(c.name)}</div></td>
      <td class="xs">${c.single_point_for.length ? `Only route to ${c.single_point_for.map((x) => `<span class="tag bad">${esc(x)}</span>`).join(" ")}` : ""}${c.articulation_point ? `<div class="muted">Articulation point</div>` : ""}</td>
      <td style="min-width:110px">${meter(c.betweenness / 0.2, "ai")}<span class="xs mono">${c.betweenness.toFixed(3)}</span></td></tr>`).join("")}</table></div>`;
    $$("#critical tr.click").forEach((tr) => tr.addEventListener("click", () => { showDeps(tr.dataset.n); TWIN.highlight({ nodes: [tr.dataset.n] }); }));
  }
  async function showDeps(id) {
    const b = await api(`/api/graph/blast/${id}`), n = NODE[id];
    $("#depTitle").textContent = `${id} · ${n.name}`;
    const up = [...new Set(NET.links.filter((l) => l.to === id).map((l) => l.from))], down = b.direct, cut = new Set(b.customers_cut_off_if_failed);
    const W = 520, rowH = 24, H = Math.max(up.length, down.length, 3) * rowH + 40, cx = W / 2, cy = H / 2;
    const yU = (i) => 20 + i * rowH + (H - 40 - up.length * rowH) / 2 + rowH / 2, yD = (i) => 20 + i * rowH + (H - 40 - down.length * rowH) / 2 + rowH / 2;
    $("#dep").innerHTML = `<svg class="dep" viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Dependencies of ${esc(id)}">
      ${up.map((u, i) => `<path d="M140 ${yU(i)} C ${cx - 60} ${yU(i)}, ${cx - 60} ${cy}, ${cx - 30} ${cy}" style="stroke-dasharray:400;stroke-dashoffset:400;animation:draw .9s ${i * 50}ms var(--ease-out) forwards"/>`).join("")}
      ${down.map((d, i) => `<path class="${cut.has(d) ? "cut" : ""}" d="M${cx + 30} ${cy} C ${cx + 60} ${cy}, ${cx + 60} ${yD(i)}, ${W - 140} ${yD(i)}" style="stroke-dasharray:400;stroke-dashoffset:400;animation:draw .9s ${300 + i * 50}ms var(--ease-out) forwards"/>`).join("")}
      ${up.map((u, i) => `<text x="134" y="${yU(i) + 4}" text-anchor="end">${esc(u)}</text>`).join("")}
      ${down.map((d, i) => `<text x="${W - 134}" y="${yD(i) + 4}" ${cut.has(d) ? 'style="fill:var(--red);font-weight:600"' : ""}>${esc(d)}</text>`).join("")}
      <image href="${px(TYPE_SPRITE[n.type], { scale: 3, c: PX_PALETTE.n })}" x="${cx - 24}" y="${cy - 18}" width="48" height="${PX_SPRITES[TYPE_SPRITE[n.type]].length * 3}" style="image-rendering:pixelated"/>
      <text x="${cx}" y="${cy + 32}" text-anchor="middle" style="fill:var(--text)">${esc(id)}</text><text x="10" y="14">Supplied by</text><text x="${W - 10}" y="14" text-anchor="end">Ships to</text></svg>`
      + (cut.size ? `<div class="callout bad">${pxImg("warning", { scale: 2 })}<div><h3>If ${esc(id)} fails, ${[...cut].join(" and ")} lose${cut.size === 1 ? "s" : ""} all supply</h3><p>${b.indirect.length} further facilities are downstream. <a href="#/incident" id="depSim">Simulate it →</a></p></div></div>`
        : `<p class="xs muted">Every customer served by ${esc(id)} can still be reached another way. ${b.indirect.length} facilities are downstream.</p>`);
    const a = $("#depSim"); if (a) a.addEventListener("click", () => sessionStorage.setItem("pnt1.incTarget", id));
  }

  /* ------------------------------------------------------------ technical proof */
  async function tech() {
    const [d, f] = await Promise.all([api("/api/eval/detection"), api("/api/eval/fidelity")]);
    const att = Object.values(d.per_injector).reduce((a, v) => a + v.attacked_readings, 0), det = Object.values(d.per_injector).reduce((a, v) => a + v.detected, 0);
    const clean = d.clean_readings, fp = d.false_positive_rate != null ? d.false_positive_rate * clean : 0;
    const acc = att + clean ? (det + clean - fp) / (att + clean) : null;
    const stat = (v, l, tip) => `<div class="stat" ${tip ? `data-tip="${esc(tip)}"` : ""}><div class="v">${v}</div><div class="l">${l}</div></div>`;
    $("#evalStats").innerHTML = stat(f.position.mean_km != null ? `${(f.position.mean_km * 1000).toFixed(0)} m` : "—", "Position fidelity · mean error", `P90 ${f.position.p90_km != null ? (f.position.p90_km * 1000).toFixed(0) : "—"} m over ${f.position.n} trucks`)
      + stat(f.position.p90_km != null ? `${(f.position.p90_km * 1000).toFixed(0)} m` : "—", "Position error · P90")
      + stat(f.inventory.mape_pct != null ? `${f.inventory.mape_pct}%` : "—", "Inventory fidelity · MAPE", `${f.inventory.n} hub-SKUs`)
      + stat(att ? pct(det / att, 1) : "—", "Attack detection · reading recall", `${det.toLocaleString()} of ${att.toLocaleString()} attacked readings flagged`)
      + stat(d.false_positive_rate != null ? pct(d.false_positive_rate, 2) : "—", "False-positive rate", "clean readings wrongly quarantined")
      + stat(acc != null ? pct(acc, 2) : "—", "Trust accuracy · reading level", "(flagged attacked + passed clean) / all scored readings")
      + stat(d.attacks_injected, "Evaluation runs · injections") + stat(clean.toLocaleString("en-IN"), "Clean readings scored");
    const names = { gps_spoof_teleport: "GPS teleport", gps_spoof_drift: "GPS drift", speed_spike: "Impossible speed", inventory_fake: "Fake inventory", feed_corrupt: "Corrupted feed", payload_incomplete: "Missing fields", duplicate_replay: "Replayed messages" };
    const rows = Object.entries(d.per_injector);
    $("#detection").innerHTML = rows.length ? `<table class="table"><tr><th>Injector</th><th class="num">Attacked</th><th class="num">Flagged</th><th style="width:40%">Recall</th></tr>${rows.map(([k, v]) =>
      `<tr><td>${esc(names[k] || k)}</td><td class="num">${v.attacked_readings.toLocaleString()}</td><td class="num">${v.detected.toLocaleString()}</td><td>${meter(v.reading_recall || 0, stateOf(v.reading_recall || 0))}<span class="xs mono">${pct(v.reading_recall)}</span></td></tr>`).join("")}</table>`
      : empty("shield", "No attacks injected yet", "", '<a class="btn ghost sm" href="#/incident" style="margin-top:6px">Attack Center</a>');
    $("#evalNote").innerHTML = `${esc(d.note)} ${esc(f.note)}`;
    mcProof(); modelCard();
  }
  function mcProof() {
    if (!SCN) { $("#mcProof").innerHTML = empty("robot", "No scenario run yet"); return; }
    const r = SCN, S = r.strategies, rec = r.recommended;
    $("#mcProof").innerHTML = `<div class="stats">${[["Futures per plan", r.runs], ["Plans compared", 4], ["Expected cost (rec.)", lakh(S[rec].expected_cost)], ["Service if disrupted", pct(S[rec].if_disrupted.service_mean)],
      ["Unmet units (mean)", Math.round(S[rec].if_disrupted.unmet_units_mean).toLocaleString("en-IN")], ["Cost std-dev", lakh(S[rec].if_disrupted.cost_std)]].map(([l, v]) => `<div class="stat"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("")}</div>
      <p class="note">${esc(SCN_LABEL[r.input.kind] || r.input.kind)} at ${esc(r.input.target)} · recommended ${esc(NAMES[rec])}.</p>`;
  }
  async function modelCard() {
    let m = null; try { m = (await api("/api/models")).anomaly; } catch { /* none */ }
    if (!m) { $("#modelCard").innerHTML = empty("gear", "No trained model loaded", "Train with <span class=\"mono\">uv run python -m pnt1.ml_train</span>."); return; }
    const ev = m.evaluation;
    $("#modelCard").innerHTML = `<p class="xs">${esc(m.model)} · ${m.features.length} features · trained on ${m.train.readings.toLocaleString()} clean readings · evaluated on unseen seeds ${ev.seeds.join(", ")}.</p>
      <div class="stats"><div class="stat"><div class="v">${ev.roc_auc.toFixed(3)}</div><div class="l">ROC AUC</div></div><div class="stat"><div class="v">${ev.average_precision.toFixed(3)}</div><div class="l">Average precision</div></div>
      <div class="stat"><div class="v">${pct(ev.combined_fpr_clean, 2)}</div><div class="l">Rules + model FPR</div></div></div>`;
  }

  /* ------------------------------------------------------------ time machine */
  const PHASES = [["Normal", "ok"], ["Disruption", "bad"], ["Cascade", "bad"], ["Inventory risk", "warn"], ["Recovery prepared", "ai"], ["Recovery approved", "ai"], ["Network stabilizing", "ok"]];
  function phaseTimes() {
    const ev = [...AUDIT].sort((a, b) => a.seq - b.seq);
    const first = (fn) => { const e = ev.find(fn); return e ? e.sim_t : null; };
    const dis = first((e) => e.entry_type === "incident" && e.body.kind || (e.entry_type === "attack_injected") || (e.entry_type === "inference" && e.body.status !== "open"));
    const casc = first((e) => e.sim_t >= (dis ?? Infinity) && (e.entry_type === "inference" && e.body.status === "blocked_inferred" || e.entry_type === "mode_change" && e.body.to !== "NORMAL" || e.entry_type === "quarantine"));
    const inv = (() => { if (dis == null) return null; const h = RES.history.find((x) => x.t >= dis && x.points && x.points.inventory_buffer < (RES.history[0].points || {}).inventory_buffer - 0.3); return h ? h.t : null; })();
    const prep = first((e) => e.sim_t >= (dis ?? Infinity) && e.entry_type === "recommendation");
    const appr = first((e) => e.sim_t >= (dis ?? Infinity) && (e.entry_type === "decision" && e.body.action === "approve" || e.entry_type === "reroute_approved"));
    const stab = first((e) => e.sim_t >= (appr ?? Infinity) && (e.entry_type === "inference" && e.body.status === "open" || e.entry_type === "incident" && ["resolved", "expired"].includes(e.body.event) || e.entry_type === "mode_change" && e.body.to === "NORMAL"));
    const t0 = RES.history.length ? RES.history[0].t : 0;
    return [t0, dis, casc, inv, prep, appr, stab];
  }
  async function timeMachine() {
    [RES, AUDIT] = await Promise.all([api("/api/resilience"), api("/api/audit?limit=400")]);
    const start = Math.max(0, ...AUDIT.filter((a) => a.entry_type === "system" && a.body && a.body.event === "start").map((a) => a.seq));
    AUDIT = AUDIT.filter((a) => a.seq >= start);          // this run only (the log is shared across restarts)
    const H = RES.history; if (H.length < 2) { $("#tmChart").innerHTML = empty("clock", "Not enough history yet"); return; }
    const t0 = H[0].t, t1 = H[H.length - 1].t, W = 600, HH = 150, lo = Math.min(...H.map((h) => h.index)) - 3, hi = Math.max(...H.map((h) => h.index)) + 3;
    const X = (t) => ((t - t0) / Math.max(1, t1 - t0)) * W, Y = (v) => HH - 18 - ((v - lo) / Math.max(1, hi - lo)) * (HH - 30);
    const pts = H.map((h) => `${X(h.t).toFixed(1)},${Y(h.index).toFixed(1)}`).join(" ");
    const marks = AUDIT.filter((a) => a.sim_t != null && a.sim_t >= t0 && ["incident", "attack_injected", "recommendation", "decision", "reroute_approved", "mode_change"].includes(a.entry_type));
    const phases = phaseTimes();
    $("#tmChart").innerHTML = `<svg class="chart" viewBox="0 0 ${W} ${HH}" preserveAspectRatio="none" style="height:170px">
      <defs><linearGradient id="tmg" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="var(--primary)" stop-opacity=".3"/><stop offset="1" stop-color="var(--primary)" stop-opacity="0"/></linearGradient></defs>
      ${[lo + 3, (lo + hi) / 2, hi - 3].map((v) => `<line class="axis" x1="0" x2="${W}" y1="${Y(v)}" y2="${Y(v)}" stroke-dasharray="3 4"/><text x="4" y="${Y(v) - 3}">${v.toFixed(0)}</text>`).join("")}
      <polygon points="0,${HH - 18} ${pts} ${W},${HH - 18}" fill="url(#tmg)"/><polyline points="${pts}" fill="none" stroke="var(--primary-2)" stroke-width="2" vector-effect="non-scaling-stroke"/>
      ${marks.map((m) => `<g><line x1="${X(m.sim_t)}" x2="${X(m.sim_t)}" y1="6" y2="${HH - 18}" stroke="var(--${AUDIT_TAG[m.entry_type] === "bad" ? "red" : AUDIT_TAG[m.entry_type] === "ok" ? "green" : AUDIT_TAG[m.entry_type] === "ai" ? "violet" : "amber"})" stroke-opacity=".5"/><title>${esc(AUDIT_LABEL[m.entry_type] || m.entry_type)} · ${dayclock(m.sim_t)}</title></g>`).join("")}
      <line id="tmCursor" x1="0" x2="0" y1="0" y2="${HH - 18}" stroke="var(--text)" stroke-width="1.5"/><circle id="tmDot" r="4" fill="var(--violet)"/>
      <text x="0" y="${HH - 4}">${dayclock(t0)}</text><text x="${W}" y="${HH - 4}" text-anchor="end">${dayclock(t1)}</text></svg>
      <div class="row" style="margin-top:6px"><button class="btn sm" id="tmPlay">${ico("play")} Replay</button><input type="range" id="tmR" min="0" max="${H.length - 1}" value="${H.length - 1}" style="flex:1" aria-label="Time machine"></div>`;
    const set = (i) => { const h = H[i]; $("#tmCursor").setAttribute("x1", X(h.t)); $("#tmCursor").setAttribute("x2", X(h.t)); $("#tmDot").setAttribute("cx", X(h.t)); $("#tmDot").setAttribute("cy", Y(h.index));
      let ph = 0; phases.forEach((t, k) => { if (t != null && t <= h.t) ph = k; });
      $("#tmState").innerHTML = `<div class="grid2" style="margin-top:10px;grid-template-columns:150px 1fr"><div class="stat"><div class="v">${h.index.toFixed(1)}</div><div class="l">Resilience Index at ${dayclock(h.t)}</div></div>
        <div class="flow">${PHASES.map(([n, c], k) => `<div class="fs ${k < ph ? "done" : k === ph ? `now ${c}` : ""}"><span class="dot">${k < ph ? ico("check", 12) : k + 1}</span><div><b>${n}</b></div><span class="t">${phases[k] != null ? clock(phases[k]) : "—"}</span></div>`).join("")}</div></div>`;
      setRangeFill($("#tmR")); };
    $("#tmR").addEventListener("input", (e) => { clearInterval(tmTimer); tmTimer = null; $("#tmPlay").innerHTML = ico("play") + " Replay"; set(+e.target.value); });
    $("#tmPlay").addEventListener("click", () => { if (tmTimer) { clearInterval(tmTimer); tmTimer = null; $("#tmPlay").innerHTML = ico("play") + " Replay"; return; }
      let i = 0; $("#tmPlay").innerHTML = ico("pause") + " Pause"; const step = Math.max(1, Math.round(H.length / 90));
      tmTimer = setInterval(() => { i = Math.min(H.length - 1, i + step); $("#tmR").value = i; set(i); if (i >= H.length - 1) { clearInterval(tmTimer); tmTimer = null; $("#tmPlay").innerHTML = ico("play") + " Replay"; } }, REDUCED ? 200 : 60); });
    set(H.length - 1);
    audit();
  }
  function auditSummary(r) {
    const b = r.body;
    switch (r.entry_type) {
      case "quarantine": return `<span class="mono">${esc(b.entity)}</span> held back, ρ ${b.rho}: ${esc((b.reasons || [])[0] || "")}`;
      case "mode_change": return `Network mode ${esc(b.from)} → ${esc(b.to)} (${esc(b.reason)})`;
      case "inference": return `Road <span class="mono">${esc(b.link_id)}</span> ${esc((b.status || "").replace("_", " "))}, confidence ${b.confidence}`;
      case "attack_injected": return `Simulated injection <b>${esc(b.kind)}</b> on ${esc((b.targets || []).slice(0, 4).join(", ") || "network")}`;
      case "recommendation": return `${esc(cap(b.input.kind))} at <span class="mono">${esc(b.input.target)}</span>: recommended <b>${esc(NAMES[b.recommended] || b.recommended)}</b>, expected ${lakh(b.expected_cost)}`;
      case "decision": return `<b>${esc(b.action)}</b> ${esc(NAMES[b.strategy] || b.strategy)} for ${esc(b.scenario_id)} by ${esc(b.approver)}`;
      case "incident": return b.label ? `Incident declared: <b>${esc(b.label)}</b> (${b.duration_h} h)` : `Incident ${esc(b.id)} ${esc(b.event || "")}`;
      case "reroute_approved": return `Reroute approved for <span class="mono">${esc(b.vehicle)}</span>: ${esc((b.new_route || []).join(" → "))}${b.turnaround ? " (turn back)" : ""}`;
      case "support_ticket": return `Ticket ${esc(b.id)} (${esc(b.category)}) for order ${esc(b.order_id)}`;
      case "quarantine_review": return `Quarantine #${b.quarantine_id} reviewed as ${esc(cap(b.verdict))}`;
      default: return esc(JSON.stringify(b).slice(0, 140));
    }
  }
  function audit() {
    const types = [...new Set(AUDIT.map((r) => r.entry_type))], sel = $("#auditType"), cur = sel.value;
    sel.innerHTML = `<option value="">All types</option>` + types.map((t) => `<option value="${t}" ${t === cur ? "selected" : ""}>${AUDIT_LABEL[t] || t}</option>`).join("");
    const t = sel.value, q = $("#auditSearch").value.trim().toLowerCase();
    const rows = AUDIT.filter((r) => (!t || r.entry_type === t) && (!q || JSON.stringify(r.body).toLowerCase().includes(q)));
    $("#audit").innerHTML = rows.length ? `<table class="table"><tr><th class="num">#</th><th>Sim</th><th>Type</th><th>Record</th><th>Hash</th></tr>${rows.slice(0, 200).map((r) => `
      <tr><td class="num mono">${r.seq}</td><td class="mono xs">${r.sim_t != null ? clock(r.sim_t) : "—"}</td><td><span class="tag ${AUDIT_TAG[r.entry_type] || ""}">${AUDIT_LABEL[r.entry_type] || esc(r.entry_type)}</span></td>
      <td class="xs">${auditSummary(r)}<div class="xs muted">${esc(r.actor)}</div>${r.entry_type === "recommendation" ? `<button class="btn quiet sm rp" data-s="${r.seq}">${ico("replay")} Replay decision</button> <span class="xs" id="rp${r.seq}"></span>` : ""}</td>
      <td class="mono xxs muted">${esc(String(r.hash).slice(0, 12))}…</td></tr>`).join("")}</table>` : empty("package", "No matching records", "Records appear as the system runs.");
    $$("#audit button.rp").forEach((b) => b.addEventListener("click", async () => { busy(b, true); const o = $(`#rp${b.dataset.s}`);
      try { const x = await post(`/api/audit/${b.dataset.s}/replay`); o.innerHTML = x.identical ? `<span class="tag ok">identical</span> ${esc(NAMES[x.replayed])}` : `<span class="tag warn">differs</span> ${esc(x.original)} → ${esc(x.replayed)}`; }
      catch (e) { o.innerHTML = `<span class="error">${esc(e.message)}</span>`; } finally { busy(b, false); } }));
  }

  function tab(t) {
    $$("#proofTabs button").forEach((x) => x.classList.toggle("on", x.dataset.t === t));
    $$('#panel [data-page="proof"] .tabp').forEach((p) => p.classList.toggle("on", p.dataset.t === t));
    if (t === "doctor") doctor(); if (t === "tech") tech(); if (t === "time") timeMachine();
  }
  function init() {
    $$("#proofTabs button").forEach((b) => b.addEventListener("click", () => tab(b.dataset.t)));
    $("#evalRefresh").addEventListener("click", tech);
    $("#auditType").addEventListener("change", audit); $("#auditSearch").addEventListener("input", audit);
    $("#verify").addEventListener("click", async () => { const v = await api("/api/audit/verify");
      $("#verifyOut").innerHTML = v.ok ? `<span class="tag ok">${ico("check", 12)} intact</span> ${v.entries} entries` : `<span class="tag bad">broken</span> at #${v.broken_at}`; });
  }
  return { init, enter() { tab($("#proofTabs button.on").dataset.t); TWIN.ready.then(() => TWIN.clearRoutes()); }, leave() { clearInterval(tmTimer); TWIN.clearHighlight(); } };
})();
