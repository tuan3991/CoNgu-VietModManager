Mục tiêu: Việt hóa hoàn chỉnh 100% tựa game tại: [ĐƯỜNG_DẪN_GAME]

[QUY TẮC ĐIỀU PHỐI CỐT LÕI - CƠ CHẾ CHỐNG LÀM TẮT (BẮT BUỘC TUÂN THỦ)]
1. Không làm gộp, không nhảy cóc: Bạn phải thực thi tuần tự từng giai đoạn từ Bước 0 đến Giai đoạn 5.
2. Hồ sơ bằng chứng (`PROGRESS.md`): Ngay khi bắt đầu, hãy tạo file `PROGRESS.md` tại thư mục làm việc. Kết thúc MỖI giai đoạn, bạn BẮT BUỘC phải ghi số liệu bằng chứng thực tế của giai đoạn đó vào `PROGRESS.md` theo đúng yêu cầu ở mục `[CHỐT CHẶN NGHIỆM THU]` cuối mỗi giai đoạn.
3. Cấm đóng gói khi chưa đủ bằng chứng: Tuyệt đối không chạy `pack_mod.py` ở Giai đoạn 5 nếu bất kỳ mục nào trong `PROGRESS.md` chưa đạt trạng thái `PASS` 100%.

---

[BƯỚC 0 - NẠP BỐI CẢNH HỆ THỐNG CỔ NGỮ (BẮT BUỘC DÀNH CHO AGENT MỚI)]
Trước khi thực hiện bất kỳ thao tác nào, hãy đọc ngay tệp tài liệu kiến trúc tại thư mục dự án chính:
- Đường dẫn thư mục hệ thống CỔ NGỮ (VietModHub): [ĐIỀN_ĐƯỜNG_DẪN_THƯ_MỤC_VIETMODMANAGER_CỦA_BẠN, VD: C:\Users\tuan3\...\VietModManager]
- Hãy đọc file `ARCHITECTURE.md`, `games.json`, `pack_mod.py` và `app.py` trong thư mục trên để nắm rõ 100% kiến trúc container `.congu` V2, cơ chế Data-Driven Action Pipeline (`install_steps` / `uninstall_steps`), Streaming Binary Diff (`tools/xdelta3.exe`, `hdiffz.exe`, `hpatchz.exe`) và cách vận hành của ứng dụng.
Sau khi đã đọc hiểu `ARCHITECTURE.md`, hãy thực hiện tuần tự 5 giai đoạn sau cho game tại [ĐƯỜNG_DẪN_GAME]. TUYỆT ĐỐI KHÔNG nhảy cóc sang bước đóng gói nếu chưa vượt qua Giai đoạn 4:

---

[GIAI ĐOẠN 1: NHẬN DIỆN ENGINE, NGHIÊN CỨU CỐT TRUYỆN & QUÉT SÂU 100% NGUỒN TEXT]
1. Xác định chính xác Engine của game (Unity Mono / Unity IL2CPP / Unreal Engine / Godot / RPG Maker / Custom Engine...) và bảng mã lưu trữ chuỗi gốc (`UTF-8`, `UTF-16`, hay `ANSI / Windows-1252`) để chọn bộ công cụ trích xuất phù hợp.
2. NGHIÊN CỨU GAME TRÊN INTERNET & LẬP HỒ SƠ BẢN ĐỊA HÓA (`GAME_BIBLE.md`):
   - BẮT BUỘC dùng công cụ tìm kiếm (Web Search) tra cứu tên game kèm các từ khóa: `"Steam"`, `"Wiki"`, `"TVTropes"`, `"Characters"`, `"Gameplay"` trước khi đụng vào text.
   - Tạo file `GAME_BIBLE.md` tại thư mục làm việc, ghi rõ 4 thông tin cốt lõi:
     a) Thể loại & Cơ chế Gameplay chính: (VD: Metroidvania, Roguelike, Soulslike, FPS...) để dịch chuẩn thuật ngữ thao tác (VD: trong Platformer thì `Platform` = Bệ đứng/Bậc, `Slide` = Trượt/Lướt, `Dash` = Lướt nhanh, `Objective` = Mục tiêu/Nhiệm vụ).
     b) Tông giọng chủ đạo (Tone) & Độ tuổi (Maturity Rating): Xác định rõ game thuộc nhóm Nghiêm túc/Bi tráng, Đen tối/Bạo lực (18+), Hài hước/Lầy lội, hay Đời thường.
     c) Bảng phân vai & Giọng điệu nhân vật (Character Voice & Pronouns): Liệt kê từng nhân vật chính/phụ, tính cách, cách xưng hô (Tao - Mày, Anh - Em, Ta - Ngươi, Huynh - Đệ, Bố mày - Chúng mày...) và thói quen dùng từ (ăn nói cục súc, chửi thề, lịch thiệp, hay cộc lốc). CẤM dùng "Tôi - Bạn" trong hội thoại.
     d) Bảng Glossary thuật ngữ bất biến: Tên riêng, Địa danh, Phép thuật/Cơ chế đặc thù (VD: `Arcana`), Vật phẩm và Chỉ số hệ thống.
