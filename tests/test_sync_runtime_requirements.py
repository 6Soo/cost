from pathlib import Path

import pytest

from tools.sync_runtime_requirements import synchronize


def test_check_detects_drift_without_writing_and_generation_preserves_source(tmp_path):
    source = tmp_path / "requirements.txt"
    source.write_bytes(b"# source owner\nexample[crypto]>=2.8,<3\nother==1.2\n")
    mirror = tmp_path / "webapp" / "requirements.txt"
    mirror.parent.mkdir()
    mirror.write_bytes(b"example==0\n")
    before = source.read_bytes()
    assert synchronize(tmp_path)["status"] == "DRIFT"
    assert mirror.read_bytes() == b"example==0\n"
    assert synchronize(tmp_path, write=True)["status"] == "GENERATED"
    assert source.read_bytes() == before
    assert synchronize(tmp_path)["status"] == "MATCH"
    assert mirror.read_text().splitlines()[-2:] == ["example[crypto]>=2.8,<3", "other==1.2"]


@pytest.mark.parametrize("declaration", ["-r nested.txt", "-e ../package", "./package.whl", ""])
def test_relative_or_empty_inputs_never_replace_the_mirror(tmp_path, declaration):
    (tmp_path / "requirements.txt").write_text(declaration, encoding="utf-8")
    mirror = tmp_path / "webapp" / "requirements.txt"
    mirror.parent.mkdir()
    mirror.write_bytes(b"preserved\n")
    with pytest.raises(ValueError):
        synchronize(tmp_path, write=True)
    assert mirror.read_bytes() == b"preserved\n"
