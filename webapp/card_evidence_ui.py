"""Read-only HTML evidence presentation for card transactions, OTA snapshots, and refunds.

Extracts UI presentation responsibilities from webapp.card_flow:
- OTA snapshot evidence badge, notes, and staleness details
- OTA catalog block details
- Refund merchant candidate comparison rows and Kakao T taxi inventories
- Refund evidence summaries and links

This module is strictly read-only and presentation-only:
- NO database connections or SQL queries
- NO board objects or module globals passed
- NO financial matching or transaction classification judgments
- Exact behavioral preservation of legacy defaults, exceptions, and escaping
"""
from __future__ import annotations

import html
import re
from typing import Callable, Iterable, Sequence
from urllib.parse import urlencode


def default_esc(value: object) -> str:
    """Escape value for safe HTML insertion."""
    return html.escape("" if value is None else str(value), quote=True)


def refund_merchant_key(value: object) -> str:
    """Diagnostic merchant family only. NEVER use as a financial matching key.

    Kakao Pay, gift shops, parking, substitute drivers and other services
    cannot be silently grouped with Kakao T taxi authorizations.
    """
    compact = re.sub(r"[^0-9a-z가-힣]", "", str(value or "").casefold())
    taxi_prefix = ("카카오t", "카카오택시", "카카오모빌리티택시",
                   "kakaotaxi", "kakaot")
    if compact.startswith(taxi_prefix) or (
        compact.startswith("카카오모빌리티") and
        any(word in compact for word in ("일반택시", "가승인", "선승인", "택시요금"))
    ):
        if any(word in compact for word in ("대리", "주차", "바이크", "퀵")):
            return compact
        return "카카오택시"
    return compact


def render_ota_snapshot_evidence(
    entry: dict,
    tid: str = "",
    *,
    esc: Callable[[object], str] | None = None,
) -> str:
    """중앙 OTA 스냅샷 엔트리에서 근거 HTML을 생성.

    OTA exact/inferred/multiple/unlinked, snapshot refreshing/input error,
    여행 없음/무효, 원문충돌/중복/환불미완료/수동보류, 준비/기록완료/금융보호 상태 표시.
    """
    if esc is None:
        esc = default_esc

    status = entry.get('ota_status', '')
    notes = entry.get('ota_notes', [])
    snap = entry.get('snapshot', {})
    fresh = snap.get('fresh', False)
    snap_status = snap.get('status', 'unknown')
    # 세대 번호는 내부 진단값이므로 화면 문구에 넣지 않는다.

    lines = []

    # OTA 연결 상태 뱃지
    status_labels = {
        'EXACT': ('확정 연결', 'ok'),
        'INFERRED': ('추론 연결', 'warn'),
        'GROUP_RECONCILED': ('그룹 대응 (개별 미확정)', 'warn'),
        'USER_CONFIRMED': ('사용자 확정', 'ok'),
        'RESERVATION_INFERRED': ('예약 추론 관계', 'idle'),
        'RESERVATION_CONFIRMED': ('예약 관계 사용자 확인', 'ok'),
        'RESERVATION_NEEDS_REVIEW': ('예약 후보 경합/충돌', 'warn'),
        'RESERVATION_STALE': ('예약 관계 근거 변경', 'bad'),
        'REVIEW_REQUIRED': ('그룹 부분 대응·보류', 'bad'),
        'CANDIDATE': ('후보 존재·미연결', 'idle'),
        'MULTIPLE_CANDIDATES': ('복수 후보·개별 미확정', 'warn'),
        'UNLINKED': ('OTA 결제 연결 없음 · 결제 근거 확인 필요', 'idle'),
    }
    label, tone = status_labels.get(status, ('연결 상태 확인 대기', 'idle'))
    lines.append(f"<span class='cleanup-ota-badge cleanup-ota-badge-{tone}'>{esc(label)}</span>")

    # 스냅샷 신선도
    if not fresh:
        if snap_status == 'refreshing':
            lines.append(f"<span class='cleanup-snapshot-refreshing'>{esc('예약 근거 갱신 중...')}</span>")
        elif snap_status == 'stale':
            lines.append(f"<span class='cleanup-snapshot-stale'>{esc('스냅샷 구버전 (갱신 대기)')}</span>")
        elif snap_status == 'error':
            lines.append(f"<span class='cleanup-snapshot-error'>{esc('예약 근거 입력 오류')}</span>")
        elif snap_status == 'loading':
            lines.append(f"<span class='cleanup-snapshot-loading'>{esc('스냅샷 로딩 중...')}</span>")
        else:
            lines.append(f"<span class='cleanup-snapshot-stale'>{esc('현재 예약 연결을 확인할 수 없습니다.')}</span>")
    else:
        lines.append(f"<span class='cleanup-snapshot-fresh'>{esc('최신 예약 자료 확인')}</span>")

    # 동일 카드의 후보와 거절 사유를 모두 보존한다.
    for note in notes:
        lines.append(f"<span class='cleanup-ota-note'>{esc(note)}</span>")

    # 보호/보류 상태 추가 정보
    if status in ('GROUP_RECONCILED', 'REVIEW_REQUIRED'):
        lines.append(f"<span class='cleanup-protected-hint'>{esc('개별 예약↔카드 연결 미확정 · 장부 기록은 금융 검증 후 허용')}</span>")
    elif status in ('RESERVATION_NEEDS_REVIEW', 'RESERVATION_STALE'):
        lines.append(f"<span class='cleanup-protected-hint'>{esc('예약 관계만 확인됨 · 결제 검증 별도 · 사용자 재확인 필요')}</span>")

    items = ''.join(f"<li>{line}</li>" for line in lines)
    return (f"<details class='cleanup-evidence cleanup-ota-snapshot' open><summary>{esc('OTA 연결 근거')}</summary>"
            f"<ul>{items}</ul></details>")


