import sqlite3
db = sqlite3.connect('outputs/agoda-card-link-candidate-v5-promoted.sqlite')
cur = db.cursor()
cur.execute('SELECT name FROM sqlite_master WHERE type="table"')
tables = [r[0] for r in cur.fetchall()]
print('Tables:', tables)
db.close()