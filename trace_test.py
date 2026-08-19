import time
import os
import json
from camoufox.sync_api import Camoufox
from core.tempmail import TempMailClient

os.makedirs("/home/chinhan/xai-grok-account-creator/debug_run", exist_ok=True)

print("=== 1. Creating TempMail ===")
temp_client = TempMailClient()
email, _ = temp_client.create_inbox()
print(f"Email created: {email}")

print("=== 2. Launching Camoufox ===")
with Camoufox(headless=True) as browser:
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    
    # Capture all network requests/responses
    def on_response(response):
        url = response.url
        if "auth_mgmt" in url or "accounts.x.ai" in url or "grok.com" in url:
            print(f"[NET RESP] {response.status} {url}")
            if "auth_mgmt" in url:
                try:
                    headers = response.headers
                    print(f"   gRPC-web status / headers: {headers.get('grpc-status')}, {headers.get('grpc-message')}")
                except Exception:
                    pass
    page.on("response", on_response)
    page.on("console", lambda msg: print(f"[CONSOLE] {msg.type}: {msg.text}"))

    print("=== 3. Navigating to accounts.x.ai ===")
    page.goto("https://accounts.x.ai/sign-up?redirect=grok-com&return_to=%2F", wait_until="domcontentloaded")
    time.sleep(3)
    page.screenshot(path="/home/chinhan/xai-grok-account-creator/debug_run/01_loaded.png")

    # Clean OneTrust
    page.evaluate('''() => {
        const b = document.getElementById("onetrust-banner-sdk");
        if (b) b.remove();
        const f = document.querySelector(".onetrust-pc-dark-filter");
        if (f) f.remove();
    }''')

    # Click 'Sign up with email'
    try:
        btn = page.wait_for_selector('button:has-text("Sign up with email"), a:has-text("Sign up with email")', timeout=8000)
        if btn:
            btn.click()
            time.sleep(1)
    except Exception as e:
        print("Sign up with email not clicked:", e)

    page.screenshot(path="/home/chinhan/xai-grok-account-creator/debug_run/02_email_form.png")

    # Fill email
    email_inp = page.wait_for_selector('input[data-testid="email"], input[name="email"]', timeout=10000)
    email_inp.click()
    email_inp.fill("")
    email_inp.type(email, delay=30)
    time.sleep(0.5)

    submit_btn = page.wait_for_selector('button[type="submit"], button:has-text("Sign up")', timeout=5000)
    submit_btn.click()
    print("Submitted email, waiting for OTP screen...")
    time.sleep(4)
    page.screenshot(path="/home/chinhan/xai-grok-account-creator/debug_run/03_otp_screen.png")

    # Fetch OTP
    print("=== 4. Fetching OTP from TempMail ===")
    otp_code = temp_client.fetch_otp_code(timeout_sec=90)
    print(f"OTP Code received: {otp_code}")

    if not otp_code:
        print("Failed to get OTP! Exiting.")
        exit(1)

    # Submit OTP
    print("=== 5. Submitting OTP into form ===")
    otp_input = page.locator('input[data-input-otp="true"], input[name="code"]').first
    otp_input.click()
    otp_input.type(otp_code, delay=50)
    time.sleep(1)

    confirm_btn = page.locator('button:has-text("Confirm email"), button:has-text("Verify"), button[type="submit"]').first
    if confirm_btn.count() > 0 and confirm_btn.is_visible():
        confirm_btn.click()

    print("Waiting 5s after OTP submission...")
    time.sleep(5)
    page.screenshot(path="/home/chinhan/xai-grok-account-creator/debug_run/04_after_otp.png")
    print("Page URL after OTP:", page.url)
    print("Page Body Text after OTP:")
    print(page.locator("body").inner_text()[:600])

    print("=== 6. Checking Profile Inputs ===")
    inputs = page.locator("input").all()
    for idx, inp in enumerate(inputs):
        try:
            print(f"Input #{idx}: visible={inp.is_visible()}, outerHTML={inp.evaluate('el => el.outerHTML')}")
        except Exception as e:
            print(f"Input #{idx} error: {e}")

    buttons = page.locator("button").all()
    for idx, b in enumerate(buttons):
        try:
            print(f"Button #{idx}: visible={b.is_visible()}, text={repr(b.inner_text())}, outerHTML={b.evaluate('el => el.outerHTML[:120]')}")
        except Exception as e:
            print(f"Button #{idx} error: {e}")

    # Fill profile
    print("=== 7. Filling Profile ===")
    fn_loc = page.locator('input[data-testid="givenName"], input[name="givenName"], input[autocomplete="given-name"]')
    if fn_loc.count() > 0 and fn_loc.first.is_visible():
        print("Filling givenName...")
        fn_loc.first.click()
        fn_loc.first.type("taikhoan_01", delay=30)

    ln_loc = page.locator('input[data-testid="familyName"], input[name="familyName"], input[autocomplete="family-name"]')
    if ln_loc.count() > 0 and ln_loc.first.is_visible():
        print("Filling familyName...")
        ln_loc.first.click()
        ln_loc.first.type("AI", delay=30)

    pwd_loc = page.locator('input[data-testid="password"], input[name="password"], input[type="password"]')
    if pwd_loc.count() > 0 and pwd_loc.first.is_visible():
        print("Filling password...")
        pwd_loc.first.click()
        pwd_loc.first.type("taikhoanAI123", delay=30)

    page.screenshot(path="/home/chinhan/xai-grok-account-creator/debug_run/05_profile_filled.png")

    time.sleep(3)
    # Check submit button
    sub = page.locator('button[type="submit"]').first
    print("Submit button disabled?", sub.evaluate("el => el.disabled"))
    print("Clicking submit button...")
    sub.click()

    for w in range(15):
        time.sleep(1)
        cookies = page.context.cookies()
        c_names = [c['name'] for c in cookies]
        print(f"Wait {w}s: URL={page.url}, Cookies={c_names}")
        if "sso" in c_names or "x-userid" in c_names:
            print("FOUND SSO COOKIE / USERID!")
            break

    page.screenshot(path="/home/chinhan/xai-grok-account-creator/debug_run/06_final.png")
