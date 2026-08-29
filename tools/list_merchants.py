import sqlite3
db = sqlite3.connect('outputs/agoda-card-link-candidate-v5-promoted.sqlite')
cur = db.cursor()
cur.execute('SELECT DISTINCT merchant FROM payment_transactions WHERE merchant IS NOT NULL AND merchant != ""')
for r in cur.fetchall():
    print(r[0])
db.close()