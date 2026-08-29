import sqlite3
db = sqlite3.connect('outputs/agoda-card-link-candidate-v5-20260826.sqlite')
cur = db.cursor()

for table in ['direct_ota_reservation_queue', 'direct_verified_lodging_facts']:
    print(f"\n=== {table} ===")
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    print(f"Count: {cur.fetchone()[0]}")
    cur.execute(f"PRAGMA table_info({table})")
    cols = cur.fetchall()
    print(f"Columns: {[c[1] for c in cols]}")
    cur.execute(f"SELECT * FROM {table} LIMIT 3")
    for r in cur.fetchall():
        print(f"  {r}")