from tools.agoda_windows_cdp_capture import SHARDS, _is_agoda_bookings_url, shard_for


def test_upcoming_has_one_logical_worker():
    key = b"k" * 32
    assert shard_for("Upcoming", "100000001", key) == "U01"
    assert shard_for("Upcoming", "100000002", key) == "U01"


def test_completed_is_partitioned_across_named_workers():
    key = b"k" * 32
    labels = {shard_for("Completed", str(100000000 + i), key) for i in range(1, 10000)}
    assert labels <= set(SHARDS[1:])
    assert labels == set(SHARDS[1:])


def test_cancelled_is_never_assigned():
    key = b"k" * 32
    assert shard_for("Cancelled", "100000001", key) is None
    assert shard_for("Unknown", "100000001", key) is None


def test_bookings_route_requires_agoda_host_and_account_path():
    assert _is_agoda_bookings_url("https://www.agoda.com/ko-kr/account/bookings.html")
    assert _is_agoda_bookings_url("https://agoda.com/account/bookings.html")
    assert not _is_agoda_bookings_url("https://example.com/account/bookings.html")
    assert not _is_agoda_bookings_url("https://www.agoda.com/ko-kr/")
