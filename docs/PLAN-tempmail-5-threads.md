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

## Global Constraints (binding — copy verbatim vào mọi brief/review)

- `TempMailRateLimitError` là subclass của `RuntimeError`.
- Khi HTTP 429: đọc header `Retry-After`; nếu không có, chờ 30s. Retry **chính
  request đó**, tối đa 3 lần, rồi raise `TempMailRateLimitError`.
- `_request()` **không bao giờ** retry khi bỏ proxy (không fallback no-proxy).
- `MailboxPool(proxy_mgr, count, spacing=12, max_per_ip=4)`.
- `prepare()` tạo mailbox tuần tự, cách nhau `spacing` giây, tối đa
  `max_per_ip` mailbox/IP rồi xoay proxy.
- Khi một luồng retry account attempt: **dùng lại đúng mailbox đã pre-create**,
  không tạo mailbox mới.
- `acquire()` là blocking, FIFO; `release()` trả mailbox về pool.
- Khi `total_count` > `max_per_ip` × số IP lấy được: log cảnh báo rõ ràng, tạo
  tối đa số mailbox thực hiện được, các luồng còn lại báo fail thay vì 429 spam.
- `stopped` flag hủy phần pre-create đang chờ (kiểm tra giữa mỗi mailbox).

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

## Kiểm thử tổng thể

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

---

# Task 1: Sửa `core/tempmail.py` — retry 429 không drop proxy + `TempMailRateLimitError`

## Yêu cầu

1. Thêm class `TempMailRateLimitError(RuntimeError)`.
2. Sửa `_request()`:
   - Bỏ `attempts = [True, False]`/fallback no-proxy. Chỉ dùng proxy nếu
     `self.proxies` tồn tại; không bao giờ retry mà bỏ proxy.
   - Khi `status_code == 429`: đọc header `Retry-After` (giây); nếu không có,
     chờ 30s. Retry **chính request đó**, tối đa 3 lần (kèm 1 lần đầu = 4 tổng),
     rồi raise `TempMailRateLimitError(f"Temp-Mail rate limited (HTTP 429: {resp.text[:200]})")`.
   - Lỗi mạng (exception khi request): giữ retry tối đa 2 lần như hiện tại nhưng
     **không bỏ proxy**.
3. `create_mailbox()`: để `TempMailRateLimitError` lan truyền (không bọc lại
   thành `ValueError`).
4. Test: `tests/test_tempmail.py` — mock `_request` HTTP layer (dùng monkeypatch
   module `requests` hoặc inject) để verify:
   - 429 → retry đúng 3 lần với proxy vẫn giữ nguyên → raise `TempMailRateLimitError`.
   - 429 có `Retry-After` → chờ đúng số giây đó.
   - 429 không có `Retry-After` → chờ 30s.
   - Lỗi mạng → retry 2 lần, proxy không bị drop.
   - Giới hạn: dùng `time.sleep` patch (monkeypatch `time.sleep`) để test nhanh.

## Ghi chú implementer

- File hiện tại: `core/tempmail.py` (189 dòng). Đọc trước khi sửa.
- Test file: `tests/test_tempmail.py` — chỉ có 1 test regex hiện tại, thêm test mới.
- Dùng `pytest -q tests/test_tempmail.py` để chạy.

# Task 2: Thêm `rotate_to_new_ip()` vào `core/proxyxoay.py`

## Yêu cầu

1. Thêm method `rotate_to_new_ip(timeout_sec: int = 30) -> Tuple[bool, Optional[str], Dict[str, Any]]`:
   - Lặp gọi `get_proxy(force_rotate=True, timeout_sec=...)`.
   - Gặp status 101/102 (cooldown) → đọc `wait_seconds` từ data → `time.sleep(wait_seconds)` rồi thử lại.
   - Gặp status 100 → trả `(True, proxy_url, data)`.
   - Lỗi liên tục / hết thời gian tổng (`timeout_sec` cho toàn bộ vòng lặp) →
     `(False, None, data_cuối)`.
   - Lưu ý: proxyxoay có thể trả lại đúng port/`proxy_url` cũ nhưng `ip` exit đã
     đổi — đó vẫn tính là "IP mới".
