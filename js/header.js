/**
 * AutoPrestige — Header / Menu partagé
 * Injecte le même menu sur toutes les pages.
 * Inscription est dans le menu « Plus ».
 */
(function () {
  'use strict';

  // Escape HTML to prevent XSS attacks
  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  /* SVG Icons for header */
  const ICONS = {
    moon: '<svg class="icon-moon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>',
    sun: '<svg class="icon-sun" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>',
    globe: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>',
    menu: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>',
    chevronDown: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>',
  };

  const PAGES = {
    home: 'index.html',
    vehicles: 'vehicules.html',
    financing: 'financement.html',
    sell: 'vendre.html',
    contact: 'contact.html',
    brands: 'marques.html',
    warranty: 'garantie.html',
    rv: 'camping-car.html',
    agri: 'machines-agricoles.html',
    insurance: 'assurance.html',
    delivery: 'livraison.html',
    maintenance: 'entretien.html',
    faq: 'faq.html',
    about: 'a-propos.html',
    reviews: 'avis.html',
    login: 'connexion.html',
    register: 'inscription.html',
    account: 'compte.html',
  };

  function currentFile() {
    const path = window.location.pathname || '';
    const name = path.split('/').pop() || 'index.html';
    return name === '' ? 'index.html' : name;
  }

  function isActive(file) {
    return currentFile() === file ? ' active' : '';
  }

  function buildHeaderHTML() {
    return `
  <header class="header" id="main-header">
    <div class="container header-inner">
      <a href="${PAGES.home}" class="logo">
        <img src="Logo.svg" alt="Auto-prestige">
        Auto-<span>prestige</span>
      </a>

      <nav class="nav" id="main-nav" aria-label="Navigation principale">
        <a href="${PAGES.home}" class="${isActive(PAGES.home).trim()}" data-i18n="nav.home">Accueil</a>
        <a href="${PAGES.vehicles}" class="${isActive(PAGES.vehicles).trim()}" data-i18n="nav.vehicles">Véhicules</a>
        <a href="${PAGES.financing}" class="${isActive(PAGES.financing).trim()}" data-i18n="nav.financing">Financement</a>
        <a href="${PAGES.sell}" class="${isActive(PAGES.sell).trim()}" data-i18n="nav.sell">Vendre</a>
        <a href="${PAGES.contact}" class="${isActive(PAGES.contact).trim()}" data-i18n="nav.contact">Contact</a>

        <div class="nav-item" id="nav-more">
          <a href="#" class="nav-more-toggle" data-i18n="nav.more" aria-haspopup="true" aria-expanded="false">Plus ${ICONS.chevronDown}</a>
          <div class="dropdown" role="menu">
            <a href="${PAGES.brands}" class="${isActive(PAGES.brands).trim()}" data-i18n="nav.brands">Marques</a>
            <a href="${PAGES.warranty}" class="${isActive(PAGES.warranty).trim()}" data-i18n="nav.warranty">Garantie</a>
            <a href="${PAGES.rv}" class="${isActive(PAGES.rv).trim()}" data-i18n="nav.rv">Camping-car</a>
            <a href="${PAGES.agri}" class="${isActive(PAGES.agri).trim()}" data-i18n="nav.agri">Machines agricoles</a>
            <a href="${PAGES.insurance}" class="${isActive(PAGES.insurance).trim()}" data-i18n="nav.insurance">Assurance</a>
            <a href="${PAGES.delivery}" class="${isActive(PAGES.delivery).trim()}" data-i18n="nav.delivery">Livraison</a>
            <a href="${PAGES.maintenance}" class="${isActive(PAGES.maintenance).trim()}" data-i18n="nav.maintenance">Entretien</a>
            <a href="${PAGES.faq}" class="${isActive(PAGES.faq).trim()}" data-i18n="nav.faq">FAQ</a>
            <a href="${PAGES.about}" class="${isActive(PAGES.about).trim()}" data-i18n="nav.about">À propos</a>
            <a href="${PAGES.reviews}" class="${isActive(PAGES.reviews).trim()}" data-i18n="nav.reviews">Avis clients</a>
            <div class="dropdown-divider"></div>
            <a href="${PAGES.register}" class="${isActive(PAGES.register).trim()}" data-i18n="nav.register">Inscription</a>
            <a href="${PAGES.login}" class="${isActive(PAGES.login).trim()}" data-i18n="nav.login">Connexion</a>
          </div>
        </div>
      </nav>

      <div class="header-actions">
        <button type="button" class="theme-toggle" id="theme-toggle" aria-label="Changer le thème">${ICONS.moon}${ICONS.sun}</button>
        <div class="header-auth" id="header-auth">
          <a href="${PAGES.login}" class="header-auth-link" data-i18n="nav.login">Connexion</a>
        </div>
        <button type="button" class="mobile-toggle" aria-label="Menu" data-i18n-aria="header.menu" id="mobile-toggle"><span aria-hidden="true">${ICONS.menu}</span></button>
      </div>
    </div>
  </header>`;
  }

  function bindMobileMenu() {
    const toggle = document.getElementById('mobile-toggle');
    const nav = document.getElementById('main-nav');
    if (!toggle || !nav) return;

    toggle.addEventListener('click', (e) => {
      e.stopPropagation();
      nav.classList.toggle('open');
      toggle.setAttribute('aria-expanded', nav.classList.contains('open') ? 'true' : 'false');
    });

    // Dropdown "Plus" on mobile (click)
    const more = document.getElementById('nav-more');
    if (more) {
      const moreToggle = more.querySelector('.nav-more-toggle');
      if (moreToggle) {
        moreToggle.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          more.classList.toggle('open');
          moreToggle.setAttribute('aria-expanded', more.classList.contains('open') ? 'true' : 'false');
        });
      }
    }

    // Close mobile nav on link click
    nav.querySelectorAll('a[href]:not(.nav-more-toggle)').forEach((link) => {
      link.addEventListener('click', () => {
        nav.classList.remove('open');
      });
    });
  }

  function updateAuthArea() {
    const el = document.getElementById('header-auth');
    if (!el) return;
    try {
      const token = localStorage.getItem('token') || localStorage.getItem('access_token');
      const userRaw = localStorage.getItem('user');
      if (token && userRaw) {
        const user = JSON.parse(userRaw);
        const name = (user.first_name || user.email || 'Compte').toString();
        const safeName = escapeHtml(name);
        el.innerHTML = `
          <div class="header-auth-user">
            <a href="${PAGES.account}">${safeName}</a>
          </div>`;
      }
    } catch (_) {
      /* ignore */
    }
  }

  async function updateSiteContactInfo() {
    const configuredBase = localStorage.getItem('api_base');
    const isLocal = ['localhost', '127.0.0.1', '::1'].includes(window.location.hostname);
    const apiBase = configuredBase
      ? configuredBase.replace(/\/$/, '') + '/api'
      : (isLocal ? 'http://127.0.0.1:8000/api' : 'https://autoprestige-api.onrender.com/api');
    try {
      const response = await fetch(apiBase + '/site-settings');
      if (!response.ok) return;
      const settings = await response.json();
      const phone = (settings.contact_phone || '').trim();
      const email = (settings.contact_email || '').trim();
      const whatsapp = (settings.contact_whatsapp || '').replace(/[^0-9+]/g, '');
      const address = (settings.contact_address || '').trim();

      if (phone) {
        document.querySelectorAll('a[href^="tel:"]').forEach((link) => {
          link.href = 'tel:' + phone.replace(/[^0-9+]/g, '');
          link.textContent = phone;
        });
      }
      if (email) {
        document.querySelectorAll('a[href^="mailto:"]').forEach((link) => {
          link.href = 'mailto:' + email;
          link.textContent = email;
        });
      }
      if (whatsapp) {
        document.querySelectorAll('a[href*="wa.me/"]').forEach((link) => {
          link.href = 'https://wa.me/' + whatsapp;
        });
      }
      if (address) {
        document.querySelectorAll('[data-site-address]').forEach((element) => {
          element.textContent = address;
        });
      }
    } catch (_) {
      // The static contact values remain available if the API is offline.
    }
  }



  /** theme preference: 'light' | 'dark' uniquement */
  function getThemePref() {
    const v = localStorage.getItem('theme');
    // Migrer l'ancien mode "system" vers dark
    if (v === 'light' || v === 'dark') return v;
    return 'dark';
  }

  function resolveTheme(pref) {
    return (pref === 'light') ? 'light' : 'dark';
  }

  function applyThemeFromPref(pref) {
    pref = (pref === 'light') ? 'light' : 'dark';
    const resolved = resolveTheme(pref);
    // Smooth transition flash
    document.documentElement.classList.add('theme-switching');
    requestAnimationFrame(() => {
      document.documentElement.setAttribute('data-theme', resolved);
      document.documentElement.setAttribute('data-theme-pref', pref);
      localStorage.setItem('theme', pref);
      requestAnimationFrame(() => {
        setTimeout(() => {
          document.documentElement.classList.remove('theme-switching');
        }, 50);
      });
    });

    const btn = document.getElementById('theme-toggle');
    if (btn) {
      if (pref === 'dark') {
        btn.setAttribute('aria-label', 'Thème sombre — cliquer pour le mode clair');
        btn.title = 'Mode sombre → cliquer pour clair';
      } else {
        btn.setAttribute('aria-label', 'Thème clair — cliquer pour le mode sombre');
        btn.title = 'Mode clair → cliquer pour sombre';
      }
    }

    document.dispatchEvent(new CustomEvent('themeChanged', { detail: { pref, resolved } }));
  }

  function cycleTheme() {
    const current = getThemePref();
    const next = current === 'dark' ? 'light' : 'dark';
    // Trigger animation on toggle button
    const btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.classList.add('animating');
      btn.addEventListener('animationend', () => {
        btn.classList.remove('animating');
      }, { once: true });
    }
    applyThemeFromPref(next);
  }

  function initThemeToggle() {
    const pref = getThemePref();
    applyThemeFromPref(pref);

    const btn = document.getElementById('theme-toggle');
    if (btn && !btn.dataset.bound) {
      btn.dataset.bound = '1';
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        cycleTheme();
      });
    }
  }

  function injectHeader() {
    const html = buildHeaderHTML();
    const mount = document.getElementById('site-header');
    if (mount) {
      mount.outerHTML = html.trim();
    } else {
      const existing = document.querySelector('header.header');
      if (existing) {
        existing.outerHTML = html.trim();
      } else {
        document.body.insertAdjacentHTML('afterbegin', html);
      }
    }
    bindMobileMenu();
    updateAuthArea();
    initThemeToggle();
    updateSiteContactInfo();

    // Re-apply translations if i18n already loaded
    if (window.I18N && typeof window.I18N.apply === 'function') {
      window.I18N.apply();
    }
    // Re-inject language switcher after header is ready
    if (window.I18N && typeof window.I18N.injectSwitcher === 'function') {
      window.I18N.injectSwitcher();
    }

    document.dispatchEvent(new CustomEvent('headerReady'));
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectHeader);
  } else {
    injectHeader();
  }

  window.AutoPrestigeHeader = { inject: injectHeader, pages: PAGES };
})();
