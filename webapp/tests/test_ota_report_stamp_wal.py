"""OTA 보고서 표식 계산에서 WAL 파일이 충돌하지 않는지 검증한다(회귀: 8c5e618d)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ota_store import OtaStore
from webapp.ledger_store import LedgerStore
from webapp.card_flow import CardFlow


class OtaReportStampWalTests(unittest.TestCase):
    """통합 OTA DB의 WAL 파일이 _compute_ota_report에서 TypeError를 일으키지 않는지 확인한다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        # WEBLEDGER_UNIFIED_DB 환경변수로 통합 DB 모드 활성화
        self.env = patch.dict(os.environ, {
            'WEBLEDGER_UNIFIED_DB': '1',
            'WEBLEDGER_OTA_SOURCES': str(self.data_dir / 'ota-sources.json'),
        })
        self.env.start()
        self.board = LedgerStore(self.data_dir / 'board.sqlite', seed_demo=False)
        self.flow = CardFlow(self.board)

    def tearDown(self):
        self.board.close()
        self.env.stop()
        self.tmp.cleanup()

    def _create_unified_store_manifest(self, store_path):
        """통합 OTA DB를 가리키는 manifest를 생성한다."""
        manifest = {
            "schema_version": "ota-sources-v1",
            "unified_database": str(store_path),
        }
        (self.data_dir / 'ota-sources.json').write_text(json.dumps(manifest), encoding='utf-8')

    def test_compute_ota_report_with_wal_file_does_not_crash(self):
        """포털 DB가 OTA 저장소이고 WAL 파일이 존재해도 _compute_ota_report가 충돌 없이 끝난다."""
        # 1. 통합 OTA 저장소 생성 및 데이터 임포트
        store_path = self.data_dir / 'store.sqlite'
        store = OtaStore(store_path)
        try:
            # 최소한의 메일 데이터로 저장소 초기화
            mail_folder = self.data_dir / 'mail'
            mail_folder.mkdir()
            (mail_folder / 'gmail.json').write_text(
                json.dumps({'responses': []}, ensure_ascii=False), encoding='utf-8')
            store.import_mail(mail_folder)
            store.conn.commit()

            # 2. WAL 파일 생성: 트랜잭션 시작 후 커밋하지 않음
            store.conn.execute('BEGIN IMMEDIATE')
            store.import_mail(mail_folder)  # 같은 데이터 다시 임포트 (변경 없음)
            # 커밋하지 않음 → WAL 파일이 남음
            wal_path = store_path.with_name(store_path.name + '-wal')
            self.assertTrue(wal_path.exists(), "WAL 파일이 존재해야 함")

            # 3. Manifest로 통합 DB 등록
            self._create_unified_store_manifest(store_path)

            # 4. _compute_ota_report 호출 - 충돌 없이 끝나야 함
            # (이전 버그: WAL 파일의 content_stamp가 None을 반환해 정렬 시 TypeError 발생)
            report = self.flow._compute_ota_report()

            # 5. 보고서가 정상적으로 생성되었는지 확인 (None이 아닐 수 있음, 구조만 확인)
            # 버그 수정 전이면 이 라인에 도달하지 못하고 TypeError 발생
            self.assertIsNotNone(report, "보고서가 생성되어야 함")
            self.assertIn('matches', report)
            self.assertIn('type_only_candidates', report)
            self.assertIn('rules', report)

            # 6. 표식 계산 경로에서 WAL이 제외되는지 검증 (source_stamps 경유)
            from app import ota_sources
            sources = self.flow._ota_sources()
            stamps = ota_sources.source_stamps(sources)
            # WAL 파일 경로가 표식에 없어야 함
            wal_str = str(wal_path.resolve())
            for stamp in stamps:
                self.assertNotEqual(stamp['path'], wal_str, "WAL 파일은 표식에서 제외되어야 함")
            # 메인 DB는 ota_store_state 표식이 있어야 함
            main_db_str = str(store_path.resolve())
            found_main = False
            for stamp in stamps:
                if stamp['path'] == main_db_str:
                    found_main = True
                    self.assertIn('ota_store_state', stamp, "메인 DB는 ota_store_state 표식이어야 함")
            self.assertTrue(found_main, "메인 DB 표식이 있어야 함")

        finally:
            store.close()

    def test_compute_ota_report_without_wal_works_as_before(self):
        """WAL 파일 없을 때 기존 동작 그대로 유지됨."""
        store_path = self.data_dir / 'store2.sqlite'
        store = OtaStore(store_path)
        try:
            mail_folder = self.data_dir / 'mail2'
            mail_folder.mkdir()
            (mail_folder / 'gmail.json').write_text(
                json.dumps({'responses': []}, ensure_ascii=False), encoding='utf-8')
            store.import_mail(mail_folder)
            store.conn.commit()

            self._create_unified_store_manifest(store_path)

            report = self.flow._compute_ota_report()
            self.assertIsNotNone(report)
            self.assertIn('matches', report)

            # 표식에 메인 DB만 있고 ota_store_state여야 함
            from app import ota_sources
            sources = self.flow._ota_sources()
            stamps = ota_sources.source_stamps(sources)
            main_db_str = str(store_path.resolve())
            found_main = False
            for stamp in stamps:
                if stamp['path'] == main_db_str:
                    found_main = True
                    self.assertIn('ota_store_state', stamp)
            self.assertTrue(found_main)
        finally:
            store.close()


if __name__ == '__main__':
    unittest.main()