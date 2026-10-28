"""Read-only RF-001 static call map. No application modules are imported.

Run with --summary for a bounded overview; default output retains all findings.
Edges are syntactic candidates, never proof of runtime use or authorization.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

from tools.audit_write_boundaries import analyze_source, dotted
from tools.runtime_dependency_catalog import tracked_paths

ROOT = Path(__file__).resolve().parents[1]
MAX_OUTPUT_BYTES = 1024 * 1024  # 1 MiB limit for config artifact
LIMITATIONS = [
    'Static syntax only; no runtime, authorization, or production-use proof.',
    'code_sha identifies base HEAD; analysis reads tracked working files, including staged edits.',
    'Only tracked Python in runtime_dependency_catalog candidate paths is read.',
    'Route decorators, HTTP tuples and do_METHOD dispatchers are candidates; route literals are omitted.',
    'Only lexical functions, explicit imports, and direct self methods resolve.',
    'Dynamic receivers, inheritance, rebinding, callbacks, generated SQL and middleware remain OPEN_QUESTION.',
    'No literal values, SQL text, function bodies or application imports are emitted.',
    'Static candidates are not promoted to actual permissions or active status.',
    'Output size capped at 1 MiB; full graph requires rerun without --summary.',
]

# Known store patterns for dynamic dispatch resolution.
# Maps variable name / call pattern to the module/class providing the methods.
STORE_PATTERNS = {
    '_active_store': 'webapp.ledger_store.LedgerStore',
    '_ACCESS': 'webapp.access_control.AccessStore',
    'store': 'webapp.ledger_store.LedgerStore',  # common variable name after _active_store()
    'board': 'webapp.ledger_store.LedgerStore',  # used in some handlers
    'access_store': 'webapp.access_control.AccessStore',
    'card_store': 'webapp.ledger_store.LedgerStore',
}


def module_name(path):
    parts = list(Path(path).with_suffix('').parts)
    if parts[-1] == '__init__':
        parts.pop()
    return '.'.join(parts)


class Index(ast.NodeVisitor):
    def __init__(self, path):
        self.path = path
        self.scope = []
        self.classes = []
        self.functions = []
        self.nodes = []
        self.calls = []
        self.routes = []
        self.imports = {}
        self.assignments = {}  # variable -> inferred type/module

    def visit_Import(self, node):
        if not self.scope:
            for alias in node.names:
                self.imports[alias.asname or alias.name.split('.')[0]] = alias.name if alias.asname else alias.name.split('.')[0]

    def visit_ImportFrom(self, node):
        if self.scope:
            return
        package = module_name(self.path).split('.')
        if not self.path.endswith('/__init__.py'):
            package.pop()
        prefix = package[:len(package) - node.level + 1] if node.level else []
        base = '.'.join(prefix + ([node.module] if node.module else []))
        for alias in node.names:
            if alias.name != '*':
                self.imports[alias.asname or alias.name] = '.'.join(filter(None, (base, alias.name)))

    def visit_Assign(self, node):
        # Track simple assignments: var = _active_store() or var = _ACCESS
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            var_name = node.targets[0].id
            if isinstance(node.value, ast.Call):
                func_name = dotted(node.value.func)
                if func_name in STORE_PATTERNS:
                    self.assignments[var_name] = STORE_PATTERNS[func_name]
            elif isinstance(node.value, ast.Name):
                name = node.value.id
                if name in STORE_PATTERNS:
                    self.assignments[var_name] = STORE_PATTERNS[name]
                elif name in self.assignments:
                    self.assignments[var_name] = self.assignments[name]
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        # Track annotated assignments: store: LedgerStore = ...
        if isinstance(node.target, ast.Name):
            var_name = node.target.id
            if node.value:
                self.visit(node.value)
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self.scope.append(node.name)
        self.classes.append('.'.join(self.scope))
        for statement in node.body:
            self.visit(statement)
        self.classes.pop()
        self.scope.pop()

    def visit_FunctionDef(self, node):
        self.scope.append(node.name)
        symbol = '.'.join(self.scope)
        self.nodes.append({'path': self.path, 'symbol': symbol, 'line': node.lineno,
                           'end_line': node.end_lineno})
        if node.name in {'do_GET', 'do_POST', 'do_PUT', 'do_PATCH', 'do_DELETE', 'do_HEAD', 'do_OPTIONS'}:
            self.routes.append({'path': self.path, 'symbol': symbol, 'line': node.lineno,
                                'status': 'STATIC_CANDIDATE'})
        for decorator in node.decorator_list:
            name = dotted(decorator.func if isinstance(decorator, ast.Call) else decorator)
            if name.split('.')[-1] in {'get', 'post', 'put', 'patch', 'delete', 'route'}:
                self.routes.append({'path': self.path, 'symbol': symbol, 'line': decorator.lineno,
                                    'status': 'STATIC_CANDIDATE'})
        self.functions.append(symbol)
        for statement in node.body:
            self.visit(statement)
        self.functions.pop()
        self.scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node):
        call_name = dotted(node.func) or '<dynamic>'
        source_symbol = self.functions[-1] if self.functions else '<module>'
        self.calls.append({'source': f'{self.path}:{source_symbol}',
                           'path': self.path, 'line': node.lineno, 'call': call_name,
                           '_class': self.classes[-1] if self.classes else None,
                           '_function': source_symbol,
                           '_assignments': dict(self.assignments)})
        self.generic_visit(node)

    def visit_Tuple(self, node):
        if (len(node.elts) == 3 and isinstance(node.elts[0], ast.Constant)
                and node.elts[0].value in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'}):
            name = dotted(node.elts[2])
            if name.startswith('self.') and self.classes:
                name = self.classes[-1] + name[4:]
            if name:
                self.routes.append({'path': self.path, 'symbol': name, 'line': node.lineno,
                                    'status': 'STATIC_CANDIDATE'})
        self.generic_visit(node)


def resolve_store_method(call_name, assignments, module_paths, symbols):
    """Resolve store.method() calls using known patterns and assignments."""
    if '.' not in call_name:
        return None
    receiver, method = call_name.split('.', 1)
    # Check direct assignments
    if receiver in assignments:
        store_class = assignments[receiver]
        # Map store class to module path
        if store_class == 'webapp.ledger_store.LedgerStore':
            target_path = 'webapp/ledger_store.py'
        elif store_class == 'webapp.access_control.AccessStore':
            target_path = 'webapp/access_control.py'
        else:
            return None
        candidate = f'{target_path}:{store_class.split(".")[-1]}.{method}'
        if candidate in symbols:
            return candidate
    # Check STORE_PATTERNS for direct calls like _active_store().method()
    if receiver in STORE_PATTERNS:
        store_class = STORE_PATTERNS[receiver]
        if store_class == 'webapp.ledger_store.LedgerStore':
            target_path = 'webapp/ledger_store.py'
        elif store_class == 'webapp.access_control.AccessStore':
            target_path = 'webapp/access_control.py'
        else:
            return None
        candidate = f'{target_path}:{store_class.split(".")[-1]}.{method}'
        if candidate in symbols:
            return candidate
    return None


def build_repro_command(root, call):
    """Generate a reproduction command for an OPEN_QUESTION call."""
    path = call['path']
    line = call['line']
    call_name = call['call']
    return f"python -m tools.audit_write_boundaries {path} --pretty  # line {line}: {call_name}"


def build_map(root=ROOT):
    root = Path(root).resolve()
    result = {'schema': 'rf001-call-map/v1', 'mode': 'static_ast_only',
              'files': [], 'symbols': [], 'calls': [], 'routes': [], 'effects': [],
              'errors': [], 'limitations': LIMITATIONS}
    try:
        result['code_sha'] = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'],
            capture_output=True, text=True, check=True).stdout.strip()
    except subprocess.CalledProcessError:
        result['code_sha'] = None
    try:
        paths = sorted(p for p in tracked_paths(root) if p.suffix == '.py')
    except (OSError, subprocess.CalledProcessError):
        result['errors'].append({'code': 'GIT_METADATA_ERROR'})
        return result
    indexes = {}
    module_paths = {}
    for path in paths:
        rel = path.relative_to(root).as_posix()
        if not path.resolve().is_relative_to(root) or any(p.is_symlink() for p in [path, *path.parents] if p != root):
            result['errors'].append({'path': rel, 'code': 'INDIRECT_SOURCE_PATH'})
            continue
        try:
            source = path.read_text(encoding='utf-8-sig')
            tree = ast.parse(source)
        except (OSError, UnicodeError):
            result['errors'].append({'path': rel, 'code': 'SOURCE_READ_ERROR'})
            continue
        except SyntaxError as exc:
            result['errors'].append({'path': rel, 'code': 'SYNTAX_ERROR', 'line': exc.lineno})
            continue
        index = Index(rel)
        index.visit(tree)
        indexes[rel] = index
        module_paths[module_name(rel)] = rel
        result['files'].append({'path': rel, 'symbols': len(index.nodes)})
        result['symbols'].extend(index.nodes)
        result['routes'].extend(index.routes)
        for finding in analyze_source(source, rel)['findings']:
            if finding['kind'] not in {'sql_unknown', 'sql_write', 'sql_read_or_other', 'write_like_call'}:
                continue
            owners = [n for n in index.nodes if n['line'] <= finding['line'] <= n['end_line']]
            owner = max(owners, key=lambda n: n['line'])['symbol'] if owners else '<module>'
            result['effects'].append(dict(finding, path=rel, owner=f'{rel}:{owner}'))
    symbols = {f"{n['path']}:{n['symbol']}" for n in result['symbols']}
    for rel, index in indexes.items():
        for raw in index.calls:
            call = dict(raw)
            name = call['call']
            cls = call.pop('_class')
            function = call.pop('_function')
            assignments = call.pop('_assignments', {})
            candidates = []
            # Try store pattern resolution first
            store_target = resolve_store_method(name, assignments, module_paths, symbols)
            if store_target:
                candidates.append(store_target)
            # Fallback to existing resolution
            if name.startswith('self.') and cls:
                candidates.append(f'{rel}:{cls}.{name[5:]}')
            elif '.' not in name:
                scope = function.split('.')[:-1]
                while scope:
                    if '.'.join(scope) != cls:
                        candidates.append(f'{rel}:{".".join(scope)}.{name}')
                    scope.pop()
                candidates.append(f'{rel}:{name}')
            head, *tail = name.split('.')
            if head in index.imports:
                full = '.'.join([index.imports[head], *tail])
                for module, target_path in module_paths.items():
                    if full.startswith(module + '.'):
                        candidates.append(f'{target_path}:{full[len(module)+1:]}')
            target = next((c for c in candidates if c in symbols), None)
            call['status'] = 'STATIC_CANDIDATE' if target else 'OPEN_QUESTION'
            if target:
                call['target'] = target
            # Add reproduction command for OPEN_QUESTION
            if call['status'] == 'OPEN_QUESTION':
                call['repro'] = build_repro_command(root, call)
            result['calls'].append(call)
            if name.split('.')[0] in {'subprocess', 'requests', 'httpx', 'urllib', 'socket', 'smtplib'}:
                result['effects'].append({'path': rel, 'line': call['line'], 'owner': call['source'],
                    'call': name, 'kind': 'external_candidate', 'status': 'OPEN_QUESTION'})
    return result


def truncate_to_limit(obj, limit=MAX_OUTPUT_BYTES):
    """Truncate JSON output to size limit by removing less critical fields."""
    import copy
    obj = copy.deepcopy(obj)
    # First, try removing calls details (keep counts)
    if len(json.dumps(obj, ensure_ascii=False).encode('utf-8')) > limit:
        obj['calls'] = [{'status': c['status']} for c in obj['calls']]
    if len(json.dumps(obj, ensure_ascii=False).encode('utf-8')) > limit:
        obj['symbols'] = [{'path': s['path'], 'symbol': s['symbol']} for s in obj['symbols']]
    if len(json.dumps(obj, ensure_ascii=False).encode('utf-8')) > limit:
        obj['effects'] = [{'kind': e['kind'], 'status': e['status'], 'table': e.get('table')} for e in obj['effects']]
    if len(json.dumps(obj, ensure_ascii=False).encode('utf-8')) > limit:
        obj['routes'] = [{'path': r['path'], 'symbol': r['symbol']} for r in obj['routes']]
    return obj


def summary(result):
    return {'schema': result['schema'], 'mode': result['mode'], 'code_sha': result['code_sha'],
            'counts': {key: len(result[key]) for key in ('files', 'symbols', 'calls', 'routes', 'effects', 'errors')},
            'call_status': dict(Counter(c['status'] for c in result['calls'])),
            'routes': result['routes'], 'errors': result['errors'],
            'limitations': result['limitations'] + ['Summary omits graph details; rerun without --summary for all locations.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--summary', action='store_true')
    parser.add_argument('--limit-output', action='store_true', help='Enforce 1 MiB output limit')
    args = parser.parse_args(argv)
    result = build_map(args.root)
    if args.limit_output:
        result = truncate_to_limit(result)
    output = json.dumps(summary(result) if args.summary else result, ensure_ascii=False, indent=2)
    if args.limit_output and len(output.encode('utf-8')) > MAX_OUTPUT_BYTES:
        # Final truncation if still over limit
        output = output[:MAX_OUTPUT_BYTES] + '\n... [TRUNCATED]'
    print(output)
    return 2 if result['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())