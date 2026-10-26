# CỔ NGỮ (VietModHub) - Kiến Trúc Hệ Thống & Hướng Dẫn Kỹ Thuật (Architecture & Dev Guide)

> Tài liệu này được thiết kế để bất kỳ Lập trình viên hoặc Mô hình AI nào (ChatGPT, Claude, Gemini, DeepSeek, Cursor...) khi đọc vào cũng hiểu 100% kiến trúc, luồng dữ liệu và cách vận hành dự án.

---

## 1. Tổng Quan Dự Án
- **Tên ứng dụng**: CỔ NGỮ (VietModHub Pro).
- **Mục tiêu**: Phần mềm Portable quản lý, tự động phát hiện và cài đặt 1-click các gói dịch thuật / Việt hóa game (hỗ trợ Unreal Engine, Unity, GameMaker, BepInEx, Bethesda, REDengine...).
- **Đặc điểm nổi bật**:
  - **Không cần cài đặt (Portable Standalone)**: Chạy ngay không cần cài đặt rườm rà.
  - **Tải Cloud Siêu Tốc**: Tích hợp máy chủ Cloud CDN (GitHub Releases) và Google Drive tải 1-click từ mọi máy tính.
  - **Bảo mật tài sản dịch chuẩn quân sự**: Đóng gói trong định dạng container độc quyền `.congu` mã hóa AES-256-GCM in-memory, bảo vệ bản quyền công sức dịch giả.
  - **Sao lưu tại chỗ nguyên tử & Chống crash cập nhật game (In-Place Atomic Backup with Smart Steam/Epic Detection)**: Đổi tên tức thời `{target}` $\rightarrow$ `{target}.congu_bak` ngay trong thư mục game (0 giây độ trễ, 0 byte lãng phí ổ C:); lưu trữ tệp manifest JSON siêu nhẹ (~500 bytes) trong `%APPDATA%/VietModHub/` ghi nhận mã băm kép (`original_sha256` và `modded_sha256`). Tự động phát hiện khi game được Steam/Epic cập nhật lên phiên bản mới hoặc Verify Integrity để dọn dẹp backup cũ và tạo backup mới, ngăn chặn triệt để lỗi văng game (Crash).
  - **Cơ chế Transaction Rollback đơn tầng nghiêm ngặt & Auto-Backup ngầm**: Bọc toàn bộ quy trình cài đặt trong khối an toàn giao dịch; hoàn nguyên chuẩn xác từng thao tác theo đúng `executed_journal` của phiên hiện tại; kiên quyết không tự động kích hoạt Lớp 2 hay Lớp 3 khi gặp lỗi nhằm bảo vệ tối đa dữ liệu của các phiên bản cài đặt trước đó.
  - **Cơ chế "Tắt là tắt hẳn" (Zero-Leak Clean Exit)**: Đóng ứng dụng lập tức giải phóng toàn bộ tiến trình con và RAM, không bao giờ để lại tiến trình chạy ngầm.

---

## 2. Ngăn Xếp Công Nghệ (Tech Stack)
- **Backend / Core Engine**: Python 3.11
  - `pywebview`: Render cửa sổ desktop native Windows (EdgeChromium / WinForms), không thanh URL, không tab web. Hỗ trợ cầu nối IPC nguyên bản (`js_api=ModManagerAPI()`) cho phép Frontend gọi trực tiếp phương thức Python trong RAM không cần qua mạng.
  - `wsgiref` & `bottle` (**Multi-Threaded WSGI Server - Mục 1.4**): Phục vụ Single-Page UI tĩnh qua cổng động Port 0 (`127.0.0.1:0`) kế thừa `socketserver.ThreadingMixIn` (`ThreadingWSGIServer`). Xử lý từng HTTP request trên luồng riêng biệt, loại bỏ hoàn toàn hiện tượng nghẽn luồng UI (Single-Threaded bottleneck) khi vừa cài đặt/tải mod vừa polling tiến trình `/api/progress` hoặc tải hình ảnh tĩnh.
  - `Session Auth-Token (CSRF Protection)`: Mỗi phiên chạy phát sinh một khóa phiên bảo mật ngẫu nhiên (`secrets.token_hex(16)`), bảo vệ 100% các endpoint API khỏi bất kỳ website hay tiến trình lạ nào khác trên máy gọi lén.
  - `cryptography`: Thư viện mật mã học chuyên nghiệp (AES-256-GCM + PBKDF2-HMAC-SHA256).
