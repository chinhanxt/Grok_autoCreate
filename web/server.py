"""
FastAPI Server for Grok & x.ai Account Creator Web UI.
Unified 1-Click Automated Mode with Realtime Temp-Mail.org Integration.
"""
import os
import uuid
import time
import random
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
    DEFAULT_NAME_PREFIX,
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

@app.on_event("startup")
def on_server_startup():
    from core.oauth import start_auto_oauth_daemon
    start_auto_oauth_daemon(interval_sec=3.0, max_workers=2)

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
    name_prefix: Optional[str] = DEFAULT_NAME_PREFIX
    # Concurrency / Multi-threading
    threads: int = 1
    # Proxy mode: "decoupled" (ProxyXoay for xAI + Tor for TempMail), "rotating", "tor", "direct"
    proxy_mode: str = "decoupled"
    use_tor: bool = False
    tor_for_tempmail: bool = False
    tor_socks_host: str = "127.0.0.1"
    tor_socks_port: int = DEFAULT_TOR_SOCKS_PORT
    tor_control_port: int = DEFAULT_TOR_CONTROL_PORT
    tor_password: Optional[str] = None
    # ProxyXoay Residential Proxy Settings
    rotating_proxy_key: Optional[str] = DEFAULT_PROXYXOAY_KEY
    rotating_proxy_nhamang: str = DEFAULT_PROXYXOAY_NHAMANG
    rotating_proxy_tinhthanh: str = DEFAULT_PROXYXOAY_TINHTHANH
    rotating_proxy_whitelist: Optional[str] = None
    # Dedicated Proxy Overrides
    xai_proxy: Optional[str] = None
    tempmail_proxy: Optional[str] = None


@app.get("/api/tor/status")
def get_tor_status(
    host: str = "127.0.0.1",
    socks_port: int = DEFAULT_TOR_SOCKS_PORT,
    control_port: int = DEFAULT_TOR_CONTROL_PORT
):
    """Checks Tor SOCKS5 proxy connection and returns current exit node IP info."""
    mgr = TorProxyManager(socks_host=host, socks_port=socks_port, control_port=control_port)
    ok, ip, details = mgr.check_connection(timeout_sec=10)
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


