# Grok & x.ai Automated Account Creator (CLI + Web UI)

Công cụ tạo tài khoản Grok / x.ai tự động với đầy đủ **Giao diện Web UI trực quan** và **CLI dòng lệnh**, tích hợp **Scrapling & Camoufox** để tự động bypass Cloudflare Turnstile & anti-abuse checks, hỗ trợ Proxy và xuất toàn bộ Cookies / SSO Session Tokens.

---

## 🌟 Cấu hình mặc định & Công thức đặt tên
- **Công thức đặt tên ngẫu nhiên:** `User_[2 Số][2 Ký tự]` (vd: `User_01AI`, `User_48QK`, `User_92ZX`)
- **Password:** `taikhoanAI123`
- **Vòng lặp (Batch mode):** Tự động tạo liên tiếp nhiều tài khoản theo số lượng tùy chỉnh trên giao diện Web UI hoặc CLI.

---

## 🚀 Cách mở Giao diện Web UI

Mở terminal và khởi chạy server Web UI:
```bash
cd /home/chinhan/xai-grok-account-creator
./venv/bin/python web_app.py --port 7860
```
👉 Mở trình duyệt và truy cập: **[http://127.0.0.1:7860](http://127.0.0.1:7860)**

### Các tính năng trên giao diện Web:
1. **Tích hợp Tor Proxy (Fake IP & Tự động xoay IP)**: Tự động định tuyến toàn bộ lưu lượng duyệt web & TempMail qua mạng Tor SOCKS5 (`127.0.0.1:9050`), tự động gửi lệnh `SIGNAL NEWNYM` qua Control Port (`9051`) để đổi sang một Exit Node IP tại quốc gia khác cho mỗi tài khoản trong vòng lặp!
2. **Thiết lập Vòng lặp (Batch Count)**: Nhập số lượng tài khoản (vd: 5, 10, 20), hệ thống sẽ tự động chạy liên tục từng tài khoản.
3. **Auto Random Name (`User_XXYY`)**: Tự động sinh tên theo chuẩn `User_01AI` cho mỗi tài khoản trong vòng lặp.
4. **Nút Dừng tiến trình (Stop Button)**: Cho phép dừng vòng lặp bất kỳ lúc nào mà không làm mất các tài khoản đã tạo thành công trước đó.
5. **Thanh tiến độ (Progress Bar)**: Hiển thị tiến trình trực tiếp theo thời gian thực (`Đang xử lý: 2/5`).
6. **Live Execution Logs**: Xem trực tiếp log từng bước của từng tài khoản trên giao diện terminal ảo.
7. **Quản lý & Xuất tài khoản**: Bảng danh sách tài khoản đã tạo kèm nút **1-Click Copy** (Copy Email:Pass:Token:UserID, Copy Cookie SSO), nút **Xuất TXT** và **Xuất JSON**.
8. **Cấu hình Proxy Tùy chỉnh**: Hỗ trợ nhập proxy HTTP / SOCKS5 riêng nếu không dùng Tor.

---

## 💻 Cách sử dụng qua CLI dòng lệnh

```bash
cd /home/chinhan/xai-grok-account-creator
source venv/bin/activate

# 1. Tạo tự động qua mạng Tor Proxy (Tự động đổi IP mới mỗi tài khoản)
python3 cli.py --tempmail --tor --count 5

# 2. Tạo tự động 1 tài khoản (Tên random dạng User_01AI)
python3 cli.py --tempmail

# 3. Tạo tự động vòng lặp nhiều tài khoản (vd: 5 tài khoản)
python3 cli.py --tempmail --count 5

# 4. Tạo với Email & Tùy chỉnh tên riêng
python3 cli.py --email "email_cua_ban@domain.com" --first-name "User_01AI" --last-name "AI"

# 5. Tạo với Proxy tùy chỉnh
python3 cli.py --tempmail --proxy "http://user:pass@host:port" --count 3

# 6. Xem danh sách tài khoản & cookies đã tạo
python3 cli.py --list
```

---

## 📁 Định dạng kết quả xuất ra

- **File `accounts.json`**:
  ```json
  [
    {
      "email": "user@neplis.com",
      "password": "taikhoanAI123",
      "first_name": "taikhoan_01",
      "last_name": "AI",
      "user_id": "5eb432f6-d2bc-448c-a449-31ee2cc1c6c4",
      "session_id": "b6cd1632-45b6-4d73-8de1-8c860e667bdd",
      "sso_cookie": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
      "status": "active"
    }
  ]
  ```

- **File `accounts.txt`**:
  ```text
  user@neplis.com:taikhoanAI123:eyJ0eXAiOiJKV1Qi...:5eb432f6-d2bc-448c-a449-31ee2cc1c6c4
  ```
