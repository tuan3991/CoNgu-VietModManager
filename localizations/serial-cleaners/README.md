# Serial Cleaners — nguồn Việt hóa tiếng Việt

Bản xuất **bản dịch + script staging + tài liệu**, dành cho **Steam build10874768** (depot1337921, manifest4624538395234988795), Unity2020.3.36f1/IL2CPP/Addressables1.18.19.

**Đây không phải gói cài bản vá.** Không chứa executable, bundle, font/atlas, video, bản sao game gốc, save/config cá nhân, log nguyên bản hoặc thông tin tài khoản. Không sửa mã ứng dụng CỔ NGỮ và không thêm game vào catalog.

## Nội dung

- [raw_strings.json](raw_strings.json):3951bản ghiI2, gồm3947TRANSLATEđãduyệt và4PROTECT. Giữsource/termkey/địachỉ/hash đểcóthểđốichiếu antoàn.
- [research_scope/outside_authored_strings.json](research_scope/outside_authored_strings.json):412địachỉngoàiI2,388APPROVED/21PROTECTED/3NEEDS_REVIEW;386trườngthựcsựthayđổi,2headerLQAgiữnguyên.
- [GAME_BIBLE.md](GAME_BIBLE.md):bối cảnh, xưng hô và thuật ngữ. Tham chiếu nghiên cứu nội bộ trong tài liệu này không được phân phối trong bản xuất.
- [original_manifest.json](original_manifest.json), [allowed_files.json](allowed_files.json):hash/bộđịachỉcủabuildđãkiểm;**khôngcóbytesgamegốc**.
- [reviewed_build_hashes.json](reviewed_build_hashes.json):hash16filebảndựngcục bộ đãQA, đãloạibỏđườngdẫnmáy. Khôngphảimanifestinstaller.
- [qa_summary.json](qa_summary.json):tómtắtQAđãlượcthôngtincánhân, khônggắnkèmlog/screenshotriêngtư.
- [publication_manifest.json](publication_manifest.json):SHA256mọifilethuộcbảnxuấtnguồn.

Bản dịch được soạn trực tiếp trong phiên trợ lý và xử lý bằng Python cục bộ, không gọi API dịch/AI bên ngoài.

## Kiểm tra bản xuất

Python3.11. ChỉbộváUnitycầnUnityPy1.25.4;kiểmtranguồn/testnegativekhôngcầngame.

```powershell
python validate_sources.py
python audit_translation_structure.py
python research_scope/test_patch_outside_i2.py
```

- `validate_sources.py` kiểmsourcehash/NFC/approval/địachỉvàhashbảnxuất.
- BộkiểmcấutrúcI2 phát hiện51cảnhbáotagnguồngốc và14cảnhbáosố/leetspeak đãbiên tậprà;0lỗicấutrúcbắtbụcsửa ởmốcbàngiao.
- TestngoàiI2gồm19casechọnlọc/negative;khôngghiassetgame.

## Script staging, không tự cài game

```powershell
python -m pip install -r requirements-staging.txt
python build_i2_staging.py --out staging/i2_new
```

`build_i2_staging.py` cần người sở hữu game chuẩn bị hai file gốc đúng hash dưới `original/<đường_dẫn_tương_đối>`:bootdata vàlifetimesystems từmanifest. Scriptchỉghivàothưmụcstagingmớitrongproject, khônglaunchgame hoặc cài.

**Không chép đầu ra I2 đơn lẻ vào game:** đây chỉ là text staging, thiếu bước font/material/catalog. Bản đã được nghiệm thu cục bộ có20TMPfonts,245ký tự,24materialreferences và14bundlecatalog; pipeline/fontbinaries đó không được phân phối trong lần đăng nguồn này. Vì vậy repository này **không tái tạo trọn vẹn bản cài đã QA chỉ bằng một lệnh**.

BộvángoàiI2 [patch_outside_i2.py](research_scope/patch_outside_i2.py) nhậnmapđầuvàocomposedtườngminh vàchỉghithưmụcconmới:

```powershell
python research_scope/patch_outside_i2.py --help
```

Nó khóa fulladdress/sourcehash/inventory; chỉ chọnTRANSLATE+APPROVED; mụcREVIEWđượcpromotephảicólýdoconsumer. KhôngtựváXbox/accountidentity/promptmặcđịnh hoặc tênasset. `ready_to_patch=false`tronginventoryngoàiI2làmetadata giai đoạn soạn; selectortrên dùngrole+approval+consumerreason vàcónegative tests.

## QA đã xác lập và giới hạn

- Bản dựng cục bộ được cài và đối chiếu208file:16patch+192gốc đúnghash.
- Người dùng cho phép một phiênQA mới sau khi lầnđầu bịSteamchờxácnhận;7ảnhhợplệcùngphiên, sampleVNstartuphiểnthịdấurõ. Người dùng xác nhận bản dịch hiển thịổn. Steamghi game thoát0.
- Không thấyfatalassetload/CRCexceptiontronglogquan sát. FMODlistener/NotoKRatlasreadabilitywarnings cũngcótrênnguyênbản;khôngđượcche thành“khôngcócảnhbáo”.
- **Chưa chơi kiểm hết mọi màn/DLC, font fallback và bố cục.** Dấughépfontcáchđiệucònexperimental.
- Chữ trong hình/video chưa đượcOCR/dịchđầyđủ. Literalnativechưachứngminhconsumer khôngváhàngloạt.
-5payloadbiểuthứcngoặcvuông vàmảnhchữbịche giữnguyêncóchúthích;3mụcngoàiI2heldREVIEWkhôngvá. KhôngtuyênbốViệthóa100%toàngame.
- Bảncài thaycộtEnglish:chọnEnglishđểdùngVN. Steamupdate/verifycóthểkhôiphụcbảngốc. Khôngápdụnghashlạ/buildkhác.

## Quyền và phân phối

Tên game, chuỗi nguồn và tài nguyên gốc thuộc chủ sở hữu tương ứng. Bản xuất này chỉ cung cấp dữ liệu dịch/địa chỉ kiểm chứng và script; **không cấp lại quyền đối với tài nguyên game**. Không thêm giấy phép mã nguồn chung cho nội dung dịch/nguồn khi chưa có quyết định của chủ repository.

Không upload bundle/font/executable hoặc bất kỳ dữ liệu tài khoản nào khi bổ sung nội dung sau này. Tạo gói patch tải về và cập nhật catalog là nhiệm vụ riêng, cần kiểm thử cài/gỡ và quyền phân phối phù hợp.
