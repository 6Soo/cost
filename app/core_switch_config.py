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


class CoreSwitchRefused(ValueError):
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


def read_options(config_dir) -> dict:
    """`<config_dir>/card-flow.json` as a dict (BOM allowed); absent means no keys. The one reader for every host process."""
    path = Path(config_dir) / 'card-flow.json'
    options = json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else {}
    return options if isinstance(options, dict) else {}


def apply_from_host(config_dir, data_root, environ=None) -> None:
    """Read `<config_dir>/card-flow.json` (absent means no keys) and apply it."""
    apply(read_options(config_dir), data_root, environ)


def check_host(host_root) -> None:
    """Run the launcher's validation without touching this process's environment."""
    host = Path(host_root)
    apply(read_options(host / 'config'), host / 'data', environ={})


def refuse_manual_apply(host_root) -> None:
    """Manual tools write the board with Python; with a rust writer configured that would mix writers."""
    if read_options(Path(host_root) / 'config').get('classification_writer') == 'rust':
        raise CoreSwitchRefused('CORE_WRITER_MANUAL_APPLY_REFUSED')


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description='Validate the core switch keys of a host card-flow.json before a restart.')
    parser.add_argument('--host-root', type=Path, default=Path('D:/WebLedgerHost'))
    parser.add_argument('--check', action='store_true', required=True)
    args = parser.parse_args(argv)
    try:
        check_host(args.host_root)
    except CoreSwitchRefused as exc:
        print(f'refused [{exc.code}]')
        return 2
    except Exception:
        print('refused [ARG]')
        return 2
    print('ok')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
