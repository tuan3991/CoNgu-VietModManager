import os

# 1. REVERT static/index.html
html_path = os.path.join('static', 'index.html')
with open(html_path, 'r', encoding='utf-8') as f:
    html = f.read()

# Replace body background and titlebar back to original
bg_and_header_old_start = '<body class="h-screen overflow-hidden'
bg_and_header_old_end = '<!-- Cụm phải: 3 nút tròn + 2 nút viên thuốc + điều khiển cửa sổ -->'

idx_h1 = html.find(bg_and_header_old_start)
idx_h2 = html.find(bg_and_header_old_end)
assert idx_h1 != -1 and idx_h2 != -1, f"header bounds not found: {idx_h1}, {idx_h2}"

reverted_bg_and_header = '''<body class="h-screen overflow-hidden selection:bg-[#00F0FF] selection:text-black flex flex-col relative">
  <!-- NỀN APP — Ambient tối giản (ảnh thành phố chỉ còn là texture mờ) -->
  <div class="pointer-events-none fixed inset-0 z-0 overflow-hidden select-none">
    <div class="w-full h-full bg-cover bg-no-repeat transition-transform duration-1000 scale-105"
         style="background-image: url('/static/pixel_city_bg.png');
                background-position: center top;
                opacity: 0.10;
                filter: blur(28px) saturate(0.6) contrast(0.9);"></div>
    <div class="absolute inset-0 bg-gradient-to-b from-[#0b0b0e]/40 via-[#0b0b0e]/20 to-[#0b0b0e]/80"></div>
  </div>


  <!-- TOP HEADER — MODERN MINIMAL (1 nền trung tính + 1 nhấn emerald) -->
  <!-- TOP HEADER — RECOMPLAUNCHER STYLE: phẳng, không viền, gạch chân cyan -->
  <header id="appTitlebar" class="sticky top-0 z-40 shrink-0 glass border-b border-white/[0.06] px-3 lg:px-5 h-14 flex items-center gap-2 pywebview-drag-region select-none cursor-grab active:cursor-grabbing" ondblclick="maximizeWindow()" title="Kéo để di chuyển cửa sổ | Bấm đúp để phóng to/thu nhỏ">

    <!-- Cụm trái: Logo + nút mở Sidebar + Segmented Đã Cài / Tất Cả -->
    <div class="flex items-center gap-1.5 shrink-0">
      <div class="w-8 h-8 rounded-xl overflow-hidden bg-[#111114] ring-1 ring-white/10 flex items-center justify-center p-0.5 transition-transform hover:scale-105 duration-200 cursor-pointer no-drag" onclick="refreshData()" title="Bấm vào logo để làm mới danh sách game">
        <img src="/static/app_icon.png" alt="CO NGU Icon" class="w-full h-full object-cover rounded-[9px] pointer-events-none" />
      </div>

      <button
        id="btnBrandToggleSidebar"
        onclick="toggleSidebar()"
        class="ui-icon-btn no-drag"
        title="Mở danh sách game bên trái (Ctrl+B)">
        <i id="brandToggleSidebarIcon" data-lucide="panel-left" class="w-4 h-4"></i>
      </button>

      <!-- Nút ẩn giữ tương thích JS toggleSidebar() -->
      <button id="btnToggleSidebar" class="hidden" aria-hidden="true" tabindex="-1"></button>
    </div>

    <!-- Cụm giữa: nav chữ hoặc ô tìm kiếm bung ngang tại chỗ -->
    <!-- Cụm giữa: Menu điều hướng + Ô tìm kiếm luôn hiển thị ở giữa -->
    <div id="navCenter" class="flex items-center justify-center min-w-0 px-2 flex-1 gap-3.5">
      <nav id="mainNav" class="hidden md:flex items-center gap-1 shrink-0 bg-[#0E1420]/80 border border-white/[0.08] p-1 rounded-full shadow-inner">
        <!-- Nhóm 1: Thư viện cá nhân + Nút Thêm Game -->
        <div class="flex items-center gap-1 shrink-0">
          <button id="btnLibraryNav" onclick="switchToLibraryView()" data-nav="library" class="ui-tab-nav is-active" title="Kho game của tôi – Các tựa game trên máy tính của bạn">
            <i data-lucide="library" class="w-3.5 h-3.5 shrink-0 pointer-events-none"></i>
            <span class="pointer-events-none">Kho game của tôi</span>
            <span class="text-[11px] font-semibold px-1.5 py-0.2 rounded-full bg-white/[0.08] text-zinc-300 shrink-0 pointer-events-none">
              <span id="count-all">0</span>
            </span>
          </button>
          <button id="btnAddCustomGame" onclick="openAddCustomGameModal()" class="w-7 h-7 rounded-full bg-white/[0.05] hover:bg-cyan-500/20 text-zinc-400 hover:text-cyan-300 border border-white/[0.08] hover:border-cyan-500/30 flex items-center justify-center transition shrink-0" title="Thêm game ngoài (Non-Steam)">
            <i data-lucide="plus" class="w-3.5 h-3.5"></i>
          </button>
        </div>

        <!-- Đường kẻ phân cách 1 -->
        <div class="w-px h-4 bg-white/10 shrink-0 mx-0.5"></div>

        <!-- Nhóm 2: Kho nội dung & Khám phá -->
        <button id="btnCatalogueNav" onclick="switchToCatalogueView()" data-nav="catalogue" class="ui-tab-nav" title="Kho Bản Dịch Cổ Ngữ – 27 Tựa game đã sẵn sàng Việt hóa trọn vẹn">
          <i data-lucide="sparkles" class="w-3.5 h-3.5 shrink-0 pointer-events-none text-cyan-400"></i>
          <span class="pointer-events-none">Kho Bản Dịch</span>
          <span class="text-[11px] font-semibold px-1.5 py-0.2 rounded-full bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 shrink-0 pointer-events-none">
            <span id="count-catalogue">27</span>
          </span>
        </button>

        <button id="btnDiscoveryHub" onclick="uiSetActiveNav('discover'); openDiscoveryHub()" data-nav="discover" class="ui-tab-nav" title="Khám Phá game hot trên Steam">
          <i data-lucide="compass" class="w-3.5 h-3.5 shrink-0 pointer-events-none"></i>
          <span class="pointer-events-none">Khám Phá</span>
        </button>

        <button id="btnDownloadsNav" onclick="openHydraModal('downloads')" data-nav="downloads" class="ui-tab-nav" title="Tiến Trình Tải Về Game &amp; Repack">
          <i data-lucide="download" class="w-3.5 h-3.5 shrink-0 pointer-events-none"></i>
          <span class="pointer-events-none">Tải Về</span>
          <span id="navDownloadBadge" class="hidden text-[10px] font-bold px-1.5 py-0.2 rounded-full bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shrink-0 pointer-events-none">
            <span id="navDownloadCount">0</span>
          </span>
        </button>

        <!-- Đường kẻ phân cách 2 -->
        <div class="w-px h-4 bg-white/10 shrink-0 mx-0.5"></div>

        <!-- Nhóm 3: Hồ sơ game thủ -->
        <button id="btnProfileNav" onclick="openProfilePage()" data-nav="profile" class="ui-tab-nav" title="Hồ Sơ Game Thủ, Huy Hiệu &amp; Két Save .congu_save">
          <i data-lucide="circle-user-round" class="w-3.5 h-3.5 shrink-0 pointer-events-none"></i>
          <span class="pointer-events-none">Hồ Sơ</span>
        </button>
      </nav>

      <!-- Đường kẻ phân cách giữa Nav và Search -->
      <div class="hidden lg:block w-px h-5 bg-white/10 shrink-0"></div>

      <!-- Ô tìm kiếm toàn cục (Omnibox) luôn hiển thị ở giữa cố định -->
      <div id="searchInline" class="flex w-full max-w-sm lg:max-w-md xl:max-w-lg items-center gap-2 relative no-drag">
        <div class="relative w-full">
          <i data-lucide="search" class="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none"></i>
          <input
            id="searchInput"
            type="text"
            autocomplete="off"
            aria-label="Tìm kiếm toàn cục trong Thư viện, Kho Việt hóa và Kho Tải về"
            placeholder="Tìm trong Thư viện, Kho Việt hóa... (Ctrl+K)"
            class="w-full pl-9 pr-8 py-1.5 bg-white/[0.05] border border-white/[0.1] hover:border-white/20 focus:border-[#00F0FF]/60 rounded-full text-[12px] focus:outline-none text-zinc-100 placeholder-zinc-500 transition shadow-[inset_0_1px_3px_rgba(0,0,0,0.4)]"
          />
          <button id="clearSearchBtn" onclick="clearSearch()" class="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-white hidden">
            <i data-lucide="x" class="w-3.5 h-3.5"></i>
          </button>
        </div>
      </div>

      <!-- Kết quả Omnibox chia 3 nhóm kho -->
      <div id="omniDropdown" class="hidden absolute left-1/2 -translate-x-1/2 top-[52px] w-[min(680px,calc(100vw-2rem))] max-h-[72vh] overflow-y-auto rounded-2xl bg-[#0d0f1c]/[0.99] border border-white/10 shadow-2xl z-50 no-drag"></div>
    </div>
    '''

