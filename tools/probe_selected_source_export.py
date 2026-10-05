"""Check the selected read-only source export without emitting source data."""
import hashlib
import io
import json
from pathlib import Path
import urllib.error
import urllib.request
import zipfile

URL = "https://docs.google.com/spreadsheets/d/1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU/export?format=xlsx"
OUTPUT = Path(__file__).resolve().parents[1] / "docs/handoff/2026-10-01/source-export-probe.json"


def main():
    result = {"read_only": True, "source_upload_performed": False, "export_available": False}
    try:
        request = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            result["http_status"] = response.status
            data = response.read(20 * 1024 * 1024 + 1)
        if len(data) > 20 * 1024 * 1024:
            result["failure_code"] = "SOURCE_TOO_LARGE"
        elif not zipfile.is_zipfile(io.BytesIO(data)):
            result["failure_code"] = "SOURCE_NOT_XLSX"
        else:
            root = Path(r"D:\WebLedgerHost\review\source-refresh-probe")
            root.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256(data).hexdigest()
            target = root / (digest + ".xlsx")
            if not target.exists():
                target.write_bytes(data)
            result.update(export_available=True, snapshot_sha256=digest, byte_count=len(data))
    except urllib.error.HTTPError as error:
        result.update(http_status=error.code, failure_code="SOURCE_HTTP_ERROR")
    except Exception:
        result["failure_code"] = "SOURCE_FETCH_FAILED"
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
