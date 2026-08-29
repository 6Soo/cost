import sqlite3
db = sqlite3.connect('outputs/agoda-card-link-candidate-v5-20260826.sqlite')
cur = db.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("Tables with relevant data:")
for t in tables:
    if any(k in t.lower() for k in ['source', 'mail', 'agoda', 'direct', 'lodging']):
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        print(f"  {t}: {cur.fetchone()[0]}")