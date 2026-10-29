"""보험가입 명단 배치를 참가 저장소에 등록한다.

전달 자료는 Git에서 제외된 로컬 경로에만 둔다. 이 도구는 운영 장부와 Google에
쓰지 않고, 참가 확정을 별도 저장소에만 기록한다. 이름과 원본 경로는 표준 출력에
그대로 싣지 않고 항목 id와 상태만 보여 준다.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.participant_roster import (  # noqa: E402
    ParticipantStore,
    RosterError,
    mapping_resolver,
    register_roster,
)


def _load_mapping(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch-dir', type=Path, required=True,
                        help='manifest.json과 participants.json이 있는 배치 폴더')
    parser.add_argument('--db', type=Path, required=True,
                        help='참가 저장소 파일 (.local-archive 아래여야 합니다)')
    parser.add_argument('--mapping', type=Path,
                        help='google-tab-mapping.json 경로. 없으면 여행 연결을 보류합니다')
    parser.add_argument('--report', type=Path, help='결과를 저장할 JSON 경로')
    parser.add_argument('--apply', action='store_true',
                        help='검증 후 참가 저장소에 기록합니다. 기본은 preview/read-only입니다')
    args = parser.parse_args()

    destination = args.db.resolve()
    archive = Path(__file__).resolve().parents[1] / '.local-archive'
    if archive.resolve() not in destination.parents:
        parser.error('참가 저장소는 저장소의 .local-archive 아래에 지정해야 합니다')
    if not args.batch_dir.is_dir():
        parser.error('배치 폴더가 없습니다')

    if not args.apply:
        # Preview deliberately does not open/create SQLite. The batch parser and
        # runtime identity checks are separate read-only operations.
        print(json.dumps({'status': 'preview', 'db': str(destination),
                          'would_write': True}, ensure_ascii=False))
        return 0

    store = ParticipantStore.open(destination)
    try:
        result = register_roster(store, args.batch_dir,
                                 trip_resolver=mapping_resolver(_load_mapping(args.mapping)))
    except RosterError as exc:
        print(json.dumps({'status': 'rejected', 'code': exc.code}, ensure_ascii=False))
        return 2
    finally:
        store.close()

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
