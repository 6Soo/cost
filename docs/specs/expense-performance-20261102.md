# Expense cleanup and classification performance (2026-11-02)

Current user scope: improve elapsed time after PR486; implement and compare Python/Rust on identical inputs, preserve rules/data, test, merge, deploy. Production classification/apply, financial/trip/Google/source/schema/reprocessing writes are excluded.

| Requirement | State | Evidence |
| --- | --- | --- |
| Operating/synthetic profiling | Done | SQL/Python/presentation/I/O; read-only snapshots; authenticated GET |
| Python optimization | Implemented, tested | Reuse validation within one plan; no cross-request cache |
| Actual Rust comparison | Done | Built C ABI DLL;250seeded cases and full outputs equivalent |
| Selection/protection | Done | Choose Python;79targeted+109adjacent protection tests passed |
| PR/deployment/handoff | In progress | PR507; fixed-SHA deployment/acceptance pending |

## Bottleneck and implementation

Initial synthetic2,000rows/70trips cProfile:8,757ms total,72ms SQL/12statements,2.1ms Path I/O,8,683ms remaining Python. canonical_trip_periods ran4,001times/5,124ms cumulative. Operating6,895rows/66registered trips:5,911calls/7,850ms cumulative. Cumulative times overlap; cProfile overhead means these are not wall-time benchmarks.

Reuse periods already validated by plan in inference/candidate generation. Standalone calls revalidate. No global cache. Preserve manual corrections, holds, refunds, OTA service periods, region/tie/nets rules and full results/digest. New regressions change periods, remove trips, clear authority and change nets between calls; inputs remain unchanged and outputs match the baseline.

Reuse independently shipped [PR498 SQL/refund optimization](cleanup-read-performance-20261102.md) through normal merge: uncorrelated IN sets and exact candidate buckets. No duplicate implementation/index/schema change. Its4.35x read-kernel gain is not attributed to this PR.

## Same-input full-plan comparison

Baseline automatic/provisional modules114af50d; all other code/refund implementation/connection/input shared. Same read-only transaction, warm runs alternating order, every complete output/digest equal and total_changes unchanged. WindowsAMD64/Python3.14.7; identical driver instrumentation.

| Workload/repetitions | Baseline Python | Optimized Python | Optimized Python+Rust selection |
| --- | ---: | ---: | ---: |
| Synthetic2,000rows/70trips /7median | 2,102.6ms | 1,036.7ms | 1,279.7ms |
| Operating6,895rows/66registered trips /5median | 3,258.2ms | 1,206.0ms | 1,266.3ms |
| Operating6,895rows/64valid trips+Google nets /5median | 2,611.9ms | 1,046.3ms | 997.9ms |

Actual completion context: Python59.9% shorter/2.50x. Last-context Rust median4.6% faster, but ranges overlap(Python960.7-1,266.3ms;Rust951.4-1,415.6ms). Rust is5.0% slower on registered trips and23.4% slower synthetically. No consistent Rust end-to-end advantage. These are read-only plans, not actual apply/upload transactions.

SQL count unchanged:12synthetic/13operating. Actual-context SQL medians399.5/396.0/380.7ms reflect run variation, not this PR changing SQL.

## Native experiment and decision

Actual tools/experiments/trip_choice.rs implements O(T) maximum-score/earliest-date/lexical-ID selection and score-tie count. Replaces only Python sorting/tie counting, not date scoring/regions/the whole policy.250seeded random cases and complete plans match.

Python-to-ctypes arrays/date/ID conversion/native call/result construction included.1/10/70candidates: Python2.24/9.74/66.65us versus Rust-with-boundary13.20/26.93/171.33us. DLL load/adapter separately1.63-1.76ms. Native-only timing does not substitute for full cost.