3. Quét vét cạn (Deep Scan) toàn bộ 4 tầng chứa text của game — TUYỆT ĐỐI KHÔNG chỉ quét mỗi file ngôn ngữ chính:
   - Tầng 1 (Localization & DataTables): Toàn bộ `TextAsset`, CSV, JSON, XML, `I2Languages`, `Unity.Localization` StringTables trong `.assets` và `.bundle` (bao gồm cả thư mục `StreamingAssets/aa` Addressables).
   - Tầng 2 (UI Prefab & Scene `m_text`): Quét toàn bộ file `level*`, `sharedassets*.assets`, `resources.assets` để lấy 100% trường `m_text` / `m_Text` bên trong các component `TextMeshProUGUI`, `TextMeshPro`, `UnityEngine.UI.Text` (đây là nơi chứa các nhãn UI cố định như "Player", tiêu đề bảng, thông báo mở khóa...).
   - Tầng 3 (ScriptableObjects / MonoBehaviour Custom Fields): Đọc đệ quy toàn bộ cây `TypeTree` của mọi `MonoBehaviour` trong game để lấy tất cả các trường kiểu `string` chứa tên Kỹ năng, Nội tại, Vật phẩm, Tooltip mô tả (như `Name`, `Title`, `Header`, `Description`, `Tooltip`, `FlavorText`, `Prefix`, `Suffix`...).
   - Tầng 4 (Hardcode & Dynamic Strings trong Binary): Bắt buộc trích xuất chuỗi hiển thị trong `Assembly-CSharp.dll` (dùng `dnlib` / `Mono.Cecil` quét lệnh `ldstr` với game Unity Mono) hoặc `global-metadata.dat` (với game IL2CPP) để bắt hết các chuỗi ghép động hệ thống như `"{0} Damage"`, `" + {0}% Speed"`, `"Locked"`, `"detonates"`...
4. QUY TẮC CẤM BỎ SÓT KHI LỌC CHUỖI (ANTI-SKIP RULES):
   - CẤM dùng điều kiện `if ' ' not in text: continue` làm mất các từ đơn hệ thống (`Player`, `Damage`, `Health`, `Spell`, `Equip`, `Back`, `Confirm`...). Phải đối chiếu từ đơn với từ điển tiếng Anh để trích xuất đầy đủ 100% từ vựng UI đơn lẻ.
   - CẤM bỏ qua các chuỗi có chứa thẻ Rich Text hoặc Icon như `<sprite...>`, `<style...>`, `<link...>`, `<color...>`. Phải trích xuất nguyên chuỗi và dịch phần văn bản hiển thị bên ngoài cặp dấu `< >`.
   - Lưu ý cơ chế Keyword Parser của game: Nếu game dùng từ khóa tiếng Anh trong câu mô tả (như `detonates`, `Damage`) để tra cứu hiệu ứng hoặc tô màu tự động trong code, phải kiểm tra và dịch đồng bộ cả từ khóa gốc lẫn chuỗi hiển thị (hoặc chỉ đổi phần text hiển thị bên trong thẻ `<link="id">Text hiển thị</link>` mà giữ nguyên `id`).

* [CHỐT CHẶN NGHIỆM THU GIAI ĐOẠN 1 -> GHI VÀO `PROGRESS.md`]:
  - Ghi rõ Engine, Bảng mã (Encoding) của file gốc và số lượng chuỗi trích xuất được ở từng tầng: Tầng 1 (`...` chuỗi), Tầng 2 (`...` chuỗi), Tầng 3 (`...` chuỗi), Tầng 4 (`...` chuỗi). Nếu bất kỳ tầng nào bằng `0`, phải giải trình rõ nguyên nhân kỹ thuật trước khi sang Giai đoạn 2.

---

