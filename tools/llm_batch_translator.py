#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llm_batch_translator.py
Bộ khung dịch thuật Bản địa hóa Game (Contextual Game Localization Engine)
- Tự động nạp GAME_BIBLE.md (Cốt truyện, Tông giọng, Ma trận xưng hô, Glossary)
- Giữ nguyên Key/Path ngữ cảnh và phân loại tự động [UI_CONTROL], [DIALOGUE], [LORE_SYSTEM]
- Mở khóa bộ lọc an toàn (BLOCK_NONE) để dịch chuẩn các phân cảnh chửi thề, bạo lực, 18+ trong game
- Kiểm tra toàn vẹn 100% thẻ Rich Text (<sprite>, <link>, <color>, {0}, %s) & Chuẩn hóa Unicode NFC
- Tích hợp 2 chế độ:
  + Chế độ 1 (api): Gọi trực tiếp Gemini API theo cụm 40-60 dòng (Structured JSON Output)
  + Chế độ 2 (export-batches / merge-batches): Chia file thành từng gói kèm GAME_BIBLE để Coding Agent tự dịch trực tiếp và kiểm định
"""

import os
import re
import sys
import json
import time
import argparse
import unicodedata
from pathlib import Path
from typing import List, Dict, Any, Tuple

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


# ==============================================================================
# 1. CẤU HÌNH NHẬN DIỆN THẺ HỆ THỐNG & PHÂN LOẠI NGỮ CẢNH TỰ ĐỘNG
# ==============================================================================
TAG_PATTERN = re.compile(
    r'(\{\d+\}|\{[a-zA-Z0-9_:]+\}|%[sdif]|\\n|\\r|<[^>]+>|\[[a-zA-Z0-9_=#/]+\])'
)

# Từ điển chống dịch sai các từ đơn/ngắn phổ biến trên UI/Controls
UI_DISAMBIGUATION_HINTS = {
    "objective": "Mục tiêu / Nhiệm vụ (TUYỆT ĐỐI CẤM dịch là 'Khách quan')",
    "objectives": "Mục tiêu / Nhiệm vụ (TUYỆT ĐỐI CẤM dịch là 'Khách quan')",
    "slide": "Trượt / Lướt (Động từ thao tác điều khiển, CẤM dịch là 'Cầu trượt')",
    "drop from platform": "Nhảy xuống bệ / Tụt xuống bậc (CẤM dịch là 'Thả từ nền tảng')",
    "platform": "Bệ đứng / Bậc thềm (trong game đi cảnh, CẤM dịch là 'Nền tảng')",
    "cast a spell": "Thi triển phép / Tung phép (CẤM dịch mạo từ 'Truyền một câu thần chú')",
    "use a health tonic": "Dùng bình máu / Uống thuốc hồi máu (CẤM dịch 'Sử dụng một loại thuốc bổ sức khỏe')",
    "interact with an object": "Tương tác (CẤM dịch 'Tương tác với một đối tượng')",
    "back": "Quay lại (nếu là nút UI, CẤM dịch là 'Lưng')",
    "close": "Đóng (nếu là nút UI)",
    "chest": "Rương (nếu là vật phẩm/tương tác, CẤM dịch là 'Ngực')",
    "party": "Tổ đội / Nhóm (CẤM dịch là 'Bữa tiệc' hay 'Đảng')",
    "save": "Lưu (CẤM dịch là 'Cứu' trên menu)",
    "load": "Tải lại / Nạp (CẤM dịch là 'Tải trọng')",
    "resume": "Tiếp tục (CẤM dịch là 'Sơ yếu lý lịch')",
    "controls": "Điều khiển / Đặt phím (CẤM dịch là 'Kiểm soát')",
    "credits": "Đội ngũ phát triển (CẤM dịch là 'Tín dụng')",
}


def detect_category(key: str, text: str) -> str:
    """Phân loại ngữ cảnh dòng text dựa trên Key/Path và độ dài câu."""
    k = key.lower()
    word_count = len(text.strip().split())

    if any(w in k for w in ["ui", "menu", "btn", "button", "control", "keybind", "input", "hud", "tab", "header", "stat", "option", "setting"]):
        return "UI_CONTROL"
    if any(w in k for w in ["diag", "dlg", "talk", "chat", "voice", "subtitle", "line", "banter", "bark", "npc", "speak"]):
        return "DIALOGUE"
    if any(w in k for w in ["lore", "desc", "tooltip", "codex", "journal", "note", "book", "card", "arcana", "skill", "item_info"]):
        return "LORE_SYSTEM"

    # Suy luận dự phòng nếu key không rõ ràng
    if word_count <= 4 and not any(p in text for p in ["?", "!", "."]):
        return "UI_CONTROL"
    if any(q in text for q in ["?", "!", '"', "“", "”", "'re", "'ll", "'ve", "n't", "fuck", "shit", "damn", "hell"]):
        return "DIALOGUE"
    return "LORE_SYSTEM"


def get_ui_hint(text: str) -> str:
    """Lấy gợi ý chống dịch sai nếu chuỗi khớp với từ nhạy cảm."""
    clean = text.strip().lower()
    if clean in UI_DISAMBIGUATION_HINTS:
        return UI_DISAMBIGUATION_HINTS[clean]
    for k, hint in UI_DISAMBIGUATION_HINTS.items():
        if k in clean and len(clean) < 35:
            return hint
    return ""


def extract_tags(text: str) -> List[str]:
    """Trích xuất toàn bộ biến và thẻ điều khiển cần bảo toàn."""
    return TAG_PATTERN.findall(text)


def normalize_vn(text: str) -> str:
    """Chuẩn hóa Unicode dựng sẵn (NFC) cho chuỗi tiếng Việt."""
    return unicodedata.normalize("NFC", text)


def validate_translation(source: str, translated: str) -> Tuple[bool, List[str]]:
    """Kiểm tra tính toàn vẹn của thẻ điều khiển và phát hiện lỗi dịch máy cơ bản."""
    if not source or not source.strip():
        return True, []

    if not translated or not translated.strip():
        return False, ["Chuỗi dịch bị rỗng"]

    issues = []
    src_tags = extract_tags(source)
    dst_tags = extract_tags(translated)
    for tag in set(src_tags):
        if src_tags.count(tag) != dst_tags.count(tag):
            issues.append(f"Lệch số lượng thẻ '{tag}' (Gốc: {src_tags.count(tag)}, Dịch: {dst_tags.count(tag)})")

    # Kiểm tra các cụm từ dịch máy (Calque) bị cấm
    lower_vn = translated.lower()
    banned_calques = [
        ("objective", "khách quan", "Dịch sai 'Objective' thành 'Khách quan' (phải là 'Mục tiêu' / 'Nhiệm vụ')"),
        ("slide", "cầu trượt", "Dịch sai 'Slide' thành 'Cầu trượt' (phải là 'Trượt' / 'Lướt')"),
        ("platform", "thả từ nền tảng", "Dịch word-by-word 'Drop from platform' (phải là 'Nhảy xuống bệ')"),
        ("cast a spell", "truyền một câu thần chú", "Dịch thừa mạo từ & nghĩa đen (phải là 'Thi triển phép' / 'Tung phép')"),
        ("health tonic", "thuốc bổ sức khỏe", "Dịch word-by-word 'health tonic' (phải là 'bình máu' / 'thuốc hồi máu')"),
        ("interact with an object", "tương tác với một đối tượng", "Dịch thừa mạo từ (phải là 'Tương tác')"),
    ]
    lower_src = source.lower()
    for src_kw, bad_vn, msg in banned_calques:
        if src_kw in lower_src and bad_vn in lower_vn:
            issues.append(msg)

    return len(issues) == 0, issues


# ==============================================================================
# 2. XÂY DỰNG SYSTEM PROMPT TỪ GAME_BIBLE.md
# ==============================================================================
def build_system_prompt(game_bible_path: str) -> str:
    bible_content = "Chưa có file GAME_BIBLE.md. Hãy dịch theo chuẩn game hành động/nhập vai."
    if os.path.exists(game_bible_path):
        with open(game_bible_path, "r", encoding="utf-8") as f:
            bible_content = f.read()

    return f"""Bạn là Đạo diễn Bản địa hóa Game (Lead Game Localization Director) kỳ cựu tại Việt Nam.
