import sqlite3
db = sqlite3.connect('outputs/agoda-card-link-candidate-v5-promoted.sqlite')
cur = db.cursor()
# Check payment_booking_links
cur.execute('PRAGMA table_info(payment_booking_links)')
for r in cur.fetchall():
    print(r)
db.close()