[GIAI ĐOẠN 2: XỬ LÝ TRIỆT ĐỂ FONT CHỮ TIẾNG VIỆT & CHỐNG LỖI FALLBACK / MẤT CHỮ LATIN-1]
1. Chạy script Python tự động kiểm tra toàn bộ file font rời (`.ttf`, `.otf`), Bitmap Font (`.fnt`, `.xml` + `.png`/`.dds`/`.tga`), Unreal Font (`.ufont`/`.uasset`) hoặc `TMP_FontAsset` / `Font` trong các file `.assets` / `.bundle` của Unity xem đã có đủ 134 ký tự tiếng Việt dựng sẵn (cả chữ thường lẫn CHỮ HOA) chưa:
   ```python
   # Mẫu logic bắt buộc chạy để kiểm tra đủ 134 ký tự tiếng Việt (74 chữ thường/gốc + 60 chữ HOA có dấu)
   VN_CHARS = (
       "ăâđêôơưĂÂĐÊÔƠƯ"
       "áàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệóòỏõọốồổỗộớờởỡợúùủũụứừửữựíìỉĩịýỳỷỹỵ"
       "ÁÀẢÃẠẤẦẨẪẬẮẰẲẴẶÉÈẺẼẸẾỀỂỄỆÓÒỎÕỌỐỒỔỖỘỚỜỞỠỢÚÙỦŨỤỨỪỬỮỰÍÌỈĨỊÝỲỶỸỴ"
   )
   assert len(VN_CHARS) == 134
   # 1. Với file .ttf/.otf: dùng fontTools kiểm tra all(ord(ch) in font.getBestCmap() for ch in VN_CHARS)
   # 2. Với Unity TMP_FontAsset (qua UnityPy): đọc m_CharacterTable, lấy tập hợp {item.m_Unicode for item in data.m_CharacterTable} và kiểm tra đủ 100% ord(ch) trong VN_CHARS.
   ```
2. QUY TẮC TOÁN HỌC BẮT BUỘC KHI REBUILD TMP_FONTASSET BẰNG PYTHON:
   * Khi tạo lại Atlas cho TMP_FontAsset, BẮT BUỘC xóa các glyph Latin cũ (U+0020 - U+007E) và sinh lại đồng bộ cả A-Z, a-z, 0-9, dấu câu lẫn 134 ký tự tiếng Việt từ cùng 1 file .ttf (cấm giữ A-Z gốc rồi chỉ chèn thêm chữ có dấu gây lệch độ đậm nhạt).
   * Cập nhật đồng bộ cả 2 bảng `m_GlyphTable` (chứa `m_GlyphRect` và `m_Metrics`) và `m_CharacterTable` (ánh xạ `m_Unicode` -> `m_GlyphIndex`).
   * Cấm co kéo (resize) chữ có dấu theo khung cố định. Bắt buộc tính đường gióng ngang trong `m_Metrics` theo đúng công thức: `ascent, descent = font.getmetrics()`, `left, top, right, bottom = font.getbbox(ch)` -> `m_HorizontalBearingY = ascent - top`, `m_HorizontalBearingX = left`, `m_HorizontalAdvance = font.getlength(ch)`.
   * Áp dụng biến đổi khoảng cách `scipy.ndimage.distance_transform_edt` chuẩn hóa theo `m_AtlasPadding` (spread) để tạo biên SDF mượt (tâm cạnh chữ = 128).
3. QUY TẮC BẮT BUỘC VỚI BITMAP FONT, CUSTOM ENGINE & BẪY BẢNG MÃ LATIN-1 (CHỐNG MẤT CHỮ TÀNG HÌNH):
   * Cảnh giác bẫy Latin-1 (`Windows-1252` / `ISO-8859-1`): Các ký tự `á, à, é, è, í, ì, ó, ò, ú, ù, ý, â, ê, ô` nằm trong bảng mã phương Tây `Latin-1` (`U+0080 - U+00FF`) nên font gốc của game luôn hiển thị được, nhưng các ký tự tiếng Việt thuộc `Latin Extended` (`ă, đ, ơ, ư, ắ, ầ, ọ, ạ, ể...` từ `U+0100` trở lên) sẽ bị biến mất hoàn toàn (không hiện cả ô vuông `□`, ví dụ: `"Bắt đầu trò chơi"` bị cụt thành `"Bt u trò chi"`, `"CHỌN"` thành `"CHN"`).
   * Bắt buộc truy vết đúng Font đang gắn trực tiếp trên UI Component (Scene/Prefab/Menu) thay vì chỉ sửa file `.ttf` rời trong thư mục game (vì nhiều game để file `.ttf` rác nhưng UI thực tế lại đọc từ Bitmap Font `.fnt`/`.xml` + `.png`/`.dds`/`.tga` hoặc Pre-baked Font Atlas).
   * Nếu game dùng Bitmap Font (`.fnt`, `.xml`, `.dat` đi kèm ảnh texture): BẮT BUỘC dùng script Python vẽ lại ảnh Font Atlas chứa đủ 134 ký tự `VN_CHARS` và cập nhật lại toàn bộ tọa độ `char id / x / y / width / height / xoffset / yoffset / xadvance` trong file cấu hình font.
   * Nếu Engine của game hoặc file ngôn ngữ chỉ đọc bảng mã 1-byte (`ANSI / Windows-1252`, lọc bỏ mọi ký tự có mã `ord(ch) > 255`):
     - Cách 1: Hook/Patch hàm đọc chuỗi và hàm vẽ chữ trong file binary (`.exe` / `.dll`) sang chuẩn `UTF-8` / `UTF-16`.
     - Cách 2 (Character Remapping): Ánh xạ các ký tự tiếng Việt ngoài bảng `Latin-1` vào các ô mã `0x80 - 0xFF` không dùng tới của bảng `Windows-1252` (như `¤, §, ¨, ©, ª, «, ¬, ®...`), đồng thời vẽ hình dáng chữ tiếng Việt tương ứng vào đúng các ô mã đó trên Font Atlas.