html = html[:idx_h1] + reverted_bg_and_header + html[idx_h2:]

# Replace right cluster back
rc_start = '<!-- Cụm phải: 3 nút tròn + 2 nút viên thuốc + điều khiển cửa sổ -->'
rc_end = '<!-- Menu Đám Mây / Hồ Sơ .congu_save -->'
idx_r1 = html.find(rc_start)
idx_r2 = html.find(rc_end)
assert idx_r1 != -1 and idx_r2 != -1, f"right cluster not found: {idx_r1}, {idx_r2}"

reverted_rc = '''<!-- Cụm phải: 3 nút tròn + 2 nút viên thuốc + điều khiển cửa sổ -->
    <div class="flex items-center gap-1 ml-auto shrink-0">
      <!-- Fallback icon cho cửa sổ hẹp (<md) -->
      <button onclick="switchToGridView()" class="ui-icon-btn md:hidden" title="Thư Viện">
        <i data-lucide="library" class="w-4 h-4"></i>
      </button>
      <button onclick="openDiscoveryHub()" class="ui-icon-btn md:hidden" title="Khám Phá">
        <i data-lucide="compass" class="w-4 h-4"></i>
      </button>
      <button onclick="openHydraModal()" class="ui-icon-btn md:hidden" title="Kho Tải Game">
        <i data-lucide="download-cloud" class="w-4 h-4"></i>
      </button>
      <button onclick="openProfilePage()" class="ui-icon-btn md:hidden" title="Hồ Sơ Game Thủ &amp; Két Save">
        <i data-lucide="circle-user-round" class="w-4 h-4"></i>
      </button>

      <!-- Các nút công cụ -->
      <button onclick="refreshData()" class="ui-icon-btn" aria-label="Làm mới" title="Quét và làm mới danh sách game">
        <i data-lucide="refresh-cw" class="w-4 h-4"></i>
      </button>
      <button id="btnHeaderSettings" onclick="openSettingsModal()" class="ui-icon-btn" aria-label="Cài đặt" title="Cài đặt hệ thống">
        <i data-lucide="settings" class="w-4 h-4"></i>
      </button>

      <!-- 2 nút viên thuốc (thu về icon khi cửa sổ hẹp để không tràn header) -->
      <button onclick="openGameRequestModal()" class="pixel-btn ui-pill hidden xl:flex items-center gap-1.5 px-2.5 2xl:px-3.5 py-1.5 text-[12px] whitespace-nowrap shrink-0 ml-1" title="Yêu cầu Việt hóa game mới">
        <i data-lucide="sparkles" class="w-3.5 h-3.5 shrink-0"></i>
        <span class="hidden 2xl:inline">Yêu Cầu</span>
      </button>

      <div class="h-5 w-px bg-white/10 mx-1 hidden sm:block"></div>

      <!-- Điều khiển cửa sổ -->
      <div class="flex items-center -mr-2 gap-0.5" title="Điều khiển cửa sổ">
        <button onclick="minimizeWindow()" class="w-8 h-8 flex items-center justify-center text-zinc-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors" title="Thu nhỏ (Minimize)">
          <i data-lucide="minus" class="w-3.5 h-3.5 stroke-[2]"></i>
        </button>
        <button onclick="maximizeWindow()" class="w-8 h-8 flex items-center justify-center text-zinc-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors" title="Phóng to / Khôi phục (Maximize)">
          <i data-lucide="square" class="w-3 h-3 stroke-[2]"></i>
        </button>
        <button onclick="quitApp()" class="w-8 h-8 flex items-center justify-center text-zinc-400 hover:text-white hover:bg-[#e81123] rounded-lg transition-colors" title="Đóng (Close)">
          <i data-lucide="x" class="w-4 h-4 stroke-[2]"></i>
        </button>
      </div>
    </div>

    '''

