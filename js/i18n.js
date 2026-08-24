/**
 * AutoPrestige i18n
 * - data-i18n pour les textes connus (JSON locaux)
 * - DeepL via le backend pour tout le contenu visible
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
      if (this.currentLang !== 'fr' && this._originalText.has(node)) nodes.push({ node, text: this._originalText.get(node) });
    }
    document.querySelectorAll('[placeholder], [title], [aria-label]').forEach(el => {
      if (el.closest('.lang-switcher, [data-no-translate]')) return;
      const attrs = this._originalAttributes.get(el) || {};
      ['placeholder', 'title', 'aria-label'].forEach(name => {
        if (attrs[name]?.trim()) nodes.push({ element: el, attribute: name, text: attrs[name] });
      });
    });
    return nodes;
  },

  async translatePage() {
    if (this.currentLang === 'fr') return;
    this.captureOriginalContent();
    const items = this.translatableNodes();
    for (let offset = 0; offset < items.length; offset += 50) {
      const batch = items.slice(offset, offset + 50);
      const response = await fetch(`${this.apiBase()}/translate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ texts: batch.map(item => item.text), target_lang: this.currentLang.toUpperCase() })
      });
      if (!response.ok) throw new Error('DeepL translation unavailable');
      const data = await response.json();
      batch.forEach((item, index) => {
        const translated = data.translations[index];
        if (item.node) item.node.nodeValue = item.node.nodeValue.replace(item.text.trim(), translated);
        if (item.element) item.element.setAttribute(item.attribute, translated);
      });
    }
  },

  observeDynamicContent() {
    if (this._observer) return;
    this._observer = new MutationObserver(() => {
      if (this._translating || this.currentLang === 'fr') return;
      clearTimeout(this._translateTimer);
      this._translateTimer = setTimeout(() => {
        this._translating = true;
        this.translatePage().catch(() => {}).finally(() => { this._translating = false; });
      }, 150);
    });
    this._observer.observe(document.body, { childList: true, subtree: true });
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

  /**
   * Change la langue du site entier
   */
  async setLanguage(lang) {
    if (!this.supported.includes(lang)) lang = 'fr';
    localStorage.setItem('lang', lang);
    this.currentLang = lang;

    this.restoreOriginalContent();
    await this.loadJson(lang);
    this._translating = true;
    try { await this.translatePage(); } catch (err) { console.warn('DeepL:', err); }
    this._translating = false;

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
    // Langue : localStorage > navigateur > français
    const saved = localStorage.getItem('lang');
    const browser = (navigator.language || 'fr').slice(0, 2).toLowerCase();
    const initial = saved || (this.supported.includes(browser) ? browser : 'fr');

    this.currentLang = initial;
    localStorage.setItem('lang', initial);
    this.captureOriginalContent();
    await this.loadJson(initial);
    this.injectSwitcher();
    this.observeDynamicContent();
    if (initial !== 'fr') {
      this._translating = true;
      try { await this.translatePage(); } catch (err) { console.warn('DeepL:', err); }
      this._translating = false;
    }
  }
};

document.addEventListener('DOMContentLoaded', () => I18N.init());
document.addEventListener('headerReady', () => {
  if (I18N.translations && Object.keys(I18N.translations).length) I18N.apply();
  I18N.injectSwitcher();
});
