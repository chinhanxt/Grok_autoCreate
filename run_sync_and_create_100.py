import time
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.engine import StealthEngine
from core.auth import AccountCreator
from core.tempmail import TempMailClient
from core.exporter import load_accounts, save_account, AccountRecord
from core.proxyxoay import ProxyXoayManager
from core.oauth import OAuthTokenManager
from config import generate_random_name, DEFAULT_JSON_OUTPUT, DEFAULT_TXT_OUTPUT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("sync_and_create")

PROXYXOAY_KEY = "HVnSXrEVXRSrUYBkwYzuId"
TARGET_NEW_ACCOUNTS = 100
CREATION_WORKERS = 20
SYNC_WORKERS = 5

stop_event = threading.Event()
save_lock = threading.Lock()
created_success = 0
create_lock = threading.Lock()
tm_lock = threading.Lock()

# ==================== LUỒNG ĐỒNG BỘ TỰ ĐỘNG CHẠY SONG SONG LIÊN TỤC ====================
def background_sync_loop():
    """
    Chạy song song liên tục trong suốt quá trình tạo tài khoản.
    Bất kỳ tài khoản nào vừa tạo xong hoặc tài khoản cũ chưa có OAuth
    sẽ được lập tức cấp OAuth CLI Token siêu tốc (Direct ~6-10s).
    """
    logger.info("⚡ Đã kích hoạt [TIẾN TRÌNH ĐỒNG BỘ OAUTH SONG SONG]")
    oauth_mgr = OAuthTokenManager()

    def _sync_single(acc):
        email = acc.get("email")
        sso = acc.get("sso_cookie")
        sso_rw = acc.get("sso_rw_cookie", sso)
        if not sso:
            return
        
        logger.info(f"🔄 [Auto-Sync] Đang cấp bù OAuth cho: {email}...")
        engine = StealthEngine(headless=True)
        try:
            page = engine.start()
            cookies = [
                {"name": "sso", "value": sso, "domain": ".x.ai", "path": "/"},
                {"name": "sso-rw", "value": sso_rw, "domain": ".x.ai", "path": "/"},
                {"name": "sso", "value": sso, "domain": "accounts.x.ai", "path": "/"},
                {"name": "sso-rw", "value": sso_rw, "domain": "accounts.x.ai", "path": "/"},
                {"name": "sso", "value": sso, "domain": "auth.x.ai", "path": "/"},
                {"name": "sso-rw", "value": sso_rw, "domain": "auth.x.ai", "path": "/"},
            ]
            page.context.add_cookies(cookies)
            tokens = oauth_mgr.mint_tokens_for_page(page)
            
            rec = AccountRecord(
                email=email,
                password=acc.get("password", "taikhoanAI123"),
                first_name=acc.get("first_name", ""),
                last_name=acc.get("last_name", ""),
                user_id=acc.get("user_id", "") or tokens.get("id_token", ""),
                session_id=acc.get("session_id", ""),
                sso_cookie=sso,
                sso_rw_cookie=sso_rw,
                access_token=tokens["access_token"],
                refresh_token=tokens["refresh_token"]
            )
            with save_lock:
                save_account(rec, DEFAULT_JSON_OUTPUT, DEFAULT_TXT_OUTPUT)
                logger.info(f"✔ [Auto-Sync] ĐỒNG BỘ THÀNH CÔNG: {email} -> OAuth Token OK!")
        except Exception as e:
            logger.warning(f"✘ [Auto-Sync] Lỗi cấp bù {email}: {e}")
        finally:
            engine.close()

    while not stop_event.is_set():
        try:
            with save_lock:
                accounts = load_accounts(DEFAULT_JSON_OUTPUT)
            
            pending = [
                acc for acc in accounts 
                if not (acc.get("access_token") and acc.get("access_token").startswith("eyJ"))
                and acc.get("sso_cookie")
            ]
            
            if pending:
                logger.info(f"🔍 [Auto-Sync] Tìm thấy {len(pending)} tài khoản cần đồng bộ OAuth. Bắt đầu xử lý...")
                with ThreadPoolExecutor(max_workers=SYNC_WORKERS) as pool:
                    list(pool.map(_sync_single, pending[:SYNC_WORKERS * 2]))
            
            time.sleep(3.0)
        except Exception as e:
            logger.warning(f"[Auto-Sync Loop Notice]: {e}")
            time.sleep(5.0)