- **Frontend / UI**:
  - HTML5, Vanilla JavaScript (không phụ thuộc Node.js hay build-step phức tạp).
  - TailwindCSS (Utility-first styling, giao diện tối Dark Mode Cyberpunk).
  - Lucide Icons (Hệ thống icon hiện đại).
- **Đóng gói & Phân phối**:
  - `PyInstaller` (One-dir standalone).
  - **Smart UAC Elevation & Pre-Flight Detection**: Ứng dụng chạy mặc định ở quyền User thông thường nhằm hạn chế tối đa False Positive từ Windows Defender. Kiểm tra sớm quyền ghi (`.congu_write_test`) ngay tại thời điểm quét thư mục hoặc người dùng chọn thư mục mới. Nếu phát hiện thư mục nằm trong `Program Files` hoặc bị khóa quyền ghi, hệ thống lưu đường dẫn vào cấu hình và thông báo nâng quyền ngay từ đầu qua Windows ShellExecute `runas` (hoặc hỗ trợ truyền HMAC Ticket sang worker process), tránh tình trạng đứt quãng trải nghiệm khi đang cài đặt dở dang.

---

## 3. Cấu Trúc Thư Mục & Vai Trò Các Tệp Tin

```
VietModManager/
├── app.py                      # Bộ não chính: Server Bottle (Port 0), API PyWebView, quét Steam/Epic/GOG, pipeline cài/gỡ mod
├── security.py                 # Mã nguồn Python bảo mật: Logic đóng gói/giải mã container .congu (AES-256-GCM in-memory)
├── security.cp311-win_amd64.pyd# Bản biên dịch C-Extension nhị phân (Cython + MinGW GCC -O3 -s) phân phối chính thức
├── security.pyd                # Bản C-Extension bí danh (Generic Alias)
├── compile_security_pyd.py     # Script tự động hóa biên dịch Cython security.py -> .c -> .pyd
├── pack_mod.py                 # Công cụ CLI đóng gói mod an toàn: tự động tính SHA-256, nén AES-256-GCM container .congu
├── games.json                  # Cơ sở dữ liệu: Danh mục 11 game, định dạng mod, pipeline install/uninstall, mã SHA-256, link tải
├── version.json                # Quản lý phiên bản app và changelog cập nhật
├── app_icon.ico / app_icon.png # Icon ứng dụng chính thức
├── Chay_Co_Ngu.bat             # File khởi động thông minh cho người dùng cuối
├── tools/                      # Bộ công cụ nhị phân streaming diff (xdelta3.exe, hdiffz.exe, hpatchz.exe)
├── static/
│   └── index.html              # Toàn bộ giao diện frontend (Single-Page App), CSS, modal, logic JS
└── VietModHub_Portable/        # Thư mục ứng dụng đã được đóng gói sẵn để chia sẻ cho người dùng (KHÔNG chứa plaintext security.py)
```

---

## 4. Cơ Chế Xử Lý Mod Cũ (Legacy `mod_type` - Tương Thích Ngược)

> [!NOTE]
> **Khuyến cáo kiến trúc**: Toàn bộ 11 tựa game hiện tại trong `games.json` và mọi game mới trong tương lai đều được vận hành dựa trên **Data-Driven Action Pipeline** (`install_steps` & `uninstall_steps` tại Mục 6). Các loại `mod_type` hardcode dưới đây chỉ được giữ lại trong `app.py` như một cơ chế **Fallback tương thích ngược** phòng trường hợp dữ liệu game thiếu trường `install_steps`:

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

## 5. Cơ Chế Bảo Mật Định Dạng `.congu` & Chống Dịch Ngược (Hardened Security)

- **Cấu trúc container `.congu` (V1 & V2 Streaming Chunked)**:
  `[CONGU\x02 (6 bytes Magic)] + [Salt (16 bytes)] + [Chunk_Length (4 bytes) + Nonce (12 bytes) + Ciphertext + Tag]...`
