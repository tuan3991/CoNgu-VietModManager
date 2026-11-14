// =============================================================================
// CỔ NGỮ (VIETMODHUB) - OMNIBOX: TÌM KIẾM TOÀN CỤC 3 KHO
// =============================================================================

const omniState = {
  query: '',
  library: [],
  translations: [],
  downloads: [],
  filter: 'all',
  loadingDownloads: false,
  requestSeq: 0,
  abortController: null,
  downloadTimer: null
};

let omniResultsQuery = '';

function omniEsc(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function omniNorm(text) {
  const raw = String(text || '');
  return (typeof removeVietnameseTones === 'function' ? removeVietnameseTones(raw) : raw.toLowerCase()).trim();
}

function omniMatches(game, qNorm) {
  if (!game || !qNorm) return false;
  return [game.title, game.vietnamese_title, game.genre, game.engine, game.developer]
    .some(value => omniNorm(value).includes(qNorm));
}

function omniGameScore(game) {
  let score = 0;
  if (game.is_favorite) score += 4;
  if (game.status_code === 'INSTALLED') score += 3;
  else if (game.status_code === 'NOT_INSTALLED' || game.status_code === 'UPDATE_DETECTED') score += 2;
  else if (game.is_bookmarked) score += 1;
  return score;
}

function omniCover(game) {
  return game.local_cover || game.avatar_url || (game.assets && game.assets.poster) || '';
}

function omniLibraryStateText(game) {
  if (game.is_ghost) return 'Chưa cài trên máy · đã lưu Save';
  if (game.is_custom_game) return game.is_game_found ? 'Game tự thêm' : 'Game tự thêm · thiếu file';
  if (game.status_code === 'INSTALLED') return 'Sẵn sàng chơi';
  if (game.status_code === 'UPDATE_DETECTED') return 'Cần cài lại Việt hóa';
  if (game.status_code === 'NOT_INSTALLED') return 'Đã có game · chờ Việt hóa';
  if (game.library_state === 'bookmark') return 'Đã lưu · chưa tải';
  return 'Kho bản dịch · chưa có game';
}

// -----------------------------------------------------------------------------
// CHẠY TÌM KIẾM
// -----------------------------------------------------------------------------
function omniRunSearch(rawQuery) {
  const q = String(rawQuery || '').trim();
  omniState.query = q;

  const clearBtn = document.getElementById('clearSearchBtn');
  if (clearBtn) clearBtn.classList.toggle('hidden', !q);

  if (!q) {
    omniState.requestSeq++;
    if (omniState.downloadTimer) clearTimeout(omniState.downloadTimer);
    if (omniState.abortController) omniState.abortController.abort();
    omniState.library = [];
    omniState.translations = [];
    omniState.downloads = [];
    omniState.loadingDownloads = false;
    omniCloseDropdown();
    return;
  }

  const qNorm = omniNorm(q);
  const list = Array.isArray(gamesList) ? gamesList : [];

  omniState.library = list
    .filter(game => omniMatches(game, qNorm))
    .sort((a, b) => omniGameScore(b) - omniGameScore(a))
    .slice(0, 40);

  omniState.translations = list
    .filter(game => !game.is_custom_game && !game.is_bookmark_only)
    .filter(game => game.translation_stats || (Array.isArray(game.versions) && game.versions.length))
    .filter(game => omniMatches(game, qNorm))
    .sort((a, b) => omniGameScore(b) - omniGameScore(a))
    .slice(0, 40);

  // Kết quả tải về của từ khóa cũ không được hiển thị nhầm cho từ khóa mới
  omniState.requestSeq++;
  if (omniState.abortController) omniState.abortController.abort();
  omniState.downloads = [];
  omniState.loadingDownloads = false;
  renderOmniDropdown();

  if (omniState.downloadTimer) clearTimeout(omniState.downloadTimer);
  omniState.downloadTimer = setTimeout(() => omniSearchDownloads(q), 320);
}

async function omniSearchDownloads(query) {
  const seq = ++omniState.requestSeq;
  if (omniState.abortController) omniState.abortController.abort();
  const controller = new AbortController();
  omniState.abortController = controller;
  omniState.loadingDownloads = true;
  renderOmniDropdown();

  try {
    const res = await fetch('/api/hydra/catalogue/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: query, limit: 30 }),
      signal: controller.signal
    });
    const data = await res.json();
    if (seq !== omniState.requestSeq) return;
    omniState.downloads = (data && data.success && Array.isArray(data.games)) ? data.games.slice(0, 30) : [];
  } catch (err) {
    if (err && err.name === 'AbortError') return;
    if (seq !== omniState.requestSeq) return;
    omniState.downloads = [];
  } finally {
    if (seq === omniState.requestSeq) {
      omniState.loadingDownloads = false;
      renderOmniDropdown();
      const resultsView = document.getElementById('viewSearchResults');
      if (resultsView && !resultsView.classList.contains('hidden')) renderSearchResultsPage();
    }
  }
}

