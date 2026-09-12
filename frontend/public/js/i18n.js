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
  // Coupe-circuit : après un échec DUR du provider (clé invalide, quota,
  // indisponible, rate-limit), on cesse toute traduction réseau pendant
  // cette durée — sinon chaque page en échec générait des centaines de
  // requêtes (repli bloc-par-bloc + passes + observateur). Sans revenir,
  // le site reste français mais n'asphyxie plus le backend.
  PROVIDER_COOLDOWN_MS: 20000,

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
  _readyPromise: null,       // promesse d'initialisation (locale chargée)
  _originalTitle: undefined, // titre d'origine de la page (langue FR)
  _circuit: { openUntil: 0, kind: '' },  // coupe-circuit du provider DeepL

  // Le message d'erreur ne porte pas le statut HTTP (api.request ne renvoie
  // que le `detail` du backend), mais les libellés sont caractéristiques :
  // on les détecte pour distinguer « le SERVEUR/le provider est en panne »
  // (coupe-circuit + aucun repli bloc-par-bloc) de « mon message est mal
  // formé » (repli bloc-par-bloc légitime, ex. 422 HTML invalide).
  _isProviderHardFailure(msg) {
    return !!(msg && /quota|clé api|clé de traduction|indisponible|trop de demandes|volume de traduction|reviens|réessayez/i.test(msg));
  },

  _circuitOpen() {
    return this._circuit.openUntil > Date.now();
  },

  _recordProviderFailure(msg) {
    if (this._circuitOpen()) return; // déjà en pause
    this._circuit.openUntil = Date.now() + this.PROVIDER_COOLDOWN_MS;
    this._circuit.kind = msg || 'inconnu';
    console.warn('i18n: traduction en pause 20 s (provider indisponible) :', this._circuit.kind);
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
    const book = this.translations.phrasebook || {};
    const langCache = this._cache[this.currentLang] || {};
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const parent = node.parentElement;
      const value = node.nodeValue?.trim();
      if (!parent || !value || parent.closest('script, style, noscript, textarea, .lang-switcher, [data-no-translate]')) continue;
      // Optimisation : les textes déjà couverts (phrasebook, cache, clés de
      // locale) n'ont PAS besoin de DeepL — on ne les envoie pas.
      if (book[value] !== undefined) continue;
      if (langCache[value] !== undefined) continue;
      if (this.t(value) !== value && /^[\w.]+$/.test(value)) continue;
      const original = this._originalText.get(node);
      if (original?.trim()) items.push({ node, text: original.trim() });
    }
    root.querySelectorAll?.('[placeholder], [title], [aria-label], [alt]').forEach(el => {
      if (el.closest('.lang-switcher, [data-no-translate]')) return;
      const attrs = this._originalAttributes.get(el) || {};
      ['placeholder', 'title', 'aria-label', 'alt'].forEach(name => {
        const text = attrs[name]?.trim();
        if (!text) return;
        if (book[text] !== undefined) return;
        if (langCache[text] !== undefined) return;
        items.push({ element: el, attribute: name, text });
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
    if (this._circuitOpen()) return texts.map((t) => t); // récupération : rien à traduire
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
        const msg = err?.message || '';
        console.warn('i18n: DeepL indisponible, textes laissés en français :', msg || err);
        if (this._isProviderHardFailure(msg)) this._recordProviderFailure(msg);
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
        // Idempotence : si le nœud porte déjà la traduction (passe précédente,
        // pipeline HTML), on ne réapplique pas — sinon « x·EN·EN·EN ».
        if (item.node.nodeValue.includes(translated)) return;
        item.node.nodeValue = item.node.nodeValue.replace(item.text, translated);
      } else if (item.element) {
        item.element.setAttribute(item.attribute, translated);
      }
    });
    this.savePersistentCache(this.currentLang);
  },

  /* ===== Contenu dynamique : passes successives tant que la page évolue ===== */

  // Construit le HTML « propre » d'une section avant l'envoi à DeepL
  // (étape 4 du protocole) : sans scripts/styles/iframes/SVG, sans les
  // zones [translate=no]/[data-no-translate] (étape 3 : menu, footer…),
  // sans attributs id/class/on*/srcset, et sans les textes déjà traduits
  // (phrasebook ou cache) pour ne pas payer deux fois.
  _buildCleanHtml(root) {
    const clone = root.cloneNode(true);
    // Synchronise les textes du clone avec leurs ORIGINAUX : le clone n'a pas
    // accès au WeakMap, or un texte déjà traduit ne doit pas repartir chez
    // DeepL (sinon traduction de la traduction : « x·EN·EN »).
    const liveWalker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const cloneWalker = document.createTreeWalker(clone, NodeFilter.SHOW_TEXT);
    let liveNode, cloneNode;
    while ((liveNode = liveWalker.nextNode()) && (cloneNode = cloneWalker.nextNode())) {
      const original = this._originalText.get(liveNode);
      if (original !== undefined && cloneNode.nodeValue !== original) {
        cloneNode.nodeValue = original;
      }
    }
    clone.querySelectorAll('script, style, noscript, template, iframe, svg, canvas, [translate="no"], [data-no-translate]')
      .forEach(el => el.remove());
    clone.removeAttribute('id');
    clone.removeAttribute('class');
    [clone, ...clone.querySelectorAll('*')].forEach(el => {
      [...el.attributes].forEach(attr => {
        const name = attr.name.toLowerCase();
        if (name.startsWith('on') || name === 'srcset') el.removeAttribute(attr.name);
      });
    });
    const book = this.translations.phrasebook || {};
    const langCache = this._cache[this.currentLang] || {};
    const walker = document.createTreeWalker(clone, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const value = node.nodeValue.trim();
      if (value && (book[value] !== undefined || langCache[value] !== undefined)) {
        node.nodeValue = ''; // déjà traduit localement : exclu de la requête
      }
    }
    return clone.innerHTML;
  },

  // Textes non vides d'un fragment HTML, dans l'ordre du document.
  _textsFromHtml(html) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
    const out = [];
    let node;
    while ((node = walker.nextNode())) {
      if (node.nodeValue.trim()) out.push(node.nodeValue);
    }
    return out;
  },

  // Découpe le HTML d'une section en blocs traduisibles séparément :
  // l'énorme grille catalogue (120 véhicules) dépasse les limites d'une
  // requête DeepL. Chaque enfant de premier niveau devient un bloc ; un bloc
  // encore trop gros (section encapsulante) est redécoupé récursivement
  // jusqu'à ses feuilles (cartes véhicules, listes de filtres…).
  _splitIntoBlocks(html, maxChars = 9000) {
    const doc = new DOMParser().parseFromString('<div id="__i18n_root">' + html + '</div>', 'text/html');
    const rootNode = doc.getElementById('__i18n_root');
    if (!rootNode) return [html];

    // Texte DIRECT de l'élément (ses enfants texte à lui, pas ses
    // descendants) : un conteneur avec peu de texte mais un HTML énorme
    // (grille de 120 cartes) DOIT être redécoupé, pas traité en feuille.
    const ownTextLen = (el) => {
      let n = 0;
      for (const c of el.childNodes) {
        if (c.nodeType === Node.TEXT_NODE) n += c.nodeValue.trim().length;
      }
      return n;
    };

    const split = (node, depth) => {
      const htmlOf = (n) => n.nodeType === Node.TEXT_NODE
        ? n.nodeValue
        : (n.outerHTML || '');
      if (htmlOf(node).length <= maxChars) return [htmlOf(node)];
      // Feuille trop grosse : on ne peut pas la découper proprement.
      if (node.nodeType === Node.TEXT_NODE || depth > 6 || !node.querySelector?.('*') || ownTextLen(node) > maxChars) {
        return [htmlOf(node)];
      }
      const children = [...node.childNodes].filter(n =>
        n.nodeType === Node.ELEMENT_NODE || (n.nodeType === Node.TEXT_NODE && n.nodeValue.trim()));
      if (children.length <= 1) return [htmlOf(node)];
      return children.flatMap(c => split(c, depth + 1));
    };

    const children = [...rootNode.childNodes].filter(n =>
      n.nodeType === Node.ELEMENT_NODE || (n.nodeType === Node.TEXT_NODE && n.nodeValue.trim()));
    if (!children.length) return [html];
    return children.flatMap(c => split(c, 0));
  },

  // Regroupe les blocs en lots compacts pour limiter le nombre de requêtes.
  _groupBlocks(blocks, maxChars = 9000) {
    const groups = [];
    let current = [], size = 0;
    for (const b of blocks) {
      const len = b.length;
      if (len > maxChars) {
        if (current.length) { groups.push(current); current = []; size = 0; }
        groups.push([b]);
        continue;
      }
      if (size + len > maxChars && current.length) {
        groups.push(current);
        current = []; size = 0;
      }
      current.push(b);
      size += len;
    }
    if (current.length) groups.push(current);
    return groups;
  },

  // Traduit une section HTML ENTIÈRE via /translate/html — DeepL reçoit le
  // bloc d'une traite avec tag_handling=html v2 et respecte la structure
  // (étapes 1 & 2 du protocole). Les grosses sections sont découpées en
  // blocs (grille catalogue…) regroupés en quelques requêtes. Seuls les
  // TEXTES de la réponse sont réinjectés dans le DOM vivant : identifiants,
  // attributs, images et écouteurs d'événements restent intacts. En cas
  // d'échec, repli transparent sur la passe par lots.
  async translateSection(root) {
    if (!root || this.currentLang === 'fr') return true;
    if (this._circuitOpen()) return false; // provider en pause : rien à demander
    const api = window.API;
    if (!api || typeof api.request !== 'function') return false;
    const lang = this.currentLang;
    const html = this._buildCleanHtml(root);
    const sent = this._textsFromHtml(html);
    if (!sent.length) return true; // rien à confier à DeepL

    this._translating = true; // l'observateur ne lance pas de passe concurrente
    const translated = new Map(); // texte envoyé → texte traduit
    let anySuccess = false;
    try {
      const blocks = this._splitIntoBlocks(html);
      const groups = this._groupBlocks(blocks);
      for (const group of groups) {
        if (this.currentLang !== lang) break; // langue changée en cours
        if (this._circuitOpen()) break; // échec dur rencontré : on arrête tout
        let ok = false;
        let hardFailure = '';
        try {
          const data = await api.request('/translate/html', {
            method: 'POST',
            body: JSON.stringify({ html: group.join(''), target_lang: lang.toUpperCase() }),
          });
          if (data && typeof data.html === 'string') {
            const sentTexts = group.flatMap(g => this._textsFromHtml(g));
            const gotTexts = this._textsFromHtml(data.html);
            if (gotTexts.length === sentTexts.length) {
              sentTexts.forEach((t, i) => translated.set(t, gotTexts[i]));
              ok = true;
              anySuccess = true;
            }
          }
        } catch (err) {
          const msg = err?.message || '';
          console.warn('i18n: /translate/html :', msg || err);
          if (this._isProviderHardFailure(msg)) {
            // Le BACKEND/DeepL est en panne (quota, clé, indisponible,
            // rate-limit) : retenter bloc par bloc n'apportera rien et
            // mitraille le serveur (des centaines de requêtes par page).
            hardFailure = msg;
            this._recordProviderFailure(msg);
          }
        }
        if (!ok && group.length > 1 && !hardFailure) {
          // Échec de FORMAT/structure uniquement (ex. 422 HTML invalide) :
          // le lot entier à échoué mais un bloc isolé peut passer — un
          // véhicule cassé ne bloque pas les 119 autres.
          for (const single of group) {
            if (this._circuitOpen()) break;
            try {
              const data = await api.request('/translate/html', {
                method: 'POST',
                body: JSON.stringify({ html: single, target_lang: lang.toUpperCase() }),
              });
              if (data && typeof data.html === 'string') {
                const sentTexts = this._textsFromHtml(single);
                const gotTexts = this._textsFromHtml(data.html);
                if (gotTexts.length === sentTexts.length) {
                  sentTexts.forEach((t, i) => translated.set(t, gotTexts[i]));
                  anySuccess = true;
                }
              }
            } catch (err) {
              const msg = err?.message || '';
              if (this._isProviderHardFailure(msg)) this._recordProviderFailure(msg);
              /* sinon : bloc ignoré silencieusement */
            }
          }
        }
      }
    } finally {
      this._translating = false;
    }
    if (this.currentLang !== lang) return false; // langue changée entre-temps

    if (!anySuccess) {
      this._scheduleTranslate(); // repli : passe par lots classique
      return false;
    }

    // Ré-injection : appaire chaque texte traduit au nœud VIVANT dont
    // l'original correspond (ordre DeepL conservé grâce à l'appariement).
    const pending = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const original = this._originalText.get(node) ?? node.nodeValue;
      if (original.trim()) pending.push({ node, original });
    }
    const langCache = this._cache[lang] || (this._cache[lang] = {});
    translated.forEach((newText, old) => {
      if (!newText || !newText.trim() || newText.trim() === old.trim()) return;
      const idx = pending.findIndex(e => e.original.trim() === old.trim());
      if (idx === -1) return;
      const { node: target, original } = pending.splice(idx, 1)[0];
      if (target.nodeValue.includes(newText)) return; // déjà appliqué (idempotence)
      if (!this._originalText.has(target)) this._originalText.set(target, original);
      target.nodeValue = original.replace(old, newText);
      // Mémorise le couple : jamais retraduit (cache persistant + observateur).
      langCache[old.trim()] = newText.trim();
    });
    this.savePersistentCache(lang);
    return true;
  },

  // Traduit un fragment de DOM à la volée (contenu injecté par JS : fiche
  // véhicule, cartes catalogue, avis…). Instantané via phrasebook/clés,
  // puis la section entière part en UNE requête DeepL « HTML v2 ».
  translateElement(root) {
    if (!root || this.currentLang === 'fr') return;
    this.captureOriginalContent(root);
    this.applyLocaleKeys(root);
    this.applyPhrasebook(root);
    this.translateSection(root).catch(() => {});
  },

  _scheduleTranslate() {
    if (this._circuitOpen()) return; // provider en pause : on ne relance rien
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
    if (this._circuitOpen()) return;
    this._translating = true;
    try {
      for (let pass = 0; pass < this.MAX_PASSES; pass++) {
        this._dirty = false;
        await this.translatePage();
        if (this._circuitOpen()) break; // panne survenue en cours : stop
        if (!this._dirty) break; // page stable : terminé
      }
    } finally {
      this._translating = false;
    }
  },

  observeDynamicContent() {
    if (this._observer) return;
    // Perf : en français (langue source) aucun nœud n'est à traduire —
    // inutile d'écouter chaque mutation du DOM sur toutes les pages.
    if (this.currentLang === 'fr' && !this._observer) {
      const start = () => this.observeDynamicContent();
      document.addEventListener('languageChanged', start, { once: true });
      return;
    }
    this._observer = new MutationObserver(() => {
      if (this.currentLang === 'fr') return;
      this._scheduleTranslate();
    });
    this._observer.observe(document.body, { childList: true, subtree: true });
  },

  /* ===== Language change ===== */

  async setLanguage(lang) {
    if (!this.supported.includes(lang)) lang = 'fr';
    // Choix explicite du visiteur via le sélecteur : mémorisé et prioritaire
    // sur l'auto-détection du navigateur (voir _init).
    localStorage.setItem('lang', lang);
    localStorage.setItem('lang_manual', '1');
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
      await this.translateSection(document.body).catch(err => console.warn('i18n:', err));
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
     1. S'il a choisi UNE LANGUE MANUELLEMENT (sélecteur → 'lang_manual'),
        on respecte durablement son choix (localStorage 'lang').
     2. Sinon, la langue du navigateur est détectée À CHAQUE VISITE
        (navigator.languages puis navigator.language) et le site s'adapte
        automatiquement. ex : "fr-FR", "en-US", "de-DE" → préfixe (fr, en, de…)
        et variantes régionales acceptées (pt-BR → pt, en-GB → en…).
     3. Repli : préférence précédente mémorisée, puis français.
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
    this._readyPromise = this._init();
    return this._readyPromise;
  },

  // Promesse résolue quand la locale initiale est chargée et appliquée.
  // Permet aux pages (fiche véhicule…) d'attendre les traductions avant
  // leur premier rendu — plus de textes français corrigés après coup.
  whenReady() {
    if (this._readyPromise) return this._readyPromise;
    return Promise.resolve();
  },

  async _init() {
    const saved = localStorage.getItem('lang');
    const manual = localStorage.getItem('lang_manual') === '1';
    const browser = this.detectBrowserLanguage();
    // Détection automatique à chaque visite, sauf choix manuel explicite.
    const initial = manual ? (saved || browser || 'fr') : (browser || saved || 'fr');

    this.currentLang = initial;
    // On ne mémorise que le choix MANUEL : sans lui, la langue du navigateur
    // est re-sondée à chaque visite (et le site s'adapte tout seul).
    if (manual) localStorage.setItem('lang', initial);
    else localStorage.removeItem('lang');
    await this.loadLocaleFile(initial).catch(() => {});
    this.apply();
    this.injectSwitcher();
    // Clés statiques (nav, footer, filtres, titres) dès le chargement,
    // y compris en français (valeurs identiques au texte source).
    this.applyLocaleKeys();

    if (initial !== 'fr') {
      // Phrasebook immédiat (zéro réseau), puis la page part en UNE requête
      // DeepL « HTML v2 » ; les passes par lots ne traitent que les restes
      // (attributs, contenus apparus entre-temps).
      this.loadPersistentCache(initial);
      this.applyPhrasebook();
      await new Promise(resolve => setTimeout(resolve, 100));
      await this.translateSection(document.body).catch(err => console.warn('i18n:', err));
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