- **Khóa giải mã Master Key**:
  - Được bảo vệ bằng thuật toán XOR Masking đa tầng trong RAM.
  - Được phái sinh bằng PBKDF2-HMAC-SHA256 với 100,000 vòng lặp.
- **Biên dịch Native Binary chống dịch ngược (Cython C-Extension)**:
  - Toàn bộ module `security.py` được Cython biên dịch sang mã máy C/Assembly (`security.cp311-win_amd64.pyd` và `security.pyd`) bằng GCC 16 MinGW-w64 với cờ tối ưu `-O3 -s -fvisibility=hidden`.
  - Toàn bộ debug symbol và bảng tên hàm bị xóa sạch (stripped).
  - Không tồn tại file mã nguồn `security.py` hoặc bytecode `.pyc` trong bản phân phối `VietModHub_Portable`.
  - Các công cụ trích xuất/dịch ngược Python phổ biến (như `pyinstxtractor`, `pylingual`, `uncompyle6`, `decompyle++`) hoàn toàn vô hiệu.
- **Bảo Vệ Chống Tấn Công Import Hijacking & Hỗ Trợ Đa Tiến Trình (Parent/Worker/Elevated)**:
  - File `.pyd` tự động xác thực chữ ký phiên làm việc Ephemeral HMAC Ticket gắn với `PID` tiến trình chủ, hoặc `PID` tiến trình cha, hoặc role được ký bảo mật (`worker`/`elevated`). Bất kỳ script ngoài nào mở Python và gọi lén `import security; security.execute_secure_install(...)` đều bị từ chối truy cập ngay lập tức, trong khi tiến trình worker con hoặc tiến trình nâng quyền hợp lệ vẫn xác thực thông suốt.
- **Kiểm tra toàn vẹn gói mod (SHA-256 Integrity Check)**:
  - Mỗi tựa game trong `games.json` đều lưu trữ trường `congu_sha256` chuẩn của gói phát hành.
  - Khi tải về hoặc nạp từ bộ nhớ đệm (Cache), ứng dụng tự động kiểm tra mã băm SHA-256 trước khi giải mã. Nếu file bị lỗi đường truyền hoặc bị can thiệp trái phép, hệ thống từ chối giải mã và cảnh báo ngay lập tức.
- **Nguyên tắc In-Memory Direct-to-Disk Streaming (ConguStreamReader)**:
  - File được giải mã cuốn chiếu từng khối (Chunk Sliding Window) hoàn toàn trong RAM thông qua class `ConguStreamReader(io.RawIOBase)` và truyền trực tiếp vào `zipfile` để ghi thẳng xuống file đích trong thư mục game.
  - **Hỗ trợ Random Seeking & Đọc EOCD của `zipfile` (Seekable Stream & Chunk Offset Index - Mục 1.3)**:
    - Khi khởi tạo, `zipfile.ZipFile` của Python luôn gọi `seek(-22, os.SEEK_END)` để tìm đọc bảng End of Central Directory (EOCD) ở cuối tệp ZIP và liên tục nhảy cóc giữa các offset để trích xuất từng file member.
    - `ConguStreamReader` override phương thức `seekable() -> True`, cài đặt đầy đủ `seek(offset, whence)` (hỗ trợ `SEEK_SET`, `SEEK_CUR`, `SEEK_END`) và `tell()`.
    - **Bảng chỉ mục Offset siêu tốc (Chunk Offset Index)**: Quét lướt qua các trường `Chunk_Length` (4 bytes) ngay khi mở container `.congu` V2 mà chưa giải mã dữ liệu, lập chỉ mục vị trí các khối trong tích tắc (~10ms). Nhờ đó, khi `zipfile` gọi `seek()` tới bất kỳ offset nào, `ConguStreamReader` sử dụng tìm kiếm nhị phân (`bisect`) nhảy thẳng $O(1)$ tới đúng chunk tương ứng và chỉ giải mã duy nhất chunk đang nằm trong cửa sổ trượt RAM.
  - Tuyệt đối KHÔNG sử dụng `tempfile.SpooledTemporaryFile` (loại bỏ hoàn toàn nguy cơ Python tự động xả tràn dữ liệu chưa mã hóa xuống `%TEMP%` khi gặp file mod dung lượng lớn như `.pak` Unreal Engine hay `.assets` Unity).
  - Tuyệt đối không tạo file zip thô trung gian ở `%APPDATA%` hoặc bất kỳ đâu trên ổ cứng người dùng.
