"""Same-date amount matching for OTA: card occurred_on + amount == mail sentAt + amount
Trip.com, Booking.com, Agoda, Klook 등 모든 OTA에 적용.
"""
import sqlite3, json, pathlib, collections
from datetime import date

DB = pathlib.Path("outputs/agoda-card-link-candidate-v5-20260826.sqlite")

def load_mail_by_date():
    """Load mail records grouped by sentAt date (YYYY-MM-DD)"""
    conn = sqlite3.connect(str(DB))
    cur = conn.cursor()
    # Trip.com etc. from ota_mail_non_agoda
    cur.execute("SELECT payload_json FROM direct_source_records WHERE source_kind='ota_mail_non_agoda'")
    mail_by_date = collections.defaultdict(list)
    for (j,) in cur.fetchall():
        try:
            d = json.loads(j)
            sent = d.get('sentAt','')[:10]
            provider = d.get('provider','')
            for amt in d.get('amounts',[]):
                mail_by_date[(sent, provider)].append(amt)
        except:
            pass
    # Agoda portal detail: observed_at + price_components paid_today
    cur.execute("SELECT payload_json FROM direct_source_records WHERE source_kind='agoda_portal_detail'")
    for (j,) in cur.fetchall():
        try:
            d = json.loads(j)
            sent = d.get('observed_at','')[:10]
            for pc in d.get('price_components',[]):
                if pc.get('kind')=='paid_today':
                    # minor_units to KRW? Agoda JPY to KRW approx *10, but keep as is for now
                    mail_by_date[(sent, 'agoda')].append(pc.get('minor_units'))
        except:
            pass
    return mail_by_date

def match_same_date():
    mail_by_date = load_mail_by_date()
    print(f"Mail by date-provider: {len(mail_by_date)} groups")
    for k,v in list(mail_by_date.items())[:5]:
        print(f"  {k}: {v[:3]}")

    conn = sqlite3.connect(str(DB))
    cur = conn.cursor()
    # Card by date
    cur.execute("SELECT occurred_on, GROUP_CONCAT(amount_krw) FROM payment_transactions GROUP BY occurred_on")
    card_by_date = {r[0]: [int(x) for x in r[1].split(',')] for r in cur.fetchall()}
    print(f"\nCard by date: {len(card_by_date)} dates")

    # Match: same date, same amount
    matches = 0
    for (sent, provider), mail_amts in mail_by_date.items():
        card_amts = card_by_date.get(sent, [])
        if not card_amts:
            continue
        # Simple: amount equality (need FX conversion for JPY etc., but try direct)
        common = set(card_amts) & set(mail_amts)
        if common:
            matches += len(common)
            print(f"Match {sent} {provider}: card {card_amts[:3]} vs mail {mail_amts[:3]} -> {common}")

    print(f"\nTotal same-date amount matches: {matches}")

if __name__ == "__main__":
    match_same_date()