// -----------------------------------------------------------------------------
// RENDER DROPDOWN
// -----------------------------------------------------------------------------
function omniThumbHtml(src, alt) {
  if (src) {
    return `<img src="${omniEsc(src)}" alt="" class="w-10 h-12 rounded-md object-cover border border-white/10 shrink-0" onerror="this.style.display='none'" />`;
  }
  return `<div class="w-10 h-12 rounded-md bg-white/[0.04] border border-white/[0.06] flex items-center justify-center shrink-0">
            <i data-lucide="gamepad-2" class="w-4 h-4 text-zinc-500"></i>
          </div>`;
}

function omniGroupHtml(title, count, rowsHtml) {
  return `
    <div class="p-1.5">
      <div class="flex items-center justify-between px-2.5 py-1.5 text-[10px] font-bold tracking-wider uppercase text-zinc-500">
        <span>${title}</span><span>${count}</span>
      </div>
      <div class="space-y-0.5">${rowsHtml}</div>
    </div>
  `;
}

function omniLibraryRow(game, index) {
  let actionHtml = '';
  if (game.status_code === 'INSTALLED') {
    actionHtml = `<button onclick="event.stopPropagation(); omniLibraryAction(${index}, 'play')" class="omni-action px-2.5 py-1 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 text-[10px] font-bold hover:bg-red-400/25 shrink-0">Chơi</button>`;
  } else if (game.status_code === 'UPDATE_DETECTED') {
    actionHtml = `<button onclick="event.stopPropagation(); omniLibraryAction(${index}, 'reinstall')" class="omni-action px-2.5 py-1 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/30 text-[10px] font-bold hover:bg-amber-500/25 shrink-0">Cài lại</button>`;
  } else if (game.status_code === 'NOT_INSTALLED') {
    actionHtml = `<button onclick="event.stopPropagation(); omniLibraryAction(${index}, 'install')" class="omni-action px-2.5 py-1 rounded-full bg-red-500/15 text-red-300 border border-red-500/30 text-[10px] font-bold hover:bg-red-500/25 shrink-0">Cài Việt hóa</button>`;
  } else if (game.is_ghost) {
    actionHtml = `<button onclick="event.stopPropagation(); omniLibraryAction(${index}, 'install_ghost')" class="omni-action px-2.5 py-1 rounded-full bg-red-500/15 text-red-300 border border-red-500/30 text-[10px] font-bold hover:bg-red-500/25 shrink-0">Cài đặt</button>`;
  } else if (game.library_state === 'bookmark') {
    actionHtml = `<button onclick="event.stopPropagation(); omniLibraryAction(${index}, 'download')" class="omni-action px-2.5 py-1 rounded-full bg-red-500/15 text-red-300 border border-red-500/30 text-[10px] font-bold hover:bg-red-500/25 shrink-0">Tải game</button>`;
  } else {
    actionHtml = `<button onclick="event.stopPropagation(); omniLibraryAction(${index}, 'detail')" class="omni-action px-2.5 py-1 rounded-full bg-white/[0.06] text-zinc-300 border border-white/10 text-[10px] font-bold hover:bg-white/[0.12] shrink-0">Chọn thư mục</button>`;
  }

  return `
    <div onclick="omniOpenLibrary(${index})" class="flex items-center gap-2.5 px-2.5 py-2 rounded-xl hover:bg-white/[0.05] cursor-pointer transition">
      ${omniThumbHtml(omniCover(game), game.title)}
      <div class="min-w-0 flex-1">
        <div class="text-[12px] font-bold text-white truncate">${omniEsc(game.vietnamese_title || game.title)}</div>
        <div class="text-[10px] text-zinc-500 truncate">${omniEsc(omniLibraryStateText(game))}${game.engine ? ' · ' + omniEsc(game.engine) : ''}</div>
      </div>
      ${actionHtml}
    </div>
  `;
}

