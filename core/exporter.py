"""
Account export and storage module.
"""
import os
import json
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Union


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
            "refresh_token": "...",
            "sso_cookie": "...",
            "sso_rw_cookie": "..."
        }
        """
        is_real_rt = bool(
            self.refresh_token
            and not self.refresh_token.startswith("sso")
            and ";" not in self.refresh_token
        )
        valid_ref = self.refresh_token if is_real_rt else ""
        acc_tok = self.access_token or self.sso_cookie
        sso = self.sso_cookie
        sso_rw = self.sso_rw_cookie or self.sso_cookie
        return {
            "email": self.email,
            "access_token": acc_tok,
            "refresh_token": valid_ref,
            "sso_cookie": sso,
            "sso_rw_cookie": sso_rw
        }

    def to_router_node_dict(self) -> Dict[str, Any]:
        # Chỉ nhận refresh_token thật (chuỗi OAuth hợp lệ, không chứa cookie 'sso=')
        is_real_rt = bool(self.refresh_token and not self.refresh_token.startswith("sso") and ";" not in self.refresh_token)
        valid_ref = self.refresh_token if is_real_rt else ""
        return {
            "id": self.user_id or str(uuid.uuid4()),
            "name": self.email,
            "email": self.email,
            "ssoToken": self.access_token,
            "refreshToken": valid_ref,
            "status": self.status or "active",
            "createdAt": self.created_at,
            "oauthVerified": is_real_rt,
            "oauthScope": self.extra.get("scope", "grok-cli:access") if self.extra else "grok-cli:access"
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


def _to_account_record(item: Any) -> AccountRecord:
    if isinstance(item, AccountRecord):
        return item
    if isinstance(item, dict):
        return AccountRecord(
            email=item.get("email", ""),
            password=item.get("password", ""),
            first_name=item.get("first_name", ""),
            last_name=item.get("last_name", ""),
            user_id=item.get("user_id", ""),
            session_id=item.get("session_id", ""),
            sso_cookie=item.get("sso_cookie", ""),
            sso_rw_cookie=item.get("sso_rw_cookie", ""),
            access_token=item.get("access_token", ""),
            refresh_token=item.get("refresh_token", ""),
            created_at=item.get("created_at") or datetime.now(timezone.utc).isoformat(),
            status=item.get("status", "active"),
            extra=item.get("extra") or {}
        )
    raise TypeError(f"Expected AccountRecord or dict, got {type(item)}")


def load_oauth_accounts(json_path: str = "accounts.json", only_healthy: bool = False) -> List[Dict[str, Any]]:
    """
    Loads and exports all accounts in standard Grok Router OAuth format:
    [
      {
        "email": "...",
        "access_token": "...",
        "refresh_token": "...",
        "sso_cookie": "...",
        "sso_rw_cookie": "..."
      }
    ]
    """
    raw_accounts = load_accounts(json_path)
    oauth_list = []
    for acc in raw_accounts:
        if only_healthy and acc.get("status") not in ("active", "healthy", "ok"):
            continue
        rec = _to_account_record(acc)
        oauth_list.append(rec.to_oauth_dict())
    return oauth_list


def save_oauth_router_accounts(output_path: str, json_path: str = "accounts.json", only_healthy: bool = False) -> int:
    """
    Exports all accounts to a dedicated router JSON file with 5 standard fields.
    Returns the count of exported accounts.
    """
    oauth_data = load_oauth_accounts(json_path, only_healthy=only_healthy)
    with _FILE_LOCK:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(oauth_data, f, indent=2, ensure_ascii=False)
    return len(oauth_data)


def export_for_router(
    output_path: Optional[str] = None,
    json_path: str = "accounts.json",
    only_healthy: bool = False,
    accounts: Optional[List[Any]] = None
) -> List[Dict[str, Any]]:
    """
    Exports accounts in standard format for Grok_Router-Mini:
    [
      {
        "id": "...",
        "name": "...",
        "email": "...",
        "ssoToken": "...",
        "refreshToken": "...",
        "status": "active",
        "createdAt": "...",
        "oauthVerified": True,
        "oauthScope": "grok-cli:access"
      }
    ]
    If output_path is provided, writes the router node list to that file.
    Returns the list of router node dicts.
    """
    if isinstance(output_path, list):
        accounts = output_path
        output_path = None

    if accounts is None:
        raw_accounts = load_accounts(json_path)
    else:
        raw_accounts = accounts

    router_nodes: List[Dict[str, Any]] = []
    for acc in raw_accounts:
        rec = _to_account_record(acc)
        if only_healthy and rec.status not in ("active", "healthy", "ok"):
            continue
        router_nodes.append(rec.to_router_node_dict())

    if output_path:
        with _FILE_LOCK:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(router_nodes, f, indent=2, ensure_ascii=False)

    return router_nodes