html = html[:idx_r1] + reverted_rc + html[idx_r2:]

# Replace viewBrowseGrid content back
grid_start = '<div id="viewBrowseGrid" class="space-y-6">'
grid_end = '<!-- VIEW 2: GAME DETAIL VIEW'
idx_g1 = html.find(grid_start)
idx_g2 = html.find(grid_end)
assert idx_g1 != -1 and idx_g2 != -1, f"browse grid not found: {idx_g1}, {idx_g2}"

reverted_grid = '''<div id="viewBrowseGrid" class="space-y-6">

    <!-- BANNER KHO BẢN DỊCH CỔ NGỮ (Hiển thị khi ở Tab Kho Bản Dịch) -->
    <div id="catalogueHeaderBanner" class="hidden relative overflow-hidden rounded-2xl bg-gradient-to-r from-[#0d1627] via-[#091120] to-[#0A0E1A] border border-cyan-500/30 p-5 sm:p-6 shadow-[0_15px_35px_rgba(0,0,0,0.6)]">
      <div class="absolute -right-12 -top-12 w-64 h-64 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none"></div>
      <div class="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div class="space-y-1.5 max-w-2xl">
          <div class="flex items-center gap-2">
            <span class="px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 inline-flex items-center gap-1.5">
              <i data-lucide="sparkles" class="w-3 h-3 text-cyan-400"></i>
              Kho Bản Dịch Độc Quyền Cổ Ngữ
            </span>
            <span class="text-[11px] text-zinc-400 font-medium">27 Tựa Game Hoàn Tất</span>
          </div>
          <h2 class="text-xl sm:text-2xl font-display font-bold text-white tracking-wide">
            Tất Cả Tựa Game Đã Hỗ Trợ Tiếng Việt Trọn Vẹn
          </h2>
          <p class="text-xs sm:text-[13px] text-zinc-400 leading-relaxed">
            Chọn bất kỳ tựa game nào dưới đây để xem thông tin bản dịch, cài đặt Việt hóa 1-click hoặc lưu vào <strong class="text-zinc-200">Kho game của tôi</strong> để quản lý.
          </p>
        </div>
        <div class="flex items-center gap-2 shrink-0">
          <button onclick="openDiscoveryHub()" class="pixel-btn btn-neon-cyan px-4 py-2 text-xs flex items-center gap-1.5 rounded-xl font-bold">
            <i data-lucide="cloud-download" class="w-3.5 h-3.5"></i>
            <span>Tải Game Repack</span>
          </button>
          <button onclick="switchToLibraryView()" class="px-3.5 py-2 rounded-xl bg-white/[0.06] hover:bg-white/[0.12] text-zinc-300 hover:text-white border border-white/10 text-xs flex items-center gap-1.5 transition">
            <i data-lucide="library" class="w-3.5 h-3.5"></i>
            <span>Về Thư Viện Của Tôi</span>
          </button>
        </div>
      </div>
    </div>

    <!-- HERO SPOTLIGHT — Hộp kính nổi bên trái, ảnh nhường nửa phải -->
    <div id="heroBanner" onmouseenter="isHeroHovered = true" onmouseleave="isHeroHovered = false" class="relative overflow-hidden hero-arcade-frame bg-[#0F1522] min-h-[300px] flex items-center p-4 sm:p-6 transition-all duration-500">
      <div id="heroBg" class="absolute inset-0 bg-cover opacity-100 transition-transform duration-700 scale-100" style="background-image: url('/assets/preludes/library_hero.jpg'); background-position: 72% 25%;"></div>
      <div class="absolute inset-0 bg-gradient-to-r from-[#0A0E1A]/95 via-[#0A0E1A]/60 to-transparent"></div>
      <div class="absolute inset-0 bg-gradient-to-t from-[#0A0E1A]/85 via-transparent to-transparent"></div>

      <!-- Đổi game spotlight -->
      <button onclick="shuffleHeroSpotlight()" class="absolute top-5 right-5 z-30 px-3 py-1.5 rounded-full bg-black/50 backdrop-blur-md hover:bg-black/70 text-[12px] text-zinc-200 hover:text-white border border-white/10 transition flex items-center gap-2 group" title="Tự động đổi game sau mỗi 5s (hoặc nhấp để đổi ngay)">
        <i data-lucide="shuffle" class="w-3.5 h-3.5 group-hover:rotate-180 transition-transform duration-500"></i>
        <span>Đổi game</span>
        <span class="text-[10px] text-zinc-400">5s</span>
      </button>

      <!-- Hộp kính mờ: toàn bộ chữ nằm gọn bên trái -->
      <div class="relative z-10 w-full max-w-[430px] rounded-2xl bg-white/[0.06] backdrop-blur-2xl border border-white/10 p-5 sm:p-6 shadow-[0_25px_60px_-20px_rgba(0,0,0,0.95)] space-y-3">
        <div class="flex flex-wrap items-center gap-2">
          <!-- Trạng thái Việt hóa: điểm nhấn emerald duy nhất trên Hero -->
          <span id="heroBadge" class="text-[11px] font-medium px-2.5 py-1 rounded-full bg-emerald-500/[0.12] text-emerald-300 border border-emerald-500/25 flex items-center gap-1.5">
            <span id="heroBadgeDot" class="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block"></span>
            <span id="heroStatusText">Đã cài Việt hóa</span>
          </span>
          <span id="heroEngine" class="text-[11px] font-medium px-2.5 py-1 rounded-full bg-white/[0.06] text-zinc-300 border border-white/[0.08]">Unreal Engine</span>
          <span id="heroPlaytimeBadge" class="hidden text-[11px] font-medium px-2.5 py-1 rounded-full bg-white/[0.06] text-zinc-300 border border-white/[0.08] flex items-center gap-1.5">
            <i data-lucide="clock" class="w-3.5 h-3.5"></i>
            <span id="heroPlaytimeText">Chưa chơi</span>
          </span>
        </div>

        <h2 id="heroTitle" class="font-display text-2xl sm:text-3xl font-bold text-white tracking-tight leading-tight">
          Tails: The Backbone Preludes (Tiền Truyện)
        </h2>
        <p id="heroDesc" class="text-[13px] text-zinc-400 line-clamp-2 leading-relaxed">
          Tựa game trinh thám noir phân nhánh lựa chọn sâu sắc với 22,240 câu thoại đã được bản địa hóa chuẩn văn học, hỗ trợ đầy đủ font pixel-art tiếng Việt có dấu.
        </p>

        <!-- Ghi chú quan trọng -->
        <div id="heroNoteContainer" class="hidden p-3 rounded-xl bg-amber-500/[0.08] border border-amber-500/20 flex items-start gap-2.5">
          <i data-lucide="alert-triangle" class="w-4 h-4 text-amber-400 shrink-0 mt-0.5"></i>
          <div class="text-xs leading-relaxed">
            <span class="text-[11px] text-amber-300 mr-1.5 font-semibold">Lưu ý:</span>
            <span id="heroNoteText" class="text-amber-100/80"></span>
          </div>
        </div>

        <!-- Hành động -->
        <div class="pt-2 flex flex-wrap items-center gap-2.5">
          <button id="heroActionBtn" onclick="onHeroMainAction()" class="pixel-btn btn-neon-green px-6 py-2.5 text-sm flex items-center gap-2 rounded-xl">
            <i data-lucide="play" class="w-4 h-4 fill-current"></i>
            <span>Chơi Ngay</span>
          </button>
          <button id="heroDetailBtn" onclick="openGameModal(heroGameId)" class="px-4 py-2.5 rounded-xl bg-white/[0.06] hover:bg-white/[0.12] text-zinc-200 text-sm flex items-center gap-2 transition">
            <i data-lucide="info" class="w-4 h-4"></i>
            <span>Chi tiết</span>
          </button>
          <button onclick="openGameFolder(heroGameId)" class="w-10 h-10 rounded-full bg-white/10 hover:bg-white/20 border border-white/10 text-zinc-200 hover:text-white flex items-center justify-center transition shrink-0" title="Mở thư mục cài đặt game">
            <i data-lucide="folder" class="w-4 h-4"></i>
          </button>
        </div>
      </div>
    </div>

    <!-- THỂ LOẠI: ô bấm nhanh thay cho dropdown -->
    <div class="flex flex-wrap items-center gap-2 pt-1">
      <button data-genre-tile="all" onclick="setGenreQuick('all')" class="ui-genre-chip is-active">Tất cả</button>
      <button data-genre-tile="action_shooter" onclick="setGenreQuick('action_shooter')" class="ui-genre-chip">Hành Động</button>
      <button data-genre-tile="detective_adventure" onclick="setGenreQuick('detective_adventure')" class="ui-genre-chip">Phiêu Lưu</button>
      <button data-genre-tile="rpg_story" onclick="setGenreQuick('rpg_story')" class="ui-genre-chip">Nhập Vai</button>
      <button data-genre-tile="roguelike_strategy" onclick="setGenreQuick('roguelike_strategy')" class="ui-genre-chip">Roguelike</button>
      <button data-genre-tile="cozy_casual" onclick="setGenreQuick('cozy_casual')" class="ui-genre-chip">Thư Giãn</button>
      <button data-genre-tile="horror_dark" onclick="setGenreQuick('horror_dark')" class="ui-genre-chip">Kinh Dị</button>

      <!-- Select ẩn: giữ nguyên hợp đồng dữ liệu với onGenreFilterChange() -->
      <select id="genreFilter" onchange="onGenreFilterChange()" class="hidden">
        <option value="all">Tất cả thể loại</option>
        <option value="rpg_story">Nhập vai &amp; Cốt truyện</option>
        <option value="action_shooter">Hành động &amp; Bắn súng</option>
        <option value="detective_adventure">Trinh thám &amp; Phiêu lưu</option>
        <option value="roguelike_strategy">Roguelike &amp; Chiến thuật</option>
        <option value="cozy_casual">Thư giãn &amp; Cozy</option>
        <option value="horror_dark">Kinh dị &amp; Hắc ám</option>
      </select>
    </div>

    <!-- Filter trạng thái Thư Viện: Sẵn sàng chơi / Chờ Việt hóa / Chưa tải (Bookmark) -->
    <div class="flex flex-wrap items-center gap-2 pt-1" id="libraryStateFilters">
      <button id="filter-all" onclick="setFilter('all')" class="pixel-tab active-filter-tab px-3.5 py-1.5 text-xs font-bold transition">
        Tất cả <span id="count-all-pill" class="opacity-60 font-normal">0</span>
      </button>
      <button id="filter-on_disk" onclick="setFilter('on_disk')" class="pixel-tab px-3.5 py-1.5 text-xs font-bold transition">
        Đã cài trên máy <span id="count-on-disk" class="opacity-60 font-normal">0</span>
      </button>
      <button id="filter-bookmark" onclick="setFilter('bookmark')" class="pixel-tab px-3.5 py-1.5 text-xs font-bold transition">
        Chưa tải (Bookmark) <span id="count-bookmark" class="opacity-60 font-normal">0</span>
      </button>
      <button id="filter-ghost" onclick="setFilter('ghost')" class="pixel-tab px-3.5 py-1.5 text-xs font-bold transition">
        Chưa cài (Có Save) <span id="count-ghost" class="opacity-60 font-normal">0</span>
      </button>
    </div>

    <!-- GAMES GRID (2:3 Portrait Cards) -->
    <div id="gamesGrid" class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-3 xl:grid-cols-4 gap-5">
      <!-- Game Cards Generated Dynamically via JS -->
    </div>

        </div> <!-- End viewBrowseGrid -->

        '''

