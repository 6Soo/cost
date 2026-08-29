import sqlite3
db = sqlite3.connect('outputs/agoda-card-link-candidate-v5-20260826.sqlite')
cur = db.execute("SELECT DISTINCT merchant, COUNT(*) FROM payment_transactions WHERE merchant LIKE '%Trip%' OR merchant LIKE '%TRIP%' OR merchant LIKE '%Trip%' OR merchant LIKE '%travel%' OR merchant LIKE '%Travel%' GROUP BY merchant")
for r in cur.fetchall():
    print(f"{repr(r[0])}: {r[1]}")
db.close()