2. Test: `tests/test_proxyxoay.py` — mock `get_proxy` để verify:
   - Status 101 → sleep đúng `wait_seconds` → thử lại → status 100 → return proxy.
   - Nhiều lần cooldown → vẫn loop cho đến khi hết `timeout_sec`.
   - Hết `timeout_sec` → return `(False, None, ...)`.
   - `time.sleep` được patch để test nhanh.

## Ghi chú implementer

- File hiện tại: `core/proxyxoay.py` (173 dòng). `get_proxy` đã xử lý cache/reuse.
- Test file: `tests/test_proxyxoay.py` — có 2 test init, thêm test mới.
- Dùng `pytest -q tests/test_proxyxoay.py`.

# Task 3: Tạo `core/mailbox_pool.py` — module mới

## Yêu cầu

1. Tạo module `core/mailbox_pool.py` với:
   - `@dataclass MailboxEntry: email, token, proxy` (có thể thêm `used: bool = False`).
   - `class MailboxPool`:
     - `__init__(self, proxy_mgr, count: int, spacing: float = 12, max_per_ip: int = 4, stopped: Optional[Callable[[], bool]] = None)`.
       `stopped` là callable trả `True` để hủy pre-create.
     - `prepare() -> int`: pre-create tối đa `count` mailbox tuần tự:
       - Giữ `current_proxy` từ `proxy_mgr.get_proxy()` (nếu fail → log, dùng None = direct).
       - Đếm `made_on_current_ip`; khi đạt `max_per_ip` → `proxy_mgr.rotate_to_new_ip()`
         để lấy IP mới (nếu fail → chờ `spacing` rồi retry), reset bộ đếm.
       - Tạo mailbox: `TempMailClient(proxy=current_proxy).create_inbox()`.
       - Gặp `TempMailRateLimitError` → gọi `rotate_to_new_ip()` rồi retry chính
         request (không tạo mailbox mới ngay). Nếu rotate fail → chờ 30s retry.
       - Giữa mỗi mailbox: `time.sleep(spacing)`; kiểm tra `stopped()` giữa mỗi
         mailbox → nếu `True` → dừng, trả số đã tạo.
       - Lưu `MailboxEntry` vào queue/stack.
       - Trả số mailbox đã tạo thành công.
     - `acquire() -> Optional[MailboxEntry]`: blocking FIFO (dùng `queue.Queue`),
       trả `None` nếu pool rỗng và đã closed.
     - `release(entry: MailboxEntry)`: trả mailbox về pool để tái dùng.
   - Không import web/cli; chỉ import `threading`/`queue`/`time`/`logging`/
     `core.tempmail`.
2. Test: tạo `tests/test_mailbox_pool.py`:
   - Mock `TempMailClient.create_inbox` (monkeypatch class) để test không cần mạng:
     - `prepare()` tạo đúng `count` mailbox, mỗi lần cách `spacing` (patch `time.sleep`).
     - Sau `max_per_ip` mailbox → `rotate_to_new_ip` được gọi.
     - `acquire()` lấy đúng FIFO.
     - `release()` đưa mailbox về pool.
     - `stopped()` trả True sau 2 mailbox → `prepare()` dừng, trả 2.
     - `TempMailRateLimitError` → rotate proxy → retry thành công.
   - Patch `time.sleep` để test nhanh.

## Ghi chú implementer

- `proxy_mgr` là `ProxyXoayManager` (hoặc object mock có `get_proxy` + `rotate_to_new_ip`).
- Dùng `queue.Queue` cho FIFO + blocking acquire.
- `pytest -q tests/test_mailbox_pool.py`.

# Task 4: `web/server.py` — dùng MailboxPool, luồng acquire từ pool

## Yêu cầu

