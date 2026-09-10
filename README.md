<img src="https://raw.githubusercontent.com/r-carissimi/wasure/9c23740a47eaab6444735afcdca79dbcca17a57b/assets/logo.png" width="200">

# WASURE - WebAssembly SUite for Runtime Evaluation

**⚠️ This is a work in progress!**

**WASURE** is a command-line toolkit that helps you **benchmark WebAssembly runtimes** with clarity. It lets you run benchmarks across multiple engines, manage runtime environments, and generate meaningful visualizations and exports for analysis.



## 🚀 Features

- Run and manage WebAssembly benchmarks across various runtimes
- Install, update, and manage runtimes with simple commands
- Export results to CSV for analysis or create plots for quick visualization
- Designed for clarity, reproducibility, and extensibility



## 🛠 Getting Started

### Quick Install

Install the latest released version from PyPI. You can use either **pip** or **uv**:

```bash
pip3 install wasure
# or
uv add wasure
```

> [!WARNING]
> Updating the pip package **will delete all changes made**, including benchmark results, installed runtimes, saved plots, and custom benchmarks. To avoid this, you can either:
> - Use a custom directory for these data (by using the relevant flags, such as `--runtimes-folder`) 
> - Back up any important data beforehand
> - Use `wasure` from source, without installing it




### Run Without Installing

Run the project from source, without installing it. This will provide the newest version. You can use either **pip** or **uv** for dependency management:

```bash
git clone https://github.com/r-carissimi/wasure.git
cd wasure
```
then:
```bash
pip3 install -r requirements.txt
python3 -m wasure
```
or
```bash
uv venv                    
source .venv/bin/activate
uv pip install -r requirements.txt
python3 -m wasure
```

> [!NOTE]
> While following the instructions below, be sure to replace `wasure` with `python3 -m wasure`



### Install Latest Version from GitHub

If you want to install the newest features or fixes, install directly from the repository:

```bash
git clone https://github.com/r-carissimi/wasure.git
cd wasure
```
then:
```bash
pip install .
```
or
```bash
uv pip install .
```

## 📖 How to Use WASURE

WASURE is structured as a command-line tool with modular subcommands to list, run, compare, and visualize WebAssembly benchmarks. Each subcommand has its own options, allowing you to start simple and scale up your experiments as needed.

```bash
wasure [OPTIONS] COMMAND
```

Use `--log-level DEBUG` to troubleshoot issues and `--help` under any subcommand for more information.



### 🔍 Listing Available Benchmarks

See what benchmarks are available:

```bash
wasure benchmarks list
```



### ⚙️ Managing Runtimes

Install, update, and manage supported runtimes:

```bash
# View available runtimes
wasure runtimes available

# Install a runtime
wasure runtimes install wasmtime

# Update or remove runtimes
wasure runtimes update wasmtime
wasure runtimes remove wasmtime

# List installed runtimes and their versions
wasure runtimes list
wasure runtimes version
```



### 🏃 Running Benchmarks

Run benchmarks with your chosen runtimes:

```bash
# Run a single benchmark on one runtime
wasure run -b helloworld -r wasmtime

# Run multiple benchmarks on multiple runtimes
wasure run -b pystone dummy dhrystone/dhrystone10M -r wasmtime wasmedge wasmer --repeat 3

# Run a raw WebAssembly file directly
wasure run -b py2wasm/pystone/pystone.wasm -r wasmtime

# Run a benchmark tracking the memory consumption. Timings may increase.
wasure run -b helloworld -r wasmtime
```

#### Useful Flags

- `--repeat N`: Repeat each benchmark N times
- `--no-store-output`: Don’t save output, just timings
- `--results-folder <path>`: Define custom output directory
- `--memory`: Pool the memory consumption
- `--timeout N`: Stop benchmarks after N seconds



### 📊 Visualizing and Exporting Results

Plot or export results with:

```bash
# Plot benchmark output
wasure plot /path/to/results/2025-05-06_10-56-21.json

# Plot the mean of repeated runs instead of the median
wasure plot /path/to/results/2025-05-06_10-56-21.json --statistic mean

# Export results to CSV
wasure export /path/to/results/2025-05-06_10-56-21.json
```

