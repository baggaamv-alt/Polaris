/* VIGILAX / PNT1 pixel-art system (2.3).
 * One illustration language for logistics entities only: truck, plane, ship, train, container, package,
 * warehouse, port, factory, supplier, location pin, disruption, driver.
 * Construction rules shared by every sprite: a fixed pixel grid, a single 1-px ink outline generated from the fill
 * shapes, 3-tone flat shading lit from the top-left (highlight / base / shade), no dithering, a 20-colour palette
 * that lives in CSS (--px-*) so sprites follow the light and dark themes. The sprites are the product's signature;
 * they are never used as UI icons (see icons.js) and never for typography.
 */
const PX_PALETTE = {
  k: "var(--px-k)", w: "var(--px-w)", h: "#d7e1ea", s: "var(--px-s)", x: "#5f768c", n: "var(--px-n)", a: "#c9973f", q: "#9b6f2c",
  b: "#b08558", B: "#7d5a3a", y: "var(--px-y)", d: "var(--px-d)", g: "var(--px-g)", r: "var(--px-r)", v: "var(--px-v)",
  e: "var(--px-e)", l: "var(--px-l)", o: "var(--px-o)",
};
const PX_CLASS = { k: "k", w: "w", h: "h", s: "s", x: "x", n: "n", a: "a", q: "q", b: "b", B: "B2", y: "y", d: "d", g: "g", r: "r", v: "v", e: "e", l: "l", o: "o" };
const PX_STATE = { trusted: "#5d8257", estimated: "#b98a45", quarantined: "#a9483b", stale: "#8f8c84", sim: "#4d7590" };