1. Trước khi bắn luồng (trong hàm xử lý tạo account):
   - Nếu dùng tempmail: tạo `pool = MailboxPool(proxy_mgr, total_count).prepare()`
     (chỉ pre-create khi `total_count > 0` và không bị `stopped`).
   - Log tiến độ: `"Đang tạo hòm thư Temp-Mail #n/total (serialized)..."`.
   - Nếu `pool.prepare() < total_count` → log cảnh báo số mailbox thiếu.
   - Khi chưa có `proxy_mgr` (không proxyxoay/tor): cho phép `proxy_mgr=None` —
     `MailboxPool` dùng proxy trực tiếp (current_proxy=None).
2. Trong `_create_single_account`:
   - Thay `TempMailClient(proxy=thread_proxy)` + `create_inbox()` bằng
     `mailbox = pool.acquire()`; nếu `None` → fail luồng với thông báo.
   - `tempmail_client = TempMailClient(proxy=mailbox.proxy); tempmail_client.set_token(mailbox.token)`;
     `email = mailbox.email`.
   - **Khi retry attempt: dùng lại chính `tempmail_client`/mailbox đã acquire**,
     không tạo mailbox mới, không acquire lại.
   - Sau khi hết attempt (fail) → `pool.release(mailbox)` nếu có.
3. Import: thêm `from core.mailbox_pool import MailboxPool`.
4. Test: `tests/test_web.py` — verify import OK, app vẫn start được, các endpoint
   hiện có vẫn pass. (Không cần test luồng đầy đủ — phần pool đã test ở Task 3.)

## Ghi chú implementer

- File `web/server.py` (536 dòng). Đọc kỹ `_create_single_account` (khoảng dòng
  339–450) và phần preflight proxy (dòng ~280–330).
- Không phá vỡ flow tor/direct hiện có.
- `pytest -q tests/test_web.py`.

# Task 5: `cli.py` — dùng MailboxPool cho chế độ multi-thread + tempmail

## Yêu cầu

1. Ở chế độ multi-thread (`--threads > 1` và `--count > 1`) + `--tempmail`:
   - Pre-create `count` mailbox qua `MailboxPool` trước khi bắn ThreadPoolExecutor.
   - `worker(idx)` nhận mailbox từ pool thay vì tạo mới.
   - `create_single_account` thêm tham số `mailbox: Optional[MailboxEntry] = None`:
     - Nếu `mailbox` được truyền → dùng nó (set_token, email = mailbox.email).
     - Nếu `use_tempmail` và không có mailbox → tạo qua `MailboxPool(..., count=1)`.
2. Chế độ đơn luồng giữ nguyên hành vi, nhưng đi qua `MailboxPool(count=1)` cho
   nhất quán (vẫn được hưởng logic retry 429 mới).
3. Import: thêm `from core.mailbox_pool import MailboxPool, MailboxEntry`.
4. Test: `tests/test_cli.py` — chỉ verify import/help OK (CLI hiện có).

## Ghi chú implementer

- File `cli.py` (292 dòng). Đọc kỹ `create_single_account` (dòng 43–142) và
  `main()` phần multi-thread (dòng 234–252).
- `pytest -q tests/test_cli.py`.

## Các file thay đổi (tổng hợp)

| File | Thay đổi |
|---|---|
| `core/tempmail.py` | Task 1: retry 429 không drop proxy, `TempMailRateLimitError` |
| `core/proxyxoay.py` | Task 2: `rotate_to_new_ip()` |
| `core/mailbox_pool.py` | Task 3 (mới): serialize + giới hạn mailbox/IP |
| `web/server.py` | Task 4: pre-create qua pool, luồng acquire từ pool |
| `cli.py` | Task 5: pool cho multi-thread + tempmail |
| `tests/test_tempmail.py` | Task 1 |
| `tests/test_proxyxoay.py` | Task 2 |
| `tests/test_mailbox_pool.py` | Task 3 (mới) |
| `tests/test_web.py` | Task 4 |
| `tests/test_cli.py` | Task 5 |
