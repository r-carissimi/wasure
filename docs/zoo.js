import * as aq from "https://cdn.jsdelivr.net/npm/arquero@5.4.1/+esm";
import { createZoo } from "./zoo-core.js";

export const { buildTables } = createZoo(aq, aq.op);
