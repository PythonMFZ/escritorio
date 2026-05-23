/* ============================================================
   Maffezzolli Capital — main.js
   ============================================================ */

/* ── Nav scroll state ──────────────────────────────────────── */
const nav = document.querySelector('nav');
window.addEventListener('scroll', () => {
  nav && nav.classList.toggle('scrolled', window.scrollY > 40);
}, { passive: true });

/* ── Active nav link ───────────────────────────────────────── */
(function () {
  const path = window.location.pathname.replace(/\/$/, '') || '/';
  document.querySelectorAll('.nav-links a, .mobile-menu a').forEach(a => {
    const href = a.getAttribute('href').replace(/\/$/, '') || '/';
    if (href === path || (path === '/' && (href === '/index.html' || href === '.'))) {
      a.classList.add('active');
    }
  });
})();

/* ── Hamburger menu ────────────────────────────────────────── */
const hamburger   = document.querySelector('.hamburger');
const mobileMenu  = document.querySelector('.mobile-menu');
hamburger && hamburger.addEventListener('click', () => {
  hamburger.classList.toggle('open');
  mobileMenu.classList.toggle('open');
});
mobileMenu && mobileMenu.querySelectorAll('a').forEach(a => {
  a.addEventListener('click', () => {
    hamburger.classList.remove('open');
    mobileMenu.classList.remove('open');
  });
});

/* ── Fade-up on scroll ─────────────────────────────────────── */
const observer = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('visible');
    }
  });
}, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });

document.querySelectorAll('.fade-up').forEach(el => observer.observe(el));