html = html[:idx_g1] + reverted_grid + html[idx_g2:]

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)
print("index.html reverted successfully!")


# 2. REVERT static/js/ui_render.js
js_path = os.path.join('static', 'js', 'ui_render.js')
with open(js_path, 'r', encoding='utf-8') as f:
    js = f.read()

# Revert syncTabHeaderDisplay
sync_start = 'function syncTabHeaderDisplay() {'
sync_end = 'function switchToLibraryView()'
idx_s1 = js.find(sync_start)
idx_s2 = js.find(sync_end)
assert idx_s1 != -1 and idx_s2 != -1

reverted_sync = '''function syncTabHeaderDisplay() {
      const heroBanner = document.getElementById('heroBanner');
      const catBanner = document.getElementById('catalogueHeaderBanner');
      const libFilters = document.getElementById('libraryStateFilters');
      const myGames = (Array.isArray(gamesList) ? gamesList : []).filter(isGameInUserLibrary);

      if (currentMainTab === 'catalogue') {
        if (heroBanner) heroBanner.classList.add('hidden');
        if (catBanner) catBanner.classList.remove('hidden');
        if (libFilters) libFilters.classList.add('hidden');
      } else {
        // Tab Kho Game Của Tôi
        if (catBanner) catBanner.classList.add('hidden');
        if (libFilters) libFilters.classList.remove('hidden');
        if (heroBanner) {
          if (myGames.length > 0) heroBanner.classList.remove('hidden');
          else heroBanner.classList.add('hidden');
        }
      }
    }

    '''

