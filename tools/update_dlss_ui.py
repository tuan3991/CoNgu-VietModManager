import os

js_path = os.path.join('static', 'js', 'ui_render.js')

with open(js_path, 'r', encoding='utf-8') as f:
    text = f.read()

loop_start = 'filtered.forEach(game => {'
loop_end = 'container.appendChild(card);\n      });'
idx1 = text.find(loop_start)
idx2 = text.find(loop_end)
assert idx1 != -1 and idx2 != -1, f'card loop not found: {idx1}, {idx2}'
idx2 += len(loop_end)

new_card_loop = '''filtered.forEach(game => {
        const card = document.createElement('div');
        const isBookmarkState = game.library_state === 'bookmark';
        const isGhost = !!game.is_ghost;
        card.className = `group dlss-card${isGameFavorite(game) ? ' is-favorite' : ''}`;
        card.setAttribute('data-game-id', game.id);

        const posterSrc = game.local_cover
          || (game.assets && game.assets.poster)
          || game.avatar_url
          || (game.steam_appid ? `https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/${game.steam_appid}/library_600x900.jpg` : '');

        const fallbackHeaderSrc = game.header_url
          || (game.assets && game.assets.header)
          || (game.steam_appid ? `https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/${game.steam_appid}/header.jpg` : '');

        let cleanTitle = game.title || 'Game';
        cleanTitle = cleanTitle.replace(/\\s*\\(Tự Thêm\\)/gi, '').replace(/\\s*\\(Non-Steam\\)/gi, '').trim();

        const pt = game.playtime || { is_running: false, formatted_time: 'Chưa chơi', last_played_str: 'Chưa từng mở', total_seconds: 0 };

        card.innerHTML = `
          <!-- Poster Box (DLSS 5 Manager Rounded Bezel) -->
          <div class="dlss-poster-box" onclick="openGameModal('${game.id}')" oncontextmenu="openCardContextMenu(event, '${game.id}')">
            <!-- Poster Art -->
            <img
              src="${posterSrc}"
              alt="${cleanTitle}"
              class="w-full h-full object-cover transition-transform duration-500 ease-out group-hover:scale-105${isGhost ? ' opacity-50 grayscale brightness-[0.65]' : (isBookmarkState ? ' opacity-60 saturate-50' : '')}"
              onerror="if (this.dataset.fallback !== '1' && '${fallbackHeaderSrc}') { this.dataset.fallback = '1'; this.src = '${fallbackHeaderSrc}'; } else { this.style.display = 'none'; if (this.nextElementSibling) this.nextElementSibling.classList.remove('hidden'); }"
            />

            <!-- Fallback text art -->
            <div class="hidden absolute inset-0 bg-[#0d121d] flex flex-col items-center justify-center p-3 text-center">
              <i data-lucide="gamepad-2" class="w-8 h-8 text-zinc-600 mb-2"></i>
              <span class="text-xs font-semibold text-zinc-300 line-clamp-2">${cleanTitle}</span>
            </div>

            <!-- Top Right Bookmark & Favorite -->
            <div class="absolute top-2.5 right-2.5 z-30 flex items-center gap-1.5 transition-opacity duration-200 ${isGameFavorite(game) ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}">
              ${gridBookmarkButtonHtml(game)}
              ${gridFavoriteButtonHtml(game)}
            </div>

            <!-- Hover Action Overlay -->
            <div class="dlss-overlay">
              ${gridHoverActionsHtml(game, pt)}
            </div>
          </div>

          <!-- Game Title Underneath (DLSS 5 Manager Style) -->
          <div class="dlss-title" onclick="openGameModal('${game.id}')" title="${cleanTitle}">
            ${cleanTitle}
          </div>
        `;

        container.appendChild(card);
      });'''

text = text[:idx1] + new_card_loop + text[idx2:]

hover_start = 'function gridHoverActionsHtml(game, pt) {'
hover_end = 'function vaultPendingButtonHtml(game) {'
idx3 = text.find(hover_start)
idx4 = text.find(hover_end)
assert idx3 != -1 and idx4 != -1, f'hoverActions not found: {idx3}, {idx4}'

