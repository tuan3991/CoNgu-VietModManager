/*
 * CỔ NGỮ (VietModHub Pro) - First-Run Profile Onboarding
 * ------------------------------------------------------
 * Khi mở app trên PC mới (hoặc Hồ Sơ chưa được thiết lập), hiện màn hình chào
 * mừng để người dùng TỰ ĐẶT TÊN hồ sơ. Không lấy tên tài khoản Windows làm tên
 * mặc định nữa, tránh hiển thị nhầm tên cũ của người dùng.
 */
(function () {
  'use strict';

  var MODAL_ID = 'firstRunProfileModal';
  var shown = false;
  var busy = false;

  function hasApi(name) {
    return !!(window.pywebview && window.pywebview.api && typeof window.pywebview.api[name] === 'function');
  }

  function escapeHtml(text) {
    return String(text == null ? '' : text).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function toast(msg, type) {
    try {
      if (typeof window.showToast === 'function') window.showToast(msg, type || 'info');
    } catch (e) { /* ignore */ }
  }

  async function fetchStatus() {
    try {
      if (hasApi('get_profile_setup_status')) {
        return await window.pywebview.api.get_profile_setup_status();
      }
      var r = await fetch('/api/profile/setup-status', { method: 'GET' });
      if (!r.ok) return null;
      return await r.json();
    } catch (e) {
      return null;
    }
  }

  async function saveProfileName(name) {
    var payload = { player_name: name, sync_cloud: false };
    if (hasApi('update_profile_settings')) {
      return await window.pywebview.api.update_profile_settings(payload);
    }
    var r = await fetch('/api/profile/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!r.ok) return { success: false, error: 'HTTP ' + r.status };
    return await r.json();
  }

  function buildModal() {
    var el = document.createElement('div');
    el.id = MODAL_ID;
    el.className = 'fixed inset-0 z-[90] flex items-center justify-center p-4 bg-black/90 backdrop-blur-md';
    el.innerHTML =
      '<div class="relative w-full max-w-md pixel-modal overflow-hidden bg-[#090b1a] border border-red-500/40 ' +
      'shadow-[0_12px_40px_rgba(0,0,0,0.9),0_0_25px_rgba(255,42,85,0.25)]">' +
      '  <div class="p-5 border-b border-red-500/30 bg-[#1A0A0E] flex items-center gap-3">' +
      '    <div class="w-11 h-11 rounded-[4px] bg-red-500/20 border border-red-500/60 flex items-center justify-center text-red-400">' +
      '      <i data-lucide="user-plus" class="w-5 h-5"></i>' +
      '    </div>' +
      '    <div>' +
      '      <h3 class="font-display text-lg font-bold text-white tracking-wider uppercase">Chào mừng đến Cổ Ngữ</h3>' +
      '      <p class="text-[11px] text-slate-400">Tạo hồ sơ game thủ của riêng bạn trên máy này</p>' +
      '    </div>' +
      '  </div>' +
      '  <div class="p-5 space-y-4">' +
      '    <p class="text-xs text-slate-300 leading-relaxed">' +
      '      Đây là lần đầu mở Cổ Ngữ trên máy này. Hãy đặt tên hiển thị của bạn — ' +
      '      tên này sẽ xuất hiện trong Hồ Sơ, bảng tổng kết phiên chơi và khi đồng bộ Đám Mây.' +
      '    </p>' +
      '    <div>' +
      '      <label for="firstRunPlayerName" class="block text-[11px] font-bold text-slate-300 uppercase tracking-wider mb-1.5">Tên hồ sơ của bạn</label>' +
      '      <input id="firstRunPlayerName" type="text" maxlength="24" autocomplete="off" ' +
      '        class="w-full px-3.5 py-2.5 rounded-lg bg-black/40 border border-white/15 text-sm text-white ' +
      '        placeholder-zinc-500 focus:outline-none focus:border-red-400/70 focus:ring-1 focus:ring-red-400/40 transition" ' +
      '        placeholder="Ví dụ: Minh, Kaiz, GameThủ92...">' +
      '      <p id="firstRunError" class="hidden mt-2 text-[11px] text-red-400"></p>' +
      '    </div>' +
      '    <p class="text-[10px] text-slate-500 flex items-start gap-1.5">' +
      '      <i data-lucide="info" class="w-3.5 h-3.5 mt-0.5 shrink-0"></i>' +
      '      <span>Bạn có thể đổi tên, avatar và ảnh bìa bất cứ lúc nào trong trang Hồ Sơ.</span>' +
      '    </p>' +
      '  </div>' +
      '  <div class="p-4 border-t border-white/[0.06] bg-[#070912] flex items-center justify-end gap-2">' +
      '    <button id="firstRunSubmit" type="button" ' +
      '      class="pixel-btn px-5 py-2.5 text-xs font-bold flex items-center gap-2 bg-red-500/20 hover:bg-red-500/30 ' +
      '      text-red-200 border border-red-500/50 hover:border-red-400 transition disabled:opacity-40 disabled:cursor-not-allowed">' +
      '      <i data-lucide="check" class="w-4 h-4"></i><span>Tạo hồ sơ</span>' +
      '    </button>' +
      '  </div>' +
      '</div>';
    document.body.appendChild(el);
    return el;
  }

  function showModal() {
    var modal = document.getElementById(MODAL_ID) || buildModal();
    modal.classList.remove('hidden');
    if (window.lucide) { try { window.lucide.createIcons(); } catch (e) { /* ignore */ } }

    var input = document.getElementById('firstRunPlayerName');
    var btn = document.getElementById('firstRunSubmit');
    var err = document.getElementById('firstRunError');

    function validate() {
      var ok = input && input.value.trim().length >= 2;
      if (btn) btn.disabled = !ok;
      return ok;
    }

    async function submit() {
      if (busy) return;
      var name = (input && input.value || '').trim().replace(/\s+/g, ' ');
      if (name.length < 2) {
        if (err) { err.textContent = 'Tên hồ sơ cần ít nhất 2 ký tự.'; err.classList.remove('hidden'); }
        return;
      }
      busy = true;
      if (btn) btn.disabled = true;
      if (err) err.classList.add('hidden');
      try {
        var res = await saveProfileName(name);
        if (!res || !res.success) {
          throw new Error((res && (res.error || res.message)) || 'Không lưu được hồ sơ');
        }
        modal.classList.add('hidden');
        toast('Đã tạo hồ sơ "' + name + '"! Chào mừng bạn đến với Cổ Ngữ.', 'success');
        try {
          if (typeof window.loadProfile === 'function') window.loadProfile(true);
        } catch (e) { /* ignore */ }
      } catch (e) {
        if (err) { err.textContent = String(e && e.message || e); err.classList.remove('hidden'); }
        if (btn) btn.disabled = false;
      } finally {
        busy = false;
      }
    }

    if (input) {
      input.addEventListener('input', validate);
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); submit(); }
      });
      setTimeout(function () { try { input.focus(); } catch (e) { /* ignore */ } }, 120);
    }
    if (btn) btn.addEventListener('click', submit);
    validate();
  }

  async function check() {
    if (shown || document.getElementById(MODAL_ID)) return;
    var status = await fetchStatus();
    if (!status || !status.needs_setup) return;
    shown = true;
    showModal();
  }

  window.addEventListener('pywebviewready', function () { setTimeout(check, 500); });
  document.addEventListener('DOMContentLoaded', function () { setTimeout(check, 1200); });
  // Phòng trường hợp pywebview đã sẵn sàng trước khi file này được nạp.
  setTimeout(check, 2000);
})();
