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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("batch_creator")

PROXYXOAY_KEY = "HVnSXrEVXRSrUYBkwYzuId"
TARGET_ACCOUNTS = 20
CONCURRENT_WORKERS = 20
JSON_PATH = "/home/chinhan/xai-grok-account-creator/accounts.json"
TXT_PATH = "/home/chinhan/xai-grok-account-creator/accounts.txt"

completed_count = 0
lock = threading.Lock()

def create_one_account(index: int):
    global completed_count
    first_name, last_name = generate_random_name()
    password = "taikhoanAI123"

    for attempt in range(3):
        # 1. Get rotating proxy
        px_mgr = ProxyXoayManager(api_key=PROXYXOAY_KEY)
        ok, p_url, _ = px_mgr.get_proxy()
        xai_proxy = p_url if ok else None

        # 2. Get TempMail inbox
        try:
            tm = TempMailClient(max_retry_delay=3.0)
            email, token = tm.create_inbox()
        except Exception as e:
            logger.warning(f"[{index}] TempMail error: {e}, retrying...")
            time.sleep(1.0)
            continue

        # 3. Create account with Camoufox
        engine = None
        try:
            logger.info(f"[{index}] Starting account creation for {email} ({first_name} {last_name}) via {xai_proxy or 'Direct'}...")
            engine = StealthEngine(headless=True, proxy=xai_proxy)
            creator = AccountCreator(engine=engine)

            creator.start_signup(email=email)
            logger.info(f"[{index}] Waiting for OTP for {email}...")

            otp = tm.fetch_otp_code(timeout_sec=60, page=creator.page)
            if not otp:
                raise RuntimeError(f"OTP timeout for {email}")

            logger.info(f"[{index}] Got OTP: {otp}. Submitting...")
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
                    logger.warning(f"[{index}] Manual OAuth mint notice: {e}")

            save_account(record, json_path=JSON_PATH, txt_path=TXT_PATH)
            
            with lock:
                completed_count += 1
                curr = completed_count
                logger.info(f"🎉 [{curr}/{TARGET_ACCOUNTS}] THÀNH CÔNG: {email} | User ID: {record.user_id} | OAuth: {has_oauth}")
            return True

        except Exception as e:
            logger.warning(f"[{index}] Attempt {attempt+1} failed: {e}")
            time.sleep(1.0)
        finally:
            if engine:
                try:
                    engine.close()
                except Exception:
                    pass

    return False

def main():
    logger.info(f"🚀 Bắt đầu tạo {TARGET_ACCOUNTS} tài khoản OAuth với {CONCURRENT_WORKERS} luồng...")
    
    with ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
        futures = []
        for i in range(TARGET_ACCOUNTS):
            futures.append(executor.submit(create_one_account, i + 1))
        
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                logger.error(f"Worker exception: {e}")

    logger.info(f"🏁 ĐÃ HOÀN TẤT BATCH! Tổng tài khoản thành công: {completed_count}/{TARGET_ACCOUNTS}")

if __name__ == "__main__":
    main()
