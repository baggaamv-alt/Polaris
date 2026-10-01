/* STORY: scroll-driven landing. One sticky network drawing changes state as each section scrolls into view:
 * India → nodes → telemetry → trust → disruption → cascade → alternatives → AI recommendation → approval → recovery →
 * Resilience Index. Every figure is pulled from the live API; the disruption example is computed by the real planner. */
"use strict";
PAGES.story = (() => {
  let built = false, io = null, stage = 0, ex = null, truckTimer = null;
  const HB = { lon0: 67, lon1: 92.5, lat0: 6.5, lat1: 32.5, W: 560, H: 540 };
  const hp = (lon, lat) => [((lon - HB.lon0) / (HB.lon1 - HB.lon0)) * HB.W, ((HB.lat1 - lat) / (HB.lat1 - HB.lat0)) * HB.H];
  const SECS = [
    ["01", "India, live.", "Suppliers, ports, factories and hubs linked by road, rail and sea.", (d) => `${NET.nodes.length} facilities · ${NET.links.length} links · ${STATE ? STATE.vehicles.length : 150} trucks`],
    ["02", "The network <em>appears</em>.", "Every facility and lane, with live weather at each.", () => { const c = (t) => NET.nodes.filter((n) => n.type === t).length; return `${c("Warehouse")} hubs · ${c("Port")} ports · ${c("Factory")} factories · ${c("Supplier")} suppliers · ${c("CustomerCluster")} demand clusters${WX.meta && WX.data.summary ? ` · weather ${WX.meta.status.toLowerCase()}: ${WX.data.summary.nodes_affected} facilities affected now` : WX.meta ? ` · weather ${WX.meta.status.toLowerCase()}` : ""}`; }],
    ["03", "Telemetry <em>streams in</em>.", "Trucks report position, speed, fuel and load.", () => STATE ? `${STATE.kpis.events_per_min.toLocaleString()} events per minute right now` : "connecting…"],
    ["04", "The Trust Engine <em>checks everything</em>.", "Eight checks per reading. Suspicious data is quarantined.", () => STATE ? `${STATE.kpis.trusted_coverage_pct}% of entities trusted · ${STATE.kpis.valid_pct}% messages valid` : ""],
    ["05", "A disruption <em>hits</em>.", "The Hyderabad–Vijayawada corridor closes.", () => ex ? `Example · ${ex.closed.join(", ")} closed` : ""],
    ["06", "The cascade <em>spreads</em>.", "Inbound stops, stock runs down, orders back up.", () => ex && ex.blast ? `If W-VGA fails, ${ex.blast.customers_cut_off_if_failed.join(" and ") || "no customer"} lose all supply` : ""],
    ["07", "Alternatives <em>appear</em>.", "Open routes around the closure, each costed.", () => ex ? `${ex.plan.routes.length} open alternatives found · ${ex.plan.routes.map((r) => `${r.label} ${hrs(r.time_h)}`).join(" · ")}` : ""],
    ["08", "The AI <em>recommends</em>.", "With the trade-off explained.", () => ex ? `Route ${ex.rec.label}: ${inr(ex.rec.total_cost)} · ${hrs(ex.rec.time_h)} · ${ex.plan.why[ex.plan.why.length > 1 ? 1 : 0] || ""}` : ""],
    ["09", "A human <em>approves</em>.", "Nothing moves until an operator approves. Every decision is logged.", () => ""],
    ["10", "The network <em>recovers</em>.", "Trucks reroute and hubs refill.", () => STATE && STATE.ops ? `${STATE.ops.orders_total} shipments in transit · network capacity ${STATE.ops.network_capacity_pct}%` : ""],
  ];
  function build() {
    const svg = $("#storyNet");
    let land = "";
    const L = TWIN_LAND();
    for (const poly of L) for (const ring of poly) { if (!ring.some(([x, y]) => x > HB.lon0 - 4 && x < HB.lon1 + 4 && y > HB.lat0 - 4 && y < HB.lat1 + 4)) continue; land += "M" + ring.map((c) => hp(c[0], c[1]).map((v) => v.toFixed(1)).join(",")).join("L") + "Z"; }
    const grid = []; for (let lon = 70; lon <= 90; lon += 5) { const [x] = hp(lon, 0); grid.push(`<line x1="${x}" y1="0" x2="${x}" y2="${HB.H}"/>`); } for (let lat = 10; lat <= 30; lat += 5) { const [, y] = hp(0, lat); grid.push(`<line x1="0" y1="${y}" x2="${HB.W}" y2="${y}"/>`); }
    const links = NET.links.map((l) => { const a = hp(...l.coords[0]), b = hp(...l.coords[1]); return `<line class="lk ${l.mode}" data-id="${l.id}" x1="${a[0].toFixed(1)}" y1="${a[1].toFixed(1)}" x2="${b[0].toFixed(1)}" y2="${b[1].toFixed(1)}"/>`; }).join("");
    const nodes = NET.nodes.map((n, i) => { const [x, y] = hp(n.lon, n.lat); const major = ["Warehouse", "Port", "Factory"].includes(n.type);
      return `<g class="nd" data-id="${n.id}" style="transition-delay:${(i * 25) % 900}ms"><circle cx="${x}" cy="${y}" r="${major ? 5 : 2.8}" fill="${n.type === "Warehouse" ? "var(--green)" : n.type === "Port" ? "var(--primary)" : n.type === "Factory" ? "var(--text-2)" : n.type === "Supplier" ? "var(--amber)" : "var(--muted)"}"/>${major ? `<text x="${x + 8}" y="${y + 3}" style="font:500 9px var(--sans,Inter,sans-serif);fill:var(--text-2)">${n.id}</text>` : ""}</g>`; }).join("");
    const [px, py] = hp(80.65, 16.51);
    svg.innerHTML = `<g class="grid">${grid.join("")}</g><path class="land" d="${land}"/><g>${links}</g><g id="stAlt"></g><g>${nodes}</g><g id="stTrucks" class="tk"></g><circle class="pulse" cx="${px}" cy="${py}" r="4"/><circle class="pulse" cx="${px}" cy="${py}" r="4" style="animation-delay:1s"/>`;
    $("#storySteps").innerHTML = `<div class="hero"><div class="kicker">Vigilax 2.5</div>
        <h1>Know what your network can take before it breaks.</h1>
        <p>Sees the network, trusts the right data, predicts disruption and recommends recovery.</p>
        <div class="row wrap"><a class="btn lg primary" href="#/command">Open the command center</a><a class="btn ghost lg" href="#/incident">Simulate a disruption</a></div>
        <div class="scene" aria-hidden="true">${["warehouse","truck","port","ship","plane","container","factory"].map((n)=>pxImg(n,{scale:2})).join('<i class="rt"></i>')}</div>
        <ol class="journey">${["See","Trust","Detect","Predict","Simulate","Optimize","Recover","Prove"].map((w, i) => `<li><span>${i + 1}</span>${w}</li>`).join("")}</ol>
        <div class="scrollhint">Scroll</div></div></div>`
      + SECS.map(([n, h, p], i) => `<section class="sec" data-s="${i + 1}"><div class="txt"><div class="n">${n} of 10</div><h2>${h}</h2><p>${p}</p><div class="fact" data-f="${i}"></div></div></section>`).join("")
      + `<section class="sec final" data-s="11"><div class="txt" style="max-width:460px"><div class="n">Result</div><h2>Supply chain <em>resilience</em></h2>
          <div class="ribar" style="margin:10px 0"><b id="stRI">—</b><span class="tag" id="stBand"></span></div>
                    <div class="row wrap"><a class="btn lg" href="#/command">Open the command center</a><a class="btn ghost lg" href="#/proof">See the proof</a></div>
          <p class="note">Fleet, orders and telemetry are simulated. Weather is real.</p></div></section>`;
    $("#storyHud").innerHTML = `<div class="glass" id="stHud"></div>`;
    built = true;
  }
  function TWIN_LAND() { // reuse the vendored coastline
    return (window.__land || []);
  }
  async function example() {
    try {
      const closed = ["L053", "L054"];
      const [plan, blast] = await Promise.all([post("/api/routes/plan", { origin: "W-HYD", destination: "W-VGA", avoid_disruptions: false, what_if_closed: ["L053"], priority: "HIGH",
        weights: { money: 0.3, time: 0.4, fuel: 0.1, distance: 0.1, carbon: 0.1 } }), api("/api/graph/blast/W-VGA")]);
      ex = { plan, rec: plan.routes.find((r) => r.id === plan.recommended), blast, closed };
    } catch { ex = null; }
  }
  function drawAlt(on) {
    const g = $("#stAlt"); if (!g) return;
    if (!on || !ex) { g.innerHTML = ""; return; }
    g.innerHTML = ex.plan.routes.map((r, i) => r.hops.map(([lid]) => { const l = LINK[lid]; const a = hp(...l.coords[0]), b = hp(...l.coords[1]);
      return `<line class="lk alt ${r.id === ex.rec.id && stage >= 8 ? "rec" : ""}" style="animation-delay:${i * 0.35}s;${r.id === ex.rec.id && stage >= 10 ? "stroke:var(--green)" : ""}" x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}"/>`; }).join("")).join("");
  }
  function trucks() {
    const g = $("#stTrucks"); if (!g || !STATE || (stage < 3 && stage !== 0)) { if (g) g.innerHTML = ""; return; }
    const sc = stateColors();
    g.innerHTML = STATE.vehicles.map((v) => { const [x, y] = hp(v.lon, v.lat); const c = stage >= 4 || stage === 0 ? sc[v.cls === "quarantined" ? "quarantined" : v.cls] : "var(--primary)";
      return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="1.9" fill="${c}"/>`; }).join("");
  }
  function applyWx(n) {
    const cells = {}; ((typeof WX !== "undefined" && WX.data && WX.data.cells) || []).forEach((c) => { cells[c.id] = c; });
    $$("#storyNet .nd").forEach((g) => { const c = cells[g.dataset.id], ci = g.querySelector("circle"); if (!ci) return;
      if (n >= 2 && c && c.sev >= 0.25) { ci.setAttribute("stroke", c.sev >= 0.75 ? "var(--red)" : "var(--amber)"); ci.setAttribute("stroke-width", "2.2"); ci.setAttribute("paint-order", "stroke"); } else ci.removeAttribute("stroke"); });
  }
  function hud() {
    const h = $("#stHud"); if (!h) return;
    const k = STATE ? STATE.kpis : null;
    const w = typeof WX !== "undefined" && WX.data ? WX.data : null, ws = w && w.summary;
    const cards = {
      2: w ? (ws ? `<div class="eyebrow">Real weather · ${esc(w.meta.status.toLowerCase())}</div><p class="xs" style="margin:6px 0 0">${ws.nodes_affected} of ${ws.nodes_total} facilities under severe weather now, ${ws.corridors_at_risk} corridors at risk in the next 48 h. Rings on the map mark affected facilities.</p>` : `<div class="eyebrow">Weather unavailable</div><p class="xs" style="margin:6px 0 0">Live weather could not be retrieved, so no weather effect is applied.</p>`) : "",
      3: `<div class="eyebrow">Telemetry</div><div class="pipe" style="grid-template-columns:repeat(2,1fr)"><div class="st"><b>events/min</b><span>${k ? k.events_per_min.toLocaleString() : "—"}</span></div><div class="st"><b>valid</b><span>${k ? k.valid_pct : "—"}%</span></div></div>`,
      4: `<div class="eyebrow">Trust Engine verdicts</div><div class="row wrap" style="margin-top:8px"><span class="verdict trusted"><i class="dot ok"></i> TRUSTED</span><span class="verdict estimated"><i class="dot warn"></i> UNCERTAIN</span><span class="verdict quarantined"><i class="dot bad"></i> SUSPICIOUS</span></div>`,
      5: `<div class="eyebrow">Resilience Engine</div><p class="xs">Fleet A stopped + Fleet B stopped + road alert (mock) + no contradicting traffic</p><div style="font:600 18px var(--sans,Inter,sans-serif);color:var(--red)">HIGH-CONFIDENCE DISRUPTION</div>`,
      7: ex ? `<div class="eyebrow">Alternatives</div>${ex.plan.routes.map((r, i) => `<div class="row xs" style="margin-top:4px"><b style="color:${ROUTE_COLORS[i]}">${r.label}</b>${esc(r.mode_label)}<span class="spacer"></span>${inr(r.total_cost)} · ${hrs(r.time_h)}</div>`).join("")}` : "",
      8: ex ? `<div class="eyebrow" style="color:var(--primary)">AI recommendation</div><div style="font:600 17px var(--sans,Inter,sans-serif)">Route ${ex.rec.label} · ${esc(ex.rec.mode_label)}</div><p class="xs muted">${esc(ex.plan.why.slice(-2).join(" · "))}</p>` : "",
      9: `<div class="row">${pxImg("driver", { scale: 3 })}<div><div class="eyebrow">Operator</div><button class="btn good sm" tabindex="-1">Approve</button></div></div>`,
      10: `<div class="eyebrow">Recovered</div><div class="row">${pxImg("check", { scale: 3 })}<b>Route active · network stabilizing</b></div>`,
    };
    h.innerHTML = cards[stage] || ""; h.classList.toggle("on", !!cards[stage]);
  }
  function setStage(n) {
    stage = n;
    const svg = $("#storyNet");
    svg.classList.toggle("s-nodes", n >= 2 || n === 0); svg.classList.toggle("s-live", n >= 3 || n === 0); svg.classList.toggle("s-dis", n >= 5 && n < 10);
    svg.style.setProperty("--sc", n === 0 ? 0.95 : n === 1 ? 1 : n >= 5 && n <= 9 ? 1.55 : 1.08);
    svg.style.setProperty("--tx", n === 0 || n === 11 ? "22%" : "12%");
    svg.style.setProperty("--py", n >= 5 && n <= 9 ? "6%" : "0");
    $$(".lk", svg).forEach((l) => l.classList.toggle("cut", !!ex && n >= 5 && n < 10 && ex.closed.includes(l.dataset.id)));
    const cutoff = new Set(ex && ex.blast ? [...ex.blast.customers_cut_off_if_failed, ...ex.blast.direct] : []);
    $$(".nd", svg).forEach((g) => { g.classList.toggle("warn", n >= 6 && n < 10 && cutoff.has(g.dataset.id)); g.classList.toggle("bad", n >= 5 && n < 10 && g.dataset.id === "W-VGA"); });
    drawAlt(n >= 7); trucks(); hud(); applyWx(n);
    const tk = $("#stTrucks"); if (tk) tk.style.opacity = n >= 5 && n <= 9 ? 0.28 : 1;
    $$("#storySteps .fact").forEach((f) => { const i = +f.dataset.f; f.textContent = SECS[i][3](); });
    if (n === 11 && STATE && STATE.resilience) { countTo($("#stRI"), STATE.resilience.index, (x) => x.toFixed(0), 1600); $("#stBand").textContent = STATE.resilience.band; $("#stBand").className = `tag band-${STATE.resilience.band}`; }
  }
  return {
    async enter() {
      if (!built) { build(); await example(); }
      if (io) io.disconnect();
      io = new IntersectionObserver((ents) => ents.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); setStage(+e.target.dataset.s || 0); } }), { threshold: 0.45 });
      $$("#storySteps .sec, #storySteps .hero").forEach((s) => io.observe(s));
      setStage(0);
      clearInterval(truckTimer); truckTimer = setInterval(() => { if (PAGE === "") { trucks(); hud(); } }, 1500);
    },
    refresh() { if (built) { hud(); applyWx(stage); $$("#storySteps .fact").forEach((f) => { const i = +f.dataset.f; f.textContent = SECS[i][3](); }); } },
    leave() { if (io) io.disconnect(); clearInterval(truckTimer); },
  };
})();
on("weather", () => { if (PAGE === "") { try { PAGES.story.refresh && PAGES.story.refresh(); } catch { /* story not built yet */ } } });