function omniTranslationRow(game, index) {
  const version = game.latest_version || (game.translation_stats && game.translation_stats.version) || 'v1.0.0';
  const lines = game.translation_stats && game.translation_stats.total_lines;
  let actionHtml = '';
  if (game.status_code === 'INSTALLED') {
    actionHtml = `<button onclick="event.stopPropagation(); omniTranslationAction(${index}, 'detail')" class="px-2.5 py-1 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 text-[10px] font-bold shrink-0">Đã cài</button>`;
  } else if (game.status_code === 'UPDATE_DETECTED') {
    actionHtml = `<button onclick="event.stopPropagation(); omniTranslationAction(${index}, 'reinstall')" class="px-2.5 py-1 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/30 text-[10px] font-bold hover:bg-amber-500/25 shrink-0">Cài lại</button>`;
  } else if (game.status_code === 'NOT_INSTALLED') {
    actionHtml = `<button onclick="event.stopPropagation(); omniTranslationAction(${index}, 'install')" class="px-2.5 py-1 rounded-full bg-red-500/15 text-red-300 border border-red-500/30 text-[10px] font-bold hover:bg-red-500/25 shrink-0">Cài đặt</button>`;
  } else if (game.is_ghost) {
    actionHtml = `<button onclick="event.stopPropagation(); omniTranslationAction(${index}, 'install_ghost')" class="px-2.5 py-1 rounded-full bg-red-500/15 text-red-300 border border-red-500/30 text-[10px] font-bold hover:bg-red-500/25 shrink-0">Cài game</button>`;
  } else if (game.is_bookmarked) {
    actionHtml = `<button onclick="event.stopPropagation(); omniTranslationAction(${index}, 'detail')" class="px-2.5 py-1 rounded-full bg-white/[0.06] text-zinc-300 border border-white/10 text-[10px] font-bold shrink-0">Đã lưu</button>`;
  } else {
    actionHtml = `<button onclick="event.stopPropagation(); omniTranslationAction(${index}, 'bookmark')" class="px-2.5 py-1 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/30 text-[10px] font-bold hover:bg-amber-500/25 shrink-0">Lưu vào Thư viện</button>`;
  }

  return `
    <div onclick="omniTranslationAction(${index}, 'detail')" class="flex items-center gap-2.5 px-2.5 py-2 rounded-xl hover:bg-white/[0.05] cursor-pointer transition">
      ${omniThumbHtml(omniCover(game), game.title)}
      <div class="min-w-0 flex-1">
        <div class="text-[12px] font-bold text-white truncate">Gói Việt hóa ${omniEsc(game.vietnamese_title || game.title)} <span class="text-[10px] text-amber-300 font-mono">${omniEsc(version)}</span></div>
        <div class="text-[10px] text-zinc-500 truncate">${lines ? omniEsc(lines) + ' · ' : ''}${game.engine ? omniEsc(game.engine) : 'PC Game'}</div>
      </div>
      ${actionHtml}
    </div>
  `;
}