def render_catalog_block(
    entry: dict,
    *,
    esc: Callable[[object], str] | None = None,
) -> str:
    """OTA 예약의 판단에 필요한 줄: 예약번호·상태, 이용기간, 후보 여행, 연결 카드 결제."""
    if esc is None:
        esc = default_esc

    relation = {'covers': '전체 포함', 'overlaps': '일부 겹침', 'none': ''}
    lines = [f"예약 {entry['booking_ref']} · {entry.get('status') or '상태 미확인'}"]
    if entry.get('period'):
        lines.append(f"이용 {entry['period']}")
    candidates = [f"{c.get('display_key') or c.get('tab_id')}({relation.get(c.get('relation'), '')})"
                  for c in entry.get('candidates') or []]
    if candidates:
        lines.append('후보 여행: ' + ', '.join(candidates))
    cancelled = entry.get('cancelled_matches') or 0
    if cancelled:
        lines.append(f'취소 결제 {cancelled}건')
    items = ''.join(f"<li>{esc(line)}</li>" for line in lines)
    return (f"<details class='cleanup-evidence' open><summary>{esc(entry.get('provider') or 'OTA')} 예약 자료</summary>"
            f"<ul>{items}</ul></details>")


def render_no_booking_evidence(
    *,
    fresh: bool = False,
    source: str = "",
    is_ota: bool = False,
) -> str:
    """예약 자료가 없을 때 검토 안내 문구를 반환."""
    if source == "booking_evidence_needed" or is_ota:
        if fresh:
            return ("<p class='cleanup-evidence-none'>이 결제와 연결된 예약 자료가 현재 검토 목록에 없습니다. "
                    "예약 확인서에서 예약번호와 이용기간을 확인해 주세요. "
                    "카드 결제일만으로는 여행을 정할 수 없습니다.</p>")
        return "<p class='cleanup-evidence-none'>현재 예약 자료를 확인할 수 없어 예약 부재 여부를 판단하지 않았습니다.</p>"
    return ""


