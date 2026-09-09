/**
 * Autohaus i18n — traduction dynamique via DeepL (endpoint backend /translate).
 * Aucun appel direct à un service de traduction depuis le navigateur : le
 * backend détient la clé et regroupe les textes par lots vers DeepL.
 * Les traductions sont mises en cache dans le localStorage pour ne jamais
 * retraduire deux fois la même phrase. Le contenu injecté dynamiquement
 * (cartes véhicules, résultats, etc.) est capté par un MutationObserver
 * et traduit en plusieurs passes tant que la page évolue.
 *
 * En complément, les clés statiques (nav, footer, filtres, titres…) sont
 * chargées depuis locales/<lang>.json et appliquées instantanément via les
 * attributs data-i18n / data-i18n-placeholder / data-i18n-aria / data-i18n-alt
 * et data-i18n-title (sur <body>) pour le titre de l'onglet.
 */
const I18N = {
  currentLang: 'fr',
  translations: {},          // clés de locales/<lang>.json
  supported: ['fr', 'en', 'de', 'it', 'es', 'pt', 'ro'],
  MAX_TEXT_LENGTH: 8000,      // texte plus long : laissé en français
  BRAND_NAME: 'Autohaus',     // nom de l'entreprise : jamais traduit

  // Regroupement des textes : une requête backend = jusqu'à 40 phrases
  // (~9 000 caractères, sous les limites de l'endpoint /translate).
  CHUNK_MAX_ITEMS: 40,
  CHUNK_MAX_CHARS: 9000,
  BACKOFF_MS: [400, 1200, 2500], // attente avant réessai d'un lot échoué
  MAX_CACHE_ENTRIES: 1500,    // entrées max par langue dans le localStorage
  MAX_PASSES: 4,              // passes max tant que la page évolue

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
  _dirty: false,             // du contenu est apparu pendant une passe
  _translateTimer: null,
  _cache: {},  // { lang: { originalText: translatedText } }
  _failed: {}, // { lang: { originalText: true } } — phrases en échec (session) pour ne pas marteler
  _localeLoaded: {},         // fichiers locales/<lang>.json déjà chargés
  _originalTitle: undefined, // titre d'origine de la page (langue FR)

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

  // Clé de locale avec repli : I18N.staticT('nav.logout', 'Déconnexion')
  staticT(key, fallback) {
    const value = this.t(key);
    return value !== key ? value : fallback;
  },

  apply() {
    document.documentElement.lang = this.currentLang;
    // Titre de l'onglet via data-i18n-title sur <body> (locales/<lang>.json)
    const titleKey = document.body?.getAttribute('data-i18n-title');
    if (titleKey) {
      if (this._originalTitle === undefined) this._originalTitle = document.title;
      const value = this.t(titleKey);
      document.title = value !== titleKey ? value : this._originalTitle;
    }
    this.updateSwitcherUI();
  },

  /* ===== Clés de locale : traduction instantanée via locales/<lang>.json ===== */

  async loadLocaleFile(lang) {
    if (this._localeLoaded[lang]) return;
    try {
      const res = await fetch(`locales/${lang}.json`);
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      this.translations = Object.assign({}, this.translations, data);
      this._localeLoaded[lang] = true;
    } catch (err) {
      console.warn('i18n: locales/' + lang + '.json indisponible :', err?.message || err);
    }
  },

  // Remplace uniquement le premier nœud texte : préserve les icônes SVG
  // imbriquées dans les liens et boutons (chevrons, burger…).
  _setFirstTextNode(el, value) {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (node.nodeValue.trim()) {
        if (!this._originalText.has(node)) this._originalText.set(node, node.nodeValue);
        node.nodeValue = value;
        return;
      }
    }
    el.textContent = value;
  },

  // Applique les clés statiques (nav, footer, filtres, placeholders…).
  // Les éléments sans clé restent en français et passent par DeepL ensuite.
  applyLocaleKeys(root = document.body) {
    if (!root) return;
    const skip = '.lang-switcher, [data-no-translate]';
    root.querySelectorAll('[data-i18n]').forEach(el => {
      if (el.closest(skip)) return;
      const key = el.getAttribute('data-i18n');
      const value = this.t(key);
      if (value !== key) this._setFirstTextNode(el, value);
    });
    const attrMap = {
      'data-i18n-placeholder': 'placeholder',
      'data-i18n-aria': 'aria-label',
      'data-i18n-alt': 'alt',
    };
    root.querySelectorAll('[data-i18n-placeholder], [data-i18n-aria], [data-i18n-alt]').forEach(el => {
      if (el.closest(skip)) return;
      if (!this._originalAttributes.has(el)) {
        const stored = {};
        Object.values(attrMap).forEach(name => {
          if (el.hasAttribute(name)) stored[name] = el.getAttribute(name);
        });
        this._originalAttributes.set(el, stored);
      }
      Object.entries(attrMap).forEach(([attr, name]) => {
        const key = el.getAttribute(attr);
        if (!key) return;
        const value = this.t(key);
        if (value !== key) el.setAttribute(name, value);
      });
    });
  },

  // Applique le phrasebook (textes statiques pré-traduits dans locales/*.json).
  // Remplace le premier nœud texte si son contenu correspond exactement à une
  // entrée du dictionnaire — instantané, sans appel réseau.
  applyPhrasebook(root = document.body) {
    if (!root) return;
    const book = this.translations.phrasebook;
    if (!book) return;
    const skip = '.lang-switcher, [data-no-translate], script, style, textarea';
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const value = node.nodeValue;
      const hit = book[value.trim()];
      if (hit === undefined) continue;
      const parent = node.parentElement;
      if (parent && parent.closest(skip)) continue;
      if (!this._originalText.has(node)) this._originalText.set(node, value);
      // Préserve l'espacement d'origine (indentation) autour du texte
      node.nodeValue = value.replace(value.trim(), hit);
    }
    // Placeholders, titres, aria-label, alt
    const attrMap = { placeholder: 'data-i18n-placeholder', title: 'data-i18n-title-attr', 'aria-label': 'data-i18n-aria', alt: 'data-i18n-alt' };
    root.querySelectorAll('[placeholder], [title], [aria-label], [alt]').forEach(el => {
      if (el.closest('.lang-switcher, [data-no-translate]')) return;
      Object.entries(attrMap).forEach(([name]) => {
        const original = this._originalAttributes.get(el)?.[name] ?? el.getAttribute(name);
        if (!original) return;
        const hit = book[original.trim()];
        if (hit !== undefined && hit !== original) el.setAttribute(name, hit);
      });
    });
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
    root.querySelectorAll?.('[placeholder], [title], [aria-label], [alt]').forEach(el => {
      if (el.closest('.lang-switcher, [data-no-translate]')) return;
      const attrs = {};
      ['placeholder', 'title', 'aria-label', 'alt'].forEach(name => {
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
    document.querySelectorAll('[placeholder], [title], [aria-label], [alt]').forEach(el => {
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
    root.querySelectorAll?.('[placeholder], [title], [aria-label], [alt]').forEach(el => {
      if (el.closest('.lang-switcher, [data-no-translate]')) return;
      const attrs = this._originalAttributes.get(el) || {};
      ['placeholder', 'title', 'aria-label', 'alt'].forEach(name => {
        if (attrs[name]?.trim()) items.push({ element: el, attribute: name, text: attrs[name] });
      });
    });
    return items;
  },

  needsTranslation(text) {
    return text.length > 1
      && text.length <= this.MAX_TEXT_LENGTH
      && /[a-zA-ZàâäéèêëîïôöùûüçœÀÂÄÉÈÊËÎÏÔÖÙÛÜÇŒ]/.test(text);
  },

  /* ===== Traduction via le backend (DeepL côté serveur) ===== */

  // Appel de l'endpoint /translate du backend.
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

  async fetchBackendBatchWithRetry(texts, targetLang) {
    let lastErr;
    for (let attempt = 0; attempt <= this.BACKOFF_MS.length; attempt++) {
      try {
        return await this.fetchBackendBatch(texts, targetLang);
      } catch (err) {
        lastErr = err;
        if (attempt < this.BACKOFF_MS.length) {
          await new Promise(r => setTimeout(r, this.BACKOFF_MS[attempt]));
        }
      }
    }
    throw lastErr;
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

    // Requêtes groupées vers le backend : quelques requêtes par page.
    // En cas d'échec définitif d'un lot (backend indisponible, quota DeepL
    // épuisé…), les textes restent en français et ne sont pas retentés
    // pendant la session.
    for (const chunk of this.chunkEntries(eligible)) {
      try {
        const translatedList = await this.fetchBackendBatchWithRetry(chunk.map(e => e.text), targetLang);
        chunk.forEach((entry, i) => {
          const value = (translatedList[i] || '').trim();
          results[entry.index] = value || entry.text;
        });
      } catch (err) {
        console.warn('i18n: DeepL indisponible, textes laissés en français :', err?.message || err);
        chunk.forEach(entry => {
          results[entry.index] = entry.text;
          failed[entry.text] = true;
        });
      }
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
    // 1) Phrasebook local (locales/*.json) : application INSTANTANÉE, zéro réseau.
    //    Couvre tous les textes statiques du site — la traduction est complète
    //    même si le backend est endormi (Render free tier).
    this.applyLocaleKeys();
    this.applyPhrasebook();
    const items = this.collectTexts();
    if (!items.length) return;

    // 2) DeepL uniquement pour les textes absents du phrasebook (contenu
    //    dynamique : catalogue véhicules, avis API, etc.).
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

  /* ===== Contenu dynamique : passes successives tant que la page évolue ===== */

  _scheduleTranslate() {
    if (this._translating) {
      // Du contenu est arrivé pendant une passe : on le traitera à la passe
      // suivante au lieu de l'ignorer (sinon les cartes véhicules, résultats
      // de filtres, etc. restaient en français).
      this._dirty = true;
      return;
    }
    clearTimeout(this._translateTimer);
    this._translateTimer = setTimeout(() => {
      this._runTranslationPasses().catch(err => console.warn('i18n:', err));
    }, 300);
  },

  async _runTranslationPasses() {
    this._translating = true;
    try {
      for (let pass = 0; pass < this.MAX_PASSES; pass++) {
        this._dirty = false;
        await this.translatePage();
        if (!this._dirty) break; // page stable : terminé
      }
    } finally {
      this._translating = false;
    }
  },

  observeDynamicContent() {
    if (this._observer) return;
    this._observer = new MutationObserver(() => {
      if (this.currentLang === 'fr') return;
      this._scheduleTranslate();
    });
    this._observer.observe(document.body, { childList: true, subtree: true });
  },

  /* ===== Language change ===== */

  async setLanguage(lang) {
    if (!this.supported.includes(lang)) lang = 'fr';
    localStorage.setItem('lang', lang);
    this.currentLang = lang;
    // Fichier de locale d'abord : nav/footer/filtres/titres + PHRASEBOOK.
    // Le phrasebook couvre tout le texte statique → la page est entièrement
    // traduite instantanément, même si DeepL est indisponible.
    await this.loadLocaleFile(lang).catch(() => {});
    this.apply();

    if (lang === 'fr') {
      this.restoreOriginalContent();
    } else {
      this._failed[lang] = {}; // nouveau choix de langue → on peut tout retenter
      this.loadPersistentCache(lang);
      this.applyPhrasebook(); // immédiat, zéro réseau
      await this._runTranslationPasses().catch(err => console.warn('i18n:', err));
    }

    this.observeDynamicContent();
    // Le catalogue et les contenus JS se re-rendent dans la nouvelle langue.
    document.dispatchEvent(new CustomEvent('languageChanged', { detail: { lang } }));
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

  /* ===== Détection de la langue du visiteur =====
     1. Choix sauvegardé (localStorage 'lang') — l'utilisateur a déjà choisi
     2. Langue de son téléphone/navigateur (navigator.languages puis navigator.language)
        ex : "fr-FR", "en-US", "de-DE" → on garde le préfixe (fr, en, de…)
        et on accepte les variantes régionales (pt-BR → pt, en-GB → en…)
     3. Repli : français
  */
  detectBrowserLanguage() {
    const candidates = [];
    if (Array.isArray(navigator.languages)) candidates.push(...navigator.languages);
    if (navigator.language) candidates.push(navigator.language);
    if (navigator.userLanguage) candidates.push(navigator.userLanguage); // anciens IE/Edge
    for (const raw of candidates) {
      if (!raw || typeof raw !== 'string') continue;
      const code = raw.trim().toLowerCase().split(/[-_]/)[0];
      if (this.supported.includes(code)) return code;
    }
    return null;
  },

  async init() {
    const saved = localStorage.getItem('lang');
    const browser = this.detectBrowserLanguage();
    const initial = saved || browser || 'fr';

    this.currentLang = initial;
    localStorage.setItem('lang', initial);
    await this.loadLocaleFile(initial).catch(() => {});
    this.apply();
    this.injectSwitcher();
    // Clés statiques (nav, footer, filtres, titres) dès le chargement,
    // y compris en français (valeurs identiques au texte source).
    this.applyLocaleKeys();

    if (initial !== 'fr') {
      // Phrasebook immédiat (zéro réseau) puis passes DeepL pour le dynamique
      this.loadPersistentCache(initial);
      this.applyPhrasebook();
      await new Promise(resolve => setTimeout(resolve, 100));
      await this._runTranslationPasses().catch(err => console.warn('i18n:', err));
    }
    this.observeDynamicContent();
    // Notifier le reste de la page (catalogue, badges…) pour un rendu localisé.
    document.dispatchEvent(new CustomEvent('languageChanged', { detail: { lang: initial } }));
  }
};

document.addEventListener('DOMContentLoaded', () => I18N.init());
document.addEventListener('headerReady', () => {
  I18N.apply();
  I18N.injectSwitcher();
  I18N.applyLocaleKeys();
});