const PX_SPRITES = {
  truck: [
    "..........................",
    "...kkkkkkkkkkkk...........",
    "..khhhhhhhhhhhhk..........",
    "..kwwwwwwwwwwwsk.kkkkk....",
    "..kwwnnnnnnnnwskkccccck...",
    "..kwwnnnnnnnnwskchhhhck...",
    "..kwwnnnnnnnnwskchhhhck...",
    "..kwwwwwwwwwwwskccccccck..",
    "..kwwwwwwwwwwwskccccccck..",
    "..kxxxxxxxxxxxxkccccccak..",
    ".kddddddddddddddddddddddk.",
    "..kkdddkkkkkkdddkkkdddkk..",
    "..kdyyydk..kdyyydkdyyydk..",
    "...kdddk....kdddk.kdddk...",
    "....kkk......kkk...kkk....",
  ],
  plane: [
    "..........................",
    "...kk.....................",
    "..knnk....................",
    "..knnnk......kkkk.........",
    "..knnnnkkkkkksssskkkk.....",
    "...knnnnhhhhhhhhhhhhhkk...",
    "..kwwwwwwwwwwwwwwwwwwwhkk.",
    ".kwwwwwwwwwwwwwwwwwwwwwwhk",
    ".kwnnnnnnnnnnnnnnnnnwwweek",
    "..kwwwwwwwwwwwwwwwwwwwwek.",
    "...kxxxxxxxxxxxxxxxxxxkk..",
    "....kkkkksssssskkkkkkk....",
    ".......ksssssxxxk.........",
    "......ksxxxxxxkk..........",
    ".......kkkkkkk............",
  ],
  ship: [
    "..........................",
    "...........kkkk...........",
    ".........kksssskkk........",
    "...kkkk.keeeekaaaakkkkk...",
    "..krrrrkkeeeekaaaakwwwwk..",
    "..krrrrkkeeeekaaaakwhhwk..",
    "..kaaaakkrrrrkeeeekwwwwk..",
    "..kaaaakkrrrrkeeeekwwwwk..",
    ".knnnnnnnnnnnnnnnnnnnnnnk.",
    ".knnnnnnnnnnnnnnnnnnnnnnk.",
    "..knnnnnnnnnnnnnnnnnnnnk..",
    "...kxxxxxxxxxxxxxxxxxxk...",
    "....kkkkkkkkkkkkkkkkkk....",
  ],
  train: [
    "..........................",
    "..kkkkkkkkkkk.kkkkkkkk....",
    ".kbbbbbbbbbbbknnnnnnnnk...",
    ".kbbbbbbbbbbbknhhnhhnnk...",
    ".kBBBBBBBBBBBknhhnhhnnnk..",
    ".kbbbbbbbbbbbknnnnnnnnnnk.",
    ".kbbbbbbbbbbbknnnnnnnnnak.",
    ".kBBBBBBBBBBBknnnnnnnnnnk.",
    ".kddddddddddddddddddddddk.",
    "..kdydkkdydkkdydkdydkdydk.",
    "...kdk..kdk..kdk.kdk.kdk..",
    "....k....k....k...k...k...",
  ],
  container: [
    "..........................",
    "..kkkkkkkkkkkkkkkkkkkkkk..",
    ".kaaaaaaaaaaaaaaaaaaaaaak.",
    ".kaqaqaqaqaqaqaqaqaqaqaak.",
    ".kaqaqaqaqaqaqaqaqaqaqaak.",
    ".kaqaqaqaqaqaqaqaqaqaqaak.",
    ".kaqaqaqaqaqaqaqaqaqaqaak.",
    ".kaqaqaqaqaqaqaqaqaqaqaak.",
    ".kqqqqqqqqqqqqqqqqqqqqqqk.",
    "..kkkkkkkkkkkkkkkkkkkkkk..",
  ],
  package: [
    "..................",
    "...kkkkkkkkkkk....",
    "..kbbbbwwbbbbbk...",
    ".kbbbbbwwbbbbbbk..",
    ".kBBBBBBBBBBBBBk..",
    ".kbbbbbwwbbbbbbk..",
    ".kbbbbbwwbbbbbbk..",
    ".kbbbbbwwbbbbbbk..",
    ".kBBBBBBBBBBBBBk..",
    "..kkkkkkkkkkkkk...",
  ],
  warehouse: [
    "..........................",
    "..........kkkkkk..........",
    ".......kkknnnnnnkkk.......",
    ".....kknnnnnnnnnnnnkk.....",
    "...kknnnnnnnnnnnnnnnnkk...",
    "..knnnnnnnnnnnnnnnnnnnnk..",
    ".kxxxxxxxxxxxxxxxxxxxxxxk.",
    ".kwwwwwwwwwwwwwwwwwwwwwwk.",
    ".kwwwwwaaaaaaaaaaawwwwwwk.",
    ".kwsssswwwwwwwwwwwsssswwwk",
    ".kwshhswwhhhhhhhwwshhswwwk",
    ".kwsssswwxxxxxxxwwsssswwwk",
    ".kwshhswwxxxxxxxwwshhswwwk",
    ".kwsssswwxxxxxxxwwsssswwwk",
    "..kkkkkkkkkkkkkkkkkkkkkkk.",
  ],
  port: [
    "..........................",
    "..kkkkkkkkkkkkkkk.........",
    ".kaaaaaaaaaaaaaaakk.......",
    ".kaqkkkkkkkkkkkkkaqk......",
    ".kaqk.......k...kaqk......",
    ".kaqk......kdk..kaqk......",
    ".kaqk......kdkk.kaqk......",
    ".kaqk.....keeeekkaqk......",
    ".kaqk.....keeeekkaqk......",
    ".kaqkkkkkkkeeeekkaqkkkkkk.",
    "kyyyyyyyyyyyyyyyyyyyyyyyyk",
    "kyyyyyyyyyyyyyyyyyyyyyyyyk",
    "kssssssssssssssssssssssssk",
    ".kkkkkkkkkkkkkkkkkkkkkkkk.",
  ],
  factory: [
    "..........................",
    "..........kk..............",
    ".........kddk.............",
    ".........kddk.............",
    "...k...k.kyyk.k...k.......",
    "..knk.knk.kyyknk.knk......",
    "..knnkknnkkyyknnkknnk.....",
    "..knnnknnnkkkknnnknnnk....",
    "..knnnnnnnnnnnnnnnnnnnk...",
    "..kwwwwwwwwwwwwwwwwwwwk...",
    "..kwhhwwhhwwhhwwhhwwwwk...",
    "..kwwwwwwwwwwwwwwwwwwwk...",
    "..kwwwwwwwwwaaaaawwwwwk...",
    "..kwwwwwwwwwaaaaawwwwwk...",
    "...kkkkkkkkkkkkkkkkkkk....",
  ],
  supplier: [
    "..........................",
    ".....kkkk.................",
    "....khhhhk................",
    "...kssssssk...............",
    "..khsssssxxk.kkkkkkkkkk...",
    "..khsssssxxkknnnnnnnnnnk..",
    "..khsssssxxknnnnnnnnnnnnk.",
    "..ksssssxxxkkwwwwwwwwwwk..",
    "..ksssssxxxkkwwhhwwaaawwk.",
    "..ksssssxxxkkwwhhwwaaawwk.",
    "..ksssssxxxkkwwwwwwaaawwk.",
    "...kkkkkkkk..kkkkkkkkkkk..",
  ],
  pin: [
    "......kkkkkk......",
    ".....kcccccck.....",
    "....kcccccccck....",
    "...kcccccccccck...",
    "...kccccwwcccck...",
    "...kccccwwcccck...",
    "...kcccccccccck...",
    "....kcccccccck....",
    ".....kcccccck.....",
    "......kcccck......",
    ".......kcck.......",
    "........kk........",
  ],
  warning: [
    "........kk........",
    ".......kaak.......",
    "......kaaaak......",
    "......kaaaak......",
    ".....kaaaaaak.....",
    ".....kaakkaak.....",
    "....kaaakkaaak....",
    "....kaaakkaaak....",
    "...kaaaaaaaaaak...",
    "...kaaaakkaaaak...",
    "..kaaaaaaaaaaaak..",
    "..kaaaaaaaaaaaak..",
    "...kkkkkkkkkkkk...",
  ],
  driver: [
    ".......kkkk.......",
    "......knnnnk......",
    ".....knnnnnnk.....",
    ".....kooooook.....",
    ".....koowowok.....",
    ".....kooooook.....",
    ".....kkooookk.....",
    "....knnnnnnnnk....",
    "...knnnnnnnnnnk...",
    "...knnhnnnnhnnk...",
    "...koonnnnnnook...",
    "....knnnnnnnnk....",
    "....kddkkkkddk....",
    "....kddk..kddk....",
    ".....kk....kk.....",
  ],
};

