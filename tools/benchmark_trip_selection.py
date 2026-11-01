"""Compare attribution kernels on synthetic data against a committed baseline."""
import argparse
import ast
from datetime import date, timedelta
import json
from pathlib import Path
from statistics import median
import subprocess
import sqlite3
import sys
from time import perf_counter
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.provisional_assignment import canonical_trip_periods, card_trip_candidates
from app.automatic_classification import _read, FIELDS


def timing(call, repeats=7):
    result = call()
    samples = []
    for _ in range(repeats):
        started = perf_counter()
        assert call() == result
        samples.append(perf_counter() - started)
    return result, median(samples)


def benchmark(revision):
    source = subprocess.check_output(['git', 'show', revision + ':app/provisional_assignment.py']).decode('utf-8-sig')
    baseline = types.ModuleType('app._baseline_provisional')
    exec(compile(source, '<committed baseline>', 'exec'), baseline.__dict__)
    # Many trips at the same start stress the former suffix scans. This is an
    # explicit stress case, not a claim about production response latency.
    open_trips = [dict(trip_id=str(i), starts_on='2026-01-01') for i in range(2000)]
    start = date(2020, 1, 1)
    trips = [dict(trip_id=str(i), starts_on=(start + timedelta(days=i * 2)).isoformat(),
                  ends_on=(start + timedelta(days=i * 2 + 1)).isoformat()) for i in range(1000)]
    row = {'approval_date': '2030-01-01'}  # After every trip: preparation cannot change semantics.
    measurements = {}
    for name, old, new in (
        ('open_periods_2000_same_start', lambda: baseline.canonical_trip_periods(open_trips), lambda: canonical_trip_periods(open_trips)),
        ('rank_1000_past_trips', lambda: baseline.card_trip_candidates(row, trips), lambda: card_trip_candidates(row, trips)),
    ):
        left, before = timing(old)
        right, after = timing(new)
        assert left == right, name
        measurements[name] = {'baseline_median_ms': before * 1000, 'current_median_ms': after * 1000,
                              'speedup': before / after, 'outputs_equal': True}
    source = subprocess.check_output(['git', 'show', revision + ':app/automatic_classification.py']).decode('utf-8-sig')
    old_read = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == '_read')
    namespace = {'FIELDS': FIELDS}
    exec(compile(ast.Module(body=[old_read], type_ignores=[]), '<baseline row reader>', 'exec'), namespace)
    columns = eval(compile(ast.Expression(old_read.body[0].value), '<reader columns>', 'eval'), namespace)
    with sqlite3.connect(':memory:') as conn:
        conn.execute('CREATE TABLE transactions (' + ','.join(name + (' TEXT PRIMARY KEY' if name == 'transaction_id' else ' TEXT') for name in columns) + ')')
        conn.executemany('INSERT INTO transactions VALUES (' + ','.join('?' for _ in columns) + ')',
                         [(str(index), *('synthetic' for _ in columns[1:])) for index in range(20000)])
        selected = {str(index) for index in range(50)}
        left, before = timing(lambda: namespace['_read'](conn, selected))
        right, after = timing(lambda: _read(conn, selected))
        assert left == right
        measurements['read_50_of_20000_sources'] = {'baseline_median_ms': before * 1000, 'current_median_ms': after * 1000,
                                                   'speedup': before / after, 'outputs_equal': True}
    return {'baseline': revision, 'source': 'synthetic only', 'measurements': measurements,
            'limitations': 'Kernel microbenchmarks; excludes DB, I/O, HTTP and native-language boundary costs.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default='bc723cfa')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = benchmark(args.baseline)
    if args.output:
        args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
