// Dataset of any length, availability and stage counts from the 2D twin (05_twin_2d/app.js, unchanged), run headless in Node.
// Story: Start up (cold start from 25 °C at minute 0) → hot standby → … → hot standby → Shut down (cool to <40 °C, air off,
// plant off to the end). In between: part loads (PL) and cold shutdowns (CS: Shut down from hot standby, cool, air off, stay,
// Start plant, heat up). Each PL and CS starts and ends in hot standby (twin v3.0 rules: the heat up ends in hot standby = natural gas on, no current; part load
// always unloads to hot standby), so hot standbys = part loads + cold shutdowns + 1. No trips.
// Rated powers (twin v3.3: 30 A per string = 52 kW, button only, reached only from part load): R of the part loads, spread evenly, go on to
// rated power for --rated-hours each (PL → RP → HS), then unload to hot standby. RP counts as available; its fixed minutes come
// out of the available time before PL and HS share the rest. No plant data above 34 kW: RP readings are the rated (30 A) extrapolation (data/sensors.js "rated").
// Availability = (part load + hot standby + fuel switch) / period, as 03_data_analysis/scripts/availability.py. The available minutes
// are exactly availability × period: PL and HS share them (PL 4 : HS 1, each varied by a fixed ±20 % cycle), and the last hot
// standby ends on the exact minute. Start up, cold shutdowns and the final shutdown are the rest; the extra not-available time
// beyond their minimum is split evenly over the cold shutdown stays and the final plant-off time.
// Run:   node 04_synthetic_data/twin_dataset.js --days 181 --availability 95 --part-loads 5 --hot-standbys 7 --cold-shutdowns 1
//          [--rated-powers 0] [--rated-hours 4] [--start 2027-01-01] [--out folder] [--check]
//        → 04_synthetic_data/datasets/twin_<days>d_<avail>pct_<P>pl_<C>cs[_<R>rp<h>h]/ (sofc_twin_dataset.csv.gz, events.csv, summary.json, preview.json)
// --check: only validate the inputs and print "@plan {...}" (used by the app). Progress lines "@progress f", result "@done {...}".
// Needs Node.js and the sibling folder 05_twin_2d (app.js, data/sensors.js, data/bends.js). Nothing else.
const fs = require("fs"),
  path = require("path"),
  vm = require("vm"),
  zlib = require("zlib"),
  { parseArgs } = require("util");
const { values: arg } = parseArgs({
  options: {
    days: { type: "string", default: "181" },
    availability: { type: "string", default: "95" },
    "part-loads": { type: "string", default: "5" },
    "hot-standbys": { type: "string" },
    "cold-shutdowns": { type: "string", default: "1" },
    "rated-powers": { type: "string", default: "0" },
    "rated-hours": { type: "string", default: "4" },
    start: { type: "string", default: "2027-01-01" },
    out: { type: "string" },
    check: { type: "boolean", default: false },
  },
});
const stop = (msg) => {
  console.error(msg);
  process.exit(1);
};
const DAYS = +arg.days,
  AVAIL = +arg.availability,
  P = +arg["part-loads"],
  C = +arg["cold-shutdowns"],
  H = arg["hot-standbys"] == null ? P + C + 1 : +arg["hot-standbys"];
const R = +arg["rated-powers"],
  RH = +arg["rated-hours"],
  RP_MIN = Math.round(RH * 60);
const START = Date.parse(arg.start + "T00:00:00Z");
if (!(DAYS > 0)) stop("Duration must be above 0 days.");
if (!/^\d{4}-\d\d-\d\d$/.test(arg.start) || isNaN(START))
  stop("Start date must look like 2027-01-01.");
for (const [n, v] of [
  ["Part loads", P],
  ["Hot standbys", H],
  ["Cold shutdowns", C],
  ["Rated powers", R],
])
  if (!(Number.isInteger(v) && v >= 0))
    stop(`${n} must be a whole number, 0 or more.`);
if (!(AVAIL > 0 && AVAIL < 100))
  stop(
    "Availability must be above 0 and below 100 %: start up and the final shutdown are never available.",
  );
