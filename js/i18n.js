/**
 * Autohaus i18n — traduction dynamique via l'API backend (DeepL).
 * Les textes sont regroupés et envoyés à l'endpoint /translate du backend,
 * qui appelle DeepL côté serveur (la clé API n'est jamais exposée au client).
 * En cas d'indisponibilité du backend, repli sur l'endpoint public gratuit
 * de Google. Les traductions sont mises en cache dans le localStorage pour
 * ne jamais retraduire deux fois la même phrase.
 */
const I18N = {
  currentLang: 'fr',
  translations: {},
  supported: ['fr', 'en', 'de', 'it', 'es', 'pt', 'ro'],
  // Constantes du repli Google (une requête = un texte, débit bridé)
  MAX_TEXT_LENGTH: 1800,      // texte plus long : laissé en français
  CONCURRENCY: 4,             // requêtes simultanées max (repli)
  REQUEST_GAP_MS: 40,         // espacement minimal entre deux requêtes (repli)
  RETRY_DELAYS: [400, 1200, 2500], // attente avant réessai (HTTP 429)
  MAX_CACHE_ENTRIES: 1500,    // entrées max par langue dans le localStorage
  BRAND_NAME: 'Autohaus',     // nom de l'entreprise : jamais traduit
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
  _failed: {}, // { lang: { originalText: true } } — phrases en échec (session) pour ne pas marteler

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

  /* ===== Traduction via le backend (DeepL), repli Google gratuit ===== */

  // Regroupement des textes : une requête backend = jusqu'à 40 phrases
  // (~9 000 caractères, sous les limites de l'endpoint /translate).
  CHUNK_MAX_ITEMS: 40,
  CHUNK_MAX_CHARS: 9000,

  translateUrl(text, targetLang) {
    return 'https://translate.googleapis.com/translate_a/single?client=gtx&sl=fr&tl='
      + targetLang.toLowerCase() + '&dt=t&q=' + encodeURIComponent(text);
  },

  // « Bonjour le monde » → [[["Hello world","Bonjour le monde",...]],null,"fr",...]
  parseResponse(data) {
    try {
      const chunks = data && Array.isArray(data[0]) ? data[0] : [];
      return chunks.map(chunk => (chunk && chunk[0]) ? chunk[0] : '').join('').trim();
    } catch (_) {
      return '';
    }
  },

  needsTranslation(text) {
    return text.length > 1
      && text.length <= this.MAX_TEXT_LENGTH
      && /[a-zA-ZàâäéèêëîïôöùûüçœÀÂÄÉÈÊËÎÏÔÖÙÛÜÇŒ]/.test(text);
  },

  async fetchTranslation(text, targetLang) {
    for (let attempt = 0; attempt <= this.RETRY_DELAYS.length; attempt++) {
      try {
        const res = await fetch(this.translateUrl(text, targetLang));
        if (res.ok) {
          const translated = this.parseResponse(await res.json());
          return translated || text;
        }
        // 429 = débit limité : on attend puis on réessaie, sinon repli sur l'original
        if (res.status !== 429 || attempt === this.RETRY_DELAYS.length) return text;
        await new Promise(r => setTimeout(r, this.RETRY_DELAYS[attempt]));
      } catch (err) {
        console.warn('Google Translate (repli):', err);
        return text; // réseau coupé / hors-ligne : repli sur l'original
      }
    }
    return text;
  },

  // Appel de l'endpoint /translate du backend (DeepL côté serveur).
  // window.API vient de js/api.js, chargé avant DOMContentLoaded.
  async fetchBackendBatch(texts, targetLang) {
    const api = window.API;
    if (!api || typeof api.request !== 'function') throw new Error('API indisponible');
    const data = await api.request('/translate', {
      method: 'POST',
      body: JSON.stringify({ texts, target_lang: targetLang.toUpperCase() }),
    });
    const list = data && Array.isArray(data.translations) ? data.translations : null;
    if (!list || list.length !== texts.length) throw new Error('Réponse de traduction invalide');
    return list;
  },

  chunkEntries(entries) {
    const chunks = [];
    let current = [];
    let chars = 0;
    for (const entry of entries) {
      const len = entry.text.length;
      if (current.length >= this.CHUNK_MAX_ITEMS || (chars + len > this.CHUNK_MAX_CHARS && current.length)) {
        chunks.push(current);
        current = [];
        chars = 0;
      }
      current.push(entry);
      chars += len;
    }
    if (current.length) chunks.push(current);
    return chunks;
  },

  async translateTexts(texts, targetLang) {
    if (!texts.length) return [];
    const results = new Array(texts.length).fill(null);
    const failed = this._failed[targetLang] || (this._failed[targetLang] = {});

    const eligible = [];
    texts.forEach((text, index) => {
      if (!this.needsTranslation(text) || failed[text]) results[index] = text;
      else eligible.push({ text, index });
    });
    if (!eligible.length) return texts.map((text, i) => results[i] === null ? text : results[i]);

    // 1) Backend (DeepL) : requêtes groupées — quelques requêtes par page
    const pending = [];
    for (const chunk of this.chunkEntries(eligible)) {
      try {
        const translatedList = await this.fetchBackendBatch(chunk.map(e => e.text), targetLang);
        chunk.forEach((entry, i) => {
          const value = (translatedList[i] || '').trim();
          results[entry.index] = value || entry.text;
        });
      } catch (err) {
        console.warn('Traduction backend :', err?.message || err);
        pending.push(...chunk); // backend indisponible → repli Google
      }
    }

    // 2) Repli : endpoint public gratuit de Google, texte par texte
    if (pending.length) {
      let lastLaunch = 0;
      const worker = async () => {
        while (pending.length) {
          const entry = pending.shift();
          const text = entry.text;
          const wait = Math.max(0, this.REQUEST_GAP_MS - (Date.now() - lastLaunch));
          if (wait > 0) await new Promise(r => setTimeout(r, wait));
          lastLaunch = Date.now();
          const translated = await this.fetchTranslation(text, targetLang);
          results[entry.index] = translated;
          if (translated === text) failed[text] = true; // ne pas marteler dans la session
        }
      };
      const poolSize = Math.min(this.CONCURRENCY, pending.length);
      await Promise.all(Array.from({ length: poolSize }, worker));
    }

    return texts.map((text, i) => results[i] === null ? text : results[i]);
  },

  /* ===== Cache localStorage (une phrase traduite = jamais retraduite) ===== */

  cacheKey(lang) {
    return 'ap_gt_cache_' + lang;
  },

  loadPersistentCache(lang) {
    try {
      const raw = localStorage.getItem(this.cacheKey(lang));
      if (raw) this._cache[lang] = Object.assign(this._cache[lang] || {}, JSON.parse(raw));
    } catch (_) { /* quota ou JSON invalide : on ignore */ }
  },

  savePersistentCache(lang) {
    const cache = this._cache[lang];
    if (!cache) return;
    try {
      const entries = Object.entries(cache);
      if (entries.length > this.MAX_CACHE_ENTRIES) {
        this._cache[lang] = Object.fromEntries(entries.slice(-this.MAX_CACHE_ENTRIES));
      }
      localStorage.setItem(this.cacheKey(lang), JSON.stringify(this._cache[lang]));
    } catch (_) { /* quota dépassé : on ignore */ }
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
        const value = translated[idx] || orig;
        // On ne garde que les vrais succès : un repli FR pourra être retenté plus tard
        if (value !== orig) langCache[orig] = value;
      });
      this._cache[this.currentLang] = langCache;
    }

    // Le nom de l'entreprise doit rester intact : DeepL peut le traiter comme
    // un nom commun allemand ("Autohaus" = concession). Si une traduction
    // altère ou supprime la marque, on rejette la traduction (texte FR gardé).
    const brand = this.BRAND_NAME;
    const brandRegex = new RegExp(brand, 'gi');

    // Apply translations
    const fullCache = this._cache[this.currentLang];
    items.forEach(item => {
      let translated = fullCache[item.text] || item.text;
      if (translated !== item.text) {
        const brandCount = (item.text.match(brandRegex) || []).length;
        if (brandCount && (translated.match(brandRegex) || []).length !== brandCount) {
          translated = item.text; // marque altérée → on garde l'original
        } else if (brandCount) {
          translated = translated.replace(brandRegex, brand); // casse exacte
        }
      }
      if (item.node) {
        item.node.nodeValue = item.node.nodeValue.replace(item.text, translated);
      } else if (item.element) {
        item.element.setAttribute(item.attribute, translated);
      }
    });
    this.savePersistentCache(this.currentLang);
  },

  observeDynamicContent() {
    if (this._observer) return;
    this._observer = new MutationObserver(() => {
      if (this._translating || this.currentLang === 'fr') return;
      clearTimeout(this._translateTimer);
      this._translateTimer = setTimeout(() => {
        this._translating = true;
        this.translatePage().catch(err => console.warn('i18n:', err)).finally(() => { this._translating = false; });
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
      this._failed[lang] = {}; // nouveau choix de langue → on peut tout retenter
      this.loadPersistentCache(lang);
      this._translating = true;
      await this.translatePage().catch(err => console.warn('i18n:', err));
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
      // Attendre que le DOM soit prêt puis traduire (cache d'abord)
      this.loadPersistentCache(initial);
      await new Promise(resolve => setTimeout(resolve, 100));
      this._translating = true;
      await this.translatePage().catch(err => console.warn('i18n:', err));
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
