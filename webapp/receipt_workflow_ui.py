"""Paseo-backed receipt processing screen.

The receipt_workflow backend owns model execution and persisted review state. This
module renders the browser UI and only calls its authenticated HTTP contract.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

_STATIC = Path(__file__).resolve().parent / "static"
WORKFLOW_CSS = (_STATIC / "css" / "receipt_workflow.css").read_text(encoding="utf-8")
WORKFLOW_SCRIPT = (_STATIC / "js" / "receipt_workflow.js").read_text(encoding="utf-8")


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _script_json(value: object) -> str:
    """Serialize data safely inside HTML script text, including hostile strings."""
    return (json.dumps(value, ensure_ascii=True)
            .replace("&", "\\u0026")
            .replace("<", "\\u003c")
            .replace(">", "\\u003e"))


def _image_rows(data: dict) -> list[dict]:
    pdfs = {item.get("sha256"): item for item in data.get("pdfs", []) if isinstance(item, dict)}
    uploads = {item.get("sha256"): item for item in data.get("uploads", []) if isinstance(item, dict)}
    page_labels: dict[str, str] = {}
    for pdf_sha, pdf in pdfs.items():
        for index, image_sha in enumerate(pdf.get("pages", []), 1):
            page_labels.setdefault(image_sha, f"PDF {index}페이지")
    rows = []
    for image_sha in data.get("images", []):
        if not isinstance(image_sha, str) or len(image_sha) != 64:
            continue
        upload = uploads.get(image_sha)
        rows.append({
            "sha": image_sha,
            "name": (upload or {}).get("name") or page_labels.get(image_sha) or "저장된 사진",
            "source": "PDF 페이지" if image_sha in page_labels else "사진",
        })
    return rows


def render_panel(data: dict, csrf: str, trips: list[dict] | None = None) -> str:
    """Render a scoped panel to insert above the existing receipt review UI."""
    trips = trips or []
    image_rows = _image_rows(data)
    photos = "".join(
        "<label class='rw-photo-choice'>"
        f"<input type='checkbox' data-rw-image value='{_e(row['sha'])}' aria-label='{_e(row['name'])} 분석 대상으로 선택'>"
        "<span class='rw-photo-thumb'>"
        f"<img src='/api/receipts/image/{_e(row['sha'])}' loading='lazy' width='96' height='112' alt='저장된 영수증 원본'>"
        "</span><span class='rw-photo-copy'>"
        f"<strong>{_e(row['name'])}</strong><small>{_e(row['source'])}</small>"
        "</span></label>"
        for row in image_rows
    )
    initial_photos = photos or "<p class='rw-empty' data-rw-no-photos>저장된 사진이 없습니다. 위에서 사진을 올려 주세요.</p>"
    csrf_json = _script_json(csrf)
    trips_json = _script_json(trips)
    return (
        "<section id='receipt-workflow-panel' aria-labelledby='rw-main-title'>"
        "<div class='rw-title-row'><div><p class='rw-eyebrow'>Paseo 사진 처리</p><h2 id='rw-main-title'>사진을 장부 내역으로</h2>"
        "<p class='rw-intro'>사진을 올리고 처리할 모델을 고르면 분석이 시작됩니다. 결과는 서버에 저장되어 다른 페이지를 이용한 뒤에도 이어서 검수할 수 있습니다.</p></div>"
        "<a class='rw-classic-link' href='/receipts?mode=classic'>기존 검수·직접 입력</a></div>"
        "<section class='rw-panel rw-upload-panel' aria-labelledby='rw-upload-title'>"
        "<div class='rw-section-heading'><div><p class='rw-step'>1</p><h2 id='rw-upload-title'>사진 올리기</h2></div>"
        "<span class='rw-support-note'>PNG·JPEG·PDF · 파일당 최대 5MB</span></div>"
        "<label class='rw-file-label' for='rw-files'>사진 또는 PDF 파일 선택</label>"
        "<input id='rw-files' type='file' accept='image/jpeg,image/png,application/pdf,.jpg,.jpeg,.png,.pdf' multiple>"
        "<div class='rw-upload-actions'><button type='button' id='rw-upload-button' class='rw-button rw-secondary'>선택한 원본 저장</button>"
        "<span id='rw-upload-status' role='status' aria-live='polite'></span></div>"
        "<p class='rw-hint'>HEIC 등 추가 형식과 기존 초안·수동 입력은 <a href='/receipts?mode=classic'>기존 검수·직접 입력 화면</a>에서 사용할 수 있습니다.</p>"
        "</section>"
        "<section class='rw-panel' aria-labelledby='rw-photos-title'>"
        "<div class='rw-section-heading'><div><p class='rw-step'>2</p><h2 id='rw-photos-title'>분석할 사진</h2></div>"
        "<div class='rw-inline-actions'><button type='button' id='rw-select-all' class='rw-button rw-quiet'>전체 선택</button>"
        "<button type='button' id='rw-clear-selection' class='rw-button rw-quiet'>선택 해제</button></div></div>"
        f"<div id='rw-photo-list' class='rw-photo-list' aria-describedby='rw-photo-help'>{initial_photos}</div>"
        "<p id='rw-photo-help' class='rw-hint'>사진은 처음에 선택되지 않습니다. 필요한 원본만 선택하세요.</p>"
        "</section>"
        "<section class='rw-panel rw-model-panel' aria-labelledby='rw-model-title'>"
        "<div class='rw-section-heading'><div><p class='rw-step'>3</p><h2 id='rw-model-title'>모델 선택</h2></div>"
        "<button type='button' id='rw-catalog-refresh' class='rw-button rw-quiet'>목록 새로고침</button></div>"
        "<p id='rw-host-status' class='rw-host-status' role='status' aria-live='polite'>연결된 로컬 Paseo 목록을 불러오는 중입니다.</p>"
        "<div class='rw-model-controls'><label for='rw-provider'>Provider</label><select id='rw-provider'><option value=''>Provider 선택</option></select>"
        "<label for='rw-model'>Model</label><select id='rw-model' disabled><option value=''>Provider를 먼저 선택하세요</option></select></div>"
        "<p id='rw-model-reason' class='rw-hint' aria-live='polite'>목록 탐색은 모델을 실행하지 않습니다.</p>"
        "<button type='button' id='rw-run-model' class='rw-button rw-primary' disabled>이 모델로 처리</button>"
        "<p class='rw-hint'>승인된 사진 처리 경로만 실행할 수 있습니다. 분석 지시는 관리되는 기본 설정을 사용합니다.</p>"
        "</section>"
        "<p id='rw-page-status' class='rw-page-status' role='status' aria-live='polite'></p>"
        "<section class='rw-panel rw-results-panel' aria-labelledby='rw-results-title'>"
        "<div class='rw-section-heading'><div><p class='rw-step'>4</p><h2 id='rw-results-title'>처리 결과와 검수</h2></div>"
        "<button type='button' id='rw-refresh' class='rw-button rw-quiet'>결과 새로고침</button></div>"
        "<div id='rw-batches'><p class='rw-empty'>저장된 분석 결과를 불러오는 중입니다.</p></div>"
        "<div class='rw-apply-bar'><p id='rw-selection-summary' aria-live='polite'>선택된 내역 0건</p>"
        "<button type='button' id='rw-apply' class='rw-button rw-primary' disabled>선택한 내역을 장부에 반영</button></div>"
        "<p class='rw-hint'>처리 결과는 자동으로 장부에 반영되지 않습니다. 확인하고 선택한 내역만 한 번에 반영합니다.</p>"
        "</section></section>"
        f"<script>window.RECEIPT_WORKFLOW_CSRF={csrf_json};window.RECEIPT_WORKFLOW_TRIPS={trips_json};</script>"
    )
