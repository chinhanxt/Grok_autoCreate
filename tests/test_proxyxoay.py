import pytest
from core.proxyxoay import ProxyXoayManager


def test_proxyxoay_initialization():
    mgr = ProxyXoayManager(api_key="TEST_KEY", nhamang="viettel", tinhthanh="1")
    assert mgr.api_key == "TEST_KEY"
    assert mgr.nhamang == "viettel"
    assert mgr.tinhthanh == "1"


def test_proxyxoay_empty_key():
    mgr = ProxyXoayManager(api_key="")
    ok, proxy_url, data = mgr.get_proxy()
    assert ok is False
    assert proxy_url is None
