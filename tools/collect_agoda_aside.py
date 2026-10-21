"""검증한 목록의 예약을 단일 Aside REPL에서 읽고 로컬 캡처로 저장한다."""
from __future__ import annotations

import argparse
import json
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


PRELUDE = r'''(async () => {
await fs.mkdir('./artifacts/details', {recursive:true});
await openTab('https://www.agoda.com/ko-kr/account/bookings.html?navBack=true');
console.log((await snapshot(page)).tree);
globalThis.captureBooking = async function(booking, status) {
  if (!/^\d{6,20}$/.test(booking)) throw new Error('INVALID_BOOKING');
  if (await page.getByRole('button',{name:'예약 현황 페이지로 돌아가기',exact:true}).count()===1) {
    await page.getByRole('button',{name:'예약 현황 페이지로 돌아가기',exact:true}).click();
    console.log((await snapshot(page)).diff);
  }
  const names={upcoming:'다가오는 예약',completed:'완료된 예약',cancelled:'취소된 예약'};
  if (!names[status]) throw new Error('BOOKING_NOT_IN_VERIFIED_LISTS');
  await page.getByRole('tab',{name:names[status],exact:true}).click();
  console.log((await snapshot(page)).diff);
  await page.getByRole('textbox',{name:'예약 번호로 검색',exact:true}).fill(booking);
  console.log((await snapshot(page)).diff);
  await page.getByRole('textbox',{name:'예약 번호로 검색',exact:true}).press('Enter');
  let list=null;
  for(let attempt=0;attempt<5;attempt++) {
    const s=await snapshot(page);
    console.log(s.diff);
    if (/title:.*로그인|captcha|보안 확인이 필요/i.test(s.tree)) throw new Error('AUTH_REQUIRED');
    if (s.tree.includes('ID '+booking) &&
        await page.getByRole('button',{name:'예약 확인/변경하기 '+booking,exact:true}).count()===1) {list=s;break;}
    if(attempt<4) await sleep(800);
  }
  if(!list) throw new Error('BOOKING_LIST_PROOF_MISSING');
  await page.getByRole('button',{name:'예약 확인/변경하기 '+booking,exact:true}).click();
  let detail=null;
  for(let attempt=0;attempt<5;attempt++) {
    const s=await snapshot(page);
    console.log(s.diff);
    const ids=Array.from(s.tree.matchAll(/예약\s*번호\s*[:：]?\s*(\d{6,20})/g)).map(m=>m[1]);
    /* Flight pages put the booking ID in a separate node.
       Require an adjacent label, not an unrelated number on the page. */
    const flightIds=Array.from(s.tree.matchAll(/- text: "[^"\n]*예약\s*번호\s*[:：]\s*"\s*\n- generic "(\d{6,20})"/g)).map(m=>m[1]);
    if(ids.includes(booking) || flightIds.includes(booking)) {detail=s;break;}
    if(attempt<4) await sleep(800);
  }
  if(!detail) throw new Error('DETAIL_IDENTITY_NOT_CONFIRMED');
  const views=[detail.tree];
  const payment=page.getByRole('heading',{name:'결제 정보',exact:true});
  if(await payment.count()===1) {
    await payment.scrollIntoViewIfNeeded();
    const paymentView=await snapshot(page);
    console.log(paymentView.diff);
    views.push(paymentView.tree);
  }
  const observed=new Date().toISOString();
  const value={schema_version:'agoda-aside-capture-v1',kind:'detail',account_key:'aside-u0',
    booking_number:booking,observed_at:observed,list_status:status,list_page:null,
    entry_proof:{booking_number:booking,button_name:'예약 확인/변경하기 '+booking,snapshot_text:list.tree},
    url:page.url(),snapshot_text:views.join('\n'),view_count:views.length};
  const filename='./artifacts/details/'+booking+'-'+Date.now()+'.json';
  await fs.writeFile(filename+'.tmp',JSON.stringify(value));
  await fs.rename(filename+'.tmp',filename);
  return {booking_number:booking,filename,observed_at:observed};
};
return {session_directory:pwd};
})()'''


def collect_jobs(manifest, priorities):
    """검증되지 않은 목록이나 임의 예약 ID로 상세에 들어가지 않는다."""
    if manifest.get('status') != 'PASS' or manifest.get('account_key') != 'aside-u0':
        raise ValueError('VERIFIED_LIST_MANIFEST_REQUIRED')
    known = {}
    for page in manifest['pages']:
        if page.get('list_status') not in ('upcoming', 'completed', 'cancelled'):
            raise ValueError('INVALID_LIST_STATUS')
        for booking in page['booking_numbers']:
            known.setdefault(booking, set()).add(page['list_status'])
    jobs, unavailable = [], []
    for item in priorities['bookings']:
        booking = str(item['booking_number'])
        if not re.fullmatch(r'\d{6,20}', booking):
            raise ValueError('INVALID_BOOKING')
        statuses = known.get(booking, set())
        if len(statuses) == 1:
            jobs.append((booking, next(iter(statuses))))
        else:
            unavailable.append({'booking_number': booking, 'reason': 'not_unique_in_verified_lists'})
    return list(dict.fromkeys(jobs)), unavailable