4. QUY TẮC CHỐNG LỖI "CHỮ TEO NHỎ & BAY LƠ LỬNG NHƯ SỐ MŨ" (ANTI-SUPERSCRIPT & BASELINE CALIBRATION):
   * CẤM CHẮP VÁ LỆCH FONT (No Hybrid Patching): Tuyệt đối cấm giữ nguyên các chữ cái gốc (`A-Z, a-z, ò, á, ù`) trên Atlas của game rồi chỉ vẽ chèn thêm các ký tự tiếng Việt thiếu (`ă, đ, ơ, ư, ắ, ầ, ọ, ạ...`) bằng một font khác hoặc kích thước khác, gây ra lỗi chữ mới chèn bị nhỏ tí hon, nét mảnh và bay lơ lửng trên đầu chữ cũ (kiểu `Bắᵗ đầᵘ trò chơⁱ`).
   * BẮT BUỘC ĐO VÀ KHÓA CỨNG CHIỀU CAO PIXEL (Auto-Calibrate Point Size):
     - Trước khi render glyph mới bằng Python (PIL/FreeType), bắt buộc đọc thông số của ký tự chữ cái gốc trong game (lấy chữ `'O'` hoa và `'o'` thường làm chuẩn) để lấy chính xác chiều cao hiển thị thực tế tính bằng pixel (`orig_cap_height = height_of('O')`).
     - Dùng vòng lặp tự động tăng/giảm `font_size` của file `.ttf` tiếng Việt cho đến khi chiều cao thực tế của chữ `'O'` mới (`bbox[3] - bbox[1]`) khớp 100% với `orig_cap_height` của font gốc (sai số tối đa ±1px). Tuyệt đối cấm đoán mò hoặc gán cứng `font_size` mặc định (như 16, 24, 32).
     - Phải render lại ĐỒNG BỘ 100% cả chữ cái không dấu (`A-Z, a-z, 0-9`) lẫn 134 ký tự `VN_CHARS` từ cùng một font `.ttf` ở cùng `font_size` đã đo (và tái tạo lại hiệu ứng viền/stroke/shadow nếu font gốc có viền).
   * BẮT BUỘC CĂN THẲNG ĐƯỜNG GIÓNG CHÂN (Baseline / Y-Offset Alignment):
     - Tuyệt đối cấm gán `yoffset = 0` khi cắt glyph theo khung sát (`tight bounding box`), vì sẽ làm các chữ có dấu bị hút dính lên mép trên cùng của dòng.
     - Công thức bắt buộc cho Bitmap Font (`.fnt` / XML / Custom Atlas): Với `ascent, descent = font.getmetrics()` và `left, top, right, bottom = font.getbbox(ch)`, bắt buộc đặt `width = right - left`, `height = bottom - top`, `xoffset = left`, và **`yoffset = top`** (hoặc `yoffset = base_line - (ascent - top)` theo hệ quy chiếu của file `.fnt` gốc) sao cho chân của các chữ cái tiếng Việt (`ă, ắ, đ, ơ, ư`) nằm thẳng tắp trên cùng một đường kẻ ngang với chân chữ `'a'`, `'o'`, `'B'`, `'T'`.