js = js[:idx_s1] + reverted_sync + js[idx_s2:]

# Revert renderHero
hero_start = 'function renderHero() {'
hero_end = 'function getHeroCandidateGames()'
idx_h1 = js.find(hero_start)
idx_h2 = js.find(hero_end)
assert idx_h1 != -1 and idx_h2 != -1

reverted_hero = '''function renderHero() {
      const heroBanner = document.getElementById('heroBanner');
      if (currentMainTab === 'catalogue') {
        if (heroBanner) heroBanner.classList.add('hidden');
        return;
      }
      const heroPool = getHeroCandidateGames();
      if (heroPool.length === 0) {
        if (heroBanner) heroBanner.classList.add('hidden');
        return;
      }
      if (heroBanner) heroBanner.classList.remove('hidden');

      const game = heroPool.find(g => g.id === heroGameId) || heroPool[0];
      if (!game) return;

      const heroBannerImg = game.local_cover || (game.assets && game.assets.banner) || game.header_url || game.avatar_url || '';
      document.getElementById('heroBg').style.backgroundImage = `url('${heroBannerImg}')`;
      document.getElementById('heroTitle').innerText = game.vietnamese_title || game.title;
      document.getElementById('heroDesc').innerText = game.description || '';
      document.getElementById('heroEngine').innerText = game.engine || 'Game Engine';

      const statusBadge = document.getElementById('heroBadge');
      const badgeDot = document.getElementById('heroBadgeDot');
      const statusText = document.getElementById('heroStatusText');

      if (game.status_code === 'INSTALLED') {
        statusBadge.className = 'text-[11px] font-medium px-2.5 py-1 rounded-full bg-emerald-500/[0.12] text-emerald-300 border border-emerald-500/25 flex items-center gap-1.5';
        badgeDot.className = 'w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block';
        statusText.innerText = 'Đã cài Việt hóa';
      } else if (game.status_code === 'UPDATE_DETECTED') {
        statusBadge.className = 'text-[11px] font-medium px-2.5 py-1 rounded-full bg-amber-500/[0.12] text-amber-300 border border-amber-500/25 flex items-center gap-1.5';
        badgeDot.className = 'w-1.5 h-1.5 rounded-full bg-amber-400 inline-block animate-pulse';
        statusText.innerText = 'Mất Việt hóa sau cập nhật';
      } else {
        statusBadge.className = 'text-[11px] font-medium px-2.5 py-1 rounded-full bg-white/[0.06] text-zinc-300 border border-white/[0.08] flex items-center gap-1.5';
        badgeDot.className = 'w-1.5 h-1.5 rounded-full bg-cyan-400 inline-block';
        statusText.innerText = 'Sẵn sàng cài đặt';
      }

      const playtimeBadge = document.getElementById('heroPlaytimeBadge');
      const playtimeText = document.getElementById('heroPlaytimeText');
      if (playtimeBadge && playtimeText) {
        const pt = game.playtime;
        if (pt && pt.total_seconds > 0) {
          playtimeBadge.classList.remove('hidden');
          playtimeText.innerText = pt.formatted_time;
        } else {
          playtimeBadge.classList.add('hidden');
        }
      }

      heroGameId = game.id;
    }

    '''

