"""Every OTA snapshot worker a test starts is stopped and joined before the next test runs."""
import pytest

from webapp import ota_snapshot


@pytest.fixture(autouse=True)
def _ota_snapshot_workers_stop_with_their_test():
    yield
    ota_snapshot.stop_all()
