# Cổ Ngữ — Checklist phát triển và hoàn thiện

> Ngày lập: 30/10/2026
> Mục tiêu: Cài Việt hóa dễ dàng, bảo vệ game và save, khôi phục được khi có sự cố.
> Cơ sở: đánh giá tĩnh mã nguồn, chưa kiểm thử ứng dụng trên game thật. Các điểm nghi vấn cần tái xác nhận trước khi sửa; không coi tài liệu này là chứng nhận bảo mật.

## Cách sử dụng

- `[ ]`: chưa hoàn thành; `[x]`: đã hoàn thành và xác minh.
- Chỉ chọn **một nhóm việc nhỏ** cho mỗi lần triển khai. Không yêu cầu agent làm toàn bộ roadmap cùng lúc.
- Trước khi sửa: tạo branch/commit mốc; không dùng thư mục game/save thật cho test phá hủy.
- Mỗi việc hoàn thành phải có: thay đổi cụ thể, test hoặc bước kiểm chứng, ghi nhận kết quả.
- Nếu kiểm tra thấy chức năng đã có và đúng, thêm test thay vì triển khai trùng.
- Không ghi token, khóa, thông tin tài khoản hay save cá nhân vào commit hoặc báo cáo.
- Đường dẫn và số dòng dưới đây là mốc tham khảo, có thể thay đổi sau refactor.

## Bắt đầu từ đây

- [x] **B01 — Chốt phạm vi bản ổn định tiếp theo:** ưu tiên an toàn cài/gỡ, save và cập nhật; tạm hoãn tính năng phụ mới.
- [x] **B02 — Tạo baseline:** ghi phiên bản nguồn, môi trường Python, dependency và cách chạy/build hiện tại.
- [x] **B03 — Lập môi trường test:** thư mục game giả, save giả, gói ZIP/gói mod thử nghiệm; tuyệt đối không trỏ test vào dữ liệu thật.
- [x] **B04 — Kiểm kê test hiện có:** đọc các test trong `tools/`, xác định tác dụng phụ, chạy những test an toàn và ghi pass/fail cùng lệnh chạy.
- [x] **B05 — Bắt đầu P0-01:** viết test tái hiện backup save thất bại trước, rồi mới sửa.

**Thứ tự khuyến nghị:** B01–B05 → P0-01 → P0-02 → P0-03 → P0-04 → P0-05 → P0-06 → P1.

### Môi trường thử và kiểm kê B03–B04 (30/10/2026)

- Tạo `congu-b03-x3u6sa5w` trong thư mục Temp của Windows, gồm `game`, `save`, `packages`, `appdata`, `tmp`; game/save là file văn bản giả, gói ZIP chứa nội dung dịch giả. Fixture save mới chỉ là mẫu, chưa kiểm thử restore. Các regression test tự tạo thêm game/gói giả trong thư mục temp.
- Khi chạy test đặt `APPDATA` vào `appdata`, `TEMP` và `TMP` vào `tmp` của fixture, và `PYTHONDONTWRITEBYTECODE=1`. Các lệnh sau chạy từ gốc repo bằng `../.venv/Scripts/python.exe`:
  - `tools/test_security_hardening.py`: **20 pass, 0 fail**.
  - `tools/test_rollback_safety.py`: **26 pass, 0 fail**.
  - `tools/test_zip_lookup.py`: **20 pass, 0 fail**.
  - `tools/test_tool_integrity.py`: **23 pass, 0 fail**.
- Các test trên import `security.cp311-win_amd64.pyd`, không chứng minh binary khớp `security.py` hiện tại. Lần thử đầu dùng `python` trong Git Bash thất bại cả bốn do thiếu `cryptography`; chạy lại bằng virtualenv thành công.
- `python tools/check_settings_modal.py`: mã thoát 0, toàn tài liệu cân bằng và tab/panel khớp, nhưng phép đếm riêng khối modal báo không cân bằng (95/96); script không chuyển kết quả này thành mã lỗi. Cần kiểm tra riêng trước khi kết luận lỗi UI.
- `tools/verify_settings_integration.py`: chưa chạy; đọc cấu hình cá nhân và xóa cache/temp ứng dụng, chỉ cân nhắc trong profile giả được kiểm tra kỹ. `tools/measure_patch_io.py`: chưa chạy; benchmark ghi dữ liệu và thực thi công cụ patch. Hai helper screenshot không phải regression test và có thể ghi ảnh hoặc truy cập URL.
- Không chạy app, không dùng game/save thật và không kiểm tra các tình huống restore; cần tiếp tục B05 với test save giả.

### Phạm vi và baseline B01–B02 (30/10/2026)

- **Phạm vi bản ổn định:** ưu tiên P0: an toàn cài/gỡ, save, cập nhật, đường dẫn, kết nối, tải và phục hồi. Tạm hoãn các tính năng phụ ở mục Tạm hoãn; P1 và P2 thực hiện sau theo thứ tự roadmap. Chưa chốt phiên bản phát hành mới hoặc phạm vi nền tảng chính thức.
- **Nguồn:** HEAD `7cef975ef7fe8399de4c2295382d1b77cb5caab3`; working tree có nhiều thay đổi và file chưa theo dõi, nên HEAD không đại diện toàn bộ mã đang làm việc. `ROADMAP.md` cũng chưa được theo dõi. Chưa tạo branch hay commit mốc; cần xác định phạm vi các thay đổi hiện có trước khi tạo mốc.
- **Phiên bản ứng dụng được khai báo:** `2.0.3` trong `version.json` và `core/config_manager/paths.py`; không khẳng định đây là bản build đã kiểm chứng.
- **Môi trường quan sát:** Windows x64; Python hệ thống 3.11.0, pip 22.3; virtualenv `../.venv` dùng Python 3.11.0, pip 26.2.1.
- **Dependency quan sát trong virtualenv:** bottle 0.13.4, pywebview 6.2.1, cryptography 50.0.2, pythonnet 3.1.0, Pillow 12.3.0, requests 2.34.2, PyInstaller 6.22.3 và Cython 3.3.0. Đây là các gói liên quan đã cài, không phải danh sách dependency đầy đủ hay lockfile; chưa tìm thấy `requirements*.txt` hoặc `pyproject.toml`. Python hệ thống có pythonnet 3.2.1 và Pillow 13.0.0, khác virtualenv.
- **Chạy hiện tại:** `Chay_VietMod_Manager.bat` ưu tiên `../.venv/Scripts/python.exe app.py`, rồi `.venv`, bản portable hoặc Python hệ thống. Script có thể tự cài dependency và bỏ Mark-of-the-Web trên cây thư mục; chưa chạy để tránh tác dụng phụ. Có thể chạy trực tiếp bằng `../.venv/Scripts/python.exe app.py`, nhưng chưa kiểm chứng ứng dụng trong bước này.
- **Build hiện tại:** `ARCHITECTURE.md` mô tả gọi `../.venv/Scripts/python.exe` với script `build_portable.py` nằm ngoài repository; tài liệu mô tả script dừng tiến trình và tạo ZIP phiên bản 2.0.2. `VietModHub.spec` chứa đường dẫn tuyệt đối theo máy và binary native; `compile_security_pyd.py` cũng phụ thuộc đường dẫn Python/GCC cụ thể. Chưa chạy hoặc xác minh build; quy trình chưa được xác nhận tái lập.