function omniDownloadRow(item, index) {
  const cover = item.cover_url || '';
  const title = String(item.title || '').replace(/[\s,;]+$/, '');
  const sources = (item.sources || []).slice(0, 2).join(' · ');
  const size = item.best_size_gb != null ? `${item.best_size_gb} GB` : '';
  const meta = [sources, size, item.total_repacks ? `${item.total_repacks} nguồn` : ''].filter(Boolean).join(' · ');

  return `
    <div onclick="omniOpenDownload(${index})" class="flex items-center gap-2.5 px-2.5 py-2 rounded-xl hover:bg-white/[0.05] cursor-pointer transition">
      ${omniThumbHtml(cover, title)}
      <div class="min-w-0 flex-1">
        <div class="text-[12px] font-bold text-white truncate">${omniEsc(title)}</div>
        <div class="text-[10px] text-zinc-500 truncate">${omniEsc(meta || 'Kho tải game')}${item.has_viet_mod ? ' · Có Việt hóa' : ''}</div>
      </div>
      <button onclick="event.stopPropagation(); omniOpenDownload(${index})" class="px-2.5 py-1 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 text-[10px] font-bold hover:bg-red-400/25 shrink-0">Tải về</button>
    </div>
  `;
}

function renderOmniDropdown() {
  const box = document.getElementById('omniDropdown');
  if (!box) return;

  if (!omniState.query) {
    box.innerHTML = '';
    box.classList.add('hidden');
    return;
  }

  const libSlice = omniState.library.slice(0, 5);
  const trSlice = omniState.translations.slice(0, 4);
  const dlSlice = omniState.downloads.slice(0, 5);

  let html = '';
  if (libSlice.length) {
    html += omniGroupHtml('📁 Trong Thư Viện Của Bạn', omniState.library.length, libSlice.map((g, i) => omniLibraryRow(g, i)).join(''));
  }
  if (trSlice.length) {
    html += omniGroupHtml('🇻🇳 Kho Gói Việt Hóa', omniState.translations.length, trSlice.map((g, i) => omniTranslationRow(g, i)).join(''));
  }
  if (omniState.loadingDownloads) {
    html += `<div class="px-4 py-3 text-[11px] text-zinc-500 flex items-center gap-2"><i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i> Đang tra Kho Tải Về...</div>`;
  } else if (dlSlice.length) {
    html += omniGroupHtml('🌏 Kho Game Tải Về', omniState.downloads.length, dlSlice.map((g, i) => omniDownloadRow(g, i)).join(''));
  }

  const total = omniState.library.length + omniState.translations.length + omniState.downloads.length;
  if (total > 0) {
    html += `
      <div class="p-2 border-t border-white/[0.06]">
        <button onclick="openSearchResultsPage()" class="w-full flex items-center justify-between px-3 py-2 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] text-[11px] text-zinc-300 transition">
          <span>Xem tất cả ${total} kết quả</span>
          <span class="text-zinc-500">Enter ↵</span>
        </button>
      </div>
    `;
  } else if (!omniState.loadingDownloads) {
    html = `<div class="px-4 py-8 text-center text-[12px] text-zinc-500">Không tìm thấy kết quả cho “${omniEsc(omniState.query)}”.</div>`;
  }

  box.innerHTML = html;
  box.classList.remove('hidden');
  if (window.lucide) lucide.createIcons();
}

function omniCloseDropdown() {
  const box = document.getElementById('omniDropdown');
  if (box) {
    box.classList.add('hidden');
    box.innerHTML = '';
  }
}

// -----------------------------------------------------------------------------
// HÀNH ĐỘNG NHANH
// -----------------------------------------------------------------------------
function omniCloseAll() {
  if (typeof window.closeSearchPanel === 'function') window.closeSearchPanel();
  else omniCloseDropdown();
}

function omniOpenLibrary(index) {
  const game = omniState.library[index];
  if (!game) return;
  omniCloseAll();
  if (typeof openGameModal === 'function') openGameModal(game.id);
}

function omniLibraryAction(index, action) {
  const game = omniState.library[index];
  if (!game) return;
  if (action === 'play' || action === 'install' || action === 'reinstall' || action === 'download') omniCloseAll();
  if (action === 'play') {
    if (typeof launchGame === 'function') launchGame(game.id);
  } else if (action === 'install') {
    if (typeof toggleMod === 'function') toggleMod(game.id);
  } else if (action === 'reinstall') {
    if (typeof toggleMod === 'function') toggleMod(game.id, true);
  } else if (action === 'download') {
    if (typeof bookmarkOpenDownload === 'function') bookmarkOpenDownload(game.id);
  } else if (action === 'install_ghost') {
    omniCloseAll();
    if (typeof installGhostGame === 'function') installGhostGame(game.id);
  } else {
    omniCloseAll();
    if (typeof openGameModal === 'function') openGameModal(game.id);
  }
}

