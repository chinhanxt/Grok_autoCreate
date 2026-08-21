"""
Start local Tor SOCKS daemons used by the Web UI (Tor 1 + Tor 2).

Does not require a system `tor` package: the Ubuntu .deb is extracted into
vendor/tor and launched as the current user on 127.0.0.1.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENDOR_TOR_ROOT = PROJECT_ROOT / "vendor" / "tor"
VENDOR_TOR_BIN = VENDOR_TOR_ROOT / "usr" / "bin" / "tor"
RUN_ROOT = PROJECT_ROOT / ".run"

TOR_INSTANCES = [
    {"name": "tor1", "socks_port": 9050, "control_port": 9051},
    {"name": "tor2", "socks_port": 9052, "control_port": 9053},
]

_TOR_DEB_PACKAGES = ["tor", "libevent-2.1-7t64"]


def is_port_open(host: str, port: int, timeout_sec: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True
    except OSError:
        return False


def build_torrc(data_dir: Path, socks_port: int, control_port: int) -> str:
    data_dir = Path(data_dir)
    return "\n".join([
        f"DataDirectory {data_dir}",
        f"PidFile {data_dir / 'tor.pid'}",
        f"Log notice file {data_dir / 'notice.log'}",
        f"SocksPort 127.0.0.1:{socks_port} IsolateSOCKSAuth",
        f"ControlPort 127.0.0.1:{control_port}",
        "CookieAuthentication 0",
        "AvoidDiskWrites 1",
        "SafeLogging 0",
        "",
    ])


def find_tor_binary() -> Path:
    env_bin = os.environ.get("TOR_BIN")
    if env_bin and Path(env_bin).is_file() and os.access(env_bin, os.X_OK):
        return Path(env_bin)

    which = shutil.which("tor")
    if which:
        return Path(which)

    if VENDOR_TOR_BIN.is_file() and os.access(VENDOR_TOR_BIN, os.X_OK):
        return VENDOR_TOR_BIN

    ensure_vendor_tor()
    if VENDOR_TOR_BIN.is_file() and os.access(VENDOR_TOR_BIN, os.X_OK):
        return VENDOR_TOR_BIN

    raise FileNotFoundError(
        "Không tìm thấy binary Tor. Hãy chạy: make install  hoặc cài gói tor."
    )


def ensure_vendor_tor() -> Path:
    """Extract Ubuntu tor + libevent debs into vendor/tor (no sudo)."""
    if VENDOR_TOR_BIN.is_file() and os.access(VENDOR_TOR_BIN, os.X_OK):
        return VENDOR_TOR_BIN

    VENDOR_TOR_ROOT.mkdir(parents=True, exist_ok=True)
    apt_get = shutil.which("apt-get")
    dpkg_deb = shutil.which("dpkg-deb")
    if not apt_get or not dpkg_deb:
        raise RuntimeError("Cần apt-get và dpkg-deb để tải Tor (không cần sudo).")

    with tempfile.TemporaryDirectory(prefix="tor-debs-") as tmp:
        tmp_path = Path(tmp)
        proc = subprocess.run(
            [apt_get, "download", *_TOR_DEB_PACKAGES],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"apt-get download tor thất bại:\n{proc.stderr or proc.stdout}")

        debs = list(tmp_path.glob("*.deb"))
        if not debs:
            raise RuntimeError("Không tải được file .deb của tor.")

        for deb in debs:
            extract = subprocess.run(
                [dpkg_deb, "-x", str(deb), str(VENDOR_TOR_ROOT)],
                capture_output=True,
                text=True,
            )
            if extract.returncode != 0:
                raise RuntimeError(f"dpkg-deb -x {deb.name} thất bại:\n{extract.stderr}")

    if not VENDOR_TOR_BIN.is_file():
        raise RuntimeError(f"Extract xong nhưng không thấy {VENDOR_TOR_BIN}")
    VENDOR_TOR_BIN.chmod(0o755)
    return VENDOR_TOR_BIN


def _tor_env(tor_bin: Path) -> dict:
    env = os.environ.copy()
    lib_dirs = [
        VENDOR_TOR_ROOT / "usr" / "lib" / "x86_64-linux-gnu",
        VENDOR_TOR_ROOT / "lib" / "x86_64-linux-gnu",
    ]
    extra = [str(p) for p in lib_dirs if p.is_dir()]
    if extra:
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = ":".join(extra + ([existing] if existing else []))
    env.setdefault("HOME", str(Path.home()))
    return env


def _write_torrc(instance: Dict[str, int]) -> Path:
    data_dir = RUN_ROOT / instance["name"]
    data_dir.mkdir(parents=True, exist_ok=True)
    torrc_path = data_dir / "torrc"
    torrc_path.write_text(
        build_torrc(data_dir, instance["socks_port"], instance["control_port"]),
        encoding="utf-8",
    )
    return torrc_path


def _start_instance(instance: Dict[str, int], tor_bin: Path) -> None:
    torrc_path = _write_torrc(instance)
    log_path = RUN_ROOT / instance["name"] / "notice.log"
    if log_path.exists():
        log_path.write_text("", encoding="utf-8")

    cmd = [str(tor_bin), "-f", str(torrc_path), "--RunAsDaemon", "1"]
    proc = subprocess.run(
        cmd,
        env=_tor_env(tor_bin),
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Không start được {instance['name']} (SOCKS {instance['socks_port']}):\n"
            f"{proc.stderr or proc.stdout}"
        )


def _wait_bootstrapped(instance: Dict[str, int], timeout_sec: float = 90.0) -> bool:
    log_path = RUN_ROOT / instance["name"] / "notice.log"
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if log_path.is_file():
            text = log_path.read_text(encoding="utf-8", errors="ignore")
            if "Bootstrapped 100%" in text:
                return True
            if "Could not bind" in text or "Address already in use" in text:
                return is_port_open("127.0.0.1", instance["socks_port"])
        elif is_port_open("127.0.0.1", instance["socks_port"]):
            time.sleep(0.4)
        else:
            time.sleep(0.4)
    return is_port_open("127.0.0.1", instance["socks_port"])


def ensure_local_tors(timeout_sec: float = 90.0, quiet: bool = False) -> List[Dict[str, object]]:
    """
    Ensure Tor 1 (9050/9051) and Tor 2 (9052/9053) are listening on localhost.
    Idempotent: already-open SOCKS ports are left alone.
    """
    tor_bin = find_tor_binary()
    results: List[Dict[str, object]] = []

    def _log(msg: str) -> None:
        if not quiet:
            print(msg, flush=True)

    _log(f"Tor binary: {tor_bin}")

    for instance in TOR_INSTANCES:
        name = instance["name"]
        socks = instance["socks_port"]
        control = instance["control_port"]
        already = is_port_open("127.0.0.1", socks)
        started = False
        if already:
            _log(f"✔ {name}: SOCKS {socks} đã mở sẵn")
        else:
            _log(f"→ Khởi động {name} (SOCKS {socks}, Control {control})...")
            _start_instance(instance, tor_bin)
            started = True
            ready = _wait_bootstrapped(instance, timeout_sec=timeout_sec)
            if not ready:
                _log(f"⚠ {name}: daemon đã chạy nhưng chưa bootstrap 100% (timeout {timeout_sec}s)")
            else:
                _log(f"✔ {name}: online tại socks5://127.0.0.1:{socks}")
        results.append({
            "name": name,
            "socks_port": socks,
            "control_port": control,
            "already_running": already,
            "started": started,
            "online": is_port_open("127.0.0.1", socks),
        })

    missing = [r["name"] for r in results if not r["online"]]
    if missing:
        raise RuntimeError(
            "Tor chưa listen: " + ", ".join(str(n) for n in missing)
            + ". Xem log trong .run/tor1/notice.log và .run/tor2/notice.log"
        )
    return results


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        ensure_local_tors()
        return 0
    except Exception as exc:
        print(f"❌ {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