@app.post("/api/sync-oauth")
@app.get("/api/sync-oauth")
@app.post("/api/accounts/sync-oauth")
def sync_oauth_tokens_for_all():
    """
    Background worker that runs OAuth CLI token minting for all existing accounts in accounts.json.
    """
    def _worker():
        from core.engine import StealthEngine
        from core.oauth import OAuthTokenManager
        from core.exporter import load_accounts, save_account, AccountRecord
        from core.proxyxoay import ProxyXoayManager
        from concurrent.futures import ThreadPoolExecutor

        accounts = load_accounts(DEFAULT_JSON_OUTPUT)
        oauth_mgr = OAuthTokenManager()
        pending = [acc for acc in accounts if not (acc.get("access_token") and acc.get("access_token").startswith("eyJ")) and acc.get("sso_cookie")]
        if not pending:
            return

        px_mgr = ProxyXoayManager("HVnSXrEVXRSrUYBkwYzuId")
        ok, p_url, _ = px_mgr.get_proxy()
        proxy = p_url if ok else None

        save_lock = threading.Lock()

        def _sync_one(acc):
            engine = StealthEngine(headless=True, proxy=proxy)
            try:
                page = engine.start()
                cookies_to_set = [
                    {"name": "sso", "value": acc["sso_cookie"], "domain": ".x.ai", "path": "/"},
                    {"name": "sso-rw", "value": acc.get("sso_rw_cookie", acc["sso_cookie"]), "domain": ".x.ai", "path": "/"},
                    {"name": "sso", "value": acc["sso_cookie"], "domain": "accounts.x.ai", "path": "/"},
                    {"name": "sso-rw", "value": acc.get("sso_rw_cookie", acc["sso_cookie"]), "domain": "accounts.x.ai", "path": "/"},
                    {"name": "sso", "value": acc["sso_cookie"], "domain": "auth.x.ai", "path": "/"},
                    {"name": "sso-rw", "value": acc.get("sso_rw_cookie", acc["sso_cookie"]), "domain": "auth.x.ai", "path": "/"},
                ]
                page.context.add_cookies(cookies_to_set)
                tokens = oauth_mgr.mint_tokens_for_page(page, proxy=proxy)
                acc["access_token"] = tokens["access_token"]
                acc["refresh_token"] = tokens["refresh_token"]
                rec = AccountRecord(
                    email=acc["email"],
                    password=acc.get("password", DEFAULT_PASSWORD),
                    first_name=acc.get("first_name", ""),
                    last_name=acc.get("last_name", ""),
                    user_id=acc.get("user_id", "") or tokens.get("id_token", ""),
                    session_id=acc.get("session_id", ""),
                    sso_cookie=acc.get("sso_cookie", ""),
                    sso_rw_cookie=acc.get("sso_rw_cookie", ""),
                    access_token=tokens["access_token"],
                    refresh_token=tokens["refresh_token"]
                )
                with save_lock:
                    save_account(rec, DEFAULT_JSON_OUTPUT, DEFAULT_TXT_OUTPUT)
            except Exception as e:
                logger.warning(f"OAuth sync failed for {acc.get('email')}: {e}")
            finally:
                engine.close()

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(_sync_one, pending))

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
    tor2_mgr: Optional[TorProxyManager] = None
    proxyxoay_mgr: Optional[ProxyXoayManager] = None
    xai_active_proxy: Optional[str] = req.xai_proxy or req.proxy
    tempmail_active_proxy: Optional[str] = req.tempmail_proxy or req.proxy

    # Strategy:
    # 1. Decoupled (Default / Recommended): ProxyXoay for xAI, Tor with stream isolation for TempMail
    # 2. Rotating: ProxyXoay for both
    # 3. Tor: Tor for both
    # 4. Direct: Direct for both
    is_decoupled = (req.proxy_mode == "decoupled") or (req.tor_for_tempmail and bool(req.rotating_proxy_key)) or (req.use_tor and bool(req.rotating_proxy_key))
    is_rotating_only = (req.proxy_mode == "rotating") and not req.tor_for_tempmail and not req.use_tor
    is_tor_only = (req.proxy_mode == "tor") and not is_decoupled
    use_tor_for_tm = is_decoupled or is_tor_only or req.tor_for_tempmail or (req.use_tor and not is_rotating_only)

    # Connect ProxyXoay for xAI
    if is_decoupled or is_rotating_only or (bool(req.rotating_proxy_key) and req.proxy_mode != "direct" and req.proxy_mode != "tor"):
        if req.rotating_proxy_key:
            sess["logs"].append(f"Đang kết nối Proxy Dân Cư cho xAI (proxyxoay.shop)...")
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
                sess["logs"].append(f"Đã kết nối Proxy Dân Cư (xAI): {ip} [{isp.upper() if isp else ''} - {loc}]")
                xai_active_proxy = p_url
                if not is_decoupled and not req.tor_for_tempmail:
                    tempmail_active_proxy = p_url
            else:
                msg = p_data.get("message") or p_data.get("error") or "Không lấy được proxy"
                sess["logs"].append(f"Không lấy được ProxyXoay ({msg}).")

    # Connect Tor for TempMail
    if use_tor_for_tm:
        sess["logs"].append(f"Đang kết nối Tor SOCKS5 ({req.tor_socks_host}:{req.tor_socks_port}) với Stream Isolation cho TempMail...")
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
            sess["logs"].append(f"Đã kết nối Tor Proxy thành công! Exit Node: {ip}{loc_str}")
            if is_decoupled or req.tor_for_tempmail:
                tempmail_active_proxy = tor_mgr.proxy_url
                sess["logs"].append(f"Đã kích hoạt Stream Isolation: Mỗi luồng TempMail nhận 1 mạch/IP Tor riêng biệt.")
            if is_tor_only:
                xai_active_proxy = tor_mgr.proxy_url
                tempmail_active_proxy = tor_mgr.proxy_url
        else:
            sess["logs"].append(f"Không thể kết nối Tor Proxy tại {tor_mgr.proxy_url}.")
        tor2_mgr = TorProxyManager(
            socks_host=req.tor_socks_host,
            socks_port=9052,
            control_port=9053,
            control_password=req.tor_password
        )

    # If xAI proxy is not set (e.g. ProxyXoay expired or not configured):
    # Trình duyệt x.ai dùng kết nối Trực tiếp (Direct - proxy=None) vì x.ai chặn dải IP Tor
    if not xai_active_proxy:
        xai_active_proxy = None
        sess["logs"].append("Trình duyệt x.ai: Kết nối Trực tiếp (Direct Mode - Tránh lỗi Tor Region Block).")

    num_threads = min(max(1, req.threads or 1), 10)
    sess["threads"] = num_threads
    sess["start_time"] = time.time()
    sess["thread_states"] = {
        str(t): {
            "id": t,
            "status": "idle",
            "account_num": 0,
            "email": "",
            "step": "Chờ lệnh...",
            "progress": 0,
            "elapsed_sec": 0
        }
        for t in range(1, num_threads + 1)
    }
    
    lock = threading.Lock()
    available_wids = list(range(1, num_threads + 1))
    wid_lock = threading.Lock()

    def _acquire_wid():
        with wid_lock:
            return available_wids.pop(0) if available_wids else 1

    def _release_wid(wid):
        with wid_lock:
            if wid not in available_wids:
                available_wids.append(wid)
                available_wids.sort()

    if num_threads > 1 and total_count > 1:
        sess["logs"].append(f"Chạy song song {num_threads} luồng (Tổng: {total_count} acc)")
    else:
        sess["logs"].append(f"Bắt đầu tạo {total_count} tài khoản...")

    # For shared-IP proxy modes, pre-create mailbox pool.
    pool = None
    is_tor_isolated = tor_mgr and (is_decoupled or req.tor_for_tempmail or is_tor_only)
    if num_threads > 1 and req.use_tempmail and total_count > 0 and not is_tor_isolated and not sess.get("stopped", False):
        tm_mgr = proxyxoay_mgr

        def _on_mailbox_progress(made_count, total, entry):
            if entry:
                sess["logs"].append(f"✔ Đã tạo hòm thư #{made_count}/{total}: {entry.email}")
            elif made_count < total:
                sess["logs"].append(f"Chuẩn bị hòm thư #{made_count + 1}/{total}...")

        sess["logs"].append(f"Đang chuẩn bị {total_count} hòm thư Temp-Mail...")
        pool = MailboxPool(
            proxy_mgr=tm_mgr,
            count=total_count,
            spacing=1.5,
            stopped=lambda: sess.get("stopped", False),
            initial_proxy=tempmail_active_proxy if not tm_mgr else None,
            progress_callback=_on_mailbox_progress,
        )
        made = pool.prepare()
        if made < total_count:
            sess["logs"].append(f"⚠️ Chỉ tạo được {made}/{total_count} hòm thư Temp-Mail.")
        else:
            sess["logs"].append(f"Đã chuẩn bị sẵn {made}/{total_count} hòm thư.")

    def _create_single_account(i: int):
        if sess.get("stopped"):
            return

        wid = _acquire_wid()
        t_start = time.time()
        tag = f"[L{wid}]" if num_threads > 1 else ""

        def _set_thread_state(step: str, progress: int, status: str = "running", email_addr: str = None):
            with lock:
                ts = sess["thread_states"].get(str(wid))
                if ts:
                    ts["status"] = status
                    ts["account_num"] = i + 1
                    if email_addr:
                        ts["email"] = email_addr
                    ts["step"] = step
                    ts["progress"] = progress
                    ts["elapsed_sec"] = int(time.time() - t_start)

        try:
            _set_thread_state("1. Khởi tạo trình duyệt & proxy...", 15)
            # Stagger concurrent thread starts slightly
            if num_threads > 1 and i > 0:
                time.sleep(min((i % num_threads) * 0.2, 0.8))

            # Determine Name for this account
            if req.random_name or not req.first_name:
                prefix = (req.name_prefix or DEFAULT_NAME_PREFIX).strip() or DEFAULT_NAME_PREFIX
                first_name, last_name = generate_random_name(prefix=prefix)
            else:
                first_name = req.first_name
                last_name = req.last_name or DEFAULT_LAST_NAME

            password = req.password or DEFAULT_PASSWORD

            with lock:
                sess["current_index"] = max(sess.get("current_index", 0), i + 1)
                sess["logs"].append(f"{tag} #{i+1}/{total_count} Bắt đầu: {first_name} {last_name}")

            # Acquire or dynamically create mailbox for this account
            _set_thread_state("2. Đang lấy hòm thư Temp-Mail...", 30)
            tempmail_client = None
            email = None
            if req.use_tempmail:
                if pool is not None:
                    mailbox = pool.acquire(timeout=1.0)
                    if mailbox is not None:
                        mbox_proxy = mailbox.proxy or tempmail_active_proxy
                        tempmail_client = TempMailClient(proxy=mbox_proxy)
                        tempmail_client.set_token(mailbox.token, email=mailbox.email)
                        email = mailbox.email
                
                if not email:
                    # Retry mailbox creation with per-worker Tor stream isolation
                    for mb_try in range(3):
                        try:
                            worker_tor_proxy = None
                            if tempmail_active_proxy and "9050" in tempmail_active_proxy:
                                rnd_id = random.randint(10000, 99999)
                                worker_tor_proxy = f"socks5://tw_{wid}_{rnd_id}:pwd_{rnd_id}@127.0.0.1:{req.tor_socks_port}"
                            tempmail_client = TempMailClient(proxy=worker_tor_proxy or tempmail_active_proxy)
                            email, token = tempmail_client.create_inbox()
                            break
                        except Exception as e:
                            if mb_try == 2:
                                _set_thread_state(f"Lỗi lấy hòm thư: {e}", 0, status="error")
                                with lock:
                                    sess["failed_count"] += 1
                                    sess["logs"].append(f"{tag} Lỗi Temp-Mail: {e}")
                                return
                            time.sleep(1.0 + mb_try * 1.0)

            _set_thread_state("3. Truy cập x.ai & vượt Cloudflare...", 45, email_addr=email)
            with lock:
                sess["logs"].append(f"{tag} Inbox: {email} -> Đang mở x.ai...")

            max_attempts = 2
            for attempt in range(max_attempts):
                if sess.get("stopped"):
                    break

                t_attempt_start = time.time()

                # Dynamic proxy rotation for xAI per account attempt if ProxyXoay is enabled
                thread_xai_proxy = xai_active_proxy
                if proxyxoay_mgr and (is_decoupled or is_rotating_only):
                    try:
                        ok_rot, p_url, _ = proxyxoay_mgr.get_proxy()
                        if ok_rot and p_url:
                            thread_xai_proxy = p_url
                    except Exception:
                        pass

                if attempt > 0:
                    # Acquire fresh mailbox for retry attempt so we don't collide with already registered email
                    fresh_email = None
                    if pool is not None:
                        mailbox = pool.acquire(timeout=0.5)
                        if mailbox:
                            mbox_proxy = mailbox.proxy or tempmail_active_proxy
                            tempmail_client = TempMailClient(proxy=mbox_proxy)
                            tempmail_client.set_token(mailbox.token, email=mailbox.email)
                            fresh_email = mailbox.email
                    if not fresh_email:
                        try:
                            worker_tor_proxy = None
                            if tempmail_active_proxy and "9050" in tempmail_active_proxy:
                                rnd_id = random.randint(10000, 99999)
                                worker_tor_proxy = f"socks5://tw_{wid}_{rnd_id}:pwd_{rnd_id}@127.0.0.1:{req.tor_socks_port}"
                            tempmail_client = TempMailClient(proxy=worker_tor_proxy or tempmail_active_proxy)
                            fresh_email, _ = tempmail_client.create_inbox()
                        except Exception:
                            pass
                    if fresh_email:
                        email = fresh_email

                    _set_thread_state(f"Thử lại lần {attempt+1}/{max_attempts}...", 40, email_addr=email)
                    with lock:
                        sess["logs"].append(f"{tag} Thử lại lần {attempt+1}/{max_attempts}... (Email mới: {email})")
                    time.sleep(1.0)

                engine = StealthEngine(headless=req.headless, proxy=thread_xai_proxy)
                creator = AccountCreator(engine=engine)

                try:
                    creator.start_signup(email=email)
                    _set_thread_state("4. Đang chờ mã OTP (SpaceXAI)...", 65, email_addr=email)
                    with lock:
                        sess["logs"].append(f"{tag} Đã vượt Cloudflare -> Chờ OTP...")

                    otp_code = tempmail_client.fetch_otp_code(timeout_sec=50, page=creator.page)
                    if not otp_code:
                        raise RuntimeError("Không nhận được mã OTP từ x.ai.")

                    _set_thread_state(f"5. Xác nhận OTP ({otp_code}) & tạo Profile...", 85, email_addr=email)
                    with lock:
                        sess["logs"].append(f"{tag} OTP: {otp_code} -> Đang đăng ký...")

                    creator.submit_otp(code=otp_code)

                    record = creator.complete_registration(
                        first_name=first_name,
                        last_name=last_name,
                        password=password
                    )
                    if not record.sso_cookie and not record.user_id and not record.access_token:
                        raise RuntimeError("Không lấy được phiên đăng nhập (SSO/OAuth rỗng).")

                    with lock:
                        save_account(record, json_path=DEFAULT_JSON_OUTPUT, txt_path=DEFAULT_TXT_OUTPUT)
                        sess["success_count"] += 1
                        sess["created_accounts"].append(record.to_dict())
                        sess["account"] = record.to_dict()
                        sess["logs"].append(f"{tag} ✔ Thành công: {email}")

                    _set_thread_state(f"✔ Thành công", 100, status="success", email_addr=email)
                    break

                except Exception as e:
                    err_msg = str(e)
                    # If Region Blocked, auto-rotate Tor IP so next attempt uses a fresh US exit node!
                    if ("region" in err_msg.lower() or "blocked" in err_msg.lower()) and not sess.get("stopped"):
                        try:
                            if tor2_mgr:
                                tor2_mgr.renew_ip(wait_sec=1.5)
                            elif tor_mgr:
                                tor_mgr.renew_ip(wait_sec=1.5)
                        except Exception:
                            pass

                    if attempt < max_attempts - 1 and not sess.get("stopped"):
                        with lock:
                            sess["logs"].append(f"{tag} Thử lại: {err_msg}")
                        time.sleep(1.0)
                    else:
                        _set_thread_state(f"Thất bại: {err_msg}", 0, status="error", email_addr=email)
                        with lock:
                            sess["failed_count"] += 1
                            sess["logs"].append(f"{tag} ✖ Thất bại: {err_msg}")
                            if total_count == 1:
                                sess["error"] = err_msg
                finally:
                    engine.close()
        finally:
            _release_wid(wid)

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
        sess["logs"].append(f"Đã dừng tiến trình ({sess['success_count']}/{total_count} thành công).")
    elif sess["success_count"] > 0:
        sess["status"] = "success"
        sess["stage"] = "finished"
        sess["logs"].append(f"✔ HOÀN TẤT: Tạo thành công {sess['success_count']}/{total_count} tài khoản.")
    else:
        sess["status"] = "failed"
        sess["stage"] = "error"
        sess["error"] = "Tất cả các lượt tạo đều thất bại."
        sess["logs"].append(f"✖ Kết thúc: Tất cả {total_count} lượt đều thất bại.")


