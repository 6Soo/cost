"""Compare full same-input plans and cleanup HTML, including native boundary cost.

Operational mode is an explicit read-only SQLite snapshot. No source rows,
SQL parameters, HTML or customer strings are serialized into the report.
"""
from __future__ import annotations
import argparse
import ast
import ctypes
import hashlib
import inspect
import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
import types
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.profile_expense_performance import setup_synthetic,setup_operational,Meter


def baseline(revision):
    modules=[]
    for path in ('app/provisional_assignment.py','app/automatic_classification.py'):
        source=subprocess.check_output(['git','show',revision+':'+path],cwd=ROOT).decode('utf-8-sig')
        module=types.ModuleType('app._benchmark_'+Path(path).stem)
        module.__package__='app'
        exec(compile(source,'<baseline-'+Path(path).name+'>','exec'),vars(module))
        modules.append(module)
    modules[1].card_trip_candidates=modules[0].card_trip_candidates
    return modules[1]


def native_selector(path):
    dll=ctypes.CDLL(str(path.resolve()))
    choose=dll.choose_trip
    choose.argtypes=[ctypes.POINTER(ctypes.c_int64),ctypes.POINTER(ctypes.c_uint64),ctypes.POINTER(ctypes.c_uint64),ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)]
    choose.restype=ctypes.c_int32
    def select(candidates,valid):
        n=len(candidates)
        identities={identity:index for index,identity in enumerate(sorted(c['trip_id'] for c in candidates))}
        # Every conversion/allocation and the ctypes invocation are timed as
        # part of the whole plan. Buffers never escape this synchronous call.
        scores=(ctypes.c_int64*n)(*(c['score'] for c in candidates))
        starts=(ctypes.c_uint64*n)(*(int(valid[c['trip_id']]['starts_on'].replace('-','')) for c in candidates))
        ids=(ctypes.c_uint64*n)(*(identities[c['trip_id']] for c in candidates))
        index,ties=ctypes.c_size_t(),ctypes.c_size_t()
        if choose(scores,starts,ids,n,ctypes.byref(index),ctypes.byref(ties))!=0:
            raise ValueError('native choice refused')
        return candidates[index.value],ties.value
    return select


def native_infer(policy,select):
    tree=ast.parse(inspect.getsource(policy.infer_trip))
    node=next(n for n in tree.body[0].body if isinstance(n,ast.If) and isinstance(n.test,ast.Name) and n.test.id=='candidates')
    assert isinstance(node.body[0],ast.Expr) and node.body[0].value.func.attr=='sort'
    node.body[:3]=ast.parse('top, ties = _native_choice(candidates, valid)').body
    namespace=dict(vars(policy),_native_choice=select)
    exec(compile(ast.fix_missing_locations(tree),'<native-ranking-variant>','exec'),namespace)
    return namespace['infer_trip']


def choose_equivalence(select):
    rng=random.Random(486)
    for iteration in range(250):
        n=rng.randint(1,160)
        candidates=[dict(trip_id=f'trip-{i}',score=rng.randint(-10,10)) for i in range(n)]
        valid={c['trip_id']:dict(starts_on=f'2026-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}') for c in candidates}
        ordered=sorted(candidates,key=lambda c:(-c['score'],valid[c['trip_id']]['starts_on'],c['trip_id']))
        expected=(ordered[0],sum(c['score']==ordered[0]['score'] for c in candidates))
        assert select(candidates,valid)==expected


def boundary_comparison(select):
    """Expose the conversion/call cost hidden by a native-only microbenchmark."""
    results = []
    for size in (1, 10, 70):
        candidates = [dict(trip_id=f'trip-{i}', score=i % 5) for i in range(size)]
        valid = {c['trip_id']: dict(starts_on='2026-10-01') for c in candidates}
        def python_choice():
            ordered = sorted(candidates, key=lambda c: (-c['score'], valid[c['trip_id']]['starts_on'], c['trip_id']))
            return ordered[0], sum(c['score'] == ordered[0]['score'] for c in candidates)
        assert python_choice() == select(candidates, valid)
        timings = {}
        for name, call in [('python', python_choice), ('rust_with_conversion_and_call', lambda: select(candidates, valid))]:
            samples = []
            for _ in range(5):
                start = time.perf_counter()
                for _ in range(2000):
                    call()
                samples.append((time.perf_counter() - start) * 1e6 / 2000)
            timings[name + '_us'] = statistics.median(samples)
        results.append(dict(candidates=size, **timings))
    return results


