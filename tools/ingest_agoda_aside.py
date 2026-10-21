"""Aside 수집 파일을 운영과 분리된 로컬 증거 DB로 가져온다."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agoda_capture import CaptureStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture-root', type=Path, required=True)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--mail-manifest', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    # 운영 장부와 사용자 결정 저장소를 실수로 증거 DB로 열지 않는다.
    destination = args.db.resolve()
    archive = Path(__file__).resolve().parents[1] / '.local-archive'
    if archive.resolve() not in destination.parents:
        parser.error('증거 DB는 저장소의 .local-archive 아래에 지정해야 합니다')
    if not args.capture_root.is_dir():
        parser.error('수집 폴더가 없습니다')
    failures = []
    added = 0
    store = CaptureStore(destination)
    try:
        for kind in ('pages', 'details'):
            for path in sorted((args.capture_root / kind).glob('*.json')):
                try:
                    capture = json.loads(path.read_text(encoding='utf-8'))
                    # 큐·manifest 파일은 원문 캡처가 아니다.
                    if capture.get('kind') not in ('list', 'detail'):
                        continue
                    added += store.ingest(capture, run_id=args.run_id)
                except (ValueError, KeyError, TypeError) as exc:
                    failures.append({'file': str(path.resolve()), 'error': str(exc)})
        if args.mail_manifest:
            manifest = json.loads(args.mail_manifest.read_text(encoding='utf-8'))
            store.ingest_mail(manifest['mail_directories'])
        result = {'status': 'PARTIAL' if failures else 'PASS', 'new_captures': added,
                  'summary': store.summary(), 'failures': failures,
                  'scope': 'local_evidence_only_no_ledger_writes'}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k: v for k, v in result.items() if k != 'failures'}, ensure_ascii=False))
        return 1 if failures else 0
    finally:
        store.close()


if __name__ == '__main__':
    raise SystemExit(main())