Actual Rust1.99.1 built using official manifest/SHA256-verified portable compiler/std(77.1/23.6MB compressed), no OS/PATH/rustup changes. DLL2,560bytes;no_std/no heap/no I/O. Toolchain and DLL excluded from Git/production. Rust adds Windows build/architecture/ABI/buffer-lifetime/loading/deployment failure paths. Choose optimized Python: no consistent gain justifies these costs. This limited selection experiment does not generalize to other Rust kernels/workloads.

Reproduce without customer data:

```powershell
python tools/profile_expense_performance.py --rows 2000 --trips 70 --output profile.json
python tools/benchmark_expense_performance.py --baseline 114af50d --rows 2000 --trips 70 --repeats 7 --output python.json
# Set rustc/rustLld to actual absolute executable paths.
& $rustc tools/experiments/trip_choice.rs --crate-type cdylib --edition=2024 -C opt-level=3 -C panic=abort -C linker=$rustLld -C link-arg=/NODEFAULTLIB -C link-arg=/NOENTRY -o trip_choice.dll
python tools/benchmark_expense_performance.py --baseline 114af50d --rows 2000 --trips 70 --repeats 7 --native-dll ./trip_choice.dll --output rust.json
```

Explicit --operational-db uses URI mode=ro/query_only/BEGIN and diagnostic facade bypassing writer/schema constructors. Sensitive stored authority/Google paths and context harness stay local.

## Memory and complexity: no claimed improvement

Separate actual-context tracemalloc peaks97.02/97.25/97.06MiB(baseline/Python/Rust); synthetic23.80/23.79/23.80MiB. Excludes OS/DLL; kernel allocates no heap. Fresh child process per variant/two operating66trip plans: total peak working set139.02/138.55/139.34MiB, final private bytes59.59/62.00/60.38MiB. Includes interpreter/imports/DBpages/DLL. No meaningful memory improvement; not a long-term/concurrency bound.

Two runtime modules755->759physical lines;26->26functions;24->24import statements;141->144ASTbranches(If/IfExp/For/While/Try, not cyclomatic complexity). Repeated validation work decreases, static size/branches/dependencies do not. Measurement/native experiment/tests add maintenance code separately. No new production dependency/schema/external I/O/deployment step.

## Cleanup and HTTP limits

Same operating DB cleanup core before/after reusing PR498: warm cProfile2,167.5->940.0ms;SQL1,646.3->725.7ms;189statements unchanged;PathI/O4.29->4.85ms;presentation self0.205->0.236ms;HTML SHA256 equal. Cold2,213.5->1,273.4ms. Driver includes fetch/iteration and some Python conversion; presentation self only covers two UI modules, not all HTML construction. read_text counts characters. OTA deliberately unavailable/failclosed to prevent worker effects: not full authenticated HTTP.

Real authenticated ego-browser /import GET5samples afterPR498: median1,497.5ms(range1,251.0-2,260.7),200/189,673characters. Proxy/network/OTA/context included. GET does not run automatic plan; no page-load acceleration is attributed to this Python optimization. Cache/concurrent host work/sample5or7 variation; cold-start/concurrency/long-term memory/write transactions unmeasured. Never combine synthetic/profile/HTTP into one percentage.

## Validation/evidence

79targeted passed(new freshness3,existing full-plan/digest8,completion/correction/preparation/domestic-overseas/SQL equivalence);109adjacent protection passed(manual/source/duplicate/partial/foreign/original-approval/cross-batch refunds/correction rules). No weakened assertions. Full regression omitted for local computation reuse; prior20case task not reopened. Host venv lacks pytest: tests used developmentPython3.14.7; operational diagnostics hostvenvPython3.14.7.

Local .local-archive/expense-performance-20261102/: synthetic-before.json,operating-plan-before.json,synthetic-final.json,operating-comparison.json,business-context-comparison.json,operating-cleanup-before.json,operating-cleanup-after-pr498.json,browser-before.json,complexity.json,memory-baseline/python/rust.json,measure-process-memory.py,final-targeted.xml,protection-tests.xml. No customer rows/IDs/SQLparameters/HTML/individual links in reports/Git/external models.
