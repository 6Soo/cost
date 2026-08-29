import sqlite3
db = sqlite3.connect('outputs/agoda-card-link-candidate-v5-promoted.sqlite')
cur = db.cursor()
booking_ids = ['1715470826', '661776875', '661778779', '1680375476', '1673605517', '1698436218', '1698435672', '1698435971', '1720330717', '1720331103']
for bid in booking_ids:
    cur.execute('''
        SELECT pt.merchant, pt.amount_krw, b.service_start_on, b.service_end_on
        FROM payment_transactions pt
        JOIN payment_booking_links pbl ON pt.id = pbl.payment_id
        JOIN bookings b ON b.id = pbl.booking_id
        WHERE b.booking_number = ?
    ''', (bid,))
    r = cur.fetchone()
    if r:
        print(f'{bid}: merchant={r[0]} amount={r[1]} service={r[2]}~{r[3]}')
    else:
        cur.execute('SELECT * FROM bookings WHERE booking_number=?', (bid,))
        b = cur.fetchone()
        print(f'{bid}: NOT LINKED, booking row={b}')
db.close()