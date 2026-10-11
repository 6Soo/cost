from tools.verify_operational_backup_restore import product_files, digest_file


def test_backup_covers_receipt_original_decisions_and_google_generation(tmp_path):
    paths = ['config/card-flow.json', 'data/receipts/receipts.json',
             'data/receipts/receipts.images/synthetic.bin',
             'data/google-authority/snapshot.json', 'data/google-authority/rows.generation.json']
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(('synthetic:' + name).encode())
    secret = tmp_path / 'secrets/session-secret.txt'
    secret.parent.mkdir()
    secret.write_text('synthetic-secret')
    before = {name: digest_file(tmp_path / name) for name in paths}
    files = product_files(tmp_path)
    assert set(files) == {'host-config/card-flow.json', 'receipts/receipts.json',
                          'receipts/receipts.images/synthetic.bin',
                          'google-authority/snapshot.json', 'google-authority/rows.generation.json'}
    assert {name: digest_file(tmp_path / name) for name in paths} == before
    assert secret not in files.values()
