"""
FastAPI Server for Grok & x.ai Account Creator Web UI.
Unified 1-Click Automated Mode with Realtime Temp-Mail.org Integration.
"""
import os
import uuid
import time
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, Any, List
from pydantic import BaseModel

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from core.engine import StealthEngine
from core.auth import AccountCreator
from core.tempmail import TempMailClient
from core.mailbox_pool import MailboxPool
from core.exporter import AccountRecord, save_account, load_accounts
from core.tor_proxy import TorProxyManager
from core.proxyxoay import ProxyXoayManager
from config import (
    DEFAULT_JSON_OUTPUT,
    DEFAULT_TXT_OUTPUT,
    DEFAULT_FIRST_NAME,
    DEFAULT_LAST_NAME,
    DEFAULT_PASSWORD,
    DEFAULT_TOR_SOCKS_PORT,
    DEFAULT_TOR_CONTROL_PORT,
    DEFAULT_TOR_PROXY_URL,
    DEFAULT_PROXYXOAY_KEY,
    DEFAULT_PROXYXOAY_NHAMANG,
    DEFAULT_PROXYXOAY_TINHTHANH,
    generate_random_name
)

logger = logging.getLogger("xai_web")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Grok & x.ai Account Creator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active creation sessions
SESSIONS: Dict[str, Dict[str, Any]] = {}


class SignupRequest(BaseModel):
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    password: Optional[str] = DEFAULT_PASSWORD
    use_tempmail: bool = True
    proxy: Optional[str] = None
    headless: bool = True
    count: int = 1
    random_name: bool = True
    # Concurrency / Multi-threading
    threads: int = 1
    # Proxy mode: "rotating", "tor", "direct"
    proxy_mode: str = "rotating"
    use_tor: bool = False
    tor_socks_host: str = "127.0.0.1"
    tor_socks_port: int = DEFAULT_TOR_SOCKS_PORT
    tor_control_port: int = DEFAULT_TOR_CONTROL_PORT
    tor_password: Optional[str] = None
    # ProxyXoay Residential Proxy Settings
    rotating_proxy_key: Optional[str] = DEFAULT_PROXYXOAY_KEY
    rotating_proxy_nhamang: str = DEFAULT_PROXYXOAY_NHAMANG
    rotating_proxy_tinhthanh: str = DEFAULT_PROXYXOAY_TINHTHANH
    rotating_proxy_whitelist: Optional[str] = None


@app.get("/api/tor/status")
def get_tor_status(
    host: str = "127.0.0.1",
    socks_port: int = DEFAULT_TOR_SOCKS_PORT,
    control_port: int = DEFAULT_TOR_CONTROL_PORT
):
    """Checks Tor SOCKS5 proxy connection and returns current exit node IP info."""
    mgr = TorProxyManager(socks_host=host, socks_port=socks_port, control_port=control_port)
    ok, ip, details = mgr.check_connection(timeout_sec=5)
    return {
        "online": ok,
        "proxy_url": mgr.proxy_url,
        "ip": ip,
        "details": details or {}
    }


@app.post("/api/tor/renew-ip")
def renew_tor_ip(
    host: str = "127.0.0.1",
    socks_port: int = DEFAULT_TOR_SOCKS_PORT,
    control_port: int = DEFAULT_TOR_CONTROL_PORT,
    password: Optional[str] = None
):
    """Triggers SIGNAL NEWNYM to rotate to a new Tor Exit Node IP."""
    mgr = TorProxyManager(
        socks_host=host,
        socks_port=socks_port,
        control_port=control_port,
        control_password=password
    )
    ok, new_ip = mgr.renew_ip(wait_sec=2.5)
    return {
        "success": ok,
        "ip": new_ip,
        "proxy_url": mgr.proxy_url
    }