> [!TIP]
> Use `--repeat` when running benchmarks, and prefer the default `median`
> statistic when plotting. Timings are right-skewed — a run can be slowed by
> unrelated load but never made faster than the machine allows — so a single
> sample or a mean is easily distorted by one interrupted run. On short
> benchmarks the fastest engines have been measured varying by more than 4x
> across ten repeats, while slower ones varied by around 2%.
> `--statistic` accepts `median` (default), `mean` or `min`; the error bars
> always show the full observed range.

#### 📄 Exported CSV Structure

When you export benchmark results to CSV, each row contains the following columns:

| Column            | Description                                                |
|-------------------|------------------------------------------------------------|
| `benchmark`       | Name of the benchmark or WebAssembly file                  |
| `runtime`         | Name of the runtime used                                   |
| `run_index`       | Index of the run (for repeated benchmarks)                 |
| `elapsed_time_ns` | Execution time in nanoseconds                              |
| `score`           | Benchmark-specific score (if applicable, else 0)           | 
| `return_code`     | Process return code (0 means success)                      |
| `max_rss_bytes`   | Maximum resident set size in bytes, if `--memory` is set   |
| `max_vms_bytes`   | Maximum virtual memory size in bytes, if `--memory` is set |

##### Return codes

A `return_code` of `0` means the run succeeded. A positive value is the exit
status reported by the payload, and a small negative value is the signal that
killed it (for example `-11` for `SIGSEGV`). Two values are reported by WASURE
itself rather than by the payload:

| Value   | Meaning                                                              |
|---------|----------------------------------------------------------------------|
| `-1001` | The run exceeded `--timeout` and was killed                          |
| `-1002` | The run finished but its output did not match its `output-validator`  |

In both of these cases `elapsed_time_ns` and `score` are reported as `0`, since
no usable measurement was obtained. Treat any non-zero `return_code` as a failed
run.

> [!NOTE]
> Prefer `max_rss_bytes` when comparing memory use. `max_vms_bytes` counts every
> mapped region rather than memory actually used, so it is not comparable across
> platforms — on macOS it routinely reads as hundreds of gigabytes.
> Both columns are left empty for runs too short to be sampled.



### ✅ Checking Runtimes Support

The `check` command allows you to verify if specific benchmarks run successfully on selected runtimes. It is particularly useful when combined with the `wasm-features` or `wasi-proposals` benchmark groups. These groups enable you to track which runtime has implemented specific features or proposals.

```bash
# Check the wasm features support on all runtimes
wasure check wasm-features

# Check the wasi proposals implementation on wasmtime and wasmedge
wasure check wasi-proposals -r wasmtime wasmedge
```



### 💡 Run WASI benchmarks on runtimes that do not support WASI

Refer to the [Replay Merger project](https://github.com/r-carissimi/wasm-r3-replay-generator-docker) for instructions on how to run WASI benchmarks on runtimes that do not support WASI.

### ➕ Adding New Benchmarks

Refer to the [Benchmarks Management Documentation](docs/benchmarks-management.md) for detailed instructions on adding new benchmarks.

### ⚙️ Adding or Editing a Runtime

Refer to the [Runtimes Management Documentation](docs/runtimes-management.md) for detailed instructions on adding or editing runtimes.



## ⚠️ Known Limitations

- **Platform Support:** Linux and macOS are supported. Windows is currently **not** supported.
- **Path Restrictions:** Installers relying on `npm` (e.g., v8, jsc, spidermonkey) may fail if the runtimes path contains spaces.
- **Non-ASCII Characters:** JSC (JavaScriptCore) does not support payload paths with non-ASCII characters.



## 🤝 Contributing

Contributions are welcome! Feel free to open issues or submit pull requests to improve the project. Please ensure your code follows the [PEP 8](https://peps.python.org/pep-0008/) style guide for Python to maintain consistency across the project.



## 📜 License

This project is licensed under the [GNU General Public License v3.0](LICENSE).
