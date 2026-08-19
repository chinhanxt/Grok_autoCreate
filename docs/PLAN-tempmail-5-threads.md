# PLAN: Chạy 5 luồng không dính 429 Temp-Mail

## Vấn đề

Khi chạy 5 luồng tạo tài khoản song song, hệ thống bị temp-mail.org trả
HTTP 429 `TooManyRequestsException` vì:

1. Mỗi luồng + mỗi lần retry đều gọi `POST /mailbox` mới, tạo mailbox đồng
   thời từ **cùng 1 IP duy nhất** (proxyxoay chỉ cấp 1 IP/tại một thời điểm —
   đã kiểm chứng: 5 kết nối song song ra cùng exit IP).
2. Temp-Mail giới hạn ~**4 mailbox/IP** trước khi 429 (đã kiểm chứng bằng test
   thực tế, mỗi mailbox cách 12s vẫn 429 ở cái thứ 5).
3. IP bị temp-mail flag sau vài lần dùng → bị **403 Cloudflare** (kể cả IP thật).
4. Retry logic hiện tại: bỏ proxy retry direct (leak IP), chỉ chờ 1s rồi raise →
   outer retry tạo mailbox mới → đổ thêm dầu vào lửa.

## Mục tiêu

- 5 luồng chạy đồng thời, mỗi luồng tạo thành công 1 tài khoản x.ai.
- Không tạo mailbox đồng thời từ cùng 1 IP.
- Không spam `POST /mailbox` khi gặp 429.
- Không leak IP thật (bỏ fallback no-proxy).

## Thiết kế

### Nguyên tắc cốt lõi

**"1 IP = tối đa 4 mailbox, serialize khâu tạo mailbox, xoay IP giữa chừng".**

Tách khâu tạo mailbox (giới hạn tốc độ) khỏi khâu browser (chạy song song).
Pre-create N mailbox tuần tự trước khi bắn luồng, mỗi luồng nhận sẵn
mailbox + token → browser chạy song song không tranh chấp temp-mail.

### Flow mới

```
[Start]
  ├─ Lấy 1 proxy từ ProxyXoay (IP A)
  ├─ FOR n = 1..5:
  │    └─ Global lock → tạo mailbox #n (POST /mailbox)
  │         ├─ OK → lưu (mailbox, token, proxy) vào pool
  │         ├─ 429 → xoay proxy (chờ cooldown) → retry chính request đó
  │         └─ đếm số mailbox/IP; khi chạm 4 → xoay proxy trước khi tạo tiếp
  │         (mỗi mailbox cách nhau ~12s)
  ├─ Bắn 5 thread, thread #i nhận mailbox #i + token + proxy đã gán
  │    ├─ start_signup(email)
  │    ├─ fetch_otp_code(timeout=120, page)  ← dùng token đã pre-create
  │    └─ submit_otp + complete_registration
  └─ [Done]
```

## Các thay đổi

### 1. `core/tempmail.py` — sửa retry 429 + bỏ fallback no-proxy

- `_request()`:
  - Bỏ `attempts = [True, False]` (bỏ retry không proxy → không leak IP).
  - Khi `status_code == 429`: đọc header `Retry-After` (nếu có) hoặc chờ
    30–60s rồi retry **chính request đó**, tối đa 3 lần, rồi mới raise
    `TempMailRateLimitError` (subclass của RuntimeError).
- Thêm class `TempMailRateLimitError(RuntimeError)` để caller phân biệt
  429 với lỗi khác.
- `create_mailbox()`: nếu lỗi 429 → raise `TempMailRateLimitError`.

### 2. `core/mailbox_pool.py` — module mới

Quản lý pool mailbox + serialize việc tạo mailbox:

- `MailboxPool(proxy_mgr, count, spacing=12, max_per_ip=4)`:
  - `global_lock = threading.Lock()` — chỉ 1 luồng tạo mailbox tại một thời điểm.
  - `prepare()`: pre-create `count` mailbox tuần tự:
    - Tạo mailbox qua `TempMailClient(proxy=current_proxy)`.
    - Đếm số mailbox/IP hiện tại.
    - Chạm `max_per_ip` → gọi `proxy_mgr.get_proxy(force_rotate=True)`
      (xử lý cooldown 101/102: chờ `wait_seconds` rồi thử lại) → dùng IP mới.
    - Gặp 429 → chờ cooldown/xoay proxy rồi retry (không tạo mailbox mới vô tội vạ).
    - Lưu vào danh sách `MailboxEntry(email, token, proxy)`.
  - `acquire()`: lấy 1 mailbox từ pool (blocking, FIFO) cho 1 luồng.
  - `return_()` / `release()`: trả mailbox khi luồng xong.