Nhiệm vụ của bạn là dịch và phóng tác (Transcreate) văn bản trong game sang tiếng Việt sao cho TỰ NHIÊN, ĐÚNG CHẤT GAME THỦ VIỆT và BÁM SÁT TÍNH CÁCH NHÂN VẬT.

================ HỒ SƠ GAME (GAME BIBLE) ================
{bible_content}
=========================================================

QUY TẮC BẮT BUỘC PHẢI TUÂN THỦ 100%:

1. PHÂN TÁCH 3 TẦNG GIỌNG VĂN DỰA TRÊN NHÃN `category`:
   - Nếu `category` == "UI_CONTROL":
     + Dịch theo ĐỘNG TỪ THAO TÁC hoặc THUẬT NGỮ GAME THỦ ngắn gọn, súc tích.
     + TUYỆT ĐỐI BỎ QUA mạo từ `a / an / the`:
       * "Cast a spell" -> "Thi triển phép" hoặc "Tung phép" (CẤM dịch "Truyền một câu thần chú")
       * "Use a health tonic" -> "Dùng bình máu" (CẤM dịch "Sử dụng một loại thuốc bổ sức khỏe")
       * "Drop from platform" -> "Nhảy xuống bệ" (CẤM dịch "Thả từ nền tảng")
       * "Interact with an object" -> "Tương tác" (CẤM dịch "Tương tác với một đối tượng")
       * "Slide" -> "Trượt" hoặc "Lướt" (CẤM dịch "Cầu trượt")
       * "Objective" -> "Mục tiêu" hoặc "Nhiệm vụ" (CẤM dịch "Khách quan")

   - Nếu `category` == "DIALOGUE":
     + Dịch thoát ý sang khẩu ngữ đời thực, sử dụng đại từ xưng hô chuẩn theo GAME BIBLE (Tao - Mày, Anh - Em, Ta - Ngươi, Huynh - Đệ...). TUYỆT ĐỐI CẤM dùng "Tôi - Bạn".
     + Thêm trợ từ tiếng Việt tự nhiên (đấy, nhỉ, cơ mà, nhé, thôi, mất rồi...).
     + CẤP QUYỀN VĂNG TỤC / CHỬI THỀ: Khi câu gốc có từ chửi thề (fuck, shit, damn, hell, bastard, bitch, asshole, screw...) hoặc nhân vật là kẻ địch/côn đồ/lính đánh thuê đang tức giận, BẮT BUỘC dịch gắt đúng sắc thái tiếng Việt ("ĐM", "mẹ kiếp", "khốn kiếp", "đéo", "vãi cả...", "cút xéo", "thằng chó", "toang rồi"). Không được làm nhẹ câu chửi thành văn vẻ lịch sự.

   - Nếu `category` == "LORE_SYSTEM":
     + Đập bỏ cấu trúc câu rườm rà của tiếng Anh, nắm bắt ý cốt lõi và viết lại bằng văn phong tiếng Việt gãy gọn, giàu hình ảnh.
     + Lược bỏ các từ thừa kiểu dịch máy: CẤM dùng "dưới hình thức...", "cũng như tất cả...", "nếu bạn cảm thấy mình bị...", và lược bỏ bớt chữ "của bạn" lặp đi lặp lại.

