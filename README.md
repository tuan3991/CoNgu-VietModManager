# VietMod Hub - Trình Quản Lý & Tự Động Cài Đặt Game Việt Hóa

**VietMod Hub** là ứng dụng desktop hiện đại, trực quan, chuyên dụng để quản lý, lưu trữ và tự động cài đặt / gỡ bỏ các bản Việt hóa game một cách an toàn (Hỗ trợ Unreal Engine, Unity, GameMaker, C++).

---

## 📂 Kho Lưu Trữ Bản Dịch (Repository)
Toàn bộ các gói mod Việt hóa của bạn được lưu trữ tập trung tại:
👉 **`C:\Users\tuan3\Documents\antigravity google\Viethoagame`**

---

## 🌟 Danh Sách 6 Game Đã Được Thêm Vào Thư Viện

| STT | Tựa Game | Thể Loại / Engine | Dung Lượng / Tiến Độ | Trạng Thái |
| :---: | :--- | :--- | :--- | :---: |
| 1 | **Tails: The Backbone Preludes** | Trinh thám Noir / Unreal Engine 5.1 | 22,240 câu thoại &bull; 100% có dấu | 🟢 ĐÃ CÀI ĐẶT |
| 2 | **Backbone (Tails Noir)** | Trinh thám Noir / Unreal Engine 4.25 | 15,225 câu thoại &bull; 100% có dấu | 🟢 ĐÃ CÀI ĐẶT |
| 3 | **TOEM - A Photo Adventure** | Phiêu lưu Nhiếp ảnh / Unity Engine | 3,438 dòng thoại &bull; Font vẽ tay | 🟢 ĐÃ CÀI ĐẶT |
| 4 | **Hotline Miami (1989)** | Hành động Top-down / C++ OpenGL | 1,901 câu thoại &bull; Font 80s Arcade | 🟢 ĐÃ CÀI ĐẶT |
| 5 | **Risk of Rain 2** | Bắn súng Co-op / Unity + BepInEx | 4,709 chuỗi (Base + 3 DLC) | 🟢 ĐÃ CÀI ĐẶT |
| 6 | **Fallout Tactics: Brotherhood of Steel** | Chiến thuật RPG / Tactical Engine Hi-Res | 57 Chiến dịch &bull; 6 bộ Font chuẩn | 🟢 ĐÃ CÀI ĐẶT |

---

## 🚀 Hướng Dẫn Sử Dụng Nhanh

1. Nhấp đúp chuột vào file **`Chay_VietMod_Manager.bat`** tại thư mục gốc.
2. Ứng dụng sẽ tự động mở lên:
   - Tự động nhận diện thư mục cài đặt của tất cả 6 tựa game trên ổ C: và E:.
   - Hiển thị đầy đủ poster dọc 600x900, banner ngang và logo chính thức từ Steam.
   - Cho phép cài đặt hoặc gỡ bỏ bản Việt hóa trong 1 cú nhấp (1-Click Install / Uninstall).
- Nút **"Chơi Ngay (Launch)"** mở game trực tiếp qua Steam.
   - Nút **"Kho Viethoagame"** mở nhanh thư mục chứa file mod trong Windows Explorer.

---

## 📦 Đóng Gói Mod Mới & Tự Động Tính SHA-256 (`pack_mod.py`)

Hệ thống cung cấp sẵn tiện ích CLI **`pack_mod.py`** giúp tự động hóa 100% quy trình tạo gói mod bảo mật `.congu` V2 và cập nhật vào `games.json`:

```bash
# 1. Chạy chế độ tương tác trực quan (Interactive Mode):
python pack_mod.py

# 2. Hoặc đóng gói tự động và cập nhật trực tiếp mã SHA-256 vào games.json:
python pack_mod.py "path/to/mod_folder" --game-id <game_id> --update-json
```

**Tính năng nổi bật:**
- Tự động nén thư mục mod thành tệp zip trung gian trong RAM.
- Mã hóa bằng thuật toán **AES-256-GCM Streaming Chunked (V2)** chống tràn RAM & disk.
- Tự động tính toán mã băm SHA-256 thực tế của file `.congu` đầu ra, loại bỏ hoàn toàn rủi ro copy-paste mã băm rỗng (`e3b0c442...`).
- Tự động cập nhật `congu_sha256` và `mod_size` vào `games.json` kèm sao lưu an toàn `games.json.bak`.
