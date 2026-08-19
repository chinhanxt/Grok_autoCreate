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
