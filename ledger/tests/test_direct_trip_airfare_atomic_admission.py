import copy,csv,hashlib,inspect,io,os,tempfile,threading,unittest
from pathlib import Path
from unittest import mock

from ledger.domain import direct_trip_airfare_atomic_admission as r57
from ledger.domain import direct_receipt_airfare_evidence as r43

ROOT=Path('/tmp/cost-r43-evidence.tdApsq')
PYTHON=Path('/tmp/cost-r43-pdf-venv/bin/python')

class TripAirfareAtomicAdmissionTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  if not ROOT.exists():raise unittest.SkipTest('restricted R43 inputs unavailable')
  cls.args=(ROOT,ROOT/'provenance.v2.json',ROOT/'provenance.key',PYTHON)
  cls.manifest,cls.files=r57._build(*cls.args)

 def test_actual_report_and_privacy(self):
  m=self.manifest
  self.assertEqual((m['full_classification_delta'],m['accepted_union'],m['global_residual']),(2,1538,3790))
  self.assertEqual((m['selected_event_set_sha256'],m['post_admission_accepted_set_sha256'],m['post_admission_residual_set_sha256']),(r57.MEMBER_SET_SHA256,r57.POST_ACCEPTED_SHA256,r57.POST_RESIDUAL_SHA256))
  self.assertEqual((m['bijection_asserted'],m['individual_relation_count'],m['receipt_permutation_count'],m['korean_vat_document_count'],m['card4_asserted']),(False,0,2,0,False))
  rows=list(csv.DictReader(io.StringIO(self.files['proposals.csv'].decode())))
  self.assertEqual((len(rows),{x['atomic_member_count'] for x in rows},{x['vat_tag'] for x in rows},{x['bijection_asserted'] for x in rows}),(2,{'2'},{'불공제_해외'},{'false'}))
  r57._privacy(self.files)

 def test_manual_each_semantic_and_item_independent_collision(self):
  raw=r57.MANUAL.read_bytes();rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))));fields=rows[0].keys()
  def encoded(rs):
   s=io.StringIO();w=csv.DictWriter(s,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(rs);return s.getvalue().encode()
  changes=[lambda x:x.update(tab='wrong'),lambda x:x.update(item='wrong'),lambda x:x.update(desc='wrong'),lambda x:x.update(card='하나'),lambda x:x.update(date='26.03.25'),lambda x:x.update(amount='208401'),lambda x:x.update(book='locator')]
  for change in changes:
   bad=copy.deepcopy(rows);change(next(x for x in bad if x['card']=='국민' and x['amount']=='208400.0'));data=encoded(bad)
   with tempfile.TemporaryDirectory() as td:
    p=Path(td)/'m.csv';p.write_bytes(data)
    with mock.patch.object(r57,'MANUAL',p),mock.patch.object(r57,'MANUAL_SHA256',hashlib.sha256(data).hexdigest()),self.assertRaises(ValueError):r57._read_manual(p)
  bad=copy.deepcopy(rows);next(x for x in bad if x['card']!='국민').update(card='국민',amount='208400',item='unrelated');data=encoded(bad)
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'m.csv';p.write_bytes(data)
   with mock.patch.object(r57,'MANUAL',p),mock.patch.object(r57,'MANUAL_SHA256',hashlib.sha256(data).hexdigest()),self.assertRaisesRegex(ValueError,'global_collision'):r57._read_manual(p)
  bad=copy.deepcopy(rows)
  for x in bad:
   if x['card']=='국민' and x['amount']=='208400.0':x['date']='26.03.25'
  data=encoded(bad)
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'m.csv';p.write_bytes(data)
   with mock.patch.object(r57,'MANUAL',p),mock.patch.object(r57,'MANUAL_SHA256',hashlib.sha256(data).hexdigest()),self.assertRaises(ValueError):r57._read_manual(p)

 def test_manual_symlink_hardlink_and_path_swap(self):
  with tempfile.TemporaryDirectory() as td:
   real=Path(td)/'real';real.write_bytes(r57.MANUAL.read_bytes());link=Path(td)/'link';link.symlink_to(real)
   with mock.patch.object(r57,'MANUAL',link),self.assertRaisesRegex(ValueError,'manual_file_invalid'):r57._read_manual(link)
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'m';p.write_bytes(r57.MANUAL.read_bytes());os.link(p,Path(td)/'h')
   with mock.patch.object(r57,'MANUAL',p),self.assertRaisesRegex(ValueError,'manual_file_invalid'):r57._read_manual(p)
  real_open=os.open;calls=0
  def swapped(path,*a,**kw):
   nonlocal calls
   fd=real_open(path,*a,**kw);calls+=1
   if calls==2:return real_open('/dev/null',os.O_RDONLY)
   return fd
  with mock.patch.object(r57.os,'open',side_effect=swapped),self.assertRaisesRegex(ValueError,'identity_changed'):r57._read_manual()

 def test_current_predicates_member_exchange_duplicate_payload_and_signature(self):
  selected={'a','b'}
  base={'source_system':'KBD','occurred_on':'2026-03-24','signed_amount_krw':208400,'currency':'KRW','transaction_type':'purchase','event_role':'single','merchant':'트립닷컴'}
  rows=[{'direct_event_key':k,**base} for k in selected];payloads={k:{'merchant':'트립닷컴'} for k in selected}
  r57._validate_current(rows,payloads,selected)
  with self.assertRaisesRegex(ValueError,'physical_duplicate'):r57._validate_current(rows+[dict(rows[0])],payloads,selected)
  exchanged=copy.deepcopy(rows);exchanged[0]['direct_event_key']='outsider'
  with self.assertRaisesRegex(ValueError,'member_exchange'):r57._validate_current(exchanged,payloads,selected)
  for field,value in [('occurred_on','2026-03-25'),('signed_amount_krw',208401),('currency','USD'),('transaction_type','cancellation'),('event_role','refund')]:
   bad=copy.deepcopy(rows);bad[0][field]=value
   with self.assertRaises(ValueError):r57._validate_current(bad,payloads,selected)
  with self.assertRaisesRegex(ValueError,'payload_missing'):r57._validate_current(rows,{'a':payloads['a']},selected)

 def test_receipt_order_permutation_duplicate_ref_supplier_token_and_korean_vat(self):
  expected=r57._validate_receipts(ROOT)
  cfg=r43.GROUPS[r57.GID]
  with mock.patch.dict(cfg,{'aliases':tuple(reversed(cfg['aliases']))}):self.assertEqual(r57._validate_receipts(ROOT),expected)
  original_parse=r43._parse
  def duplicate(alias,text,cfg):
   _ref,*rest=original_parse(alias,text,cfg);return '1'*16,*rest
  with mock.patch.object(r43,'_parse',side_effect=duplicate),self.assertRaisesRegex(ValueError,'receipt_fact'):r57._validate_receipts(ROOT)
  original=r43._read_private
  with mock.patch.object(r43,'_read_private',side_effect=lambda d,n:original(d,n).replace(b'Kookmin Card',b'Other Card') if n=='trip_a.txt' else original(d,n)),self.assertRaises(ValueError):r57._validate_receipts(ROOT)
  with mock.patch.object(r43,'_read_private',side_effect=lambda d,n:original(d,n)+b'\nKorean VAT' if n=='trip_a.txt' else original(d,n)),self.assertRaisesRegex(ValueError,'korean_vat'):r57._validate_receipts(ROOT)

 def test_post_hashes_are_enforced(self):
  with mock.patch.object(r57,'POST_RESIDUAL_SHA256','f'*64),self.assertRaisesRegex(ValueError,'post_state'):r57._build(*self.args)

 def test_r43_member_and_document_commitments_are_enforced(self):
  row={'group_id':r57.GID,'member_set_sha256':r57.MEMBER_SET_SHA256,'document_set_sha256':r57.DOCUMENT_SET_SHA256,'member_count':'2','document_count':'2'}
  fake={'groups.csv':r57._csv(tuple(row),[row])}
  for name in ('MEMBER_SET_SHA256','DOCUMENT_SET_SHA256'):
   with mock.patch.object(r57.r43,'_build',return_value=({},fake)),mock.patch.object(r57,name,'f'*64),self.assertRaisesRegex(ValueError,'member_or_document_set_mismatch'):
    r57._live(*self.args,Path('ledger').resolve())

 def test_no_replace_publish_verify_and_post_publish_value_error(self):
  with tempfile.TemporaryDirectory() as td:
   out=Path(td)/'exists';out.mkdir()
   with mock.patch.object(r57,'_build',return_value=(self.manifest,self.files)),self.assertRaises(FileExistsError):r57.build_trip_airfare_atomic_admission(*self.args,output=out)
  with tempfile.TemporaryDirectory() as td:
   out=Path(td)/'ok'
   with mock.patch.object(r57,'_build',return_value=(self.manifest,self.files)):r57.build_trip_airfare_atomic_admission(*self.args,output=out)
   with mock.patch.object(r57,'_build',return_value=(self.manifest,self.files)):r57.verify_trip_airfare_atomic_admission(out,*self.args)
   (out/'groups.csv').write_bytes(b'tampered');os.chmod(out/'groups.csv',0o600)
   with mock.patch.object(r57,'_build',return_value=(self.manifest,self.files)),self.assertRaises(ValueError):r57.verify_trip_airfare_atomic_admission(out,*self.args)
  with tempfile.TemporaryDirectory() as td:
   out=Path(td)/'durable';real_fsync=os.fsync;calls=0
   def durability_fail(fd):
    nonlocal calls
    calls+=1
    if calls==len(r57.FILES)+2:raise OSError('parent fsync')
    return real_fsync(fd)
   with mock.patch.object(r57,'_build',return_value=(self.manifest,self.files)),mock.patch.object(r57.os,'fsync',side_effect=durability_fail),self.assertRaises(r57.PublicationDurabilityError) as got:r57.build_trip_airfare_atomic_admission(*self.args,output=out)
   with mock.patch.object(r57,'_build',return_value=(self.manifest,self.files)):self.assertTrue(r57.reconcile_publication(got.exception,*self.args)['durable'])
  with tempfile.TemporaryDirectory() as td:
   out=Path(td)/'bad';real=r57._capture_dirfd;calls=0
   def fail(fd):
    nonlocal calls
    calls+=1
    if calls==2:raise ValueError('post publish')
    return real(fd)
   with mock.patch.object(r57,'_build',return_value=(self.manifest,self.files)),mock.patch.object(r57,'_capture_dirfd',side_effect=fail),self.assertRaises(r57.PublicationIntegrityError):r57.build_trip_airfare_atomic_admission(*self.args,output=out)

 def test_production_has_no_global_mock_and_r55_isolation(self):
  self.assertNotIn('patch.object',inspect.getsource(r57))
  sentinel=object();observed=[]
  def r55_side():
   with mock.patch.object(r57.r55,'_build',return_value=sentinel):
    observed.append(r57._build is not sentinel)
  t=threading.Thread(target=r55_side);t.start();t.join()
  self.assertEqual(observed,[True])

if __name__=='__main__':unittest.main()