@app.get("/api/rotating-proxy/status")
def get_rotating_proxy_status(
    key: str = DEFAULT_PROXYXOAY_KEY,
    nhamang: str = DEFAULT_PROXYXOAY_NHAMANG,
    tinhthanh: str = DEFAULT_PROXYXOAY_TINHTHANH,
    whitelist: Optional[str] = None
):
    """Checks ProxyXoay residential rotating proxy status and current IP."""
    mgr = ProxyXoayManager(api_key=key, nhamang=nhamang, tinhthanh=tinhthanh, whitelist=whitelist)
    ok, proxy_url, data = mgr.get_proxy(timeout_sec=8)
    return {
        "success": ok,
        "proxy_url": proxy_url,
        "ip": mgr.last_ip or data.get("ip"),
        "nhamang": data.get("Nha Mang"),
        "vitri": data.get("Vi Tri"),
        "message": data.get("message"),
        "status": data.get("status"),
        "wait_seconds": data.get("wait_seconds", 0),
        "raw": data
    }


@app.post("/api/rotating-proxy/rotate")
def rotate_rotating_proxy(
    key: str = DEFAULT_PROXYXOAY_KEY,
    nhamang: str = DEFAULT_PROXYXOAY_NHAMANG,
    tinhthanh: str = DEFAULT_PROXYXOAY_TINHTHANH,
    whitelist: Optional[str] = None
):
    """Forces ProxyXoay to rotate to a new residential IP."""
    mgr = ProxyXoayManager(api_key=key, nhamang=nhamang, tinhthanh=tinhthanh, whitelist=whitelist)
    ok, proxy_url, data = mgr.get_proxy(force_rotate=True, timeout_sec=8)
    return {
        "success": ok,
        "proxy_url": proxy_url,
        "ip": mgr.last_ip or data.get("ip"),
        "nhamang": data.get("Nha Mang"),
        "vitri": data.get("Vi Tri"),
        "message": data.get("message"),
        "status": data.get("status"),
        "wait_seconds": data.get("wait_seconds", 0),
        "raw": data
    }


@app.get("/api/accounts")
def get_accounts():
    """Returns the list of all saved accounts."""
    return load_accounts(DEFAULT_JSON_OUTPUT)


@app.delete("/api/accounts/{index}")
def delete_account(index: int):
    """Deletes an account by list index."""
    accounts = load_accounts(DEFAULT_JSON_OUTPUT)
    if 0 <= index < len(accounts):
        deleted = accounts.pop(index)
        import json
        with open(DEFAULT_JSON_OUTPUT, "w", encoding="utf-8") as f:
            json.dump(accounts, f, indent=2, ensure_ascii=False)
        # Also rewrite txt
        with open(DEFAULT_TXT_OUTPUT, "w", encoding="utf-8") as f:
            for acc in accounts:
                f.write(f"{acc.get('email')}:{acc.get('password')}:{acc.get('sso_cookie')}:{acc.get('user_id')}\n")
        return {"status": "success", "deleted": deleted}
    raise HTTPException(status_code=404, detail="Account index out of range")


@app.get("/api/export-json")
def export_json():
    if os.path.exists(DEFAULT_JSON_OUTPUT):
        return FileResponse(DEFAULT_JSON_OUTPUT, filename="grok_accounts.json", media_type="application/json")
    return JSONResponse(content=[])


@app.get("/api/export-oauth-json")
def export_oauth_json():
    """
    Exports all accounts formatted specifically for Grok Routers and CLI Token managers:
    [
      {
        "email": "...",
        "access_token": "...",
        "refresh_token": "..."
      }
    ]
    """
    from core.exporter import load_oauth_accounts
    oauth_data = load_oauth_accounts(DEFAULT_JSON_OUTPUT)
    return JSONResponse(
        content=oauth_data,
        headers={"Content-Disposition": "attachment; filename=grok_oauth_tokens.json"}
    )


