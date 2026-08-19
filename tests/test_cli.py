import subprocess
import sys
import pytest


def test_cli_help():
    result = subprocess.run(
        [sys.executable, "cli.py", "--help"],
        capture_output=True,
        text=True,
        cwd="/home/chinhan/xai-grok-account-creator"
    )
    assert result.returncode == 0
    assert "Grok & x.ai Automated Account Creator CLI" in result.stdout
    assert "--email" in result.stdout
    assert "--tempmail" in result.stdout
    assert "--proxy" in result.stdout
    assert "--list" in result.stdout
