/* VIGILAX · 2.5 front end — core: utilities, theme, router, live state bus, motion helpers.
 * Every number on screen comes from an API field. Nothing is hardcoded; simulated data is labelled. */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) {
    let m = await r.text();
    try { const j = JSON.parse(m); m = j.detail || m; } catch { /* plain text */ }
    throw new Error(typeof m === "string" ? m : JSON.stringify(m));
  }
  return r.json();
}
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}) });

/* ---------------------------------------------------------------- formatting */
const inr = (x, d = 0) => (x == null ? "—" : `₹${Math.round(x).toLocaleString("en-IN")}`);
const lakh = (x) => { if (x == null) return "—"; const s = x < 0 ? "−" : "", a = Math.abs(x);
  return a >= 1e7 ? `${s}₹${(a / 1e7).toLocaleString("en-IN", { maximumFractionDigits: 2 })} Cr` : `${s}₹${(a / 1e5).toLocaleString("en-IN", { maximumFractionDigits: 2 })} L`; };
const pct = (x, d = 1) => (x == null ? "—" : `${(100 * x).toFixed(d)}%`);
const hrs = (h) => (h == null ? "—" : h < 1 ? `${Math.round(h * 60)} min` : `${h.toFixed(h < 10 ? 1 : 0)} h`);
const km = (x) => (x == null ? "—" : `${Math.round(x).toLocaleString("en-IN")} km`);
const clock = (t) => { const m = Math.floor((t + 8 * 3600) / 60); return `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`; };
const dayclock = (t) => `D${Math.floor((t + 8 * 3600) / 86400) + 1} ${clock(t)}`;
const cap = (s) => String(s || "").replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase());

/* ---------------------------------------------------------------- theme-aware colours */
function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
const STATE_COLOR = { trusted: "#3f7d58", estimated: "#b9822a", quarantined: "#a8403a", stale: "#7a8594" };
function stateColors() {
  return { trusted: css("--green"), estimated: css("--amber"), quarantined: css("--red"), stale: css("--neutral") };
}
const ROUTE_COLORS = ["#35557a", "#b9822a", "#3f7d58", "#7a5a8a", "#8a7a45"];
const CLS_LABEL = { trusted: "TRUSTED", estimated: "UNCERTAIN", quarantined: "SUSPICIOUS" };
const CLS_ICON = { trusted: '<i class="dot ok"></i>', estimated: '<i class="dot warn"></i>', quarantined: '<i class="dot bad"></i>' };
const NAMES = { do_nothing: "Do nothing", reroute: "Reroute", transfer: "Transfer stock", hybrid: "Reroute + transfer" };
const TYPE_SPRITE = { Warehouse: "warehouse", Port: "port", Factory: "factory", Supplier: "supplier", CustomerCluster: "pin" };

/* ---------------------------------------------------------------- UI helpers */
function toast(msg, kind = "") {
  const t = document.createElement("div");
  t.className = `toast ${kind === true ? "err" : kind}`;
  const spr = kind === "ok" ? "check" : kind === "ai" ? "robot" : kind === "err" || kind === true ? "warning" : "radar";
  t.innerHTML = `${pxImg(spr, { scale: 1 })}<span>${esc(msg)}</span>`;
  $("#toasts").appendChild(t);
  setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 400); }, 4600);
}
const meter = (v, cls = "") => `<div class="meter ${cls}"><i style="width:${Math.max(0, Math.min(1, v ?? 0)) * 100}%"></i></div>`;
const stateOf = (v) => (v >= 0.8 ? "ok" : v >= 0.5 ? "warn" : "bad");
const loading = (msg, bars = 3) => `<div class="loading"><div class="road">${pxImg("truck", { scale: 2, c: "#b9822a" })}</div><span>${esc(msg)}</span><div class="bars">${"<i></i>".repeat(bars)}</div></div>`;
const empty = (sprite, title, text, action = "") => `<div class="empty">${pxImg(sprite, { scale: 3, c: "#b9822a" })}<div><b>${esc(title)}</b>${text ? `<p>${text}</p>` : ""}${action}</div></div>`;
const dm = (kind, label) => `<span class="dm ${kind}">${esc(label || kind)}</span>`;

