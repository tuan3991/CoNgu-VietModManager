# LỘ TRÌNH PHÁT TRIỂN & TỐI ƯU KIẾN TRÚC: CỔ NGỮ (VietModHub Pro)

Tài liệu này tổng hợp đánh giá kỹ thuật dựa trên mã nguồn khởi chạy (`app.py`), chỉ ra các điểm nghẽn tiềm ẩn trong kiến trúc Desktop lai (PyWebView + Bottle Server + Win32 API) và thiết lập lộ trình phát triển theo từng giai đoạn kèm danh sách công việc (Actionable Checklist).

---

## 1. Đánh giá Kiến trúc Hiện tại (Điểm sáng Kỹ thuật)

Kiến trúc hiện tại của **CỔ NGỮ** đã giải quyết rất tốt nhiều bài toán khó của ứng dụng Python Desktop trên nền tảng Windows:

* **Tối ưu mạng & Bảo toàn Proxy/VPN:** Sử dụng `--proxy-bypass-list=127.0.0.1;localhost;[::1]` thay vì `--no-proxy-server` hoặc `<-loopback>`. Cách tiếp cận này giúp luồng giao tiếp nội bộ (IPC) luôn đi thẳng với độ trễ bằng $0\text{ ms}$, đồng thời giữ nguyên cấu hình VPN/WARP của người dùng khi tải dữ liệu từ Steam CDN, GitHub hoặc Google Drive.
* **An toàn Đa luồng Win32 & Chống treo UI:**
  * Sử dụng `PostMessageW` (bất đồng bộ) thay vì `SendMessageW` trong `apply_titlebar_icon` để tránh khóa chéo (deadlock) với message pump của WebView2.
  * Giữ tham chiếu toàn cục `_TITLEBAR_ICON_REF` để ngăn Garbage Collector của Python/.NET thu hồi biểu tượng đang gắn trên thanh tiêu đề.
  * Đặt cờ `window._serializable = False` để ngăn PyWebView duyệt đệ quy đối tượng WinForms `window.native`, tránh lỗi treo ứng dụng lúc khởi tạo cầu nối JS API.
* **Single-Instance & Đánh thức Tức thì:** Kết hợp Mutex `Local\CoNguVietModHubSingleInstance` và Auto-Reset Named Event `Local\CoNguVietModHubWakeupEvent` giúp đánh thức cửa sổ đang ẩn dưới khay hệ thống ngay lập tức mà không phụ thuộc vào cổng mạng hay Token xác thực.
* **Cơ chế Tự phục hồi Đa tầng (Resilience):**
  * Có Watchdog tự động nạp lại trang tối đa $3$ lần nếu WebView2 gặp lỗi màn hình đen lúc khởi chạy.
  * Tự động chuyển sang chế độ **Fallback Browser** (Edge/Chrome App Mode) nếu máy người dùng hỏng WebView2 Runtime, đi kèm cơ chế `run_fallback_browser_watchdog` kiểm tra nhịp tim (Heartbeat) mỗi $2\text{ giây}$ để duy trì triết lý *"Tắt là tắt hẳn"* (Zero-Leak Clean Exit).
* **Tối ưu Tài nguyên (Game Booster) & Phím tắt Thông minh:**
  * Tự động thu nhỏ xuống System Tray và gọi `boost_memory()` (Trim Working Set) để giảm mức tiêu thụ RAM từ $\sim 200\text{ MB}$ xuống $\sim 10\text{ MB}$ khi vào game.
  * Luồng lắng nghe phím tắt toàn cục (`Ctrl+F5` / `Ctrl+F9`) chạy trên Win32 message-pump riêng biệt và chỉ chiếm quyền phím tắt khi thực sự có phiên chơi game đang hoạt động.

---

## 2. Các Lỗ hổng Logic & Điểm nghẽn Cần Khắc phục Ngay (Critical Issues)

Trước khi phát triển tính năng mới, cần ưu tiên xử lý $5$ vấn đề cốt lõi sau:

