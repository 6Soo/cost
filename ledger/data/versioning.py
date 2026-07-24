# -*- coding: utf-8 -*-
"""산출물 버전 자동관리(2026-07-24, 사용자 지적 "버전이 또 안 올라가고 있어").
P9(원장 C절): "내용이 바뀌면 파일명 버전(_vNN)도 반드시 올린다"는 사람이 기억해서
지키는 규칙이었다 — 로직을 여러 번 고치는 동안 매번 잊고 같은 파일명으로 다른 내용을
덮어써왔다. 이 모듈은 그 판단을 코드로 넘긴다: 실제로 내용이 달라졌을 때만, 자동으로
다음 버전 번호를 골라 새 파일명으로 저장한다. 내용이 같으면(재실행만 한 경우) 버전을
올리지 않고 기존 파일명을 유지한다(불필요한 버전 인플레이션 방지).

레지스트리(output_versions.json)에 논리적 이름(key)→현재 실제 파일명을 기록해두고,
다른 스크립트(예: consolidate_2q.py)가 이 레지스트리로 "지금 진짜 최신 파일명"을
알아내게 해서, gen_april_rev.py가 버전을 올려도 consolidate_2q.py가 구버전 파일명을
그대로 찾다가 깨지는 일이 없게 한다.
"""
import json, hashlib, os, re

def _content_hash(path):
    """xlsx는 저장할 때마다 docProps(생성시각 등) 메타데이터가 바뀌어 원시 바이트 해시로는
    항상 '다름'으로 나온다(2026-07-24 실측: 완전히 동일한 재실행에도 매번 버전이 올라감) —
    실제 내용(시트별 셀 값)만 뽑아 해시한다. xlsx가 아니면 원시 바이트로 폴백."""
    if path.lower().endswith(('.xlsx', '.xlsm')):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            h = hashlib.sha256()
            for name in wb.sheetnames:
                h.update(name.encode('utf-8'))
                for row in wb[name].iter_rows(values_only=True):
                    for v in row:
                        h.update(repr(v).encode('utf-8'))
            return h.hexdigest()
        except Exception:
            pass
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()

REG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output_versions.json')

def _load_registry():
    if os.path.exists(REG_PATH):
        return json.load(open(REG_PATH, encoding='utf-8'))
    return {}

def _save_registry(reg):
    json.dump(reg, open(REG_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=2, sort_keys=True)

def current_path(key, base_name, ext='xlsx'):
    """key로 등록된 현재 파일명을 반환. 레지스트리에 없으면 디렉터리에서 base_name_vN.ext 중
    가장 높은 N을 찾고, 그것도 없으면 base_name_v1.ext를 가정."""
    reg = _load_registry()
    if key in reg and os.path.exists(reg[key]):
        return reg[key]
    pat = re.compile(r'^' + re.escape(base_name) + r'_v(\d+)\.' + re.escape(ext) + r'$')
    cands = [(int(m.group(1)), f) for f in os.listdir('.') if (m := pat.match(f))]
    if cands:
        return max(cands)[1]
    return f'{base_name}_v1.{ext}'

def save_versioned(key, base_name, write_fn, ext='xlsx'):
    """write_fn(path)이 실제 저장을 수행한다. 직전 등록 파일과 내용(해시)이 다르면 버전을
    올려 새 파일명으로 저장하고, 같으면 기존 파일명을 유지(덮어쓰기)한다. 최종 파일명 반환."""
    current = current_path(key, base_name, ext)
    tmp = '.tmp_versioning_' + current
    write_fn(tmp)
    new_hash = _content_hash(tmp)
    old_hash = _content_hash(current) if os.path.exists(current) else None
    if old_hash == new_hash:
        os.replace(tmp, current)
        final = current
        print('[versioning] %s: 내용 변경 없음 — %s 유지' % (key, final))
    else:
        m = re.search(r'_v(\d+)\.', current)
        nextv = (int(m.group(1)) + 1) if m else 1
        final = '%s_v%d.%s' % (base_name, nextv, ext)
        os.replace(tmp, final)
        if old_hash is not None:
            print('[versioning] %s: 내용 변경 감지 → %s → %s (버전 자동상승)' % (key, current, final))
        else:
            print('[versioning] %s: 신규 생성 %s' % (key, final))
    reg = _load_registry()
    reg[key] = final
    _save_registry(reg)
    return final