class AsideSession:
    def __init__(self, executable, log_path):
        self.log = log_path.open('a', encoding='utf-8')
        self.process = subprocess.Popen([executable, 'repl'], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
            errors='replace', bufsize=1, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.lines = queue.Queue()
        def read():
            for line in self.process.stdout:
                self.log.write(line)
                self.log.flush()
                self.lines.put(line)
            self.lines.put(None)
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()

    def run(self, expression, timeout=130):
        marker = 'ASIDE_CAPTURE_' + uuid.uuid4().hex + ':'
        # 대화형 입력 한 줄에 전달하되 문자열 내부의 이스케이프는 그대로 둔다.
        expression = expression.replace('\r', '').replace('\n', ' ')
        command = ('await (async()=>{try{const result=await(' + expression + ');console.log('
                   + json.dumps(marker) + '+JSON.stringify({ok:true,result}));}catch(e){console.log('
                   + json.dumps(marker) + '+JSON.stringify({ok:false,error:String(e.message||e)}));}})();')
        self.process.stdin.write(command + '\n')
        self.process.stdin.flush()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self.lines.get(timeout=1)
            except queue.Empty:
                continue
            if line is None:
                raise RuntimeError('ASIDE_PROCESS_EXITED')
            # The REPL echo contains the marker's code, but only a real result has JSON immediately after it.
            start = line.find(marker + '{')
            if start >= 0:
                result = json.JSONDecoder().raw_decode(line[start + len(marker):])[0]
                if not result['ok']:
                    raise RuntimeError(result['error'])
                return result.get('result')
        raise RuntimeError('ASIDE_STEP_TIMEOUT')

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.write('exit\n')
                self.process.stdin.flush()
            except OSError:
                pass
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=10)
        self.reader.join(timeout=2)
        self.log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--priorities', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    root = args.output_root.resolve()
    archive = Path(__file__).resolve().parents[1] / '.local-archive'
    if archive.resolve() not in root.parents:
        parser.error('수집 폴더는 저장소의 .local-archive 아래여야 합니다')
    root.mkdir(parents=True, exist_ok=True)
    (root / 'details').mkdir(exist_ok=True)
    executable = shutil.which('aside')
    if not executable:
        parser.error('Aside CLI가 없습니다')
    jobs, unavailable = collect_jobs(json.loads(args.manifest.read_text(encoding='utf-8')),
                                    json.loads(args.priorities.read_text(encoding='utf-8')))
    done = {json.loads(p.read_text(encoding='utf-8'))['booking_number']
            for p in (root / 'details').glob('*.json')}
    remaining = [(b, s) for b, s in jobs if b not in done]
    selected = remaining[:args.limit] if args.limit else remaining
    report = {'status': 'RUNNING', 'done': sorted(done), 'failed': unavailable,
              'pending': [b for b, _ in remaining]}
    def checkpoint():
        report['updated_at'] = datetime.now(timezone.utc).isoformat()
        temporary = root / 'collection-checkpoint.json.tmp'
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(root / 'collection-checkpoint.json')
    checkpoint()
    session = AsideSession(executable, root / 'aside-transcript.log')
    try:
        started = session.run(PRELUDE)
        for booking, status in selected:
            for attempt in range(3):
                try:
                    result = session.run('captureBooking(' + json.dumps(booking) + ',' + json.dumps(status) + ')')
                    source = Path(started['session_directory']) / result['filename']
                    # Only the exact file returned by the browser capture is copied.
                    shutil.copy2(source, root / 'details' / source.name)
                    report['done'].append(booking)
                    break
                except (RuntimeError, OSError) as exc:
                    if 'AUTH_REQUIRED' in str(exc) or 'TIMEOUT' in str(exc) or 'PROCESS_EXITED' in str(exc):
                        report['status'] = 'BLOCKED'
                        report['blocked_reason'] = str(exc)
                        checkpoint()
                        return 1
                    if attempt == 2:
                        report['failed'].append({'booking_number': booking, 'reason': str(exc)})
            report['pending'].remove(booking)
            checkpoint()
            print(json.dumps({'done': len(report['done']), 'failed': len(report['failed']),
                              'pending': len(report['pending'])}), flush=True)
        report['status'] = 'PARTIAL' if report['failed'] or report['pending'] else 'COMPLETE'
        checkpoint()
        return 0
    finally:
        session.close()


if __name__ == '__main__':
    raise SystemExit(main())