- **Cơ chế chống Path Traversal & Zip Slip (Bảo Vệ Tuyệt Đối Hệ Thống Khỏi Cấu Hình / File Nén Độc Hại)**:
  - Hàm chuẩn hóa và thẩm định đường dẫn bắt buộc `validate_safe_path(base_dir, relative_or_target_path, allow_base_itself=False)` được nhúng trực tiếp trong cả `security.py` / `security.pyd` và `app.py`.
  - Sử dụng `os.path.realpath` để chuẩn hóa đường dẫn, giải quyết symlink và relative navigation (`..`).
  - **Chuẩn hóa chữ hoa/thường trên Windows (Case-Insensitive Normalization with `os.path.normcase` - Mục 1.5)**: Trên hệ điều hành Windows, hệ thống tệp không phân biệt chữ hoa/thường nhưng phép so sánh chuỗi trong Python lại phân biệt hoa/thường (dẫn đến nguy cơ `game_root` dạng `c:\games\...` và `target_path` dạng `C:\Games\...` bị so sánh lệch và văng lỗi `PathTraversalError` oan). Hàm `validate_safe_path` bọc cả hai biến bằng `os.path.normcase(os.path.realpath(...))` trước khi đưa vào `os.path.commonpath([base_norm, target_norm]) == base_norm`, triệt tiêu hoàn toàn lỗi lệch case hoặc tên rút gọn 8.3 (`PROGRA~1`), đồng thời vẫn ngăn chặn 100% mọi hành vi Path Traversal thực sự.
  - Từ chối thực thi và raise `PathTraversalError` ngay lập tức nếu bất kỳ đường dẫn nào (`target`, `destination`, `file`, `source`, `executable_name`) trỏ ra ngoài thư mục gốc của game hoặc nằm khác phân vùng ổ đĩa (Cross-Drive Traversal trên Windows).
  - Chống triệt để lỗ hổng Zip Slip trong các hành động `extract_all`, `extract_zip` và `copy_folder`: duyệt từng `member` trong tệp nén, thẩm định đường dẫn đích và trích xuất an toàn file-by-file theo luồng nhị phân (loại bỏ lỗ hổng từ việc gọi `extractall` thô).
  - Ngăn chặn nguy cơ xóa nhầm thư mục game: cờ `allow_base_itself=False` trong các hành động như `delete` ngăn chặn tuyệt đối các cấu hình rỗng (`""` hoặc `"."`) nhắm vào xóa toàn bộ thư mục game.

---

## 6. Hướng Dẫn Thêm Game Mới Vào Kho (Data-Driven Action Pipeline)

Không cần sửa code `app.py` hay build lại `.exe`! Mọi game mới đều được định nghĩa thông qua các bước nguyên tử (`install_steps` và `uninstall_steps`) trong `games.json`:

