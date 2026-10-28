// =============================================================================
// CỔ NGỮ (VIETMODHUB) - API CLIENT & NATIVE IPC BRIDGE (api_client.js)
// =============================================================================


    // -------------------------------------------------------------
    // Core Engine Security & PyWebView Native IPC Bridge
    // -------------------------------------------------------------
    const SESSION_AUTH_TOKEN = document.querySelector('meta[name="session-auth-token"]')?.content || '';

    // Auto-inject session authentication token to all fetch requests
    const _originalFetch = window.fetch;
    window.fetch = function (resource, config = {}) {
      const url = typeof resource === 'string' ? resource : (resource && resource.url ? resource.url : '');
      if (url && (url.startsWith('/api/') || url.includes('/api/'))) {
        config = Object.assign({}, config);
        if (!config.headers) {
          config.headers = {};
        }
        if (config.headers instanceof Headers) {
          if (!config.headers.has('X-App-Auth-Token') && SESSION_AUTH_TOKEN) {
            config.headers.set('X-App-Auth-Token', SESSION_AUTH_TOKEN);
          }
        } else if (Array.isArray(config.headers)) {
          if (SESSION_AUTH_TOKEN) config.headers.push(['X-App-Auth-Token', SESSION_AUTH_TOKEN]);
        } else {
          if (SESSION_AUTH_TOKEN) config.headers['X-App-Auth-Token'] = SESSION_AUTH_TOKEN;
        }
      }
      return _originalFetch.call(this, resource, config);
    };

    let activeFilter = 'all';
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

    // Fetch games from backend API
    async function fetchGames() {
      try {
        const [resGames, resRepo] = await Promise.all([
          fetch('/api/games'),
          fetch('/api/repo_dir')
        ]);
        gamesList = await resGames.json();
        try {
          const repoData = await resRepo.json();
          const rEl = document.getElementById('repoPathDisplay');
          if (rEl) rEl.innerText = (repoData && repoData.repo_dir) || 'Chưa thiết lập kho bản dịch';
        } catch (_) {}
        updateUI();
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
        showToast('Không thể kết nối đến máy chủ quản lý game!', 'error');
      }
    }

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

    async function checkGameUpdates(gameId) {
      try {
        const res = await fetch('/api/check_updates', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: gameId })
        });
        const data = await res.json();
        if (data.success) {
          showToast(`Bản Việt hóa hiện tại (${data.latest_version}) đã là phiên bản mới nhất!`, 'success');
        }
      } catch (err) {
        showToast('Không thể kiểm tra cập nhật!', 'error');
      }
    }
    // Install / Uninstall Trigger
    async function toggleMod(gameId, force = false) {
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
      if (!summaryEl || !listEl) return;

      summaryEl.textContent = 'Đang quét dữ liệu thành tựu...';
      listEl.innerHTML = '<div class="col-span-full py-5 text-center text-xs text-slate-500 flex items-center justify-center gap-2"><i data-lucide="loader-2" class="w-4 h-4 animate-spin text-cyan-400"></i><span>Đang nạp thành tựu và hướng dẫn mở khóa...</span></div>';
      if (window.lucide) lucide.createIcons();

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
          summaryEl.textContent = 'Chưa phát hiện file thành tựu hoặc game không có thành tựu.';
          if (countEl) countEl.textContent = '0/0';
          if (badgeEl) badgeEl.textContent = '0%';
          if (barEl) barEl.style.width = '0%';
          listEl.innerHTML = '<div class="py-6 text-center text-xs text-slate-500 italic">Chưa phát hiện dữ liệu thành tựu. Hãy vào game và hoàn thành thử thách!</div>';
          currentAchievementsData = null;
          if (window.lucide) lucide.createIcons();
          return;
        }

        currentAchievementsData = data;
        summaryEl.textContent = `Đã mở khóa ${data.unlocked_count} / ${data.total} thành tựu (${data.percent}%)`;
        if (countEl) countEl.textContent = `${data.unlocked_count}/${data.total}`;
        if (badgeEl) badgeEl.textContent = `${data.percent}%`;
        if (barEl) barEl.style.width = `${data.percent}%`;

        renderAchievementsList();
      } catch (err) {
        console.warn('[Achievements Error]', err);
        summaryEl.textContent = 'Không thể nạp dữ liệu thành tựu.';
      }
    }

    async function launchGameFromHub(gameId) {
      if (!gameId) return;
      const game = gamesList.find(g => g.id === gameId);
      if (!game || !game.is_game_found) {
        showToast('Chưa tìm thấy thư mục cài đặt game trên máy! Vui lòng chọn thư mục trước.', 'error');
        return;
      }

      setGamePlayingState(gameId, true);

      let res;
      try {
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.launch_game === 'function') {
          res = await window.pywebview.api.launch_game(gameId);
        } else {
          const resp = await fetch('/api/launch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ game_id: gameId })
          });
          res = await resp.json();
        }
      } catch (err) {
        showToast('Không thể kết nối đến máy chủ khởi chạy: ' + (err && err.message ? err.message : err), 'error');
        setGamePlayingState(gameId, false);
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

      // Tự động thu nhỏ CỔ NGỮ xuống Taskbar để tiết kiệm ~0% CPU/RAM và người chơi tập trung vào game
      setTimeout(() => {
        minimizeWindow();
      }, 1200);
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

    async function chooseFolderForActiveGame() {
      if (!activeModalGameId) return;
      try {
        const res = await fetch('/api/select_folder', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: activeModalGameId })
        });
        const data = await res.json();
        if (data.success) {
          showToast(data.message || `Đã chọn thư mục: ${data.path}`, 'success');
          gamesList = data.games;
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
        } else if (data.message) {
          showToast(data.message, 'warning');
        }
      } catch (err) {
        showToast('Lỗi mở hộp thoại chọn thư mục!', 'error');
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
        <i data-lucide="loader-2" class="w-6 h-6 text-[#00F0FF] animate-spin"></i>
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

          let badgeClass = 'bg-[#00F0FF] text-black border border-[#00F0FF]/60';
          let badgeText = 'Steam Store';
          let borderHoverClass = 'hover:border-[#00F0FF] hover:shadow-[0_4px_16px_rgba(0,240,255,0.25)]';
          let btnClass = 'bg-[#00F0FF] text-black';
          let subtitleClass = 'text-cyan-400';

          if (isCongu) {
            badgeClass = 'bg-[#FF2A85] text-white border border-[#FF2A85]/60';
            badgeText = 'Kho Cổ Ngữ';
            borderHoverClass = 'hover:border-[#FF2A85] hover:shadow-[0_4px_16px_rgba(255,42,133,0.3)]';
            btnClass = 'bg-[#FF2A85] text-white';
            subtitleClass = 'text-pink-400';
          } else if (isSteamGrid) {
            badgeClass = 'bg-[#B026FF] text-white border border-[#B026FF]/70 shadow-[0_0_8px_rgba(176,38,255,0.5)]';
            badgeText = 'SteamGridDB';
            borderHoverClass = 'hover:border-[#B026FF] hover:shadow-[0_4px_16px_rgba(176,38,255,0.35)]';
            btnClass = 'bg-[#B026FF] text-white';
            subtitleClass = 'text-purple-400';
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
                 class="group cursor-pointer bg-[#070914] border border-[#1e2340] ${borderHoverClass} rounded-[2px] overflow-hidden flex flex-col transition-all duration-200 hover:-translate-y-1 relative">
              <div class="aspect-[2/3] w-full bg-[#05060f] relative overflow-hidden flex items-center justify-center">
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
                  <span class="pixel-btn ${btnClass} text-[11px] font-bold px-3 py-1.5 rounded-[2px] shadow-[2px_2px_0px_#000] flex items-center space-x-1">
                    <i data-lucide="check" class="w-3.5 h-3.5 stroke-[3]"></i>
                    <span>Chọn Mẫu Này</span>
                  </span>
                </div>
              </div>
              <div class="p-2.5 bg-[#0b0d1e] border-t border-[#1a1e38] flex-1 flex flex-col justify-between">
                <div class="text-xs font-bold text-white group-hover:text-[#00F0FF] truncate leading-tight" title="${safeTitle}">${item.title}</div>
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
            <i data-lucide="loader-2" class="w-6 h-6 text-[#00F0FF] animate-spin"></i>
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
    function quitApp() {
      if (typeof progressInterval !== 'undefined' && progressInterval) {
        showToast('Đang trong quá trình cài đặt hoặc gỡ bỏ bản mod! Vui lòng chờ hoàn tất để không làm hỏng tệp game.', 'error');
        return;
      }

      // 1. An toan bo giao dien ngay lap tuc (0ms Visual Feedback)
      document.body.style.display = 'none';

      // 2. Gui lenh tat toi PyWebView native window
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.quit_app === 'function') {
        try {
          window.pywebview.api.quit_app();
        } catch (e) {}
      }

      // 3. Gui lenh tat backend qua sendBeacon / fetch khong block
      const quitUrl = SESSION_AUTH_TOKEN ? `/api/app/quit?token=${encodeURIComponent(SESSION_AUTH_TOKEN)}` : '/api/app/quit';
      try {
        if (navigator.sendBeacon) {
          navigator.sendBeacon(quitUrl);
        } else {
          fetch(quitUrl, { method: 'POST', keepalive: true }).catch(() => {});
        }
      } catch (e) {}

      // 4. Dong cua so ngay lap tuc
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
                  <span class="font-pixel text-[10px] text-cyan-400">#${i + 1}</span>
                  <span class="font-bold text-white">${c.name}</span>
                  <span class="text-[10px] text-slate-400 font-mono">(${c.api})</span>
                </div>
                <div class="flex items-center space-x-2">
                  <span class="text-[10px] font-pixel px-1.5 py-0.2 rounded bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">${c.type}</span>
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

      const config = {
        enabled: toggle ? !!toggle.checked : false,
        mode: selectedMode,
        preset: presetSel ? presetSel.value : 'platformer',
        vibration: vibToggle ? !!vibToggle.checked : true,
        deadzone: dzRange ? (parseInt(dzRange.value) / 100.0) : 0.15
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

    async function startCustomGameDetect() {
      const exePath = document.getElementById('cgExeInput').value.trim();
      if (!exePath) {
        showToast('Vui lòng chọn hoặc dán đường dẫn file .exe của game!', 'warning');
        return;
      }

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
          body: JSON.stringify({ exe_path: exePath })
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
      const appid = document.getElementById('cgAppIdInput').value.trim();
      const coverUrl = document.getElementById('cgPosterUrlInput').value.trim();

      if (!title) {
        showToast('Tên tựa game không được để trống!', 'warning');
        return;
      }

      currentDetectedCustomGame.title = title;
      currentDetectedCustomGame.vietnamese_title = vnTitle || `${title} (Tự Thêm)`;
      currentDetectedCustomGame.developer = dev || 'Chưa rõ';
      currentDetectedCustomGame.engine = engine || 'PC Game';
      currentDetectedCustomGame.steam_appid = appid || '';
      currentDetectedCustomGame.cover_url = coverUrl || '';

      const btn = document.getElementById('btnSaveCustomGameToLib');
      btn.disabled = true;
      btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i><span>Đang lưu...</span>`;
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
