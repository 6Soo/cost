import sys
sys.path.insert(0, '.')
import sqlite3
import pathlib
from ledger.domain.direct_verified_ota_lodging import prepare_external_lodging_facts
db_path = pathlib.Path('outputs/agoda-card-link-candidate-v5-20260826.sqlite')
db = sqlite3.connect(str(db_path))
try:
    db.execute("DELETE FROM direct_verified_lodging_facts")
    db.execute("DELETE FROM direct_lodging_withheld")
    db.execute("DELETE FROM direct_lodging_authorities")
    result = prepare_external_lodging_facts(db, 'ota_lodging_run_2026')
    print('prepare_external_lodging_facts result:', result)
    db.commit()
except Exception as e:
    print(f'ERROR: {e}')
    import traceback
    traceback.print_exc()
db.close()