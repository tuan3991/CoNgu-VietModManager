/**
 * =========================================================================================
 * CỔ NGỮ (VietModHub Pro) - Centralized Community Cloud Save Server (Google Apps Script)
 * =========================================================================================
 * 
 * HƯỚNG DẪN TRIỂN KHAI NHANH CHO ADMIN (CHỈ MẤT 1 PHÚT):
 * -----------------------------------------------------------------------------------------
 * 1. Mở trình duyệt, truy cập https://script.google.com và đăng nhập Google Drive của Admin.
 * 2. Bấm "Dự án mới" (New project), xóa hết mã cũ và dán toàn bộ nội dung file này vào `Code.gs`.
 * 3. Bấm nút "Triển khai" (Deploy) ở góc trên bên phải -> "Tùy chọn triển khai mới" (New deployment).
 *    - Chọn loại (Select type): Nhấp biểu tượng bánh răng ⚙️ -> Chọn "Ứng dụng web" (Web app).
 *    - Mô tả (Description): "VietModHub Cloud Save Hub"
 *    - Thực thi dưới dạng (Execute as): "Tôi" (Me - tức tài khoản Google của Admin).
 *    - Ai có quyền truy cập (Who has access): "Bất kỳ ai" (Anyone - để người dùng VietModHub gửi save).
 * 4. Bấm "Triển khai" (Deploy). Cấp quyền truy cập Google Drive khi được hỏi.
 * 5. Sao chép "URL ứng dụng web" (có dạng https://script.google.com/macros/s/AKfycb.../exec).
 * 6. Dán URL này vào VietModHub (trong phần Cấu hình Máy Chủ Đám Mây) hoặc gán vào DEFAULT_APPS_SCRIPT_URL.
 * =========================================================================================
 */

var ROOT_FOLDER_NAME = "VietModHub_Cloud_Storage";

/**
 * Xử lý GET request (Dùng để kiểm tra trạng thái máy chủ trên trình duyệt)
 */
function doGet(e) {
  var output = {
    status: "online",
    service: "Cổ Ngữ Community Cloud Save Server",
    version: "2.0",
    time: new Date().toISOString(),
    message: "Máy chủ lưu trữ Đám Mây Cổ Ngữ đang hoạt động bình thường!"
  };
  return ContentService.createTextOutput(JSON.stringify(output))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * Xử lý POST request từ ứng dụng VietModHub
 */
function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return jsonResponse(false, "Không nhận được dữ liệu tải lên.");
    }

    var payload = JSON.parse(e.postData.contents);
    var action = payload.action;

    if (action === "ping") {
      return jsonResponse(true, "Kết nối thành công tới Máy Chủ Đám Mây Cổ Ngữ!", { version: "2.0" });
    }

    var cloudId = (payload.cloud_id || "").trim().toLowerCase();
    var password = (payload.password || "").trim();

    if (!cloudId) {
      return jsonResponse(false, "Mã Cloud ID không được để trống.");
    }

    // 1. Kiểm tra format ID hợp lệ (chữ cái, số, gạch dưới, gạch ngang)
    var idRegex = /^[a-z0-9_-]{3,32}$/;
    if (!idRegex.test(cloudId)) {
      return jsonResponse(false, "Mã Cloud ID chỉ được chứa chữ cái, số, dấu gạch nối (- hoặc _) từ 3 đến 32 ký tự.");
    }

    // Lấy hoặc tạo thư mục gốc
    var rootFolder = getOrCreateRootFolder();

    // ==========================================
    // ACTION: REGISTER (Đăng ký ID mới tự chọn)
    // ==========================================
    if (action === "register") {
      if (password.length < 4) {
        return jsonResponse(false, "Mật khẩu bảo vệ phải có ít nhất 4 ký tự.");
      }

      var userFolderIter = rootFolder.getFoldersByName(cloudId);
      if (userFolderIter.hasNext()) {
        var existingUserFolder = userFolderIter.next();
        var accFiles = existingUserFolder.getFilesByName("account.json");
        if (accFiles.hasNext()) {
          return jsonResponse(false, "Mã Cloud ID '" + cloudId + "' đã có người sử dụng! Vui lòng chọn một ID khác.");
        }
      }

      // Tạo thư mục mới cho User
      var newUserFolder = userFolderIter.hasNext() ? userFolderIter.next() : rootFolder.createFolder(cloudId);
      var passHash = hashPassword(password);
      var accData = {
        cloud_id: cloudId,
        pass_hash: passHash,
        created_at: new Date().toISOString()
      };

      // Lưu file account.json
      cleanOldFiles(newUserFolder, "account.json");
      newUserFolder.createFile("account.json", JSON.stringify(accData, null, 2), "application/json");

      return jsonResponse(true, "Tạo Mã Cloud ID '" + cloudId + "' thành công!", { cloud_id: cloudId });
    }

    // ==========================================
    // ACTION: LOGIN (Xác thực ID & Mật khẩu)
    // ==========================================
    if (action === "login") {
      var authRes = authenticateUser(rootFolder, cloudId, password);
      if (!authRes.success) {
        return jsonResponse(false, authRes.error);
      }

      var userFolder = authRes.folder;
      var saveFiles = userFolder.getFilesByName("PlayerProfile.congu_save");
      var hasSave = false;
      var lastSync = null;
      var fileSize = 0;

      if (saveFiles.hasNext()) {
        var saveFile = saveFiles.next();
        hasSave = true;
        lastSync = saveFile.getLastUpdated().toISOString();
        fileSize = saveFile.getSize();
      }

      return jsonResponse(true, "Đăng nhập thành công!", {
        cloud_id: cloudId,
        has_save: hasSave,
        last_sync: lastSync,
        file_size: fileSize
      });
    }

    // ==========================================
    // ACTION: UPLOAD (Tải Save Game lên Drive)
    // ==========================================
    if (action === "upload") {
      var authRes = authenticateUser(rootFolder, cloudId, password);
      if (!authRes.success) {
        return jsonResponse(false, authRes.error);
      }

      var fileDataB64 = payload.file_data;
      if (!fileDataB64) {
        return jsonResponse(false, "Dữ liệu tệp save tải lên bị trống.");
      }

      var userFolder = authRes.folder;
      var bytes = Utilities.base64Decode(fileDataB64);
      var blob = Utilities.newBlob(bytes, "application/octet-stream", "PlayerProfile.congu_save");

      // Xóa tệp cũ nếu đã có để không chiếm dung lượng thừa
      cleanOldFiles(userFolder, "PlayerProfile.congu_save");

      var newFile = userFolder.createFile(blob);
      var updatedAt = newFile.getLastUpdated().toISOString();
      var size = newFile.getSize();

      return jsonResponse(true, "Lưu trữ Save Game lên Mây thành công!", {
        cloud_id: cloudId,
        file_size: size,
        updated_at: updatedAt
      });
    }

    // ==========================================
    // ACTION: DOWNLOAD (Kéo Save Game về máy)
    // ==========================================
    if (action === "download") {
      var authRes = authenticateUser(rootFolder, cloudId, password);
      if (!authRes.success) {
        return jsonResponse(false, authRes.error);
      }

      var userFolder = authRes.folder;
      var saveFiles = userFolder.getFilesByName("PlayerProfile.congu_save");
      if (!saveFiles.hasNext()) {
        return jsonResponse(false, "Mã ID '" + cloudId + "' chưa có bản lưu trữ Save Game nào trên Mây.");
      }

      var saveFile = saveFiles.next();
      var fileBytes = saveFile.getBlob().getBytes();
      var b64Data = Utilities.base64Encode(fileBytes);

      return jsonResponse(true, "Tải bản lưu trữ Save Game thành công!", {
        cloud_id: cloudId,
        file_data: b64Data,
        size_bytes: saveFile.getSize(),
        updated_at: saveFile.getLastUpdated().toISOString()
      });
    }

    return jsonResponse(false, "Thao tác không được hỗ trợ: " + action);

  } catch (err) {
    return jsonResponse(false, "Lỗi máy chủ nội bộ: " + err.toString());
  }
}

