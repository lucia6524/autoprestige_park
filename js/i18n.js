/**
 * AutoPrestige i18n
 * - data-i18n pour menu / footer / éléments marqués (JSON locaux)
 * - Google Translate pour TOUT le reste de la page (nécessite Internet)
 */
const I18N = {
  currentLang: 'fr',
  translations: {},
  supported: ['fr', 'en', 'de', 'it', 'es', 'pt', 'ro'],
  flags: {
    fr: '🇫🇷', en: '🇬🇧', de: '🇩🇪', it: '🇮🇹',
    es: '🇪🇸', pt: '🇵🇹', ro: '🇷🇴'
  },
  names: {
    fr: 'Français', en: 'English', de: 'Deutsch', it: 'Italiano',
    es: 'Español', pt: 'Português', ro: 'Română'
  },
  _googleReady: false,
  _outsideClickBound: false,

  t(key) {
    if (!key) return '';
    const keys = key.split('.');
    let value = this.translations;
    for (const k of keys) {
      if (value && typeof value === 'object' && k in value) value = value[k];
      else return key;
    }
    return typeof value === 'string' ? value : key;
  },

  apply() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.getAttribute('data-i18n');
      const translated = this.t(key);
      if (translated && translated !== key) el.textContent = translated;
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
      const key = el.getAttribute('data-i18n-placeholder');
      const translated = this.t(key);
      if (translated && translated !== key) el.placeholder = translated;
    });
    document.querySelectorAll('[data-i18n-aria]').forEach(el => {
      const key = el.getAttribute('data-i18n-aria');
      const translated = this.t(key);
      if (translated && translated !== key) el.setAttribute('aria-label', translated);
    });
    const titleKey = document.body.getAttribute('data-i18n-title');
    if (titleKey) {
      const translated = this.t(titleKey);
      if (translated && translated !== titleKey) document.title = translated;
    }
    document.documentElement.lang = this.currentLang;
    this.updateSwitcherUI();
  },

  async loadJson(lang) {
    if (!this.supported.includes(lang)) lang = 'fr';
    try {
      const res = await fetch(`locales/${lang}.json`);
      if (!res.ok) throw new Error('locale missing');
      this.translations = await res.json();
      this.currentLang = lang;
      this.apply();
      return true;
    } catch (err) {
      console.warn('i18n JSON:', err);
      if (lang !== 'fr') return this.loadJson('fr');
      return false;
    }
  },

  /* ========== Google Translate (page entière) ========== */

  getCookie(name) {
    const m = document.cookie.match(new RegExp('(?:^|; )' + name.replace(/([.$?*|{}()[\]\\/+^])/g, '\\$1') + '=([^;]*)'));
    return m ? decodeURIComponent(m[1]) : '';
  },

  setGoogleCookie(lang) {
    // Effacer d'abord
    const expire = 'Thu, 01 Jan 1970 00:00:00 GMT';
    document.cookie = 'googtrans=; expires=' + expire + '; path=/';
    document.cookie = 'googtrans=; expires=' + expire + '; path=/; domain=' + location.hostname;
    document.cookie = 'googtrans=; expires=' + expire + '; path=/; domain=.' + location.hostname;

    if (lang && lang !== 'fr') {
      // /fr/xx = langue source française → cible
      const val = '/fr/' + lang;
      document.cookie = 'googtrans=' + val + '; path=/';
      try {
        document.cookie = 'googtrans=' + val + '; path=/; domain=' + location.hostname;
      } catch (_) {}
    }
  },

  detectLangFromCookie() {
    const c = this.getCookie('googtrans'); // ex: /fr/en
    if (!c) return null;
    const parts = c.split('/');
    const lang = parts[parts.length - 1];
    return this.supported.includes(lang) ? lang : null;
  },

  injectGoogleTranslate() {
    if (document.getElementById('google-translate-script')) return;

    // Conteneur caché requis par Google
    if (!document.getElementById('google_translate_element')) {
      const div = document.createElement('div');
      div.id = 'google_translate_element';
      div.style.display = 'none';
      document.body.appendChild(div);
    }

    window.googleTranslateElementInit = () => {
      try {
        // eslint-disable-next-line no-new
        new google.translate.TranslateElement({
          pageLanguage: 'fr',
          includedLanguages: this.supported.join(','),
          autoDisplay: false,
          layout: google.translate.TranslateElement.InlineLayout.SIMPLE
        }, 'google_translate_element');
        this._googleReady = true;
        // Appliquer la langue sauvegardée via le combo Google si besoin
        const lang = localStorage.getItem('lang') || 'fr';
        if (lang !== 'fr') {
          setTimeout(() => this.triggerGoogleCombo(lang), 800);
        }
      } catch (e) {
        console.warn('Google Translate init:', e);
      }
    };

    const s = document.createElement('script');
    s.id = 'google-translate-script';
    s.src = 'https://translate.google.com/translate_a/element.js?cb=googleTranslateElementInit';
    s.async = true;
    document.body.appendChild(s);

    // Styles : masquer la barre Google tout en gardant la traduction
    if (!document.getElementById('gt-hide-style')) {
      const style = document.createElement('style');
      style.id = 'gt-hide-style';
      style.textContent = `
        .goog-te-banner-frame, .goog-te-balloon-frame, #goog-gt-tt, .goog-te-balloon-frame {
          display: none !important;
        }
        body { top: 0 !important; }
        .goog-te-gadget { display: none !important; }
        .skiptranslate { display: none !important; }
        iframe.skiptranslate { display: none !important; height: 0 !important; }
        body > .skiptranslate { display: none !important; }
        .goog-text-highlight { background: none !important; box-shadow: none !important; }
      `;
      document.head.appendChild(style);
    }
  },

  triggerGoogleCombo(lang) {
    const select = document.querySelector('select.goog-te-combo');
    if (!select) return false;
    if (select.value === lang) return true;
    select.value = lang;
    select.dispatchEvent(new Event('change'));
    return true;
  },

  /**
   * Change la langue du site entier
   */
  async setLanguage(lang) {
    if (!this.supported.includes(lang)) lang = 'fr';
    localStorage.setItem('lang', lang);
    this.currentLang = lang;

    // 1) JSON local (menu / footer / data-i18n)
    await this.loadJson(lang);

    // 2) Google Translate pour tout le contenu de page
    this.setGoogleCookie(lang);

    if (lang === 'fr') {
      // Revenir à l'original : rechargement propre sans cookie
      const had = this.getCookie('googtrans');
      if (had) {
        location.reload();
        return;
      }
      this.triggerGoogleCombo('fr');
    } else {
      // Essayer sans rechargement
      const ok = this.triggerGoogleCombo(lang);
      if (!ok) {
        // Script pas encore prêt → cookie + reload
        location.reload();
        return;
      }
    }

    this.updateSwitcherUI();
    document.dispatchEvent(new CustomEvent('languageChanged', { detail: { lang } }));
  },

  async load(lang) {
    return this.setLanguage(lang);
  },

  /* ========== UI sélecteur ========== */

  createSwitcherElement() {
    const wrapper = document.createElement('div');
    wrapper.className = 'lang-switcher';
    wrapper.innerHTML = `
      <button type="button" class="lang-toggle" aria-label="Changer de langue" aria-expanded="false">
        <span class="lang-flag">${this.flags[this.currentLang] || '🇫🇷'}</span>
        <span class="lang-code">${this.currentLang.toUpperCase()}</span>
        <span class="lang-arrow">▾</span>
      </button>
      <div class="lang-dropdown" hidden>
        ${this.supported.map(code => `
          <button type="button" class="lang-option${code === this.currentLang ? ' active' : ''}" data-lang="${code}">
            <span class="lang-flag">${this.flags[code]}</span>
            <span>${this.names[code]}</span>
          </button>
        `).join('')}
      </div>
    `;

    const toggle = wrapper.querySelector('.lang-toggle');
    const dropdown = wrapper.querySelector('.lang-dropdown');

    toggle.addEventListener('click', (e) => {
      e.stopPropagation();
      const isOpen = !dropdown.hidden;
      document.querySelectorAll('.lang-dropdown').forEach(d => { d.hidden = true; });
      document.querySelectorAll('.lang-toggle').forEach(t => t.setAttribute('aria-expanded', 'false'));
      dropdown.hidden = isOpen;
      toggle.setAttribute('aria-expanded', String(!isOpen));
    });

    wrapper.querySelectorAll('.lang-option').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const lang = btn.getAttribute('data-lang');
        dropdown.hidden = true;
        toggle.setAttribute('aria-expanded', 'false');
        this.setLanguage(lang);
      });
    });

    return wrapper;
  },

  injectSwitcher() {
    if (!this._outsideClickBound) {
      document.addEventListener('click', () => {
        document.querySelectorAll('.lang-dropdown').forEach(d => { d.hidden = true; });
        document.querySelectorAll('.lang-toggle').forEach(t => t.setAttribute('aria-expanded', 'false'));
      });
      this._outsideClickBound = true;
    }

    const actions = document.querySelector('.header-actions');
    if (actions && !actions.querySelector('.lang-switcher')) {
      const wrapper = this.createSwitcherElement();
      let cta = null;
      for (const child of actions.children) {
        if (child.classList && child.classList.contains('btn-primary')) {
          cta = child;
          break;
        }
      }
      const mobileToggle = actions.querySelector('.mobile-toggle');
      if (cta) actions.insertBefore(wrapper, cta);
      else if (mobileToggle) actions.insertBefore(wrapper, mobileToggle);
      else actions.appendChild(wrapper);
    }

  },

  updateSwitcherUI() {
    document.querySelectorAll('.lang-toggle').forEach(toggle => {
      const flag = toggle.querySelector('.lang-flag');
      const code = toggle.querySelector('.lang-code');
      if (flag) flag.textContent = this.flags[this.currentLang] || '🇫🇷';
      if (code) code.textContent = this.currentLang.toUpperCase();
    });
    document.querySelectorAll('.lang-option').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-lang') === this.currentLang);
    });
  },

  async init() {
    // Langue : localStorage > cookie Google > navigateur > fr
    const saved = localStorage.getItem('lang');
    const fromCookie = this.detectLangFromCookie();
    const browser = (navigator.language || 'fr').slice(0, 2).toLowerCase();
    const initial = saved || fromCookie || (this.supported.includes(browser) ? browser : 'fr');

    this.currentLang = initial;
    localStorage.setItem('lang', initial);
    if (initial !== 'fr') this.setGoogleCookie(initial);

    await this.loadJson(initial);
    this.injectSwitcher();
    this.injectGoogleTranslate();
  }
};

document.addEventListener('DOMContentLoaded', () => I18N.init());
document.addEventListener('headerReady', () => {
  if (I18N.translations && Object.keys(I18N.translations).length) I18N.apply();
  I18N.injectSwitcher();
});
