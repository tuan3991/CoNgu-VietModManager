// =============================================================================


// CỔ NGỮ (VIETMODHUB) - HỒ SƠ GAME THỦ (PROFILE UI)


// =============================================================================






let profileOverview = null;


let profileVaultData = null;


let profileActiveTab = 'showcase';


let profileLoading = false;






function profileEsc(value) {


  if (typeof escapeHtml === 'function') return escapeHtml(String(value == null ? '' : value));


  return String(value == null ? '' : value)


    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')


    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');


}






// Tham số JS an toàn cho onclick="fn('...')" (khác với escape HTML)


function profileJsArg(value) {


  return String(value == null ? '' : value)


    .replace(/\\/g, '\\\\')


    .replace(/'/g, "\\'")


    .replace(/</g, '\\x3c')


    .replace(/\r?\n/g, ' ');


}






function openProfilePage() {


  const view = document.getElementById('viewProfile');


  if (!view) return;






  ['viewBrowseGrid', 'viewGameDetail', 'viewDiscovery', 'viewSearchResults'].forEach(id => {


    const el = document.getElementById(id);


    if (el) el.classList.add('hidden');


  });


  view.classList.remove('hidden');






  if (typeof updateSidebarSelection === 'function') updateSidebarSelection(null);


  const player = document.getElementById('modalVideoPlayer');


  if (player) player.src = '';


  if (typeof window.uiSetActiveNav === 'function') window.uiSetActiveNav('profile');






  const scroller = document.getElementById('mainScrollContainer');


  if (scroller) scroller.scrollTo({ top: 0 });






  profileSwitchTab(profileActiveTab);


  loadProfile(false);


  if (window.lucide) lucide.createIcons();


}


window.openProfilePage = openProfilePage;






function profileSwitchTab(tab) {
  profileActiveTab = tab === 'vault' ? 'vault' : 'showcase';


  const showcase = document.getElementById('profileTab-showcase');
  const vault = document.getElementById('profileTab-vault');
  if (showcase) showcase.classList.toggle('hidden', profileActiveTab !== 'showcase');
  if (vault) vault.classList.toggle('hidden', profileActiveTab !== 'vault');
  window.profileActiveTab = profileActiveTab;


  ['showcase', 'vault'].forEach(name => {
    const btn = document.getElementById('profileTabBtn-' + name);
    if (!btn) return;
    btn.className = name === profileActiveTab
      ? 'pixel-tab active-filter-tab px-3.5 py-1.5 text-xs font-bold transition flex items-center gap-1.5'
      : 'pixel-tab px-3.5 py-1.5 text-xs font-bold transition flex items-center gap-1.5';
  });


  if (profileActiveTab === 'vault' && !profileVaultData) {
    loadProfile(true);
  }
  if (window.lucide) lucide.createIcons();
}
window.profileSwitchTab = profileSwitchTab;


async function loadProfile(force) {


  if (profileLoading && !force) return;


  profileLoading = true;


  try {


    const [overviewRes, vaultRes] = await Promise.all([


      fetch('/api/profile/overview'),


      fetch('/api/vault/status')


    ]);


    const overview = await overviewRes.json();


    const vaultInfo = await vaultRes.json();






    if (overview && overview.player) {


      profileOverview = overview;


      profileRenderHeader(overview);


      profileRenderBadges(overview);


      profileRenderTopGames(overview);


      profileRenderRecent(overview);


    } else {


      showToast((overview && overview.message) || 'Không thể tải Hồ Sơ Game Thủ!', 'error');


    }






    if (vaultInfo && !vaultInfo.error) {


      profileVaultData = vaultInfo;


      profileRenderVault(vaultInfo);


    }


    if (window.lucide) lucide.createIcons();


  } catch (err) {


    console.warn('[Profile] Load failed:', err);


    showToast('Không thể kết nối máy chủ để tải Hồ Sơ!', 'error');


  } finally {


    profileLoading = false;


  }


}










// =============================================================================


// THƯ VIỆN PRESETS AVATAR & COVER GAME THỦ ĐỘC QUYỀN


// =============================================================================


const PROFILE_PRESETS = {


  avatars: [


    {


      id: 'cyber_visor',


      name: 'Cyber Visor',


      tag: 'Cyberpunk',


      svg: 'data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%22http%3A//www.w3.org/2000/svg%22%20viewBox%3D%220%200%20100%20100%22%3E%3Cdefs%3E%3ClinearGradient%20id%3D%22g1%22%20x1%3D%220%25%22%20y1%3D%220%25%22%20x2%3D%22100%25%22%20y2%3D%22100%25%22%3E%3Cstop%20offset%3D%220%25%22%20stop-color%3D%22%23061426%22/%3E%3Cstop%20offset%3D%22100%25%22%20stop-color%3D%22%230D2B45%22/%3E%3C/linearGradient%3E%3ClinearGradient%20id%3D%22g2%22%20x1%3D%220%25%22%20y1%3D%220%25%22%20x2%3D%22100%25%22%20y2%3D%220%25%22%3E%3Cstop%20offset%3D%220%25%22%20stop-color%3D%22%2300F0FF%22/%3E%3Cstop%20offset%3D%22100%25%22%20stop-color%3D%22%2300FF9D%22/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect%20width%3D%22100%22%20height%3D%22100%22%20rx%3D%2220%22%20fill%3D%22url%28%23g1%29%22/%3E%3Ccircle%20cx%3D%2250%22%20cy%3D%2242%22%20r%3D%2222%22%20fill%3D%22%231E293B%22%20stroke%3D%22%23334155%22%20stroke-width%3D%222%22/%3E%3Crect%20x%3D%2230%22%20y%3D%2238%22%20width%3D%2240%22%20height%3D%2210%22%20rx%3D%225%22%20fill%3D%22url%28%23g2%29%22/%3E%3Cpath%20d%3D%22M25%2080%20C%2025%2064%2C%2075%2064%2C%2075%2080%20Z%22%20fill%3D%22%231E293B%22%20stroke%3D%22%2300F0FF%22%20stroke-width%3D%221.5%22/%3E%3C/svg%3E'


    },


    {


      id: 'pixel_knight',


      name: 'Pixel Knight',


      tag: 'RPG',


      svg: 'data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%22http%3A//www.w3.org/2000/svg%22%20viewBox%3D%220%200%20100%20100%22%3E%3Cdefs%3E%3ClinearGradient%20id%3D%22gk%22%20x1%3D%220%25%22%20y1%3D%220%25%22%20x2%3D%22100%25%22%20y2%3D%22100%25%22%3E%3Cstop%20offset%3D%220%25%22%20stop-color%3D%22%231A130B%22/%3E%3Cstop%20offset%3D%22100%25%22%20stop-color%3D%22%233A2412%22/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect%20width%3D%22100%22%20height%3D%22100%22%20rx%3D%2220%22%20fill%3D%22url%28%23gk%29%22/%3E%3Crect%20x%3D%2234%22%20y%3D%2224%22%20width%3D%2232%22%20height%3D%2234%22%20rx%3D%224%22%20fill%3D%22%23FBBF24%22%20opacity%3D%220.9%22/%3E%3Crect%20x%3D%2244%22%20y%3D%2220%22%20width%3D%2212%22%20height%3D%2210%22%20fill%3D%22%23EF4444%22/%3E%3Crect%20x%3D%2238%22%20y%3D%2236%22%20width%3D%2224%22%20height%3D%226%22%20fill%3D%22%230F172A%22/%3E%3Cpath%20d%3D%22M26%2082%20C%2026%2066%2C%2074%2066%2C%2074%2082%20Z%22%20fill%3D%22%23D97706%22/%3E%3C/svg%3E'


    },


    {


      id: 'neon_samurai',


      name: 'Neon Blade',


      tag: 'Samurai',


      svg: 'data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%22http%3A//www.w3.org/2000/svg%22%20viewBox%3D%220%200%20100%20100%22%3E%3Cdefs%3E%3ClinearGradient%20id%3D%22gs%22%20x1%3D%220%25%22%20y1%3D%220%25%22%20x2%3D%22100%25%22%20y2%3D%22100%25%22%3E%3Cstop%20offset%3D%220%25%22%20stop-color%3D%22%23180820%22/%3E%3Cstop%20offset%3D%22100%25%22%20stop-color%3D%22%23320B44%22/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect%20width%3D%22100%22%20height%3D%22100%22%20rx%3D%2220%22%20fill%3D%22url%28%23gs%29%22/%3E%3Ccircle%20cx%3D%2250%22%20cy%3D%2242%22%20r%3D%2222%22%20fill%3D%22%230F172A%22%20stroke%3D%22%23E11D48%22%20stroke-width%3D%222%22/%3E%3Cpath%20d%3D%22M34%2042%20Q%2050%2028%2066%2042%22%20stroke%3D%22%23F43F5E%22%20stroke-width%3D%224%22%20fill%3D%22none%22/%3E%3Cpolygon%20points%3D%2250%2C18%2042%2C32%2058%2C32%22%20fill%3D%22%23FB7185%22/%3E%3Cpath%20d%3D%22M25%2082%20C%2025%2066%2C%2075%2066%2C%2075%2082%20Z%22%20fill%3D%22%23881337%22/%3E%3C/svg%3E'


    },


    {


      id: 'mecha_core',


      name: 'Mecha Unit',


      tag: 'Sci-Fi',


      svg: 'data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%22http%3A//www.w3.org/2000/svg%22%20viewBox%3D%220%200%20100%20100%22%3E%3Cdefs%3E%3ClinearGradient%20id%3D%22gm%22%20x1%3D%220%25%22%20y1%3D%220%25%22%20x2%3D%22100%25%22%20y2%3D%22100%25%22%3E%3Cstop%20offset%3D%220%25%22%20stop-color%3D%22%230B192C%22/%3E%3Cstop%20offset%3D%22100%25%22%20stop-color%3D%22%231E3E62%22/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect%20width%3D%22100%22%20height%3D%22100%22%20rx%3D%2220%22%20fill%3D%22url%28%23gm%29%22/%3E%3Cpolygon%20points%3D%2250%2C22%2074%2C38%2074%2C66%2050%2C80%2026%2C66%2026%2C38%22%20fill%3D%22%230F172A%22%20stroke%3D%22%2300F0FF%22%20stroke-width%3D%222.5%22/%3E%3Ccircle%20cx%3D%2250%22%20cy%3D%2250%22%20r%3D%2212%22%20fill%3D%22%2300F0FF%22%20opacity%3D%220.85%22/%3E%3Ccircle%20cx%3D%2250%22%20cy%3D%2250%22%20r%3D%226%22%20fill%3D%22%23FFFFFF%22/%3E%3C/svg%3E'


    },


    {


      id: 'hacker_cat',


      name: 'Cyber Cat',


      tag: 'Hacker',


      svg: 'data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%22http%3A//www.w3.org/2000/svg%22%20viewBox%3D%220%200%20100%20100%22%3E%3Cdefs%3E%3ClinearGradient%20id%3D%22gc%22%20x1%3D%220%25%22%20y1%3D%220%25%22%20x2%3D%22100%25%22%20y2%3D%22100%25%22%3E%3Cstop%20offset%3D%220%25%22%20stop-color%3D%22%23051910%22/%3E%3Cstop%20offset%3D%22100%25%22%20stop-color%3D%22%230D3823%22/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect%20width%3D%22100%22%20height%3D%22100%22%20rx%3D%2220%22%20fill%3D%22url%28%23gc%29%22/%3E%3Cpolygon%20points%3D%2230%2C22%2042%2C38%2024%2C40%22%20fill%3D%22%2310B981%22/%3E%3Cpolygon%20points%3D%2270%2C22%2058%2C38%2076%2C40%22%20fill%3D%22%2310B981%22/%3E%3Ccircle%20cx%3D%2250%22%20cy%3D%2252%22%20r%3D%2222%22%20fill%3D%22%23064E3B%22%20stroke%3D%22%2334D399%22%20stroke-width%3D%222%22/%3E%3Cellipse%20cx%3D%2242%22%20cy%3D%2250%22%20rx%3D%224%22%20ry%3D%226%22%20fill%3D%22%2300FF9D%22/%3E%3Cellipse%20cx%3D%2258%22%20cy%3D%2250%22%20rx%3D%224%22%20ry%3D%226%22%20fill%3D%22%2300FF9D%22/%3E%3Cpath%20d%3D%22M46%2060%20Q%2050%2063%2054%2060%22%20stroke%3D%22%2334D399%22%20stroke-width%3D%222%22%20fill%3D%22none%22/%3E%3C/svg%3E'


    },


    {


      id: 'retro_skull',


      name: 'Arcade Skull',


      tag: 'Steam',


      svg: 'data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%22http%3A//www.w3.org/2000/svg%22%20viewBox%3D%220%200%20100%20100%22%3E%3Cdefs%3E%3ClinearGradient%20id%3D%22gsk%22%20x1%3D%220%25%22%20y1%3D%220%25%22%20x2%3D%22100%25%22%20y2%3D%22100%25%22%3E%3Cstop%20offset%3D%220%25%22%20stop-color%3D%22%23111827%22/%3E%3Cstop%20offset%3D%22100%25%22%20stop-color%3D%22%23374151%22/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect%20width%3D%22100%22%20height%3D%22100%22%20rx%3D%2220%22%20fill%3D%22url%28%23gsk%29%22/%3E%3Cpath%20d%3D%22M30%2042%20C%2030%2026%2C%2070%2026%2C%2070%2042%20C%2070%2052%2C%2064%2058%2C%2064%2068%20L%2036%2068%20C%2036%2058%2C%2030%2052%2C%2030%2042%20Z%22%20fill%3D%22%23E5E7EB%22/%3E%3Ccircle%20cx%3D%2242%22%20cy%3D%2244%22%20r%3D%225%22%20fill%3D%22%2300F0FF%22/%3E%3Ccircle%20cx%3D%2258%22%20cy%3D%2244%22%20r%3D%225%22%20fill%3D%22%2300F0FF%22/%3E%3Crect%20x%3D%2242%22%20y%3D%2262%22%20width%3D%224%22%20height%3D%226%22%20fill%3D%22%23111827%22/%3E%3Crect%20x%3D%2254%22%20y%3D%2262%22%20width%3D%224%22%20height%3D%226%22%20fill%3D%22%23111827%22/%3E%3C/svg%3E'


    },


    {


      id: 'dragon_fire',


      name: 'Dragon Spirit',


      tag: 'Fantasy',


      svg: 'data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%22http%3A//www.w3.org/2000/svg%22%20viewBox%3D%220%200%20100%20100%22%3E%3Cdefs%3E%3ClinearGradient%20id%3D%22gdf%22%20x1%3D%220%25%22%20y1%3D%220%25%22%20x2%3D%22100%25%22%20y2%3D%22100%25%22%3E%3Cstop%20offset%3D%220%25%22%20stop-color%3D%22%232A0808%22/%3E%3Cstop%20offset%3D%22100%25%22%20stop-color%3D%22%235C1D1D%22/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect%20width%3D%22100%22%20height%3D%22100%22%20rx%3D%2220%22%20fill%3D%22url%28%23gdf%29%22/%3E%3Cpath%20d%3D%22M50%2018%20Q%2065%2030%2075%2048%20Q%2055%2052%2050%2068%20Q%2045%2052%2025%2048%20Q%2035%2030%2050%2018%20Z%22%20fill%3D%22%23F97316%22%20stroke%3D%22%23FBBF24%22%20stroke-width%3D%222%22/%3E%3Ccircle%20cx%3D%2250%22%20cy%3D%2242%22%20r%3D%225%22%20fill%3D%22%23FEF08A%22/%3E%3Cpath%20d%3D%22M30%2082%20C%2030%2068%2C%2070%2068%2C%2070%2082%20Z%22%20fill%3D%22%237C2D12%22/%3E%3C/svg%3E'


    },


    {


      id: 'space_astro',


      name: 'Astro Explorer',


      tag: 'Cosmic',


      svg: 'data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%22http%3A//www.w3.org/2000/svg%22%20viewBox%3D%220%200%20100%20100%22%3E%3Cdefs%3E%3ClinearGradient%20id%3D%22gsa%22%20x1%3D%220%25%22%20y1%3D%220%25%22%20x2%3D%22100%25%22%20y2%3D%22100%25%22%3E%3Cstop%20offset%3D%220%25%22%20stop-color%3D%22%23030712%22/%3E%3Cstop%20offset%3D%22100%25%22%20stop-color%3D%22%231E1B4B%22/%3E%3C/linearGradient%3E%3ClinearGradient%20id%3D%22gvisor%22%20x1%3D%220%25%22%20y1%3D%220%25%22%20x2%3D%22100%25%22%20y2%3D%22100%25%22%3E%3Cstop%20offset%3D%220%25%22%20stop-color%3D%22%23F59E0B%22/%3E%3Cstop%20offset%3D%2250%25%22%20stop-color%3D%22%23EC4899%22/%3E%3Cstop%20offset%3D%22100%25%22%20stop-color%3D%22%238B5CF6%22/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect%20width%3D%22100%22%20height%3D%22100%22%20rx%3D%2220%22%20fill%3D%22url%28%23gsa%29%22/%3E%3Ccircle%20cx%3D%2250%22%20cy%3D%2244%22%20r%3D%2224%22%20fill%3D%22%23E2E8F0%22/%3E%3Crect%20x%3D%2234%22%20y%3D%2234%22%20width%3D%2232%22%20height%3D%2220%22%20rx%3D%2210%22%20fill%3D%22url%28%23gvisor%29%22%20stroke%3D%22%23FDE68A%22%20stroke-width%3D%221.5%22/%3E%3Cpath%20d%3D%22M26%2084%20C%2026%2070%2C%2074%2070%2C%2074%2084%20Z%22%20fill%3D%22%23CBD5E1%22/%3E%3C/svg%3E'


    }


  ],


  covers: [


    {


      id: 'night_city',


      name: 'Cyberpunk Night City',


      tag: 'Cyberpunk',


      gradient: 'linear-gradient(135deg, rgba(13,19,32,0.95) 0%, rgba(10,14,26,0.85) 50%, rgba(255, 42, 85,0.2) 100%), url("/static/pixel_city_bg.png")'


    },


    {


      id: 'cosmic_nebula',


      name: 'Deep Cosmic Nebula',


      tag: 'Cosmic',


      gradient: 'radial-gradient(circle at 80% 20%, rgba(139,92,246,0.35) 0%, transparent 60%), radial-gradient(circle at 20% 80%, rgba(255, 42, 85,0.25) 0%, transparent 50%), linear-gradient(135deg, #060914 0%, #0F0C29 50%, #24243E 100%)'


    },


    {


      id: 'elden_fantasy',


      name: 'Elden Dark Fantasy',


      tag: 'Fantasy',


      gradient: 'radial-gradient(circle at 75% 25%, rgba(245,158,11,0.3) 0%, transparent 55%), radial-gradient(circle at 15% 75%, rgba(180,83,9,0.2) 0%, transparent 60%), linear-gradient(135deg, #0C0A08 0%, #1A140F 50%, #2B1D12 100%)'


    },


    {


      id: 'synthwave',


      name: 'Synthwave 80s Grid',


      tag: 'Retro',


      gradient: 'radial-gradient(circle at 50% 10%, rgba(255,0,128,0.3) 0%, transparent 60%), linear-gradient(180deg, #10002B 0%, #240046 50%, #3C096C 85%, #FF2A55 100%)'


    },


    {


      id: 'pixel_winter',


      name: 'Pixel Winter Glacier',


      tag: 'Atmosphere',


      gradient: 'radial-gradient(circle at 80% 20%, rgba(103,232,249,0.3) 0%, transparent 50%), linear-gradient(135deg, #050B14 0%, #0C1E30 50%, #153755 100%)'


    },


    {


      id: 'hyper_speed',


      name: 'Quantum Speedtrack',


      tag: 'High-Tech',


      gradient: 'radial-gradient(circle at 90% 50%, rgba(0,255,157,0.25) 0%, transparent 50%), linear-gradient(90deg, #040810 0%, #081B2C 45%, #FF2A55 95%)'


    }


  ]


};






function updateProfileNavAvatar(player) {
  if (!player) return;
  const avatarUrl = player.avatar_url || '';
  const initial = player.initial || (player.name ? player.name.charAt(0).toUpperCase() : '?');

  const imgDesk = document.getElementById('navProfileAvatarImg');
  const textDesk = document.getElementById('navProfileAvatarText');
  if (textDesk) textDesk.textContent = initial;
  if (imgDesk && textDesk) {
    applyProfileAvatar(avatarUrl, imgDesk, textDesk);
  }

  const imgMobile = document.getElementById('navProfileAvatarImgMobile');
  const textMobile = document.getElementById('navProfileAvatarTextMobile');
  if (textMobile) textMobile.textContent = initial;
  if (imgMobile && textMobile) {
    applyProfileAvatar(avatarUrl, imgMobile, textMobile);
  }
}
window.updateProfileNavAvatar = updateProfileNavAvatar;

function applyProfileAvatar(avatarVal, imgEl, textEl) {


  if (!imgEl || !textEl) return;


  if (!avatarVal) {


    imgEl.classList.add('hidden');


    imgEl.src = '';


    textEl.classList.remove('hidden');


    return;


  }


  if (avatarVal.startsWith('preset:')) {


    const key = avatarVal.replace('preset:', '');


    const item = PROFILE_PRESETS.avatars.find(a => a.id === key);


    if (item && item.svg) {


      imgEl.src = item.svg;


      imgEl.classList.remove('hidden');


      textEl.classList.add('hidden');


      return;


    }


  }


  imgEl.src = avatarVal;


  imgEl.classList.remove('hidden');


  textEl.classList.add('hidden');


}






function applyProfileCover(coverVal, targetEl) {


  if (!targetEl) return;


  if (!coverVal) {


    targetEl.style.background = 'radial-gradient(120% 90% at 12% 0%, rgba(255, 42, 85,0.16), transparent 55%), radial-gradient(90% 80% at 92% 8%, rgba(255, 42, 85,0.14), transparent 60%)';


    return;


  }


  if (coverVal.startsWith('preset:')) {


    const key = coverVal.replace('preset:', '');


    const item = PROFILE_PRESETS.covers.find(c => c.id === key);


    if (item && item.gradient) {


      targetEl.style.background = item.gradient;


      targetEl.style.backgroundSize = 'cover';


      targetEl.style.backgroundPosition = 'center';


      return;


    }


  }


  targetEl.style.backgroundImage = `url("${coverVal}")`;


  targetEl.style.backgroundSize = 'cover';


  targetEl.style.backgroundPosition = 'center';


}






function profileRenderHeader(data) {


  const player = data.player || {};


  const stats = data.stats || {};


  const badgeSummary = data.badge_summary || { unlocked: 0, total: 0 };






  const nameEl = document.getElementById('profilePlayerName');


  if (nameEl) nameEl.textContent = player.name || 'Game Thủ';






  // Avatar (hỗ trợ ảnh/preset hoặc chữ cái đầu)


  const avatarText = document.getElementById('profileAvatarText');


  const avatarImg = document.getElementById('profileAvatarImg');


  if (avatarText) avatarText.textContent = player.initial || '?';


  applyProfileAvatar(player.avatar_url, avatarImg, avatarText);
  updateProfileNavAvatar(player);






  // Cover Banner


  const coverBanner = document.getElementById('profileCoverBanner');


  applyProfileCover(player.cover_url, coverBanner);






  // Bio / Chữ ký


  const bioEl = document.getElementById('profileBioText');


  if (bioEl) {


    if (player.bio) {


      bioEl.textContent = `"${player.bio}"`;


      bioEl.classList.remove('hidden');


    } else {


      bioEl.classList.add('hidden');


    }


  }






  const titleEl = document.getElementById('profileTitleLevel');


  if (titleEl) titleEl.textContent = `${player.title || 'Tân Binh Cổ Ngữ'} · Cấp ${player.level || 1}`;






  const lastActive = document.getElementById('profileLastActive');


  if (lastActive) {


    lastActive.textContent = player.last_active_label


      ? `Hoạt động gần đây: ${player.last_active_label}`


      : 'Chưa có hoạt động chơi game';


  }






  const onlineBadge = document.getElementById('profileOnlineBadge');


  if (onlineBadge) {


    if (player.is_online) {


      onlineBadge.textContent = player.online_provider === 'community' && player.cloud_id


        ? `Đám Mây Cổ Ngữ · ${player.cloud_id}`


        : (player.online_provider === 'gdrive' ? 'Google Drive đã kết nối' : 'Đã kết nối Đám Mây');


      onlineBadge.className = 'text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 font-semibold';


    } else {


      onlineBadge.textContent = 'Hồ sơ Offline · Lưu trên máy';


      onlineBadge.className = 'text-[10px] px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-300 border border-amber-500/30 font-semibold';


    }


  }






  const cloudBtnLabel = document.querySelector('#profileCloudManageBtn span');


  if (cloudBtnLabel) {


    cloudBtnLabel.textContent = player.is_online ? 'Quản Lý Tài Khoản Cloud' : 'Nâng Cấp Tài Khoản Online';


  }






  const xpText = document.getElementById('profileXpText');


  if (xpText) xpText.textContent = `${player.xp || 0} / ${player.next_level_xp || 100} XP`;


  const levelText = document.getElementById('profileLevelText');


  if (levelText) levelText.textContent = `Cấp ${player.level || 1}`;


  const xpFill = document.getElementById('profileXpFill');


  if (xpFill) xpFill.style.width = `${Math.max(0, Math.min(100, player.level_percent || 0))}%`;






  const statGames = document.getElementById('profileStatGames');


  if (statGames) statGames.innerHTML = `${stats.games_owned || 0} <span class="text-[11px] font-normal text-zinc-500">game</span>`;


  const statHours = document.getElementById('profileStatHours');


  if (statHours) statHours.innerHTML = `${stats.formatted_playtime || '0 phút'} <span class="text-[11px] font-normal text-zinc-500">• ${stats.sessions || 0} phiên</span>`;


  const statAch = document.getElementById('profileStatAch');


  if (statAch) statAch.innerHTML = `${stats.achievements_unlocked || 0} <span class="text-[11px] font-normal text-zinc-500">cúp</span>`;


  const statBadges = document.getElementById('profileStatBadges');


  if (statBadges) statBadges.innerHTML = `${badgeSummary.unlocked || 0} <span class="text-[11px] font-normal text-zinc-500">/ ${badgeSummary.total || 0}</span>`;


}






const PROFILE_TIER_STYLE = {


  bronze: { label: 'Đồng', icon: 'text-amber-300', box: 'bg-amber-500/10 border-amber-500/30', chip: 'bg-amber-500/10 text-amber-300 border-amber-500/30' },


  silver: { label: 'Bạc', icon: 'text-slate-200', box: 'bg-slate-400/10 border-slate-400/30', chip: 'bg-slate-400/10 text-slate-200 border-slate-400/30' },


  gold: { label: 'Vàng', icon: 'text-yellow-300', box: 'bg-yellow-400/10 border-yellow-400/30', chip: 'bg-yellow-400/10 text-yellow-300 border-yellow-400/30' }


};






function profileRenderBadges(data) {


  const container = document.getElementById('profileBadgesGrid');


  if (!container) return;


  const badges = data.badges || [];


  const summary = data.badge_summary || { unlocked: 0, total: badges.length };


  const summaryEl = document.getElementById('profileBadgeSummary');


  if (summaryEl) summaryEl.textContent = `${summary.unlocked || 0}/${summary.total || badges.length} đã mở khóa`;






  if (!badges.length) {


    container.innerHTML = '<div class="col-span-full text-center py-8 text-xs text-zinc-500">Chưa có dữ liệu huy hiệu.</div>';


    return;


  }






  container.innerHTML = badges.map(badge => {


    const tier = PROFILE_TIER_STYLE[badge.tier] || PROFILE_TIER_STYLE.bronze;


    const unlocked = !!badge.unlocked;


    const dateLabel = unlocked && badge.unlocked_ts


      ? new Date(badge.unlocked_ts * 1000).toLocaleDateString('vi-VN')


      : '';


    const footer = unlocked


      ? `<div class="text-[10px] text-emerald-300/90">Mở khóa ${dateLabel ? '• ' + dateLabel : ''}</div>`


      : `<div class="space-y-1">


           <div class="flex items-center justify-between text-[10px] text-zinc-500">


             <span>${badge.current}/${badge.target} ${badge.unit}</span>


             <span>${badge.progress}%</span>


           </div>


           <div class="h-1 rounded-full bg-white/[0.06] overflow-hidden">


             <div class="h-full rounded-full bg-red-400/70" style="width:${badge.progress}%"></div>


           </div>


         </div>`;






    return `


      <div class="rounded-xl border ${unlocked ? tier.box : 'border-white/[0.06] bg-[#0A0E1A]'} p-3 space-y-2 ${unlocked ? '' : 'opacity-60'}">


        <div class="flex items-start justify-between">


          <div class="w-9 h-9 rounded-lg ${unlocked ? tier.box : 'bg-white/[0.04] border-white/[0.06]'} border flex items-center justify-center">


            <i data-lucide="${badge.icon}" class="w-4 h-4 ${unlocked ? tier.icon : 'text-zinc-500'}"></i>


          </div>


          <span class="text-[9px] px-1.5 py-0.5 rounded-full border ${tier.chip}">${tier.label}</span>


        </div>


        <div class="text-[12px] font-bold text-white leading-snug">${profileEsc(badge.title)}</div>


        <div class="text-[10px] text-zinc-500 leading-snug">${profileEsc(badge.description)}</div>


        ${footer}


      </div>


    `;


  }).join('');


}






function profileRenderTopGames(data) {


  const container = document.getElementById('profileTopGames');


  if (!container) return;


  const games = data.top_games || [];


  if (!games.length) {


    container.innerHTML = '<div class="text-center py-8 text-xs text-zinc-500">Chưa có giờ chơi nào được ghi nhận. Hãy mở một game để bắt đầu!</div>';


    return;


  }






  container.innerHTML = games.map(game => {


    const total = game.achievements_total || 0;


    const unlocked = game.achievements_unlocked || 0;


    const percent = total > 0 ? Math.min(100, Math.round(unlocked / total * 100)) : 0;


    const achText = total > 0 ? `${unlocked}/${total} thành tựu` : `${unlocked} thành tựu`;


    const cover = game.cover_url


      ? `<img src="${profileEsc(game.cover_url)}" alt="" class="w-10 h-10 rounded-lg object-cover border border-white/10" onerror="this.style.display='none'" />`


      : `<div class="w-10 h-10 rounded-lg bg-white/[0.04] border border-white/[0.06] flex items-center justify-center"><i data-lucide="gamepad-2" class="w-4 h-4 text-zinc-500"></i></div>`;






    return `


      <div class="flex items-center gap-3 p-2.5 rounded-xl bg-white/[0.02] border border-white/[0.05]">


        ${cover}


        <div class="min-w-0 flex-1 space-y-1">


          <div class="text-xs font-bold text-white truncate">${profileEsc(game.title)}</div>


          <div class="text-[10px] text-zinc-400 flex items-center justify-between gap-2">


            <span class="truncate">${achText}</span>


            <span class="shrink-0 text-red-300 font-semibold">${profileEsc(game.formatted_playtime)}</span>


          </div>


          <div class="h-1 rounded-full bg-white/[0.06] overflow-hidden">


            <div class="h-full rounded-full bg-amber-400/80" style="width:${percent}%"></div>


          </div>


        </div>


      </div>


    `;


  }).join('');


}






const PROFILE_ACTIVITY_STYLE = {


  play: { icon: 'gamepad-2', color: 'text-red-300' },


  bookmark: { icon: 'bookmark', color: 'text-amber-300' },


  request: { icon: 'megaphone', color: 'text-red-300' }


};






function profileRenderRecent(data) {


  const container = document.getElementById('profileRecentActivity');


  if (!container) return;


  const items = data.recent_activity || [];


  if (!items.length) {


    container.innerHTML = '<div class="text-center py-8 text-xs text-zinc-500">Chưa có hoạt động nào.</div>';


    return;


  }






  container.innerHTML = items.map(item => {


    const style = PROFILE_ACTIVITY_STYLE[item.type] || PROFILE_ACTIVITY_STYLE.play;


    return `


      <div class="flex items-start gap-2.5 p-2 rounded-lg hover:bg-white/[0.03] transition">


        <div class="w-7 h-7 rounded-full bg-white/[0.04] border border-white/[0.06] flex items-center justify-center shrink-0">


          <i data-lucide="${style.icon}" class="w-3.5 h-3.5 ${style.color}"></i>


        </div>


        <div class="min-w-0 flex-1">


          <div class="text-[11px] font-semibold text-zinc-200 truncate">${profileEsc(item.title)}</div>


          <div class="text-[10px] text-zinc-500 truncate">${profileEsc(item.detail)}</div>


        </div>


        <span class="text-[10px] text-zinc-500 shrink-0">${profileEsc(item.time_label)}</span>


      </div>


    `;


  }).join('');


}






function profileRenderVault(vaultInfo) {


  const cloud = vaultInfo.cloud || {};


  const badge = document.getElementById('profileVaultCloudBadge');


  if (badge) {


    if (cloud.connected || (window.communityCloudLoggedIn)) {


      badge.textContent = 'Đám Mây: Đang kết nối';


      badge.className = 'text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/30';


    } else {


      badge.textContent = 'Bản Lưu Cục Bộ';


      badge.className = 'text-[10px] px-2 py-0.5 rounded-full bg-white/[0.05] text-zinc-400 border border-white/10';


    }


  }






  const setText = (id, val) => {


    const el = document.getElementById(id);


    if (el) el.textContent = val;


  };


  setText('profileVaultUpdated', vaultInfo.formatted_updated_at || 'Chưa có');






  const container = document.getElementById('profileVaultGames');


  const countEl = document.getElementById('profileVaultCount');


  const gamesMap = vaultInfo.games || {};


  const gids = Object.keys(gamesMap);


  if (countEl) countEl.textContent = `${gids.length} game`;


  if (!container) return;






  if (!gids.length) {


    container.innerHTML = '<div class="text-center py-6 text-xs text-zinc-500 bg-black/20 rounded-xl border border-dashed border-white/10">Chưa có bản sao lưu nào. Bấm "Sao Lưu Tất Cả" để bắt đầu sao lưu các tựa game đang có.</div>';


    return;


  }






  container.innerHTML = gids.map(gid => {


    const info = gamesMap[gid] || {};


    const title = info.title || gid;


    const sizeKb = info.save_size_bytes ? `${(info.save_size_bytes / 1024).toFixed(1)} KB` : '';


    const hasSave = !!(info.save_updated_at || info.save_size_bytes);


    const updated = info.save_updated_at


      ? new Date(info.save_updated_at * 1000).toLocaleString('vi-VN')


      : '';






    const saveStatusText = hasSave


      ? `Đã lưu: ${updated}${sizeKb ? ` (${sizeKb})` : ''}`


      : `Chưa có bản sao lưu nào`;






    return `


      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 p-3 rounded-lg bg-white/[0.02] hover:bg-white/[0.04] border border-white/[0.05] transition">


        <div class="min-w-0 space-y-0.5">


          <div class="text-xs font-bold text-white truncate">


            ${profileEsc(title)}


          </div>


          <div class="text-[11px] ${hasSave ? 'text-zinc-400' : 'text-zinc-500 italic'}">


            ${profileEsc(saveStatusText)}


          </div>


        </div>


        <div class="flex items-center gap-2 shrink-0 self-end sm:self-center">


          <button onclick="profileVaultPack('${profileJsArg(gid)}')" class="pixel-btn px-3 py-1.5 text-xs font-medium flex items-center gap-1.5 bg-white/[0.04] hover:bg-white/[0.08] text-slate-200 border border-white/10 rounded" title="Sao lưu save của game này">


            <i data-lucide="arrow-up" class="w-3.5 h-3.5 text-red-400"></i>


            <span>Sao Lưu</span>


          </button>


          <button onclick="profileVaultUnpack('${profileJsArg(gid)}')" ${hasSave ? '' : 'disabled'} class="pixel-btn px-3 py-1.5 text-xs font-medium flex items-center gap-1.5 ${hasSave ? 'bg-white/[0.04] hover:bg-white/[0.08] text-slate-200 border border-white/10' : 'opacity-40 cursor-not-allowed text-zinc-500 border border-white/5'} rounded" title="${hasSave ? 'Khôi phục save của game này vào máy' : 'Chưa có bản sao lưu để khôi phục'}">


            <i data-lucide="arrow-down" class="w-3.5 h-3.5 ${hasSave ? 'text-amber-300' : 'text-zinc-600'}"></i>


            <span>Khôi Phục</span>


          </button>


        </div>


      </div>


    `;


  }).join('');


  if (window.lucide) lucide.createIcons();


}






async function profileOpenSaveDirectory() {


  try {


    const res = await fetch('/api/vault/open_folder', { method: 'POST' });


    const data = await res.json();


    if (data && data.success) {


      showToast('Đã mở thư mục lưu trữ save game!', 'success');


    } else {


      showToast(data ? data.message : 'Không tìm thấy thư mục save', 'error');


    }


  } catch (e) {


    showToast('Lỗi khi mở thư mục: ' + e.message, 'error');


  }


}


window.profileOpenSaveDirectory = profileOpenSaveDirectory;






function toggleProfileExportImportMenu(e) {


  if (e) e.stopPropagation();


  const menu = document.getElementById('profileExportImportMenu');


  if (menu) menu.classList.toggle('hidden');


}


window.toggleProfileExportImportMenu = toggleProfileExportImportMenu;






document.addEventListener('click', (e) => {


  const container = document.getElementById('profileExportImportContainer');


  const menu = document.getElementById('profileExportImportMenu');


  if (container && menu && !container.contains(e.target)) {


    menu.classList.add('hidden');


  }


});






async function profileBackupAllAction() {


  const btn = document.getElementById('btnProfileBackupAll');


  const origHtml = btn ? btn.innerHTML : '';


  if (btn) {


    btn.disabled = true;


    btn.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i><span>Đang Sao Lưu...</span>`;


    if (window.lucide) lucide.createIcons();


  }


  try {


    showToast('Đang quét và sao lưu toàn bộ save game...', 'info');


    if (typeof packAllToVault === 'function') {


      await packAllToVault();


    }


    try {


      await fetch('/api/community_cloud/upload', { method: 'POST' });


    } catch (_) {}


    showToast('Đã sao lưu toàn bộ save game thành công!', 'success');


    await loadProfile(true);


  } catch (e) {


    showToast('Lỗi sao lưu: ' + e.message, 'error');


  } finally {


    if (btn) {


      btn.disabled = false;


      btn.innerHTML = origHtml;


      if (window.lucide) lucide.createIcons();


    }


  }


}


window.profileBackupAllAction = profileBackupAllAction;






async function profileVaultAction(action) {


  try {


    if (action === 'sync') {


      const cloud = (profileVaultData && profileVaultData.cloud) || {};


      if (!cloud.connected) {


        showToast('Chưa kết nối Google Drive. Hãy đăng nhập để đồng bộ Hồ Sơ!', 'warning');


        if (typeof openCloudModal === 'function') openCloudModal();


        return;


      }


      await uploadVaultToDrive();


    } else if (action === 'export') {


      await exportVault();


    } else if (action === 'import') {


      await importVault();


    } else if (action === 'pack_all') {


      await packAllToVault();


    }


  } catch (err) {


    console.warn('[Profile] Vault action failed:', err);


  }


  await loadProfile(true);


}






async function profileVaultPack(gameId) {


  if (typeof packGameToVault !== 'function') return;


  await packGameToVault(gameId);


  await loadProfile(true);


}






async function profileVaultUnpack(gameId) {


  if (typeof unpackGameFromVault !== 'function') return;


  await unpackGameFromVault(gameId);


  await loadProfile(true);


}






// Tạo / đăng nhập / đăng xuất Cloud ID xong -> cập nhật ngay header Hồ Sơ


window.addEventListener('congu:community-cloud-changed', () => {


  const view = document.getElementById('viewProfile');


  if (view && !view.classList.contains('hidden')) loadProfile(true);


});










// =============================================================================


// MODAL CHỈNH SỬA HỒ SƠ GAME THỦ (AVATAR, COVER, CLOUD SYNC)


// =============================================================================


let profileEditDraft = {


  name: '',


  avatar: '',


  cover: '',


  bio: '',


  syncCloud: true


};






function openProfileEditModal(defaultTab = 'avatar') {


  const modal = document.getElementById('profileEditModal');


  if (!modal) return;






  const player = (profileOverview && profileOverview.player) || {};


  profileEditDraft.name = player.name || 'Game Thủ';


  profileEditDraft.avatar = player.avatar_url || '';


  profileEditDraft.cover = player.cover_url || '';


  profileEditDraft.bio = player.bio || '';


  profileEditDraft.syncCloud = true;






  // Populate form fields


  const nameInput = document.getElementById('editInputPlayerName');


  if (nameInput) nameInput.value = profileEditDraft.name;






  const bioInput = document.getElementById('editInputBio');


  if (bioInput) bioInput.value = profileEditDraft.bio;






  const avatarInput = document.getElementById('editInputAvatarUrl');


  if (avatarInput) avatarInput.value = profileEditDraft.avatar.startsWith('data:') ? '' : profileEditDraft.avatar;






  const coverInput = document.getElementById('editInputCoverUrl');


  if (coverInput) coverInput.value = profileEditDraft.cover.startsWith('data:') ? '' : profileEditDraft.cover;






  const syncCheck = document.getElementById('editCheckSyncCloud');


  if (syncCheck) syncCheck.checked = true;






  renderProfilePresetsUI();


  updateProfileEditPreview();


  switchProfileEditTab(defaultTab);






  modal.classList.remove('hidden');


  if (window.lucide) lucide.createIcons();


}






function closeProfileEditModal() {


  const modal = document.getElementById('profileEditModal');


  if (modal) modal.classList.add('hidden');


}






function switchProfileEditTab(tab) {


  ['avatar', 'cover', 'info'].forEach(t => {


    const btn = document.getElementById(`editTabBtn-${t}`);


    const content = document.getElementById(`editTabContent-${t}`);


    const isActive = t === tab;


    if (btn) {


      btn.className = isActive


        ? 'pixel-tab active-filter-tab px-4 py-2 text-xs font-bold transition flex items-center gap-1.5'


        : 'pixel-tab px-4 py-2 text-xs font-bold transition flex items-center gap-1.5 text-zinc-400 hover:text-white';


    }


    if (content) {


      content.classList.toggle('hidden', !isActive);


    }


  });


  if (window.lucide) lucide.createIcons();


}






function renderProfilePresetsUI() {


  // 1. Render Avatar presets


  const avatarGrid = document.getElementById('editAvatarPresetsGrid');


  if (avatarGrid) {


    avatarGrid.innerHTML = PROFILE_PRESETS.avatars.map(item => {


      const isSelected = profileEditDraft.avatar === `preset:${item.id}`;


      return `


        <div 


          onclick="profileSelectPresetAvatar('${item.id}')"


          class="group relative flex flex-col items-center gap-1.5 p-1.5 rounded-xl border ${isSelected ? 'border-red-400 bg-red-500/20 ring-2 ring-red-400/50 shadow-[0_0_15px_rgba(255, 42, 85,0.3)]' : 'border-white/10 bg-black/30 hover:border-white/30'} cursor-pointer transition-all hover:scale-105"


          title="${item.name} (${item.tag})"


        >


          <div class="w-12 h-12 rounded-lg overflow-hidden flex items-center justify-center pointer-events-none">


            <img src="${item.svg}" alt="${item.name}" class="w-full h-full object-cover" />


          </div>


          <span class="text-[9px] font-semibold text-zinc-300 truncate w-full text-center">${item.name}</span>


        </div>


      `;


    }).join('');


  }






  // 2. Render Cover presets


  const coverGrid = document.getElementById('editCoverPresetsGrid');


  if (coverGrid) {


    coverGrid.innerHTML = PROFILE_PRESETS.covers.map(item => {


      const isSelected = profileEditDraft.cover === `preset:${item.id}`;


      return `


        <div 


          onclick="profileSelectPresetCover('${item.id}')"


          class="group relative flex flex-col overflow-hidden rounded-xl border ${isSelected ? 'border-red-400 bg-red-500/20 ring-2 ring-red-400/50 shadow-[0_0_15px_rgba(255, 42, 85,0.3)]' : 'border-white/10 bg-black/40 hover:border-white/30'} cursor-pointer transition-all hover:scale-[1.02]"


          title="${item.name}"


        >


          <div class="h-16 w-full rounded-t-xl bg-cover bg-center" style="background: ${item.gradient}; background-size: cover;"></div>


          <div class="p-2 bg-[#0d1222] flex items-center justify-between">


            <span class="text-[11px] font-bold text-white truncate">${item.name}</span>


            <span class="text-[9px] px-1.5 py-0.5 rounded bg-white/[0.06] text-red-300 border border-white/10">${item.tag}</span>


          </div>


        </div>


      `;


    }).join('');


  }


}






function updateProfileEditPreview() {


  const avatarImg = document.getElementById('editModalAvatarImgPreview');


  const avatarText = document.getElementById('editModalAvatarTextPreview');


  const namePreview = document.getElementById('editModalNamePreview');


  const bioPreview = document.getElementById('editModalBioPreview');


  const coverPreview = document.getElementById('editModalCoverPreview');






  if (namePreview) namePreview.textContent = profileEditDraft.name || 'Game Thủ';


  if (bioPreview) {


    bioPreview.textContent = profileEditDraft.bio ? `"${profileEditDraft.bio}"` : 'Chưa có chữ ký cá nhân';


  }


  if (avatarText) avatarText.textContent = ((profileEditDraft.name || 'G').charAt(0) || 'G').toUpperCase();






  applyProfileAvatar(profileEditDraft.avatar, avatarImg, avatarText);


  applyProfileCover(profileEditDraft.cover, coverPreview);


}






function profileSelectPresetAvatar(id) {


  profileEditDraft.avatar = `preset:${id}`;


  const input = document.getElementById('editInputAvatarUrl');


  if (input) input.value = '';


  renderProfilePresetsUI();


  updateProfileEditPreview();


}






function profileSelectPresetCover(id) {


  profileEditDraft.cover = `preset:${id}`;


  const input = document.getElementById('editInputCoverUrl');


  if (input) input.value = '';


  renderProfilePresetsUI();


  updateProfileEditPreview();


}






function profileOnAvatarUrlInput(url) {


  profileEditDraft.avatar = (url || '').trim();


  renderProfilePresetsUI();


  updateProfileEditPreview();


}






function profileOnCoverUrlInput(url) {


  profileEditDraft.cover = (url || '').trim();


  renderProfilePresetsUI();


  updateProfileEditPreview();


}






function profileOnNameInput(name) {


  profileEditDraft.name = (name || '').trim();


  updateProfileEditPreview();


}






function profileOnBioInput(bio) {


  profileEditDraft.bio = (bio || '').trim();


  updateProfileEditPreview();


}






function applyPickedImageData(type, dataUri, filename, sizeKb) {


  if (type === 'avatar') {


    profileEditDraft.avatar = dataUri;


    const input = document.getElementById('editInputAvatarUrl');


    if (input) input.value = `[Tệp: ${filename || 'avatar'} (${sizeKb || 0} KB)]`;


  } else {


    profileEditDraft.cover = dataUri;


    const input = document.getElementById('editInputCoverUrl');


    if (input) input.value = `[Tệp: ${filename || 'cover'} (${sizeKb || 0} KB)]`;


  }


  renderProfilePresetsUI();


  updateProfileEditPreview();


  showToast(`Đã tải ảnh ${filename || ''} (${sizeKb || 0} KB)! Bấm "Lưu & Đồng Bộ" để áp dụng.`, 'success');


}






function profileHandleDirectFile(inputEl, type) {


  const file = inputEl && inputEl.files && inputEl.files[0];


  if (!file) return;






  if (file.size > 2 * 1024 * 1024) {


    showToast('Tệp ảnh vượt quá 2MB! Vui lòng chọn ảnh nhỏ hơn để đảm bảo đồng bộ mượt mà.', 'warning');


    return;


  }






  const reader = new FileReader();


  reader.onload = function (e) {


    const dataUri = e.target.result;


    const sizeKb = Math.round(file.size / 1024);


    applyPickedImageData(type, dataUri, file.name, sizeKb);


  };


  reader.onerror = function () {


    showToast('Không thể đọc file ảnh đã chọn!', 'error');


  };


  reader.readAsDataURL(file);


}






async function profilePickImageFromDisk(type = 'avatar') {


  // Thử gọi native dialog trước


  try {


    showToast(`Đang mở hộp thoại chọn ảnh ${type === 'avatar' ? 'Avatar' : 'Ảnh Bìa'}...`, 'info');


    const resp = await fetch('/api/profile/select_image', {


      method: 'POST',


      headers: { 'Content-Type': 'application/json' },


      body: JSON.stringify({ type: type })


    });


    if (resp.ok) {


      const res = await resp.json();


      if (res.cancelled) return;


      if (res.success && res.data_uri) {


        applyPickedImageData(type, res.data_uri, res.filename, res.size_kb);


        return;


      }


    }


  } catch (err) {


    console.warn('[Profile] Native file dialog failed, falling back to browser file input:', err);


  }






  // Fallback: kích hoạt trực tiếp HTML5 file input nếu native dialog không hỗ trợ hoặc lỗi


  const directId = type === 'avatar' ? 'profileDirectAvatarInput' : 'profileDirectCoverInput';


  const fileInput = document.getElementById(directId);


  if (fileInput) {


    fileInput.value = '';


    fileInput.click();


  }


}






async function profileSaveSettings() {


  const btn = document.getElementById('btnProfileSaveSettings');


  const origHtml = btn ? btn.innerHTML : '';


  if (btn) {


    btn.disabled = true;


    btn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i><span>Đang Lưu & Đồng Bộ...</span>';


    if (window.lucide) lucide.createIcons();


  }






  const syncCheck = document.getElementById('editCheckSyncCloud');


  const doSync = syncCheck ? syncCheck.checked : true;






  try {


    const payload = {


      player_name: profileEditDraft.name,


      avatar_url: profileEditDraft.avatar,


      cover_url: profileEditDraft.cover,


      bio: profileEditDraft.bio,


      sync_cloud: doSync


    };






    const resp = await fetch('/api/profile/update', {


      method: 'POST',


      headers: { 'Content-Type': 'application/json' },


      body: JSON.stringify(payload)


    });


    const data = await resp.json();






    if (data.success) {


      showToast(data.message || 'Đã lưu và đồng bộ Hồ Sơ thành công!', 'success');


      closeProfileEditModal();


      await loadProfile(true);


      window.dispatchEvent(new CustomEvent('congu:community-cloud-changed'));


    } else {


      showToast(data.error || 'Lỗi khi lưu cài đặt hồ sơ!', 'error');


    }


  } catch (err) {


    showToast(`Lỗi lưu hồ sơ: ${err.message}`, 'error');


  } finally {


    if (btn) {


      btn.disabled = false;


      btn.innerHTML = origHtml;


      if (window.lucide) lucide.createIcons();


    }


  }


}






// Hỗ trợ mở trực tiếp qua URL Hash #profile


window.addEventListener('DOMContentLoaded', () => {


  if (window.location.hash === '#profile') {


    setTimeout(openProfilePage, 300);


  }


});


window.addEventListener('hashchange', () => {


  if (window.location.hash === '#profile') {


    openProfilePage();


  }


});










// Gắn tường minh vào window để mọi nút bấm onclick trong HTML luôn gọi được


window.openProfilePage = openProfilePage;


window.openProfileEditModal = openProfileEditModal;


window.closeProfileEditModal = closeProfileEditModal;


window.switchProfileEditTab = switchProfileEditTab;


window.renderProfilePresetsUI = renderProfilePresetsUI;


window.updateProfileEditPreview = updateProfileEditPreview;


window.profileSelectPresetAvatar = profileSelectPresetAvatar;


window.profileSelectPresetCover = profileSelectPresetCover;


window.profileOnAvatarUrlInput = profileOnAvatarUrlInput;


window.profileOnCoverUrlInput = profileOnCoverUrlInput;


window.profileOnNameInput = profileOnNameInput;


window.profileOnBioInput = profileOnBioInput;


window.profilePickImageFromDisk = profilePickImageFromDisk;


window.profileHandleDirectFile = profileHandleDirectFile;


window.profileSaveSettings = profileSaveSettings;


// Tự động tải avatar người dùng lên thanh điều hướng khi khởi động
async function initNavProfileAvatar() {
  try {
    let player = null;
    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.get_profile_overview === 'function') {
      const data = await window.pywebview.api.get_profile_overview();
      if (data && data.player) player = data.player;
    }
    if (!player) {
      const res = await fetch('/api/profile/overview');
      if (res.ok) {
        const data = await res.json();
        if (data && data.player) player = data.player;
      }
    }
    if (player) {
      updateProfileNavAvatar(player);
    }
  } catch (e) {
    console.warn('[ProfileNav] initNavProfileAvatar:', e);
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initNavProfileAvatar);
} else {
  initNavProfileAvatar();
}
window.addEventListener('pywebviewready', initNavProfileAvatar);