js = js[:idx_h1] + reverted_hero + js[idx_h2:]

# Revert card loop in renderGrid
card_loop_start = 'filtered.forEach(game => {'
card_loop_end = 'container.appendChild(card);\n      });'
idx_c1 = js.find(card_loop_start)
idx_c2 = js.find(card_loop_end)
assert idx_c1 != -1 and idx_c2 != -1
idx_c2 += len(card_loop_end)

reverted_card_loop = '''filtered.forEach(game => {
        const card = document.createElement('div');
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

        const pt = game.playtime || { is_running: false, formatted_time: 'Chưa chơi', last_played_str: 'Chưa từng mở', total_seconds: 0 };

        card.innerHTML = `
          <!-- Poster 2:3 — ảnh gốc full-bleed, sạch sẽ -->
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

            <!-- Cụm góc phải: chỉ nút Yêu thích / Bookmark khi hover hoặc đã yêu thích -->
            <div class="absolute top-3 right-3 z-30 flex items-center gap-1.5">
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

            <!-- Hành động khi hover -->
            <div class="absolute inset-x-0 bottom-0 p-3 pt-8 bg-gradient-to-t from-zinc-950 via-zinc-950/95 to-transparent opacity-0 translate-y-2 group-hover:opacity-100 group-hover:translate-y-0 transition-all duration-200 z-30 flex items-center justify-center">
              ${gridHoverActionsHtml(game, pt)}
            </div>
          </div>
        `;

        container.appendChild(card);
      });'''

