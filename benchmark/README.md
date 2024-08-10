<!-- Copyright 2024 Michael Käser -->
<!-- SPDX-License-Identifier: (Apache-2.0 OR MIT) -->
# Eventlib-py Benchmark

This benchmark compares the performance of the eventlib-py library with a reference implementation hard-coded in Python.

## Usage

In the root directory of this repo run the following commands:

```bash
poetry install --with=dev --with=benchmark
poetry shell
python -m benchmark --help
```

- Use Python's `-O` flag to disable assertions and run the benchmark with optimized code.
- Use `nice -20` to give the benchmark process a higher priority.

### Single run

```bash
nice -20 python -O -m benchmark run -r 100 -i 10_000
```
- `-r` is the number of repetitions.
- `-i` is the number of iterations per repetition.
- The results will be printed to the console.

```markdown
Results for benchmark 'benchmark.cases.case_all' and 10000 iterations:
|      |   Reference |   Library |   Library Init |   Factor |
|:-----|------------:|----------:|---------------:|---------:|
| 0.50 |    42.289μs |  45.373μs |      135.125μs |     1.07 |
| 0.90 |    43.560μs |  46.809μs |      143.000μs |     1.10 |
| 0.99 |    46.658μs |  50.048μs |      260.393μs |     1.15 |
```

### Ranged run

Run the benchmark for a range of iterations (from `1` to `2**{iterations-power}`, default: `2**18`).
It will write the results to a json file and show the rendering.

```bash
nice -20 python -O -m benchmark range --file results.json
```
- `--file` is the file to write the results to.
- The results will be shown as matplotlib plot.

### Render a previous ranged run

```bash
python -O -m benchmark render --file results.json
```
- `--file` is the file to read the results from.
- The results will be shown as matplotlib plot.