def measured(function,conn):
    conn.meter=Meter()
    start=time.perf_counter();result=function();elapsed=(time.perf_counter()-start)*1000
    return result,dict(total_ms=elapsed,sql_ms=conn.meter.sql_seconds*1000,sql_statements=conn.meter.statements)


def compare(functions,conn,repeats):
    expected=next(iter(functions.values()))()
    samples={key:[] for key in functions}
    for iteration in range(repeats):
        order=list(functions.items())
        if iteration%2:order.reverse()
        for name,fn in order:
            before=conn.total_changes
            result,measurement=measured(fn,conn)
            assert result==expected,name
            assert conn.total_changes==before
            samples[name].append(measurement)
    memory={}
    for name,fn in functions.items():
        tracemalloc.start();fn();_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        memory[name]=peak
    return dict(outputs_equal=True,output_sha256=hashlib.sha256(json.dumps(expected,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest(),samples=repeats,
        variants={name:dict(median_ms=statistics.median(v['total_ms'] for v in values),min_ms=min(v['total_ms'] for v in values),max_ms=max(v['total_ms'] for v in values),sql_ms_median=statistics.median(v['sql_ms'] for v in values),sql_statements=values[0]['sql_statements'],python_allocation_peak_bytes=memory[name]) for name,values in samples.items()})


def main(args):
    os.environ['WEBLEDGER_CARD_SCHEMA_POLICY']='require' if args.operational_db else 'create'
    os.environ['WEBLEDGER_UNIFIED_DB']='1'
    from app import automatic_classification as policy
    from webapp import card_flow,ledger_board
    old=baseline(args.baseline)
    native=None
    native_metadata={}
    if args.native_dll:
        start=time.perf_counter()
        select=native_selector(args.native_dll)
        native_metadata['dll_load_and_adapter_ms']=(time.perf_counter()-start)*1000
        choose_equivalence(select)
        native_metadata['selection_boundary']=boundary_comparison(select)
        native=native_infer(policy,select)
    with tempfile.TemporaryDirectory(prefix='cost-performance-compare-') as d:
        store,trips=setup_operational(args.operational_db) if args.operational_db else setup_synthetic(Path(d),args.rows,args.trips)
        try:
            functions={'baseline_python':lambda:old.plan(store.conn,trips),'optimized_python':lambda:policy.plan(store.conn,trips)}
            if native:
                def native_plan():
                    with patch.object(policy,'infer_trip',native):return policy.plan(store.conn,trips)
                functions['optimized_python_rust_choice']=native_plan
            result=dict(scope='operational-read-only' if args.operational_db else 'synthetic',baseline=args.baseline,rows=store.conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0],trips=len(trips),python=sys.version,plan=compare(functions,store.conn,args.repeats),native_choice_random_equivalence_cases=250 if native else 0,native_dll_bytes=args.native_dll.stat().st_size if args.native_dll else None,native_metadata=native_metadata,
                limits='SQL driver timing instrumented in all variants; warm in-process repeated plans; separate tracemalloc run excludes native heap/RSS; no HTTP or network; no production writes')
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
            print(json.dumps(result))
        finally:ledger_board.bind_store(None);store.conn.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',default='951fa9d2')
    p.add_argument('--rows',type=int,default=2000)
    p.add_argument('--trips',type=int,default=70)
    p.add_argument('--repeats',type=int,default=7)
    p.add_argument('--operational-db',type=Path)
    p.add_argument('--native-dll',type=Path)
    p.add_argument('--output',type=Path,required=True)
    main(p.parse_args())
