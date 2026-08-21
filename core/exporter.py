"""
Account export and storage module.
"""
import os
import json
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any


@dataclass
class AccountRecord:
    email: str
    password: str
    first_name: str
    last_name: str
    user_id: str = ""
    session_id: str = ""
    sso_cookie: str = ""
    sso_rw_cookie: str = ""
    access_token: str = ""
    refresh_token: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "active"
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_oauth_dict(self) -> Dict[str, Any]:
        """
        Returns standard OAuth format for Grok routers / API gateways:
        {
            "email": "...",
            "access_token": "...",
            "refresh_token": "..."
        }
        """
        acc_tok = self.access_token or self.sso_cookie
        ref_tok = self.refresh_token or self.sso_rw_cookie or self.sso_cookie
        return {
            "email": self.email,
            "access_token": acc_tok,
            "refresh_token": ref_tok
        }

    def to_line_format(self) -> str:
        """
        Returns standard colon-separated format:
        email:password:sso_cookie:user_id
        """
        return f"{self.email}:{self.password}:{self.sso_cookie}:{self.user_id}"


_FILE_LOCK = __import__("threading").Lock()


def save_account(
    account: AccountRecord,
    json_path: str = "accounts.json",
    txt_path: str = "accounts.txt"
) -> None:
    """
    Saves an AccountRecord to both JSON and TXT format in a thread-safe manner.
    """
    with _FILE_LOCK:
        # 1. Update JSON file
        existing_accounts: List[Dict[str, Any]] = []
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    existing_accounts = json.load(f)
                    if not isinstance(existing_accounts, list):
                        existing_accounts = []
            except Exception:
                existing_accounts = []

        # Check if email already exists, update or append
        account_dict = account.to_dict()
        updated = False
        for i, acc in enumerate(existing_accounts):
            if acc.get("email", "").lower() == account.email.lower():
                # Preserve existing access_token if new record does not have one
                if not account_dict.get("access_token") and acc.get("access_token"):
                    account_dict["access_token"] = acc["access_token"]
                    account_dict["refresh_token"] = acc.get("refresh_token", "")
                existing_accounts[i] = account_dict
                updated = True
                break
        if not updated:
            existing_accounts.append(account_dict)

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(existing_accounts, f, indent=2, ensure_ascii=False)

        # 2. Append or rewrite TXT file
        with open(txt_path, "w", encoding="utf-8") as f:
            for acc in existing_accounts:
                line = f"{acc.get('email', '')}:{acc.get('password', '')}:{acc.get('sso_cookie', '')}:{acc.get('user_id', '')}"
                f.write(line + "\n")

        # 3. Trigger auto-oauth daemon if this account lacks OAuth access token
        if not (account_dict.get("access_token") and account_dict.get("access_token").startswith("eyJ")) and account_dict.get("sso_cookie"):
            try:
                from core.oauth import start_auto_oauth_daemon
                start_auto_oauth_daemon()
            except Exception:
                pass


def load_accounts(json_path: str = "accounts.json") -> List[Dict[str, Any]]:
    """
    Loads all accounts from the JSON file.
    """
    if not os.path.exists(json_path):
        return []
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def load_oauth_accounts(json_path: str = "accounts.json") -> List[Dict[str, Any]]:
    """
    Loads and exports all accounts in standard Grok Router OAuth format:
    [
      {
        "email": "...",
        "access_token": "...",
        "refresh_token": "..."
      }
    ]
    """
    raw_accounts = load_accounts(json_path)
    oauth_list = []
    for acc in raw_accounts:
        email = acc.get("email", "")
        # Use access_token if present, else fallback to sso JWT
        access_token = acc.get("access_token") or acc.get("sso_cookie", "")
        # Use refresh_token if present, else fallback to sso_rw_cookie or sso_cookie
        refresh_token = acc.get("refresh_token") or acc.get("sso_rw_cookie") or acc.get("sso_cookie", "")
        oauth_list.append({
            "email": email,
            "access_token": access_token,
            "refresh_token": refresh_token
        })
    return oauth_list
