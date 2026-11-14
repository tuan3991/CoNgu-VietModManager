# Hướng dẫn cho Agent

## Tuyệt đối không tắt trình duyệt của người dùng

- **KHÔNG** chạy `Get-Process chrome | Stop-Process`, `Stop-Process -Name chrome`,
  `taskkill /IM chrome.exe`, `taskkill /F /IM msedge.exe` hoặc bất kỳ lệnh nào
  kill toàn bộ `chrome.exe` / `msedge.exe`.
- Không cần đóng Chrome để chụp screenshot. Chrome/Edge headless có thể chạy
  song song với Chrome thường nếu dùng `--user-data-dir` riêng.
- Nếu buộc phải tự khởi chạy trình duyệt:
  - Luôn thêm `--user-data-dir=<thư mục tạm riêng>`;
  - Chỉ kill đúng PID do mình tạo (ví dụ `taskkill /PID <pid> /T /F`),
    không kill theo tên tiến trình.

## Chụp preview / screenshot

Dùng helper an toàn có sẵn:

```powershell
python tools/preview_shot.py static/index.html -o preview.png --width 1440 --height 900
python tools/preview_shot.py http://127.0.0.1:8000 -o preview.png
```

Helper này tự tạo profile tạm trong `%TEMP%`, không ảnh hưởng Chrome đang mở,
và chỉ dọn tiến trình của chính nó.
