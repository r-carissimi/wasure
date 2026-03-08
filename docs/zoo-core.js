export function createZoo(aq, op) {
  function readCsvData(csvContent) {
    return aq.fromCSV(csvContent).rename({ runtime: "engine" });
  }

  function preprocessData(table) {
    return table
      .select(aq.not("run_index", "score"))
      .filter((d) => d.elapsed_time_ns !== 0 && d.return_code === 0)
      .select(aq.not("return_code"))
      .filter(d => d.engine !== 'wasmedge-aot') // XXX: wasmedge-aot had sketchy data
      // XXX: AOT engines should probably have their own category,
      // and e.g. wizard spc should probably be aot
      .filter(d => d.engine !== 'wasmtime-aot')
      .filter(d => d.engine !== 'wasmer-aot');
  }

  function addBenchmarkScores(table) {
    // Calculate geometric mean per benchmark: exp(mean(ln(x)))
    const benchmarkStats = table
      .groupby("benchmark")
      .rollup({ gmean_elapsed_ns: (d) => op.exp(op.mean(op.log(d.elapsed_time_ns))) });

    // Join and calculate speedup score
    return table
      .join(benchmarkStats, "benchmark")
      .derive({ score: (d) => d.gmean_elapsed_ns / d.elapsed_time_ns })
      .select("engine", "benchmark", "elapsed_time_ns", "score");
  }

  function getEngineScores(table) {
    return table
      .groupby("engine")
      .rollup({ total_score: (d) => op.sum(d.score) })
      .orderby(aq.desc("total_score"));
  }

  // Compute scores table from runs: engine × benchmark scores, ordered by total
  function computeScores(runsTable) {
    const benchmarks = addBenchmarkScores(runsTable);
    const engineScores = getEngineScores(benchmarks);
    const benchmarkNames = [...new Set(benchmarks.array("benchmark"))].sort();

    return benchmarks
      .groupby("engine")
      .pivot("benchmark", { score: (d) => op.mean(d.score) })
      .join(engineScores, "engine")
      .orderby(aq.desc("total_score"))
      .select("engine", "total_score", ...benchmarkNames);
  }

  // Compute runtimes table from runs: engine × benchmark times (seconds), ordered by total
  function computeRuntimes(runsTable) {
    const benchmarks = addBenchmarkScores(runsTable);
    const engineScores = getEngineScores(benchmarks);
    const engines = engineScores.array("engine");
    const benchmarkNames = [...new Set(benchmarks.array("benchmark"))].sort();

    const timesPivot = benchmarks
      .derive({ elapsed_time_s: (d) => d.elapsed_time_ns / 1000000000 })
      .groupby("engine")
      .pivot("benchmark", { elapsed_time_s: (d) => op.mean(d.elapsed_time_s) });
    const engineRuntimes = benchmarks
      .derive({ elapsed_time_s: (d) => d.elapsed_time_ns / 1000000000 })
      .groupby("engine")
      .rollup({ total_runtime: (d) => op.sum(d.elapsed_time_s) });

    return aq
      .table({ engine: engines })
      .join(timesPivot, "engine")
      .join(engineRuntimes, "engine")
      .select("engine", "total_runtime", ...benchmarkNames);
  }

  function buildTables(csvContent) {
    const raw = readCsvData(csvContent);
    const failed = raw.filter(d => d.return_code !== 0);
    const runs = preprocessData(raw);

    return {
      raw,
      runs,
      failed,
      benchmarks: addBenchmarkScores(runs),
      scores: computeScores(runs),
      runtimes: computeRuntimes(runs),
      computeScores,
      computeRuntimes,
    };
  }

  return { buildTables };
}
