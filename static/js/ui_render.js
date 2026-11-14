// =============================================================================
// CỔ NGỮ (VIETMODHUB) - UI RENDER & DOM CONTROLLER (ui_render.js)
// =============================================================================

    let gamesList = [];
    let heroGameId = 'preludes';
    let currentTopNav = 'library'; // 'library' (Kho game của tôi) | 'catalogue' (Kho Game Việt Hóa)
    window.currentTopNav = currentTopNav;

    // Steam-Style Library Sidebar State
    let sidebarFilter = 'installed'; // 'installed' | 'all'
    let sidebarOnlyReady = false;    // chỉ hiện game INSTALLED
    let sidebarQuery = '';
    let sidebarSort = 'az';          // 'az' | 'recent'
    let activeSidebarGameId = null;

    // Toast notification utility
    function showToast(message, type = 'info') {
      const container = document.getElementById('toastContainer');
      const toast = document.createElement('div');

      const colors = {
        success: 'bg-[#0A1F16] text-[#34D399] border border-[#34D399] shadow-[0_8px_24px_rgba(0,0,0,0.45)]',
        error: 'bg-[#2A1216] text-[#F87171] border border-[#F87171] shadow-[0_8px_24px_rgba(0,0,0,0.45)]',
        info: 'bg-[#08121f] text-[#FF2A55] border border-[#FF2A55] shadow-[0_8px_24px_rgba(0,0,0,0.45)]',
        warning: 'bg-[#1c1404] text-[#FBBF24] border border-[#FBBF24] shadow-[0_8px_24px_rgba(0,0,0,0.45)]'
      };

      const icons = {
        success: 'check-circle-2',
        error: 'alert-circle',
        info: 'info',
        warning: 'alert-triangle'
      };

      toast.className = `ios-island flex items-center space-x-3 px-5 py-2.5 font-sans text-xs font-medium pointer-events-none max-w-full ${colors[type] || colors.info}`;
      toast.innerHTML = `
        <i data-lucide="${icons[type] || 'info'}" class="w-4 h-4 shrink-0"></i>
        <span class="truncate">${message}</span>
      `;

      container.appendChild(toast);
      lucide.createIcons();

      setTimeout(() => {
        toast.classList.add('is-leaving');
        setTimeout(() => toast.remove(), 240);
      }, 3500);
    }

    // Helper: Normalize string for fuzzy unaccented search
    function removeVietnameseTones(str) {
      if (!str) return '';
      str = str.toLowerCase();
      str = str.replace(/à|á|ạ|ả|ã|â|ầ|ấ|ậ|ẩ|ẫ|ă|ằ|ắ|ặ|ẳ|ẵ/g, "a");
      str = str.replace(/è|é|ẹ|ẻ|ẽ|ê|ề|ế|ệ|ể|ễ/g, "e");
      str = str.replace(/ì|í|ị|ỉ|ĩ/g, "i");
      str = str.replace(/ò|ó|ọ|ỏ|õ|ô|ồ|ố|ộ|ổ|ỗ|ơ|ờ|ớ|ợ|ở|ỡ/g, "o");
      str = str.replace(/ù|ú|ụ|ủ|ũ|ư|ừ|ứ|ự|ử|ữ/g, "u");
      str = str.replace(/ỳ|ý|ỵ|ỷ|ỹ/g, "y");
      str = str.replace(/đ/g, "d");
      return str;
    }


    function updateUI() {
      renderCounts();
      renderHero();
      renderGrid();
      renderSidebar();
      startHeroAutoRotate();
      if (activeModalGameId) {
        const cur = gamesList.find(g => g.id === activeModalGameId);
        if (cur) openGameModal(cur.id);
      }
    }

    // -------------------------------------------------------------
    // Yêu thích game (Favorites): helper render nút trái tim
    // -------------------------------------------------------------
    function isGameFavorite(game) {
      // Backend chưa sẵn sàng (is_favorite undefined) => coi như chưa yêu thích
      return !!(game && game.is_favorite);
    }

    // Nút tim trên một dòng game ở sidebar: đã thích -> luôn hiện, chưa thích -> hiện khi hover dòng
    function sidebarFavoriteButtonHtml(game) {
      const isFav = isGameFavorite(game);
      const justToggled = (typeof favoriteJustToggledId !== 'undefined' && favoriteJustToggledId === game.id);
      const heartClasses = isFav
        ? 'fav-heart-icon w-3 h-3 text-[#FF2A55] fill-[#FF2A55]'
        : 'fav-heart-icon w-3 h-3 text-slate-500';
      return `
        <button
          type="button"
          onclick="event.stopPropagation(); toggleFavorite('${game.id}')"
          ondblclick="event.stopPropagation()"
          class="fav-heart-btn ${isFav ? 'is-favorite opacity-100' : 'opacity-0 group-hover:opacity-100'}${justToggled ? ' just-toggled' : ''} p-0.5 rounded-[2px] flex items-center justify-center cursor-pointer shrink-0"
          title="Yêu thích / Bỏ yêu thích"
          aria-label="Yêu thích / Bỏ yêu thích"
          aria-pressed="${isFav ? 'true' : 'false'}"
        >
          <i data-lucide="heart" class="${heartClasses}"></i>
        </button>
      `;
    }

    // Nút tim dạng badge tròn ở góc trên-phải poster (lưới trang chủ)
    // LƯU Ý: nút này nằm TRONG cụm flex ở góc phải (không dùng absolute) để không đè lên nhãn giờ chơi
    function gridFavoriteButtonHtml(game) {
      const isFav = isGameFavorite(game);
      const justToggled = (typeof favoriteJustToggledId !== 'undefined' && favoriteJustToggledId === game.id);
      const heartClasses = isFav
        ? 'fav-heart-icon w-3.5 h-3.5 text-[#FF2A55] fill-[#FF2A55]'
        : 'fav-heart-icon w-3.5 h-3.5 text-slate-400';
      return `
        <button
          type="button"
          onclick="event.stopPropagation(); toggleFavorite('${game.id}')"
          class="fav-heart-btn fav-heart-badge shrink-0 w-6 h-6 rounded-full items-center justify-center cursor-pointer ${isFav ? 'is-favorite flex' : 'hidden group-hover:flex'}${justToggled ? ' just-toggled' : ''}"
          title="Yêu thích / Bỏ yêu thích"
          aria-label="Yêu thích / Bỏ yêu thích"
          aria-pressed="${isFav ? 'true' : 'false'}"
        >
          <i data-lucide="heart" class="${heartClasses}"></i>
        </button>
      `;
    }

    // Nút bỏ khỏi Thư viện cho game đang ở trạng thái "Chưa tải" (bookmark)
    function gridBookmarkButtonHtml(game) {
      if (!game || game.library_state !== 'bookmark') return '';
      return `
        <button
          type="button"
          onclick="event.stopPropagation(); toggleGameBookmark('${game.id}')"
          class="shrink-0 w-6 h-6 rounded-full flex items-center justify-center bg-red-500/20 border border-red-400/50 text-red-200 hover:bg-red-500/35 transition"
          title="Bỏ khỏi Thư viện (danh sách Chưa tải)"
          aria-label="Bỏ khỏi Thư viện"
        >
          <i data-lucide="bookmark-check" class="w-3.5 h-3.5"></i>
        </button>
      `;
    }

    // Đồng bộ nút tim ở thanh công cụ trang chi tiết game (viewGameDetail)
    function syncFavoriteDetailButton() {
      const btn = document.getElementById('detailFavoriteBtn');
      if (!btn) return;

      const game = gamesList.find(g => g.id === activeModalGameId);
      const isFav = isGameFavorite(game);
      const justToggled = (typeof favoriteJustToggledId !== 'undefined' && favoriteJustToggledId === activeModalGameId);

      btn.className = `fav-heart-btn pixel-btn px-2.5 py-1.5 text-xs flex items-center space-x-1.5 ${
        isFav
          ? 'is-favorite bg-[#FF2A55]/15 text-[#FF2A55] border border-[#FF2A55] hover:bg-[#FF2A55]/30'
          : 'bg-[#1C2536] text-slate-300 hover:text-white border border-[#2A3548] hover:border-[#FF2A55]'
      }${justToggled ? ' just-toggled' : ''}`;
      btn.title = isFav ? 'Bỏ khỏi Yêu thích' : 'Thêm vào Yêu thích';
      btn.setAttribute('aria-pressed', isFav ? 'true' : 'false');
      btn.innerHTML = `
        <i data-lucide="heart" class="fav-heart-icon w-3.5 h-3.5 ${isFav ? 'text-[#FF2A55] fill-[#FF2A55]' : 'text-slate-400'}"></i>
        <span class="hidden sm:inline font-bold">${isFav ? 'Đã Yêu Thích' : 'Yêu Thích'}</span>
      `;
      if (window.lucide) lucide.createIcons();
    }

    // -------------------------------------------------------------
    // Steam-Style Game Library Sidebar System
    // -------------------------------------------------------------
    function renderSidebar() {
      const container = document.getElementById('sidebarGamesList');
      if (!container) return;

      let list = Array.isArray(gamesList) ? [...gamesList] : [];

      // 1. Sidebar tab filter
      if (sidebarFilter === 'installed') {
        // Chỉ lấy các game đã nhận diện trên máy
        list = list.filter(g => g.status_code === 'INSTALLED' || g.status_code === 'NOT_INSTALLED' || g.status_code === 'UPDATE_DETECTED');
      }

      // 2. Only ready-to-play toggle (Chỉ game Đã Cài Việt Hóa)
      if (sidebarOnlyReady) {
        list = list.filter(g => g.status_code === 'INSTALLED');
      }

      // 3. Search query
      const q = sidebarQuery.trim();
      if (q) {
        const normQ = removeVietnameseTones(q);
        list = list.filter(g => {
          const t1 = removeVietnameseTones(g.title || '');
          const t2 = removeVietnameseTones(g.vietnamese_title || '');
          return t1.includes(normQ) || t2.includes(normQ);
        });
      }

      // 4. Sort: game YÊU THÍCH luôn xếp trước (cả A-Z và Gần đây), sau đó mới tới tiêu chí cũ
      const favoriteFirst = (a, b) => (isGameFavorite(b) ? 1 : 0) - (isGameFavorite(a) ? 1 : 0);
      if (sidebarSort === 'az') {
        list.sort((a, b) => {
          const byFavorite = favoriteFirst(a, b);
          if (byFavorite !== 0) return byFavorite;
          return (a.title || a.vietnamese_title || '').localeCompare(b.title || b.vietnamese_title || '');
        });
      } else if (sidebarSort === 'recent') {
        list.sort((a, b) => {
          const byFavorite = favoriteFirst(a, b);
          if (byFavorite !== 0) return byFavorite;
          const ta = (a.playtime && a.playtime.last_played) || 0;
          const tb = (b.playtime && b.playtime.last_played) || 0;
          return tb - ta;
        });
      }

      // Counts for badges
      const installedCount = gamesList.filter(g => g.status_code === 'INSTALLED' || g.status_code === 'NOT_INSTALLED' || g.status_code === 'UPDATE_DETECTED').length;
      const readyCount = gamesList.filter(g => g.status_code === 'INSTALLED').length;
      const allCount = gamesList.length;

      const badgeInstalled = document.getElementById('sidebarInstalledTabCount');
      if (badgeInstalled) badgeInstalled.innerText = installedCount;
      const badgeAll = document.getElementById('sidebarAllTabCount');
      if (badgeAll) badgeAll.innerText = allCount;
      const badgeReady = document.getElementById('sidebarReadyCount');
      if (badgeReady) badgeReady.innerText = readyCount;

      if (list.length === 0) {
        container.innerHTML = `
          <div class="py-10 px-3 text-center text-slate-500 space-y-2">
            <i data-lucide="package-search" class="w-7 h-7 mx-auto text-slate-600"></i>
            <p class="text-xs">Không có tựa game nào phù hợp</p>
            ${sidebarFilter === 'installed' ? '<button onclick="setSidebarFilter(\'all\')" class="text-[11px] text-[#FF2A55] hover:underline font-bold">Xem tất cả kho game</button>' : ''}
          </div>
        `;
        lucide.createIcons();
        return;
      }

      // Nhóm YÊU THÍCH luôn ở trên cùng; các game đã thích không lặp lại ở những nhóm bên dưới
      const groupFavorite = list.filter(g => isGameFavorite(g));
      const remainingList = list.filter(g => !isGameFavorite(g));

      const groupInstalled = remainingList.filter(g => g.status_code === 'INSTALLED');
      const groupDetected = remainingList.filter(g => g.status_code === 'NOT_INSTALLED' || g.status_code === 'UPDATE_DETECTED');
      const groupBookmark = remainingList.filter(g => g.library_state === 'bookmark');
      const groupGhost = remainingList.filter(g => g.library_state === 'uninstalled_ghost');
      const groupMissing = remainingList.filter(g =>
        g.status_code === 'GAME_MISSING'
        && g.library_state !== 'bookmark'
        && g.library_state !== 'uninstalled_ghost'
      );

      const isHomeActive = !activeModalGameId && !activeSidebarGameId;
      let html = `
        <div
          id="sidebarHomeRow"
          onclick="switchToGridView()"
          class="sidebar-game-row flex items-center justify-between px-2.5 py-2 rounded cursor-pointer transition-all duration-150 text-xs mb-2 ${isHomeActive ? 'bg-white/[0.08] text-white font-semibold border-l-2 border-white/25' : 'text-zinc-400 hover:text-white hover:bg-white/[0.04] border-l-2 border-transparent'}"
          title="Xem trang chủ và kho lưới poster tất cả game"
        >
          <div class="flex items-center space-x-2">
            <i data-lucide="layout-grid" class="w-3.5 h-3.5 text-zinc-400"></i>
            <span class="font-display font-semibold uppercase tracking-wider text-[11px]">Trang Chủ Kho Game</span>
          </div>
          <span class="text-[10px] text-zinc-500 bg-white/[0.06] px-1.5 py-0.5 rounded-full font-medium">${allCount}</span>
        </div>
      `;

      function buildGroup(title, items, iconName, colorClass) {
        if (!items || items.length === 0) return '';
        let s = `
          <div class="mb-3">
            <div class="flex items-center justify-between px-2 py-1 text-[10px] font-pixel font-bold tracking-wider uppercase ${colorClass}">
              <span class="flex items-center space-x-1.5">
                <i data-lucide="${iconName}" class="w-3 h-3"></i>
                <span>${title} (${items.length})</span>
              </span>
            </div>
            <div class="space-y-0.5 mt-0.5">
        `;

        items.forEach(game => {
          const isActive = (activeSidebarGameId === game.id) || (!activeSidebarGameId && heroGameId === game.id);
          const iconSrc = game.local_cover
            || (game.assets && game.assets.poster)
            || game.avatar_url
            || (game.steam_appid ? `https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/${game.steam_appid}/capsule_sm_120.jpg` : '/static/app_icon.png');

          const isRunning = game.playtime && game.playtime.is_running;
          let statusDot = '';
          if (isRunning) {
            statusDot = `<span class="w-2 h-2 rounded-full bg-amber-400 animate-pulse shadow-[0_0_6px_#f59e0b]" title="Đang chơi"></span>`;
          } else if (game.status_code === 'INSTALLED' && game.has_mod_update) {
            statusDot = `<span class="w-2 h-2 rounded-full bg-red-400 animate-pulse shadow-[0_0_6px_#06b6d4]" title="Có bản cập nhật mod mới"></span>`;
          } else if (game.status_code === 'INSTALLED') {
            statusDot = `<span class="w-1.5 h-1.5 rounded-full bg-emerald-400" title="Đã cài Việt Hóa"></span>`;
          } else if (game.status_code === 'UPDATE_DETECTED') {
            statusDot = `<span class="w-2 h-2 rounded-full bg-amber-400 animate-ping" title="Game vừa cập nhật - Cần cài lại"></span>`;
          } else if (game.status_code === 'NOT_INSTALLED') {
            statusDot = `<span class="w-1.5 h-1.5 rounded-full bg-zinc-500" title="Có game trên máy - Sẵn sàng cài mod"></span>`;
          } else if (game.library_state === 'uninstalled_ghost') {
            statusDot = `<span class="w-1.5 h-1.5 rounded-full bg-red-400" title="Chưa cài trên máy này - đã lưu Save trong Hồ Sơ"></span>`;
          } else if (game.library_state === 'bookmark') {
            statusDot = `<span class="w-1.5 h-1.5 rounded-full bg-red-400" title="Đã lưu - Chưa tải game"></span>`;
          } else {
            statusDot = `<span class="w-1.5 h-1.5 rounded-full bg-slate-600" title="Chưa có game"></span>`;
          }

          const activeClasses = isActive
            ? 'bg-white/[0.08] text-white font-semibold border-l-2 border-white/25'
            : 'text-zinc-400 hover:text-white hover:bg-white/[0.04] border-l-2 border-transparent';

          s += `
            <div
              class="sidebar-game-row group flex items-center justify-between px-2 py-1.5 rounded-[2px] cursor-pointer transition-all duration-150 text-xs ${activeClasses}"
              data-sidebar-game-id="${game.id}"
              onclick="selectSidebarGame('${game.id}')"
              ondblclick="selectSidebarGame('${game.id}')"
              title="${escapeHtml(game.title)} - ${escapeHtml(game.vietnamese_title)}&#10;(Click: Xem chi tiết & Chơi game)"
            >
              <div class="flex items-center space-x-2 min-w-0 flex-1">
                <img
                  src="${iconSrc}"
                  class="w-4 h-4 rounded object-cover shrink-0 bg-[#0F1522] border border-white/10 group-hover:border-white/25 transition"
                  onerror="this.onerror=null;this.src='/static/app_icon.png'"
                />
                <span class="truncate block font-sans text-xs ${isActive ? 'text-white' : 'group-hover:text-white'}">
                  ${escapeHtml(game.title || game.vietnamese_title)}
                </span>
              </div>
              <div class="flex items-center space-x-1 shrink-0 ml-1.5">
                ${isRunning ? '<span class="text-[9px] text-amber-300 font-pixel font-bold mr-1 animate-pulse">CHƠI</span>' : ''}
                ${statusDot}
                ${game.status_code === 'INSTALLED' && !isRunning ? `
                  <button
                    onclick="event.stopPropagation(); launchGame('${game.id}')"
                    class="opacity-0 group-hover:opacity-100 p-0.5 text-emerald-400 hover:bg-red-400/15 rounded transition"
                    title="Chơi Ngay (Launch)"
                  >
                    <i data-lucide="play" class="w-3 h-3 fill-emerald-400"></i>
                  </button>
                ` : ''}
                ${sidebarFavoriteButtonHtml(game)}
              </div>
            </div>
          `;
        });

        s += `
            </div>
          </div>
        `;
        return s;
      }

      // Nhóm YÊU THÍCH nằm ngay dưới dòng "Trang Chủ Kho Game" và chỉ hiện khi có game đã thích
      html += buildGroup('★ YÊU THÍCH', groupFavorite, 'star', 'text-zinc-400');

      if (sidebarFilter === 'installed') {
        html += buildGroup('Đã Cài Việt Hóa', groupInstalled, 'check-circle-2', 'text-emerald-400');
        html += buildGroup('Có Sẵn Trên Máy', groupDetected, 'folder-check', 'text-zinc-400');
      } else {
        html += buildGroup('Đã Cài Việt Hóa', groupInstalled, 'check-circle-2', 'text-emerald-400');
        html += buildGroup('Có Sẵn Trên Máy', groupDetected, 'folder-check', 'text-zinc-400');
        html += buildGroup('Danh Sách Chờ (Chưa Tải)', groupBookmark, 'bookmark', 'text-red-400');
        html += buildGroup('Chưa Cài Đặt (Đã Lưu Save)', groupGhost, 'cloud-off', 'text-red-300');
        html += buildGroup('Kho Bản Dịch (Chưa Tải Game)', groupMissing, 'cloud-download', 'text-zinc-500');
      }

      container.innerHTML = html;
      lucide.createIcons();
    }

    function selectSidebarGame(gameId) {
      if (!gameId) {
        switchToGridView();
        return;
      }
      // Mở ngay trang chi tiết game phủ kín panel bên phải (Steam Library Experience)
      openGameModal(gameId);
    }

    function updateSidebarSelection(gameId) {
      activeSidebarGameId = gameId;
      activeModalGameId = gameId;

      const homeRow = document.getElementById('sidebarHomeRow');
      if (homeRow) {
        if (!gameId) {
          homeRow.className = 'sidebar-game-row flex items-center justify-between px-2.5 py-2 rounded cursor-pointer transition-all duration-150 text-xs mb-2 bg-white/[0.08] text-white font-semibold border-l-2 border-white/25';
        } else {
          homeRow.className = 'sidebar-game-row flex items-center justify-between px-2.5 py-2 rounded cursor-pointer transition-all duration-150 text-xs mb-2 text-zinc-400 hover:text-white hover:bg-white/[0.04] border-l-2 border-transparent';
        }
      }

      document.querySelectorAll('.sidebar-game-row[data-sidebar-game-id]').forEach(row => {
        const rowId = row.getAttribute('data-sidebar-game-id');
        const textSpan = row.querySelector('.font-sans');
        if (rowId === gameId) {
          row.className = 'sidebar-game-row group flex items-center justify-between px-2 py-1.5 rounded cursor-pointer transition-all duration-150 text-xs bg-white/[0.08] text-white font-semibold border-l-2 border-white/25';
          if (textSpan) {
            textSpan.classList.add('text-white');
            textSpan.classList.remove('group-hover:text-white');
          }
        } else {
          row.className = 'sidebar-game-row group flex items-center justify-between px-2 py-1.5 rounded cursor-pointer transition-all duration-150 text-xs text-zinc-400 hover:text-white hover:bg-white/[0.04] border-l-2 border-transparent';
          if (textSpan) {
            textSpan.classList.remove('text-white');
            textSpan.classList.add('group-hover:text-white');
          }
        }
      });
    }

    function switchToGridView(targetNav) {
      const applySwitch = () => {
        activeModalGameId = null;
        activeSidebarGameId = null;

        // Đưa gạch chân navbar về tab đích nếu có
        if (targetNav && typeof window.uiSetActiveNav === 'function') {
          window.uiSetActiveNav(targetNav);
        }

        // 1. Chuyển đổi View: Hiện kho lưới, ẩn trang chi tiết
        const viewGrid = document.getElementById('viewBrowseGrid');
        const viewDetail = document.getElementById('viewGameDetail');
        const viewDiscovery = document.getElementById('viewDiscovery');
        const viewProfile = document.getElementById('viewProfile');
        const viewSearch = document.getElementById('viewSearchResults');
        if (viewGrid) viewGrid.classList.remove('hidden');
        if (viewDetail) viewDetail.classList.add('hidden');
        if (viewDiscovery) viewDiscovery.classList.add('hidden');
        if (viewProfile) viewProfile.classList.add('hidden');
        if (viewSearch) viewSearch.classList.add('hidden');

        // 2. Ngắt âm thanh video nếu đang phát trailer
        const player = document.getElementById('modalVideoPlayer');
        if (player) {
          player.src = '';
        }
        currentActiveVideoId = null;

        // 3. Highlight lại nút "Trang Chủ Kho Game" trên sidebar
        updateSidebarSelection(null);

        // 4. Cuộn mượt lên đầu trang
        const mainScroll = document.getElementById('mainScrollContainer');
        if (mainScroll) {
          mainScroll.scrollTo({ top: 0, behavior: 'smooth' });
        }

        if (window.lucide) lucide.createIcons();
      };

      if (typeof window.withIosViewTransition === 'function') window.withIosViewTransition(applySwitch);
      else applySwitch();
    }
    window.switchToGridView = switchToGridView;

    function switchToLibraryView() {
      currentTopNav = 'library';
      window.currentTopNav = 'library';
      if (typeof window.uiSetActiveNav === 'function') {
        window.uiSetActiveNav('library');
      }
      switchToGridView('library');
      const catBanner = document.getElementById('catalogueHeaderBanner');
      if (catBanner) catBanner.classList.add('hidden');
      const hero = document.getElementById('heroBanner');
      if (hero) hero.classList.remove('hidden');
      setFilter('installed');
    }
    window.switchToLibraryView = switchToLibraryView;

    function switchToCatalogueView() {
      currentTopNav = 'catalogue';
      window.currentTopNav = 'catalogue';
      if (typeof window.uiSetActiveNav === 'function') {
        window.uiSetActiveNav('catalogue');
      }
      switchToGridView('catalogue');
      const catBanner = document.getElementById('catalogueHeaderBanner');
      if (catBanner) catBanner.classList.remove('hidden');
      const hero = document.getElementById('heroBanner');
      if (hero) hero.classList.add('hidden');
      setFilter('all');
    }
    window.switchToCatalogueView = switchToCatalogueView;

    function setSidebarFilter(filter) {
      sidebarFilter = filter;
      const tabInst = document.getElementById('sidebarTabInstalled');
      const tabAll = document.getElementById('sidebarTabAll');
      if (filter === 'installed') {
        if (tabInst) tabInst.className = 'flex-1 py-1 px-1.5 text-center text-xs font-bold font-display rounded-[2px] bg-[#FF2A55]/15 text-[#FF2A55] border border-[#FF2A55]/50 transition';
        if (tabAll) tabAll.className = 'flex-1 py-1 px-1.5 text-center text-xs font-bold font-display rounded-[2px] text-slate-400 hover:text-white transition';
      } else {
        if (tabInst) tabInst.className = 'flex-1 py-1 px-1.5 text-center text-xs font-bold font-display rounded-[2px] text-slate-400 hover:text-white transition';
        if (tabAll) tabAll.className = 'flex-1 py-1 px-1.5 text-center text-xs font-bold font-display rounded-[2px] bg-[#FF2A55]/15 text-[#FF2A55] border border-[#FF2A55]/50 transition';
      }
      renderSidebar();
    }

    function toggleSidebarInstalledOnly() {
      sidebarOnlyReady = !sidebarOnlyReady;
      const btn = document.getElementById('sidebarOnlyInstalledBtn');
      if (btn) {
        if (sidebarOnlyReady) {
          btn.className = 'pixel-btn p-1.5 bg-[#FF2A55] text-black border border-[#FF2A55] rounded-[2px] shadow-[0_0_8px_#FF2A55]';
        } else {
          btn.className = 'pixel-btn p-1.5 bg-[#1C2536] text-slate-400 hover:text-[#FF2A55] border border-[#2A3548] rounded-[2px]';
        }
      }
      renderSidebar();
    }

    function toggleSidebarSort() {
      sidebarSort = sidebarSort === 'az' ? 'recent' : 'az';
      const btn = document.getElementById('sidebarSortBtn');
      if (btn) {
        if (sidebarSort === 'recent') {
          btn.innerHTML = '<i data-lucide="clock" class="w-3 h-3 text-[#FF2A55]"></i>';
          btn.title = 'Đang sắp xếp: Giờ chơi gần đây (Bấm để đổi sang A-Z)';
        } else {
          btn.innerHTML = '<i data-lucide="arrow-down-a-z" class="w-3 h-3 text-slate-400"></i>';
          btn.title = 'Đang sắp xếp: Tên A-Z (Bấm để đổi sang gần đây)';
        }
        lucide.createIcons();
      }
      renderSidebar();
    }

    function toggleSidebar() {
      const sidebar = document.getElementById('librarySidebar');
      const strip = document.getElementById('collapsedSidebarStrip');
      const btn = document.getElementById('btnToggleSidebar');
      const brandIcon = document.getElementById('brandToggleSidebarIcon');
      const brandBtn = document.getElementById('btnBrandToggleSidebar');

      if (!sidebar) return;
      const isHidden = sidebar.classList.contains('hidden');
      if (isHidden) {
        sidebar.classList.remove('hidden');
        if (strip) strip.classList.add('hidden');
        if (btn) {
          btn.classList.add('bg-[#FF2A55]/20', 'text-[#FF2A55]');
        }
        if (brandIcon) {
          brandIcon.setAttribute('data-lucide', 'panel-left-close');
        }
        if (brandBtn) {
          brandBtn.title = 'Thu gọn danh sách game bên trái (Ctrl+B)';
        }
        localStorage.setItem('sidebar_visible', 'true');
      } else {
        sidebar.classList.add('hidden');
        if (strip) strip.classList.add('hidden');
        if (btn) {
          btn.classList.remove('bg-[#FF2A55]/20', 'text-[#FF2A55]');
        }
        if (brandIcon) {
          brandIcon.setAttribute('data-lucide', 'panel-left');
        }
        if (brandBtn) {
          brandBtn.title = 'Mở danh sách game bên trái (Ctrl+B)';
        }
        localStorage.setItem('sidebar_visible', 'false');
      }
      lucide.createIcons();
    }


    function renderCounts() {
      const allCount = gamesList.length;
      const onDiskCount = gamesList.filter(g => g.is_custom_game || g.is_game_found || ['INSTALLED', 'NOT_INSTALLED', 'UPDATE_DETECTED'].includes(g.status_code)).length;
      const bookmarkCount = gamesList.filter(g => g.library_state === 'bookmark').length;
      const ghostCount = gamesList.filter(g => g.library_state === 'uninstalled_ghost').length;

      const countAll = document.getElementById('count-all');
      if (countAll) countAll.innerText = allCount;
      const pillAll = document.getElementById('count-all-pill');
      if (pillAll) pillAll.innerText = (currentTopNav === 'library') ? onDiskCount : allCount;
      const pillOnDisk = document.getElementById('count-on-disk');
      if (pillOnDisk) pillOnDisk.innerText = onDiskCount;
      const pillBookmark = document.getElementById('count-bookmark');
      if (pillBookmark) pillBookmark.innerText = bookmarkCount;
      const pillGhost = document.getElementById('count-ghost');
      if (pillGhost) pillGhost.innerText = ghostCount;

      // Tính tổng thời gian chơi toàn bộ thư viện game Cổ Ngữ
      let totalPlaySecs = 0;
      gamesList.forEach(g => {
        if (g.playtime && g.playtime.total_seconds) {
          totalPlaySecs += g.playtime.total_seconds;
        }
      });
      // Đếm game thay đổi -> nút nav đổi độ rộng, đồng bộ lại viên thuốc
      if (typeof window.iosSyncNavPill === 'function') window.iosSyncNavPill();

      const globalPtElem = document.getElementById('globalPlaytimeText');
      if (globalPtElem) {
        if (totalPlaySecs === 0) {
          globalPtElem.innerText = 'Tổng giờ chơi: 0 giờ';
        } else if (totalPlaySecs < 3600) {
          globalPtElem.innerText = `Tổng giờ chơi: ${Math.max(1, Math.floor(totalPlaySecs / 60))} phút`;
        } else {
          globalPtElem.innerText = `Tổng giờ chơi: ${(totalPlaySecs / 3600).toFixed(1)} giờ`;
        }
      }

      // Update genre options with exact counts
      const optAll = document.querySelector('#genreFilter option[value="all"]');
      if (optAll) optAll.innerText = `Tất cả thể loại (${allCount})`;

      const genreDefs = {
        'rpg_story': ['nhập vai', 'rpg', 'cốt truyện', 'story', 'tường thuật', 'lựa chọn'],
        'action_shooter': ['hành động', 'bắn súng', 'action', 'top-down'],
        'detective_adventure': ['trinh thám', 'phiêu lưu', 'giải đố', 'noir'],
        'roguelike_strategy': ['roguelike', 'roguelite', 'chiến thuật', 'bộ bài', 'vòng lặp'],
        'cozy_casual': ['thư giãn', 'nhiếp ảnh', 'cozy', 'thư thái'],
        'horror_dark': ['kinh dị', 'quản lý', 'dark fantasy', 'bạo lực', 'hắc ám']
      };

      for (const [key, kws] of Object.entries(genreDefs)) {
        const count = gamesList.filter(g => {
          const txt = ((g.genre || '') + ' ' + (g.title || '') + ' ' + (g.vietnamese_title || '')).toLowerCase();
          return kws.some(k => txt.includes(k));
        }).length;
        const opt = document.querySelector(`#genreFilter option[value="${key}"]`);
        if (opt) {
          const baseName = opt.getAttribute('data-name') || opt.innerText.split(' (')[0];
          opt.innerText = `${baseName} (${count})`;
        }
      }
    }

    function setFilter(filter) {
      if (document.getElementById('viewBrowseGrid') && document.getElementById('viewBrowseGrid').classList.contains('hidden')) {
        switchToGridView();
      }
      activeFilter = filter;
      ['all', 'on_disk', 'bookmark', 'ghost'].forEach(f => {
        const btn = document.getElementById(`filter-${f}`);
        if (!btn) return;
        if (f === filter) {
          btn.className = 'pixel-tab active-filter-tab px-3.5 py-1.5 text-xs font-bold transition';
        } else {
          btn.className = 'pixel-tab px-3.5 py-1.5 text-xs font-bold transition';
        }
      });
      // Đồng bộ segmented "Đã Cài | Tất Cả" trên header
      try {
        window.dispatchEvent(new CustomEvent('congu:filter-changed', { detail: filter }));
      } catch (e) { /* ignore */ }
      renderGrid();
    }

    function onGenreFilterChange() {
      if (document.getElementById('viewBrowseGrid') && document.getElementById('viewBrowseGrid').classList.contains('hidden')) {
        switchToGridView();
      }
      activeGenreFilter = document.getElementById('genreFilter').value;
      renderGrid();
    }

    // 5-Second Hero Auto-Rotate System
    let heroAutoTimer = null;
    let isHeroHovered = false;

    // Hero chỉ xoay quanh game thực sự có trên máy / có bản dịch, không quảng bá thẻ "Chưa tải"
    function getHeroCandidateGames() {
      const list = Array.isArray(gamesList) ? gamesList : [];
      if (currentTopNav === 'library') {
        const onDisk = list.filter(g => g && (g.is_custom_game || g.is_game_found || ['INSTALLED', 'NOT_INSTALLED', 'UPDATE_DETECTED'].includes(g.status_code)));
        if (onDisk.length) return onDisk;
      }
      const pool = list.filter(g => g && g.library_state !== 'bookmark' && g.library_state !== 'uninstalled_ghost');
      return pool.length ? pool : list;
    }

    function autoRotateHero() {
      if (!document.getElementById('heroBanner')) return;
      const heroPool = getHeroCandidateGames();
      if (heroPool.length <= 1 || isHeroHovered) return;
      // Do not auto-rotate if user is actively viewing game modal details
      const modal = document.getElementById('gameModal');
      if (modal && !modal.classList.contains('hidden')) return;

      const currentIndex = heroPool.findIndex(g => g.id === heroGameId);
      const nextIndex = (currentIndex + 1) % heroPool.length;
      heroGameId = heroPool[nextIndex].id;
      renderHero();
    }

    function startHeroAutoRotate() {
      if (!document.getElementById('heroBanner')) return;
      if (heroAutoTimer) clearInterval(heroAutoTimer);
      heroAutoTimer = setInterval(autoRotateHero, 5000);
    }

    function shuffleHeroSpotlight() {
      if (!document.getElementById('heroBanner')) return;
      const heroPool = getHeroCandidateGames();
      if (heroPool.length === 0) return;
      const otherGames = heroPool.filter(g => g.id !== heroGameId);
      const nextGame = otherGames[Math.floor(Math.random() * otherGames.length)] || heroPool[0];
      heroGameId = nextGame.id;
      renderHero();
      startHeroAutoRotate(); // Reset 5s countdown
    }

    function renderHero() {
      if (!document.getElementById('heroBanner')) return;
      const heroPool = getHeroCandidateGames();
      const game = heroPool.find(g => g.id === heroGameId) || heroPool[0];
      if (!game) return;

      const heroBannerImg = game.local_cover || (game.assets && game.assets.banner) || game.header_url || game.avatar_url || '';
      const heroBg = document.getElementById('heroBg');
      if (heroBg) heroBg.style.backgroundImage = `url('${heroBannerImg}')`;
      const heroTitle = document.getElementById('heroTitle');
      if (heroTitle) heroTitle.innerText = game.vietnamese_title || game.title || '';
      const heroDesc = document.getElementById('heroDesc');
      if (heroDesc) heroDesc.innerText = game.description || '';
      const heroEngine = document.getElementById('heroEngine');
      if (heroEngine) heroEngine.innerText = game.engine || '';

      // Important note
      const heroNote = document.getElementById('heroNoteContainer');
      const heroNoteText = document.getElementById('heroNoteText');
      if (heroNote && heroNoteText) {
        if (game.important_note) {
          heroNoteText.innerText = game.important_note;
          heroNote.classList.remove('hidden');
        } else {
          heroNote.classList.add('hidden');
        }
      }

      // Hero 3-state badge & main action
      const badge = document.getElementById('heroBadge');
      const badgeDot = document.getElementById('heroBadgeDot');
      const statusText = document.getElementById('heroStatusText');
      const actionBtn = document.getElementById('heroActionBtn');

      if (!actionBtn) return;

      if (game.status_code === 'INSTALLED') {
        if (game.has_mod_update) {
          badge.className = 'text-[11px] font-medium px-2.5 py-1 rounded-full bg-red-500/[0.15] text-red-300 border border-red-500/30 inline-flex items-center gap-1.5 animate-pulse';
          badgeDot.className = 'w-1.5 h-1.5 rounded-full bg-red-400 inline-block';
          statusText.innerText = `Có bản cập nhật (${game.latest_mod_version || 'Mới'})`;
          actionBtn.className = 'pixel-btn btn-arcade-red px-6 py-2.5 text-sm flex items-center gap-2 rounded-xl';
          actionBtn.innerHTML = `<i data-lucide="arrow-up-circle" class="w-4 h-4 stroke-[2.5]"></i><span>Cập Nhật Việt Hóa</span>`;
        } else {
          badge.className = 'text-[11px] font-medium px-2.5 py-1 rounded-full bg-emerald-500/[0.12] text-emerald-300 border border-emerald-500/25 inline-flex items-center gap-1.5';
          badgeDot.className = 'w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block';
          statusText.innerText = 'Đã cài Việt hóa';
          actionBtn.className = 'pixel-btn btn-neon-green px-6 py-2.5 text-sm flex items-center gap-2 rounded-xl';
          actionBtn.innerHTML = `<i data-lucide="play" class="w-4 h-4 fill-current"></i><span>Chơi Ngay</span>`;
        }
      } else if (game.status_code === 'UPDATE_DETECTED') {
        badge.className = 'text-[11px] font-medium px-2.5 py-1 rounded-full bg-amber-500/[0.12] text-amber-300 border border-amber-500/25 inline-flex items-center gap-1.5';
        badgeDot.className = 'w-1.5 h-1.5 rounded-full bg-amber-400 inline-block';
        statusText.innerText = 'Game vừa cập nhật — mất Việt hóa';
        actionBtn.className = 'pixel-btn btn-arcade-amber px-6 py-2.5 text-sm flex items-center gap-2 rounded-xl';
        actionBtn.innerHTML = `<i data-lucide="refresh-cw" class="w-4 h-4 stroke-[2.5]"></i><span>Cài Lại 1-Click</span>`;
      } else if (game.status_code === 'GAME_MISSING') {
        badge.className = 'text-[11px] font-medium px-2.5 py-1 rounded-full bg-white/[0.06] text-zinc-300 border border-white/[0.08] inline-flex items-center gap-1.5';
        badgeDot.className = 'w-1.5 h-1.5 rounded-full bg-zinc-500 inline-block';
        statusText.innerText = 'Chưa tìm thấy game';
        actionBtn.className = 'pixel-btn px-6 py-2.5 text-sm flex items-center gap-2 rounded-xl';
        actionBtn.innerHTML = `<i data-lucide="folder-search" class="w-4 h-4 stroke-[2.5]"></i><span>Chọn Đường Dẫn Game</span>`;
      } else {
        badge.className = 'text-[11px] font-medium px-2.5 py-1 rounded-full bg-white/[0.06] text-zinc-300 border border-white/[0.08] inline-flex items-center gap-1.5';
        badgeDot.className = 'w-1.5 h-1.5 rounded-full bg-zinc-500 inline-block';
        statusText.innerText = 'Chưa cài mod';
        actionBtn.className = 'pixel-btn btn-arcade-amber px-6 py-2.5 text-sm flex items-center gap-2 rounded-xl';
        actionBtn.innerHTML = `<i data-lucide="download" class="w-4 h-4 stroke-[2.5]"></i><span>Cài Đặt Việt Hóa</span>`;
      }

      // Hero Playtime Badge & Playing State (Luôn hiển thị rõ ràng như Steam)
      const heroPtBadge = document.getElementById('heroPlaytimeBadge');
      const heroPtText = document.getElementById('heroPlaytimeText');
      if (heroPtBadge && heroPtText) {
        const pt = game.playtime || { is_running: false, formatted_time: 'Chưa chơi', last_played_str: 'Chưa từng mở', total_seconds: 0 };
        heroPtBadge.classList.remove('hidden');
        if (pt.is_running) {
          heroPtBadge.className = 'text-[11px] font-medium px-2.5 py-1 rounded-full bg-amber-500/[0.12] text-amber-300 border border-amber-500/25 inline-flex items-center gap-1.5 animate-pulse';
          heroPtText.innerText = 'Đang chơi...';
        } else if (pt.total_seconds > 0) {
          heroPtBadge.className = 'text-[11px] font-medium px-2.5 py-1 rounded-full bg-white/[0.06] text-zinc-300 border border-white/[0.08] inline-flex items-center gap-1.5';
          heroPtText.innerText = `Giờ chơi: ${pt.formatted_time} • Lần cuối: ${pt.last_played_str}`;
        } else {
          heroPtBadge.className = 'text-[11px] font-medium px-2.5 py-1 rounded-full bg-white/[0.06] text-zinc-400 border border-white/[0.08] inline-flex items-center gap-1.5';
          heroPtText.innerText = 'Chưa chơi';
        }
      }

      if (game.playtime && game.playtime.is_running) {
        actionBtn.disabled = true;
        actionBtn.className = 'pixel-btn px-6 py-2.5 text-sm flex items-center gap-2 rounded-xl cursor-not-allowed animate-pulse';
        actionBtn.innerHTML = `<i data-lucide="gamepad-2" class="w-4 h-4"></i><span>Đang chơi...</span>`;
      } else {
        actionBtn.disabled = false;
      }

      lucide.createIcons();
    }

    function onHeroMainAction() {
      const game = gamesList.find(g => g.id === heroGameId);
      if (!game) return;

      if (game.status_code === 'INSTALLED') {
        if (game.has_mod_update) {
          toggleMod(game.id, true);
        } else {
          launchGame(game.id);
        }
      } else if (game.status_code === 'UPDATE_DETECTED') {
        toggleMod(game.id, true);
      } else if (game.status_code === 'GAME_MISSING') {
        openGameModal(game.id);
      } else {
        toggleMod(game.id);
      }
    }

    // Get Short Punchy Primary Genre Tag for Poster Badge
    function getPrimaryGenreTag(game) {
      const g = (game.genre || '').toLowerCase();
      if (g.includes('trinh thám') || g.includes('noir')) return 'Trinh Thám';
      if (g.includes('chiến thuật')) return 'Chiến Thuật';
      if (g.includes('nhập vai') || g.includes('rpg') || g.includes('arpg')) return 'Nhập Vai';
      if (g.includes('roguelike') || g.includes('roguelite')) return 'Roguelike';
      if (g.includes('kinh dị')) return 'Kinh Dị';
      if (g.includes('thư giãn') || g.includes('cozy') || g.includes('nhiếp ảnh')) return 'Thư Giãn';
      if (g.includes('hành động') || g.includes('bắn súng')) return 'Hành Động';
      if (g.includes('phiêu lưu')) return 'Phiêu Lưu';
      if (g.includes('steam store') || g.trim() === 'steam') return 'Steam';
      // Không cắt cứng chuỗi nữa (trước đây slice(0,10) làm "Steam Store" -> "Steam Stor");
      // việc xuống dòng/đứt chữ do class `truncate` của CSS đảm nhiệm.
      const raw = (game.genre || '').split(',')[0].trim();
      if (!raw) return game.is_custom_game ? 'Game Lẻ' : 'Việt Hóa';
      return raw;
    }

    // Render 2:3 Portrait Cards Grid
    function renderGrid() {
      const container = document.getElementById('gamesGrid');
      container.innerHTML = '';

      // Sao chép mảng để không làm thay đổi thứ tự gốc của gamesList khi sort
      let filtered = Array.isArray(gamesList) ? [...gamesList] : [];

      // 1. Phân định theo Tab chính: Kho game của tôi vs Kho Game Việt Hóa
      if (currentTopNav === 'library') {
        // Kho game của tôi: CHỈ hiển thị game ĐÃ CÓ TRÊN MÁY (hoặc game tự thêm Non-Steam)
        filtered = filtered.filter(g => 
          g.is_custom_game || 
          g.is_game_found || 
          ['INSTALLED', 'NOT_INSTALLED', 'UPDATE_DETECTED'].includes(g.status_code)
        );
      } else {
        // Kho Game Việt Hóa: Toàn bộ danh mục game, lọc theo trạng thái nếu có
        if (activeFilter === 'on_disk' || activeFilter === 'installed') {
          filtered = filtered.filter(g => ['INSTALLED', 'NOT_INSTALLED', 'UPDATE_DETECTED'].includes(g.status_code));
        } else if (activeFilter === 'bookmark') {
          filtered = filtered.filter(g => g.library_state === 'bookmark');
        } else if (activeFilter === 'ghost') {
          filtered = filtered.filter(g => g.library_state === 'uninstalled_ghost');
        } else if (activeFilter === 'uninstalled') {
          filtered = filtered.filter(g => g.status_code === 'NOT_INSTALLED');
        } else if (activeFilter === 'missing') {
          filtered = filtered.filter(g => g.status_code === 'GAME_MISSING');
        }
      }

      // 2. Genre Filter
      if (activeGenreFilter !== 'all') {
        filtered = filtered.filter(g => {
          const genreText = ((g.genre || '') + ' ' + (g.title || '') + ' ' + (g.vietnamese_title || '')).toLowerCase();
          if (activeGenreFilter === 'rpg_story') {
            return ['nhập vai', 'rpg', 'cốt truyện', 'story', 'tường thuật', 'lựa chọn'].some(k => genreText.includes(k));
          }
          if (activeGenreFilter === 'action_shooter') {
            return ['hành động', 'bắn súng', 'action', 'top-down'].some(k => genreText.includes(k));
          }
          if (activeGenreFilter === 'detective_adventure') {
            return ['trinh thám', 'phiêu lưu', 'giải đố', 'noir'].some(k => genreText.includes(k));
          }
          if (activeGenreFilter === 'roguelike_strategy') {
            return ['roguelike', 'roguelite', 'chiến thuật', 'bộ bài', 'vòng lặp'].some(k => genreText.includes(k));
          }
          if (activeGenreFilter === 'cozy_casual') {
            return ['thư giãn', 'nhiếp ảnh', 'cozy', 'thư thái'].some(k => genreText.includes(k));
          }
          if (activeGenreFilter === 'horror_dark') {
            return ['kinh dị', 'quản lý', 'dark fantasy', 'bạo lực', 'hắc ám'].some(k => genreText.includes(k));
          }
          return true;
        });
      }

      // 3. Sắp xếp: game YÊU THÍCH luôn lên đầu lưới (giữ nguyên thứ tự cũ cho các game còn lại)
      filtered.sort((a, b) => (isGameFavorite(b) ? 1 : 0) - (isGameFavorite(a) ? 1 : 0));

      if (filtered.length === 0) {
        if (currentTopNav === 'library') {
          container.innerHTML = `
            <div class="col-span-full py-16 text-center text-slate-400 space-y-3">
              <i data-lucide="folder-search" class="w-12 h-12 mx-auto text-slate-500"></i>
              <h4 class="text-sm font-bold text-white">Chưa có tựa game nào trong Kho game của tôi</h4>
              <p class="text-xs text-slate-400 max-w-md mx-auto leading-relaxed">
                Bạn có thể bấm <strong>"Thêm game"</strong> ở góc phải để thêm game từ máy tính, hoặc sang tab <strong>"Kho Game Việt Hóa"</strong> để tìm và tải bản dịch cho các tựa game yêu thích!
              </p>
              <button onclick="switchToCatalogueView()" class="pixel-btn btn-neon-red px-4 py-2 text-xs font-bold inline-flex items-center gap-1.5 mt-2">
                <i data-lucide="compass" class="w-4 h-4"></i>
                <span>Khám Phá Kho Game Việt Hóa</span>
              </button>
            </div>
          `;
        } else {
          container.innerHTML = `
            <div class="col-span-full py-16 text-center text-slate-500 space-y-2">
              <i data-lucide="search-x" class="w-10 h-10 mx-auto text-slate-600"></i>
              <p class="text-sm">Không tìm thấy tựa game nào phù hợp với bộ lọc hiện tại!</p>
            </div>
          `;
        }
        lucide.createIcons();
        return;
      }

      filtered.forEach(game => {
        const card = document.createElement('div');
        // Card đang Yêu thích được viền/glow hồng neon nhẹ (xem .pixel-card.is-favorite trong styles.css)
        const isBookmarkState = game.library_state === 'bookmark';
        const isGhost = !!game.is_ghost;
        const isWaitingTranslation = game.library_state === 'needs_translation';
        card.className = `group relative pixel-card overflow-hidden flex flex-col${isGameFavorite(game) ? ' is-favorite' : ''}${isWaitingTranslation ? ' ring-1 ring-amber-400/30' : ''}`;
        card.setAttribute('data-game-id', game.id);

        const posterSrc = game.local_cover
          || (game.assets && game.assets.poster)
          || game.avatar_url
          || (game.steam_appid ? `https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/${game.steam_appid}/library_600x900.jpg` : '');

        const fallbackHeaderSrc = game.header_url
          || (game.assets && game.assets.header)
          || (game.steam_appid ? `https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/${game.steam_appid}/header.jpg` : '');

        let statusBadgeHtml = '';
        if (game.status_code === 'INSTALLED') {
          statusBadgeHtml = `<span class="font-pixel text-[10px] font-bold px-2 py-0.5 rounded-[4px] bg-[#0A0E1A]/80 text-emerald-400 border border-emerald-500/40 flex items-center space-x-1.5 tracking-wide shadow-[0_2px_8px_rgba(0,0,0,0.5)]" style="backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);"><span class="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block shrink-0 shadow-[0_0_6px_#34D399]"></span><span>Đã Cài Đặt</span></span>`;
        } else if (game.status_code === 'UPDATE_DETECTED') {
          statusBadgeHtml = `<span class="font-pixel text-[10px] font-bold px-2 py-0.5 rounded-[4px] bg-[#0A0E1A]/80 text-amber-300 border border-amber-400/60 flex items-center space-x-1.5 tracking-wide shadow-[0_2px_8px_rgba(0,0,0,0.5)]" style="backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);"><span class="w-1.5 h-1.5 rounded-full bg-amber-400 inline-block animate-pulse shadow-[0_0_6px_#F59E0B]"></span><span>⚠️ Mất Việt Hóa</span></span>`;
        } else if (game.status_code === 'GAME_MISSING') {
          statusBadgeHtml = `<span class="font-pixel text-[10px] font-bold px-2 py-0.5 rounded-[4px] bg-[#0A0E1A]/80 text-red-400 border border-red-500/40 flex items-center space-x-1.5 tracking-wide shadow-[0_2px_8px_rgba(0,0,0,0.5)]" style="backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);"><i data-lucide="folder-x" class="w-3.5 h-3.5 text-red-400"></i><span>Chưa Có Game</span></span>`;
        } else {
          statusBadgeHtml = `<span class="font-pixel text-[10px] font-bold px-2 py-0.5 rounded-[4px] bg-[#0A0E1A]/80 text-amber-400 border border-amber-500/40 flex items-center space-x-1.5 tracking-wide shadow-[0_2px_8px_rgba(0,0,0,0.5)]" style="backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);"><i data-lucide="arrow-down-circle" class="w-3.5 h-3.5 text-amber-400"></i><span>Chưa Cài Mod</span></span>`;
        }

        // Game lẻ (Non-Steam): hiển thị rõ đây là game tự thêm + trạng thái Yêu cầu Việt hóa
        const myLocReq = game.is_custom_game ? getMyLocRequest(game) : null;
        if (game.is_custom_game) {
          statusBadgeHtml = myLocReq
            ? `<span class="font-pixel text-[10px] font-bold px-2 py-0.5 rounded-[4px] bg-[#0A0E1A]/85 text-amber-300 border border-[#FBBF24]/60 flex items-center space-x-1 tracking-wide shadow-[0_2px_8px_rgba(0,0,0,0.5)]" style="backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);" title="Đã lưu yêu cầu Việt hóa trong Hồ Sơ .congu_save • ${(myLocReq.status_label || 'Đang chờ duyệt')}"><i data-lucide="megaphone" class="w-3 h-3 text-[#FBBF24]"></i><span>Đã YC Việt Hóa</span></span>`
            : `<span class="font-pixel text-[10px] font-bold px-2 py-0.5 rounded-[4px] bg-[#0A0E1A]/85 text-red-300 border border-red-500/50 flex items-center space-x-1 tracking-wide shadow-[0_2px_8px_rgba(0,0,0,0.5)]" style="backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);"><i data-lucide="gamepad" class="w-3 h-3 text-red-300"></i><span>Game Tự Thêm</span></span>`;
        }

        const noteBadgeHtml = game.important_note
          ? `<span class="font-pixel text-[10px] font-bold px-2 py-0.5 rounded-[4px] bg-[#0A0E1A]/80 text-rose-400 border border-rose-500/50 flex items-center space-x-1.5 tracking-wide shadow-[0_2px_8px_rgba(0,0,0,0.5)]" style="backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);"><i data-lucide="alert-triangle" class="w-3 h-3 text-rose-400"></i><span>Lưu Ý</span></span>`
          : '';

        let playtimeBadgeHtml = '';
        const pt = game.playtime || { is_running: false, formatted_time: 'Chưa chơi', last_played_str: 'Chưa từng mở', total_seconds: 0 };
        if (pt.is_running) {
          playtimeBadgeHtml = `<span id="card-playtime-${game.id}" class="font-pixel text-[10px] font-bold px-2 py-0.5 rounded-[4px] bg-amber-500/20 text-amber-300 border border-amber-400/60 flex items-center space-x-1 tracking-wide animate-pulse" style="backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);"><i data-lucide="gamepad-2" class="w-3 h-3 text-amber-300"></i><span>ĐANG CHƠI</span></span>`;
        } else if (pt.total_seconds > 0) {
          playtimeBadgeHtml = `<span id="card-playtime-${game.id}" class="font-pixel text-[10px] font-bold px-2 py-0.5 rounded-[4px] bg-[#0A0E1A]/80 text-red-400 border border-red-500/30 flex items-center space-x-1 tracking-wide shadow-[0_2px_8px_rgba(0,0,0,0.5)]" style="backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);" title="Thời gian chơi: ${pt.formatted_time} • Lần cuối: ${pt.last_played_str}"><i data-lucide="clock" class="w-2.5 h-2.5 text-red-400"></i><span>${pt.formatted_time}</span></span>`;
        } else {
          playtimeBadgeHtml = `<span id="card-playtime-${game.id}" class="font-pixel text-[10px] font-bold px-2 py-0.5 rounded-[4px] bg-[#0A0E1A]/80 text-slate-400 border border-slate-700/50 flex items-center space-x-1 tracking-wide shadow-[0_2px_8px_rgba(0,0,0,0.5)]" style="backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);" title="Thời gian chơi: Chưa chơi"><i data-lucide="clock" class="w-2.5 h-2.5 text-slate-500"></i><span>Chưa chơi</span></span>`;
        }

        // === 1 huy hiệu duy nhất (pill nhỏ) ở góc trên phải poster ===
        const pillBase = 'inline-flex items-center gap-1.5 px-2 py-1 rounded-full bg-black/60 backdrop-blur-md text-[10px] font-semibold tracking-wide border whitespace-nowrap';
        let statusPillHtml = '';
        if (isGhost) {
          statusPillHtml = `<span class="${pillBase} border-red-500/40 text-red-200" title="Game chưa cài trên máy này nhưng đã có Save trong Hồ Sơ"><i data-lucide="cloud-off" class="w-3 h-3"></i>CHƯA CÀI · ĐÃ LƯU SAVE</span>`;
        } else if (isBookmarkState) {
          statusPillHtml = `<span class="${pillBase} border-red-500/40 text-red-200" title="Đã lưu trong Thư viện nhưng chưa tải game"><i data-lucide="cloud-download" class="w-3 h-3"></i>CHƯA TẢI</span>`;
        } else if (game.status_code === 'INSTALLED' && game.has_mod_update) {
          statusPillHtml = `<span class="${pillBase} border-red-500/40 text-red-200 animate-pulse" title="Có bản cập nhật mod mới"><span class="w-1.5 h-1.5 rounded-full bg-red-400"></span>CÓ BẢN MỚI</span>`;
        } else if (game.status_code === 'INSTALLED') {
          statusPillHtml = `<span class="${pillBase} border-emerald-500/30 text-emerald-300" title="Đã cài Việt hóa"><span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>VI</span>`;
        } else if (game.status_code === 'UPDATE_DETECTED') {
          statusPillHtml = `<span class="${pillBase} border-amber-500/30 text-amber-300" title="Game vừa cập nhật — cần cài lại Việt hóa"><span class="w-1.5 h-1.5 rounded-full bg-amber-400"></span>CẦN CÀI LẠI</span>`;
        } else if (game.status_code === 'GAME_MISSING') {
          statusPillHtml = `<span class="${pillBase} border-white/10 text-zinc-400" title="Chưa có game trên máy">THIẾU GAME</span>`;
        } else if (game.is_custom_game) {
          statusPillHtml = `<span class="${pillBase} border-white/10 text-zinc-400" title="Game tự thêm (Non-Steam)">TỰ THÊM</span>`;
        } else {
          // Nhãn "CHƯA CÀI": kính mờ cực dịu, tương phản thấp để không tranh chấp với nhãn • VI
          statusPillHtml = `<span class="inline-flex items-center gap-1.5 px-2 py-1 rounded-full bg-black/50 backdrop-blur-md text-[10px] font-semibold tracking-wide border border-white/10 text-zinc-400 whitespace-nowrap" title="Chưa cài mod Việt hóa">CHƯA CÀI</span>`;
        }
        if (game.important_note) {
          statusPillHtml += `<span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/30" title="Game có lưu ý quan trọng"><i data-lucide="alert-triangle" class="w-3 h-3"></i></span>`;
        }

        // Huy hiệu góc phải: giờ chơi hoặc nguồn game (Steam / Tự thêm)
        const topPill = (function () {
          if (pt.total_seconds > 0 && pt.formatted_time) {
            return `<span class="${pillBase} border-white/10 text-zinc-300" title="Thời gian chơi: ${pt.formatted_time} • Lần cuối: ${pt.last_played_str}"><i data-lucide="clock" class="w-3 h-3"></i>${pt.formatted_time}</span>`;
          }
          if (isGhost) {
            const ach = game.vault_save && game.vault_save.achievements_count;
            return `<span class="${pillBase} border-red-500/30 text-red-300" title="Đã lưu Save trong Hồ Sơ"><i data-lucide="archive" class="w-3 h-3"></i>${ach ? ach + ' cúp' : 'Có Save'}</span>`;
          }
          if (isBookmarkState) {
            return `<span class="${pillBase} border-red-500/30 text-red-300" title="Đã lưu trong Thư viện"><i data-lucide="bookmark" class="w-3 h-3"></i>Đã lưu</span>`;
          }
          if (game.steam_appid) {
            return `<span class="${pillBase} border-white/10 text-zinc-400" title="Game Steam"><i data-lucide="steam" class="w-3 h-3"></i></span>`;
          }
          if (game.is_custom_game) {
            return `<span class="${pillBase} border-white/10 text-zinc-400" title="Game tự thêm">Tự thêm</span>`;
          }
          return `<span class="${pillBase} border-white/10 text-zinc-500" title="Chưa chơi">Chưa chơi</span>`;
        })();

        card.innerHTML = `
          <!-- Poster 2:3 — ảnh gốc full-bleed, không nhãn đè lên logo -->
          <div class="relative aspect-[2/3] w-full overflow-hidden bg-[#0F1522] cursor-pointer" onclick="openGameModal('${game.id}')" oncontextmenu="openCardContextMenu(event, '${game.id}')">
            <!-- Ảnh bìa -->
            <img
              src="${posterSrc}"
              alt="${game.title}"
              class="absolute inset-0 z-10 w-full h-full object-cover transition-transform duration-500 ease-out group-hover:scale-[1.04]${isGhost ? ' opacity-50 grayscale brightness-[0.65]' : (isBookmarkState ? ' opacity-60 saturate-50' : '')}"
              onerror="if (this.dataset.fallback !== '1' && '${fallbackHeaderSrc}') { this.dataset.fallback = '1'; this.src = '${fallbackHeaderSrc}'; } else { this.style.display = 'none'; if (this.nextElementSibling) this.nextElementSibling.classList.remove('hidden'); }"
            />

            <!-- Ảnh dự phòng khi không có bìa -->
            <div class="hidden absolute inset-0 bg-gradient-to-br from-zinc-900 via-zinc-800 to-zinc-900 flex-col items-center justify-center p-4 text-center">
              <span class="text-[10px] font-semibold tracking-wider text-zinc-500 mb-2 uppercase">${getPrimaryGenreTag(game) || 'Đã Việt Hóa'}</span>
              <h3 class="font-display text-sm font-semibold text-white leading-snug line-clamp-3 px-2">${game.title}</h3>
            </div>

            <!-- Lớp gradient đáy: bảo đảm chữ luôn đọc rõ trên bìa sáng -->
            <div class="absolute inset-x-0 bottom-0 z-10 h-[58%] bg-gradient-to-t from-zinc-950 via-zinc-950/70 to-transparent pointer-events-none"></div>

            <!-- Huy hiệu trái: trạng thái Việt hóa -->
            <div class="absolute top-3 left-3 z-30 flex items-center gap-1.5 pointer-events-none">
              ${statusPillHtml}
            </div>

            <!-- Cụm góc phải: nhãn giờ chơi + nút Yêu thích xếp CÙNG MỘT HÀNG (không absolute chồng nhau) -->
            <div class="absolute top-3 right-3 z-30 flex items-center gap-1.5 max-w-[calc(100%-1.5rem)]">
              <div class="min-w-0 pointer-events-none transition-opacity duration-200 group-hover:opacity-0">
                ${topPill}
              </div>
              ${gridBookmarkButtonHtml(game)}
              ${gridFavoriteButtonHtml(game)}
            </div>

            <!-- Tên game + thông tin phụ (hiện khi hover) -->
            <div class="absolute inset-x-0 bottom-0 z-20 p-4 pointer-events-none transition-transform duration-200 group-hover:-translate-y-11">
              <h3 class="font-display text-[15px] font-semibold text-white leading-snug line-clamp-1">${game.title}</h3>
              <div id="card-playtime-sub-${game.id}" class="mt-1 flex items-center gap-1.5 text-[11px] text-zinc-400 opacity-0 group-hover:opacity-100 transition-opacity duration-200 min-w-0">
                <span class="truncate">${getPrimaryGenreTag(game) || 'Đã Việt hóa'}</span>
                <span class="text-zinc-600 shrink-0">•</span>
                <span id="card-playtime-text-${game.id}" class="shrink-0 whitespace-nowrap">${pt.is_running ? 'Đang chơi...' : (pt.total_seconds > 0 ? pt.formatted_time : 'Chưa chơi')}${game.vault_save && game.vault_save.achievements_count ? ` · ${game.vault_save.achievements_count} cúp` : ''}${game.pending_vault_save ? ' · Save chờ' : ''}</span>
              </div>
            </div>

            <!-- Badge giờ chơi cũ: ẩn nhưng giữ ID cho JS cập nhật realtime -->
            <div class="hidden" aria-hidden="true">${playtimeBadgeHtml}</div>

            <!-- Hành động khi hover -->
            <div class="absolute inset-x-0 bottom-0 p-3 pt-8 bg-gradient-to-t from-zinc-950 via-zinc-950/95 to-transparent opacity-0 translate-y-2 group-hover:opacity-100 group-hover:translate-y-0 transition-all duration-200 z-30 flex items-center justify-center">
              ${gridHoverActionsHtml(game, pt)}
            </div>
          </div>
        `;

        container.appendChild(card);
      });

      // Các thẻ chỉ xuất hiện khi cuộn tới (iOS scroll reveal)
      if (typeof iosRevealCards === 'function') iosRevealCards(container);

      lucide.createIcons();
    }

    // Nút hành động hiện ra khi rê chuột lên thẻ game (Arcade micro-switch)
    function gridHoverActionsHtml(game, pt) {
      const runningBtn = `<button id="btn-play-${game.id}" disabled class="pixel-btn bg-amber-500/20 border border-amber-500/50 text-amber-300 w-full py-2 px-3 text-xs flex items-center justify-center space-x-2 font-bold cursor-not-allowed animate-pulse shadow-[0_2px_8px_rgba(0,0,0,0.35)]">
                     <i data-lucide="gamepad-2" class="w-3.5 h-3.5"></i>
                     <span>Đang Chơi...</span>
                   </button>`;

      // Game lẻ (Non-Steam): [Chơi Ngay]
      if (game.is_custom_game) {
        const launchBtn = (pt && pt.is_running)
          ? runningBtn
          : `<button id="btn-play-${game.id}" onclick="event.stopPropagation(); launchGame('${game.id}')" class="pixel-btn btn-neon-green w-full py-2 px-3 text-xs flex items-center justify-center space-x-2 font-bold shadow-[0_2px_8px_rgba(0,0,0,0.35)]">
                       <i data-lucide="play" class="w-3.5 h-3.5 fill-black"></i>
                       <span>Chơi Ngay</span>
                     </button>`;
        return `<div class="w-full flex flex-col gap-1.5">${launchBtn}${vaultPendingButtonHtml(game)}</div>`;
      }

      if (pt && pt.is_running) return runningBtn;

      // Ghost Library: game từng có trong Hồ Sơ nhưng máy này chưa cài
      if (game.is_ghost) {
        return `<div class="w-full flex flex-col gap-1.5">
                     <button onclick="event.stopPropagation(); installGhostGame('${game.id}')" class="pixel-btn w-full py-2 px-3 text-xs flex items-center justify-center space-x-2 font-bold shadow-[0_2px_8px_rgba(0,0,0,0.35)] bg-[#061c24] border border-[#FF2A55]/60 text-[#FF2A55] hover:bg-[#082b36]">
                       <i data-lucide="download-cloud" class="w-3.5 h-3.5"></i>
                       <span>Cài Đặt</span>
                     </button>
                     <button onclick="event.stopPropagation(); openGameModal('${game.id}')" class="pixel-btn w-full py-1.5 px-2 text-[11px] flex items-center justify-center space-x-1.5 font-bold shadow-[0_2px_8px_rgba(0,0,0,0.35)] bg-[#1C2536] border border-white/15 text-slate-300 hover:text-white">
                       <i data-lucide="folder-search" class="w-3.5 h-3.5"></i>
                       <span>Chọn Thư Mục Cài Sẵn</span>
                     </button>
                   </div>`;
      }

      // Game đã lưu vào Thư viện nhưng chưa tải: [Tải Game] + [Trỏ đường dẫn có sẵn]
      if (game.library_state === 'bookmark') {
        return `<div class="w-full flex flex-col gap-1.5">
                     <button onclick="event.stopPropagation(); bookmarkOpenDownload('${game.id}')" class="pixel-btn btn-neon-green w-full py-2 px-3 text-xs flex items-center justify-center space-x-2 font-bold shadow-[0_2px_8px_rgba(0,0,0,0.35)]">
                       <i data-lucide="download" class="w-3.5 h-3.5 fill-black"></i>
                       <span>Tải Game</span>
                     </button>
                     <button onclick="event.stopPropagation(); bookmarkLinkExisting('${game.id}')" class="pixel-btn w-full py-1.5 px-2 text-[11px] flex items-center justify-center space-x-1.5 font-bold shadow-[0_2px_8px_rgba(0,0,0,0.35)] bg-[#061c24] border border-[#FF2A55]/50 text-[#FF2A55] hover:bg-[#082b36] transition-all">
                       <i data-lucide="folder-search" class="w-3.5 h-3.5"></i>
                       <span>Trỏ Đường Dẫn</span>
                     </button>
                   </div>`;
      }

      if (game.status_code === 'INSTALLED') {
        return `<div class="w-full flex flex-col gap-1.5">
                  <button id="btn-play-${game.id}" onclick="event.stopPropagation(); launchGame('${game.id}')" class="pixel-btn btn-neon-green w-full py-2 px-3 text-xs flex items-center justify-center space-x-2 font-bold shadow-[0_2px_8px_rgba(0,0,0,0.35)]">
                    <i data-lucide="play" class="w-3.5 h-3.5 fill-black"></i>
                    <span>Chơi Ngay</span>
                  </button>
                  ${vaultPendingButtonHtml(game)}
                </div>`;
      }
      if (game.status_code === 'UPDATE_DETECTED') {
        return `<div class="w-full flex flex-col gap-1.5">
                  <button onclick="event.stopPropagation(); toggleMod('${game.id}', true)" class="pixel-btn btn-arcade-amber w-full py-2 px-3 text-xs flex items-center justify-center space-x-2 font-bold shadow-[0_2px_8px_rgba(0,0,0,0.35)]">
                    <i data-lucide="refresh-cw" class="w-3.5 h-3.5 text-black stroke-[3]"></i>
                    <span>Cài Lại 1-Click</span>
                  </button>
                  ${vaultPendingButtonHtml(game)}
                </div>`;
      }
      if (game.status_code === 'GAME_MISSING') {
        return `<button onclick="event.stopPropagation(); openGameModal('${game.id}')" class="pixel-btn btn-neon-red w-full py-2 px-3 text-xs flex items-center justify-center space-x-2 font-bold shadow-[0_2px_8px_rgba(0,0,0,0.35)]">
                           <i data-lucide="folder-search" class="w-3.5 h-3.5 text-black"></i>
                           <span>Chọn Thư Mục</span>
                         </button>`;
      }
      return `<div class="w-full flex flex-col gap-1.5">
                <button onclick="event.stopPropagation(); toggleMod('${game.id}')" class="w-full py-2 px-3 text-xs flex items-center justify-center gap-2 bg-white/10 hover:bg-red-400 text-white hover:text-zinc-950 font-semibold rounded-full border border-white/15 hover:border-emerald-400 transition-colors duration-200">
                  <i data-lucide="download" class="w-3.5 h-3.5 text-current stroke-[2.5]"></i>
                  <span>Cài Việt Hóa</span>
                </button>
                ${vaultPendingButtonHtml(game)}
              </div>`;
    }

    function vaultPendingButtonHtml(game) {
      if (!game || !game.pending_vault_save) return '';
      return `<button onclick="event.stopPropagation(); restorePendingVaultSave('${game.id}')" class="pixel-btn w-full py-1.5 px-2 text-[11px] flex items-center justify-center space-x-1.5 font-bold shadow-[0_2px_8px_rgba(0,0,0,0.35)] bg-[#1c1405] border border-amber-500/60 text-amber-300 hover:bg-[#2a1e07] transition-all" title="Bung save đã lưu trong Hồ Sơ .congu_save về máy này">
                    <i data-lucide="archive-restore" class="w-3.5 h-3.5"></i>
                    <span>Khôi Phục Save</span>
                  </button>`;
    }

    function selectGameSpotlight(gameId) {
      heroGameId = gameId;
      renderHero();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    // Modal Details Functions & Tab Switcher
    function openGameModal(gameId) {
      const game = gamesList.find(g => g.id === gameId);
      if (!game) return;

      heroGameId = game.id;
      try {
        renderHero();
      } catch (errHero) {
        console.warn('renderHero error ignored:', errHero);
      }
      activeModalGameId = game.id;
      activeSidebarGameId = game.id;

      // Chuyển đổi View: Hiện trang chi tiết phủ kín bên phải, ẩn kho lưới (Steam Library Experience)
      const viewGrid = document.getElementById('viewBrowseGrid');
      const viewDetail = document.getElementById('viewGameDetail');
      const viewDiscovery = document.getElementById('viewDiscovery');
      const viewProfile = document.getElementById('viewProfile');
      const viewSearch = document.getElementById('viewSearchResults');
      if (viewGrid) viewGrid.classList.add('hidden');
      if (viewDetail) viewDetail.classList.remove('hidden');
      if (viewDiscovery) viewDiscovery.classList.add('hidden');
      if (viewProfile) viewProfile.classList.add('hidden');
      if (viewSearch) viewSearch.classList.add('hidden');

      const breadcrumbTitle = document.getElementById('detailBreadcrumbTitle');
      if (breadcrumbTitle) {
        breadcrumbTitle.textContent = `${game.vietnamese_title || game.title}`;
      }

      updateSidebarSelection(game.id);
      syncFavoriteDetailButton();

      const modalBannerImg = game.local_cover || (game.assets && game.assets.banner) || game.header_url || game.avatar_url || '';
      const bannerBg = document.getElementById('modalBannerBg');
      if (bannerBg) bannerBg.style.backgroundImage = `url('${modalBannerImg}')`;
      const modalTitleEl = document.getElementById('modalTitle');
      if (modalTitleEl) modalTitleEl.innerText = game.vietnamese_title || game.title || '';
      const origTitleEl = document.getElementById('modalOrigTitle');
      if (origTitleEl) origTitleEl.textContent = game.developer ? `${game.title} • ${game.developer}` : `${game.title || ''}`;
      const engineBadgeEl = document.getElementById('modalEngineBadge');
      if (engineBadgeEl) engineBadgeEl.innerText = game.engine || 'PC Game';
      const versionBadgeEl = document.getElementById('modalVersionBadge');
      if (versionBadgeEl) versionBadgeEl.innerText = game.latest_version || 'v1.0.0';
      const descEl = document.getElementById('modalDesc');
      if (descEl) descEl.innerText = game.description || 'Chưa có thông tin mô tả cho trò chơi này.';

      // Cloud Download URL (Internal Handled)
      const cloudInput = document.getElementById('modalCloudInput');
      if (cloudInput) cloudInput.value = game.download_url || '';

      // Important Note
      const noteContainer = document.getElementById('modalNoteContainer');
      const noteText = document.getElementById('modalNoteText');
      if (noteContainer) {
        if (game.important_note && noteText) {
          noteText.innerText = game.important_note;
          noteContainer.classList.remove('hidden');
        } else {
          noteContainer.classList.add('hidden');
        }
      }

      // Game Information (Thông tin game chuẩn Game Launcher)
      const infoDev = document.getElementById('modalInfoDev');
      const infoGenre = document.getElementById('modalInfoGenre');
      const infoEngine = document.getElementById('modalInfoEngine');
      const infoPlatform = document.getElementById('modalInfoPlatform');

      if (infoDev) infoDev.innerText = game.developer || 'Chưa rõ';
      if (infoGenre) infoGenre.innerText = game.genre || (game.genres && game.genres.join(', ')) || 'Hành động, Phiêu lưu';
      if (infoEngine) infoEngine.innerText = game.engine || 'PC Game';
      if (infoPlatform) {
        if (game.is_custom_game) {
          infoPlatform.innerText = game.steam_appid ? `Non-Steam (AppID: ${game.steam_appid})` : 'Non-Steam (Tự thêm)';
        } else {
          infoPlatform.innerText = game.steam_appid ? `Steam (AppID: ${game.steam_appid})` : 'PC Game';
        }
      }

      // Playtime Tracker UI update
      const pt = game.playtime || { is_running: false, formatted_time: 'Chưa chơi', last_played_str: 'Chưa từng mở', total_seconds: 0, sessions_count: 0 };
      const ptVal = document.getElementById('modalPlaytimeValue');
      const lpVal = document.getElementById('modalLastPlayedValue');
      const sessVal = document.getElementById('modalSessionsValue');
      const ptBtn = document.getElementById('modalPlayBtn');
      if (ptVal) ptVal.textContent = pt.formatted_time || 'Chưa chơi';
      if (lpVal) lpVal.textContent = pt.last_played_str || 'Chưa từng mở';
      if (sessVal) sessVal.textContent = `${pt.sessions_count || 0} phiên`;

      // Update Playtime Badge in Modal Header
      const headerPtBadge = document.getElementById('modalHeaderPlaytimeBadge');
      const headerPtText = document.getElementById('modalHeaderPlaytimeText');
      if (headerPtBadge && headerPtText) {
        if (pt.is_running) {
          headerPtBadge.className = 'font-pixel text-xs font-bold px-3 py-1 rounded-[2px] bg-amber-500/20 text-amber-300 border border-amber-400/60 shadow-[0_2px_8px_rgba(0,0,0,0.35)] tracking-wide flex items-center space-x-1.5 animate-pulse';
          headerPtText.innerText = 'Đang Chơi...';
        } else if (pt.total_seconds > 0) {
          headerPtBadge.className = 'font-pixel text-xs font-bold px-3 py-1 rounded-[2px] bg-[#0A0E1A]/90 text-red-400 border border-red-500/60 shadow-[0_2px_8px_rgba(0,0,0,0.35)] tracking-wide flex items-center space-x-1.5';
          headerPtText.innerText = `Giờ chơi: ${pt.formatted_time}`;
        } else {
          headerPtBadge.className = 'font-pixel text-xs font-bold px-3 py-1 rounded-[2px] bg-[#0A0E1A]/90 text-slate-400 border border-slate-700/60 shadow-[0_2px_8px_rgba(0,0,0,0.35)] tracking-wide flex items-center space-x-1.5';
          headerPtText.innerText = 'Chưa chơi';
        }
      }

      if (ptBtn) {
        if (!game.is_game_found) {
          ptBtn.disabled = true;
          ptBtn.className = "flex items-center justify-center gap-2 bg-slate-800 text-slate-500 font-bold px-4 py-2.5 rounded-xl text-xs cursor-not-allowed";
          ptBtn.innerHTML = `<i data-lucide="folder-x" class="w-4 h-4"></i><span>CHƯA CÓ GAME</span>`;
        } else if (pt.is_running) {
          ptBtn.disabled = true;
          ptBtn.className = "flex items-center justify-center gap-2 bg-amber-500/20 border border-amber-500/50 text-amber-300 font-bold px-5 py-2.5 rounded-xl text-sm cursor-not-allowed animate-pulse";
          ptBtn.innerHTML = `<i data-lucide="gamepad-2" class="w-4 h-4"></i><span>ĐANG CHƠI...</span>`;
          startPlaytimePolling(game.id);
        } else {
          ptBtn.disabled = false;
          ptBtn.className = "flex items-center justify-center gap-2 bg-[#FF2A55] hover:bg-[#FF6685] text-[#061418] font-bold px-5 py-2.5 rounded-xl text-sm shadow-lg shadow-black/30 transition-all shrink-0";
          ptBtn.innerHTML = `<i data-lucide="play" class="w-4 h-4 fill-current"></i><span>CHƠI NGAY</span>`;
        }
      }

      // Status Badge (Cyber-Pixel Style)
      const statusBadge = document.getElementById('modalStatusBadge');
      if (game.is_custom_game) {
        statusBadge.className = 'font-pixel text-xs font-bold px-3 py-1 rounded-[2px] bg-red-500/20 text-red-300 border border-red-500/70 shadow-[0_2px_8px_rgba(0,0,0,0.35)] tracking-wide';
        statusBadge.innerText = 'Game Tự Thêm (Non-Steam)';
      } else if (game.status_code === 'INSTALLED') {
        statusBadge.className = 'font-pixel text-xs font-bold px-3 py-1 rounded-[2px] bg-[#34D399]/15 text-[#34D399] border border-[#34D399]/70 shadow-[0_2px_8px_rgba(0,0,0,0.35)] tracking-wide';
        statusBadge.innerText = 'Đã Cài Đặt Việt Hóa';
      } else if (game.status_code === 'UPDATE_DETECTED') {
        statusBadge.className = 'font-pixel text-xs font-bold px-3 py-1 rounded-[2px] bg-amber-500/20 text-amber-300 border border-amber-400 shadow-[0_2px_8px_rgba(0,0,0,0.35)] tracking-wide';
        statusBadge.innerText = '⚠️ Game Vừa Cập Nhật - Mất Việt Hóa';
      } else if (game.status_code === 'GAME_MISSING') {
        statusBadge.className = 'font-pixel text-xs font-bold px-3 py-1 rounded-[2px] bg-[#FF2A55]/15 text-[#FF2A55] border border-[#FF2A55]/70 shadow-[0_2px_8px_rgba(0,0,0,0.35)] tracking-wide';
        statusBadge.innerText = 'Chưa Có Game Trên Máy';
      } else {
        statusBadge.className = 'font-pixel text-xs font-bold px-3 py-1 rounded-[2px] bg-[#FBBF24]/15 text-[#FBBF24] border border-[#FBBF24]/70 shadow-[0_2px_8px_rgba(0,0,0,0.35)] tracking-wide';
        statusBadge.innerText = 'Chưa Cài Đặt Mod';
      }

      // Path
      const pathInput = document.getElementById('modalPathInput');
      if (pathInput) pathInput.value = game.game_path || 'Chưa tìm thấy thư mục cài đặt game trên máy';

      // Early UAC Admin Warning Banner (Chỉ hiện khi đường dẫn thực sự nằm trong Program Files)
      const adminWarning = document.getElementById('modalAdminWarningBanner');
      const pathStatus = document.getElementById('modalPathStatus');
      const pathLower = (game.game_path || '').toLowerCase();
      const isInProgramFiles = pathLower.includes('program files') || pathLower.includes('program files (x86)');
      const needsAdmin = Boolean(game.requires_admin && isInProgramFiles);

      if (pathStatus) {
        if (game.is_game_found) {
          pathStatus.innerHTML = '<span class="text-[#34D399] font-medium flex items-center space-x-1"><i data-lucide="check-circle-2" class="w-3.5 h-3.5"></i><span>Thư mục hợp lệ</span></span>';
        } else {
          pathStatus.innerHTML = '<span class="text-[#F87171] font-medium flex items-center space-x-1"><i data-lucide="alert-triangle" class="w-3.5 h-3.5"></i><span>Chưa phát hiện</span></span>';
        }
      }

      if (adminWarning) {
        if (game.is_game_found && needsAdmin && !game.is_custom_game) {
          adminWarning.classList.remove('hidden');
        } else {
          adminWarning.classList.add('hidden');
        }
      }

      // Steam Update Health Warning Banner
      const updateWarning = document.getElementById('modalUpdateWarningBanner');
      if (updateWarning) {
        if (!game.is_custom_game && (game.status_code === 'UPDATE_DETECTED' || game.update_detected)) {
          updateWarning.classList.remove('hidden');
          const updateText = document.getElementById('modalUpdateWarningText');
          if (updateText && game.health_reason) {
            updateText.innerHTML = `${game.health_reason}. Bản dịch đã bị đè về tiếng Anh gốc. Bạn có thể bấm <strong>"Cài Lại 1-Click"</strong> bên dưới để khôi phục lại ngay lập tức từ bộ nhớ đệm Cache mà không cần tải lại!`;
          }
          const updateRestoreBtn = document.getElementById('modalUpdateRestoreBtn');
          if (updateRestoreBtn) {
            if (game.has_cached_congu) {
              updateRestoreBtn.classList.remove('hidden');
              updateRestoreBtn.classList.add('flex');
              updateRestoreBtn.disabled = false;
            } else {
              updateRestoreBtn.classList.add('hidden');
              updateRestoreBtn.classList.remove('flex');
            }
          }
        } else {
          updateWarning.classList.add('hidden');
          const updateRestoreBtnHidden = document.getElementById('modalUpdateRestoreBtn');
          if (updateRestoreBtnHidden) {
            updateRestoreBtnHidden.classList.add('hidden');
            updateRestoreBtnHidden.classList.remove('flex');
          }
        }
      }

      // Mod Info
      const modInfo = document.getElementById('modalModInfo');
      if (modInfo) {
        if (game.is_custom_game) {
          const appidText = game.steam_appid
            ? `Steam AppID: <span class="text-red-400 font-mono font-bold">${game.steam_appid}</span>`
            : `<span class="text-amber-400 italic">Chưa gắn Steam AppID</span>`;
          modInfo.innerHTML = `Định dạng: <span class="text-red-300 font-bold">Game Ngoài (Non-Steam)</span> • Engine: <span class="text-slate-300 font-mono">${game.engine || 'PC'}</span> • ${appidText} <button onclick="promptEditCustomGameAppId('${game.id}', '${game.steam_appid || ''}')" class="ml-2 text-xs text-red-400 hover:text-red-300 underline font-bold cursor-pointer">[🏷️ ${game.steam_appid ? 'Đổi AppID' : 'Gắn AppID'}]</button>`;
        } else if (game.status_code === 'INSTALLED') {
          modInfo.innerHTML = `Trạng thái: <span class="text-emerald-400 font-bold">Đang hoạt động trong game</span> • Cập nhật: ${game.translation_stats?.last_updated || 'Mới nhất'}`;
        } else {
          modInfo.innerHTML = `Nguồn: <span class="text-slate-300 font-mono">${game.mod_subfolder || 'Official'}</span>`;
        }
      }

      // Nút Gắn/Đổi Steam AppID trong thẻ Thành Tựu
      const achAppIdBtn = document.getElementById('btnCustomGameAppIdInAch');
      const achAppIdText = document.getElementById('btnCustomGameAppIdText');
      if (achAppIdBtn) {
        if (game.is_custom_game) {
          achAppIdBtn.classList.remove('hidden');
          if (achAppIdText) {
            achAppIdText.textContent = game.steam_appid ? `Đổi AppID (${game.steam_appid})` : '🏷️ Gắn Steam AppID';
          }
        } else {
          achAppIdBtn.classList.add('hidden');
        }
      }

      // Action Button in Modal (Arcade Micro-Switch Buttons)
      const emergencyBtn = document.getElementById('modalEmergencyRestoreBtn');
      if (emergencyBtn) {
        if (game.is_game_found && !game.is_custom_game) {
          emergencyBtn.classList.remove('hidden');
        } else {
          emergencyBtn.classList.add('hidden');
        }
      }

      const installBtn = document.getElementById('modalInstallBtn');
      const topInstallBtn = document.getElementById('modalTopInstallBtn');
      function syncInstallBtn(btn, isTop = false) {
        if (!btn) return;
        if (isTop) {
          // Nút trên cạnh CHƠI NGAY: chỉ hiện khi CHƯA cài đặt Việt hóa (Cài Đặt / Cập Nhật / Cài Lại)
          // Khi game đã cài đặt hoặc game tự thêm, ẩn hoàn toàn để CHƠI NGAY đứng độc tôn
          if (game.is_custom_game || game.status_code === 'INSTALLED') {
            btn.classList.add('hidden');
            return;
          }
          btn.classList.remove('hidden');
          if (game.status_code === 'UPDATE_DETECTED') {
            btn.className = 'pixel-btn btn-arcade-amber text-xs flex items-center justify-center space-x-2 font-bold px-4 py-2.5 rounded-[4px] transition shadow-lg shadow-amber-900/30 cursor-pointer';
            btn.innerHTML = `<i data-lucide="refresh-cw" class="w-4 h-4 text-black stroke-[3]"></i><span>Cài Lại 1-Click</span>`;
            btn.onclick = () => startInstall(game.id, true);
          } else {
            btn.className = 'pixel-btn btn-arcade-amber text-xs flex items-center justify-center space-x-2 font-bold px-4 py-2.5 rounded-[4px] transition shadow-lg shadow-amber-900/30 cursor-pointer';
            btn.innerHTML = `<i data-lucide="download" class="w-4 h-4 text-black stroke-[3]"></i><span>Cài Đặt Việt Hóa</span>`;
            btn.onclick = () => startInstall(game.id, false);
          }
        } else {
          btn.classList.add('hidden');
        }
      }
      syncInstallBtn(installBtn, false);
      syncInstallBtn(topInstallBtn, true);

      // Menu thả xuống ⚙ Quản Lý: hiện/ẩn các mục theo trạng thái game
      const itemDeleteCustom = document.getElementById('menuItemDeleteCustom');
      const itemUninstallMod = document.getElementById('menuItemUninstallMod');
      const itemEmergency = document.getElementById('menuItemEmergencyRestore');
      if (itemDeleteCustom) itemDeleteCustom.classList.toggle('hidden', !game.is_custom_game);
      if (itemUninstallMod) itemUninstallMod.classList.toggle('hidden', !(!game.is_custom_game && game.status_code === 'INSTALLED'));
      if (itemEmergency) itemEmergency.classList.toggle('hidden', !(game.is_game_found && !game.is_custom_game));
      closeDetailManageMenu();

      const launchBtn = document.getElementById('modalLaunchBtn');
      if (launchBtn) {
        if (!game.is_game_found) {
          launchBtn.classList.add('hidden');
        } else {
          launchBtn.classList.remove('hidden');
          if (pt.is_running) {
            launchBtn.disabled = true;
            launchBtn.className = 'pixel-btn modal-action-btn bg-amber-500/20 border border-amber-500/50 text-amber-300 text-xs font-bold cursor-not-allowed animate-pulse flex items-center justify-center space-x-1.5';
            launchBtn.innerHTML = `<i data-lucide="gamepad-2" class="w-4 h-4"></i><span>Đang Chơi...</span>`;
          } else if (game.is_custom_game) {
            launchBtn.disabled = false;
            launchBtn.className = 'pixel-btn modal-action-btn btn-neon-green text-xs font-bold transition flex items-center justify-center space-x-1.5 shadow-[0_2px_8px_rgba(0,0,0,0.35)]';
            launchBtn.innerHTML = `<i data-lucide="play" class="w-4 h-4 fill-black"></i><span>Chơi Ngay (Non-Steam)</span>`;
          } else if (game.status_code === 'INSTALLED') {
            launchBtn.disabled = false;
            launchBtn.className = 'pixel-btn modal-action-btn btn-neon-green text-xs font-bold transition flex items-center justify-center space-x-1.5 shadow-[0_2px_8px_rgba(0,0,0,0.35)]';
            launchBtn.innerHTML = `<i data-lucide="play" class="w-4 h-4 fill-black"></i><span>Chơi Ngay (Đã Việt Hóa)</span>`;
          } else {
            launchBtn.disabled = false;
            launchBtn.className = 'pixel-btn modal-action-btn bg-[#181a2f] text-slate-300 hover:text-white border border-[#2A3548] text-xs font-bold transition flex items-center justify-center space-x-1.5';
            launchBtn.innerHTML = `<i data-lucide="play" class="w-4 h-4"></i><span>Chơi Bản Gốc</span>`;
          }
        }
      }

      // Nút [Yêu Cầu Việt Hóa] chỉ hiện với game lẻ (Non-Steam)
      syncModalRequestLocButton();

      // Populate Versions Tab
      renderVersionsTab(game);

      // Populate Feedback Tab
      initRatingStars(game.user_rating || 5);
      document.getElementById('userCommentInput').value = game.user_comment || '';

      // Setup Media (Trailers & Cutscenes)
      const quickTrailerBtn = document.getElementById('modalQuickTrailerBtn');
      const mediaTabBtn = document.getElementById('tabBtn-media');
      const mediaBadge = document.getElementById('modalMediaCountBadge');
      const playlistContainer = document.getElementById('modalVideoPlaylist');

      const trailers = (game.media && game.media.trailers) ? game.media.trailers : [];
      if (trailers.length > 0) {
        if (quickTrailerBtn) quickTrailerBtn.classList.remove('hidden');
        if (mediaTabBtn) mediaTabBtn.classList.remove('hidden');
        if (mediaBadge) {
          mediaBadge.innerText = trailers.length;
          mediaBadge.classList.remove('hidden');
        }

        if (playlistContainer) {
          playlistContainer.innerHTML = trailers.map((item, idx) => `
            <div class="media-playlist-card pixel-panel p-2.5 bg-[#0F1522] border border-white/10 hover:border-[#FF2A55]/60 cursor-pointer flex items-center space-x-3 transition group rounded-[2px]"
                 data-clip-id="${item.id}"
                 onclick="playGameVideo('${item.youtube_id}', '${item.id}')">
              <div class="relative w-24 h-14 rounded-[2px] overflow-hidden bg-black shrink-0 border border-white/10">
                <img src="https://img.youtube.com/vi/${item.youtube_id}/mqdefault.jpg" class="w-full h-full object-cover group-hover:scale-105 transition duration-200" alt="" onerror="this.onerror=null;this.src='/static/icons/game_placeholder.png'" />
                <div class="absolute inset-0 bg-black/30 flex items-center justify-center group-hover:bg-black/10 transition">
                  <div class="w-6 h-6 rounded-full bg-[#FF2A55]/90 flex items-center justify-center shadow-[0_0_8px_#FF2A55]">
                    <i data-lucide="play" class="w-3 h-3 fill-black text-black ml-0.5"></i>
                  </div>
                </div>
              </div>
              <div class="min-w-0 flex-1">
                <span class="inline-block px-1.5 py-0.2 rounded text-[9px] font-pixel font-bold ${item.badge === 'CẮT CẢNH' ? 'bg-[#FF2A55]/20 text-[#FF2A55] border border-[#FF2A55]/40' : 'bg-[#FF2A55]/20 text-[#FF2A55] border border-[#FF2A55]/40'} mb-1">
                  ${item.badge || 'TRAILER'}
                </span>
                <h5 class="text-xs font-bold text-white group-hover:text-[#FF2A55] transition-colors truncate font-display">${item.title}</h5>
                <span class="text-[10px] text-slate-400 font-mono flex items-center gap-1 mt-0.5">
                  <i data-lucide="clock" class="w-2.5 h-2.5"></i> ${item.duration || 'Full HD'}
                </span>
              </div>
            </div>
          `).join('');
        }
      } else {
        if (quickTrailerBtn) quickTrailerBtn.classList.add('hidden');
        if (mediaTabBtn) mediaTabBtn.classList.add('hidden');
        if (mediaBadge) mediaBadge.classList.add('hidden');
        if (playlistContainer) playlistContainer.innerHTML = '<div class="col-span-2 py-8 text-center text-xs text-slate-300 font-sans">Chưa có video trailer cho tựa game này.</div>';
      }

      switchModalTab('overview');
      const gameModalEl = document.getElementById('gameModal');
      if (gameModalEl) gameModalEl.classList.remove('hidden');
      try {
        if (typeof loadGameAchievements === 'function') {
          loadGameAchievements(game.id);
        }
      } catch (errAch) {
        console.warn('loadGameAchievements error:', errAch);
      }
      try {
        if (typeof updateGamepadBadge === 'function') updateGamepadBadge(game.id);
      } catch (e) {}
      try {
        if (typeof preloadGameRepacksBadge === 'function') preloadGameRepacksBadge(game.id);
      } catch (e) {}

      // Cập nhật cảnh báo nếu chưa cài đặt game trên máy
      const missingDownloadAlert = document.getElementById('modalMissingGameDownloadAlert');
      if (missingDownloadAlert) {
        if (!game.is_game_found) {
          missingDownloadAlert.classList.remove('hidden');
        } else {
          missingDownloadAlert.classList.add('hidden');
        }
      }

      // Cuộn lên đầu view bên phải ngay lập tức
      const mainScroll = document.getElementById('mainScrollContainer');
      if (mainScroll) {
        mainScroll.scrollTo({ top: 0, behavior: 'instant' });
      }

      lucide.createIcons();
    }

    function closeGameModal() {
      switchToGridView();
    }

    // Cài / cập nhật Việt hóa (dùng chung luồng toggleMod)
    function startInstall(gameId, force = false) {
      return toggleMod(gameId, force);
    }
    // Gỡ Việt hóa có hỏi xác nhận
    function confirmUninstall(gameId) {
      const g = gamesList.find(x => x.id === gameId);
      const name = g ? (g.vietnamese_title || g.title) : 'game này';
      if (!confirm(`Gỡ bỏ Việt hóa của "${name}" và khôi phục bản gốc?`)) return;
      return toggleMod(gameId, false);
    }
    window.startInstall = startInstall;
    window.confirmUninstall = confirmUninstall;

    // Menu thả xuống ⚙ Quản Lý ở trang chi tiết game
    function closeDetailManageMenu() {
      const menu = document.getElementById('detailManageMenu');
      if (menu) menu.classList.add('hidden');
    }
    function toggleDetailManageMenu(event) {
      if (event) event.stopPropagation();
      const menu = document.getElementById('detailManageMenu');
      if (!menu) return;
      menu.classList.toggle('hidden');
      if (window.lucide) lucide.createIcons();
    }
    window.closeDetailManageMenu = closeDetailManageMenu;
    window.toggleDetailManageMenu = toggleDetailManageMenu;
    document.addEventListener('click', (e) => {
      const box = document.getElementById('detailManageDropdownContainer');
      if (box && !box.contains(e.target)) closeDetailManageMenu();
    });

    let currentActiveVideoId = null;
    let currentActiveYoutubeId = null;

    function openExternalUrl(url) {
      if (!url) return;
      fetch('/api/open_url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url })
      }).catch(() => {
        window.open(url, '_blank');
      });
    }

    function switchModalTab(tabName) {
      ['overview', 'media', 'versions', 'feedback', 'cloudsave', 'gamepad', 'repacks'].forEach(t => {
        const btn = document.getElementById(`tabBtn-${t}`);
        const content = document.getElementById(`tabContent-${t}`);
        if (!btn || !content) return;

        if (t === tabName) {
          btn.className = 'py-3 px-4 text-[#FF2A55] border-b-2 border-[#FF2A55] flex items-center space-x-1.5 transition font-bold font-display tracking-wide text-xs shrink-0';
          content.classList.remove('hidden');
        } else {
          btn.className = 'py-3 px-4 text-slate-400 hover:text-white border-b-2 border-transparent flex items-center space-x-1.5 transition font-bold font-display tracking-wide text-xs shrink-0';
          content.classList.add('hidden');
        }
      });

      if (tabName === 'cloudsave' && activeModalGameId) {
        loadCloudSaveTab(activeModalGameId);
      }

      if (tabName === 'gamepad' && activeModalGameId) {
        loadGamepadTab(activeModalGameId);
      }

      if (tabName === 'repacks' && activeModalGameId) {
        loadGameRepacksTab(activeModalGameId);
      }

      // Handle video playback
      const player = document.getElementById('modalVideoPlayer');
      if (player) {
        if (tabName === 'media') {
          // If no video playing, play the first available clip
          if (!player.src || player.src.includes('about:blank') || !currentActiveVideoId) {
            const game = gamesList.find(g => g.id === activeModalGameId);
            if (game && game.media && game.media.trailers && game.media.trailers.length > 0) {
              playGameVideo(game.media.trailers[0].youtube_id, game.media.trailers[0].id);
            }
          }
        } else {
          // Pause / clear iframe when leaving media tab to stop background sound
          player.src = '';
          currentActiveVideoId = null;
          currentActiveYoutubeId = null;
        }
      }

      lucide.createIcons();
    }

    function playGameVideo(youtubeId, clipId) {
      currentActiveVideoId = clipId;
      currentActiveYoutubeId = youtubeId;
      const player = document.getElementById('modalVideoPlayer');
      if (player) {
        player.src = `https://www.youtube.com/embed/${youtubeId}?autoplay=1&rel=0`;
      }

      // Update active highlight on playlist cards
      const cards = document.querySelectorAll('.media-playlist-card');
      cards.forEach(c => {
        if (c.getAttribute('data-clip-id') === clipId) {
          c.classList.add('border-[#FF2A55]', 'bg-[#FF2A55]/20', 'shadow-[0_0_15px_rgba(255, 42, 85,0.25)]');
          c.classList.remove('border-white/10', 'bg-[#0F1522]');
        } else {
          c.classList.remove('border-[#FF2A55]', 'bg-[#FF2A55]/20', 'shadow-[0_0_15px_rgba(255, 42, 85,0.25)]');
          c.classList.add('border-white/10', 'bg-[#0F1522]');
        }
      });
      if (window.lucide) lucide.createIcons();
    }

    function renderVersionsTab(game) {
      const container = document.getElementById('modalVersionsList');
      container.innerHTML = '';
      const versions = game.versions || [];

      if (versions.length === 0) {
        container.innerHTML = '<p class="text-xs text-slate-400">Chưa có thông tin phiên bản mở rộng.</p>';
        return;
      }

      versions.forEach((v, idx) => {
        const vCard = document.createElement('div');
        vCard.className = 'p-3.5 rounded-[6px] bg-white/[0.03] hover:bg-white/[0.05] transition-colors space-y-1.5';
        vCard.innerHTML = `
          <div class="flex items-center justify-between">
            <div class="flex items-center space-x-2">
              <span class="font-mono text-[11px] font-bold px-2 py-0.5 rounded-[4px] ${idx === 0 ? 'bg-[#FF2A55]/15 text-[#FF2A55] border border-[#FF2A55]/30' : 'bg-white/[0.05] text-slate-300'}">${v.version}</span>
              ${idx === 0 ? '<span class="text-[10px] font-bold text-brand-400">Mới nhất</span>' : ''}
            </div>
            <span class="text-[11px] text-slate-400 font-mono">${v.release_date}</span>
          </div>
          <p class="text-xs text-slate-300 leading-relaxed font-sans">${v.changelog}</p>
        `;
        container.appendChild(vCard);
      });
    }

    // Rating Star Component
    function initRatingStars(stars) {
      selectedRating = stars;
      const container = document.getElementById('starRatingContainer');
      container.innerHTML = '';
      for (let i = 1; i <= 5; i++) {
        const star = document.createElement('i');
        star.setAttribute('data-lucide', 'star');
        star.className = `w-5 h-5 cursor-pointer ${i <= stars ? 'text-amber-400 fill-amber-400' : 'text-slate-600'} transition hover:scale-110`;
        star.onclick = () => {
          initRatingStars(i);
        };
        container.appendChild(star);
      }
      const labels = ['', '1/5 Cần cải thiện', '2/5 Tạm được', '3/5 Khá tốt', '4/5 Rất tốt', '5/5 Tuyệt vời hoàn hảo'];
      document.getElementById('starRatingLabel').innerText = labels[stars] || `${stars}/5`;
      lucide.createIcons();
    }

    let activeProgressGameId = null;
    let currentProgressOp = 'install';

    function onProgressLaunchGame() {
      const gId = activeProgressGameId;
      closeProgressModal();
      if (gId) {
        launchGame(gId);
      }
    }

    // Modern Progress Modal
    function showProgressModal(title, subTitle, gameId = null, op = 'install') {
      activeProgressGameId = gameId;
      currentProgressOp = op;
      document.getElementById('progressTitle').innerText = title;
      document.getElementById('progressSubTitle').innerText = subTitle;
      document.getElementById('progressBarFill').style.width = '10%';
      document.getElementById('progressPercentText').innerText = '10%';
      document.getElementById('progressStepText').innerText = 'Đang khởi chạy...';
      document.getElementById('progressCloseBtn').classList.add('hidden');
      const launchBtn = document.getElementById('progressLaunchBtn');
      if (launchBtn) launchBtn.classList.add('hidden');
      document.getElementById('progressIcon').setAttribute('data-lucide', 'loader-2');
      document.getElementById('progressIcon').classList.add('animate-spin');
      document.getElementById('progressModal').classList.remove('hidden');
      lucide.createIcons();

      // Poll progress API
      if (progressInterval) clearInterval(progressInterval);
      progressInterval = setInterval(async () => {
        try {
          let p;
          if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.get_progress === 'function') {
            p = await window.pywebview.api.get_progress();
          } else {
            const res = await fetch('/api/progress');
            p = await res.json();
          }
          if (p && p.percent !== undefined) {
            document.getElementById('progressBarFill').style.width = `${p.percent}%`;
            document.getElementById('progressPercentText').innerText = `${p.percent}%`;
          }
          if (p && p.message) {
            document.getElementById('progressStepText').innerText = p.message;
          }
          if (p && (p.status === 'success' || p.status === 'error' || p.percent >= 100)) {
            clearInterval(progressInterval);
            document.getElementById('progressIcon').classList.remove('animate-spin');
            if (p.status === 'success') {
              document.getElementById('progressIcon').setAttribute('data-lucide', 'check-circle-2');
              document.getElementById('progressIcon').className = 'w-5 h-5 text-emerald-400';
              if (currentProgressOp === 'install' && activeProgressGameId) {
                const launchBtn = document.getElementById('progressLaunchBtn');
                if (launchBtn) launchBtn.classList.remove('hidden');
              }
            } else {
              document.getElementById('progressIcon').setAttribute('data-lucide', 'alert-triangle');
              document.getElementById('progressIcon').className = 'w-5 h-5 text-rose-400';
            }
            document.getElementById('progressCloseBtn').classList.remove('hidden');
            lucide.createIcons();
          }
        } catch (e) {}
      }, 350);
    }

    function closeProgressModal() {
      document.getElementById('progressModal').classList.add('hidden');
      if (progressInterval) clearInterval(progressInterval);
    }


    const activePlaytimeTimers = {};

    function setGamePlayingState(gameId, isPlaying) {
      const game = gamesList.find(g => g.id === gameId);
      if (game) {
        if (!game.playtime) game.playtime = {};
        game.playtime.is_running = isPlaying;
        if (isPlaying) {
          game.playtime.last_played_str = 'Đang chơi';
        }
      }

      // 1. Nút trong Playtime Widget của Modal
      const modalPlayBtn = document.getElementById('modalPlayBtn');
      if (modalPlayBtn && activeModalGameId === gameId) {
        if (isPlaying) {
          modalPlayBtn.disabled = true;
          modalPlayBtn.className = "flex items-center justify-center gap-2 bg-amber-500/20 border border-amber-500/50 text-amber-300 font-bold px-5 py-2.5 rounded-xl text-sm cursor-not-allowed animate-pulse";
          modalPlayBtn.innerHTML = `<i data-lucide="gamepad-2" class="w-4 h-4"></i><span>ĐANG CHƠI...</span>`;
        } else {
          modalPlayBtn.disabled = false;
          modalPlayBtn.className = "flex items-center justify-center gap-2 bg-[#FF2A55] hover:bg-[#FF6685] text-[#061418] font-bold px-5 py-2.5 rounded-xl text-sm shadow-lg shadow-black/30 transition-all shrink-0";
          modalPlayBtn.innerHTML = `<i data-lucide="play" class="w-4 h-4 fill-current"></i><span>CHƠI NGAY</span>`;
        }
      }

      // 2. Nút Modal Footer
      const modalLaunchBtn = document.getElementById('modalLaunchBtn');
      if (modalLaunchBtn && activeModalGameId === gameId) {
        if (isPlaying) {
          modalLaunchBtn.disabled = true;
          modalLaunchBtn.className = "pixel-btn modal-action-btn bg-amber-500/20 border border-amber-500/50 text-amber-300 text-xs font-bold cursor-not-allowed animate-pulse flex items-center justify-center space-x-1.5";
          modalLaunchBtn.innerHTML = `<i data-lucide="gamepad-2" class="w-4 h-4"></i><span>Đang Chơi...</span>`;
        } else {
          modalLaunchBtn.disabled = false;
          modalLaunchBtn.className = "pixel-btn modal-action-btn btn-neon-green text-xs font-bold transition flex items-center justify-center space-x-1.5 shadow-[0_2px_8px_rgba(0,0,0,0.35)]";
          modalLaunchBtn.innerHTML = `<i data-lucide="play" class="w-4 h-4 fill-black"></i><span>Chơi Ngay (Đã Việt Hóa)</span>`;
        }
      }

      // 3. Nút trên Card
      const cardBtn = document.getElementById(`btn-play-${gameId}`);
      if (cardBtn) {
        if (isPlaying) {
          cardBtn.disabled = true;
          cardBtn.className = "pixel-btn bg-amber-500/20 border border-amber-500/50 text-amber-300 w-full py-2 px-3 text-xs flex items-center justify-center space-x-2 font-bold cursor-not-allowed animate-pulse shadow-[0_2px_8px_rgba(0,0,0,0.35)]";
          cardBtn.innerHTML = `<i data-lucide="gamepad-2" class="w-3.5 h-3.5"></i><span>ĐANG CHƠI...</span>`;
        } else {
          cardBtn.disabled = false;
          cardBtn.className = "pixel-btn btn-neon-green w-full py-2 px-3 text-xs flex items-center justify-center space-x-2 font-bold shadow-[0_2px_8px_rgba(0,0,0,0.35)]";
          cardBtn.innerHTML = `<i data-lucide="play" class="w-3.5 h-3.5 fill-black"></i><span>Chơi Ngay</span>`;
        }
      }

      // 4. Hero Action Button
      if (heroGameId === gameId) {
        const heroBtn = document.getElementById('heroActionBtn');
        if (heroBtn) {
          if (isPlaying) {
            heroBtn.disabled = true;
            heroBtn.className = "pixel-btn bg-amber-500/20 border border-amber-500/50 text-amber-300 px-6 py-2.5 text-sm flex items-center space-x-2 font-bold cursor-not-allowed animate-pulse";
            heroBtn.innerHTML = `<i data-lucide="gamepad-2" class="w-4 h-4"></i><span>ĐANG CHƠI...</span>`;
          } else {
            heroBtn.disabled = false;
            heroBtn.className = "pixel-btn btn-neon-green px-6 py-2.5 text-sm flex items-center space-x-2";
            heroBtn.innerHTML = `<i data-lucide="play" class="w-4 h-4 fill-black"></i><span>Chơi Ngay (Launch)</span>`;
          }
        }
      }

      // 5. Cập nhật Badge & Subtitle trên Card
      const cardPtBadge = document.getElementById(`card-playtime-${gameId}`);
      if (cardPtBadge) {
        if (isPlaying) {
          cardPtBadge.className = 'font-pixel text-[10px] font-bold px-2 py-0.5 rounded-[4px] bg-amber-500/20 text-amber-300 border border-amber-400/60 flex items-center space-x-1 tracking-wide animate-pulse';
          cardPtBadge.innerHTML = `<i data-lucide="gamepad-2" class="w-3 h-3 text-amber-300"></i><span>ĐANG CHƠI</span>`;
        }
      }
      const cardPtSub = document.getElementById(`card-playtime-text-${gameId}`);
      if (cardPtSub && isPlaying) {
        cardPtSub.textContent = 'Đang chơi...';
      }

      if (window.lucide) lucide.createIcons();
    }

    function startPlaytimePolling(gameId) {
      if (activePlaytimeTimers[gameId]) {
        clearInterval(activePlaytimeTimers[gameId]);
      }

      activePlaytimeTimers[gameId] = setInterval(async () => {
        try {
          let stats;
          if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.get_playtime_stats === 'function') {
            stats = await window.pywebview.api.get_playtime_stats(gameId);
          } else {
            const resp = await fetch(`/api/playtime/${encodeURIComponent(gameId)}`);
            stats = await resp.json();
          }

          if (stats) {
            const game = gamesList.find(g => g.id === gameId);
            if (game) {
              game.playtime = stats;
            }

            // Cập nhật giá trị hiển thị trên Modal nếu đang mở đúng game này
            if (activeModalGameId === gameId) {
              const ptVal = document.getElementById('modalPlaytimeValue');
              const lpVal = document.getElementById('modalLastPlayedValue');
              const headerPtBadge = document.getElementById('modalHeaderPlaytimeBadge');
              const headerPtText = document.getElementById('modalHeaderPlaytimeText');
              if (ptVal) ptVal.textContent = stats.formatted_time || 'Chưa chơi';
              if (lpVal) lpVal.textContent = stats.last_played_str || 'Chưa từng mở';
              if (headerPtText) {
                headerPtText.textContent = stats.is_running ? 'Đang Chơi...' : (stats.formatted_time ? `Giờ chơi: ${stats.formatted_time}` : 'Chưa chơi');
              }
              if (headerPtBadge) {
                if (stats.is_running) {
                  headerPtBadge.className = 'font-pixel text-xs font-bold px-3 py-1 rounded-[2px] bg-amber-500/20 text-amber-300 border border-amber-400/60 shadow-[0_2px_8px_rgba(0,0,0,0.35)] tracking-wide flex items-center space-x-1.5 animate-pulse';
                } else {
                  headerPtBadge.className = 'font-pixel text-xs font-bold px-3 py-1 rounded-[2px] bg-[#0A0E1A]/90 text-red-400 border border-red-500/60 shadow-[0_2px_8px_rgba(0,0,0,0.35)] tracking-wide flex items-center space-x-1.5';
                }
              }
            }

            // Cập nhật giá trị trên Hero nếu đang chọn game này
            if (heroGameId === gameId) {
              const heroPtText = document.getElementById('heroPlaytimeText');
              if (heroPtText) heroPtText.textContent = stats.is_running ? 'Đang chơi...' : (stats.formatted_time ? `Giờ chơi: ${stats.formatted_time} • Lần cuối: ${stats.last_played_str}` : 'Thời gian chơi: Chưa chơi');
            }

            // Cập nhật Badge trên Card
            const cardPtBadge = document.getElementById(`card-playtime-${gameId}`);
            if (cardPtBadge) {
              if (stats.is_running) {
                cardPtBadge.className = 'font-pixel text-[10px] font-bold px-2 py-0.5 rounded-[4px] bg-amber-500/20 text-amber-300 border border-amber-400/60 flex items-center space-x-1 tracking-wide animate-pulse';
                cardPtBadge.innerHTML = `<i data-lucide="gamepad-2" class="w-3 h-3 text-amber-300"></i><span>ĐANG CHƠI</span>`;
              } else if (stats.total_seconds > 0) {
                cardPtBadge.className = 'font-pixel text-[10px] font-bold px-2 py-0.5 rounded-[4px] bg-[#0A0E1A]/80 text-red-400 border border-red-500/30 flex items-center space-x-1 tracking-wide shadow-[0_2px_8px_rgba(0,0,0,0.5)]';
                cardPtBadge.innerHTML = `<i data-lucide="clock" class="w-2.5 h-2.5 text-red-400"></i><span>${stats.formatted_time}</span>`;
                cardPtBadge.title = `Thời gian chơi: ${stats.formatted_time} • Lần cuối: ${stats.last_played_str}`;
              } else {
                cardPtBadge.className = 'font-pixel text-[10px] font-bold px-2 py-0.5 rounded-[4px] bg-[#0A0E1A]/80 text-slate-400 border border-slate-700/50 flex items-center space-x-1 tracking-wide shadow-[0_2px_8px_rgba(0,0,0,0.5)]';
                cardPtBadge.innerHTML = `<i data-lucide="clock" class="w-2.5 h-2.5 text-slate-500"></i><span>Chưa chơi</span>`;
                cardPtBadge.title = `Thời gian chơi: Chưa chơi`;
              }
            }

            // Cập nhật Subtitle trên Card (chỉ đổi phần giờ chơi, giữ nguyên "Thể loại •")
            const cardPtSub = document.getElementById(`card-playtime-text-${gameId}`);
            if (cardPtSub) {
              cardPtSub.textContent = stats.is_running
                ? 'Đang chơi...'
                : (stats.total_seconds > 0 ? stats.formatted_time : 'Chưa chơi');
            }

            if (window.lucide) lucide.createIcons();

            // Nếu game đã tắt
            if (!stats.is_running) {
              clearInterval(activePlaytimeTimers[gameId]);
              delete activePlaytimeTimers[gameId];
              setGamePlayingState(gameId, false);
              showToast(`Phiên chơi đã kết thúc! Tổng thời gian chơi: ${stats.formatted_time}`, 'info');
              renderCounts();
              renderGrid();
              renderHero();
            }
          }
        } catch (e) {
          console.warn('[Playtime Polling Error]', e);
        }
      }, 3000);
    }

    // ========================================================
    // HYDRA ACHIEVEMENTS TRACKER & REALTIME TOAST SYSTEM
    // ========================================================
    function escapeHtml(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }

    let achAudioCtx = null;
    function playAchievementSound() {
      try {
        if (window.currentSettings && window.currentSettings.general && window.currentSettings.general.achievement_sound === false) {
          return;
        }
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext) return;
        if (!achAudioCtx) achAudioCtx = new AudioContext();
        if (achAudioCtx.state === 'suspended') achAudioCtx.resume();

        const now = achAudioCtx.currentTime;
        // Âm thanh TING! pha lê (G5 thân ấm + G6 chủ đạo + D7 quãng 5 + G7 lấp lánh)
        const partials = [
          { freq: 783.99, amp: 0.14, delay: 0.0, dur: 0.45 },
          { freq: 1567.98, amp: 0.36, delay: 0.0, dur: 1.05 },
          { freq: 2349.32, amp: 0.18, delay: 0.0, dur: 0.90 },
          { freq: 3135.96, amp: 0.22, delay: 0.008, dur: 0.78 },
          { freq: 4703.94, amp: 0.06, delay: 0.014, dur: 0.40 }
        ];

        partials.forEach(p => {
          const osc = achAudioCtx.createOscillator();
          const gain = achAudioCtx.createGain();
          osc.type = 'sine';
          osc.frequency.setValueAtTime(p.freq, now + p.delay);

          gain.gain.setValueAtTime(0.0001, now + p.delay);
          gain.gain.linearRampToValueAtTime(p.amp, now + p.delay + 0.004);
          gain.gain.exponentialRampToValueAtTime(0.0005, now + p.delay + p.dur);

          osc.connect(gain);
          gain.connect(achAudioCtx.destination);

          osc.start(now + p.delay);
          osc.stop(now + p.delay + p.dur + 0.05);
        });
      } catch (e) {
        console.warn('[Audio Chime Error]', e);
      }
    }

    let achToastTimeout = null;
    function showAchievementToast(ach) {
      if (!ach) return;
      if (!ach.overlay_played) {
        playAchievementSound();
      }

      const toast = document.getElementById('achievementToast');
      const icon = document.getElementById('toast-ach-icon');
      const placeholder = document.getElementById('toast-ach-placeholder');
      const title = document.getElementById('toast-ach-title');
      const desc = document.getElementById('toast-ach-desc');
      if (!toast) return;

      if (title) title.textContent = ach.title || ach.id || 'Thành Tựu Mới!';
      if (desc) desc.textContent = ach.description || 'Đã mở khóa trong quá trình chơi';

      if (ach.icon) {
        icon.src = ach.icon;
        icon.classList.remove('hidden');
        if (placeholder) placeholder.classList.add('hidden');
      } else {
        icon.classList.add('hidden');
        if (placeholder) placeholder.classList.remove('hidden');
      }

      toast.classList.remove('hidden');
      requestAnimationFrame(() => {
        toast.classList.remove('translate-y-12', 'opacity-0');
        toast.classList.add('translate-y-0', 'opacity-100');
      });

      if (window.lucide) lucide.createIcons();

      if (achToastTimeout) clearTimeout(achToastTimeout);
      achToastTimeout = setTimeout(() => {
        toast.classList.remove('translate-y-0', 'opacity-100');
        toast.classList.add('translate-y-12', 'opacity-0');
        setTimeout(() => toast.classList.add('hidden'), 500);
      }, 5500);
    }

    let currentAchievementsData = null;
    let currentAchievementFilter = 'all';
    window.currentAchievementsData = currentAchievementsData;
    window.currentAchievementFilter = currentAchievementFilter;

    function filterAchievementsUI(filter) {
      currentAchievementFilter = filter;
      window.currentAchievementFilter = filter;
      ['all', 'unlocked', 'locked'].forEach(f => {
        const btn = document.getElementById(`ach-filter-${f}`);
        if (!btn) return;
        if (f === filter) {
          btn.className = 'px-2.5 py-1 rounded bg-slate-800 text-white font-bold shadow-sm transition';
        } else {
          btn.className = 'px-2.5 py-1 rounded bg-transparent text-slate-400 font-medium hover:text-white transition';
        }
      });
      renderAchievementsList();
    }
    window.filterAchievementsUI = filterAchievementsUI;

    function revealSpoiler(achId) {
      const real = document.getElementById(`desc-real-${achId}`);
      const placeholder = document.getElementById(`desc-placeholder-${achId}`);
      const btn = document.getElementById(`btn-reveal-${achId}`);
      const title = document.getElementById(`title-${achId}`);
      if (real) real.classList.remove('hidden');
      if (placeholder) placeholder.classList.add('hidden');
      if (btn) btn.classList.add('hidden');
      if (title && title.dataset.origTitle) title.textContent = title.dataset.origTitle;
    }
    window.revealSpoiler = revealSpoiler;

    function renderAchievementsList() {
      const listEl = document.getElementById('ach-list-container');
      const data = window.currentAchievementsData || currentAchievementsData;
      if (!listEl || !data) return;

      const items = data.achievements || [];
      const unlockedList = items.filter(a => a.unlocked);
      const lockedList = items.filter(a => !a.unlocked);

      let displayedItems = [];
      if (currentAchievementFilter === 'unlocked') {
        displayedItems = unlockedList;
      } else if (currentAchievementFilter === 'locked') {
        displayedItems = lockedList;
      } else {
        displayedItems = items;
      }

      if (displayedItems.length === 0) {
        listEl.innerHTML = '<div class="py-6 text-center text-xs text-slate-500 italic">Không có thành tựu nào trong danh mục này.</div>';
        return;
      }

      const renderCard = (ach) => {
        const isUnlocked = Boolean(ach.unlocked);
        let iconSrc = ach.icon || '';
        if (iconSrc && !iconSrc.startsWith('http') && !iconSrc.startsWith('/') && !iconSrc.startsWith('data:') && data.appid) {
          iconSrc = `https://shared.akamai.steamstatic.com/community_assets/images/apps/${data.appid}/${iconSrc}`;
        }
        const isHiddenLocked = Boolean(ach.hidden && !isUnlocked);
        const percentStr = (ach.global_percent !== null && ach.global_percent !== undefined)
          ? `${ach.global_percent}% người chơi có thành tựu này`
          : '';

        return `
          <div class="flex items-start gap-3 p-3 rounded-xl border transition-all ${isUnlocked ? 'bg-slate-950/80 border-amber-500/30 hover:border-amber-400/50 shadow-md shadow-black/40' : 'bg-slate-950/40 border-slate-800/80 opacity-80 hover:opacity-100'}">
            <!-- Icon -->
            <div class="relative w-12 h-12 rounded-lg bg-slate-900 flex-shrink-0 overflow-hidden flex items-center justify-center border ${isUnlocked ? 'border-amber-400/50 shadow-[0_0_8px_rgba(251,191,36,0.15)]' : 'border-slate-800'}">
              ${iconSrc
                ? `<img src="${iconSrc}" class="w-full h-full object-cover ${isUnlocked ? '' : 'grayscale contrast-75 brightness-75'}" onerror="this.onerror=null;this.classList.add('hidden');this.nextElementSibling.classList.remove('hidden');" /><i data-lucide="${isUnlocked ? 'trophy' : 'lock'}" class="w-5 h-5 hidden ${isUnlocked ? 'text-amber-400' : 'text-slate-600'}"></i>`
                : `<i data-lucide="${isUnlocked ? 'trophy' : 'lock'}" class="w-5 h-5 ${isUnlocked ? 'text-amber-400' : 'text-slate-600'}"></i>`
              }
            </div>

            <!-- Content -->
            <div class="flex-1 min-w-0">
              <div class="flex items-center justify-between gap-2">
                <h5 id="title-${ach.id}" data-orig-title="${escapeHtml(ach.title || ach.id)}" class="text-xs font-bold ${isUnlocked ? 'text-amber-300' : 'text-slate-200'} truncate">
                  ${isHiddenLocked ? 'Thành Tựu Ẩn' : escapeHtml(ach.title || ach.id)}
                </h5>
                ${isUnlocked
                  ? `<span class="text-[10px] font-mono text-emerald-400 font-semibold shrink-0">Đã mở: ${ach.unlock_time_str || 'Đã mở'}</span>`
                  : `<span class="text-[10px] font-mono text-slate-500 shrink-0">Chưa mở</span>`
                }
              </div>

              <!-- CÁCH THỰC HIỆN / HƯỚNG DẪN MỞ KHÓA -->
              <div class="mt-1">
                ${isHiddenLocked
                  ? `<div class="flex items-center gap-2">
                       <span id="desc-placeholder-${ach.id}" class="text-[11px] text-slate-500 italic">Thành tựu ẩn. Bấm để xem cách làm.</span>
                       <span id="desc-real-${ach.id}" class="text-[11px] text-slate-300 font-sans leading-relaxed hidden">${escapeHtml(ach.description || 'Hoàn thành thử thách đặc biệt trong game')}</span>
                       <button type="button" onclick="revealSpoiler('${ach.id}')" id="btn-reveal-${ach.id}" class="text-[10px] font-medium text-red-400 hover:text-red-300 underline underline-offset-2 shrink-0">👁️ Hiện cách làm</button>
                     </div>`
                  : `<p class="text-[11px] text-slate-300 font-sans leading-relaxed">${escapeHtml(ach.description || 'Hoàn thành thử thách đặc biệt trong game để mở khóa.')}</p>`
                }
              </div>

              <!-- TỶ LỆ TOÀN CẦU % -->
              ${percentStr
                ? `<div class="mt-1.5 flex items-center gap-1.5 text-[10px] text-slate-400">
                     <i data-lucide="users" class="w-3 h-3 text-red-400 shrink-0"></i>
                     <span><strong class="text-slate-300 font-mono">${ach.global_percent}%</strong> người chơi toàn cầu đã đạt được</span>
                   </div>`
                : ''
              }
            </div>
          </div>
        `;
      };

      if (currentAchievementFilter === 'all' && unlockedList.length > 0 && lockedList.length > 0) {
        listEl.innerHTML = `
          <div class="space-y-2">
            <div class="text-[11px] font-bold text-amber-400 flex items-center gap-1.5 px-1 pt-1 tracking-wider uppercase">
              <i data-lucide="check-circle-2" class="w-3.5 h-3.5 text-amber-400"></i>
              <span>Thành Tựu Đã Mở Khóa (${unlockedList.length})</span>
            </div>
            ${unlockedList.map(renderCard).join('')}
          </div>
          <div class="space-y-2 pt-3">
            <div class="text-[11px] font-bold text-slate-400 flex items-center gap-1.5 px-1 pt-1 tracking-wider uppercase">
              <i data-lucide="lock" class="w-3.5 h-3.5 text-slate-400"></i>
              <span>Thành Tựu Chưa Mở Khóa (${lockedList.length})</span>
            </div>
            ${lockedList.map(renderCard).join('')}
          </div>
        `;
      } else {
        listEl.innerHTML = displayedItems.map(renderCard).join('');
      }

      if (window.lucide) lucide.createIcons();
    }

    // Global Playtime & Running Status Heartbeat (Tự động nhận diện khi mở game ngoài Desktop / Steam)
    let globalPlaytimeSyncInterval = null;
    function startGlobalPlaytimeWatcher() {
      if (globalPlaytimeSyncInterval) return;
      globalPlaytimeSyncInterval = setInterval(async () => {
        try {
          let allStats = null;
          if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.get_all_playtime_stats === 'function') {
            allStats = await window.pywebview.api.get_all_playtime_stats();
          } else {
            const resp = await fetch('/api/playtime/stats');
            if (resp.ok) {
              allStats = await resp.json();
            }
          }
          if (!allStats || typeof allStats !== 'object') return;

          let anyChange = false;
          for (const [gid, stats] of Object.entries(allStats)) {
            const game = gamesList.find(g => g.id === gid);
            if (!game) continue;

            const prevRunning = Boolean(game.is_playing || (game.playtime && game.playtime.is_running));
            const currRunning = Boolean(stats.is_running);

            // Đồng bộ dữ liệu mới nhất vào game model
            game.playtime = stats;

            if (prevRunning !== currRunning) {
              anyChange = true;
              setGamePlayingState(gid, currRunning);
              if (currRunning) {
                startPlaytimePolling(gid);
              }
            } else if (currRunning) {
              // Cập nhật Live Time ngay lập tức trên Card
              const cardPtBadge = document.getElementById(`card-playtime-${gid}`);
              if (cardPtBadge) {
                cardPtBadge.className = 'font-pixel text-[10px] font-bold px-2 py-0.5 rounded-[4px] bg-amber-500/20 text-amber-300 border border-amber-400/60 flex items-center space-x-1 tracking-wide animate-pulse';
                cardPtBadge.innerHTML = `<i data-lucide="gamepad-2" class="w-3 h-3 text-amber-300"></i><span>ĐANG CHƠI</span>`;
              }
              const cardPtSub = document.getElementById(`card-playtime-text-${gid}`);
              if (cardPtSub) {
                cardPtSub.textContent = `Đang chơi (${stats.formatted_time})...`;
              }
            }
          }

          if (anyChange) {
            renderCounts();
            renderGrid();
            renderHero();
            if (window.lucide) lucide.createIcons();
          }

          // Polling thành tựu mới mở khóa trong thời gian thực (Cơ chế Hydra Launcher / Achievement Watcher)
          try {
            let newAchs = null;
            if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.poll_new_achievements === 'function') {
              newAchs = await window.pywebview.api.poll_new_achievements();
            } else {
              const achResp = await fetch('/api/achievements/poll_new');
              if (achResp.ok) {
                newAchs = await achResp.json();
              }
            }
            if (Array.isArray(newAchs) && newAchs.length > 0) {
              newAchs.forEach(ach => {
                showAchievementToast(ach);
              });
              if (activeModalGameId) {
                loadGameAchievements(activeModalGameId);
              }
            }
          } catch (achErr) {
            // Im lặng bỏ qua lỗi mạng
          }
        } catch (e) {
          // Im lặng bỏ qua lỗi mạng tạm thời
        }
      }, 4000);
    }

    // -------------------------------------------------------------
    // Game Card Context Menu & Custom Cover Picker (4 Lớp Avatar)
    // -------------------------------------------------------------
    let activeContextGameId = null;

    function openCardContextMenu(event, gameId) {
      if (event) {
        event.preventDefault();
        event.stopPropagation();
      }
      activeContextGameId = gameId;
      const menu = document.getElementById('cardContextMenu');
      if (!menu) return;

      const clickX = event.clientX;
      const clickY = event.clientY;
      const windowWidth = window.innerWidth;
      const windowHeight = window.innerHeight;

      // Hiện trước để đo kích thước thật (menu kính mờ bo tròn, min-w 230px, 4 mục)
      menu.classList.remove('hidden');
      const rect = menu.getBoundingClientRect();
      const menuWidth = rect.width || 230;
      const menuHeight = rect.height || 190;

      // Kẹp menu trong viewport, không để tràn ra mép phải/dưới
      const left = Math.max(10, Math.min(clickX, windowWidth - menuWidth - 10));
      const top = clickY + menuHeight > windowHeight
        ? Math.max(10, windowHeight - menuHeight - 10)
        : clickY;

      menu.style.left = `${left}px`;
      menu.style.top = `${top}px`;
      lucide.createIcons();
    }

    function closeCardContextMenu() {
      const menu = document.getElementById('cardContextMenu');
      if (menu) menu.classList.add('hidden');
      activeContextGameId = null;
    }

    window.addEventListener('click', () => closeCardContextMenu());
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeCardContextMenu();
    });

    function onContextChangeCover() {
      const gid = activeContextGameId;
      closeCardContextMenu();
      if (gid) {
        // Mở thẳng Avatar Picker (tìm ảnh online Steam/SteamGridDB + tải ảnh từ máy)
        // để "Đổi Ảnh Bìa" là điểm vào duy nhất, không cần mục "Tìm & Chọn lại game" riêng.
        const game = gamesList.find(g => g.id === gid);
        openAvatarPicker(gid, game ? (game.title || game.name || '') : '');
      }
    }

    function onContextOpenFolder() {
      const gid = activeContextGameId;
      closeCardContextMenu();
      if (gid) openGameFolder(gid);
    }

    function onContextOpenDetails() {
      const gid = activeContextGameId;
      closeCardContextMenu();
      if (gid) openGameModal(gid);
    }

    let currentEditingGameId = null;
    let cachedCandidates = [];
    let avatarSearchDebounceTimer = null;

    function openAvatarPicker(gameId, currentTitle) {
      if (!gameId) return;
      currentEditingGameId = gameId;
      const modal = document.getElementById('avatarPickerModal');
      const input = document.getElementById('avatarSearchInput');
      const grid = document.getElementById('avatarResultsGrid');
      if (!modal) return;

      modal.classList.remove('hidden');
      const initialQuery = currentTitle || (gamesList.find(g => g.id === gameId)?.title) || '';
      input.value = initialQuery;
      grid.innerHTML = '<div class="col-span-full text-center py-12 text-slate-300 text-xs font-sans">Đang nạp gợi ý tìm kiếm...</div>';
      input.focus();
      lucide.createIcons();

      if (initialQuery) {
        triggerAvatarSearch();
      }
    }

    function closeAvatarPicker() {
      const modal = document.getElementById('avatarPickerModal');
      if (modal) modal.classList.add('hidden');
      currentEditingGameId = null;
    }

    function onAvatarSearchInputDebounced(val) {
      clearTimeout(avatarSearchDebounceTimer);
      const query = (val || '').trim();
      if (!query || query.length < 2) return;
      avatarSearchDebounceTimer = setTimeout(() => {
        triggerAvatarSearch();
      }, 200);
    }

    function handleCandidateImgError(img, idx) {
      if (!img) return;
      const bg = document.getElementById(`cand-bg-${idx}`);
      const step = parseInt(img.dataset.step || '0', 10);
      const header = img.dataset.header;
      const capsule = img.dataset.capsule;

      if (step === 0 && header && header !== img.src) {
        img.dataset.step = '1';
        img.src = header;
        if (bg) bg.src = header;
        return;
      }
      if (step <= 1 && capsule && capsule !== img.src) {
        img.dataset.step = '2';
        img.src = capsule;
        if (bg) bg.src = capsule;
        return;
      }

      // Hide broken image and show styled fallback
      img.style.display = 'none';
      if (bg) bg.style.display = 'none';
      const parent = img.parentElement;
      if (parent && !parent.querySelector('.no-poster-box')) {
        const box = document.createElement('div');
        box.className = 'no-poster-box absolute inset-0 flex flex-col items-center justify-center p-3 text-center bg-[#0A0E1A] border border-[#FF2A55]/30';
        box.innerHTML = `
          <i data-lucide="image-off" class="w-7 h-7 text-slate-500 mb-1"></i>
          <span class="font-pixel text-[10px] text-[#FF2A55]">KHO CỔ NGỮ</span>
          <span class="text-[9px] text-slate-400 font-sans mt-0.5">Không có ảnh bìa dọc</span>
        `;
        parent.appendChild(box);
        if (window.lucide) lucide.createIcons();
      }
    }

    function triggerCustomCoverFromModal() {
      const gid = currentEditingGameId;
      closeAvatarPicker();
      if (gid) {
        changeGameCover(gid);
      }
    }

    // Tương thích ngược với các lời gọi cũ
    function openRemapModal(gameId) {
      const game = gamesList.find(g => g.id === gameId);
      openAvatarPicker(gameId, game ? (game.title || game.name || '') : '');
    }
    function closeRemapModal() {
      closeAvatarPicker();
    }
    window.openAvatarPicker = openAvatarPicker;
    window.closeAvatarPicker = closeAvatarPicker;
    window.triggerCustomCoverFromModal = triggerCustomCoverFromModal;
    window.openRemapModal = openRemapModal;
    window.closeRemapModal = closeRemapModal;

            // ==============================================================================
    // COMMUNITY LOCALIZATION WISHLIST & VOTING LOGIC
    // ==============================================================================
    let communityWishlistItems = [];
    let activeWishlistTab = 'top'; // 'top' | 'recent' | 'voted' | 'mine'
    let wishlistFilterQuery = '';
    let selectedGameRequest = null;
    let reqSearchDebounceTimer = null;
    let reqDropdownItems = [];
    let reqActiveIndex = -1;
    let steamGamesDb = null;

    // -------------------------------------------------------------------------
    // YÊU CẦU VIỆT HÓA GAME LẺ (lưu trong Hồ Sơ Di Động .congu_save)
    // -------------------------------------------------------------------------
    let myLocalizationRequests = [];   // Danh sách yêu cầu đọc từ profile_manifest.json
    let myLocRequestMap = {};          // Tra cứu nhanh theo steam_appid / game_id
    let locNewsNotifications = [];     // Thông báo "Tin vui! Game đã có bản Việt Hóa"

    function rebuildMyLocRequestMap() {
      myLocRequestMap = {};
      (myLocalizationRequests || []).forEach(it => {
        if (!it) return;
        if (it.request_key) myLocRequestMap[String(it.request_key)] = it;
        if (it.steam_appid) myLocRequestMap[String(it.steam_appid)] = it;
        if (it.game_id) myLocRequestMap[String(it.game_id)] = it;
      });
    }

    function getMyLocRequest(game) {
      if (!game) return null;
      const keys = [game.steam_appid, game.id, game.request_key]
        .filter(k => k !== undefined && k !== null && String(k).trim() !== '')
        .map(k => String(k));
      for (const k of keys) {
        if (myLocRequestMap[k]) return myLocRequestMap[k];
      }
      return null;
    }

    function locRequestStatusBadge(rec) {
      const st = (rec && rec.status) || 'pending';
      if (st === 'completed') {
        return `<span class="px-2 py-0.5 text-[9px] font-pixel text-[#34D399] bg-[#34D399]/15 border border-[#34D399]/40 rounded">Đã Hoàn Thành</span>`;
      }
      if (st === 'in_progress') {
        return `<span class="px-2 py-0.5 text-[9px] font-pixel text-[#FF2A55] bg-[#FF2A55]/15 border border-[#FF2A55]/40 rounded animate-pulse">Đang Dịch</span>`;
      }
      if (st === 'reviewing') {
        return `<span class="px-2 py-0.5 text-[9px] font-pixel text-amber-300 bg-amber-400/10 border border-amber-400/30 rounded">Tiếp Nhận</span>`;
      }
      if (st === 'rejected') {
        return `<span class="px-2 py-0.5 text-[9px] font-pixel text-rose-300 bg-rose-500/10 border border-rose-500/30 rounded">Đã Từ Chối</span>`;
      }
      return `<span class="px-2 py-0.5 text-[9px] font-pixel text-[#FF2A55] bg-[#FF2A55]/10 border border-[#FF2A55]/30 rounded">Đang Chờ Duyệt</span>`;
    }

    // Xử lý khi bấm nút [Yêu Cầu Việt Hóa] trên thẻ game lẻ
    async function onCustomGameRequestLoc(gameId) {
      const game = (typeof gamesList !== 'undefined' ? gamesList : []).find(g => String(g.id) === String(gameId));
      const rec = getMyLocRequest(game);
      if (rec) {
        openMyRequestsTab();
        return;
      }
      if (typeof requestCustomGameLocalization === 'function') {
        await requestCustomGameLocalization(gameId);
      }
    }

    function onModalRequestLocClick() {
      if (!activeModalGameId) return;
      return onCustomGameRequestLoc(activeModalGameId);
    }

    // Cập nhật nút [Yêu Cầu Việt Hóa] trong modal chi tiết theo trạng thái hồ sơ
    function syncModalRequestLocButton() {
      const btn = document.getElementById('modalRequestLocBtn');
      if (!btn) return;
      const game = (typeof gamesList !== 'undefined' ? gamesList : []).find(g => String(g.id) === String(activeModalGameId));
      if (!game || !game.is_custom_game) {
        btn.classList.add('hidden');
        return;
      }
      btn.classList.remove('hidden');
      const rec = getMyLocRequest(game);
      const txt = document.getElementById('modalRequestLocBtnText');
      if (rec) {
        btn.className = 'pixel-btn px-3 py-2 bg-[#240C12] text-[#FF2A55] hover:text-red-300 text-xs border border-[#FF2A55]/50 hover:border-[#FF2A55] font-bold transition flex items-center justify-center space-x-1.5 shadow-[0_2px_8px_rgba(0,0,0,0.35)]';
        if (txt) txt.textContent = rec.status === 'completed' ? 'Đã Có Việt Hóa (Cài Ngay)' : 'Đã Yêu Cầu (Xem Tiến Độ)';
        btn.title = `Yêu cầu đã lưu trong Hồ Sơ .congu_save • Trạng thái: ${rec.status_label || 'Đang chờ duyệt'} • ${rec.community_votes || 0} lượt bình chọn`;
      } else {
        btn.className = 'pixel-btn px-3 py-2 btn-arcade-amber text-black text-xs font-bold transition flex items-center justify-center space-x-1.5 shadow-[0_2px_8px_rgba(0,0,0,0.35)]';
        if (txt) txt.textContent = 'Yêu Cầu Việt Hóa';
        btn.title = 'Gửi yêu cầu Việt hóa tựa game ngoài này lên hệ thống CỔ NGỮ (tự động quét Engine)';
      }
      if (window.lucide) lucide.createIcons();
    }

    function openMyRequestsTab() {
      const modal = document.getElementById('requestModal');
      if (modal) modal.classList.remove('hidden');
      closeProposalDrawer();
      setWishlistTab('mine');
      if (window.lucide) lucide.createIcons();
    }

    // Banner "Tin vui!" trong Bảng Nguyện Vọng
    function renderLocNewsBanner() {
      const banner = document.getElementById('locNewsBanner');
      if (!banner) return;
      const list = locNewsNotifications || [];
      if (!list.length) {
        banner.classList.add('hidden');
        banner.innerHTML = '';
        return;
      }
      banner.classList.remove('hidden');
      banner.innerHTML = list.map((n, idx) => `
        <div class="flex items-center justify-between gap-3">
          <div class="flex items-center space-x-2 min-w-0">
            <i data-lucide="party-popper" class="w-4 h-4 text-[#34D399] shrink-0"></i>
            <span class="text-xs font-sans text-emerald-200 truncate" title="${(n.message || '').replace(/"/g, '&quot;')}">
              Tin vui! <strong class="text-white">${n.vietnamese_title || n.title}</strong> bạn yêu cầu đã có bản Việt Hóa chính thức!
            </span>
          </div>
          <div class="flex items-center space-x-1.5 shrink-0">
            <button onclick="installRequestedGame(${idx})" class="pixel-btn btn-neon-green px-2.5 py-1 text-[10px] font-bold flex items-center space-x-1">
              <i data-lucide="download" class="w-3 h-3 fill-black"></i><span>Cài Ngay</span>
            </button>
            <button onclick="dismissLocNews(${idx})" class="text-slate-400 hover:text-white px-1.5" title="Bỏ qua thông báo">
              <i data-lucide="x" class="w-3.5 h-3.5"></i>
            </button>
          </div>
        </div>
      `).join('');
      if (window.lucide) lucide.createIcons();
    }

    function dismissLocNews(idx) {
      locNewsNotifications.splice(idx, 1);
      renderLocNewsBanner();
    }

    function installRequestedGame(idx) {
      const n = (locNewsNotifications || [])[idx];
      if (!n || !n.official_game_id) return;
      closeGameRequestModal();
      openGameModal(n.official_game_id);
    }



    if (typeof requestIdleCallback !== 'undefined') {
      requestIdleCallback(() => loadSteamGamesDb());
    } else {
      setTimeout(() => loadSteamGamesDb(), 1500);
    }

    // Modal lifecycle
    async function openGameRequestModal() {
      document.getElementById('requestModal').classList.remove('hidden');
      closeProposalDrawer();
      if (window.lucide) lucide.createIcons();
      renderLocNewsBanner();
      if (typeof loadMyLocalizationRequests === 'function') {
        await loadMyLocalizationRequests(true);
      }
      await loadCommunityRequests();
      if (activeWishlistTab === 'mine') renderMyLocalizationRequests();
    }

    function closeGameRequestModal() {
      document.getElementById('requestModal').classList.add('hidden');
      closeReqDropdown();
      closeProposalDrawer();
    }

    function toggleProposalDrawer() {
      const drawer = document.getElementById('proposalDrawer');
      if (drawer.classList.contains('hidden')) {
        drawer.classList.remove('hidden');
        document.getElementById('reqGameName').value = '';
        document.getElementById('reqGameNote').value = '';
        clearSelectedSteamGame();
        closeReqDropdown();
        setTimeout(() => {
          document.getElementById('reqGameName').focus();
        }, 80);
      } else {
        closeProposalDrawer();
      }
      if (window.lucide) lucide.createIcons();
    }

    function closeProposalDrawer() {
      const drawer = document.getElementById('proposalDrawer');
      if (drawer) drawer.classList.add('hidden');
      closeReqDropdown();
    }

    const FIREBASE_WISHLIST_URL = "https://congu-hub-default-rtdb.asia-southeast1.firebasedatabase.app";


    function updateCloudStatusBadge(cloudConnected) {
      const badge = document.getElementById('wishlistCloudBadge');
      if (!badge) return;
      if (cloudConnected) {
        badge.innerHTML = `
          <span class="inline-flex items-center space-x-1.5 px-2 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/30 text-[10px] text-emerald-400 font-sans">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
            <span>Cloud Realtime Online</span>
          </span>
        `;
      } else {
        badge.innerHTML = `
          <span class="inline-flex items-center space-x-1.5 px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/30 text-[10px] text-amber-400 font-sans" title="Chưa gắn URL Firebase, dữ liệu đang đồng bộ cục bộ và sẵn sàng kết nối Cloud">
            <span class="w-1.5 h-1.5 rounded-full bg-amber-400"></span>
            <span>Chế độ Offline / Sẵn sàng kết nối Firebase</span>
          </span>
        `;
      }
    }

    function setWishlistTab(tab) {
      activeWishlistTab = tab;

      const tabTop = document.getElementById('tabTopVoted');
      const tabRecent = document.getElementById('tabRecent');
      const tabMyVoted = document.getElementById('tabMyVoted');
      const tabMyRequests = document.getElementById('tabMyRequests');

      [tabTop, tabRecent, tabMyVoted, tabMyRequests].forEach(btn => {
        if (!btn) return;
        btn.classList.remove('bg-[#FF2A55]/20', 'text-[#FF2A55]', 'border', 'border-[#FF2A55]/40', 'font-bold');
        btn.classList.add('text-slate-400');
      });

      if (tab === 'top' && tabTop) {
        tabTop.classList.add('bg-[#FF2A55]/20', 'text-[#FF2A55]', 'border', 'border-[#FF2A55]/40', 'font-bold');
      } else if (tab === 'recent' && tabRecent) {
        tabRecent.classList.add('bg-[#FF2A55]/20', 'text-[#FF2A55]', 'border', 'border-[#FF2A55]/40', 'font-bold');
      } else if (tab === 'voted' && tabMyVoted) {
        tabMyVoted.classList.add('bg-[#FF2A55]/20', 'text-[#FF2A55]', 'border', 'border-[#FF2A55]/40', 'font-bold');
      } else if (tab === 'mine' && tabMyRequests) {
        tabMyRequests.classList.add('bg-[#FF2A55]/20', 'text-[#FF2A55]', 'border', 'border-[#FF2A55]/40', 'font-bold');
      }

      if (tab === 'mine') {
        renderMyLocalizationRequests();
      } else {
        renderCommunityRequests();
      }
    }

    // Bảng "Yêu cầu Việt hóa của tôi" (đọc từ Hồ Sơ .congu_save, ghép trạng thái Server)
    function renderMyLocalizationRequests() {
      const container = document.getElementById('communityRequestList');
      const statsText = document.getElementById('wishlistStatsText');
      if (!container) return;

      // Cập nhật số lượng trên tab
      const countBadge = document.getElementById('tabMyRequestsCount');
      if (countBadge) {
        const n = (myLocalizationRequests || []).length;
        if (n > 0) {
          countBadge.textContent = n;
          countBadge.classList.remove('hidden');
        } else {
          countBadge.classList.add('hidden');
        }
      }

      let items = [...(myLocalizationRequests || [])];
      if (wishlistFilterQuery) {
        const q = wishlistFilterQuery.toLowerCase();
        items = items.filter(it =>
          (it.title && it.title.toLowerCase().includes(q)) ||
          (it.steam_appid && String(it.steam_appid).includes(q)) ||
          (it.game_id && String(it.game_id).includes(q))
        );
      }

      if (statsText) {
        const totalVotes = (myLocalizationRequests || []).reduce((acc, it) => acc + (it.community_votes || 0), 0);
        statsText.innerHTML = `
          <span>📌 <strong class="text-white">${(myLocalizationRequests || []).length}</strong> yêu cầu trong Hồ Sơ .congu_save &bull; <strong class="text-[#FF2A55]">${totalVotes}</strong> lượt cộng đồng đã đồng tình</span>
        `;
      }

      if (items.length === 0) {
        container.innerHTML = `
          <div class="py-12 flex flex-col items-center justify-center space-y-3 text-slate-400 font-sans">
            <i data-lucide="inbox" class="w-8 h-8 text-slate-600"></i>
            <span class="text-xs text-slate-300">Bạn chưa yêu cầu Việt hóa tựa game nào.</span>
            <span class="text-[11px] text-slate-500 text-center max-w-sm leading-relaxed">Thêm game lẻ từ ổ cứng, sau đó bấm nút <strong class="text-[#FF2A55]">Yêu Cầu Việt Hóa</strong> trên thẻ game để gửi đề xuất. Yêu cầu được lưu vào Hồ Sơ .congu_save nên sẽ đi theo bạn sang mọi PC khác!</span>
          </div>
        `;
        if (window.lucide) lucide.createIcons();
        return;
      }

      container.innerHTML = items.map(it => {
        const title = it.vietnamese_title || it.title || it.game_id || '';
        const capsule = it.capsule || (it.steam_appid
          ? `https://cdn.akamai.steamstatic.com/steam/apps/${it.steam_appid}/capsule_sm_120.jpg`
          : '/static/icons/game_placeholder.png');
        const isDone = (it.status === 'completed') && it.official_game_id;
        const actionBtn = isDone
          ? `<button onclick="installRequestedGameById('${it.official_game_id}')" class="pixel-btn btn-neon-green px-3 py-2 text-[11px] font-bold flex items-center space-x-1.5 shrink-0">
               <i data-lucide="download" class="w-3.5 h-3.5 fill-black"></i><span>Cài Ngay</span>
             </button>`
          : `<div class="flex flex-col items-end shrink-0">
               <span class="text-[10px] font-pixel text-[#8B9BB4]">${it.community_votes || 0} 🔥</span>
               <span class="text-[9px] text-slate-500 font-sans">${it.request_ticket_id || ''}</span>
             </div>`;

        return `
          <div class="pixel-panel p-2.5 sm:p-3 bg-[#0F1522] border border-white/10 hover:border-[#FF2A55]/40 flex items-center justify-between gap-3 transition-all rounded-[2px]">
            <div class="flex items-center space-x-2.5 sm:space-x-3.5 min-w-0">
              <img src="${capsule}" class="w-[88px] sm:w-[104px] h-[38px] sm:h-[44px] object-cover rounded-[2px] border border-white/10 shrink-0 bg-[#0F1522]" alt="" onerror="this.onerror=null;this.src='/static/icons/game_placeholder.png'" />
              <div class="min-w-0">
                <div class="flex items-center space-x-2 flex-wrap gap-y-1">
                  <h4 class="text-xs sm:text-sm font-bold text-white truncate font-display">${title}</h4>
                  ${locRequestStatusBadge(it)}
                </div>
                <div class="flex items-center space-x-2 text-[11px] text-slate-400 mt-0.5 truncate">
                  <span class="text-[#8B9BB4] font-mono text-[10px]">${it.steam_appid ? 'AppID: ' + it.steam_appid : (it.game_id || '')}</span>
                  <span class="text-slate-600">&bull;</span>
                  <span class="text-slate-300 font-sans truncate" title="Engine phát hiện tự động">⚙️ ${it.detected_engine || 'Chưa quét'}</span>
                </div>
              </div>
            </div>
            ${actionBtn}
          </div>
        `;
      }).join('');
      if (window.lucide) lucide.createIcons();
    }

    function installRequestedGameById(officialGameId) {
      if (!officialGameId) return;
      closeGameRequestModal();
      openGameModal(officialGameId);
    }

    function renderCommunityRequests() {
      const container = document.getElementById('communityRequestList');
      const statsText = document.getElementById('wishlistStatsText');
      if (!container) return;

      // Filter by search query
      let items = [...communityWishlistItems];
      if (wishlistFilterQuery) {
        const q = wishlistFilterQuery.toLowerCase();
        items = items.filter(it =>
          (it.name && it.name.toLowerCase().includes(q)) ||
          (it.id && String(it.id).includes(q)) ||
          (it.note && it.note.toLowerCase().includes(q))
        );
      }

      // Sort / Filter by tab
      if (activeWishlistTab === 'top') {
        items.sort((a, b) => (b.votes || 0) - (a.votes || 0));
      } else if (activeWishlistTab === 'recent') {
        items.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
      } else if (activeWishlistTab === 'voted') {
        items = items.filter(it => it.has_voted);
        items.sort((a, b) => (b.votes || 0) - (a.votes || 0));
      }

      // Update stats text
      const totalVotes = communityWishlistItems.reduce((acc, it) => acc + (it.votes || 0), 0);
      if (statsText) {
        statsText.innerHTML = `
          <span>🔥 Tổng cộng: <strong class="text-white">${communityWishlistItems.length}</strong> tựa game &bull; <strong class="text-[#FF2A55]">${totalVotes}</strong> lượt bình chọn</span>
        `;
      }

      if (items.length === 0) {
        container.innerHTML = `
          <div class="py-12 flex flex-col items-center justify-center space-y-3 text-slate-400 font-sans">
            <i data-lucide="inbox" class="w-8 h-8 text-slate-600"></i>
            <span class="text-xs text-slate-300">Chưa có tựa game nào trong danh mục này.</span>
            <button onclick="toggleProposalDrawer()" class="pixel-btn btn-cyber-magenta px-3 py-1.5 text-xs font-bold">
              + Đề cử game đầu tiên
            </button>
          </div>
        `;
        if (window.lucide) lucide.createIcons();
        return;
      }

      const html = items.map((item, index) => {
        const rank = index + 1;
        const steamHeader = item.id
          ? `https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/${item.id}/header.jpg`
          : '';
        const thumbSrc = item.capsule || steamHeader;
        let rankBadge = '';
        let borderAccent = 'border-white/[0.06] hover:border-white/15';

        if (activeWishlistTab === 'top') {
          if (rank === 1) {
            rankBadge = `<span class="px-2.5 py-1 rounded-full bg-amber-400/15 border border-amber-400/25 text-amber-300 font-semibold text-[11px] shrink-0">👑 #1</span>`;
            borderAccent = 'border-amber-400/25';
          } else if (rank === 2) {
            rankBadge = `<span class="px-2.5 py-1 rounded-full bg-white/10 border border-white/15 text-zinc-200 font-semibold text-[11px] shrink-0">🥈 #2</span>`;
          } else if (rank === 3) {
            rankBadge = `<span class="px-2.5 py-1 rounded-full bg-amber-700/15 border border-amber-600/25 text-amber-400 font-semibold text-[11px] shrink-0">🥉 #3</span>`;
          } else {
            rankBadge = `<span class="px-2.5 py-1 rounded-full bg-white/[0.06] border border-white/10 text-zinc-400 text-[11px] font-medium shrink-0">#${rank}</span>`;
          }
        }

        // Status badge — pill mềm
        let statusBadge = '';
        const st = item.status || 'voting';
        if (st === 'reviewing') {
          statusBadge = `<span class="px-2.5 py-1 text-[10px] font-medium text-amber-300 bg-amber-400/10 border border-amber-400/20 rounded-full whitespace-nowrap">Tiếp Nhận</span>`;
        } else if (st === 'translating') {
          statusBadge = `<span class="px-2.5 py-1 text-[10px] font-medium text-red-300 bg-red-500/15 border border-red-500/25 rounded-full animate-pulse whitespace-nowrap">Đang Dịch</span>`;
        } else if (st === 'completed') {
          statusBadge = `<span class="px-2.5 py-1 text-[10px] font-medium text-emerald-300 bg-emerald-500/15 border border-emerald-500/25 rounded-full whitespace-nowrap">Đã Hoàn Thành</span>`;
        } else {
          statusBadge = `<span class="px-2.5 py-1 text-[10px] font-medium text-zinc-300 bg-white/[0.06] border border-white/10 rounded-full whitespace-nowrap">Đang Bình Chọn</span>`;
        }

        // Vote button — viên thuốc
        const voteBtn = item.has_voted ? `
          <button onclick="voteCommunityRequest('${item.id}')" class="pixel-btn ui-pill vote-btn-active px-3 sm:px-4 py-2 flex items-center gap-1.5 shrink-0" title="Bấm để hủy bình chọn">
            <i data-lucide="check" class="w-3.5 h-3.5"></i>
            <span class="text-xs font-semibold">${item.votes || 0}</span>
            <span class="text-[10px] hidden sm:inline">Đã Vote</span>
          </button>
        ` : `
          <button onclick="voteCommunityRequest('${item.id}')" class="pixel-btn ui-pill px-3 sm:px-4 py-2 flex items-center gap-1.5 shrink-0 group" title="Bình chọn cho tựa game này">
            <span class="text-xs">🔥</span>
            <span class="text-xs font-semibold">${item.votes || 0}</span>
            <span class="text-[10px] hidden sm:inline">Bình Chọn</span>
          </button>
        `;

        return `
          <div class="p-2.5 sm:p-3 bg-[#0F1522] border ${borderAccent} flex items-center justify-between gap-3 transition-all rounded-2xl">
            <div class="flex items-center space-x-2.5 sm:space-x-3.5 min-w-0">
              ${rankBadge}
              ${thumbSrc ? `
                <img src="${thumbSrc}" class="w-[88px] sm:w-[104px] h-[38px] sm:h-[44px] object-cover rounded-lg border border-white/10 shrink-0 bg-[#0F1522]" alt=""
                  onerror="if(!this.dataset.f){this.dataset.f='1';this.src='${steamHeader}';}else{this.style.display='none';this.nextElementSibling.classList.remove('hidden');}" />
                <div class="hidden w-[88px] sm:w-[104px] h-[38px] sm:h-[44px] rounded-lg bg-gradient-to-br from-zinc-700 to-zinc-900 border border-white/10 shrink-0 items-center justify-center">
                  <i data-lucide="gamepad-2" class="w-4 h-4 text-zinc-500"></i>
                </div>` : `
                <div class="w-[88px] sm:w-[104px] h-[38px] sm:h-[44px] rounded-lg bg-gradient-to-br from-zinc-700 to-zinc-900 border border-white/10 shrink-0 flex items-center justify-center">
                  <i data-lucide="gamepad-2" class="w-4 h-4 text-zinc-500"></i>
                </div>`}
              <div class="min-w-0">
                <div class="flex items-center space-x-2">
                  <h4 class="text-xs sm:text-sm font-semibold text-white truncate font-display">${item.name}</h4>
                  ${statusBadge}
                </div>
                <div class="flex items-center space-x-2 text-xs text-zinc-500 mt-0.5 truncate">
                  <span class="text-zinc-500 font-mono text-[10px]">AppID: ${item.id}</span>
                  ${item.note ? `<span class="text-zinc-700">&bull;</span> <span class="truncate text-zinc-400 text-xs" title="${(item.note || '').replace(/"/g, '&quot;')}">${item.note}</span>` : ''}
                </div>
              </div>
            </div>
            ${voteBtn}
          </div>
        `;
      }).join('');

      container.innerHTML = html;
      if (window.lucide) lucide.createIcons();
    }

    // Steam Autocomplete input events for Game Request
    function closeReqDropdown() {
      const dd = document.getElementById('reqSteamDropdown');
      if (dd) dd.classList.add('hidden');
      reqActiveIndex = -1;
      reqDropdownItems = [];
    }

    function clearReqInput() {
      const input = document.getElementById('reqGameName');
      input.value = '';
      document.getElementById('reqClearInputBtn').classList.add('hidden');
      clearSelectedSteamGame();
      closeReqDropdown();
      input.focus();
    }

    function clearSelectedSteamGame() {
      selectedGameRequest = null;
      const card = document.getElementById('reqSelectedCard');
      if (card) card.classList.add('hidden');
    }

    function selectSteamGame(item) {
      if (!item) return;
      selectedGameRequest = item;
      document.getElementById('reqGameName').value = item.name;
      document.getElementById('reqClearInputBtn').classList.remove('hidden');

      const card = document.getElementById('reqSelectedCard');
      const img = document.getElementById('reqSelectedCapsule');
      const title = document.getElementById('reqSelectedName');
      const meta = document.getElementById('reqSelectedId');

      img.src = item.capsule;
      title.textContent = item.name;
      meta.textContent = `Steam App ID: ${item.id}`;
      card.classList.remove('hidden');

      closeReqDropdown();
      if (window.lucide) lucide.createIcons();
    }

    function updateActiveDropdownItem() {
      const rows = document.querySelectorAll('.req-dropdown-row');
      rows.forEach((row, idx) => {
        if (idx === reqActiveIndex) {
          row.classList.add('bg-[#FF2A55]/25', 'border-l-4', 'border-[#FF2A55]');
          row.scrollIntoView({ block: 'nearest' });
        } else {
          row.classList.remove('bg-[#FF2A55]/25', 'border-l-4', 'border-[#FF2A55]');
        }
      });
    }

    function renderReqDropdown(results, query) {
      const dropdown = document.getElementById('reqSteamDropdown');
      if (!dropdown) return;

      reqDropdownItems = results || [];
      reqActiveIndex = -1;

      if (!results || results.length === 0) {
        dropdown.innerHTML = `
          <div class="p-3 text-center text-xs text-slate-300 font-sans">
            <div class="text-slate-200 font-semibold mb-1">Không thấy trong top game Steam phổ biến</div>
            <div class="text-[11px] text-slate-400">Bạn vẫn có thể đề cử tên này bằng nút "GỬI ĐỀ CỬ"!</div>
          </div>
        `;
        dropdown.classList.remove('hidden');
        return;
      }

      const qLow = query.toLowerCase();
      const html = results.map((item, idx) => {
        const name = item.name;
        const matchIdx = name.toLowerCase().indexOf(qLow);
        let nameHtml = name;
        if (matchIdx !== -1) {
          const pre = name.slice(0, matchIdx);
          const match = name.slice(matchIdx, matchIdx + qLow.length);
          const post = name.slice(matchIdx + qLow.length);
          nameHtml = `${pre}<span class="text-[#FF2A55] underline decoration-[#FF2A55]/60 underline-offset-2">${match}</span>${post}`;
        }

        return `
          <div class="req-dropdown-row flex items-center space-x-3 p-2 hover:bg-[#FF2A55]/15 cursor-pointer transition-colors group select-none" onclick="selectSteamGame(reqDropdownItems[${idx}])">
            <img src="${item.capsule}" class="w-[84px] h-[36px] object-cover rounded-[2px] border border-white/10 shrink-0 bg-[#0F1522]" alt="" onerror="this.style.opacity='0.2'" />
            <div class="flex-1 min-w-0">
              <div class="text-xs font-bold text-white group-hover:text-[#FF2A55] truncate">${nameHtml}</div>
              <div class="text-[10px] text-slate-400 font-mono flex items-center space-x-2 mt-0.5">
                <span class="text-[#8B9BB4] font-semibold">Steam AppID: ${item.id}</span>
              </div>
            </div>
            <div class="text-[10px] text-slate-400 font-mono opacity-0 group-hover:opacity-100 transition-opacity flex items-center space-x-1 shrink-0 pr-1">
              <span>chọn</span>
              <i data-lucide="chevron-right" class="w-3 h-3 text-[#FF2A55]"></i>
            </div>
          </div>
        `;
      }).join('');

      dropdown.innerHTML = `
        <div class="p-1.5 text-[10px] text-slate-400 font-mono bg-[#0A0E1A] flex justify-between items-center border-b border-white/5">
          <span class="text-slate-400 flex items-center gap-1"><i data-lucide="sparkles" class="w-3 h-3 text-[#FF2A55]"></i> Gợi ý từ Steam (${results.length})</span>
          <span class="text-[#FF2A55] font-semibold text-[9px] tracking-wide">Cơ sở dữ liệu Steam</span>
        </div>
        <div class="divide-y divide-white/5">${html}</div>
      `;
      dropdown.classList.remove('hidden');
      if (window.lucide) lucide.createIcons();
    }

    // Attach search events for wishlist filter & steam autocomplete
    document.addEventListener('DOMContentLoaded', () => {
      // Wishlist live filter search
      const wishlistFilterInput = document.getElementById('wishlistFilterInput');
      if (wishlistFilterInput) {
        wishlistFilterInput.addEventListener('input', (e) => {
          wishlistFilterQuery = e.target.value.trim();
          if (activeWishlistTab === 'mine') renderMyLocalizationRequests();
          else renderCommunityRequests();
        });
      }

      // Steam input autocomplete
      const reqInput = document.getElementById('reqGameName');
      const reqDropdown = document.getElementById('reqSteamDropdown');
      const reqSpinner = document.getElementById('reqSearchSpinner');
      const reqClearBtn = document.getElementById('reqClearInputBtn');

      if (reqInput) {
        reqInput.addEventListener('input', (e) => {
          const q = e.target.value.trim();
          if (q.length > 0) {
            reqClearBtn.classList.remove('hidden');
          } else {
            reqClearBtn.classList.add('hidden');
            clearSelectedSteamGame();
            closeReqDropdown();
            return;
          }

          if (selectedGameRequest && selectedGameRequest.name !== q) {
            clearSelectedSteamGame();
          }

          if (q.length < 2) {
            closeReqDropdown();
            return;
          }

          clearTimeout(reqSearchDebounceTimer);
          reqSearchDebounceTimer = setTimeout(async () => {
            reqSpinner.classList.remove('hidden');
            reqClearBtn.classList.add('hidden');
            try {
              const results = await querySteamSearch(q);
              renderReqDropdown(results, q);
            } catch (err) {
              console.error('Steam search error:', err);
            } finally {
              reqSpinner.classList.add('hidden');
              if (reqInput.value.trim().length > 0) {
                reqClearBtn.classList.remove('hidden');
              }
            }
          }, 120);
        });

        reqInput.addEventListener('keydown', (e) => {
          if (reqDropdown.classList.contains('hidden') || !reqDropdownItems.length) {
            if (e.key === 'Enter') {
              e.preventDefault();
              submitGameProposal();
            }
            return;
          }

          if (e.key === 'ArrowDown') {
            e.preventDefault();
            reqActiveIndex = (reqActiveIndex + 1) % reqDropdownItems.length;
            updateActiveDropdownItem();
          } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            reqActiveIndex = (reqActiveIndex - 1 + reqDropdownItems.length) % reqDropdownItems.length;
            updateActiveDropdownItem();
          } else if (e.key === 'Enter') {
            e.preventDefault();
            if (reqActiveIndex >= 0 && reqActiveIndex < reqDropdownItems.length) {
              selectSteamGame(reqDropdownItems[reqActiveIndex]);
            } else {
              closeReqDropdown();
            }
          } else if (e.key === 'Escape') {
            closeReqDropdown();
          }
        });

        document.addEventListener('click', (e) => {
          if (!reqInput.contains(e.target) && !reqDropdown.contains(e.target) && !e.target.closest('#reqClearInputBtn')) {
            closeReqDropdown();
          }
        });
      }
    });


    // [TÌM KIẾM TOÀN CỤC: đã tách sang static/js/omni_search.js]

    // [ĐÁM MÂY CỔ NGỮ & VAULT: Đã tách sang static/js/cloud_save_ui.js]

    // Global Keyboard Shortcuts
    window.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && (e.key === 'b' || e.key === 'B')) {
        e.preventDefault();
        toggleSidebar();
        return;
      }
      if (e.key === 'Escape') {
        closeGameModal();
        if (typeof closeSettingsModal === 'function') closeSettingsModal();
        if (typeof closeCustomGameModal === 'function') closeCustomGameModal();
        if (typeof closeCardContextMenu === 'function') closeCardContextMenu();
        closeGameRequestModal();
        closeCloudModal();
        closeCloudConflictModal();
        closeVaultModal();
      }
    });



    // Khi nguoi dung dong cua so / tab, tu dong gui tin hieu tat sach tien trinh
    window.addEventListener('beforeunload', (e) => {
      if (typeof progressInterval !== 'undefined' && progressInterval) {
        e.preventDefault();
        e.returnValue = 'Đang tiến hành vá tệp game, bạn có chắc chắn muốn thoát?';
        return;
      }
      try {
        // fetch wrapper tự gắn token header; sendBeacon không hỗ trợ header.
        fetch('/api/app/quit', { method: 'POST', keepalive: true }).catch(() => {});
      } catch (e) {}
    });

    // Titlebar Dragging System (Native Windows OS Drag via Win32 SetWindowPos Tracking)
    (function initTitlebarDrag() {
      const titlebar = document.getElementById('appTitlebar');
      if (!titlebar) return;

      let isDragging = false;

      titlebar.addEventListener('mousedown', function (e) {
        // Chặn pywebview tự xử lý drag-region (customize.js gắn listener trên document.body):
        // tránh DOUBLE-DRAG đánh nhau giữa pywebviewMoveWindow và native SetWindowPos tracking.
        e.stopPropagation();

        // Only primary mouse button (left click)
        if (e.button !== 0) return;

        // Do not drag if clicking inside an interactive control
        if (e.target.closest('button, input, select, textarea, a, .no-drag')) {
          return;
        }

        // Prevent text selection or browser default drag ghost
        e.preventDefault();
        isDragging = true;

        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.drag_window === 'function') {
          window.pywebview.api.drag_window().catch(() => {});
        } else {
          fetch('/api/window/drag', { method: 'POST' }).catch(() => {});
        }
      });

      window.addEventListener('mouseup', function () {
        if (isDragging) {
          isDragging = false;
          if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.drag_stop === 'function') {
            window.pywebview.api.drag_stop().catch(() => {});
          } else {
            fetch('/api/window/drag_stop', { method: 'POST' }).catch(() => {});
          }
        }
      });
    })();

    // =========================================================================
    // GAMEPAD & STEAM INPUT EMULATION MODULE (CẤP ĐỘ 3)
    // =========================================================================
    let cachedConnectedControllers = [];
    let currentGamepadConfig = null;

    function applyGamepadConfigToUI(cfg) {
      if (!cfg) return;
      const toggle = document.getElementById('gamepadEnableToggle');
      const optSection = document.getElementById('gamepadOptionsSection');
      if (toggle) toggle.checked = !!cfg.enabled;
      if (optSection) {
        if (cfg.enabled) {
          optSection.classList.remove('opacity-40', 'pointer-events-none');
        } else {
          optSection.classList.add('opacity-40', 'pointer-events-none');
        }
      }

      // Mode
      const modeRadios = document.getElementsByName('gamepadMode');
      for (const r of modeRadios) {
        if (r.value === (cfg.mode || 'xinput_wrapper')) {
          r.checked = true;
          break;
        }
      }

      // Preset
      const presetSel = document.getElementById('gamepadPresetSelect');
      if (presetSel) presetSel.value = cfg.preset || 'platformer';

      // Vibration
      const vibToggle = document.getElementById('gamepadVibrationToggle');
      if (vibToggle) vibToggle.checked = cfg.vibration !== false;

      // Deadzone
      const dzVal = Math.round((cfg.deadzone || 0.15) * 100);
      const dzRange = document.getElementById('gamepadDeadzoneRange');
      const dzText = document.getElementById('gamepadDeadzoneVal');
      if (dzRange) dzRange.value = dzVal;
      if (dzText) dzText.textContent = `${dzVal}%`;
    }

    function onGamepadConfigChanged() {
      const toggle = document.getElementById('gamepadEnableToggle');
      const optSection = document.getElementById('gamepadOptionsSection');
      if (toggle && optSection) {
        if (toggle.checked) {
          optSection.classList.remove('opacity-40', 'pointer-events-none');
        } else {
          optSection.classList.add('opacity-40', 'pointer-events-none');
        }
      }
      // Tự động lưu cấu hình khi người dùng thay đổi
      saveGamepadConfigAuto();
    }

    let saveGamepadTimeout = null;
    function saveGamepadConfigAuto() {
      if (saveGamepadTimeout) clearTimeout(saveGamepadTimeout);
      saveGamepadTimeout = setTimeout(() => {
        saveGamepadConfigInternal(false);
      }, 500);
    }

    // =========================================================================
    // NON-STEAM & CUSTOM GAMES AUTO-DISCOVERY MODULE
    // =========================================================================
    let currentDetectedCustomGame = null;

    function openAddCustomGameModal(prefill) {
      const modal = document.getElementById('customGameModal');
      if (!modal) return;

      // Reset form
      document.getElementById('cgExeInput').value = '';
      const presetAppIdEl = document.getElementById('cgPresetAppIdInput');
      if (presetAppIdEl) presetAppIdEl.value = '';
      document.getElementById('cgDetectResultSection').classList.add('hidden');
      document.getElementById('cgDetectLoading').classList.add('hidden');
      document.getElementById('btnSaveCustomGameToLib').disabled = true;
      currentDetectedCustomGame = null;

      // Điền sẵn thông tin khi người dùng bấm "Trỏ Đường Dẫn" từ thẻ Chưa tải
      if (prefill && typeof prefill === 'object') {
        const setVal = (id, value) => {
          const el = document.getElementById(id);
          if (el && value) el.value = value;
        };
        setVal('cgTitleInput', prefill.title);
        setVal('cgAppIdInput', prefill.steam_appid);
        setVal('cgPresetAppIdInput', prefill.steam_appid);
        setVal('cgPosterUrlInput', prefill.cover_url);
        const posterImg = document.getElementById('cgPosterImg');
        if (posterImg && prefill.cover_url) posterImg.src = prefill.cover_url;
      }

      modal.classList.remove('hidden');
      lucide.createIcons();
    }

    function closeCustomGameModal() {
      const modal = document.getElementById('customGameModal');
      if (modal) modal.classList.add('hidden');
    }

    function applyDetectedGameToUI(game) {
      if (!game) return;

      document.getElementById('cgTitleInput').value = game.title || '';
      document.getElementById('cgVnTitleInput').value = game.vietnamese_title || game.title || '';
      document.getElementById('cgDevInput').value = game.developer || '';
      document.getElementById('cgEngineInput').value = game.engine || 'PC Game';
      document.getElementById('cgAppIdInput').value = game.steam_appid || '';
      const presetAppIdEl = document.getElementById('cgPresetAppIdInput');
      if (presetAppIdEl && game.steam_appid) presetAppIdEl.value = game.steam_appid;
      document.getElementById('cgPosterUrlInput').value = game.cover_url || game.header_url || '';

      const posterImg = document.getElementById('cgPosterImg');
      const engineBadge = document.getElementById('cgEngineBadge');
      if (posterImg) posterImg.src = game.local_cover || game.cover_url || game.header_url || '/static/icons/game_placeholder.png';
      if (engineBadge) engineBadge.textContent = game.engine || 'PC';

      renderCustomGameSaveLocations(game.vault_config?.save_locations || []);
    }

    function renderCustomGameSaveLocations(locations) {
      const container = document.getElementById('cgSaveLocationsList');
      if (!container) return;

      if (!locations || locations.length === 0) {
        container.innerHTML = '<div class="text-xs text-slate-500 py-2">Chưa xác định được thư mục save game tự động. Bạn có thể bấm "Thêm thư mục khác" ở trên.</div>';
        return;
      }

      container.innerHTML = locations.map((loc, idx) => `
        <div class="p-2 rounded bg-white/[0.03] border border-white/5 flex items-center justify-between text-xs font-mono">
          <div class="flex items-center space-x-2 truncate">
            <i data-lucide="folder-check" class="w-3.5 h-3.5 text-emerald-400 shrink-0"></i>
            <span class="text-slate-300 truncate" title="${loc.path}">${loc.path}</span>
          </div>
          <button onclick="removeCustomSaveLocation(${idx})" class="text-slate-500 hover:text-rose-400 p-1 shrink-0" title="Xóa thư mục này">
            <i data-lucide="x" class="w-3.5 h-3.5"></i>
          </button>
        </div>
      `).join('');
      lucide.createIcons();
    }

    function removeCustomSaveLocation(idx) {
      if (currentDetectedCustomGame && currentDetectedCustomGame.vault_config && Array.isArray(currentDetectedCustomGame.vault_config.save_locations)) {
        currentDetectedCustomGame.vault_config.save_locations.splice(idx, 1);
        renderCustomGameSaveLocations(currentDetectedCustomGame.vault_config.save_locations);
      }
    }

    function addManualSaveLocation() {
      const customPath = prompt("Nhập đường dẫn thư mục save game (hỗ trợ macro {DOCUMENTS}, {APPDATA}, {LOCALAPPDATA_LOW} hoặc đường dẫn tuyệt đối):");
      if (customPath && customPath.trim()) {
        if (!currentDetectedCustomGame) currentDetectedCustomGame = {};
        if (!currentDetectedCustomGame.vault_config) currentDetectedCustomGame.vault_config = {};
        if (!Array.isArray(currentDetectedCustomGame.vault_config.save_locations)) {
          currentDetectedCustomGame.vault_config.save_locations = [];
        }
        currentDetectedCustomGame.vault_config.save_locations.push({
          slot: `manual_${currentDetectedCustomGame.vault_config.save_locations.length + 1}`,
          path: customPath.trim().replace(/\\/g, '/')
        });
        renderCustomGameSaveLocations(currentDetectedCustomGame.vault_config.save_locations);
      }
    }
    // [HYDRA REPACK SOURCES & TORRENT: Đã tách sang static/js/torrent_ui.js]

// =============================================================================
// APPLICATION BOOTSTRAP & WATCHERS
// =============================================================================
(function initApp() {
    // Mặc định: ẩn Sidebar để lưới poster full-width (kiểu RecompLauncher).
    const isSidebarStoredHidden = localStorage.getItem('sidebar_visible') !== 'true';
    const sb = document.getElementById('librarySidebar');
    const strip = document.getElementById('collapsedSidebarStrip');
    const sbtn = document.getElementById('btnToggleSidebar');
    const brandIcon = document.getElementById('brandToggleSidebarIcon');
    const brandBtn = document.getElementById('btnBrandToggleSidebar');

    if (isSidebarStoredHidden) {
      if (sb) sb.classList.add('hidden');
      if (strip) strip.classList.add('hidden');
      if (sbtn) sbtn.classList.remove('bg-[#FF2A55]/20', 'text-[#FF2A55]');
      if (brandIcon) brandIcon.setAttribute('data-lucide', 'panel-left');
      if (brandBtn) brandBtn.title = 'Mở danh sách game bên trái (Ctrl+B)';
    } else {
      if (sb) sb.classList.remove('hidden');
      if (strip) strip.classList.add('hidden');
      if (sbtn) sbtn.classList.add('bg-[#FF2A55]/20', 'text-[#FF2A55]');
      if (brandIcon) brandIcon.setAttribute('data-lucide', 'panel-left-close');
      if (brandBtn) brandBtn.title = 'Thu gọn danh sách game bên trái (Ctrl+B)';
    }
    if (typeof initSettingsOnStartup === 'function') initSettingsOnStartup();
    if (typeof fetchBookmarks === 'function') fetchBookmarks();
    currentTopNav = 'library';
    window.currentTopNav = 'library';
    activeFilter = 'installed';
    if (typeof fetchGames === 'function') fetchGames();
    if (typeof syncLocalizationRequestsOnStartup === 'function') syncLocalizationRequestsOnStartup();
    if (typeof startGlobalPlaytimeWatcher === 'function') startGlobalPlaytimeWatcher();
    if (typeof checkCommunityCloudStatus === 'function') checkCommunityCloudStatus();
    if (typeof checkGdriveStatus === 'function') checkGdriveStatus();
    if (typeof startGlobalTorrentWatcher === 'function') startGlobalTorrentWatcher();
})();