@app.post("/api/accounts/sync-oauth")
def sync_oauth_tokens_for_all():
    """
    Background worker that runs OAuth CLI token minting for all existing accounts in accounts.json.
    """
    def _worker():
        from core.engine import StealthEngine
        from core.oauth import OAuthTokenManager
        from core.exporter import load_accounts, save_account, AccountRecord

        accounts = load_accounts(DEFAULT_JSON_OUTPUT)
        oauth_mgr = OAuthTokenManager()
        for acc in accounts:
            if acc.get("access_token", "").startswith("eyJ0eXAiOiJhdCtqd3Qi"):
                continue
            if not acc.get("sso_cookie"):
                continue
            engine = StealthEngine(headless=True)
            try:
                page = engine.start()
                cookies_to_set = [
                    {"name": "sso", "value": acc["sso_cookie"], "domain": ".x.ai", "path": "/"},
                    {"name": "sso-rw", "value": acc.get("sso_rw_cookie", acc["sso_cookie"]), "domain": ".x.ai", "path": "/"},
                    {"name": "sso", "value": acc["sso_cookie"], "domain": ".grok.com", "path": "/"},
                    {"name": "sso-rw", "value": acc.get("sso_rw_cookie", acc["sso_cookie"]), "domain": ".grok.com", "path": "/"},
                ]
                page.context.add_cookies(cookies_to_set)
                tokens = oauth_mgr.mint_tokens_for_page(page)
                acc["access_token"] = tokens["access_token"]
                acc["refresh_token"] = tokens["refresh_token"]
                rec = AccountRecord(
                    email=acc["email"],
                    password=acc.get("password", DEFAULT_PASSWORD),
                    first_name=acc.get("first_name", ""),
                    last_name=acc.get("last_name", ""),
                    user_id=acc.get("user_id", ""),
                    session_id=acc.get("session_id", ""),
                    sso_cookie=acc.get("sso_cookie", ""),
                    sso_rw_cookie=acc.get("sso_rw_cookie", ""),
                    access_token=tokens["access_token"],
                    refresh_token=tokens["refresh_token"]
                )
                save_account(rec, DEFAULT_JSON_OUTPUT, DEFAULT_TXT_OUTPUT)
            except Exception as e:
                logger.warning(f"OAuth sync failed for {acc.get('email')}: {e}")
            finally:
                engine.close()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return {"status": "started", "message": "Đang đồng bộ OAuth Token cho tất cả tài khoản trong nền..."}


@app.get("/api/export-txt")
def export_txt():
    if os.path.exists(DEFAULT_TXT_OUTPUT):
        return FileResponse(DEFAULT_TXT_OUTPUT, filename="grok_accounts.txt", media_type="text/plain")
    return Response(content="", media_type="text/plain")