### 2.1. Xung đột giữa `os._exit(0)` và tiến trình Cloud Sync ngầm (Nguy cơ mất Save)
* **Hiện trạng:** Khi người chơi thoát game, `_booster_on_game_exit` được kích hoạt để khôi phục cửa sổ và đẩy tệp `.congu_save` lên Google Drive. Lúc này phiên chơi đã kết thúc nên `has_active_play_session()` trả về `False`.
* **Rủi ro:** Nếu người dùng bấm nút đóng cửa sổ (`X` hoặc `Alt+F4`) ngay khi bảng tổng kết vừa hiện lên, hàm `request_close` hoặc `on_closed` sẽ gọi thẳng `os._exit(0)`, giết chết luồng tải save lên Google Drive ngay giữa chừng.
* **Giải pháp:** Bổ sung hàm kiểm tra `is_cloud_sync_busy()` hoặc bộ đếm tác vụ nền (Background Task Guard). Nếu đang đồng bộ đám mây hoặc đang đóng gói `.congu_save`, việc bấm nút đóng chỉ được phép ẩn cửa sổ xuống Tray kèm thông báo *"Đang hoàn tất đồng bộ Cloud Save..."* và tự động thoát sau khi tải xong.

### 2.2. Hiệu năng & Giới hạn Đơn phiên trong Quick Checkpoint (`Ctrl+F5` / `Ctrl+F9`)
* **Hiện trạng:**
  * `BOOSTER_STATE` chỉ lưu một `game_id` duy nhất và `_get_active_game_context()` luôn lấy phần tử đầu tiên `ids[0]`.
  * Mỗi lần bấm `Ctrl+F5` hoặc `Ctrl+F9`, hàm `_get_active_game_context()` lại gọi `api_instance.get_games()` và `load_user_config()` để đọc lại cấu hình từ ổ cứng.
* **Giải pháp:** Lưu đệm (Cache) thông tin `active_game_context` vào bộ nhớ RAM ngay khi bắt đầu phiên chơi (và xóa khi kết thúc phiên) để thao tác bấm phím tắt phản hồi tức thì mà không phát sinh truy xuất đĩa (Disk I/O).

### 2.3. Đứt gãy Giao tiếp Đẩy (Server-to-UI Push) ở chế độ Fallback Browser
* **Hiện trạng:** Các hàm `_push_toast`, `_push_session_summary` và `_push_dnd_result` phụ thuộc hoàn toàn vào `window.evaluate_js(...)` của PyWebView.
* **Rủi ro:** Khi ứng dụng chạy ở chế độ Fallback Browser (mở bằng trình duyệt Edge/Chrome độc lập), biến `window` bằng `None` hoặc không gắn với trình duyệt ngoài, làm mất toàn bộ thông báo Toast, bảng tổng kết phiên chơi và tính năng kéo-thả tệp.
* **Giải pháp:** Xây dựng hàng đợi sự kiện (Event Queue) phía Backend và đẩy xuống Frontend thông qua **Server-Sent Events (SSE)** tại endpoint `/api/events` (hoặc đính kèm vào phản hồi của `/api/heartbeat`).

### 2.4. Cơ chế Phục hồi Giao dịch Cài đặt (`recover_pending_transaction`) chưa hoàn chỉnh
* **Hiện trạng:** Trong `main()`, bước kiểm tra `get_pending_transaction` mới chỉ dừng ở mức ghi log cảnh báo vì journal chưa lưu đủ dữ liệu để tự động hoàn nguyên (rollback) khi mất điện hoặc sập ứng dụng lúc đang cài Việt hóa.
* **Giải pháp:** Nâng cấp `installer_pipeline` theo mô hình Atomic Transaction: sao lưu mọi tệp gốc sắp bị ghi đè vào thư mục tạm `.congu_staging/<tx_id>/backup/` kèm bảng kê mã băm SHA-256 trước khi thực hiện thay đổi.

### 2.5. Phím tắt Toàn cục Cố định (`Ctrl+F5` / `Ctrl+F9`)
* **Hiện trạng:** Mã phím `VK_F5` (`0x74`) và `VK_F9` (`0x78`) đang được gán cứng trong `_hotkey_loop()`.
* **Rủi ro:** Dễ xung đột với phím Quick Save mặc định của bản thân trò chơi (nhiều game RPG dùng `F5`/`F9`) hoặc phần mềm quay màn hình/stream.
* **Giải pháp:** Cho phép người dùng tùy chỉnh tổ hợp phím hoặc bật/tắt tính năng Quick Checkpoint trong phần Cài đặt.

