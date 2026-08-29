import sqlite3
db = sqlite3.connect('outputs/agoda-card-link-candidate-v5-20260826.sqlite')
cur = db.cursor()
cur.execute("SELECT id, booking_number, service_start_on, service_end_on, provider FROM bookings WHERE provider='trip' LIMIT 10")
for r in cur.fetchall():
    print(r)