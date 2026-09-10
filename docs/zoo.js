// Keep this version in sync with the arquero dependency in package.json and
// with the import in index.html, so that the site and `npm test` exercise the
// same library.
import * as aq from "https://cdn.jsdelivr.net/npm/arquero@8.0.3/+esm";
import { createZoo } from "./zoo-core.js";

export const { buildTables } = createZoo(aq, aq.op);