def render_refund_merchant_candidates(
    refund: tuple | list | None,
    candidates: list,
    count: int,
    *,
    existing_ledger_ids: Iterable[str] | None = None,
    kakao_inventory: list[dict] | None = None,
    esc: Callable[[object], str] | None = None,
) -> str:
    """Show review candidates only. Nothing is saved or automatically linked."""
    if not refund:
        return ""
    if esc is None:
        esc = default_esc

    issuer, tail, merchant, day, amount, approval, original = refund
    key = refund_merchant_key(merchant)
    header = ("카카오T 택시 가맹점 표기 대조" if key == "카카오택시"
              else "같은 카드·가맹점 원결제 비교")
    parts = [
        f"<details class='cleanup-merchant-compare'><summary>{esc(header)}"
        f" <span class='cleanup-mini-count'>{count}건</span></summary>",
        "<p class='cleanup-evidence-meta'>원결제 연결은 미확정 · 같은 카드의 최근 14일 거래를 비교합니다.</p>",
        f"<p class='cleanup-evidence-meta'>환불 카드 {esc(issuer)} · 끝자리 {esc(tail)}"
        f" · 승인번호 {esc(approval or '없음')} · 원승인번호 {esc(original or '없음')}</p>"
    ]
    if key == "카카오택시":
        parts.append("<p class='cleanup-evidence-meta'>카카오T 가승인·선승인·일반택시·유페이 표기를"
                     " 비교 후보로 묶었습니다. 카카오페이·선물·대리·주차는 택시 거래로 합치지 않습니다."
                     " 가승인 해제와 실제 요금/부분 환불은 별개이므로 확정 연결하지 않습니다."
                     " 원승인번호와 같은 카드의 정상 원결제가 식별되면 가맹점명이 달라도 확정 연결합니다."
                     " 유페이 일반결제는 택시 결제의 후보일 수 있어 보여 주되, 가맹점 동일성이나 실제 환급을 확정하지 않습니다."
                     " 한 원결제에 취소·환불이 여러 건인 것은 정상이며, 총 환불액과 잔액은 따로 검증합니다.</p>")
        inventory = kakao_inventory or []
        taxi_count = sum(item["count"] for item in inventory if item["family"] == "카카오택시")
        other_count = sum(item["count"] for item in inventory if item["family"] != "카카오택시")
        parts.append("<details class='cleanup-kakao-inventory'><summary>"
                     f"카카오·유페이 표기 점검 · 택시 {taxi_count}건 / 기타 {other_count}건"
                     "</summary><p class='cleanup-evidence-meta'>현재 저장된 카드 원행의 가맹점 표기를 "
                     "읽기 전용으로 집계합니다. 카카오페이·기타 서비스는 택시 후보에서 분리하며 "
                     "원결제 매칭이나 계좌 출금 증거로 사용하지 않습니다.</p>")
        for item in inventory[:40]:
            group = "택시 표기" if item["family"] == "카카오택시" else "별도 서비스"
            parts.append(f"<p class='cleanup-evidence-meta'>{esc(group)} · "
                         f"{esc(item['merchant'])} · {esc(item['direction'])} "
                         f"{item['count']}건</p>")
        if len(inventory) > 40:
            parts.append(f"<p class='cleanup-evidence-meta'>표기 {len(inventory)}종 중 "
                         "40종만 펼쳐 보여줍니다. 집계는 전체 원행 기준입니다.</p>")
        parts.append("</details>")
    if candidates:
        parts.append("<div class='cleanup-compare-list' role='list'>")
        existing = set(existing_ledger_ids) if existing_ledger_ids else set()
        for cid, batch, name, date, gross, number, duplicate, conflict, error in candidates:
            alias_match = refund_merchant_key(name) == key
            upay_proxy = (key == "카카오택시" and
                          str(name or "").replace(" ", "").startswith("유페이"))
            flags = ["같은 카드",
                     "가맹점명 동일" if name == merchant else
                     "표기 변형" if alias_match else
                     "유페이 결제중계 후보 · 동일 서비스 확인 필요" if upay_proxy else
                     "원승인번호 대조 · 가맹점 불일치",
                     "금액 일치" if gross == abs(amount or 0) else "금액 차이",
                     "장부 기록 있음" if cid in existing else "장부 미기록"]
            if original and number and str(original).strip() == str(number).strip():
                flags.append("원승인번호 일치 · 확정 연결은 별도 검증")
            if duplicate or conflict or error:
                flags.append("중복·원본 오류")
            link = "/import?" + urlencode({"batch": batch, "transaction": cid})
            parts.append("<article class='cleanup-compare-row' role='listitem'>"
                         f"<div class='cleanup-compare-main'><strong>{esc(name)}</strong>"
                         f"<b>{gross:,}원</b></div>"
                         f"<p>{esc(str(date))} · 승인 {esc(number or '없음')}</p>"
                         f"<p class='cleanup-evidence-meta'>{esc(' · '.join(flags))}</p>"
                         f"<a href='{esc(link)}'>원결제 자료 보기</a></article>")
        parts.append("</div>")
        if count > len(candidates):
            parts.append(f"<p class='cleanup-evidence-meta'>총 {count}건 중 최근·근거 우선"
                         f" {len(candidates)}건 표시. 전체 거래 검색에서 추가 확인해 주세요.</p>")
    else:
        parts.append("<p>최근 14일 내 같은 카드·가맹점 표기 후보가 없습니다."
                     " 더 오래된 승인과 다른 카드 거래는 전체 거래 검색에서 확인해 주세요."
                     " 결제중계 가맹점과 원승인번호를 확인하기 전에는 연결을 확정하지 않습니다.</p>")
    query = "카카오" if key == "카카오택시" else merchant
    search = "/import?" + urlencode({"scope": "all", "q": query})
    parts.append(f"<p><a href='{esc(search)}'>가맹점명으로 전체 카드 거래 검색</a></p></details>")
    return "<div class='cleanup-refund-candidates'>" + "".join(parts) + "</div>"


def render_refund_evidence(
    title: str,
    lines: Sequence[str],
    comparison_html: str = "",
    *,
    esc: Callable[[object], str] | None = None,
) -> str:
    """원결제 연결과 실제 기록 상태를 순수 HTML로 렌더링."""
    if esc is None:
        esc = default_esc
    return ("<details class='cleanup-evidence cleanup-refund'><summary>" + esc(title) +
            '</summary><ul>' + ''.join('<li>' + esc(line) + '</li>' for line in lines) + '</ul>' +
            comparison_html + '</details>')


def render_booking_email_evidence(
    entries_described: Sequence[Sequence[str]],
    searched_count: int,
    amount: int | float | None,
    *,
    esc: Callable[[object], str] | None = None,
) -> str:
    """같은 금액의 예약 메일 근거를 순수 HTML로 렌더링."""
    if esc is None:
        esc = default_esc
    if not entries_described:
        return (f"<p class='cleanup-evidence-none'>같은 금액 {abs(int(amount or 0)):,}원의 예약 메일이 없습니다."
                f" 메일 {searched_count:,}통을 확인했습니다.</p>")
    items = ''.join('<li>' + '<br>'.join(esc(line) for line in desc) + '</li>'
                    for desc in entries_described)
    return (f"<details class='cleanup-evidence' open><summary>같은 금액의 예약 {len(entries_described)}건</summary>"
            f"<ul>{items}</ul></details>")