---

## 3. Lộ trình Phát triển Chi tiết (Product & Engineering Roadmap)

### Giai đoạn 1: Ngắn hạn (Tuần 1 $\rightarrow$ Tuần 3)
**Mục tiêu:** *Ổn định nhân ứng dụng, Tách nhỏ `app.py` (Modularization) & Hoàn thiện cơ chế An toàn Dữ liệu.*

- [ ] **1.1. Tái cấu trúc (Refactor) `app.py` thành các module chuyên biệt:**
  - [ ] Tách phần quản lý Single-Instance Mutex, Named Event và Win32 Icon sang `core/win32_interop.py`.
  - [ ] Tách phần quản lý System Tray (`NotifyIcon`, ContextMenu, Balloon Tip) sang `core/system_tray.py`.
  - [ ] Tách bộ điều phối Game Booster (`enter_game_booster_mode`, Post-Exit Hook) sang `core/game_booster.py`.
  - [ ] Tách trình lắng nghe phím tắt (`_hotkey_loop`, Quick Checkpoint trigger) sang `core/hotkey_listener.py`.
  - [ ] Giữ `app.py` gọn nhẹ ($< 200$ dòng), chỉ đóng vai trò khởi tạo vòng đời ứng dụng (Entry Point).
- [ ] **1.2. Triển khai Graceful Shutdown Guard (Bảo vệ luồng thoát):**
  - [ ] Tạo bộ quản lý `BACKGROUND_TASKS` theo dõi trạng thái đóng gói `.congu_save` và tiến trình tải lên Google Drive.
  - [ ] Cập nhật `request_close()`, `on_closing()` và `run_fallback_browser_watchdog()` để chờ các tác vụ đồng bộ hoàn tất trước khi gọi `os._exit(0)`.
- [ ] **1.3. Hoàn thiện Atomic Installer & Rollback Journal:**
  - [ ] Ghi nhật ký giao dịch (`transaction.json`) bao gồm: danh sách tệp mới thêm vào và đường dẫn bản sao lưu của các tệp gốc bị ghi đè.
  - [ ] Tự động hóa hoàn toàn hàm `recover_pending_transaction(game_id, game_path)` khi khởi động lại ứng dụng sau sự cố.
- [ ] **1.4. Tối ưu hóa Quick Checkpoint Hotkeys:**
  - [ ] Lưu đệm (Cache) thông tin game đang chạy trong `PLAYTIME_MGR` để loại bỏ thao tác đọc ổ cứng khi bấm phím tắt.
  - [ ] Đọc cấu hình phím tắt từ `user_config.json` (cho phép đổi phím hoặc vô hiệu hóa).

---

### Giai đoạn 2: Trung hạn (Tháng 1 $\rightarrow$ Tháng 2)
**Mục tiêu:** *Đồng nhất giao tiếp IPC, Ảo hóa cài đặt Mod (Không chạm tệp gốc) & Nâng cấp trải nghiệm Game thủ.*

- [ ] **2.1. Đồng nhất kênh truyền sự kiện bằng Server-Sent Events (SSE):**
  - [ ] Tạo endpoint `GET /api/stream` trên Bottle Server để đẩy sự kiện thời gian thực từ Python xuống JS (Toast, tiến độ tải, kết quả kéo-thả, bảng tổng kết phiên chơi).
  - [ ] Viết lớp bọc (Wrapper) ở cả Backend và Frontend để tự động dùng SSE cho cả WebView2 lẫn chế độ Fallback Browser, xóa bỏ sự phụ thuộc vào `window.evaluate_js`.
