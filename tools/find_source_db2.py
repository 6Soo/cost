import sqlite3
import pathlib
for f in pathlib.Path('outputs').glob('*.sqlite'):
    try:
        db = sqlite3.connect(str(f))
        cur = db.cursor()
        cur.execute('SELECT name FROM sqlite_master WHERE type="table"')
        tables = [r[0] for r in cur.fetchall()]
        if 'payment_transactions' in tables:
            cur.execute('SELECT COUNT(*) FROM payment_transactions')
            print(f'{f.name}: payments={cur.fetchone()[0]}, tables={tables[:5]}')
            db.close()
            break
        db.close()
    except:
        pass