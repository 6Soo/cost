"""Tests for the P2 mail excerpt helper.

All mail bodies below are fabricated samples; no real names, card numbers
or booking references are used.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tools.p2_excerpt.excerpt import make_excerpt  # noqa: E402


def _excerpt(text, **kwargs):
    kwargs.setdefault("subject", "SUBJ-FAKE")
    kwargs.setdefault("sender", "no-reply@example.test")
    kwargs.setdefault("sent_date", "2026-07-15")
    kwargs.setdefault("body", text)
    return make_excerpt(**kwargs)


def test_plain_text_keeps_amount_date_and_booking_line() -> None:
    body = "\n".join(
        [
            "안내 인사",
            "예약번호: FAKE-A1B2",
            "문의는 웹사이트를 이용해 주세요",
            "총액: 123,456원",
            "감사합니다",
            "주말 특가 할인 광고 문구",
        ]
    )
    result = _excerpt(body)
    assert "예약번호: FAKE-A1B2" in result["text"]
    assert "총액: 123,456원" in result["text"]
    assert "주말 특가 할인 광고 문구" not in result["text"]


def test_html_strips_tags_style_and_script() -> None:
    body = (
        "<html><head><style>.a{color:red}</style></head>"
        "<body><p>예약번호 FAKE-HTML-1</p>"
        "<script>var tracker = 'ad';</script>"
        "<br>총액 10,000원 &amp; 부가세</body></html>"
    )
    result = _excerpt(body)
    assert "예약번호 FAKE-HTML-1" in result["text"]
    assert "10,000원" in result["text"]
    assert "color:red" not in result["text"]
    assert "var tracker" not in result["text"]
    assert "<" not in result["text"]
    assert "&" in result["text"]


def test_base64_image_blob_is_removed() -> None:
    blob = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=" * 4
    body = f"data:image/png;base64,{blob}\n예약번호 FAKE-B64\n총액 5,000원"
    result = _excerpt(body)
    assert "base64" not in result["text"].lower()
    assert "QUJD" not in result["text"]
    assert "예약번호 FAKE-B64" in result["text"]


def test_html_table_cells_are_separated() -> None:
    body = (
        "<table><tr><td>예약번호</td><td>ABC123</td></tr>"
        "<tr><td>총액</td><td>JPY</td><td>12,300</td></tr></table>"
    )
    result = _excerpt(body)
    assert "예약번호 ABC123" in result["text"]
    assert "총액 JPY 12,300" in result["text"]


def test_quoted_prior_mail_is_dropped() -> None:
    body = "\n".join(
        [
            "예약번호 QUOTE-FAKE",
            "총액 9,000원",
            "> 이전 대화 인용입니다",
            "> 예약번호 OLD-QUOTE",
            "-----Original Message-----",
            "예약번호 OLD-2",
            "From: someone@example.test",
            "예약번호 OLD-3",
        ]
    )
    result = _excerpt(body)
    assert "예약번호 QUOTE-FAKE" in result["text"]
    assert "인용" not in result["text"]
    assert "OLD-QUOTE" not in result["text"]
    assert "OLD-2" not in result["text"]
    assert "OLD-3" not in result["text"]


@pytest.mark.parametrize(
    "amount",
    ["123,456원", "KRW 123,456", "₩123,456", "JPY 12,300", "¥12,300",
     "USD 45.67", "$45.67", "EUR 30.00", "€30.00"],
)
def test_currency_variants_are_important(amount: str) -> None:
    body = f"금액 표기 확인 {amount} 입니다"
    assert amount in _excerpt(body)["text"]


@pytest.mark.parametrize(
    "date",
    [
        "2026-07-15",
        "2026.07.15",
        "2026/07/15",
        "2026년 7월 15일",
        "7월 15일",
        "Jul 15, 2026",
        "15 Jul 2026",
    ],
)
def test_date_variants_are_important(date: str) -> None:
    body = f"일정 날짜 {date} 관련 안내"
    assert date in _excerpt(body)["text"]


def test_context_lines_and_ellipsis_between_gaps() -> None:
    body = "\n".join(
        [
            "예약번호 ELL-1",
            "첫 문맥 줄",
            "광고 문구 하나",
            "광고 문구 둘",
            "둘째 문맥 줄",
            "총액 8,000원",
            "끝 줄",
        ]
    )
    result = _excerpt(body, context_lines=1)
    text = result["text"]
    assert "예약번호 ELL-1" in text
    assert "첫 문맥 줄" in text
    assert "둘째 문맥 줄" in text
    assert "총액 8,000원" in text
    assert "광고 문구 하나" not in text
    assert "광고 문구 둘" not in text
    assert text.index("예약번호 ELL-1") < text.index("...")
    assert text.index("...") < text.index("둘째 문맥 줄")


def test_overlapping_context_is_not_duplicated() -> None:
    body = "\n".join(
        [
            "글자0",
            "글자1",
            "예약번호 DUP-FAKE",
            "글자3",
            "글자4",
        ]
    )
    result = _excerpt(body, context_lines=2)
    assert result["text"].count("글자3") == 1
    assert result["kept_lines"] == 5


def test_truncation_bounds_utf8_and_marks_end() -> None:
    body = "\n".join(
        f"총액 1,000원 줄번호 {index:03d} 예약번호 T-{index:03d}" for index in range(60)
    )
    result = _excerpt(body, max_bytes=400)
    assert result["truncated"] is True
    assert len(result["text"].encode("utf-8")) <= 400
    lines = result["text"].split("\n")
    assert lines[-1] == "[잘림]"
    assert lines[0] == "제목: SUBJ-FAKE"
    assert lines[1] == "발신: example.test"
    assert lines[2] == "발송일: 2026-07-15"


def test_header_has_domain_only() -> None:
    result = make_excerpt(
        "제목 줄",
        '"Agoda <no-reply@agoda.com>"',
        "2026-07-15",
        "예약번호 HEADER-FAKE",
    )
    assert "제목: 제목 줄" in result["text"]
    assert "발신: agoda.com" in result["text"]
    assert "no-reply" not in result["text"]


def test_no_important_lines_uses_first_five() -> None:
    body = "\n".join(f"평범한 안내 문구 {index}" for index in range(12))
    result = _excerpt(body)
    assert "평범한 안내 문구 0" in result["text"]
    assert "평범한 안내 문구 4" in result["text"]
    assert "평범한 안내 문구 5" not in result["text"]


def test_none_and_empty_inputs_do_not_raise() -> None:
    for args in [
        (None, None, None, None),
        ("", "", "", ""),
        ("S", "a@b.test", "2026-01-01", "   \n\n  "),
    ]:
        result = make_excerpt(*args)
        assert set(result) == {"text", "truncated", "kept_lines", "total_lines"}
        assert result["truncated"] is False
        assert result["total_lines"] == 0


def test_counts_reflect_deduped_lines_and_kept_range() -> None:
    body = "\n".join(
        [
            "처음 줄",
            "예약번호 COUNT-FAKE",
            "가운데 줄",
            "총액 2,000원",
            "끝 줄",
        ]
    )
    result = _excerpt(body)
    assert result["total_lines"] == 5
    assert result["kept_lines"] == 5
    assert result["text"].count("가운데 줄") == 1
