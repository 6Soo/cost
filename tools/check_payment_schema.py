import sqlite3
db = sqlite3.connect('outputs/agoda-card-link-candidate-v5-promoted.sqlite')
cur = db.cursor()
# Check payment_transactions for merchant
cur.execute('PRAGMA table_info(payment_transactions)')
for r in cur.fetchall():
    print(r)
db.close()