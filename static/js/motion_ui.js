// =============================================================================
// CỔ NGỮ (VIETMODHUB) - iOS MOTION HELPERS
// Spring physics, sliding nav pill, view transitions, fly-to-library.
// =============================================================================

function iosReducedMotion() {
  return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
}

function iosSyncNavPill() {
  const nav = document.getElementById('mainNav');
  if (!nav) return;

  nav.classList.add('ios-pill-track');
  let pill = nav.querySelector('.ios-nav-pill');
  if (!pill) {
    pill = document.createElement('div');
    pill.className = 'ios-nav-pill';
    nav.insertBefore(pill, nav.firstChild);
  }

  const active = nav.querySelector('.ui-tab-nav.is-active');
  const navStyle = window.getComputedStyle(nav);
  if (!active || navStyle.display === 'none' || navStyle.visibility === 'hidden') {
    pill.style.opacity = '0';
    return;
  }

  const navRect = nav.getBoundingClientRect();
  const activeRect = active.getBoundingClientRect();
  if (!activeRect.width) {
    pill.style.opacity = '0';
    return;
  }
  pill.style.width = `${activeRect.width}px`;
  pill.style.height = `${activeRect.height}px`;
  pill.style.top = `${activeRect.top - navRect.top}px`;
  pill.style.bottom = 'auto';
  pill.style.transform = `translateX(${activeRect.left - navRect.left}px)`;
  pill.style.opacity = '1';
}

function withIosViewTransition(update) {
  if (typeof update !== 'function') return;

  const afterUpdate = () => {
    update();
    setTimeout(() => {
      if (typeof window.iosUpdateScrollEffects === 'function') window.iosUpdateScrollEffects();
    }, 80);
  };

  if (!document.startViewTransition || iosReducedMotion()) {
    afterUpdate();
    return;
  }
  try {
    document.startViewTransition(afterUpdate);
  } catch (err) {
    afterUpdate();
  }
}

function iosInitScrollEffects() {
  const scroller = document.getElementById('mainScrollContainer');
  if (!scroller) return;

  const heroBg = document.getElementById('heroBg');
  if (heroBg) heroBg.classList.add('ios-parallax-bg');
  const progress = document.getElementById('scrollProgressBar');

  let ticking = false;
  const update = () => {
    ticking = false;
    const y = scroller.scrollTop || 0;

    if (heroBg) {
      if (iosReducedMotion()) {
        heroBg.style.transform = '';
      } else {
        const offset = Math.min(y, 620);
        heroBg.style.transform = `translate3d(0, ${offset * 0.28}px, 0) scale(1.06)`;
      }
    }

    if (progress) {
      const max = scroller.scrollHeight - scroller.clientHeight;
      const ratio = max > 0 ? Math.min(1, Math.max(0, y / max)) : 0;
      progress.style.transform = `scaleX(${ratio})`;
    }
  };

  window.iosUpdateScrollEffects = update;
  scroller.addEventListener('scroll', () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(update);
  }, { passive: true });

  const content = scroller.firstElementChild;
  if (content && window.ResizeObserver) {
    const resizeObserver = new ResizeObserver(() => update());
    resizeObserver.observe(content);
  }
  window.addEventListener('resize', update);
  update();
}

function iosRevealCards(container) {
  if (!container) return;
  const cards = Array.from(container.querySelectorAll('.pixel-card[data-game-id]'));
  if (!cards.length || iosReducedMotion()) return;
  if (!('IntersectionObserver' in window)) return;

  if (window.__iosCardObserver) {
    try { window.__iosCardObserver.disconnect(); } catch (_) {}
  }

  // Giữ thẻ ở trạng thái chờ trong đúng frame render để không bị nháy
  cards.forEach(card => card.classList.add('ios-reveal-pending'));

  const root = document.getElementById('mainScrollContainer');
  const observer = new IntersectionObserver((entries) => {
    const visible = entries.filter(entry => entry.isIntersecting);
    visible.forEach((entry, index) => {
      const card = entry.target;
      card.classList.remove('ios-reveal-pending');
      card.style.animationDelay = `${Math.min(index * 35, 210)}ms`;
      card.classList.add('game-card-enter');
      observer.unobserve(card);
    });
  }, {
    root: root || null,
    threshold: 0.06,
    rootMargin: '0px 0px -20px 0px'
  });

  window.__iosCardObserver = observer;
  cards.forEach(card => observer.observe(card));
}

