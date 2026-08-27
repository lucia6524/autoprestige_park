/**
 * AutoPrestige i18n
 * - Widget Google Translate pour tout le contenu visible
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
  _outsideClickBound: false,
  _originalText: new WeakMap(),
  _originalAttributes: new WeakMap(),
  _observer: null,
  _translating: false,

  setGoogleCookie(lang) {
    const value = lang === 'fr' ? '' : `/fr/${lang}`;
    document.cookie = `googtrans=${value}; path=/`;
    document.cookie = `googtrans=${value}; path=/; domain=${window.location.hostname}`;
  },

  loadGoogleWidget() {
    if (window.google?.translate?.TranslateElement) {
      window.googleTranslateElementInit();
      return;
    }
    if (document.querySelector('script[data-google-translate]')) return;
    window.googleTranslateElementInit = () => {
      if (!window.google?.translate?.TranslateElement) return;
      new google.translate.TranslateElement({
        pageLanguage: 'fr',
        includedLanguages: this.supported.join(','),
        autoDisplay: false
      }, 'google_translate_element');
    };
    const script = document.createElement('script');
    script.src = 'https://translate.google.com/translate_a/element.js?cb=googleTranslateElementInit';
    script.async = true;
    script.dataset.googleTranslate = 'true';
    document.head.appendChild(script);
  },

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
    document.documentElement.lang = this.currentLang;
    this.updateSwitcherUI();
  },

  apiBase() {
    return (localStorage.getItem('api_base') || 'http://127.0.0.1:8000') + '/api';
  },

  captureOriginalContent(root = document.body) {
    if (!root) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (node.parentElement && !node.parentElement.closest('script, style, noscript, textarea')) {
        if (!this._originalText.has(node)) this._originalText.set(node, node.nodeValue);
      }
    }
    root.querySelectorAll?.('[placeholder], [title], [aria-label]').forEach(el => {
      const attrs = {};
      ['placeholder', 'title', 'aria-label'].forEach(name => {
        if (el.hasAttribute(name)) attrs[name] = el.getAttribute(name);
      });
      if (!this._originalAttributes.has(el)) this._originalAttributes.set(el, attrs);
    });
  },

  restoreOriginalContent() {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const original = this._originalText.get(node);
      if (original !== undefined) node.nodeValue = original;
    }
    document.querySelectorAll('[placeholder], [title], [aria-label]').forEach(el => {
      const attrs = this._originalAttributes.get(el);
      if (attrs) Object.entries(attrs).forEach(([name, value]) => el.setAttribute(name, value));
    });
  },

  translatableNodes(root = document.body) {
    const nodes = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const parent = node.parentElement;
      const value = node.nodeValue?.trim();
      if (!parent || !value || parent.closest('script, style, noscript, textarea, .lang-switcher, [data-no-translate]')) continue;
      const original = this._originalText.get(node);
      if (this.currentLang !== 'fr' && original?.trim()) nodes.push({ node, text: original });
    }
    root.querySelectorAll?.('[placeholder], [title], [aria-label]').forEach(el => {
      if (el.closest('.lang-switcher, [data-no-translate]')) return;
      const attrs = this._originalAttributes.get(el) || {};
      ['placeholder', 'title', 'aria-label'].forEach(name => {
        if (attrs[name]?.trim()) nodes.push({ element: el, attribute: name, text: attrs[name] });
      });
    });
    return nodes;
  },

  async translatePage() {
    this.loadGoogleWidget();
  },

  observeDynamicContent() {
    if (this._observer) return;
    this._observer = new MutationObserver(() => {
      if (this._translating || this.currentLang === 'fr') return;
      clearTimeout(this._translateTimer);
      this._translateTimer = setTimeout(() => {
        this._translating = true;
        this.translatePage().catch(err => console.warn('Google Translate:', err)).finally(() => { this._translating = false; });
      }, 150);
    });
    this._observer.observe(document.body, { childList: true, subtree: true });
  },

  async loadJson(lang) {
    this.currentLang = this.supported.includes(lang) ? lang : 'fr';
    this.translations = {};
    this.setGoogleCookie(this.currentLang);
    this.apply();
    return true;
  },

  /**
   * Change la langue du site entier
   */
  async setLanguage(lang) {
    if (!this.supported.includes(lang)) lang = 'fr';
    localStorage.setItem('lang', lang);
    this.currentLang = lang;

    this.setGoogleCookie(lang);
    window.location.reload();
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
    const googleWidget = document.createElement('div');
    googleWidget.id = 'google_translate_element';
    googleWidget.hidden = true;
    wrapper.appendChild(googleWidget);

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
    // Langue : localStorage > navigateur > français
    const saved = localStorage.getItem('lang');
    const browser = (navigator.language || 'fr').slice(0, 2).toLowerCase();
    const initial = saved || (this.supported.includes(browser) ? browser : 'fr');

    this.currentLang = initial;
    localStorage.setItem('lang', initial);
    this.setGoogleCookie(initial);
    await this.loadJson(initial);
    this.injectSwitcher();
    this.loadGoogleWidget();
  }
};

document.addEventListener('DOMContentLoaded', () => I18N.init());
document.addEventListener('headerReady', () => {
  if (I18N.translations && Object.keys(I18N.translations).length) I18N.apply();
  I18N.injectSwitcher();
});
