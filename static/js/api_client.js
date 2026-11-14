// =============================================================================
// CỔ NGỮ (VIETMODHUB) - API CLIENT & NATIVE IPC BRIDGE (api_client.js)
// =============================================================================


    // -------------------------------------------------------------
    // Core Engine Security & PyWebView Native IPC Bridge
    // -------------------------------------------------------------
    function getSessionToken() {
      return document.querySelector('meta[name="session-auth-token"]')?.content || '';
    }

    // Auto-inject session authentication token to all fetch requests
    const _originalFetch = window.fetch;
    window.fetch = function (resource, config = {}) {
      const url = typeof resource === 'string' ? resource : (resource && resource.url ? resource.url : '');
      const token = getSessionToken();
      if (url && (url.startsWith('/api/') || url.includes('/api/'))) {
        config = Object.assign({}, config);
        if (!config.headers) {
          config.headers = {};
        }
        if (config.headers instanceof Headers) {
          if (!config.headers.has('X-App-Auth-Token') && token) {
            config.headers.set('X-App-Auth-Token', token);
          }
        } else if (Array.isArray(config.headers)) {
          if (token) config.headers.push(['X-App-Auth-Token', token]);
        } else {
          if (token) config.headers['X-App-Auth-Token'] = token;
        }
      }
      return _originalFetch.call(this, resource, config);
    };

    let activeFilter = 'installed';
    let activeGenreFilter = 'all';
    let activeModalGameId = null;
    let selectedRating = 5;
    let progressInterval = null;

    // -------------------------------------------------------------
    // Yêu thích game (Steam-style Favorites)
    // -------------------------------------------------------------
    let favoritePendingIds = new Set();
    // Id game vừa được toggle -> chỉ nút tim của game này chạy hiệu ứng "pop" khi render
    let favoriteJustToggledId = null;

    // Cập nhật cờ is_favorite trong gamesList rồi vẽ lại mọi bề mặt hiển thị game.
    // favorites: (tuỳ chọn) danh sách id yêu thích server trả về -> đồng bộ lại toàn bộ.
    // animate: true -> nút tim của game vừa toggle sẽ nảy nhẹ (dùng cho lần vẽ sau phản hồi server).
    function applyFavoriteState(gameId, isFavorite, favorites, animate) {
      if (!Array.isArray(gamesList)) return;

      const target = gamesList.find(g => g.id === gameId);
      if (target) target.is_favorite = !!isFavorite;

      if (Array.isArray(favorites)) {
        const favSet = new Set(favorites.map(id => String(id)));
        gamesList.forEach(g => {
          // Game vừa toggle lấy theo is_favorite (nguồn chuẩn nhất), các game khác theo danh sách
          if (target && g.id === target.id) return;
          g.is_favorite = favSet.has(String(g.id));
        });
      }

      favoriteJustToggledId = animate ? gameId : null;

      // Vẽ lại sidebar + lưới poster + nút tim ở trang chi tiết (nếu đang mở)
      try {
        [
          typeof renderSidebar === 'function' ? renderSidebar : null,
          typeof renderGrid === 'function' ? renderGrid : null,
          typeof syncFavoriteDetailButton === 'function' ? syncFavoriteDetailButton : null
        ].forEach(fn => {
          if (!fn) return;
          try {
            fn();
          } catch (e) {
            console.warn('[Favorite] Lỗi khi vẽ lại giao diện:', e);
          }
        });
      } finally {
        favoriteJustToggledId = null;
      }
    }

    // Bật/tắt Yêu thích với Optimistic UI (đổi ngay trên màn hình, rollback nếu lỗi)
    async function toggleFavorite(gameId) {
      if (!gameId || !Array.isArray(gamesList)) return;

      const game = gamesList.find(g => g.id === gameId);
      if (!game) return;

      // Chống bấm dồn dập: mỗi game chỉ có 1 request đang bay tại một thời điểm
      if (favoritePendingIds.has(gameId)) return;
      favoritePendingIds.add(gameId);

      const prevFavorite = !!game.is_favorite;
      const optimisticFavorite = !prevFavorite;

      // 1. Optimistic UI: đảo trạng thái + render ngay, không chờ server
      applyFavoriteState(gameId, optimisticFavorite);

      try {
        // 2. Gọi API thật (api_client đã tự gắn header X-App-Auth-Token)
        const res = await fetch('/api/favorite/toggle', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: gameId })
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        // Chấp nhận cả trường hợp server trả 200 nhưng body rỗng (backend chưa hoàn thiện)
        let data = null;
        try {
          data = await res.json();
        } catch (_) {
          data = null;
        }
        if (data && data.success === false) {
          throw new Error(data.message || 'Máy chủ không trả về kết quả hợp lệ');
        }

        // 3. Đồng bộ theo phản hồi chuẩn của server (kèm hiệu ứng nảy nhẹ cho nút tim vừa bấm)
        const finalFavorite = (data && typeof data.is_favorite === 'boolean') ? data.is_favorite : optimisticFavorite;
        applyFavoriteState(gameId, finalFavorite, data ? data.favorites : null, true);

        showToast(finalFavorite ? '⭐ Đã thêm vào Yêu thích' : 'Đã bỏ khỏi Yêu thích', 'success');
      } catch (err) {
        // 4. Rollback về trạng thái trước đó khi lỗi mạng / 404 / backend chưa sẵn sàng
        console.warn('[Favorite] Toggle thất bại:', err);
        applyFavoriteState(gameId, prevFavorite);
        showToast('Không thể cập nhật Yêu thích. Vui lòng thử lại!', 'error');
      } finally {
        favoritePendingIds.delete(gameId);
      }
    }

    // -------------------------------------------------------------
    // Thư Viện: "Thêm vào Thư viện" (Bookmarks) - game chưa tải vẫn nằm trong kho
    // -------------------------------------------------------------
    let bookmarkEntries = [];
    let bookmarkIdSet = new Set();
    let bookmarkAppIdSet = new Set();
    let bookmarkTitleSet = new Set();
    let bookmarkPendingKeys = new Set();

    function bookmarkTitleKey(text) {
      const raw = String(text || '');
      const normalized = (typeof removeVietnameseTones === 'function') ? removeVietnameseTones(raw) : raw.toLowerCase();
      return normalized.replace(/[^a-z0-9]+/g, ' ').trim();
    }

    function isGameBookmarked(obj) {
      if (!obj) return false;
      const id = String(obj.id || obj.game_id || '');
      if (id && bookmarkIdSet.has(id)) return true;
      const appid = String(obj.steam_appid || '');
      if (appid && bookmarkAppIdSet.has(appid)) return true;
      const key = bookmarkTitleKey(obj.title);
      return !!(key && bookmarkTitleSet.has(key));
    }

    // Đồng bộ cờ bookmark + trạng thái Thư Viện cho toàn bộ gamesList hiện tại
    function applyBookmarkEntries(entries) {
      bookmarkEntries = Array.isArray(entries) ? entries : [];
      bookmarkIdSet = new Set(bookmarkEntries.map(b => String(b.id)));
      bookmarkAppIdSet = new Set(bookmarkEntries.map(b => String(b.steam_appid || '')).filter(Boolean));
      bookmarkTitleSet = new Set(bookmarkEntries.map(b => bookmarkTitleKey(b.title)).filter(Boolean));

      (Array.isArray(gamesList) ? gamesList : []).forEach(g => {
        const isBm = isGameBookmarked(g);
        g.is_bookmarked = isBm;
        if (g.status_code === 'INSTALLED') {
          g.library_state = 'ready';
        } else if (g.status_code === 'NOT_INSTALLED' || g.status_code === 'UPDATE_DETECTED') {
          g.library_state = 'needs_translation';
        } else {
          g.library_state = isBm ? 'bookmark' : 'unavailable';
        }
      });
    }

    async function fetchBookmarks() {
      try {
        const res = await fetch('/api/bookmarks');
        const data = await res.json();
        if (data && data.success) applyBookmarkEntries(data.bookmarks);
      } catch (err) {
        console.warn('[Bookmark] Không nạp được danh sách Thư viện:', err);
      }
    }

    function refreshBookmarkSurfaces() {
      try {
        const viewDiscovery = document.getElementById('viewDiscovery');
        if (viewDiscovery && !viewDiscovery.classList.contains('hidden') && typeof renderDiscoveryFeed === 'function') {
          renderDiscoveryFeed();
        }
      } catch (err) {
        console.warn('[Bookmark] Lỗi vẽ lại Khám Phá:', err);
      }
    }

    // Bật/tắt lưu game vào Thư viện. Nhận game_id (từ Thư Viện) hoặc payload metadata
    // (từ Khám Phá / Kho Tải Game) để game chưa tải vẫn có đủ thông tin hiển thị.
    async function toggleGameBookmark(target) {
      let payload = null;
      if (typeof target === 'string') {
        const game = (Array.isArray(gamesList) ? gamesList : []).find(g => g.id === target);
        if (!game) return;
        payload = {
          game_id: game.id,
          title: game.title,
          vietnamese_title: game.vietnamese_title,
          steam_appid: game.steam_appid || '',
          cover_url: game.local_cover || game.avatar_url || (game.assets && game.assets.poster) || '',
          genre: game.genre || '',
          source: game.bookmark_source || 'library',
          slug: game.slug || ''
        };
      } else if (target && typeof target === 'object') {
        payload = Object.assign({}, target);
      }
      if (!payload || (!payload.title && !payload.steam_appid && !payload.slug)) return;

      const pendingKey = String(payload.game_id || payload.steam_appid || payload.slug || payload.title);
      if (bookmarkPendingKeys.has(pendingKey)) return;
      bookmarkPendingKeys.add(pendingKey);

      try {
        const res = await fetch('/api/bookmark/toggle', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!data || data.success === false) {
          throw new Error((data && data.message) || 'Máy chủ không phản hồi hợp lệ');
        }

        applyBookmarkEntries(data.bookmarks);
        showToast(
          data.is_bookmarked ? 'Đã thêm vào Thư viện (Chưa tải)' : 'Đã bỏ khỏi Thư viện',
          'success'
        );

        // Nạp lại danh sách game để thẻ "Chưa tải" xuất hiện / biến mất khỏi Thư Viện
        if (typeof fetchGames === 'function') await fetchGames();
        applyBookmarkEntries(data.bookmarks);
        if (typeof renderCounts === 'function') renderCounts();
        if (typeof renderGrid === 'function') renderGrid();
        if (typeof renderSidebar === 'function') renderSidebar();
        refreshBookmarkSurfaces();
        return !!data.is_bookmarked;
      } catch (err) {
        console.warn('[Bookmark] Toggle thất bại:', err);
        showToast('Không thể cập nhật Thư viện. Vui lòng thử lại!', 'error');
        return false;
      } finally {
        bookmarkPendingKeys.delete(pendingKey);
      }
    }

    // Mở Kho Tải Game và tìm sẵn tên game đã lưu để người dùng lấy bộ cài
    function bookmarkOpenDownload(gameId) {
      const game = (Array.isArray(gamesList) ? gamesList : []).find(g => g.id === gameId);
      if (!game) return;
      if (typeof openDiscoveryHub === 'function') {
        openDiscoveryHub();
      }
    }

    // Trỏ tới bản cài sẵn có: mở hộp thoại Game Tự Thêm với thông tin điền sẵn
    function bookmarkLinkExisting(gameId) {
      const game = (Array.isArray(gamesList) ? gamesList : []).find(g => g.id === gameId);
      if (!game || typeof openAddCustomGameModal !== 'function') return;
      openAddCustomGameModal({
        title: game.title,
        steam_appid: game.steam_appid || '',
        cover_url: game.local_cover || game.avatar_url || ''
      });
    }

    // Ghost Library: mở Steam để cài game chưa có trên máy
    async function installGhostGame(gameId) {
      const game = (Array.isArray(gamesList) ? gamesList : []).find(g => g.id === gameId);
      if (!game) return;

      if (!game.steam_appid) {
        showToast('Game không có Steam AppID. Hãy chọn thư mục cài sẵn trên máy!', 'warning');
        if (typeof openGameModal === 'function') openGameModal(game.id);
        return;
      }

      try {
        const res = await fetch('/api/game/steam_install', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ appid: game.steam_appid })
        });
        const data = await res.json();
        showToast((data && data.message) || 'Đã mở Steam để cài game.', data && data.success ? 'success' : 'error');
      } catch (err) {
        showToast('Không mở được Steam: ' + err.message, 'error');
      }
    }

    // Bung save đang chờ trong .congu_save về thư mục game đã cài trên máy này
    async function restorePendingVaultSave(gameId) {
      const game = (Array.isArray(gamesList) ? gamesList : []).find(g => g.id === gameId);
      if (!game) return;
      try {
        showToast('Đang bung save từ Hồ Sơ .congu_save về máy...', 'info');
        const res = await fetch('/api/vault/unpack', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: gameId, backup_existing: true })
        });
        const data = await res.json();
        if (data && data.success) {
          showToast(`Đã khôi phục ${data.unpacked_saves || 0} tệp save cho ${game.vietnamese_title || game.title}!`, 'success');
          await fetchGames();
        } else {
          showToast((data && data.error) || 'Khôi phục save thất bại!', 'error');
        }
      } catch (err) {
        showToast('Lỗi khi khôi phục save: ' + err.message, 'error');
      }
    }

    // Fetch games from backend API (Native PyWebView Bridge + HTTP Fallback)
    async function fetchGames(_attempt = 0) {
      try {
        let gamesData = null;
        let repoData = null;

        // 1. Ưu tiên đọc trực tiếp từ native PyWebView API bridge nếu có (0ms, độc lập hoàn toàn mạng & token)
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.get_games === 'function') {
          try {
            gamesData = await window.pywebview.api.get_games();
          } catch (bridgeErr) {
            console.warn('[Bridge get_games error]', bridgeErr);
          }
        }

        // 2. Fallback qua HTTP Server nội bộ
        if (!gamesData || !Array.isArray(gamesData) || gamesData.length === 0) {
          const resGames = await fetch('/api/games');
          if (!resGames.ok) {
            throw new Error(`HTTP ${resGames.status}`);
          }
          const parsed = await resGames.json();
          if (Array.isArray(parsed) && parsed.length > 0) {
            gamesData = parsed;
          }
        }

        if (!Array.isArray(gamesData) || (gamesData.length === 0 && _attempt < 4)) {
          throw new Error('Danh sách game chưa sẵn sàng');
        }

        gamesList = gamesData || [];

        // Lấy thông tin thư mục repo
        try {
          const resRepo = await fetch('/api/repo_dir');
          if (resRepo.ok) {
            const rData = await resRepo.json();
            const rEl = document.getElementById('repoPathDisplay');
            if (rEl && rData && rData.repo_dir) {
              rEl.innerText = rData.repo_dir;
            }
          }
        } catch (_) {}

        try {
          updateUI();
        } catch (uiErr) {
          console.error('Lỗi khi cập nhật giao diện (updateUI):', uiErr);
        }

        // Tự động kích hoạt polling cho bất kỳ game nào đang chạy ngầm ngoài Desktop/Steam
        if (Array.isArray(gamesList)) {
          gamesList.forEach(g => {
            if (g.playtime && g.playtime.is_running) {
              startPlaytimePolling(g.id);
            }
          });
        }
      } catch (err) {
        console.error('Lỗi nạp dữ liệu:', err);
        // Backend có thể đang quét ổ đĩa ở lần đầu: tự thử lại
        if (_attempt < 5) {
          await new Promise(r => setTimeout(r, 600 * (_attempt + 1)));
          return fetchGames(_attempt + 1);
        }
        showToast('Không thể kết nối đến máy chủ quản lý game!', 'error');
      }
    }

    // Tự động kích hoạt nạp lại khi PyWebView Native Bridge sẵn sàng
    window.addEventListener('pywebviewready', () => {
      fetchGames();
    });

    async function refreshData() {
      const btn = document.querySelector('button[onclick="refreshData()"]');
      const icon = btn ? btn.querySelector('svg, i') : null;
      if (icon) icon.classList.add('animate-spin');
      
      showToast('Đang làm mới và cập nhật danh sách game...', 'info');
      try {
        const syncRes = await fetch('/api/catalog/sync', { method: 'POST' });
        const syncData = await syncRes.json();
        if (syncData && syncData.updated) {
          showToast(syncData.message, 'success');
        } else {
          showToast('Đã làm mới danh sách game!', 'success');
        }
      } catch (e) {
        showToast('Đã làm mới danh sách game!', 'info');
      } finally {
        await fetchGames();
        if (icon) setTimeout(() => icon.classList.remove('animate-spin'), 600);
        // Tab Khám Phá không còn nút Làm mới riêng: icon header làm mới luôn feed
        const discoveryView = document.getElementById('viewDiscovery');
        if (discoveryView && !discoveryView.classList.contains('hidden') && typeof loadDiscoveryFeed === 'function') {
          loadDiscoveryFeed(true, true);
        }
      }
    }

    async function submitUserRating() {
      if (!activeModalGameId) return;
      const comment = document.getElementById('userCommentInput').value.trim();
      try {
        const res = await fetch('/api/rate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: activeModalGameId, stars: selectedRating, comment })
        });
        const data = await res.json();
        showToast(data.message, 'success');
      } catch (err) {
        showToast('Lỗi khi lưu đánh giá!', 'error');
      }
    }

    async function submitBugReport() {
      if (!activeModalGameId) return;
      const desc = document.getElementById('bugReportInput').value.trim();
      if (!desc) {
        showToast('Vui lòng nhập nội dung lỗi câu thoại!', 'warning');
        return;
      }
      try {
        const res = await fetch('/api/bug_report', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: activeModalGameId, description: desc })
        });
        const data = await res.json();
        showToast(data.message, 'success');
        document.getElementById('bugReportInput').value = '';
      } catch (err) {
        showToast('Lỗi khi gửi báo cáo lỗi!', 'error');
      }
    }

    
    async function verifyModIntegrity(gameId) {
      if (!gameId) gameId = activeModalGameId;
      if (!gameId) return;
      showToast('Đang đối chiếu tính toàn vẹn bản Việt hóa (Steam-style)...', 'info');
      try {
        let res = null;
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.verify_mod_integrity === 'function') {
          res = await window.pywebview.api.verify_mod_integrity(gameId);
        } else {
          const resp = await fetch('/api/verify_mod_integrity', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ game_id: gameId })
          });
          res = await resp.json();
        }
        if (res && res.success) {
          if (res.intact) {
            showToast(res.message, 'success');
          } else {
            showToast(res.message, 'warning');
            const restoreBtn = document.getElementById('modalUpdateRestoreBtn');
            const warningBanner = document.getElementById('modalUpdateWarningBanner');
            if (warningBanner) warningBanner.classList.remove('hidden');
            if (restoreBtn) restoreBtn.classList.remove('hidden');
          }
        } else {
          showToast((res && res.message) || 'Không thể kiểm tra toàn vẹn tệp!', 'error');
        }
      } catch (err) {
        showToast('Lỗi khi kiểm tra tính toàn vẹn: ' + err.message, 'error');
      }
    }

    async function checkGameUpdates(gameId) {
      try {
        const res = await fetch('/api/check_updates', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: gameId })
        });
        const data = await res.json();
        if (data.success) {
          if (data.has_update) {
            showToast(data.message || `Phát hiện bản Việt hóa mới (${data.latest_version})!`, 'info');
          } else if (data.status === 'not_installed') {
            showToast(data.message || `Game chưa được cài đặt Việt hóa (Bản mới nhất: ${data.latest_version}).`, 'info');
          } else {
            showToast(data.message || `Bản Việt hóa hiện tại (${data.latest_version}) đã là phiên bản mới nhất!`, 'success');
          }
        } else {
          showToast(data.message || 'Không thể kiểm tra cập nhật!', 'error');
        }
      } catch (err) {
        showToast('Không thể kiểm tra cập nhật!', 'error');
      }
    }
    // Install / Uninstall Trigger
    const _busyGameOps = new Set();
    async function toggleMod(gameId, force = false) {
      if (_busyGameOps.has(gameId)) {
        showToast('Thao tác đang diễn ra, vui lòng không bấm liên tục!', 'info');
        return;
      }
      _busyGameOps.add(gameId);
      try {
        await _toggleModInternal(gameId, force);
      } finally {
        _busyGameOps.delete(gameId);
      }
    }

    async function _toggleModInternal(gameId, force = false) {
      const game = gamesList.find(g => g.id === gameId);
      if (!game) return;
      if (game.status_code === 'UPDATE_DETECTED') {
        force = true;
      }

      if (game.status_code === 'GAME_MISSING') {
        showToast('Vui lòng chọn đường dẫn game trước khi cài đặt!', 'warning');
        openGameModal(game.id);
        return;
      }

      if (game.status_code === 'INSTALLED') {
        // Uninstall
        showProgressModal('Đang Gỡ Bỏ Việt Hóa', `Khôi phục nguyên bản tiếng Anh cho ${game.title}`, game.id, 'uninstall');
        try {
          let data;
          if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.uninstall_mod === 'function') {
            data = await window.pywebview.api.uninstall_mod(game.id);
          } else {
            const res = await fetch('/api/uninstall', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ game_id: game.id })
            });
            data = await res.json();
          }
          if (data && data.is_game_running) {
            closeProgressModal();
            const confirmed = confirm(
              `⚠️ [CẢNH BÁO: TIẾN TRÌNH GAME ĐANG CHẠY]\n\n` +
              `Tiến trình "${data.running_process}" của ${game.title} đang mở trên máy tính.\n` +
              `Nếu tiếp tục gỡ cài đặt, Windows sẽ khóa tệp tin (WinError 32) và gây lỗi.\n\n` +
              `Bạn có muốn CỔ NGỮ tự động đóng tiến trình "${data.running_process}" và tiếp tục gỡ cài đặt không?`
            );
            if (confirmed) {
              showToast(`Đang đóng tiến trình ${data.running_process}...`, 'info');
              let killRes;
              if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.kill_game_process === 'function') {
                killRes = await window.pywebview.api.kill_game_process(gameId);
              } else {
                const kFetch = await fetch('/api/kill_process', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ game_id: gameId })
                });
                killRes = await kFetch.json();
              }
              if (killRes && killRes.success) {
                showToast(killRes.message, 'success');
                setTimeout(() => toggleMod(gameId, force), 600);
              } else {
                showToast((killRes && killRes.message) || 'Không thể đóng game tự động, vui lòng tắt thủ công!', 'error');
              }
            }
            return;
          }
          if (data && data.requires_admin) {
            closeProgressModal();
            const confirmed = confirm(data.message + "\n\nBạn có muốn khởi động lại Cổ Ngữ với quyền Administrator để thao tác thư mục này không?");
            if (confirmed) {
              if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.elevate_admin === 'function') {
                await window.pywebview.api.elevate_admin();
              } else {
                await fetch('/api/elevate_admin', { method: 'POST' });
              }
            }
            return;
          }
          if (data && data.success) {
            showToast(data.message, 'success');
            gamesList = data.games;
            updateUI();
          } else {
            showToast((data && data.message) || 'Lỗi khi gỡ bỏ bản mod!', 'error');
          }
        } catch (err) {
          showToast('Lỗi khi gỡ bỏ bản mod!', 'error');
        }
      } else {
        // Install
        showProgressModal('Đang Cài Đặt Việt Hóa', `Áp dụng gói dịch và font chuẩn cho ${game.title}`, game.id, 'install');
        try {
          let data;
          if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.install_mod === 'function') {
            data = await window.pywebview.api.install_mod(game.id, force);
          } else {
            const res = await fetch('/api/install', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ game_id: game.id, force: force })
            });
            if (!res.ok) {
              let errMsg = `Lỗi máy chủ (${res.status})`;
              try {
                const errData = await res.json();
                errMsg = errData.message || errMsg;
              } catch (_) {
                const text = await res.text();
                if (text.includes('Forbidden')) errMsg = 'Phiên làm việc hết hạn hoặc bị chặn truy cập (403 Forbidden). Vui lòng khởi động lại app!';
                else if (text) errMsg = text.slice(0, 150);
              }
              throw new Error(errMsg);
            }
            data = await res.json();
          }
          if (data && data.is_game_running) {
            closeProgressModal();
            const confirmed = confirm(
              `⚠️ [CẢNH BÁO: TIẾN TRÌNH GAME ĐANG CHẠY]\n\n` +
              `Tiến trình "${data.running_process}" của ${game.title} đang mở trên máy tính.\n` +
              `Nếu tiếp tục cài đặt, Windows sẽ khóa tệp tin (WinError 32) và gây lỗi.\n\n` +
              `Bạn có muốn CỔ NGỮ tự động đóng tiến trình "${data.running_process}" và tiếp tục cài đặt không?`
            );
            if (confirmed) {
              showToast(`Đang đóng tiến trình ${data.running_process}...`, 'info');
              let killRes;
              if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.kill_game_process === 'function') {
                killRes = await window.pywebview.api.kill_game_process(gameId);
              } else {
                const kFetch = await fetch('/api/kill_process', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ game_id: gameId })
                });
                killRes = await kFetch.json();
              }
              if (killRes && killRes.success) {
                showToast(killRes.message, 'success');
                setTimeout(() => toggleMod(gameId, force), 600);
              } else {
                showToast((killRes && killRes.message) || 'Không thể đóng game tự động, vui lòng tắt thủ công!', 'error');
              }
            }
            return;
          }
          if (data && data.requires_admin) {
            closeProgressModal();
            const confirmed = confirm(data.message + "\n\nBạn có muốn khởi động lại Cổ Ngữ với quyền Administrator để thao tác thư mục này không?");
            if (confirmed) {
              if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.elevate_admin === 'function') {
                await window.pywebview.api.elevate_admin();
              } else {
                await fetch('/api/elevate_admin', { method: 'POST' });
              }
            }
            return;
          }
          if (data && data.warning_mismatch) {
            closeProgressModal();
            const confirmed = confirm(data.message);
            if (confirmed) {
              toggleMod(gameId, true);
            }
            return;
          }
          if (data && data.success) {
            let msg = data.message;
            if (game.important_note) msg += ` (Lưu ý: ${game.important_note})`;
            showToast(msg, 'success');
            gamesList = data.games;
            heroGameId = gameId;
            updateUI();
            if (activeModalGameId === gameId) {
              openGameModal(gameId);
            }
            const launchBtn = document.getElementById('progressLaunchBtn');
            if (launchBtn) launchBtn.classList.remove('hidden');
            lucide.createIcons();
          } else {
            const errMsg = (data && data.message) || 'Lỗi khi cài đặt bản mod!';
            showToast(errMsg, 'error');
            document.getElementById('progressStepText').innerText = errMsg;
            document.getElementById('progressIcon').classList.remove('animate-spin');
            document.getElementById('progressIcon').setAttribute('data-lucide', 'alert-triangle');
            document.getElementById('progressIcon').className = 'w-5 h-5 text-rose-400';
            document.getElementById('progressCloseBtn').classList.remove('hidden');
            lucide.createIcons();
          }
        } catch (err) {
          const errMsg = err && err.message ? err.message : 'Lỗi khi cài đặt bản mod!';
          showToast(errMsg, 'error');
          document.getElementById('progressStepText').innerText = errMsg;
          document.getElementById('progressIcon').classList.remove('animate-spin');
          document.getElementById('progressIcon').setAttribute('data-lucide', 'alert-triangle');
          document.getElementById('progressIcon').className = 'w-5 h-5 text-rose-400';
          document.getElementById('progressCloseBtn').classList.remove('hidden');
          lucide.createIcons();
        }
      }
    }

    async function emergencyRestoreGame(gameId) {
      if (_busyGameOps.has(gameId)) {
        showToast('Thao tác đang diễn ra, vui lòng không bấm liên tục!', 'info');
        return;
      }
      _busyGameOps.add(gameId);
      try {
        await _emergencyRestoreGameInternal(gameId);
      } finally {
        _busyGameOps.delete(gameId);
      }
    }

    async function _emergencyRestoreGameInternal(gameId) {
      const game = gamesList.find(g => g.id === gameId);
      if (!game) return;

      if (!game.is_game_found) {
        showToast('Vui lòng chọn đường dẫn game trước khi khôi phục!', 'warning');
        return;
      }

      const confirmed = confirm(
        `[KHÔI PHỤC GỐC KHẨN CẤP / SỬA LỖI GAME]\n\n` +
        `Hệ thống sẽ quét sâu toàn bộ thư mục game "${game.title}" để tìm và phục hồi 100% các tệp tin gốc (.congu_bak), đưa game trở về nguyên bản tiếng Anh sạch sẽ.\n\n` +
        `Bạn có chắc chắn muốn tiến hành không?`
      );
      if (!confirmed) return;

      showProgressModal('Đang Khôi Phục Gốc Khẩn Cấp', `Quét và phục hồi toàn bộ tệp gốc cho ${game.title}...`);
      try {
        let data;
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.emergency_restore_game === 'function') {
          data = await window.pywebview.api.emergency_restore_game(game.id);
        } else {
          const res = await fetch('/api/emergency_restore', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ game_id: game.id })
          });
          data = await res.json();
        }
        closeProgressModal();
        if (data && data.success) {
          showToast(data.message, 'success');
          if (data.games) {
            gamesList = data.games;
            updateUI();
            openGameModal(game.id);
          }
        } else {
          showToast((data && data.message) || 'Lỗi khi khôi phục gốc!', 'error');
        }
      } catch (err) {
        closeProgressModal();
        showToast('Lỗi khi khôi phục gốc: ' + (err && err.message ? err.message : err), 'error');
      }
    }

    async function loadGameAchievements(gameId) {
      const summaryEl = document.getElementById('ach-summary-text');
      const countEl = document.getElementById('ach-count-badge');
      const badgeEl = document.getElementById('ach-percent-badge');
      const barEl = document.getElementById('ach-progress-bar');
      const listEl = document.getElementById('ach-list-container');
      const cardEl = document.getElementById('modalAchievementsCard');
      const barWrap = document.getElementById('achProgressBarWrap');
      const filterWrap = document.getElementById('achFilterTabsWrap');
      const percentWrap = document.getElementById('achPercentBadgeWrap');
      if (!summaryEl) return;

      summaryEl.textContent = 'Đang quét dữ liệu thành tựu...';

      try {
        let data = null;
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.get_game_achievements === 'function') {
          data = await window.pywebview.api.get_game_achievements(gameId);
        } else {
          const resp = await fetch(`/api/achievements/${encodeURIComponent(gameId)}`);
          if (resp.ok) {
            data = await resp.json();
          }
        }

        if (!data || data.total === 0) {
          summaryEl.textContent = 'Trò chơi này không hỗ trợ hoặc chưa có dữ liệu thành tựu.';
          if (barWrap) barWrap.classList.add('hidden');
          if (filterWrap) filterWrap.classList.add('hidden');
          if (percentWrap) percentWrap.classList.add('hidden');
          if (listEl) {
            listEl.innerHTML = '';
            listEl.classList.add('hidden');
          }
          if (cardEl) {
            cardEl.className = 'bg-[#0D1322] border border-white/[0.07] rounded-[6px] p-3 sm:p-3.5 shadow-lg shadow-black/40 space-y-0';
          }
          currentAchievementsData = null;
          if (window.lucide) lucide.createIcons();
          return;
        }

        if (barWrap) barWrap.classList.remove('hidden');
        if (filterWrap) filterWrap.classList.remove('hidden');
        if (percentWrap) percentWrap.classList.remove('hidden');
        if (listEl) listEl.classList.remove('hidden');
        if (cardEl) {
          cardEl.className = 'bg-[#0D1322] border border-white/[0.07] rounded-[6px] p-4 sm:p-5 shadow-lg shadow-black/40 space-y-3';
        }

        window.currentAchievementsData = data;
        currentAchievementsData = data;
        if (data.appid) {
          const g = (gamesList || []).find(x => x.id === gameId);
          if (g && !g.steam_appid) {
            g.steam_appid = data.appid;
          }
          const achAppIdText = document.getElementById('achAppIdBtnText');
          if (achAppIdText && g) {
            achAppIdText.textContent = `Đổi AppID (${data.appid})`;
          }
        }
        summaryEl.textContent = `Đã mở khóa ${data.unlocked_count} / ${data.total} thành tựu (${data.percent}%)`;
        if (countEl) countEl.textContent = `${data.unlocked_count}/${data.total}`;
        if (badgeEl) badgeEl.textContent = `${data.percent}%`;
        if (barEl) barEl.style.width = `${data.percent}%`;

        if (typeof window.renderAchievementsList === 'function') {
          window.renderAchievementsList();
        } else if (typeof renderAchievementsList === 'function') {
          renderAchievementsList();
        }
      } catch (err) {
        console.warn('[Achievements Error]', err);
        summaryEl.textContent = 'Trò chơi này không hỗ trợ hoặc chưa có dữ liệu thành tựu.';
        if (barWrap) barWrap.classList.add('hidden');
        if (filterWrap) filterWrap.classList.add('hidden');
        if (percentWrap) percentWrap.classList.add('hidden');
        if (listEl) {
          listEl.innerHTML = '';
          listEl.classList.add('hidden');
        }
        if (cardEl) {
          cardEl.className = 'bg-[#0D1322] border border-white/[0.07] rounded-[6px] p-3 sm:p-3.5 shadow-lg shadow-black/40 space-y-0';
        }
      }
    }

    async function launchGameFromHub(gameId, _force) {
      if (!gameId) return;
      const game = gamesList.find(g => g.id === gameId);
      if (!game || !game.is_game_found) {
        showToast('Chưa tìm thấy thư mục cài đặt game trên máy! Vui lòng chọn thư mục trước.', 'error');
        return;
      }

      let forceLaunch = _force === true;

      // --- PRE-FLIGHT GAME DOCTOR: kiểm tra VC++ / .NET / DirectX / BepInEx / Font ---
      if (!forceLaunch) {
        try {
          let docRes = null;
          if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.run_game_doctor === 'function') {
            docRes = await window.pywebview.api.run_game_doctor(gameId);
          } else {
            const r = await fetch('/api/game/doctor', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ game_id: gameId })
            });
            docRes = await r.json();
          }
          const doc = docRes && docRes.doctor;
          if (doc && doc.severity && doc.severity !== 'ok') {
            const go = await showGameDoctor(doc);
            if (!go) return;             // Người dùng bấm Huỷ
            forceLaunch = true;
          }
        } catch (e) {
          console.warn('[GameDoctor] Bỏ qua kiểm tra:', e);
        }
      }

      setGamePlayingState(gameId, true);

      let res;
      try {
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.launch_game === 'function') {
          res = await window.pywebview.api.launch_game(gameId, forceLaunch);
        } else {
          const resp = await fetch('/api/launch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ game_id: gameId, force: forceLaunch })
          });
          res = await resp.json();
        }
      } catch (err) {
        showToast('Không thể kết nối đến máy chủ khởi chạy: ' + (err && err.message ? err.message : err), 'error');
        setGamePlayingState(gameId, false);
        return;
      }

      if (res && res.status === 'doctor_warning' && res.doctor) {
        setGamePlayingState(gameId, false);
        const go = await showGameDoctor(res.doctor);
        if (go) return launchGameFromHub(gameId, true);
        return;
      }

      if (!res || res.status === 'error' || res.success === false) {
        if (res && res.status === 'already_running') {
          showToast(res.message, 'info');
          startPlaytimePolling(gameId);
          return;
        }
        showToast((res && res.message) || 'Không thể khởi động game!', 'error');
        setGamePlayingState(gameId, false);
        return;
      }

      showToast(res.message || 'Game đang khởi chạy...', 'success');
      startPlaytimePolling(gameId);

      // Tự động thu nhỏ CỔ NGỮ xuống Taskbar để tiết kiệm ~0% CPU/RAM (trừ khi Game Booster đã ẩn xuống khay hệ thống)
      if (!(res.booster && res.booster.hidden_to_tray)) {
        setTimeout(() => {
          minimizeWindow();
        }, 1200);
      }
    }

    async function launchGame(gameId) {
      return launchGameFromHub(gameId);
    }

    
    async function changeRepoFolder() {
      try {
        const res = await fetch('/api/select_repo_folder', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
          document.getElementById('repoPathDisplay').innerText = data.repo_dir;
          showToast(`Đã đổi kho bản dịch: ${data.repo_dir}`, 'success');
          gamesList = data.games;
          updateUI();
        } else if (data.message) {
          showToast(data.message, 'info');
        }
      } catch (err) {
        showToast('Lỗi khi đổi thư mục kho bản dịch!', 'error');
      }
    }

    
    async function saveCloudUrlForActiveGame() {
      if (!activeModalGameId) return;
      const url = document.getElementById('modalCloudInput').value.trim();
      try {
        const res = await fetch('/api/set_cloud_url', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: activeModalGameId, download_url: url })
        });
        const data = await res.json();
        if (data.success) {
          showToast(data.message, 'success');
          gamesList = data.games;
          updateUI();
        }
      } catch (err) {
        showToast('Lỗi khi lưu link Google Drive!', 'error');
      }
    }

    async function triggerAdminElevation() {
      const confirmed = confirm(
        "Ứng dụng sẽ khởi động lại với quyền Administrator để có đầy đủ quyền ghi tệp vào Program Files.\n\n" +
        "Đường dẫn thư mục đã được lưu an toàn. Bạn có muốn tiếp tục nâng quyền không?"
      );
      if (confirmed) {
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.elevate_admin === 'function') {
          await window.pywebview.api.elevate_admin();
        } else {
          await fetch('/api/elevate_admin', { method: 'POST' });
        }
      }
    }

    let isChoosingFolder = false;
    async function chooseFolderForActiveGame() {
      if (!activeModalGameId || isChoosingFolder) return;
      isChoosingFolder = true;
      try {
        let data = null;
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.select_folder === 'function') {
          try {
            data = await window.pywebview.api.select_folder(activeModalGameId);
          } catch (ipcErr) {
            console.warn('[chooseFolderForActiveGame] Native IPC fallback to HTTP fetch:', ipcErr);
          }
        }
        if (!data) {
          const res = await fetch('/api/select_folder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ game_id: activeModalGameId })
          });
          data = await res.json();
        }

        if (data && data.success) {
          showToast(data.message || `Đã chọn thư mục: ${data.path}`, 'success');
          if (data.games) gamesList = data.games;
          updateUI();
          if (activeModalGameId) {
            openGameModal(activeModalGameId);
            const chosenG = gamesList.find(g => g.id === activeModalGameId);
            if (chosenG && !chosenG.local_cover && !chosenG.avatar_url && (!chosenG.assets || !chosenG.assets.poster)) {
              setTimeout(() => {
                openAvatarPicker(activeModalGameId, chosenG.title || '');
              }, 400);
            }
          }
          if (data.requires_admin) {
            setTimeout(async () => {
              const confirmed = confirm(
                `Thư mục bạn vừa chọn:\n${data.path}\n\n` +
                `Nằm trong phân vùng hệ thống (Program Files) yêu cầu quyền ghi đặc biệt của Windows.\n\n` +
                `Đường dẫn đã được lưu. Bạn có muốn khởi động lại ứng dụng với quyền Administrator ngay bây giờ không?`
              );
              if (confirmed) {
                if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.elevate_admin === 'function') {
                  await window.pywebview.api.elevate_admin();
                } else {
                  await fetch('/api/elevate_admin', { method: 'POST' });
                }
              }
            }, 300);
          }
        } else if (data && data.message) {
          if (data.message.includes("Không có thư mục") || data.message.includes("Chưa chọn")) {
            console.log("[chooseFolderForActiveGame] User closed/cancelled folder picker.");
          } else {
            showToast(data.message, 'warning');
          }
        }
      } catch (err) {
        console.error('[chooseFolderForActiveGame] Error:', err);
        showToast('Lỗi chọn thư mục: ' + (err.message || 'Hộp thoại không phản hồi'), 'error');
      } finally {
        isChoosingFolder = false;
      }
    }

    async function openGameFolder(gameId) {
      try {
        const res = await fetch('/api/open_game_folder', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: gameId })
        });
        const data = await res.json();
        if (!data.success) showToast(data.message, 'error');
      } catch (err) {}
    }

    async function triggerAvatarSearch() {
      const input = document.getElementById('avatarSearchInput');
      const grid = document.getElementById('avatarResultsGrid');
      const spinner = document.getElementById('avatarSearchSpinner');
      const query = (input ? input.value : '').trim();
      if (!query || !grid) return;

      if (spinner) spinner.classList.remove('hidden');
      grid.innerHTML = `<div class="col-span-full text-center py-12 text-slate-300 text-xs font-sans flex flex-col items-center justify-center space-y-2">
        <i data-lucide="loader-2" class="w-6 h-6 text-[#FF2A55] animate-spin"></i>
        <span>Đang kết nối kho game Steam trên mạng để tìm "${query}"...</span>
      </div>`;
      lucide.createIcons();

      try {
        let results = [];
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.search_game_for_avatar === 'function') {
          results = await window.pywebview.api.search_game_for_avatar(query);
        } else {
          const res = await fetch(`/api/game/search_avatar?q=${encodeURIComponent(query)}`);
          results = await res.json();
        }

        cachedCandidates = Array.isArray(results) ? results : [];

        if (cachedCandidates.length === 0) {
          grid.innerHTML = `
            <div class="col-span-full text-center py-12 text-slate-300 text-xs font-sans space-y-2">
              <i data-lucide="search-x" class="w-8 h-8 mx-auto text-slate-500"></i>
              <p>Không tìm thấy kết quả nào cho "${query}".</p>
              <p class="text-[11px] text-slate-400">Hãy thử rút gọn từ khóa hoặc tải ảnh trực tiếp từ máy tính!</p>
            </div>
          `;
          lucide.createIcons();
          return;
        }

        grid.innerHTML = cachedCandidates.map((item, idx) => {
          const isCongu = item.source === 'congu_db';
          const isSteamGrid = item.source === 'steamgriddb';

          let badgeClass = 'bg-[#FF2A55] text-black border border-[#FF2A55]/60';
          let badgeText = 'Steam Store';
          let borderHoverClass = 'hover:border-[#FF2A55] hover:shadow-[0_4px_16px_rgba(255, 42, 85,0.25)]';
          let btnClass = 'bg-[#FF2A55] text-black';
          let subtitleClass = 'text-red-400';

          if (isCongu) {
            badgeClass = 'bg-[#FF2A55] text-white border border-[#FF2A55]/60';
            badgeText = 'Kho Cổ Ngữ';
            borderHoverClass = 'hover:border-[#FF2A55] hover:shadow-[0_4px_16px_rgba(255, 42, 85,0.3)]';
            btnClass = 'bg-[#FF2A55] text-white';
            subtitleClass = 'text-red-400';
          } else if (isSteamGrid) {
            badgeClass = 'bg-[#FF2A55] text-white border border-[#FF2A55]/70 shadow-[0_0_8px_rgba(255, 42, 85,0.5)]';
            badgeText = 'SteamGridDB';
            borderHoverClass = 'hover:border-[#FF2A55] hover:shadow-[0_4px_16px_rgba(255, 42, 85,0.35)]';
            btnClass = 'bg-[#FF2A55] text-white';
            subtitleClass = 'text-red-400';
          }

          const posterUrl = item.avatar_url || item.header_url || item.capsule || '';
          const headerFallback = item.header_url || (item.steam_appid ? `https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/${item.steam_appid}/header.jpg` : '');
          const capsuleFallback = item.capsule || '';

          const safeTitle = (item.title || '').replace(/"/g, '&quot;');
          const safeSubtitle = (item.subtitle || '').replace(/"/g, '&quot;');
          const safeHeader = (headerFallback || '').replace(/"/g, '&quot;');
          const safeCapsule = (capsuleFallback || '').replace(/"/g, '&quot;');

          return `
            <div onclick="selectGameCandidate(${idx})" 
                 class="group cursor-pointer bg-[#0A0E1A] border border-[#1e2340] ${borderHoverClass} rounded-[2px] overflow-hidden flex flex-col transition-all duration-200 hover:-translate-y-1 relative">
              <div class="aspect-[2/3] w-full bg-[#0A0E1A] relative overflow-hidden flex items-center justify-center">
                <!-- Crisp foreground image: full bleed 2:3 vertical poster preview -->
                <img id="cand-fg-${idx}" 
                     src="${posterUrl}" 
                     data-header="${safeHeader}" 
                     data-capsule="${safeCapsule}"
                     onerror="handleCandidateImgError(this, ${idx})"
                     alt="${safeTitle}"
                     class="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105 drop-shadow-md" />
                
                <!-- Source Badge -->
                <span class="absolute top-1.5 left-1.5 z-20 font-pixel text-[9px] font-bold px-1.5 py-0.5 rounded-[2px] ${badgeClass} shadow-md tracking-wide">
                  ${badgeText}
                </span>

                <!-- Hover Overlay Chọn Mẫu Này -->
                <div class="absolute inset-0 z-30 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center p-2 backdrop-blur-[1px]">
                  <span class="pixel-btn ${btnClass} text-[11px] font-bold px-3 py-1.5 rounded-[2px] shadow-[0_2px_8px_rgba(0,0,0,0.35)] flex items-center space-x-1">
                    <i data-lucide="check" class="w-3.5 h-3.5 stroke-[3]"></i>
                    <span>Chọn Mẫu Này</span>
                  </span>
                </div>
              </div>
              <div class="p-2.5 bg-[#0b0d1e] border-t border-[#1a1e38] flex-1 flex flex-col justify-between">
                <div class="text-xs font-bold text-white group-hover:text-[#FF2A55] truncate leading-tight" title="${safeTitle}">${item.title}</div>
                <div class="text-[10px] ${subtitleClass} font-mono truncate mt-1">${safeSubtitle}</div>
              </div>
            </div>
          `;
        }).join('');

        lucide.createIcons();
      } catch (err) {
        grid.innerHTML = `<div class="col-span-full text-center py-12 text-rose-400 text-xs font-sans">Lỗi khi tìm kiếm: ${err}</div>`;
      } finally {
        if (spinner) spinner.classList.add('hidden');
      }
    }

    async function selectGameCandidate(index) {
      const selected = cachedCandidates[index];
      if (!selected || !currentEditingGameId) return;

      const targetId = currentEditingGameId;
      showToast(`Đang đồng bộ ảnh bìa cho ${selected.title}...`, 'info');
      
      try {
        let res = null;
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.apply_selected_avatar === 'function') {
          res = await window.pywebview.api.apply_selected_avatar(targetId, selected);
        } else {
          const resp = await fetch('/api/game/apply_avatar', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ game_id: targetId, selected: selected })
          });
          res = await resp.json();
        }

        if (res && (res.status === 'success' || res.success)) {
          showToast(res.message || 'Đã áp dụng ảnh bìa thành công!', 'success');
          closeAvatarPicker();

          const newImgUrl = res.local_cover || res.avatar_url;
          // 1. Cập nhật ngay lập tức ảnh trên thẻ game ngoài giao diện
          const cardEl = document.querySelector(`[data-game-id="${targetId}"]`);
          if (cardEl) {
            const cardImg = cardEl.querySelector('img');
            if (cardImg && newImgUrl) {
              cardImg.src = newImgUrl;
              cardImg.dataset.fallback = '0';
              cardImg.style.display = '';
            }
          }

          // 2. Cập nhật state gamesList & re-render nếu có danh sách mới
          if (res.games) {
            gamesList = res.games;
            updateUI();
          }

          // 3. Nếu modal chi tiết game đang mở, cập nhật banner modal luôn
          if (activeModalGameId === targetId) {
            const updatedGame = gamesList.find(g => g.id === targetId);
            if (updatedGame) {
              const bannerImg = updatedGame.local_cover || (updatedGame.assets && updatedGame.assets.banner) || updatedGame.header_url || updatedGame.avatar_url || res.avatar_url || '';
              const mb = document.getElementById('modalBannerBg');
              if (mb) mb.style.backgroundImage = `url('${bannerImg}')`;
            }
          }
        } else {
          showToast(res ? res.message : 'Lỗi khi cập nhật ảnh bìa!', 'error');
        }
      } catch (err) {
        showToast(`Lỗi khi gán ảnh: ${err}`, 'error');
      }
    }

    async function changeGameCover(gameId) {
      if (!gameId) return;
      try {
        showToast('Đang mở hộp thoại chọn ảnh bìa...', 'info');
        const res = await fetch('/api/game/custom_cover', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: gameId })
        });
        const data = await res.json();
        if (data.success) {
          showToast(data.message || 'Đã đổi ảnh bìa thành công!', 'success');
          if (data.games) {
            gamesList = data.games;
            updateUI();
            if (activeModalGameId === gameId) {
              const updatedGame = gamesList.find(g => g.id === gameId);
              if (updatedGame) {
                const bannerImg = updatedGame.local_cover || (updatedGame.assets && updatedGame.assets.banner) || updatedGame.header_url || updatedGame.avatar_url || '';
                document.getElementById('modalBannerBg').style.backgroundImage = `url('${bannerImg}')`;
              }
            }
          }
        } else if (data.message && data.message !== 'Chưa chọn ảnh nào.') {
          showToast(data.message, 'warning');
        }
      } catch (err) {
        showToast('Lỗi khi đổi ảnh bìa: ' + err, 'error');
      }
    }

    async function openModFolder(gameId) {
      try {
        const res = await fetch('/api/open_mod_folder', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: gameId })
        });
        const data = await res.json();
        if (!data.success) showToast(data.message, 'error');
      } catch (err) {}
    }

    async function openRepoFolder() {
      try {
        const res = await fetch('/api/open_repo', { method: 'POST' });
        const data = await res.json();
        if (!data.success) showToast(data.message, 'error');
      } catch (err) {}
    }

    async function verifyModIntegrity(gameId) {
      try {
        const res = await fetch('/api/verify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: gameId })
        });
        const data = await res.json();
        showToast(data.message, data.is_valid ? 'success' : 'warning');
      } catch (err) {
        showToast('Lỗi kiểm tra tính toàn vẹn!', 'error');
      }
    }
    // Asynchronously preload steam games database
    async function loadSteamGamesDb() {
      if (steamGamesDb && steamGamesDb.length > 0) return steamGamesDb;
      try {
        const res = await fetch('/static/data/steam_games.json');
        if (res.ok) {
          steamGamesDb = await res.json();
          return steamGamesDb;
        }
      } catch (err) {
        console.warn('Could not load steam_games.json:', err);
      }
      return null;
    }

    function searchSteamLocal(query, limit = 10) {
      if (!steamGamesDb || !steamGamesDb.length) return [];
      const q = query.trim().toLowerCase();
      const exact = [];
      const starts = [];
      const word_starts = [];
      const contains = [];
      const seen = new Set();

      for (let i = 0; i < steamGamesDb.length; i++) {
        const g = steamGamesDb[i];
        if (seen.has(g.id)) continue;
        const nameLow = g.name.toLowerCase();

        if (nameLow === q) {
          exact.push(g);
          seen.add(g.id);
        } else if (nameLow.startsWith(q)) {
          starts.push(g);
          seen.add(g.id);
        } else if (nameLow.split(/\s+/).some(w => w.startsWith(q))) {
          word_starts.push(g);
          seen.add(g.id);
        } else if (nameLow.includes(q)) {
          contains.push(g);
          seen.add(g.id);
        }

        if (seen.size >= 30) break;
      }

      const matched = [...exact, ...starts, ...word_starts, ...contains].slice(0, limit);
      return matched.map(g => ({
        id: g.id,
        name: g.name,
        capsule: `https://cdn.akamai.steamstatic.com/steam/apps/${g.id}/capsule_sm_120.jpg`
      }));
    }

    async function querySteamSearch(query) {
      if (!steamGamesDb) {
        await loadSteamGamesDb();
      }
      if (steamGamesDb && steamGamesDb.length > 0) {
        const localResults = searchSteamLocal(query, 10);
        if (localResults.length > 0) {
          return localResults;
        }
      }
      try {
        const res = await fetch(`/api/steam/search?q=${encodeURIComponent(query)}`);
        if (res.ok) {
          return await res.json();
        }
      } catch (e) {
        console.error('Server search error:', e);
      }
      return [];
    }
    // Load & Render Community Wishlist
    async function loadCommunityRequests() {
      const container = document.getElementById('communityRequestList');
      if (container) {
        container.innerHTML = `
          <div class="py-12 flex flex-col items-center justify-center space-y-3 text-slate-400 font-sans">
            <i data-lucide="loader-2" class="w-6 h-6 text-[#FF2A55] animate-spin"></i>
            <span class="text-xs text-slate-300">Đang nạp bảng nguyện vọng cộng đồng...</span>
          </div>
        `;
        if (window.lucide) lucide.createIcons();
      }

      // 1. Try local server API first
      try {
        const res = await fetch('/api/community_requests');
        if (res.ok) {
          const data = await res.json();
          if (data.success) {
            communityWishlistItems = data.items || [];
            updateCloudStatusBadge(true);
            renderCommunityRequests();
            return;
          }
        }
      } catch (err) {
        console.warn('Local API /api/community_requests unreachable, falling back to direct Firebase REST API:', err);
      }

      // 2. Direct Firebase REST API fallback
      try {
        const fbRes = await fetch(`${FIREBASE_WISHLIST_URL}/community_requests.json`);
        if (fbRes.ok) {
          const fbData = await fbRes.json();
          const items = [];
          const userVoted = JSON.parse(localStorage.getItem('congu_voted_requests') || '[]');
          
          for (const [gid, item] of Object.entries(fbData || {})) {
            if (item && typeof item === 'object') {
              item.id = isNaN(Number(gid)) ? gid : Number(gid);
              item.has_voted = userVoted.includes(String(gid));
              items.push(item);
            }
          }
          items.sort((a, b) => (b.votes || 0) - (a.votes || 0));
          communityWishlistItems = items;
          updateCloudStatusBadge(true);
          renderCommunityRequests();
          return;
        }
      } catch (fbErr) {
        console.error('Firebase direct load error:', fbErr);
      }

      // 3. Fallback error state
      if (container) {
        container.innerHTML = `
          <div class="py-8 text-center text-xs text-rose-400 font-sans">
            Không thể nạp dữ liệu từ Cloud. Vui lòng kiểm tra lại kết nối mạng!
          </div>
        `;
      }
    }

    async function voteCommunityRequest(gameId) {
      const gidStr = String(gameId);
      const item = communityWishlistItems.find(it => String(it.id) === gidStr);
      if (!item) return;

      // 1. Try local server API
      try {
        const res = await fetch('/api/community_requests/vote', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: gameId })
        });
        if (res.ok) {
          const data = await res.json();
          if (data.success) {
            showToast(data.message, data.has_voted ? 'success' : 'info');
            item.votes = data.votes;
            item.has_voted = data.has_voted;
            renderCommunityRequests();
            return;
          }
        }
      } catch (err) {
        console.warn('Local vote API failed, using direct Firebase:', err);
      }

      // 2. Direct Firebase REST fallback
      try {
        let userVoted = JSON.parse(localStorage.getItem('congu_voted_requests') || '[]');
        const isVoted = userVoted.includes(gidStr);
        const newVotes = isVoted ? Math.max(0, (item.votes || 1) - 1) : (item.votes || 0) + 1;
        
        await fetch(`${FIREBASE_WISHLIST_URL}/community_requests/${gidStr}.json`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ votes: newVotes })
        });

        if (isVoted) {
          userVoted = userVoted.filter(x => x !== gidStr);
          item.has_voted = false;
          showToast(`Đã hủy bình chọn cho game '${item.name}'`, 'info');
        } else {
          userVoted.push(gidStr);
          item.has_voted = true;
          showToast(`Đã bình chọn (+1 Vote) cho game '${item.name}'!`, 'success');
        }
        localStorage.setItem('congu_voted_requests', JSON.stringify(userVoted));
        item.votes = newVotes;
        renderCommunityRequests();
      } catch (fbErr) {
        showToast('Lỗi khi gửi bình chọn lên Cloud!', 'error');
      }
    }

    async function submitGameProposal() {
      const gname = document.getElementById('reqGameName').value.trim();
      const gnote = document.getElementById('reqGameNote').value.trim();
      if (!gname) {
        showToast('Vui lòng chọn hoặc nhập tên tựa game mong muốn!', 'warning');
        return;
      }

      const gameId = selectedGameRequest ? selectedGameRequest.id : ('custom_' + Math.floor(Math.random()*1000000));
      const capsule = selectedGameRequest ? selectedGameRequest.capsule : `https://cdn.akamai.steamstatic.com/steam/apps/${gameId}/capsule_sm_120.jpg`;
      const gidStr = String(gameId);

      // Check if already in list
      const existing = communityWishlistItems.find(it => String(it.id) === gidStr);
      if (existing) {
        showToast(`Tựa game '${gname}' đã có trên bảng, đang tự động bình chọn!`, 'info');
        closeProposalDrawer();
        if (!existing.has_voted) {
          await voteCommunityRequest(existing.id);
        }
        return;
      }

      // 1. Try local server API
      try {
        const res = await fetch('/api/community_requests/create', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            game_id: gameId,
            name: gname,
            capsule: capsule,
            note: gnote
          })
        });
        if (res.ok) {
          const data = await res.json();
          if (data.success) {
            showToast(data.message, 'success');
            closeProposalDrawer();
            await loadCommunityRequests();
            return;
          }
        }
      } catch (err) {
        console.warn('Local create API failed, using direct Firebase:', err);
      }

      // 2. Direct Firebase fallback
      try {
        const newItem = {
          id: gameId,
          name: gname,
          capsule: capsule,
          votes: 1,
          status: 'voting',
          note: gnote,
          created_at: new Date().toISOString()
        };
        await fetch(`${FIREBASE_WISHLIST_URL}/community_requests/${gidStr}.json`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(newItem)
        });

        let userVoted = JSON.parse(localStorage.getItem('congu_voted_requests') || '[]');
        if (!userVoted.includes(gidStr)) userVoted.push(gidStr);
        localStorage.setItem('congu_voted_requests', JSON.stringify(userVoted));

        showToast(`Đã đề cử thành công tựa game '${gname}' (+1 Vote)!`, 'success');
        closeProposalDrawer();
        await loadCommunityRequests();
      } catch (fbErr) {
        showToast('Lỗi khi gửi đề cử lên Cloud!', 'error');
      }
    }

    // =========================================================================
    // YÊU CẦU VIỆT HÓA GAME LẺ (Lưu vào Hồ Sơ .congu_save + Cộng dồn Vote Server)
    // =========================================================================
    async function loadMyLocalizationRequests(silent = true) {
      try {
        const res = await fetch('/api/localization/my_requests');
        if (!res.ok) return;
        const data = await res.json();
        if (!data.success) return;

        myLocalizationRequests = data.items || [];
        if (typeof rebuildMyLocRequestMap === 'function') rebuildMyLocRequestMap();

        // Cập nhật lại nhãn "Đã Yêu Cầu Việt Hóa" trên lưới thẻ game
        if (typeof renderGrid === 'function' && Array.isArray(gamesList) && gamesList.length > 0) {
          const grid = document.getElementById('viewBrowseGrid');
          if (!grid || !grid.classList.contains('hidden')) renderGrid();
        }
        if (typeof syncModalRequestLocButton === 'function' && activeModalGameId) {
          syncModalRequestLocButton();
        }
        if (typeof renderMyLocalizationRequests === 'function' && activeWishlistTab === 'mine') {
          renderMyLocalizationRequests();
        }
      } catch (err) {
        if (!silent) console.warn('[LocalizationRequest] Không tải được danh sách yêu cầu:', err);
      }
    }

    async function requestCustomGameLocalization(gameId) {
      const game = (Array.isArray(gamesList) ? gamesList : []).find(g => String(g.id) === String(gameId)) || {};
      const existing = (typeof getMyLocRequest === 'function') ? getMyLocRequest(game) : null;
      if (existing) {
        if (typeof openMyRequestsTab === 'function') openMyRequestsTab();
        return;
      }

      showToast('Đang quét Engine game và gửi yêu cầu Việt hóa...', 'info');
      try {
        const res = await fetch('/api/localization/request', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: gameId, user_note: '' })
        });
        const data = await res.json();

        if (data.success) {
          showToast(data.message || 'Đã gửi yêu cầu Việt hóa!', 'success');
          const eng = data.engine_info && data.engine_info.engine;
          if (eng) {
            setTimeout(() => showToast(`Engine phát hiện: ${eng}`, 'info'), 700);
          }
          await loadMyLocalizationRequests();
          await loadCommunityRequests();
        } else if (data.already_requested) {
          showToast(data.message || 'Bạn đã yêu cầu tựa game này rồi!', 'info');
          await loadMyLocalizationRequests();
        } else {
          showToast(data.message || 'Không gửi được yêu cầu Việt hóa!', 'error');
        }
      } catch (err) {
        console.error('[LocalizationRequest] request failed:', err);
        showToast('Lỗi kết nối máy chủ khi gửi yêu cầu Việt hóa!', 'error');
      }
    }

    async function syncLocalizationRequestsOnStartup() {
      try {
        const res = await fetch('/api/localization/sync', { method: 'POST' });
        const data = await res.json();
        if (!data.success) return;

        locNewsNotifications = data.notifications || [];
        if (typeof renderLocNewsBanner === 'function') renderLocNewsBanner();

        // "Tin vui! Tựa game bạn yêu cầu đã có bản Việt Hóa chính thức!"
        locNewsNotifications.forEach((n, idx) => {
          setTimeout(() => {
            showToast(n.message || `Tin vui! '${n.vietnamese_title || n.title}' đã có bản Việt Hóa chính thức!`, 'success');
          }, 1200 + idx * 1100);
        });

        myLocalizationRequests = data.items || [];
        if (typeof rebuildMyLocRequestMap === 'function') rebuildMyLocRequestMap();
        if (typeof renderGrid === 'function' && Array.isArray(gamesList) && gamesList.length > 0) renderGrid();
      } catch (err) {
        console.warn('[LocalizationRequest] Startup sync bỏ qua (offline):', err);
      }
    }

    // Frameless Window Control Functions
    async function minimizeToTray() {
      showToast('CỔ NGỮ đã ẩn xuống Khay Hệ Thống. Bấm icon góc đồng hồ hoặc mở lại Shortcut Desktop để mở lại.', 'info');
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.minimize_to_tray === 'function') {
        try {
          return await window.pywebview.api.minimize_to_tray();
        } catch (e) {}
      }
      try {
        await fetch('/api/window/minimize_tray', { method: 'POST' });
      } catch (e) {
        console.error('Failed to minimize to tray:', e);
      }
    }

    async function minimizeWindow() {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.minimize_window === 'function') {
        try {
          return await window.pywebview.api.minimize_window();
        } catch (e) {}
      }
      try {
        await fetch('/api/window/minimize', { method: 'POST' });
      } catch (e) {
        console.error('Failed to minimize window:', e);
      }
    }

    async function maximizeWindow() {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.maximize_window === 'function') {
        try {
          return await window.pywebview.api.maximize_window();
        } catch (e) {}
      }
      try {
        await fetch('/api/window/maximize', { method: 'POST' });
      } catch (e) {
        console.error('Failed to maximize window:', e);
      }
    }
    // Thoat hoan toan ung dung ngay lap tuc (Instant Zero-Latency Exit)
    async function quitApp() {
      if (typeof progressInterval !== 'undefined' && progressInterval) {
        showToast('Đang trong quá trình cài đặt hoặc gỡ bỏ bản mod! Vui lòng chờ hoàn tất để không làm hỏng tệp game.', 'error');
        return;
      }

      // 1. Hoi Backend: dang theo doi phien choi game thi AN XUONG KHAY thay vi thoat han
      try {
        let closeRes = null;
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.request_close === 'function') {
          closeRes = await window.pywebview.api.request_close();
        } else {
          const r = await fetch('/api/window/close', { method: 'POST' });
          closeRes = await r.json();
        }
        if (closeRes && closeRes.hidden_to_tray) {
          if (typeof showToast === 'function') {
            showToast(
              closeRes.message ||
                'CỔ NGỮ đang đếm giờ chơi game nên được thu nhỏ xuống Khay Hệ Thống. Nháy đúp icon góc đồng hồ để mở lại.',
              'info'
            );
          }
          return;
        }
      } catch (e) {
        console.warn('[quitApp] request_close fallback:', e);
      }

      // 2. An toan bo giao dien ngay lap tuc (0ms Visual Feedback)
      document.body.style.display = 'none';

      // 3. Gui lenh tat toi PyWebView native window
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.quit_app === 'function') {
        try {
          window.pywebview.api.quit_app();
        } catch (e) {}
      }

      // 4. Gửi lệnh tắt qua fetch keepalive. Không dùng sendBeacon vì nó không
      //    gắn được header token, và tuyệt đối không đưa token vào query string.
      try {
        fetch('/api/app/quit', { method: 'POST', keepalive: true }).catch(() => {});
      } catch (e) {}

      // 5. Dong cua so ngay lap tuc
      window.close();
    }

    async function updateGamepadBadge(gameId) {
      const badge = document.getElementById('modalGamepadBadge');
      if (!badge || !gameId) return;
      try {
        const res = await fetch(`/api/gamepad/config/${encodeURIComponent(gameId)}`);
        const data = await res.json();
        if (data && data.success && data.config && data.config.enabled) {
          badge.classList.remove('hidden');
          badge.textContent = data.config.mode === 'keyboard_mapper' ? 'PHÍM ẢO' : 'XINPUT';
        } else {
          badge.classList.add('hidden');
        }
      } catch (e) {
        badge.classList.add('hidden');
      }
    }

    async function loadGamepadTab(gameId) {
      if (!gameId) return;
      
      // 1. Quét danh sách phần cứng tay cầm đang cắm
      await rescanGamepads(false);

      // 2. Tải cấu hình đã lưu trong .congu_save
      try {
        const res = await fetch(`/api/gamepad/config/${encodeURIComponent(gameId)}`);
        const data = await res.json();
        if (data && data.success && data.config) {
          currentGamepadConfig = data.config;
          applyGamepadConfigToUI(currentGamepadConfig);
        } else {
          // Mặc định
          currentGamepadConfig = {
            enabled: false,
            mode: "xinput_wrapper",
            preset: "platformer",
            vibration: true,
            deadzone: 0.15
          };
          applyGamepadConfigToUI(currentGamepadConfig);
        }
      } catch (e) {
        console.error("Lỗi tải cấu hình gamepad:", e);
      }
      lucide.createIcons();
    }

    async function rescanGamepads(showToastMsg = true) {
      const container = document.getElementById('gamepadListContainer');
      const titleElem = document.getElementById('gamepadHardwareTitle');
      const descElem = document.getElementById('gamepadHardwareDesc');
      const badgeElem = document.getElementById('gamepadTypeBadge');
      const dotElem = document.getElementById('gamepadStatusDot');

      try {
        const res = await fetch('/api/gamepad/controllers');
        const data = await res.json();
        cachedConnectedControllers = (data && data.success && Array.isArray(data.controllers)) ? data.controllers : [];

        if (cachedConnectedControllers.length === 0) {
          if (titleElem) titleElem.textContent = 'Chưa phát hiện tay cầm';
          if (descElem) descElem.textContent = 'Hãy cắm tay cầm PS4, PS5, Xbox, Switch Pro hoặc DirectInput USB/Bluetooth';
          if (badgeElem) {
            badgeElem.textContent = 'OFFLINE';
            badgeElem.className = 'text-[9px] font-pixel px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700 font-bold uppercase';
          }
          if (dotElem) dotElem.className = 'w-2.5 h-2.5 rounded-full bg-slate-500';
          if (container) {
            container.innerHTML = `
              <div class="p-2.5 rounded bg-white/[0.02] border border-white/5 text-center text-xs text-slate-400 font-sans">
                Chưa cắm tay cầm. Khi cắm tay cầm vào PC, bấm nút <strong>Quét Lại</strong> để nhận diện.
              </div>
            `;
          }
        } else {
          const first = cachedConnectedControllers[0];
          if (titleElem) titleElem.textContent = first.name || 'Tay cầm đang kết nối';
          if (descElem) descElem.textContent = `Loại: ${first.type || 'Generic'} • Chuẩn: ${first.api || 'DirectInput'}${first.bluetooth ? ' • Không dây (Bluetooth)' : ' • Dây USB'}`;
          if (badgeElem) {
            badgeElem.textContent = first.type || 'CONNECTED';
            badgeElem.className = 'text-[9px] font-pixel px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 font-bold uppercase';
          }
          if (dotElem) dotElem.className = 'w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse';

          if (container) {
            container.innerHTML = cachedConnectedControllers.map((c, i) => `
              <div class="p-2 rounded bg-white/[0.03] border border-white/5 flex items-center justify-between text-xs">
                <div class="flex items-center space-x-2">
                  <span class="font-pixel text-[10px] text-red-400">#${i + 1}</span>
                  <span class="font-bold text-white">${c.name}</span>
                  <span class="text-[10px] text-slate-400 font-mono">(${c.api})</span>
                </div>
                <div class="flex items-center space-x-2">
                  <span class="text-[10px] font-pixel px-1.5 py-0.2 rounded bg-red-500/20 text-red-300 border border-red-500/30">${c.type}</span>
                  ${c.has_rumble ? '<span class="text-[9px] text-emerald-400 font-bold" title="Hỗ trợ rung">📳 Rung OK</span>' : ''}
                </div>
              </div>
            `).join('');
          }
        }

        if (showToastMsg) {
          showToast(`Đã quét xong: Phát hiện ${cachedConnectedControllers.length} tay cầm đang cắm.`, 'info');
        }
      } catch (e) {
        console.error("Lỗi quét gamepad:", e);
      }
      lucide.createIcons();
    }

    async function testGamepadVibration() {
      const btn = document.getElementById('btnTestVibration');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i><span>Đang rung...</span>`;
        lucide.createIcons();
      }

      try {
        const res = await fetch('/api/gamepad/test_vibration', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ controller_index: 0, duration_sec: 0.6 })
        });
        const data = await res.json();
        if (data && data.success) {
          showToast(data.message || 'Đã kích hoạt rung tay cầm thành công!', 'success');
        } else {
          showToast(data.message || 'Tay cầm không phản hồi rung hoặc chưa kết nối.', 'warning');
        }
      } catch (e) {
        showToast('Lỗi khi kiểm tra rung: ' + e.message, 'error');
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = `<i data-lucide="vibrate" class="w-3.5 h-3.5"></i><span>Rung Thử Nghiệm</span>`;
          lucide.createIcons();
        }
      }
    }

    async function saveGamepadConfigExplicit() {
      await saveGamepadConfigInternal(true);
    }

    async function saveGamepadConfigInternal(showSuccessToast = false) {
      if (!activeModalGameId) return;

      const toggle = document.getElementById('gamepadEnableToggle');
      const modeRadios = document.getElementsByName('gamepadMode');
      let selectedMode = 'xinput_wrapper';
      for (const r of modeRadios) {
        if (r.checked) {
          selectedMode = r.value;
          break;
        }
      }

      const presetSel = document.getElementById('gamepadPresetSelect');
      const vibToggle = document.getElementById('gamepadVibrationToggle');
      const dzRange = document.getElementById('gamepadDeadzoneRange');

      const gyroToggle = document.getElementById('gamepadGyroToggle');
      const gyroRadios = document.getElementsByName('gyroMode');
      let selectedGyroMode = 'aiming_l2';
      for (const r of gyroRadios) {
        if (r.checked) {
          selectedGyroMode = r.value;
          break;
        }
      }
      const gyroSensRange = document.getElementById('gyroSensitivityRange');

      const config = {
        enabled: toggle ? !!toggle.checked : false,
        mode: selectedMode,
        preset: presetSel ? presetSel.value : 'platformer',
        vibration: vibToggle ? !!vibToggle.checked : true,
        deadzone: dzRange ? (parseInt(dzRange.value) / 100.0) : 0.15,
        gyro_enabled: gyroToggle ? !!gyroToggle.checked : false,
        gyro_mode: selectedGyroMode,
        gyro_sensitivity: gyroSensRange ? (parseInt(gyroSensRange.value) / 100.0) : 1.0
      };

      try {
        const res = await fetch('/api/gamepad/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            game_id: activeModalGameId,
            config: config
          })
        });
        const data = await res.json();
        if (data && data.success) {
          updateGamepadBadge(activeModalGameId);
          if (showSuccessToast) {
            showToast('Đã lưu cấu hình tay cầm vào Hồ Sơ .congu_save!', 'success');
          }
        } else if (showSuccessToast) {
          showToast(data.message || 'Không thể lưu cấu hình tay cầm.', 'error');
        }
      } catch (e) {
        if (showSuccessToast) {
          showToast('Lỗi lưu cấu hình: ' + e.message, 'error');
        }
      }
    }

    async function browseCustomGameExe() {
      try {
        const res = await fetch('/api/custom_games/browse_exe', { method: 'POST' });
        const data = await res.json();
        if (data && data.success && data.exe_path) {
          document.getElementById('cgExeInput').value = data.exe_path;
          startCustomGameDetect();
        } else if (data && data.message && data.message !== 'Chưa chọn file thực thi nào.') {
          showToast(data.message, 'warning');
        }
      } catch (e) {
        showToast('Lỗi khi mở hộp thoại chọn file: ' + e.message, 'error');
      }
    }

    function parseSteamAppId(raw) {
      const text = String(raw || '').trim();
      if (!text) return '';
      const urlMatch = text.match(/(?:steampowered\.com|steamdb\.info)\/app\/(\d{3,10})/i);
      if (urlMatch) return urlMatch[1];
      if (/^\d{3,10}$/.test(text)) return text;
      const numMatch = text.match(/\b(\d{4,10})\b/);
      return numMatch ? numMatch[1] : '';
    }

    async function testAchievementOverlay() {
      try {
        const gid = (typeof activeModalGameId !== 'undefined' && activeModalGameId) ? activeModalGameId : '';
        let data = null;
        if (window.pywebview && window.pywebview.api && window.pywebview.api.test_achievement_overlay) {
          data = await window.pywebview.api.test_achievement_overlay(gid);
        } else {
          const res = await fetch('/api/achievements/test_overlay', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ game_id: gid })
          });
          data = await res.json();
        }
        if (data && data.success) {
          showToast(data.message || 'Đã bật thử thông báo Steam ở góc phải dưới màn hình!', 'success');
        } else {
          showToast((data && data.message) || 'Không thể hiển thị thông báo thử nghiệm.', 'warning');
        }
      } catch (e) {
        showToast('Lỗi khi thử thông báo Steam: ' + e.message, 'error');
      }
    }
    window.testAchievementOverlay = testAchievementOverlay;

    async function fetchCustomGameByAppId(fromStep1 = false) {
      const presetEl = document.getElementById('cgPresetAppIdInput');
      const step2El = document.getElementById('cgAppIdInput');
      const rawInput = fromStep1
        ? (presetEl?.value.trim() || step2El?.value.trim() || '')
        : (step2El?.value.trim() || presetEl?.value.trim() || '');
      const cleanAppId = parseSteamAppId(rawInput);

      if (!cleanAppId) {
        showToast('Vui lòng nhập Steam AppID (VD: 2288630) hoặc link Steam Store!', 'warning');
        return;
      }

      const exePath = document.getElementById('cgExeInput')?.value.trim() || '';
      const loading = document.getElementById('cgDetectLoading');
      const resultSec = document.getElementById('cgDetectResultSection');
      const saveBtn = document.getElementById('btnSaveCustomGameToLib');
      const fetchBtn = document.getElementById(fromStep1 ? 'btnFetchCgPresetAppId' : 'btnFetchCgByAppId');

      if (loading) loading.classList.remove('hidden');
      if (fetchBtn) fetchBtn.disabled = true;

      try {
        const res = await fetch('/api/custom_games/fetch_by_appid', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ steam_appid: rawInput, exe_path: exePath })
        });
        const data = await res.json();
        if (data && data.success && data.game) {
          const prevGame = currentDetectedCustomGame;
          const fetched = data.game;
          if (prevGame) {
            if (!fetched.game_root && prevGame.game_root) fetched.game_root = prevGame.game_root;
            if (!fetched.executable_name && prevGame.executable_name) fetched.executable_name = prevGame.executable_name;
            if ((!fetched.engine || fetched.engine === 'Chưa rõ') && prevGame.engine) fetched.engine = prevGame.engine;
          }
          currentDetectedCustomGame = fetched;
          applyDetectedGameToUI(currentDetectedCustomGame);
          if (resultSec) resultSec.classList.remove('hidden');
          if (saveBtn) saveBtn.disabled = !exePath && !currentDetectedCustomGame.executable_name;
          if (saveBtn && (exePath || currentDetectedCustomGame.executable_name)) saveBtn.disabled = false;
          if (!exePath && !currentDetectedCustomGame.executable_name) {
            showToast(`Đã lấy thông tin "${fetched.title}"! Hãy chọn thêm file .exe của game ở Bước 1 để lưu.`, 'info');
          } else {
            showToast(`Đã lấy toàn bộ thông tin "${fetched.title}" từ Steam (giữ nguyên file chạy ${fetched.executable_name})!`, 'success');
          }
        } else {
          showToast((data && data.message) || 'Không tìm thấy game theo Steam AppID này.', 'error');
        }
      } catch (e) {
        showToast('Lỗi khi lấy thông tin từ Steam: ' + e.message, 'error');
      } finally {
        if (loading) loading.classList.add('hidden');
        if (fetchBtn) fetchBtn.disabled = false;
        if (window.lucide) lucide.createIcons();
      }
    }
    window.fetchCustomGameByAppId = fetchCustomGameByAppId;

    async function startCustomGameDetect() {
      const exePath = document.getElementById('cgExeInput').value.trim();
      if (!exePath) {
        showToast('Vui lòng chọn hoặc dán đường dẫn file .exe của game!', 'warning');
        return;
      }

      const presetRaw = document.getElementById('cgPresetAppIdInput')?.value.trim() || '';
      const fallbackRaw = document.getElementById('cgAppIdInput')?.value.trim() || '';
      const overrideAppId = parseSteamAppId(presetRaw || fallbackRaw);

      const loading = document.getElementById('cgDetectLoading');
      const resultSec = document.getElementById('cgDetectResultSection');
      const saveBtn = document.getElementById('btnSaveCustomGameToLib');

      loading.classList.remove('hidden');
      resultSec.classList.add('hidden');
      saveBtn.disabled = true;

      try {
        const res = await fetch('/api/custom_games/detect', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ exe_path: exePath, steam_appid: overrideAppId })
        });
        const data = await res.json();
        if (data && data.success && data.game) {
          currentDetectedCustomGame = data.game;
          applyDetectedGameToUI(currentDetectedCustomGame);
          loading.classList.add('hidden');
          resultSec.classList.remove('hidden');
          saveBtn.disabled = false;
          showToast(`Đã nhận diện thành công: ${data.game.title}!`, 'success');
        } else {
          loading.classList.add('hidden');
          showToast(data.message || 'Không thể nhận diện tựa game này.', 'error');
        }
      } catch (e) {
        loading.classList.add('hidden');
        showToast('Lỗi khi phân tích game: ' + e.message, 'error');
      }
      lucide.createIcons();
    }

    async function submitSaveCustomGame() {
      if (!currentDetectedCustomGame) return;

      const title = document.getElementById('cgTitleInput').value.trim();
      const vnTitle = document.getElementById('cgVnTitleInput').value.trim();
      const dev = document.getElementById('cgDevInput').value.trim();
      const engine = document.getElementById('cgEngineInput').value.trim();
      const rawAppId = document.getElementById('cgAppIdInput').value.trim();
      const appid = parseSteamAppId(rawAppId);
      const coverUrl = document.getElementById('cgPosterUrlInput').value.trim();

      if (!title) {
        showToast('Tên tựa game không được để trống!', 'warning');
        return;
      }
      if (!currentDetectedCustomGame.executable_name) {
        const exeVal = document.getElementById('cgExeInput')?.value.trim() || '';
        if (!exeVal) {
          showToast('Vui lòng chọn file thực thi (.exe) cho game ở Bước 1!', 'warning');
          return;
        }
      }

      currentDetectedCustomGame.title = title;
      currentDetectedCustomGame.vietnamese_title = vnTitle || title;
      currentDetectedCustomGame.developer = dev || 'Chưa rõ';
      currentDetectedCustomGame.engine = engine || 'PC Game';
      currentDetectedCustomGame.steam_appid = appid || '';
      currentDetectedCustomGame.cover_url = coverUrl || '';

      const btn = document.getElementById('btnSaveCustomGameToLib');
      btn.disabled = true;
      btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i><span>Đang thêm vào thư viện...</span>`;
      lucide.createIcons();

      try {
        const res = await fetch('/api/custom_games/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_data: currentDetectedCustomGame })
        });
        const data = await res.json();
        if (data && data.success) {
          showToast(data.message || 'Đã thêm game vào thư viện CỔ NGỮ!', 'success');
          closeCustomGameModal();
          // Cập nhật lại danh sách game
          await fetchGames();
          // Tự động mở trang chi tiết của game vừa thêm
          const newGid = currentDetectedCustomGame.id;
          setTimeout(() => {
            openGameModal(newGid);
          }, 300);
        } else {
          showToast(data.message || 'Không thể lưu game.', 'error');
        }
      } catch (e) {
        showToast('Lỗi khi lưu game: ' + e.message, 'error');
      } finally {
        btn.disabled = false;
        btn.innerHTML = `<i data-lucide="check" class="w-4 h-4"></i><span>LƯU VÀO THƯ VIỆN CỔ NGỮ</span>`;
        lucide.createIcons();
      }
    }

    async function deleteCustomGame(gameId) {
      const game = gamesList.find(g => g.id === gameId);
      const title = game ? (game.vietnamese_title || game.title) : 'tựa game này';
      if (!confirm(`Bạn có chắc chắn muốn xóa "${title}" khỏi thư viện CỔ NGỮ không?\n(File game gốc trên máy tính của bạn sẽ KHÔNG bị xóa).`)) {
        return;
      }

      try {
        const res = await fetch('/api/custom_games/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: gameId })
        });
        const data = await res.json();
        if (data && data.success) {
          showToast('Đã xóa game khỏi thư viện CỔ NGỮ.', 'info');
          closeGameModal();
          await fetchGames();
        } else {
          showToast(data.message || 'Không thể xóa game.', 'error');
        }
      } catch (e) {
        showToast('Lỗi khi xóa game: ' + e.message, 'error');
      }
    }

    async function promptEditCustomGameAppId(customGameId = null, currentAppId = "") {
      const gId = customGameId || activeModalGameId;
      const game = gamesList.find(g => g.id === gId);
      if (!game) return;
      const curr = currentAppId || game.steam_appid || "";

      const input = prompt(
        `Nhập Steam AppID cho tựa game "${game.title}":\n\n(Ví dụ: TOEM là 1307580, Hollow Knight là 367520, Elden Ring là 1245620)\nBạn có thể tra cứu mã AppID nhanh của mọi game tại: https://steamdb.info\n\nSau khi gắn AppID, hệ thống sẽ tự động kéo 100% Thành tựu, cách làm và đồng bộ tiến độ!`,
        curr
      );
      if (input === null) return;
      const newAppId = input.trim();

      try {
        const res = await fetch('/api/custom_games/set_appid', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: gId, steam_appid: newAppId })
        });
        const data = await res.json();
        if (data && data.success) {
          game.steam_appid = newAppId;
          showToast(data.message || `Đã gắn Steam AppID: ${newAppId}`, 'success');
          await loadGameAchievements(gId);
          openGameModal(gId);
        } else {
          showToast(data ? data.message : 'Lỗi khi lưu Steam AppID', 'error');
        }
      } catch (err) {
        showToast('Lỗi kết nối: ' + err.message, 'error');
      }
    }

    // =============================================================================
    // CÀI ĐẶT TRUNG TÂM (UNIFIED SETTINGS MODAL)
    // =============================================================================
    window.currentSettings = null;
    let settingsCustomPathsList = [];

    let latestAppUpdateInfo = null;

    async function checkAppVersionSilent() {
      try {
        const resp = await fetch('/api/version/check');
        const data = await resp.json();
        latestAppUpdateInfo = data || null;
        if (data && data.success && data.has_update) {
          const banner = document.getElementById('updateNotificationBanner');
          const version = document.getElementById('updateBannerVersion');
          const title = document.getElementById('updateBannerTitle');
          if (version) version.textContent = `// BẢN CẬP NHẬT v${data.latest_version}:`;
          if (title) title.textContent = data.title || 'Đã có phiên bản phần mềm mới';
          if (banner) banner.classList.remove('hidden');
          if (window.lucide) lucide.createIcons();
        }
        return data;
      } catch (err) {
        console.warn('[Update] Không thể kiểm tra phiên bản:', err);
        return null;
      }
    }

    function closeUpdateBanner() {
      const banner = document.getElementById('updateNotificationBanner');
      if (banner) banner.classList.add('hidden');
    }

    async function openUpdateModal() {
      const info = latestAppUpdateInfo || await checkAppVersionSilent();
      if (!info || !info.has_update) {
        showToast('Bạn đang sử dụng phiên bản CỔ NGỮ mới nhất!', 'success');
        return;
      }
      const url = info.download_url || info.portable_zip_url;
      if (url) {
        if (typeof openExternalUrl === 'function') {
          openExternalUrl(url);
        } else if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.open_url === 'function') {
          await window.pywebview.api.open_url(url);
        } else {
          window.open(url, '_blank', 'noopener,noreferrer');
        }
      } else {
        showToast(`Đã có bản cập nhật v${info.latest_version}.`, 'info');
      }
    }

    async function initSettingsOnStartup() {
      try {
        const data = await getSettings();
        if (data && data.settings) {
          window.currentSettings = data.settings;
          if (window.currentSettings?.general?.auto_check_update) {
            setTimeout(() => {
              if (typeof checkAppVersionSilent === 'function') checkAppVersionSilent();
            }, 3000);
          }
        }
      } catch (e) {
        console.warn('[Settings] Error loading settings on startup:', e);
      }
    }

    async function getSettings() {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.get_settings === 'function') {
        return await window.pywebview.api.get_settings();
      }
      const res = await fetch('/api/settings');
      return await res.json();
    }

    async function loadSettings() {
      try {
        const data = await getSettings();
        if (!data || !data.settings) return;
        const s = data.settings;
        window.currentSettings = s;

        // TAB 1: General
        const general = s.general || {};
        window.__settingsLoadedTheme = general.theme || 'cyberpunk_default';
        const themeSelect = document.getElementById('settingInput-theme');
        if (themeSelect && general.theme) themeSelect.value = general.theme;
        
        const achSound = document.getElementById('settingInput-achievement_sound');
        if (achSound) achSound.checked = general.achievement_sound !== false;

        const autoUpdate = document.getElementById('settingInput-auto_check_update');
        if (autoUpdate) autoUpdate.checked = general.auto_check_update !== false;

        // TAB 2: Scanner
        const scanner = s.scanner || {};
        const autoScan = document.getElementById('settingInput-auto_scan_on_startup');
        if (autoScan) autoScan.checked = scanner.auto_scan_on_startup !== false;

        const scanSteam = document.getElementById('settingInput-scan_steam');
        if (scanSteam) scanSteam.checked = scanner.scan_steam !== false;

        const scanEpic = document.getElementById('settingInput-scan_epic');
        if (scanEpic) scanEpic.checked = scanner.scan_epic !== false;

        const scanGog = document.getElementById('settingInput-scan_gog');
        if (scanGog) scanGog.checked = scanner.scan_gog !== false;

        settingsCustomPathsList = Array.isArray(scanner.custom_library_paths) ? [...scanner.custom_library_paths] : [];
        renderSettingsCustomPaths(settingsCustomPathsList);

        // TAB 3: In-Game & Booster
        const inGame = s.in_game || {};
        const booster = document.getElementById('settingInput-game_booster_enabled');
        if (booster) booster.checked = inGame.game_booster_enabled !== false;

        const autoMin = document.getElementById('settingInput-auto_minimize_on_launch');
        if (autoMin) autoMin.checked = inGame.auto_minimize_on_launch !== false;

        const qcp = document.getElementById('settingInput-quick_checkpoint_enabled');
        if (qcp) qcp.checked = inGame.quick_checkpoint_enabled !== false;

        const cpSound = document.getElementById('settingInput-checkpoint_sound');
        if (cpSound) cpSound.checked = inGame.checkpoint_sound !== false;

        const sessSum = document.getElementById('settingInput-show_session_summary');
        if (sessSum) sessSum.checked = inGame.show_session_summary !== false;

        const hkSave = document.getElementById('settingInput-hotkey_save');
        if (hkSave) hkSave.value = inGame.hotkey_save || 'Ctrl+F5';

        const hkLoad = document.getElementById('settingInput-hotkey_load');
        if (hkLoad) hkLoad.value = inGame.hotkey_load || 'Ctrl+F9';

        // TAB 4: Downloader
        const dl = s.downloader || {};
        const prefSource = dl.preferred_source || 'github_cdn';
        const radio = document.querySelector(`input[name="preferred_source"][value="${prefSource}"]`);
        if (radio) radio.checked = true;

        const limitSelect = document.getElementById('settingInput-max_download_limit_kb');
        if (limitSelect) limitSelect.value = String(dl.max_download_limit_kb || 0);

        const concurSelect = document.getElementById('settingInput-max_concurrent_downloads');
        if (concurSelect) concurSelect.value = String(dl.max_concurrent_downloads || 3);

        const keepCache = document.getElementById('settingInput-keep_congu_cache');
        if (keepCache) keepCache.checked = !!dl.keep_congu_cache;

        // TAB 4: Cloud Save
        const cs = s.cloud_save || {};
        const cloudId = document.getElementById('settingInput-cloud_id');
        if (cloudId) cloudId.value = cs.cloud_id || '';

        const cloudPass = document.getElementById('settingInput-cloud_password');
        if (cloudPass) cloudPass.value = cs.password || '';

        const autoSync = document.getElementById('settingInput-auto_sync_on_exit');
        if (autoSync) autoSync.checked = cs.auto_sync_on_exit !== false;

        const trackPt = document.getElementById('settingInput-track_playtime');
        if (trackPt) trackPt.checked = cs.track_playtime !== false;

        const offAch = document.getElementById('settingInput-offline_achievements_scan');
        if (offAch) offAch.checked = cs.offline_achievements_scan !== false;

        // TAB 6: Controller
        const ctrl = s.controller || {};
        const ctrlEnabled = document.getElementById('settingInput-controller_enabled');
        if (ctrlEnabled) ctrlEnabled.checked = ctrl.enabled !== false;

        const ctrlVib = document.getElementById('settingInput-controller_vibration');
        if (ctrlVib) ctrlVib.checked = ctrl.vibration !== false;

        const ctrlDz = document.getElementById('settingInput-controller_deadzone');
        const ctrlDzDisp = document.getElementById('controllerDeadzoneDisplay');
        if (ctrlDz) {
          ctrlDz.value = String(ctrl.deadzone || 0.15);
          if (ctrlDzDisp) ctrlDzDisp.innerText = Math.round((ctrl.deadzone || 0.15) * 100) + '%';
        }

      } catch (e) {
        console.warn('[Settings] Lỗi nạp dữ liệu cài đặt:', e);
      }
    }

    async function loadSettingsThemes() {
      const themeSelect = document.getElementById('settingInput-theme');
      if (!themeSelect) return;
      try {
        let themesData = null;
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.get_themes === 'function') {
          themesData = await window.pywebview.api.get_themes();
        } else {
          const res = await fetch('/api/themes');
          themesData = await res.json();
        }
        if (themesData && Array.isArray(themesData.themes)) {
          themeSelect.innerHTML = '';
          themesData.themes.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t.id;
            opt.textContent = `${t.name || t.id} (${t.author || 'Cổ Ngữ'})`;
            themeSelect.appendChild(opt);
          });
          if (themesData.active) {
            themeSelect.value = themesData.active;
          }
        }
      } catch (e) {
        console.warn('[Settings] Lỗi nạp danh sách theme:', e);
      }
    }

    function renderSettingsCustomPaths(paths) {
      const container = document.getElementById('settingsCustomPathsList');
      if (!container) return;
      if (!paths || paths.length === 0) {
        container.innerHTML = `
          <div class="p-3 text-center border border-dashed border-white/10 rounded-[4px] text-slate-500 text-xs">
            <i data-lucide="folder" class="w-4 h-4 mx-auto mb-1 text-slate-600"></i>
            <span>Chưa thêm thư mục game ngoài nào. Bấm "+ Thêm Thư Mục" để bổ sung nơi lưu game của bạn.</span>
          </div>
        `;
        if (window.lucide) lucide.createIcons();
        return;
      }

      container.innerHTML = paths.map((p, idx) => `
        <div class="flex items-center justify-between p-2 rounded-[4px] bg-[#0A0E1A] border border-white/10 text-xs gap-2">
          <div class="flex items-center space-x-2 min-w-0">
            <i data-lucide="folder" class="w-3.5 h-3.5 text-red-400 shrink-0"></i>
            <span class="font-mono text-slate-300 truncate" title="${p}">${p}</span>
          </div>
          <button type="button" onclick="removeCustomLibraryPath(${idx})" class="p-1 text-slate-400 hover:text-red-400 rounded shrink-0 transition" title="Xóa thư mục khỏi danh sách quét">
            <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
          </button>
        </div>
      `).join('');
      if (window.lucide) lucide.createIcons();
    }

    async function addCustomLibraryPath() {
      try {
        let res = null;
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.select_custom_library_folder === 'function') {
          res = await window.pywebview.api.select_custom_library_folder();
        } else {
          const resp = await fetch('/api/settings/browse_folder', { method: 'POST' });
          res = await resp.json();
        }
        if (res && res.success && res.path) {
          const p = res.path;
          if (!settingsCustomPathsList.includes(p)) {
            settingsCustomPathsList.push(p);
            renderSettingsCustomPaths(settingsCustomPathsList);
            showToast(`Đã thêm thư mục quét: ${p}`, 'info');
          } else {
            showToast('Thư mục này đã có trong danh sách quét!', 'info');
          }
        }
      } catch (e) {
        showToast('Lỗi chọn thư mục: ' + e.message, 'error');
      }
    }

    function removeCustomLibraryPath(index) {
      if (index >= 0 && index < settingsCustomPathsList.length) {
        const removed = settingsCustomPathsList.splice(index, 1);
        renderSettingsCustomPaths(settingsCustomPathsList);
        showToast(`Đã xóa thư mục: ${removed[0]}`, 'info');
      }
    }

    async function refreshSettingsCacheInfo() {
      const display = document.getElementById('settingsCacheSizeDisplay');
      if (!display) return;
      display.textContent = 'Đang tính...';
      try {
        let data = null;
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.get_cache_info === 'function') {
          data = await window.pywebview.api.get_cache_info();
        } else {
          const resp = await fetch('/api/cache/info');
          data = await resp.json();
        }
        if (data && data.success) {
          display.textContent = `${data.formatted_size || '0 B'} (${data.file_count || 0} tệp)`;
        } else {
          display.textContent = '0 B';
        }
      } catch (e) {
        display.textContent = 'Không rõ';
      }
    }

    async function clearAppCacheFromSettings() {
      if (!confirm('Bạn có chắc chắn muốn dọn dẹp sạch toàn bộ cache và tệp nén tạm thời không?\n(Dung lượng ổ cứng sẽ được giải phóng, các game đã cài vẫn hoạt động bình thường).')) {
        return;
      }
      const btn = document.getElementById('btnSettingsClearCache');
      if (btn) btn.disabled = true;
      try {
        let data = null;
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.clear_cache === 'function') {
          data = await window.pywebview.api.clear_cache();
        } else {
          const resp = await fetch('/api/cache/clear', { method: 'POST' });
          data = await resp.json();
        }
        if (data && data.success) {
          showToast(data.message || 'Đã dọn dẹp cache thành công!', 'success');
          await refreshSettingsCacheInfo();
        } else {
          showToast(data ? data.message : 'Không thể dọn dẹp cache.', 'error');
        }
      } catch (e) {
        showToast('Lỗi dọn dẹp: ' + e.message, 'error');
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    async function openAppDataFolderFromSettings() {
      try {
        let res = null;
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.open_appdata_folder === 'function') {
          res = await window.pywebview.api.open_appdata_folder();
        } else {
          const resp = await fetch('/api/settings/open_appdata', { method: 'POST' });
          res = await resp.json();
        }
        if (res && res.success) {
          showToast(res.message || 'Đã mở thư mục AppData', 'info');
        } else {
          showToast(res ? res.message : 'Lỗi mở thư mục', 'error');
        }
      } catch (e) {
        showToast('Lỗi: ' + e.message, 'error');
      }
    }

    async function checkAppUpdateFromSettings() {
      const btn = document.getElementById('btnSettingsCheckUpdate');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i><span>Đang kiểm tra...</span>`;
        if (window.lucide) lucide.createIcons();
      }
      try {
        let data = null;
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.check_app_version === 'function') {
          data = await window.pywebview.api.check_app_version();
        } else {
          const resp = await fetch('/api/version/check');
          data = await resp.json();
        }
        if (data && data.has_update) {
          showToast(`Đã có bản cập nhật mới v${data.latest_version}!`, 'success');
          if (typeof openUpdateModal === 'function') {
            openUpdateModal();
          }
        } else {
          showToast('Bạn đang sử dụng phiên bản CỔ NGỮ mới nhất!', 'success');
        }
      } catch (e) {
        showToast('Không thể kiểm tra cập nhật: ' + e.message, 'error');
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = `<i data-lucide="cloud-download" class="w-3.5 h-3.5 text-red-400"></i><span>Kiểm Tra Bản Mới</span>`;
          if (window.lucide) lucide.createIcons();
        }
      }
    }

    async function applyAppUpdateFromSettings() {
      if (!confirm('Ứng dụng sẽ tải bản cập nhật mới, tự đóng, chép đè và khởi động lại.\n\nBạn có chắc chắn muốn cập nhật ngay? (Không nên cập nhật khi đang cài đặt bản mod)')) {
        return;
      }
      const btn = document.getElementById('btnSettingsApplyUpdate');
      const restoreBtnLabel = () => {
        if (!btn) return;
        btn.innerHTML = '<i data-lucide="arrow-up-circle" class="w-3.5 h-3.5"></i><span>Cập Nhật Ngay</span>';
        if (window.lucide) lucide.createIcons();
      };
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i><span>Đang cập nhật...</span>';
        if (window.lucide) lucide.createIcons();
      }
      try {
        let data = null;
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.apply_app_update === 'function') {
          data = await window.pywebview.api.apply_app_update();
        } else {
          const resp = await fetch('/api/app/update', { method: 'POST' });
          data = await resp.json();
        }
        if (data && data.success) {
          showToast(data.message || 'Đang cập nhật ứng dụng...', 'success');
        } else {
          showToast((data && data.message) || 'Không thể cập nhật ứng dụng.', 'error');
          if (btn) btn.disabled = false;
          restoreBtnLabel();
        }
      } catch (e) {
        showToast('Lỗi cập nhật: ' + (e && e.message ? e.message : e), 'error');
        if (btn) btn.disabled = false;
        restoreBtnLabel();
      }
    }

    function switchSettingsTab(tabName) {
      const tabs = ['general', 'scanner', 'in_game', 'downloader', 'cloud_save', 'controller'];
      tabs.forEach(t => {
        const btn = document.getElementById(`settingsTabBtn-${t}`);
        const panel = document.getElementById(`settingsPanel-${t}`);
        if (t === tabName) {
          if (btn) btn.classList.add('is-active');
          if (panel) panel.classList.remove('hidden');
        } else {
          if (btn) btn.classList.remove('is-active');
          if (panel) panel.classList.add('hidden');
        }
      });
      if (tabName === 'downloader') {
        refreshSettingsCacheInfo();
      }
      if (window.lucide) lucide.createIcons();
    }

    function openSettingsModal(defaultTab = 'general') {
      const modal = document.getElementById('settingsModal');
      if (!modal) return;
      modal.classList.remove('hidden');
      switchSettingsTab(defaultTab);
      loadSettingsThemes();
      loadSettings();
      refreshSettingsCacheInfo();
      if (window.lucide) lucide.createIcons();
    }

    function closeSettingsModal() {
      const modal = document.getElementById('settingsModal');
      if (modal) modal.classList.add('hidden');
    }

    async function saveAllSettings() {
      const btn = document.getElementById('btnSaveAllSettings');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i><span>ĐANG LƯU...</span>`;
        if (window.lucide) lucide.createIcons();
      }

      try {
        const new_config = {
          general: {
            theme: document.getElementById('settingInput-theme')?.value || 'cyberpunk_default',
            achievement_sound: !!document.getElementById('settingInput-achievement_sound')?.checked,
            auto_check_update: !!document.getElementById('settingInput-auto_check_update')?.checked,
          },
          scanner: {
            auto_scan_on_startup: !!document.getElementById('settingInput-auto_scan_on_startup')?.checked,
            scan_steam: !!document.getElementById('settingInput-scan_steam')?.checked,
            scan_epic: !!document.getElementById('settingInput-scan_epic')?.checked,
            scan_gog: !!document.getElementById('settingInput-scan_gog')?.checked,
            custom_library_paths: settingsCustomPathsList,
          },
          in_game: {
            game_booster_enabled: !!document.getElementById('settingInput-game_booster_enabled')?.checked,
            auto_minimize_on_launch: !!document.getElementById('settingInput-auto_minimize_on_launch')?.checked,
            quick_checkpoint_enabled: !!document.getElementById('settingInput-quick_checkpoint_enabled')?.checked,
            checkpoint_sound: !!document.getElementById('settingInput-checkpoint_sound')?.checked,
            show_session_summary: !!document.getElementById('settingInput-show_session_summary')?.checked,
            hotkey_save: document.getElementById('settingInput-hotkey_save')?.value || 'Ctrl+F5',
            hotkey_load: document.getElementById('settingInput-hotkey_load')?.value || 'Ctrl+F9',
          },
          downloader: {
            preferred_source: document.querySelector('input[name="preferred_source"]:checked')?.value || 'github_cdn',
            keep_congu_cache: !!document.getElementById('settingInput-keep_congu_cache')?.checked,
            max_concurrent_downloads: parseInt(document.getElementById('settingInput-max_concurrent_downloads')?.value || '3', 10),
            max_download_limit_kb: parseInt(document.getElementById('settingInput-max_download_limit_kb')?.value || '0', 10),
          },
          cloud_save: {
            cloud_id: (document.getElementById('settingInput-cloud_id')?.value || '').trim(),
            password: document.getElementById('settingInput-cloud_password')?.value || '',
            auto_sync_on_exit: !!document.getElementById('settingInput-auto_sync_on_exit')?.checked,
            track_playtime: !!document.getElementById('settingInput-track_playtime')?.checked,
            offline_achievements_scan: !!document.getElementById('settingInput-offline_achievements_scan')?.checked,
          },
          controller: {
            enabled: !!document.getElementById('settingInput-controller_enabled')?.checked,
            vibration: !!document.getElementById('settingInput-controller_vibration')?.checked,
            sound_effects: true,
            deadzone: parseFloat(document.getElementById('settingInput-controller_deadzone')?.value || '0.15'),
          }
        };

        let res = null;
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.update_settings === 'function') {
          res = await window.pywebview.api.update_settings(new_config);
        } else {
          const resp = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(new_config)
          });
          res = await resp.json();
        }

        if (res && res.success) {
          window.currentSettings = res.settings || new_config;

          // Áp dụng Theme ngay lập tức nếu người dùng đã đổi theme trong modal
          const prevTheme = window.__settingsLoadedTheme || '';
          const newTheme = new_config.general.theme;
          if (newTheme && newTheme !== prevTheme && typeof switchTheme === 'function') {
            try { await switchTheme(newTheme); } catch (_) {}
          }
          window.__settingsLoadedTheme = newTheme || prevTheme;

          showToast('Đã lưu toàn bộ cài đặt thành công!', 'success');
          closeSettingsModal();
        } else {
          showToast(res ? res.message : 'Lỗi khi lưu cài đặt!', 'error');
        }
      } catch (e) {
        showToast('Lỗi lưu cài đặt: ' + e.message, 'error');
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = `<i data-lucide="check" class="w-4 h-4 stroke-[2.5]"></i><span>LƯU CÀI ĐẶT</span>`;
          if (window.lucide) lucide.createIcons();
        }
      }
    }

    async function resetSettingsToDefault() {
      if (!confirm('Bạn có chắc chắn muốn đặt lại tất cả cài đặt về giá trị mặc định ban đầu không?')) {
        return;
      }
      const default_config = {
        general: {
          theme: 'cyberpunk_default',
          achievement_sound: true,
          auto_check_update: true,
        },
        scanner: {
          auto_scan_on_startup: true,
          scan_steam: true,
          scan_epic: true,
          scan_gog: true,
          custom_library_paths: [],
        },
        downloader: {
          preferred_source: 'github_cdn',
          keep_congu_cache: false,
          max_concurrent_downloads: 3,
          max_download_limit_kb: 0,
        },
        cloud_save: {
          cloud_id: '',
          password: '',
          auto_sync_on_exit: true,
          track_playtime: true,
          offline_achievements_scan: true,
        }
      };

      let res = null;
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.update_settings === 'function') {
        res = await window.pywebview.api.update_settings(default_config);
      } else {
        const resp = await fetch('/api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(default_config)
        });
        res = await resp.json();
      }

      if (res && res.success) {
        window.currentSettings = res.settings || default_config;
        if (typeof switchTheme === 'function') {
          try { await switchTheme('cyberpunk_default'); } catch (_) {}
        }
        await loadSettings();
        showToast('Đã khôi phục cài đặt mặc định!', 'success');
      } else {
        showToast('Lỗi khi khôi phục mặc định.', 'error');
      }
    }

    // Keyboard shortcuts for Settings: Ctrl+, / Esc
    window.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === ',') {
        e.preventDefault();
        openSettingsModal();
      } else if (e.key === 'Escape') {
        const modal = document.getElementById('settingsModal');
        if (modal && !modal.classList.contains('hidden')) {
          closeSettingsModal();
        }
      }
    });

    // =========================================================================
    // FALLBACK BROWSER HEARTBEAT (Zero-Leak Clean Exit)
    // Gửi ping nhẹ mỗi 5 giây để backend biết cửa sổ Edge/Chrome vẫn còn mở.
    // Khi người dùng đóng cửa sổ trình duyệt, watchdog trong app.py sẽ tự thoát
    // tiến trình sau 15 giây (trừ khi vẫn còn game đang chạy để đếm giờ / Cloud Save).
    // =========================================================================
    (function initUiHeartbeat() {
      const HEARTBEAT_INTERVAL_MS = 5000;

      function sendHeartbeat() {
        try {
          fetch('/api/heartbeat', { method: 'POST', keepalive: true }).catch(() => {});
        } catch (e) {}
      }

      sendHeartbeat();
      setInterval(sendHeartbeat, HEARTBEAT_INTERVAL_MS);
    })();

    // =========================================================================
    // GAME BOOSTER - BẢNG TỔNG KẾT PHIÊN CHƠI
    // Được Python gọi qua window.evaluate_js() ngay sau khi người chơi thoát game.
    // =========================================================================
    window.showSessionSummary = function (payload) {
      try {
        payload = payload || {};
        const esc = (v) =>
          String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
          }[c]));

        const old = document.getElementById('conguSessionSummary');
        if (old) old.remove();

        if (!document.getElementById('conguSessionSummaryStyle')) {
          const st = document.createElement('style');
          st.id = 'conguSessionSummaryStyle';
          st.textContent =
            '@keyframes conguSummaryIn{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:translateY(0)}}' +
            '@keyframes conguSummaryBar{from{width:100%}to{width:0%}}';
          document.head.appendChild(st);
        }

        const row = (label, value, color) =>
          '<div style="display:flex;justify-content:space-between;gap:10px;font-size:12px;line-height:1.5;margin-top:6px;">' +
          '<span style="color:#7b8ba3;">' + esc(label) + '</span>' +
          '<span style="color:' + (color || '#d7e6f5') + ';font-weight:600;text-align:right;">' + esc(value) + '</span></div>';

        const freed = Number(payload.freed_mb || 0);
        const box = document.createElement('div');
        box.id = 'conguSessionSummary';
        box.style.cssText =
          'position:fixed;right:18px;bottom:18px;z-index:99999;width:330px;' +
          'background:rgba(10,14,26,0.97);border:1px solid rgba(255, 42, 85,0.55);border-radius:6px;' +
          'box-shadow:0 12px 40px rgba(0,0,0,0.65),0 0 24px rgba(255, 42, 85,0.15);' +
          'font-family:Inter,system-ui,sans-serif;color:#e6f7ff;overflow:hidden;' +
          'animation:conguSummaryIn .25s ease-out;';

        box.innerHTML =
          '<div style="display:flex;align-items:center;justify-content:space-between;' +
          'padding:10px 12px;background:linear-gradient(90deg,rgba(255, 42, 85,0.16),rgba(255, 42, 85,0.10));' +
          'border-bottom:1px solid rgba(255, 42, 85,0.25);">' +
          '<div style="font-size:11px;letter-spacing:1px;font-weight:700;color:#FF2A55;">// TỔNG KẾT PHIÊN CHƠI</div>' +
          '<button id="conguSummaryClose" style="background:transparent;border:0;color:#8fa6bd;font-size:16px;' +
          'cursor:pointer;line-height:1;padding:0 2px;">&times;</button></div>' +
          '<div style="padding:10px 12px 12px 12px;">' +
          '<div style="font-size:13px;font-weight:700;color:#fff;margin-bottom:2px;">' + esc(payload.game_name || payload.game_id || 'Game') + '</div>' +
          row('Thời lượng phiên', payload.duration_text || '—', '#F2F6FC') +
          (payload.total_played ? row('Tổng giờ chơi', payload.total_played) : '') +
          row('Google Drive', payload.cloud_status || '—', '#8ad4ff') +
          (freed > 0 ? row('RAM đã giải phóng', freed.toFixed(1) + ' MB') : '') +
          '<div style="margin-top:10px;height:3px;background:rgba(255,255,255,0.08);border-radius:2px;overflow:hidden;">' +
          '<div style="height:100%;background:#FF2A55;' +
          'animation:conguSummaryBar 12s linear forwards;"></div></div>' +
          '</div>';

        document.body.appendChild(box);

        const close = () => { const el = document.getElementById('conguSessionSummary'); if (el) el.remove(); };
        box.querySelector('#conguSummaryClose').addEventListener('click', close);
        setTimeout(close, 12000);
        return true;
      } catch (e) {
        console.warn('[showSessionSummary] error', e);
        return false;
      }
    };

    // =========================================================================
    // UNIVERSAL DRAG & DROP - Lớp phủ gợi ý khi kéo file vào cửa sổ
    // =========================================================================
    (function initDragDropOverlay() {
      let overlay = null;
      let depth = 0;

      function ensureOverlay() {
        if (overlay) return overlay;
        overlay = document.createElement('div');
        overlay.id = 'conguDropOverlay';
        overlay.style.cssText =
          'position:fixed;inset:0;z-index:99998;display:none;align-items:center;justify-content:center;' +
          'pointer-events:none;background:rgba(5,8,18,0.72);';
        overlay.innerHTML =
          '<div style="border:2px dashed rgba(255, 42, 85,0.75);border-radius:10px;padding:32px 44px;text-align:center;' +
          'background:rgba(10,14,26,0.92);box-shadow:0 0 40px rgba(255, 42, 85,0.25);font-family:Inter,system-ui,sans-serif;">' +
          '<div style="font-size:32px;line-height:1;margin-bottom:10px;">📥</div>' +
          '<div style="font-size:15px;font-weight:700;color:#FF2A55;letter-spacing:.5px;">THẢ FILE VÀO ĐÂY</div>' +
          '<div style="font-size:12px;color:#9fb3c8;margin-top:8px;line-height:1.7;">' +
          '.exe / .lnk → thêm Game Lẻ &nbsp;·&nbsp; .congu → cài Việt hóa Offline<br>' +
          '.congu_save → nạp Hồ sơ Save &amp; Thành tựu &nbsp;·&nbsp; .congu_theme → đổi Theme</div></div>';
        document.body.appendChild(overlay);
        return overlay;
      }

      window.addEventListener('dragenter', (e) => {
        const types = (e.dataTransfer && e.dataTransfer.types) || [];
        if (!Array.from(types).includes('Files')) return;
        depth += 1;
        ensureOverlay().style.display = 'flex';
      });
      window.addEventListener('dragover', (e) => {
        const types = (e.dataTransfer && e.dataTransfer.types) || [];
        if (!Array.from(types).includes('Files')) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
      });
      window.addEventListener('dragleave', () => {
        depth = Math.max(0, depth - 1);
        if (depth === 0 && overlay) overlay.style.display = 'none';
      });
      window.addEventListener('drop', () => {
        setTimeout(() => { if (overlay) overlay.style.display = 'none'; depth = 0; }, 80);
      });
    })();

    // =========================================================================
    // UNIVERSAL DRAG & DROP - Hiển thị kết quả + hộp thoại xác nhận nạp Hồ sơ
    // =========================================================================
    window.handleDroppedFilesResult = function (res) {
      try {
        const items = (res && res.items) || [];
        if (!items.length) return false;

        const confirmItem = items.find((i) => i.requires_confirm && i.kind === 'vault');
        if (confirmItem) showVaultImportConfirm(confirmItem);

        const rest = items.filter((i) => i.status !== 'confirm');
        if (!rest.length) return true;

        const colorOf = (st) => ({
          ok: '#34D399', installing: '#FF2A55', error: '#F87171', unsupported: '#FBBF24'
        }[st] || '#9fb3c8');

        const html = rest.map((i) => {
          const name = String(i.file || '').split(/[\\/]/).pop();
          return '<div style="display:flex;gap:8px;margin-top:7px;font-size:12px;line-height:1.45;">' +
            '<span style="color:' + colorOf(i.status) + ';font-weight:700;">●</span>' +
            '<span style="flex:1;"><b style="color:#dceaf7;">' + _dndEscapeHtml(name) + '</b><br>' +
            '<span style="color:#93a7bd;">' + _dndEscapeHtml(i.message || '') + '</span></span></div>';
        }).join('');

        let card = document.getElementById('conguDndResult');
        if (card) card.remove();
        card = document.createElement('div');
        card.id = 'conguDndResult';
        card.style.cssText =
          'position:fixed;right:18px;bottom:18px;z-index:99999;width:360px;max-height:60vh;overflow:auto;' +
          'background:rgba(10,14,26,0.98);border:1px solid rgba(255, 42, 85,0.45);border-radius:6px;' +
          'box-shadow:0 12px 40px rgba(0,0,0,0.6);font-family:Inter,system-ui,sans-serif;color:#e6f7ff;';
        card.innerHTML =
          '<div style="display:flex;justify-content:space-between;align-items:center;padding:9px 12px;' +
          'background:linear-gradient(90deg,rgba(255, 42, 85,0.14),rgba(255, 42, 85,0.08));' +
          'border-bottom:1px solid rgba(255, 42, 85,0.22);">' +
          '<span style="font-size:11px;font-weight:700;letter-spacing:1px;color:#FF2A55;">// KẾT QUẢ KÉO &amp; THẢ</span>' +
          '<button id="conguDndClose" style="background:transparent;border:0;color:#8fa6bd;font-size:16px;cursor:pointer;">&times;</button></div>' +
          '<div style="padding:6px 12px 12px 12px;">' + html + '</div>';
        document.body.appendChild(card);
        card.querySelector('#conguDndClose').addEventListener('click', () => card.remove());
        setTimeout(() => { if (card && card.parentNode) card.remove(); }, 14000);

        try {
          if (items.some((i) => i.kind === 'custom_game' && i.status === 'ok') && typeof refreshData === 'function') {
            setTimeout(() => refreshData(), 600);
          }
        } catch (e) {}
        return true;
      } catch (e) {
        console.warn('[handleDroppedFilesResult] error', e);
        return false;
      }
    };

    function _dndEscapeHtml(v) {
      return String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }[c]));
    }

    function showVaultImportConfirm(item) {
      const old = document.getElementById('conguVaultConfirm');
      if (old) old.remove();

      const box = document.createElement('div');
      box.id = 'conguVaultConfirm';
      box.style.cssText =
        'position:fixed;inset:0;z-index:100000;display:flex;align-items:center;justify-content:center;' +
        'background:rgba(4,6,14,0.78);font-family:Inter,system-ui,sans-serif;';
      box.innerHTML =
        '<div style="width:430px;max-width:92vw;background:rgba(12,16,30,0.98);border:1px solid rgba(255, 42, 85,0.5);' +
        'border-radius:8px;box-shadow:0 24px 60px rgba(0,0,0,0.75),0 0 30px rgba(255, 42, 85,0.18);overflow:hidden;">' +
        '<div style="padding:12px 16px;background:linear-gradient(90deg,rgba(255, 42, 85,0.16),rgba(255, 42, 85,0.10));' +
        'border-bottom:1px solid rgba(255, 42, 85,0.25);font-size:12px;font-weight:700;letter-spacing:1px;color:#FF2A55;">' +
        '// NẠP HỒ SƠ SAVE &amp; THÀNH TỰU</div>' +
        '<div style="padding:18px 16px;color:#dbe9f6;font-size:13px;line-height:1.7;">' +
        'Bạn có muốn nạp Hồ sơ Save &amp; Thành tựu của ' +
        '<b style="color:#34D399;">' + _dndEscapeHtml(item.player_name || 'Game Thủ Cổ Ngữ') + '</b> không?' +
        '<div style="margin-top:8px;color:#8fa6bd;font-size:12px;">Hồ sơ chứa <b>' + Number(item.games_count || 0) +
        '</b> game đã lưu. Hồ sơ hiện tại trên máy sẽ được sao lưu thành <code>.congu_vault_bak</code> trước khi thay thế.</div>' +
        '</div>' +
        '<div style="display:flex;justify-content:flex-end;gap:8px;padding:0 16px 16px 16px;">' +
        '<button id="conguVaultCancel" style="padding:7px 14px;font-size:12px;border-radius:4px;cursor:pointer;' +
        'background:#171a2c;color:#c7d5e4;border:1px solid #2b3050;">Để sau</button>' +
        '<button id="conguVaultAccept" style="padding:7px 14px;font-size:12px;border-radius:4px;cursor:pointer;' +
        'background:#0f7a52;color:#eafff6;border:1px solid #34D399;font-weight:700;">Nạp Hồ sơ</button>' +
        '</div></div>';
      document.body.appendChild(box);

      const close = () => box.remove();
      box.querySelector('#conguVaultCancel').addEventListener('click', close);
      box.querySelector('#conguVaultAccept').addEventListener('click', async () => {
        close();
        try {
          if (typeof showToast === 'function') showToast('Đang nạp Hồ sơ Save & Thành tựu...', 'info');
          const r = await fetch('/api/vault/import', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_path: item.path, auto_unpack: true })
          });
          const data = await r.json();
          if (typeof showToast === 'function') {
            showToast(data.success ? (data.message || 'Đã nạp Hồ sơ thành công!') : (data.error || 'Nạp Hồ sơ thất bại.'),
              data.success ? 'success' : 'error');
          }
          if (data.success) {
            setTimeout(() => {
              if (typeof refreshData === 'function') refreshData();
              else location.reload();
            }, 800);
          }
        } catch (e) {
          if (typeof showToast === 'function') showToast('Lỗi nạp Hồ sơ: ' + e, 'error');
        }
      });
    }

    // =========================================================================
    // PRE-FLIGHT GAME DOCTOR - Modal cảnh báo trước khi chơi
    // Trả về Promise<boolean>: true = người dùng chọn "Vẫn chơi", false = Huỷ.
    // =========================================================================
    window.showGameDoctor = function (report) {
      return new Promise((resolve) => {
        try {
          const old = document.getElementById('conguGameDoctor');
          if (old) old.remove();

          const ICONS = { ok: '✅', warn: '⚠️', error: '⛔', skip: '➖' };
          const COLORS = { ok: '#34D399', warn: '#FBBF24', error: '#F87171', skip: '#7b8ba3' };
          const checks = (report && report.checks) || [];

          const rows = checks.map((c) => {
            const st = c.status || 'skip';
            const fix = c.fix_url
              ? '<button data-fix="' + escapeAttr(c.fix_url) + '" class="conguDocFix" ' +
                'style="margin-top:6px;padding:4px 10px;font-size:11px;border-radius:4px;cursor:pointer;' +
                'background:#12314a;color:#9fe8ff;border:1px solid rgba(255, 42, 85,0.45);font-weight:700;">' +
                escapeHtmlText(c.fix_label || 'Tải về') + '</button>'
              : '';
            const hint = c.hint
              ? '<div style="margin-top:4px;color:#8fa6bd;font-size:11.5px;line-height:1.5;">' + escapeHtmlText(c.hint) + '</div>'
              : '';
            return '<div style="display:flex;gap:9px;padding:9px 0;border-bottom:1px solid rgba(255,255,255,0.06);">' +
              '<span style="font-size:15px;line-height:1.2;">' + (ICONS[st] || '➖') + '</span>' +
              '<div style="flex:1;">' +
              '<div style="font-size:12.5px;font-weight:700;color:' + (COLORS[st] || '#9fb3c8') + ';">' +
              escapeHtmlText(c.label || '') + '</div>' +
              '<div style="font-size:12px;color:#c7d5e4;margin-top:2px;line-height:1.55;">' +
              escapeHtmlText(c.detail || '') + '</div>' + hint + fix +
              '</div></div>';
          }).join('');

          const isErr = report && report.severity === 'error';
          const box = document.createElement('div');
          box.id = 'conguGameDoctor';
          box.style.cssText =
            'position:fixed;inset:0;z-index:100001;display:flex;align-items:center;justify-content:center;' +
            'background:rgba(4,6,14,0.82);font-family:Inter,system-ui,sans-serif;';
          box.innerHTML =
            '<div style="width:560px;max-width:94vw;max-height:86vh;display:flex;flex-direction:column;' +
            'background:rgba(12,16,30,0.99);border:1px solid ' + (isErr ? 'rgba(255,77,109,0.6)' : 'rgba(255,176,32,0.55)') + ';' +
            'border-radius:8px;box-shadow:0 24px 60px rgba(0,0,0,0.8);overflow:hidden;">' +
            '<div style="padding:12px 16px;background:linear-gradient(90deg,rgba(255, 42, 85,0.12),rgba(255, 42, 85,0.08));' +
            'border-bottom:1px solid rgba(255, 42, 85,0.22);font-size:12px;font-weight:700;letter-spacing:1px;color:#FF2A55;">' +
            '🩺 // GAME DOCTOR — KIỂM TRA TRƯỚC KHI CHƠI</div>' +
            '<div style="padding:12px 16px 4px 16px;font-size:12.5px;color:#dbe9f6;line-height:1.6;">' +
            escapeHtmlText((report && report.summary) || '') + '</div>' +
            '<div style="padding:0 16px 10px 16px;overflow:auto;flex:1;">' + rows + '</div>' +
            '<div style="display:flex;justify-content:flex-end;gap:8px;padding:12px 16px;' +
            'border-top:1px solid rgba(255,255,255,0.07);">' +
            '<button id="conguDocCancel" style="padding:7px 14px;font-size:12px;border-radius:4px;cursor:pointer;' +
            'background:#171a2c;color:#c7d5e4;border:1px solid #2b3050;">Huỷ</button>' +
            '<button id="conguDocContinue" style="padding:7px 14px;font-size:12px;border-radius:4px;cursor:pointer;' +
            'background:' + (isErr ? '#7a1f2f' : '#0f7a52') + ';color:#fff;border:1px solid ' +
            (isErr ? '#F87171' : '#34D399') + ';font-weight:700;">' +
            (isErr ? 'Vẫn chơi (không khuyến nghị)' : 'Đã hiểu, tiếp tục') + '</button>' +
            '</div></div>';

          document.body.appendChild(box);

          const finish = (val) => { try { box.remove(); } catch (e) {} resolve(val); };
          box.querySelector('#conguDocCancel').addEventListener('click', () => finish(false));
          box.querySelector('#conguDocContinue').addEventListener('click', () => finish(true));
          box.querySelectorAll('.conguDocFix').forEach((btn) => {
            btn.addEventListener('click', () => {
              const url = btn.getAttribute('data-fix');
              if (!url) return;
              try {
                if (window.pywebview && window.pywebview.api && window.pywebview.api.open_url) {
                  window.pywebview.api.open_url(url);
                } else {
                  window.open(url, '_blank');
                }
              } catch (e) { window.open(url, '_blank'); }
            });
          });
        } catch (e) {
          console.warn('[showGameDoctor] error', e);
          resolve(true);
        }
      });
    };

    function escapeHtmlText(v) {
      return String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }[c]));
    }

    function escapeAttr(v) {
      return String(v == null ? '' : v).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }


    // =========================================================================
    // STEAM-STYLE GAME CONTEXT MENU (CHUỘT PHẢI)
    // =========================================================================
    let _activeContextMenuGameId = null;

    function showGameContextMenu(e, gameId) {
      if (!gameId) return;
      e.preventDefault();
      e.stopPropagation();

      const game = gamesList.find(g => g.id === gameId);
      if (!game) return;

      _activeContextMenuGameId = gameId;
      const menu = document.getElementById('gameContextMenu');
      if (!menu) return;

      // Update titles
      const titleElem = document.getElementById('ctxMenuGameTitle');
      const statusElem = document.getElementById('ctxMenuGameStatus');
      if (titleElem) titleElem.textContent = game.vietnamese_title || game.title;
      if (statusElem) statusElem.textContent = game.status_text || (game.is_installed ? 'ĐÃ CÀI VIỆT HÓA' : 'CHƯA CÀI');

      // Update toggle mod button text
      const toggleText = document.getElementById('ctxBtnToggleModText');
      if (toggleText) {
        toggleText.textContent = game.is_installed ? 'Gỡ Bỏ Bản Việt Hóa' : 'Cài Đặt Bản Việt Hóa';
      }

      // Update favorite button text
      const favText = document.getElementById('ctxBtnFavoriteText');
      if (favText) {
        favText.textContent = game.is_favorite ? 'Bỏ khỏi Yêu thích' : 'Thêm vào Yêu thích';
      }

      // Position menu near cursor
      let posX = e.clientX;
      let posY = e.clientY;
      const menuWidth = 224;
      const menuHeight = 220;
      if (posX + menuWidth > window.innerWidth) posX = window.innerWidth - menuWidth - 12;
      if (posY + menuHeight > window.innerHeight) posY = window.innerHeight - menuHeight - 12;

      menu.style.left = `${Math.max(10, posX)}px`;
      menu.style.top = `${Math.max(10, posY)}px`;
      menu.classList.remove('hidden');

      if (window.lucide) lucide.createIcons();
    }

    function closeGameContextMenu() {
      const menu = document.getElementById('gameContextMenu');
      if (menu) menu.classList.add('hidden');
    }

    document.addEventListener('click', (e) => {
      const menu = document.getElementById('gameContextMenu');
      if (menu && !menu.contains(e.target)) {
        closeGameContextMenu();
      }
    });

    document.addEventListener('contextmenu', (e) => {
      const menu = document.getElementById('gameContextMenu');
      if (menu && !e.target.closest('[data-game-id], .sidebar-game-row, .game-card')) {
        closeGameContextMenu();
      }
    });

    function ctxActionPlay() {
      const gid = _activeContextMenuGameId;
      closeGameContextMenu();
      if (gid) launchGame(gid);
    }

    function ctxActionToggleMod() {
      const gid = _activeContextMenuGameId;
      closeGameContextMenu();
      if (gid) toggleMod(gid);
    }

    function ctxActionVerify() {
      const gid = _activeContextMenuGameId;
      closeGameContextMenu();
      if (gid) verifyModIntegrity(gid);
    }

    function ctxActionToggleFavorite() {
      const gid = _activeContextMenuGameId;
      closeGameContextMenu();
      if (gid) toggleFavoriteGame(gid);
    }

    function ctxActionOpenFolder() {
      const gid = _activeContextMenuGameId;
      closeGameContextMenu();
      if (gid) openGameFolder(gid);
    }

    function ctxActionOpenDetail() {
      const gid = _activeContextMenuGameId;
      closeGameContextMenu();
      if (gid) selectGame(gid);
    }

    // =========================================================================
    // MOTION GYRO LIVE VISUALIZER & TESTER
    // =========================================================================
    let gyroLiveTestInterval = null;
    let isGyroLiveTesting = false;

    async function toggleGyroLiveTest() {
      const btn = document.getElementById('btnTestGyroLive');
      const btnText = document.getElementById('btnTestGyroLiveText');
      const container = document.getElementById('gyroLiveMetersContainer');

      if (isGyroLiveTesting) {
        // Tắt test
        isGyroLiveTesting = false;
        if (gyroLiveTestInterval) {
          clearInterval(gyroLiveTestInterval);
          gyroLiveTestInterval = null;
        }
        if (btnText) btnText.textContent = 'Kiểm Tra Con Quay';
        if (btn) btn.className = 'pixel-btn px-3 py-1.5 text-xs bg-red-600/30 hover:bg-red-500/40 text-red-300 border border-red-400/50 rounded font-bold flex items-center space-x-1.5 transition';
        if (container) container.classList.add('hidden');
        try {
          await fetch('/api/gamepad/gyro/test_toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enable: false })
          });
        } catch (e) {}
      } else {
        // Bật test
        try {
          const res = await fetch('/api/gamepad/gyro/test_toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enable: true })
          });
          const data = await res.json();
          if (!data || !data.running) {
            showToast('Không thể kết nối cảm biến con quay. Hãy đảm bảo tay cầm PS4/PS5 đang cắm qua USB/Bluetooth!', 'warning');
            return;
          }
        } catch (e) {
          showToast('Lỗi bật test con quay: ' + e.message, 'error');
          return;
        }

        isGyroLiveTesting = true;
        if (btnText) btnText.textContent = 'Dừng Kiểm Tra';
        if (btn) btn.className = 'pixel-btn px-3 py-1.5 text-xs bg-rose-600/30 hover:bg-rose-500/40 text-rose-300 border border-rose-400/50 rounded font-bold flex items-center space-x-1.5 transition';
        if (container) container.classList.remove('hidden');

        // Bắt đầu đọc số liệu liên tục
        gyroLiveTestInterval = setInterval(async () => {
          if (!isGyroLiveTesting) return;
          try {
            const res = await fetch('/api/gamepad/gyro/live');
            const data = await res.json();
            if (data && data.success && data.state) {
              const s = data.state;
              const pitchEl = document.getElementById('gyroMeterPitch');
              const yawEl = document.getElementById('gyroMeterYaw');
              const rollEl = document.getElementById('gyroMeterRoll');
              const l2Badge = document.getElementById('gyroLiveL2Badge');

              if (pitchEl) pitchEl.textContent = `${(s.pitch || 0).toFixed(1)}°/s`;
              if (yawEl) yawEl.textContent = `${(s.yaw || 0).toFixed(1)}°/s`;
              if (rollEl) rollEl.textContent = `${(s.roll || 0).toFixed(1)}°/s`;
              if (l2Badge) {
                const l2Val = s.l2_trigger || 0;
                l2Badge.textContent = `L2 (Ngắm): ${l2Val}`;
                l2Badge.className = l2Val > 30 
                  ? 'px-1.5 py-0.5 rounded bg-red-500/30 text-[10px] text-red-300 font-mono font-bold border border-red-400/60'
                  : 'px-1.5 py-0.5 rounded bg-slate-800 text-[10px] text-slate-300 font-mono';
              }
            }
          } catch (e) {}
        }, 60);
      }
    }