function iosInitRipple() {
  document.addEventListener('pointerdown', (event) => {
    if (event.button !== 0 || iosReducedMotion()) return;
    const btn = event.target && event.target.closest
      ? event.target.closest('.pixel-btn, .ui-tab-nav, .ui-icon-btn')
      : null;
    if (!btn) return;

    const rect = btn.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height) * 1.1;
    if (!size) return;

    const ripple = document.createElement('span');
    ripple.className = 'ios-ripple';
    ripple.style.width = `${size}px`;
    ripple.style.height = `${size}px`;
    ripple.style.left = `${event.clientX - rect.left - size / 2}px`;
    ripple.style.top = `${event.clientY - rect.top - size / 2}px`;

    btn.classList.add('ios-ripple-host');
    btn.appendChild(ripple);
    setTimeout(() => {
      ripple.remove();
      if (!btn.querySelector('.ios-ripple')) btn.classList.remove('ios-ripple-host');
    }, 600);
  }, { passive: true });
}

function iosLibraryTarget() {
  const candidates = [
    document.querySelector('[data-nav="library"]'),
    document.querySelector('button[onclick*="switchToGridView"]')
  ];
  return candidates.find(el => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }) || null;
}

function flyCoverToLibrary(sourceImg) {
  if (!sourceImg || iosReducedMotion()) return;
  const target = iosLibraryTarget();
  if (!target) return;

  const start = sourceImg.getBoundingClientRect();
  if (!start.width || !start.height) return;
  const end = target.getBoundingClientRect();

  const clone = sourceImg.cloneNode(true);
  Object.assign(clone.style, {
    position: 'fixed',
    left: `${start.left}px`,
    top: `${start.top}px`,
    width: `${start.width}px`,
    height: `${start.height}px`,
    objectFit: 'cover',
    borderRadius: '12px',
    zIndex: '9999',
    pointerEvents: 'none',
    boxShadow: '0 12px 30px rgba(255, 42, 85, 0.45)'
  });
  document.body.appendChild(clone);

  const dx = (end.left + end.width / 2) - (start.left + start.width / 2);
  const dy = (end.top + end.height / 2) - (start.top + start.height / 2);

  const anim = clone.animate([
    { transform: 'translate(0, 0) scale(1)', opacity: 1, offset: 0 },
    { transform: `translate(${dx * 0.5}px, ${dy * 0.5 - 70}px) scale(0.42)`, opacity: 0.9, offset: 0.45 },
    { transform: `translate(${dx}px, ${dy}px) scale(0.08)`, opacity: 0, offset: 1 }
  ], {
    duration: 560,
    easing: 'cubic-bezier(0.22, 1, 0.36, 1)'
  });

  const cleanup = () => clone.remove();
  if (anim) anim.onfinish = cleanup;
  else setTimeout(cleanup, 620);

  if (target.animate) {
    target.animate([
      { transform: 'scale(1)' },
      { transform: 'scale(1.16)' },
      { transform: 'scale(1)' }
    ], { duration: 360, easing: 'cubic-bezier(0.34, 1.56, 0.64, 1)' });
  }
}

(function initIosMotion() {
  const boot = () => {
    iosSyncNavPill();
    iosInitScrollEffects();
    iosInitRipple();
    setTimeout(iosSyncNavPill, 150);
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  window.addEventListener('resize', () => iosSyncNavPill());
  window.addEventListener('load', () => iosSyncNavPill());
  setTimeout(iosSyncNavPill, 400);
  setTimeout(iosSyncNavPill, 1200);
})();
