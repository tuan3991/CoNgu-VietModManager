// =============================================================================
// CỔ NGỮ (VIETMODHUB) - HỆ THỐNG ĐỔI TÀI KHOẢN & KÍCH DỮ LIỆU CŨ (ACCOUNT UI)
// Hỗ trợ đổi tài khoản Offline / Online và kích toàn bộ dữ liệu cũ ra để lại app trống.
// =============================================================================

(function () {
  let currentAccountsData = null;
  let activeTab = 'existing'; // 'existing' | 'blank' | 'online'

  function esc(val) {
    if (typeof escapeHtml === 'function') return escapeHtml(String(val == null ? '' : val));
    return String(val == null ? '' : val)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function jsArg(val) {
    return String(val == null ? '' : val)
      .replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"');
  }

  async function openAccountModal() {
    const modal = document.getElementById('accountSwitchModal');
    if (!modal) return;
    modal.classList.remove('hidden');
    await loadAccounts();
    if (window.lucide) lucide.createIcons();
  }

  function closeAccountModal() {
    const modal = document.getElementById('accountSwitchModal');
    if (modal) modal.classList.add('hidden');
  }

  function switchAccountTab(tab) {
    activeTab = tab;
    const tabBtns = ['existing', 'blank', 'online'];
    tabBtns.forEach(t => {
      const btn = document.getElementById(`accTabBtn-${t}`);
      const content = document.getElementById(`accTabContent-${t}`);
      if (btn) {
        if (t === tab) {
          btn.className = 'py-2.5 px-3 border-b-2 border-red-400 text-red-300 font-bold flex items-center space-x-1.5 transition text-xs';
        } else {
          btn.className = 'py-2.5 px-3 border-b-2 border-transparent text-slate-400 hover:text-white flex items-center space-x-1.5 transition text-xs';
        }
      }
      if (content) {
        content.classList.toggle('hidden', t !== tab);
      }
    });
    if (window.lucide) lucide.createIcons();
  }

  async function loadAccounts() {
    const listContainer = document.getElementById('accListContainer');
    const activeBanner = document.getElementById('accActiveBanner');
    if (!listContainer) return;

    listContainer.innerHTML = '<div class="p-6 text-center text-slate-400 text-xs"><i data-lucide="loader-2" class="w-5 h-5 mx-auto mb-2 animate-spin text-red-400"></i>Đang tải danh sách tài khoản...</div>';
    if (window.lucide) lucide.createIcons();

    try {
      const resp = await fetch('/api/account/status');
      const data = await resp.json();
      currentAccountsData = data;

      const active = data.active_account || {};
      const accounts = data.accounts || [];

      // Render Active Banner
      if (activeBanner) {
        const isOnline = active.type === 'online';
        const typeBadge = isOnline
          ? `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/40">ONLINE · ${esc(active.cloud_id || active.name)}</span>`
          : `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/40">OFFLINE · CỤC BỘ</span>`;

        activeBanner.innerHTML = `
          <div class="p-4 rounded-xl border border-red-500/30 bg-gradient-to-r from-red-950/40 to-[#0A101D] flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-[0_0_20px_rgba(255, 42, 85,0.1)]">
            <div class="flex items-center gap-3 min-w-0">
              <div class="w-12 h-12 rounded-xl bg-red-500/20 border border-red-400/50 flex items-center justify-center font-bold text-white text-lg overflow-hidden shrink-0">
                ${active.name ? esc(active.name.slice(0, 1).toUpperCase()) : 'G'}
              </div>
              <div class="min-w-0">
                <div class="flex items-center gap-2 flex-wrap">
                  <h4 class="font-display font-bold text-white text-base truncate">${esc(active.name || 'Game Thủ')}</h4>
                  ${typeBadge}
                </div>
                <p class="text-[11px] text-slate-400 truncate">${active.bio ? esc(active.bio) : 'Tài khoản đang hoạt động'}</p>
              </div>
            </div>
            <div class="flex items-center gap-2 shrink-0">
              <button onclick="handlePurgeAndLogout()" class="pixel-btn px-3 py-1.5 text-xs font-bold bg-red-500/15 hover:bg-red-500/25 text-red-300 border border-red-500/40 hover:border-red-400 rounded transition flex items-center gap-1.5" title="Kích toàn bộ dữ liệu tài khoản này ra khỏi app và làm trống ứng dụng">
                <i data-lucide="log-out" class="w-3.5 h-3.5"></i>
                <span>Kích Dữ Liệu &amp; Làm Trống App</span>
              </button>
            </div>
          </div>
        `;
      }

      // Render danh sách tài khoản
      if (accounts.length === 0) {
        listContainer.innerHTML = '<div class="p-6 text-center text-slate-500 text-xs">Chưa có tài khoản nào được lưu trên máy.</div>';
      } else {
        let html = '<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">';
        accounts.forEach(acc => {
          const isActive = acc.id === active.id;
          const isOnline = acc.type === 'online';
          const badgeClass = isOnline ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' : 'bg-amber-500/20 text-amber-300 border-amber-500/30';
          const typeLabel = isOnline ? 'ONLINE' : 'OFFLINE';

          html += `
            <div class="p-3.5 rounded-xl border ${isActive ? 'border-red-400 bg-red-950/30 shadow-[0_0_15px_rgba(255, 42, 85,0.15)]' : 'border-white/10 bg-[#0E1422] hover:border-white/20'} flex flex-col justify-between gap-3 transition">
              <div class="flex items-start justify-between gap-2">
                <div class="flex items-center gap-2.5 min-w-0">
                  <div class="w-9 h-9 rounded-lg ${isActive ? 'bg-red-500/25 border border-red-400/60' : 'bg-white/5 border border-white/10'} flex items-center justify-center font-bold text-white text-sm shrink-0">
                    ${acc.name ? esc(acc.name.slice(0, 1).toUpperCase()) : 'G'}
                  </div>
                  <div class="min-w-0">
                    <div class="font-bold text-white text-xs truncate">${esc(acc.name)}</div>
                    <div class="flex items-center gap-1.5 mt-0.5">
                      <span class="text-[9px] px-1.5 py-0.2 rounded border ${badgeClass} font-mono">${typeLabel}</span>
                      ${acc.cloud_id ? `<span class="text-[9px] text-slate-400 truncate">ID: ${esc(acc.cloud_id)}</span>` : ''}
                    </div>
                  </div>
                </div>
                ${!isActive ? `
                  <button onclick="handleDeleteAccount('${jsArg(acc.id)}', '${jsArg(acc.name)}')" class="text-slate-500 hover:text-red-400 p-1 transition" title="Xóa tài khoản này khỏi máy">
                    <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                  </button>
                ` : '<span class="text-[9px] font-bold text-red-400 bg-red-500/10 px-1.5 py-0.5 rounded border border-red-400/30">ĐANG DÙNG</span>'}
              </div>
              <div class="flex items-center justify-between pt-2 border-t border-white/[0.06] text-[10px] text-slate-500">
                <span>Cập nhật: ${acc.last_active ? new Date(acc.last_active * 1000).toLocaleDateString('vi-VN') : '—'}</span>
                ${!isActive ? `
                  <button onclick="handleSwitchAccount('${jsArg(acc.id)}')" class="pixel-btn px-2.5 py-1 text-[11px] font-bold bg-white/5 hover:bg-red-500/20 text-slate-200 hover:text-red-300 border border-white/10 hover:border-red-400/40 rounded transition flex items-center gap-1">
                    <i data-lucide="repeat" class="w-3 h-3 text-red-400"></i>
                    <span>Chuyển sang</span>
                  </button>
                ` : `
                  <span class="text-red-400 font-semibold">Tài khoản hiện tại</span>
                `}
              </div>
            </div>
          `;
        });
        html += '</div>';
        listContainer.innerHTML = html;
      }
    } catch (err) {
      listContainer.innerHTML = `<div class="p-6 text-center text-red-400 text-xs">Lỗi tải danh sách tài khoản: ${esc(err.message)}</div>`;
    }

    if (window.lucide) lucide.createIcons();
  }

  async function handleSwitchAccount(accountId) {
    if (!confirm('Bạn có chắc chắn muốn chuyển sang tài khoản này?\n\nỨng dụng sẽ tự động lưu dữ liệu hiện tại vào sandbox riêng và kích toàn bộ dữ liệu của tài khoản cũ ra khỏi app.')) {
      return;
    }

    showToast('Đang kích dữ liệu cũ và chuyển sang tài khoản mới...', 'info');
    try {
      const resp = await fetch('/api/account/switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_id: accountId })
      });
      const res = await resp.json();
      if (!res.success) {
        showToast(res.error || 'Chuyển tài khoản thất bại!', 'error');
        return;
      }

      showToast(res.message, 'success');
      closeAccountModal();
      await triggerAppFullRefresh();
    } catch (err) {
      showToast(`Lỗi khi chuyển tài khoản: ${err.message}`, 'error');
    }
  }

  async function handleCreateBlankAccount() {
    const inputName = document.getElementById('accNewOfflineName');
    const name = inputName ? inputName.value.trim() : '';

    if (!confirm(`Bạn có chắc muốn tạo tài khoản Offline '${name || 'Tài Khoản Mới'}'?\n\nỨng dụng sẽ KÍCH TOÀN BỘ dữ liệu cũ ra và mở ra trạng thái TRỐNG HOÀN TOÀN để bạn bắt đầu.`)) {
      return;
    }

    showToast('Đang kích dữ liệu cũ và làm trống ứng dụng...', 'info');
    try {
      const resp = await fetch('/api/account/create_blank', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, type: 'offline' })
      });
      const res = await resp.json();
      if (!res.success) {
        showToast(res.error || 'Tạo tài khoản thất bại!', 'error');
        return;
      }

      showToast(res.message, 'success');
      if (inputName) inputName.value = '';
      closeAccountModal();
      await triggerAppFullRefresh();
    } catch (err) {
      showToast(`Lỗi tạo tài khoản: ${err.message}`, 'error');
    }
  }

  async function handleLoginOnlineAccount() {
    const inputId = document.getElementById('accOnlineCloudId');
    const inputPass = document.getElementById('accOnlinePassword');

    const cloudId = inputId ? inputId.value.trim() : '';
    const pass = inputPass ? inputPass.value : '';

    if (!cloudId) {
      showToast('Vui lòng nhập Mã Cloud ID!', 'warning');
      return;
    }

    if (!confirm(`Bạn có chắc muốn đăng nhập tài khoản Online '${cloudId}'?\n\nỨng dụng sẽ KÍCH HẾT dữ liệu của tài khoản cũ ra và tải dữ liệu đám mây của tài khoản này về máy.`)) {
      return;
    }

    showToast(`Đang kích dữ liệu cũ và đăng nhập vào Đám Mây '${cloudId}'...`, 'info');
    try {
      const resp = await fetch('/api/account/login_online', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cloud_id: cloudId, password: pass })
      });
      const res = await resp.json();
      if (!res.success) {
        showToast(res.error || 'Đăng nhập online thất bại!', 'error');
        return;
      }

      showToast(res.message, 'success');
      if (inputId) inputId.value = '';
      if (inputPass) inputPass.value = '';
      closeAccountModal();
      await triggerAppFullRefresh();
    } catch (err) {
      showToast(`Lỗi đăng nhập online: ${err.message}`, 'error');
    }
  }

  async function handlePurgeAndLogout() {
    if (!confirm('CẢNH BÁO KÍCH DỮ LIỆU:\n\nBạn có chắc muốn KÍCH TOÀN BỘ dữ liệu cũ ra khỏi máy và đưa ứng dụng về TRẠNG THÁI TRỐNG HOÀN TOÀN không?\n\n(Dữ liệu của tài khoản hiện tại đã được sao lưu an toàn trong sandbox cục bộ và bạn có thể chuyển lại bất kỳ lúc nào).')) {
      return;
    }

    showToast('Đang kích toàn bộ dữ liệu phiên cũ ra khỏi app...', 'info');
    try {
      const resp = await fetch('/api/account/purge_logout', { method: 'POST' });
      const res = await resp.json();
      if (!res.success) {
        showToast(res.error || 'Lỗi khi kích dữ liệu!', 'error');
        return;
      }

      showToast(res.message, 'success');
      closeAccountModal();
      await triggerAppFullRefresh();
    } catch (err) {
      showToast(`Lỗi kích dữ liệu: ${err.message}`, 'error');
    }
  }

  async function handleDeleteAccount(accountId, accountName) {
    if (!confirm(`Bạn có chắc chắn muốn XÓA VĨNH VIỄN tài khoản '${accountName}'?\n\nToàn bộ dữ liệu save game và cấu hình lưu trữ của tài khoản này sẽ bị xóa khỏi máy và không thể khôi phục!`)) {
      return;
    }

    try {
      const resp = await fetch('/api/account/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_id: accountId })
      });
      const res = await resp.json();
      if (!res.success) {
        showToast(res.error || 'Không thể xóa tài khoản!', 'error');
        return;
      }

      showToast(res.message, 'success');
      await loadAccounts();
    } catch (err) {
      showToast(`Lỗi xóa tài khoản: ${err.message}`, 'error');
    }
  }

  async function triggerAppFullRefresh() {
    try {
      if (typeof fetchGames === 'function') {
        await fetchGames();
      }
      if (typeof loadProfile === 'function') {
        await loadProfile(true);
      }
      if (typeof checkCommunityCloudStatus === 'function') {
        await checkCommunityCloudStatus();
      }
      if (typeof checkGdriveStatus === 'function') {
        await checkGdriveStatus();
      }
    } catch (e) {
      console.warn('[AccountUI] Refresh error:', e);
    }
  }

  // Xuất các hàm ra phạm vi toàn cục window
  window.openAccountModal = openAccountModal;
  window.closeAccountModal = closeAccountModal;
  window.switchAccountTab = switchAccountTab;
  window.handleSwitchAccount = handleSwitchAccount;
  window.handleCreateBlankAccount = handleCreateBlankAccount;
  window.handleLoginOnlineAccount = handleLoginOnlineAccount;
  window.handlePurgeAndLogout = handlePurgeAndLogout;
  window.handleDeleteAccount = handleDeleteAccount;
})();
