import sqlite3
db = sqlite3.connect('outputs/agoda-card-link-candidate-v5-20260826.sqlite')
cur = db.cursor()
cur.execute('SELECT name FROM sqlite_master WHERE type="table"')
tables = [r[0] for r in cur.fetchall()]
print("All tables with mail/ota/booking/message/event:")
for t in tables:
    if any(k in t.lower() for k in ['mail', 'ota', 'lodging', 'message', 'event']):
        print(f"  {t}")