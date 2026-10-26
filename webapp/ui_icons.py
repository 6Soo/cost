"""작은 선형 SVG 아이콘 집합. 외부 요청·폰트·패키지 없이 동작한다.

시각 방향은 Lucide 선형 아이콘(24px viewBox, 둥근 선 끝)을 따르며,
아래 경로는 COST용으로 직접 작성한 단순 도형이다. Lucide 공식 SVG를
복사하지 않았으므로 특정 버전의 경로와 동일하다고 주장하지 않는다.
방향 참고와 라이선스 고지는 docs/design/icon-license.md에 기록한다.

사용 규칙:
- 허용된 이름만 렌더링한다. 알 수 없는 이름은 빈 문자열을 돌려준다.
- 장식용이므로 항상 aria-hidden이며 클릭은 부모 버튼에 전달된다.
- 버튼의 접근 가능한 이름(문구·aria-label)을 바꾸지 않는다.
"""

from __future__ import annotations

import html

_SIZE = {14, 16, 18}

# 각 값은 <svg> 안쪽 요소 문자열이다. 24x24, 채움 없음, 선 색상은
# currentColor를 그대로 사용하므로 버튼 글자색을 따라간다.
ICONS = {
    "sun": "<circle cx='12' cy='12' r='4'/><path d='M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5'/>",
    "moon": "<path d='M21 13a9 9 0 0 1-10-10A9 9 0 1 0 21 13z'/>",
    "plane": "<path d='m22 2-7 20-4-9-9-4z'/><path d='m22 2-11 11'/>",
    "bed": "<path d='M3 18V6m18 12V10H3m0 5h18M7 10V7h6v3'/>",
    "bus": "<rect x='5' y='3' width='14' height='17' rx='3'/><path d='M5 11h14M8 20v2m8-2v2M8 15h.01M16 15h.01'/>",
    "utensils": "<path d='M4 3v6a3 3 0 0 0 6 0V3M7 3v19M20 22V3c-5 3-5 10 0 10'/>",
    "map-pin": "<path d='M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 0 1 16 0z'/><circle cx='12' cy='10' r='3'/>",
    "house": (
        "<path d='M3 10.5 12 3l9 7.5'/>"
        "<path d='M5 9.5V21h14V9.5'/>"
        "<path d='M10 21v-6h4v6'/>"
    ),
    "book-open": (
        "<path d='M2 4h6a4 4 0 0 1 4 4v12a3 3 0 0 0-3-3H2z'/>"
        "<path d='M22 4h-6a4 4 0 0 0-4 4v12a3 3 0 0 1 3-3h7z'/>"
    ),
    "map": (
        "<path d='M9 4 3 6v14l6-2 6 2 6-2V4l-6 2z'/>"
        "<path d='M9 4v14'/>"
        "<path d='M15 6v14'/>"
    ),
    "credit-card": (
        "<rect x='2' y='5' width='20' height='14' rx='2'/>"
        "<path d='M2 10h20'/>"
    ),
    "list": (
        "<path d='M8 6h13'/>"
        "<path d='M8 12h13'/>"
        "<path d='M8 18h13'/>"
        "<path d='M3 6h.01'/>"
        "<path d='M3 12h.01'/>"
        "<path d='M3 18h.01'/>"
    ),
    "receipt": (
        "<path d='M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2z'/>"
        "<path d='M8 7h8'/>"
        "<path d='M8 11h8'/>"
    ),
    "table": (
        "<rect x='3' y='4' width='18' height='16' rx='2'/>"
        "<path d='M3 10h18'/>"
        "<path d='M9 10v10'/>"
    ),
    "link": (
        "<path d='M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7'/>"
        "<path d='M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7'/>"
    ),
    "users": (
        "<path d='M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2'/>"
        "<circle cx='9' cy='7' r='4'/>"
        "<path d='M22 21v-2a4 4 0 0 0-3-3.9'/>"
        "<path d='M16 3.1a4 4 0 0 1 0 7.8'/>"
    ),
    "upload": (
        "<path d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'/>"
        "<path d='M17 8l-5-5-5 5'/>"
        "<path d='M12 3v12'/>"
    ),
    "search": (
        "<circle cx='11' cy='11' r='7'/>"
        "<path d='m21 21-4.3-4.3'/>"
    ),
    "pencil": (
        "<path d='M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z'/>"
    ),
    "save": (
        "<path d='M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z'/>"
        "<path d='M17 21v-8H7v8'/>"
        "<path d='M7 3v5h8'/>"
    ),
    "check": "<path d='M20 6 9 17l-5-5'/>",
    "copy": (
        "<rect x='9' y='9' width='13' height='13' rx='2'/>"
        "<path d='M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1'/>"
    ),
    "refresh-cw": (
        "<path d='M3 12a9 9 0 0 1 15.5-6.4L21 8'/>"
        "<path d='M21 3v5h-5'/>"
        "<path d='M21 12a9 9 0 0 1-15.5 6.4L3 16'/>"
        "<path d='M3 21v-5h5'/>"
    ),
    "rotate-ccw": (
        "<path d='M1 4v6h6'/>"
        "<path d='M3.5 15a9 9 0 1 0 2.1-9.4L1 10'/>"
    ),
    "circle-minus": (
        "<circle cx='12' cy='12' r='10'/>"
        "<path d='M8 12h8'/>"
    ),
    "calendar-days": (
        "<rect x='3' y='4' width='18' height='18' rx='2'/>"
        "<path d='M16 2v4'/>"
        "<path d='M8 2v4'/>"
        "<path d='M3 10h18'/>"
    ),
    "arrow-up-down": (
        "<path d='m21 16-4 4-4-4'/>"
        "<path d='M17 20V4'/>"
        "<path d='m3 8 4-4 4 4'/>"
        "<path d='M7 4v16'/>"
    ),
    "list-filter": (
        "<path d='M3 6h18'/>"
        "<path d='M7 12h10'/>"
        "<path d='M10 18h4'/>"
    ),
    "chevron-down": "<path d='m6 9 6 6 6-6'/>",
    "chevron-left": "<path d='m15 18-6-6 6-6'/>",
    "chevron-right": "<path d='m9 18 6-6-6-6'/>",
    "menu": (
        "<path d='M4 6h16'/>"
        "<path d='M4 12h16'/>"
        "<path d='M4 18h16'/>"
    ),
    "alert-triangle": (
        "<path d='m10.3 3.9-8.5 14a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3l-8.5-14a2 2 0 0 0-3.4 0z'/>"
        "<path d='M12 9v4'/>"
        "<path d='M12 17h.01'/>"
    ),
    "archive": (
        "<rect x='2' y='3' width='20' height='5' rx='1'/>"
        "<path d='M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8'/>"
        "<path d='M10 12h4'/>"
    ),
    "x-circle": (
        "<circle cx='12' cy='12' r='10'/>"
        "<path d='m15 9-6 6'/>"
        "<path d='m9 9 6 6'/>"
    ),
}


def icon(name: str, size: int = 16) -> str:
    """허용된 이름의 장식용 SVG를 돌려준다. 모르면 빈 문자열이다."""
    body = ICONS.get(name)
    if body is None:
        return ""
    if size not in _SIZE:
        size = 16
    return (
        f"<svg class='ic' width='{size}' height='{size}' viewBox='0 0 24 24' "
        "fill='none' stroke='currentColor' stroke-width='2' "
        "stroke-linecap='round' stroke-linejoin='round' "
        "aria-hidden='true' focusable='false'>"
        f"{body}</svg>"
    )


def esc_icon(name: str, size: int = 16) -> str:
    """이름 검증을 거친 뒤 icon()을 호출한다. 동적 입력은 절대 경로가 되지 않는다."""
    if not isinstance(name, str) or name not in ICONS:
        return ""
    return icon(name, size)