### Các Hành Động Nguyên Tử Được Hỗ Trợ:
1. `backup`: Sao lưu tại chỗ tức thời `{target}` $\rightarrow$ `{target}.congu_bak` (0s, 0 byte ổ C:). Nếu cài đè lần 2, hệ thống tự động bảo toàn file `.congu_bak` gốc, tuyệt đối không ghi đè mất file gốc.
2. `copy_file`: Sao chép 1 tệp từ gói mod vào thư mục game (`source`, `destination`, `optional`).
3. `copy_folder`: Sao chép đệ quy cả thư mục từ gói mod vào thư mục game.
4. `patch_ini`: Tự động sao lưu và sửa key/value trong tệp INI (`file`, `section`, `key`, `value`), bảo toàn 100% comment và cấu trúc gốc. Sử dụng cơ chế Copy Backup để file gốc vẫn tồn tại cho tiến trình patch. **Cơ chế Tự Phục Hồi (Self-Healing - Mục 1.3)**: Nếu cộng tác viên theo thói quen thêm bước `backup` phía trước làm đổi tên `{target}` thành `{target}.congu_bak`, `patch_ini` sẽ tự động phát hiện và chép ngược nội dung từ `.congu_bak` ra lại `{target}` rồi mới sửa key/value, bảo toàn 100% mọi thiết lập đồ họa/âm thanh/phím bấm ban đầu của game.
5. `extract_all` / `extract_zip`: Giải nén gói mod hoặc file nén vào thư mục game.
6. `delete`: Xóa tệp hoặc thư mục dư thừa khi gỡ mod.
7. `rename`: Đổi tên tệp/thư mục.
8. `restore_backup`: Tự động khôi phục `{target}.congu_bak` $\rightarrow$ `{target}` sạch sẽ.
9. `patch_binary`: Vá nhị phân tại chỗ (**Streaming Binary Diff Patching** hỗ trợ đa thuật toán xdelta3 / VCDIFF, HDiffPatch và BSDIFF40) trực tiếp lên tệp tài nguyên gốc trên máy người chơi (`target`, `patch`, `original_sha256`, `patched_sha256`).
   - **Giải quyết triệt để game Unity (`resources.assets`), GameMaker (`data.win`), WAD/PAK**: Thay vì sao chép và phân phối lại toàn bộ tệp game gốc nặng từ vài trăm MB đến hàng GB, gói mod chỉ cần chứa tệp patch diff siêu nhẹ (từ vài trăm KB đến vài MB).
   - **Tiết kiệm 99% băng thông**: Tốc độ tải về tính bằng giây, hoàn toàn không lo giới hạn băng thông Google Drive / GitHub Releases.
   - **Chống bản quyền DMCA 100%**: Bản mod chỉ chứa mã nhị phân sai khác của phần dịch thuật/font, tuyệt đối không phân phối lại tài sản đồ họa/âm thanh độc quyền của nhà phát triển game.
   - **Chống Tràn RAM Tuyệt Đối Cho Tệp Hàng GB (Streaming Sliding Window - Mục 1.2)**:
     - **Vấn đề của bsdiff4 truyền thống**: Nạp toàn bộ tệp vào RAM và thuật toán Suffix Sorting ngốn tới 8x-17x dung lượng (tệp 1 GB ngốn 15 GB RAM khi tạo diff; ngốn 3 GB RAM tức thời trên máy người chơi).
     - **Giải pháp Streaming Engine**: Hệ thống tích hợp bộ công cụ native streaming trong thư mục `tools/` (`xdelta3.exe`, `hdiffz.exe`, `hpatchz.exe`). Hàm `apply_binary_patch` tự động đọc 16 bytes Magic nhận diện định dạng:
       - VCDIFF (RFC 3284 / xdelta3 - `\xd6\xc3\xc4`): Chạy `xdelta3.exe -B 64MB` hoặc `hpatchz.exe -s-64m`.
       - HDiffPatch (`HDIFF`): Chạy `hpatchz.exe -s-64m`.
       - BSDIFF40 (`BSDIFF40`): Tự động ưu tiên gọi `hpatchz.exe -s-64m` để vá theo luồng streaming cửa sổ trượt thay vì nạp toàn bộ vào RAM; chỉ fallback sang `bsdiff4.file_patch` cho tệp nhỏ.
     - **RAM tiêu thụ cố định**: Giữ vững ở mức **32 MB – 64 MB RAM** kể cả khi tệp gốc nặng từ 1.5 GB đến 10 GB.
     - **Phía đóng gói (`pack_mod.py --diff`)**: Tự động kích hoạt cơ chế streaming khi tệp gốc vượt quá 150 MB, cảnh báo và ngăn chặn hoàn toàn lỗi văng `MemoryError`.
   - **Bảo vệ toàn vẹn tuyệt đối**: Kiểm tra mã băm tệp gốc `original_sha256` trước khi vá (từ chối vá nếu game lệch phiên bản); tự động sao lưu ngầm `.congu_bak`; và kiểm tra `patched_sha256` sau khi vá.
   - **Cơ chế Tự Động Nhận Diện Cài Đè / Cập Nhật (Smart Re-patch & Update Fallback - Mục 1.1)**: Khi người dùng cài đè phiên bản dịch mới v1.1 hoặc bấm "Cài lại", tệp `{target}` trên đĩa đã mang mã băm đã mod (`patched_sha256`) và không khớp với `original_sha256`. Hệ thống không báo lỗi ngay mà tự động kiểm tra tệp sao lưu `{target}.congu_bak`. Nếu `{target}.congu_bak` khớp với `original_sha256`, hệ thống lấy chính tệp sao lưu này làm dữ liệu nguồn (source) để áp dụng bản vá nhị phân và ghi đè nguyên tử lên `{target}`, đồng thời bảo toàn vẹn nguyên tệp `.congu_bak` gốc ban đầu.

