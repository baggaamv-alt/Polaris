/* VIGILAX · 2.5 — the persistent 3D geospatial digital twin (one MapLibre globe shared by every page).
 *
 * Honesty rules encoded here:
 *  - The satellite layer is Esri World Imagery, a STATIC basemap. It is never presented as live satellite intelligence.
 *  - Trucks are the simulator's telemetry after the Trust Engine (SIMULATED).
 *  - Ships and trains animate optimizer-PLANNED sea/rail flows, not tracked vessels.
 *
 * Performance: one rAF loop; GeoJSON sources are updated at ≤ 20 fps; paint-property animations at ≤ 15 fps;
 * the loop stops while the map is hidden (story page / background tab) and runs at reduced cost with reduced motion.
 */
"use strict";
const TWIN = (() => {
  let map = null, ready = null, readyResolve;
  ready = new Promise((r) => (readyResolve = r));
  const EMPTY = { type: "FeatureCollection", features: [] };
  let LAND = null;
  let basemap = "satellite", proj = "globe", satFailed = false, satOk = false;
  const opt = { trucks: true, flows: true, assets: true, columns: true, labels: true, relief: true, autofocus: true, weather: true, terrain: true };
  try { const s = JSON.parse(localStorage.getItem("pnt1.map") || "{}"); Object.assign(opt, s.opt || {}); basemap = s.basemap || basemap; proj = s.proj || proj; } catch { /* default */ }
  const save = () => { try { localStorage.setItem("pnt1.map", JSON.stringify({ opt, basemap, proj })); } catch { /* ignore */ } };

  /* ------------------------------------------------------------ palette per theme */
  function P() {
    const dark = theme() === "dark";
    return {
      dark, bg: css("--map-bg"), land: css("--map-land"), coast: css("--map-coast"), grid: css("--map-grid"),
      road: dark ? "rgba(205,208,214,0.36)" : "rgba(58,64,74,0.42)", roadActive: dark ? "#9ab6d6" : "#2f4a6a",
      rail: dark ? "#d3a75e" : "#8a6230", sea: dark ? "#82adc2" : "#4a7590", node: dark ? "#c9d6e3" : "#2f4a6a", supplier: dark ? "#d3a75e" : "#8a6230", customer: dark ? "#9aa4ae" : "#6d7780",
      closed: css("--red"), suspected: css("--amber"), ok: css("--green"), warn: css("--amber"), bad: css("--red"),
      unknown: css("--neutral"), primary: css("--primary"), violet: css("--violet"), cyan: css("--cyan"),
      casing: dark ? "#14171a" : "#f6f2e7", hl: css("--amber"),
    };
  }

  /* ------------------------------------------------------------ geometry helpers */
  const lerp = (a, b, t) => a + (b - a) * t;
  function bearing(a, b) { const y = Math.sin((b[0] - a[0]) * Math.PI / 180) * Math.cos(b[1] * Math.PI / 180);
    const x = Math.cos(a[1] * Math.PI / 180) * Math.sin(b[1] * Math.PI / 180) - Math.sin(a[1] * Math.PI / 180) * Math.cos(b[1] * Math.PI / 180) * Math.cos((b[0] - a[0]) * Math.PI / 180);
    return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360; }
  function along(coords, f) { // position at fraction f along a polyline (planar, fine for display)
    if (coords.length === 2) return [lerp(coords[0][0], coords[1][0], f), lerp(coords[0][1], coords[1][1], f), bearing(coords[0], coords[1])];
    let tot = 0; const seg = [];
    for (let i = 1; i < coords.length; i++) { const d = Math.hypot(coords[i][0] - coords[i - 1][0], coords[i][1] - coords[i - 1][1]); seg.push(d); tot += d; }
    let x = f * tot;
    for (let i = 0; i < seg.length; i++) { if (x <= seg[i] || i === seg.length - 1) { const t = seg[i] ? Math.min(1, x / seg[i]) : 0;
      return [lerp(coords[i][0], coords[i + 1][0], t), lerp(coords[i][1], coords[i + 1][1], t), bearing(coords[i], coords[i + 1])]; } x -= seg[i]; }
    return [...coords[coords.length - 1], 0];
  }
  function bbox(coords) { let a = [999, 999, -999, -999]; coords.forEach(([x, y]) => { a = [Math.min(a[0], x), Math.min(a[1], y), Math.max(a[2], x), Math.max(a[3], y)]; }); return [[a[0], a[1]], [a[2], a[3]]]; }
  const square = (lon, lat, r) => { const k = r / Math.cos(lat * Math.PI / 180); return [[[lon - k, lat - r], [lon + k, lat - r], [lon + k, lat + r], [lon - k, lat + r], [lon - k, lat - r]]]; };

  /* ------------------------------------------------------------ vendored coastline (works offline) */
  async function loadLand() {
    try {
      const topo = await (await fetch("/static/vendor/land-50m.json")).json();
      const world = topojson.feature(topo, topo.objects.land);
      const near = (ring) => { let x0 = 999, x1 = -999, y0 = 999, y1 = -999; for (const [x, y] of ring) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); } return y0 > -60; };
      const polys = [];
      for (const f of world.features) { const g = f.geometry; const list = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
        for (const p of list) if (near(p[0]) && p[0].length >= 8) polys.push(p); }
      LAND = { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "MultiPolygon", coordinates: polys } }] };
      window.__land = polys;          // the story page draws the same coastline
    } catch { LAND = EMPTY; }
    return LAND;
  }
  function graticule() { const f = [];
    for (let lon = -180; lon <= 180; lon += 10) f.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: Array.from({ length: 33 }, (_, i) => [lon, -80 + i * 5]) } });
    for (let lat = -80; lat <= 80; lat += 10) f.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: Array.from({ length: 73 }, (_, i) => [-180 + i * 5, lat]) } });
    return { type: "FeatureCollection", features: f }; }

  function style() {
    const p = P();
    return { version: 8, projection: { type: proj },
      sky: skySpec(),
      sources: {
        land: { type: "geojson", data: LAND || EMPTY, maxzoom: 7, tolerance: 0.8, attribution: "Coastline: Natural Earth" },
        grid: { type: "geojson", data: graticule() },
        sat: { type: "raster", tileSize: 256, maxzoom: 17, tiles: [location.origin + "/tiles/sat/{z}/{x}/{y}"],
          attribution: "Imagery © Esri, Maxar, Earthstar Geographics (static basemap, not live) · served via the local tile cache" },
        dem: { type: "raster-dem", encoding: "terrarium", tileSize: 256, maxzoom: 10, tiles: [location.origin + "/tiles/dem/{z}/{x}/{y}"],
          attribution: "Elevation: Mapzen/AWS Terrain Tiles" },
      },
      layers: [
        { id: "bg", type: "background", paint: { "background-color": p.bg } },
        { id: "grid", type: "line", source: "grid", paint: { "line-color": p.grid, "line-width": 0.6 } },
        { id: "land", type: "fill", source: "land", paint: { "fill-color": p.land } },
        { id: "coast", type: "line", source: "land", paint: { "line-color": p.coast, "line-width": 0.9 } },
        { id: "sat", type: "raster", source: "sat", layout: { visibility: basemap === "satellite" ? "visible" : "none" },
          paint: { "raster-saturation": p.dark ? -0.55 : -0.45, "raster-brightness-max": p.dark ? 0.62 : 0.92, "raster-contrast": 0.05, "raster-fade-duration": 250 } },
        { id: "relief", type: "hillshade", source: "dem", layout: { visibility: opt.relief ? "visible" : "none" },
          paint: { "hillshade-exaggeration": basemap === "satellite" ? 0.25 : 0.45, "hillshade-shadow-color": p.dark ? "#000" : "#6d6656", "hillshade-highlight-color": p.dark ? "#56606b" : "#fffdf5", "hillshade-accent-color": p.dark ? "#1a1e22" : "#d9d2bf" } },
      ] };
  }
  function skySpec() {
    const dark = theme() === "dark";
    return dark ? { "sky-color": "#0f1214", "horizon-color": "#2a3038", "fog-color": "#14171a", "sky-horizon-blend": 0.4, "horizon-fog-blend": 0.4, "fog-ground-blend": 0.8,
      "atmosphere-blend": ["interpolate", ["linear"], ["zoom"], 0, 0.6, 5, 0.6, 7, 0] }
      : { "sky-color": "#d9d3c2", "horizon-color": "#f1ece0", "fog-color": "#ece6d8", "sky-horizon-blend": 0.4, "horizon-fog-blend": 0.4, "fog-ground-blend": 0.85,
        "atmosphere-blend": ["interpolate", ["linear"], ["zoom"], 0, 0.5, 5, 0.5, 7, 0] };
  }

  /* ------------------------------------------------------------ sprites */
  function addImages() {
    const sc = stateColors();
    const put = (id, name, o) => { const cv = pxCanvas(name, { scale: 2, ...o }); const data = cv.getContext("2d").getImageData(0, 0, cv.width, cv.height);
      if (map.hasImage(id)) map.updateImage(id, data); else map.addImage(id, data, { pixelRatio: 2 }); };
    Object.entries(sc).forEach(([s, c]) => { put(`truck-${s}-r`, "truck", { c }); put(`truck-${s}-l`, "truck", { c, flip: true }); });
    put("ship-r", "ship"); put("ship-l", "ship", { flip: true }); put("train-r", "train"); put("train-l", "train", { flip: true });
    put("pkg", "package"); put("n-Warehouse", "warehouse"); put("n-Port", "port"); put("n-Factory", "factory"); put("n-Supplier", "supplier"); put("n-CustomerCluster", "pin", { c: PX_PALETTE.n });
  }

  /* ------------------------------------------------------------ data → GeoJSON */
  function linkFC() {
    return { type: "FeatureCollection", features: NET.links.map((l) => ({ type: "Feature",
      properties: { id: l.id, mode: l.mode, corridor: l.corridor, from: l.from, to: l.to, status: "open", act: 0, hl: 0 },
      geometry: { type: "LineString", coordinates: l.coords } })) };
  }
  const nodeState = {};
  function nodeFC() {
    return { type: "FeatureCollection", features: NET.nodes.map((n) => ({ type: "Feature",
      properties: { id: n.id, type: n.type, name: n.name, icon: `n-${n.type}`, state: nodeState[n.id] || "healthy", major: ["Warehouse", "Port", "Factory"].includes(n.type) ? 1 : 0, hl: 0 },
      geometry: { type: "Point", coordinates: [n.lon, n.lat] } })) };
  }
  let colStock = {};
  function columnFC() {
    return { type: "FeatureCollection", features: NET.nodes.filter((n) => n.type === "Warehouse").map((n) => ({ type: "Feature",
      properties: { id: n.id, h: Math.max(4000, (colStock[n.id] || 0) * 30), state: nodeState[n.id] || "healthy" }, geometry: { type: "Polygon", coordinates: square(n.lon, n.lat, 0.07) } })) };
  }

  /* ------------------------------------------------------------ layers */
  function addLayers() {
    const p = P();
    map.addSource("links", { type: "geojson", data: linkFC() });
    map.addSource("nodes", { type: "geojson", data: nodeFC() });
    map.addSource("cols", { type: "geojson", data: columnFC() });
    map.addSource("wx", { type: "geojson", data: EMPTY });
    map.addSource("veh", { type: "geojson", data: EMPTY });
    map.addSource("cargo", { type: "geojson", data: EMPTY });
    map.addSource("assets", { type: "geojson", data: EMPTY });
    map.addSource("ripples", { type: "geojson", data: EMPTY });
    map.addSource("sel", { type: "geojson", data: EMPTY });
    map.addSource("hl", { type: "geojson", data: EMPTY });
    for (let i = 0; i < 5; i++) map.addSource(`route${i}`, { type: "geojson", data: EMPTY, lineMetrics: true });
    map.addSource("restore", { type: "geojson", data: EMPTY, lineMetrics: true });
    map.addSource("mover", { type: "geojson", data: EMPTY });

    const L = (id, filter, paint, layout = {}) => map.addLayer({ id, type: "line", source: "links", filter, layout: { "line-cap": "round", "line-join": "round", ...layout }, paint });
    const open = ["==", ["get", "status"], "open"], mode = (m) => ["==", ["get", "mode"], m];
    const zw = (a, b) => ["interpolate", ["linear"], ["zoom"], 3, a, 8, b];
    L("l-road", ["all", mode("road"), open], { "line-color": ["case", [">", ["get", "act"], 0], p.roadActive, p.road], "line-width": ["interpolate", ["linear"], ["zoom"], 3, ["case", [">", ["get", "act"], 0], 1.4, 0.7], 8, ["case", [">", ["get", "act"], 0], 3.2, 1.6]], "line-opacity": 0.9 });
    L("l-rail", ["all", mode("rail"), open], { "line-color": p.rail, "line-width": zw(1.2, 2.6), "line-dasharray": [3, 2], "line-opacity": 0.85 }, { "line-cap": "butt" });
    L("l-sea", ["all", mode("sea"), open], { "line-color": p.sea, "line-width": zw(1.2, 2.4), "line-dasharray": [0.4, 2.2], "line-opacity": 0.85 });
    L("l-casing", ["!", open], { "line-color": p.casing, "line-width": zw(6, 11), "line-opacity": 0.85 });
    L("l-closed", ["match", ["get", "status"], ["blocked", "blocked_inferred", "closed"], true, false], { "line-color": p.closed, "line-width": zw(3, 6), "line-dasharray": [2, 2] }, { "line-cap": "butt" });
    L("l-suspected", ["==", ["get", "status"], "suspected"], { "line-color": p.suspected, "line-width": zw(3, 6), "line-dasharray": [1, 1.4] }, { "line-cap": "butt" });
    map.addLayer({ id: "hl-line", type: "line", source: "hl", filter: ["==", ["geometry-type"], "LineString"], paint: { "line-color": p.hl, "line-width": zw(5, 10), "line-opacity": 0.9 } });

    map.addLayer({ id: "restore", type: "line", source: "restore", layout: { "line-cap": "round" }, paint: { "line-width": zw(4, 8), "line-gradient": ["step", ["line-progress"], p.ok, 0, "rgba(0,0,0,0)"] } });
    for (let i = 4; i >= 0; i--) {
      map.addLayer({ id: `route${i}-glow`, type: "line", source: `route${i}`, layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
        paint: { "line-width": zw(1, 2), "line-opacity": 0, "line-gradient": ["step", ["line-progress"], ROUTE_COLORS[i], 0, "rgba(0,0,0,0)"] } });
      map.addLayer({ id: `route${i}`, type: "line", source: `route${i}`, layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-width": zw(3, 6), "line-gradient": ["step", ["line-progress"], ROUTE_COLORS[i], 0, "rgba(0,0,0,0)"] } });
    }
    const wxCol = ["interpolate", ["linear"], ["get", "sev"], 0.25, "#c9962e", 0.5, "#c2692f", 0.75, "#a8403a"];
    map.addLayer({ id: "wx-halo", type: "circle", source: "wx", filter: [">=", ["get", "sev"], 0.25], layout: { visibility: opt.weather ? "visible" : "none" }, paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, ["+", 6, ["*", 12, ["get", "sev"]]], 7, ["+", 12, ["*", 28, ["get", "sev"]]]], "circle-color": wxCol, "circle-opacity": 0.1, "circle-blur": 0 } });
    map.addLayer({ id: "wx-ring", type: "circle", source: "wx", filter: [">=", ["get", "sev"], 0.25], layout: { visibility: opt.weather ? "visible" : "none" }, paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 4, 8, 9], "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": wxCol, "circle-stroke-width": 1.6, "circle-stroke-opacity": 0.9 } });
    map.addLayer({ id: "cargo", type: "circle", source: "cargo", layout: { visibility: opt.flows ? "visible" : "none" }, paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 1.6, 8, 3.2], "circle-color": ["match", ["get", "mode"], "rail", p.rail, "sea", p.sea, p.cyan],
      "circle-opacity": 0.95, "circle-blur": 0 } });
    map.addLayer({ id: "cols", type: "fill-extrusion", source: "cols", maxzoom: 7, layout: { visibility: opt.columns ? "visible" : "none" }, paint: {
      "fill-extrusion-color": ["match", ["get", "state"], "critical", p.bad, "warning", p.warn, "unknown", p.unknown, p.primary],
      "fill-extrusion-height": ["get", "h"], "fill-extrusion-opacity": 0.7, "fill-extrusion-height-transition": { duration: 900 } } });
    map.addLayer({ id: "ripple", type: "circle", source: "ripples", paint: { "circle-radius": 10, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": p.closed, "circle-stroke-width": 2, "circle-stroke-opacity": 0.8 } });
    map.addLayer({ id: "ripple2", type: "circle", source: "ripples", paint: { "circle-radius": 10, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": p.closed, "circle-stroke-width": 1.5, "circle-stroke-opacity": 0.45 } });
    map.addLayer({ id: "n-pulse", type: "circle", source: "nodes", filter: ["==", ["get", "major"], 1], paint: { "circle-radius": 8, "circle-color": "rgba(0,0,0,0)", "circle-stroke-width": 1,
      "circle-stroke-color": ["match", ["get", "state"], "critical", p.bad, "warning", p.warn, "unknown", p.unknown, p.ok], "circle-stroke-opacity": 0.45 } });
    map.addLayer({ id: "n-core", type: "circle", source: "nodes", paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, ["case", ["==", ["get", "major"], 1], 4, 2.2], 8, ["case", ["==", ["get", "major"], 1], 7, 4]],
      "circle-color": ["match", ["get", "state"], "critical", p.bad, "warning", p.warn, "unknown", p.unknown, ["match", ["get", "type"], "Supplier", p.supplier, "CustomerCluster", p.customer, "Port", p.sea, "Factory", p.rail, p.node]],
      "circle-stroke-color": p.casing, "circle-stroke-width": 1.2 } });
    map.addLayer({ id: "hl-node", type: "circle", source: "hl", filter: ["==", ["geometry-type"], "Point"], paint: { "circle-radius": 16, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": p.hl, "circle-stroke-width": 3, "circle-blur": 0 } });
    map.addLayer({ id: "n-icon", type: "symbol", source: "nodes", minzoom: 5.2, layout: { "icon-image": ["get", "icon"], "icon-allow-overlap": true, "icon-ignore-placement": true,
      "icon-size": ["interpolate", ["linear"], ["zoom"], 5.2, 0.9, 9, 2], "icon-offset": [0, -9] } });
    map.addLayer({ id: "assets", type: "symbol", source: "assets", layout: { visibility: opt.assets ? "visible" : "none", "icon-image": ["get", "icon"], "icon-allow-overlap": true, "icon-ignore-placement": true,
      "icon-size": ["interpolate", ["linear"], ["zoom"], 3, 0.7, 8, 1.6] } });
    map.addLayer({ id: "veh-glow", type: "circle", source: "veh", layout: { visibility: opt.trucks ? "visible" : "none" }, paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 3.2, 7, 7, 10, 14], "circle-blur": 0, "circle-opacity": 0,
      "circle-color": ["get", "col"] } });
    map.addLayer({ id: "veh-dot", type: "circle", source: "veh", maxzoom: 6.2, layout: { visibility: opt.trucks ? "visible" : "none" }, paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 1.7, 6.2, 3.2], "circle-color": ["get", "col"], "circle-stroke-color": p.casing, "circle-stroke-width": 0.6 } });
    map.addLayer({ id: "veh-crit", type: "circle", source: "veh", minzoom: 5.5, filter: ["==", ["get", "pr"], 1], layout: { visibility: opt.trucks ? "visible" : "none" }, paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 5.5, 7, 10, 16], "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": p.violet, "circle-stroke-width": 1.4, "circle-stroke-opacity": 0.9 } });
    map.addLayer({ id: "veh", type: "symbol", source: "veh", minzoom: 6.2, layout: { visibility: opt.trucks ? "visible" : "none", "icon-image": ["get", "icon"], "icon-allow-overlap": true, "icon-ignore-placement": true,
      "icon-size": ["interpolate", ["linear"], ["zoom"], 6.2, 1, 10, 2] } });
    map.addLayer({ id: "mover", type: "symbol", source: "mover", layout: { "icon-image": "pkg", "icon-allow-overlap": true, "icon-ignore-placement": true, "icon-size": ["interpolate", ["linear"], ["zoom"], 3, 1, 8, 2] } });
    map.addLayer({ id: "sel", type: "circle", source: "sel", paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 9, 10, 22], "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": p.primary, "circle-stroke-width": 2.5 } });
    map.addLayer({ id: "sel-unc", type: "circle", source: "sel", filter: [">", ["get", "unc"], 0.6], paint: {
      "circle-radius": ["interpolate", ["exponential", 2], ["zoom"], 4, ["*", ["get", "unc"], 0.11], 12, ["*", ["get", "unc"], 28]],
      "circle-color": p.dark ? "rgba(59,140,255,0.08)" : "rgba(29,78,216,0.06)", "circle-stroke-color": p.primary, "circle-stroke-width": 1, "circle-stroke-opacity": 0.45 } });
  }

  function repaint() { // theme change: recolour without rebuilding sources
    if (!map || !map.getLayer("l-road")) return;
    const p = P();
    const set = (l, k, v) => { if (map.getLayer(l)) map.setPaintProperty(l, k, v); };
    set("bg", "background-color", p.bg); set("grid", "line-color", p.grid); set("land", "fill-color", p.land); set("coast", "line-color", p.coast);
    set("sat", "raster-saturation", p.dark ? -0.55 : -0.45); set("sat", "raster-brightness-max", p.dark ? 0.62 : 0.92);
    set("relief", "hillshade-shadow-color", p.dark ? "#000" : "#6d6656"); set("relief", "hillshade-highlight-color", p.dark ? "#56606b" : "#fffdf5"); set("relief", "hillshade-accent-color", p.dark ? "#1a1e22" : "#d9d2bf");
    set("l-road", "line-color", ["case", [">", ["get", "act"], 0], p.roadActive, p.road]);
    set("l-rail", "line-color", p.rail); set("l-sea", "line-color", p.sea); set("l-casing", "line-color", p.casing);
    set("l-closed", "line-color", p.closed); set("l-suspected", "line-color", p.suspected); set("hl-line", "line-color", p.hl); set("hl-node", "circle-stroke-color", p.hl);
    set("cargo", "circle-color", ["match", ["get", "mode"], "rail", p.rail, "sea", p.sea, p.cyan]);
    set("n-core", "circle-stroke-color", p.casing); set("veh-dot", "circle-stroke-color", p.casing); 
    set("veh-crit", "circle-stroke-color", p.violet); set("sel", "circle-stroke-color", p.primary);
    set("n-core", "circle-color", ["match", ["get", "state"], "critical", p.bad, "warning", p.warn, "unknown", p.unknown, ["match", ["get", "type"], "Supplier", p.supplier, "CustomerCluster", p.customer, "Port", p.sea, "Factory", p.rail, p.node]]);
    set("n-pulse", "circle-stroke-color", ["match", ["get", "state"], "critical", p.bad, "warning", p.warn, "unknown", p.unknown, p.ok]);
    set("cols", "fill-extrusion-color", ["match", ["get", "state"], "critical", p.bad, "warning", p.warn, "unknown", p.unknown, p.primary]);
    try { map.setSky(skySpec()); } catch { /* older API */ }
    addImages();
    lastVehSig = "";
    legend();
  }

  /* ------------------------------------------------------------ vehicles: smooth interpolation between snapshots */
  const veh = new Map(); let vehTs = 0, vehDur = 1000, lastVehSig = "";
  function updateVehicles(s) {
    const now = performance.now();
    vehDur = Math.min(2500, Math.max(400, now - vehTs)); vehTs = now;
    const sc = stateColors(), seen = new Set();
    for (const v of s.vehicles) {
      seen.add(v.id);
      const st = v.cls === "quarantined" ? "quarantined" : v.age_s > 45 ? "stale" : v.cls;
      const cur = veh.get(v.id);
      const to = [v.lon, v.lat];
      let from = to;
      if (cur) { const k = Math.min(1, (now - cur.t0) / cur.dur); from = [lerp(cur.from[0], cur.to[0], k), lerp(cur.from[1], cur.to[1], k)]; }
      if (Math.hypot(from[0] - to[0], from[1] - to[1]) > 0.5) from = to; // teleports / quarantine snaps never animate
      veh.set(v.id, { from, to, t0: now, dur: vehDur, props: { id: v.id, st, cls: v.cls, speed: v.speed, unc: v.unc_km, load: v.load, sku: v.sku, pr: v.pr,
        col: sc[st], icon: `truck-${st}-${v.heading > 180 && v.heading < 360 ? "l" : "r"}` } });
    }
    for (const k of [...veh.keys()]) if (!seen.has(k)) veh.delete(k);
  }
  function vehFrame(now) {
    const feats = [];
    let sel = null;
    for (const v of veh.values()) {
      const k = REDUCED ? 1 : Math.min(1, (now - v.t0) / v.dur);
      const c = [lerp(v.from[0], v.to[0], k), lerp(v.from[1], v.to[1], k)];
      const f = { type: "Feature", properties: v.props, geometry: { type: "Point", coordinates: c } };
      feats.push(f);
      if (selected && selected.kind === "vehicle" && selected.id === v.props.id) sel = f;
    }
    map.getSource("veh").setData({ type: "FeatureCollection", features: feats });
    if (selected && selected.kind === "vehicle") { map.getSource("sel").setData({ type: "FeatureCollection", features: sel ? [sel] : [] }); if (sel) selectedPos = sel.geometry.coordinates; }
  }

  /* ------------------------------------------------------------ planned flows: cargo particles, ships, trains */
  let flowSet = [], flowMode = "baseline";
  function setFlows(perLink, modeLabel = "baseline") {
    flowMode = modeLabel;
    flowSet = [];
    const entries = Object.entries(perLink || {}).filter(([lid, q]) => LINK[lid] && q > 0.5);
    const max = Math.max(1, ...entries.map(([, q]) => q));
    for (const [lid, q] of entries) {
      const l = LINK[lid];
      const n = l.mode === "road" ? Math.max(1, Math.min(6, Math.round(1 + 5 * Math.sqrt(q / max)))) : Math.max(1, Math.min(3, Math.round(1 + 2 * q / max)));
      for (let i = 0; i < n; i++) flowSet.push({ lid, mode: l.mode, coords: l.coords, phase: i / n + (Math.random() * 0.15), speed: l.mode === "road" ? 0.07 : 0.035 });
    }
    if (flowSet.length > 320) flowSet = flowSet.filter((_, i) => i % Math.ceil(flowSet.length / 320) === 0);
  }
  function flowFrame(now) {
    const t = now / 1000, cargo = [], assets = [];
    for (const f of flowSet) {
      const fr = REDUCED ? f.phase % 1 : (f.phase + t * f.speed) % 1;
      const [x, y, b] = along(f.coords, fr);
      if (f.mode === "road") cargo.push({ type: "Feature", properties: { mode: "road" }, geometry: { type: "Point", coordinates: [x, y] } });
      else assets.push({ type: "Feature", properties: { icon: `${f.mode === "sea" ? "ship" : "train"}-${b > 180 ? "l" : "r"}` }, geometry: { type: "Point", coordinates: [x, y] } });
    }
    map.getSource("cargo").setData({ type: "FeatureCollection", features: cargo });
    map.getSource("assets").setData({ type: "FeatureCollection", features: assets });
  }

  /* ------------------------------------------------------------ network state: links, nodes, ripples, columns */
  let linkStatus = {}, prevClosed = new Set(), ripplePts = [], scenarioOverride = null;
  function applyNetworkState(s) {
    const statuses = scenarioOverride ? scenarioOverride.links : s.links;
    const act = new Set();
    if (!scenarioOverride) for (const v of s.vehicles) if (v.speed > 5 && v.cls === "trusted") { const r = nearestRoad(v.lon, v.lat); if (r) act.add(r); }
    const fc = linkFC();
    fc.features.forEach((f) => { const st = statuses[f.properties.id]; f.properties.status = st ? st.status : "open"; f.properties.act = act.has(f.properties.id) ? 1 : 0; });
    map.getSource("links").setData(fc);
    // restoration: links that just re-opened sweep green
    const closedNow = new Set(Object.entries(statuses).filter(([, v]) => v.status !== "open").map(([k]) => k));
    const reopened = [...prevClosed].filter((k) => !closedNow.has(k) && LINK[k]);
    if (reopened.length && !scenarioOverride) restoreSweep(reopened);
    prevClosed = closedNow;
    linkStatus = statuses;
    // node states
    const ns = scenarioOverride ? { ...s.node_state, ...scenarioOverride.nodes } : s.node_state || {};
    Object.assign(nodeState, ns);
    map.getSource("nodes").setData(nodeFC());
    // ripples: closed link midpoints + incident nodes
    ripplePts = [];
    const pts = new Set();
    Object.entries(statuses).forEach(([lid, st]) => { if (st.status === "open" || !LINK[lid]) return; const c = LINK[lid].coords; const key = `${((c[0][0] + c[1][0]) / 2).toFixed(1)},${((c[0][1] + c[1][1]) / 2).toFixed(1)}`;
      if (!pts.has(key)) { pts.add(key); ripplePts.push([(c[0][0] + c[1][0]) / 2, (c[0][1] + c[1][1]) / 2]); } });
    (scenarioOverride ? scenarioOverride.rippleNodes || [] : (s.incidents || []).flatMap((i) => i.nodes)).forEach((n) => NODE[n] && ripplePts.push([NODE[n].lon, NODE[n].lat]));
    map.getSource("ripples").setData({ type: "FeatureCollection", features: ripplePts.map((c) => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: c } })) });
    // 3D inventory columns (trusted stock, twin belief)
    colStock = {};
    Object.entries(s.warehouses || {}).forEach(([w, x]) => { colStock[w] = Object.values(x.inv).reduce((a, b) => a + (b || 0), 0); });
    if (scenarioOverride && scenarioOverride.stock) Object.assign(colStock, scenarioOverride.stock);
    map.getSource("cols").setData(columnFC());
  }
  let roadIdx = null;
  function nearestRoad(lon, lat) {
    roadIdx ||= NET.links.filter((l) => l.mode === "road").map((l) => ({ id: l.id, a: l.coords[0], b: l.coords[1] }));
    const kx = Math.cos(lat * Math.PI / 180); let best = null, bd = 0.01;
    for (const r of roadIdx) { const ax = (r.a[0] - lon) * kx, ay = r.a[1] - lat, bx = (r.b[0] - lon) * kx, by = r.b[1] - lat, dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy;
      const t = L2 > 0 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / L2)) : 0; const d = Math.hypot(ax + t * dx, ay + t * dy); if (d < bd) { bd = d; best = r.id; } }
    return best;
  }
  let restoreAnim = null;
  function restoreSweep(lids) {
    const feats = lids.map((lid) => ({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: LINK[lid].coords } }));
    map.getSource("restore").setData({ type: "FeatureCollection", features: feats });
    restoreAnim = { t0: performance.now(), dur: 2600 };
  }

  /* ------------------------------------------------------------ alternative routes: sequential draw-in */
  let routes = [], routeAnim = null, recIdx = -1, moverRoute = null;
  /* Link geometry is straight (synthetic network). Alternatives that share endpoints would overlap, so each
     alternative is drawn as a gentle arc with its own bend: purely a display offset, labelled routes stay exact. */
  function curve(coords, k) {
    if (!k) return coords;
    const out = [coords[0]];
    for (let i = 1; i < coords.length; i++) {
      const [x0, y0] = coords[i - 1], [x1, y1] = coords[i], dx = x1 - x0, dy = y1 - y0, L = Math.hypot(dx, dy) || 1;
      const nx = -dy / L, ny = dx / L, bend = k * Math.min(0.9, 0.16 * L);
      const cx = (x0 + x1) / 2 + nx * bend, cy = (y0 + y1) / 2 + ny * bend;
      for (let t = 1; t <= 16; t++) { const u = t / 16, a = (1 - u) * (1 - u), b = 2 * (1 - u) * u, c = u * u; out.push([a * x0 + b * cx + c * x1, a * y0 + b * cy + c * y1]); }
    }
    return out;
  }
  const BEND = [0, 1, -1, 1.8, -1.8];
  const live = () => !!(map && map.getSource && map.getSource("veh"));
  function showRoutes(list, recommendedId, { animate = true, fit = true, focusIdx = null } = {}) {
    if (!live()) { ready.then(() => showRoutes(list, recommendedId, { animate, fit, focusIdx })); return; }
    routes = list.slice(0, 5);
    recIdx = routes.findIndex((r) => r.id === recommendedId);
    for (let i = 0; i < 5; i++) {
      const r = routes[i];
      if (r) r._draw = curve(r.coords, BEND[i] * (list.length > 1 ? 1 : 0));
      map.getSource(`route${i}`).setData(r ? { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: r._draw } } : EMPTY);
      map.setLayoutProperty(`route${i}-glow`, "visibility", i === recIdx ? "visible" : "none");
      map.setPaintProperty(`route${i}`, "line-width", i === recIdx ? ["interpolate", ["linear"], ["zoom"], 3, 5, 8, 9] : ["interpolate", ["linear"], ["zoom"], 3, 2.4, 8, 5]);
      map.setPaintProperty(`route${i}`, "line-opacity", r && r.blocked ? 0.55 : 1);
    }
    routeAnim = { t0: performance.now(), n: routes.length, per: animate === true && !REDUCED ? 650 : 0, recOnly: animate === "rec" && !REDUCED };
    moverRoute = recIdx >= 0 ? routes[recIdx]._draw : null;
    if (fit && routes.length) { const all = routes.flatMap((r) => r.coords); camera.fit(all, { pitch: 38 }); }
    if (focusIdx != null) focusRoute(focusIdx);
  }
  function focusRoute(i) { if (!live()) return; for (let k = 0; k < routes.length; k++) map.setPaintProperty(`route${k}`, "line-opacity", k === i || i == null ? 1 : 0.35); }
  function clearRoutes() { if (!live()) return; routes = []; routeAnim = null; moverRoute = null; recIdx = -1;
    for (let i = 0; i < 5; i++) { map.getSource(`route${i}`).setData(EMPTY); map.setLayoutProperty(`route${i}-glow`, "visibility", "none"); }
    map.getSource("mover").setData(EMPTY); }
  function routeFrame(now) {
    if (!routeAnim) return;
    const { t0, per } = routeAnim;
    let busyDrawing = false;
    if (!routeAnim.done) for (let i = 0; i < routes.length; i++) {
      const p = routeAnim.recOnly ? (i === recIdx ? Math.max(0, Math.min(1, (now - t0) / 1100)) : 1) : per ? Math.max(0, Math.min(1, (now - t0 - i * per) / per)) : 1;
      if (p < 1) busyDrawing = true;
      const col = i === recIdx ? P().violet : ROUTE_COLORS[i];
      const g = p >= 1 ? ["step", ["line-progress"], col, 1.01, col] : ["step", ["line-progress"], col, Math.max(0.0001, p), "rgba(0,0,0,0)"];
      map.setPaintProperty(`route${i}`, "line-gradient", g);
      map.setPaintProperty(`route${i}-glow`, "line-gradient", g);
    }
    if (!busyDrawing) routeAnim.done = true;
    if (routeAnim.done && moverRoute) {
      const fr = REDUCED ? 0.5 : ((now - t0 - routes.length * per) / 7000) % 1;
      const [x, y] = along(moverRoute, Math.max(0, fr));
      map.getSource("mover").setData({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [x, y] } });
    }
    if (routeAnim.done && !moverRoute) routeAnim = null;
  }

  /* ------------------------------------------------------------ highlight (Supply Chain Doctor, cascade focus) */
  function highlight({ nodes = [], links = [] } = {}, fly = true) {
    if (!live()) { ready.then(() => highlight({ nodes, links }, fly)); return; }
    const feats = [...links.filter((l) => LINK[l]).map((l) => ({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: LINK[l].coords } })),
      ...nodes.filter((n) => NODE[n]).map((n) => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [NODE[n].lon, NODE[n].lat] } }))];
    map.getSource("hl").setData({ type: "FeatureCollection", features: feats });
    if (fly && feats.length) camera.fit(feats.flatMap((f) => f.geometry.type === "Point" ? [f.geometry.coordinates] : f.geometry.coordinates), { pitch: 35, maxZoom: 6.5 });
  }
  function clearHighlight() { if (live() && map.getSource("hl")) map.getSource("hl").setData(EMPTY); }

  /* ------------------------------------------------------------ scenario overlay (72-hour timeline) */
  function setScenarioFrame(ov) { scenarioOverride = ov; if (STATE && live()) applyNetworkState(STATE); }
  function clearScenario() { scenarioOverride = null; if (STATE && live()) applyNetworkState(STATE); loadBaselineFlows(); }

  /* ------------------------------------------------------------ camera */
  let selected = null, selectedPos = null, follow = false, lastInteract = 0;
  const LEVELS = [["india", "India"], ["region", "Region"], ["city", "City"], ["facility", "Facility"], ["vehicle", "Vehicle"]];
  const camera = {
    go(level) {
      if (!live()) return;
      follow = false;
      const dur = REDUCED ? 0 : 1700;
      const tgt = selected ? (selected.kind === "vehicle" ? selectedPos : [NODE[selected.id].lon, NODE[selected.id].lat]) : null;
      if (level === "india") return map.flyTo({ center: [80.5, 21.5], zoom: proj === "globe" ? 3.55 : 4.2, pitch: 0, bearing: 0, duration: dur, essential: true });
      if (!tgt) return;
      if (level === "region") map.flyTo({ center: tgt, zoom: 5.6, pitch: 30, bearing: -8, duration: dur, essential: true });
      if (level === "city") map.flyTo({ center: tgt, zoom: 8.2, pitch: 45, bearing: -14, duration: dur, essential: true });
      if (level === "facility") map.flyTo({ center: tgt, zoom: 11.2, pitch: 60, bearing: -20, duration: dur, essential: true });
      if (level === "vehicle") { map.flyTo({ center: tgt, zoom: 10.5, pitch: 55, bearing: 0, duration: dur, essential: true }); follow = selected.kind === "vehicle"; }
    },
    fit(coords, { pitch = 0, maxZoom = 7.5, padding = 70 } = {}) {
      if (!coords.length || !live()) return;
      follow = false;
      const b = bbox(coords);
      map.fitBounds(b, { padding, maxZoom, pitch, duration: REDUCED ? 0 : 1600, essential: true });
    },
  };
  function ladder() {
    const z = map ? map.getZoom() : 3;
    const lvl = follow ? "vehicle" : z >= 10.8 ? "facility" : z >= 7.5 ? "city" : z >= 5 ? "region" : "india";
    const has = !!selected;
    $("#ladder").innerHTML = LEVELS.map(([k, n], i) => `${i ? '<span class="sep">›</span>' : ""}<button data-l="${k}" class="${k === lvl ? "on" : ""}" ${k !== "india" && (!has || (k === "vehicle" && selected.kind !== "vehicle")) ? "disabled" : ""}>${n}</button>`).join("")
      + (selected ? `<span class="sep">·</span><span class="xs mono" style="padding:0 6px;color:var(--text-2)">${esc(selected.id.replace("wh:", ""))}</span>` : "");
  }
  function select(kind, id, { fly = false } = {}) {
    if (!live()) { ready.then(() => select(kind, id, { fly })); return; }
    selected = id ? { kind, id } : null; follow = false;
    if (!selected) { map.getSource("sel").setData(EMPTY); ladder(); return; }
    if (kind === "node") { const n = NODE[id]; map.getSource("sel").setData({ type: "Feature", properties: { unc: 0 }, geometry: { type: "Point", coordinates: [n.lon, n.lat] } }); }
    if (kind === "vehicle") { const v = veh.get(id); selectedPos = v ? v.to : null; }
    ladder();
    if (fly) camera.go(kind === "vehicle" ? "vehicle" : "city");
  }
  function autoFocus(coords) {
    if (!opt.autofocus || !map || performance.now() - lastInteract < 8000 || !["command", "twin", "incident"].includes(PAGE)) return;
    camera.fit(coords, { pitch: 42, maxZoom: 7 });
  }

  /* ------------------------------------------------------------ main loop */
  let lastData = 0, lastPaint = 0, lastDash = 0, dashStep = 0, raf = null;
  const DASH = [[0, 2, 2], [0.5, 2, 1.5], [1, 2, 1], [1.5, 2, 0.5], [2, 2, 0], [0, 0.5, 2, 1.5], [0, 1, 2, 1], [0, 1.5, 2, 0.5]];
  function loop(now) {
    raf = requestAnimationFrame(loop);
    if (!map || !map.getSource("veh") || document.hidden || document.body.classList.contains("story-mode")) return;
    const dataEvery = REDUCED ? 1000 : 50;
    if (now - lastData >= dataEvery) {
      lastData = now;
      if (opt.trucks) vehFrame(now);
      if (opt.flows || opt.assets) flowFrame(now);
      if (follow && selectedPos) map.easeTo({ center: selectedPos, duration: 50, easing: (t) => t });
    }
    routeFrame(now);
    if (REDUCED) return;
    if (now - lastPaint >= 66) {
      lastPaint = now;
      const t = now / 1000;
      const ph = (sp) => (t * sp) % 1;
      const rC = 10 + 14 * ph(0.9), rW = 9 + 10 * ph(0.6), rH = 8 + 6 * ph(0.35);
      if (ripplePts.length) {
        const a = ph(0.5), b = (a + 0.5) % 1;
        map.setPaintProperty("ripple", "circle-radius", 6 + 44 * a); map.setPaintProperty("ripple", "circle-stroke-opacity", 0.9 * (1 - a));
        map.setPaintProperty("ripple2", "circle-radius", 6 + 44 * b); map.setPaintProperty("ripple2", "circle-stroke-opacity", 0.7 * (1 - b));
      }
      if (restoreAnim) {
        const k = Math.min(1, (now - restoreAnim.t0) / restoreAnim.dur);
        map.setPaintProperty("restore", "line-gradient", ["step", ["line-progress"], P().ok, Math.max(0.0001, Math.min(1, k * 1.4)), "rgba(0,0,0,0)"]);
        map.setPaintProperty("restore", "line-opacity", k < 0.7 ? 1 : 1 - (k - 0.7) / 0.3);
        if (k >= 1) { restoreAnim = null; map.getSource("restore").setData(EMPTY); }
      }
    }
    if (now - lastDash >= 90 && Object.keys(linkStatus).length) {
      lastDash = now; dashStep = (dashStep + 1) % DASH.length;
      map.setPaintProperty("l-closed", "line-dasharray", DASH[dashStep]);
    }
  }

  /* ------------------------------------------------------------ hub labels (HTML: no glyph server needed) */
  const labels = [];
  function makeLabels() {
    NET.nodes.forEach((n) => {
      const el = document.createElement("div"); el.className = "maplabel"; el.textContent = n.id;
      const m = new maplibregl.Marker({ element: el, anchor: "left" }).setLngLat([n.lon, n.lat]).addTo(map);
      labels.push({ m, el, major: ["Warehouse", "Port", "Factory"].includes(n.type) });
    });
    const vis = () => { const z = map.getZoom(); labels.forEach((l) => { l.el.style.display = opt.labels && (l.major ? z >= 3.3 : z >= 6.8) ? "" : "none"; l.el.classList.toggle("chart", basemap === "chart" || satFailed); }); };
    map.on("zoom", vis); vis();
    return vis;
  }
  let refreshLabels = () => {};

  /* ------------------------------------------------------------ controls, legend, chips */
  function controls() {
    $("#mapctl").innerHTML = `<button data-a="in" title="Zoom in" aria-label="Zoom in">+</button><button data-a="out" title="Zoom out" aria-label="Zoom out">−</button>
      <button data-a="home" title="Back to India" aria-label="Back to India">⌂</button><hr><button data-a="tilt" title="Tilt 3D view" aria-label="Tilt">3D</button>
      <button data-a="layers" title="Layers" aria-label="Layers">${ico("layers")}</button>`;
    $("#mapctl").addEventListener("click", (e) => { const a = e.target.closest("button")?.dataset.a; if (!a) return;
      if (a === "in") map.zoomIn(); if (a === "out") map.zoomOut(); if (a === "home") camera.go("india");
      if (a === "tilt") map.easeTo({ pitch: map.getPitch() > 10 ? 0 : 55, bearing: map.getPitch() > 10 ? 0 : -18, duration: 900 });
      if (a === "layers") { $("#layersBox").hidden = !$("#layersBox").hidden; e.target.classList.toggle("on", !$("#layersBox").hidden); } });
    const tg = (k, label) => `<label class="toggle"><input type="checkbox" data-k="${k}" ${opt[k] ? "checked" : ""}><i></i>${label}</label>`;
    $("#layersBox").innerHTML = `<h4>Basemap</h4><span class="seg" id="bmSeg"><button data-v="satellite" class="${basemap === "satellite" ? "on" : ""}">Satellite</button><button data-v="chart" class="${basemap === "chart" ? "on" : ""}">Chart</button></span>
      <span class="seg" id="projSeg"><button data-v="globe" class="${proj === "globe" ? "on" : ""}">Globe</button><button data-v="mercator" class="${proj === "mercator" ? "on" : ""}">Flat</button></span>
      <h4>Layers</h4>${tg("trucks", "Trucks (telemetry)")}${tg("flows", "Cargo flow particles")}${tg("assets", "Ships &amp; trains (planned)")}${tg("columns", "3D inventory columns")}${tg("labels", "Facility labels")}${tg("relief", "Terrain relief")}${tg("terrain", "3D terrain (tilt to see it)")}${tg("weather", "Real weather overlay")}
      <h4>Camera</h4>${tg("autofocus", "Auto-focus on disruptions")}<h4>Offline</h4><div id="tilePack"></div>`;
    tilePack();
    $$("#layersBox input[type=checkbox]").forEach((c) => c.addEventListener("change", () => { opt[c.dataset.k] = c.checked; save(); applyOpts(); }));
    $$("#bmSeg button").forEach((b) => b.addEventListener("click", () => { basemap = b.dataset.v; save(); $$("#bmSeg button").forEach((x) => x.classList.toggle("on", x === b)); applyOpts(); chips(); }));
    $$("#projSeg button").forEach((b) => b.addEventListener("click", () => { proj = b.dataset.v; save(); $$("#projSeg button").forEach((x) => x.classList.toggle("on", x === b)); map.setProjection({ type: proj }); }));
  }
  function applyOpts() {
    const vis = (l, on) => map.getLayer(l) && map.setLayoutProperty(l, "visibility", on ? "visible" : "none");
    ["veh", "veh-dot", "veh-glow", "veh-crit"].forEach((l) => vis(l, opt.trucks));
    vis("cargo", opt.flows); ["wx-halo", "wx-ring"].forEach((l) => vis(l, opt.weather)); applyTerrain(); vis("assets", opt.assets); vis("cols", opt.columns); vis("relief", opt.relief); vis("sat", basemap === "satellite");
    if (map.getLayer("relief")) map.setPaintProperty("relief", "hillshade-exaggeration", basemap === "satellite" ? 0.25 : 0.45);
    refreshLabels();
    if (!opt.trucks) map.getSource("veh").setData(EMPTY);
  }
  /* 3D terrain: real elevation (AWS terrain tiles via the local cache) under the satellite imagery. Only switched on
     once elevation tiles have actually loaded, so an offline map never tilts over a void. */
  let terrainOk = false;
  function applyTerrain() {
    if (!map || !map.getSource("dem")) return;
    try {
      if (opt.terrain && terrainOk && basemap === "satellite") map.setTerrain({ source: "dem", exaggeration: proj === "globe" ? 1.6 : 1.8 });
      else map.setTerrain(null);
    } catch (err) { console.warn("terrain", err); }
  }
  let wxCells = [];
  function setWeather(cells) {
    wxCells = cells || [];
    const src = map && map.getSource("wx"); if (!src) return;
    src.setData({ type: "FeatureCollection", features: wxCells.filter((c) => c.sev >= 0.25).map((c) => ({ type: "Feature", properties: { id: c.id, sev: c.sev, level: c.level, text: c.text || "", rain: c.precip_mm_h, gust: c.gust_kmh },
      geometry: { type: "Point", coordinates: [c.lon, c.lat] } })) });
    chips();
  }
  async function tilePack() {
    const box = $("#tilePack"); if (!box) return;
    let st; try { st = await api("/api/tiles/status"); } catch { return; }
    const j = st.job;
    box.innerHTML = `<div class="xs muted">${st.cached_tiles.toLocaleString("en-IN")} tiles cached (${st.cached_mb} MB)${j.running ? ` · downloading ${j.done}/${j.total}` : j.total ? ` · last pack ${j.done - j.failed}/${j.total} ok` : ""}</div>
      <button class="btn ghost sm" id="tileGo" ${j.running ? "disabled" : ""}>${ico("download")} Save offline imagery pack</button>`;
    const go = $("#tileGo"); if (go) go.onclick = async () => { await post("/api/tiles/prewarm", {}); toast("Downloading satellite + terrain tiles for India and every facility (needs internet once)", "ok"); tilePack(); };
    if (j.running) setTimeout(tilePack, 2500);
  }
  function legend() {
    const sc = stateColors(), p = P();
    $("#legend").innerHTML = `<h4>Trust</h4><div class="lg"><i class="d" style="background:${sc.trusted}"></i>Trusted</div>
      <div class="lg"><i class="d" style="background:${sc.estimated}"></i>Uncertain</div><div class="lg"><i class="d" style="background:${sc.quarantined}"></i>Suspicious</div>
      <h4>Network</h4><div class="lg"><i class="l" style="border-color:${p.roadActive}"></i>Road</div><div class="lg"><i class="l" style="border-top-style:dashed;border-color:${p.rail}"></i>Rail</div>
      <div class="lg"><i class="l" style="border-top-style:dotted;border-color:${p.sea}"></i>Sea lane</div><div class="lg"><i class="l" style="border-top:3px dashed ${p.closed}"></i>Closed / blocked</div>`;
  }
  function chips() {
    const mc = (kind, label) => `<span class="mc ${kind}"><i></i>${esc(label)}</span>`;
    const w = typeof WX !== "undefined" && WX.meta ? WX.meta : null;
    $("#mapChips").innerHTML = (basemap === "satellite" ? (satFailed ? mc("mock", "Imagery offline") : mc("static", "Static imagery")) : mc("static", "Chart basemap"))
      + (w ? mc(w.status === "LIVE" ? "live" : w.status === "STALE" ? "mock" : w.status === "UNAVAILABLE" ? "bad" : "replay", `Weather: ${w.status.toLowerCase()}`) : "")
      + mc("sim", "Trucks: simulated") + mc("mock", "Alerts: mock") + (flowMode === "scenario" ? mc("replay", "Forecast overlay") : "");
  }

  /* ------------------------------------------------------------ interaction */
  function interactions() {
    const pop = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12, maxWidth: "280px" });
    const sc = stateColors();
    const vehLayers = ["veh", "veh-dot"];
    vehLayers.forEach((ly) => {
      map.on("mousemove", ly, (e) => { const q = e.features[0].properties; map.getCanvas().style.cursor = "pointer";
        pop.setLngLat(e.features[0].geometry.coordinates).setHTML(`<b class="mono">${esc(q.id)}</b> <span class="tag ${q.cls}">${CLS_LABEL[q.cls] || q.cls}</span><br><span class="muted xs">${q.speed} km/h${+q.load ? ` · ${q.load} pallets ${esc(q.sku)}` : " · empty"}${+q.pr === 1 ? " · <b style='color:var(--violet)'>critical cargo</b>" : ""}</span>`).addTo(map); });
      map.on("mouseleave", ly, () => { pop.remove(); map.getCanvas().style.cursor = ""; });
      map.on("click", ly, (e) => { const id = e.features[0].properties.id; select("vehicle", id); emit("select", { kind: "vehicle", id }); });
    });
    ["n-core", "n-icon"].forEach((ly) => {
      map.on("mousemove", ly, (e) => { const q = e.features[0].properties; map.getCanvas().style.cursor = "pointer";
        const w = STATE && STATE.warehouses[q.id]; const stock = w ? Object.values(w.inv).reduce((a, b) => a + (b || 0), 0) : null;
        pop.setLngLat(e.features[0].geometry.coordinates).setHTML(`<b class="mono">${esc(q.id)}</b> <span class="tag ${q.state}">${esc(q.state)}</span><br>${esc(q.name)}${stock != null ? `<br><span class="muted xs">${stock.toLocaleString("en-IN")} units trusted stock</span>` : ""}`).addTo(map); });
      map.on("mouseleave", ly, () => { pop.remove(); map.getCanvas().style.cursor = ""; });
      map.on("click", ly, (e) => { const id = e.features[0].properties.id; select("node", id); emit("select", { kind: "node", id }); });
    });
    ["l-road", "l-rail", "l-sea", "l-closed", "l-suspected"].forEach((ly) => {
      map.on("mousemove", ly, (e) => { const q = e.features[0].properties;
        pop.setLngLat(e.lngLat).setHTML(`<b class="mono">${esc(q.id)}</b> ${esc(q.from)} → ${esc(q.to)}<br><span class="muted xs">${esc(q.corridor)} · ${esc(q.mode)} · ${q.status === "open" ? (q.act ? "trucks on it" : "open") : `<b style="color:var(--red)">${esc(q.status.replace("_", " "))}</b>`}</span>`).addTo(map); });
      map.on("mouseleave", ly, () => pop.remove());
    });
    for (let i = 0; i < 5; i++) {
      map.on("click", `route${i}`, () => emit("routeclick", i));
      map.on("mouseenter", `route${i}`, () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", `route${i}`, () => { map.getCanvas().style.cursor = ""; });
    }
    ["dragstart", "zoomstart", "rotatestart", "pitchstart"].forEach((ev) => map.on(ev, (e) => { if (e.originalEvent) { lastInteract = performance.now(); if (ev === "dragstart") follow = false; } }));
    map.on("zoomend", ladder); map.on("moveend", ladder);
    $("#ladder").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b && !b.disabled) camera.go(b.dataset.l); });
  }

  /* ------------------------------------------------------------ baseline flows */
  async function loadBaselineFlows() {
    try { const f = await api("/api/flows/baseline"); if (!scenarioOverride) { setFlows(f.per_link_per_day, "baseline"); chips(); } } catch { /* optional */ }
  }

  /* ------------------------------------------------------------ init */
  async function init() {
    await loadLand();
    map = new maplibregl.Map({ container: "map", style: style(), center: [80.5, 21.5], zoom: proj === "globe" ? 1.6 : 3.6, pitch: 0, minZoom: 1, maxZoom: 14,
      attributionControl: { compact: true }, fadeDuration: 150 });
    // Tile failures (offline, firewalled imagery or relief) are non-fatal: the vendored coastline stays underneath.
    map.on("error", (e) => {
      if (e && e.sourceId === "sat" && !satOk && !satFailed) { satFailed = true; chips(); refreshLabels(); }
      if (e && e.sourceId) return;
      console.warn(e && e.error);
    });
    map.on("sourcedata", (e) => { if (e.sourceId === "dem" && e.tile && e.tile.state === "loaded" && !terrainOk) { terrainOk = true; applyTerrain(); chips(); }
      if (e.sourceId === "dem") return; if (e.sourceId === "sat" && e.tile && e.tile.state === "loaded" && !satOk) { satOk = true; satFailed = false; chips(); refreshLabels(); } });
    // "style.load", not "load": "load" waits for every basemap tile, which never settles when imagery is
    // blocked or offline. The twin must work without the internet basemap.
    map.once("style.load", () => {
      for (const [name, fn] of [["images", addImages], ["layers", addLayers], ["controls", controls], ["legend", legend], ["chips", chips], ["interactions", interactions],
        ["labels", () => { refreshLabels = makeLabels(); }], ["options", applyOpts], ["ladder", ladder]]) {
        try { fn(); } catch (err) { console.error(`map init step "${name}" failed`, err); }
      }
      if (!REDUCED) setTimeout(() => map.flyTo({ center: [80.5, 21.5], zoom: proj === "globe" ? 3.55 : 4.2, duration: 3200, essential: true }), 300);
      else map.jumpTo({ center: [80.5, 21.5], zoom: proj === "globe" ? 3.55 : 4.2 });
      loadBaselineFlows(); setInterval(() => { if (!scenarioOverride) loadBaselineFlows(); }, 60000);
      raf = requestAnimationFrame(loop);
      readyResolve(map);
      if (STATE) onState({ s: STATE, prev: null });
    });
    on("theme", () => repaint());
    on("resize", () => map && map.resize());
    on("page", (pg) => { if (pg !== "twin") follow = false; });
    on("state", onState);
    new ResizeObserver(() => map && map.resize()).observe($("#mapwrap"));
  }
  const seenInc = new Set(), seenClosed = new Set();
  function onState({ s }) {
    if (!map || !map.getSource("veh")) return;
    updateVehicles(s);
    applyNetworkState(s);
    $("#mapBanner").hidden = s.kpis.mode !== "BLIND";
    $("#mapBanner").textContent = "BLIND MODE · positions estimated from last trusted state";
    // camera: new disruption → gently move towards it (only if the user is not driving the map)
    for (const i of s.incidents || []) if (!seenInc.has(i.id)) { seenInc.add(i.id);
      const coords = [...i.links.filter((l) => LINK[l]).flatMap((l) => LINK[l].coords), ...i.nodes.filter((n) => NODE[n]).map((n) => [NODE[n].lon, NODE[n].lat])];
      if (coords.length) autoFocus(coords); }
    for (const [lid, st] of Object.entries(s.links || {})) if (st.status !== "open" && !seenClosed.has(lid) && LINK[lid]) { seenClosed.add(lid);
      if (!(s.incidents || []).some((i) => i.links.includes(lid))) autoFocus(LINK[lid].coords); }
  }

  return { init, ready, get map() { return map; }, showRoutes, clearRoutes, focusRoute, highlight, clearHighlight, setFlows, setScenarioFrame, clearScenario,
    select, camera, loadBaselineFlows, chips, setWeather, along, get selected() { return selected; } };
})();
