import sqlite3
db = sqlite3.connect('agoda-card-link-candidate-v4-20260823.sqlite')
cur = db.cursor()
cur.execute('SELECT name FROM sqlite_master WHERE type="table"')
tables = [r[0] for r in cur.fetchall()]
print('Tables:', tables)
cur.execute('SELECT COUNT(*) FROM payment_transactions')
print('payments:', cur.fetchone()[0])
cur.execute('SELECT COUNT(*) FROM booking_transactions')
print('bookings:', cur.fetchone()[0])
cur.execute('SELECT COUNT(*) FROM proposed_links')
print('proposed_links:', cur.fetchone()[0])
db.close()