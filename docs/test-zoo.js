import { readFileSync } from "node:fs";
import { buildTables } from "./zoo.node.js";

const csvContent = readFileSync(new URL("./wasure-results.csv", import.meta.url), "utf-8");
const result = buildTables(csvContent);

console.log("Meta:", result.meta);
console.log("\nEngine Scores:");
console.log(result.engineScores.print());
console.log("\nScores by Benchmark:");
console.log(result.scores.print());
