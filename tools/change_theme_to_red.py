# -*- coding: utf-8 -*-
"""
Codemod: Chuyển đổi toàn bộ màu chủ đạo từ Xanh Neon (Cyan #00F0FF) sang Đỏ Neon (Red #FF2A55).
Áp dụng cho:
- static/css/styles.css
- static/index.html
- static/themes/cyberpunk_default/theme.json
- Toàn bộ static/js/*.js
"""
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TARGET_FILES = [
    ROOT / "static" / "css" / "styles.css",
    ROOT / "static" / "index.html",
    ROOT / "static" / "themes" / "cyberpunk_default" / "theme.json",
]
TARGET_FILES += sorted((ROOT / "static" / "js").glob("*.js"))

HEX_REPLACEMENTS = [
    # Neon Cyan -> Neon Red
    (r"#00[Ff]0[Ff]{2}", "#FF2A55"),
    (r"#66[Ff]5[Ff]{2}", "#FF6685"),
    # Tint backgrounds
    (r"#0[Cc]1[Bb]24", "#240C12"),
    (r"#12303[Dd]", "#3D121B"),
    (r"#06141[Cc]", "#1A0A0E"),
    (r"#061410", "#1A0A0E"),
]

RGBA_REPLACEMENTS = [
    (r"rgba\(\s*0\s*,\s*240\s*,\s*255\s*,", "rgba(255, 42, 85,"),
    (r"rgba\(\s*34\s*,\s*211\s*,\s*238\s*,", "rgba(255, 42, 85,"),
]

def transform_content(text: str) -> tuple[str, int]:
    total_hits = 0

    # 1. Hex replacements
    for pattern, repl in HEX_REPLACEMENTS:
        text, hits = re.subn(pattern, repl, text)
        total_hits += hits

    # 2. RGBA replacements
    for pattern, repl in RGBA_REPLACEMENTS:
        text, hits = re.subn(pattern, repl, text, flags=re.IGNORECASE)
        total_hits += hits

    # 3. Tailwind cyan- classes -> red- classes
    # e.g., text-cyan-400 -> text-red-400, bg-cyan-500/20 -> bg-red-500/20, border-cyan-400 -> border-red-400
    text, hits = re.subn(r"\bcyan-(?=\d)", "red-", text, flags=re.IGNORECASE)
    total_hits += hits

    # 4. Text/keyword specific replacements
    # active-cyan -> active-red
    text, hits = re.subn(r"\bactive-cyan\b", "active-red", text)
    total_hits += hits

    return text, total_hits

def main():
    print("====================================================")
    print("   CODEMOD: CHUYỂN MÀU CHỦ ĐẠO TỪ CYAN SANG ĐỎ      ")
    print("====================================================")
    grand_total = 0

    for file_path in TARGET_FILES:
        if not file_path.exists():
            continue
        original = file_path.read_text(encoding="utf-8")
        transformed, hits = transform_content(original)

        if original != transformed:
            file_path.write_text(transformed, encoding="utf-8", newline="")
            print(f"[OK] {file_path.relative_to(ROOT)}: {hits} thay đổi")
            grand_total += hits
        else:
            print(f"[-] {file_path.relative_to(ROOT)}: 0 thay đổi")

    print("----------------------------------------------------")
    print(f"TỔNG CỘNG ĐÃ THAY ĐỔI: {grand_total:,} vị trí!")
    print("====================================================")

if __name__ == "__main__":
    main()
