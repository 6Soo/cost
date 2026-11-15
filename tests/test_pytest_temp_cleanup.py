import pytest

import conftest


def test_session_cleanup_removes_only_its_direct_child(tmp_path):
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    owned = temp_root / "cost-pytest-owned"
    other_run = temp_root / "cost-pytest-other"
    owned.mkdir()
    other_run.mkdir()
    (owned / "test.sqlite").write_bytes(b"owned")
    (other_run / "test.sqlite").write_bytes(b"other run")

    assert conftest._remove_session_folder(owned, temp_root, retries=1, delay=0)

    assert not owned.exists()
    assert (other_run / "test.sqlite").read_bytes() == b"other run"


def test_session_cleanup_refuses_paths_outside_temp_root(tmp_path):
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    outside = tmp_path / "customer-data"
    outside.mkdir()
    sentinel = outside / "keep.sqlite"
    sentinel.write_bytes(b"preserve")

    assert not conftest._is_safe_session_child(outside, temp_root)
    assert not conftest._remove_session_folder(outside, temp_root, retries=1, delay=0)
    assert sentinel.read_bytes() == b"preserve"


def test_session_cleanup_refuses_reparse_points(tmp_path, monkeypatch):
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    candidate = temp_root / "cost-pytest-junction"
    candidate.mkdir()
    sentinel = candidate / "keep.sqlite"
    sentinel.write_bytes(b"preserve")
    monkeypatch.setattr(conftest, "_is_reparse_point", lambda _details: True)

    assert not conftest._is_safe_session_child(candidate, temp_root)
    assert not conftest._remove_session_folder(candidate, temp_root, retries=1, delay=0)
    assert sentinel.read_bytes() == b"preserve"


def test_session_cleanup_refuses_symlinks_to_external_directories(tmp_path):
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "keep.sqlite"
    sentinel.write_bytes(b"preserve")
    link = temp_root / "cost-pytest-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"directory symlink unavailable: {exc}")

    assert not conftest._is_safe_session_child(link, temp_root)
    assert not conftest._remove_session_folder(link, temp_root, retries=1, delay=0)
    assert sentinel.read_bytes() == b"preserve"
