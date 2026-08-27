import json
import time
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from core.engine import StealthEngine
from core.oauth import OAuthTokenManager
from core.exporter import load_accounts, save_account, AccountRecord
from core.proxyxoay import ProxyXoayManager
from config import DEFAULT_JSON_OUTPUT, DEFAULT_TXT_OUTPUT

def main():
    accounts = load_accounts(DEFAULT_JSON_OUTPUT)
    oauth_mgr = OAuthTokenManager()
    
    pending = [
        acc for acc in accounts 
        if not (acc.get("access_token") and acc.get("access_token").startswith("eyJ"))
        and acc.get("sso_cookie")
    ]
    
    total_pending = len(pending)
    print(f"=== BẮT ĐẦU ĐỒNG BỘ {total_pending} TÀI KHOẢN CHƯA CÓ OAUTH ===")
    if total_pending == 0:
        print("Tất cả tài khoản đã có OAuth 2.0 CLI Token!")
        return

    px_mgr = ProxyXoayManager("HVnSXrEVXRSrUYBkwYzuId")
    ok, p_url, _ = px_mgr.get_proxy()
    proxy = p_url if ok else None
    print(f"Using Proxy: {proxy or 'Direct'}")

    success_count = 0
    failed_count = 0
    lock = threading.Lock()

    def sync_account(idx_and_acc):
        nonlocal success_count, failed_count
        idx, acc = idx_and_acc
        email = acc.get("email")
        sso = acc.get("sso_cookie")
        sso_rw = acc.get("sso_rw_cookie", sso)
        
        print(f"[{idx+1}/{total_pending}] Đang xử lý: {email}...")
        
        engine = StealthEngine(headless=True, proxy=proxy)
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
            tokens = oauth_mgr.mint_tokens_for_page(page, proxy=proxy)
            
            from core.healthcheck import verify_grok_cli_health
            is_healthy, h_code, h_msg = verify_grok_cli_health(tokens["access_token"], proxy=proxy)
            
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
                refresh_token=tokens["refresh_token"],
                status="active" if is_healthy else "created",
                extra={"health_verified": is_healthy, "health_status": h_msg}
            )
            save_account(rec, DEFAULT_JSON_OUTPUT, DEFAULT_TXT_OUTPUT)
            with lock:
                success_count += 1
                h_badge = "100% SỐNG (HTTP 200)" if is_healthy else f"Chưa đạt ping: {h_msg}"
                print(f"✔ [{success_count + failed_count}/{total_pending}] THÀNH CÔNG: {email} -> OAuth cấp OK [{h_badge}]")
        except Exception as e:
            with lock:
                failed_count += 1
                print(f"✘ [{success_count + failed_count}/{total_pending}] THẤT BẠI: {email} -> {e}")
        finally:
            engine.close()

    items = list(enumerate(pending))
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(sync_account, items))

    from core.exporter import save_oauth_router_accounts
    exported = save_oauth_router_accounts("grok_router_accounts.json", json_path=DEFAULT_JSON_OUTPUT)
    print(f"\n=== HOÀN TẤT ĐỒNG BỘ: Thành công {success_count}/{total_pending} (Thất bại: {failed_count}) ===")
    print(f"🎉 Đã xuất {exported} tài khoản theo chuẩn Router ra file 'grok_router_accounts.json'!")

if __name__ == "__main__":
    main()
