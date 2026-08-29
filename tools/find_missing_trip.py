import sqlite3
db = sqlite3.connect('outputs/agoda-card-link-candidate-v5-20260826.sqlite')
cur = db.execute("""
    SELECT pt.occurred_on, pt.merchant, pt.amount_krw
    FROM payment_transactions pt
    WHERE pt.occurred_on IS NOT NULL
      AND (
        (pt.occurred_on BETWEEN '2026-03-01' AND '2026-04-10' AND ABS(pt.amount_krw - 297136) < 5000)
        OR (pt.occurred_on BETWEEN '2026-05-15' AND '2026-07-01' AND ABS(pt.amount_krw - 840578) < 5000)
        OR (pt.occurred_on BETWEEN '2026-07-01' AND '2026-08-15' AND ABS(pt.amount_krw - 295341) < 5000)
      )
    ORDER BY occurred_on
""")
for r in cur.fetchall():
    print(r)
db.close()