### Cấu Hình Chuẩn Mẫu Đầy Đủ Trong `games.json`:
```json
{
  "id": "game_moi",
  "steam_appid": "1234560",
  "title": "Tựa Game Mới",
  "vietnamese_title": "Tựa Game Mới Việt Hóa",
  "executable_name": "GameMoi.exe",
  "congu_sha256": "5f07e8167c23ddc089ddc5cabed2e547f2ce6659e045ce126950604899045066",
  "install_steps": [
    {
      "action": "patch_binary",
      "target": "Game_Data/resources.assets",
      "patch": "resources.assets.diff",
      "original_sha256": "310da15f2cd75a35236b71ce9a847b596e47f4e914d5a7595bd2413a72ba123a",
      "patched_sha256": "c46e9588dfe9bebc9e77796cbb4046a7f532573e75e20938016adbaf51f2ce2d"
    },
    {
      "action": "patch_ini",
      "file": "settings.ini",
      "section": "Language",
      "key": "Locale",
      "value": "vi"
    }
  ],
  "uninstall_steps": [
    {
      "action": "restore_backup",
      "target": "Game_Data/resources.assets"
    },
    {
      "action": "restore_backup",
      "target": "settings.ini"
    }
  ],
  "download_url": "https://github.com/tuan3991/CoNgu-VietModManager/releases/download/mods-v1/GameMoi.congu"
}
```

> ⚠️ **LƯU Ý QUAN TRỌNG VỀ `congu_sha256`**:
> - Tuyệt đối **không** copy-paste mã băm mẫu hoặc mã băm của chuỗi rỗng (`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`). Nếu mã `congu_sha256` bị sai lệch, hệ thống bảo vệ toàn vẹn sẽ từ chối giải mã và chặn cài đặt để bảo vệ game của người dùng.
> - **Tự động hóa & Kiểm tra chéo hoàn toàn với `pack_mod.py`**: Khi đóng gói bản mod mới, hãy luôn dùng công cụ tiện ích `pack_mod.py`. Tiện ích này sẽ:
>   1. Tự động lọc bỏ 100% file rác hệ điều hành (`thumbs.db`, `desktop.ini`, `.DS_Store`, `.congu_bak`, `.congu_tx_tmp`, `.pyc`, `.git`, `__pycache__`).
>   2. **Tự động kiểm tra chéo (Cross-Validation)** cấu trúc gói mod với các bước `install_steps` trong `games.json`: cảnh báo ngay nếu thiếu tệp `source`, `patch` hay `copy_folder` (ngăn chặn triệt để lỗi do nén dư tầng thư mục cha hoặc gõ nhầm tên file).
>   3. Nén và mã hóa sang container `.congu` V2 (AES-256-GCM Streaming), tính toán SHA-256 thực tế và tự động điền/cập nhật trực tiếp `congu_sha256` cùng `mod_size` vào `games.json`:
>   ```bash
>   # Cú pháp tự động đóng gói và cập nhật trực tiếp vào games.json:
>   python pack_mod.py "path/to/mod_folder" --game-id game_moi --update-json
>
>   # Hoặc chạy ở chế độ tương tác trực quan (Interactive Mode):
>   python pack_mod.py
>   ```
> Khi bạn cập nhật `games.json` trên GitHub, toàn bộ người dùng sẽ tự động nhận diện và cài đặt/gỡ cài đặt được tựa game mới ngay lập tức mà không cần cập nhật file `.exe`!

---

## 7. Cơ Chế "Transaction Rollback", Auto-Backup Ngầm & Khôi Phục Gốc Khẩn Cấp

