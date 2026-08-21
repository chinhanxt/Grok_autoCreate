from pathlib import Path

from core.tor_launcher import TOR_INSTANCES, build_torrc, is_port_open


def test_tor_instances_match_web_ui_ports():
    assert [(i["socks_port"], i["control_port"]) for i in TOR_INSTANCES] == [
        (9050, 9051),
        (9052, 9053),
    ]


def test_build_torrc_binds_localhost_socks_and_control(tmp_path):
    torrc = build_torrc(
        data_dir=tmp_path,
        socks_port=9050,
        control_port=9051,
    )
    assert "SocksPort 127.0.0.1:9050 IsolateSOCKSAuth" in torrc
    assert "ControlPort 127.0.0.1:9051" in torrc
    assert "CookieAuthentication 0" in torrc
    assert str(tmp_path) in torrc


def test_is_port_open_false_for_unused_port():
    assert is_port_open("127.0.0.1", 59998) is False


def test_makefile_dev_starts_tor():
    makefile = Path("/home/chinhan/xai-grok-account-creator/Makefile").read_text()
    assert "dev: tor" in makefile
    assert "core.tor_launcher" in makefile
    assert "ensure_local_tors" in makefile
