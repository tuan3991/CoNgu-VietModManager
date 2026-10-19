# CỔ NGỮ (VietModHub) - Kiến Trúc Hệ Thống & Hướng Dẫn Kỹ Thuật (Architecture & Dev Guide)

> Tài liệu này được thiết kế để bất kỳ Lập trình viên hoặc Mô hình AI nào (ChatGPT, Claude, Gemini, DeepSeek, Cursor...) khi đọc vào cũng hiểu 100% kiến trúc, luồng dữ liệu và cách vận hành dự án.

---

## 1. Tổng Quan Dự Án
- **Tên ứng dụng**: CỔ NGỮ (VietModHub Pro).
- **Mục tiêu**: Phần mềm Portable quản lý, tự động phát hiện và cài đặt 1-click các gói dịch thuật / Việt hóa game (hỗ trợ Unreal Engine, Unity, GameMaker, BepInEx, Bethesda, REDengine...).
- **Đặc điểm nổi bật**:
  - Không cần cài đặt (Portable Standalone).
  - Tích hợp máy chủ Cloud CDN (GitHub Releases) tải siêu tốc 1-click từ mọi máy tính.
  - Bảo mật tài sản dịch bằng định dạng mã hóa độc quyền `.congu` (chuẩn quân sự AES-256-GCM).
  - Tự động sao lưu file gốc an toàn ra `%APPDATA%/VietModHub/backups/`.
  - Cơ chế "Tắt là tắt hẳn" (Zero-Leak Clean Exit) không để lại tiến trình chạy ngầm.

---

## 2. Ngăn Xếp Công Nghệ (Tech Stack)
- **Backend / Core Engine**: Python 3.11
  - `bottle`: Web micro-framework siêu nhẹ, chạy server cục bộ tại `127.0.0.1:49888`.
  - `pywebview`: Render cửa sổ desktop native Windows (EdgeChromium / WinForms), không thanh URL, không tab web.
  - `cryptography`: Thư viện mật mã học chuyên nghiệp (AES-256-GCM + PBKDF2-HMAC-SHA256).
- **Frontend / UI**:
  - HTML5, Vanilla JavaScript (không phụ thuộc Node.js hay build-step phức tạp).
  - TailwindCSS (Utility-first styling, giao diện tối Dark Mode Cyberpunk).
  - Lucide Icons (Hệ thống icon hiện đại).
- **Đóng gói**:
  - `PyInstaller` (One-dir standalone, tự động kích hoạt `--uac-admin` để có quyền ghi thư mục game).

---

## 3. Cấu Trúc Thư Mục & Vai Trò Các Tệp Tin

```
VietModManager/
├── app.py                      # Bộ não chính: Server Bottle, API, quét Steam, logic cài/gỡ mod, điều khiển PyWebView
├── security.py                 # Module bảo mật: Đóng gói và giải mã file .congu (AES-256-GCM in-memory)
├── games.json                  # Cơ sở dữ liệu: Danh mục 11 game, định dạng mod, đường dẫn file, link tải Cloud
├── version.json                # Quản lý phiên bản app và changelog cập nhật
├── app_icon.ico / app_icon.png # Icon ứng dụng chính thức
├── Chay_Co_Ngu.bat             # File khởi động thông minh cho người dùng cuối
├── static/
│   └── index.html              # Toàn bộ giao diện frontend (Single-Page App), CSS, modal, logic JS
└── VietModHub_Portable/        # Thư mục ứng dụng đã được đóng gói sẵn để chia sẻ cho người dùng
```

---

## 4. Các Loại Game Mod Được Hỗ Trợ (`mod_type` trong `games.json`)

1. **`pak`** (Unreal Engine: *Preludes, Backbone, Ravenous Devils*):
   - Đích đến: `{Game_Path}/{relative_install_path}/{target_pak_name}`
2. **`unity_assets`** (Unity Engine: *TOEM, Forever Ago, Erra Exordium*):
   - Thay thế `resources.assets` hoặc `sharedassets0.assets` kèm sao lưu an toàn.
3. **`wad`** (C++ / OpenGL: *Hotline Miami*):
   - Thay thế `HotlineMiami_GL.wad` và nạp thêm font nhị phân.
4. **`bepinex_language`** (Unity + BepInEx: *Risk of Rain 2*):
   - Tự động nạp `winhttp.dll`, thư mục `BepInEx` và gói ngôn ngữ `Language/vi/Main.json`.
5. **`folder_copy`** (Hi-Res Tactical: *Fallout Tactics*):
   - Sao chép toàn bộ thư mục `core/gui/font` và `core/locale`.
6. **`ini_and_exe`** (GameMaker: *Loop Hero*):
   - Ghi đè file font và patch file cấu hình ngôn ngữ `lang_eng.ini`.
7. **`witcher3_mod`** (REDengine 3: *The Witcher 3*):
   - Nạp file `en.w3strings` vào `Mods/modVietHoa/content` và patch `xml.bundle`.

---

## 5. Cơ Chế Bảo Mật Định Dạng `.congu`

- **Cấu trúc file `.congu`**:
  `[CONGU\x01 (6 bytes Magic)] + [Salt (16 bytes)] + [Nonce (12 bytes)] + [Ciphertext + Auth Tag (AES-256-GCM)]`
- **Khóa giải mã**: Được tạo bằng PBKDF2-HMAC-SHA256 với 100,000 vòng lặp từ Master Secret Key được phân mảnh động trong `security.py`.
- **Nguyên tắc In-Memory**: File sau khi tải về được giải mã trực tiếp trong RAM (`io.BytesIO`) và giải nén thẳng vào game. Tuyệt đối không ghi file zip thô ra đĩa cứng để ngăn chặn việc trích xuất tài sản dịch.

---

## 6. Hướng Dẫn Thêm Game Mới Vào Kho

Khi muốn thêm 1 tựa game mới:
1. Chuẩn bị file zip chứa gói mod chuẩn.
2. Dùng hàm `security.encrypt_mod_package("GameMoi.zip", "GameMoi.congu")` để tạo file `.congu`.
3. Tải `GameMoi.congu` lên GitHub Release Tag `mods-v1`.
4. Mở `games.json` và thêm cấu hình game mới theo mẫu:
```json
{
  "id": "ten_game_id",
  "steam_appid": "123456",
  "title": "Tên Game Gốc",
  "vietnamese_title": "Tên Game Việt Hóa",
  "engine": "Unity Engine",
  "mod_type": "unity_assets",
  "mod_file": "Game_Data/resources.assets",
  "relative_install_path": "Game_Data",
  "target_pak_name": "resources.assets",
  "download_url": "https://github.com/tuan3991/CoNgu-VietModManager/releases/download/mods-v1/GameMoi.congu"
}
```
5. Push `games.json` lên GitHub `main`. Toàn bộ các máy tính của người dùng đang chạy app sẽ tự động đồng bộ game mới trong 1 giây mà không cần cập nhật lại phần mềm!

---

## 7. Lệnh Đóng Gói Lại Bản Portable (Khi có thay đổi code)

Chạy lệnh trong terminal:
```powershell
& "C:\Users\tuan3\Documents\antigravity google\.venv\Scripts\python.exe" C:\Users\tuan3\.gemini\antigravity-ide\scratch\build_portable.py
```
File đóng gói sẽ tự động được đồng bộ vào `VietModHub_Portable` và nén thành `CoNgu_v2.0.2_Portable.zip`.
