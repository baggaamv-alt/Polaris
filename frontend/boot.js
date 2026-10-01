/* Boot: load the network, start the map, wire pages, open the live stream, route. */
"use strict";
(async function boot() {
  $$("[data-ico]").forEach((el) => { el.outerHTML = ico(el.dataset.ico); });
  $("#bootTruck").innerHTML = pxImg("truck", { scale: 3, c: "#3b8cff" });
  $("#logo").innerHTML = pxImg("truck", { scale: 1, c: "#ffffff" });
  $("#themeBtn").innerHTML = theme() === "dark" ? SUN : MOON;
  $("#themeBtn").addEventListener("click", () => setTheme(theme() === "dark" ? "light" : "dark"));
  for (;;) {
    try { NET = await api("/api/network"); break; }
    catch (e) { $("#bootMsg").textContent = `Waiting for the twin API (${e.message})…`; await sleep(2000); }
  }
  NET.nodes.forEach((n) => (NODE[n.id] = n));
  NET.links.forEach((l) => (LINK[l.id] = l));
  initClock();
  $("#bootMsg").textContent = "Loading the 3D digital twin…";
  await TWIN.init();
  Object.values(PAGES).forEach((p) => { try { p.init && p.init(); } catch (e) { console.error(e); } });
  connect();
  WX.start();
  route();
  let done = false;
  const finish = () => { if (done) return; done = true; $("#boot").classList.add("done"); };
  on("state", finish); setTimeout(finish, 2500);
})();