- [ ] **2.2. Công nghệ Virtual Mod Deployment (NTFS Hardlink / Symlink Engine):**
  - [ ] Thay vì chép đè tệp Việt hóa trực tiếp vào thư mục cài game, giải nén gói `.congu` vào thư mục lưu trữ riêng của CỔ NGỮ.
  - [ ] Khi người dùng bật Việt hóa, sử dụng NTFS Hardlink (hoặc Symbolic Link) để ánh xạ tệp dịch vào thư mục game.
  - [ ] **Lợi ích:** Bật/tắt bản dịch hoặc chuyển đổi giữa nhiều bản dịch khác nhau trong $< 1\text{ giây}$, không tốn gấp đôi dung lượng ổ cứng, giữ thư mục gốc của game luôn sạch khi Steam cập nhật.
- [ ] **2.3. Hệ thống Multi-Slot Quick Checkpoint & Âm báo Tùy biến:**
  - [ ] Nâng cấp từ $1$ bản lưu đè lên thành $5$ ô lưu nhanh (Rolling Slots) cho mỗi game, kèm giao diện chọn bản lưu để khôi phục.
  - [ ] Thay thế tiếng bíp đơn điệu của `winsound.Beep` bằng tệp âm thanh nhẹ (`.wav`) êm tai, có tùy chọn tắt âm trong cài đặt.
- [ ] **2.4. Chế độ Điều khiển bằng Tay cầm (Gamepad / Big Picture Mode):**
  - [ ] Tích hợp Web Gamepad API trên Frontend kết hợp điều hướng tiêu điểm (Spatial Navigation) để hỗ trợ tay cầm Xbox/PlayStation trên PC và máy chơi game cầm tay (ROG Ally, Legion Go, MSI Claw).

---

### Giai đoạn 3: Dài hạn (Tháng 3 $\rightarrow$ Tháng 6)
**Mục tiêu:** *Tối ưu băng thông cập nhật, Kiểm tra tương thích tự động & Đồng bộ đám mây chuyên sâu.*

- [ ] **3.1. Cập nhật Bản dịch theo cơ chế Delta Patching:**
  - [ ] Tích hợp thuật toán so sánh nhị phân (`xdelta3` / `bsdiff`) vào quy trình cập nhật bản Việt hóa.
  - [ ] Khi nhóm dịch phát hành bản vá lỗi dịch thuật (ví dụ bản `1.0.1` lên `1.0.2`), người dùng chỉ cần tải vài megabyte phần chênh lệch thay vì tải lại gói `.congu` nặng hàng gigabyte.
- [ ] **3.2. Bộ kiểm tra Tương thích Phiên bản Game (Game Version Guard):**
  - [ ] Tự động lấy mã băm (SHA-256 / FileVersionInfo) của tệp `.exe` gốc trước khi khởi chạy game.
  - [ ] Cảnh báo sớm cho người chơi nếu game vừa được Steam/Epic tự động cập nhật lên phiên bản mới làm lệch cấu trúc tệp Việt hóa, tránh lỗi văng game (crash) không rõ nguyên nhân.
- [ ] **3.3. Giao diện Giải quyết Xung đột Cloud Save (Conflict Resolution UI):**
  - [ ] Khi phát hiện xung đột giữa tệp `.congu_save` trên máy cục bộ và bản trên Google Drive (khi người dùng chơi luân phiên trên PC và máy cầm tay), hiển thị hộp thoại so sánh chi tiết: thời gian sửa đổi, tổng số giờ chơi, dung lượng và tên thiết bị tải lên để người dùng chủ động chọn bản giữ lại.

---

### Giai đoạn 4: Mở rộng Hệ sinh thái (Trên 6 tháng)
**Mục tiêu:** *Xây dựng công cụ cho Nhóm dịch (Creator Economy) & Mở rộng sang Linux / SteamOS.*

- [ ] **4.1. Cổng Công cụ cho Nhóm Dịch (CỔ NGỮ Creator Studio & SDK):**
  - [ ] Cung cấp giao diện đóng gói tệp `.congu` chuẩn hóa ngay trong ứng dụng: tự động tạo cấu hình nhận diện thư mục game, mã hóa bảo vệ tài nguyên dịch thuật và gắn chữ ký số (Digital Signature) xác thực nhóm dịch.
  - [ ] Tích hợp tính năng gửi báo lỗi dịch thuật (kèm ảnh chụp màn hình và tọa độ câu thoại) từ người chơi về thẳng kênh quản lý của nhóm dịch.