js = js[:idx_c1] + reverted_card_loop + js[idx_c2:]

# Revert gridHoverActionsHtml (keeping the user fix that removed bulky Yêu Cầu Việt Hóa button)
hover_start = 'function gridHoverActionsHtml(game, pt) {'
hover_end = 'function vaultPendingButtonHtml(game) {'
idx_v1 = js.find(hover_start)
idx_v2 = js.find(hover_end)
assert idx_v1 != -1 and idx_v2 != -1

reverted_hover = '''function gridHoverActionsHtml(game, pt) {
      const runningBtn = `<button id="btn-play-${game.id}" disabled class="pixel-btn bg-amber-500/20 border border-amber-500/50 text-amber-300 w-full py-2 px-3 text-xs flex items-center justify-center space-x-2 font-bold cursor-not-allowed animate-pulse shadow-[0_2px_8px_rgba(0,0,0,0.35)]">
                     <i data-lucide="gamepad-2" class="w-3.5 h-3.5"></i>
                     <span>Đang Chơi...</span>
                   </button>`;

      // Game lẻ (Non-Steam): tinh gọn chỉ giữ duy nhất [Chơi Ngay] (đã bỏ nút Yêu cầu Việt hóa to theo yêu cầu)
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
                     <button onclick="event.stopPropagation(); installGhostGame('${game.id}')" class="pixel-btn w-full py-2 px-3 text-xs flex items-center justify-center space-x-2 font-bold shadow-[0_2px_8px_rgba(0,0,0,0.35)] bg-[#061c24] border border-[#00F0FF]/60 text-[#00F0FF] hover:bg-[#082b36]">
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
                     <button onclick="event.stopPropagation(); bookmarkLinkExisting('${game.id}')" class="pixel-btn w-full py-1.5 px-2 text-[11px] flex items-center justify-center space-x-1.5 font-bold shadow-[0_2px_8px_rgba(0,0,0,0.35)] bg-[#061c24] border border-[#00F0FF]/50 text-[#00F0FF] hover:bg-[#082b36] transition-all">
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
      if (currentMainTab === 'catalogue' && game.status_code === 'GAME_MISSING') {
        const isBookmarked = game.library_state === 'bookmark' || game.is_bookmarked;
        const bmBtn = isBookmarked
          ? `<button onclick="event.stopPropagation(); toggleGameBookmark('${game.id}')" class="pixel-btn w-full py-1.5 px-2 text-[11px] flex items-center justify-center space-x-1.5 font-bold shadow-[0_2px_8px_rgba(0,0,0,0.35)] bg-cyan-500/20 border border-cyan-400/50 text-cyan-200 hover:bg-cyan-500/35 transition" title="Bỏ khỏi Kho game của tôi">
               <i data-lucide="bookmark-check" class="w-3.5 h-3.5"></i>
               <span>Đã Trong Thư Viện</span>
             </button>`
          : `<button onclick="event.stopPropagation(); toggleGameBookmark('${game.id}')" class="pixel-btn w-full py-1.5 px-2 text-[11px] flex items-center justify-center space-x-1.5 font-bold shadow-[0_2px_8px_rgba(0,0,0,0.35)] bg-white/10 border border-white/20 text-white hover:bg-white/20 transition" title="Lưu game này vào Kho game của tôi để quản lý">
               <i data-lucide="bookmark-plus" class="w-3.5 h-3.5 text-cyan-400"></i>
               <span>+ Lưu Vào Thư Viện</span>
             </button>`;

        return `<div class="w-full flex flex-col gap-1.5">
                  <button onclick="event.stopPropagation(); openGameModal('${game.id}')" class="pixel-btn btn-neon-cyan w-full py-2 px-3 text-xs flex items-center justify-center space-x-2 font-bold shadow-[0_2px_8px_rgba(0,0,0,0.35)]">
                    <i data-lucide="sparkles" class="w-3.5 h-3.5 text-black"></i>
                    <span>Xem Bản Dịch &amp; Cài Đặt</span>
                  </button>
                  ${bmBtn}
                </div>`;
      }
      if (game.status_code === 'GAME_MISSING') {
        return `<button onclick="event.stopPropagation(); openGameModal('${game.id}')" class="pixel-btn btn-neon-cyan w-full py-2 px-3 text-xs flex items-center justify-center space-x-2 font-bold shadow-[0_2px_8px_rgba(0,0,0,0.35)]">
                           <i data-lucide="folder-search" class="w-3.5 h-3.5 text-black"></i>
                           <span>Chọn Thư Mục</span>
                         </button>`;
      }
      return `<div class="w-full flex flex-col gap-1.5">
                <button onclick="event.stopPropagation(); toggleMod('${game.id}')" class="w-full py-2 px-3 text-xs flex items-center justify-center gap-2 bg-white/10 hover:bg-cyan-400 text-white hover:text-zinc-950 font-semibold rounded-full border border-white/15 hover:border-emerald-400 transition-colors duration-200">
                  <i data-lucide="download" class="w-3.5 h-3.5 text-current stroke-[2.5]"></i>
                  <span>Cài Việt Hóa</span>
                </button>
                ${vaultPendingButtonHtml(game)}
              </div>`;
    }

    '''

js = js[:idx_v1] + reverted_hover + js[idx_v2:]

with open(js_path, 'w', encoding='utf-8') as f:
    f.write(js)
print("ui_render.js reverted successfully!")
