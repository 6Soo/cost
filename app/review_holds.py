"""취소 정산과 사용자 보류를 일반 비용 전기에서 분리한다."""
def active_holds(conn):
    # 읽기 전용 구버전 DB도 계속 조회할 수 있다. 스키마 추가는 운영 작성자가 한다.
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='transaction_review_holds'").fetchone():
        return {}
    result={}
    for identity,source,kind,reason,current in conn.execute(
        'SELECT h.transaction_id,h.source_hash,h.kind,h.reason,t.source_hash '
        'FROM transaction_review_holds h JOIN transactions t ON t.transaction_id=h.transaction_id'):
        result[identity]={'kind':kind if source==current else 'evidence_pending',
                          'reason':reason if source==current else '보류한 원본이 달라 다시 확인해야 합니다'}
    return result