* [CHỐT CHẶN NGHIỆM THU GIAI ĐOẠN 2 -> GHI VÀO `PROGRESS.md`]:
  - Liệt kê tên chính xác của TẤT CẢ các Font Asset thực tế đang gắn trên UI Menu/HUD của game, định dạng của chúng (`TTF`, `TMP_FontAsset`, hay `Bitmap Font`), và kết quả kiểm tra độ phủ `VN_CHARS` trên từng font (`134/134 PASS`).

---

[GIAI ĐOẠN 3: DỊCH THUẬT BẢN ĐỊA HÓA SÁNG TẠO (TRANSCREATION & CONTEXTUAL LOCALIZATION)]
1. QUY TRÌNH DỊCH BẮT BUỘC VỚI `tools/llm_batch_translator.py` (CẤM DỊCH MÁY RẺ TIỀN):
   * TUYỆT ĐỐI CẤM sử dụng Google Translate API (`googletrans`, `deep-translator`, `translate.googleapis.com`) hoặc bất kỳ công cụ dịch từng từ/từng câu không có System Prompt nào trong script Python.
   * Khi trích xuất toàn bộ chuỗi ra file `raw_strings.json`, BẮT BUỘC giữ kèm trường `key` (Path/Component_Name) theo đúng định dạng: `[{"id": 1, "key": "Tutorial/Controls/Slide", "source": "Slide"}]`.
   * Thực thi tuần tự 3 bước bằng bộ công cụ chuẩn của hệ thống:
     - Bước 3.1: Chạy `python tools/llm_batch_translator.py --mode export-batches --input raw_strings.json --output batches_dir --bible GAME_BIBLE.md` (hoặc `--mode api` nếu dùng Gemini API trực tiếp).
     - Bước 3.2: Đọc `GAME_BIBLE.md` và dịch trực tiếp từng file `batch_*.json` (cụm 40 - 60 dòng liền kề) theo đúng nhãn `category` (`UI_CONTROL`, `DIALOGUE`, `LORE_SYSTEM`) và gợi ý `hint`.
     - Bước 3.3: Chạy `python tools/llm_batch_translator.py --mode merge-batches --input batches_dir --output translated_strings.json` để gộp file và chuẩn hóa Unicode NFC.

2. QUY TẮC XỬ LÝ 3 TẦNG GIỌNG VĂN & CẤP QUYỀN KHẨU NGỮ / CHỬI THỀ:
   * Tầng 1: UI / HUD / Hướng dẫn nút bấm (`UI_CONTROL`):
     - Dịch theo ĐỘNG TỪ THAO TÁC hoặc THUẬT NGỮ GAME THỦ VIỆT ngắn gọn, dứt khoát.
     - CẤM dịch thừa chữ `"trò chơi"` (`Game`) trên các nút Menu chính: `"Start Game"` / `"Play Game"` -> `"Bắt đầu"` hoặc `"Chơi ngay"` (CẤM dịch `"Bắt đầu trò chơi"`), `"Game Options"` -> `"Tùy chọn"` (CẤM dịch `"Tùy chọn trò chơi"`), `"Exit Game"` / `"Quit Game"` -> `"Thoát"` (CẤM dịch `"Thoát trò chơi"`).
     - CẤM dịch mạo từ `a / an / some` hoặc từ thừa: `"Cast a spell"` -> `"Thi triển phép"` / `"Tung phép"` (CẤM dịch `"Truyền một câu thần chú"`), `"Use a health tonic"` -> `"Dùng bình máu"` (CẤM dịch `"Sử dụng một loại thuốc bổ sức khỏe"`), `"Interact with an object"` -> `"Tương tác"` (CẤM dịch `"Tương tác với một đối tượng"`), `"Drop from platform"` -> `"Nhảy xuống bệ"` (CẤM dịch `"Thả từ nền tảng"`).
     - Cảnh giác tối đa với từ đa nghĩa đứng một mình: `"Objective"` = `"Mục tiêu / Nhiệm vụ"` (CẤM dịch `"Khách quan"`), `"Slide"` = `"Trượt / Lướt"` (CẤM dịch `"Cầu trượt"`), `"Back"` = `"Quay lại"` (CẤM dịch `"Lưng"`), `"Chest"` = `"Rương"` (CẤM dịch `"Ngực"`).
   * Tầng 2: Hội thoại, Độc thoại & Phân cảnh cao trào (`DIALOGUE` - Cho phép văng tục/chửi thề đúng chất game):
     - Bám sát cảm xúc của phân cảnh (đang bị truy sát, đánh trùm, cãi lộn, phản bội hay trêu chọc) và tính cách nhân vật trong `GAME_BIBLE.md`.
     - ĐƯỢC PHÉP VÀ KHUYẾN KHÍCH dùng khẩu ngữ gắt, tiếng lóng, chửi thề tự nhiên bằng tiếng Việt (`mẹ kiếp`, `khốn kiếp`, `chết tiệt`, `đéo`, `vãi cả...`, `cút xéo`, `thằng chó`, `con đĩ`, `bố mày`...) khi câu gốc có sắc thái chửi thề (`fuck`, `shit`, `damn`, `hell`, `bastard`, `bitch`, `asshole`, `screw this`...) hoặc khi nhân vật thuộc tầng lớp tội phạm, lính đánh thuê, kẻ thù hung hãn.
     - Điều chỉnh độ nặng nhẹ theo ngữ cảnh:
       + Cảnh ngạc nhiên/bực bội nhẹ: `"What the hell?"` -> `"Cái quái gì thế này?"` / `"Chuyện đéo gì vậy?"`
       + Cảnh chiến đấu/tức giận: `"Get the fuck out of my way!"` -> `"Cút mẹ mày ra chỗ khác!"` / `"Tránh xác ra!"`
       + Cảnh tuyệt vọng/hoảng loạn: `"We're screwed!"` -> `"Xong đời rồi!"` / `"Toang thật rồi!"`
   * Tầng 3: Mô tả hệ thống, Nhật ký & Lore (`LORE_SYSTEM`):
     - Đập bỏ cấu trúc ngữ pháp câu tiếng Anh, nắm lấy ý chính rồi viết lại bằng câu tiếng Việt mạch lạc, gãy gọn.
     - Ví dụ: Thay vì dịch word-by-word `"Objectives show Rose's current task in the form of a tarot card reading, as well as all Arcana relevant to completing your goal"` thành `"Mục tiêu cho thấy nhiệm vụ hiện tại của Rose dưới hình thức đọc lá bài tarot, cũng như tất cả các Arcana liên quan đến việc hoàn thành mục tiêu của bạn"`, PHẢI viết lại thành: `"Mục tiêu hiển thị nhiệm vụ hiện tại của Rose dưới dạng một trải bài Tarot, kèm theo các lá Arcana cần thiết để hoàn thành hành trình."`

