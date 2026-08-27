import time
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from core.engine import StealthEngine
from core.auth import AccountCreator
from core.tempmail import TempMailClient
from core.exporter import save_account, AccountRecord
from core.proxyxoay import ProxyXoayManager
from config import generate_random_name

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("batch_creator_100")

PROXYXOAY_KEY = "HVnSXrEVXRSrUYBkwYzuId"
TARGET_ACCOUNTS = 100
CONCURRENT_WORKERS = 20  # High-speed multi-threaded workers
JSON_PATH = "/home/chinhan/xai-grok-account-creator/accounts.json"
TXT_PATH = "/home/chinhan/xai-grok-account-creator/accounts.txt"

completed_count = 0
attempt_counter = 0
lock = threading.Lock()
tempmail_lock = threading.Lock()

def create_one_account(worker_id: int):
    global completed_count, attempt_counter
    
    while True:
        with lock:
            if completed_count >= TARGET_ACCOUNTS:
                break
            attempt_counter += 1
            cur_attempt = attempt_counter

        first_name, last_name = generate_random_name()
        password = "taikhoanAI123"

        # 1. Get rotating residential proxy from ProxyXoay
        px_mgr = ProxyXoayManager(api_key=PROXYXOAY_KEY)
        ok, p_url, _ = px_mgr.get_proxy()
        xai_proxy = p_url if ok else None

        # 2. Get TempMail inbox with thread-safe staggering to prevent 429
        tm = None
        email = None
        for tm_try in range(5):
            try:
                with tempmail_lock:
                    tm = TempMailClient(max_retry_delay=3.0)
                    email, token = tm.create_inbox()
                    time.sleep(0.3)  # clean delay between mailbox requests
                break
            except Exception as e:
                logger.warning(f"[W{worker_id}] TempMail try {tm_try+1} error: {e}, backing off...")
                time.sleep(2.0)

        if not email or not tm:
            logger.error(f"[W{worker_id}] Không thể tạo hòm thư TempMail sau 5 lần thử. Bỏ qua.")
            time.sleep(2.0)
            continue

        # 3. Create account with stealth browser
        engine = None
        try:
            logger.info(f"[W{worker_id}|#{cur_attempt}] Đang tạo tài khoản cho {email} ({first_name} {last_name}) qua {xai_proxy or 'Direct'}...")
            engine = StealthEngine(headless=True, proxy=xai_proxy)
            creator = AccountCreator(engine=engine)

            creator.start_signup(email=email)
            logger.info(f"[W{worker_id}|#{cur_attempt}] Đang chờ OTP cho {email}...")

            otp = tm.fetch_otp_code(timeout_sec=60, page=creator.page)
            if not otp:
                raise RuntimeError(f"OTP timeout for {email}")

            logger.info(f"[W{worker_id}|#{cur_attempt}] Nhận được OTP: {otp}. Đang xác thực...")
            creator.submit_otp(code=otp)

            record = creator.complete_registration(
                first_name=first_name,
                last_name=last_name,
                password=password
            )

            has_oauth = bool(record.access_token and record.access_token.startswith("eyJ"))
            if not has_oauth:
                try:
                    from core.oauth import OAuthTokenManager
                    oauth_mgr = OAuthTokenManager()
                    toks = oauth_mgr.mint_tokens_for_page(creator.page, proxy=xai_proxy)
                    record.access_token = toks.get("access_token", "")
                    record.refresh_token = toks.get("refresh_token", "")
                    has_oauth = bool(record.access_token and record.access_token.startswith("eyJ"))
                except Exception as e:
                    logger.warning(f"[W{worker_id}|#{cur_attempt}] Cấp lại OAuth notice: {e}")

            save_account(record, json_path=JSON_PATH, txt_path=TXT_PATH)
            
            with lock:
                completed_count += 1
                curr = completed_count
                logger.info(f"🎉 [{curr}/{TARGET_ACCOUNTS}] THÀNH CÔNG: {email} | User ID: {record.user_id} | OAuth: {has_oauth}")
            
        except Exception as e:
            logger.warning(f"[W{worker_id}|#{cur_attempt}] Lỗi tạo tài khoản ({email}): {e}")
            time.sleep(1.0)
        finally:
            if engine:
                try:
                    engine.close()
                except Exception:
                    pass

def main():
    logger.info(f"🚀 BẮT ĐẦU TIẾN TRÌNH TẠO {TARGET_ACCOUNTS} TÀI KHOẢN VỚI {CONCURRENT_WORKERS} LUỒNG...")
    
    with ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
        futures = []
        for w_id in range(CONCURRENT_WORKERS):
            futures.append(executor.submit(create_one_account, w_id + 1))
            time.sleep(0.8)
        
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                logger.error(f"Worker exception: {e}")

    logger.info(f"🏁 ĐÃ HOÀN TẤT BATCH! Tổng tài khoản thành công: {completed_count}/{TARGET_ACCOUNTS}")
    try:
        from core.exporter import save_oauth_router_accounts
        count = save_oauth_router_accounts("grok_router_accounts.json", json_path=JSON_PATH)
        logger.info(f"🎉 Đã xuất {count} tài khoản chuẩn Router ra 'grok_router_accounts.json'!")
    except Exception as e:
        logger.warning(f"Lỗi xuất file router: {e}")

if __name__ == "__main__":
    main()
