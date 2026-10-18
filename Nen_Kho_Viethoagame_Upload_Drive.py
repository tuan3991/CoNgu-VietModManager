import os
import zipfile
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

REPO_DIR = r"G:\My Drive\Viethoagame"
OUTPUT_DIR = os.path.join(REPO_DIR, "_gdrive_zips")
os.makedirs(OUTPUT_DIR, exist_ok=True)

print("========================================================================")
print("     TIỆN ÍCH TỰ ĐỘNG NÉN KHO MOD ĐỂ UPLOAD LÊN GOOGLE DRIVE")
print("========================================================================")
print(f"Kho nguồn: {REPO_DIR}")
print(f"Thư mục lưu file zip: {OUTPUT_DIR}\n")

if not os.path.exists(REPO_DIR):
    print(f"[!] Không tìm thấy thư mục {REPO_DIR}. Vui lòng kiểm tra lại đường dẫn!")
    sys.exit(1)

subfolders = [f for f in os.listdir(REPO_DIR) if os.path.isdir(os.path.join(REPO_DIR, f)) and not f.startswith("_")]

print(f"Tìm thấy {len(subfolders)} tựa game trong kho cần nén:")
for sf in subfolders:
    src_dir = os.path.join(REPO_DIR, sf)
    zip_name = f"{sf}.zip"
    zip_path = os.path.join(OUTPUT_DIR, zip_name)
    
    print(f"-> Đang nén '{sf}' ... ", end="", flush=True)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(src_dir):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, src_dir)
                zf.write(full_path, rel_path)
    
    sz_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"Xong! ({sz_mb:.2f} MB) -> {zip_name}")

print("\n========================================================================")
print(f"[✓] HOÀN TẤT NÉN TOÀN BỘ KHO MOD TẠI: {OUTPUT_DIR}")
print("HƯỚNG DẪN LẤY LINK GOOGLE DRIVE:")
print(" 1. Mở Google Drive trên trình duyệt web, vào thư mục '_gdrive_zips'.")
print(" 2. Nhấp chuột phải vào file .zip của game -> Chọn 'Chia sẻ' (Share).")
print(" 3. Đổi quyền thành 'Bất kỳ ai có đường liên kết đều có thể xem'.")
print(" 4. Bấm 'Sao chép đường liên kết' (Copy link).")
print(" 5. Mở VietMod Hub -> Bấm vào game -> Dán link vào ô 'Link Tải Google Drive' và bấm 'Lưu'!")
print("========================================================================")