/* animated number: remembers the previous value on the element */
function countTo(el, value, fmt = (x) => Math.round(x).toLocaleString("en-IN"), dur = 900) {
  if (!el) return;
  if (value == null || Number.isNaN(value)) { el.textContent = "—"; el.dataset.v = ""; return; }
  const from = el.dataset.v === undefined || el.dataset.v === "" ? value : +el.dataset.v;
  el.dataset.v = value;
  if (REDUCED || from === value || !document.body.contains(el)) { el.textContent = fmt(value); return; }
  const t0 = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
    el.textContent = fmt(from + (value - from) * e);
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
function flash(el) { if (!el || REDUCED) return; el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash"); }
function setRangeFill(r) { const p = ((r.value - r.min) / (r.max - r.min)) * 100; r.style.setProperty("--fill", `${p}%`); }
function busy(btn, on) { if (!btn) return; btn.disabled = on; btn.classList.toggle("busy", on); }

function modal(html) {
  const m = document.createElement("div"); m.className = "modal";
  m.innerHTML = `<div class="box" role="dialog" aria-modal="true">${html}</div>`;
  document.body.appendChild(m);
  const close = () => { m.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  m.addEventListener("click", (e) => { if (e.target === m) close(); });
  return { el: m, close };
}

/* tooltips for any [data-tip] */
(function tips() {
  const tip = () => $("#tip");
  document.addEventListener("pointerover", (e) => {
    const t = e.target.closest("[data-tip]"); if (!t) return;
    const el = tip(); el.innerHTML = t.dataset.tip; el.classList.add("on");
    const r = t.getBoundingClientRect(), w = el.offsetWidth;
    el.style.left = `${Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width / 2 - w / 2))}px`;
    el.style.top = `${r.top - el.offsetHeight - 8 < 60 ? r.bottom + 8 : r.top - el.offsetHeight - 8}px`;
  });
  document.addEventListener("pointerout", (e) => { if (e.target.closest("[data-tip]")) tip().classList.remove("on"); });
})();
/* press ripple position for buttons */
document.addEventListener("pointerdown", (e) => {
  const b = e.target.closest(".btn"); if (!b) return;
  const r = b.getBoundingClientRect(); b.style.setProperty("--mx", `${e.clientX - r.left}px`); b.style.setProperty("--my", `${e.clientY - r.top}px`);
});

/* ---------------------------------------------------------------- event bus */
const BUS = {};
function on(ev, fn) { (BUS[ev] ||= []).push(fn); }
function emit(ev, data) { (BUS[ev] || []).forEach((fn) => { try { fn(data); } catch (err) { console.error(ev, err); } }); }

/* ---------------------------------------------------------------- global state */
let NET = null, STATE = null, SCN = null;
const NODE = {}, LINK = {};
const PAGES = {};
let PAGE = null;

/* ---------------------------------------------------------------- theme */
const SUN = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>`;
const MOON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>`;
function theme() { return document.documentElement.dataset.theme || "light"; }
function setTheme(t) {
  document.body.classList.add("theming");
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("pnt1.theme", t); } catch { /* storage unavailable */ }
  $("#themeBtn").innerHTML = t === "dark" ? SUN : MOON;
  setTimeout(() => document.body.classList.remove("theming"), 500);
  emit("theme", t);
}

/* ---------------------------------------------------------------- router */
const LAYOUT = { command: "map", twin: "map", incident: "split", recovery: "split", business: "wide", proof: "split" };
function route() {
  const key = location.hash.replace(/^#\/?/, "").split("?")[0];
  const page = LAYOUT[key] ? key : "";
  const story = !page;
  document.body.classList.toggle("story-mode", story);
  $("#story").hidden = !story;
  $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.p === page));
  if (PAGE && PAGE !== page && PAGES[PAGE] && PAGES[PAGE].leave) PAGES[PAGE].leave();
  const prev = PAGE; PAGE = page;
  if (story) { window.scrollTo(0, 0); if (PAGES.story) PAGES.story.enter(); emit("page", "story"); return; }
  if (PAGES.story && prev === "") PAGES.story.leave?.();
  $("#stage").dataset.layout = LAYOUT[page];
  $$(".pg").forEach((el) => el.classList.toggle("active", el.dataset.page === page));
  $("#panel").scrollTop = 0;
  if (PAGES[page] && PAGES[page].enter) PAGES[page].enter();
  emit("page", page);
  setTimeout(() => emit("resize"), 650);
}
window.addEventListener("hashchange", route);

/* ---------------------------------------------------------------- clock controls */
function initClock() {
  $$("#speedSeg button").forEach((b) => b.addEventListener("click", async () => {
    await post("/api/clock", { speed: +b.dataset.v });
    $$("#speedSeg button").forEach((x) => x.classList.toggle("on", x === b));
    toast(`Simulation speed ${b.dataset.v}×`);
  }));
  $("#pause").addEventListener("click", async () => {
    const r = await post("/api/clock", { paused: !(STATE && STATE.paused) });
    $("#pause").innerHTML = r.paused ? `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 5l12 7-12 7z"/></svg>` : `<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>`;
    toast(r.paused ? "Simulation paused" : "Simulation resumed");
  });
}

/* ---------------------------------------------------------------- live state */
let wsOk = false;
function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onopen = () => { wsOk = true; };
  ws.onmessage = (e) => {
    const s = JSON.parse(e.data);
    const prev = STATE; STATE = s;
    $("#simtime").textContent = new Date(s.sim_time).toISOString().slice(5, 16).replace("T", " ");
    const mode = s.kpis.mode, m = $("#mode");
    m.className = `modechip st-${mode}`; m.textContent = mode;
    emit("state", { s, prev });
  };
  ws.onclose = () => { wsOk = false; $("#simtime").textContent = "reconnecting…"; setTimeout(connect, 2000); };
}

