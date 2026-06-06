/* ============================================================
   INTERNOVA ANIMATION UTILITIES v2
   ============================================================ */

/* ---- RIPPLE ON BUTTONS ---- */
document.addEventListener('click', e => {
  const btn = e.target.closest('.btn');
  if (!btn || btn.classList.contains('loading')) return;

  const rect   = btn.getBoundingClientRect();
  const size   = Math.max(rect.width, rect.height) * 2;
  const x      = e.clientX - rect.left - size / 2;
  const y      = e.clientY - rect.top  - size / 2;

  const ripple = document.createElement('span');
  ripple.className = 'ripple';
  ripple.style.cssText = `width:${size}px;height:${size}px;left:${x}px;top:${y}px`;
  btn.appendChild(ripple);
  ripple.addEventListener('animationend', () => ripple.remove());
});

/* ---- COUNTER ANIMATION ---- */
function animateCounter(el) {
  const target = parseFloat(el.dataset.target || el.textContent.replace(/[^0-9.]/g, ''));
  const suffix = el.dataset.suffix || el.textContent.replace(/[0-9.]/g, '');
  if (isNaN(target)) return;

  const duration = 900;
  const start    = performance.now();
  const isDecimal = String(target).includes('.');
  const decimals  = isDecimal ? (String(target).split('.')[1] || '').length : 0;

  function ease(t) { return 1 - Math.pow(1 - t, 4); }

  function update(now) {
    const elapsed = now - start;
    const progress = Math.min(elapsed / duration, 1);
    const current  = target * ease(progress);
    el.textContent = (isDecimal ? current.toFixed(decimals) : Math.round(current)) + suffix;
    if (progress < 1) requestAnimationFrame(update);
  }
  requestAnimationFrame(update);
}

/* ---- INTERSECTION OBSERVER for scroll-reveal & counter ---- */
const revealObserver = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (!entry.isIntersecting) return;
    const el = entry.target;

    /* Counter */
    if (el.classList.contains('animate-count')) {
      animateCounter(el);
      revealObserver.unobserve(el);
    }

    /* Reveal stagger */
    if (el.classList.contains('reveal')) {
      el.classList.add('revealed');
      revealObserver.unobserve(el);
    }
  });
}, { threshold: 0.2, rootMargin: '0px 0px -40px 0px' });

/* Init counters and reveal elements */
function initAnimations() {
  document.querySelectorAll('.animate-count').forEach(el => revealObserver.observe(el));
  document.querySelectorAll('.reveal').forEach(el => revealObserver.observe(el));

  /* Stagger grid cards automatically */
  document.querySelectorAll('.card-grid').forEach(grid => {
    grid.querySelectorAll('.card').forEach((card, i) => {
      card.style.animationDelay = (i * 65) + 'ms';
      card.style.animationFillMode = 'both';
    });
  });

  /* Auto-dismiss flash messages */
  document.querySelectorAll('.flash-msg').forEach(el => {
    setTimeout(() => {
      el.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
      el.style.opacity = '0';
      el.style.transform = 'translateY(-8px)';
      setTimeout(() => el.remove(), 500);
    }, 10000);
  });
}

document.addEventListener('DOMContentLoaded', initAnimations);

/* ---- SMOOTH SECTION TRANSITIONS (SPA) ---- */
const origShowSection = window.showSection;
if (typeof window.showSection !== 'undefined') {
  window.showSection = function(id) {
    origShowSection?.(id);
    const el = document.getElementById(id);
    if (el) {
      el.style.animation = 'none';
      el.offsetHeight; /* reflow */
      el.style.animation = '';
    }
  };
}

/* ---- THEME TRANSITION ---- */
function smoothThemeChange() {
  document.documentElement.style.transition = 'background 0.35s ease, color 0.35s ease';
  setTimeout(() => {
    document.documentElement.style.transition = '';
  }, 400);
}

const origToggleTheme = window.toggleTheme;
if (typeof window.toggleTheme !== 'undefined') {
  window.toggleTheme = function() {
    smoothThemeChange();
    origToggleTheme?.();
  };
}

/* ---- INPUT FOCUS ANIMATIONS ---- */
document.addEventListener('focusin', e => {
  if (e.target.matches('.input')) {
    e.target.style.transition = 'border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease';
  }
});

/* ---- PAGE LOAD PROGRESS BAR ---- */
(function() {
  const bar = document.createElement('div');
  bar.id = 'page-progress';
  bar.style.cssText = `
    position: fixed; top: 0; left: 0; height: 2px; z-index: 9999;
    background: linear-gradient(90deg, rgba(130,140,255,0.8), rgba(100,180,255,0.8));
    transition: width 0.3s ease, opacity 0.4s ease;
    width: 0; opacity: 0;
    pointer-events: none;
  `;
  document.body.prepend(bar);

  /* Animate on load */
  window.addEventListener('load', () => {
    bar.style.opacity = '1';
    bar.style.width   = '100%';
    setTimeout(() => { bar.style.opacity = '0'; bar.style.width = '0'; }, 600);
  });
})();

/* ---- HOVER SOUND (subtle visual feedback enhancement) ---- */
document.addEventListener('mouseover', e => {
  const card = e.target.closest('.card');
  if (card && !card._hoverInitialized) {
    card._hoverInitialized = true;
  }
});
