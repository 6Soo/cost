import hashlib,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ledger.domain import direct_ota_lifecycle_support as r41
class OtaLifecycleSupportTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.manifest,cls.files=r41._build(Path("ledger"))
 def test_live_census_and_zero_authority(self):
  self.assertEqual(self.manifest["counts"],r41.EXPECTED);self.assertEqual((self.manifest["full_classification_delta"],self.manifest["vat_proposals"],self.manifest["confirmed_count"],self.manifest["gate5_credit"],self.manifest["applied"]),(0,0,0,0,False))
 def test_privacy_schema_and_empty_new_proposals(self):
  self.assertEqual(self.manifest["files"]["new_proposals.csv"]["rows"],0)
  forbidden={"booking_reference","pnr","subject","amount","card4","guest","passenger","url","pin","access_token"}
  exported={x.lower() for fields in (r41.COMP_FIELDS,r41.REJ_FIELDS,r41.LINK_FIELDS,r41.NEW_FIELDS) for x in fields}
  self.assertFalse(exported&forbidden)
  package=b"".join(self.files.values());mail=json.loads(Path("ledger/data/ota_mail_index.json").read_text(encoding="utf-8"))["records"]
  identities={x for row in mail for x in row["bookingRefs"]+row["pnrs"] if len(x)>=6}
  for value in identities:
   self.assertNotIn(value.encode(),package);self.assertNotIn(hashlib.sha256(value.encode()).hexdigest().encode(),package)
 def test_amount_only_is_rejection_never_link(self):
  self.assertEqual(self.manifest["files"]["rejections.csv"]["rows"],162);self.assertEqual(self.manifest["reason_census"]["repository_fact_current_identity_unresolved"],1);self.assertEqual(self.manifest["counts"]["amount_only_singletons_rejected"],61);self.assertEqual(self.manifest["counts"]["net_new_events"],0)
 def test_external_publish_verify_and_no_replace(self):
  with tempfile.TemporaryDirectory() as d,patch.object(r41,"_build",return_value=(self.manifest,self.files)):
   out=Path(d)/"pkg";r41.build_ota_lifecycle_support(out);self.assertEqual(r41.verify_ota_lifecycle_support(out)["net_new_events"],0)
   with self.assertRaises(FileExistsError):r41.build_ota_lifecycle_support(out)
 def test_set_hash_is_permutation_invariant(self):
  self.assertEqual(r41._setsha(["b","a","c"]),r41._setsha(["c","b","a"]))
 def test_namespace_resolution_requires_unique_full_node(self):
  nodes={("ref","123"):{("trip","ref","123"),("agoda","ref","123")},("pnr","123"):{("agoda","pnr","123")},("ref","456"):{("trip","ref","456")}}
  self.assertIsNone(r41._resolve_fact_node("123","ref",None,nodes));self.assertEqual(r41._resolve_fact_node("123","pnr","agoda",nodes),("agoda","pnr","123"));self.assertIsNone(r41._resolve_fact_node("123","ref","booking",nodes));self.assertEqual(r41._resolve_fact_node("456","ref","trip",nodes),("trip","ref","456"))
 def test_strict_message_rejects_bad_time_dates_identity_and_duplicates(self):
  base={"messageId":"a"*16,"subject":"x","sentAt":"Fri, 01 Aug 2025 00:00:00 +0000","provider":"trip","bookingRefs":["1"*16],"pnrs":["ABC123"],"travelDates":["0229"],"amounts":[1],"messageHash":"b"*64,"redactionVersion":"ota-allowlist-v1"}
  for field,value in (("sentAt","2025-99-99T99:99:99Z"),("sentAt","2025-01-01T00:00:00"),("travelDates",["0231"]),("travelDates",["1939"]),("bookingRefs",["１２３４５６７８９０１２３４５６"]),("pnrs",["ＡＢＣ１２３"]),("bookingRefs",["1"*16,"1"*16])):
   row=dict(base);row[field]=value
   with self.assertRaises(ValueError):r41._validate_message(row)
  live={row["messageId"]:row for row in json.loads(Path("ledger/data/ota_mail_index.json").read_text(encoding="utf-8"))["records"]}
  for message_id,_,_,_ in r41.LEGACY_UTC_ROWS:r41._validate_message(live[message_id])
  forged=dict(base,sentAt="2099-01-01T00:00:00.12345678")
  with self.assertRaises(ValueError):r41._validate_message(forged)
  legacy=dict(live[next(iter(r41.LEGACY_UTC_ROWS))[0]]);legacy["provider"]="agoda"
  with self.assertRaises(ValueError):r41._validate_message(legacy)
 def test_nested_fact_and_fake_vat_rejected(self):
  booking={"1"*16:{"label":"x","period":"숙박_0101_0102"}};periods={"1"*10:{"category":"숙박","period":"0101_0102","source":"x"}};ota={"TRIP-0001":{"category":"숙박","period":"0101_0102","vat_tag":"공제"}}
  with self.assertRaises(ValueError):r41._validate_repository_facts(booking,periods,ota)
  evil={"1"*16:{"label":"x","period":"EVIL_0101_0102"}}
  with self.assertRaises(ValueError):r41._validate_repository_facts(evil,periods,{})
  fullwidth={"TRIP-0001":{"category":"숙박","period":"0101_0102","booking_id":"１２３４５６７８９０"}}
  with self.assertRaises(ValueError):r41._validate_repository_facts(booking,periods,fullwidth)
  attacks=[{"booking_id":"12345678901"},{"linked_uid":"bad nested identity!"},{"linked_uid":"ＴＲＩＰ－０００１"},{"reference_code":"ABC123"}]
  for mutation in attacks:
   fact={"category":"숙박","period":"0101_0102",**mutation}
   with self.assertRaises(ValueError):r41._validate_repository_facts(booking,periods,{"TRIP-0001":fact},messages={},source_uids={"TRIP-0001"})
  missing_message={"TRIP-0001":{"category":"숙박","period":"0101_0102","source_message_id":"aaaaaaaaaaaaaaaa"}}
  with self.assertRaises(ValueError):r41._validate_repository_facts(booking,periods,missing_message,messages={},source_uids={"TRIP-0001"})
  missing_uid={"TRIP-0001":{"category":"숙박","period":"0101_0102","linked_uid":"TRIP-9999"}}
  with self.assertRaises(ValueError):r41._validate_repository_facts(booking,periods,missing_uid,messages={},source_uids={"TRIP-0001"})
  canonical=json.loads(Path("ledger/data/ota_event_links_verified.json").read_text(encoding="utf-8"))["TRIP-0100"]
  relocated={"TRIP-0001":canonical}
  with self.assertRaises(ValueError):r41._validate_repository_facts(booking,periods,relocated,messages={},source_uids={"TRIP-0001","TRIP-0100"},allowed_orphan_fact_rows=r41.QUARANTINED_ORPHAN_FACT_ROWS)
  changed={"TRIP-0100":{**canonical,"period":"0418_0428"}}
  with self.assertRaises(ValueError):r41._validate_repository_facts(booking,periods,changed,messages={},source_uids={"TRIP-0100"},allowed_orphan_fact_rows=r41.QUARANTINED_ORPHAN_FACT_ROWS)
 def test_fabricated_cardinality_bytes_are_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   out=Path(d)/"pkg";out.mkdir(mode=0o700)
   for name,data in self.files.items():(out/name).write_bytes(data);os.chmod(out/name,0o600)
   data=(out/"existing_links.csv").read_text(encoding="utf-8");(out/"existing_links.csv").write_text(data.replace(",1,",",99,",1));os.chmod(out/"existing_links.csv",0o600)
   with patch.object(r41,"_build",return_value=(self.manifest,self.files)),self.assertRaisesRegex(ValueError,"semantics_mismatch"):r41.verify_ota_lifecycle_support(out)
 def test_parent_fsync_failure_is_reconcilable_published_state(self):
  with tempfile.TemporaryDirectory() as d,patch.object(r41,"_build",return_value=(self.manifest,self.files)):
   out=Path(d)/"pkg";real=os.fsync;calls=0
   def fail_parent(fd):
    nonlocal calls;calls+=1
    if calls==7:raise OSError("parent")
    return real(fd)
   with patch.object(r41.os,"fsync",side_effect=fail_parent),self.assertRaises(r41.PublicationDurabilityError) as caught:r41.build_ota_lifecycle_support(out)
   self.assertTrue(caught.exception.published);self.assertTrue(out.exists())
   valid={"status":"valid","package_set_sha256":self.manifest["package_set_sha256"],"net_new_events":0}
   with patch.object(r41,"verify_ota_lifecycle_support",return_value=valid):self.assertTrue(r41.reconcile_ota_lifecycle_publication(caught.exception)["durable"])
if __name__=="__main__":unittest.main()
