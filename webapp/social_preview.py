"""Public brand assets only; no ledger or request values in social metadata."""
import re
from pathlib import Path

IMAGE_PATH = "/assets/og/cost-wallet-v1.png"
IMAGE_FILE = Path(__file__).parent / "static" / "og" / "cost-wallet-v1.png"
META = '''<meta property="og:type" content="website">
<meta property="og:site_name" content="COST">
<meta property="og:title" content="COST · 여행 회계를 간편하게">
<meta property="og:description" content="카드와 영수증을 정리하고 여행별 장부를 확인하세요.">
<meta property="og:url" content="https://ledger.foresttour.kr/share">
<meta property="og:locale" content="ko_KR">
<meta property="og:image" content="https://ledger.foresttour.kr/assets/og/cost-wallet-v1.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:type" content="image/png">
<meta property="og:image:alt" content="민트 배경의 초록 지갑과 COST, 여행 회계를 간편하게">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="COST · 여행 회계를 간편하게">
<meta name="twitter:image" content="https://ledger.foresttour.kr/assets/og/cost-wallet-v1.png">'''


def decorate(html: str) -> str:
    if 'property="og:image"' in html:
        return html
    return re.sub(r"</head\s*>", lambda _: META + "</head>", html,
                  count=1, flags=re.IGNORECASE)


def dispatch(handler, path: str) -> bool:
    if path == IMAGE_PATH:
        data = IMAGE_FILE.read_bytes()
        handler.send_response(200)
        handler.send_header("Content-Type", "image/png")
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Cache-Control", "public, max-age=86400")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.end_headers()
        handler.wfile.write(data)
        return True
    if path == "/share":
        handler._send('''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>COST · 여행 회계를 간편하게</title>
<style>body{margin:0;background:#eefaf1;color:#073c26;font:16px/1.6 system-ui,sans-serif}
main{max-width:900px;margin:10vh auto;padding:24px}img{width:100%;height:auto;border-radius:20px}
a{display:inline-block;margin-top:24px;padding:12px 24px;background:#146b43;color:white;border-radius:10px;text-decoration:none}</style>
</head><body><main><img src="/assets/og/cost-wallet-v1.png" width="1200" height="630" alt="COST · 여행 회계를 간편하게">
<p>카드와 영수증을 정리하고 여행별 장부를 확인하세요.</p>
<a href="/">로그인하고 시작하기</a></main></body></html>''')
        return True
    return False
