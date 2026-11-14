# -*- coding: utf-8 -*-
"""Codemod: đồng bộ màu UI CỔ NGỮ về Graphite + Cyan (quy luật 80/20/10).

- Magenta/purple decorative -> accent cyan #00F0FF.
- CTA xanh lá -> accent cyan; success/warning/error giữ dạng muted.
- Gom ~30 màu nền tối gần giống nhau về thang neutral 5 nấc.
- Shadow pixel cứng -> shadow mềm (quieter).

Chạy: python tools/harmonize_colors.py
Idempotent: chạy lại không đổi gì thêm.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = [ROOT / "static" / "index.html", ROOT / "static" / "css" / "styles.css"]
FILES += sorted((ROOT / "static" / "js").glob("*.js"))

# 1. Rule đặc biệt (literal, chạy TRƯỚC generic để không bị ghi đè sai ngữ cảnh)
SPECIAL = [
    # Thanh XP / progress: bỏ gradient cầu vồng -> accent đơn sắc
    ("bg-gradient-to-r from-[#00F0FF] via-[#00FF9D] to-[#FFB800]", "bg-[#00F0FF]"),
    ("bg-gradient-to-r from-[#00F0FF] to-[#00FF9D]", "bg-[#00F0FF]"),
    ("background:linear-gradient(90deg,#00F0FF,#00FF9D);", "background:#00F0FF;"),
    # Nút tải về (discovery) -> CTA cyan
    ("bg-[#08251c] text-[#00FF9D] border border-[#00FF9D]/40 hover:border-[#00FF9D]",
     "bg-[#0C1B24] text-[#00F0FF] border border-[#00F0FF]/40 hover:border-[#00F0FF]"),
    # Nút yêu cầu Việt hóa -> CTA cyan
    ("bg-[#06241a] border border-[#00FF9D]/60 text-[#00FF9D] hover:bg-[#083023]",
     "bg-[#0C1B24] border border-[#00F0FF]/60 text-[#00F0FF] hover:bg-[#12303D]"),
    ("text-[#00FF9D] hover:text-emerald-300", "text-[#00F0FF] hover:text-cyan-300"),
    ("border-[#00FF9D]/50 hover:border-[#00FF9D]", "border-[#00F0FF]/50 hover:border-[#00F0FF]"),
    # Nút upload cloud save
    ("text-[#00FF9D] hover:text-white px-3.5 py-2", "text-[#00F0FF] hover:text-white px-3.5 py-2"),
    ('<i data-lucide="upload" class="w-4 h-4 text-[#00FF9D]">', '<i data-lucide="upload" class="w-4 h-4 text-[#00F0FF]">'),
    ("border-[#00FF9D]/30 transition", "border-[#00F0FF]/30 transition"),
    # Nút mở thư mục game
    ('<i data-lucide="folder" class="w-3.5 h-3.5 text-[#00FF9D]">', '<i data-lucide="folder" class="w-3.5 h-3.5 text-[#00F0FF]">'),
    ("hover:border-[#00FF9D]", "hover:border-[#00F0FF]"),
    ("hover:text-[#00FF9D]", "hover:text-[#00F0FF]"),
    # Số liệu thống kê -> neutral (không màu)
    ('text-[#00FF9D]">~15 MB', 'text-[#F2F6FC]">~15 MB'),
    ('id="modalStatLines" class="text-xs font-mono font-bold text-[#FFB800]"',
     'id="modalStatLines" class="text-xs font-mono font-bold text-[#F2F6FC]"'),
    ("payload.duration_text || '—', '#00FF9D'", "payload.duration_text || '—', '#F2F6FC'"),
    ("text-[#00FF9D]/90 font-mono", "text-[#8B9BB4] font-mono"),
    ("text-[#00FF9D]/90 font-semibold", "text-[#8B9BB4] font-semibold"),
    # Tiến trình % -> accent
    ('id="progressPercentText" class="font-bold text-[#00FF9D]"',
     'id="progressPercentText" class="font-bold text-[#00F0FF]"'),
    # Nhãn section -> neutral
    ("font-pixel text-[10px] text-[#00FF9D] tracking-widest", "font-pixel text-[10px] text-[#8B9BB4] tracking-widest"),
    # Thẻ game đã chọn (request) -> accent
    ("text-[9px] font-pixel text-[#00FF9D] tracking-wide", "text-[9px] font-pixel text-[#00F0FF] tracking-wide"),
    ('<i data-lucide="check" class="w-3 h-3 text-[#00FF9D]">', '<i data-lucide="check" class="w-3 h-3 text-[#00F0FF]">'),
    ("border border-[#00FF9D]/60 rounded-[2px] shadow-[0_0_12px_rgba(0,255,157,0.2)]",
     "border border-[#00F0FF]/60 rounded-[2px] shadow-[0_0_12px_rgba(0,240,255,0.2)]"),
    ('class="w-[88px] h-[36px] object-cover rounded-[2px] border border-[#00FF9D]/40',
     'class="w-[88px] h-[36px] object-cover rounded-[2px] border border-[#00F0FF]/40'),
    # Badge phiên bản / tab đang active -> accent
    ("bg-[#FFB800]/15 text-[#FFB800] border border-[#FFB800]/50", "bg-[#00F0FF]/15 text-[#00F0FF] border border-[#00F0FF]/50"),
    ("bg-[#FFB800]/30 text-[#FFB800]", "bg-[#00F0FF]/30 text-[#00F0FF]"),
    ("bg-[#FFB800]/20", "bg-[#00F0FF]/20"),
    ("'text-[#FFB800]', 'border', 'border-[#FFB800]/40'", "'text-[#00F0FF]', 'border', 'border-[#00F0FF]/40'"),
    ("bg-[#00FF9D]/15 text-[#00FF9D] border border-[#00FF9D]/30", "bg-[#00F0FF]/15 text-[#00F0FF] border border-[#00F0FF]/30"),
    # Nút icon active xanh lá -> cyan
    ("bg-[#00FF9D] text-black border border-[#00FF9D] rounded-[2px] shadow-[0_0_8px_#00FF9D]",
     "bg-[#00F0FF] text-black border border-[#00F0FF] rounded-[2px] shadow-[0_0_8px_#00F0FF]"),
    # Số vote / chữ nhấn trong empty state
    ("font-pixel text-[#FFB800]", "font-pixel text-[#8B9BB4]"),
    ('<strong class="text-[#FFB800]">Yêu Cầu Việt Hóa</strong>', '<strong class="text-[#00F0FF]">Yêu Cầu Việt Hóa</strong>'),
    # Dấu * bắt buộc -> đỏ muted (giữ convention form)
    ('<span class="text-[#FF2A85]">*</span>', '<span class="text-[#F87171]">*</span>'),
    # CTA còn dùng Tailwind emerald -> accent cyan duy nhất
    ("bg-emerald-600/90 hover:bg-emerald-500 text-white", "bg-[#00F0FF] hover:bg-[#66F5FF] text-[#061418]"),
    ("bg-emerald-600 hover:bg-emerald-500 text-white", "bg-[#00F0FF] hover:bg-[#66F5FF] text-[#061418]"),
    ("bg-emerald-600 text-white", "bg-[#00F0FF] text-[#061418]"),
    ("hover:bg-emerald-500", "hover:bg-cyan-400"),
    ("hover:text-emerald-300", "hover:text-cyan-300"),
    ("group-hover:text-emerald-400", "group-hover:text-cyan-300"),
    ("peer-checked:bg-emerald-400", "peer-checked:bg-cyan-400"),
    ("shadow-emerald-900/30", "shadow-black/30"),
    ("border-b-2 border-emerald-400 text-emerald-300", "border-b-2 border-cyan-400 text-cyan-300"),
    # Shadow pixel cứng -> shadow mềm
    ("shadow-[4px_4px_0px_#05050a]", "shadow-[0_8px_24px_rgba(0,0,0,0.45)]"),
    ("shadow-[2px_2px_0px_#05050a]", "shadow-[0_2px_8px_rgba(0,0,0,0.35)]"),
    ("shadow-[2px_2px_0px_#000]", "shadow-[0_2px_8px_rgba(0,0,0,0.35)]"),
    ("shadow-[1px_1px_0_#05050a]", "shadow-[0_1px_3px_rgba(0,0,0,0.35)]"),
]

# 2. Hex generic (regex ignore-case, thay mọi biến thể hoa/thường)
HEX_MAP = {
    "#FF2A85": "#00F0FF",  # magenta -> accent
    "#B026FF": "#00F0FF",  # purple -> accent
    "#00FF9D": "#34D399",  # neon green -> success muted
    "#10B981": "#34D399",  # emerald -> success muted (CTA xử lý riêng trong CSS)
    "#FFB800": "#FBBF24",  # amber -> warning muted
    "#FFE600": "#FBBF24",
    "#FFB020": "#FBBF24",
    "#FF3344": "#F87171",  # crimson -> error muted
    "#FF4D6D": "#F87171",
    "#FF6677": "#F87171",
    "#F0ABFC": "#8B9BB4",  # tím nhạt -> neutral
    # Bề mặt neutral (gom về thang 5 nấc)
    "#17192E": "#1C2536", "#181A33": "#1C2536", "#202447": "#26314A",
    "#1A1D36": "#1C2536", "#2B2F52": "#2A3548",
    "#070814": "#0A0E1A", "#070817": "#0A0E1A", "#070918": "#0A0E1A",
    "#070914": "#0A0E1A", "#070915": "#0A0E1A", "#080A16": "#0A0E1A",
    "#080A18": "#0A0E1A", "#05060F": "#0A0E1A", "#08080A": "#0A0E1A",
    "#0B0D18": "#0F1522", "#0A0C1B": "#0F1522", "#0A1020": "#0F1522",
    "#0A0D1C": "#0F1522", "#0C1628": "#0F1522", "#09152B": "#0F1522",
    "#0D1026": "#0F1522", "#0E1022": "#0F1522", "#0E0F22": "#0F1522",
    "#0F0F13": "#0F1522", "#101014": "#0F1522", "#121216": "#0F1522",
    "#121424": "#0F1522", "#1E223B": "#151C2C", "#080914": "#0A0E1A",
    "#0B1020": "#0F1522", "#111326": "#151C2C", "#1A0B1E": "#151C2C",
    "#0B0C1A": "#0A0E1A", "#161129": "#0F1522", "#111224": "#0F1522",
    # Bề mặt tint theo màu cũ -> tint accent / success
    "#190A1C": "#0C1B24", "#1F0D22": "#0C1B24", "#301235": "#12303D",
    "#06241A": "#0C1B24", "#08251C": "#0C1B24", "#083023": "#12303D",
    "#062A1D": "#0C1B24", "#08251B": "#0F1522", "#09151C": "#0C1B24",
    "#071912": "#0A1F16", "#22070F": "#2A1216",
}

# 3. rgba(...) theo họ màu (ignore-case, giữ nguyên alpha)
RGBA_MAP = [
    ("rgba(255,42,133", "rgba(0,240,255"),
    ("rgba(255, 42, 133", "rgba(0, 240, 255"),
    ("rgba(176,38,255", "rgba(0,240,255"),
    ("rgba(176, 38, 255", "rgba(0, 240, 255"),
    ("rgba(16,185,129", "rgba(0,240,255"),
    ("rgba(16, 185, 129", "rgba(0, 240, 255"),
    ("rgba(0,255,157", "rgba(52,211,153"),
    ("rgba(0, 255, 157", "rgba(52, 211, 153"),
    ("rgba(255,184,0", "rgba(251,191,36"),
    ("rgba(255, 184, 0", "rgba(251, 191, 36"),
    ("rgba(255,51,68", "rgba(248,113,113"),
    ("rgba(255, 51, 68", "rgba(248, 113, 113"),
]


def main() -> None:
    grand_total = 0
    for path in FILES:
        text = path.read_text(encoding="utf-8")
        original = text
        count = 0
        for old, new in SPECIAL:
            hits = text.count(old)
            if hits:
                text = text.replace(old, new)
                count += hits
        text, hits = re.subn(r"\b(?:pink|purple|fuchsia|violet)-(?=\d)", "cyan-", text, flags=re.IGNORECASE)
        count += hits
        for old, new in HEX_MAP.items():
            text, hits = re.subn(re.escape(old), new, text, flags=re.IGNORECASE)
            count += hits
        for old, new in RGBA_MAP:
            text, hits = re.subn(re.escape(old), new, text, flags=re.IGNORECASE)
            count += hits
        if text != original:
            path.write_text(text, encoding="utf-8", newline="")
        print(f"{path.relative_to(ROOT)}: {count} replacements")
        grand_total += count
    print(f"TOTAL: {grand_total} replacements")


if __name__ == "__main__":
    main()
