// =============================================================================
// CỔ NGỮ (VIETMODHUB) - DISCOVERY HUB (Tab Khám Phá)
// Ghép 3 nguồn: Steam Trending + Link tải Hydra (.json) + Kho Việt hóa (games.json)
// -----------------------------------------------------------------------------
//  Tầng 1: Hero Banner "Tâm Điểm Tuần Này"
//  Tầng 2: "Mới Lên Kệ Tải Về" (uploadDate mới nhất từ fitgirl/dodi/gog/tinyrepacks)
//  Tầng 3: "Đang Thịnh Hành Trên Thế Giới" (featuredcategories + auto-match link tải)
//  Tầng 4: "Góc Chơi Chung (Co-op / OnlineFix)" + bộ lọc nhanh
//  Trải nghiệm: lazy-load poster 600x900, hover micro-trailer 0.8s, Smart PC Check,
//               nút "Yêu cầu Việt hóa" và "Theo dõi bản tải".
// =============================================================================
let discoveryFeed = null;
let discoveryLoading = false;
let discoveryFilters = { chip: 'all', genre: 'all', trending: 'all', search: '' };
let discoveryLists = { hero: [], recent: [], trending: [], coop: [], suggest: [] };
let discoveryActiveDownloads = [];
let discoveryPosterObserver = null;
let discoveryPosterResolving = new Set();
const discoveryHoverTimers = new Map();
const discoveryTrailerCache = {};
let discoveryActiveGameTitle = '';
let discoveryActiveGameAppid = '';
const DISCOVERY_POSTER_KEY = 'congu_discovery_poster_cache_v2';
// -----------------------------------------------------------------------------
// TIỆN ÍCH
// -----------------------------------------------------------------------------
function discoveryEsc(str) {
  if (typeof escapeHtml === 'function') return escapeHtml(str == null ? '' : String(str));
  return String(str == null ? '' : str).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
/**
 * Chuỗi an toàn để nhúng vào onclick="..." (escape cho cả HTML attribute lẫn JS string),
 * tránh vỡ giao diện với tên game có dấu nháy như "Assassin's Creed".
 */
function discoveryJsArg(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\\/g, '\\\\')
    .replace(/'/g, "\\'")
    .replace(/\r?\n/g, ' ');
}
function discoveryPosterStore() {
  try { return JSON.parse(localStorage.getItem(DISCOVERY_POSTER_KEY) || '{}') || {}; }
  catch (e) { return {}; }
}
function discoveryPosterSave(map) {
  try { localStorage.setItem(DISCOVERY_POSTER_KEY, JSON.stringify(map)); } catch (e) { /* quota */ }
}
function discoveryFormatSize(item) {
  if (!item) return '';
  if (item.file_size) return item.file_size;
  if (item.best_size) return item.best_size;
  return item.size_gb ? item.size_gb + ' GB' : '';
}
function discoveryDateLabel(item) {
  const raw = item.upload_date || item.release_date || '';
  if (!raw) return '';
  if (typeof item.days_ago === 'number') {
    if (item.days_ago <= 0) return 'Hôm nay';
    if (item.days_ago === 1) return 'Hôm qua';
    if (item.days_ago < 30) return item.days_ago + ' ngày trước';
  }
  return raw;
}
// -----------------------------------------------------------------------------
// MỞ / ĐÓNG TAB KHÁM PHÁ
// -----------------------------------------------------------------------------
function openDiscoveryHub() {
  const applyOpen = () => {
  const grid = document.getElementById('viewBrowseGrid');
  const detail = document.getElementById('viewGameDetail');
  const view = document.getElementById('viewDiscovery');
  const profile = document.getElementById('viewProfile');
  const searchResults = document.getElementById('viewSearchResults');
  if (!view) return;
  if (grid) grid.classList.add('hidden');
  if (detail) detail.classList.add('hidden');
  if (profile) profile.classList.add('hidden');
  if (searchResults) searchResults.classList.add('hidden');
  view.classList.remove('hidden');
  const scroller = document.getElementById('mainScrollContainer');
  if (scroller) scroller.scrollTo({ top: 0 });
  if (!discoveryFeed) {
    loadDiscoveryFeed(false);
  } else {
    renderDiscoveryFeed();
  }
  if (window.lucide) lucide.createIcons();
  };
  if (typeof window.withIosViewTransition === 'function') window.withIosViewTransition(applyOpen);
  else applyOpen();
}
function closeDiscoveryHub() {
  const view = document.getElementById('viewDiscovery');
  const grid = document.getElementById('viewBrowseGrid');
  const detail = document.getElementById('viewGameDetail');
  if (view) view.classList.add('hidden');
  if (detail) detail.classList.add('hidden');
  if (grid) grid.classList.remove('hidden');
  if (typeof updateSidebarSelection === 'function') updateSidebarSelection(null);
  const scroller = document.getElementById('mainScrollContainer');
  if (scroller) scroller.scrollTo({ top: 0, behavior: 'smooth' });
  if (window.lucide) lucide.createIcons();
}
// -----------------------------------------------------------------------------
// NẠP DỮ LIỆU
// -----------------------------------------------------------------------------
async function loadDiscoveryFeed(force, silent) {
  if (discoveryLoading) return;
  discoveryLoading = true;
  const statsEl = document.getElementById('discoveryStatsLine');
  if (statsEl && !discoveryFeed) statsEl.textContent = 'Đang tổng hợp Steam + nguồn Hydra + kho Việt hóa...';
  renderDiscoverySkeleton();
  try {
    const res = await fetch('/api/discovery/feed' + (force ? '?refresh=1' : ''));
    const data = await res.json();
    if (data && data.success) {
      discoveryFeed = data;
      renderDiscoveryFeed();
      if (force && !silent) showToast('Đã làm mới dữ liệu Khám Phá!', 'success');
    } else {
      renderDiscoveryError((data && (data.error || data.message)) || 'Không rõ nguyên nhân');
    }
  } catch (e) {
    renderDiscoveryError(e.message || 'Lỗi kết nối');
  } finally {
    discoveryLoading = false;
  }
}
function renderDiscoverySkeleton() {
  const heroWrap = document.getElementById('discoveryHeroWrap');
  if (heroWrap && !discoveryFeed) {
    heroWrap.innerHTML = `<div class="rounded-3xl border border-white/[0.06] bg-[#0F1522] min-h-[260px] flex items-center justify-center">
      <div class="text-center space-y-3">
        <i data-lucide="radar" class="w-9 h-9 text-zinc-600 mx-auto animate-pulse"></i>
        <p class="font-display text-sm text-zinc-300">Đang quét Steam Trending &amp; nguồn tải Hydra...</p>
        <p class="text-[11px] text-zinc-500">Lần đầu mất vài giây, sau đó mở tab tức thì nhờ cache 6 giờ</p>
      </div>
    </div>`;
  }
  ['discoverySuggestGrid', 'discoveryRecentGrid', 'discoveryTrendingGrid', 'discoveryCoopGrid'].forEach(id => {
    const el = document.getElementById(id);
    if (el && !discoveryFeed) {
      el.innerHTML = Array.from({ length: 5 }).map(() => `
        <div class="rounded-[2px] border border-white/5 bg-[#0c0e22] overflow-hidden animate-pulse">
          <div class="aspect-[2/3] bg-white/5"></div>
          <div class="p-2.5 space-y-2"><div class="h-3 bg-white/10 rounded"></div><div class="h-2.5 w-2/3 bg-white/5 rounded"></div></div>
        </div>`).join('');
    }
  });
  if (window.lucide) lucide.createIcons();
}
function renderDiscoveryError(msg) {
  const heroWrap = document.getElementById('discoveryHeroWrap');
  if (heroWrap) {
    heroWrap.innerHTML = `<div class="rounded-2xl border border-rose-500/20 bg-rose-500/[0.06] p-5 flex items-start space-x-3">
      <i data-lucide="alert-triangle" class="w-5 h-5 text-rose-400 shrink-0 mt-0.5"></i>
      <div class="text-xs text-rose-100/80 space-y-2">
        <p class="font-display text-sm text-white">Không nạp được dữ liệu Khám Phá</p>
        <p>${discoveryEsc(msg)}</p>
        <button onclick="loadDiscoveryFeed(true)" class="pixel-btn btn-retro-crimson px-3 py-1.5 text-xs">Thử lại</button>
      </div>
    </div>`;
  }
  if (window.lucide) lucide.createIcons();
}
// -----------------------------------------------------------------------------
// RENDER TỔNG
// -----------------------------------------------------------------------------
function renderDiscoveryFeed() {
  if (!discoveryFeed) return;
  const stats = discoveryFeed.stats || {};
  const statsEl = document.getElementById('discoveryStatsLine');
  if (statsEl) {
    statsEl.innerHTML = `<span class="text-zinc-400 inline-flex items-center gap-1"><i data-lucide="zap" class="w-3 h-3 text-amber-400"></i> ${(stats.repacks || 0).toLocaleString('vi-VN')} bản tải</span>
      <span class="text-zinc-700">•</span>
      <span class="text-zinc-400 inline-flex items-center gap-1"><i data-lucide="languages" class="w-3 h-3 text-red-400"></i> ${stats.vietnamese || 0} bản Việt hóa</span>
      <span class="text-zinc-700">•</span>
      <span class="text-zinc-500">${stats.trending || 0} game hot</span>`;
  }
  renderDiscoveryHero();
  discoveryApplyFilters();
  discoveryNotifyWatchlist();
  if (window.lucide) lucide.createIcons();
  setupDiscoveryHover();
}
// -----------------------------------------------------------------------------
// TẦNG 1: HERO BANNER
// -----------------------------------------------------------------------------
function renderDiscoveryHero() {
  const wrap = document.getElementById('discoveryHeroWrap');
  if (!wrap) return;
  const heroes = (discoveryFeed && discoveryFeed.hero) || [];
  discoveryLists.hero = heroes;
  if (!heroes.length) {
    wrap.innerHTML = `<div class="rounded-2xl border border-white/[0.06] bg-[#0F1522] p-6 text-center">
      <p class="font-display text-sm text-zinc-300">Chưa có tâm điểm nào. Hãy đồng bộ nguồn Hydra rồi bấm nút Làm mới trên thanh Header.</p>
    </div>`;
    return;
  }
  // CHỈ 1 banner lớn duy nhất cho game tiêu điểm đầu tiên
  const featured = heroes[0];
  const bg = featured.hero_url || featured.poster_url || '';
  const appid = featured.steam_appid || '';
  const genres = (featured.genres || []).slice(0, 2);
  wrap.innerHTML = `
    <div class="relative overflow-hidden hero-arcade-frame bg-[#0F1522] min-h-[260px] sm:h-[276px] flex items-center">
      ${bg ? `<div class="absolute inset-0 bg-cover" style="background-image:url('${discoveryEsc(bg)}'); background-position:68% 24%;"></div>` : ''}
      <div class="absolute inset-0" style="background:linear-gradient(90deg, rgba(12,14,18,0.95) 0%, rgba(12,14,18,0.75) 45%, transparent 100%);"></div>
      <div class="absolute inset-x-0 bottom-0 h-24" style="background:linear-gradient(0deg, rgba(10,12,16,0.9) 0%, transparent 100%);"></div>
      <div class="relative z-10 w-full max-w-xl px-5 sm:px-8 py-4 space-y-2">
        <div class="flex flex-wrap items-center gap-1.5">
          <span class="text-[11px] font-medium px-2.5 py-1 rounded-full bg-amber-400/[0.12] text-amber-200 border border-amber-400/25">★ Tâm điểm tuần này</span>
          ${genres.map(g => `<span class="text-[11px] px-2.5 py-1 rounded-full bg-white/[0.06] text-zinc-300 border border-white/[0.08]">${discoveryEsc(g)}</span>`).join('')}
        </div>
        <h2 class="font-display text-2xl sm:text-[30px] font-bold text-white tracking-tight leading-tight line-clamp-2">
          ${discoveryEsc(featured.display_title || featured.title)}
        </h2>
        <p class="text-[12.5px] text-zinc-300/80 line-clamp-2 leading-relaxed max-w-lg">${discoveryEsc(featured.description || 'Chưa có mô tả cho tựa game này.')}</p>
        <div class="flex flex-wrap items-center gap-2 pt-1">
          <button onclick="discoveryHeroAction(0)" class="pixel-btn btn-neon-green px-5 py-2.5 text-sm flex items-center gap-2 rounded-xl">
            <i data-lucide="info" class="w-4 h-4"></i><span>Xem Chi Tiết</span>
          </button>
          <button onclick="discoveryOpenTrailer('${discoveryJsArg(appid)}', '${discoveryJsArg(featured.title)}')" class="px-4 py-2.5 rounded-xl bg-white/[0.08] hover:bg-white/[0.14] text-zinc-100 text-sm flex items-center gap-2 transition">
            <span>▶ Trailer</span>
          </button>
        </div>
      </div>
    </div>`;
}
function renderDiscoverySuggestions() {
  const section = document.getElementById('discoverySuggestSection');
  const grid = document.getElementById('discoverySuggestGrid');
  const countEl = document.getElementById('discoverySuggestCount');
  if (!section || !grid) return;
  const list = (discoveryFeed && Array.isArray(discoveryFeed.recommendations) && discoveryFeed.recommendations.length)
    ? discoveryFeed.recommendations
    : ((discoveryLists.hero || []).slice(1));
  if (!list.length) {
    section.classList.add('hidden');
    grid.innerHTML = '';
    return;
  }
  section.classList.remove('hidden');
  const visible = list.filter(item => discoveryMatchItem(item, 'suggest') || discoveryMatchItem(item, 'hero'));
  discoveryLists.suggest = visible;
  if (countEl) countEl.textContent = `${visible.length} tựa game`;
  grid.innerHTML = visible.length
    ? visible.map((item, i) => discoveryCardHtml(
        Object.assign({}, item, { poster_url: item.poster_url || item.hero_url || '' }),
        'suggest', i, { playOverlay: false }
      )).join('')
    : `<div class="col-span-full py-6 text-center space-y-2">
         <p class="text-xs text-slate-400 font-sans">Không có tựa game nào khớp bộ lọc.</p>
         <button onclick="discoveryResetFilters()" class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500/10 text-red-400 border border-red-400/30 hover:bg-red-500/20 text-xs font-medium transition cursor-pointer">
           <i data-lucide="rotate-ccw" class="w-3.5 h-3.5"></i><span>Xóa toàn bộ bộ lọc</span>
         </button>
       </div>`;
}
function discoveryHeroAction(idx) {
  const h = discoveryLists.hero[idx];
  if (!h) return;
  discoveryOpenDownloads('hero', idx);
}
function discoveryOpenLocalGame(gameId) {
  if (!gameId) return;
  closeDiscoveryHub();
  if (typeof selectSidebarGame === 'function') {
    selectSidebarGame(gameId);
  } else if (typeof openGameModal === 'function') {
    openGameModal(gameId);
  }
}
// -----------------------------------------------------------------------------
// THẺ GAME (dùng chung cho cả 3 tầng danh sách)
// -----------------------------------------------------------------------------
function discoveryCardBadges(item) {
  // Đồng bộ với tab Thư Viện: đúng 1 nhãn • VI ở góc trái trên poster
  if (!item.has_vietnamese) return '';
  return `<span class="inline-flex items-center gap-1.5 px-2 py-1 rounded-full bg-black/60 backdrop-blur-md text-[10px] font-semibold tracking-wide border border-emerald-500/30 text-emerald-300 whitespace-nowrap" title="Đã có Việt hóa trong CỔ NGỮ"><span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>VI</span>`;
}
function discoveryCardHtml(item, kind, idx, opts) {
  opts = opts || {};
  let poster = item.poster_url || '';
  const header = item.header_url || item.hero_url || '';
  const appid = item.steam_appid || '';
  const title = item.title || 'Không rõ tên';


  // Tối ưu hóa ảnh bìa dọc 2:3 chuẩn vừa vặn cho toàn bộ card
  if ((!poster || poster.includes('/api/game/poster_preview') || poster.includes('header.jpg')) && appid && /^\d+$/.test(String(appid))) {
    poster = `https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/${appid}/library_600x900.jpg`;
  }
  const sub = item.has_vietnamese && item.vietnamese_title ? item.vietnamese_title : '';
  const repackers = (item.repackers || (item.repacker ? [item.repacker] : [])).slice(0, 3).join(' · ');
  const metaBits = [];
  if (repackers) metaBits.push(repackers);
  const size = discoveryFormatSize(item);
  if (size) metaBits.push(size);
  const dateLabel = discoveryDateLabel(item);
  if (dateLabel) metaBits.push(dateLabel);
  const initialImg = poster || header;
  const posterInner = initialImg
    ? `<img src="${discoveryEsc(initialImg)}" data-appid="${discoveryEsc(appid)}" data-header="${discoveryEsc(header)}" data-title="${discoveryEsc(title)}" alt="${discoveryEsc(title)}"
         class="discovery-poster-img w-full h-full object-cover" loading="lazy" onerror="discoveryImgFallback(this)" />`
    : `<div class="discovery-poster-skeleton flex items-center justify-center">
         <i data-lucide="loader-2" class="w-5 h-5 text-[#FF2A55]/60 animate-spin"></i>
       </div>`;
  return `
  <div class="discovery-card group relative rounded-2xl bg-[#0F1522] border border-white/[0.06] hover:border-red-500/40 hover:-translate-y-1 overflow-hidden transition-all duration-300 cursor-pointer" onclick="discoveryOpenGameDetail('${kind}', ${idx})">
    <div class="discovery-card-poster relative aspect-[2/3] overflow-hidden bg-[#0F1522] ${poster ? '' : 'discovery-need-poster'}"
         ${poster ? '' : `data-poster-query="${discoveryEsc(title)}"`}
         data-steam-appid="${discoveryEsc(appid)}">
      ${posterInner}
      ${discoveryCardBadges(item) ? `<div class="absolute left-1.5 top-1.5 z-20">${discoveryCardBadges(item)}</div>` : ''}
      <div class="discovery-card-actions absolute right-1.5 top-1.5 z-20 flex items-center gap-1">
        <button onclick="event.stopPropagation(); discoveryToggleBookmark('${discoveryJsArg(title)}', '${discoveryJsArg(appid)}', '${discoveryJsArg(poster)}', this)"
                class="w-6 h-6 rounded-full flex items-center justify-center border transition ${discoveryIsBookmarked(title, appid) ? 'bg-red-500/30 border-red-400 text-red-100' : 'bg-black/60 border-white/15 text-zinc-300 hover:text-red-300 hover:border-red-400/60'}"
                title="${discoveryIsBookmarked(title, appid) ? 'Bỏ khỏi Thư viện (Chưa tải)' : 'Thêm vào Thư viện để tải sau'}">
          <i data-lucide="bookmark${discoveryIsBookmarked(title, appid) ? '-check' : '-plus'}" class="w-3 h-3"></i>
        </button>
        <button onclick="event.stopPropagation(); discoveryToggleWatch('${discoveryJsArg(title)}', '${discoveryJsArg(appid)}', '${discoveryJsArg(poster)}')"
                class="w-6 h-6 rounded-full flex items-center justify-center border transition ${discoveryIsWatching(title) ? 'bg-amber-500/30 border-amber-400 text-amber-200' : 'bg-black/60 border-white/15 text-zinc-300 hover:text-amber-300 hover:border-amber-400/60'}"
                title="${discoveryIsWatching(title) ? 'Bỏ theo dõi tựa game này' : 'Theo dõi để nhận thông báo khi có bản tải / Việt hóa'}">
          <i data-lucide="bell${discoveryIsWatching(title) ? '-ring' : ''}" class="w-3 h-3"></i>
        </button>
      </div>
      <div class="absolute inset-0 bg-gradient-to-t from-[#0A0E1A] via-transparent to-transparent opacity-70 pointer-events-none"></div>
      ${opts.playOverlay === false ? '' : `<button onclick="discoveryOpenTrailer('${discoveryJsArg(appid)}', '${discoveryJsArg(title)}')"
        class="discovery-play-btn absolute inset-0 m-auto w-11 h-11 rounded-full bg-black/60 border border-white/15 text-zinc-100 flex items-center justify-center opacity-0 group-hover:opacity-100 transition"
        title="Xem trailer">
        <i data-lucide="play" class="w-5 h-5 fill-current"></i>
      </button>`}
    </div>
    <div class="p-2.5 space-y-1.5">
      <h4 class="font-display text-xs font-bold text-white line-clamp-1" title="${discoveryEsc(title)}">${discoveryEsc(title)}</h4>
      ${sub ? `<p class="font-pixel text-[9px] text-amber-300/90 line-clamp-1">${discoveryEsc(sub)}</p>` : ''}
      <p class="text-[10px] text-slate-400 line-clamp-1">${discoveryEsc(metaBits.join(' · ') || 'Kho CỔ NGỮ')}</p>
      <div class="flex items-center gap-1.5 pt-0.5">
        <button onclick="event.stopPropagation(); discoveryOpenDownloads('${kind}', ${idx})" class="pixel-btn flex-1 px-2 py-1.5 text-[10px] font-bold bg-[#240C12] text-[#FF2A55] border border-[#FF2A55]/40 hover:border-[#FF2A55] flex items-center justify-center space-x-1" title="Xem danh sách nguồn tải Repack">
          <i data-lucide="download" class="w-3 h-3"></i><span>Tải</span>
        </button>
        <button onclick="event.stopPropagation(); discoveryOpenTrailer('${discoveryJsArg(appid)}', '${discoveryJsArg(title)}')" class="pixel-btn px-2 py-1.5 text-[10px] bg-[#1C2536] text-[#FF2A55] border border-[#FF2A55]/30 hover:border-[#FF2A55]" title="Xem trailer">
          <i data-lucide="film" class="w-3 h-3"></i>
        </button>
        ${item.has_vietnamese
          ? (item.viet_game_id ? `<button onclick="event.stopPropagation(); discoveryOpenLocalGame('${discoveryJsArg(item.viet_game_id)}')" class="pixel-btn px-2 py-1.5 text-[10px] bg-[#1c1405] text-amber-300 border border-amber-500/40 hover:border-amber-400" title="Mở bản Việt hóa trong Thư viện"><i data-lucide="library" class="w-3 h-3"></i></button>` : '')
          : `<button onclick="event.stopPropagation(); discoveryRequestViet('${discoveryJsArg(title)}', '${discoveryJsArg(appid)}')" class="pixel-btn px-2 py-1.5 text-[10px] bg-[#240C12] text-red-300 border border-[#FF2A55]/40 hover:border-[#FF2A55]" title="Yêu cầu Việt hóa"><i data-lucide="flame" class="w-3 h-3"></i></button>`}
      </div>
    </div>
  </div>`;
}
function renderProceduralCover(parent, title, appid) {
  if (!parent) return;
  const gradients = [
    'from-[#1A102F] via-[#2A1545] to-[#0A0E1A]',
    'from-[#0A2540] via-[#0F3550] to-[#061524]',
    'from-[#24131E] via-[#381827] to-[#0E070B]',
    'from-[#132A18] via-[#1B3620] to-[#071309]',
    'from-[#2B1E05] via-[#3D2908] to-[#120C02]',
    'from-[#1B1B3A] via-[#25204D] to-[#0C0C1A]',
  ];
  let hash = 0;
  for (let i = 0; i < (title || '').length; i++) {
    hash = (hash << 5) - hash + title.charCodeAt(i);
    hash |= 0;
  }
  const grad = gradients[Math.abs(hash) % gradients.length];
  parent.innerHTML = `
    <div class="w-full h-full bg-gradient-to-br ${grad} p-3.5 flex flex-col justify-between relative overflow-hidden select-none">
      <div class="absolute -top-10 -right-10 w-28 h-28 rounded-full bg-red-400/15 blur-2xl pointer-events-none"></div>
      <div class="absolute -bottom-10 -left-10 w-28 h-28 rounded-full bg-purple-500/15 blur-2xl pointer-events-none"></div>
      <div class="flex items-center justify-between z-10">
        <span class="text-[9px] font-pixel px-2 py-0.5 rounded bg-black/40 text-red-300 border border-red-400/30 backdrop-blur-sm">STEAM</span>
        <div class="w-6 h-6 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center text-zinc-300 backdrop-blur-sm">
          <i data-lucide="gamepad-2" class="w-3.5 h-3.5 text-red-400"></i>
        </div>
      </div>
      <div class="z-10 py-2 text-center space-y-1">
        <div class="w-8 h-1 bg-gradient-to-r from-red-400 to-purple-500 rounded-full mx-auto mb-1.5 opacity-80"></div>
        <h3 class="font-display text-xs sm:text-[13px] font-extrabold text-white leading-snug tracking-wide uppercase drop-shadow-[0_2px_8px_rgba(0,0,0,0.8)] line-clamp-3 px-1">
          ${discoveryEsc(title)}
        </h3>
      </div>
      <div class="z-10 flex items-center justify-between pt-1.5 border-t border-white/10 text-[9px] text-zinc-400 font-mono">
        <span class="truncate">ID: ${discoveryEsc(appid || 'GAME')}</span>
        <span class="text-red-400 font-bold">★ CỔ NGỮ</span>
      </div>
    </div>
  `;
  if (window.lucide) lucide.createIcons();
}
function discoveryImgFallback(img) {
  const appid = img.getAttribute('data-appid') || '';
  const header = img.getAttribute('data-header') || '';
  const title = img.getAttribute('data-title') || img.alt || '';
  const stage = parseInt(img.getAttribute('data-stage') || '0', 10);
  // 1. Thử Akamai CDN 600x900_2x nếu 600x900 bị lỗi mạng tạm thời
  if (stage === 0 && appid) {
    img.setAttribute('data-stage', '1');
    img.src = `https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/${appid}/library_600x900_2x.jpg`;
    return;
  }
  // 2. Thử local proxy poster_preview
  if (stage <= 1 && header) {
    img.setAttribute('data-stage', '2');
    img.src = `/api/game/poster_preview?url=${encodeURIComponent(header)}`;
    return;
  }
  // 3. Thử Akamai CDN header
  if (stage === 2 && appid) {
    img.setAttribute('data-stage', '3');
    img.src = `https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/${appid}/header.jpg`;
    return;
  }
  // 4. Thử Capsule 616x353
  if (stage === 3 && appid) {
    img.setAttribute('data-stage', '4');
    img.src = `https://cdn.akamai.steamstatic.com/steam/apps/${appid}/capsule_616x353.jpg`;
    return;
  }
  // 5. Thất bại toàn bộ (VD máy mất mạng): Tự động tạo Cover Tĩnh Nghệ Thuật (Procedural Glassmorphism Card)
  // Tuyệt đối không để ô đen hay icon gạch chéo hỏng!
  const parent = img.parentElement;
  if (parent) {
    img.remove();
    renderProceduralCover(parent, title, appid);
  }
}
// -----------------------------------------------------------------------------
// BỘ LỌC NHANH
// -----------------------------------------------------------------------------
function discoveryMatchItem(item, kind) {
  const f = discoveryFilters;
  const sizeGb = (item.size_gb != null) ? item.size_gb : (item.best_size_gb != null ? item.best_size_gb : null);
  const hasDownload = !!(item.has_download || item.uri || (item.downloads && item.downloads.length));
  if (f.chip === 'light' && !(sizeGb != null && sizeGb > 0 && sizeGb <= 5)) return false;
  if (f.chip === 'portable' && !(item.is_portable || (item.repackers || []).concat(item.repacker ? [item.repacker] : []).some(r => /gog|portable/i.test(String(r))))) return false;
  if (f.chip === 'viet' && !item.has_vietnamese) return false;
  if (f.chip === 'download' && !hasDownload) return false;
  if (f.chip === 'coop' && !item.is_onlinefix) return false;
  if (f.genre !== 'all') {
    const g = f.genre.toLowerCase();
    const genres = (item.genres || []).map(x => String(x).toLowerCase());
    if (!genres.some(x => x.indexOf(g) >= 0)) return false;
  }
  if (kind === 'trending') {
    if (f.trending === 'download' && !hasDownload) return false;
    if (f.trending === 'viet' && !item.has_vietnamese) return false;
    if (f.trending === 'top' && !(item.categories || []).includes('Bán chạy nhất')) return false;
    if (f.trending === 'new' && !(item.categories || []).includes('Mới phát hành')) return false;
  }
  if (f.search) {
    const q = f.search.toLowerCase().trim();
    const title = String(item.title || item.display_title || '').toLowerCase();
    const vietTitle = String(item.vietnamese_title || '').toLowerCase();
    const desc = String(item.description || '').toLowerCase();
    const rep = String(item.repacker || '').toLowerCase();
    let matched = title.includes(q) || vietTitle.includes(q) || desc.includes(q) || rep.includes(q);
    if (!matched) {
      // Fuzzy so khớp token (VD gõ "eden ring" vẫn khớp "Elden Ring")
      const tokens = q.split(/\s+/).filter(Boolean);
      matched = tokens.length > 0 && tokens.every(tok => {
        if (title.includes(tok) || vietTitle.includes(tok)) return true;
        const words = (title + ' ' + vietTitle).split(/[\s:_\-\[\]\(\)\.\,\+]+/);
        return words.some(w => {
          if (w === tok) return true;
          if (w.length >= 4 && tok.length >= 4 && w[0] === tok[0]) {
            let common = 0;
            for (let ch of tok) { if (w.includes(ch)) common++; }
            return (common / Math.max(w.length, tok.length)) >= 0.70;
          }
          return false;
        });
      });
    }
    if (!matched) return false;
  }
  return true;
}
function discoveryEmptyFilterHtml(msg) {
  return `
    <div class="col-span-full py-8 text-center space-y-2">
      <p class="text-xs text-slate-400 font-sans">${discoveryEsc(msg || 'Không có tựa game nào khớp bộ lọc hiện tại.')}</p>
      <button onclick="discoveryResetFilters()" class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500/10 text-red-400 border border-red-400/30 hover:bg-red-500/20 text-xs font-medium transition cursor-pointer">
        <i data-lucide="rotate-ccw" class="w-3.5 h-3.5"></i><span>Xóa toàn bộ bộ lọc</span>
      </button>
    </div>
  `;
}
function discoveryApplyFilters() {
  if (!discoveryFeed) return;
  // Tầng 2: Mới lên kệ (repack từ nguồn Hydra)
  const recent = (discoveryFeed.recent_repacks || []).filter(it => discoveryMatchItem(it, 'recent'));
  discoveryLists.recent = recent;
  const recentGrid = document.getElementById('discoveryRecentGrid');
  if (recentGrid) {
    recentGrid.innerHTML = recent.length
      ? recent.map((it, i) => discoveryCardHtml(it, 'recent', i)).join('')
      : discoveryEmptyFilterHtml('Không có bản tải nào khớp bộ lọc.');
  }
  // Tầng 3: Steam Trending
  const trending = (discoveryFeed.steam_trending || []).filter(it => discoveryMatchItem(it, 'trending'));
  discoveryLists.trending = trending;
  const trendingGrid = document.getElementById('discoveryTrendingGrid');
  if (trendingGrid) {
    trendingGrid.innerHTML = trending.length
      ? trending.map((it, i) => discoveryCardHtml(it, 'trending', i)).join('')
      : discoveryEmptyFilterHtml('Không có tựa game nào khớp bộ lọc hiện tại.');
  }
  // Tầng 4: Co-op / OnlineFix
  const coop = (discoveryFeed.online_coop || []).filter(it => discoveryMatchItem(it, 'coop'));
  discoveryLists.coop = coop;
  const coopGrid = document.getElementById('discoveryCoopGrid');
  if (coopGrid) {
    coopGrid.innerHTML = coop.length
      ? coop.map((it, i) => discoveryCardHtml(it, 'coop', i)).join('')
      : (discoveryFeed.online_coop && discoveryFeed.online_coop.length
          ? discoveryEmptyFilterHtml('Không có bản Co-op nào khớp bộ lọc hiện tại.')
          : `<div class="col-span-full rounded-[2px] border border-[#FF2A55]/20 bg-[#0c0e22] p-5 text-center space-y-2">
               <p class="text-xs text-slate-300 font-sans">Chưa có bản Co-op / OnlineFix nào trong cache nguồn.</p>
               <p class="text-[11px] text-slate-500">Thêm nguồn <span class="text-[#FF2A55] font-mono-tech">onlinefix.json</span> rồi đồng bộ để nhóm bạn cùng chơi.</p>
             </div>`);
  }
  renderDiscoverySuggestions();
  if (window.lucide) lucide.createIcons();
  setupDiscoveryPosterObserver();
  setupDiscoveryHover();
}
function discoveryResetFilters() {
  discoveryFilters = { chip: 'all', genre: 'all', trending: 'all', search: '' };
  const searchInput = document.getElementById('searchInput');
  if (searchInput) searchInput.value = '';
  const sel = document.getElementById('discoveryGenreSelect');
  if (sel) sel.value = 'all';
  document.querySelectorAll('[data-discovery-chip]').forEach(btn => {
    btn.classList.toggle('active-filter-tab', btn.getAttribute('data-discovery-chip') === 'all');
  });
  document.querySelectorAll('[data-discovery-trending]').forEach(btn => {
    btn.classList.toggle('active-filter-tab', btn.getAttribute('data-discovery-trending') === 'all');
  });
  discoveryApplyFilters();
}
function onDiscoverySearchInput(val) {
  discoveryFilters.search = (val || '').trim();
  discoveryApplyFilters();
}
function discoverySetChip(chip) {
  discoveryFilters.chip = chip;
  document.querySelectorAll('[data-discovery-chip]').forEach(btn => {
    btn.classList.toggle('active-filter-tab', btn.getAttribute('data-discovery-chip') === chip);
  });
  discoveryApplyFilters();
}
function discoverySetGenre(genre) {
  discoveryFilters.genre = genre;
  const sel = document.getElementById('discoveryGenreSelect');
  if (sel) sel.value = genre;
  discoveryApplyFilters();
}
function discoverySetTrendingTab(tab) {
  discoveryFilters.trending = tab;
  document.querySelectorAll('[data-discovery-trending]').forEach(btn => {
    btn.classList.toggle('active-filter-tab', btn.getAttribute('data-discovery-trending') === tab);
  });
  discoveryApplyFilters();
}
// -----------------------------------------------------------------------------
// LAZY-LOAD POSTER 600x900 (IntersectionObserver + cache localStorage)
// -----------------------------------------------------------------------------
function setupDiscoveryPosterObserver() {
  const nodes = document.querySelectorAll('#viewDiscovery .discovery-need-poster');
  if (!nodes.length) return;
  if (!('IntersectionObserver' in window)) {
    nodes.forEach(n => resolveDiscoveryPoster(n));
    return;
  }
  if (!discoveryPosterObserver) {
    const rootEl = document.getElementById('mainScrollContainer');
    discoveryPosterObserver = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          discoveryPosterObserver.unobserve(entry.target);
          resolveDiscoveryPoster(entry.target);
        }
      });
    }, { root: rootEl || null, rootMargin: '400px 0px' });
  }
  nodes.forEach(n => discoveryPosterObserver.observe(n));
}
async function resolveDiscoveryPoster(el) {
  if (!el || el.dataset.resolved === '1') return;
  const query = el.getAttribute('data-poster-query');
  if (!query) return;
  const key = query.toLowerCase().trim();
  if (discoveryPosterResolving.has(key)) return;
  el.dataset.resolved = '1';
  const cache = discoveryPosterStore();
  let hit = cache[key];
  if (!hit) {
    discoveryPosterResolving.add(key);
    try {
      const res = await fetch('/api/game/search_avatar?q=' + encodeURIComponent(query));
      const list = await res.json();
      const best = Array.isArray(list) ? list.find(x => x && (x.avatar_url || x.header_url || x.steam_appid)) : null;
      if (best) {
        const appid = String(best.steam_appid || '');
        const posterUrl = (appid && /^\d+$/.test(appid))
          ? `https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/${appid}/library_600x900.jpg`
          : (best.avatar_url || best.header_url || '');
        hit = {
          avatar_url: posterUrl,
          header_url: best.header_url || '',
          steam_appid: appid
        };
        cache[key] = hit;
        discoveryPosterSave(cache);
      }
    } catch (e) { /* im lặng */ }
    discoveryPosterResolving.delete(key);
  }
  if (!hit || (!hit.avatar_url && !hit.header_url)) {
    el.classList.add('discovery-poster-missing');
    return;
  }
  const title = query;
  const img = document.createElement('img');
  img.className = 'discovery-poster-img w-full h-full object-cover';
  img.loading = 'lazy';
  img.alt = title;
  img.setAttribute('data-appid', hit.steam_appid || '');
  img.setAttribute('data-header', hit.header_url || '');
  img.setAttribute('onerror', 'discoveryImgFallback(this)');
  img.src = hit.avatar_url || hit.header_url;
  const skeleton = el.querySelector('.discovery-poster-skeleton');
  if (skeleton) skeleton.remove();
  el.insertBefore(img, el.firstChild);
  const appid = hit.steam_appid || '';
  if (appid) {
    el.setAttribute('data-steam-appid', appid);
    const card = el.closest('.discovery-card');
    if (card) card.setAttribute('data-steam-appid', appid);
    const playBtn = el.querySelector('.discovery-play-btn');
    if (playBtn) playBtn.setAttribute('onclick', `discoveryOpenTrailer('${discoveryJsArg(appid)}', '${discoveryJsArg(title)}')`);
  }
}
// -----------------------------------------------------------------------------
// HOVER MICRO-TRAILER (0.8 giây)
// -----------------------------------------------------------------------------
function setupDiscoveryHover() {
  document.querySelectorAll('#viewDiscovery .discovery-card').forEach(card => {
    if (card.dataset.hoverBound === '1') return;
    card.dataset.hoverBound = '1';
    card.addEventListener('mouseenter', () => discoveryHoverStart(card));
    card.addEventListener('mouseleave', () => discoveryHoverStop(card));
  });
}
function discoveryHoverPoster(card) {
  return card.querySelector('.discovery-card-poster');
}
function discoveryHoverStart(card) {
  const poster = discoveryHoverPoster(card);
  if (!poster) return;
  const appid = poster.getAttribute('data-steam-appid') || card.getAttribute('data-steam-appid') || '';
  if (!appid || !/^\d+$/.test(appid)) return;
  if (discoveryHoverTimers.has(poster)) clearTimeout(discoveryHoverTimers.get(poster));
  const timer = setTimeout(() => discoveryPlayPreview(poster, appid), 800);
  discoveryHoverTimers.set(poster, timer);
}
function discoveryHoverStop(card) {
  const poster = discoveryHoverPoster(card);
  if (!poster) return;
  if (discoveryHoverTimers.has(poster)) {
    clearTimeout(discoveryHoverTimers.get(poster));
    discoveryHoverTimers.delete(poster);
  }
  const video = poster.querySelector('.discovery-hover-video-el');
  if (video) {
    try { video.pause(); } catch (e) { /* noop */ }
    video.remove();
  }
}
async function discoveryPlayPreview(poster, appid) {
  if (!poster.isConnected) return;
  let clipUrl = discoveryTrailerCache[appid];
  if (clipUrl === undefined) {
    try {
      const res = await fetch('/api/discovery/trailer?appid=' + encodeURIComponent(appid) + '&seconds=10');
      const data = await res.json();
      clipUrl = (data && data.success) ? data.clip_url : '';
    } catch (e) {
      clipUrl = '';
    }
    discoveryTrailerCache[appid] = clipUrl || '';
  }
  if (!clipUrl || !poster.isConnected) return;
  const video = document.createElement('video');
  video.className = 'discovery-hover-video-el';
  video.src = clipUrl;
  video.muted = true;
  video.loop = true;
  video.autoplay = true;
  video.playsInline = true;
  video.setAttribute('muted', '');
  video.setAttribute('playsinline', '');
  video.addEventListener('error', () => video.remove());
  poster.appendChild(video);
  const play = video.play();
  if (play && typeof play.catch === 'function') play.catch(() => { /* autoplay policy */ });
}
// -----------------------------------------------------------------------------
// MODAL CHỌN NGUỒN TẢI
// -----------------------------------------------------------------------------
async function discoveryOpenDownloads(kind, idx) {
  const item = (discoveryLists[kind] || [])[idx];
  if (!item) {
    console.warn('[Discovery] Không tìm thấy game:', kind, idx);
    showToast('Không tìm thấy thông tin tựa game!', 'error');
    return;
  }
  discoveryActiveGameTitle = item.title || '';
  discoveryActiveGameAppid = item.steam_appid || '';
  let downloads = (item.downloads || []).slice();
  if (!downloads.length && item.uri) {
    downloads = [{
      title: item.release_title || item.title,
      repacker: item.repacker || 'Repack',
      file_size: item.file_size,
      upload_date: item.upload_date,
      uri: item.uri,
      is_portable: item.is_portable,
      is_onlinefix: item.is_onlinefix
    }];
  }
  // Nếu game chưa có sẵn downloads trong cache -> tự động truy vấn tức thời /api/hydra/search
  if (!downloads.length) {
    showToast(`Đang quét nguồn Repack cho "${item.title}"...`, 'info');
    try {
      const res = await fetch('/api/hydra/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: item.title || '',
          steam_appid: item.steam_appid || '',
          game_id: item.viet_game_id || ''
        })
      });
      const data = await res.json();
      if (data && Array.isArray(data.results) && data.results.length > 0) {
        downloads = data.results.map(r => ({
          title: r.title || item.title,
          repacker: r.repacker || r.source_name || 'Repack',
          file_size: r.file_size || 'N/A',
          upload_date: r.upload_date || '',
          uri: r.uri || (r.uris && r.uris[0]) || '',
          uris: r.uris || (r.uri ? [r.uri] : []),
          is_portable: Boolean(r.is_portable),
          is_onlinefix: Boolean(r.is_onlinefix)
        })).filter(d => Boolean(d.uri));
        item.downloads = downloads;
      }
    } catch (e) {
      console.warn('[Discovery] Lỗi quét repack nhanh:', e);
    }
  }
  discoveryActiveDownloads = downloads;
  if (downloads.length > 0) {
    discoveryOpenDownloadsModal(kind, idx);
    return;
  }
  showToast('Chưa có link tải trực tiếp cho tựa game này.', 'warning');
}
function discoveryOpenDownloadsModal(kind, idx) {
  const item = (discoveryLists[kind] || [])[idx];
  if (!item) return;
  discoveryActiveGameTitle = item.title || '';
  discoveryActiveGameAppid = item.steam_appid || '';
  let downloads = (discoveryActiveDownloads && discoveryActiveDownloads.length)
    ? discoveryActiveDownloads
    : ((item.downloads || []).slice());
  if (!downloads.length && item.uri) {
    downloads = [{
      title: item.release_title || item.title,
      repacker: item.repacker || 'Repack',
      file_size: item.file_size,
      upload_date: item.upload_date,
      uri: item.uri,
      is_portable: item.is_portable,
      is_onlinefix: item.is_onlinefix
    }];
  }
  discoveryActiveDownloads = downloads;
  const modal = document.getElementById('discoveryDownloadModal');
  const titleEl = document.getElementById('discoveryDownloadTitle');
  const subEl = document.getElementById('discoveryDownloadSubtitle');
  const listEl = document.getElementById('discoveryDownloadList');
  if (!modal || !listEl) return;
  if (titleEl) titleEl.textContent = item.title || 'Nguồn tải game';
  if (subEl) {
    subEl.textContent = [
      downloads.length ? `${downloads.length} nguồn có sẵn` : '',
      discoveryFormatSize(item) ? 'Dung lượng ' + discoveryFormatSize(item) : ''
    ].filter(Boolean).join('  •  ');
  }
  listEl.innerHTML = downloads.length ? downloads.map((d, i) => {
    const badges = [
      d.is_portable ? '<span class="text-[10px] font-bold px-2 py-0.5 rounded-[4px] bg-red-500/15 text-red-300 border border-red-500/30">PORTABLE</span>' : '',
      d.is_onlinefix ? '<span class="text-[10px] font-bold px-2 py-0.5 rounded-[4px] bg-pink-500/15 text-pink-300 border border-pink-500/30">ONLINE FIX</span>' : ''
    ].filter(Boolean).join(' ');
    return `
    <div class="p-4 rounded-[6px] bg-[#0D1322] border border-white/[0.08] hover:border-red-500/40 transition space-y-3">
      <div class="flex items-start justify-between gap-2">
        <div class="min-w-0 space-y-1">
          <div class="flex items-center gap-2">
            <span class="text-xs font-bold text-white tracking-wide uppercase">Nguồn: ${discoveryEsc(d.repacker || 'Nguồn Tải')}</span>
            ${badges}
          </div>
          <p class="text-xs text-zinc-300 font-medium truncate" title="${discoveryEsc(d.title || item.title)}">
            ${discoveryEsc(d.title || item.title)}
          </p>
          <p class="text-[11px] text-zinc-400 font-mono">
            ${discoveryEsc(d.file_size || 'Dung lượng gốc')} · ${discoveryEsc((d.upload_date || '').slice(0, 10) || 'Mới cập nhật')}
          </p>
        </div>
      </div>
      <div class="flex items-center gap-2 pt-0.5">
        <button onclick="discoveryOpenExternalRow(${i})" class="pixel-btn flex-1 py-2 px-3 text-xs font-bold bg-[#FF2A55] hover:bg-[#38bdf8] text-black rounded-[4px] shadow-[0_0_15px_rgba(255, 42, 85,0.35)] flex items-center justify-center gap-2 transition cursor-pointer" title="Mở link tải bằng ứng dụng ngoài (qBittorrent / BitTorrent / Trình duyệt)">
          <i data-lucide="external-link" class="w-3.5 h-3.5 stroke-[2.5]"></i>
          <span>Torrent ngoài</span>
        </button>
        <button onclick="discoveryCopyRow(${i})" class="pixel-btn px-3 py-2 text-xs font-medium bg-white/[0.06] hover:bg-white/[0.12] text-slate-300 hover:text-white border border-white/10 rounded-[4px] flex items-center gap-1.5 transition cursor-pointer" title="Sao chép link tải (Magnet / URL)">
          <i data-lucide="copy" class="w-3.5 h-3.5"></i>
          <span>Sao chép</span>
        </button>
      </div>
    </div>`;
  }).join('') : '<p class="text-xs text-slate-400 text-center py-6">Chưa có link tải trực tiếp cho tựa game này.</p>';
  modal.classList.remove('hidden');
  if (window.lucide) lucide.createIcons();
}
function discoveryCloseDownloadModal() {
  const modal = document.getElementById('discoveryDownloadModal');
  if (modal) modal.classList.add('hidden');
}
function discoveryStartDownloadRow(rowIdx) {
  const d = discoveryActiveDownloads[rowIdx];
  if (!d || !d.uri) {
    showToast('Không tìm thấy link tải hợp lệ!', 'error');
    return;
  }
  startRepackDownload(encodeURIComponent(d.uri), d.title || discoveryActiveGameTitle || 'download');
}
function discoveryOpenExternalRow(rowIdx) {
  const d = (discoveryActiveDownloads || [])[rowIdx];
  if (!d || !d.uri) {
    if (typeof showToast === 'function') showToast('Không tìm thấy link tải!', 'warning');
    return;
  }
  const dlTitle = d.title || discoveryActiveGameTitle || 'Game';
  if (typeof openExternalTorrentLink === 'function') {
    openExternalTorrentLink(encodeURIComponent(d.uri), encodeURIComponent(dlTitle));
  } else {
    fetch('/api/torrent/open_external', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uri: d.uri, title: dlTitle })
    }).then(r => r.json()).then(data => {
      if (data && data.success) {
        showToast(data.message || 'Đã chuyển liên kết tới ứng dụng ngoài của máy!', 'success');
      } else {
        showToast(data ? data.message : 'Không thể mở phần mềm ngoài', 'error');
      }
    }).catch(err => {
      showToast('Lỗi: ' + err.message, 'error');
    });
  }
}
function discoveryCopyRow(rowIdx) {
  const d = discoveryActiveDownloads[rowIdx];
  if (!d || !d.uri) return;
  discoveryCopyText(d.uri);
}
function discoveryCopyText(text) {
  const done = () => showToast('Đã sao chép link tải vào clipboard!', 'success');
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => showToast('Không sao chép được link.', 'error'));
    return;
  }
  const ta = document.createElement('textarea');
  ta.value = text;
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand('copy'); done(); } catch (e) { showToast('Không sao chép được link.', 'error'); }
  ta.remove();
}
async function discoveryRunPcCheck(appid) {
  const el = document.getElementById('discoveryPcCheckText');
  if (el) el.textContent = 'Đang đọc cấu hình máy và yêu cầu của game...';
  try {
    const res = await fetch('/api/discovery/pc_check?steam_appid=' + encodeURIComponent(appid));
    const data = await res.json();
    if (el) {
      el.textContent = (data && data.message) || 'Không đọc được cấu hình.';
      el.className = 'text-[11px] font-sans ' + (data.status === 'weak' ? 'text-amber-300' : (data.status === 'unknown' ? 'text-slate-400' : 'text-[#34D399]'));
      if (data && data.system) {
        el.textContent += `  (CPU: ${data.system.cpu || 'N/A'} • GPU: ${data.system.gpu || 'N/A'})`;
      }
    }
  } catch (e) {
    if (el) el.textContent = 'Không đọc được cấu hình máy: ' + e.message;
  }
}
// -----------------------------------------------------------------------------
// MODAL TRAILER
// -----------------------------------------------------------------------------
async function discoveryOpenTrailer(appid, title) {
  const modal = document.getElementById('discoveryTrailerModal');
  const video = document.getElementById('discoveryTrailerVideo');
  const titleEl = document.getElementById('discoveryTrailerTitle');
  const statusEl = document.getElementById('discoveryTrailerStatus');
  const ytBtn = document.getElementById('discoveryTrailerYoutubeBtn');
  if (!modal) return;
  discoveryActiveGameTitle = title || '';
  discoveryActiveGameAppid = appid || '';
  if (titleEl) titleEl.textContent = title || 'Trailer';
  if (ytBtn) {
    ytBtn.setAttribute('onclick', `openExternalUrl('https://www.youtube.com/results?search_query=${encodeURIComponent((title || '') + ' trailer')}')`);
  }
  if (video) { try { video.pause(); } catch (e) {} video.removeAttribute('src'); video.load(); }
  if (statusEl) statusEl.textContent = 'Đang tải trailer...';
  modal.classList.remove('hidden');
  if (window.lucide) lucide.createIcons();
  if (!appid || !/^\d+$/.test(String(appid))) {
    if (statusEl) statusEl.textContent = 'Tựa game này chưa có Steam AppID — hãy xem trailer trên YouTube.';
    return;
  }
  try {
    const res = await fetch('/api/discovery/trailer?appid=' + encodeURIComponent(appid) + '&seconds=20');
    const data = await res.json();
    if (data && data.success && data.clip_url) {
      if (video) {
        video.src = data.clip_url;
        video.muted = false;
        video.volume = 0.8;
        const p = video.play();
        if (p && typeof p.catch === 'function') {
          p.catch(() => { video.muted = true; const p2 = video.play(); if (p2 && p2.catch) p2.catch(() => {}); });
        }
      }
      if (statusEl) statusEl.textContent = (data.movies && data.movies.length) ? (data.movies[0].name || 'Trailer chính thức') : 'Trailer chính thức';
    } else {
      if (statusEl) statusEl.textContent = (data && data.message) || 'Không lấy được trailer từ Steam.';
    }
  } catch (e) {
    if (statusEl) statusEl.textContent = 'Lỗi tải trailer: ' + e.message;
  }
}
function discoveryCloseTrailerModal() {
  const modal = document.getElementById('discoveryTrailerModal');
  const video = document.getElementById('discoveryTrailerVideo');
  if (video) { try { video.pause(); } catch (e) {} video.removeAttribute('src'); video.load(); }
  if (modal) modal.classList.add('hidden');
}
// -----------------------------------------------------------------------------
// YÊU CẦU VIỆT HÓA / THEO DÕI BẢN TẢI
// -----------------------------------------------------------------------------
async function discoveryRequestViet(title, appid) {
  if (!title) return;
  try {
    const res = await fetch('/api/discovery/request_vietnamese', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: title, steam_appid: appid || '' })
    });
    const data = await res.json();
    showToast((data && data.message) || 'Đã ghi nhận yêu cầu Việt hóa!', data && data.success ? 'success' : 'error');
  } catch (e) {
    showToast('Không gửi được yêu cầu: ' + e.message, 'error');
  }
}
async function discoveryToggleWatch(title, appid, posterUrl) {
  if (!title) return;
  const watching = discoveryIsWatching(title);
  try {
    const res = await fetch('/api/discovery/watchlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action: watching ? 'remove' : 'add',
        title: title,
        steam_appid: appid || '',
        poster_url: posterUrl || ''
      })
    });
    const data = await res.json();
    if (data && data.success) {
      if (discoveryFeed) discoveryFeed.watchlist = data.watchlist || [];
      discoveryApplyFilters();
      showToast(data.message || 'Đã cập nhật danh sách theo dõi!', 'success');
    } else {
      showToast((data && data.message) || 'Không cập nhật được danh sách theo dõi.', 'error');
    }
  } catch (e) {
    showToast('Lỗi cập nhật theo dõi: ' + e.message, 'error');
  }
}
function discoveryIsWatching(title) {
  const list = (discoveryFeed && discoveryFeed.watchlist) || [];
  const key = String(title || '').toLowerCase().trim();
  return list.some(w => String(w.title || '').toLowerCase().trim() === key);
}
function discoveryIsBookmarked(title, appid) {
  return typeof isGameBookmarked === 'function' && isGameBookmarked({ title: title, steam_appid: appid || '' });
}
async function discoveryToggleBookmark(title, appid, posterUrl, sourceEl) {
  if (!title || typeof toggleGameBookmark !== 'function') return;
  const card = sourceEl && sourceEl.closest ? sourceEl.closest('.discovery-card') : null;
  const sourceImg = card ? card.querySelector('img') : null;
  const added = await toggleGameBookmark({
    title: title,
    steam_appid: appid || '',
    cover_url: posterUrl || '',
    source: 'discovery'
  });
  if (added && typeof flyCoverToLibrary === 'function') flyCoverToLibrary(sourceImg);
  if (typeof discoveryApplyFilters === 'function') discoveryApplyFilters();
}
function discoveryNotifyWatchlist() {
  const list = (discoveryFeed && discoveryFeed.watchlist) || [];
  if (!list.length) return;
  const recent = (discoveryFeed.recent_repacks || []).concat(discoveryFeed.online_coop || []);
  const available = [];
  list.forEach(w => {
    const key = String(w.title || '').toLowerCase().trim();
    if (!key) return;
    const hit = recent.find(r => {
      const t = String(r.title || '').toLowerCase().trim();
      return t === key || (t && t.indexOf(key) >= 0) || (t && key.indexOf(t) >= 0);
    });
    if (hit) available.push(w.title);
  });
  if (available.length) {
    showToast(`Đã có bản tải cho game bạn theo dõi: ${available.slice(0, 2).join(', ')}`, 'success');
  }
}
// -----------------------------------------------------------------------------
// PHÍM TẮT ESC ĐÓNG MODAL KHÁM PHÁ
// -----------------------------------------------------------------------------
document.addEventListener('keydown', function (e) {
  if (e.key !== 'Escape') return;
  const downloadModal = document.getElementById('discoveryDownloadModal');
  const trailerModal = document.getElementById('discoveryTrailerModal');
  const detailModal = document.getElementById('discoveryGameDetailModal');
  if (detailModal && !detailModal.classList.contains('hidden')) {
    discoveryCloseGameDetailModal();
  } else if (trailerModal && !trailerModal.classList.contains('hidden')) {
    discoveryCloseTrailerModal();
  } else if (downloadModal && !downloadModal.classList.contains('hidden')) {
    discoveryCloseDownloadModal();
  }
});
// Tự làm mới feed nếu cache đã cũ (quá 6 giờ) khi app mở lâu
setInterval(function () {
  if (!discoveryFeed || !discoveryFeed.updated_at) return;
  const ageSec = Date.now() / 1000 - discoveryFeed.updated_at;
  if (ageSec > 6 * 3600 && !discoveryLoading) loadDiscoveryFeed(true);
}, 15 * 60 * 1000);


