import { WASI } from "wasi";
import { readFileSync } from "fs";

const wasi = new WASI({
  args: Bun.argv.slice(2),
  env: process.env,
  preopens: { "/": "/" },
});

const bytes = readFileSync(Bun.argv[2]);
const module = new WebAssembly.Module(bytes);
const instance = new WebAssembly.Instance(module, {
  wasi_snapshot_preview1: wasi.wasiImport,
});
wasi.start(instance);