Khi thực thi `install_steps` (ví dụ: Bước 1: `backup`, Bước 2: `copy_file`, Bước 3: `patch_ini`), nếu bất kỳ bước nào gặp sự cố (tiến trình game đang chạy khóa file, thiếu quyền ghi, lỗi định dạng tệp...), hệ thống cam kết **không bao giờ để game rơi vào trạng thái "nửa nạc nửa mỡ"**:

1. **Cơ Chế Auto-Backup Ngầm (Implicit In-Place Auto-Backup)**:
   - Tích hợp trực tiếp bên trong các hành động `copy_file`, `copy_folder`, `extract_all` / `extract_zip`: Cứ hễ đích đến (destination) đã tồn tại tệp tin trên đĩa trước khi ghi đè, hệ thống tự động tạo bản sao lưu tại chỗ `.congu_bak` (nếu chưa có) và ghi nhận vào `executed_journal`.
   - **Lợi ích**: Triệt tiêu hoàn toàn nguy cơ mất tệp gốc của game kể cả khi người viết `games.json` vô tình quên khai báo hành động `backup` trước các lệnh sao chép thư mục hoặc giải nén.
2. **Rollback Giao Dịch Đơn Tầng Nghiêm Ngặt (Strict Single-Transaction Reversal)**:
   - Khi xảy ra lỗi tại bước $N$, hệ thống chỉ kích hoạt chuỗi **Rollback Ngược Chiều theo đúng `executed_journal` của phiên hiện tại**.
   - **Tuyệt đối KHÔNG tự động chạy Lớp 2 (`uninstall_steps`) hay Lớp 3 (quét toàn bộ thư mục)** khi cài đặt gặp lỗi.
   - **Bảo toàn khi cập nhật mod (Cơ chế Sao Lưu Phiên Giao Dịch `.congu_tx_tmp` - Mục 1.4)**:
     - Khi người dùng đã cài bản mod v1.0 trước đó và đang cài đè bản cập nhật v1.1 mà gặp lỗi giữa chừng: nếu chỉ hoàn nguyên bằng `.congu_bak`, tệp mod v1.0 sẽ bị xóa sạch và game bị lùi về tận bản tiếng Anh gốc.
     - **Giải pháp `.congu_tx_tmp`**: Khi thực hiện các hành động ghi đè (`backup`, `copy_file`, `patch_binary`, `copy_folder`, `extract_all`, `patch_ini`) mà phát hiện tệp sao lưu `.congu_bak` đã tồn tại sẵn (chứa tiếng Anh gốc), Auto-Backup ngầm tự động sao lưu tệp hiện tại (v1.0) sang `{target}.congu_tx_tmp` và ghi nhận `has_tx_tmp: True` vào nhật ký giao dịch.
     - **Khi thành công 100%**: Khối `finally` dọn dẹp sạch sẽ toàn bộ các tệp `.congu_tx_tmp`, không để lại tệp rác trên ổ cứng.
     - **Khi xảy ra lỗi ở bước $N$**: Vòng lặp Rollback ưu tiên kiểm tra `has_tx_tmp`, tự động thay thế nguyên tử `{target}.congu_tx_tmp` $\rightarrow$ `{target}`, đảm bảo game quay về đúng phiên bản mod v1.0 nguyên vẹn 100%, trong khi `{target}.congu_bak` (tiếng Anh gốc) vẫn nằm yên an toàn!
3. **Cơ Chế Chống Crash Khi Steam/Epic Cập Nhật Game (Smart Steam/Epic Detection)**:
   - File manifest JSON lưu tại `%APPDATA%/VietModHub/<game_id>/backup_manifest.json` ghi nhận mã băm kép: `original_sha256` (file gốc) và `modded_sha256` (file sau khi mod).
   - Khi người dùng cài đè hoặc gỡ cài đặt (`restore_backup`): Hệ thống tự động kiểm tra mã băm của file hiện tại trong thư mục game.
     - Nếu file hiện tại **không khớp** `modded_sha256` (nghĩa là Steam/Epic đã tự động cập nhật game hoặc người dùng vừa Verify Integrity file), hệ thống nhận diện file hiện tại đã là file game mới sạch.
     - Khi đó, hệ thống sẽ tự động dọn bỏ file `.congu_bak` cũ lỗi thời và sao lưu từ phiên bản mới (khi cài đặt), hoặc bỏ qua khôi phục và dọn `.congu_bak` cũ (khi gỡ cài đặt), ngăn chặn 100% việc lấy file cũ thời kỳ trước đè lên game mới gây crash.
