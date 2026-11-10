// Self-check of the app's data viewer (app.js "data viewer"), run headless in Node like 04_synthetic_data/twin_dataset.js.
// 1 Data file: the generated 6-month .csv.gz → one row per minute, stage minutes = summary.json.
// 2 Data file: one plant logger day file (1 Hz, tab, decimal comma) → ≤ 1440 rows, stack T from the TCs, stages by the twin rules.
// Run: node 05_twin_2d/tools/feed_check.js [logger day file, default 02_data/common/20260330.txt]
const fs = require("fs"),
  path = require("path"),
  vm = require("vm");
const TWIN = path.join(__dirname, ".."),
  ROOT = path.join(TWIN, "..");
const stub = new Proxy(function () {}, {
  get: (t, k) =>
    k === Symbol.toPrimitive ? () => 0 : k === "length" ? 0 : stub,
  apply: () => stub,
  construct: () => stub,
  set: () => true,
});
const ctx = {
  window: {},
  document: stub,
  performance: { now: () => 0 },
  requestAnimationFrame: () => 0,
  getComputedStyle: () => stub,
  localStorage: stub,
  setTimeout,
  console,
  Float32Array,
  Uint8Array,
  Math,
  Map,
  Set,
  Object,
  JSON,
  Number,
  String,
  Array,
  Date,
  isFinite,
  isNaN,
  TextDecoder,
  DecompressionStream,
  Error,
};
ctx.window = ctx;
ctx.addEventListener = () => {};
ctx.innerHeight = 800;
ctx.devicePixelRatio = 1;
vm.createContext(ctx);
for (const f of ["data/sensors.js", "data/bends.js"])
  vm.runInContext(fs.readFileSync(path.join(TWIN, f), "utf8"), ctx);
const src = fs.readFileSync(path.join(TWIN, "app.js"), "utf8"),
  // whitespace-tolerant so prettier line breaks in app.js do not break the hook
  END_LINE =
    /select\("stack"\);\s*render\(\);\s*requestAnimationFrame\(loop\);/;
if (!END_LINE.test(src))
  throw new Error("app.js end line changed: update feed_check.js");
vm.runInContext(
  src.replace(
    END_LINE,
    "window.__t={S,FEED,IDX,rowParser,readFile,enterFeed,leaveFeed,show};",
  ),
  ctx,
);
const { S, FEED, IDX, rowParser, readFile, enterFeed, leaveFeed, show } =
  ctx.__t;
const assert = (c, m) => {
  if (!c) throw new Error("check failed: " + m);
  console.log("ok  " + m);
};
const blob = async (p) => {
  const b = await fs.openAsBlob(p);
  return {
    name: path.basename(p),
    stream: () => b.stream(),
    size: b.size,
    slice: (a, z) => b.slice(a, z),
  };
};
async function fileRows(p) {
  enterFeed("file");
  const parse = rowParser(),
    rows = FEED.rows;
  await readFile(await blob(p), (l) => {
    const r = parse(l);
    if (r) rows.push(r);
  });
  return rows;
}
const count = (rows) =>
  rows.reduce((m, r) => ((m[r.st] = (m[r.st] || 0) + 1), m), {});

(async () => {
  // 1 generated 6-month data
  const gen = path.join(
      ROOT,
      "04_synthetic_data/datasets/twin_181d_85pct_4pl_1cs_4rp4h/sofc_twin_dataset.csv.gz",
    ),
    sum = JSON.parse(
      fs.readFileSync(path.join(path.dirname(gen), "summary.json")),
    );
  const g = await fileRows(gen);
  assert(
    g.length === sum.minutes,
    `6-month file: ${g.length} rows = ${sum.minutes} minutes`,
  );
  const key = (o) => JSON.stringify(Object.entries(o).sort());
  assert(
    key(count(g)) === key(sum.minutes_per_stage),
    "6-month file: minutes per stage = summary.json",
  );
  assert(
    g[0].t === Date.UTC(2027, 0, 1) / 6e4 && g[1].t - g[0].t === 1,
    "6-month file: time from the timestamp column, 1 min steps",
  );
  show(1000);
  assert(
    S.T === g[999].T &&
      S.feedSt === g[999].st &&
      S.hist.length === 1000 &&
      S.hist[999] === g[999],
    "show(): state and 48 h history from the rows",
  );
  leaveFeed();
  assert(
    FEED.mode === "twin" && S.feedSt === null && S.T === 25,
    "back to the twin: simulation state restored",
  );

  // 2 plant logger day file
  const day = process.argv[2] || path.join(ROOT, "02_data/common/20260330.txt");
  const r = await fileRows(day),
    Ts = r.map((x) => x.T);
  assert(
    r.length > 1300 && r.length <= 1440,
    `logger file ${path.basename(day)}: ${r.length} minute rows`,
  );
  assert(
    Math.min(...Ts) > 0 && Math.max(...Ts) < 900,
    `logger file: stack T (median TC) ${Math.min(...Ts).toFixed(0)}–${Math.max(...Ts).toFixed(0)} °C`,
  );
  console.log("    stages:", JSON.stringify(count(r)));
  const E = [
      "eta_module_pct",
      ...[1, 2, 3, 4, 5].map((k) => `eta_string${k}_pct`),
    ].map((c) => IDX.get(c)),
    pl = r.filter((x) => x.st === "Part load" && x.v[E[0]] === x.v[E[0]]);
  const em = pl.map((x) => x.v[E[0]]).sort((p, q) => p - q),
    mean5 = (x) => E.slice(1).reduce((s, i) => s + x.v[i], 0) / 5;
  assert(
    !pl.length ||
      (em[0] >= 0 &&
        em.at(-1) < 60 &&
        pl.every((x) => Math.abs(mean5(x) - x.v[E[0]]) < 0.01)),
    `logger file: efficiency in part load ${pl.length ? em[0].toFixed(1) + "–" + em.at(-1).toFixed(1) + " %, median " + em[em.length >> 1].toFixed(1) : "(no part load)"}; string mean = module`,
  );
  leaveFeed();

  console.log("all checks passed");
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
