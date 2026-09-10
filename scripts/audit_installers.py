#!/usr/bin/env python3
"""Install runtimes in isolation and report which ones are actually healthy.

WASURE installs engines by running vendor scripts that fetch the latest
release, so an upstream change to a command-line flag can break an installer
without anything in this repository changing. Worse, `runtimes install`
discards subruntimes that fail their dummy run with only a warning, so an
engine can report a successful install while most of its backends are gone.
Both failure modes have happened:

  * wasmtime removed `-S threads`, so every configuration failed and nothing
    was installed at all;
  * wasmer's `--enable-all` began requesting a proposal no backend supports,
    so 3 of its 4 backends were silently dropped and its published results
    were empty.

This script makes both visible. It installs each runtime into its own
directory, compares the subruntimes that survived against the ones the
installer declares, and optionally runs real benchmarks on each survivor. It
exits non-zero if anything is missing, which is what makes it useful in CI.

Usage:
    python scripts/audit_installers.py --all
    python scripts/audit_installers.py wasmtime wasmedge --benchmarks helloworld
    python scripts/audit_installers.py --all --keep --workdir /tmp/audit
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALLERS = os.path.join(REPO_ROOT, "wasure", "installers")
BENCHMARKS = os.path.join(REPO_ROOT, "wasure", "benchmarks")

GREEN, RED, YELLOW, DIM, RESET = (
    ("\033[92m", "\033[91m", "\033[93m", "\033[2m", "\033[0m")
    if sys.stdout.isatty()
    else ("", "", "", "", "")
)


def declared_runtimes():
    """Map each installer's runtime name to the subruntimes it declares."""

    declared = {}
    for entry in sorted(os.listdir(INSTALLERS)):
        if not entry.endswith(".json"):
            continue
        with open(os.path.join(INSTALLERS, entry)) as f:
            data = json.load(f)
        declared[data["name"]] = [s["name"] for s in data.get("subruntimes", [])]
    return declared


def surviving_runtimes(runtimes_file, name):
    """Read back what the install actually recorded."""

    if not os.path.exists(runtimes_file):
        return None
    with open(runtimes_file) as f:
        installed = json.load(f).get("runtimes", [])
    for runtime in installed:
        if runtime["name"] == name:
            return [s["name"] for s in runtime.get("subruntimes", [])]
    return None


def run(command, timeout):
    try:
        return subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None


def install(name, workdir, timeout):
    folder = os.path.join(workdir, name)
    runtimes_file = os.path.join(folder, "runtimes.json")
    os.makedirs(folder, exist_ok=True)

    result = run(
        [
            sys.executable, "-m", "wasure", "runtimes", "install", name,
            "--runtimes-folder", folder,
            "--runtimes-file", runtimes_file,
            "--benchmarks-folder", BENCHMARKS,
        ],
        timeout,
    )
    return folder, runtimes_file, result


def benchmark(name, folder, runtimes_file, names, timeout):
    """Run real benchmarks and return {runtime: {benchmark: return_code}}."""

    results_folder = os.path.join(folder, "_audit_results")
    result = run(
        [
            sys.executable, "-m", "wasure", "run",
            "-b", *names, "-r", "all",
            "--runtimes-folder", folder,
            "--runtimes-file", runtimes_file,
            "--benchmarks-folder", BENCHMARKS,
            "--results-folder", results_folder,
            "--no-store-output",
            "--timeout", "120",
        ],
        timeout,
    )
    if result is None:
        return None

    files = sorted(
        os.path.join(results_folder, f)
        for f in os.listdir(results_folder)
        if f.endswith(".json")
    ) if os.path.isdir(results_folder) else []
    if not files:
        return None

    with open(files[-1]) as f:
        data = json.load(f)
    return {
        runtime: {b: (runs[0]["return_code"] if runs else 1) for b, runs in benchs.items()}
        for runtime, benchs in data.items()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("runtimes", nargs="*", help="Runtime names to audit")
    parser.add_argument("--all", action="store_true", help="Audit every installer")
    parser.add_argument(
        "--benchmarks",
        nargs="*",
        default=["dummy"],
        help="Benchmarks to run on each survivor (default: dummy)",
    )
    parser.add_argument(
        "--workdir", help="Where to install (default: a temporary directory)"
    )
    parser.add_argument(
        "--keep", action="store_true", help="Do not delete the work directory"
    )
    parser.add_argument(
        "--install-timeout", type=int, default=3600,
        help="Seconds to allow per install (default: 3600)",
    )
    args = parser.parse_args()

    declared = declared_runtimes()
    targets = sorted(declared) if args.all else args.runtimes
    if not targets:
        parser.error("name at least one runtime, or pass --all")

    unknown = [t for t in targets if t not in declared]
    if unknown:
        parser.error(f"no installer for: {', '.join(unknown)}")

    workdir = args.workdir or tempfile.mkdtemp(prefix="wasure-audit-")
    os.makedirs(workdir, exist_ok=True)
    print(f"{DIM}Installing into {workdir}{RESET}\n")

    report = []
    for name in targets:
        started = time.time()
        print(f"{name} ... ", end="", flush=True)

        folder, runtimes_file, result = install(name, workdir, args.install_timeout)
        elapsed = time.time() - started

        if result is None:
            print(f"{RED}TIMEOUT{RESET} after {elapsed:.0f}s")
            report.append((name, "timeout", [], declared[name], {}))
            continue

        survived = surviving_runtimes(runtimes_file, name)
        if survived is None:
            print(f"{RED}FAILED TO INSTALL{RESET} ({elapsed:.0f}s)")
            report.append((name, "failed", [], declared[name], {}))
            continue

        missing = [s for s in declared[name] if s not in survived]
        outcomes = benchmark(
            name, folder, runtimes_file, args.benchmarks, args.install_timeout
        ) or {}
        broken = {
            runtime: bs
            for runtime, bs in outcomes.items()
            if any(code != 0 for code in bs.values())
        }

        if missing or broken:
            print(f"{YELLOW}DEGRADED{RESET} ({elapsed:.0f}s)")
            report.append((name, "degraded", survived, declared[name], broken))
        else:
            print(f"{GREEN}ok{RESET} ({elapsed:.0f}s)")
            report.append((name, "ok", survived, declared[name], {}))

    print("\n" + "=" * 72)
    print(f"{'runtime':22}{'status':11}{'backends':12}notes")
    print("-" * 72)

    failures = []
    for name, status, survived, expected, broken in report:
        backends = f"{len(survived)}/{len(expected)}" if expected else "-"
        notes = []
        dropped = [s for s in expected if s not in survived]
        if dropped:
            notes.append(f"dropped: {', '.join(dropped)}")
        if broken:
            notes.append(f"failing: {', '.join(sorted(broken))}")
        colour = {"ok": GREEN, "degraded": YELLOW}.get(status, RED)
        print(
            f"{name:22}{colour}{status:11}{RESET}{backends:12}"
            f"{'; '.join(notes) if notes else ''}"
        )
        if status != "ok":
            failures.append(name)

    print("=" * 72)
    if not args.keep:
        shutil.rmtree(workdir, ignore_errors=True)
    else:
        print(f"{DIM}Left in place: {workdir}{RESET}")

    if failures:
        print(f"\n{RED}{len(failures)} runtime(s) need attention: "
              f"{', '.join(failures)}{RESET}")
        return 1

    print(f"\n{GREEN}All {len(report)} runtime(s) healthy.{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