if (R > P)
  stop(
    `Rated powers can be at most ${P}: rated power is reached only from a part load, one per part load.`,
  );
if (R > 0 && !(RP_MIN >= 1)) stop("Rated power hours must be above 0.");
if (H !== P + C + 1)
  stop(
    `Hot standbys must be ${P + C + 1} for ${P} part loads and ${C} cold shutdown${C === 1 ? "" : "s"}: one after start up, and one after every part load and every cold restart.`,
  );

// ---- block order: SU HS (X HS)* SD, X = part loads with the cold shutdowns spread evenly among them ----
const X = P + C,
  xs = Array(X).fill("PL");
for (let k = 0; k < C; k++) xs[Math.floor(((k + 0.5) * X) / C)] = "CS";
const plAt = xs.flatMap((x, i) => (x === "PL" ? [i] : [])),
  rpAt = new Set(
    Array.from({ length: R }, (_, k) => plAt[Math.floor(((k + 0.5) * P) / R)]),
  );
const SEQ = ["SU", "HS"];
xs.forEach((x, i) => SEQ.push(...(rpAt.has(i) ? [x, "RP"] : [x]), "HS"));
SEQ.push("SD");
const DAY = 1440,
  N = Math.round(DAYS * DAY),
  END = START + N * 60000;
const DOWN = Math.round((1 - AVAIL / 100) * N),
  AV = N - DOWN;
const HEAT_EST = 735,
  COOL_EST = 2070,
  MIN_SEG = 60; // cold start 25 °C → hot standby; hot standby → air off <40 °C
const DOWN_MIN = HEAT_EST + C * (COOL_EST + HEAT_EST) + COOL_EST;
const VARY = [1, 0.8, 1.2, 0.9, 1.1],
  W = { PL: 4, HS: 1 };
const wts = SEQ.map((b, i) => (W[b] ? W[b] * VARY[i % VARY.length] : 0)),
  wsum = wts.reduce((a, b) => a + b, 0);
const DUR = wts.map((w, i) =>
  SEQ[i] === "RP" ? RP_MIN : Math.round((w / wsum) * (AV - R * RP_MIN)),
);
const minDays = Math.ceil(DOWN_MIN / (1 - AVAIL / 100) / DAY),
  maxAvail = Math.floor(10000 * (1 - DOWN_MIN / N)) / 100;
if (DOWN < DOWN_MIN)
  stop(
    `${AVAIL} % of ${DAYS} days leaves ${DOWN.toLocaleString("en")} not available minutes, but start up, ${C} cold shutdown${C === 1 ? "" : "s"} and the final shutdown need about ${DOWN_MIN.toLocaleString("en")}. ` +
      `Use availability up to ${maxAvail} %, at least ${minDays} days, or fewer cold shutdowns.`,
  );
if (DUR.some((m, i) => W[SEQ[i]] && m < MIN_SEG))
  stop(
    `${AVAIL} % of ${DAYS} days leaves ${AV.toLocaleString("en")} available minutes for ${P + H} part load and hot standby blocks${R ? ` and ${R} rated power${R === 1 ? "" : "s"} of ${RP_MIN.toLocaleString("en")} min` : ""}: some would be under ${MIN_SEG} minutes. Use more days or fewer blocks.`,
  );
const OUT = path.resolve(
  __dirname,
  "datasets",
  arg.out ||
    `twin_${DAYS}d_${AVAIL}pct_${P}pl_${C}cs` + (R ? `_${R}rp${RH}h` : ""),
);
const plan = {
  order: SEQ,
  folder: path.basename(OUT),
  minutes: N,
  available_min: AV,
  not_available_min: DOWN,
  min_days: minDays,
  max_availability_pct: maxAvail,
  start: new Date(START).toISOString().slice(0, 10),
  end: new Date(END).toISOString().slice(0, 16).replace("T", " "),
};
if (arg.check) {
  console.log("@plan " + JSON.stringify(plan));
  process.exit(0);
}

