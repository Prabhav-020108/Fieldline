import asyncio
from unittest.mock import MagicMock, patch

import pytest

from connectivity import ConnectivityMonitor, _probe_internet


@pytest.fixture
def monitor():
    m = ConnectivityMonitor()
    yield m
    m.stop()


def test_initial_state_is_online(monitor):
    assert monitor.is_online is True


@pytest.mark.asyncio
async def test_mark_offline_fires_disconnect_callbacks_once(monitor):
    calls = []

    async def cb():
        calls.append("disconnected")

    monitor.on_disconnect(cb)
    monitor.mark_offline()
    await asyncio.sleep(0.01)

    assert monitor.is_online is False
    assert len(calls) == 1

    # Repeated call while already offline must NOT fire callback again
    monitor.mark_offline()
    await asyncio.sleep(0.01)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_mark_online_fires_reconnect_callbacks_once(monitor):
    calls = []

    async def cb():
        calls.append("reconnected")

    monitor.on_reconnect(cb)
    monitor.mark_offline()
    await asyncio.sleep(0.01)

    monitor.mark_online()
    await asyncio.sleep(0.01)

    assert monitor.is_online is True
    assert len(calls) == 1

    # Repeated call while already online must NOT fire callback again
    monitor.mark_online()
    await asyncio.sleep(0.01)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_start_and_stop_lifecycle(monitor):
    assert monitor._task is None
    monitor.start()
    assert monitor._task is not None
    assert not monitor._task.done()

    # Calling start() again should be a no-op (idempotent)
    task1 = monitor._task
    monitor.start()
    assert monitor._task is task1

    monitor.stop()
    assert monitor._task is None


def test_probe_internet_success():
    with patch("socket.create_connection") as mock_conn:
        mock_sock = MagicMock()
        mock_conn.return_value.__enter__.return_value = mock_sock
        assert _probe_internet() is True


def test_probe_internet_failure():
    with patch("socket.create_connection", side_effect=OSError("Network unreachable")):
        assert _probe_internet() is False
