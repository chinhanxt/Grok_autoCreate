import inspect
import subprocess
import sys

import cli


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


def test_cli_imports_mailbox_pool():
    assert hasattr(cli, "MailboxPool")
    assert hasattr(cli, "MailboxEntry")


def test_create_single_account_accepts_mailbox_kwarg():
    params = inspect.signature(cli.create_single_account).parameters
    assert "mailbox" in params
    assert params["mailbox"].default is None
