# Merge Gate — Unsafe AI Code Test Cases (`test_cases/`)

This directory contains starter test code files designed to test Merge Gate's independent verifier and deterministic benchmark rules (`R10`–`R14` / `AG-07`–`AG-11`). When each file is run through the analyzer, Merge Gate detects the unsafe AI-generated code changes and outputs an actionable Issue Ticket explaining why the change was blocked or flagged.

## Test Files Included

| File | Benchmark Verification | Verdict | Defect Summary |
| --- | --- | --- | --- |
| `01_broken_runtime_crash.py` | **Runtime Execution Integrity (`R10`)** | `BLOCK` | Invalid syntax (missing `:`), nonexistent module import, and undefined exception identifier that crashes on startup. |
| `02_performance_latency_slowdown.py` | **Performance & Latency Guard (`R11`)** | `BLOCK` | Replaces $O(1)$ dictionary lookup with a nested $O(N^2)$ loop over unindexed collections and adds blocking `time.sleep(0.250)`. |
| `03_complexity_inflation_overengineered.py` | **Code Simplicity & Cyclomatic Complexity (`R12`)** | `BLOCK` | Refactors a simple 4-line function into an 8-branch, 5-level nested conditional labyrinth. |
| `04_inconsistent_styling_drift.py` | **Code Style Conventions Consistency (`R13`)** | `REVIEW` | Introduces `camelCase` function/variable names in a strict `snake_case` Python codebase and drops type annotations. |
| `05_regulatory_rule_violation.py` | **Regulatory & Styling Rules (`R14`)** | `BLOCK` | Uses wildcard imports (`from auth.crypto import *`), bare `except: pass` swallowing errors, and leftover debug `print()` statements. |
| `06_clean_conforming_code.py` | **Conforming Baseline** | `PASS` | Clean $O(1)$ implementation with low cyclomatic complexity, strict `snake_case` naming, full type annotations, and structured logging. |

## Running the Analyzer & Generating Issue Tickets

Run all test files at once:

```bash
python3 scripts/analyze_test_cases.py
```

Or run the analyzer on a single test file:

```bash
python3 scripts/analyze_test_cases.py test_cases/02_performance_latency_slowdown.py
```