/**
 * Helper: Tạo hoặc lấy thư mục gốc VietModHub_Cloud_Storage
 */
function getOrCreateRootFolder() {
  var folders = DriveApp.getFoldersByName(ROOT_FOLDER_NAME);
  if (folders.hasNext()) {
    return folders.next();
  }
  return DriveApp.createFolder(ROOT_FOLDER_NAME);
}

/**
 * Helper: Xác thực tài khoản dựa trên file account.json
 */
function authenticateUser(rootFolder, cloudId, password) {
  var userFolders = rootFolder.getFoldersByName(cloudId);
  if (!userFolders.hasNext()) {
    return { success: false, error: "Không tìm thấy Mã Cloud ID '" + cloudId + "' trên máy chủ. Bạn có muốn Đăng ký mới không?" };
  }

  var userFolder = userFolders.next();
  var accFiles = userFolder.getFilesByName("account.json");
  if (!accFiles.hasNext()) {
    return { success: false, error: "Tài khoản bị lỗi dữ liệu hồ sơ (thiếu account.json)." };
  }

  var accFile = accFiles.next();
  var accContent = accFile.getBlob().getDataAsString();
  var accData = JSON.parse(accContent);

  var expectedHash = accData.pass_hash;
  var inputHash = hashPassword(password);

  if (expectedHash !== inputHash) {
    return { success: false, error: "Mật khẩu bảo vệ không chính xác! Vui lòng kiểm tra lại." };
  }

  return { success: true, folder: userFolder };
}

/**
 * Helper: Băm mật khẩu bằng SHA-256
 */
function hashPassword(pass) {
  var rawHash = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, pass, Utilities.Charset.UTF_8);
  var txtHash = '';
  for (var i = 0; i < rawHash.length; i++) {
    var hashVal = rawHash[i];
    if (hashVal < 0) hashVal += 256;
    var byteString = hashVal.toString(16);
    if (byteString.length == 1) byteString = '0' + byteString;
    txtHash += byteString;
  }
  return txtHash;
}

/**
 * Helper: Dọn dẹp tệp cũ cùng tên trong thư mục
 */
function cleanOldFiles(folder, fileName) {
  var files = folder.getFilesByName(fileName);
  while (files.hasNext()) {
    var f = files.next();
    f.setTrashed(true);
  }
}

/**
 * Helper: Trả về JSON Response chuẩn
 */
function jsonResponse(success, message, extra) {
  var resp = {
    success: success,
    message: message || (success ? "Thành công" : "Thất bại")
  };
  if (!success) {
    resp.error = message;
  }
  if (extra) {
    for (var key in extra) {
      resp[key] = extra[key];
    }
  }
  return ContentService.createTextOutput(JSON.stringify(resp))
    .setMimeType(ContentService.MimeType.JSON);
}