2. BẢO TOÀN KỸ THUẬT:
   - Giữ nguyên 100% các thẻ biến và Rich Text như `{{0}}`, `%s`, `\\n`, `<sprite...>`, `<link="id">...</link>`, `<color=...>`. Không dịch thuộc tính `id` bên trong thẻ.
   - Trả về đúng định dạng JSON Array chứa các object `{{"id": ..., "vi": "..."}}` tương ứng với đầu vào.
"""


# ==============================================================================
# 3. CHẾ ĐỘ 1: DỊCH TRỰC TIẾP QUA GEMINI API (CÓ BLOCK_NONE CHO PHÂN CẢNH 18+/CHỬI THỀ)
# ==============================================================================
def translate_batch_gemini_api(
    batch: List[Dict[str, Any]],
    system_prompt: str,
    model_name: str = "gemini-2.5-flash",
    api_key: str = None,
) -> Dict[str, str]:
    """Gọi Gemini API dịch 1 cụm 40-60 dòng với Safety Settings = BLOCK_NONE."""
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise RuntimeError(
            "Chưa cài đặt thư viện 'google-genai'. Chạy: pip install google-genai "
            "hoặc dùng chế độ '--mode export-batches' để Agent tự dịch trực tiếp."
        )

    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY"))

    payload = []
    for item in batch:
        entry = {
            "id": item["id"],
            "key": item.get("key", ""),
            "category": detect_category(item.get("key", ""), item["source"]),
            "source": item["source"],
        }
        hint = get_ui_hint(item["source"])
        if hint:
            entry["hint"] = hint
        payload.append(entry)

    user_prompt = (
        "Hãy dịch danh sách các chuỗi game dưới đây sang tiếng Việt theo đúng ngữ cảnh liền kề và quy tắc trong System Prompt.\n"
        'Trả về duy nhất một JSON Array có cấu trúc: [{"id": "...", "vi": "..."}]\n\n'
        f"INPUT JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )

    response = client.models.generate_content(
        model=model_name,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.3,
            response_mime_type="application/json",
            safety_settings=[
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
            ],
        ),
    )

    result_list = json.loads(response.text)
    return {str(obj["id"]): normalize_vn(obj["vi"]) for obj in result_list}


# ==============================================================================
# 4. CHẾ ĐỘ 2: CHIA GÓI CHO CODING AGENT TỰ DỊCH (KHÔNG CẦN API KEY NGOÀI)
# ==============================================================================
def export_agent_batches(
    items: List[Dict[str, Any]],
    out_dir: str,
    batch_size: int = 50,
    game_bible_path: str = "GAME_BIBLE.md",
):
    """
    Chia file JSON tổng thành từng file batch_XXX.json (40-60 dòng) kèm sẵn
    nhãn phân loại [UI_CONTROL / DIALOGUE / LORE_SYSTEM] và gợi ý chống dịch sai
    để Coding Agent đọc và điền trực tiếp vào trường 'vi' bằng chính LLM của Agent.
    """
    os.makedirs(out_dir, exist_ok=True)
    total_batches = 0

    for i in range(0, len(items), batch_size):
        chunk = items[i : i + batch_size]
        batch_data = {
            "_instructions": (
                f"Đọc kỹ {game_bible_path} trước khi dịch. Điền bản dịch tiếng Việt vào trường 'vi'. "
                "TUYỆT ĐỐI CẤM dùng Google Translate. Chú ý trường 'category' và 'hint' của từng dòng."
            ),
            "items": [],
        }
        for row in chunk:
            src = row["source"]
            entry = {
                "id": row["id"],
                "key": row.get("key", ""),
                "category": detect_category(row.get("key", ""), src),
                "source": src,
                "required_tags": extract_tags(src),
                "vi": row.get("vi", ""),
            }
            hint = get_ui_hint(src)
            if hint:
                entry["hint"] = hint
            batch_data["items"].append(entry)

        batch_file = os.path.join(out_dir, f"batch_{total_batches:04d}.json")
        with open(batch_file, "w", encoding="utf-8") as f:
            json.dump(batch_data, f, ensure_ascii=False, indent=2)
        total_batches += 1

    print(f"[+] Đã xuất {total_batches} gói ngữ cảnh tại thư mục: {out_dir}")


def merge_and_verify_agent_batches(batch_dir: str, output_file: str) -> bool:
    """Gộp các file batch_XXX.json đã dịch, chuẩn hóa NFC và kiểm tra lỗi thẻ/dịch máy."""
    batch_files = sorted(Path(batch_dir).glob("batch_*.json"))
    merged = []
    all_errors = []

    for bf in batch_files:
        with open(bf, "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("items", []):
            vi_text = normalize_vn(item.get("vi", ""))
            ok, issues = validate_translation(item["source"], vi_text)
            if not ok:
                all_errors.append(
                    f"[{bf.name} | ID={item['id']} | Key={item.get('key','')}]\n"
                    f"  Gốc : {item['source']}\n"
                    f"  Dịch: {vi_text}\n"
                    f"  Lỗi : {', '.join(issues)}"
                )
            merged.append(
                {
                    "id": item["id"],
                    "key": item.get("key", ""),
                    "source": item["source"],
                    "vi": vi_text,
                }
            )

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    if all_errors:
        print(f"[!] PHÁT HIỆN {len(all_errors)} LỖI CẦN SỬA TRƯỚC KHI ĐÓNG GÓI:")
        for err in all_errors[:25]:
            print(err)
        return False

    print(f"[+] Kiểm định thành công 100%! Đã lưu {len(merged)} dòng chuẩn NFC tại: {output_file}")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Contextual Game Localization Batch Translator")
    parser.add_argument("--mode", choices=["api", "export-batches", "merge-batches"], required=True)
    parser.add_argument("--input", help="File JSON đầu vào (chứa danh sách {id, key, source})")
    parser.add_argument("--output", help="File JSON đầu ra hoặc thư mục chứa batches")
    parser.add_argument("--bible", default="GAME_BIBLE.md", help="Đường dẫn tới file GAME_BIBLE.md")
    parser.add_argument("--batch-size", type=int, default=50, help="Số dòng mỗi cụm ngữ cảnh (mặc định: 50)")
    parser.add_argument("--model", default="gemini-2.5-flash", help="Tên model Gemini khi chạy mode api")
    args = parser.parse_args()

    if args.mode == "export-batches":
        with open(args.input, "r", encoding="utf-8") as f:
            raw_items = json.load(f)
        export_agent_batches(raw_items, args.output, args.batch_size, args.bible)

    elif args.mode == "merge-batches":
        ok = merge_and_verify_agent_batches(args.input, args.output)
        sys.exit(0 if ok else 1)

    elif args.mode == "api":
        with open(args.input, "r", encoding="utf-8") as f:
            raw_items = json.load(f)
        sys_prompt = build_system_prompt(args.bible)
        translated_items = []
        for i in range(0, len(raw_items), args.batch_size):
            chunk = raw_items[i : i + args.batch_size]
            print(f"[*] Đang dịch cụm {i} -> {i + len(chunk)} / {len(raw_items)}...")
            trans_map = translate_batch_gemini_api(chunk, sys_prompt, model_name=args.model)
            for row in chunk:
                row["vi"] = trans_map.get(str(row["id"]), "")
                translated_items.append(row)
            time.sleep(0.5)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(translated_items, f, ensure_ascii=False, indent=2)
        print(f"[+] Hoàn tất dịch API! Đã lưu tại: {args.output}")
