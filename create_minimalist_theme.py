# -*- coding: utf-8 -*-
"""
Script tạo theme tối giản (minimalist_dark) cho VietModHub.
"""
import os
import sys
import json
import math
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.theme_manager import (
    get_themes_root,
    list_themes,
    get_theme,
    get_theme_css,
    export_theme,
)
from core.theme_manager.manifest import (
    normalize_manifest,
    validate_manifest,
    manifest_to_json,
)

def main():
    themes_root = get_themes_root()
    theme_id = "minimalist_dark"
    theme_dir = os.path.join(themes_root, theme_id)
    os.makedirs(theme_dir, exist_ok=True)

    # 1. Background image (Subtle dark slate vignette)
    w, h = 1920, 1080
    img = Image.new("RGB", (w, h), color=(15, 17, 21))
    draw = ImageDraw.Draw(img)
    cx, cy = w // 2, h // 3
    max_r = math.sqrt(w * w + h * h) / 1.5

    for r in range(int(max_r), 0, -8):
        factor = 1.0 - (r / max_r)
        v = int(15 + factor * 14)
        v2 = int(17 + factor * 16)
        v3 = int(21 + factor * 22)
        bbox = [cx - r, cy - r, cx + r, cy + r]
        draw.ellipse(bbox, fill=(v, v2, v3))

    bg_path = os.path.join(theme_dir, "background.jpg")
    img.save(bg_path, "JPEG", quality=90)
    print(f"[1/5] Background image generated: {bg_path} ({os.path.getsize(bg_path)} bytes)")

    # 2. theme.json
    manifest_data = {
        "id": theme_id,
        "name": "Tối Giản Tinh Tế (Minimalist Dark)",
        "author": "VietModHub",
        "version": "1.0",
        "description": "Giao diện tối giản tông than chì, loại bỏ ánh neon và đổ bóng cứng, êm mắt và tập trung.",
        "variables": {
            "--bg-primary": "#0f1115",
            "--bg-secondary": "#181a20",
            "--text-primary": "#f3f4f6",
            "--text-muted": "#88909e",
            "--accent-color": "#3b82f6",
            "--accent-hover": "#60a5fa",
            "--border-color": "rgba(255, 255, 255, 0.08)",
            "--card-radius": "8px",
            "--glass-blur": "0px"
        },
        "assets": {
            "background_image": "background.jpg",
            "background_opacity": 0.12,
            "custom_css": "custom.css"
        }
    }

    normalized = normalize_manifest(manifest_data)
    ok, err = validate_manifest(normalized)
    if not ok:
        print(f"Validation error: {err}")
        sys.exit(1)

    manifest_file = os.path.join(theme_dir, "theme.json")
    with open(manifest_file, "w", encoding="utf-8") as f:
        f.write(manifest_to_json(normalized))
    print(f"[2/5] Saved manifest: {manifest_file}")

    # 3. custom.css
    css_content = """/* ==========================================================================
   Cổ Ngữ Minimalist Dark (Tối Giản Tinh Tế) — custom.css
   ========================================================================== */

/* 1. Thay thế đổ bóng pixel retro bằng độ nổi phẳng (flat depth) êm dịu */
body[data-theme="minimalist_dark"] .pixel-card {
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3) !important;
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease !important;
}

body[data-theme="minimalist_dark"] .pixel-card:hover {
  transform: translateY(-2px) !important;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45) !important;
  border-color: var(--accent-color) !important;
}

body[data-theme="minimalist_dark"] #heroBanner.hero-arcade-frame {
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.35) !important;
  outline: none !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
}

body[data-theme="minimalist_dark"] .pixel-modal {
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.6) !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
}

body[data-theme="minimalist_dark"] .pixel-tab.active-filter-tab {
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.3) !important;
}

body[data-theme="minimalist_dark"] .btn-neon-cyan {
  transition: background-color 0.15s ease, color 0.15s ease, box-shadow 0.15s ease !important;
}

body[data-theme="minimalist_dark"] .btn-neon-cyan:hover {
  box-shadow: 0 4px 14px rgba(59, 130, 246, 0.3) !important;
}

/* 2. Tắt text-shadow retro trên các tiêu đề */
body[data-theme="minimalist_dark"] h1,
body[data-theme="minimalist_dark"] h2,
body[data-theme="minimalist_dark"] h3,
body[data-theme="minimalist_dark"] h4,
body[data-theme="minimalist_dark"] .font-pixel {
  text-shadow: none !important;
}

/* 3. Thanh cuộn tối giản hiện đại (Minimal Sleek Scrollbar) */
body[data-theme="minimalist_dark"] ::-webkit-scrollbar {
  width: 6px !important;
  height: 6px !important;
}

body[data-theme="minimalist_dark"] ::-webkit-scrollbar-track {
  background: var(--bg-primary) !important;
  border-left: 1px solid rgba(255, 255, 255, 0.04) !important;
}

body[data-theme="minimalist_dark"] ::-webkit-scrollbar-thumb {
  background: #2b2e38 !important;
  border: none !important;
  border-radius: 4px !important;
}

body[data-theme="minimalist_dark"] ::-webkit-scrollbar-thumb:hover {
  background: var(--accent-color) !important;
}

/* 4. Tinh chỉnh ô tìm kiếm & các dòng danh sách */
body[data-theme="minimalist_dark"] #searchInput:focus {
  border-color: var(--accent-color) !important;
  box-shadow: 0 0 0 1px var(--accent-color) !important;
}

body[data-theme="minimalist_dark"] .sidebar-game-row {
  transition: background-color 0.15s ease, border-color 0.15s ease !important;
}
"""

    css_file = os.path.join(theme_dir, "custom.css")
    with open(css_file, "w", encoding="utf-8") as f:
        f.write(css_content)
    print(f"[3/5] Saved custom CSS: {css_file}")

    # 4. Verify with theme_manager
    all_themes = list_themes()
    print(f"[4/5] Available themes ({len(all_themes)}): {[t['id'] for t in all_themes]}")
    detail = get_theme(theme_id)
    if detail:
        print(f"      Theme '{detail['name']}' verified:")
        print(f"      - has_custom_css: {detail['has_custom_css']}")
        print(f"      - has_background: {detail['has_background']}")
        print(f"      - preview_url: {detail['preview_url']}")
        print(f"      - warnings: {detail['warnings']}")

    # 5. Export package
    export_dest = os.path.abspath("minimalist_dark.congu_theme")
    res = export_theme(theme_id, export_dest)
    print(f"[5/5] Export package result: {res}")
    print("\n>>> TẠO THEME TỐI GIẢN THÀNH CÔNG! <<<")

if __name__ == "__main__":
    main()
