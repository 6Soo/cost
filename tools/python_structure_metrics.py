"""Reproducible static metrics for tracked Python; never import product code.

Branch counts are AST decision counts, not a runtime profile or full McCabe
analysis. Duplicates ignore function names/docstrings, but retain identifiers
and constants. SQL/template strings remain in physical line counts.
"""
from __future__ import annotations

import argparse
import ast
from collections import defaultdict
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def measure(root=ROOT, revision=None):
    if revision:
        content = subprocess.check_output(['git', '-C', str(root), 'archive', '--format=tar', revision, '--', '*.py'])
        with tarfile.open(fileobj=io.BytesIO(content)) as archive:
            sources = {item.name: archive.extractfile(item).read().decode('utf-8-sig')
                       for item in archive if item.isfile()}
    else:
        raw = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z'])
        sources = {p.decode('utf-8'): (root / p.decode('utf-8')).read_text(encoding='utf-8-sig')
                   for p in raw.split(b'\0') if p.endswith(b'.py')}
    files, functions, clones, dependencies, errors = [], [], defaultdict(list), set(), []
    for path, source in sorted(sources.items()):
        group = 'tests' if 'tests' in Path(path).parts or Path(path).name.startswith('test_') else 'product'
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            errors.append({'path': path, 'line': exc.lineno})
            continue
        scope = ('tests' if group == 'tests' else 'runtime' if Path(path).parts[0] in ('app', 'webapp', 'ledger')
                 else 'historical' if Path(path).parts[0] == 'outputs' else 'maintenance')
        files.append({'path': path, 'group': group, 'scope': scope, 'lines': len(source.splitlines())})
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [('.' * node.level) + (node.module or '')]
                dependencies.update((path, name) for name in names)
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            branches = sum(isinstance(n, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.comprehension)) for n in ast.walk(node))
            branches += sum(len(n.values) - 1 for n in ast.walk(node) if isinstance(n, ast.BoolOp))
            record = {'path': path, 'name': node.name, 'line': node.lineno,
                      'lines': node.end_lineno - node.lineno + 1, 'branches': branches, 'group': group, 'scope': scope}
            functions.append(record)
            body = list(node.body)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                body.pop(0)
            if sum(1 for stmt in body for _ in ast.walk(stmt)) >= 35:
                normalized = ast.dump(ast.Module(body=body, type_ignores=[]), include_attributes=False)
                clones[hashlib.sha256(normalized.encode()).hexdigest()].append(record)
    duplicate_groups = [values for values in clones.values() if len(values) > 1]
    summary = {}
    for group in ('product', 'tests'):
        fs = [f for f in functions if f['group'] == group]
        duplicate = [[r for r in rows if r['group'] == group] for rows in duplicate_groups]
        summary[group] = {'files': sum(f['group'] == group for f in files),
                          'lines': sum(f['lines'] for f in files if f['group'] == group),
                          'functions': len(fs), 'branches': sum(f['branches'] for f in fs),
                          'functions_over_100_lines': sum(f['lines'] > 100 for f in fs),
                          'duplicate_function_copies': sum(max(0, len(rows) - 1) for rows in duplicate)}
    scopes = {scope: {'files': sum(f['scope'] == scope for f in files),
                      'lines': sum(f['lines'] for f in files if f['scope'] == scope),
                      'functions_over_100_lines': sum(f['scope'] == scope and f['lines'] > 100 for f in functions),
                      'duplicate_function_copies': sum(max(0, sum(r['scope'] == scope for r in rows) - 1) for rows in duplicate_groups)}
              for scope in ('runtime', 'maintenance', 'historical', 'tests')}
    return {'method': __doc__, 'revision': revision or 'index-paths/working-content', 'summary': summary, 'scopes': scopes, 'files': files,
            'functions': functions, 'duplicate_groups': duplicate_groups,
            'import_edges': len(dependencies), 'syntax_errors': errors,
            'largest_functions': sorted(functions, key=lambda f: f['branches'], reverse=True)[:30]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--revision', help='Read a committed tree without checking it out')
    args = parser.parse_args()
    report = measure(revision=args.revision)
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('summary', 'scopes', 'import_edges', 'syntax_errors')}, indent=2))


if __name__ == '__main__':
    main()
