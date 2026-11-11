"""Excerpt decision-relevant lines from reservation/payment email bodies.

The helper turns a raw mail body into a short, human-readable snippet that
keeps the lines a reviewer/classifier needs (amounts, dates, booking and
journey keywords) plus a small amount of surrounding context.
"""

from __future__ import annotations

import html
import re

__all__ = ["make_excerpt"]

# --- HTML handling -------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<!--|</?[a-zA-Z][a-zA-Z0-9:._-]*(?:\s[^<>]*)?/?>", re.S)
_SCRIPT_STYLE_RE = re.compile(
    r"</?(?:script|style)\b[^>]*>.*?</(?:script|style)\s*>", re.I | re.S
)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_BLOCK_TAG_RE = re.compile(r"</?(?:br|p|div|tr|li)\s*/?>", re.I)
_ANY_TAG_RE = re.compile(r"<[^>]*>")
_DATA_URI_RE = re.compile(r"data:image/[^;,\s]+;base64,[A-Za-z0-9+/=]{16,}")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})")

# --- Decision-relevant line detection -----------------------------------

_AMOUNT_RE = re.compile(
    r"(?:[\$\u20a9\u00a5\u20ac]\s*\d[\d,]*(?:\.\d+)?)"  # $ ₩ ¥ €
    r"|(?:(?:USD|EUR|JPY|KRW|CNY|GBP|AUD|CAD)\s*\d[\d,]*(?:\.\d+)?)"
    r"|(\d[\d,]*(?:\.\d+)?\s*(?:원|KRW|JPY|USD|EUR))",
    re.I,
)

_DATE_RE = re.compile(
    r"\d{4}[-./]\d{1,2}[-./]\d{1,2}"  # 2026-07-15 / 2026.07.15 / 2026/07/15
    r"|\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일"  # 2026년 7월 15일
    r"|\d{1,2}\s*월\s*\d{1,2}\s*일"  # 7월 15일
    r"|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}"  # Jul 15, 2026
    r"|\d{1,2}\s+[A-Za-z]{3,9},?\s+\d{4}",  # 15 Jul 2026
    re.I,
)

_KEYWORDS = (
    "예약번호",
    "예약 번호",
    "확인번호",
    "booking",
    "reservation",
    "confirmation",
    "체크인",
    "체크아웃",
    "check-in",
    "check in",
    "check-out",
    "check out",
    "숙박",
    "nights",
    "출발",
    "도착",
    "departure",
    "arrival",
    "탑승",
    "픽업",
    "반납",
    "pick-up",
    "drop-off",
    "취소",
    "환불",
    "cancel",
    "refund",
    "결제",
    "청구",
    "합계",
    "총액",
    "total",
    "paid",
    "charged",
    "payment",
    "카드",
    "card",
)

_QUOTE_PREFIXES = ("-----Original Message-----", "보낸 사람:", "From:")
_ON_WROTE_RE = re.compile(r"^On\b.*\bwrote:\s*$", re.I)


def _is_important(line: str) -> bool:
    if _AMOUNT_RE.search(line) or _DATE_RE.search(line):
        return True
    lowered = line.lower()
    return any(keyword.lower() in lowered for keyword in _KEYWORDS)


def _to_plain_text(body: str) -> str:
    text = _DATA_URI_RE.sub("", body)
    text = _SCRIPT_STYLE_RE.sub("", text)
    text = _COMMENT_RE.sub("", text)
    text = _BLOCK_TAG_RE.sub("\n", text)
    text = _ANY_TAG_RE.sub("", text)
    return html.unescape(text)


def _sender_domain(sender: str) -> str:
    match = _EMAIL_RE.search(sender)
    if match:
        return match.group(1)
    return sender.strip()


def _byte_size(lines) -> int:
    return len("\n".join(lines).encode("utf-8"))


def make_excerpt(
    subject: str,
    sender: str,
    sent_date: str,
    body: str,
    max_bytes: int = 4096,
    context_lines: int = 1,
) -> dict:
    """Return ``{text, truncated, kept_lines, total_lines}`` for a mail."""
    if body is None:
        body = ""
    body = str(body)
    body = _DATA_URI_RE.sub("", body)

    if _HTML_TAG_RE.search(body):
        body = _to_plain_text(body)

    # Split into lines; drop blanks and consecutive duplicates.
    total_lines = 0
    lines: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if lines and lines[-1] == line:
            continue
        lines.append(line)
        total_lines += 1

    # Drop quoted prior mail from the marker onward.
    for index, line in enumerate(lines):
        if line.startswith(">"):
            lines = lines[:index]
            break
        if line.startswith(_QUOTE_PREFIXES) or _ON_WROTE_RE.match(line):
            lines = lines[:index]
            break

    context = max(0, context_lines)
    important = [i for i, line in enumerate(lines) if _is_important(line)]

    selected: list[str] = []
    if important:
        ranges: list[list[int]] = []
        for index in important:
            start = max(0, index - context)
            end = min(len(lines) - 1, index + context)
            if ranges and start <= ranges[-1][1] + 1:
                ranges[-1][1] = max(ranges[-1][1], end)
            else:
                ranges.append([start, end])
        previous_end = -2
        for start, end in ranges:
            if selected and start > previous_end + 1:
                selected.append("...")
            selected.extend(lines[start : end + 1])
            previous_end = end
    else:
        selected = lines[:5]

    subject = "" if subject is None else str(subject)
    sender = "" if sender is None else str(sender)
    sent_date = "" if sent_date is None else str(sent_date)
    header = [
        "제목: " + subject,
        "발신: " + _sender_domain(sender),
        "발송일: " + sent_date,
    ]

    out_lines = header + selected
    truncated = False
    header_count = len(header)
    if _byte_size(out_lines) > max_bytes:
        truncated = True
        body_lines = out_lines[header_count:]
        while body_lines and _byte_size(
            out_lines[:header_count] + body_lines + ["[잘림]"]
        ) > max_bytes:
            body_lines.pop()
        if _byte_size(out_lines[:header_count] + body_lines + ["[잘림]"]) > max_bytes:
            while header_count > 1 and _byte_size(
                out_lines[:header_count] + ["[잘림]"]
            ) > max_bytes:
                header_count -= 1
        out_lines = out_lines[:header_count] + body_lines + ["[잘림]"]

    kept_lines = sum(
        1
        for line in out_lines[header_count:]
        if line != "[잘림]" and line != "..."
    )
    return {
        "text": "\n".join(out_lines),
        "truncated": truncated,
        "kept_lines": kept_lines,
        "total_lines": total_lines,
    }