4. **Tính Năng "Sửa Lỗi / Khôi Phục Gốc Khẩn Cấp" Theo Yêu Cầu (On-Demand Emergency Deep Restore)**:
   - Việc quét đệ quy toàn bộ thư mục game (`os.walk`) tìm đuôi `.congu_bak` được chuyển thành một tính năng cứu hộ độc lập, **chỉ kích hoạt khi người dùng chủ động bấm nút "Khôi Phục Gốc Khẩn Cấp" trên giao diện**.
   - Điều này giúp triệt tiêu hoàn toàn hiện tượng nghẽn I/O (đơ ứng dụng) đối với các tựa game nặng chứa hàng chục nghìn file.
5. **Phản Hồi Trực Quan Lên Giao Diện PyWebView**:
   - Cửa sổ tiến trình hiển thị cảnh báo đỏ (`alert-triangle`), thông báo chi tiết bước bị lỗi và xác nhận: *"Hệ thống đã tự động kích hoạt Transaction Rollback: toàn bộ tệp tin game đã được hoàn nguyên 100% về trạng thái ổn định trước khi cài đặt!"*.
   - Người dùng có thể bấm Đóng modal và game vẫn mở lên chơi bình thường ở trạng thái nguyên vẹn.
6. **Bảo Vệ Môi Trường BepInEx & Mod Gameplay Tiền Tồn Tại (Pre-existing BepInEx Protection - Mục 1.5)**:
   - Ở các tựa game Unity sử dụng BepInEx / Doorstop loader (điển hình như *Risk of Rain 2*), người chơi thường đã tự cài sẵn BepInEx cùng hàng chục mod gameplay trong `BepInEx/plugins/`.
   - Khi bắt đầu cài đặt, hệ thống tự động phát hiện và ghi nhận vào `%APPDATA%/VietModHub/backups/<game_id>/backup_manifest.json` xem trước đó game đã có sẵn `winhttp.dll` và thư mục `BepInEx` hay chưa (`winhttp_preexisting: true/false`, `bepinex_preexisting: true/false`). Trạng thái này được bảo toàn bất biến kể cả khi cài đè hoặc cập nhật nhiều lần.
   - Khi người chơi bấm Gỡ cài đặt Việt hóa:
     - Nếu `winhttp_preexisting == True`: Hệ thống chỉ dọn dẹp đúng gói ngôn ngữ tiếng Việt (`Language/vi/` hoặc `StreamingAssets/Language/vi/`), **tự động bỏ qua các bước xóa hoặc đổi tên `winhttp.dll` thành `winhttp.dll.disabled` và tuyệt đối không xóa thư mục `BepInEx`**. Toàn bộ mod gameplay của người chơi được bảo toàn nguyên vẹn 100%!
     - Nếu `winhttp_preexisting == False`: Cho phép đổi tên hoặc dọn dẹp `winhttp.dll` để trả game về vanilla nguyên bản sạch sẽ không còn loader Doorstop.

---

## 8. Lệnh Đóng Gói Lại Bản Portable (Khi có thay đổi code)

Chạy lệnh trong terminal:
```powershell
& "C:\Users\tuan3\Documents\antigravity google\.venv\Scripts\python.exe" C:\Users\tuan3\.gemini\antigravity-ide\scratch\build_portable.py
```
File đóng gói sẽ tự động:
1. Dọn dẹp các tiến trình `VietModHub` đang chạy ngầm.
2. Tự động gọi `compile_security_pyd.py` biên dịch `security.py` $\rightarrow$ `security.cp311-win_amd64.pyd`.
3. Chạy `PyInstaller` tạo thư mục `VietModHub_Portable`.
4. Xóa sạch mọi file mã nguồn thô `security.py` trong bản phát hành.
5. Tự động nén thành `CoNgu_v2.0.2_Portable.zip` (dung lượng ~36MB).