def _run_account_creation_worker(task_id: str, req: SignupRequest):
    sess = SESSIONS[task_id]
    total_count = max(1, req.count or 1)
    sess["total_count"] = total_count
    sess["status"] = "running"
    sess["stage"] = "initializing"

    tor_mgr: Optional[TorProxyManager] = None
    proxyxoay_mgr: Optional[ProxyXoayManager] = None
    active_proxy = req.proxy

    # Determine Proxy Strategy
    is_rotating = (req.proxy_mode == "rotating") or (bool(req.rotating_proxy_key) and req.proxy_mode != "tor" and req.proxy_mode != "direct")
    is_tor = (req.proxy_mode == "tor") or (req.use_tor and not is_rotating)

    if is_rotating and req.rotating_proxy_key:
        sess["logs"].append(f"Đang kết nối Proxy Dân Cư (proxyxoay.shop)...")
        proxyxoay_mgr = ProxyXoayManager(
            api_key=req.rotating_proxy_key,
            nhamang=req.rotating_proxy_nhamang,
            tinhthanh=req.rotating_proxy_tinhthanh,
            whitelist=req.rotating_proxy_whitelist
        )
        ok, p_url, p_data = proxyxoay_mgr.get_proxy(timeout_sec=10)
        if ok and p_url:
            loc = p_data.get("Vi Tri", "")
            isp = p_data.get("Nha Mang", "")
            ip = p_data.get("ip") or p_url
            sess["logs"].append(f"Đã kết nối Proxy Dân Cư: {ip} [{isp.upper() if isp else ''} - {loc}]")
            active_proxy = p_url
        else:
            msg = p_data.get("message") or p_data.get("error") or "Không lấy được proxy"
            sess["logs"].append(f"Không lấy được ProxyXoay ({msg}). Chuyển sang Direct IP.")

    elif is_tor:
        sess["logs"].append(f"Đang kiểm tra kết nối mạng Tor Proxy ({req.tor_socks_host}:{req.tor_socks_port})...")
        tor_mgr = TorProxyManager(
            socks_host=req.tor_socks_host,
            socks_port=req.tor_socks_port,
            control_port=req.tor_control_port,
            control_password=req.tor_password
        )
        ok, ip, details = tor_mgr.check_connection(timeout_sec=8)
        if ok and ip:
            country = details.get("country", "") if details else ""
            city = details.get("city", "") if details else ""
            loc_str = f" ({city}, {country})" if (city or country) else ""
            sess["logs"].append(f"Đã kết nối Tor Proxy thành công! Exit Node IP: {ip}{loc_str}")
            active_proxy = tor_mgr.proxy_url
        else:
            sess["logs"].append(f"Không thể kết nối Tor Proxy tại {tor_mgr.proxy_url}. Sử dụng proxy mặc định / direct.")

    num_threads = min(max(1, req.threads or 1), 10)
    sess["threads"] = num_threads
    
    lock = threading.Lock()

    if num_threads > 1 and total_count > 1:
        sess["logs"].append(f"Chế độ ĐA LUỒNG: Chạy đồng thời {num_threads} luồng song song.")
    sess["logs"].append(f"Bắt đầu tiến trình tạo {total_count} tài khoản Grok / x.ai...")

    # Pre-create a Temp-Mail mailbox pool (serialized) before firing threads.
    # Only worth it for multi-thread runs; single-thread web tempmail creates
    # inline via a MailboxPool(count=1) inside _create_single_account so it
    # stays consistent (serialized) instead of recreating concurrently.
    pool = None
    if num_threads > 1 and req.use_tempmail and total_count > 0 and not sess.get("stopped", False):
        sess["logs"].append(f"Đang tạo hòm thư Temp-Mail #1/{total_count} (serialized)...")
        pool = MailboxPool(
            proxy_mgr=proxyxoay_mgr,
            count=total_count,
            stopped=lambda: sess.get("stopped", False),
            initial_proxy=active_proxy,
        )
        made = pool.prepare()
        if made < total_count:
            sess["logs"].append(
                f"⚠️ Cảnh báo: Chỉ tạo được {made}/{total_count} hòm thư Temp-Mail. "
                f"Các tài khoản vượt quá số hòm thư sẽ thất bại với 'không đủ hòm thư Temp-Mail' "
                f"thay vì spam 429."
            )

    def _create_single_account(i: int):
        if sess.get("stopped"):
            return

        # Stagger concurrent thread starts slightly so browser processes and network don't choke
        if num_threads > 1 and i > 0:
            time.sleep(min((i % num_threads) * 1.5, 4.5))

        prefix_tag = f"[{i + 1}/{total_count}]" if total_count > 1 else ""

        # Determine Name for this account
        if req.random_name or not req.first_name:
            first_name, last_name = generate_random_name()
        else:
            first_name = req.first_name
            last_name = req.last_name or DEFAULT_LAST_NAME

        password = req.password or DEFAULT_PASSWORD

        with lock:
            sess["current_index"] = max(sess.get("current_index", 0), i + 1)
            sess["logs"].append(f"----------------------------------------")
            sess["logs"].append(f"{prefix_tag} Bắt đầu tạo tài khoản: {first_name} {last_name}")

        max_attempts = 3

        # Acquire a pre-created Temp-Mail mailbox ONCE (reused across retry attempts)
        mailbox = None
        tempmail_client = None
        email = None
        if pool is not None:
            mailbox = pool.acquire(timeout=0)
            if mailbox is None:
                with lock:
                    sess["failed_count"] += 1
                    sess["logs"].append(f"{prefix_tag} Thất bại: không đủ hòm thư Temp-Mail.")
                return
            tempmail_client = TempMailClient(proxy=mailbox.proxy)
            tempmail_client.set_token(mailbox.token)
            email = mailbox.email

        for attempt in range(max_attempts):
            if sess.get("stopped"):
                break

            # Dynamic proxy rotation per account attempt if ProxyXoay is enabled
            thread_proxy = active_proxy
            if is_rotating and proxyxoay_mgr:
                try:
                    ok_rot, p_url, _ = proxyxoay_mgr.get_proxy()
                    if ok_rot and p_url:
                        thread_proxy = p_url
                except Exception:
                    pass

            if attempt > 0:
                with lock:
                    sess["logs"].append(f"{prefix_tag} Thử lại tạo tài khoản (lần {attempt+1}/{max_attempts})...")
                time.sleep(1.0)

            engine = StealthEngine(headless=req.headless, proxy=thread_proxy)
            creator = AccountCreator(engine=engine)

            try:
                with lock:
                    sess["logs"].append(f"{prefix_tag} Đang tạo hòm thư Temp-Mail tự động...")
                if tempmail_client is None:
                    inline_pool = MailboxPool(
                        proxy_mgr=proxyxoay_mgr,
                        count=1,
                        stopped=lambda: sess.get("stopped", False),
                        initial_proxy=thread_proxy,
                    )
                    inline_pool.prepare()
                    mbox = inline_pool.acquire(timeout=0)
                    if mbox is None:
                        raise RuntimeError("không đủ hòm thư Temp-Mail.")
                    tempmail_client = TempMailClient(proxy=mbox.proxy)
                    tempmail_client.set_token(mbox.token)
                    email = mbox.email
                with lock:
                    sess["email"] = email
                    sess["logs"].append(f"{prefix_tag} Email: {email} ({tempmail_client.provider})")
                    sess["logs"].append(f"{prefix_tag} Đang truy cập x.ai & vượt Cloudflare...")

                creator.start_signup(email=email)
                with lock:
                    sess["logs"].append(f"{prefix_tag} Đã vượt Cloudflare & gửi yêu cầu mã OTP.")
                    sess["logs"].append(f"{prefix_tag} Đang chờ mã OTP từ SpaceXAI cho {email}...")

                otp_code = tempmail_client.fetch_otp_code(timeout_sec=120, page=creator.page)
                if not otp_code:
                    raise RuntimeError(f"Không nhận được mã OTP từ x.ai trong thời gian chờ.")
                with lock:
                    sess["logs"].append(f"{prefix_tag} Đã nhận mã OTP: {otp_code}")
                    sess["logs"].append(f"{prefix_tag} Đang nhập OTP ({otp_code}) vào x.ai...")

                creator.submit_otp(code=otp_code)

                with lock:
                    sess["logs"].append(f"{prefix_tag} Thiết lập Profile ({first_name} {last_name}) và mật khẩu...")

                record = creator.complete_registration(
                    first_name=first_name,
                    last_name=last_name,
                    password=password
                )
                if not record.sso_cookie and not record.user_id:
                    raise RuntimeError("Không thể tạo phiên đăng nhập (SSO Cookie rỗng).")

                with lock:
                    save_account(record, json_path=DEFAULT_JSON_OUTPUT, txt_path=DEFAULT_TXT_OUTPUT)
                    sess["success_count"] += 1
                    sess["created_accounts"].append(record.to_dict())
                    sess["account"] = record.to_dict()
                    sess["logs"].append(f"{prefix_tag} Tạo tài khoản THÀNH CÔNG!")
                    sess["logs"].append(f"  Email: {email} | Pass: {password}")
                    sess["logs"].append(f"  User ID: {record.user_id} | Name: {first_name}")
                break

            except Exception as e:
                err_msg = str(e)
                if attempt < max_attempts - 1 and not sess.get("stopped"):
                    with lock:
                        sess["logs"].append(f"{prefix_tag} Gặp sự cố tạm thời ({err_msg}). Tự động thử lại...")
                    time.sleep(1.0)
                else:
                    with lock:
                        sess["failed_count"] += 1
                        sess["logs"].append(f"{prefix_tag} Thất bại: {err_msg}")
                        if total_count == 1:
                            sess["error"] = err_msg
                    # Do NOT release `mailbox` back to the pool: its email was
                    # already used in a signup attempt, so a later thread could
                    # re-acquire it and hit "email already registered" cascades.
            finally:
                engine.close()

    if num_threads > 1 and total_count > 1:
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(_create_single_account, idx) for idx in range(total_count)]
            for f in as_completed(futures):
                if sess.get("stopped"):
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
    else:
        for idx in range(total_count):
            if sess.get("stopped"):
                break
            _create_single_account(idx)
            if idx < total_count - 1 and not sess.get("stopped"):
                time.sleep(1.0)

    # Final status determination
    if sess.get("stopped"):
        sess["status"] = "stopped"
        sess["stage"] = "stopped"
        sess["logs"].append(f"\nĐã dừng tiến trình theo yêu cầu (Đã tạo thành công {sess['success_count']}/{total_count}).")
    elif sess["success_count"] > 0:
        sess["status"] = "success"
        sess["stage"] = "finished"
        sess["logs"].append(f"\nHOÀN TẤT TIẾN TRÌNH! Đã tạo thành công {sess['success_count']}/{total_count} tài khoản.")
    else:
        sess["status"] = "failed"
        sess["stage"] = "error"
        sess["error"] = "Tất cả các lượt tạo đều thất bại."
        sess["logs"].append(f"\nKết thúc: Tất cả {total_count} lượt tạo đều thất bại.")


