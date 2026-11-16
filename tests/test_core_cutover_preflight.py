"""Unit tests for the offline core-cutover preflight test double.

The preflight verifies recorded, copied inputs only. These tests exercise the contract with an injected
subprocess runner and temporary synthetic files: no live host path, no network, no file output.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from tools import core_cutover_preflight as cp


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setup_trees(tmp_path):
    host = tmp_path / 'host'
    (host / 'data' / 'backups').mkdir(parents=True)
    repo = tmp_path / 'repo'
    (repo / 'core').mkdir(parents=True)
    (repo / 'config').mkdir()
    (repo / 'core' / 'known-diffs.txt').write_text('# synthetic\n', encoding='utf-8')
    (repo / 'config' / 'refund-pairing.json').write_text('{"synthetic": true}\n', encoding='utf-8')
    (repo / 'config' / 'ota-matching-defaults.json').write_text('{"synthetic": true}\n', encoding='utf-8')
    db = tmp_path / 'copy' / 'board-copy.sqlite'
    db.parent.mkdir()
    db.write_bytes(b'fake-board-bytes')
    ota = tmp_path / 'copy' / 'ota-input.json'
    ota.write_text('{"kind": "ota"}', encoding='utf-8')
    return host, repo, db, ota, sha(db), sha(ota)


class FakeRunner:
    """Stands in for subprocess: records argv, returns canned version/shadow results."""

    def __init__(self, version=(0, 'costcore 0.1.0', ''), shadow=(0, '', ''), mutate=None):
        self.calls = []
        self.version = version
        self.shadow = shadow
        self.mutate = mutate

    def __call__(self, argv):
        self.calls.append(list(argv))
        if self.mutate is not None:
            self.mutate()
        if len(argv) == 2 and argv[1] == '--version':
            return self.version
        return self.shadow


def shadow_json(refund=(2, 2), ota=(3, 3), status='PASS', unlisted=None):
    part = lambda p: None if p is None else {'python': p[0], 'rust': p[1]}
    return json.dumps({'status': status, 'refund': part(refund), 'ota': part(ota),
                       'types': [], 'unlisted': unlisted if unlisted is not None else []})


def ready_args(tmp_path, runner=None):
    host, repo, db, ota, db_sha, ota_sha = setup_trees(tmp_path)
    return {'host_root': str(host), 'db': str(db), 'ota_input': str(ota), 'repo_root': str(repo),
            'costcore_bin': '', 'expected_binary_sha256': None}, runner


def run(tmp_path, runner=None, **overrides):
    args, fake = ready_args(tmp_path, runner)
    binary = tmp_path / 'copy' / 'costcore'
    binary.write_bytes(b'#!/bin/sh\necho costcore\n')
    args.update({'costcore_bin': str(binary), 'expected_binary_sha256': sha(binary)})
    args.update(overrides)
    return cp.check(**args, runner=fake if runner is None else runner), fake


@pytest.mark.parametrize('missing', ['db', 'ota_input', 'costcore_bin'])
def test_missing_required_paths_block(tmp_path, missing):
    args, fake = ready_args(tmp_path)
    args[missing] = ''
    args['expected_binary_sha256'] = None
    result = cp.check(**args, runner=fake)
    assert result['status'] == 'BLOCKED'
    assert result['code'] == 'INPUTS_REQUIRED'


def test_missing_binary_and_ota_block(tmp_path, capsys):
    args, fake = ready_args(tmp_path)
    args['costcore_bin'] = str(tmp_path / 'nope' / 'costcore')
    args['expected_binary_sha256'] = '0' * 64
    assert cp.check(**args, runner=fake)['code'] == 'BINARY_NOT_FOUND'
    binary = tmp_path / 'copy' / 'costcore'
    binary.write_bytes(b'bin')
    args['costcore_bin'] = str(binary)
    args['expected_binary_sha256'] = None
    assert cp.check(**args, runner=fake)['code'] == 'BINARY_SHA_REQUIRED'
    args['expected_binary_sha256'] = 'zz'
    assert cp.check(**args, runner=fake)['code'] == 'BINARY_SHA_INVALID'
    assert cp.main(['--host-root', str(args['host_root']), '--db', str(tmp_path / 'nope.sqlite'),
                    '--ota-input', str(tmp_path / 'nope.json'), '--costcore-bin', str(binary),
                    '--expected-binary-sha256', '0' * 64, '--repo-root', str(args['repo_root'])]) == 1
    assert capsys.readouterr().out.strip().startswith('{')


def test_live_db_and_aliases_are_refused(tmp_path):
    host, repo, db, ota, _, _ = setup_trees(tmp_path)
    live = host / 'data' / 'board.sqlite'
    live.write_bytes(db.read_bytes())
    binary = tmp_path / 'costcore'
    binary.write_bytes(b'bin')
    base = {'host_root': str(host), 'ota_input': str(ota), 'repo_root': str(repo),
            'costcore_bin': str(binary), 'expected_binary_sha256': sha(binary)}

    def run(args):
        return cp.check(**args, runner=FakeRunner(version=(0, 'costcore 0.1.0', ''),
                                                  shadow=(0, shadow_json(), '')))

    assert run(dict(base, db=str(live)))['code'] == 'DB_IS_LIVE'
    link = tmp_path / 'copy' / 'hardlink.sqlite'
    try:
        os.link(live, link)
    except (OSError, NotImplementedError):
        return
    assert run(dict(base, db=str(link)))['code'] == 'DB_IS_LIVE'
    try:
        sym = tmp_path / 'copy' / 'sym.sqlite'
        os.symlink(live, sym)
    except (OSError, NotImplementedError):
        return
    assert run(dict(base, db=str(sym)))['code'] == 'DB_IS_SYMLINK'


def test_binary_hash_and_version_checked(tmp_path):
    host, repo, db, ota, _, _ = setup_trees(tmp_path)
    binary = tmp_path / 'costcore'
    binary.write_bytes(b'bin')
    base = {'host_root': str(host), 'db': str(db), 'ota_input': str(ota), 'repo_root': str(repo),
            'costcore_bin': str(binary)}
    fake = FakeRunner(version=(1, '', 'no version'))
    assert cp.check(**base, expected_binary_sha256=sha(binary), runner=fake)['code'] == 'BINARY_VERSION_FAILED'
    fake = FakeRunner(version=(0, 'costcore 0.1.0', ''), shadow=(0, shadow_json(), ''))
    assert cp.check(**base, expected_binary_sha256='f' * 64, runner=fake)['code'] == 'BINARY_SHA_MISMATCH'
    fake = FakeRunner(version=(0, 'costcore 0.1.0', ''), shadow=(0, shadow_json(), ''))
    assert cp.check(**base, expected_binary_sha256=sha(binary), runner=fake)['status'] == 'READY'


@pytest.mark.parametrize('name,code', [('exit', 'SHADOW_EXIT_NONZERO'),
                                       ('status', 'SHADOW_STATUS_NOT_PASS'),
                                       ('unlisted', 'SHADOW_UNLISTED'),
                                       ('refund-zero', 'SHADOW_ZERO_COUNT'),
                                       ('ota-zero', 'SHADOW_ZERO_COUNT'),
                                       ('mismatch', 'SHADOW_COUNT_MISMATCH')])
def test_shadow_failure_is_closed(tmp_path, name, code):
    host, repo, db, ota, _, _ = setup_trees(tmp_path)
    binary = tmp_path / 'costcore'
    binary.write_bytes(b'bin')
    if name == 'exit':
        shadow = (1, '', 'boom')
    elif name == 'status':
        shadow = (0, shadow_json(status='FAIL'), '')
    elif name == 'unlisted':
        shadow = (0, shadow_json(unlisted=['B-C|ota_link|full|differs']), '')
    elif name in ('refund-zero', 'ota-zero'):
        shadow = (0, shadow_json(refund=(0, 0) if name == 'refund-zero' else (2, 2),
                                 ota=(0, 0) if name == 'ota-zero' else (3, 3)), '')
    else:
        shadow = (0, shadow_json(refund=(2, 3)), '')
    args = {'host_root': str(host), 'db': str(db), 'ota_input': str(ota), 'repo_root': str(repo),
            'costcore_bin': str(binary), 'expected_binary_sha256': sha(binary)}
    result = cp.check(**args, runner=FakeRunner(shadow=shadow))
    assert result['status'] == 'BLOCKED' and result['code'] == code
    assert str(db) not in json.dumps(result) and str(binary) not in json.dumps(result)


def test_shadow_command_and_version_are_pinned(tmp_path):
    result, fake = run(tmp_path, FakeRunner(shadow=(0, shadow_json(), '')))
    assert result['status'] == 'READY'
    assert fake.calls[0] == [str(tmp_path / 'copy' / 'costcore'), '--version']
    shadow_argv = fake.calls[1]
    assert shadow_argv[0] == str(tmp_path / 'copy' / 'costcore')
    assert shadow_argv[1] == 'shadow-links'
    for flag in ('--host-root', '--db', '--ota-input', '--repo-root'):
        assert flag in shadow_argv
    assert result['inputs_changed'] is False
    assert result['limits']


def test_input_change_during_run_is_detected(tmp_path):
    def mutate():
        (tmp_path / 'copy' / 'board-copy.sqlite').write_bytes(b'changed')

    result, _ = run(tmp_path, FakeRunner(shadow=(0, shadow_json(), ''), mutate=mutate))
    assert result['status'] == 'BLOCKED' and result['code'] == 'INPUTS_CHANGED'
    assert result['changed'] == ['db']


def test_ok_requires_both_regions_nonzero_and_equal(tmp_path):
    host, repo, db, ota, _, _ = setup_trees(tmp_path)
    binary = tmp_path / 'costcore'
    binary.write_bytes(b'bin')
    base = {'host_root': str(host), 'db': str(db), 'ota_input': str(ota), 'repo_root': str(repo),
            'costcore_bin': str(binary), 'expected_binary_sha256': sha(binary)}
    for refund, ota_part, code in [(None, (3, 3), 'SHADOW_REGIONS_INVALID'),
                                   ((2, 2), None, 'SHADOW_REGIONS_INVALID')]:
        fake = FakeRunner(shadow=(0, shadow_json(refund=refund, ota=ota_part), ''))
        assert cp.check(**base, runner=fake)['code'] == code


def test_binary_version_must_match_the_real_format(tmp_path):
    host, repo, db, ota, _, _ = setup_trees(tmp_path)
    binary = tmp_path / 'costcore'
    binary.write_bytes(b'bin')
    base = {'host_root': str(host), 'db': str(db), 'ota_input': str(ota), 'repo_root': str(repo),
            'costcore_bin': str(binary), 'expected_binary_sha256': sha(binary)}
    assert cp.check(**base, runner=FakeRunner(version=(0, '', '')))['code'] == 'BINARY_VERSION_INVALID'
    assert cp.check(**base, runner=FakeRunner(version=(0, 'not-a-version', '')))['code'] == 'BINARY_VERSION_INVALID'
    result = cp.check(**base, runner=FakeRunner(version=(0, 'costcore 0.1.0', ''),
                                                shadow=(0, shadow_json(), '')))
    assert result['status'] == 'READY'


def test_binary_replaced_between_checks_is_refused(tmp_path):
    host, repo, db, ota, _, _ = setup_trees(tmp_path)
    binary = tmp_path / 'costcore'
    binary.write_bytes(b'bin')
    base = {'host_root': str(host), 'db': str(db), 'ota_input': str(ota), 'repo_root': str(repo),
            'costcore_bin': str(binary), 'expected_binary_sha256': sha(binary)}

    def swap():
        binary.write_bytes(b'substituted')

    assert cp.check(**base, runner=FakeRunner(version=(0, 'costcore 0.1.0', ''), mutate=swap)) \
        ['code'] == 'BINARY_CHANGED'


def test_db_sidecar_journal_is_refused(tmp_path):
    host, repo, db, ota, _, _ = setup_trees(tmp_path)
    binary = tmp_path / 'costcore'
    binary.write_bytes(b'bin')
    sidecar = str(db) + '-wal'
    Path(sidecar).write_bytes(b'journal')
    sidecar_args = {'host_root': str(host), 'db': str(db), 'ota_input': str(ota), 'repo_root': str(repo),
                    'costcore_bin': str(binary), 'expected_binary_sha256': sha(binary)}
    result = cp.check(**sidecar_args, runner=FakeRunner(version=(0, 'costcore 0.1.0', ''), shadow=(0, shadow_json(), '')))
    assert result['status'] == 'BLOCKED' and result['code'] == 'DB_SIDECAR_PRESENT'
    Path(sidecar).unlink()
    result = cp.check(**sidecar_args,
                      runner=FakeRunner(version=(0, 'costcore 0.1.0', ''), shadow=(0, shadow_json(), ''),
                                        mutate=lambda: Path(sidecar).write_bytes(b'x')))
    assert result['status'] == 'BLOCKED' and result['code'] == 'DB_SIDECAR_PRESENT'


def test_repo_side_evidence_checked(tmp_path):
    host, repo, db, ota, _, _ = setup_trees(tmp_path)
    binary = tmp_path / 'costcore'
    binary.write_bytes(b'bin')
    args = {'host_root': str(host), 'db': str(db), 'ota_input': str(ota), 'repo_root': str(repo),
            'costcore_bin': str(binary), 'expected_binary_sha256': sha(binary)}
    (repo / 'config' / 'ota-matching-defaults.json').unlink()
    assert cp.check(**args, runner=FakeRunner(version=(0, 'costcore 0.1.0', ''),
                                              shadow=(0, shadow_json(), '')))['code'] == 'REPO_FILE_MISSING'
    (repo / 'config' / 'ota-matching-defaults.json').write_text('{}\n', encoding='utf-8')
    result = cp.check(**args, runner=FakeRunner(version=(0, 'costcore 0.1.0', ''), shadow=(0, shadow_json(),
                                                                                              ''),
                                                mutate=lambda: (repo / 'config' /
                                                                'refund-pairing.json').write_text('{}\n')))
    assert result['status'] == 'BLOCKED' and result['code'] == 'REPO_FILE_CHANGED'
    result = cp.check(**args, runner=FakeRunner(version=(0, 'costcore 0.1.0', ''), shadow=(0, shadow_json(), '')))
    assert result['status'] == 'READY'
    assert result['repo_files']['core/known-diffs.txt'] == sha(repo / 'core' / 'known-diffs.txt')


def test_main_prints_aggregate_json_only(tmp_path, capsys):
    host, repo, db, ota, _, _ = setup_trees(tmp_path)
    binary = tmp_path / 'costcore'
    binary.write_bytes(b'bin')
    rc = cp.main(['--host-root', str(host), '--db', str(db), '--ota-input', str(ota),
                  '--costcore-bin', str(binary), '--expected-binary-sha256', sha(binary),
                  '--repo-root', str(repo)])
    out = capsys.readouterr().out
    assert rc == 1
    assert out.count('\n') == 1 and out.strip().startswith('{')
    payload = json.loads(out)
    assert payload['status'] == 'BLOCKED' and payload['code'] == 'BINARY_VERSION_FAILED'


def test_removed_repo_evidence_during_run_is_a_json_block(tmp_path):
    fake = FakeRunner(shadow=(0, shadow_json(), ''))
    def runner(argv):
        if argv[1] == 'shadow-links':
            (tmp_path / 'repo/config/refund-pairing.json').unlink()
        return fake(argv)
    result, _ = run(tmp_path, runner)
    assert result['status'] == 'BLOCKED' and result['code'] == 'REPO_FILE_CHANGED'


def test_unlisted_scope_never_leaks_untrusted_source_text(tmp_path):
    secret = 'synthetic_private_booking_ref'
    result, _ = run(tmp_path, FakeRunner(shadow=(0, shadow_json(unlisted=[f'B-C|ota_link|{secret}|differs']), '')))
    assert result['status'] == 'BLOCKED'
    assert secret not in json.dumps(result)


def test_costcore_name_without_semver_is_not_version_evidence(tmp_path):
    result, _ = run(tmp_path, FakeRunner(version=(0, 'costcore not-a-version', ''),
                                        shadow=(0, shadow_json(), '')))
    assert result['status'] == 'BLOCKED' and result['code'] == 'BINARY_VERSION_INVALID'


@pytest.mark.parametrize('stage', ['version', 'shadow'])
def test_undecodable_subprocess_output_is_a_sanitized_block(tmp_path, stage):
    def decode_error(_):
        raise UnicodeDecodeError('utf-8', b'\xffsynthetic-private', 0, 1, 'invalid')
    fake = FakeRunner(shadow=(0, shadow_json(), ''))
    def runner(argv):
        if (argv[1] == '--version') == (stage == 'version'):
            return decode_error(argv)
        return fake(argv)
    result, _ = run(tmp_path, runner)
    assert result['status'] == 'BLOCKED'
    assert 'synthetic-private' not in json.dumps(result)