- [ ] **4.2. Đa nền tảng — Hỗ trợ Linux / Steam Deck (SteamOS):**
  - [ ] Đóng gói toàn bộ các lệnh gọi `ctypes.windll` (Win32 API) vào lớp trừu tượng hệ điều hành (`core/platform/win32.py` và `core/platform/linux.py`).
  - [ ] Hỗ trợ tự động nhận diện thư mục `compatdata` (Proton Prefix) trên Steam Deck để cài đặt Việt hóa và đồng bộ Cloud Save xuyên suốt giữa PC Windows và Steam Deck.

---

## 4. Đề xuất Cấu trúc Thư mục sau khi Refactor (Mục tiêu Giai đoạn 1)

Để dễ bảo trì và mở rộng theo lộ trình trên, cấu trúc mã nguồn nên được tổ chức lại như sau:

```text
vietmodhub_pro/
├── app.py                      # Entry point gọn nhẹ (< 200 dòng): điều phối khởi chạy
├── api/
│   ├── __init__.py
│   ├── bridge.py               # ModManagerAPI (PyWebView JS Bridge)
│   ├── routes.py               # Bottle REST Endpoints & Heartbeat
│   └── sse_events.py           # [MỚI] Kênh Server-Sent Events đẩy thông báo xuống UI
├── core/
│   ├── config_manager.py       # Quản lý cấu hình & đồng bộ danh mục
│   ├── installer_pipeline.py   # Cài đặt, Atomic Journal & Rollback tự động
│   ├── vfs_deployer.py         # [MỚI - GĐ2] Triển khai Mod qua Hardlink/Symlink
│   ├── cloud_save.py           # Đóng gói .congu_save, đếm giờ & Google Drive Sync
│   ├── quick_checkpoint.py     # Nén & hoàn nguyên nhanh bản lưu trong lúc chơi
│   ├── system_booster.py       # Giải phóng RAM (Trim Working Set)
│   └── lifecycle_guard.py      # [MỚI] Quản lý trạng thái bận để chống tắt ngang (Graceful Exit)
├── desktop/                    # [MỚI] Tách toàn bộ logic đặc thù Desktop/OS từ app.py
│   ├── __init__.py
│   ├── single_instance.py      # Mutex & Named Event Wakeup Listener
│   ├── win32_window.py         # Gán Icon Titlebar, Frameless Drag, Restore Window
│   ├── system_tray.py          # Khởi tạo NotifyIcon, Menu chuột phải & Balloon Tip
│   ├── game_booster_ctrl.py    # Điều phối ẩn cửa sổ, gọi Trim RAM & Post-Exit Hook
│   ├── hotkey_listener.py      # Luồng Win32 Message-Pump lắng nghe Ctrl+F5 / Ctrl+F9
│   └── fallback_browser.py     # Khởi chạy Edge/Chrome App Mode & Heartbeat Watchdog
└── static/                     # Giao diện Single-Page Application (HTML/CSS/JS)
```

---

## 5. Tiêu chí Nghiệm thu Kỹ thuật (Definition of Done)

Mỗi giai đoạn khi hoàn thành cần đạt được các chỉ số kỹ thuật sau:
1. **Độ tin cậy Dữ liệu (Zero Data Loss):** $100\%$ các lần đóng ứng dụng đột ngột trong lúc đang đồng bộ Cloud Save hoặc đang cài đặt gói Việt hóa không làm hỏng tệp game gốc và không tạo ra tệp `.congu_save` lỗi trên Google Drive.
2. **Hiệu năng Hệ thống:**
   * Thời gian phản hồi khi đánh thức ứng dụng từ Single-Instance hoặc System Tray: $< 50\text{ ms}$.
   * Mức tiêu thụ RAM của CỔ NGỮ khi đang chạy ngầm trong chế độ Game Booster: $< 15\text{ MB}$.
   * Thời gian thực thi thao tác Quick Checkpoint (`Ctrl+F5`): $< 200\text{ ms}$ (không gây khựng khung hình trong game).
3. **Tính tương thích:** Giao diện và toàn bộ tính năng thông báo hoạt động đồng nhất $100\%$ giữa chế độ cửa sổ chuẩn (WebView2) và chế độ dự phòng (Fallback Browser).