@app.post("/api/start-signup")
def start_signup(req: SignupRequest):
    task_id = str(uuid.uuid4())
    total_count = max(1, req.count or 1)
    SESSIONS[task_id] = {
        "id": task_id,
        "status": "pending",
        "stage": "starting",
        "logs": [],
        "total_count": total_count,
        "current_index": 0,
        "success_count": 0,
        "failed_count": 0,
        "created_accounts": [],
        "stopped": False,
        "email": None,
        "error": None,
        "account": None
    }
    t = threading.Thread(target=_run_account_creation_worker, args=(task_id, req), daemon=True)
    t.start()
    return {"task_id": task_id, "status": "started", "total_count": total_count}


@app.post("/api/stop-task/{task_id}")
def stop_task(task_id: str):
    if task_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Task ID not found")
    SESSIONS[task_id]["stopped"] = True
    SESSIONS[task_id]["logs"].append("⚠️ Đã gửi tín hiệu dừng tiến trình...")
    return {"status": "stopping", "task_id": task_id}


@app.get("/api/task-status/{task_id}")
def get_task_status(task_id: str):
    if task_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Task ID not found")
    sess = SESSIONS[task_id]
    return {
        "id": task_id,
        "status": sess.get("status"),
        "stage": sess.get("stage"),
        "total_count": sess.get("total_count", 1),
        "current_index": sess.get("current_index", 0),
        "success_count": sess.get("success_count", 0),
        "failed_count": sess.get("failed_count", 0),
        "stopped": sess.get("stopped", False),
        "email": sess.get("email"),
        "logs": sess.get("logs", []),
        "error": sess.get("error"),
        "account": sess.get("account"),
        "created_accounts": sess.get("created_accounts", [])
    }


# Static Web Files
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