new_hover_actions = '''function gridHoverActionsHtml(game, pt) {
      const runningBtn = `<button id="btn-play-${game.id}" disabled class="w-full max-w-[130px] py-2 px-3 rounded-xl bg-amber-500/20 border border-amber-500/50 text-amber-300 text-xs font-bold flex items-center justify-center gap-1.5 cursor-not-allowed animate-pulse shadow-lg">
                     <i data-lucide="gamepad-2" class="w-3.5 h-3.5"></i>
                     <span>Đang Chơi</span>
                   </button>`;

      if (pt && pt.is_running) return runningBtn;

      // Game lẻ (Non-Steam)
      if (game.is_custom_game) {
        return `<button id="btn-play-${game.id}" onclick="event.stopPropagation(); launchGame('${game.id}')" class="w-full max-w-[130px] py-2.5 px-3 rounded-xl bg-cyan-400 hover:bg-cyan-300 text-black text-xs font-bold flex items-center justify-center gap-1.5 shadow-[0_4px_16px_rgba(0,240,255,0.4)] transition transform hover:scale-105 active:scale-95">
                  <i data-lucide="play" class="w-3.5 h-3.5 fill-black"></i>
                  <span>Chơi Ngay</span>
                </button>`;
      }

      // Ghost Library
      if (game.is_ghost) {
        return `<button onclick="event.stopPropagation(); installGhostGame('${game.id}')" class="w-full max-w-[130px] py-2.5 px-3 rounded-xl bg-cyan-500/20 border border-cyan-400/60 text-cyan-300 hover:bg-cyan-500/30 text-xs font-bold flex items-center justify-center gap-1.5 shadow-lg transition transform hover:scale-105 active:scale-95">
                  <i data-lucide="download-cloud" class="w-3.5 h-3.5"></i>
                  <span>Cài Đặt</span>
                </button>`;
      }

      // Bookmark
      if (game.library_state === 'bookmark') {
        return `<button onclick="event.stopPropagation(); bookmarkOpenDownload('${game.id}')" class="w-full max-w-[130px] py-2.5 px-3 rounded-xl bg-emerald-400 hover:bg-emerald-300 text-black text-xs font-bold flex items-center justify-center gap-1.5 shadow-[0_4px_16px_rgba(16,185,129,0.4)] transition transform hover:scale-105 active:scale-95">
                  <i data-lucide="download" class="w-3.5 h-3.5 fill-black"></i>
                  <span>Tải Game</span>
                </button>`;
      }

      // Installed & ready to play
      if (game.status_code === 'INSTALLED') {
        return `<button id="btn-play-${game.id}" onclick="event.stopPropagation(); launchGame('${game.id}')" class="w-full max-w-[130px] py-2.5 px-3 rounded-xl bg-cyan-400 hover:bg-cyan-300 text-black text-xs font-bold flex items-center justify-center gap-1.5 shadow-[0_4px_16px_rgba(0,240,255,0.4)] transition transform hover:scale-105 active:scale-95">
                  <i data-lucide="play" class="w-3.5 h-3.5 fill-black"></i>
                  <span>Chơi Ngay</span>
                </button>`;
      }

      // Lost translation
      if (game.status_code === 'UPDATE_DETECTED') {
        return `<button onclick="event.stopPropagation(); toggleMod('${game.id}', true)" class="w-full max-w-[130px] py-2.5 px-3 rounded-xl bg-amber-400 hover:bg-amber-300 text-black text-xs font-bold flex items-center justify-center gap-1.5 shadow-[0_4px_16px_rgba(245,158,11,0.4)] transition transform hover:scale-105 active:scale-95">
                  <i data-lucide="refresh-cw" class="w-3.5 h-3.5 stroke-[2.5]"></i>
                  <span>Cài Lại Mod</span>
                </button>`;
      }

      // Catalogue or Game Missing
      if (currentMainTab === 'catalogue' || game.status_code === 'GAME_MISSING') {
        return `<button onclick="event.stopPropagation(); openGameModal('${game.id}')" class="w-full max-w-[130px] py-2.5 px-3 rounded-xl bg-white/10 hover:bg-white/20 text-white text-xs font-bold flex items-center justify-center gap-1.5 backdrop-blur-md border border-white/20 transition transform hover:scale-105 active:scale-95">
                  <i data-lucide="info" class="w-3.5 h-3.5"></i>
                  <span>Chi Tiết</span>
                </button>`;
      }

      // Default: Cài Việt Hóa
      return `<button onclick="event.stopPropagation(); toggleMod('${game.id}')" class="w-full max-w-[130px] py-2.5 px-3 rounded-xl bg-cyan-400 hover:bg-cyan-300 text-black text-xs font-bold flex items-center justify-center gap-1.5 shadow-[0_4px_16px_rgba(0,240,255,0.4)] transition transform hover:scale-105 active:scale-95">
                <i data-lucide="download" class="w-3.5 h-3.5 stroke-[2.5]"></i>
                <span>Cài Việt Hóa</span>
              </button>`;
    }

    '''

text = text[:idx3] + new_hover_actions + text[idx4:]

with open(js_path, 'w', encoding='utf-8') as f:
    f.write(text)

print("SUCCESS: Updated renderGrid card loop and gridHoverActionsHtml!")
