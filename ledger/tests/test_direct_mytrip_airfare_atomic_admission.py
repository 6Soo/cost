import csv,io,os,tempfile,unittest
from pathlib import Path
from unittest import mock
from ledger.domain import direct_mytrip_airfare_atomic_admission as r59

ROOT=Path('/tmp/cost-r43-evidence.tdApsq');PY=Path('/tmp/cost-r43-pdf-venv/bin/python')
class R59Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  if not ROOT.exists():raise unittest.SkipTest('private R43 absent')
  cls.args=(ROOT,ROOT/'provenance.v2.json',ROOT/'provenance.key',PY);cls.m,cls.f=r59._build(*cls.args)
 def test_actual_four_and_authority_boundary(self):
  m=self.m;self.assertEqual((m['full_classification_delta'],m['accepted_union'],m['global_residual']),(4,1542,3786));self.assertEqual(m['selected_event_set_sha256'],r59.SELECTED_SET_SHA256)
  self.assertEqual((m['bijection_asserted'],m['individual_relation_count'],m['korean_tax_invoice_count'],m['authority_status'],m['posting_status']),(False,0,0,'unattested','blocked'))
  p=list(csv.DictReader(io.StringIO(self.f['proposals.csv'].decode())));self.assertEqual((len(p),{x['account'] for x in p},{x['cost_type'] for x in p},{x['vat_tag'] for x in p},{x['atomic_member_count'] for x in p}),(4,{'항공료'},{'여행원가'},{'불공제_국내'},{'2'}));r59._privacy(self.f)
 def test_r43_group_commitments_fail_closed(self):
  fields=('group_id','member_set_sha256','document_set_sha256','member_count','document_count');rows=[]
  for gid,(member,doc,*_) in r59.GROUPS.items():rows.append({'group_id':gid,'member_set_sha256':member,'document_set_sha256':doc,'member_count':2,'document_count':2})
  fake={'groups.csv':r59._csv(fields,rows),'proposals.csv':b''};docs=[{'alias':a,'transport_auth':'forwarded_outer_auth_observed_unverified'} for gid in r59.GROUPS for a in r59.r43.GROUPS[gid]['aliases']]
  for gid in r59.GROUPS:
   for index in (0,1):
    bad=dict(r59.GROUPS);v=list(bad[gid]);v[index]='f'*64;bad[gid]=tuple(v)
    with mock.patch.object(r59.r43.r43auth,'verify_authenticated_inputs',return_value={'provenance':{'documents':docs}}),mock.patch.object(r59.r43,'_build',return_value=({'a0_policy_sha256':r59.A0_POLICY_SHA256},fake)),mock.patch.object(r59,'GROUPS',bad),self.assertRaisesRegex(ValueError,'commitment'):r59._live(*self.args,Path('ledger').resolve())
 def test_receipt_order_and_tax_invoice_reject(self):
  self.assertEqual(set(r59._receipts(ROOT)),set(r59.GROUPS));real=r59.r43._read_private
  with mock.patch.object(r59.r43,'_read_private',side_effect=lambda d,n:real(d,n)+b'\nTax Invoice' if n=='mytrip_a.txt' else real(d,n)),self.assertRaisesRegex(ValueError,'tax_invoice'):r59._receipts(ROOT)
  parse=r59.r43._parse
  with mock.patch.object(r59.r43,'_parse',side_effect=lambda a,t,c:(lambda z:(z[0],z[1],'2026-03-15',z[3]))(parse(a,t,c)) if a=='mytrip_a' else parse(a,t,c)),self.assertRaisesRegex(ValueError,'receipt_fact'):r59._receipts(ROOT)
 def test_transport_authority_tamper_rejects_before_live(self):
  docs=[{'alias':a,'transport_auth':'forwarded_outer_auth_observed_unverified'} for gid in r59.GROUPS for a in r59.r43.GROUPS[gid]['aliases']];docs[0]['transport_auth']='provider_outer_dkim_aligned'
  with mock.patch.object(r59.r43.r43auth,'verify_authenticated_inputs',return_value={'provenance':{'documents':docs}}),self.assertRaisesRegex(ValueError,'transport_authority'):r59._live(*self.args,Path('ledger').resolve())
 def test_manual_global_collision(self):
  rows=list(csv.DictReader(io.StringIO(r59.MANUAL.read_bytes().decode('utf-8-sig'))));target=next(x for x in rows if x['tab']=='0712_몽골' and x['amount']=='793669.0');target['date']='26.03.15';s=io.StringIO();w=csv.DictWriter(s,fieldnames=rows[0],lineterminator='\n');w.writeheader();w.writerows(rows);data=s.getvalue().encode()
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'m';p.write_bytes(data)
   with mock.patch.object(r59,'MANUAL',p),mock.patch.object(r59,'MANUAL_SHA256',r59._sha(data)),self.assertRaisesRegex(ValueError,'manual_global'):r59._read_manual(p)
 def test_current_date_member_exchange_and_outside_collision(self):
  universe={};payload={};by={};selected=set()
  for gi,(gid,v) in enumerate(r59.GROUPS.items()):
   for j in range(2):
    k=f'k{gi}{j}';content=f'c{gi}{j}';selected.add(k);universe[k]={'direct_event_key':k,'current_event_sha256':content,'source_system':'KBD','occurred_on':'20'+v[3].replace('.','-'),'signed_amount_krw':v[4],'currency':'KRW','transaction_type':'purchase','event_role':'single','merchant':'고투게이트'};payload[k]={'merchant':'고투게이트'};by[content]={'group_id':gid}
  pin=r59._setsha(selected)
  with mock.patch.object(r59,'SELECTED_SET_SHA256',pin):r59._validate_current_census(universe,selected,payload,by)
  bad={k:dict(v) for k,v in universe.items()};bad[next(iter(selected))]['occurred_on']='2026-01-01'
  with mock.patch.object(r59,'SELECTED_SET_SHA256',pin),self.assertRaisesRegex(ValueError,'current_fact'):r59._validate_current_census(bad,selected,payload,by)
  with mock.patch.object(r59,'SELECTED_SET_SHA256',pin),self.assertRaisesRegex(ValueError,'member_exchange'):r59._validate_current_census(universe,(selected-{'k00'})|{'outside'},payload,by)
  bad={k:dict(v) for k,v in universe.items()};bad['outside']={**next(iter(universe.values())),'direct_event_key':'outside'}
  with mock.patch.object(r59,'SELECTED_SET_SHA256',pin),self.assertRaisesRegex(ValueError,'global_collision'):r59._validate_current_census(bad,selected,payload,by)
 def test_publish_verify_durability_reconcile_and_post_publish_error(self):
  with tempfile.TemporaryDirectory() as td:
   out=Path(td)/'p'
   with mock.patch.object(r59,'_build',return_value=(self.m,self.f)):r59.build_mytrip_airfare_atomic_admission(output=out)
   with mock.patch.object(r59,'_build',return_value=(self.m,self.f)):r59.verify_mytrip_airfare_atomic_admission(out)
   (out/'groups.csv').write_bytes(b'tamper');os.chmod(out/'groups.csv',0o600)
   with mock.patch.object(r59,'_build',return_value=(self.m,self.f)),self.assertRaises(ValueError):r59.verify_mytrip_airfare_atomic_admission(out)
  with tempfile.TemporaryDirectory() as td:
   out=Path(td)/'d';real=os.fsync;calls=0
   def fail(fd):
    nonlocal calls;calls+=1
    if calls==len(r59.FILES)+2:raise OSError('parent')
    return real(fd)
   with mock.patch.object(r59,'_build',return_value=(self.m,self.f)),mock.patch.object(r59.os,'fsync',side_effect=fail),self.assertRaises(r59.PublicationDurabilityError) as got:r59.build_mytrip_airfare_atomic_admission(output=out)
   with mock.patch.object(r59,'_build',return_value=(self.m,self.f)):self.assertTrue(r59.reconcile_publication(got.exception)['durable'])
   old=Path(td)/'old';out.rename(old);out.mkdir();os.chmod(out,0o700)
   for n,d in self.f.items():(out/n).write_bytes(d);os.chmod(out/n,0o600)
   with mock.patch.object(r59,'_build',return_value=(self.m,self.f)),self.assertRaises(ValueError):r59.reconcile_publication(got.exception)
  with tempfile.TemporaryDirectory() as td:
   out=Path(td)/'x';real=r59.r57._capture_dirfd;calls=0
   def capture(fd):
    nonlocal calls;calls+=1
    if calls==2:raise ValueError('post')
    return real(fd)
   with mock.patch.object(r59,'_build',return_value=(self.m,self.f)),mock.patch.object(r59.r57,'_capture_dirfd',side_effect=capture),self.assertRaises(r59.PublicationIntegrityError):r59.build_mytrip_airfare_atomic_admission(output=out)
 def test_partial_and_zero_write(self):
  real=os.write
  with tempfile.TemporaryDirectory() as td:
   out=Path(td)/'partial'
   def partial(fd,data):return real(fd,data[:max(1,len(data)//2)])
   with mock.patch.object(r59,'_build',return_value=(self.m,self.f)),mock.patch.object(r59.os,'write',side_effect=partial):r59.build_mytrip_airfare_atomic_admission(output=out)
   self.assertEqual(r59.r57._capture(out),self.f)
  with tempfile.TemporaryDirectory() as td:
   with mock.patch.object(r59,'_build',return_value=(self.m,self.f)),mock.patch.object(r59.os,'write',return_value=0),self.assertRaises(OSError):r59.build_mytrip_airfare_atomic_admission(output=Path(td)/'zero')
 def test_pre_rename_parent_path_swap_rejected(self):
  with tempfile.TemporaryDirectory() as td:
   base=Path(td);parent=base/'parent';parent.mkdir();old=base/'old';out=parent/'pkg';real=os.stat;calls=0
   def swap(path,*args,**kwargs):
    nonlocal calls
    if Path(path)==parent:
     calls+=1
     if calls==2:parent.rename(old);parent.mkdir()
    return real(path,*args,**kwargs)
   with mock.patch.object(r59,'_build',return_value=(self.m,self.f)),mock.patch.object(r59.os,'stat',side_effect=swap),self.assertRaisesRegex(ValueError,'parent_identity_changed'):r59.build_mytrip_airfare_atomic_admission(output=out)
   self.assertFalse((parent/'pkg').exists());self.assertFalse((old/'pkg').exists())
   self.assertEqual(list(parent.glob('.r59-stage-*')),[]);self.assertEqual(list(old.glob('.r59-stage-*')),[])
if __name__=='__main__':unittest.main()
