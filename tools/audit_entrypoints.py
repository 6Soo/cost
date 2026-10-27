"""RF-001 static callable/route candidates. No source execution or DB access."""
from __future__ import annotations
import argparse
import ast
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted(node.value)
        return parent + '.' + node.attr if parent else node.attr
    return ''


def route_literal(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.fullmatch(r'/[A-Za-z0-9_./-]*', node.value):
        return node.value
    return None


class Inventory(ast.NodeVisitor):
    def __init__(self):
        self.stack = []
        self.callables = []
        self.routes = []
        self.calls = []
        self.main_guard = False

    def visit_ClassDef(self, node):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node):
        self.stack.append(node.name)
        self.callables.append({'name': '.'.join(self.stack), 'line': node.lineno,
                               'async': isinstance(node, ast.AsyncFunctionDef)})
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def add_route(self, node, literal, match):
        route = route_literal(literal)
        if route is not None:
            method = next((part[3:] for part in reversed(self.stack) if part in ('do_GET', 'do_POST', 'do_PUT', 'do_DELETE')), 'UNKNOWN')
            self.routes.append({'route': route, 'method': method, 'match': match,
                                'handler': '.'.join(self.stack), 'line': node.lineno,
                                'status': 'STATIC_CANDIDATE'})

    def visit_Compare(self, node):
        operands = [node.left, *node.comparators]
        if any(isinstance(x, ast.Name) and x.id == '__name__' for x in operands) and any(
            isinstance(x, ast.Constant) and x.value == '__main__' for x in operands
        ):
            self.main_guard = True
        if len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq):
            for expression, literal in ((node.left, node.comparators[0]), (node.comparators[0], node.left)):
                if dotted(expression).split('.')[-1] in ('path', 'route'):
                    self.add_route(node, literal, 'equals')
        self.generic_visit(node)

    def visit_Call(self, node):
        name = dotted(node.func)
        if name:
            self.calls.append({'caller': '.'.join(self.stack) or '<module>', 'callee': name,
                               'line': node.lineno, 'resolution': 'UNVERIFIED'})
        if isinstance(node.func, ast.Attribute) and node.func.attr == 'startswith' and node.args:
            if dotted(node.func.value).split('.')[-1] in ('path', 'route'):
                self.add_route(node, node.args[0], 'prefix')
        self.generic_visit(node)


def analyze(source, path):
    visitor = Inventory()
    visitor.visit(ast.parse(source))
    return {'path': path, 'owner_module': path.removesuffix('.py').replace('/', '.'),
            'main_guard_candidate': visitor.main_guard, 'callables': visitor.callables,
            'routes': visitor.routes, 'calls': visitor.calls}


def inventory(root=ROOT):
    root = root.resolve()
    result = {'schema_version': 1, 'mode': 'static_read_only', 'modules': [], 'errors': [],
              'open_questions': ['Aliases, generated routes, call targets and runtime/background activation require source/runtime confirmation.',
                                 'This inventory does not prove authorization, write ownership, active use or audit delivery.']}
    try:
        paths = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'], check=True,
                               capture_output=True).stdout.split(b'\0')
    except (OSError, subprocess.CalledProcessError) as exc:
        result['errors'].append({'code': 'GIT_METADATA_ERROR', 'error_type': type(exc).__name__})
        return result
    for raw in paths:
        if not raw:
            continue
        relative = raw.decode('utf-8')
        parts = Path(relative).parts
        if not relative.endswith('.py') or 'tests' in parts or Path(relative).name.startswith('test_'):
            continue
        if relative != 'run_candidate.py' and not relative.startswith(('app/', 'webapp/', 'ledger/domain/')):
            continue
        path = root / relative
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            result['errors'].append({'path': relative, 'code': 'INDIRECT_SOURCE_PATH'})
            continue
        try:
            result['modules'].append(analyze(path.read_text(encoding='utf-8-sig'), relative))
        except SyntaxError as exc:
            result['errors'].append({'path': relative, 'code': 'SYNTAX_ERROR', 'line': exc.lineno})
        except (OSError, UnicodeError) as exc:
            result['errors'].append({'path': relative, 'code': 'SOURCE_READ_ERROR', 'error_type': type(exc).__name__})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--summary', action='store_true')
    args = parser.parse_args(argv)
    result = inventory(args.root)
    if args.summary:
        output = {'modules': len(result['modules']), 'route_candidates': sum(len(m['routes']) for m in result['modules']),
                  'callables': sum(len(m['callables']) for m in result['modules']), 'errors': result['errors']}
    else:
        output = result
    print(json.dumps(output, ensure_ascii=True, indent=2))
    return 2 if result['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
