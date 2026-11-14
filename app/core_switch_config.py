"""Core switches from host `card-flow.json`, applied to a launched process's own environment only.

Keys: `classification_writer` and `links_producer` ("python" | "rust"), `costcore_bin`, `core_db`.
Absent keys leave Python and set nothing; inherited values are cleared first. `rust` without a usable
binary or core database refuses with a code, so a host never falls back to Python silently.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

SWITCHES = (('classification_writer', 'WEBLEDGER_CLASSIFICATION_WRITER'),
            ('links_producer', 'WEBLEDGER_LINKS_PRODUCER'))
ENV_NAMES = ('WEBLEDGER_CLASSIFICATION_WRITER', 'WEBLEDGER_LINKS_PRODUCER',
             'WEBLEDGER_COSTCORE_BIN', 'WEBLEDGER_CORE_DB')


class CoreSwitchRefused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _file(raw, code: str) -> Path:
    path = Path(str(raw or ''))
    if not path.is_absolute() or not path.is_file():
        raise CoreSwitchRefused(code)
    return path


def apply(options: dict, data_root, environ=None) -> None:
    env = os.environ if environ is None else environ
    for name in ENV_NAMES:
        env.pop(name, None)
    chosen = {}
    for key, name in SWITCHES:
        value = options.get(key)
        if value is None:
            continue
        if value not in ('python', 'rust'):
            raise CoreSwitchRefused('CORE_SWITCH_VALUE')
        chosen[name] = value
    if 'rust' not in chosen.values():
        return
    binary = _file(options.get('costcore_bin'), 'CORE_SWITCH_BIN')
    core_db = None
    if chosen.get('WEBLEDGER_CLASSIFICATION_WRITER') == 'rust' or options.get('core_db'):
        core_db = _file(options.get('core_db'), 'CORE_SWITCH_DB')
        # The writer may only touch the core database inside this host's durable data root.
        if os.path.normcase(os.path.dirname(os.path.realpath(core_db))) != os.path.normcase(os.path.realpath(data_root)):
            raise CoreSwitchRefused('CORE_SWITCH_DB_ROOT')
    env.update(chosen)
    env['WEBLEDGER_COSTCORE_BIN'] = str(binary)
    if core_db is not None:
        env['WEBLEDGER_CORE_DB'] = str(core_db)


def apply_from_host(config_dir, data_root, environ=None) -> None:
    """Read `<config_dir>/card-flow.json` (absent means no keys) and apply it."""
    path = Path(config_dir) / 'card-flow.json'
    options = json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else {}
    apply(options if isinstance(options, dict) else {}, data_root, environ)