### 3. `web/server.py` — dùng MailboxPool thay vì tạo mailbox trong luồng

- Trước vòng `for attempt` / trước ThreadPoolExecutor:
  - Gọi `pool = MailboxPool(proxyxoay_mgr, total_count).prepare()`.
  - Log tiến độ: `"Đang tạo hòm thư Temp-Mail #n/total (serialized)..."`.
- Trong `_create_single_account`:
  - `mailbox = pool.acquire()` thay cho `TempMailClient(...).create_inbox()`.
  - Tạo `TempMailClient(proxy=mailbox.proxy)` + `set_token(mailbox.token)`.
  - `email = mailbox.email`.
  - Khi retry attempt: **không tạo mailbox mới**, dùng lại chính mailbox đó
    (vì pre-create đã thỏa giới hạn temp-mail).
  - Nếu OTP fetch fail và hết attempt → `pool.release(mailbox)`.

### 4. `cli.py` — tương tự web/server.py

- Ở chế độ multi-thread (`--threads 5 --count 5 --tempmail`):
  - Pre-create mailbox qua `MailboxPool` trước khi bắn ThreadPoolExecutor.
  - `create_single_account` nhận `mailbox` từ pool thay vì tự tạo.
- Chế độ đơn luồng giữ nguyên, nhưng dùng `TempMailClient` mới sửa
  (vẫn pre-create 1 mailbox qua pool cho nhất quán).

### 5. `core/proxyxoay.py` — hỗ trợ xoay đúng cách

- Thêm helper `rotate_to_new_ip(timeout_sec)`:
  - Lặp gọi `get_proxy(force_rotate=True)`.
  - Gặp status 101/102 (cooldown) → đọc `wait_seconds` → `time.sleep` → thử lại.
  - Trả về (proxy_url, ip) khi status == 100.
- Lưu ý: proxyxoay có thể trả lại đúng proxy/port cũ nhưng IP exit đã đổi —
  đây vẫn tính là "IP mới" vì temp-mail giới hạn theo exit IP.

## Số liệu tham chiếu (đã test)

- 1 IP: 4 mailbox OK (cách 12s) → cái thứ 5 429.
- Xoay proxyxoay: cooldown 37–58s giữa các lần, port giữ nguyên, exit IP đổi.
- 5 luồng cần 5 mailbox → cần ≥ 2 IP (4 + 1) → thời gian prep ~ 4×12s + 40s + 12s ≈ 100s.

## Xử lý biên

- `total_count` > `max_per_ip` × số IP lấy được → log cảnh báo rõ ràng, tạo tối
  đa số mailbox thực hiện được, các luồng còn lại báo fail thay vì 429 spam.
- Nếu proxyxoay chết/không xoay được → fallback chờ cooldown temp-mail rồi retry.
- `stopped` flag: hủy phần pre-create đang chờ (kiểm tra giữa mỗi mailbox).
- Mailbox bị 403/expired → đánh dấu, xoay IP, tạo mailbox thay thế cho luồng đó.

## Kiểm thử

- `tests/test_mailbox_pool.py`: pool pre-create N mailbox tuần tự, lock đảm bảo
  không song song, acquire/release đúng FIFO.
- `tests/test_tempmail.py`: `_request` retry 429 không drop proxy, raise
  `TempMailRateLimitError` sau 3 lần.
- `tests/test_proxyxoay.py`: `rotate_to_new_ip` xử lý cooldown đúng.
- Chạy thử thật: `--threads 5 --count 5 --tempmail --proxyxoay` → không còn
  429 liên tục, 5 tài khoản thành công.

## Out of scope

- Thêm provider dự phòng (mail.tm, 1secmail) — để sau, nếu vẫn không đủ IP.
- Tăng hạn temp-mail (thay gói proxyxoay nhiều IP).

## Các file thay đổi

| File | Thay đổi |
|---|---|
| `core/tempmail.py` | Sửa `_request`: bỏ fallback no-proxy, retry 429 có backoff, thêm `TempMailRateLimitError` |
| `core/mailbox_pool.py` | **Mới**: serialize + giới hạn mailbox/IP |
| `core/proxyxoay.py` | Thêm `rotate_to_new_ip()` |
| `web/server.py` | Pre-create mailbox qua pool, luồng acquire từ pool |
| `cli.py` | Tương tự, dùng pool cho chế độ multi-thread |
| `tests/test_mailbox_pool.py` | **Mới** |
| `tests/test_tempmail.py` | Cập nhật |
| `tests/test_proxyxoay.py` | Cập nhật |