function omniTranslationAction(index, action) {
  const game = omniState.translations[index];
  if (!game) return;
  if (action === 'install' || action === 'reinstall') omniCloseAll();
  if (action === 'install') {
    if (typeof toggleMod === 'function') toggleMod(game.id);
  } else if (action === 'reinstall') {
    if (typeof toggleMod === 'function') toggleMod(game.id, true);
  } else if (action === 'bookmark') {
    if (typeof toggleGameBookmark === 'function') toggleGameBookmark(game.id);
    omniCloseAll();
  } else if (action === 'install_ghost') {
    omniCloseAll();
    if (typeof installGhostGame === 'function') installGhostGame(game.id);
  } else {
    omniCloseAll();
    if (typeof openGameModal === 'function') openGameModal(game.id);
  }
}

function omniOpenDownload(index) {
  const item = omniState.downloads[index];
  if (!item) return;
  omniCloseAll();
  // Mở thẳng bảng chọn bản tải (repack) của game được bấm
  if (typeof openCatalogueDownloadOptionsForGame === 'function') {
    openCatalogueDownloadOptionsForGame(item);
  } else if (typeof openDiscoveryHub === 'function') {
    openDiscoveryHub();
  }
}

// -----------------------------------------------------------------------------
// TRANG KẾT QUẢ ĐẦY ĐỦ (ENTER)
// -----------------------------------------------------------------------------
function openSearchResultsPage() {
  const applyOpen = () => {
  if (!omniState.query) return;
  const view = document.getElementById('viewSearchResults');
  if (!view) return;

  ['viewBrowseGrid', 'viewGameDetail', 'viewDiscovery', 'viewProfile'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.add('hidden');
  });
  view.classList.remove('hidden');

  if (omniResultsQuery !== omniState.query) {
    omniResultsQuery = omniState.query;
    omniState.filter = 'all';
  }

  const queryEl = document.getElementById('searchResultsQuery');
  if (queryEl) queryEl.textContent = omniState.query;

  omniCloseAll();
  if (typeof window.uiSetActiveNav === 'function') window.uiSetActiveNav('search');
  const scroller = document.getElementById('mainScrollContainer');
  if (scroller) scroller.scrollTo({ top: 0 });

  renderSearchResultsPage();
  };

  if (typeof window.withIosViewTransition === 'function') window.withIosViewTransition(applyOpen);
  else applyOpen();
}

function closeSearchResultsPage() {
  if (typeof switchToGridView === 'function') switchToGridView();
}

function omniSetResultFilter(filter) {
  omniState.filter = filter;
  renderSearchResultsPage();
}

