// =============================================================================
// CỔ NGỮ (VIETMODHUB) - CUSTOM THEMES & THEME STUDIO (theme_manager.js)
// =============================================================================
// Chức năng:
//   * Áp dụng theme tức thì (0.1s, không cần khởi động lại app).
//   * Modal Theme Studio: Bộ Sưu Tập (áp dụng / xuất / xóa / nhập .congu_theme)
//     và Tự Thiết Kế (màu sắc, bo góc, blur, ảnh nền, preview trực tiếp).
//
// Ghi chú kỹ thuật:
//   * Backend đã kiểm duyệt mọi giá trị CSS (hex / rgba / số + px). Phía
//     frontend vẫn lọc thêm một lớp phòng thủ (chặn ; { } url( ...).
//   * Tên file / tên theme do người dùng nhập luôn được escapeHtml trước khi
//     đưa vào innerHTML hoặc toast.
//   * Module này không sửa api_client.js / ui_render.js; chỉ dùng showToast(),
//     escapeHtml() do các module đó cung cấp.
// =============================================================================

    const THEME_MANAGER_DEFAULT_ID = 'cyberpunk_default';
    const THEME_MANAGER_PREVIEW_ID = 'theme_studio_preview';
    const THEME_MANAGER_DEFAULT_OPACITY = 0.22;

    // 9 biến CSS chuẩn của theme (đúng thứ tự / đúng tên backend chấp nhận).
    const THEME_MANAGER_VARIABLE_KEYS = [
      '--bg-primary',
      '--bg-secondary',
      '--text-primary',
      '--text-muted',
      '--accent-color',
      '--accent-hover',
      '--border-color',
      '--card-radius',
      '--glass-blur'
    ];

    const THEME_MANAGER_DEFAULT_VARIABLES = {
      '--bg-primary': '#090d16',
      '--bg-secondary': 'rgba(15, 23, 42, 0.85)',
      '--text-primary': '#f8fafc',
      '--text-muted': '#94a3b8',
      '--accent-color': '#06b6d4',
      '--accent-hover': '#22d3ee',
      '--border-color': 'rgba(6, 182, 212, 0.25)',
      '--card-radius': '12px',
      '--glass-blur': '12px'
    };

    // Cache danh sách theme cho toàn bộ phiên làm việc (force=true để làm mới).
    let themeManagerCache = {
      themes: [],
      active: THEME_MANAGER_DEFAULT_ID,
      loaded: false
    };

    // Trạng thái UI / luồng Theme Studio.
    const themeManagerState = {
      currentTab: 'collection',
      studioInitialized: false,
      previewing: false,
      backgroundPath: '',
      backgroundName: '',
      busy: false,
      activeDetail: null
    };

    // Các biến đã gán trực tiếp lên <html> (để dọn biến thừa khi đổi theme).
    let themeManagerAppliedVarKeys = new Set();

    // Chống bấm dồn dập vào cùng một theme.
    const themeManagerSwitching = new Set();

    // -------------------------------------------------------------------------
    // Helpers nhỏ (escape / toast / đọc JSON / định dạng màu)
    // -------------------------------------------------------------------------
    function conguThemeEscape(value) {
      if (typeof escapeHtml === 'function') {
        return escapeHtml(value == null ? '' : String(value));
      }
      return String(value == null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }

    function conguThemeToast(message, type) {
      try {
        if (typeof showToast === 'function') {
          showToast(message, type || 'info');
          return;
        }
      } catch (err) {
        console.warn('[Theme] showToast gặp lỗi:', err);
      }
      console.log('[Theme]', message);
    }

    async function conguThemeReadJson(response) {
      try {
        return await response.json();
      } catch (_) {
        return null;
      }
    }

    function conguThemeEl(id) {
      return document.getElementById(id);
    }

    function conguThemeIsModalOpen() {
      const modal = conguThemeEl('themeManagerModal');
      return !!modal && !modal.classList.contains('hidden');
    }

    function conguThemeClamp(value, min, max) {
      const number = Number(value);
      if (!isFinite(number)) return min;
      return Math.min(max, Math.max(min, Math.round(number)));
    }

    function conguThemeParsePx(value, fallback, min, max) {
      const match = /^\s*(-?\d+(?:\.\d+)?)\s*px\s*$/i.exec(String(value == null ? '' : value));
      if (!match) return conguThemeClamp(fallback, min, max);
      return conguThemeClamp(parseFloat(match[1]), min, max);
    }

    function conguThemeHexToRgb(hex) {
      const value = String(hex || '').trim();
      if (/^#[0-9a-f]{6}$/i.test(value)) {
        return {
          r: parseInt(value.slice(1, 3), 16),
          g: parseInt(value.slice(3, 5), 16),
          b: parseInt(value.slice(5, 7), 16)
        };
      }
      if (/^#[0-9a-f]{3}$/i.test(value)) {
        return {
          r: parseInt(value.charAt(1) + value.charAt(1), 16),
          g: parseInt(value.charAt(2) + value.charAt(2), 16),
          b: parseInt(value.charAt(3) + value.charAt(3), 16)
        };
      }
      return null;
    }

    function conguThemeRgbaFromHex(hex, alpha) {
      const rgb = conguThemeHexToRgb(hex);
      if (!rgb) return 'rgba(15, 23, 42, ' + alpha + ')';
      return 'rgba(' + rgb.r + ', ' + rgb.g + ', ' + rgb.b + ', ' + alpha + ')';
    }

    // Chuẩn hóa mọi giá trị màu về #rrggbb để đưa vào <input type="color">.
    // Hỗ trợ hex, rgb(), rgba(), hsl() nhờ trình duyệt tự quy đổi.
    function conguThemeNormalizeHex(value, fallback) {
      const raw = String(value == null ? '' : value).trim();
      if (/^#[0-9a-f]{6}$/i.test(raw)) return raw.toLowerCase();
      if (/^#[0-9a-f]{3}$/i.test(raw)) {
        return ('#' + raw.charAt(1) + raw.charAt(1) + raw.charAt(2) + raw.charAt(2) +
          raw.charAt(3) + raw.charAt(3)).toLowerCase();
      }

      let probe = null;
      try {
        probe = document.createElement('span');
        probe.style.position = 'absolute';
        probe.style.left = '-9999px';
        probe.style.top = '-9999px';
        probe.style.visibility = 'hidden';
        probe.style.color = '';
        probe.style.color = raw;
        if (!probe.style.color) return fallback;
        document.body.appendChild(probe);
        const computed = window.getComputedStyle(probe).color || '';
        const parts = computed.match(/\d+(?:\.\d+)?/g);
        if (!parts || parts.length < 3) return fallback;
        const toHex = (n) => {
          const channel = Math.max(0, Math.min(255, Math.round(parseFloat(n))));
          return channel.toString(16).padStart(2, '0');
        };
        return ('#' + toHex(parts[0]) + toHex(parts[1]) + toHex(parts[2])).toLowerCase();
      } catch (_) {
        return fallback;
      } finally {
        if (probe && probe.parentNode) probe.parentNode.removeChild(probe);
      }
    }

    function conguThemeBasename(path) {
      const raw = String(path == null ? '' : path).trim();
      if (!raw) return '';
      const parts = raw.replace(/\\/g, '/').split('/');
      return parts[parts.length - 1] || raw;
    }

    function conguThemeAssetUrl(themeId, relativePath) {
      const id = encodeURIComponent(String(themeId == null ? '' : themeId).trim());
      const relative = String(relativePath == null ? '' : relativePath)
        .replace(/\\/g, '/')
        .split('/')
        .filter(function (part) { return part && part !== '.'; })
        .map(function (part) { return encodeURIComponent(part); })
        .join('/');
      if (!id || !relative) return '';
      return '/api/themes/' + id + '/assets/' + relative;
    }

    // -------------------------------------------------------------------------
    // A. ÁP DỤNG THEME TỨC THÌ
    // -------------------------------------------------------------------------
    async function applyTheme(theme) {
      try {
        if (!theme || typeof theme !== 'object') {
          theme = {
            id: THEME_MANAGER_DEFAULT_ID,
            variables: THEME_MANAGER_DEFAULT_VARIABLES,
            assets: {}
          };
        }

        const themeId = (typeof theme.id === 'string' && theme.id.trim())
          ? theme.id.trim()
          : THEME_MANAGER_DEFAULT_ID;
        const variables = (theme.variables && typeof theme.variables === 'object')
          ? theme.variables
          : {};
        const root = document.documentElement;
        const nextKeys = new Set();

        // 1. Gán từng biến CSS an toàn (chỉ nhận key bắt đầu bằng "--").
        Object.keys(variables).forEach(function (key) {
          if (typeof key !== 'string' || key.indexOf('--') !== 0) return;

          const rawValue = variables[key];
          if (typeof rawValue !== 'string' && typeof rawValue !== 'number') return;

          const value = String(rawValue).trim();
          if (!value || value.length > 200) return;
          // Phòng thủ nhiều lớp: backend đã lọc, frontend chặn lại lần nữa.
          if (/[;{}<>]|url\s*\(|expression\s*\(|javascript:|@import/i.test(value)) {
            console.warn('[Theme] Bỏ qua giá trị CSS không an toàn cho', key);
            return;
          }

          try {
            root.style.setProperty(key, value);
            nextKeys.add(key);
          } catch (err) {
            console.warn('[Theme] Không gán được biến CSS', key, err);
          }
        });

        // Dọn các biến cũ không còn xuất hiện trong theme mới.
        themeManagerAppliedVarKeys.forEach(function (key) {
          if (!nextKeys.has(key)) {
            try {
              root.style.removeProperty(key);
            } catch (_) {}
          }
        });
        themeManagerAppliedVarKeys = nextKeys;

        // 2. Ảnh nền (wallpaper) + độ mờ lớp phủ.
        const assets = (theme.assets && typeof theme.assets === 'object')
          ? theme.assets
          : {};
        const backgroundRel = (typeof assets.background_image === 'string')
          ? assets.background_image.trim()
          : '';
        const assetThemeId = (typeof theme._assetThemeId === 'string' && theme._assetThemeId.trim())
          ? theme._assetThemeId.trim()
          : themeId;
        const backgroundUrl = backgroundRel
          ? conguThemeAssetUrl(assetThemeId, backgroundRel)
          : '';

        let opacity = THEME_MANAGER_DEFAULT_OPACITY;
        if (assets.background_opacity != null) {
          const parsed = Number(assets.background_opacity);
          if (isFinite(parsed) && parsed >= 0 && parsed <= 1) opacity = parsed;
        }

        if (backgroundUrl) {
          root.style.setProperty('--bg-wallpaper', "url('" + backgroundUrl + "')");
        } else {
          root.style.setProperty('--bg-wallpaper', 'none');
        }
        root.style.setProperty('--bg-opacity', String(opacity));

        // 3. Scope CSS override + hạ lớp nền pixel gốc khi có wallpaper.
        if (document.body) {
          document.body.dataset.theme = themeId;
          document.body.classList.toggle('congu-has-wallpaper', !!backgroundUrl);
        }

        // 4. Nạp / refresh custom.css của theme (cache-busting).
        //    Preview không có theme thật trên server nên giữ nguyên <link> hiện tại.
        if (themeId !== THEME_MANAGER_PREVIEW_ID) {
          let link = conguThemeEl('congu-custom-theme-css');
          if (!link) {
            link = document.createElement('link');
            link.id = 'congu-custom-theme-css';
            link.rel = 'stylesheet';
            link.type = 'text/css';
            document.head.appendChild(link);
          }
          link.href = '/api/themes/' + encodeURIComponent(themeId) +
            '/custom.css?t=' + Date.now();
        }

        // 5. Ghi nhớ theme đang hiển thị (bỏ qua preview).
        if (themeId !== THEME_MANAGER_PREVIEW_ID) {
          themeManagerState.activeDetail = theme;
        }

        return true;
      } catch (err) {
        // Tuyệt đối không throw ra ngoài: lỗi theme không được làm sập UI.
        console.warn('[Theme] applyTheme thất bại:', err);
        return false;
      }
    }

    // -------------------------------------------------------------------------
    // B. NẠP THEME KHI KHỞI ĐỘNG
    // -------------------------------------------------------------------------
    async function initThemeOnBoot() {
      try {
        const data = await loadThemes(true);
        const activeId = (data && data.active) || THEME_MANAGER_DEFAULT_ID;

        let detail = null;
        try {
          detail = await conguThemeFetchDetail(activeId);
        } catch (err) {
          // Im lặng: giữ giao diện mặc định nếu không đọc được chi tiết.
          console.warn('[Theme] Không đọc được chi tiết theme khi khởi động:', err);
        }

        if (detail) {
          await applyTheme(detail);
        } else {
          // Vẫn scope đúng theme id để CSS không bị lệch, dùng biến mặc định.
          await applyTheme({
            id: activeId,
            name: activeId,
            variables: THEME_MANAGER_DEFAULT_VARIABLES,
            assets: {}
          });
        }
      } catch (err) {
        // Lỗi mạng / backend chưa sẵn sàng: im lặng, không toast khi khởi động.
        console.warn('[Theme] Bỏ qua nạp theme khi khởi động:', err);
      }
    }

    // -------------------------------------------------------------------------
    // C. API HELPERS
    // -------------------------------------------------------------------------
    async function loadThemes(force) {
      if (!force && themeManagerCache.loaded) {
        return {
          themes: themeManagerCache.themes,
          active: themeManagerCache.active
        };
      }

      const response = await fetch('/api/themes', {
        method: 'GET',
        headers: { 'Accept': 'application/json' }
      });
      const data = await conguThemeReadJson(response);

      if (!response.ok || !data || data.success === false) {
        throw new Error((data && data.message) || ('Không tải được danh sách theme (HTTP ' + response.status + ')'));
      }

      themeManagerCache.themes = Array.isArray(data.themes) ? data.themes : [];
      themeManagerCache.active = (typeof data.active === 'string' && data.active.trim())
        ? data.active.trim()
        : THEME_MANAGER_DEFAULT_ID;
      themeManagerCache.loaded = true;

      return {
        themes: themeManagerCache.themes,
        active: themeManagerCache.active
      };
    }

    // Làm mới cache cho các thao tác đã thành công (không biến lỗi mạng phụ
    // thành thông báo "thao tác thất bại").
    async function conguThemeRefreshCache() {
      try {
        await loadThemes(true);
      } catch (err) {
        console.warn('[Theme] Không làm mới được danh sách theme:', err);
      }
    }

    async function conguThemeFetchDetail(themeId) {
      const id = String(themeId == null ? '' : themeId).trim();
      if (!id) throw new Error('Thiếu theme_id.');

      const response = await fetch('/api/themes/detail?theme_id=' + encodeURIComponent(id), {
        method: 'GET',
        headers: { 'Accept': 'application/json' }
      });
      const data = await conguThemeReadJson(response);

      if (!response.ok || !data || data.success === false || !data.theme) {
        throw new Error((data && data.message) || ('Không đọc được theme (HTTP ' + response.status + ')'));
      }
      return data.theme;
    }

    async function conguThemeLoadActiveDetail() {
      const activeId = themeManagerCache.active || THEME_MANAGER_DEFAULT_ID;
      if (themeManagerState.activeDetail &&
          themeManagerState.activeDetail.id === activeId) {
        return themeManagerState.activeDetail;
      }

      try {
        const detail = await conguThemeFetchDetail(activeId);
        themeManagerState.activeDetail = detail;
        return detail;
      } catch (err) {
        console.warn('[Theme] Không đọc được chi tiết theme đang dùng:', err);
        return null;
      }
    }

    // -------------------------------------------------------------------------
    // D. ĐỔI THEME
    // -------------------------------------------------------------------------
    async function switchTheme(themeId) {
      const id = String(themeId == null ? '' : themeId).trim();
      if (!id) return false;
      if (themeManagerSwitching.has(id)) return false;

      themeManagerSwitching.add(id);
      try {
        const response = await fetch('/api/themes/active', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ theme_id: id })
        });
        const data = await conguThemeReadJson(response);

        if (!response.ok || !data || data.success === false) {
          conguThemeToast(
            conguThemeEscape((data && data.message) || 'Không thể áp dụng giao diện này!'),
            'error'
          );
          return false;
        }

        const activeId = (typeof data.active_theme === 'string' && data.active_theme.trim())
          ? data.active_theme.trim()
          : id;

        let detail = null;
        try {
          detail = await conguThemeFetchDetail(activeId);
        } catch (err) {
          console.warn('[Theme] Không đọc được chi tiết theme vừa đổi:', err);
        }

        if (!detail) {
          const summary = (themeManagerCache.themes || []).find(function (item) {
            return item && item.id === activeId;
          });
          detail = {
            id: activeId,
            name: summary ? summary.name : activeId,
            variables: THEME_MANAGER_DEFAULT_VARIABLES,
            assets: {}
          };
        }

        themeManagerCache.active = activeId;
        themeManagerState.previewing = false;
        themeManagerState.studioInitialized = false;
        await applyTheme(detail);

        const displayName = detail.name || activeId;
        conguThemeToast('Đã đổi giao diện: ' + conguThemeEscape(displayName), 'success');

        // Làm mới danh sách trong modal (nếu đang mở) để cập nhật badge "Đang dùng".
        if (conguThemeIsModalOpen()) {
          try {
            await loadThemes(true);
          } catch (err) {
            console.warn('[Theme] Không làm mới được danh sách sau khi đổi theme:', err);
          }
          conguThemeRenderThemeGrid();
        }

        // Đang mở tab Tự Thiết Kế thì nạp lại thông số theo theme vừa áp dụng.
        if (themeManagerState.currentTab === 'studio') {
          await conguThemeSeedStudioForm(true);
        }
        if (window.lucide) lucide.createIcons();
        return true;
      } catch (err) {
        console.warn('[Theme] switchTheme thất bại:', err);
        conguThemeToast('Không thể đổi giao diện. Vui lòng thử lại!', 'error');
        return false;
      } finally {
        themeManagerSwitching.delete(id);
      }
    }

    // -------------------------------------------------------------------------
    // E. MODAL THEME STUDIO: MỞ / ĐÓNG / TAB
    // -------------------------------------------------------------------------
    async function openThemeManager() {
      const modal = conguThemeEl('themeManagerModal');
      if (!modal) return;

      modal.classList.remove('hidden');
      themeManagerState.currentTab = 'collection';
      conguThemeApplyTabUi('collection');
      conguThemeRenderGridMessage('Đang tải bộ sưu tập giao diện...', 'loader-2', 'loading');
      if (window.lucide) lucide.createIcons();

      try {
        await loadThemes(true);
        conguThemeRenderThemeGrid();
        await conguThemeSeedStudioForm(false);
      } catch (err) {
        console.warn('[Theme] Không mở được Theme Studio:', err);
        conguThemeRenderGridMessage(
          'Không tải được bộ sưu tập giao diện. Vui lòng kiểm tra kết nối và thử lại!',
          'alert-triangle',
          'error'
        );
        conguThemeToast('Không tải được danh sách giao diện!', 'error');
      }
    }

    function closeThemeManager() {
      const modal = conguThemeEl('themeManagerModal');
      if (!modal) return;
      modal.classList.add('hidden');

      // Đóng modal khi đang preview -> trả giao diện về theme đang dùng thật.
      if (themeManagerState.previewing) {
        themeManagerState.previewing = false;
        const activeId = themeManagerCache.active || THEME_MANAGER_DEFAULT_ID;
        const revert = (themeManagerState.activeDetail &&
          themeManagerState.activeDetail.id === activeId)
          ? themeManagerState.activeDetail
          : {
              id: activeId,
              name: activeId,
              variables: THEME_MANAGER_DEFAULT_VARIABLES,
              assets: {}
            };
        applyTheme(revert);
      }
    }

    function conguThemeApplyTabUi(tab) {
      const isStudio = tab === 'studio';
      const collectionPanel = conguThemeEl('themeTabPanelCollection');
      const studioPanel = conguThemeEl('themeTabPanelStudio');
      const collectionBtn = conguThemeEl('themeTabBtnCollection');
      const studioBtn = conguThemeEl('themeTabBtnStudio');

      if (collectionPanel) collectionPanel.classList.toggle('hidden', isStudio);
      if (studioPanel) studioPanel.classList.toggle('hidden', !isStudio);

      if (collectionBtn) {
        collectionBtn.classList.toggle('is-active', !isStudio);
        collectionBtn.setAttribute('aria-selected', String(!isStudio));
      }
      if (studioBtn) {
        studioBtn.classList.toggle('is-active', isStudio);
        studioBtn.setAttribute('aria-selected', String(isStudio));
      }
    }

    async function switchThemeTab(tab) {
      const target = tab === 'studio' ? 'studio' : 'collection';
      themeManagerState.currentTab = target;
      conguThemeApplyTabUi(target);

      if (target === 'studio') {
        await conguThemeSeedStudioForm(false);
      }
      if (window.lucide) lucide.createIcons();
    }

    // -------------------------------------------------------------------------
    // F. TAB 1: BỘ SƯU TẬP
    // -------------------------------------------------------------------------
    function conguThemeRenderGridMessage(message, icon, tone) {
      const grid = conguThemeEl('themeGrid');
      if (!grid) return;

      const toneClass = tone === 'error' ? 'text-rose-400' : 'text-slate-400';
      const iconClass = tone === 'loading'
        ? 'w-6 h-6 text-[#00F0FF] animate-spin'
        : (tone === 'error' ? 'w-7 h-7 text-rose-400' : 'w-7 h-7 text-slate-500');

      grid.innerHTML =
        '<div class="col-span-full py-12 flex flex-col items-center justify-center gap-3 text-xs font-sans ' + toneClass + '">' +
          '<i data-lucide="' + conguThemeEscape(icon) + '" class="' + iconClass + '"></i>' +
          '<span>' + conguThemeEscape(message) + '</span>' +
        '</div>';
      if (window.lucide) lucide.createIcons();
    }

    function conguThemeCardHtml(theme) {
      const id = String(theme && theme.id ? theme.id : '');
      // Backend chỉ chấp nhận id [a-z0-9_-]; kiểm tra lại trước khi nhúng vào onclick.
      if (!/^[a-z0-9][a-z0-9_\-]{1,39}$/.test(id)) return '';

      const name = conguThemeEscape(theme.name || id);
      const author = conguThemeEscape(theme.author || 'Ẩn danh');
      const version = conguThemeEscape(theme.version || '1.0');
      const description = conguThemeEscape(theme.description || '');
      const isBuiltin = !!theme.builtin;
      const isActive = id === themeManagerCache.active;
      const canDelete = !isBuiltin && !isActive;
      const previewUrl = (typeof theme.preview_url === 'string' && theme.preview_url)
        ? theme.preview_url
        : '';
      const warnings = Array.isArray(theme.warnings) ? theme.warnings : [];
      const warningsTitle = conguThemeEscape(warnings.join(' · '));

      let previewHtml;
      if (previewUrl) {
        previewHtml =
          '<img src="' + conguThemeEscape(previewUrl) + '" alt="Xem trước ' + name + '" ' +
          'class="absolute inset-0 w-full h-full object-cover" loading="lazy" ' +
          'onerror="this.style.display=\'none\'" />';
      } else {
        previewHtml =
          '<div class="absolute inset-0 flex items-center justify-center bg-gradient-to-br from-[#0b1020] via-[#111326] to-[#1a0b1e]">' +
            '<i data-lucide="palette" class="w-8 h-8 text-[#00F0FF]/40"></i>' +
          '</div>';
      }

      const activeBadge = isActive
        ? '<span class="font-pixel text-[9px] font-bold px-1.5 py-0.5 rounded-[2px] bg-[#00FF9D] text-black shadow-[1px_1px_0_#05050a]">ĐANG DÙNG</span>'
        : '';
      const builtinBadge = isBuiltin
        ? '<span class="font-pixel text-[9px] font-bold px-1.5 py-0.5 rounded-[2px] bg-[#00F0FF]/15 text-[#00F0FF] border border-[#00F0FF]/60">MẶC ĐỊNH</span>'
        : '';
      const warningHtml = warnings.length
        ? '<div class="text-[10px] text-amber-300 flex items-center gap-1" title="' + warningsTitle + '">' +
            '<i data-lucide="alert-triangle" class="w-3 h-3"></i>' +
            '<span>' + warnings.length + ' cảnh báo</span>' +
          '</div>'
        : '';

      const applyClass = isActive
        ? 'pixel-btn bg-slate-700/60 text-slate-400 border border-slate-600 cursor-default opacity-70'
        : 'pixel-btn btn-neon-cyan';

      return '' +
        '<article class="theme-card group relative flex flex-col overflow-hidden border' + (isActive ? ' is-active' : '') + '">' +
          '<div class="relative h-28 overflow-hidden bg-[#070814]">' +
            previewHtml +
            '<div class="absolute inset-0 bg-gradient-to-t from-[#05060f]/90 via-[#05060f]/10 to-transparent"></div>' +
            '<div class="absolute top-2 left-2 flex flex-wrap items-center gap-1">' +
              activeBadge + builtinBadge +
            '</div>' +
            '<span class="absolute bottom-2 right-2 font-pixel text-[9px] font-bold px-1.5 py-0.5 rounded-[2px] bg-black/70 text-slate-300 border border-white/10">v' + version + '</span>' +
          '</div>' +
          '<div class="theme-card-body flex-1 flex flex-col gap-2 p-3">' +
            '<div class="min-w-0">' +
              '<h4 class="font-display text-sm font-bold text-white truncate" title="' + name + '">' + name + '</h4>' +
              '<p class="text-[11px] text-slate-400 font-sans truncate" title="' + author + '">Tác giả: ' + author + '</p>' +
            '</div>' +
            (description
              ? '<p class="text-[11px] text-slate-400 font-sans leading-relaxed line-clamp-2">' + description + '</p>'
              : '') +
            warningHtml +
            '<div class="mt-auto flex items-center gap-1.5 pt-1">' +
              '<button type="button" onclick="switchTheme(\'' + id + '\')"' + (isActive ? ' disabled' : '') +
                ' class="' + applyClass + ' px-2.5 py-1.5 text-[11px] flex-1 flex items-center justify-center gap-1" ' +
                'title="' + (isActive ? 'Giao diện đang được sử dụng' : 'Áp dụng giao diện này') + '">' +
                '<i data-lucide="' + (isActive ? 'check' : 'play') + '" class="w-3 h-3"></i>' +
                '<span>' + (isActive ? 'Đang dùng' : 'Áp dụng') + '</span>' +
              '</button>' +
              '<button type="button" onclick="exportThemePackage(\'' + id + '\')" ' +
                'class="pixel-btn px-2 py-1.5 text-[11px] bg-[#17192e] text-slate-300 border border-[#2b2f52] hover:text-white hover:border-[#00F0FF]" ' +
                'title="Xuất gói .congu_theme để chia sẻ cộng đồng">' +
                '<i data-lucide="download" class="w-3 h-3"></i>' +
              '</button>' +
              (canDelete
                ? '<button type="button" onclick="deleteThemeById(\'' + id + '\')" ' +
                    'class="pixel-btn px-2 py-1.5 text-[11px] bg-[#22070f] text-[#FF6677] border border-[#FF3344]/60 hover:bg-[#FF3344] hover:text-white" ' +
                    'title="Xóa theme này">' +
                    '<i data-lucide="trash-2" class="w-3 h-3"></i>' +
                  '</button>'
                : '') +
            '</div>' +
          '</div>' +
        '</article>';
    }

    function conguThemeRenderThemeGrid() {
      const grid = conguThemeEl('themeGrid');
      if (!grid) return;

      const themes = Array.isArray(themeManagerCache.themes)
        ? themeManagerCache.themes
        : [];

      const countBadge = conguThemeEl('themeCountBadge');
      if (countBadge) countBadge.textContent = String(themes.length);

      if (themes.length === 0) {
        conguThemeRenderGridMessage('Chưa có giao diện nào. Hãy nhập gói .congu_theme hoặc tự thiết kế!', 'palette', 'empty');
        return;
      }

      grid.innerHTML = themes.map(conguThemeCardHtml).join('');

      // Thẻ đầu tiên phải luôn là theme mặc định? Backend đã trả builtin trước.
      if (window.lucide) lucide.createIcons();
    }

    async function importThemePackage() {
      if (themeManagerState.busy) return;
      themeManagerState.busy = true;
      const importBtn = conguThemeEl('themeImportBtn');
      if (importBtn) importBtn.disabled = true;

      try {
        const response = await fetch('/api/themes/import', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({})
        });
        const data = await conguThemeReadJson(response);

        if (response.ok && data && data.success) {
          conguThemeToast('Đã nhập gói theme thành công!', 'success');
          conguThemeShowWarnings(data.warnings);
          await conguThemeRefreshCache();
          conguThemeRenderThemeGrid();
          conguThemeApplyTabUi('collection');
          themeManagerState.currentTab = 'collection';
        } else {
          const message = (data && data.message) || 'Không nhập được gói theme.';
          const type = /chưa chọn|chưa chọn gói/i.test(message) ? 'info' : 'error';
          conguThemeToast(conguThemeEscape(message), type);
        }
      } catch (err) {
        console.warn('[Theme] Import thất bại:', err);
        conguThemeToast('Lỗi khi nhập gói theme. Vui lòng thử lại!', 'error');
      } finally {
        themeManagerState.busy = false;
        if (importBtn) importBtn.disabled = false;
        if (window.lucide) lucide.createIcons();
      }
    }

    async function exportThemePackage(themeId) {
      const id = String(themeId == null ? '' : themeId).trim();
      if (!id) return;

      try {
        const response = await fetch('/api/themes/export', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ theme_id: id })
        });
        const data = await conguThemeReadJson(response);

        if (response.ok && data && data.success) {
          const message = data.path
            ? 'Đã xuất gói theme: ' + data.path
            : 'Đã xuất gói theme thành công!';
          conguThemeToast(conguThemeEscape(message), 'success');
        } else {
          const message = (data && data.message) || 'Không xuất được gói theme.';
          const type = /chưa chọn|chưa chọn nơi lưu/i.test(message) ? 'info' : 'error';
          conguThemeToast(conguThemeEscape(message), type);
        }
      } catch (err) {
        console.warn('[Theme] Export thất bại:', err);
        conguThemeToast('Lỗi khi xuất gói theme. Vui lòng thử lại!', 'error');
      }
    }

    async function deleteThemeById(themeId) {
      const id = String(themeId == null ? '' : themeId).trim();
      if (!id) return;

      const theme = (themeManagerCache.themes || []).find(function (item) {
        return item && item.id === id;
      });
      if (!theme) {
        conguThemeToast('Không tìm thấy giao diện cần xóa!', 'error');
        return;
      }
      if (theme.builtin) {
        conguThemeToast('Không thể xóa giao diện mặc định của ứng dụng!', 'warning');
        return;
      }
      if (id === themeManagerCache.active) {
        conguThemeToast('Không thể xóa giao diện đang sử dụng. Hãy chuyển sang giao diện khác trước!', 'warning');
        return;
      }

      const label = theme.name || id;
      if (!window.confirm('Xóa giao diện "' + label + '" khỏi bộ sưu tập?\n\nHành động này không thể hoàn tác.')) {
        return;
      }

      try {
        const response = await fetch('/api/themes/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ theme_id: id })
        });
        const data = await conguThemeReadJson(response);

        if (response.ok && data && data.success) {
          conguThemeToast('Đã xóa giao diện: ' + conguThemeEscape(label), 'success');
          await loadThemes(true);
          conguThemeRenderThemeGrid();
          if (themeManagerState.currentTab === 'studio') {
            await conguThemeSeedStudioForm(true);
          }
        } else {
          conguThemeToast(
            conguThemeEscape((data && data.message) || 'Không xóa được giao diện này!'),
            'error'
          );
        }
      } catch (err) {
        console.warn('[Theme] Delete thất bại:', err);
        conguThemeToast('Lỗi khi xóa giao diện. Vui lòng thử lại!', 'error');
      }
    }

    // -------------------------------------------------------------------------
    // G. TAB 2: TỰ THIẾT KẾ (THEME STUDIO)
    // -------------------------------------------------------------------------
    function conguThemeSetColorInput(inputId, value, fallback) {
      const input = conguThemeEl(inputId);
      if (!input) return;
      input.value = conguThemeNormalizeHex(value, fallback);
    }

    function conguThemeSetRangeInput(inputId, value, fallback, min, max) {
      const input = conguThemeEl(inputId);
      if (!input) return;
      input.value = String(conguThemeParsePx(value, fallback, min, max));
    }

    function conguThemeUpdateColorReadouts() {
      [['themeColorBg', 'themeColorBgHex'],
       ['themeColorText', 'themeColorTextHex'],
       ['themeColorMuted', 'themeColorMutedHex'],
       ['themeColorAccent', 'themeColorAccentHex'],
       ['themeColorAccentHover', 'themeColorAccentHoverHex']
      ].forEach(function (pair) {
        const input = conguThemeEl(pair[0]);
        const code = conguThemeEl(pair[1]);
        if (input && code) code.textContent = input.value.toLowerCase();
      });

      const radiusInput = conguThemeEl('themeRadiusRange');
      const radiusValue = conguThemeEl('themeRadiusValue');
      if (radiusInput && radiusValue) radiusValue.textContent = radiusInput.value + 'px';

      const blurInput = conguThemeEl('themeBlurRange');
      const blurValue = conguThemeEl('themeBlurValue');
      if (blurInput && blurValue) blurValue.textContent = blurInput.value + 'px';
    }

    function conguThemeUpdateBackgroundUi() {
      const info = conguThemeEl('themeBgFileInfo');
      const nameEl = conguThemeEl('themeBgFileName');
      const removeBtn = conguThemeEl('themeBgRemoveBtn');
      const hasBackground = !!themeManagerState.backgroundName;

      if (info) {
        info.classList.toggle('hidden', !hasBackground);
        info.title = hasBackground ? themeManagerState.backgroundPath : '';
      }
      if (nameEl) nameEl.textContent = hasBackground ? themeManagerState.backgroundName : '';
      if (removeBtn) removeBtn.classList.toggle('hidden', !hasBackground);
    }

    function conguThemeSeedStudioForm(force) {
      if (themeManagerState.studioInitialized && !force) return Promise.resolve();
      if (!conguThemeEl('themeNameInput')) return Promise.resolve();

      return conguThemeLoadActiveDetail().then(function (detail) {
        const variables = Object.assign(
          {},
          THEME_MANAGER_DEFAULT_VARIABLES,
          (detail && detail.variables) || {}
        );

        conguThemeSetColorInput('themeColorBg', variables['--bg-primary'], THEME_MANAGER_DEFAULT_VARIABLES['--bg-primary']);
        conguThemeSetColorInput('themeColorText', variables['--text-primary'], THEME_MANAGER_DEFAULT_VARIABLES['--text-primary']);
        conguThemeSetColorInput('themeColorMuted', variables['--text-muted'], THEME_MANAGER_DEFAULT_VARIABLES['--text-muted']);
        conguThemeSetColorInput('themeColorAccent', variables['--accent-color'], THEME_MANAGER_DEFAULT_VARIABLES['--accent-color']);
        conguThemeSetColorInput('themeColorAccentHover', variables['--accent-hover'], THEME_MANAGER_DEFAULT_VARIABLES['--accent-hover']);

        conguThemeSetRangeInput('themeRadiusRange', variables['--card-radius'], 12, 0, 24);
        conguThemeSetRangeInput('themeBlurRange', variables['--glass-blur'], 12, 0, 32);

        const nameInput = conguThemeEl('themeNameInput');
        if (nameInput) nameInput.value = 'Theme Của Tôi';
        const authorInput = conguThemeEl('themeAuthorInput');
        if (authorInput) authorInput.value = '';

        themeManagerState.backgroundPath = '';
        themeManagerState.backgroundName = '';
        conguThemeUpdateBackgroundUi();
        conguThemeUpdateColorReadouts();
        themeManagerState.studioInitialized = true;
      }).catch(function (err) {
        console.warn('[Theme] Không nạp được thông số Theme Studio:', err);
      });
    }

    function conguThemeReadColorInput(inputId, fallback) {
      const input = conguThemeEl(inputId);
      if (!input) return fallback;
      return conguThemeNormalizeHex(input.value, fallback);
    }

    function conguThemeReadRangeInput(inputId, fallback, min, max) {
      const input = conguThemeEl(inputId);
      if (!input) return fallback;
      return conguThemeClamp(input.value, min, max);
    }

    // Gom đúng 9 biến gửi backend. Hai biến bề mặt (bg-secondary, border-color)
    // được suy ra từ màu nền / màu nhấn để theme luôn hài hoà.
    function conguThemeCollectVariables() {
      const bg = conguThemeReadColorInput('themeColorBg', THEME_MANAGER_DEFAULT_VARIABLES['--bg-primary']);
      const text = conguThemeReadColorInput('themeColorText', THEME_MANAGER_DEFAULT_VARIABLES['--text-primary']);
      const muted = conguThemeReadColorInput('themeColorMuted', THEME_MANAGER_DEFAULT_VARIABLES['--text-muted']);
      const accent = conguThemeReadColorInput('themeColorAccent', THEME_MANAGER_DEFAULT_VARIABLES['--accent-color']);
      const accentHover = conguThemeReadColorInput('themeColorAccentHover', THEME_MANAGER_DEFAULT_VARIABLES['--accent-hover']);
      const radius = conguThemeReadRangeInput('themeRadiusRange', 12, 0, 24);
      const blur = conguThemeReadRangeInput('themeBlurRange', 12, 0, 32);

      return {
        '--bg-primary': bg,
        '--bg-secondary': conguThemeRgbaFromHex(bg, 0.85),
        '--text-primary': text,
        '--text-muted': muted,
        '--accent-color': accent,
        '--accent-hover': accentHover,
        '--border-color': conguThemeRgbaFromHex(accent, 0.32),
        '--card-radius': radius + 'px',
        '--glass-blur': blur + 'px'
      };
    }

    // Preview tức thì: áp dụng ngay màu/slider lên :root, không cần lưu.
    function previewStudioTheme() {
      try {
        const variables = conguThemeCollectVariables();
        const activeId = themeManagerCache.active || THEME_MANAGER_DEFAULT_ID;
        const activeAssets = (themeManagerState.activeDetail &&
          themeManagerState.activeDetail.assets) || {};

        themeManagerState.previewing = true;
        applyTheme({
          id: THEME_MANAGER_PREVIEW_ID,
          name: 'Preview',
          variables: variables,
          assets: activeAssets,
          _assetThemeId: activeId
        });
        conguThemeUpdateColorReadouts();
      } catch (err) {
        console.warn('[Theme] Preview thất bại:', err);
      }
    }

    async function pickThemeBackground() {
      if (themeManagerState.busy) return;
      themeManagerState.busy = true;

      try {
        const response = await fetch('/api/themes/pick_background', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({})
        });
        const data = await conguThemeReadJson(response);

        if (response.ok && data && data.success && typeof data.path === 'string' && data.path.trim()) {
          const path = data.path.trim();
          themeManagerState.backgroundPath = path;
          themeManagerState.backgroundName = conguThemeBasename(path);
          conguThemeUpdateBackgroundUi();
          conguThemeToast('Đã chọn ảnh nền: ' + conguThemeEscape(themeManagerState.backgroundName), 'success');
        } else {
          const message = (data && data.message) || 'Bạn chưa chọn ảnh nền.';
          conguThemeToast(conguThemeEscape(message), 'info');
        }
      } catch (err) {
        console.warn('[Theme] Chọn ảnh nền thất bại:', err);
        conguThemeToast('Lỗi khi mở hộp thoại chọn ảnh nền!', 'error');
      } finally {
        themeManagerState.busy = false;
        if (window.lucide) lucide.createIcons();
      }
    }

    function removeThemeBackground() {
      themeManagerState.backgroundPath = '';
      themeManagerState.backgroundName = '';
      conguThemeUpdateBackgroundUi();
      conguThemeToast('Đã bỏ ảnh nền khỏi theme đang thiết kế.', 'info');
    }

    function conguThemeShowWarnings(warnings) {
      if (!Array.isArray(warnings) || warnings.length === 0) return;
      const preview = warnings.slice(0, 3).map(function (item) {
        return conguThemeEscape(item);
      }).join('<br>');
      const suffix = warnings.length > 3 ? '<br>… và ' + (warnings.length - 3) + ' cảnh báo khác' : '';
      conguThemeToast(
        '<b>Một số giá trị không hợp lệ đã bị bỏ:</b><br>' + preview + suffix,
        'warning'
      );
    }

    async function saveThemeStudio() {
      if (themeManagerState.busy) return;

      const nameInput = conguThemeEl('themeNameInput');
      const authorInput = conguThemeEl('themeAuthorInput');
      const name = (nameInput && nameInput.value ? nameInput.value : '').trim();
      const author = (authorInput && authorInput.value ? authorInput.value : '').trim();

      if (!name) {
        conguThemeToast('Vui lòng nhập tên theme trước khi lưu!', 'warning');
        if (nameInput) nameInput.focus();
        return;
      }
      if (name.length > 80) {
        conguThemeToast('Tên theme không được vượt quá 80 ký tự!', 'warning');
        if (nameInput) nameInput.focus();
        return;
      }
      if (author.length > 120) {
        conguThemeToast('Tên tác giả không được vượt quá 120 ký tự!', 'warning');
        if (authorInput) authorInput.focus();
        return;
      }

      const variables = conguThemeCollectVariables();
      const payload = {
        name: name,
        author: author,
        variables: variables
      };
      if (themeManagerState.backgroundPath) {
        payload.background_image_path = themeManagerState.backgroundPath;
      }

      themeManagerState.busy = true;
      const saveBtn = conguThemeEl('themeSaveBtn');
      if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.classList.add('opacity-60', 'cursor-wait');
      }

      try {
        const response = await fetch('/api/themes/studio', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await conguThemeReadJson(response);

        if (response.ok && data && data.success) {
          conguThemeToast(
            'Đã lưu theme: ' + conguThemeEscape(data.name || name) +
            '. Bấm "Áp dụng" trên thẻ để dùng ngay.',
            'success'
          );
          conguThemeShowWarnings(data.warnings);

          themeManagerState.backgroundPath = '';
          themeManagerState.backgroundName = '';
          themeManagerState.studioInitialized = false;
          conguThemeUpdateBackgroundUi();

          await loadThemes(true);
          conguThemeRenderThemeGrid();

          // Kết thúc preview: quay lại đúng theme đang kích hoạt.
          themeManagerState.previewing = false;
          const activeId = themeManagerCache.active || THEME_MANAGER_DEFAULT_ID;
          let activeDetail = null;
          try {
            activeDetail = await conguThemeFetchDetail(activeId);
          } catch (err) {
            console.warn('[Theme] Không đọc lại được theme đang dùng sau khi lưu:', err);
          }
          if (activeDetail) {
            themeManagerState.activeDetail = activeDetail;
            await applyTheme(activeDetail);
          } else if (themeManagerState.activeDetail) {
            await applyTheme(themeManagerState.activeDetail);
          }

          // Chuyển sang tab Bộ Sưu Tập để thấy theme vừa lưu.
          themeManagerState.currentTab = 'collection';
          conguThemeApplyTabUi('collection');
        } else {
          const message = (data && data.message) || 'Không lưu được theme. Vui lòng kiểm tra lại thông số!';
          conguThemeToast(conguThemeEscape(message), 'error');
          conguThemeShowWarnings(data && data.warnings);
        }
      } catch (err) {
        console.warn('[Theme] Lưu theme thất bại:', err);
        conguThemeToast('Lỗi khi lưu theme. Vui lòng thử lại!', 'error');
      } finally {
        themeManagerState.busy = false;
        if (saveBtn) {
          saveBtn.disabled = false;
          saveBtn.classList.remove('opacity-60', 'cursor-wait');
        }
        if (window.lucide) lucide.createIcons();
      }
    }

    // -------------------------------------------------------------------------
    // H. KHỞI ĐỘNG & PHÍM TẮT
    // -------------------------------------------------------------------------
    if (document.readyState === 'loading') {
      window.addEventListener('DOMContentLoaded', initThemeOnBoot);
    } else {
      initThemeOnBoot();
    }

    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape' && event.key !== 'Esc') return;
      if (!conguThemeIsModalOpen()) return;
      event.preventDefault();
      closeThemeManager();
    });
