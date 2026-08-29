import sqlite3
db = sqlite3.connect('outputs/agoda-card-link-candidate-v5-20260826.sqlite')
cur = db.cursor()
cur.execute("""
    SELECT merchant, COUNT(*)
    FROM payment_transactions
    WHERE merchant LIKE '%NICE%' OR merchant LIKE '%nice%' OR merchant LIKE '%Agoda%' OR merchant LIKE '%AGODA%'
    GROUP BY merchant
""")
for r in cur.fetchall():
    print(f'{r[0][:50]}: {r[1]}')