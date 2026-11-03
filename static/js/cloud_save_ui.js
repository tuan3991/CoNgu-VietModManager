    // ========================================================
    // ĐÁM MÂY CỔ NGỮ (COMMUNITY CLOUD HUB - GOOGLE APPS SCRIPT)
    // ========================================================
    let isCommCloudLoggedIn = false;
    let commCloudInfo = null;
    let isCommPassVisible = false;

    function switchCloudSubTab(tab) {
      const btnComm = document.getElementById('subtabBtn-commCloud');
      const btnOAuth = document.getElementById('subtabBtn-gdriveOAuth');
      const contentComm = document.getElementById('subtabContent-commCloud');
      const contentOAuth = document.getElementById('subtabContent-gdriveOAuth');

      if (tab === 'community') {
        if (btnComm) btnComm.className = 'py-2.5 px-3 border-b-2 border-cyan-400 text-cyan-300 font-bold flex items-center space-x-1.5 transition cursor-pointer';
        if (btnOAuth) btnOAuth.className = 'py-2.5 px-3 border-b-2 border-transparent text-slate-400 hover:text-white flex items-center space-x-1.5 transition cursor-pointer';
        if (contentComm) contentComm.classList.remove('hidden');
        if (contentOAuth) contentOAuth.classList.add('hidden');
      } else {
        if (btnOAuth) btnOAuth.className = 'py-2.5 px-3 border-b-2 border-cyan-400 text-cyan-300 font-bold flex items-center space-x-1.5 transition cursor-pointer';
        if (btnComm) btnComm.className = 'py-2.5 px-3 border-b-2 border-transparent text-slate-400 hover:text-white flex items-center space-x-1.5 transition cursor-pointer';
        if (contentOAuth) contentOAuth.classList.remove('hidden');
        if (contentComm) contentComm.classList.add('hidden');
      }
      if (window.lucide) lucide.createIcons();
    }

    function switchCommAuthMode(mode) {
      const btnReg = document.getElementById('commModeBtn-register');
      const btnLog = document.getElementById('commModeBtn-login');
      const formReg = document.getElementById('commRegisterForm');
      const formLog = document.getElementById('commLoginForm');

      if (mode === 'register') {
        if (btnReg) btnReg.className = 'flex-1 py-1.5 font-bold rounded text-center transition bg-[#00F0FF] text-[#061418] shadow cursor-pointer';
        if (btnLog) btnLog.className = 'flex-1 py-1.5 font-bold rounded text-center transition text-slate-400 hover:text-white bg-transparent cursor-pointer';
        if (formReg) formReg.classList.remove('hidden');
        if (formLog) formLog.classList.add('hidden');
      } else {
        if (btnLog) btnLog.className = 'flex-1 py-1.5 font-bold rounded text-center transition bg-cyan-600 text-white shadow cursor-pointer';
        if (btnReg) btnReg.className = 'flex-1 py-1.5 font-bold rounded text-center transition text-slate-400 hover:text-white bg-transparent cursor-pointer';
        if (formLog) formLog.classList.remove('hidden');
        if (formReg) formReg.classList.add('hidden');
      }
      if (window.lucide) lucide.createIcons();
    }

    function generateRandomCloudId() {
      const prefixes = ['congu', 'gamer', 'shadow', 'dragon', 'pixel', 'arcane', 'blade', 'cyber', 'phoenix', 'ninja'];
      const suffixes = ['vn', 'hero', 'master', 'slayer', 'warrior', 'knight', 'runner', 'legend', 'pro'];
      const randP = prefixes[Math.floor(Math.random() * prefixes.length)];
      const randS = suffixes[Math.floor(Math.random() * suffixes.length)];
      const randNum = Math.floor(100 + Math.random() * 900);
      const generated = `${randP}_${randS}_${randNum}`;

      const input = document.getElementById('inputCommRegId');
      if (input) {
        input.value = generated;
        input.focus();
        showToast(`Đã sinh Mã ID ngẫu nhiên: ${generated}`, 'info');
      }
    }

    function toggleCommPasswordVisibility() {
      isCommPassVisible = !isCommPassVisible;
      const passDisplay = document.getElementById('commCloudPassDisplay');
      const toggleLabel = document.getElementById('commPassToggleLabel');
      if (passDisplay) {
        if (isCommPassVisible && commCloudInfo && commCloudInfo.password_raw) {
          passDisplay.textContent = commCloudInfo.password_raw;
          if (toggleLabel) toggleLabel.textContent = 'Ẩn';
        } else {
          passDisplay.textContent = '••••••••';
          if (toggleLabel) toggleLabel.textContent = 'Hiện';
        }
      }
    }

    function copyCommunityCloudId() {
      const id = commCloudInfo ? commCloudInfo.cloud_id : '';
      if (id) {
        navigator.clipboard.writeText(id).then(() => {
          showToast(`Đã sao chép Mã Cloud ID: ${id}`, 'success');
        }).catch(() => {
          showToast(`Mã Cloud ID: ${id}`, 'info');
        });
      }
    }

    function toggleCommServerSettings() {
      const drawer = document.getElementById('commServerDrawer');
      const arrow = document.getElementById('commServerArrow');
      if (drawer) {
        drawer.classList.toggle('hidden');
        if (arrow) arrow.classList.toggle('rotate-180');
        if (window.lucide) lucide.createIcons();
      }
    }

    async function checkCommunityCloudStatus() {
      try {
        const resp = await fetch('/api/community_cloud/status');
        if (!resp.ok) return;
        commCloudInfo = await resp.json();
        isCommCloudLoggedIn = Boolean(commCloudInfo && commCloudInfo.is_logged_in);

        // Cập nhật nút Đám Mây trên thanh tiêu đề chính
        const topBtn = document.getElementById('btnCommunityCloud');
        const topText = document.getElementById('communityCloudTopText');
        const topBadge = document.getElementById('communityCloudBadge');

        if (topBtn) {
          if (isCommCloudLoggedIn) {
            topBtn.className = 'pixel-btn px-3 py-1.5 text-xs flex items-center space-x-1.5 rounded-[4px] border border-emerald-500/70 bg-[#061e16] text-emerald-300 hover:bg-emerald-900 transition shadow-[0_0_12px_rgba(0,240,255,0.3)]';
            if (topText) topText.textContent = commCloudInfo.cloud_id || 'Đám Mây';
            if (topBadge) {
              topBadge.classList.remove('hidden');
              topBadge.textContent = 'ON';
              topBadge.className = 'text-[9px] px-1.5 py-0.2 rounded bg-emerald-500/25 text-emerald-300 font-pixel border border-emerald-500/50';
            }
          } else {
            topBtn.className = 'pixel-btn px-3 py-1.5 text-xs flex items-center space-x-1.5 rounded-[4px] border border-emerald-500/40 bg-[#081a14]/90 text-emerald-300/80 hover:bg-emerald-950 hover:border-emerald-400 transition shadow-[0_2px_8px_rgba(0,0,0,0.35)]';
            if (topText) topText.textContent = 'Đám Mây';
            if (topBadge) {
              topBadge.classList.remove('hidden');
              topBadge.textContent = 'OFF';
              topBadge.className = 'text-[9px] px-1.5 py-0.2 rounded bg-slate-800 text-slate-400 font-pixel border border-slate-700';
            }
          }
        }

        // Cập nhật các thẻ bên trong Modal Đám Mây Cổ Ngữ
        const loggedInCard = document.getElementById('commCloudLoggedInCard');
        const loggedOutCard = document.getElementById('commCloudLoggedOutCard');
        const idDisplay = document.getElementById('commCloudIdDisplay');
        const passDisplay = document.getElementById('commCloudPassDisplay');
        const sizeDisplay = document.getElementById('commCloudSizeDisplay');
        const mtimeDisplay = document.getElementById('commCloudMtimeDisplay');

        if (loggedInCard && loggedOutCard) {
          if (isCommCloudLoggedIn) {
            loggedInCard.classList.remove('hidden');
            loggedOutCard.classList.add('hidden');

            if (idDisplay) idDisplay.textContent = commCloudInfo.cloud_id || '---';
            if (passDisplay) {
              passDisplay.textContent = isCommPassVisible && commCloudInfo.password_raw ? commCloudInfo.password_raw : '••••••••';
            }

            const sz = commCloudInfo.last_size || 0;
            if (sizeDisplay) {
              sizeDisplay.textContent = sz > 1048576 ? `${(sz / 1048576).toFixed(2)} MB` : sz > 1024 ? `${(sz / 1024).toFixed(1)} KB` : `${sz} B`;
            }

            if (mtimeDisplay) {
              if (commCloudInfo.last_sync) {
                try {
                  const d = new Date(commCloudInfo.last_sync);
                  mtimeDisplay.textContent = d.toLocaleString('vi-VN');
                } catch (e) {
                  mtimeDisplay.textContent = commCloudInfo.last_sync;
                }
              } else {
                mtimeDisplay.textContent = 'Chưa tải lên';
              }
            }
          } else {
            loggedInCard.classList.add('hidden');
            loggedOutCard.classList.remove('hidden');
          }
        }

        // Cập nhật ô input server URL cho Admin
        const inputUrl = document.getElementById('inputCommServerUrl');
        if (inputUrl && commCloudInfo && commCloudInfo.server_url) {
          inputUrl.value = commCloudInfo.server_url;
        }

        // Cập nhật Tab Cloud Save trong modal chi tiết game nếu đang mở
        const tabBadge = document.getElementById('cloudTabStatusBadge');
        const tabSubText = document.getElementById('cloudTabSubText');
        if (isCommCloudLoggedIn) {
          if (tabBadge) {
            tabBadge.textContent = `🟢 ID: ${commCloudInfo.cloud_id}`;
            tabBadge.className = 'text-[10px] font-pixel font-bold px-2 py-0.5 rounded-[2px] bg-emerald-500/20 text-emerald-300 border border-emerald-500/40';
          }
          if (tabSubText) {
            tabSubText.textContent = 'Đồng bộ qua Đám Mây Cổ Ngữ (Google Drive chung an toàn, 0% cảnh báo)';
          }
        }

        if (window.lucide) lucide.createIcons();
        try {
          window.dispatchEvent(new CustomEvent('congu:community-cloud-changed', { detail: commCloudInfo || {} }));
        } catch (e) { /* ignore */ }
      } catch (err) {
        console.warn('[Check Community Cloud Status Error]', err);
      }
    }

    async function registerCommunityCloud() {
      const regId = (document.getElementById('inputCommRegId')?.value || '').trim();
      const regPass = (document.getElementById('inputCommRegPass')?.value || '').trim();
      const serverUrl = (document.getElementById('inputCommServerUrl')?.value || '').trim();

      if (!regId) {
        showToast('Vui lòng nhập Mã Cloud ID bạn muốn tạo!', 'warning');
        document.getElementById('inputCommRegId')?.focus();
        return;
      }
      if (regId.length < 3) {
        showToast('Mã Cloud ID phải có ít nhất 3 ký tự!', 'warning');
        return;
      }
      if (!/^[a-zA-Z0-9_-]+$/.test(regId)) {
        showToast('Mã Cloud ID chỉ được chứa chữ cái, số, gạch ngang (-) hoặc gạch dưới (_)!', 'warning');
        return;
      }
      if (!regPass || regPass.length < 4) {
        showToast('Mật khẩu bảo vệ phải có ít nhất 4 ký tự!', 'warning');
        document.getElementById('inputCommRegPass')?.focus();
        return;
      }

      const btn = document.getElementById('btnCommRegisterAction');
      const originalHtml = btn ? btn.innerHTML : '';
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `
          <i data-lucide="loader-2" class="w-4 h-4 animate-spin text-white"></i>
          <span>ĐANG TẠO MÃ CLOUD ID TRÊN MÁY CHỦ...</span>
        `;
        if (window.lucide) lucide.createIcons();
      }

      try {
        const resp = await fetch('/api/community_cloud/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cloud_id: regId, password: regPass, server_url: serverUrl })
        });
        const data = await resp.json();

        if (data.success) {
          showToast(`Tạo thành công Mã Cloud ID '${regId}'! Đang đẩy save lên Mây...`, 'success');
          await checkCommunityCloudStatus();
          await uploadCommunitySave(true);
        } else {
          showToast(data.error || 'Lỗi khi tạo Mã Cloud ID!', 'error');
        }
      } catch (err) {
        showToast(`Không thể kết nối máy chủ: ${err}`, 'error');
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = originalHtml;
          if (window.lucide) lucide.createIcons();
        }
      }
    }

    async function loginCommunityCloud() {
      const logId = (document.getElementById('inputCommLogId')?.value || '').trim();
      const logPass = (document.getElementById('inputCommLogPass')?.value || '').trim();
      const serverUrl = (document.getElementById('inputCommServerUrl')?.value || '').trim();

      if (!logId) {
        showToast('Vui lòng nhập Mã Cloud ID của bạn!', 'warning');
        document.getElementById('inputCommLogId')?.focus();
        return;
      }
      if (!logPass) {
        showToast('Vui lòng nhập Mật khẩu bảo vệ!', 'warning');
        document.getElementById('inputCommLogPass')?.focus();
        return;
      }

      const btn = document.getElementById('btnCommLoginAction');
      const originalHtml = btn ? btn.innerHTML : '';
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `
          <i data-lucide="loader-2" class="w-4 h-4 animate-spin text-white"></i>
          <span>ĐANG XÁC THỰC VỚI MÁY CHỦ...</span>
        `;
        if (window.lucide) lucide.createIcons();
      }

      try {
        const resp = await fetch('/api/community_cloud/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cloud_id: logId, password: logPass, server_url: serverUrl })
        });
        const data = await resp.json();

        if (data.success) {
          showToast(`Đăng nhập thành công Mã ID '${logId}'! Đang kéo save về máy...`, 'success');
          await checkCommunityCloudStatus();
          await downloadCommunitySave(true);
        } else {
          showToast(data.error || 'Đăng nhập thất bại!', 'error');
        }
      } catch (err) {
        showToast(`Lỗi kết nối máy chủ: ${err}`, 'error');
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = originalHtml;
          if (window.lucide) lucide.createIcons();
        }
      }
    }

    async function logoutCommunityCloud() {
      if (!confirm('Bạn có chắc chắn muốn đăng xuất tài khoản Đám Mây khỏi máy này? (Save trên máy vẫn được giữ nguyên)')) {
        return;
      }
      try {
        const resp = await fetch('/api/community_cloud/logout', { method: 'POST' });
        const data = await resp.json();
        showToast('Đã đăng xuất tài khoản Đám Mây Cổ Ngữ!', 'info');
        await checkCommunityCloudStatus();
      } catch (err) {
        showToast(`Lỗi khi đăng xuất: ${err}`, 'error');
      }
    }

    async function uploadCommunitySave(isSilent = false) {
      const btnHero = document.getElementById('btnCommUploadHero');
      const origHero = btnHero ? btnHero.innerHTML : '';
      if (btnHero) {
        btnHero.disabled = true;
        btnHero.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin text-white"></i><span>ĐANG TẢI LÊN...</span>`;
        if (window.lucide) lucide.createIcons();
      }

      if (!isSilent) showToast('Đang gom save và đẩy lên Đám Mây Cổ Ngữ...', 'info');

      try {
        const resp = await fetch('/api/community_cloud/upload', { method: 'POST' });
        const data = await resp.json();

        if (data.success) {
          showToast('Đã lưu trữ toàn bộ Save Game lên Đám Mây thành công!', 'success');
          await checkCommunityCloudStatus();
          if (typeof refreshVaultModalData === 'function' && document.getElementById('vaultModal') && !document.getElementById('vaultModal').classList.contains('hidden')) {
            await refreshVaultModalData();
          }
        } else {
          showToast(data.error || 'Lỗi khi đẩy save lên mây!', 'error');
        }
      } catch (err) {
        showToast(`Lỗi đường truyền: ${err}`, 'error');
      } finally {
        if (btnHero) {
          btnHero.disabled = false;
          btnHero.innerHTML = origHero;
          if (window.lucide) lucide.createIcons();
        }
      }
    }

    async function downloadCommunitySave(isSilent = false) {
      const btnHero = document.getElementById('btnCommDownloadHero');
      const origHero = btnHero ? btnHero.innerHTML : '';
      if (btnHero) {
        btnHero.disabled = true;
        btnHero.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin text-white"></i><span>ĐANG KÉO SAVE VỀ...</span>`;
        if (window.lucide) lucide.createIcons();
      }

      if (!isSilent) showToast('Đang tải và khôi phục Save Game từ Đám Mây...', 'info');

      try {
        const resp = await fetch('/api/community_cloud/download', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ auto_unpack: true })
        });
        const data = await resp.json();

        if (data.success) {
          showToast('Đã tải và khôi phục tiến trình Save Game thành công!', 'success');
          await checkCommunityCloudStatus();
          if (typeof refreshVaultModalData === 'function' && document.getElementById('vaultModal') && !document.getElementById('vaultModal').classList.contains('hidden')) {
            await refreshVaultModalData();
          }
        } else {
          showToast(data.error || 'Lỗi khi kéo save về máy!', 'error');
        }
      } catch (err) {
        showToast(`Lỗi đường truyền: ${err}`, 'error');
      } finally {
        if (btnHero) {
          btnHero.disabled = false;
          btnHero.innerHTML = origHero;
          if (window.lucide) lucide.createIcons();
        }
      }
    }

    async function saveCommunityServerUrl() {
      const url = (document.getElementById('inputCommServerUrl')?.value || '').trim();
      try {
        const resp = await fetch('/api/community_cloud/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ server_url: url })
        });
        const data = await resp.json();
        if (data.success) {
          showToast('Đã lưu địa chỉ Máy Chủ Đám Mây thành công!', 'success');
          await checkCommunityCloudStatus();
        } else {
          showToast(data.error || 'Lỗi khi lưu cấu hình máy chủ!', 'error');
        }
      } catch (err) {
        showToast(`Lỗi: ${err}`, 'error');
      }
    }

    // Khi tạo/đăng nhập/đăng xuất Cloud ID, nếu Cài đặt đang mở thì nạp lại
    // để ô Cloud ID/Mật khẩu phản ánh đúng tài khoản vừa tạo.
    window.addEventListener('congu:community-cloud-changed', () => {
      const settingsModal = document.getElementById('settingsModal');
      if (settingsModal && !settingsModal.classList.contains('hidden') && typeof loadSettings === 'function') {
        loadSettings();
      }
    });

    // ========================================================
    // GOOGLE DRIVE CLOUD SAVE & ECOSYSTEM FUNCTIONS
    // ========================================================
    let isCloudConnected = false;
    let activeConflictData = null;

    async function checkGdriveStatus() {
      try {
        const resp = await fetch('/api/cloud/status');
        if (!resp.ok) return;
        const data = await resp.json();
        isCloudConnected = Boolean(data && data.connected);

        // Header button update
        const btnGdrive = document.getElementById('btnGdriveCloud');
        if (btnGdrive) {
          if (isCloudConnected) {
            btnGdrive.className = 'pixel-btn px-3 py-1.5 text-xs flex items-center space-x-1.5 bg-emerald-950/60 text-emerald-300 border border-emerald-500/60 shadow-[0_0_12px_rgba(0,240,255,0.3)] rounded-[2px] transition';
            btnGdrive.innerHTML = `
              <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
              <i data-lucide="cloud" class="w-3.5 h-3.5 text-emerald-400"></i>
              <span class="font-bold truncate max-w-[120px]">${escapeHtml(data.name || 'Cloud Drive')}</span>
            `;
          } else {
            btnGdrive.className = 'pixel-btn px-3 py-1.5 text-xs flex items-center space-x-1.5 bg-[#1C2536] text-slate-300 hover:text-white border border-[#2A3548] rounded-[2px] transition';
            btnGdrive.innerHTML = `
              <i data-lucide="cloud" class="w-3.5 h-3.5 text-slate-400"></i>
              <span>Google Drive</span>
            `;
          }
        }

        // Modal sections update
        const connectedSection = document.getElementById('cloudConnectedSection');
        const disconnectedSection = document.getElementById('cloudDisconnectedSection');
        const uName = document.getElementById('cloudUserName');
        const uEmail = document.getElementById('cloudUserEmail');
        const uAvatar = document.getElementById('cloudUserAvatar');

        if (connectedSection && disconnectedSection) {
          if (isCloudConnected) {
            connectedSection.classList.remove('hidden');
            disconnectedSection.classList.add('hidden');
            if (uName) uName.textContent = data.name || 'Người dùng Google';
            if (uEmail) uEmail.textContent = data.email || '';
            if (uAvatar) {
              uAvatar.src = data.picture || '/static/app_icon.png';
            }
          } else {
            connectedSection.classList.add('hidden');
            disconnectedSection.classList.remove('hidden');
          }
        }

        // Populate OAuth config inputs if available
        try {
          const cfgResp = await fetch('/api/cloud/config');
          if (cfgResp.ok) {
            const cfgData = await cfgResp.json();
            const idInput = document.getElementById('cfgGoogleClientId');
            const secInput = document.getElementById('cfgGoogleClientSecret');
            if (idInput && cfgData.client_id) idInput.value = cfgData.client_id;
            if (secInput && cfgData.masked_secret) secInput.placeholder = cfgData.masked_secret;

            // Nếu chưa có Client ID và chưa kết nối, tự động mở sẵn khung hướng dẫn
            const drawer = document.getElementById('oauthSettingsDrawer');
            const arrow = document.getElementById('oauthSettingsArrow');
            const drawerTitle = document.getElementById('oauthDrawerTitle');
            if (!cfgData.client_id && !isCloudConnected) {
              if (drawer) drawer.classList.remove('hidden');
              if (arrow) arrow.classList.add('rotate-180');
              if (drawerTitle) drawerTitle.innerHTML = `<span class="text-amber-300">Cần Cấu Hình Client ID (Chưa nhập)</span>`;
            } else if (cfgData.client_id && drawerTitle) {
              drawerTitle.innerHTML = `<span class="text-emerald-400">Đã Lưu Client ID: ${escapeHtml(cfgData.client_id.slice(0, 15))}...</span>`;
            }
          }
        } catch (e) {}

        if (window.lucide) lucide.createIcons();
      } catch (err) {
        console.warn('[Check GDrive Status Error]', err);
      }
    }

    function openCloudModal() {
      const modal = document.getElementById('cloudConnectModal');
      if (modal) {
        modal.classList.remove('hidden');
        checkCommunityCloudStatus();
        checkGdriveStatus();
        if (window.lucide) lucide.createIcons();
      }
    }

    function closeCloudModal() {
      const modal = document.getElementById('cloudConnectModal');
      if (modal) modal.classList.add('hidden');
    }

    function toggleOAuthSettings() {
      const drawer = document.getElementById('oauthSettingsDrawer');
      const arrow = document.getElementById('oauthSettingsArrow');
      if (drawer) {
        drawer.classList.toggle('hidden');
        if (arrow) arrow.classList.toggle('rotate-180');
        if (window.lucide) lucide.createIcons();
      }
    }

    async function saveOAuthSettings() {
      const clientId = document.getElementById('cfgGoogleClientId')?.value.trim();
      const clientSecret = document.getElementById('cfgGoogleClientSecret')?.value.trim();
      try {
        const resp = await fetch('/api/cloud/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ client_id: clientId, client_secret: clientSecret })
        });
        const data = await resp.json();
        if (data.success) {
          showToast('Đã lưu cấu hình Google OAuth!', 'success');
          checkGdriveStatus();
        } else {
          showToast(data.error || 'Lỗi khi lưu cấu hình OAuth!', 'error');
        }
      } catch (e) {
        showToast('Không thể kết nối đến máy chủ để lưu cấu hình!', 'error');
      }
    }

    async function loginGoogleDrive() {
      const clientId = document.getElementById('cfgGoogleClientId')?.value.trim();
      const clientSecret = document.getElementById('cfgGoogleClientSecret')?.value.trim();

      const btn = document.getElementById('btnStartGoogleLogin');
      const originalHtml = btn ? btn.innerHTML : '';
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `
          <i data-lucide="loader-2" class="w-4 h-4 animate-spin text-white"></i>
          <span>ĐANG CHỜ BẠN ĐĂNG NHẬP TRÊN TRÌNH DUYỆT...</span>
        `;
        if (window.lucide) lucide.createIcons();
      }

      showToast('Đang kết nối Google Drive...', 'info');

      try {
        const resp = await fetch('/api/cloud/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ client_id: clientId, client_secret: clientSecret })
        });
        const data = await resp.json();

        if (data.success) {
          showToast('Đã kết nối thành công Google Drive cá nhân!', 'success');
          await checkGdriveStatus();
          if (activeModalGameId) {
            loadCloudSaveTab(activeModalGameId);
          }
        } else {
          if (data.error && data.error.includes('Client ID')) {
            const drawer = document.getElementById('oauthSettingsDrawer');
            const arrow = document.getElementById('oauthSettingsArrow');
            if (drawer && drawer.classList.contains('hidden')) {
              drawer.classList.remove('hidden');
              if (arrow) arrow.classList.add('rotate-180');
            }
            document.getElementById('cfgGoogleClientId')?.focus();
          }
          showToast(data.error || 'Đăng nhập Google Drive thất bại!', 'error');
        }
      } catch (err) {
        showToast('Lỗi khi gửi yêu cầu đăng nhập: ' + (err.message || err), 'error');
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = originalHtml;
          if (window.lucide) lucide.createIcons();
        }
      }
    }

    async function logoutGoogleDrive() {
      const confirmed = confirm('Bạn có chắc chắn muốn ngắt kết nối tài khoản Google Drive khỏi CỔ NGỮ?');
      if (!confirmed) return;

      try {
        const resp = await fetch('/api/cloud/logout', { method: 'POST' });
        const data = await resp.json();
        if (data.success) {
          showToast('Đã ngắt kết nối Google Drive!', 'info');
          await checkGdriveStatus();
          if (activeModalGameId) {
            loadCloudSaveTab(activeModalGameId);
          }
        }
      } catch (e) {
        showToast('Lỗi khi ngắt kết nối Google Drive!', 'error');
      }
    }

    async function loadCloudSaveTab(gameId) {
      if (!gameId) return;
      const game = gamesList.find(g => g.id === gameId);
      if (!game) return;

      const tabBadge = document.getElementById('modalCloudBadge');
      const statusBadge = document.getElementById('cloudTabStatusBadge');
      const subText = document.getElementById('cloudTabSubText');

      const pathDisplay = document.getElementById('localSavePathDisplay');
      const localSizeDisplay = document.getElementById('localSaveSizeDisplay');
      const localMtimeDisplay = document.getElementById('localSaveMtimeDisplay');

      const cloudFileDisplay = document.getElementById('cloudSaveFilenameDisplay');
      const cloudSizeDisplay = document.getElementById('cloudSaveSizeDisplay');
      const cloudMtimeDisplay = document.getElementById('cloudSaveMtimeDisplay');

      const btnUpload = document.getElementById('btnUploadCloudSave');
      const btnDownload = document.getElementById('btnDownloadCloudSave');

      if (statusBadge) {
        statusBadge.className = 'text-[10px] font-pixel font-bold px-2 py-0.5 rounded-[2px] bg-slate-800 text-slate-400 border border-slate-700 animate-pulse';
        statusBadge.textContent = 'Đang kiểm tra...';
      }

      try {
        const resp = await fetch('/api/cloud/save/status', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: gameId })
        });
        const data = await resp.json();

        // Cập nhật thẻ Local Save
        if (data.local && data.local.exists) {
          if (pathDisplay) {
            pathDisplay.textContent = data.save_folder || data.local.path || '...';
            pathDisplay.title = data.save_folder || data.local.path || '';
          }
          if (localSizeDisplay) localSizeDisplay.textContent = `${data.local.formatted_size || '0 KB'} (${data.local.file_count || 0} tệp)`;
          if (localMtimeDisplay) localMtimeDisplay.textContent = data.local.formatted_mtime || 'Mới cập nhật';
          if (btnUpload) btnUpload.disabled = false;
        } else {
          if (pathDisplay) {
            pathDisplay.textContent = data.save_folder || 'Chưa tìm thấy thư mục save';
            pathDisplay.title = data.save_folder || '';
          }
          if (localSizeDisplay) localSizeDisplay.textContent = 'Chưa có file save';
          if (localMtimeDisplay) localMtimeDisplay.textContent = 'Chưa có save';
          if (btnUpload) btnUpload.disabled = true;
        }

        // Cập nhật thẻ Cloud Save
        if (data.cloud && data.cloud.exists) {
          if (cloudFileDisplay) cloudFileDisplay.textContent = data.cloud.name || `${gameId}_save.zip`;
          if (cloudSizeDisplay) cloudSizeDisplay.textContent = data.cloud.formatted_size || '0 KB';
          if (cloudMtimeDisplay) cloudMtimeDisplay.textContent = data.cloud.formatted_mtime || 'Đã đồng bộ';
          if (btnDownload) btnDownload.disabled = false;
        } else {
          if (cloudFileDisplay) cloudFileDisplay.textContent = `${gameId}_save.zip (Chưa có trên Drive)`;
          if (cloudSizeDisplay) cloudSizeDisplay.textContent = '0 KB';
          if (cloudMtimeDisplay) cloudMtimeDisplay.textContent = 'Chưa tải lên Drive';
          if (btnDownload) btnDownload.disabled = true;
        }

        // Cập nhật Huy hiệu trạng thái đồng bộ
        const state = data.status || 'NO_SAVE';
        if (statusBadge) {
          if (!data.connected) {
            statusBadge.className = 'text-[10px] font-pixel font-bold px-2 py-0.5 rounded-[2px] bg-slate-800 text-slate-400 border border-slate-700';
            statusBadge.textContent = 'CHƯA LIÊN KẾT DRIVE';
            if (subText) subText.textContent = 'Bấm "Tài Khoản Drive" phía trên để kết nối và tự động sao lưu.';
          } else if (state === 'IN_SYNC') {
            statusBadge.className = 'text-[10px] font-pixel font-bold px-2 py-0.5 rounded-[2px] bg-emerald-500/20 text-emerald-300 border border-emerald-500/50';
            statusBadge.textContent = 'ĐÃ ĐỒNG BỘ 100%';
            if (subText) subText.textContent = 'Bản save trên máy và Google Drive hoàn toàn trùng khớp.';
          } else if (state === 'UPLOAD_NEEDED') {
            statusBadge.className = 'text-[10px] font-pixel font-bold px-2 py-0.5 rounded-[2px] bg-amber-500/20 text-amber-300 border border-amber-500/50';
            statusBadge.textContent = 'CÓ SAVE MỚI TRÊN MÁY';
            if (subText) subText.textContent = 'Bản save cục bộ mới hơn bản trên Drive. Bấm Tải Lên để sao lưu.';
          } else if (state === 'DOWNLOAD_NEEDED') {
            statusBadge.className = 'text-[10px] font-pixel font-bold px-2 py-0.5 rounded-[2px] bg-cyan-500/20 text-cyan-300 border border-cyan-500/50';
            statusBadge.textContent = 'CÓ SAVE TRÊN CLOUD';
            if (subText) subText.textContent = 'Phát hiện save từ máy khác trên Drive. Bấm Tải Về để tiếp tục chơi.';
          } else if (state === 'CONFLICT') {
            statusBadge.className = 'text-[10px] font-pixel font-bold px-2 py-0.5 rounded-[2px] bg-rose-500/20 text-rose-300 border border-rose-500/60 animate-pulse';
            statusBadge.textContent = 'XUNG ĐỘT FILE SAVE';
            if (subText) subText.textContent = 'Cả máy và Cloud đều có file save mới khác nhau.';
          } else if (state === 'NOT_CONFIGURED') {
            statusBadge.className = 'text-[10px] font-pixel font-bold px-2 py-0.5 rounded-[2px] bg-slate-800 text-slate-400 border border-slate-700';
            statusBadge.textContent = 'CHƯA CẤU HÌNH ĐƯỜNG DẪN';
            if (subText) subText.textContent = 'Tựa game này chưa định nghĩa vị trí lưu file save.';
          } else {
            statusBadge.className = 'text-[10px] font-pixel font-bold px-2 py-0.5 rounded-[2px] bg-slate-800 text-slate-400 border border-slate-700';
            statusBadge.textContent = 'CHƯA CÓ DỮ LIỆU SAVE';
            if (subText) subText.textContent = 'Chưa phát hiện file save nào trên máy lẫn trên Google Drive.';
          }
        }

        // Cập nhật tab badge
        if (tabBadge) {
          if (state === 'IN_SYNC') {
            tabBadge.className = 'ml-1 text-[9px] font-pixel px-1.5 py-0.2 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/40';
            tabBadge.textContent = 'SYNCED';
            tabBadge.classList.remove('hidden');
          } else if (state === 'UPLOAD_NEEDED' || state === 'DOWNLOAD_NEEDED') {
            tabBadge.className = 'ml-1 text-[9px] font-pixel px-1.5 py-0.2 rounded bg-amber-500/20 text-amber-300 border border-amber-500/40';
            tabBadge.textContent = 'SYNC';
            tabBadge.classList.remove('hidden');
          } else if (state === 'CONFLICT') {
            tabBadge.className = 'ml-1 text-[9px] font-pixel px-1.5 py-0.2 rounded bg-rose-500/20 text-rose-300 border border-rose-500/40 animate-pulse';
            tabBadge.textContent = 'CONFLICT';
            tabBadge.classList.remove('hidden');
          } else {
            tabBadge.classList.add('hidden');
          }
        }

        // Lấy danh sách backup cục bộ
        loadLocalBackups(gameId);

        if (window.lucide) lucide.createIcons();
      } catch (e) {
        console.warn('[Load Cloud Save Tab Error]', e);
      }
    }

    async function loadLocalBackups(gameId) {
      const container = document.getElementById('localBackupsList');
      if (!container) return;
      try {
        const resp = await fetch(`/api/cloud/save/backups/${encodeURIComponent(gameId)}`);
        if (!resp.ok) return;
        const data = await resp.json();
        const backups = data.backups || [];

        if (backups.length === 0) {
          container.innerHTML = `
            <div class="text-xs text-slate-400 py-3 text-center font-sans">
              Chưa có bản sao lưu cục bộ nào. Khi tải save từ Cloud về ghi đè, hệ thống sẽ tự động lưu 1 bản dự phòng tại đây.
            </div>
          `;
          return;
        }

        container.innerHTML = backups.map(b => `
          <div class="p-2.5 rounded-[4px] border border-white/5 bg-[#0a0d1e] flex items-center justify-between gap-3 text-xs">
            <div class="flex items-center space-x-2.5 min-w-0">
              <i data-lucide="archive" class="w-4 h-4 text-amber-400 shrink-0"></i>
              <div class="min-w-0">
                <div class="font-mono text-slate-200 font-bold truncate">${escapeHtml(b.filename)}</div>
                <div class="text-[11px] text-slate-400 font-sans mt-0.5">
                  ${escapeHtml(b.formatted_time || '')} • <span class="font-mono text-slate-300">${escapeHtml(b.formatted_size || '')}</span>
                </div>
              </div>
            </div>
            <button onclick="restoreBackup('${escapeHtml(gameId)}', '${escapeHtml(b.filename)}')" class="pixel-btn px-2.5 py-1 text-[11px] bg-amber-500/15 hover:bg-amber-500/30 text-amber-300 border border-amber-500/40 rounded flex items-center space-x-1 shrink-0 font-bold transition">
              <i data-lucide="rotate-ccw" class="w-3 h-3"></i>
              <span>Khôi Phục</span>
            </button>
          </div>
        `).join('');

        if (window.lucide) lucide.createIcons();
      } catch (err) {
        console.warn('[Load Local Backups Error]', err);
      }
    }

    async function restoreBackup(gameId, backupFilename) {
      const confirmed = confirm(`Bạn có chắc chắn muốn khôi phục bản sao lưu:\n"${backupFilename}"\n\nDữ liệu save hiện tại trên máy sẽ được thay thế bằng bản này.`);
      if (!confirmed) return;

      try {
        const resp = await fetch('/api/cloud/save/restore_backup', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: gameId, backup_filename: backupFilename })
        });
        const data = await resp.json();
        if (data.success) {
          showToast(data.message || 'Đã khôi phục bản sao lưu thành công!', 'success');
          loadCloudSaveTab(gameId);
        } else {
          showToast(data.error || 'Khôi phục bản sao lưu thất bại!', 'error');
        }
      } catch (err) {
        showToast('Lỗi khi gửi yêu cầu khôi phục sao lưu!', 'error');
      }
    }

    async function syncCurrentGameSave(action) {
      if (!activeModalGameId) return;

      if (isCommCloudLoggedIn) {
        if (action === 'upload') {
          await uploadCommunitySave();
        } else {
          await downloadCommunitySave();
        }
        await loadCloudSaveTab(activeModalGameId);
        return;
      }

      if (!isCloudConnected) {
        showToast('Bạn chưa kết nối Đám Mây Cổ Ngữ! Vui lòng tạo ID hoặc đăng nhập.', 'info');
        openCloudModal();
        return;
      }

      const btnUp = document.getElementById('btnUploadCloudSave');
      const btnDown = document.getElementById('btnDownloadCloudSave');

      const originalUpHtml = btnUp ? btnUp.innerHTML : '';
      const originalDownHtml = btnDown ? btnDown.innerHTML : '';

      if (action === 'upload' && btnUp) {
        btnUp.disabled = true;
        btnUp.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i><span>ĐANG TẢI LÊN...</span>`;
      } else if (action === 'download' && btnDown) {
        btnDown.disabled = true;
        btnDown.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i><span>ĐANG TẢI VỀ...</span>`;
      }
      if (window.lucide) lucide.createIcons();

      try {
        const resp = await fetch('/api/cloud/save/sync', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: activeModalGameId, action: action })
        });
        const data = await resp.json();

        if (data.action === 'conflict' || data.status === 'conflict') {
          openCloudConflictModal(activeModalGameId, data.conflict_data);
          return;
        }

        if (data.success) {
          showToast(data.message || 'Đồng bộ save game thành công!', 'success');
          loadCloudSaveTab(activeModalGameId);
        } else {
          showToast(data.error || data.message || 'Đồng bộ save thất bại!', 'error');
        }
      } catch (err) {
        showToast('Lỗi khi gửi yêu cầu đồng bộ save!', 'error');
      } finally {
        if (btnUp) {
          btnUp.disabled = false;
          btnUp.innerHTML = originalUpHtml;
        }
        if (btnDown) {
          btnDown.disabled = false;
          btnDown.innerHTML = originalDownHtml;
        }
        if (window.lucide) lucide.createIcons();
      }
    }

    function openCloudConflictModal(gameId, conflictData) {
      activeConflictData = { gameId, conflictData };
      const modal = document.getElementById('cloudConflictModal');
      if (!modal) return;

      const loc = conflictData?.local || {};
      const cld = conflictData?.cloud || {};

      const locTime = document.getElementById('conflictLocalTime');
      const locSize = document.getElementById('conflictLocalSize');
      const locFiles = document.getElementById('conflictLocalFiles');

      const cldTime = document.getElementById('conflictCloudTime');
      const cldSize = document.getElementById('conflictCloudSize');
      const cldName = document.getElementById('conflictCloudName');

      if (locTime) locTime.textContent = loc.formatted_mtime || 'Không rõ';
      if (locSize) locSize.textContent = loc.formatted_size || '0 KB';
      if (locFiles) locFiles.textContent = `${loc.file_count || 0} tệp`;

      if (cldTime) cldTime.textContent = cld.formatted_mtime || 'Không rõ';
      if (cldSize) cldSize.textContent = cld.formatted_size || '0 KB';
      if (cldName) cldName.textContent = cld.name || `${gameId}_save.zip`;

      modal.classList.remove('hidden');
      if (window.lucide) lucide.createIcons();
    }

    function closeCloudConflictModal() {
      const modal = document.getElementById('cloudConflictModal');
      if (modal) modal.classList.add('hidden');
      activeConflictData = null;
    }

    async function resolveConflict(choice) {
      if (!activeConflictData || !activeConflictData.gameId) return;
      const gameId = activeConflictData.gameId;
      closeCloudConflictModal();
      await syncCurrentGameSave(choice);
    }

    async function openLocalSaveFolder(gameId) {
      if (!gameId) return;
      try {
        const resp = await fetch('/api/open_save_folder', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: gameId })
        });
        const data = await resp.json();
        if (!data.success) {
          showToast(data.message || 'Không thể mở thư mục save!', 'error');
        }
      } catch (e) {
        showToast('Lỗi khi mở thư mục save!', 'error');
      }
    }

    // =========================================================================
    // HỒ SƠ DI ĐỘNG HỢP NHẤT (.congu_save / SINGLE-FILE PORTABLE VAULT) JS LOGIC
    // =========================================================================
    let currentVaultData = null;

    async function openVaultModal() {
      const modal = document.getElementById('vaultModal');
      if (!modal) return;
      modal.classList.remove('hidden');
      await refreshVaultModalData();
      if (window.lucide) lucide.createIcons();
    }

    function closeVaultModal() {
      const modal = document.getElementById('vaultModal');
      if (modal) modal.classList.add('hidden');
    }

    async function refreshVaultModalData() {
      try {
        const resp = await fetch('/api/vault/status');
        const data = await resp.json();
        currentVaultData = data;

        // Cập nhật thông tin tổng quan
        const nameDisp = document.getElementById('vaultNameDisplay');
        const sizeDisp = document.getElementById('vaultSizeDisplay');
        const updatedDisp = document.getElementById('vaultUpdatedDisplay');
        const playerDisp = document.getElementById('vaultPlayerName');
        const totalGamesDisp = document.getElementById('vaultTotalGames');
        const totalPlaytimeDisp = document.getElementById('vaultTotalPlaytime');
        const totalAchsDisp = document.getElementById('vaultTotalAchs');
        const pathInput = document.getElementById('vaultPathInput');
        const badgeCount = document.getElementById('vaultBadgeCount');

        if (nameDisp && nameDisp.firstElementChild) nameDisp.firstElementChild.textContent = data.vault_filename || 'PlayerProfile.congu_save';
        if (sizeDisp) sizeDisp.textContent = `(${data.formatted_size || '0 KB'})`;
        if (updatedDisp) updatedDisp.textContent = data.formatted_updated_at || 'Chưa có';
        if (playerDisp) playerDisp.textContent = data.player_name || 'Game Thủ';
        if (totalGamesDisp) totalGamesDisp.textContent = `${data.total_games || 0} game`;
        if (totalPlaytimeDisp) totalPlaytimeDisp.textContent = data.total_playtime_str || '0 phút';
        if (totalAchsDisp) totalAchsDisp.textContent = `${data.total_achievements_count || 0} cúp`;
        if (pathInput) pathInput.value = data.vault_path || '';

        if (badgeCount) {
          if (data.total_games > 0) {
            badgeCount.textContent = data.total_games;
            badgeCount.classList.remove('hidden');
          } else {
            badgeCount.classList.add('hidden');
          }
        }

        // Cập nhật Google Drive Cloud Vault Card
        const driveBadge = document.getElementById('vaultDriveConnBadge');
        const connectedCard = document.getElementById('vaultDriveConnectedCard');
        const disconnectedCard = document.getElementById('vaultDriveDisconnectedCard');
        const driveFileName = document.getElementById('vaultDriveFileName');
        const driveFileSize = document.getElementById('vaultDriveFileSize');
        const driveFileMtime = document.getElementById('vaultDriveFileMtime');

        const cloud = data.cloud || {};
        if (cloud.connected) {
          if (driveBadge) {
            driveBadge.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span><span class="text-emerald-300 font-bold">Google Drive Đã Kết Nối</span>`;
          }
          if (connectedCard) connectedCard.classList.remove('hidden');
          if (disconnectedCard) disconnectedCard.classList.add('hidden');

          if (cloud.exists) {
            if (driveFileName) driveFileName.textContent = cloud.name || 'PlayerProfile.congu_save';
            if (driveFileSize) {
              const szMb = (cloud.size / (1024 * 1024)).toFixed(2);
              driveFileSize.textContent = `(${szMb} MB)`;
            }
            if (driveFileMtime) {
              const d = new Date(cloud.modifiedTime);
              driveFileMtime.textContent = `Lưu trên Drive: ${d.toLocaleString('vi-VN')}`;
            }
          } else {
            if (driveFileName) driveFileName.textContent = 'Chưa tải lên Google Drive';
            if (driveFileSize) driveFileSize.textContent = '';
            if (driveFileMtime) driveFileMtime.textContent = 'Bấm "Đẩy Két Lên Google Drive" để sao lưu';
          }
        } else {
          if (driveBadge) {
            driveBadge.innerHTML = `<span class="w-2 h-2 rounded-full bg-slate-500"></span><span class="text-slate-400">Chưa Đăng Nhập Drive</span>`;
          }
          if (connectedCard) connectedCard.classList.add('hidden');
          if (disconnectedCard) disconnectedCard.classList.remove('hidden');
        }

        // Render danh sách game trong két
        renderVaultGamesList(data.games || {});

        if (window.lucide) lucide.createIcons();
      } catch (e) {
        console.error('Lỗi khi tải dữ liệu Vault:', e);
      }
    }

    function renderVaultGamesList(gamesMap) {
      const container = document.getElementById('vaultGamesListContainer');
      const countEl = document.getElementById('vaultGamesListCount');
      if (!container) return;

      const gids = Object.keys(gamesMap);
      if (countEl) countEl.textContent = `${gids.length} game`;

      if (gids.length === 0) {
        container.innerHTML = `
          <div class="text-center py-6 text-xs text-slate-500 bg-black/20 rounded border border-white/5">
            Chưa có game nào trong két. Bấm "Gom Tất Cả Vào Két" ở trên để tự động gom toàn bộ save game hiện có!
          </div>
        `;
        return;
      }

      let html = '';
      for (const [gid, ginfo] of Object.entries(gamesMap)) {
        const title = ginfo.title || gid;
        const playtimeSec = ginfo.playtime_seconds || 0;
        let playtimeStr = '';
        if (playtimeSec >= 3600) {
          playtimeStr = `${(playtimeSec / 3600).toFixed(1)} giờ`;
        } else {
          playtimeStr = `${Math.round(playtimeSec / 60)} phút`;
        }

        const achCount = (ginfo.unlocked_achievements || []).length;
        const fileCount = ginfo.file_count || 0;
        const saveSize = ginfo.save_size_bytes ? `${(ginfo.save_size_bytes / 1024).toFixed(1)} KB` : '';
        const saveMtime = ginfo.save_updated_at ? new Date(ginfo.save_updated_at * 1000).toLocaleString('vi-VN') : 'Chưa có save';

        html += `
          <div class="p-3 rounded-[6px] bg-[#0A0E1A] border border-white/5 hover:border-amber-500/30 transition flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div class="space-y-1">
              <div class="text-xs font-bold text-white flex items-center space-x-2">
                <span>${title}</span>
                <span class="text-[10px] px-1.5 py-0.2 rounded bg-amber-500/20 text-amber-300 font-pixel">ID: ${gid}</span>
              </div>
              <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-400">
                <span class="text-cyan-300"><i data-lucide="clock" class="w-3 h-3 inline"></i> ${playtimeStr}</span>
                <span class="text-emerald-300"><i data-lucide="trophy" class="w-3 h-3 inline"></i> ${achCount} thành tựu</span>
                ${saveSize ? `<span class="text-slate-400"><i data-lucide="hard-drive" class="w-3 h-3 inline"></i> ${saveSize} (${fileCount} tệp)</span>` : ''}
                <span class="text-slate-500">Cập nhật: ${saveMtime}</span>
              </div>
            </div>
            <div class="flex items-center space-x-2 shrink-0">
              <button onclick="packGameToVault('${gid}')" class="pixel-btn px-2.5 py-1 bg-amber-600/80 hover:bg-amber-500 text-white rounded text-xs flex items-center space-x-1" title="Gom lại save của game này vào két">
                <i data-lucide="archive-restore" class="w-3 h-3"></i>
                <span>Gom Lại</span>
              </button>
              <button onclick="unpackGameFromVault('${gid}')" class="pixel-btn px-2.5 py-1 bg-cyan-700 hover:bg-cyan-600 text-white rounded text-xs flex items-center space-x-1" title="Bung save của game này về đúng thư mục máy">
                <i data-lucide="layers" class="w-3 h-3"></i>
                <span>Bung Ra Máy</span>
              </button>
              <button onclick="openSaveTimeMachine('${gid}')" class="pixel-btn px-2.5 py-1 bg-cyan-700 hover:bg-cyan-600 text-white rounded text-xs flex items-center space-x-1" title="Time Machine: khôi phục save của phiên chơi trước nếu save mới nhất bị hỏng">
                <i data-lucide="history" class="w-3 h-3"></i>
                <span>Lịch Sử</span>
              </button>
            </div>
          </div>
        `;
      }
      container.innerHTML = html;
      if (window.lucide) lucide.createIcons();
    }

    async function exportStandardSaveZip() {
      const btn = document.getElementById('btnExportStandardZip');
      if (btn) btn.disabled = true;
      try {
        showToast('Đang mở hộp thoại xuất ZIP chuẩn...', 'info');
        const resp = await fetch('/api/vault/export_standard_zip', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({})
        });
        const data = await resp.json();
        if (data.cancelled) return;
        if (data.success) {
          showToast(`Đã xuất ZIP chuẩn: ${data.games_count || 0} game, ${data.files_count || 0} tệp. Có thể mở bằng WinRAR/7-Zip.`, 'success');
        } else {
          showToast(data.error || 'Xuất ZIP chuẩn thất bại!', 'error');
        }
      } catch (e) {
        showToast('Lỗi khi xuất ZIP save tiêu chuẩn!', 'error');
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    async function importStandardSaveZip() {
      if (!confirm('Khôi phục save từ ZIP chuẩn? Save hiện có sẽ được sao lưu thành .congu_bak trước khi ghi đè.')) return;
      const btn = document.getElementById('btnImportStandardZip');
      if (btn) btn.disabled = true;
      try {
        showToast('Đang mở hộp thoại chọn ZIP chuẩn...', 'info');
        const resp = await fetch('/api/vault/import_standard_zip', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ backup_existing: true })
        });
        const data = await resp.json();
        if (data.cancelled) return;
        if (data.success) {
          const total = Object.values(data.results || {}).reduce((n, r) => n + (r.unpacked_saves || 0), 0);
          showToast(`Đã khôi phục ZIP chuẩn: ${total} tệp save.`, 'success');
          await refreshVaultModalData();
          if (typeof refreshData === 'function') refreshData();
        } else {
          showToast(data.error || 'Nạp ZIP chuẩn thất bại!', 'error');
        }
      } catch (e) {
        showToast('Lỗi khi nạp ZIP save tiêu chuẩn!', 'error');
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    async function exportVault() {
      try {
        showToast('Đang mở hộp thoại chọn vị trí lưu file .congu_save...', 'info');
        const resp = await fetch('/api/vault/export', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({})
        });
        const data = await resp.json();
        if (data.cancelled) return;
        if (data.success) {
          showToast(`Đã xuất file Hồ Sơ thành công ra: ${data.exported_to}`, 'success');
        } else {
          showToast(data.error || 'Xuất file Hồ Sơ thất bại!', 'error');
        }
      } catch (e) {
        showToast('Lỗi khi gửi yêu cầu xuất file Hồ Sơ!', 'error');
      }
    }

    async function importVault() {
      try {
        showToast('Đang mở hộp thoại chọn file .congu_save...', 'info');
        const resp = await fetch('/api/vault/import', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ auto_unpack: true })
        });
        const data = await resp.json();
        if (data.cancelled) return;
        if (data.success) {
          showToast(`Nạp Hồ Sơ thành công! Đã khôi phục ${data.imported_games_count} tựa game và tự động bung save vào máy!`, 'success');
          await refreshVaultModalData();
          if (typeof refreshData === 'function') refreshData();
          // Đồng bộ lại các yêu cầu Việt hóa đi kèm Hồ Sơ (có thể đã có bản Việt Hóa chính thức)
          if (typeof syncLocalizationRequestsOnStartup === 'function') syncLocalizationRequestsOnStartup();
        } else {
          showToast(data.error || 'Nạp file Hồ Sơ thất bại!', 'error');
        }
      } catch (e) {
        showToast('Lỗi khi nạp file Hồ Sơ!', 'error');
      }
    }

    async function packAllToVault() {
      const btn = document.getElementById('btnPackAllVault');
      const origHtml = btn ? btn.innerHTML : '';
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin text-amber-400"></i><span class="text-xs text-amber-300">Đang gom toàn bộ...</span>`;
        if (window.lucide) lucide.createIcons();
      }
      try {
        const resp = await fetch('/api/vault/pack', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({})
        });
        const data = await resp.json();
        if (data.success) {
          showToast(data.message || 'Đã đóng gói toàn bộ game vào Hồ Sơ thành công!', 'success');
          await refreshVaultModalData();
        } else {
          showToast(data.error || 'Gom vào Hồ Sơ thất bại!', 'error');
        }
      } catch (e) {
        showToast('Lỗi khi gửi yêu cầu đóng gói Hồ Sơ!', 'error');
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = origHtml;
          if (window.lucide) lucide.createIcons();
        }
      }
    }

    async function unpackAllFromVault() {
      if (!confirm('Bạn có chắc chắn muốn bung toàn bộ Save Game trong Hồ Sơ ra máy tính này không? Các file save cũ trên máy sẽ được tự động sao lưu dự phòng (.congu_bak).')) {
        return;
      }
      const btn = document.getElementById('btnUnpackAllVault');
      const origHtml = btn ? btn.innerHTML : '';
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin text-cyan-400"></i><span class="text-xs text-cyan-300">Đang bung save...</span>`;
        if (window.lucide) lucide.createIcons();
      }
      try {
        const resp = await fetch('/api/vault/unpack', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ backup_existing: true })
        });
        const data = await resp.json();
        if (data.success) {
          showToast(data.message || 'Đã bung toàn bộ Save Game ra máy tính thành công!', 'success');
          await refreshVaultModalData();
        } else {
          showToast(data.error || 'Bung Save Game thất bại!', 'error');
        }
      } catch (e) {
        showToast('Lỗi khi bung Save Game!', 'error');
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = origHtml;
          if (window.lucide) lucide.createIcons();
        }
      }
    }

    async function packGameToVault(gameId) {
      if (!gameId) return;
      try {
        showToast(`Đang gom Save Game & Thành tựu của '${gameId}' vào Két...`, 'info');
        const resp = await fetch('/api/vault/pack', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: gameId })
        });
        const data = await resp.json();
        if (data.success) {
          showToast(data.message || `Đã gom ${gameId} vào Hồ Sơ Di Động thành công!`, 'success');
          if (document.getElementById('vaultModal') && !document.getElementById('vaultModal').classList.contains('hidden')) {
            await refreshVaultModalData();
          }
        } else {
          showToast(data.error || 'Gom vào Hồ Sơ thất bại!', 'error');
        }
      } catch (e) {
        showToast('Lỗi khi gom game vào Hồ Sơ!', 'error');
      }
    }

    async function unpackGameFromVault(gameId) {
      if (!gameId) return;
      try {
        showToast(`Đang bung Save Game của '${gameId}' từ Két ra máy...`, 'info');
        const resp = await fetch('/api/vault/unpack', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: gameId, backup_existing: true })
        });
        const data = await resp.json();
        if (data.success) {
          showToast(`Đã bung ${data.unpacked_saves} file save của '${gameId}' ra máy thành công!`, 'success');
          if (typeof loadCloudSaveTab === 'function' && activeModalGameId === gameId) {
            loadCloudSaveTab(gameId);
          }
        } else {
          showToast(data.error || 'Bung save thất bại!', 'error');
        }
      } catch (e) {
        showToast('Lỗi khi bung save từ Két ra máy!', 'error');
      }
    }

    async function openVaultFolder() {
      try {
        const resp = await fetch('/api/vault/open_folder', { method: 'POST' });
        const data = await resp.json();
        if (!data.success) {
          showToast('Không thể mở thư mục chứa Hồ Sơ!', 'error');
        }
      } catch (e) {
        showToast('Lỗi khi mở thư mục Hồ Sơ!', 'error');
      }
    }

    async function uploadVaultToDrive() {
      const btn = document.getElementById('btnUploadVaultDrive');
      const origHtml = btn ? btn.innerHTML : '';
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i><span>ĐANG TẢI LÊN DRIVE...</span>`;
        if (window.lucide) lucide.createIcons();
      }
      try {
        const resp = await fetch('/api/vault/cloud/upload', { method: 'POST' });
        const data = await resp.json();
        if (data.success) {
          showToast(data.message || 'Đã đồng bộ Hồ Sơ lên Google Drive thành công!', 'success');
          await refreshVaultModalData();
        } else {
          showToast(data.error || 'Tải lên Google Drive thất bại!', 'error');
        }
      } catch (e) {
        showToast('Lỗi khi tải Hồ Sơ lên Google Drive!', 'error');
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = origHtml;
          if (window.lucide) lucide.createIcons();
        }
      }
    }

    async function downloadVaultFromDrive() {
      if (!confirm('Bạn có chắc muốn tải bản Hồ Sơ (.congu_save) từ Google Drive về máy này không? Toàn bộ save game và thành tựu sẽ được tự động bung vào máy.')) {
        return;
      }
      const btn = document.getElementById('btnDownloadVaultDrive');
      const origHtml = btn ? btn.innerHTML : '';
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i><span>ĐANG TẢI TỪ DRIVE VỀ...</span>`;
        if (window.lucide) lucide.createIcons();
      }
      try {
        const resp = await fetch('/api/vault/cloud/download', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ auto_unpack: true })
        });
        const data = await resp.json();
        if (data.success) {
          showToast(data.message || 'Đã tải và bung Hồ Sơ từ Google Drive thành công!', 'success');
          await refreshVaultModalData();
          if (typeof refreshData === 'function') refreshData();
        } else {
          showToast(data.error || 'Tải Hồ Sơ từ Google Drive thất bại!', 'error');
        }
      } catch (e) {
        showToast('Lỗi khi tải Hồ Sơ từ Google Drive!', 'error');
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = origHtml;
          if (window.lucide) lucide.createIcons();
        }
      }
    }


    // =========================================================================
    // SAVE TIME MACHINE - Lịch sử 3 thế hệ save trong .congu_save
    // =========================================================================
    async function openSaveTimeMachine(gameId) {
      const old = document.getElementById('conguTimeMachine');
      if (old) old.remove();

      const box = document.createElement('div');
      box.id = 'conguTimeMachine';
      box.style.cssText =
        'position:fixed;inset:0;z-index:100002;display:flex;align-items:center;justify-content:center;' +
        'background:rgba(4,6,14,0.82);font-family:Inter,system-ui,sans-serif;';
      box.innerHTML =
        '<div style="width:520px;max-width:94vw;max-height:86vh;display:flex;flex-direction:column;' +
        'background:rgba(12,16,30,0.99);border:1px solid rgba(217,70,239,0.55);border-radius:8px;' +
        'box-shadow:0 24px 60px rgba(0,0,0,0.8);overflow:hidden;">' +
        '<div style="padding:12px 16px;background:linear-gradient(90deg,rgba(217,70,239,0.16),rgba(0,240,255,0.08));' +
        'border-bottom:1px solid rgba(217,70,239,0.28);font-size:12px;font-weight:700;letter-spacing:1px;color:#8B9BB4;">' +
        '🕰 // TIME MACHINE — LỊCH SỬ PHIÊN BẢN SAVE</div>' +
        '<div id="conguTimeMachineBody" style="padding:14px 16px;overflow:auto;flex:1;color:#dbe9f6;font-size:12.5px;">' +
        'Đang tải lịch sử save…</div>' +
        '<div style="display:flex;justify-content:flex-end;padding:12px 16px;border-top:1px solid rgba(255,255,255,0.07);">' +
        '<button id="conguTmClose" style="padding:7px 14px;font-size:12px;border-radius:4px;cursor:pointer;' +
        'background:#171a2c;color:#c7d5e4;border:1px solid #2b3050;">Đóng</button></div>' +
        '</div>';
      document.body.appendChild(box);
      box.querySelector('#conguTmClose').addEventListener('click', () => box.remove());

      const body = box.querySelector('#conguTimeMachineBody');
      try {
        let data = null;
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.get_save_revisions === 'function') {
          data = await window.pywebview.api.get_save_revisions(gameId);
        } else {
          const r = await fetch('/api/vault/revisions?game_id=' + encodeURIComponent(gameId));
          data = await r.json();
        }
        if (!data || !data.success) {
          body.innerHTML = '<div style="color:#FF8FA3;">' + String((data && (data.error || data.message)) || 'Không đọc được lịch sử save.') + '</div>';
          return;
        }
        const revs = data.revisions || [];
        const rows = revs.map((rev) => {
          const isCurrent = rev.revision === 'current';
          const size = rev.bytes ? (rev.bytes / 1024).toFixed(1) + ' KB' : '';
          return '<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;' +
            'padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.06);">' +
            '<div><div style="font-size:12.5px;font-weight:700;color:' + (isCurrent ? '#34D399' : '#8B9BB4') + ';">' +
            rev.label + '</div>' +
            '<div style="font-size:11.5px;color:#8fa6bd;margin-top:3px;">' + rev.packed_at_text +
            (rev.files ? ' · ' + rev.files + ' tệp' : '') + (size ? ' · ' + size : '') + '</div></div>' +
            (isCurrent
              ? '<span style="font-size:11px;color:#5f7288;">đang dùng</span>'
              : '<button data-rev="' + rev.revision + '" class="conguTmRestore pixel-btn" ' +
                'style="padding:5px 11px;font-size:11.5px;border-radius:4px;cursor:pointer;background:#7e22ce;color:#fff;border:1px solid #D946EF;font-weight:700;">Khôi phục</button>') +
            '</div>';
        }).join('');

        body.innerHTML =
          '<div style="margin-bottom:8px;color:#9fb3c8;font-size:11.5px;">' +
          'CỔ NGỮ giữ luân phiên <b>3 phiên bản save</b> gần nhất. Nếu save mới nhất bị hỏng (mất điện khi auto-save), ' +
          'hãy khôi phục về phiên trước.</div>' +
          (rows || '<div style="color:#8fa6bd;">Chưa có dữ liệu save nào trong .congu_save.</div>') +
          (!data.has_history
            ? '<div style="margin-top:10px;padding:8px 10px;border-radius:4px;background:rgba(255,176,32,0.10);' +
              'border:1px solid rgba(255,176,32,0.35);color:#FBBF24;font-size:11.5px;">' +
              'Chưa có bản sao lưu phiên trước. Bản prev_1 sẽ xuất hiện sau lần chơi kế tiếp (mỗi lần CỔ NGỮ đóng gói save).</div>'
            : '');

        body.querySelectorAll('.conguTmRestore').forEach((btn) => {
          btn.addEventListener('click', () => restoreSaveRevision(gameId, btn.getAttribute('data-rev')));
        });
        if (window.lucide) lucide.createIcons();
      } catch (e) {
        body.innerHTML = '<div style="color:#FF8FA3;">Lỗi tải lịch sử save: ' + String(e) + '</div>';
      }
    }

    async function restoreSaveRevision(gameId, revision) {
      const labels = { current: 'bản hiện tại', prev_1: 'phiên chơi trước', prev_2: '2 phiên chơi trước' };
      const label = labels[revision] || revision;
      if (!window.confirm(`Khôi phục save từ ${label}?\nSave hiện tại sẽ được sao lưu thành .congu_prevbak trước khi ghi đè.`)) {
        return;
      }
      try {
        let res = null;
        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.restore_previous_save === 'function') {
          res = await window.pywebview.api.restore_previous_save(gameId, revision);
        } else {
          const r = await fetch('/api/vault/restore_revision', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ game_id: gameId, revision: revision })
          });
          res = await r.json();
        }
        if (typeof showToast === 'function') {
          showToast(res.message || (res.success ? 'Đã khôi phục save.' : 'Khôi phục thất bại.'),
            res.success ? 'success' : 'error');
        }
        if (res.success) {
          const tm = document.getElementById('conguTimeMachine');
          if (tm) tm.remove();
          if (typeof refreshVaultModalData === 'function') refreshVaultModalData();
          if (typeof refreshData === 'function') refreshData();
        }
      } catch (e) {
        if (typeof showToast === 'function') showToast('Lỗi khôi phục save: ' + e, 'error');
      }
    }