/* Non-entity glyphs that older code asked for by sprite name are drawn with the single UI icon set instead. */
const PX_AS_ICON = { robot: "spark", headset: "headset", shield: "shield", gear: "gear", check: "check", clock: "clock", radar: "radar", bolt: "bolt", stetho: "pulse", flag: "flag" };

function pxSize(name) { const r = PX_SPRITES[name]; return [Math.max(...r.map((x) => x.length)), r.length]; }
/** Inline SVG (theme-aware through CSS variables). opts: {scale, c (accent colour for 'c' pixels), flip}. */
function pxImg(name, opts = {}, cls = "px") {
  if (PX_AS_ICON[name]) return ico(PX_AS_ICON[name], Math.max(14, (opts.scale || 2) * 9));
  const rows = PX_SPRITES[name]; if (!rows) return "";
  const scale = opts.scale || 2, [W, H] = pxSize(name);
  const byCol = {};
  rows.forEach((row, y) => {
    let x = 0;
    while (x < row.length) {
      const ch = row[x]; if (ch === ".") { x++; continue; }
      let n = 1; while (row[x + n] === ch) n++;
      (byCol[ch] = byCol[ch] || []).push(`M${x} ${y}h${n}v1h-${n}z`); x += n;
    }
  });
  const paths = Object.entries(byCol).map(([ch, d]) => ch === "c" ? `<path d="${d.join("")}" style="fill:${opts.c || "var(--px-n)"}"/>` : `<path class="${PX_CLASS[ch]}" d="${d.join("")}"/>`).join("");
  return `<svg class="${cls}" viewBox="0 0 ${W} ${H}" width="${W * scale}" height="${H * scale}" aria-hidden="true" focusable="false">${opts.flip ? `<g transform="translate(${W} 0) scale(-1 1)">${paths}</g>` : paths}</svg>`;
}
/* canvas / data-URL versions (MapLibre icons, SVG <image>): resolve the CSS palette for the current theme */
const _pxCache = new Map();
function pxResolve(v) {
  const m = /^var\((--[\w-]+)\)$/.exec(v || ""); if (!m) return v;
  return getComputedStyle(document.documentElement).getPropertyValue(m[1]).trim() || "#888";
}
function pxCanvas(name, opts = {}) {
  if (PX_AS_ICON[name]) name = "package";
  const rows = PX_SPRITES[name], scale = opts.scale || 2, [W, H] = pxSize(name);
  const cv = document.createElement("canvas"); cv.width = W * scale; cv.height = H * scale;
  const ctx = cv.getContext("2d");
  rows.forEach((row, y) => { for (let x = 0; x < row.length; x++) {
    const ch = row[x]; if (ch === ".") continue;
    const col = ch === "c" ? pxResolve(opts.c || "var(--px-n)") : pxResolve(PX_PALETTE[ch]); if (!col) continue;
    ctx.fillStyle = col; ctx.fillRect((opts.flip ? W - 1 - x : x) * scale, y * scale, scale, scale); } });
  return cv;
}
function px(name, opts = {}) {
  const th = document.documentElement.dataset.theme;
  const key = `${th}|${name}|${opts.scale || 2}|${opts.c || ""}|${opts.flip ? 1 : 0}`;
  if (!_pxCache.has(key)) _pxCache.set(key, pxCanvas(name, opts).toDataURL());
  return _pxCache.get(key);
}