function renderSearchResultsPage() {
  const body = document.getElementById('searchResultsBody');
  const chips = document.getElementById('searchResultsChips');
  const summary = document.getElementById('searchResultsSummary');
  if (!body) return;

  const total = omniState.library.length + omniState.translations.length + omniState.downloads.length;
  if (summary) {
    const extra = omniState.loadingDownloads ? ' · đang tải thêm từ Kho Tải Về' : '';
    summary.textContent = `${total} kết quả${extra}`;
  }

  if (chips) {
    const defs = [
      { key: 'all', label: 'Tất cả', count: total },
      { key: 'library', label: 'Thư Viện', count: omniState.library.length },
      { key: 'translations', label: 'Kho Việt Hóa', count: omniState.translations.length },
      { key: 'downloads', label: 'Kho Tải Về', count: omniState.downloads.length }
    ];
    chips.innerHTML = defs.map(def => `
      <button onclick="omniSetResultFilter('${def.key}')" class="pixel-tab ${omniState.filter === def.key ? 'active-filter-tab' : ''} px-3.5 py-1.5 text-xs font-bold transition">
        ${def.label} <span class="opacity-60 font-normal">${def.count}</span>
      </button>
    `).join('');
  }

  let html = '';
  if (omniState.filter === 'all' || omniState.filter === 'library') {
    if (omniState.library.length) {
      html += `<section class="rounded-2xl border border-white/[0.06] bg-[#0F1522] p-3">
        <h3 class="px-2 py-1 text-[11px] font-bold uppercase tracking-wider text-zinc-400">📁 Trong Thư Viện Của Bạn · ${omniState.library.length}</h3>
        <div class="space-y-0.5">${omniState.library.map((g, i) => omniLibraryRow(g, i)).join('')}</div>
      </section>`;
    }
  }
  if (omniState.filter === 'all' || omniState.filter === 'translations') {
    if (omniState.translations.length) {
      html += `<section class="rounded-2xl border border-white/[0.06] bg-[#0F1522] p-3">
        <h3 class="px-2 py-1 text-[11px] font-bold uppercase tracking-wider text-zinc-400">🇻🇳 Kho Gói Việt Hóa · ${omniState.translations.length}</h3>
        <div class="space-y-0.5">${omniState.translations.map((g, i) => omniTranslationRow(g, i)).join('')}</div>
      </section>`;
    }
  }
  if (omniState.filter === 'all' || omniState.filter === 'downloads') {
    if (omniState.downloads.length) {
      html += `<section class="rounded-2xl border border-white/[0.06] bg-[#0F1522] p-3">
        <h3 class="px-2 py-1 text-[11px] font-bold uppercase tracking-wider text-zinc-400">🌏 Kho Game Tải Về · ${omniState.downloads.length}</h3>
        <div class="space-y-0.5">${omniState.downloads.map((g, i) => omniDownloadRow(g, i)).join('')}</div>
      </section>`;
    } else if (omniState.loadingDownloads) {
      html += `<div class="p-6 text-center text-xs text-zinc-500 flex items-center justify-center gap-2"><i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Đang tra Kho Tải Về...</div>`;
    }
  }

  if (!html) {
    html = `<div class="p-12 text-center text-xs text-zinc-500 rounded-2xl border border-dashed border-white/10">Không có kết quả phù hợp với bộ lọc này.</div>`;
  }
  body.innerHTML = html;
  if (window.lucide) lucide.createIcons();
}

// -----------------------------------------------------------------------------
// SỰ KIỆN
// -----------------------------------------------------------------------------
function clearSearch() {
  const input = document.getElementById('searchInput');
  if (input) input.value = '';
  const clearBtn = document.getElementById('clearSearchBtn');
  if (clearBtn) clearBtn.classList.add('hidden');
  omniState.query = '';
  omniState.library = [];
  omniState.translations = [];
  omniState.downloads = [];
  omniState.requestSeq++;
  if (omniState.downloadTimer) clearTimeout(omniState.downloadTimer);
  if (omniState.abortController) omniState.abortController.abort();
  omniCloseDropdown();
  const discView = document.getElementById('viewDiscovery');
  if (discView && !discView.classList.contains('hidden') && typeof onDiscoverySearchInput === 'function') {
    onDiscoverySearchInput('');
  }
}

(function initOmniSearch() {
  const input = document.getElementById('searchInput');
  if (!input) return;

  input.addEventListener('input', (event) => {
    omniRunSearch(event.target.value);
    const discView = document.getElementById('viewDiscovery');
    if (discView && !discView.classList.contains('hidden') && typeof onDiscoverySearchInput === 'function') {
      onDiscoverySearchInput(event.target.value);
    }
  });

  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      openSearchResultsPage();
    } else if (event.key === 'Escape') {
      omniCloseDropdown();
    }
  });

  document.addEventListener('click', (event) => {
    const box = document.getElementById('omniDropdown');
    if (!box || box.classList.contains('hidden')) return;
    const target = event.target;
    if (box.contains(target)) return;
    if (target.closest && target.closest('#searchInline')) return;
    omniCloseDropdown();
  });
})();
