from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from webapp.candidate_reader import ReadOnlyCandidate
from webapp.comparator import (
    compare_rows,
    export_sidecar_rows,
    read_sidecar,
    write_csv,
)
from webapp.server import WebApp, serve
from webapp.snapshot_descriptor import ContractError, seal_snapshot, verify_snapshot

from .fixtures import build_demo_snapshot


class Phase0Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cost-phase0-"))
        self.fix = build_demo_snapshot(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class DescriptorTests(Phase0Base):
    def test_seal_and_verify_ok(self):
        result = verify_snapshot(self.fix["descriptor_path"])
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["descriptor"]["run_id"], "run-demo-1")
        self.assertEqual(
            result["descriptor"]["candidate_semantic_sha256"], "a" * 64
        )

    def test_detects_db_mutation(self):
        with open(self.fix["db"], "r+b") as handle:
            handle.seek(-1, 2)
            byte = handle.read(1)
            handle.seek(-1, 2)
            handle.write(bytes([byte[0] ^ 0xFF]))
        result = verify_snapshot(self.fix["descriptor_path"])
        self.assertFalse(result["ok"])
        self.assertTrue(any("sha256 mismatch" in p for p in result["problems"]))

    def test_rejects_wal_sidecar_at_seal(self):
        Path(str(self.fix["db"]) + "-wal").write_bytes(b"x")
        with self.assertRaises(ContractError):
            seal_snapshot(
                self.fix["db"], gate_report_path=self.fix["gate_report"]
            )

    def test_verify_fails_when_gate_report_tampered(self):
        report = json.loads(self.fix["gate_report"].read_text(encoding="utf-8"))
        report["readiness"]["release_ready"] = True
        self.fix["gate_report"].write_text(
            json.dumps(report), encoding="utf-8"
        )
        result = verify_snapshot(self.fix["descriptor_path"])
        self.assertFalse(result["ok"])


class ReaderTests(Phase0Base):
    def test_query_only_blocks_write_and_disk_unchanged(self):
        from webapp.snapshot_descriptor import verify_snapshot

        result = verify_snapshot(self.fix["descriptor_path"])
        descriptor = dict(result["descriptor"])
        descriptor["base_dir"] = str(self.tmp)
        reader = ReadOnlyCandidate(self.fix["db"], descriptor=descriptor)
        try:
            exc = reader.assert_write_blocked()
            self.assertIsNotNone(exc)
            self.assertEqual(reader.integrity_check(), "ok")
            summary = reader.payments_summary()
            self.assertEqual(summary["count"], 5)
            self.assertEqual(summary["sum_krw"], 205461 + 556929 + 8420 - 543947 + 1307772)
            decisions = reader.active_decisions()
            self.assertEqual(len(decisions), 2)
            gates = reader.gates_from_report()
            by_name = {g["gate"]: g for g in gates}
            self.assertEqual(by_name["GATE5"]["status"], "FAIL")
            self.assertIs(by_name["TRIAGE_PASS"]["status"], True)
            self.assertIs(by_name["release_ready"]["status"], False)
        finally:
            reader.close()
        self.assertTrue(reader.unchanged_on_disk)

    def test_sidecar_rows_export(self):
        reader = ReadOnlyCandidate(self.fix["db"])
        try:
            rows = export_sidecar_rows(reader)
        finally:
            reader.close()
        keys = {r["key"] for r in rows}
        self.assertIn("TX-0004", keys)
        cancelled = next(r for r in rows if r["key"] == "TX-0004")
        self.assertEqual(cancelled["sign"], -1)
        self.assertEqual(cancelled["amount_krw"], 543947)


class ComparatorTests(Phase0Base):
    def _rows(self):
        reader = ReadOnlyCandidate(self.fix["db"])
        try:
            return export_sidecar_rows(reader)
        finally:
            reader.close()

    def test_csv_roundtrip_equal(self):
        rows = self._rows()
        csv_path = write_csv(rows, self.tmp / "sidecar.csv")
        other = read_sidecar(csv_path)
        self.assertTrue(compare_rows(rows, other)["ok"])

    def test_xlsx_roundtrip_equal(self):
        from openpyxl import Workbook

        rows = self._rows()
        xlsx = self.tmp / "sidecar.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.append(["key", "amount_krw", "lane", "sign"])
        for row in rows:
            ws.append([row["key"], row["amount_krw"], row["lane"], row["sign"]])
        wb.save(str(xlsx))
        other = read_sidecar(xlsx)
        report = compare_rows(rows, other)
        self.assertTrue(report["ok"], report)

    def test_detects_amount_mismatch(self):
        rows = self._rows()
        tampered = [dict(r) for r in rows]
        tampered[0]["amount_krw"] += 111
        report = compare_rows(rows, tampered)
        self.assertFalse(report["ok"])
        self.assertEqual(report["problems"][0]["type"], "field_mismatch")


class ServerPhase0Tests(Phase0Base):
    def test_no_post_routes_in_phase0(self):
        app = WebApp(self.fix["descriptor_path"], include_writes=False)
        methods = {method for method, _, _ in app.routes()}
        self.assertNotIn("POST", methods)

    def test_http_smoke_phase0(self):
        app = WebApp(self.fix["descriptor_path"], include_writes=False)
        server = serve(app, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        try:
            base = f"http://127.0.0.1:{port}"
            with urllib.request.urlopen(f"{base}/queue") as res:
                body = res.read().decode("utf-8")
                self.assertEqual(res.status, 200)
                self.assertIn("잔여 큐", body)
                self.assertIn("PLAZA HOTEL MUTSU", body)
            with urllib.request.urlopen(f"{base}/gates") as res:
                body = res.read().decode("utf-8")
                self.assertIn("TRIAGE_PASS", body)
                self.assertIn("release_ready", body)
            request = urllib.request.Request(
                f"{base}/api/propose",
                data=b"stream_id=X",
                method="POST",
            )
            try:
                urllib.request.urlopen(request)
                self.fail("expected 404 in phase0")
            except urllib.error.HTTPError as err:
                self.assertEqual(err.code, 404)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
