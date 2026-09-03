/**
 * AutoPrestige i18n — DeepL-powered dynamic translation
 * Translates page content via the backend /api/translate endpoint.
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
  _translateTimer: null,
  _cache: {},  // { lang: { originalText: translatedText } }

  apiBase() {
    const configuredBase = localStorage.getItem('api_base');
    if (configuredBase) return configuredBase.replace(/\/$/, '') + '/api';
    const isLocal = ['localhost', '127.0.0.1', '::1'].includes(window.location.hostname);
    return isLocal ? 'http://127.0.0.1:8000/api' : 'https://autoprestige-api.onrender.com/api';
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

  /* ===== Original content capture / restore ===== */

  captureOriginalContent(root = document.body) {
    if (!root) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const parent = node.parentElement;
      if (parent && !parent.closest('script, style, noscript, textarea, .lang-switcher, [data-no-translate]')) {
        if (!this._originalText.has(node)) this._originalText.set(node, node.nodeValue);
      }
    }
    root.querySelectorAll?.('[placeholder], [title], [aria-label]').forEach(el => {
      if (el.closest('.lang-switcher, [data-no-translate]')) return;
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

  /* ===== Collect translatable texts ===== */

  collectTexts(root = document.body) {
    const items = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const parent = node.parentElement;
      const value = node.nodeValue?.trim();
      if (!parent || !value || parent.closest('script, style, noscript, textarea, .lang-switcher, [data-no-translate]')) continue;
      const original = this._originalText.get(node);
      if (original?.trim()) items.push({ node, text: original.trim() });
    }
    root.querySelectorAll?.('[placeholder], [title], [aria-label]').forEach(el => {
      if (el.closest('.lang-switcher, [data-no-translate]')) return;
      const attrs = this._originalAttributes.get(el) || {};
      ['placeholder', 'title', 'aria-label'].forEach(name => {
        if (attrs[name]?.trim()) items.push({ element: el, attribute: name, text: attrs[name] });
      });
    });
    return items;
  },

  /* ===== DeepL translation via backend ===== */

  async translateTexts(texts, targetLang) {
    if (!texts.length) return [];
    // Batch in chunks of 50 (API limit)
    const chunkSize = 50;
    const results = [];
    for (let i = 0; i < texts.length; i += chunkSize) {
      const chunk = texts.slice(i, i + chunkSize);
      try {
        const res = await fetch(`${this.apiBase()}/translate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            texts: chunk,
            target_lang: targetLang.toUpperCase(),
          }),
        });
        if (!res.ok) {
          console.warn('DeepL translation failed:', res.status);
          return texts; // fallback: return originals
        }
        const data = await res.json();
        results.push(...(data.translations || []));
      } catch (err) {
        console.warn('DeepL translation error:', err);
        return texts; // fallback
      }
    }
    return results;
  },

  async translatePage() {
    if (this.currentLang === 'fr') {
      this.restoreOriginalContent();
      return;
    }

    this.captureOriginalContent();
    const items = this.collectTexts();
    if (!items.length) return;

    // Check cache
    const langCache = this._cache[this.currentLang] || {};
    const uncached = items.filter(item => !langCache[item.text]);

    if (uncached.length) {
      const uniqueTexts = [...new Set(uncached.map(i => i.text))];
      const translated = await this.translateTexts(uniqueTexts, this.currentLang);
      uniqueTexts.forEach((orig, idx) => {
        langCache[orig] = translated[idx] || orig;
      });
      this._cache[this.currentLang] = langCache;
    }

    // Apply translations
    const fullCache = this._cache[this.currentLang];
    items.forEach(item => {
      const translated = fullCache[item.text] || item.text;
      if (item.node) {
        item.node.nodeValue = item.node.nodeValue.replace(item.text, translated);
      } else if (item.element) {
        item.element.setAttribute(item.attribute, translated);
      }
    });
  },

  observeDynamicContent() {
    if (this._observer) return;
    this._observer = new MutationObserver(() => {
      if (this._translating || this.currentLang === 'fr') return;
      clearTimeout(this._translateTimer);
      this._translateTimer = setTimeout(() => {
        this._translating = true;
        this.translatePage().catch(err => console.warn('DeepL:', err)).finally(() => { this._translating = false; });
      }, 300);
    });
    this._observer.observe(document.body, { childList: true, subtree: true });
  },

  /* ===== Language change ===== */

  async setLanguage(lang) {
    if (!this.supported.includes(lang)) lang = 'fr';
    localStorage.setItem('lang', lang);
    this.currentLang = lang;
    this.apply();

    if (lang === 'fr') {
      this.restoreOriginalContent();
    } else {
      this._translating = true;
      await this.translatePage().catch(err => console.warn('DeepL:', err));
      this._translating = false;
    }

    this.observeDynamicContent();
  },

  async load(lang) {
    return this.setLanguage(lang);
  },

  /* ===== UI Switcher ===== */

  createSwitcherElement() {
    const wrapper = document.createElement('div');
    wrapper.className = 'lang-switcher';
    wrapper.innerHTML = `
      <button type="button" class="lang-toggle" aria-label="Changer de langue" aria-expanded="false">
        <span class="lang-icon" aria-hidden="true"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg></span>
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
    const saved = localStorage.getItem('lang');
    const browser = (navigator.language || 'fr').slice(0, 2).toLowerCase();
    const initial = saved || (this.supported.includes(browser) ? browser : 'fr');

    this.currentLang = initial;
    localStorage.setItem('lang', initial);
    this.apply();
    this.injectSwitcher();

    if (initial !== 'fr') {
      // Wait for DOM to be ready, then translate
      await new Promise(resolve => setTimeout(resolve, 100));
      this._translating = true;
      await this.translatePage().catch(err => console.warn('DeepL:', err));
      this._translating = false;
      this.observeDynamicContent();
    }
  }
};

document.addEventListener('DOMContentLoaded', () => I18N.init());
document.addEventListener('headerReady', () => {
  I18N.apply();
  I18N.injectSwitcher();
});