@app.post("/api/start-signup")
def start_signup(req: SignupRequest):
    task_id = str(uuid.uuid4())
    total_count = max(1, req.count or 1)
    num_threads = min(max(1, req.threads or 1), 10)
    SESSIONS[task_id] = {
        "id": task_id,
        "status": "pending",
        "stage": "starting",
        "logs": [],
        "total_count": total_count,
        "threads": num_threads,
        "thread_states": {
            str(t): {
                "id": t,
                "status": "idle",
                "account_num": 0,
                "email": "",
                "step": "Chờ lệnh...",
                "progress": 0,
                "elapsed_sec": 0
            }
            for t in range(1, num_threads + 1)
        },
        "current_index": 0,
        "success_count": 0,
        "failed_count": 0,
        "created_accounts": [],
        "stopped": False,
        "start_time": time.time(),
        "email": None,
        "error": None,
        "account": None
    }
    t = threading.Thread(target=_run_account_creation_worker, args=(task_id, req), daemon=True)
    t.start()
    return {"task_id": task_id, "status": "started", "total_count": total_count, "threads": num_threads}


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
    elapsed = int(time.time() - sess["start_time"]) if sess.get("start_time") else 0
    return {
        "id": task_id,
        "status": sess.get("status"),
        "stage": sess.get("stage"),
        "total_count": sess.get("total_count", 1),
        "current_index": sess.get("current_index", 0),
        "success_count": sess.get("success_count", 0),
        "failed_count": sess.get("failed_count", 0),
        "stopped": sess.get("stopped", False),
        "threads": sess.get("threads", 1),
        "thread_states": sess.get("thread_states", {}),
        "elapsed_sec": elapsed,
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
