"""로컬 복구 사본과 역사 자료 분리. 외부 전송·원본 삭제 없음."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / '.local-archive' / 'lightweight-20261003'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def files():
    output = subprocess.check_output(
        ['rg', '--files', '--hidden', '-g', '!.git/**', '-g', '!.local-archive/**',
         '-g', '!**/__pycache__/**', '-g', '!**/node_modules/**',
         '-g', '!**/.venv/**', '-g', '!**/venv/**', '-g', '!**/.pytest_cache/**',
         '-g', '!outputs/**'], cwd=ROOT, text=True, encoding='utf-8')
    return sorted(Path(line) for line in output.splitlines() if line)


def bounded(path, root=ROOT):
    path = path.resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError('PATH_OUTSIDE_WORKSPACE')
    return path


def snapshot():
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    target = ARCHIVE / 'before.zip'
    if target.exists():
        raise FileExistsError('SNAPSHOT_ALREADY_EXISTS')
    inventory = {}
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in files():
            data = bounded(ROOT / relative).read_bytes()
            archive.writestr(relative.as_posix(), data)
            inventory[relative.as_posix()] = digest(data)
    with zipfile.ZipFile(target) as archive:
        if set(archive.namelist()) != set(inventory):
            raise RuntimeError('BACKUP_ENTRY_MISMATCH')
        for name, expected in inventory.items():
            if digest(archive.read(name)) != expected:
                raise RuntimeError('BACKUP_DIGEST_MISMATCH')
    manifest = {'created_at': datetime.now(timezone.utc).isoformat(),
                'archive_sha256': digest(target.read_bytes()), 'files': inventory}
    (ARCHIVE / 'before.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                        encoding='utf-8')
    print(json.dumps({'verified_files': len(inventory), 'archive': str(target)}))


def archive_copies():
    manifest = json.loads((ARCHIVE / 'before.json').read_text(encoding='utf-8'))
    moved = []
    for relative in files():
        if relative.parts[:2] != ('docs', 'handoff') or relative.suffix != '.py':
            continue
        source = bounded(ROOT / relative)
        expected = manifest['files'].get(relative.as_posix())
        if expected is None or digest(source.read_bytes()) != expected:
            raise RuntimeError('SOURCE_CHANGED_SINCE_BACKUP')
        target = bounded(ARCHIVE / 'history' / relative, ARCHIVE)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError('ARCHIVE_TARGET_EXISTS')
        source.rename(target)
        if digest(target.read_bytes()) != expected:
            raise RuntimeError('ARCHIVED_DIGEST_MISMATCH')
        moved.append(relative.as_posix())
    (ARCHIVE / 'moved.json').write_text(json.dumps(moved, ensure_ascii=False, indent=2),
                                       encoding='utf-8')
    print(json.dumps({'archived_python_copies': len(moved)}))


def archive_history():
    manifest = json.loads((ARCHIVE / 'before.json').read_text(encoding='utf-8'))
    protected = {'AGENT_EXECUTION_CONTRACT.md', 'DECISION_REGISTER.md',
                 'WEB_LEDGER_APP_SPEC.md', '비용분류_지시사항_원장.md',
                 '비용분류_명세_v2.md', '비용분류_명세_v2_검증계획.md'}
    moved = []
    for relative in files():
        old_document = relative.parts[0] == 'docs' and relative.suffix == '.md' and relative.name not in protected
        old_builder = relative.parts[0] == 'ledger' and relative.name.startswith('build_workbook_v') and relative.suffix == '.py'
        if not (old_document or old_builder):
            continue
        expected = manifest['files'].get(relative.as_posix())
        if expected is None:
            continue
        source = bounded(ROOT / relative)
        if digest(source.read_bytes()) != expected:
            raise RuntimeError('SOURCE_CHANGED_SINCE_BACKUP')
        target = bounded(ARCHIVE / 'history' / relative, ARCHIVE)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError('ARCHIVE_TARGET_EXISTS')
        source.rename(target)
        moved.append(relative.as_posix())
    (ARCHIVE / 'history-moved.json').write_text(json.dumps(moved, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'archived_history_files': len(moved)}))


def archive_meta():
    manifest = json.loads((ARCHIVE / 'before.json').read_text(encoding='utf-8'))
    names = ('docs/AGENT_EXECUTION_CONTRACT.md', 'docs/DECISION_REGISTER.md',
             'docs/WEB_LEDGER_APP_SPEC.md', 'CLAUDE.md', 'LOG.md', 'STATUS.md',
             'CANDIDATE_README.md', 'FAMILY_APPROVAL_REQUEST.md')
    moved = []
    for name in names:
        source = bounded(ROOT / name)
        if not source.is_file():
            continue
        expected = manifest['files'].get(name)
        if expected is None or digest(source.read_bytes()) != expected:
            raise RuntimeError('META_CHANGED_SINCE_BACKUP')
        target = bounded(ARCHIVE / 'history' / name, ARCHIVE)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError('ARCHIVE_TARGET_EXISTS')
        source.rename(target)
        moved.append(name)
    (ARCHIVE / 'meta-moved.json').write_text(json.dumps(moved,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'archived_meta_files':len(moved)}))


def archive_legacy():
    import ast
    manifest = json.loads((ARCHIVE/'before.json').read_text(encoding='utf-8'))
    candidates = json.loads((ARCHIVE/'legacy-candidates.json').read_text(encoding='utf-8'))
    modules = {'.'.join(Path(p).with_suffix('').parts) for p in candidates}
    for relative in files():
        if relative.parts[:2] == ('ledger','tests') and relative.suffix == '.py':
            if relative.name != '__init__.py':
                candidates.append(relative.as_posix())
        if relative.parts[0] == 'tools' and relative.suffix == '.py':
            tree=ast.parse((ROOT/relative).read_text(encoding='utf-8-sig'))
            refs=[]
            for node in ast.walk(tree):
                if isinstance(node,ast.Import):
                    refs.extend(a.name for a in node.names)
                elif isinstance(node,ast.ImportFrom):
                    refs.append(node.module or '')
            if modules.intersection(refs):
                candidates.append(relative.as_posix())
        if relative.parts[0] == 'tools' and any(word in relative.name for word in ('windows_cdp','windows_uia','headless_cdp','parallel_supervisor')):
            candidates.append(relative.as_posix())
    previous_path=ARCHIVE/'legacy-moved.json'
    moved=json.loads(previous_path.read_text(encoding='utf-8')) if previous_path.is_file() else []
    for name in sorted(set(candidates)):
        source=bounded(ROOT/name)
        if not source.is_file():
            continue
        expected=manifest['files'].get(name)
        if expected is None or digest(source.read_bytes()) != expected:
            raise RuntimeError('LEGACY_CHANGED_SINCE_BACKUP:'+name)
        target=bounded(ARCHIVE/'history'/name,ARCHIVE)
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            raise FileExistsError('ARCHIVE_TARGET_EXISTS')
        source.rename(target)
        moved.append(name)
    (ARCHIVE/'legacy-moved.json').write_text(json.dumps(moved,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'archived_legacy_files':len(moved)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('snapshot', 'archive-copies', 'archive-history', 'archive-meta', 'archive-legacy'))
    action = parser.parse_args().action
    {'snapshot':snapshot, 'archive-copies':archive_copies, 'archive-history':archive_history,
     'archive-meta':archive_meta,'archive-legacy':archive_legacy}[action]()
