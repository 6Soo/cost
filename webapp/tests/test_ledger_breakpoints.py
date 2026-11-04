"""합성 LedgerStore와 실제 Chromium으로 화면 경계와 저장 흐름을 검증한다."""
import json
import os
import unittest
import uuid
from pathlib import Path

# 모듈로 가져와 기존 TestCase를 이 모듈에서 다시 수집하지 않는다.
from webapp.tests import test_ledger_redesign_desktop as helpers

VIEWPORTS = [(375, 844), (390, 844), (391, 844), (430, 900),
             (759, 900), (760, 900), (1099, 900), (1100, 900),
             (1440, 900), (1920, 1080)]

GEOMETRY = r"""() => {
 const rect=e=>{const r=e.getBoundingClientRect();return {
  left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
 const shown=e=>!!e.getClientRects().length;
 const texts=e=>{const a=[];const walk=document.createTreeWalker(e,NodeFilter.SHOW_TEXT);
  while(walk.nextNode()){const n=walk.currentNode;if(!n.textContent.trim()||!shown(n.parentElement))continue;
   const r=document.createRange();r.selectNodeContents(n);
   for(const b of r.getClientRects())a.push({text:n.textContent.trim(),left:b.left,right:b.right,top:b.top,bottom:b.bottom});
  }return a;};
 const box=e=>({...rect(e),scrollWidth:e.scrollWidth,clientWidth:e.clientWidth,
  scrollHeight:e.scrollHeight,clientHeight:e.clientHeight,scrollTop:e.scrollTop});
 const p=document.querySelector('#panel');const ft=p.querySelector('.p-ft');
 return {viewport:{width:innerWidth,height:innerHeight},fontReady:document.fonts.status,
  overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,
  document:box(document.documentElement),body:box(document.body),panel:box(p),
  panelPosition:getComputedStyle(p).position,footer:box(ft),panelBody:box(p.querySelector('.p-bd')),
  buttons:[...ft.querySelectorAll('.btn')].filter(shown).map(e=>({id:e.id||'save',
   text:e.innerText,...box(e),texts:texts(e),kbd:[...e.querySelectorAll('.kbd')].map(k=>({
    text:k.textContent,visible:shown(k),...rect(k)})),
   hit:(()=>{const r=e.getBoundingClientRect();const h=document.elementFromPoint((r.left+r.right)/2,(r.top+r.bottom)/2);return !!h&&(h===e||e.contains(h));})()}))};
}"""


