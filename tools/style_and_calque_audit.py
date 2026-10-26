#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
style_and_calque_audit.py
Script kiểm định độc lập ở GIAI ĐOẠN 4:
Quét toàn bộ bản dịch để bắt tận gốc các lỗi dịch Word-by-Word (Calque),
dịch sai từ đa nghĩa trên UI (Khách quan, Cầu trượt, Thả từ nền tảng...),
thừa mạo từ tiếng Anh ("một câu thần chú", "một loại thuốc"),
đại từ "Tôi - Bạn" trong hội thoại, và lỗi lệch thẻ điều khiển.
"""

import re
import sys
import os
import json
import unicodedata
from typing import List, Dict, Any

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


TAG_REGEX = re.compile(r'(\{\d+\}|\{[a-zA-Z0-9_:]+\}|%[sdif]|\\n|<[^>]+>|\[[a-zA-Z0-9_=#/]+\])')

# Danh sách các lỗi dịch máy / sai ngữ cảnh UI điển hình
UI_MISTRANSLATION_RULES = [
    (r"^objective(s)?$", r"khách quan", "Sai nghĩa UI: 'Objective' phải dịch là 'Mục tiêu' hoặc 'Nhiệm vụ', không phải 'Khách quan'."),
    (r"^slide$", r"cầu trượt", "Sai từ loại UI: 'Slide' trong điều khiển là động từ 'Trượt / Lướt', không phải danh từ 'Cầu trượt'."),
    (r"drop from platform", r"thả từ nền tảng", "Dịch word-by-word: 'Drop from platform' phải dịch là 'Nhảy xuống bệ' hoặc 'Tụt xuống bậc'."),
    (r"\bplatform(s)?\b", r"nền tảng", "Cảnh báo từ vựng: Trong game đi cảnh, 'Platform' là 'Bệ đứng / Bậc thềm', tránh dịch là 'Nền tảng'."),
    (r"cast a spell", r"truyền một câu thần chú", "Dịch word-by-word & thừa mạo từ: Phải dịch là 'Thi triển phép' hoặc 'Tung phép'."),
    (r"health tonic", r"thuốc bổ sức khỏe", "Dịch word-by-word: 'Health tonic' nên dịch là 'Bình máu' hoặc 'Thuốc hồi máu'."),
    (r"interact with an object", r"tương tác với một đối tượng", "Thừa cụm từ: Chỉ cần dịch ngắn gọn là 'Tương tác'."),
    (r"^back$", r"^lưng$", "Sai nghĩa nút UI: 'Back' là 'Quay lại', không phải 'Lưng'."),
    (r"^credits$", r"tín dụng", "Sai nghĩa menu: 'Credits' là 'Đội ngũ phát triển', không phải 'Tín dụng'."),
]

# Các cấu trúc câu sặc mùi Google Translate (Calque patterns)
CALQUE_PATTERNS = [
    (r"\bsử dụng một loại\b", "Dính mạo từ dịch máy 'sử dụng một loại...' -> Hãy rút gọn thành 'Dùng...'"),
    (r"\btruyền một câu\b", "Dính mạo từ dịch máy 'truyền một câu...' -> Hãy rút gọn thành 'Tung / Thi triển...'"),
    (r"\bdưới hình thức đọc lá bài\b", "Cấu trúc dịch máy 'dưới hình thức đọc lá bài' -> Sửa thành 'dưới dạng một trải bài'"),
    (r"\bcảm thấy mình bị mắc kẹt\b", "Cấu trúc dịch máy 'cảm thấy mình bị mắc kẹt' -> Sửa thành 'khi bị bế tắc / bí đường'"),
    (r"\bmột cái gì đó\b", "Cấu trúc dịch máy 'một cái gì đó' -> Đổi thành 'thứ gì đó' hoặc lược bỏ"),
    (r"\bnó đã bị\b", "Cấu trúc bị động dịch máy 'nó đã bị...' -> Chuyển sang câu chủ động tự nhiên"),
]


def audit_translations(items: List[Dict[str, Any]]) -> int:
    errors = []
    warnings = []

    for idx, item in enumerate(items):
        row_id = item.get("id", idx)
        key = item.get("key", "")
        src = item.get("source", "")
        vi = item.get("vi", "")

        if not src.strip():
            continue

        if not vi.strip():
            errors.append(f"[ID {row_id}] Bỏ trống bản dịch cho câu gốc: {src!r}")
            continue

        # 1. Kiểm tra chuẩn NFC
        if vi != unicodedata.normalize("NFC", vi):
            errors.append(f"[ID {row_id}] Chưa chuẩn hóa Unicode NFC (dễ gây lỗi tách dấu trong game): {vi!r}")

        # 2. Kiểm tra bảo toàn thẻ điều khiển & biến số
        src_tags = TAG_REGEX.findall(src)
        vi_tags = TAG_REGEX.findall(vi)
        for t in set(src_tags):
            if src_tags.count(t) != vi_tags.count(t):
                errors.append(
                    f"[ID {row_id}] Lệch thẻ điều khiển {t!r}: Gốc có {src_tags.count(t)}, Dịch có {vi_tags.count(t)} | Dịch: {vi!r}"
                )

        # 3. Quét lỗi dịch sai từ vựng UI/Tutorial
        src_low = src.strip().lower()
        vi_low = vi.strip().lower()
        for src_pat, vi_pat, msg in UI_MISTRANSLATION_RULES:
            if re.search(src_pat, src_low) and re.search(vi_pat, vi_low):
                errors.append(f"[ID {row_id} | Key={key}] {msg}\n    Gốc : {src}\n    Dịch: {vi}")

        # 4. Quét cấu trúc câu Word-by-Word (Calque)
        for pat, msg in CALQUE_PATTERNS:
            if re.search(pat, vi_low):
                warnings.append(f"[ID {row_id} | Key={key}] {msg}\n    Gốc : {src}\n    Dịch: {vi}")

        # 5. Quét đại từ "Tôi - Bạn" trong hội thoại
        is_dialogue = any(w in key.lower() for w in ["diag", "dlg", "talk", "voice", "npc", "sub"]) or (
            any(p in src for p in ["?", "!", '"']) and "you" in src_low
        )
        if is_dialogue and re.search(r"\b(tôi|chúng tôi)\b.*\bbạn\b|\bbạn\b.*\b(tôi|chúng tôi)\b", vi_low):
            warnings.append(
                f"[ID {row_id} | Key={key}] Phát hiện xưng hô 'Tôi - Bạn' cứng nhắc trong hội thoại:\n    Gốc : {src}\n    Dịch: {vi}"
            )

    print("=" * 70)
    print(f"KẾT QUẢ KIỂM ĐỊNH VĂN PHONG & KỸ THUẬT ({len(items)} dòng)")
    print("=" * 70)
    print(f"- Lỗi nghiêm trọng (BẮT BUỘC SỬA): {len(errors)}")
    print(f"- Cảnh báo Word-by-Word / Văn phong: {len(warnings)}")

    if errors:
        print("\n[!] CHI TIẾT LỖI NGHIÊM TRỌNG:")
        for e in errors[:20]:
            print("  *", e)

    if warnings:
        print("\n[~] CHI TIẾT CẢNH BÁO WORD-BY-WORD CẦN BIÊN TẬP LẠI:")
        for w in warnings[:20]:
            print("  *", w)

    return 1 if (errors or warnings) else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Cách dùng: python style_and_calque_audit.py <file_json_da_dich.json>")
        sys.exit(1)

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        data = json.load(f)

    exit_code = audit_translations(data)
    sys.exit(exit_code)