# ==================== LUỒNG TẠO TÀI KHOẢN MỚI ====================
def create_one_worker(worker_id: int):
    global created_success
    
    while not stop_event.is_set():
        with create_lock:
            if created_success >= TARGET_NEW_ACCOUNTS:
                break

        first_name, last_name = generate_random_name()
        password = "taikhoanAI123"

        px_mgr = ProxyXoayManager(api_key=PROXYXOAY_KEY)
        ok, p_url, _ = px_mgr.get_proxy()
        xai_proxy = p_url if ok else None

        tm = None
        email = None
        for attempt in range(5):
            try:
                tm = TempMailClient(max_retry_delay=15.0)
                email, token = tm.create_inbox()
                if email:
                    break
            except Exception as e:
                time.sleep(1.0)

        if not email or not tm:
            time.sleep(2.0)
            continue

        engine = None
        try:
            logger.info(f"[W{worker_id}] Bắt đầu tạo tài khoản {email} ({first_name} {last_name})...")
            engine = StealthEngine(headless=True, proxy=xai_proxy)
            creator = AccountCreator(engine=engine)

            creator.start_signup(email=email)
            otp = tm.fetch_otp_code(timeout_sec=60, page=creator.page)
            if not otp:
                raise RuntimeError(f"OTP timeout cho {email}")

            logger.info(f"[W{worker_id}] OTP nhận được: {otp}. Đang xác thực & điền thông tin...")
            creator.submit_otp(code=otp)

            record = creator.complete_registration(
                first_name=first_name,
                last_name=last_name,
                password=password
            )

            # Cấp ngay mã OAuth 2.0 trực tiếp
            has_oauth = bool(record.access_token and record.access_token.startswith("eyJ"))
            if not has_oauth:
                try:
                    from core.oauth import OAuthTokenManager
                    oauth_mgr = OAuthTokenManager()
                    toks = oauth_mgr.mint_tokens_for_page(creator.page)
                    record.access_token = toks.get("access_token", "")
                    record.refresh_token = toks.get("refresh_token", "")
                    has_oauth = bool(record.access_token and record.access_token.startswith("eyJ"))
                except Exception as e:
                    logger.warning(f"[W{worker_id}] Cấp OAuth trực tiếp notice (Auto-Sync sẽ xử lý bù): {e}")

            with save_lock:
                save_account(record, DEFAULT_JSON_OUTPUT, DEFAULT_TXT_OUTPUT)
            
            with create_lock:
                created_success += 1
                curr = created_success
                logger.info(f"🎉 [{curr}/{TARGET_NEW_ACCOUNTS}] TẠO THÀNH CÔNG: {email} | OAuth: {has_oauth}")
            
        except Exception as e:
            logger.warning(f"[W{worker_id}] Lỗi tạo tài khoản ({email}): {e}")
            time.sleep(1.0)
        finally:
            if engine:
                try:
                    engine.close()
                except Exception:
                    pass


def main():
    logger.info("=" * 60)
    logger.info(f"🚀 KHỞI ĐỘNG HỆ THỐNG SONG SONG: TẠO {TARGET_NEW_ACCOUNTS} ACC + AUTO-SYNC OAUTH")
    logger.info("=" * 60)

    # 1. Kích hoạt luồng Đồng bộ chạy ngầm song song liên tục
    sync_thread = threading.Thread(target=background_sync_loop, daemon=True)
    sync_thread.start()

    # 2. Kích hoạt các luồng tạo tài khoản
    with ThreadPoolExecutor(max_workers=CREATION_WORKERS) as executor:
        futures = [executor.submit(create_one_worker, i + 1) for i in range(CREATION_WORKERS)]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                logger.error(f"Worker exception: {e}")

    logger.info("Đang đợi đồng bộ nốt các tài khoản cuối cùng...")
    time.sleep(15.0)
    stop_event.set()
    logger.info(f"🏁 HOÀN TẤT TOÀN BỘ TIẾN TRÌNH! Đã tạo thành công {created_success}/{TARGET_NEW_ACCOUNTS} tài khoản mới.")
    try:
        from core.exporter import save_oauth_router_accounts
        count = save_oauth_router_accounts("grok_router_accounts.json", json_path=DEFAULT_JSON_OUTPUT)
        logger.info(f"🎉 Đã xuất {count} tài khoản chuẩn Router ra 'grok_router_accounts.json'!")
    except Exception as e:
        logger.warning(f"Lỗi xuất router json: {e}")

if __name__ == "__main__":
    main()
