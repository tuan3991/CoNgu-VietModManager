    // =============================================================
    // HYDRA REPACK SOURCES & ARIA2C TORRENT DOWNLOAD ENGINE (JS)
    // =============================================================
    let currentHydraModalTab = 'catalogue';
    let torrentPollingInterval = null;
    let cachedRepackResultsByGame = {};
    let catalogueCachedGames = [];
    let activeCatalogueGame = null;
    let catalogueSearchDebounceTimer = null;

    function openHydraModal(defaultTab = 'catalogue') {
      const modal = document.getElementById('hydraModal');
      if (!modal) return;
      modal.classList.remove('hidden');
      switchHydraTab(defaultTab);
      lucide.createIcons();
    }

    function closeHydraModal() {
      const modal = document.getElementById('hydraModal');
      if (modal) modal.classList.add('hidden');
      closeCatalogueDownloadOptions();
    }

    function switchHydraTab(tabName) {
      currentHydraModalTab = tabName;
      const btnCat = document.getElementById('hydraTabBtn-catalogue');
      const btnDl = document.getElementById('hydraTabBtn-downloads');
      const btnSrc = document.getElementById('hydraTabBtn-sources');
      const cCat = document.getElementById('hydraTabContent-catalogue');
      const cDl = document.getElementById('hydraTabContent-downloads');
      const cSrc = document.getElementById('hydraTabContent-sources');

      const baseBtnClass = 'py-3 px-4 text-slate-400 hover:text-white border-b-2 border-transparent flex items-center space-x-1.5 transition whitespace-nowrap font-bold font-display text-xs';
      const activeBtnClass = 'py-3 px-4 text-cyan-400 border-b-2 border-cyan-400 flex items-center space-x-1.5 transition whitespace-nowrap font-bold font-display text-xs';

      if (btnCat) btnCat.className = (tabName === 'catalogue') ? activeBtnClass : baseBtnClass;
      if (btnDl) btnDl.className = (tabName === 'downloads') ? activeBtnClass : baseBtnClass;
      if (btnSrc) btnSrc.className = (tabName === 'sources') ? activeBtnClass : baseBtnClass;

      if (cCat) cCat.classList.toggle('hidden', tabName !== 'catalogue');
      if (cDl) cDl.classList.toggle('hidden', tabName !== 'downloads');
      if (cSrc) cSrc.classList.toggle('hidden', tabName !== 'sources');

      if (tabName === 'catalogue') {
        if (!catalogueCachedGames || catalogueCachedGames.length === 0) {
          searchCatalogueGames('');
        }
      } else if (tabName === 'downloads') {
        pollTorrentStatus();
      } else if (tabName === 'sources') {
        loadHydraSourcesList();
      }
      lucide.createIcons();
    }

    // =============================================================
    // CATALOGUE ENGINE: SEARCH & RENDER GAMES (SCREENSHOT 1)
    // =============================================================
    let catalogueSearchAbort = null;
    let catalogueSearchCache = {};

    function onCatalogueSearchInput(e) {
      const val = e.target.value.trim();
      const clearBtn = document.getElementById('btnCatalogueClearSearch');
      if (clearBtn) clearBtn.classList.toggle('hidden', !val);

      if (catalogueSearchDebounceTimer) clearTimeout(catalogueSearchDebounceTimer);
      catalogueSearchDebounceTimer = setTimeout(() => {
        searchCatalogueGames(val);
      }, 250);
    }

    function clearCatalogueSearch() {
      const input = document.getElementById('catalogueSearchInput');
      if (input) {
        input.value = '';
        input.focus();
      }
      const clearBtn = document.getElementById('btnCatalogueClearSearch');
      if (clearBtn) clearBtn.classList.add('hidden');
      searchCatalogueGames('');
    }

    function quickFilterCatalogue(keyword) {
      const input = document.getElementById('catalogueSearchInput');
      if (input) input.value = keyword;
      const clearBtn = document.getElementById('btnCatalogueClearSearch');
      if (clearBtn) clearBtn.classList.toggle('hidden', !keyword);

      const tags = document.querySelectorAll('#catalogueQuickTags .cat-tag-btn');
      tags.forEach(t => {
        if ((!keyword && t.innerText.includes('Tất Cả')) || (keyword && t.innerText.toLowerCase().includes(keyword.toLowerCase()))) {
          t.className = 'cat-tag-btn px-3 py-1.5 rounded-full bg-white/[0.14] text-white border border-transparent text-[11px] font-medium transition';
        } else {
          t.className = 'cat-tag-btn px-3 py-1.5 rounded-full bg-white/[0.04] text-zinc-400 hover:text-white border border-white/[0.06] text-[11px] transition';
        }
      });

      searchCatalogueGames(keyword);
    }

    function filterOnlyVietModGames() {
      if (!catalogueCachedGames) return;
      const filtered = catalogueCachedGames.filter(g => g.has_viet_mod);
      renderCatalogueCards(filtered, true);
      const countElem = document.getElementById('catalogueResultsCountText');
      if (countElem) countElem.innerText = `Tìm thấy ${filtered.length} game có sẵn Việt Hóa`;
    }

    async function searchCatalogueGames(query = '') {
      const q = (query || '').trim();
      const container = document.getElementById('catalogueCardsContainer');
      const countElem = document.getElementById('catalogueResultsCountText');
      if (!container) return;

      // 1. Kiểm tra cache client trả về ngay tức thì
      const cacheKey = q.toLowerCase();
      if (catalogueSearchCache[cacheKey]) {
        catalogueCachedGames = catalogueSearchCache[cacheKey];
        renderCatalogueCards(catalogueCachedGames, false);
        if (countElem) {
          countElem.innerText = `${catalogueCachedGames.length} kết quả ${q ? 'cho: "' + q + '"' : ''}`;
        }
        return;
      }

      // 2. Hủy bỏ request trước đó nếu đang gửi dở (Chống Race Condition)
      if (catalogueSearchAbort) {
        catalogueSearchAbort.abort();
      }
      catalogueSearchAbort = new AbortController();
      const signal = catalogueSearchAbort.signal;

      container.innerHTML = `
        <div class="p-12 text-center space-y-3">
          <i data-lucide="loader-2" class="w-8 h-8 text-cyan-400 animate-spin mx-auto"></i>
          <p class="text-xs text-slate-300 font-bold">Đang quét kho game Repack từ các nguồn...</p>
        </div>
      `;
      if (window.lucide) lucide.createIcons();

      try {
        const res = await fetch('/api/hydra/catalogue/search', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: q, limit: 60 }),
          signal: signal
        });
        const data = await res.json();
        if (data && data.success) {
          catalogueCachedGames = data.games || [];
          catalogueSearchCache[cacheKey] = catalogueCachedGames;
          renderCatalogueCards(catalogueCachedGames, false);
          if (countElem) {
            countElem.innerText = `${catalogueCachedGames.length} kết quả ${q ? 'cho: "' + q + '"' : ''}`;
          }
        } else {
          container.innerHTML = `<div class="p-8 text-center text-xs text-rose-400">Lỗi: ${data ? data.error : 'Không thể tải danh mục'}</div>`;
        }
      } catch (e) {
        if (e.name === 'AbortError') return; // Bỏ qua nếu bị abort bởi ký tự mới
        console.error('Error searching catalogue:', e);
        container.innerHTML = `<div class="p-8 text-center text-xs text-rose-400">Lỗi kết nối khi tìm game: ${e.message}</div>`;
      }
    }

    function renderCatalogueCards(games, isFiltered = false) {
      const container = document.getElementById('catalogueCardsContainer');
      if (!container) return;

      if (!games || games.length === 0) {
        container.innerHTML = `
          <div class="p-10 text-center rounded-[6px] border border-dashed border-slate-800 bg-black/20 space-y-3">
            <i data-lucide="search-x" class="w-10 h-10 text-slate-600 mx-auto"></i>
            <p class="text-xs text-slate-300 font-bold">Không tìm thấy tựa game nào phù hợp.</p>
            <p class="text-[11px] text-slate-500 max-w-md mx-auto">
              Hãy thử tìm với từ khóa khác (ví dụ: "god of war", "cyberpunk", "wukong", "elden ring") hoặc nhấn "Quản Lý Nguồn" để nạp thêm các file .json của FitGirl, DODI, GOG, Xatab!
            </p>
            <button onclick="clearCatalogueSearch()" class="pixel-btn px-3 py-1.5 text-xs bg-cyan-900/60 hover:bg-cyan-800 text-cyan-200 border border-cyan-500/40 rounded font-bold">
              Xem Tất Cả Game
            </button>
          </div>
        `;
        if (window.lucide) lucide.createIcons();
        return;
      }

      container.innerHTML = games.map((g, idx) => {
        const cover = g.cover_url || 'https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/480/header.jpg';
        const bmActive = typeof isGameBookmarked === 'function' && isGameBookmarked({ title: g.title });
        const sourcePills = (g.sources || []).map(src => {
          let sClass = 'bg-white/[0.05] text-zinc-300 border-white/10';
          const lower = src.toLowerCase();
          if (lower.includes('fitgirl')) sClass = 'bg-amber-500/10 text-amber-200 border-amber-500/20';
          else if (lower.includes('dodi')) sClass = 'bg-rose-500/10 text-rose-200 border-rose-500/20';
          else if (lower.includes('gog')) sClass = 'bg-emerald-500/10 text-emerald-200 border-emerald-500/20';
          else if (lower.includes('xatab')) sClass = 'bg-amber-500/10 text-amber-200 border-amber-500/20';
          else if (lower.includes('kaos')) sClass = 'bg-sky-500/10 text-sky-200 border-sky-500/20';
          return `<span class="px-2.5 py-1 rounded-full text-[10px] font-medium border ${sClass}">${src}</span>`;
        }).join('');

        const vietModBadge = g.has_viet_mod ? `
          <span class="inline-flex items-center space-x-1 px-2.5 py-1 rounded-full text-[10px] font-medium bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
            <i data-lucide="check-check" class="w-3 h-3 text-emerald-400"></i>
            <span>Có Bản Dịch Cổ Ngữ</span>
          </span>
        ` : '';

        return `
          <div onclick="openCatalogueDownloadOptions(${idx})" 
               class="group relative flex flex-col sm:flex-row items-stretch sm:items-center justify-between p-3 sm:p-3.5 rounded-2xl bg-[#0F1522] hover:bg-[#141418] border border-white/[0.06] hover:border-white/15 transition-all duration-200 cursor-pointer gap-3.5">
            
            <!-- Left: Cover Image Thumbnail -->
            <div class="flex items-center space-x-3.5 min-w-0">
              <div class="w-full sm:w-36 h-24 sm:h-20 rounded-xl overflow-hidden bg-black/40 border border-white/10 shrink-0 relative">
                <img src="${cover}" alt="${g.title}" class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" onerror="this.onerror=null;this.src='/static/icons/game_placeholder.png'" />
                <div class="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent opacity-80"></div>
                <div class="absolute bottom-1 right-1.5 text-[9px] font-medium px-1.5 py-0.5 rounded-full bg-black/80 text-zinc-300 border border-white/10">
                  ${g.total_repacks} Repack
                </div>
              </div>

              <!-- Middle: Title, Genres, Source Badges -->
              <div class="min-w-0 space-y-1.5 flex-1">
                <div class="flex flex-wrap items-center gap-2">
                  <h4 class="font-display font-semibold text-sm sm:text-base text-zinc-100 group-hover:text-white transition-colors leading-snug">
                    ${g.title}
                  </h4>
                  ${vietModBadge}
                </div>

                <div class="text-xs text-zinc-500 line-clamp-1">
                  ${g.genres || 'Action, Adventure'}
                </div>

                <!-- Source Repack Badges -->
                <div class="flex flex-wrap items-center gap-1.5 pt-0.5">
                  ${sourcePills}
                </div>
              </div>
            </div>

            <!-- Right: Action Button -->
            <div class="flex sm:flex-col items-center sm:items-end justify-between sm:justify-center gap-2 shrink-0 border-t sm:border-t-0 pt-2 sm:pt-0 border-white/[0.06]">
              <span class="text-[11px] text-zinc-500 hidden sm:inline">
                ${g.total_repacks} nguồn tải
              </span>
              <div class="flex items-center gap-2">
                <button onclick="event.stopPropagation(); catalogueToggleBookmark(${idx}, this)"
                        class="pixel-btn w-8 h-8 flex items-center justify-center ${bmActive ? 'bg-cyan-500/20 text-cyan-200 border-cyan-400/50' : 'bg-[#1C2536] text-slate-300 border-white/10 hover:text-cyan-300'}"
                        title="${bmActive ? 'Bỏ khỏi Thư viện (Chưa tải)' : 'Thêm vào Thư viện để tải sau'}">
                  <i data-lucide="bookmark${bmActive ? '-check' : '-plus'}" class="w-4 h-4"></i>
                </button>
                <button onclick="event.stopPropagation(); openCatalogueDownloadOptions(${idx})" 
                        class="pixel-btn px-3.5 py-1.5 text-xs flex items-center space-x-1.5">
                  <i data-lucide="download" class="w-3.5 h-3.5"></i>
                  <span>Tùy Chọn Tải</span>
                </button>
              </div>
            </div>

          </div>
        `;
      }).join('');
      if (window.lucide) lucide.createIcons();
    }

    function rerenderCatalogueCards() {
      if (Array.isArray(catalogueCachedGames) && catalogueCachedGames.length) {
        renderCatalogueCards(catalogueCachedGames, true);
      }
    }

    async function catalogueToggleBookmark(idx, sourceEl) {
      const game = catalogueCachedGames && catalogueCachedGames[idx];
      if (!game || typeof toggleGameBookmark !== 'function') return;
      const row = sourceEl && sourceEl.closest ? sourceEl.closest('[onclick*="openCatalogueDownloadOptions"]') : null;
      const sourceImg = row ? row.querySelector('img') : null;
      const added = await toggleGameBookmark({
        title: game.title,
        slug: game.slug || '',
        genre: game.genres || '',
        cover_url: game.cover_url || '',
        source: 'hydra'
      });
      if (added && typeof flyCoverToLibrary === 'function') flyCoverToLibrary(sourceImg);
      rerenderCatalogueCards();
    }

    // =============================================================
    // DOWNLOAD OPTIONS MODAL LOGIC (SCREENSHOT 2)
    // =============================================================
    function openCatalogueDownloadOptions(idx) {
      if (!catalogueCachedGames || !catalogueCachedGames[idx]) {
        console.error("openCatalogueDownloadOptions: Invalid index", idx);
        return;
      }
      openCatalogueDownloadOptionsForGame(catalogueCachedGames[idx]);
    }

    // Mở thẳng bảng tùy chọn tải cho một game bất kỳ (dùng cho Omnibox / kết quả tìm kiếm)
    function openCatalogueDownloadOptionsForGame(game) {
      if (!game) return;
      activeCatalogueGame = game;

      const modal = document.getElementById('catalogueDownloadOptionsModal');
      const titleElem = document.getElementById('dlOptGameTitle');
      const filterInput = document.getElementById('catalogueRepackFilterInput');
      const sourceSelect = document.getElementById('catalogueRepackSourceFilter');

      if (titleElem) titleElem.innerText = game.title;
      if (filterInput) filterInput.value = '';

      if (sourceSelect) {
        const uniqueSources = game.sources || [];
        sourceSelect.innerHTML = `<option value="">Filter by source (Tất cả ${uniqueSources.length} nguồn)</option>` +
          uniqueSources.map(s => `<option value="${s}">${s}</option>`).join('');
      }

      renderRepacksList(game.repacks || []);

      if (modal) {
        modal.classList.remove('hidden');
        modal.style.display = 'flex';
      }
      if (window.lucide) lucide.createIcons();
    }

    function closeCatalogueDownloadOptions() {
      const modal = document.getElementById('catalogueDownloadOptionsModal');
      if (modal) {
        modal.classList.add('hidden');
        modal.style.display = 'none';
      }
      activeCatalogueGame = null;
    }

    function filterCatalogueRepacks() {
      if (!activeCatalogueGame || !activeCatalogueGame.repacks) return;
      const keyword = (document.getElementById('catalogueRepackFilterInput')?.value || '').toLowerCase().trim();
      const selectedSource = (document.getElementById('catalogueRepackSourceFilter')?.value || '').toLowerCase().trim();

      const filtered = activeCatalogueGame.repacks.filter(r => {
        const titleMatch = !keyword || r.title.toLowerCase().includes(keyword) || (r.repacker && r.repacker.toLowerCase().includes(keyword));
        const sourceMatch = !selectedSource || (r.repacker && r.repacker.toLowerCase() === selectedSource) || (r.source_name && r.source_name.toLowerCase().includes(selectedSource));
        return titleMatch && sourceMatch;
      });

      renderRepacksList(filtered);
    }

    function renderRepacksList(repacks) {
      const container = document.getElementById('catalogueRepacksList');
      if (!container) return;

      if (!repacks || repacks.length === 0) {
        container.innerHTML = `
          <div class="p-8 text-center text-xs text-slate-500 rounded bg-[#040810] border border-slate-800">
            Không có bản Repack nào khớp với bộ lọc. Hãy thử xóa bớt điều kiện lọc!
          </div>
        `;
        return;
      }

      container.innerHTML = repacks.map((r, i) => {
        const primaryUri = r.uri || (r.uris && r.uris[0]) || '';
        const repacker = r.repacker || r.source_name || 'Hydra Community';
        const size = r.file_size || 'Không rõ dung lượng';
        const date = r.upload_date || 'Gần đây';

        return `
          <div class="group p-3.5 rounded-[5px] bg-[#091120] hover:bg-[#0e1a32] border border-slate-800 hover:border-cyan-500/50 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 transition shadow-sm">
            
            <!-- Left Info (Screenshot 2: Title, Size, Repacker, Date) -->
            <div class="min-w-0 space-y-1.5 flex-1">
              <div class="flex items-center space-x-2">
                <span class="w-2.5 h-2.5 rounded-full bg-emerald-400 shadow-[0_0_8px_#34d399] shrink-0"></span>
                <h5 class="text-xs sm:text-sm font-bold text-slate-100 group-hover:text-cyan-200 transition-colors leading-tight">
                  ${r.title}
                </h5>
              </div>

              <div class="text-[11px] text-slate-400 font-mono flex items-center space-x-2 pl-4">
                <span>${size}</span>
                <span>•</span>
                <span class="text-cyan-300 font-semibold">${repacker}</span>
                <span>•</span>
                <span>${date}</span>
              </div>
            </div>

            <!-- Right Actions: Tải Cổ Ngữ vs qBittorrent -->
            <div class="flex items-center space-x-2 shrink-0 self-end sm:self-center pl-4 sm:pl-0">
              <button onclick="startCatalogueDownload('${encodeURIComponent(primaryUri)}', '${encodeURIComponent(r.title)}')" 
                      class="pixel-btn px-3 py-1.5 text-xs font-bold bg-cyan-600 hover:bg-cyan-500 text-white rounded flex items-center space-x-1.5 transition shadow-[0_0_12px_rgba(6,182,212,0.35)]" 
                      title="Tải siêu tốc 16 luồng bằng Aria2c tích hợp sẵn trong CỔ NGỮ">
                <i data-lucide="zap" class="w-3.5 h-3.5 text-amber-300"></i>
                <span>Tải Trong CỔ NGỮ</span>
              </button>

              <button onclick="openExternalTorrentLink('${encodeURIComponent(primaryUri)}')" 
                      class="pixel-btn px-2.5 py-1.5 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 rounded flex items-center space-x-1 transition" 
                      title="Mở bằng phần mềm Torrent trên máy (qBittorrent / uTorrent)">
                <i data-lucide="magnet" class="w-3.5 h-3.5 text-cyan-400"></i>
                <span class="hidden md:inline">qBittorrent</span>
              </button>
            </div>

          </div>
        `;
      }).join('');
      lucide.createIcons();
    }

    async function startCatalogueDownload(encodedUri, encodedTitle) {
      const uri = decodeURIComponent(encodedUri);
      const title = decodeURIComponent(encodedTitle);

      try {
        const res = await fetch('/api/torrent/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ uri: uri, title: title })
        });
        const data = await res.json();
        if (data && data.success) {
          showToast(`Đã bắt đầu tải: "${title}" (16 luồng)`, 'success');
          closeCatalogueDownloadOptions();
          switchHydraTab('downloads');
          pollTorrentStatus();
        } else {
          const errMsg = (data && (data.message || data.error)) || 'Không thể bắt đầu tải.';
          showToast(errMsg, 'error');
        }
      } catch (e) {
        showToast('Lỗi khi kích hoạt tiến trình tải: ' + e.message, 'error');
      }
    }

    async function loadHydraSourcesList() {
      try {
        const res = await fetch('/api/hydra/sources');
        const data = await res.json();
        if (!data || !data.success) return;

        const sources = data.sources || [];
        const stats = data.stats || {};

        const statRepacks = document.getElementById('hydraStatRepacksCount');
        const statSources = document.getElementById('hydraStatSourcesCount');
        const tabBadge = document.getElementById('hydraTabRepackTotalBadge');
        if (statRepacks) statRepacks.innerText = `${stats.total_repacks || 0} bản game`;
        if (statSources) statSources.innerText = `${sources.length} nguồn`;
        if (tabBadge) tabBadge.innerText = `${stats.total_repacks || 0} Repacks`;

        const container = document.getElementById('hydraSourcesListContainer');
        if (!container) return;

        if (sources.length === 0) {
          container.innerHTML = `<div class="p-6 text-center text-xs text-slate-500 rounded bg-[#03060c] border border-slate-800">Chưa có nguồn Hydra nào được thêm. Hãy dán link hoặc chọn file .json từ máy tính!</div>`;
          return;
        }

        container.innerHTML = sources.map(s => {
          const isUrl = s.startsWith('http://') || s.startsWith('https://');
          const shortName = isUrl ? s.split('/').pop() : s;
          return `
            <div class="p-3 rounded-[4px] bg-[#0F1522] border border-slate-800 hover:border-cyan-500/40 flex items-center justify-between gap-3 transition">
              <div class="flex items-center space-x-3 min-w-0">
                <div class="w-8 h-8 rounded bg-cyan-950 text-cyan-400 flex items-center justify-center shrink-0 border border-cyan-500/30">
                  <i data-lucide="${isUrl ? 'link' : 'file-code'}" class="w-4 h-4"></i>
                </div>
                <div class="min-w-0">
                  <div class="text-xs font-bold text-slate-200 truncate font-mono">${shortName}</div>
                  <div class="text-[10px] text-slate-500 truncate max-w-lg">${s}</div>
                </div>
              </div>
              <button onclick="removeHydraSource('${encodeURIComponent(s)}')" class="pixel-btn p-1.5 text-slate-500 hover:text-rose-400 hover:bg-rose-950/40 rounded transition" title="Xóa nguồn này">
                <i data-lucide="trash-2" class="w-4 h-4"></i>
              </button>
            </div>
          `;
        }).join('');
        lucide.createIcons();
      } catch (e) {
        console.error('Error loading hydra sources:', e);
      }
    }

    async function addHydraSource() {
      const input = document.getElementById('hydraSourceUrlInput');
      const url = input ? input.value.trim() : '';
      if (!url) {
        showToast('Vui lòng nhập URL nguồn .json!', 'warning');
        return;
      }
      try {
        const res = await fetch('/api/hydra/sources/add', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: url })
        });
        const data = await res.json();
        if (data && data.success) {
          showToast('Đã thêm nguồn Hydra! Đang đồng bộ trong nền...', 'success');
          if (input) input.value = '';
          loadHydraSourcesList();
        } else {
          showToast(data ? data.error || data.message : 'Lỗi khi thêm nguồn', 'error');
        }
      } catch (e) {
        showToast('Lỗi kết nối: ' + e.message, 'error');
      }
    }

    async function removeHydraSource(encodedUrl) {
      const url = decodeURIComponent(encodedUrl);
      if (!confirm(`Bạn có chắc chắn muốn xóa nguồn này?\n${url}`)) return;
      try {
        const res = await fetch('/api/hydra/sources/remove', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: url })
        });
        const data = await res.json();
        if (data && data.success) {
          showToast('Đã xóa nguồn thành công.', 'info');
          loadHydraSourcesList();
        }
      } catch (e) {
        showToast('Lỗi khi xóa nguồn: ' + e.message, 'error');
      }
    }

    async function triggerHydraSync() {
      const btn = document.getElementById('btnSyncHydraSources');
      if (btn) btn.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i><span>Đang Đồng Bộ...</span>`;
      try {
        const res = await fetch('/api/hydra/sources/sync', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ force: true })
        });
        const data = await res.json();
        showToast(data.message || 'Đang đồng bộ hóa nguồn trong nền...', 'info');
        setTimeout(() => {
          loadHydraSourcesList();
          if (btn) btn.innerHTML = `<i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i><span>Đồng Bộ Online</span>`;
          lucide.createIcons();
        }, 3000);
      } catch (e) {
        showToast('Lỗi khi kích hoạt đồng bộ: ' + e.message, 'error');
        if (btn) btn.innerHTML = `<i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i><span>Đồng Bộ Online</span>`;
      }
    }

    async function browseAndImportHydraJson() {
      const btn = document.getElementById('btnImportHydraJson');
      if (btn) btn.disabled = true;
      try {
        const res = await fetch('/api/hydra/sources/import_local', { method: 'POST' });
        const data = await res.json();
        if (data && data.success) {
          showToast(data.message, 'success');
          loadHydraSourcesList();
        } else if (data && !data.cancelled) {
          showToast(data.message || 'Không thể nạp file JSON', 'error');
        }
      } catch (e) {
        showToast('Lỗi khi nhập file JSON: ' + e.message, 'error');
      } finally {
        if (btn) btn.disabled = false;
        lucide.createIcons();
      }
    }

    // --- REPACK SEARCH & CARDS ---
    async function preloadGameRepacksBadge(gameId) {
      try {
        const game = gamesList.find(g => g.id === gameId);
        if (!game) return;
        const res = await fetch('/api/hydra/search', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            game_id: game.id,
            title: game.vietnamese_title || game.title,
            steam_appid: game.steam_appid || ''
          })
        });
        const data = await res.json();
        if (data && data.success) {
          cachedRepackResultsByGame[gameId] = data.results || [];
          const badge = document.getElementById('modalRepackCountBadge');
          if (badge) {
            badge.innerText = `${data.total || 0}`;
            if (data.total > 0) {
              badge.classList.remove('hidden');
            } else {
              badge.classList.add('hidden');
            }
          }
        }
      } catch (e) {
        console.error('Error preloading repacks badge:', e);
      }
    }

    async function loadGameRepacksTab(gameId) {
      const loading = document.getElementById('repackSearchLoading');
      const empty = document.getElementById('repackSearchEmpty');
      const container = document.getElementById('repackCardsContainer');

      if (loading) loading.classList.remove('hidden');
      if (empty) empty.classList.add('hidden');
      if (container) container.innerHTML = '';

      try {
        let results = cachedRepackResultsByGame[gameId];
        if (!results) {
          const game = gamesList.find(g => g.id === gameId);
          const res = await fetch('/api/hydra/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              game_id: gameId,
              title: game ? (game.vietnamese_title || game.title) : '',
              steam_appid: game ? (game.steam_appid || '') : ''
            })
          });
          const data = await res.json();
          results = (data && data.success) ? (data.results || []) : [];
          cachedRepackResultsByGame[gameId] = results;
        }

        if (loading) loading.classList.add('hidden');

        if (!results || results.length === 0) {
          if (empty) empty.classList.remove('hidden');
          return;
        }

        if (container) {
          container.innerHTML = results.map(r => {
            const hasUris = r.uris && r.uris.length > 0;
            const primaryUri = hasUris ? r.uris[0] : '';
            const isMagnet = primaryUri.startsWith('magnet:');
            const safeTitle = (r.title || 'Game Repack').replace(/'/g, "\\'");
            return `
              <div class="p-4 rounded-[6px] bg-[#0F1522] border border-cyan-500/30 hover:border-cyan-400 transition flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div class="space-y-1.5 flex-1 min-w-0">
                  <div class="flex items-center gap-2 flex-wrap">
                    <span class="text-[10px] font-pixel font-bold px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-300 border border-cyan-500/50 uppercase">
                      ${r.source_name || 'Repack'}
                    </span>
                    ${r.file_size ? `<span class="text-[11px] font-mono font-bold text-amber-300 bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/30">${r.file_size}</span>` : ''}
                    ${r.upload_date ? `<span class="text-[10px] text-slate-400">📅 ${r.upload_date}</span>` : ''}
                  </div>
                  <h4 class="text-sm font-bold text-white font-display truncate" title="${r.title}">
                    ${r.title}
                  </h4>
                  <div class="text-[11px] text-slate-400 font-mono truncate">
                    Nguồn: ${r.source_file || 'Hydra Community'}
                  </div>
                </div>

                <div class="flex items-center space-x-2 shrink-0">
                  <button onclick="startRepackDownload('${encodeURIComponent(primaryUri)}', '${safeTitle}')" class="pixel-btn px-4 py-2 text-xs font-bold bg-cyan-600 hover:bg-cyan-500 text-white rounded flex items-center space-x-1.5 transition shadow-[0_0_15px_rgba(6,182,212,0.35)]">
                    <i data-lucide="zap" class="w-4 h-4 text-cyan-200"></i>
                    <span>⚡ Tải Trong CỔ NGỮ</span>
                  </button>
                  ${isMagnet ? `
                    <button onclick="openExternalTorrentLink('${encodeURIComponent(primaryUri)}')" class="pixel-btn px-3 py-2 text-xs font-bold bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-600 rounded flex items-center space-x-1 transition" title="Mở bằng qBittorrent hoặc phần mềm ngoài">
                      <i data-lucide="external-link" class="w-3.5 h-3.5"></i>
                      <span>qBittorrent</span>
                    </button>
                  ` : ''}
                </div>
              </div>
            `;
          }).join('');
        }
        lucide.createIcons();
      } catch (e) {
        if (loading) loading.classList.add('hidden');
        if (empty) empty.classList.remove('hidden');
        console.error('Error loading game repacks tab:', e);
      }
    }

    function refreshGameRepacks(gameId) {
      delete cachedRepackResultsByGame[gameId];
      loadGameRepacksTab(gameId);
    }

    async function startRepackDownload(encodedUri, title) {
      const uri = decodeURIComponent(encodedUri);
      if (!uri) {
        showToast('Không tìm thấy link tải hợp lệ!', 'error');
        return;
      }
      try {
        showToast('Đang kết nối daemon aria2c và bắt đầu tải...', 'info');
        const res = await fetch('/api/torrent/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ uri: uri, title: title })
        });
        const data = await res.json();
        if (data && data.success) {
          showToast(`Đã thêm vào hàng đợi tải: ${title}`, 'success');
          openHydraModal('downloads');
          pollTorrentStatus();
        } else {
          showToast(data ? data.error || data.message : 'Lỗi khi khởi chạy aria2c', 'error');
        }
      } catch (e) {
        showToast('Lỗi kết nối tải về: ' + e.message, 'error');
      }
    }

    async function openExternalTorrentLink(encodedUri) {
      const uri = decodeURIComponent(encodedUri);
      try {
        const res = await fetch('/api/torrent/open_external', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ uri: uri })
        });
        const data = await res.json();
        if (data && data.success) {
          showToast('Đã gửi liên kết tới phần mềm Torrent của máy!', 'success');
        } else {
          showToast(data ? data.message : 'Không thể mở phần mềm ngoài', 'error');
        }
      } catch (e) {
        showToast('Lỗi: ' + e.message, 'error');
      }
    }

    // --- DOWNLOAD QUEUE STATUS & POLLING ---
    async function pollTorrentStatus() {
      try {
        const res = await fetch('/api/torrent/status');
        const data = await res.json();
        if (!data || !data.success) return;

        const downloads = data.downloads || [];
        updateTorrentQueueUI(downloads);
      } catch (e) {
        console.error('Error polling torrent status:', e);
      }
    }

    function updateTorrentQueueUI(downloads) {
      const emptyNotice = document.getElementById('hydraEmptyDownloadsNotice');
      const listContainer = document.getElementById('hydraDownloadTasksList');
      const totalSpeedElem = document.getElementById('hydraTotalDownloadSpeed');
      const topBadge = document.getElementById('hydraActiveDownloadsBadge');
      const tabBadge = document.getElementById('hydraTabDownloadCountBadge');
      const floatingDock = document.getElementById('floatingTorrentDock');
      const floatingPercent = document.getElementById('floatingTorrentPercent');
      const floatingSpeed = document.getElementById('floatingTorrentSpeed');

      let activeCount = 0;
      let totalSpeedBytes = 0;
      let topActivePercent = 0;

      downloads.forEach(d => {
        const isAct = d.status === 'downloading' || d.status === 'active' || d.status === 'seeding' || d.status === 'metadata';
        if (isAct) {
          activeCount++;
          const spd = (d.speed_bytes !== undefined) ? d.speed_bytes : (d.download_speed || 0);
          totalSpeedBytes += spd;
          if (d.percent > topActivePercent) topActivePercent = d.percent;
        }
      });

      // Update badges
      if (topBadge) {
        if (activeCount > 0) {
          topBadge.innerText = `${activeCount}`;
          topBadge.classList.remove('hidden');
        } else {
          topBadge.classList.add('hidden');
        }
      }
      if (tabBadge) {
        if (downloads.length > 0) {
          tabBadge.innerText = `${downloads.length}`;
          tabBadge.classList.remove('hidden');
        } else {
          tabBadge.classList.add('hidden');
        }
      }

      // Update total speed
      if (totalSpeedElem) {
        totalSpeedElem.innerText = formatDownloadSpeed(totalSpeedBytes);
      }

      // Update floating dock
      if (floatingDock) {
        if (activeCount > 0) {
          floatingDock.classList.remove('hidden');
          if (floatingPercent) floatingPercent.innerText = `${topActivePercent}%`;
          if (floatingSpeed) floatingSpeed.innerText = formatDownloadSpeed(totalSpeedBytes);
        } else {
          floatingDock.classList.add('hidden');
        }
      }

      // Render tasks list in tab
      if (!listContainer) return;

      if (downloads.length === 0) {
        if (emptyNotice) emptyNotice.classList.remove('hidden');
        listContainer.innerHTML = '';
        return;
      }

      if (emptyNotice) emptyNotice.classList.add('hidden');

      listContainer.innerHTML = downloads.map(task => {
        const isMetadata = task.is_metadata || ((task.status === 'active' || task.status === 'metadata' || task.status === 'waiting') && (!task.total_bytes || task.total_bytes === 0));
        const isDownloading = (task.status === 'downloading' || task.status === 'active') && !isMetadata;
        const isPaused = task.status === 'paused';
        const isComplete = task.status === 'complete';
        const isError = task.status === 'error';

        const taskTitle = task.title || task.release_title || task.game_title || 'Tệp Game Repack';
        const peers = task.connections !== undefined ? task.connections : (task.peers || 0);
        const speedText = task.speed_formatted || formatDownloadSpeed(task.speed_bytes || task.download_speed || 0);
        const completedText = task.completed_formatted || formatBytes(task.completed_bytes || task.downloaded_bytes || 0);
        const totalText = task.total_formatted || (task.total_bytes > 0 ? formatBytes(task.total_bytes) : 'Đang nạp...');

        let statusText = 'Đang tải';
        let statusBadgeClass = 'bg-cyan-500/20 text-cyan-300 border-cyan-500/50';

        if (isMetadata) {
          statusText = 'Nạp Peers & Metadata';
          statusBadgeClass = 'bg-amber-500/20 text-amber-300 border-amber-500/50 animate-pulse';
        } else if (isPaused) {
          statusText = 'Tạm dừng';
          statusBadgeClass = 'bg-slate-700/50 text-slate-300 border-slate-600';
        } else if (isComplete) {
          statusText = 'Hoàn tất';
          statusBadgeClass = 'bg-emerald-500/20 text-emerald-300 border-emerald-500/50';
        } else if (isError) {
          statusText = 'Lỗi';
          statusBadgeClass = 'bg-rose-500/20 text-rose-300 border-rose-500/50';
        } else if (task.status === 'waiting') {
          statusText = 'Đang chờ hàng đợi';
          statusBadgeClass = 'bg-indigo-500/20 text-indigo-300 border-indigo-500/50';
        }

        let infoLine = '';
        if (isMetadata) {
          infoLine = `
            <span class="text-amber-300 font-mono flex items-center space-x-1.5">
              <span class="inline-block w-2 h-2 rounded-full bg-amber-400 animate-ping"></span>
              <span>Đang kết nối Swarm (Đã bắt được ${peers} peers) • Đang tải danh sách file torrent...</span>
            </span>
          `;
        } else {
          infoLine = `
            <span>${completedText} / ${totalText}</span>
            <span>•</span>
            <span class="text-cyan-300 font-bold">${task.percent || 0}%</span>
            ${task.eta_str && task.eta_str !== 'Đang tính...' ? `<span>• Còn: ${task.eta_str}</span>` : (task.eta_seconds > 0 ? `<span>• Còn ~${Math.ceil(task.eta_seconds / 60)} phút</span>` : '')}
          `;
        }

        return `
          <div class="p-4 rounded-[6px] bg-[#0F1522] border border-cyan-500/30 space-y-3">
            <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div class="space-y-0.5 min-w-0">
                <div class="flex items-center space-x-2">
                  <span class="text-[10px] font-pixel font-bold px-2 py-0.5 rounded border uppercase ${statusBadgeClass}">
                    ${statusText}
                  </span>
                  <h4 class="text-xs font-bold text-white font-display truncate max-w-md" title="${taskTitle}">
                    ${taskTitle}
                  </h4>
                </div>
                <div class="text-[11px] text-slate-400 font-mono flex items-center space-x-3">
                  ${infoLine}
                </div>
              </div>

              <!-- Speed & Peers -->
              <div class="flex items-center space-x-3 text-xs font-mono">
                ${(isDownloading || isMetadata) ? `
                  <div class="text-right">
                    <div class="text-cyan-300 font-bold">${isMetadata ? 'Đang nạp...' : `⚡ ${speedText}`}</div>
                    <div class="text-[10px] text-slate-400">Peers: ${peers}</div>
                  </div>
                ` : ''}

                <!-- Action Controls -->
                <div class="flex items-center space-x-1.5 shrink-0">
                  ${(isDownloading || isMetadata) ? `
                    <button onclick="pauseTorrent('${task.gid}')" class="pixel-btn p-1.5 bg-slate-800 hover:bg-slate-700 text-amber-300 rounded" title="Tạm dừng">
                      <i data-lucide="pause" class="w-4 h-4"></i>
                    </button>
                  ` : ''}
                  ${isPaused ? `
                    <button onclick="resumeTorrent('${task.gid}')" class="pixel-btn p-1.5 bg-cyan-950 hover:bg-cyan-900 text-cyan-300 rounded" title="Tiếp tục tải">
                      <i data-lucide="play" class="w-4 h-4"></i>
                    </button>
                  ` : ''}
                  <button onclick="cancelTorrent('${task.gid}')" class="pixel-btn p-1.5 bg-slate-800 hover:bg-rose-950/60 text-slate-400 hover:text-rose-400 rounded transition" title="Hủy tác vụ tải">
                    <i data-lucide="trash-2" class="w-4 h-4"></i>
                  </button>
                  ${isComplete ? `
                    <button onclick="openTorrentFolder('${encodeURIComponent(task.save_dir || task.download_dir || '')}')" class="pixel-btn px-2.5 py-1 text-xs bg-emerald-950 hover:bg-emerald-900 text-emerald-300 border border-emerald-500/40 rounded flex items-center space-x-1 font-bold">
                      <i data-lucide="folder" class="w-3.5 h-3.5"></i>
                      <span>Mở Thư Mục</span>
                    </button>
                  ` : ''}
                </div>
              </div>
            </div>

            <!-- Progress Bar -->
            <div class="w-full bg-[#03060c] rounded-full h-2 overflow-hidden border border-slate-800">
              <div class="h-full rounded-full transition-all duration-300 ${
                isComplete ? 'bg-emerald-500' :
                isMetadata ? 'bg-gradient-to-r from-amber-500 via-cyan-500 to-blue-500 animate-pulse w-full' :
                'bg-gradient-to-r from-cyan-500 to-blue-500'
              }" style="${isMetadata ? 'width: 100%' : `width: ${task.percent || 0}%`}"></div>
            </div>
          </div>
        `;
      }).join('');
      lucide.createIcons();
    }

    async function pauseTorrent(gid) {
      try {
        await fetch('/api/torrent/pause', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ gid: gid })
        });
        pollTorrentStatus();
      } catch (e) {
        showToast('Lỗi khi tạm dừng: ' + e.message, 'error');
      }
    }

    async function resumeTorrent(gid) {
      try {
        await fetch('/api/torrent/resume', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ gid: gid })
        });
        pollTorrentStatus();
      } catch (e) {
        showToast('Lỗi khi tiếp tục tải: ' + e.message, 'error');
      }
    }

    async function cancelTorrent(gid) {
      if (!confirm('Bạn có chắc chắn muốn hủy tác vụ tải này không?')) return;
      try {
        await fetch('/api/torrent/cancel', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ gid: gid })
        });
        showToast('Đã hủy tác vụ tải.', 'info');
        pollTorrentStatus();
      } catch (e) {
        showToast('Lỗi khi hủy tải: ' + e.message, 'error');
      }
    }

    async function openTorrentFolder(encodedPath = '') {
      const folderPath = encodedPath ? decodeURIComponent(encodedPath) : '';
      try {
        const res = await fetch('/api/torrent/open_folder', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ folder_path: folderPath })
        });
        const data = await res.json();
        if (data && data.success) {
          showToast(`Đã mở thư mục: ${data.path}`, 'success');
        } else {
          showToast(data ? data.message : 'Không thể mở thư mục', 'error');
        }
      } catch (e) {
        showToast('Lỗi mở thư mục: ' + e.message, 'error');
      }
    }

    function formatDownloadSpeed(bytesPerSec) {
      if (!bytesPerSec || bytesPerSec <= 0) return '0 KB/s';
      const mbs = bytesPerSec / (1024 * 1024);
      if (mbs >= 1) return `${mbs.toFixed(2)} MB/s`;
      const kbs = bytesPerSec / 1024;
      return `${kbs.toFixed(0)} KB/s`;
    }

    function formatBytes(bytes) {
      if (!bytes || bytes <= 0) return '0 B';
      const k = 1024;
      const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    function startGlobalTorrentWatcher() {
      pollTorrentStatus();
      if (!torrentPollingInterval) {
        torrentPollingInterval = setInterval(() => {
          pollTorrentStatus();
        }, 4000);
      }
    }

