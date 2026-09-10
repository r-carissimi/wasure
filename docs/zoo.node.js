import * as aq from "arquero";
import { createZoo } from "./zoo-core.js";

export const { buildTables } = createZoo(aq, aq.op);