/* ---------------------------------------------------------------- shared renderers used by several pages */
function prioSliders(host, init, onChange, { compact = false } = {}) {
  const ICON = { money: ico("rupee"), time: ico("clock"), fuel: ico("fuel"), distance: ico("ruler"), carbon: ico("leaf") };
  const LBL = { money: "Money", time: "Time", fuel: "Fuel", distance: "Distance", carbon: "Carbon" };
  const COL = { money: "--amber", time: "--primary", fuel: "--red", distance: "--cyan", carbon: "--green" };
  const keys = ["money", "time", "fuel", "distance", "carbon"];
  const w = { ...init };
  const presets = { Balanced: { money: 20, time: 20, fuel: 20, distance: 20, carbon: 20 }, Cost: { money: 70, time: 10, fuel: 10, distance: 5, carbon: 5 },
    Speed: { money: 10, time: 70, fuel: 5, distance: 10, carbon: 5 }, Green: { money: 10, time: 10, fuel: 20, distance: 5, carbon: 55 } };
  host.innerHTML = `<div class="chips" style="margin-bottom:8px">${Object.keys(presets).map((p) => `<button class="chip" data-p="${p}">${p}</button>`).join("")}</div>
    <div class="prio">${keys.map((k) => `<div class="pl" data-k="${k}"><span>${ICON[k]}</span><span>${LBL[k]}</span><input type="range" min="0" max="100" step="1" value="${w[k]}" style="--c:var(${COL[k]})" aria-label="${LBL[k]} weight"><b>${Math.round(share(k))}%</b></div>`).join("")}</div>`;
  function share(k) { const s = keys.reduce((a, x) => a + (+w[x] || 0), 0) || 1; return (100 * (+w[k] || 0)) / s; }
  function paint() { keys.forEach((k) => { const row = $(`.pl[data-k=${k}]`, host); $("b", row).textContent = `${Math.round(share(k))}%`; setRangeFill($("input", row)); }); }
  let timer = null;
  const fire = () => { clearTimeout(timer); timer = setTimeout(() => onChange({ ...w }), compact ? 0 : 260); };
  keys.forEach((k) => { const r = $(`.pl[data-k=${k}] input`, host); r.addEventListener("input", () => { w[k] = +r.value; paint(); const row = r.closest(".pl"); row.classList.add("bump"); setTimeout(() => row.classList.remove("bump"), 300); $$(".chip", host).forEach((c) => c.classList.remove("on")); fire(); }); });
  $$(".chip", host).forEach((c) => c.addEventListener("click", () => { Object.assign(w, presets[c.dataset.p]); keys.forEach((k) => ($(`.pl[data-k=${k}] input`, host).value = w[k])); paint(); $$(".chip", host).forEach((x) => x.classList.toggle("on", x === c)); onChange({ ...w }); }));
  paint();
  return { get: () => ({ ...w }), set: (nw) => { Object.assign(w, nw); keys.forEach((k) => ($(`.pl[data-k=${k}] input`, host).value = w[k])); paint(); } };
}
function shares(w) { const k = ["money", "time", "fuel", "distance", "carbon"], s = k.reduce((a, x) => a + (+w[x] || 0), 0) || 1; return Object.fromEntries(k.map((x) => [x, (+w[x] || 0) / s])); }


/* ---------------------------------------------------------------- causal line: a row of steps that light up as the chain progresses */
function causal(host, steps) {
  const el = typeof host === "string" ? $(host) : host; if (!el) return;
  if (!el.classList.contains("causal")) { el.classList.add("chain", "causal"); el.innerHTML = steps.map(() => '<div class="ch"><b></b><span></span><small></small></div>').join(""); }
  steps.forEach(([b, v, sm, cl], i) => {
    const c = el.children[i]; if (!c) return;
    c.querySelector("b").textContent = b; c.querySelector("span").textContent = v; c.querySelector("small").textContent = sm;
    const want = cl ? `on ${cl}` : "", have = c.dataset.cl || "";
    if (want === have) return;
    c.dataset.cl = want;
    const apply = () => { c.classList.remove("on", "ok", "warn", "bad", "ai"); if (cl) { c.classList.add("on", cl); } };
    if (REDUCED || !cl || have) apply(); else setTimeout(apply, i * 140);
  });
}