3. BỘ LỌC CHỐNG DỊCH WORD-BY-WORD (ANTI-CALQUE RULES):
   * CẤM dùng các cấu trúc câu dịch máy: `"dưới hình thức..."`, `"cũng như tất cả..."`, `"nếu bạn cảm thấy mình bị..."`, `"một cái gì đó"`, `"nó đã bị..."`.
   * Lược bỏ đại từ sở hữu thừa thãi của tiếng Anh (`your goal`, `your health`, `my hand` -> dịch là `"mục tiêu"`, `"máu"`, `"tay"` thay vì lúc nào cũng kè kè chữ `"của bạn"`, `"của tôi"`).
   * Bảo toàn 100% các biến, mã màu, thẻ điều khiển (`{0}`, `%s`, `\n`, `<color=...>`, `<sprite...>`).
   * Chuẩn hóa Unicode dựng sẵn (`unicodedata.normalize('NFC', text)`) và lưu chuẩn UTF-8.

---

[GIAI ĐOẠN 4: TỰ KIỂM ĐỊNH ĐỘC LẬP (INDEPENDENT AUTOMATED QA GATE)]
1. Audit văn phong, Toàn vẹn thẻ & Quét lỗi Word-by-Word trước khi ghi vào game (BẮT BUỘC):
   * Chạy lệnh kiểm định văn phong tự động:
     `python tools/style_and_calque_audit.py translated_strings.json`
   * Script sẽ kiểm tra khớp 100% số lượng thẻ `{0}`, `%s`, `<sprite...>`, `<link...>`, `<color...>` và quét toàn bộ các dấu hiệu dịch máy / dịch sai ngữ cảnh UI (`"Khách quan"`, `"Cầu trượt"`, `"Nền tảng"`, `"Lưng"`, `"một câu thần chú"`, `"một loại thuốc"`, `"tương tác với một đối tượng"`, `"dưới hình thức"`, đại từ `"Tôi - Bạn"` trong lời thoại...).
   * Nếu script trả về bất kỳ lỗi nghiêm trọng hoặc cảnh báo Word-by-Word nào (Exit Code != 0), BẮT BUỘC phải biên tập lại câu đó cho tự nhiên rồi chạy lại script đến khi đạt 0 lỗi mới được ghi vào file game.
   * Tự đọc lại tối thiểu 50 dòng UI/Tutorial và 50 dòng Hội thoại ngẫu nhiên, đối chiếu với `GAME_BIBLE.md` để đảm bảo câu văn nghe đúng chất người Việt nói chuyện và đúng khí chất nhân vật.

