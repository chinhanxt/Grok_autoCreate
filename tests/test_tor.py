import pytest
from core.tor_proxy import TorProxyManager


def test_tor_proxy_manager_initialization():
    mgr = TorProxyManager(socks_host="127.0.0.1", socks_port=9050, control_port=9051)
    assert mgr.proxy_url == "socks5://127.0.0.1:9050"
    assert mgr.socks_port == 9050
    assert mgr.control_port == 9051


def test_tor_proxy_offline_check():
    # Test with a dummy non-existent port to ensure graceful False return
    mgr = TorProxyManager(socks_host="127.0.0.1", socks_port=59999)
    ok, ip, details = mgr.check_connection(timeout_sec=1)
    assert ok is False
    assert ip is None


def test_tor_proxy_stream_isolation():
    mgr = TorProxyManager(socks_host="127.0.0.1", socks_port=9050)
    assert mgr.get_isolated_proxy_url() == "socks5://127.0.0.1:9050"
    assert mgr.get_isolated_proxy_url("worker_1") == "socks5://worker_1:tor@127.0.0.1:9050"
    assert mgr.get_isolated_proxy_url("worker_5") == "socks5://worker_5:tor@127.0.0.1:9050"


def test_tor_proxy_get_proxy_and_rotate():
    mgr = TorProxyManager(socks_host="127.0.0.1", socks_port=9050)
    ok, url, data = mgr.get_proxy(stream_id="stream_abc")
    assert ok is True
    assert url == "socks5://stream_abc:tor@127.0.0.1:9050"
    assert data.get("stream_id") == "stream_abc"

    ok_rot, rot_url, rot_data = mgr.rotate_to_new_ip()
    assert ok_rot is True
    assert "tor_rot_" in rot_url
    assert "9050" in rot_url
