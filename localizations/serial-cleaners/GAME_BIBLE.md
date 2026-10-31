# Serial Cleaners — hồ sơ Việt hóa

## Phạm vi và tông giọng
Game hành động lén lút dọn hiện trường, bối cảnh thế giới ngầm New York thập niên 1990. Bốn nhân vật kể lại các phi vụ trong đêm giao thừa 1999. Giữ màu sắc noir, bạo lực hư cấu, hài đen và lời thoại đường phố. Không tẩy nhẹ tiếng chửi; UI ngắn gọn, rõ thao tác. Đây là hồ sơ nháp dựa trên dữ liệu game, bổ sung khi dịch hội thoại.

## Nhân vật và xưng hô
- Bob: tay dọn dẹp kỳ cựu, đàn anh. Giữ tên Bob. Với đàn em mặc định tôi/cậu, ngữ cảnh căng thẳng hoặc thân thiết có thể tao/mày theo nguyên tác.
- Lati: nghệ sĩ graffiti, trẻ, nhanh nhẹn; giữ tên Lati.
- Psycho: dùng cưa máy, bốc đồng; giữ biệt danh Psycho.
- Vip3r/Viper: hacker, giữ đúng cách viết tên từ nguồn.
- Người chơi trong hướng dẫn: bạn; mệnh lệnh UI thường lược chủ ngữ.
- Đã truy graph cho 1.369 term: `research/dialogue_speaker_map.json`, speaker lấy qua Actor node nối vào DialogueNodeInstance (không lấy default Bob nếu có actor connection). 6 term đa speaker/11 conflict bindings giữ tập speaker, không mặc định người đầu.
- Bob = Robert; Psycho = Hal/Haldor; Lati = Latisha; Vip3r/Viper = Erin. Giữ tên tương ứng nguyên bản.
- Bob với Lati/Erin: tôi/cô; Bob với Hal: tôi/cậu (đôi khi gọi con trai/các cháu để diễn sắc thái đàn anh). Lati/Erin với Bob: em/anh ở đoạn thân tình; chuyển tôi/anh nếu căng thẳng và đối đầu. Lati↔Erin: tao/mày khi cà khịa hoặc căng thẳng; nhóm đông thường tôi/mọi người. Psycho: tôi/anh hoặc cô, lời ít, nhịp ngắt câu có chủ ý. Không làm mất nhịp bất thường đó.
- Chưa xác minh người nói/người nghe: dựa key và câu lân cận; dùng bản dịch hợp lý, đánh NEEDS_REVIEW nếu đại từ có thể làm sai quan hệ. Không tự gán giới tính chỉ từ câu ngắn.
- Đoạn nói về mẹ Bob: con/mẹ; gọi sếp thời quá khứ: tôi/sếp. Hangman giữ biệt danh. Samantha là bạn đời của Hal.
- Vip3r dùng tiếng lóng mạng: giải nghĩa LOL/NGL/FYI/TIA/FOAD trong lời Việt tùy nhịp; giữ emoticon và tag glitch. Từ bị che bởi ký hiệu không tự phục dựng. Rikers là tên nhà tù, lặp/casing diễn tả sang chấn phải giữ toàn bộ.

## Thuật ngữ thống nhất
| Nguồn | Tiếng Việt |
|---|---|
| cleaner | người dọn dẹp / tay dọn dẹp (hội thoại) |
| cleaning / clean | dọn dẹp / dọn sạch |
| evidence | tang vật |
| body / corpse | thi thể (UI), xác (hội thoại) |
| body part | bộ phận thi thể |
| blood | máu |
| vacuum / vacuum cleaner | hút bụi / máy hút bụi |
| cleaner sense | giác quan dọn dẹp |
| crouch | cúi người |
| sprint | chạy nước rút |
| stamina | thể lực |
| checkpoint | điểm lưu |
| mission / job | nhiệm vụ / phi vụ (hội thoại) |
| objective | mục tiêu |
| disposal point | điểm phi tang |
| hide / hiding spot | ẩn nấp / chỗ ẩn nấp |
| distract / distraction | đánh lạc hướng |
| cop / police | cớm (hội thoại), cảnh sát (UI) |
| load game / save game | tải trò chơi / lưu trò chơi |
| New Game / Continue | Chơi mới / Tiếp tục |
| resume / back | chơi tiếp / quay lại |
| gamepad / controller | tay cầm |
| key binding | gán phím |
| hold / press / toggle | giữ / nhấn / bật-tắt |

## Quy ước kỹ thuật và biên tập
- Giữ nguyên ID, term key, tên asset, mã ngôn ngữ, tên font và mọi term non-text.
- Giữ nguyên placeholder, RichText, sprite, mã input, số liệu, xuống dòng và điều kiện gameplay. Chuỗi JSON UTF-8 NFC.
- Giữ tên riêng, thương hiệu, tên bài hát khi xác minh; ghi notes nếu giữ nguyên.
- Viết hoa đầu câu/nhãn, không viết hoa mọi từ. Nếu nguồn IN HOA vì màn hình, ưu tiên tương ứng khi cần thiết.
- Thay ô tiếng Anh bằng tiếng Việt để không thay đổi enum ngôn ngữ/logic; các ngôn ngữ khác và key được bảo toàn. Chưa bật đổi tên ngôn ngữ trước khi xác minh cách game tra cứu.
- Không dịch runtime debug thành nội dung người chơi nếu chưa xác minh. Mọi text ngoài I2 cần phân loại riêng.
