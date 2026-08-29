import sqlite3
db = sqlite3.connect('outputs/agoda-card-link-candidate-v5-promoted.sqlite')
cur = db.cursor()
# Check bookings table structure
cur.execute('PRAGMA table_info(bookings)')
for r in cur.fetchall():
    print(r)
db.close()