2. Audit độc lập trực tiếp trên Binary, Assets & Đối chiếu Bảng Glyph Font (CẤM chỉ kiểm tra trên file JSON trung gian):
   * Sau khi đã ghi bản dịch sạch lỗi vào các file `.assets`, `level*`, `.bundle` và `.dll`/`global-metadata.dat`, bắt buộc chạy script `independent_binary_audit.py` mở trực tiếp các file game vừa đóng gói để thực hiện 2 bài kiểm tra:
     - Kiểm tra độ phủ ngôn ngữ: Quét lại toàn bộ `m_text` (TMP), `MonoBehaviour` strings và `ldstr` trong `.dll`. Liệt kê bất kỳ chuỗi nào (kể cả từ đơn UI như `Player`, `Damage` hoặc chuỗi chứa thẻ `<sprite>`, `<link>`) vẫn còn là từ vựng tiếng Anh. Độ phủ thực tế phải đạt >= 99.8%.
     - Kiểm tra chéo Text-to-Font Glyph (Chống tàng hình chữ): Lấy tập hợp toàn bộ ký tự xuất hiện trong bản dịch (`used_chars = set("".join(translated_texts))`), đối chiếu trực tiếp với bảng `CharacterTable` / `Cmap` / `.fnt` của TẤT CẢ các Font đang được gắn vào UI Component của game. Nếu bất kỳ ký tự nào (đặc biệt là nhóm ngoài bảng `Latin-1` như `ă, đ, ơ, ư, ắ, ầ, ọ, ạ, ể...`) chưa có mặt trong bảng Glyph của Font UI hoặc bị lưu sai bảng mã (ANSI/Latin-1 làm mất byte UTF-8) -> Báo lỗi đỏ (Exit Code != 0) và BẮT BUỘC quay lại Giai đoạn 2 để sửa Font/Encoding ngay lập tức.
     - Kiểm tra toán học Tỷ lệ kích thước & Đường gióng chân (Glyph Scale & Baseline Check): Trong script kiểm định Font, bắt buộc lấy thông số `height` và vị trí đáy (`yoffset + height` đối với Bitmap Font, hoặc `m_HorizontalBearingY - m_Height` đối với TMP) của nhóm chữ cái tiếng Việt mở rộng (`ơ, đ, ă, ư`) so sánh trực tiếp với nhóm chữ cái cơ bản (`o, d, a, u`). Nếu chiều cao của `'ơ'` lệch quá 15% so với `'o'`, hoặc vị trí chân chữ lệch nhau quá 2 pixel -> Báo lỗi đỏ `FAIL: GLYPH SCALE OR BASELINE MISALIGNMENT` (Exit Code != 0) và bắt buộc quay lại Giai đoạn 2 render lại Font.
3. Smoke Test thực tế & Đối chiếu OCR từng chữ (Menu + In-game UI):
   * Cài bản dịch vào thư mục game, khởi chạy tiến trình game ở chế độ cửa sổ (non-blocking), chụp ảnh màn hình cả Menu chính lẫn giao diện UI/Sách kỹ năng.
   * BẮT BUỘC dùng Vision đọc từng chữ hiển thị thực tế trên ảnh chụp màn hình và đối chiếu 1:1 với chuỗi trong `translated_strings.json` để xác nhận 4 tiêu chí:
     (1) Không còn sót chữ hệ thống tiếng Anh (`Player`, `Damage`, `Spell`...).
     (2) Các câu mô tả có gắn thẻ `<sprite>`/`<link>` không bị tàng hình hay mất chữ.
     (3) Font hiển thị đẹp, không lỗi ô vuông (`□`), không đè chữ hay mất dấu chữ HOA.
     (4) TUYỆT ĐỐI KHÔNG bị lỗi "nuốt/rụng ký tự tiếng Việt ngoài bảng Latin-1" (Ví dụ: chỉ hiện các chữ `á, ò, ù, ê, ô` nhưng mất sạch các chữ `ă, đ, ơ, ư, ắ, ầ, ọ, ạ...` làm chữ `"CHỌN TRÒ CHƠI"` bị biến thành `"CHN TRÒ CHI"`, `"Bắt đầu"` thành `"Bt u"`, `"Quay lại"` thành `"QUAY LI"`). Nếu phát hiện thiếu bất kỳ chữ cái nào trên ảnh chụp màn hình so với bản dịch, TUYỆT ĐỐI CẤM chuyển sang Giai đoạn 5.
     (5) TUYỆT ĐỐI KHÔNG bị lỗi "chữ to chữ nhỏ / chữ bay lơ lửng như số mũ" (Superscript/Baseline Bug): Soi kỹ các dòng chữ có dấu trên ảnh chụp màn hình (như `"CHỌN TRÒ CHƠI"`, `"Bắt đầu"`, `"Tùy chọn"`, `"Quay lại"`). Nếu các ký tự tiếng Việt (`Ọ, Ơ, ắ, đ, ầ, ơ, Ạ`) bị nhỏ hơn các chữ cái đứng cạnh, khác độ dày nét chữ, hoặc bị đẩy cao lên phía trên như số mũ thay vì đứng phẳng chân trên cùng một đường thẳng ngang, BẮT BUỘC đánh trượt (`FAIL`) và quay lại Giai đoạn 2 sửa lại `font_size` + `yoffset`/`BearingY`.