// ---- load the app with a do-nothing page ----
const TWIN = path.join(__dirname, "..", "05_twin_2d");
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
  setInterval,
  clearInterval,
  TextDecoder,
  alert: () => {},
  console,
  Float32Array,
  Math,
  Map,
  Set,
  Object,
  JSON,
  Number,
  String,
  Array,
  isFinite,
  isNaN,
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
  stop(
    "05_twin_2d/app.js changed its last line: update END_LINE in twin_dataset.js.",
  );
vm.runInContext(
  src.replace(
    END_LINE,
    "window.__twin={S,tick,startNow,startPlay,stage,applyRules,followPartLoad,manual,jump,IDX};",
  ),
  ctx,
);
const {
  S,
  tick,
  startNow,
  startPlay,
  stage,
  applyRules,
  followPartLoad,
  manual,
  jump,
  IDX,
} = ctx.__twin;
// Twin v3.0 stage keys: hot standby = "Fuel switch" (natural gas on, no current); the heat up ends there by itself.
const HS = "Fuel switch";

// ---- the UI buttons, as their click handlers do it ----
const press = {
  load: () => jump("Part load"),
  rated: () => jump("Rated power"), // Go to rated power (from PL)
  standby: () => jump("Fuel switch"), // any button from RP → hot standby                                                                                    // Go to part load (from HS)
  unload: () => {
    manual();
    S.I = 0;
    applyRules(S);
    followPartLoad(S);
  }, // current knob → 0: hot standby (gas stays on)
  down: () => {
    S.trip = 0;
    S.estop = false;
    startPlay("down");
    applyRules(S);
    followPartLoad(S);
  }, // Shut down
  start: () => startNow(), // Start plant
};

// ---- record ----
fs.mkdirSync(OUT, { recursive: true });
const CSV = path.join(OUT, "sofc_twin_dataset.csv.gz");
const cols = [...IDX],
  gz = zlib.createGzip(),
  file = fs.createWriteStream(CSV),
  I_P = cols.findIndex(([c]) => c === "P_total_kW"),
  I_ETA = IDX.get("eta_module_pct");
gz.pipe(file);
gz.write(
  "timestamp,minute,plant_stage," + cols.map(([c]) => c).join(",") + "\n",
);
const stMin = {},
  events = [],
  hourly = [],
  STEP = Math.max(1, Math.ceil(N / 400));
let rec = 0,
  last = null,
  rpMax = -Infinity;
const ETA = { "Part load": [], "Rated power": [] };
function minute() {
  tick(1);
  const h = S.hist[S.hist.length - 1],
    st = h.st;
  gz.write(
    [
      new Date(START + rec * 60000)
        .toISOString()
        .slice(0, 16)
        .replace("T", " "),
      rec,
      `"${st}"`,
      ...cols.map(([, i]) => (isNaN(h.v[i]) ? "" : +h.v[i].toFixed(3))),
    ].join(",") + "\n",
  );
  stMin[st] = (stMin[st] || 0) + 1;
  if (st === "Rated power") rpMax = Math.max(rpMax, S.T);
  if (ETA[st] && h.v[I_ETA] === h.v[I_ETA]) ETA[st].push(h.v[I_ETA]);
  if (st !== last) {
    events.push({
      minute: rec,
      time: new Date(START + rec * 60000)
        .toISOString()
        .slice(0, 16)
        .replace("T", " "),
      stage: st,
      stack_C: +S.T.toFixed(1),
    });
    last = st;
  }
  if (rec % 60 === 0)
    hourly.push([rec, +S.T.toFixed(1), +(h.v[cols[I_P][1]] || 0).toFixed(2)]);
  if (rec % STEP === 0) console.log("@progress " + (rec / N).toFixed(4));
  rec++;
}
const run = (n) => {
  for (let i = 0; i < n && rec < N; i++) minute();
};
const runUntil = (cond) => {
  while (!cond() && rec < N) minute();
};
const availNow = () =>
  (stMin["Part load"] || 0) +
  (stMin["Hot standby"] || 0) +
  (stMin["Fuel switch"] || 0) +
  (stMin["Rated power"] || 0);
function fail(msg) {
  gz.destroy();
  file.on("close", () => {
    fs.rmSync(CSV, { force: true });
    if (!fs.readdirSync(OUT).length) fs.rmdirSync(OUT);
  });
  file.destroy();
  stop(msg);
}

