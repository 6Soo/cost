import sqlite3
db = sqlite3.connect('outputs/agoda-card-link-candidate-v5-promoted.sqlite')
cur = db.cursor()
booking_ids = ['1715470826', '661776875', '661778779', '1680375476', '1673605517', '1698436218', '1698435672', '1698435971', '1720330717', '1720331103']
for bid in booking_ids:
    cur.execute('SELECT merchant_name, card_last4 FROM booking_transactions WHERE booking_id=?', (bid,))
    r = cur.fetchone()
    if r:
        print(f'{bid}: merchant={r[0]} card={r[1]}')
    else:
        print(f'{bid}: NOT FOUND')
db.close()