* [CHỐT CHẶN NGHIỆM THU GIAI ĐOẠN 4 -> GHI VÀO `PROGRESS.md`]:
  - Ghi rõ kết quả chạy `style_and_calque_audit.py` và `independent_binary_audit.py` (Exit Code = 0).
  - Bảng đối chiếu OCR 1:1: BẮT BUỘC gõ lại nguyên văn từng chữ đọc được trên ảnh chụp màn hình Menu đặt cạnh chuỗi gốc trong `translated_strings.json` (VD: `Ảnh chụp màn hình: "Bắt đầu" == Bản dịch JSON: "Bắt đầu" -> PASS`).

---

[GIAI ĐOẠN 5: XUẤT BẢN, ĐỒNG BỘ AVATAR & ĐÓNG GÓI LÊN HỆ THỐNG CỔ NGỮ]
(CHỈ ĐƯỢC PHÉP THỰC THI KHI CẢ 4 CHỐT CHẶN TRONG `PROGRESS.md` ĐỀU ĐẠT `PASS` 100%)
1. Lưu 1 bản dự phòng vào: `C:\Users\tuan3\Documents\Viethoagame`
2. Tự động định danh & lấy Avatar chuẩn cho game (kể cả game lẻ / game tự cài ngoài Steam):
   * Quét trong [ĐƯỜNG_DẪN_GAME] tìm file `steam_appid.txt`, `steam_emu.ini`, `tenoke.ini`, `rune.ini`, `onlinefix.ini` hoặc đọc dòng thứ 2 của `*_Data/app.info` (với game Unity) và làm sạch tên thư mục/file `.exe` (xóa hậu tố `-Win64-Shipping`, `Repack`, `Portable`, `v1.x`...).
   * Dùng Python gọi API `https://store.steampowered.com/api/storesearch/` và `appdetails` để lấy chính xác `steam_appid`, tên thương mại chuẩn, nhãn thể loại (genre) và kiểm tra URL ảnh Poster dọc `library_600x900_2x.jpg` / `library_600x900.jpg` (nếu game mới trên Steam dùng URL chứa mã hash riêng thì lấy luôn URL ảnh kèm hash từ API và lưu cache về máy).
3. Di chuyển vào thư mục `VietModManager`, chạy `pack_mod.py` theo đúng chuẩn trong `ARCHITECTURE.md` để đóng gói container `.congu` V2 (hoặc tạo `patch_binary` `.diff` nếu tệp gốc lớn), tự động kiểm tra chéo (Cross-Validation) và cập nhật `congu_sha256`, `steam_appid`, link ảnh bìa cùng `install_steps` / `uninstall_steps` vào `games.json` rồi đẩy lên GitHub.
4. Kiểm tra tính năng Chọn lại Avatar & Tự chạy `app.py` để nghiệm thu:
   * Kiểm tra trong `app.py` và `static/index.html`: nếu chưa có nút "Tìm & Chọn lại game" trên từng thẻ game (cho phép tìm trực tiếp từ danh sách `games.json` và Steam Store để đổi lại đúng Poster ngay lập tức khi ảnh tự động bị lệch) thì bổ sung ngay vào code.
   * Tự động thêm [ĐƯỜNG_DẪN_GAME] vào thư viện đã cài đặt của ứng dụng và chạy `python app.py` (chạy ngầm non-blocking) mở cửa sổ CỔ NGỮ lên để kiểm tra trực quan xem thẻ game mới đã hiển thị đúng Poster dọc, nhãn thể loại và trạng thái "ĐÃ CÀI ĐẶT" hay chưa.