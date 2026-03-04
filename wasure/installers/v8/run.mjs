import { WASI } from "wasi";
import { readFileSync } from "fs";

const wasi = new WASI({
  version: "preview1",
  args: process.argv.slice(2),
  env: process.env,
  preopens: { "/": "/" },
});

const bytes = readFileSync(process.argv[2]);
const module = new WebAssembly.Module(bytes);
const instance = new WebAssembly.Instance(module, wasi.getImportObject());
wasi.start(instance);