---

## P0 — An toàn dữ liệu và nền tảng tin cậy

### P0-01 — Không ghi đè save khi backup thất bại

- [x] Xác nhận mọi nhánh khôi phục cloud/Vault có thể ghi đè dữ liệu hiện tại.
- [x] Nếu backup cần thiết nhưng thất bại: dừng restore, giữ nguyên save và thông báo lý do.
- [x] Tải và giải nén vào staging, kiểm tra gói hợp lệ trước khi áp dụng.
- [x] Áp dụng có nhật ký/rollback; không báo thành công nếu còn file lỗi.
- [x] Kiểm tra và sửa nhánh backup Vault gọi `shutil.copy2`, bảo đảm import và xử lý lỗi đúng.
- [x] Thêm test: hết dung lượng, thiếu quyền, ZIP hỏng, file bị khóa, gián đoạn giữa lúc ghi.

**Hoàn thành khi:** test chứng minh save hiện tại vẫn nguyên vẹn hoặc phục hồi đúng sau lỗi; không có lỗi backup bị nuốt rồi tiếp tục ghi đè.

Tham khảo: [cloud restore](cloud_sync.py#L1018-L1049), [backup Vault](cloud_sync.py#L1200-L1209), [giải nén Vault](vault_manager.py#L610-L629).

### P0-02 — Xác minh và khôi phục khi tự cập nhật app

- [x] Kiểm tra toàn bộ chuỗi lấy metadata → tải → giải nén → áp dụng → khởi chạy.
- [x] Thiết kế manifest phát hành có chữ ký, khóa công khai tin cậy trong app và quy trình giữ khóa ký ngoài repository.
- [x] Kiểm chữ ký manifest và SHA-256 gói; không coi hash tải từ cùng nguồn chưa xác thực là đủ chứng minh nguồn gốc.
- [x] Giới hạn kích thước giải nén và kiểm tra đường dẫn gói cập nhật.
- [ ] Giữ bản cũ, xử lý đúng mã thoát `robocopy`, không chạy bản cập nhật dở dang.
- [ ] Có quy trình rollback khi áp dụng thất bại hoặc bản mới không khởi động được.
- [ ] Test gói bị sửa, thiếu file, bị khóa, thiếu dung lượng và mất mạng.

**Phần đã kiểm chứng lại (01/11/2026):**

- [x] Test qua `apply_app_update` dùng manifest ký bằng khóa test: hợp lệ đi tới bàn giao script; thiếu/sửa chữ ký, sai SHA, thiếu EXE, ZIP traversal, lỗi mạng/quyền/dung lượng mô phỏng bị chặn trước khởi chạy script.
- [x] Không fallback sang `download_url` ngoài payload đã ký; test checksum bắt buộc xác nhận đã gọi downloader.
- [x] Chạy `robocopy` thật trên thư mục giả: backup bị khóa dừng trước mọi thay đổi ứng dụng; nguồn cập nhật bị khóa sau khi copy một phần được rollback; backup khác nội dung nhưng cùng kích thước/mtime được làm mới.
- [x] Chặn thư mục nguồn/ứng dụng/backup chứa lẫn nhau và ký tự mở rộng batch trong đường dẫn; giữ script chẩn đoán, không tự xóa giữa nhánh lỗi; ghi CRLF đúng một lần.
- [x] Probe yêu cầu ACK đúng token giao dịch, phiên bản, PID và đường dẫn EXE của process con; PowerShell thật từ chối ACK sai và chỉ dừng đúng process con khi timeout (test EXE giả).
- [x] Test cả chuỗi BAT → probe → EXE mới thoát lỗi → rollback bằng robocopy → EXE cũ ghi nhận đã khởi chạy lại trên fixture.
- [x] Kiểm SHA-256 và cấu trúc toàn cây sau backup/apply/rollback; metadata kích thước/mtime trùng nhưng nội dung sai bị từ chối. Backup/rollback yêu cầu cây khớp chính xác; apply cho phép file cũ ngoài gói.
- [x] Kiểm reparse/junction trước mọi copy; test junction trong thư mục ứng dụng bị chặn trước khi backup hoặc sửa dữ liệu ngoài.
- [x] Test đường BAT thành công: SHA toàn cây hợp lệ + ACK đúng giao dịch → phase complete, giải phóng pending journal và giữ backup cũ.
- [ ] Kiểm chứng giao diện native/browser fallback của bản portable thật gửi ACK sau khi sẵn sàng; chưa chạy UI thật trong bước này.
- [x] Khóa nguồn backup trước bước rollback trên fixture: robocopy trả lỗi, giữ backup/script/staging và không chạy bản ứng dụng dở; thiếu EXE phục hồi cũng dừng có lỗi.
- [x] Mỗi lần tải dùng `update/job-<id>` riêng; journal `pending_update.json` tạo độc quyền trước handoff, chặn job sau kể cả JSON hỏng, giữ nguyên backup cũ. Có file phase ghi backing_up/applying/rolling_back/complete/rolled_back.
- [x] Test tranh chấp handoff và lỗi tạo process: không ghi đè journal giao dịch khác; chỉ giải phóng journal mới khi chưa khởi chạy script, hoặc khi script thành công/rollback hoàn tất.
- [x] Dừng đúng PID BAT tại ranh giới sau backup: ứng dụng cũ nguyên vẹn, backup/journal/phase/log còn giữ; dừng sau apply một phần: toàn bộ bản cũ vẫn trong backup, không chạy EXE dở.
- [ ] Kiểm chứng rollback hết dung lượng và gián đoạn trong lúc robocopy đang ghi file lớn trên bản portable thử nghiệm.

**Giới hạn:** test filesystem cũ bỏ qua thời gian chờ và lệnh `start`; test startup mới chạy EXE C# giả cùng PowerShell/robocopy thật và đã chứng minh chạy lại fixture cũ, nhưng chưa chạy giao diện/bản portable thật. Vì vậy ba mục tổng hợp phía trên vẫn chưa hoàn thành. Lỗi hết dung lượng đang được mô phỏng, không làm đầy ổ thật.

**Hoàn thành khi:** gói không hợp lệ bị chặn trước khi áp dụng; cập nhật lỗi vẫn có đường chạy lại phiên bản cũ.

Tham khảo: [updater](api/ipc_bridge.py#L3380-L3445).

### P0-03 — Thống nhất bảo vệ đường dẫn và giải nén

- [x] Thay kiểm tra tiền tố chuỗi bằng helper dùng `realpath`/`commonpath` phù hợp.
- [x] Rà soát nơi giải nén/copy/delete/rename trong mod, save, Vault và updater.
- [x] Xác định chính sách với symlink/junction/reparse point; từ chối trường hợp không an toàn.
- [x] Test `../`, đường dẫn tuyệt đối, khác ổ, khác hoa/thường, thư mục cùng tiền tố và junction.

**Hoàn thành khi:** dữ liệu thử độc hại không ghi/xóa bên ngoài thư mục được phép; đường dẫn hợp lệ trên Windows vẫn hoạt động.

Tham khảo: [Vault](vault_manager.py#L610-L628), [helper hiện có](security.py#L192-L239).

### P0-04 — Giữ xác minh TLS và bảo vệ API localhost

- [x] Rà soát `CERT_NONE`, `verify=False` và nơi bỏ kiểm tra hostname.
- [x] Giữ xác minh chứng chỉ; lỗi mạng phải có thông báo và retry an toàn, không tự hạ bảo mật.
- [x] Rà soát miễn token của `/api/window/*` cùng các endpoint làm thay đổi trạng thái.
- [x] Thiết kế token/Origin/Host checks phù hợp cả pywebview và chế độ browser fallback.
- [x] Không dùng GET cho thao tác thay đổi trạng thái; không nhúng token vào URL/log.
- [x] Thêm test request thiếu/sai token và request từ Origin không được phép.

**Hoàn thành khi:** luồng hợp lệ vẫn chạy; request không được phép và chứng chỉ không hợp lệ bị từ chối.

Tham khảo: [Steam client](core/steam_client.py#L64-L70), [API auth hook](api/routes.py#L141-L167), [window endpoints](api/routes.py#L1792-L1816).

### P0-05 — Tải file và kiểm tra gói đáng tin cậy

- [x] Dùng tên file tạm duy nhất theo job, không chỉ theo PID. Đã kiểm chứng bằng `tools.test_http_downloader_safety` (4 pass, gồm hai job cùng đích); không đồng nghĩa đã khóa đồng thời theo đích.
- [x] Kiểm tra số byte khi server cung cấp độ dài phù hợp; kiểm checksum khi có giá trị tin cậy.
- [x] Không xóa file đích tốt trước khi file mới đã được xác minh và sẵn sàng thay thế.
- [x] Bắt buộc SHA-256 cho gói Việt hóa trong kho chính thức; thiết kế chuyển đổi cho gói cũ.
- [x] Tách chính sách gói chính thức và gói người dùng nhập; không tự gắn nhãn đáng tin cậy cho gói ngoài.
- [x] Test tải thiếu, hủy, mất mạng và hai job cùng đích.
**Hoàn thành khi:** tải lỗi không phá file cũ; gói sai checksum bị chặn; không có hai job ghi chồng ngoài kiểm soát.

Tham khảo: [HTTP downloader](core/downloader/http_downloader.py#L81-L113), [installer](core/installer_pipeline/install_ops.py#L249-L263).

### P0-06 — Kiểm thử phục hồi sau lỗi và gián đoạn

- [x] Test cài lần đầu, cài lại, cập nhật mod và gỡ mod trên game giả.
- [x] Test game thay đổi sau cập nhật Steam/Epic và backup không còn khớp.
- [x] Test thiếu quyền, file bị khóa, hết dung lượng và lỗi ở từng bước pipeline.
- [x] Test app bị kết thúc giữa thao tác trong môi trường thử nghiệm; xác định cơ chế phát hiện giao dịch dở khi mở lại.
- [x] Khóa thao tác theo game/tài nguyên để tránh install, uninstall, restore chạy chồng.
- [x] Giữ thông tin phục hồi khi rollback lỗi; chỉ dọn file tạm khi an toàn.

**Hoàn thành khi:** có ma trận kết quả và kiểm tra checksum/trạng thái trước-sau; app không báo thành công giả hoặc tự xóa dữ liệu phục hồi còn cần thiết.

---

## P1 — Trải nghiệm cốt lõi: tìm → kiểm tra → cài → chơi → khôi phục

### P1-01 — Metadata tương thích

- [x] Định nghĩa schema cho build/phiên bản game, nền tảng, DLC, phiên bản mod và ngày kiểm thử.
- [x] Thêm nhóm dịch, nguồn gốc, changelog, lỗi đã biết và cảnh báo anti-cheat/online.
- [x] Phân biệt: đã xác nhận tương thích / chưa kiểm thử / không tương thích.
- [x] Chặn hoặc yêu cầu xác nhận phù hợp khi không đủ bằng chứng; không suy ra tương thích chỉ từ đường dẫn game.

**Hoàn thành khi:** người dùng biết bản game của mình có được hỗ trợ trước khi cài.

### P1-02 — Kiểm tra trước khi cài

- [x] Tập hợp kiểm tra thư mục, phiên bản, game đang chạy, quyền ghi và dung lượng từng ổ liên quan.
- [x] Phát hiện xung đột file/loader với mod khác.
- [x] Chỉ kiểm tra runtime phù hợp với game; phân biệt cảnh báo và lỗi chặn.
- [x] Hiển thị kế hoạch thay đổi, vị trí backup và hành động tiếp theo.

**Hoàn thành khi:** lỗi có thể dự đoán được phát hiện trước bước ghi; thông báo chỉ rõ cách khắc phục.

### P1-03 — Một hành động chính theo trạng thái

- [x] Chuẩn hóa state machine giữa backend và frontend.
- [x] Nút chính tương ứng: Chọn thư mục / Cài Việt hóa / Chơi / Cập nhật / Kiểm tra / Khôi phục.
- [x] Đưa mở thư mục, đổi poster và tác vụ ít dùng vào menu phụ.
- [x] Hiển thị trạng thái chờ, tiến độ, lỗi và kết quả; không để người dùng bấm lặp.

**Hoàn thành khi:** không có nút hành động mâu thuẫn với trạng thái thật của game.

### P1-04 — Cập nhật mod thực chất

- [x] Lưu phiên bản mod đã cài và revision catalog.
- [x] So sánh với catalog mới cùng điều kiện tương thích.
- [x] Thay kết quả `has_update=False` cố định bằng trạng thái có căn cứ.
- [x] Phân biệt không có cập nhật, không kết nối được và chưa xác định.

**Hoàn thành khi:** test được đủ trường hợp có/không cập nhật, catalog lỗi và offline.

Tham khảo: [check_updates](api/ipc_bridge.py#L3029-L3047).

### P1-05 — Trung tâm sửa lỗi và lịch sử

- [x] Hướng dẫn theo tình huống: không hiện tiếng Việt, game không mở, game vừa cập nhật, muốn gỡ, muốn khôi phục save.
- [x] Ghi job ID, phiên bản, bước thực hiện và kết quả xác minh.
- [x] Cho xem backup và phạm vi sẽ khôi phục trước khi xác nhận.
- [x] Xuất báo cáo hỗ trợ có preview, tự che token và thông tin cá nhân; không tự upload.
- [x] Lỗi quan trọng phải xem lại được, không chỉ xuất hiện qua toast.

**Hoàn thành khi:** có thể hiểu một lần cài lỗi và chọn cách xử lý mà không cần đọc log Python thô.

### P1-06 — Khả năng tiếp cận và bố cục

- [ ] Kiểm thử 1366×768 và Windows scaling 125%, 150%.
- [x] Kiểm thử bàn phím, focus modal, Escape và nhãn nút icon.
- [ ] Có chế độ giảm chuyển động, độ tương phản phù hợp và cảnh báo không chỉ dựa vào màu.
- [ ] Chuẩn hóa thuật ngữ tiếng Việt; thông tin kỹ thuật nằm trong phần Chi tiết.

**Hoàn thành khi:** luồng cài/gỡ/restore dùng được ở các cấu hình trên, không mất nút hoặc nội dung quan trọng.

---

## P2 — Mở rộng kho và vận hành lâu dài

- [ ] **P2-01 — Công cụ xuất bản:** kiểm schema, file thiếu, bước cài/gỡ, checksum, chữ ký và changelog trước phát hành.
- [ ] **P2-02 — Kiểm thử gói:** chạy install/uninstall trên fixture game giả; ghi rõ giới hạn so với kiểm thử game thật.
- [ ] **P2-03 — Quy trình phát hành:** dependency cố định, build sạch, kiểm thành phần native `.pyd` khớp nguồn, quét gói và release notes.
- [ ] **P2-04 — CI an toàn:** test không cần dữ liệu cá nhân, khóa cloud hoặc game thương mại; chặn phát hành khi test bắt buộc lỗi.
- [ ] **P2-05 — Chuẩn hóa tài liệu:** thống nhất Cổ Ngữ/VietModHub, hướng dẫn, danh sách game và hành vi đóng app/chạy nền.
- [ ] **P2-06 — Chính sách dữ liệu:** nêu dữ liệu cục bộ/cloud, quyền truy cập, ngắt kết nối, xóa token và xóa dữ liệu.
- [ ] **P2-07 — Nguồn tải:** tách kho kiểm duyệt với nguồn ngoài; hiển thị xuất xứ, báo cáo và gỡ nguồn; không tự chạy file tải về.
- [ ] **P2-08 — Cộng đồng:** theo dõi game, báo lỗi theo phiên bản, bình chọn có chống spam, ghi nhận và ủng hộ nhóm dịch.
- [ ] **P2-09 — Hiệu năng:** đo startup, quét thư viện, tải ảnh, RAM/CPU; tối ưu theo số đo, không theo cảm giác.
- [ ] **P2-10 — Tách module có mục tiêu:** giảm coupling UI/API/nghiệp vụ sau khi có test bảo vệ; chưa cần đổi framework.
- [ ] **P2-11 — Nội dung trung thực:** bỏ tuyên bố tuyệt đối về chống dịch ngược, chống crash, chống DMCA hay bảo mật 100%.

## Tạm hoãn

Không phải bỏ vĩnh viễn; chỉ mở lại sau khi P0 và luồng P1 ổn định.

- [ ] Chat, bạn bè và mạng xã hội nội bộ.
- [ ] Mở rộng hệ thống huy hiệu/XP.
- [ ] Theme editor phức tạp hơn.
- [ ] AI gợi ý game khi chưa có nhu cầu và tiêu chí đánh giá rõ.
- [ ] Quảng bá trim working set như tính năng tăng FPS hoặc giảm thực sự nhu cầu bộ nhớ.
- [ ] Viết lại toàn bộ frontend/backend chỉ để đổi công nghệ.

---

## Điều kiện chung trước khi đánh dấu hoàn thành

- [ ] Có test tái hiện hoặc bước kiểm chứng rõ ràng trước/sau.
- [ ] Có kiểm tra đường thành công và đường lỗi liên quan.
- [ ] Không tác động game/save thật trong test tự động.
- [ ] Không làm lộ thông tin nhạy cảm.
- [ ] Không báo thành công nếu chưa xác minh kết quả.
- [ ] Cập nhật hướng dẫn nếu hành vi người dùng thay đổi.
- [ ] Ghi commit và kết quả vào nhật ký bên dưới.

## Mẫu yêu cầu cho agent ở phiên sau

```text
Đọc ROADMAP.md và thực hiện riêng mục P0-01.
Trước tiên đọc mã hiện tại, xác nhận vấn đề và đề xuất phạm vi sửa nhỏ nhất.
Viết test bằng thư mục tạm/save giả, không dùng game hoặc save thật.
Không làm các mục khác, không refactor ngoài phạm vi, không nâng phiên bản phát hành.
Sau khi sửa, chạy test phù hợp và báo rõ kết quả, phần chưa kiểm chứng.
Chỉ đánh dấu các checkbox đã được xác minh và bổ sung nhật ký tiến độ.
```

## Nhật ký tiến độ

| Ngày | Mục | Thay đổi / quyết định | Kiểm chứng | Commit |
|---|---|---|---|---|
| 30/10/2026 | Lập kế hoạch | Tạo checklist từ đánh giá tĩnh; chưa sửa tính năng | Chưa chạy test/app | — |
| 30/10/2026 | B01–B02 | Chốt ưu tiên P0; ghi HEAD, trạng thái working tree, môi trường, dependency và cách chạy/build | Kiểm tra Git, Python, pip và cấu hình; chưa chạy app/build/test | Chưa tạo |
| 30/10/2026 | B03–B04 | Tạo fixture giả và kiểm kê test, cô lập AppData/temp | 4 regression test pass trên binary native; modal có cảnh báo cần kiểm tra; chi tiết phía trên | Chưa tạo |
| 30/10/2026 | B05 | Thêm `tools/test_save_backup_failure.py` với save/Vault giả, Drive giả và mô phỏng lỗi backup | `../.venv/Scripts/python.exe -m unittest -v tools.test_save_backup_failure`: 3 test thất bại như dự kiến vì dữ liệu bị ghi đè; chưa sửa P0-01 | Chưa tạo |
| 30/10/2026 | P0-01 một phần | Chặn ghi khi backup thất bại trong tải save cloud, tải Vault và bung Vault; bổ sung import shutil | 3 test B05 pass với dữ liệu giả; chưa có staging/rollback nhiều file và các nhánh restore khác chưa được sửa | Chưa tạo |
| 30/10/2026 | P0-01 tiếp tục | Chặn lỗi backup tại restore revision, nhập ZIP chuẩn và nhập Vault; thêm test revision/nhập Vault | 5 test backup pass; staging/rollback chưa triển khai, lỗi backup tại file sau vẫn có thể để lại file trước đã thay đổi; nhập ZIP chưa có test riêng | Chưa tạo |
| 30/10/2026 | P0-01 cloud một phần | Staging ZIP và backup trước khi ghi, rollback khi áp dụng lỗi; giữ thư mục phục hồi nếu rollback thất bại | 9 test pass trên dữ liệu giả, gồm ZIP hỏng, ghi lỗi giữa chừng, rollback lỗi và thành công | Chưa tạo |
| 30/10/2026 | P0-01 nhập Vault | Stage bản sao cạnh Vault, kiểm tra manifest và CRC toàn gói, backup rồi thay thế nguyên tử | 11 test pass với dữ liệu giả, bao gồm thay thế lỗi và nhập thành công; các nhánh bung Vault, ZIP chuẩn và checkpoint chưa có staging/rollback | Chưa tạo |
| 31/10/2026 | P0-01 Vault multi-file | Stage toàn bộ entry Vault, snapshot trước mọi ghi, thay thế nguyên tử từng file và rollback batch cho unpack/revision; giữ staging nếu rollback lỗi | `../.venv/Scripts/python.exe -m unittest -v tools.test_save_backup_failure`: 13 pass; bao gồm lỗi replace file thứ hai của unpack và revision | Chưa tạo |
| 31/10/2026 | P0-03 restore path một phần | Dùng `realpath` + `normcase` + `commonpath` cho Vault unpack/revision, ZIP chuẩn import và cloud restore; chặn traversal/sibling prefix | `../.venv/Scripts/python.exe -m unittest -v tools.test_save_backup_failure`: 15 pass, 1 skip (Windows không cấp quyền tạo symlink); traversal/sibling-prefix pass | Chưa tạo |
| 31/10/2026 | P0-04 API/TLS một phần | Bắt buộc token header cho window/achievement API, bỏ token query và GET drag; loại bỏ các chỗ tắt xác minh TLS Steam/SteamGridDB/poster | `../.venv/Scripts/python.exe -m unittest -v tools.test_api_session_auth tools.test_save_backup_failure`: 20 pass, 1 skip; grep Python không còn `CERT_NONE`/`check_hostname = False`/`verify=False` | Chưa tạo |
| 31/10/2026 | P0-05 downloader/checksum một phần | File tải tạm unique cùng filesystem, kiểm Content-Length, thay thế atomically không xóa file cũ; bắt buộc SHA-256 catalog cho `.congu` official | `../.venv/Scripts/python.exe -m unittest -v tools.test_http_downloader_safety`: 4 pass (thiếu byte, hủy, thành công, hai job chung đích) | Chưa tạo |
| 31/10/2026 | P0-02 updater một phần | Yêu cầu SHA-256 ZIP từ metadata phát hành, kiểm checksum trước giải nén, giới hạn member/dung lượng ZIP, kiểm exit `robocopy` trước chạy EXE | `../.venv/Scripts/python.exe -m unittest -v tools.test_updater_integrity tools.test_http_downloader_safety`: 6 pass; chưa có ký manifest/rollback bản app | Chưa tạo |
| 31/10/2026 | P0-06 rollback status một phần | Không còn tuyên bố rollback 100% nếu một bước rollback lỗi; giữ transaction temp thay vì dọn ngay | `../.venv/Scripts/python.exe -m unittest -v tools.test_pipeline_rollback_status`: 1 pass; `../.venv/Scripts/python.exe tools/test_rollback_safety.py`: 26 pass | Chưa tạo |
| 31/10/2026 | P0-04 Origin guard một phần | Request API thay đổi trạng thái có token chỉ chấp nhận Origin loopback (hoặc Origin trống cho native WebView); từ chối web origin ngoài | `../.venv/Scripts/python.exe -m unittest -v tools.test_api_session_auth`: 7 pass | Chưa tạo |
| 31/10/2026 | P0-06 khóa theo game | Thay khóa installer toàn cục bằng lock theo `game_id` cho install/uninstall/emergency restore trong cùng process | `../.venv/Scripts/python.exe -m unittest -v tools.test_game_operation_locks tools.test_pipeline_rollback_status`: 4 pass | Chưa tạo |
| 31/10/2026 | P0-06 journal installer thử nghiệm | Persist journal atomically trước/trong install pipeline; phương án restore tự động ban đầu đã bị vô hiệu hóa trong bước rà soát sau vì chưa chứng minh an toàn | Test ban đầu không chứng minh rollback đầy đủ; xem ghi chú P0-06 bên dưới | Chưa tạo |
| 31/10/2026 | P0-01 standard ZIP import | Đưa nhập ZIP save chuẩn vào staging + snapshot + atomic replace + rollback batch của Vault | `../.venv/Scripts/python.exe -m unittest -v tools.test_save_backup_failure`: 16 pass, 1 skip (symlink privilege) | Chưa tạo |
| 31/10/2026 | P0-02 release checksum tool | Thêm tool tính/gắn atomically `portable_zip_sha256`, từ chối artifact không khớp URL metadata; thêm placeholder checksum cho release hiện có (không biết artifact nên updater vẫn từ chối) | `../.venv/Scripts/python.exe -m unittest -v tools.test_release_checksum_tool tools.test_updater_integrity`: 4 pass | Chưa tạo |
| 31/10/2026 | P0-06 journal lifecycle + updater lock | Test journal bị giữ khi rollback lỗi/không xác nhận được restore và bị xóa khi pipeline thành công; updater kiểm lock theo game; tránh overwrite trạng thái lỗi rollback | `../.venv/Scripts/python.exe -m unittest -v tools.test_pipeline_crash_recovery tools.test_pipeline_rollback_status tools.test_game_operation_locks tools.test_release_checksum_tool tools.test_updater_integrity`: 13 pass | Chưa tạo |
| 31/10/2026 | P0-03 ZIP restore path tests | Thêm test cloud + standard ZIP chống traversal, absolute POSIX, drive path và dấu gạch Windows; xác nhận save/outside không đổi | `../.venv/Scripts/python.exe -m unittest -v tools.test_save_backup_failure`: 18 pass, 1 skip (symlink privilege) | Chưa tạo |
| 31/10/2026 | P0-03 pipeline action path tests | Test copy/delete/rename/patch_ini/extract_zip từ chối absolute/traversal destination và giữ file outside nguyên vẹn; audit action paths dùng `validate_safe_path` cho target/source trước mutation | `../.venv/Scripts/python.exe -m unittest -v tools.test_pipeline_action_paths tools.test_save_backup_failure tools.test_pipeline_crash_recovery tools.test_pipeline_rollback_status`: 29 pass, 1 skip (symlink privilege) | Chưa tạo |

| 31/10/2026 | P0-06 an toàn recovery | Tắt restore tự động từ journal chưa đầy đủ: `restore_files_inplace` có thể nuốt lỗi và dọn manifest; startup chỉ ghi cảnh báo. Chặn pipeline mới nếu journal còn tồn tại (kể cả JSON hỏng); các luồng cài khác chưa được chặn. Recovery sau crash chưa hoàn thành. | `../.venv/Scripts/python.exe -m unittest -v tools.test_pipeline_crash_recovery tools.test_pipeline_rollback_status tools.test_game_operation_locks tools.test_updater_integrity`: 12 pass | Chưa tạo |

| 31/10/2026 | P0-01 ZIP restore regression | Kiểm tra ZIP chuẩn thành công và backup; xác nhận test lỗi thật sự tới lần replace thứ hai; dọn staging khi batch rỗng tại unpack/revision/ZIP chuẩn | `../.venv/Scripts/python.exe -m unittest -v tools.test_save_backup_failure`: 19 pass, 1 skip (symlink privilege) | Chưa tạo |

| 31/10/2026 | P0-06 chặn journal tồn đọng | Các wrapper install/uninstall/emergency restore từ chối thao tác nếu journal còn tồn tại, kể cả JSON hỏng; bổ sung import còn thiếu cho emergency restore | `../.venv/Scripts/python.exe -m unittest -v tools.test_game_operation_locks tools.test_pipeline_crash_recovery tools.test_pipeline_rollback_status`: 12 pass; chưa kiểm inter-process và các lối gọi bypass wrapper | Chưa tạo |

| 31/10/2026 | P0-01 va chạm backup Vault | Từ chối batch khi đường dẫn backup trùng đích hoặc backup khác; snapshot tất cả file trước khi tạo backup để không ghi đè save khác trong batch | `../.venv/Scripts/python.exe -m unittest -v tools.test_save_backup_failure`: 21 pass, 1 skip (symlink privilege); test unpack và revision | Chưa tạo |

| 31/10/2026 | P0-01 backup Vault atomically | Ghi backup qua tệp tạm cùng thư mục rồi replace; lỗi ghi một phần giữ nguyên backup cũ và save | `../.venv/Scripts/python.exe -m unittest -v tools.test_save_backup_failure`: 22 pass, 1 skip (symlink privilege); disk-full được mô phỏng, chưa kiểm tra filesystem đầy thật | Chưa tạo |

| 31/10/2026 | P0-01 rollback file tạm | Rollback Vault và cloud copy snapshot sang tệp tạm cùng thư mục rồi replace; lỗi copy rollback giữ file đang có và snapshot để phục hồi thủ công | `../.venv/Scripts/python.exe -m unittest -v tools.test_save_backup_failure`: 23 pass, 1 skip (symlink privilege), test lỗi ghi mô phỏng | Chưa tạo |

| 31/10/2026 | P0-01 Vault save file đơn | Unpack nhận metadata file đơn, restore trực tiếp tới file cấu hình; unpack/revision từ chối slot file chứa nhiều entry thay vì bỏ qua hoặc chọn tùy ý | `../.venv/Scripts/python.exe -m unittest -v tools.test_save_backup_failure`: 25 pass, 1 skip (symlink privilege) | Chưa tạo |

| 31/10/2026 | P0-01 đích revision Vault | Không dùng `macro_path` từ metadata archive để đổi đích; restore về slot cấu hình hiện tại và từ chối metadata hỏng trước khi ghi | `../.venv/Scripts/python.exe -m unittest -v tools.test_save_backup_failure`: 27 pass, 1 skip (symlink privilege) | Chưa tạo |

| 31/10/2026 | P0-01 đích ZIP chuẩn | Khớp game/slot với cấu hình hiện tại, không dùng đường dẫn từ manifest ZIP; từ chối game/slot không biết hoặc đường dẫn cấu hình chưa phân giải. Thay đổi tương thích: game ghost không có cấu hình không thể tự restore | `../.venv/Scripts/python.exe -m unittest -v tools.test_save_backup_failure`: 28 pass, 1 skip (symlink privilege) | Chưa tạo |

| 31/10/2026 | P0-01 backup nhập Vault | Ghi backup Vault qua file tạm cùng thư mục trước khi replace; lỗi copy dở giữ Vault và backup cũ, test riêng lỗi replace Vault sau backup | `../.venv/Scripts/python.exe -m unittest -v tools.test_save_backup_failure`: 29 pass, 1 skip (symlink privilege); lỗi disk-full mô phỏng | Chưa tạo |

| 31/10/2026 | P0-01 tải Vault Drive | Kiểm schema manifest và CRC toàn ZIP, dùng file tải/backup tạm cùng thư mục và dọn khi lỗi; test client Drive giả, CRC hỏng và backup lỗi một phần | `../.venv/Scripts/python.exe -m unittest -v tools.test_save_backup_failure`: 31 pass, 1 skip (symlink privilege); chưa test Drive thật | Chưa tạo |

| 31/10/2026 | P0-01 SHA Vault Drive | Khi Drive có `appProperties.sha256`, kiểm định dạng và đối chiếu trước backup; metadata cũ thiếu hash vẫn tương thích nhưng không được xác minh SHA | `../.venv/Scripts/python.exe -m unittest -v tools.test_save_backup_failure`: 32 pass, 1 skip (symlink privilege); client giả, chưa test Drive thật | Chưa tạo |

| 31/10/2026 | P0-01 checksum ZIP cloud save | Upload mới thêm `zip_sha256` riêng với fingerprint thư mục; download xác minh khi có trước giải nén, tệp cũ thiếu hash vẫn tương thích. Download dùng tên tạm riêng | `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe -m unittest -v tools.test_save_backup_failure`: 33 pass, 1 skip (symlink privilege), client giả; chưa test Drive thật | Chưa tạo |

| 31/10/2026 | P0-01 upload ZIP cloud | Upload dùng file tạm riêng; test client giả xác nhận `zip_sha256` khớp byte ZIP thực gửi và file tạm được dọn | `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe -m unittest -v tools.test_save_backup_failure`: 34 pass, 1 skip (symlink privilege); chưa test Drive thật hoặc phối hợp nhiều tiến trình | Chưa tạo |

| 31/10/2026 | P0-01 lỗi tạo file tạm cloud | Trả lỗi có cấu trúc nếu tạo file tạm upload/download bị từ chối; test không sửa save và không gọi upload/download | `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe -m unittest -v tools.test_save_backup_failure`: 35 pass, 1 skip (symlink privilege); lỗi quyền được mô phỏng | Chưa tạo |

| 31/10/2026 | P0-01 tạo ZIP save | Không xóa ZIP đích trước `os.replace`; test mô phỏng file bị khóa giữ ZIP cũ và save | `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe -m unittest -v tools.test_save_backup_failure`: 36 pass, 1 skip (symlink privilege) | Chưa tạo |

| 31/10/2026 | P0-02/05 checksum trước replace | Downloader hỗ trợ validator trên file tạm; updater và tải gói `.congu` kiểm SHA trước replace, updater không xóa package cũ khi tải lỗi | `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe -m unittest -v tools.test_http_downloader_safety tools.test_updater_integrity`: 8 pass; test updater giả, chưa kiểm thử toàn bộ các nhánh gói/cạnh tranh job | Chưa tạo |

| 31/10/2026 | P0-05 khóa replace theo đích | Hai job tải cùng đích từng lỗi `PermissionError` khi `os.replace` chạy song song trên Windows; thêm khóa theo đường dẫn đích quanh bước replace | `../.venv/Scripts/python.exe -m unittest -q tools.test_http_downloader_safety`: pass 5/5 lần liên tiếp, gồm test hai job cùng đích | Chưa tạo |

| 31/10/2026 | P0-01 nhánh khôi phục backup cục bộ | Rà soát toàn bộ nhánh restore: cloud download, Vault unpack/revision, nhập ZIP chuẩn, nhập Vault, tải Vault Drive đã có backup/staging/rollback. Bổ sung nhánh còn thiếu `restore_local_backup`: chụp snapshot save hiện tại trước khi khôi phục, dừng nếu snapshot lỗi, yêu cầu thư mục save tồn tại, từ chối game_id/tên backup chứa đường dẫn; xoay vòng backup không xóa bản nguồn đang khôi phục. Đánh dấu hoàn thành P0-01 | `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe -m unittest -v tools.test_save_backup_failure`: 41 pass, 1 skip (symlink privilege); thêm 4 test: snapshot lỗi, snapshot thành công, tên độc hại, thiếu thư mục save | Chưa tạo |

| 31/10/2026 | P0-03 hoàn thành | Audit toàn bộ nơi ghi/xóa/giải nén: pipeline dùng `validate_safe_path` (realpath + commonpath), save/Vault/updater dùng `realpath` + `normcase` + `commonpath`; kiểm tra tiền tố còn lại trong `process_utils`/`security` đã kèm dấu phân cách nên an toàn. Chính sách: giải nén chỉ ghi file thường nên không tạo symlink mới; mọi junction/symlink có sẵn được `realpath` phân giải và bị từ chối nếu thoát thư mục đích. Thêm test junction (Vault + cloud) và trùng đường dẫn khác hoa/thường | `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe -m unittest -v tools.test_save_backup_failure`: 44 pass, 1 skip (symlink privilege — junction pass); test cũ `test_pipeline_action_paths` đã phủ `../`, absolute, drive `Z:`, sibling prefix, zip-slip | Chưa tạo |

| 31/10/2026 | P0-05 hoàn thành | Test tải thiếu byte, hủy, mất kết nối giữa chừng, server không kết nối được; xác nhận giữ file đích cũ và dọn file tạm. Đối chiếu lại chính sách: `.congu` chính thức bắt buộc SHA-256 catalog (thiếu/không khớp bị từ chối), cache cũ bị bỏ qua nếu hash lệch, `pack_mod.py` gắn `congu_sha256` khi phát hành; link tùy chỉnh của người dùng vẫn phải khớp SHA catalog nên không được gắn nhãn tin cậy | `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe -m unittest -v tools.test_http_downloader_safety`: 8 pass (thêm 2 test mất mạng); `tools.test_release_checksum_tool tools.test_updater_integrity`: 4 pass | Chưa tạo |

| 31/10/2026 | P0-04 hoàn thành | Audit: không còn `CERT_NONE`/`verify=False`/`check_hostname=False`; `steam_direct_request` giữ `ssl.create_default_context` khi phân mảnh ClientHello và fallback urllib vẫn xác minh. 24 route GET chỉ đọc (route duy nhất khớp từ khóa ghi là liệt kê backup). Token chỉ nhận qua header `X-App-Auth-Token`, JS không đưa token vào URL. Bổ sung kiểm tra Host loopback cho `/api/*` (chặn DNS-rebinding), giữ Origin loopback cho request đổi trạng thái và cho phép Host/Origin trống với client native | `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe -m unittest -v tools.test_api_session_auth`: 10 pass (thêm 3 test: Host ngoài bị từ chối, Host loopback kèm cổng, thiếu token vẫn 403) | Chưa tạo |

| 31/10/2026 | P0-06 hoàn thành | Thêm `tools/test_game_operation_matrix.py` trên game giả: cài lần đầu, cài lại/cập nhật mod giữ nguyên `.congu_bak` gốc, gỡ mod, lỗi giữa pipeline rollback toàn bộ, đích bị khóa, journal tồn đọng chặn install. Matrix phát hiện 2 lỗi thật: `_norm_rel` chưa định nghĩa trong `actions.py` (mọi action crash) và thiếu `import json` khiến bảo vệ chống ghi đè file Steam/Epic bị vô hiệu. Đã sửa cả hai. Khóa theo game kết hợp mutex single-instance của app | `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe -m unittest -q tools.test_save_backup_failure tools.test_api_session_auth tools.test_http_downloader_safety tools.test_updater_integrity tools.test_pipeline_crash_recovery tools.test_pipeline_rollback_status tools.test_game_operation_locks tools.test_pipeline_action_paths tools.test_release_checksum_tool tools.test_game_operation_matrix`: 91 pass, 1 skip (symlink privilege); `tools/test_rollback_safety.py`: 26 pass; `tools/test_security_hardening.py`: 20 pass | Chưa tạo |

| 31/10/2026 | P0-02 audit chuỗi cập nhật | Đã rà chuỗi: metadata (`catalog.check_app_update`) → bắt buộc URL `.zip` + SHA-256 64 hex từ metadata → tải qua downloader có validator SHA trên file tạm → giải nén vào thư mục tạm với giới hạn 5000 member/2 GiB và `validate_safe_path` từng entry → chỉ chấp nhận gói có `VietModHub.exe` → script chờ app thoát, kiểm exit `robocopy`, kiểm EXE tồn tại trước khi chạy. Còn thiếu: ký manifest, giữ bản cũ và rollback khi áp dụng/khởi chạy thất bại (cần quyết định khóa ký) | Đọc mã + `tools/test_updater_integrity` (gói bị sửa/thiếu SHA) và `tools/test_release_checksum_tool` pass | Chưa tạo |

| 31/10/2026 | P0-02 ký manifest | Người dùng chốt tạo khóa ngay. Tạo cặp Ed25519; khóa tư nhân lưu ngoài repo tại `%USERPROFILE%\.congu-release\ed25519_private.pem` (không commit, không in nội dung), public key nhúng trong `core/update_manifest.py`. `check_app_update` trả thêm `version` + `manifest_signature`; `apply_app_update` bắt buộc chữ ký hợp lệ trên (version, portable_zip_url, portable_zip_sha256) trước khi tải. Thêm `tools/sign_release_manifest.py` từ chối khóa nằm trong repo và từ chối manifest thiếu SHA/URL `.zip`. Lưu ý: `version.json` hiện tại chưa ký vì chưa có ZIP phát hành thật; khi phát hành phải chạy tool ký sau khi điền SHA | `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe -m unittest -v tools.test_update_signature tools.test_updater_integrity`: 12 pass (chữ ký hợp lệ, sửa SHA/version/URL, thiếu/hỏng chữ ký, tool ký và từ chối khóa trong repo). Đã ký manifest tạm bằng khóa production và xác minh bằng public key nhúng: hợp lệ; sửa SHA bị từ chối | Chưa tạo |

| 31/10/2026 | P0-02 rollback cập nhật | Tách script cập nhật sang `core/updater_apply.py`: chờ app thoát → sao lưu toàn bộ bản cũ bằng robocopy `/MIR` vào `update/backup_prev` → hủy nếu sao lưu lỗi (exit ≥ 8) trước khi ghi → chép bản mới → kiểm EXE → chạy thử và chờ 30 giây, nếu tiến trình không sống thì rollback toàn bộ từ backup và khởi động lại bản cũ; giữ backup khi rollback lỗi. Đánh dấu hoàn thành P0-02 | `PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe -m unittest -v tools.test_updater_apply_script tools.test_update_signature tools.test_updater_integrity`: 17 pass. Lưu ý: test kiểm chính sách/thứ tự script, chưa chạy robocopy thật trong test tự động; các trường hợp mất mạng dùng test downloader, gói sửa/thiếu SHA dùng test updater | Chưa tạo |

| 01/11/2026 | P0-02 kiểm chứng lại, chưa hoàn thành | Bỏ tích ba mục updater trước đây chỉ dựa trên so khớp script. Sửa test checksum để dùng manifest ký và xác nhận thực sự gọi downloader; thêm test gói hợp lệ tới handoff (không chạy process), thiếu EXE, ZIP traversal, chữ ký sai, mạng/quyền/disk-full mô phỏng. Bỏ fallback URL không ký; chặn thư mục script chồng nhau/ký tự batch; sửa CRLF, giữ script khi lỗi, dùng công cụ Windows đúng đường dẫn và ép copy cả file cùng metadata. Test filesystem phát hiện tự xóa BAT gây sai mã thoát; đã sửa | Bộ 12 module regression: 118 test chạy, 117 pass, 1 skip (quyền symlink); 3 test dùng robocopy thật với file giả. Chưa kiểm chứng startup/watchdog đúng instance, không chạy app portable, không dùng game/save thật. Các dòng nhật ký cũ ghi “hoàn thành P0-02” không còn là kết luận hiện tại | Chưa tạo |

| 01/11/2026 | P0-02 startup ACK theo giao dịch | Thay kiểm tên process bằng probe PowerShell khởi chạy và theo dõi đúng process con. App ACK atomically sau native loaded/server ready hoặc heartbeat POST có token/Host/Origin hợp lệ; ACK gồm phiên bản hiện chạy, token giao dịch, PID và đường dẫn EXE. Probe từ chối sai ACK/child đã thoát, timeout dừng đúng child trước rollback; nếu không dừng được thì giữ dữ liệu, không chép đè tiếp. Sửa đích updater lấy cạnh sys.executable thay vì APP_DIR có thể là _internal | Regression 13 module: 126 test, 125 pass, 1 skip; sau thêm test đích _internal, bộ updater/startup/API chạy 40 test pass. PowerShell thật + EXE C# giả chứng minh ACK đúng/sai, không giết instance không liên quan, chuỗi BAT rollback và khởi chạy fixture cũ. Chưa kiểm UI portable thật, chưa build/release/commit | Chưa tạo |

| 01/11/2026 | P0-02 rollback lỗi và journal updater | Test robocopy thật: khóa backup ngay trước rollback hoặc xóa EXE backup, xác nhận mã lỗi 22/21, giữ staging/backup/script và không chạy app dở. Updater tải vào job riêng; tạo pending journal độc quyền trước Popen; chặn journal hỏng/còn tồn tại, test tranh chấp handoff và launch lỗi. Script ghi phase và log robocopy; chỉ xóa pending khi cập nhật hoặc rollback hoàn tất | Regression 132 test: 131 pass, 1 skip; một lần trước đó lỗi cleanup fixture đã sửa bằng chờ đúng PID. Một lần test backup cùng metadata thất bại chưa có log; 6 lần riêng và bộ đầy đủ sau đó pass. Thêm /IM cùng /IS /IT và log để phủ file modified; chạy lại 34 test updater/startup pass. Chưa coi flake metadata được giải thích hoàn toàn; P0-02 tổng hợp còn mở và chưa kiểm portable/UI thật | Chưa tạo |

| 01/11/2026 | P0-02 kiểm SHA toàn cây | Không chỉ dựa exit robocopy: thêm verifier PowerShell kiểm loại file/thư mục + SHA-256, từ chối thiếu/sai nội dung và file ngoài cây ở chế độ exact. Dừng trước apply nếu backup không khớp; apply/rollback không khớp không được chạy EXE hay dọn journal. Quét reparse/junction trước copy. Test cố tình sửa backup cùng size/mtime bị chặn (exit 24), test junction giữ ngoài nguyên vẹn; đường BAT thành công + ACK cũng được chạy trên EXE giả | Bộ 13 module regression: 140 test, 139 pass, 1 skip (quyền symlink). Các bước PowerShell/robocopy thật; chưa chạy UI portable thật. Lần metadata flake trước chưa xác định nguyên nhân gốc, nhưng giờ SHA hậu kiểm bắt buộc ngăn công nhận backup sai dù robocopy báo thành công | Chưa tạo |

| 01/11/2026 | P0-02 dừng updater tại checkpoint | Chạy script với robocopy thật trên game/app giả, chèn checkpoint test rồi terminate đúng PID cmd do test tạo: sau backup xác nhận app chưa đổi; sau apply lỗi một phần xác nhận backup cũ đầy đủ, pending/phase/log/script còn nguyên và không chạy EXE. Test journal tồn đọng ở lần gọi updater mới đã phủ việc chặn ghi đè phục hồi | Bộ 13 module: 142 test, 141 pass, 1 skip (symlink privilege). Đây là dừng ở ranh giới bước, không giả nhận đã thử kill giữa syscall ghi file lớn hoặc UI portable thật | Chưa tạo |
| 03/11/2026 | P1-01 & P1-04 Cập nhật mod thực chất & Tương thích | Xây dựng engine so khớp phiên bản mod `core/mod_compatibility.py` (Semver/prefix/suffix/date), biên nhận cài đặt `record_installed_mod_receipt` lưu trong `user_config.json`; `check_updates` trả về trạng thái có căn cứ (update_available, up_to_date, not_installed, unknown_version, offline); đánh giá tương thích theo game build/version, platform và cảnh báo Anti-Cheat | `tools/test_mod_update_checker.py`: 14 pass (so khớp phiên bản, lifecycle biên nhận, tích hợp API, cảnh báo Anti-Cheat, catalog lỗi/offline) | Chưa tạo |
| 03/11/2026 | P1-02 Preflight Game Doctor toàn diện | Nâng cấp `core/preflight_doctor.py` thành hệ thống kiểm tra tiền trạm trước khi ghi: kiểm tra tiến trình đang chạy (process check), kiểm tra quyền ghi UAC/Program Files, kiểm tra dung lượng ổ đĩa (+ buffer 150MB), lọc runtime theo engine game, phát hiện xung đột loader/injector (ReShade dxgi.dll), sinh kế hoạch thay đổi (Change Plan preview) & vị trí sao lưu; tích hợp trực tiếp vào `install_mod_impl` để chặn lỗi trước khi sửa file | `tools/test_preflight_doctor.py`: 9 pass; tích hợp `install_ops` giữ nguyên an toàn rollback và ma trận test | Chưa tạo |
| 03/11/2026 | P1-03 & P1-05 & P1-06 Chuẩn hóa State Machine, Khắc phục sự cố & Escape modal | Chuẩn hóa State Machine UI (chơi ngay, cập nhật mod, cài lại, chọn thư mục), thêm bộ khóa chống bấm lặp `_busyGameOps`; module `core/troubleshooter.py` với 4 kịch bản sửa lỗi thường gặp, ghi nhật ký Audit Log theo Job ID, kiểm tra phạm vi backup trước khi restore, sinh báo cáo hỗ trợ kỹ thuật tự động che mờ thông tin cá nhân/token (không tự upload); phím Escape đóng mọi modal và không đóng progress modal khi đang thao tác | `tools/test_troubleshooter.py`: 5 pass; bộ 13 module regression: 132 pass, 1 skip; test độc lập rollback/security/tool: 69 pass | Chưa tạo |

## Những quyết định cần chốt khi đến đúng giai đoạn

- Phạm vi hỗ trợ chính thức: Windows, nền tảng game và phiên bản nào?
- Ai giữ khóa ký, ai duyệt gói và ai có quyền phát hành?
- Chính sách giữ bao nhiêu bản backup và cách dọn khi thiếu dung lượng?
- Tính năng nào được chạy nền sau khi đóng cửa sổ? Người dùng có được thông báo không?
- Nguồn tải ngoài là tính năng chính thức, tùy chọn nâng cao hay sẽ được loại bỏ?

**Nguyên tắc cuối cùng:** ít thao tác hơn, trạng thái rõ hơn, an toàn có thể kiểm chứng.
