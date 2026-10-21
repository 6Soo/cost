"""운영 복구 사본에 단일 OTA DB가 빠지지 않아야 한다."""
import json

from app.ota_store import OtaStore
from tools.verify_operational_backup_restore import database_inputs


def test_operational_backup_includes_the_configured_unified_store(tmp_path):
    path = tmp_path / 'unified.sqlite'
    store = OtaStore(path)
    store.close()
    (tmp_path / 'ota-sources.json').write_text(json.dumps({'schema_version':'ota-sources-v1',
        'unified_database':str(path)}), encoding='utf-8')
    databases, _ = database_inputs(tmp_path, {'decisions_db_path':str(tmp_path / 'review.sqlite')}, {})
    assert databases['ota-evidence.sqlite'] == path