class LedgerBreakpointTests(unittest.TestCase):
    setUp = helpers.DesktopLedgerRedesignTests.setUp
    _board = helpers.DesktopLedgerRedesignTests._board

    def tearDown(self):
        # 기존 helper가 별도로 연 서버 저장소도 함께 닫는다.
        try:
            helpers.DesktopLedgerRedesignTests.tearDown(self)
        finally:
            self.server.card_store.close()

    def _ready(self, page):
        page.evaluate("() => document.fonts.ready.then(() => true)")
        page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")

    def _accept_dialog(self, dialog):
        dialog.accept()

    def _check(self, record, name, actual, expected=True):
        record["checks"].append({"name": name, "actual": actual,
                                 "expected": expected, "passed": actual == expected})

    def _goto(self, page, **state):
        self._board(page, helpers.board_url(**state))
        self._ready(page)

    def _rows(self, page, mobile):
        selector = ".lst .li[data-id]" if mobile else ".tw tr[data-id]"
        return page.locator(selector).evaluate_all("es=>es.map(e=>e.dataset.id)")

    def _selection(self, page, record, mobile, row, position):
        page.wait_for_function("id=>document.querySelector('#panel')?.dataset.row===id", arg=row)
        page.wait_for_function("s=>document.querySelector('#p-count')?.textContent===s", arg=position)
        selector = ".lst .li" if mobile else ".tw tr"
        page.wait_for_function("""({selector, row}) => {
            const selected = [...document.querySelectorAll(
                selector + "[data-id][aria-selected='true']")];
            return selected.length === 1 && selected[0].dataset.id === row;
        }""", arg={"selector": selector, "row": row})
        selected = page.locator(selector + "[data-id][aria-selected='true']").evaluate_all(
            "es=>es.map(e=>e.dataset.id)")
        self._check(record, "선택 행 " + position, selected, [row])
        self._check(record, "주소 행 " + position, page.evaluate(
            "new URL(location.href).searchParams.get('row')"), row)
        record.setdefault("positions", []).append({"position": position, "row": row, "selected": selected})

    def _geometry(self, page, record, label):
        self._ready(page)
        g = page.evaluate(GEOMETRY)
        record.setdefault("geometry", {})[label] = g
        self._check(record, label + " 가로 넘침", g["overflow"], 0)
        p, f, b = g["panel"], g["footer"], g["panelBody"]
        self._check(record, label + " 패널 뷰포트", p["left"] >= -1 and p["right"] <= g["viewport"]["width"] + 1
                    and p["top"] >= -1 and p["bottom"] <= g["viewport"]["height"] + 1)
        self._check(record, label + " 본문 푸터 겹침 없음", b["bottom"] <= f["top"] + 1)
        self._check(record, label + " 문서 세로 스크롤 없음",
                    g["document"]["scrollHeight"] <= g["viewport"]["height"] + 1)
        self._check(record, label + " 푸터 넘침 없음", f["scrollWidth"] <= f["clientWidth"])
        self._check(record, label + " 패널 위치", g["panelPosition"],
                    "fixed" if g["viewport"]["width"] < 1100 else "static")
        buttons = g["buttons"]
        for i, btn in enumerate(buttons):
            prefix = label + " " + btn["id"]
            self._check(record, prefix + " 버튼 clip 없음", btn["scrollWidth"] <= btn["clientWidth"])
            self._check(record, prefix + " 클릭 가능", btn["hit"])
            self._check(record, prefix + " 푸터 내부", btn["left"] >= f["left"] and btn["right"] <= f["right"]
                        and btn["top"] >= f["top"] and btn["bottom"] <= f["bottom"])
            for text in btn["texts"]:
                self._check(record, prefix + " 텍스트 내부 " + text["text"],
                            text["left"] >= btn["left"] - 1 and text["right"] <= btn["right"] + 1
                            and text["top"] >= btn["top"] - 1 and text["bottom"] <= btn["bottom"] + 1)
            for k in btn["kbd"]:
                self._check(record, prefix + " 단축키 표시 " + k["text"], k["visible"], g["viewport"]["width"] > 390)
                if k["visible"]:
                    self._check(record, prefix + " 단축키 내부 " + k["text"],
                                k["left"] >= btn["left"] and k["right"] <= btn["right"]
                                and k["top"] >= btn["top"] and k["bottom"] <= btn["bottom"])
            for other in buttons[i + 1:]:
                self._check(record, prefix + " 버튼 겹침 없음 " + other["id"],
                            min(btn["right"], other["right"]) <= max(btn["left"], other["left"]) + 0.5
                            or min(btn["bottom"], other["bottom"]) <= max(btn["top"], other["top"]) + 0.5)

    def _layout(self, page, record, mobile):
        self._goto(page)
        self._check(record, "장부 가로 넘침", helpers.overflow(page), 0)
        self._check(record, "목록 행 순서", self._rows(page, mobile), helpers.ALL_ROWS)
        self._check(record, "모바일 목록 표시", page.is_visible('.lst'), mobile)
        self._check(record, "표 표시", page.is_visible('.tw'), not mobile)
        self._check(record, "메뉴 버튼 표시", page.is_visible('#btn-menu'), mobile)
        if mobile:
            nav = page.locator('#nav').bounding_box()
            self._check(record, "닫힌 drawer 화면 밖", nav['x'] + nav['width'] <= 1)
            page.click('#btn-menu')
            page.wait_for_function("document.querySelector('#nav').getBoundingClientRect().left>=-1")
            self._check(record, "열린 drawer", page.is_visible('.nav.open') and page.is_visible('#nav-mask'))
            record['drawer'] = page.locator('#nav').bounding_box()
            page.click('#nav-mask', position={"x": record['width'] - 5, "y": 100})
            page.wait_for_function("!document.querySelector('#nav').classList.contains('open')")
            self._check(record, "drawer 닫힘", page.is_hidden('#nav-mask'))
        else:
            self._check(record, "데스크톱 nav 화면 내부", page.locator('#nav').bounding_box()['x'], 0)
        groups = page.locator('.lst .lg > span:first-child' if mobile else 'tbody.grp th:first-child').all_text_contents()
        self._check(record, "수입 지출 표시", groups, ['수입', '지출'])
        selector = '.lst .li .a' if mobile else '.tw td.c-amt'
        amounts = page.locator(selector).evaluate_all("""es=>es.map(e=>{const r=e.getBoundingClientRect();
          const range=document.createRange();range.selectNodeContents(e);const t=range.getBoundingClientRect();
          let visible=t.left>=r.left-1&&t.right<=r.right+1;let a=e.parentElement;
          while(a){const s=getComputedStyle(a);if(['hidden','clip','auto','scroll'].includes(s.overflowX)){
           const b=a.getBoundingClientRect();visible=visible&&t.left>=b.left-1&&t.right<=b.right+1;}a=a.parentElement;}
          return {text:e.textContent,left:r.left,right:r.right,textLeft:t.left,textRight:t.right,
           scroll:e.scrollWidth,client:e.clientWidth,unclipped:visible};})""")
        record['amounts'] = amounts
        self._check(record, "모든 금액 clip 없음", len(amounts) == 6 and all(a['unclipped'] and a['scroll'] <= a['client'] for a in amounts))

    def _flow(self, page, record, mobile):
        self._goto(page)
        page.click((".lst .li" if mobile else "#tbl tr") + "[data-id='income-demo-i2']")
        self._selection(page, record, mobile, 'income-demo-i2', '2 / 6')
        self._geometry(page, record, '열기')
        page.click('#panel .p-src summary')
        page.locator('.p-bd').evaluate('e=>e.scrollTop=e.scrollHeight')
        self._geometry(page, record, '본문 끝')
        body = record['geometry']['본문 끝']['panelBody']
        # 긴 화면에서 내용이 다 들어가면 스크롤이 필요 없다. 넘치는 경우에는
        # 실제 끝까지 이동해야 하며, 문서 대신 패널 본문이 스크롤해야 한다.
        self._check(record, '실제 패널 본문 스크롤',
                    abs(body['scrollTop'] - max(0, body['scrollHeight'] - body['clientHeight'])) <= 1)
        page.locator('.p-bd').evaluate('e=>e.scrollTop=0')
        rid = 'income-demo-i2'
        before = self.store.get_row(rid)
        note = '화면 경계 저장 ' + str(record['width'])
        page.fill('#f-operator_note', note)
        asked = []
        def dismiss(dialog):
            asked.append(dialog.message)
            dialog.dismiss()
        page.remove_listener('dialog', self._accept_dialog)
        page.on('dialog', dismiss)
        try:
            page.click('#p-next')
            self._check(record, '미저장 이동 확인 요청', len(asked), 1)
            self._selection(page, record, mobile, rid, '2 / 6')
            self._check(record, '이동 거절 입력 보존', page.input_value('#f-operator_note'), note)
            self._check(record, '이동 거절 revision 보존', self.store.get_row(rid)['revision'], before['revision'])
            record['unsaved_guard'] = {'messages': asked, 'input': page.input_value('#f-operator_note')}
        finally:
            page.remove_listener('dialog', dismiss)
            page.on('dialog', self._accept_dialog)
        route = '**/api/rows/' + rid + '/save'
        failures = []
        def abort(request):
            failures.append(request.request.method)
            request.abort('failed')
        page.route(route, abort)
        page.click('#panel button[type=submit]')
        page.wait_for_function("document.querySelector('.f-msg').textContent.includes('요청을 보내지 못')")
        self._check(record, '실제 저장 요청 중단', failures, ['POST'])
        self._check(record, '실패 입력 보존', page.input_value('#f-operator_note'), note)
        self._check(record, '실패 저장소 revision 보존', self.store.get_row(rid)['revision'], before['revision'])
        self._check(record, '실패 저장소 값 보존', self.store.get_row(rid).get('operator_note'), before.get('operator_note'))
        self._check(record, '실패 dirty 보존', page.get_attribute('form[data-js-save]', 'data-dirty'), '1')
        record['abort'] = {'message': page.inner_text('.f-msg'), 'input': page.input_value('#f-operator_note'),
                           'saving': page.get_attribute('form[data-js-save]', 'data-saving')}
        self._check(record, '실패 후 in-flight 종료', record['abort']['saving'], None)
        asked.clear()
        page.remove_listener('dialog', self._accept_dialog)
        page.on('dialog', dismiss)
        try:
            page.click('#p-next')
            record['abort']['moveMessages'] = list(asked)
            record['abort']['afterMoveMessage'] = page.inner_text('.f-msg')
            self._check(record, '실패 후 이동 확인 접근', len(asked), 1)
            self._selection(page, record, mobile, rid, '2 / 6')
            self._check(record, '실패 후 이동 거절 입력 보존', page.input_value('#f-operator_note'), note)
        finally:
            page.remove_listener('dialog', dismiss)
            page.on('dialog', self._accept_dialog)
        page.unroute(route, abort)
        # 실제 클릭으로 재시도한다. Ctrl+Enter도 아래에서 별도로 저장한다.
        page.click('#panel button[type=submit]')
        page.wait_for_function("document.querySelector('.f-msg').textContent.includes('저장했습니다')")
        after = self.store.get_row(rid)
        self._check(record, 'retry 저장 값', after.get('operator_note'), note)
        self._check(record, 'retry revision', after['revision'], before['revision'] + 1)
        self._selection(page, record, mobile, rid, '2 / 6')
        page.fill('#f-operator_note', note + ' 단축키')
        page.keyboard.press('Control+Enter')
        page.wait_for_function("rev=>document.querySelector('input[name=expected_revision]').value===String(rev)", arg=after['revision'] + 1)
        self._check(record, 'Ctrl+Enter 실제 저장', self.store.get_row(rid).get('operator_note'), note + ' 단축키')
        for button, row, pos in [('#p-next', 'income-demo-i3', '3 / 6'), ('#p-prev', rid, '2 / 6')]:
            page.click(button)
            self._selection(page, record, mobile, row, pos)
            self._geometry(page, record, pos)
        self._check(record, '다시 연 저장 값', page.input_value('#f-operator_note'), note + ' 단축키')
        with page.expect_navigation():
            page.keyboard.press('Escape')
        self._ready(page)
        self._check(record, 'Esc 패널 닫힘', page.locator('#panel').count(), 0)
        self._check(record, 'Esc 저장 값 유지', self.store.get_row(rid).get('operator_note'), note + ' 단축키')
        record['save'] = {'beforeRevision': before['revision'], 'retryRevision': after['revision'],
                          'finalRevision': self.store.get_row(rid)['revision'], 'note': note + ' 단축키'}

    def _filters(self, page, record, mobile):
        self._goto(page)
        page.fill('#q', '숙소')
        with page.expect_navigation():
            page.click('#q-go')
        self._ready(page)
        self._check(record, '검색 실제 결과', self._rows(page, mobile), helpers.ALL_ROWS[3:])
        with page.expect_navigation():
            page.click('#q-clear')
        self._ready(page)
        self._check(record, '검색 초기화', self._rows(page, mobile), helpers.ALL_ROWS)
        for kind, expected in [('ex', helpers.ALL_ROWS[3:]), ('in', helpers.ALL_ROWS[:3])]:
            with page.expect_navigation():
                page.select_option('#kind', kind)
            self._ready(page)
            self._check(record, '종류 필터 ' + kind, self._rows(page, mobile), expected)
            self._check(record, '필터 넘침 ' + kind, helpers.overflow(page), 0)

    def _manual(self, page, record, mobile):
        self._goto(page)
        selector = '.lst #add-manual-expense-mobile' if mobile else '.tw #add-manual-expense'
        link = page.locator(selector)
        self._check(record, '수기 지출 링크 수', link.count(), 1)
        if link.count() != 1:
            record['expected_failure'] = '모바일 수기 지출 링크가 없어 접근할 수 없습니다.'
            return
        self._check(record, '수기 지출 링크 표시', link.is_visible())
        self._check(record, '수기 지출 링크 주소', link.get_attribute('href'), '/expense/new')
        with page.expect_navigation():
            link.click()
        self._ready(page)
        self._check(record, '수기 지출 실제 화면', page.url.split('?')[0].endswith('/expense/new'))
        self._check(record, '수기 지출 입력 접근', page.locator('form input:not([type=hidden])').first.is_visible())
        self._check(record, '수기 지출 화면 넘침', helpers.overflow(page), 0)

    def _assignment(self, page, record, mobile):
        rid = 'expense-demo-c3'
        original = self.store.get_row(rid)
        self._board(page, helpers.board_url(tab='unclassified'))
        self._ready(page)
        root = '.lst' if mobile else '.tw'
        form = page.locator(root + ' form[data-js-move]').filter(
            has=page.locator("select[name='display_tab_id']"))
        try:
            self._check(record, '미배정 거래 표시', self._rows(page, mobile), [rid])
            form.locator("select[name='display_tab_id']").select_option(helpers.TRIP)
            form.locator('button[type=submit]').click()
            page.wait_for_url(lambda url: 'tab=unclassified' in url and 'msg=' in url)
            self._ready(page)
            moved = self.store.get_row(rid)
            self._check(record, '여행 배정 실제 저장', moved['display_tab_id'], helpers.TRIP)
            self._check(record, '여행 배정 revision', moved['revision'], original['revision'] + 1)
            self._check(record, '미배정 목록에서 제거', self._rows(page, mobile), [])
            record['assignment'] = {'row': rid, 'tab': moved['display_tab_id'], 'revision': moved['revision']}
        finally:
            # 다음 폭에도 동일한 합성 거래를 제공한다. 제품 저장 코드는 변경하지 않는다.
            with self.server.store_lock:
                current = self.store.get_row(rid)
                if current['display_tab_id'] != original['display_tab_id']:
                    self.store.save(row_id=rid, expected_revision=current['revision'],
                                    changes={'display_tab_id': original['display_tab_id']},
                                    change_mode='exception', client_request_id=uuid.uuid4().hex,
                                    actor='owner')

    def test_parameterized_breakpoints(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        results = {'browser': self._browser.version, 'synthetic': True,
                   'viewports': [], 'mobile_link': '총괄이 허용한 최소 HTML 링크를 격리 사본에 동기화했습니다.'}
        try:
            for width, height in VIEWPORTS:
                with self.subTest(width=width, height=height):
                    context = self._browser.new_context(viewport={'width': width, 'height': height})
                    page = context.new_page()
                    page.set_default_timeout(8000)
                    page.on('dialog', self._accept_dialog)
                    record = {'width': width, 'height': height, 'checks': [], 'errors': []}
                    results['viewports'].append(record)
                    try:
                        for stage in (self._layout, self._flow, self._filters, self._manual, self._assignment):
                            try:
                                stage(page, record, width < 760)
                            except Exception as exc:
                                record['errors'].append({'stage': stage.__name__, 'error': str(exc)})
                        for check in record['checks']:
                            with self.subTest(width=width, check=check['name']):
                                self.assertEqual(check['actual'], check['expected'])
                        for error in record['errors']:
                            with self.subTest(width=width, stage=error['stage']):
                                self.fail(error['error'])
                    finally:
                        context.close()
        finally:
            evidence_dir = Path(os.environ.get('WEBLEDGER_BREAKPOINT_EVIDENCE') or self.tmp)
            evidence_dir.mkdir(parents=True, exist_ok=True)
            name = os.environ.get('BREAKPOINT_EVIDENCE_NAME', 'results')
            (evidence_dir / (name + '.json')).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
