from __future__ import annotations
import csv,hashlib,io,json,os,sqlite3,tempfile,unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from ledger.domain import han_master_candidate as r39
from ledger.domain.direct_projection import (_apply_schema,project_card_payments,candidate_semantic_snapshot,
    build_source_inventory,code_bundle_descriptor,_git_head,_activate_candidate)
from ledger.domain.transition_gates_v2 import input_manifest_sha256
from ledger.domain.transition_gates_v2 import _amount_relation_gate
from ledger.domain.direct_sources import import_cards
from ledger.domain.ledger_db import connect,initialize

class HanMasterCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.db_path=Path(cls.temp.name)/"candidate.db";cls.run_id="fixture-run"
        inventory=build_source_inventory(Path("ledger"));cls.input_sha=input_manifest_sha256(inventory);bundle=code_bundle_descriptor();db=connect(cls.db_path);initialize(db);_apply_schema(db)
        db.execute("INSERT INTO direct_projection_runs(run_id,status,schema_version,input_manifest_sha256,code_commit,code_bundle_sha256) VALUES (?,'building','p07-direct-v3',?,?,?)",(cls.run_id,cls.input_sha,_git_head(),bundle["code_bundle_sha256"]))
        for x in inventory:
            db.execute("INSERT INTO direct_projection_inputs(run_id,source_kind,relative_path,raw_sha256,lf_sha256,byte_count,key_set_sha256,record_count,parser_version) VALUES (?,?,?,?,?,?,?,?,?)",
              (cls.run_id,x["source_kind"],x["relative_path"],x["raw_sha256"],x["lf_sha256"],x["byte_count"],x["key_set_sha256"],x["record_count"],x["parser_version"]))
        import_cards(db,Path("ledger"));project_card_payments(db,cls.run_id);cls.semantic_sha=candidate_semantic_snapshot(db,cls.run_id)
        db.execute("UPDATE direct_projection_runs SET candidate_semantic_sha256=? WHERE run_id=?",(cls.semantic_sha,cls.run_id));db.commit();db.close()
        cls.context={"candidate_db":cls.db_path,"run_id":cls.run_id,"input_manifest_sha256":cls.input_sha,
                     "candidate_semantic_sha256_expected":cls.semantic_sha,
                     "authority_sha256_expected":hashlib.sha256(r39.AUTHORITY_PATH.read_bytes()).hexdigest()}
        cls.manifest,cls.files=r39._build(Path("ledger"),Path("ledger/master_ledger.csv"),**cls.context)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    @staticmethod
    def rows(raw):return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    def write(self,root):
        out=root/"artifact";out.mkdir(mode=0o700)
        for n,b in self.files.items():p=out/n;p.write_bytes(b);p.chmod(0o600)
        return out
    def test_live_exact_counts_equality_privacy_and_state_preservation(self):
        summary=json.loads(self.files["summary.json"]);self.assertEqual(summary["counts"],
          {"master":5328,"non_han_preserved":3140,"han_physical":2097,"han_roles":2188,"migrated":1602,"mismatch":0,"collision":0,"unmapped":0})
        with open("ledger/master_ledger.csv",encoding="utf-8-sig",newline="") as stream:old=list(csv.DictReader(stream))
        new=self.rows(self.files["candidate_master.csv"])
        self.assertEqual([x for x in old if x["카드사"]!="하나"],[x for x in new if x["카드사"]!="하나"])
        self.assertEqual(Counter(tuple(x[k] for k in r39.REVIEW_FIELDS) for x in old if x["카드사"]=="하나"),
                         Counter(tuple(x[k] for k in r39.REVIEW_FIELDS) for x in new if x["카드사"]=="하나"))
        mapping=self.rows(self.files["private_mapping.csv"]);self.assertEqual(len(mapping),2188)
        self.assertEqual(set(mapping[0]),set(r39.MAPPING_FIELDS))
        self.assertTrue(self.manifest["contains_sensitive_values"])
        self.assertEqual(self.manifest["package_classification"],"private_sensitive")
    def test_state_classifier_rejects_mixed_and_accepts_end_states(self):
        changed=[("a","old-a","new-a",None,None,None),("b","old-b","new-b",None,None,None)]
        self.assertEqual(r39._classify_state({"old-a","old-b"},changed),"LEGACY")
        self.assertEqual(r39._classify_state({"new-a","new-b"},changed),"TARGET")
        with self.assertRaisesRegex(ValueError,"mixed_or_unknown"):
            r39._classify_state({"old-a","new-b"},changed)
    def test_target_state_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/"master.csv";target.write_bytes(self.files["candidate_master.csv"])
            manifest,files=r39._build(Path("ledger"),target,**self.context)
        summary=json.loads(files["summary.json"])
        self.assertEqual(summary["input_state"],"TARGET")
        self.assertEqual(summary["counts"]["migrated"],0)
        self.assertEqual(files["candidate_master.csv"],self.files["candidate_master.csv"])
    def test_event_equality_rejects_one_delta_offset_role_and_missing(self):
        base={"HAN:G:7#single":(100,"purchase"),"HAN:G:8#single":(200,"purchase")}
        cases=({**base,"HAN:G:7#single":(101,"purchase")},
               {"HAN:G:7#single":(101,"purchase"),"HAN:G:8#single":(199,"purchase")},
               {"HAN:G:7#single":(100,"cancellation"),"HAN:G:8#single":(200,"purchase")},
               {"HAN:G:7#single":(100,"purchase")})
        for changed in cases:
            with self.assertRaisesRegex(ValueError,"r39_(amount_role_type|identity_role_set)"):r39._compare(base,changed)
    def test_verify_tamper_shape_modes_and_no_replace(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out=self.write(root)
            with patch.object(r39,"_build",return_value=(self.manifest,self.files)):
                self.assertEqual(r39.verify_candidate(out,**self.context)["status"],"valid")
                (out/"summary.json").write_bytes(b"{}\n")
                with self.assertRaisesRegex(ValueError,"package_or_live"):r39.verify_candidate(out,**self.context)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out=self.write(root);real=root/"summary.real";real.write_bytes((out/"summary.json").read_bytes())
            (out/"summary.json").unlink();os.symlink(real,out/"summary.json")
            with self.assertRaisesRegex(ValueError,"regular_file_open_failed"):
                r39.verify_candidate(out,**self.context)
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/"out"
            with patch.object(r39,"_build",return_value=(self.manifest,self.files)),patch.object(r39,"verify_candidate",return_value={"status":"valid"}):
                r39.build_candidate(target,**self.context)
                with self.assertRaises(FileExistsError):r39.build_candidate(target,**self.context)
    def test_post_publish_durability_and_reconcile(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/"out";calls=0
            def fsync(_):
                nonlocal calls;calls+=1
                if calls==2:raise OSError("parent")
            with patch.object(r39,"_build",return_value=(self.manifest,self.files)),patch.object(r39,"verify_candidate",return_value={"status":"valid"}),patch.object(r39,"_fsync",side_effect=fsync),self.assertRaises(r39.PublicationDurabilityError) as caught:
                r39.build_candidate(target,**self.context)
            self.assertTrue(target.exists())
            with patch.object(r39,"verify_candidate",return_value={"status":"valid","package_set_sha256":self.manifest["package_set_sha256"]}),patch.object(r39,"_fsync",return_value=None):
                self.assertTrue(r39.reconcile_publication_durability(caught.exception)["parent_fsync"])
    def test_direct_run_hash_swap_and_tamper_fail_closed(self):
        cases=(({**self.context,"run_id":"other"},"direct_run_context_mismatch"),
               ({**self.context,"input_manifest_sha256":"b"*64},"live_input_manifest_mismatch"),
               ({**self.context,"candidate_semantic_sha256_expected":"c"*64},"direct_run_context_mismatch"))
        for context,error in cases:
            with self.assertRaisesRegex(ValueError,error):
                r39._build(Path("ledger"),Path("ledger/master_ledger.csv"),**context)
        with tempfile.TemporaryDirectory() as d:
            tampered=Path(d)/"candidate.db";tampered.write_bytes(self.db_path.read_bytes())
            db=sqlite3.connect(tampered);db.execute("UPDATE payment_transactions SET amount_krw=amount_krw+1 WHERE id=(SELECT MIN(id) FROM payment_transactions)");db.commit();db.close()
            with self.assertRaisesRegex(ValueError,"direct_semantic_content_mismatch"):
                r39._build(Path("ledger"),Path("ledger/master_ledger.csv"),**{**self.context,"candidate_db":tampered})
    def test_v2_candidate_is_rejected_by_b1_verifier_path(self):
        with tempfile.TemporaryDirectory() as d:
            old=Path(d)/"v2.db";db=sqlite3.connect(old)
            db.execute("CREATE TABLE direct_projection_runs(run_id TEXT PRIMARY KEY,status TEXT,schema_version TEXT,input_manifest_sha256 TEXT,candidate_semantic_sha256 TEXT,code_commit TEXT,code_bundle_sha256 TEXT)")
            db.execute("INSERT INTO direct_projection_runs VALUES (?,?,?,?,?,?,?)",(self.run_id,"building","p07-direct-v2",self.input_sha,self.semantic_sha,_git_head(),code_bundle_descriptor()["code_bundle_sha256"]));db.commit();db.close()
            with self.assertRaisesRegex(ValueError,"direct_schema_invalid"):
                r39._build(Path("ledger"),Path("ledger/master_ledger.csv"),**{**self.context,"candidate_db":old})
    def test_direct_provenance_fields_fail_closed(self):
        cases=(("UPDATE direct_projection_runs SET status='failed'","direct_status_invalid"),
               ("UPDATE direct_projection_runs SET schema_version='old'","direct_schema_invalid"),
               ("UPDATE direct_projection_runs SET code_commit='old'","direct_commit_invalid"),
               ("UPDATE direct_projection_runs SET code_bundle_sha256='old'","direct_bundle_invalid"),
               ("DELETE FROM direct_projection_inputs WHERE rowid=(SELECT MIN(rowid) FROM direct_projection_inputs)","direct_inputs_invalid"),
               ("UPDATE direct_projection_inputs SET parser_version='old' WHERE rowid=(SELECT MIN(rowid) FROM direct_projection_inputs)","direct_inputs_invalid"),
               ("UPDATE direct_projection_inputs SET raw_sha256='bad' WHERE rowid=(SELECT MIN(rowid) FROM direct_projection_inputs)","direct_inputs_invalid"))
        for sql,error in cases:
            with tempfile.TemporaryDirectory() as d:
                changed=Path(d)/"candidate.db";changed.write_bytes(self.db_path.read_bytes());db=sqlite3.connect(changed)
                db.execute(sql);db.commit();db.close()
                with self.assertRaisesRegex(ValueError,error):
                    r39._build(Path("ledger"),Path("ledger/master_ledger.csv"),**{**self.context,"candidate_db":changed})
    def test_authority_cannot_be_self_updated_through_constants(self):
        with patch.object(r39,"APPROVED_CONTRACT_SHA256","0"*64),self.assertRaisesRegex(ValueError,"authority_policy_mismatch"):
            r39._build(Path("ledger"),Path("ledger/master_ledger.csv"),**self.context)
        with tempfile.TemporaryDirectory() as d:
            changed=Path(d)/"authority.json";value=json.loads(r39.AUTHORITY_PATH.read_text(encoding="utf-8"));value["policy"]="attacker"
            changed.write_text(json.dumps(value),encoding="utf-8")
            with patch.object(r39,"AUTHORITY_PATH",changed),self.assertRaisesRegex(ValueError,"authority_sha256_mismatch"):
                r39._build(Path("ledger"),Path("ledger/master_ledger.csv"),**self.context)
    def test_wal_or_shm_sidecars_fail_closed(self):
        for suffix in ("-wal","-shm"):
            sidecar=Path(str(self.db_path)+suffix);sidecar.write_bytes(b"x")
            try:
                with self.assertRaisesRegex(ValueError,"direct_db_sidecar_present"):
                    r39._build(Path("ledger"),Path("ledger/master_ledger.csv"),**self.context)
            finally:sidecar.unlink()
        with tempfile.TemporaryDirectory() as d:
            changed=Path(d)/"candidate.db";changed.write_bytes(self.db_path.read_bytes());db=sqlite3.connect(changed)
            self.assertEqual(db.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower(),"wal")
            db.execute("UPDATE direct_projection_runs SET status='failed'")
            db.execute("UPDATE payment_transactions SET amount_krw=amount_krw+1 WHERE id=(SELECT MIN(id) FROM payment_transactions)");db.commit()
            with self.assertRaisesRegex(ValueError,"direct_db_sidecar_present"):
                r39._build(Path("ledger"),Path("ledger/master_ledger.csv"),**{**self.context,"candidate_db":changed})
            db.close()
            with self.assertRaisesRegex(ValueError,"direct_(journal_mode|status)_invalid"):
                r39._build(Path("ledger"),Path("ledger/master_ledger.csv"),**{**self.context,"candidate_db":changed})
    def test_validation_install_is_append_only_idempotent_and_gate_bound(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);database=root/"candidate.db";database.write_bytes(self.db_path.read_bytes());context={**self.context,"candidate_db":database}
            manifest,files=r39._build(Path("ledger"),Path("ledger/master_ledger.csv"),**context)
            package=root/"package";package.mkdir(mode=0o700)
            for name,data in files.items():path=package/name;path.write_bytes(data);path.chmod(0o600)
            result=r39.install_han_equality_validation(package,**context);self.assertTrue(result["installed"])
            retry=r39.install_han_equality_validation(package,**context);self.assertTrue(retry["idempotent"])
            db=sqlite3.connect(database)
            gate=_amount_relation_gate(db,self.run_id,{"directory":package,**context});self.assertTrue(gate["passed"]);self.assertEqual(gate["actual"]["validation_count"],1)
            fields=("run_id","status","package_set_sha256","authority_sha256","input_manifest_sha256","candidate_semantic_sha256","candidate_master_sha256","identity_role_set_sha256","amount_semantic_sha256")
            original=dict(zip(fields,db.execute("SELECT "+",".join(fields)+" FROM direct_projection_validations WHERE run_id=?",(self.run_id,)).fetchone()))
            forged={**original,"candidate_master_sha256":"0"*64};forged_sha=r39._sha(r39._json(forged))
            db.execute("DROP TRIGGER direct_projection_validations_no_update");db.execute("UPDATE direct_projection_validations SET candidate_master_sha256=?,validation_sha256=?",("0"*64,forged_sha));db.commit()
            self.assertFalse(_amount_relation_gate(db,self.run_id,{"directory":package,**context})["passed"])
            original_sha=r39._sha(r39._json(original));db.execute("UPDATE direct_projection_validations SET candidate_master_sha256=?,validation_sha256=?",(original["candidate_master_sha256"],original_sha));db.commit()
            db.execute("UPDATE direct_projection_runs SET gate_report_sha256='"+("f"*64)+"' WHERE run_id=?",(self.run_id,));db.commit()
            validation_sha=db.execute("SELECT validation_sha256 FROM direct_projection_validations WHERE run_id=?",(self.run_id,)).fetchone()[0]
            payment=db.execute("SELECT MIN(id) FROM payment_transactions").fetchone()[0]
            db.execute("UPDATE payment_transactions SET amount_krw=amount_krw+1 WHERE id=?",(payment,));db.commit()
            with self.assertRaisesRegex(RuntimeError,"activation_revalidation_failed"):_activate_candidate(db,self.run_id,"f"*64,validation_sha)
            db.execute("UPDATE payment_transactions SET amount_krw=amount_krw-1 WHERE id=?",(payment,));db.commit()
            _activate_candidate(db,self.run_id,"f"*64,validation_sha);db.commit()
            self.assertEqual(db.execute("SELECT status FROM direct_projection_runs WHERE run_id=?",(self.run_id,)).fetchone()[0],"passed")
            db.executescript("CREATE TRIGGER direct_projection_validations_no_update BEFORE UPDATE ON direct_projection_validations BEGIN SELECT RAISE(ABORT, 'direct_projection_validation_append_only'); END;")
            with self.assertRaisesRegex(sqlite3.IntegrityError,"append_only"):db.execute("UPDATE direct_projection_validations SET status='passed'")
            db.rollback()
            with self.assertRaisesRegex(sqlite3.IntegrityError,"append_only"):db.execute("DELETE FROM direct_projection_validations")
            db.rollback();db.close()
    def test_validation_trigger_and_activation_reject_missing_or_stale(self):
        with tempfile.TemporaryDirectory() as d:
            database=Path(d)/"candidate.db";database.write_bytes(self.db_path.read_bytes());db=sqlite3.connect(database)
            bad=(self.run_id,"passed")+("d"*64,)*8
            with self.assertRaisesRegex(sqlite3.IntegrityError,"run_mismatch"):
                db.execute("INSERT INTO direct_projection_validations(run_id,status,package_set_sha256,authority_sha256,input_manifest_sha256,candidate_semantic_sha256,candidate_master_sha256,identity_role_set_sha256,amount_semantic_sha256,validation_sha256) VALUES (?,?,?,?,?,?,?,?,?,?)",bad)
            db.rollback()
            forged=(self.run_id,"passed","d"*64,self.context["authority_sha256_expected"],self.input_sha,self.semantic_sha,"d"*64,"d"*64,"d"*64,"d"*64)
            db.execute("INSERT INTO direct_projection_validations(run_id,status,package_set_sha256,authority_sha256,input_manifest_sha256,candidate_semantic_sha256,candidate_master_sha256,identity_role_set_sha256,amount_semantic_sha256,validation_sha256) VALUES (?,?,?,?,?,?,?,?,?,?)",forged);db.commit()
            self.assertFalse(_amount_relation_gate(db,self.run_id)["passed"])
            db.execute("UPDATE direct_projection_runs SET gate_report_sha256=? WHERE run_id=?",("e"*64,self.run_id));db.commit()
            with self.assertRaisesRegex(RuntimeError,"activation_precondition_failed"):_activate_candidate(db,self.run_id,"e"*64,"0"*64)
            db.rollback();self.assertEqual(db.execute("SELECT status FROM direct_projection_runs WHERE run_id=?",(self.run_id,)).fetchone()[0],"building");db.close()
    def test_installer_rejects_package_or_db_change_before_transaction(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);database=root/"candidate.db";database.write_bytes(self.db_path.read_bytes());context={**self.context,"candidate_db":database}
            _,files=r39._build(Path("ledger"),Path("ledger/master_ledger.csv"),**context);package=root/"package";package.mkdir(mode=0o700)
            for name,data in files.items():path=package/name;path.write_bytes(data);path.chmod(0o600)
            original=(package/"summary.json").read_bytes()
            def swap(_db,_directory):(package/"summary.json").write_bytes(b"{}\n")
            with patch.object(r39,"_validation_pretransaction_hook",side_effect=swap),self.assertRaisesRegex(ValueError,"validation_package_changed"):
                r39.install_han_equality_validation(package,**context)
            (package/"summary.json").write_bytes(original)
            def mutate(db_path,_directory):
                db=sqlite3.connect(db_path);db.execute("UPDATE payment_transactions SET amount_krw=amount_krw+1 WHERE id=(SELECT MIN(id) FROM payment_transactions)");db.commit();db.close()
            with patch.object(r39,"_validation_pretransaction_hook",side_effect=mutate),self.assertRaisesRegex(ValueError,"validation_semantic_changed"):
                r39.install_han_equality_validation(package,**context)

if __name__=="__main__":unittest.main()
