// Smoke test for the benchmark explorer's data pipeline.
// Run with `npm test` from the repository root.

import { readFileSync } from "node:fs";
import { buildTables } from "./zoo.node.js";

const csvContent = readFileSync(
  new URL("./wasure-results.csv", import.meta.url),
  "utf-8",
);
const tables = buildTables(csvContent);

const failures = [];
function check(name, condition, detail) {
  if (condition) return;
  failures.push(detail ? `${name} (${detail})` : name);
}

// buildTables must expose exactly what index.html documents in its query docs,
// since a query typed into the page can reference any of these.
for (const name of ["raw", "runs", "failed", "benchmarks", "scores", "runtimes"]) {
  const table = tables[name];
  check(
    `tables.${name} is a table`,
    table && typeof table.numRows === "function",
    `got ${typeof table}`,
  );
}
for (const name of ["computeScores", "computeRuntimes"]) {
  check(`tables.${name} is a function`, typeof tables[name] === "function");
}

check("raw has rows", tables.raw?.numRows() > 0);
check("runs has rows", tables.runs?.numRows() > 0);
check(
  "runs is a subset of raw",
  tables.runs?.numRows() <= tables.raw?.numRows(),
  `${tables.runs?.numRows()} > ${tables.raw?.numRows()}`,
);

// The CSV names the column "runtime"; the pipeline renames it to "engine".
check(
  "runs exposes an engine column",
  tables.runs?.columnNames().includes("engine"),
  tables.runs?.columnNames().join(", "),
);

// Scores are a speedup ratio, so they must be finite and positive. A NaN here
// means a benchmark slipped through with a zero or missing elapsed time.
const scores = tables.benchmarks?.array("score") ?? [];
check("benchmarks has scores", scores.length > 0);
check(
  "all scores are finite and positive",
  scores.every((s) => Number.isFinite(s) && s > 0),
  `${scores.filter((s) => !(Number.isFinite(s) && s > 0)).length} bad of ${scores.length}`,
);

// Every failed run must be excluded from the successful-run table. The
// committed CSV happens to contain no zero-elapsed rows, so asserting this
// against it would pass even if the filter were removed. Use a synthetic CSV
// that contains one row of each failure shape instead.
const syntheticCsv = [
  "benchmark,runtime,run_index,elapsed_time_ns,score,return_code",
  "good,engineA,1,1000,0,0", // healthy
  "crashed,engineA,1,500,0,1", // non-zero exit
  "invalid,engineA,1,0,0,-1002", // validation failure (wasure sentinel)
  "zerotime,engineA,1,0,0,0", // exit 0 but no usable timing
].join("\n");
const synthetic = buildTables(syntheticCsv);

check(
  "runs keeps only the healthy row",
  synthetic.runs.numRows() === 1,
  `kept ${synthetic.runs.numRows()} of 4`,
);
check(
  "runs keeps the right row",
  synthetic.runs.array("benchmark")[0] === "good",
  synthetic.runs.array("benchmark").join(", "),
);
check(
  "failed surfaces every non-zero return code",
  synthetic.failed.numRows() === 2,
  `got ${synthetic.failed.numRows()}, expected crashed + invalid`,
);
check(
  "wasure failure sentinels are treated as failures",
  synthetic.failed.array("benchmark").includes("invalid"),
);

// Repeated runs must collapse to one row per engine and benchmark, summarized
// by the median. Without this an engine repeated more times than the others
// would skew the per-benchmark geometric mean the scores are relative to, and
// a single slow outlier would drag its own average.
const repeatCsv = [
  "benchmark,runtime,run_index,elapsed_time_ns,score,return_code",
  // Odd number of runs so the median is one of the samples: median 120,
  // mean 692 -- far apart, so which one is used is unambiguous.
  "b,engineA,1,100,0,0",
  "b,engineA,2,110,0,0",
  "b,engineA,3,120,0,0",
  "b,engineA,4,130,0,0",
  "b,engineA,5,3000,0,0",
  // A single run, to check unequal repeat counts are handled.
  "b,engineB,1,200,0,0",
].join("\n");
const repeated = buildTables(repeatCsv);