const SHARE = Math.floor((DOWN - DOWN_MIN) / (C + 1)); // extra not-available time per cold shutdown stay / final plant off
let heatup = null;
for (let i = 0; i < SEQ.length; i++) {
  const b = SEQ[i];
  if (b === "SU") {
    press.start();
    runUntil(() => stage(S) === HS);
    heatup = rec;
  } else if (b === "PL") {
    press.load();
    run(DUR[i]);
  } else if (b === "RP") {
    press.rated();
    run(DUR[i]);
  } else if (b === "HS") {
    if (SEQ[i - 1] === "PL") press.unload();
    else if (SEQ[i - 1] === "RP") press.standby(); // after start up / a cold restart the heat-up already ends in hot standby
    run(SEQ[i + 1] === "SD" ? AV - availNow() : DUR[i]); // the last hot standby ends on the exact available minute
  } else if (b === "CS") {
    press.down();
    runUntil(() => stage(S) === "Shutdown");
    run(SHARE);
    press.start();
    runUntil(() => stage(S) === HS);
  } else {
    press.down();
    run(N);
  } // final shutdown: cooling, air off below 40 °C, plant off to the end
}
if (stage(S) !== "Shutdown")
  fail(
    `The final shutdown did not reach plant off (air off below 40 °C) before the end: it needs more not available time. Use a lower availability or more days.`,
  );
gz.end();

// ---- self-check ----
const med = (a) => {
  if (!a.length) return null;
  a.sort((p, q) => p - q);
  return +a[a.length >> 1].toFixed(1);
};
const visits = (st) => events.filter((e) => e.stage === st).length;
const summary = {
  period: `${new Date(START).toISOString().slice(0, 16).replace("T", " ")} to ${new Date(END).toISOString().slice(0, 16).replace("T", " ")}`,
  days: DAYS,
  minutes: rec,
  availability_target_pct: AVAIL,
  availability_pct: +((100 * availNow()) / rec).toFixed(3),
  order: SEQ.join(" "),
  minutes_per_stage: stMin,
  part_loads: visits("Part load"),
  rated_powers: visits("Rated power"),
  rated_hours: R ? RH : 0,
  rated_stack_max_C: R ? +rpMax.toFixed(1) : null,
  eta_part_load_pct: med(ETA["Part load"]),
  eta_rated_pct: med(ETA["Rated power"]),
  sensors: cols.length,
  hot_standbys: visits(HS),
  cold_shutdowns: C,
  shutdowns: visits("Shutdown"),
  trips: visits("Trip: purge"),
  first_stage: events[0].stage,
  last_stage: events[events.length - 1].stage,
  startup_min: heatup,
  folder: path.basename(OUT),
};
const assert = (c, m) => {
  if (!c)
    fail("Self check failed: " + m + "\n" + JSON.stringify(summary, null, 1));
};
assert(rec === N, "length");
assert(availNow() === AV, `available minutes ${availNow()} vs ${AV}`);
assert(summary.part_loads === P, `${P} part loads`);
assert(summary.rated_powers === R, `${R} rated powers`);
assert(summary.hot_standbys === H, `${H} hot standbys`);
assert(summary.shutdowns === C + 1, `${C} cold shutdowns + final shutdown`);
assert(summary.trips === 0, "no trips");
assert(
  summary.first_stage === "Heat-up air" && summary.last_stage === "Shutdown",
  "starts with start up, ends in shutdown",
);
file.on("finish", () => {
  fs.writeFileSync(
    path.join(OUT, "events.csv"),
    "minute,time,stage,stack_C\n" +
      events
        .map((e) => `${e.minute},${e.time},"${e.stage}",${e.stack_C}`)
        .join("\n") +
      "\n",
  );
  fs.writeFileSync(
    path.join(OUT, "summary.json"),
    JSON.stringify(summary, null, 1),
  );
  fs.writeFileSync(
    path.join(OUT, "preview.json"),
    JSON.stringify({ hourly, events }),
  );
  console.log("@done " + JSON.stringify(summary));
});