// -----------------------------------------------------------------------------
// MODAL CHI TIẾT THÔNG TIN GAME KHI BẤM VÀO THẺ (DISCOVERY DETAIL MODAL)
// -----------------------------------------------------------------------------
let discoveryActiveDetailItem = null;
let discoveryActiveDetailKind = '';
let discoveryActiveDetailIdx = 0;


function discoveryOpenGameDetail(kind, idx) {
  const item = (discoveryLists[kind] || [])[idx];
  if (!item) return;


  discoveryActiveDetailItem = item;
  discoveryActiveDetailKind = kind;
  discoveryActiveDetailIdx = idx;


  const modal = document.getElementById('discoveryGameDetailModal');
  if (!modal) return;


  const title = item.title || 'Game';
  const appid = String(item.steam_appid || '');
  const isSteam = appid && /^\d+$/.test(appid);
  const poster = item.poster_url || (isSteam ? `https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/${appid}/library_600x900.jpg` : '');
  const banner = item.hero_url || item.header_url || (isSteam ? `https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/${appid}/library_hero.jpg` : poster);


  const bannerEl = document.getElementById('discoveryDetailBanner');
  if (bannerEl) bannerEl.style.backgroundImage = `url('${banner}')`;


  const posterEl = document.getElementById('discoveryDetailPoster');
  if (posterEl) posterEl.src = poster || banner;


  const titleEl = document.getElementById('discoveryDetailTitle');
  if (titleEl) titleEl.textContent = title;


  const subEl = document.getElementById('discoveryDetailSub');
  if (subEl) {
    const subText = item.has_vietnamese && item.vietnamese_title ? item.vietnamese_title : '';
    subEl.textContent = subText;
    subEl.classList.toggle('hidden', !subText);
  }


  const badgeViet = document.getElementById('discoveryDetailBadgeViet');
  if (badgeViet) badgeViet.classList.toggle('hidden', !item.has_vietnamese);


  const badgeRepack = document.getElementById('discoveryDetailBadgeRepack');
  if (badgeRepack) {
    const size = discoveryFormatSize(item);
    badgeRepack.textContent = size ? `REPACK ${size}` : 'CÓ BẢN TẢI';
  }


  const priceEl = document.getElementById('discoveryDetailPrice');
  if (priceEl) priceEl.textContent = isSteam ? 'Steam' : 'Cổ Ngữ';


  const devEl = document.getElementById('discoveryDetailDev');
  if (devEl) {
    const rep = (item.repackers || (item.repacker ? [item.repacker] : [])).join(', ');
    devEl.innerHTML = `<i data-lucide="code" class="w-3 h-3 inline mr-1 text-red-400"></i>${discoveryEsc(rep || 'PC Game')}`;
  }


  const relEl = document.getElementById('discoveryDetailRelease');
  if (relEl) {
    relEl.innerHTML = `<i data-lucide="calendar" class="w-3 h-3 inline mr-1 text-red-400"></i>${discoveryEsc(discoveryDateLabel(item) || 'Gần đây')}`;
  }


  const descEl = document.getElementById('discoveryDetailDesc');
  if (descEl) descEl.textContent = item.description || 'Đang tra cứu mô tả từ Steam Store...';


  const reqText = document.getElementById('discoveryDetailReqText');
  if (reqText) reqText.textContent = 'Đang tra cứu cấu hình từ Steam Store...';


  const genresEl = document.getElementById('discoveryDetailGenres');
  if (genresEl) {
    const genres = item.genres || [];
    genresEl.innerHTML = genres.map(g => `<span class="px-2.5 py-1 rounded-[4px] bg-white/[0.05] border border-white/10 text-red-300 text-xs font-medium">${discoveryEsc(g)}</span>`).join('');
  }


  // Hook nút tải
  const dlBtn = document.getElementById('discoveryDetailDownloadBtn');
  if (dlBtn) dlBtn.onclick = () => { discoveryCloseGameDetailModal(); discoveryOpenDownloads(kind, idx); };


  // Hook nút trailer
  const trBtn = document.getElementById('discoveryDetailTrailerBtn');
  if (trBtn) trBtn.onclick = () => discoveryOpenTrailer(appid, title);


  // Hook nút bookmark
  const bmBtn = document.getElementById('discoveryDetailBookmarkBtn');
  if (bmBtn) {
    const isBm = discoveryIsBookmarked(title, appid);
    bmBtn.innerHTML = `<i data-lucide="${isBm ? 'bookmark-check' : 'bookmark-plus'}" class="w-3.5 h-3.5"></i><span>${isBm ? 'Đã Lưu Thư Viện' : 'Lưu Thư Viện'}</span>`;
    bmBtn.onclick = function() {
      discoveryToggleBookmark(title, appid, poster, this);
      const nowBm = discoveryIsBookmarked(title, appid);
      this.innerHTML = `<i data-lucide="${nowBm ? 'bookmark-check' : 'bookmark-plus'}" class="w-3.5 h-3.5"></i><span>${nowBm ? 'Đã Lưu Thư Viện' : 'Lưu Thư Viện'}</span>`;
      if (window.lucide) lucide.createIcons();
    };
  }


  // Hook nút Việt hóa
  const vietBtn = document.getElementById('discoveryDetailVietBtn');
  if (vietBtn) {
    if (item.has_vietnamese && item.viet_game_id) {
      vietBtn.innerHTML = `<i data-lucide="library" class="w-3.5 h-3.5 text-amber-300"></i><span>Mở Bản Việt Hóa</span>`;
      vietBtn.onclick = () => { discoveryCloseGameDetailModal(); discoveryOpenLocalGame(item.viet_game_id); };
    } else {
      vietBtn.innerHTML = `<i data-lucide="flame" class="w-3.5 h-3.5 text-amber-300"></i><span>Yêu Cầu Dịch</span>`;
      vietBtn.onclick = () => discoveryRequestViet(title, appid);
    }
  }


  // Nguồn tải có sẵn
  const sourcesList = document.getElementById('discoveryDetailSourcesList');
  if (sourcesList) {
    const dls = item.downloads || [];
    if (dls.length) {
      sourcesList.innerHTML = dls.map(d => `
        <div class="flex items-center justify-between p-2 rounded bg-white/[0.03] border border-white/5 text-xs">
          <div class="min-w-0 pr-2">
            <span class="font-bold text-white">${discoveryEsc(d.title || d.repacker || title)}</span>
            <span class="text-zinc-400 font-mono ml-2 text-[11px]">${discoveryEsc(d.file_size || '')}</span>
          </div>
          <button onclick="discoveryCloseGameDetailModal(); discoveryOpenDownloads('${kind}', ${idx})" class="text-red-400 hover:text-red-300 text-[11px] font-bold">Xem nguồn &rarr;</button>
        </div>
      `).join('');
    } else {
      sourcesList.innerHTML = `<p class="text-xs text-zinc-500 italic">Bấm "Nguồn Tải Về" để kiểm tra danh sách nguồn FitGirl, DODI, GOG...</p>`;
    }
  }


  modal.classList.remove('hidden');
  if (window.lucide) lucide.createIcons();


  // Truy vấn thêm appdetails từ server
  fetch(`/api/discovery/detail?appid=${encodeURIComponent(appid)}&title=${encodeURIComponent(title)}`)
    .then(r => r.json())
    .then(res => {
      if (!res || !res.success) return;
      const d = res.detail || {};
      if (d.detailed_description || d.short_description) {
        if (descEl) descEl.innerHTML = d.detailed_description || d.short_description;
      }
      if (d.header_image && bannerEl && !item.hero_url) {
        bannerEl.style.backgroundImage = `url('${d.header_image}')`;
      }
      if (d.developers && d.developers.length && devEl) {
        devEl.innerHTML = `<i data-lucide="code" class="w-3 h-3 inline mr-1 text-red-400"></i>${discoveryEsc(d.developers.join(', '))}`;
      }
      if (d.release_date && relEl) {
        relEl.innerHTML = `<i data-lucide="calendar" class="w-3 h-3 inline mr-1 text-red-400"></i>${discoveryEsc(d.release_date)}`;
      }
      if (d.pc_requirements_min && reqText) {
        reqText.innerHTML = d.pc_requirements_min;
      } else if (reqText && !reqText.innerHTML.includes('GHz')) {
        reqText.textContent = 'Yêu cầu Windows 10/11 64-bit, DirectX 11/12, ổ cứng trống theo dung lượng game.';
      }
      if (d.price && priceEl) {
        priceEl.textContent = d.price;
      }
      if (d.genres && d.genres.length && genresEl) {
        genresEl.innerHTML = d.genres.map(g => `<span class="px-2.5 py-1 rounded-[4px] bg-white/[0.05] border border-white/10 text-red-300 text-xs font-medium">${discoveryEsc(g)}</span>`).join('');
      }
      if (window.lucide) lucide.createIcons();
    })
    .catch(() => {});
}


function discoveryCloseGameDetailModal() {
  const modal = document.getElementById('discoveryGameDetailModal');
  if (modal) modal.classList.add('hidden');
}


window.discoveryOpenGameDetail = discoveryOpenGameDetail;
window.discoveryCloseGameDetailModal = discoveryCloseGameDetailModal;
window.discoveryOpenDownloads = discoveryOpenDownloads;
window.discoveryOpenDownloadsModal = discoveryOpenDownloadsModal;
window.discoveryCloseDownloadModal = discoveryCloseDownloadModal;
window.discoveryOpenExternalRow = discoveryOpenExternalRow;
window.discoveryCopyRow = discoveryCopyRow;
// Hỗ trợ mở trực tiếp qua URL Hash #discover
window.addEventListener('DOMContentLoaded', () => {
  if (window.location.hash === '#discover') {
    setTimeout(() => {
      if (typeof openDiscoveryHub === 'function') openDiscoveryHub();
    }, 300);
  }
});
window.addEventListener('hashchange', () => {
  if (window.location.hash === '#discover') {
    if (typeof openDiscoveryHub === 'function') openDiscoveryHub();
  }
});