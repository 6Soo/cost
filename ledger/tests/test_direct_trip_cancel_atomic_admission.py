import copy,csv,hashlib,io,json,os,tempfile,unittest
from pathlib import Path
from unittest import mock

from ledger.domain import direct_trip_cancel_atomic_admission as r55
from ledger.domain import direct_trip_cancel_lifecycle_evidence as r44

ROOT=Path('/tmp/cost-r44-trip-cancel-restricted.S2RPTC')
PYTHON=Path('/tmp/cost-r43-pdf-venv/bin/python')

class TripCancelAtomicAdmissionTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  if not ROOT.exists():raise unittest.SkipTest('restricted R44 inputs unavailable')
  cls.manifest,cls.files=r55._build(ROOT,ROOT/'provenance.v2.3.json',ROOT/'seal.key',PYTHON)

 def test_actual_atomic_post_state_and_privacy(self):
  m=self.manifest;self.assertEqual((m['full_classification_delta'],m['accepted_union'],m['global_residual']),(4,1536,3792))
  self.assertEqual((m['post_admission_accepted_set_sha256'],m['post_admission_residual_set_sha256']),(r55.POST_ACCEPTED_SHA256,r55.POST_RESIDUAL_SHA256))
  rows=list(csv.DictReader(io.StringIO(self.files['proposals.csv'].decode())))
  self.assertEqual((len(rows),{x['atomic_member_count'] for x in rows},{x['bijection_asserted'] for x in rows},{x['individual_relation_count'] for x in rows}),(4,{'4'},{'false'},{'0'}))
  r55._privacy(self.files)

 def test_hidden_same_fact_current_is_rejected(self):
  rows=[{'direct_event_key':k,'source_system':'KBO','signed_amount_krw':893170 if v[0]=='purchase' else -893170,'transaction_type':v[0]} for k,v in r44.EVENTS.items()]
  r55._validate_current_census(rows)
  rows.append({'direct_event_key':'hidden','source_system':'KBO','signed_amount_krw':893170,'transaction_type':'purchase'})
  with self.assertRaisesRegex(ValueError,'current_amount_census'):r55._validate_current_census(rows)
  rows.pop()
  rows.append({'direct_event_key':'hidden-domestic','source_system':'KBD','signed_amount_krw':893170,'transaction_type':'purchase'})
  with self.assertRaisesRegex(ValueError,'current_amount_census'):r55._validate_current_census(rows)

 def test_physical_duplicate_and_same_count_exchange_reject(self):
  rows=[{'direct_event_key':k,'source_system':'KBO','signed_amount_krw':893170 if v[0]=='purchase' else -893170,'transaction_type':v[0]} for k,v in r44.EVENTS.items()]
  with self.assertRaisesRegex(ValueError,'physical_duplicate'):r55._validate_current_census(rows+[dict(rows[0])])
  exchanged=copy.deepcopy(rows);exchanged[0]['direct_event_key']='same-count-outsider'
  with self.assertRaisesRegex(ValueError,'current_amount_census'):r55._validate_current_census(exchanged)

 def test_post_accepted_hash_is_recomputed_not_decorative(self):
  with mock.patch.object(r55,'POST_ACCEPTED_SHA256','f'*64),self.assertRaisesRegex(ValueError,'post_accepted_state'):
   r55._build(ROOT,ROOT/'provenance.v2.3.json',ROOT/'seal.key',PYTHON)

 def test_provider_duplicate_swap_and_forged_capture_reject(self):
  p={'relevant_lifecycle_count':2,'capture_claims':{'authenticated':False},'lifecycles':[
   {'order_hmac_sha256':'a'*64,'receipt_sha256':'b'*64,'message_count':2,'states':['confirmation','refund_complete'],'amount_jpy':92001,'stay_start':'2026-10-06','stay_end':'2026-10-09','rooms':1,'nights':3},
   {'order_hmac_sha256':'c'*64,'receipt_sha256':'d'*64,'message_count':2,'states':['confirmation','refund_complete'],'amount_jpy':92001,'stay_start':'2026-10-06','stay_end':'2026-10-09','rooms':1,'nights':3}]}
  r55._validate_provider(p)
  bad=copy.deepcopy(p);bad['lifecycles'][1]['order_hmac_sha256']='a'*64
  with self.assertRaisesRegex(ValueError,'swap_or_duplicate'):r55._validate_provider(bad)
  bad=copy.deepcopy(p);bad['capture_claims']['authenticated']=True
  with self.assertRaisesRegex(ValueError,'authority_escalation'):r55._validate_provider(bad)

 def test_manual_mutation_collision_and_row_exchange_reject(self):
  original=r55.MANUAL.read_bytes();rows=list(csv.DictReader(io.StringIO(original.decode('utf-8-sig'))))
  fields=rows[0].keys()
  def encode(items):
   s=io.StringIO();w=csv.DictWriter(s,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(items);return s.getvalue().encode('utf-8')
  for label,change in [('role',lambda z:z.update(desc='숙박_1006_1009')),('exchange',lambda z:z.update(row='29'))]:
   changed=copy.deepcopy(rows);target=next(x for x in changed if x['tab']==r55.TRIP_TARGET and x['desc']=='취소');change(target);data=encode(changed)
   with tempfile.TemporaryDirectory() as td:
    p=Path(td)/'manual.csv';p.write_bytes(data)
    with mock.patch.object(r55,'MANUAL',p),mock.patch.object(r55,'MANUAL_SHA256',hashlib.sha256(data).hexdigest()),self.assertRaises(ValueError):r55._read_manual(p)
  changed=copy.deepcopy(rows)
  outsider=next(x for x in changed if x['tab']!=r55.TRIP_TARGET and x['card']!='국민')
  outsider.update(card='국민',amount='893170',item='완전히_다른_항목')
  data=encode(changed)
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'manual.csv';p.write_bytes(data)
   with mock.patch.object(r55,'MANUAL',p),mock.patch.object(r55,'MANUAL_SHA256',hashlib.sha256(data).hexdigest()),self.assertRaisesRegex(ValueError,'manual_hidden_collision'):
    r55._read_manual(p)
  changed=copy.deepcopy(rows);extra=copy.deepcopy(rows[0]);extra.update(tab='unrelated',row='9999',item='OTHER',card='국민',amount='893170.0');changed.append(extra);data=encode(changed)
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'manual.csv';p.write_bytes(data)
   with mock.patch.object(r55,'MANUAL',p),mock.patch.object(r55,'MANUAL_SHA256',hashlib.sha256(data).hexdigest()),self.assertRaises(ValueError):r55._read_manual(p)

 def test_manual_symlink_and_hardlink_reject(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);real=root/'real.csv';real.write_bytes(r55.MANUAL.read_bytes());link=root/'link.csv';link.symlink_to(real)
   with mock.patch.object(r55,'MANUAL',link),self.assertRaisesRegex(ValueError,'manual_file_invalid'):r55._read_manual(link)
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);p=root/'m.csv';p.write_bytes(r55.MANUAL.read_bytes());other=root/'other.csv';os.link(p,other)
   with mock.patch.object(r55,'MANUAL',p),self.assertRaisesRegex(ValueError,'manual_file_invalid'):r55._read_manual(p)

 def test_role_sign_and_atomic_subset_reject(self):
  bindings=[]
  for k,(role,content) in r44.EVENTS.items():bindings.append({'key':k,'transaction_type':role,'amount':893170 if role=='purchase' else -893170,'foreign_signed':92001 if role=='purchase' else -92001})
  r44._validate_atomic_bindings(bindings)
  bad=copy.deepcopy(bindings);bad[0]['amount']*=-1
  with self.assertRaisesRegex(ValueError,'atomic_role_or_total'):r44._validate_atomic_bindings(bad)
  with self.assertRaisesRegex(ValueError,'atomic_member_set'):r44._validate_atomic_bindings(bindings[:-1])

 def test_no_replace_publication(self):
  with tempfile.TemporaryDirectory() as td:
   out=Path(td)/'exists';out.mkdir()
   with mock.patch.object(r55,'_build',return_value=(self.manifest,self.files)),self.assertRaises(FileExistsError):
    r55.build_trip_cancel_atomic_admission(ROOT,ROOT/'provenance.v2.3.json',ROOT/'seal.key',PYTHON,out)

 def test_publication_success_target_swap_and_durability_reconcile(self):
  args=(ROOT,ROOT/'provenance.v2.3.json',ROOT/'seal.key',PYTHON)
  with tempfile.TemporaryDirectory() as td:
   out=Path(td)/'ok'
   with mock.patch.object(r55,'_build',return_value=(self.manifest,self.files)):
    r55.build_trip_cancel_atomic_admission(*args,out)
    self.assertEqual(r55._capture(out),self.files)
  with tempfile.TemporaryDirectory() as td:
   out=Path(td)/'swap';moved=Path(td)/'genuine';real=os.fsync;calls=0
   def seam(fd):
    nonlocal calls;calls+=1
    if calls==len(r55.FILES)+2:
     out.rename(moved);out.mkdir();os.chmod(out,0o700);(out/'sentinel').write_text('x')
    return real(fd)
   with mock.patch.object(r55,'_build',return_value=(self.manifest,self.files)),mock.patch.object(r55.os,'fsync',side_effect=seam),self.assertRaises(r55.PublicationIntegrityError):
    r55.build_trip_cancel_atomic_admission(*args,out)
  with tempfile.TemporaryDirectory() as td:
   out=Path(td)/'durable';real=os.fsync;calls=0
   def fail(fd):
    nonlocal calls;calls+=1
    if calls==len(r55.FILES)+2:raise OSError('parent fsync')
    return real(fd)
   with mock.patch.object(r55,'_build',return_value=(self.manifest,self.files)),mock.patch.object(r55.os,'fsync',side_effect=fail),self.assertRaises(r55.PublicationDurabilityError) as got:
    r55.build_trip_cancel_atomic_admission(*args,out)
   with mock.patch.object(r55,'_build',return_value=(self.manifest,self.files)):
    self.assertTrue(r55.reconcile_publication(got.exception,*args)['durable'])

 def test_post_publish_capture_value_error_is_typed_integrity(self):
  with tempfile.TemporaryDirectory() as td:
   out=Path(td)/'published';calls=0;real=r55._capture_dirfd
   def injected(fd):
    nonlocal calls
    calls+=1
    if calls==2:raise ValueError('injected_post_publish_capture')
    return real(fd)
   args=(ROOT,ROOT/'provenance.v2.3.json',ROOT/'seal.key',PYTHON,out)
   with mock.patch.object(r55,'_build',return_value=(self.manifest,self.files)),mock.patch.object(r55,'_capture_dirfd',side_effect=injected),self.assertRaises(r55.PublicationIntegrityError) as got:
    r55.build_trip_cancel_atomic_admission(*args)
   self.assertTrue(got.exception.published)
   self.assertTrue(out.exists())

 def test_verify_and_reconcile_target_swap_reject(self):
  args=(ROOT,ROOT/'provenance.v2.3.json',ROOT/'seal.key',PYTHON)
  with tempfile.TemporaryDirectory() as td:
   out=Path(td)/'pkg'
   with mock.patch.object(r55,'_build',return_value=(self.manifest,self.files)):r55.build_trip_cancel_atomic_admission(*args,out)
   old=Path(td)/'old';real=r55._capture_dirfd;done=False
   def swap(dfd):
    nonlocal done
    result=real(dfd)
    if not done:
     done=True;out.rename(old);out.mkdir();os.chmod(out,0o700)
     for name,data in self.files.items():p=out/name;p.write_bytes(data);os.chmod(p,0o600)
    return result
   with mock.patch.object(r55,'_build',return_value=(self.manifest,self.files)),mock.patch.object(r55,'_capture_dirfd',side_effect=swap),self.assertRaises(ValueError):
    r55.verify_trip_cancel_atomic_admission(out,*args)

if __name__=='__main__':unittest.main()