check(
  "repeats collapse to one row per engine and benchmark",
  repeated.benchmarks.numRows() === 2,
  `got ${repeated.benchmarks.numRows()} rows, expected 2`,
);
const collapsed = Object.fromEntries(
  repeated.benchmarks.objects().map((r) => [r.engine, r]),
);
check(
  "collapsed time is the median, not the mean",
  collapsed.engineA?.elapsed_time_ns === 120,
  `got ${collapsed.engineA?.elapsed_time_ns}, median is 120 and mean is 692`,
);
check(
  "the number of runs behind each row is reported",
  collapsed.engineA?.runs === 5 && collapsed.engineB?.runs === 1,
  `got ${collapsed.engineA?.runs} and ${collapsed.engineB?.runs}`,
);
check(
  "the faster engine scores higher",
  collapsed.engineA?.score > collapsed.engineB?.score,
  `${collapsed.engineA?.score} vs ${collapsed.engineB?.score}`,
);
check(
  "one leaderboard row per engine despite the repeats",
  repeated.scores.numRows() === 2,
  `got ${repeated.scores.numRows()}`,
);

// Engine versions are carried through when the CSV has them, and their
// absence must not break anything: the committed CSV predates the column.
const versionedCsv = [
  "benchmark,runtime,runtime_version,run_index,elapsed_time_ns,score,return_code",
  "b,engineA,engineA 1.2.3,1,100,0,0",
  "b,engineA,engineA 1.2.3,2,120,0,0",
  "b,engineB,,1,200,0,0",
].join("\n");
const versioned = buildTables(versionedCsv);

check(
  "versions lists one row per engine",
  versioned.versions.numRows() === 2,
  `got ${versioned.versions.numRows()}`,
);
const byEngine = Object.fromEntries(
  versioned.versions.objects().map((r) => [r.engine, r.runtime_version]),
);
check(
  "the recorded version is reported",
  byEngine.engineA === "engineA 1.2.3",
  `got ${byEngine.engineA}`,
);
check(
  "an unknown version stays empty rather than being invented",
  !byEngine.engineB,
  `got ${byEngine.engineB}`,
);
check(
  "the version survives into the per-benchmark table",
  versioned.benchmarks.columnNames().includes("runtime_version"),
  versioned.benchmarks.columnNames().join(", "),
);
check(
  "grouping by version does not split an engine's repeats",
  versioned.benchmarks.numRows() === 2,
  `got ${versioned.benchmarks.numRows()} rows for 2 engines`,
);
check(
  "repeats still collapse when a version column is present",
  versioned.benchmarks.objects().find((r) => r.engine === "engineA")?.runs === 2,
);

// A CSV without the column must still produce a working leaderboard.
check(
  "versions is empty for a CSV without the column",
  tables.versions?.numRows() === 0,
  `got ${tables.versions?.numRows()}`,
);
check(
  "the per-benchmark table omits the column when absent",
  !tables.benchmarks?.columnNames().includes("runtime_version"),
);

// computeScores must be recomputable from a filtered subset, which is the
// documented way to exclude an engine from the leaderboard.
const engines = [...new Set(tables.runs?.array("engine") ?? [])];
const recomputed = tables.computeScores(
  tables.runs.filter(`d => d.engine !== '${engines[0]}'`),
);
check(
  "computeScores drops the filtered engine",
  !recomputed.array("engine").includes(engines[0]),
);

// The leaderboard is rendered by toHTML and sorted by total_score. Assert it
// is non-empty: every other check here passes on a zero-row leaderboard.
check("scores has rows", tables.scores?.numRows() > 0);
check(
  "scores has one row per engine",
  tables.scores?.numRows() === engines.length,
  `${tables.scores?.numRows()} rows vs ${engines.length} engines`,
);
check("scores has total_score", tables.scores?.columnNames().includes("total_score"));
check("scores renders to HTML", typeof tables.scores?.toHTML === "function");
const totals = tables.scores?.array("total_score") ?? [];
check(
  "scores are ordered by descending total_score",
  totals.every((v, i) => i === 0 || totals[i - 1] >= v),
);

if (failures.length > 0) {
  console.error(`FAIL: ${failures.length} check(s) failed`);
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}

console.log(
  `PASS: ${tables.raw?.numRows()} rows, ${engines.length} engines, ` +
    `${new Set(tables.runs?.array("benchmark")).size} benchmarks, ` +
    `${tables.failed?.numRows()} failed runs excluded`,
);
