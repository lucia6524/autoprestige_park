#!/usr/bin/env node
/**
 * gen-lang-pages.mjs — Pages SEO localisées, générées AU BUILD (SSG).
 *
 * Principe (voir docs/plan-seo-multilingue.md, phases 1-2) :
 *   Les pages FR buildées (dist/*.html) sont « réémisses » par langue dans
 *   dist/<lang>/<page>.html : nœuds texte + attributs (title/alt/aria-label/
 *   placeholder) traduits au moment de la génération, structure/classes/scripts
 *   à l'identique. ZÉRO appel réseau au déploiement : les traductions vivent
 *   dans public/locales/pages/pages_fr_<lang>.json (commitées).
 *
 * Modes :
 *   1) `node scripts/gen-lang-pages.mjs`            → génère dist/<lang>/… (après astro build)
 *   2) `node scripts/gen-lang-pages.mjs --collect`  → régénère les fichiers de
 *      traductions via l'API /translate (à lancer quand le contenu FR change).
 *
 * Le mapping est amorcé par le phrasebook des locales (<lang>.json, ~620
 * entrées FR→X déjà traduites) : Google n'est appelé que pour ce qui manque.
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join, dirname } from 'node:path';

const ROOT = fileURLToPath(new URL('../', import.meta.url));
const DIST = join(ROOT, 'dist');
const LOCALES = join(ROOT, 'public', 'locales');
const MAPS_DIR = join(LOCALES, 'pages');

const LANGS = ['en', 'de', 'it', 'es', 'pt', 'ro'];
// Pages à générer par langue. EN possède déjà a-propos/faq/contact (écrites à la
// main dans src/pages/en/ → Astro les sort à chaque build, on ne les écrase pas).
const CORE = ['index.html', 'vehicules.html', 'garantie.html', 'financement.html', 'livraison.html'];
const ADDITIONAL = ['a-propos.html', 'faq.html', 'contact.html'];
const GENERATED = Object.fromEntries(LANGS.map((l) => [l, l === 'en' ? [...CORE] : [...CORE, ...ADDITIONAL]]));

const API = 'https://autohaus-park-api.onrender.com/api/translate';
const SITE_URL = 'https://autohaus-park.onrender.com';
const TRANSLATE_ATTRS = ['title', 'alt', 'aria-label', 'placeholder'];
const SKIP_TAGS = new Set(['script', 'style', 'noscript', 'template', 'iframe', 'svg', 'canvas', 'textarea']);
const ASSET_EXTS = new Set(['css', 'js', 'woff2', 'woff', 'ttf', 'png', 'jpg', 'jpeg', 'webp', 'svg', 'ico']);

const BATCH_MAX_ITEMS = 40;
const BATCH_MAX_CHARS = 9000;

/* ---------- utils texte ---------- */

const ENTITIES = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' };
function decodeEntities(s) {
  return s.replace(/&(#x?[0-9a-f]+|[a-z]+);/gi, (m, body) => {
    if (body[0] === '#') {
      const hex = body[1] === 'x' || body[1] === 'X';
      const code = parseInt(body.slice(hex ? 2 : 1), hex ? 16 : 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : m;
    }
    return ENTITIES[body.toLowerCase()] ?? m;
  });
}
function norm(s) {
  return decodeEntities(s).replace(/\s+/g, ' ').trim();
}
function hasLetters(s) {
  return /[a-zA-Zàâäéèêëîïôöùûüçœ&'’"()%€–-]/i.test(s);
}
function esc(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/* ---------- parseur HTML léger (nœuds texte + attributs) ---------- */

function forEachTag(html, cb) {
  let i = 0;
  while (i < html.length) {
    const lt = html.indexOf('<', i);
    if (lt === -1) {
      cb('text', html.slice(i), null, lt);
      return;
    }
    if (lt > i) cb('text', html.slice(i, lt), null, lt);
    let gt = lt + 1;
    let quote = null;
    while (gt < html.length) {
      const ch = html[gt];
      if (quote) {
        if (ch === quote) quote = null;
      } else if (ch === '"' || ch === "'") {
        quote = ch;
      } else if (ch === '>') {
        break;
      }
      gt++;
    }
    const raw = html.slice(lt, Math.min(gt + 1, html.length));
    cb('tag', raw, null, lt);
    i = gt + 1;
  }
}

function parseTag(raw) {
  const inner = raw.slice(1, raw.endsWith('>') ? -1 : undefined);
  const m = inner.trim().match(/^(\/?)([a-zA-Z][a-zA-Z0-9-]*)/);
  return {
    name: m ? m[2].toLowerCase() : '',
    closing: m ? m[1] === '/' : false,
    selfClosing: /\/\s*$/.test(inner),
    inner,
  };
}

function attrTokens(inner) {
  const tokens = [];
  const re = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))/g;
  let m;
  while ((m = re.exec(inner))) {
    const value = m[2] ?? m[3] ?? m[4] ?? '';
    tokens.push({ name: m[1].toLowerCase(), value, start: m.index, end: m.index + m[0].length });
  }
  return tokens;
}

/**
 * Traduit un document FR en une page localisée. `mode: 'supaMap'` exécute la
 * traduction ; `mode: 'extract'` ne fait que collecter les clés FR (build map).
 */
function buildLocalized(html, { map, langMap, siblings, generate, collect }) {
  const out = [];
  let skipDepth = 0;
  const ntStack = []; // pile des balises ouvrantes data-no-translate (logo, marque)

  function processText(text) {
    if (skipDepth > 0 || ntStack.length > 0) {
      out.push(text);
      return;
    }
    const key = norm(text);
    if (collect) {
      if (key && key.length > 1 && key.length <= 8000 && hasLetters(key)) collect.add(key);
      out.push(text);
      return;
    }
    if (map && key && map[key] && map[key] !== key) out.push(esc(map[key]));
    else out.push(text);
  }

  /**
   * Passe d'attributs sur la balise : traduit title/alt/aria-label/placeholder
   * + meta description, réécrit src/href (arborescence /<lang>/), et collecte
   * les clés en mode collect. Découpe/recolle la balise uniquement si besoin;
   * renvoie la balise reconstruite (ou raw si aucun changement).
   */
  function applyTagAttrs(raw, t) {
    const tokens = attrTokens(t.inner);
    if (!tokens.length) return raw;
    const replaced = new Map(); // start → { repl, end }
    for (const tk of tokens) {
      if (tk.name === 'content' && t.name === 'meta' && t.inner.includes('name="description"')) {
        const key = norm(tk.value);
        if (collect) {
          if (key.length > 1 && key.length <= 8000 && hasLetters(key)) collect.add(key);
        } else if (map && map[key] && map[key] !== key) {
          replaced.set(tk.start, { repl: `${tk.name}="${esc(map[key])}"`, end: tk.end });
        }
        continue;
      }
      if (TRANSLATE_ATTRS.includes(tk.name)) {
        const key = norm(tk.value);
        if (collect) {
          if (key.length > 1 && key.length <= 8000 && hasLetters(key)) collect.add(key);
        } else if (map && map[key] && map[key] !== key) {
          replaced.set(tk.start, { repl: `${tk.name}="${esc(map[key])}"`, end: tk.end });
        }
        continue;
      }
      if ((tk.name === 'src' || tk.name === 'href') && !collect) {
        const value = rewriteUrl(tk.value, langMap, siblings);
        if (value !== tk.value) {
          replaced.set(tk.start, { repl: `${tk.name}="${value}"`, end: tk.end });
        }
        continue;
      }
    }
    if (!replaced.size) return raw;
    let rebuilt = '';
    let cursor = 0;
    for (const start of [...replaced.keys()].sort((a, b) => a - b)) {
      rebuilt += t.inner.slice(cursor, start);
      rebuilt += replaced.get(start).repl;
      cursor = replaced.get(start).end;
    }
    rebuilt += t.inner.slice(cursor);
    return '<' + rebuilt + '>';
  }

  function processTag(raw) {
    const t = parseTag(raw);
    const inNt = ntStack.length > 0;
    if (t.closing) {
      // Une balise fermante ne sort de la zone data-no-translate que si c'est
      // celle de SA racine (les fermantes imbriquées — </span> dans <h1> — n'y
      // touchent pas).
      if (skipDepth > 0) skipDepth--;
      else if (inNt && t.name === ntStack[ntStack.length - 1]) ntStack.pop();
      out.push(raw);
      return;
    }
    const noTranslate = /data-no-translate/.test(raw);
    if (skipDepth > 0) {
      if (!t.selfClosing && SKIP_TAGS.has(t.name)) skipDepth++;
      // Contenu de script/style/textarea non traduit, mais les ATTRIBUTS doivent
      // rester valides/traduits (ex. src="../js/loader.js", placeholder EN).
      out.push(applyTagAttrs(raw, t));
      return;
    }
    if (inNt) {
      // Zone data-no-translate (logo, marque Autohaus) : TOUT le texte reste
      // identique, seuls les attributs sont traités (src/href réécrits).
      if (!t.selfClosing && noTranslate) ntStack.push(t.name);
      out.push(applyTagAttrs(raw, t));
      return;
    }
    if (!t.selfClosing && SKIP_TAGS.has(t.name)) {
      skipDepth++;
      out.push(applyTagAttrs(raw, t));
      return;
    }
    if (!t.selfClosing && noTranslate) {
      ntStack.push(t.name);
      out.push(applyTagAttrs(raw, t));
      return;
    }
    // On traduit TOUT le document (translate="no" ignoré) : le <header>/<footer>
    // statiques portent aussi leurs libellés dans le HTML servi (SEO sans JS).
    // Le texte des balises <script>/<style> reste intact grâce au skipDepth ci-dessus.
    out.push(applyTagAttrs(raw, t));
  }

  forEachTag(html, (kind, raw) => {
    if (kind === 'text') processText(raw);
    else processTag(raw);
  });
  return out.join('');
}

function rewriteUrl(url, langMap, siblings) {
  if (!url) return url;
  if (/^(https?:|mailto:|tel:|sms:|data:|#|\/|\.\.\/|\.\/)/i.test(url)) return url;
  const clean = url.split(/[?#]/)[0];
  const ext = clean.includes('.') ? clean.split('.').pop().toLowerCase() : '';
  if (ASSET_EXTS.has(ext)) return '../' + url;
  if (clean.endsWith('.html')) {
    const base = clean.split('/').pop();
    if (siblings && siblings.has(base)) return url;
    return '../' + url;
  }
  return '../' + url;
}

/* ---------- primage du phrasebook + chargement json ---------- */

function loadLocale(lang) {
  try {
    return JSON.parse(readFileSync(join(LOCALES, `${lang}.json`), 'utf8'));
  } catch {
    return {};
  }
}

function primeFromPhrasebook(lang) {
  const fr = loadLocale('fr').phrasebook || {};
  const target = loadLocale(lang).phrasebook || {};
  const map = {};
  for (const key of Object.keys(fr)) {
    const trans = target[key];
    if (trans && norm(key) !== norm(trans)) map[norm(key)] = trans;
  }
  return map;
}

/* ---------- collecte des traductions (nécessite l'API) ---------- */

async function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function translateBatch(texts, lang) {
  let attempt = 0;
  for (;;) {
    attempt++;
    let res;
    try {
      res = await fetch(API, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ texts, target_lang: lang.toUpperCase() }),
      });
    } catch (err) {
      if (attempt >= 3) throw err;
      console.warn(`[collect:${lang}] erreur réseau (${err.cause?.code || err.message}) → retry ${attempt}/3`);
      await sleep(7000 * attempt);
      continue;
    }
    if (res.status === 429) {
      console.warn(`[collect:${lang}] 429 volume/quota → pause 5 min`);
      await sleep(310_000);
      continue;
    }
    if (!res.ok) throw new Error(`translate ${lang} HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`);
    const data = await res.json();
    return data.translations;
  }
}

/**
 * Traductions choisies (« overrides ») pour les textes-phares de l'accueil,
 * priorité maximale : homogénéité entre pages statiques (/lang/), phrasebook
 * runtime et qualité native (locales/home/<lang>.json, écrites à la main).
 */
function loadHomeOverrides(lang) {
  try {
    return JSON.parse(readFileSync(join(LOCALES, 'home', `${lang}.json`), 'utf8'));
  } catch {
    return {};
  }
}

async function collect(lang, fresh = false) {
  const mapFile = join(MAPS_DIR, `pages_fr_${lang}.json`);
  if (!fresh && existsSync(mapFile)) {
    console.log(`[collect:${lang}] map existante → skip (relancer avec --fresh pour forcer)`);
    return;
  }
  const overrides = loadHomeOverrides(lang);
  const map = { ...primeFromPhrasebook(lang), ...overrides };
  const collectSet = new Set();
  for (const page of GENERATED[lang]) {
    const file = join(DIST, page);
    if (!existsSync(file)) continue;
    const html = readFileSync(file, 'utf8');
    buildLocalized(html, { collect: collectSet });
  }
  const unused = Object.keys(overrides).filter((k) => !collectSet.has(k));
  if (unused.length) {
    console.warn(`[collect:${lang}] ⚠️  ${unused.length} overrides jamais vus sur les pages FR → clés à corriger :`);
    for (const k of unused) console.warn('    - ' + JSON.stringify(k));
  }
  const missing = [...collectSet].filter((k) => !(k in map));
  console.log(`[collect:${lang}] ${collectSet.size} clés uniques, ${missing.length} à traduire via API`);

  // Groupage par lots ≤ 40 items / ≤ 9000 caractères.
  const chunks = [];
  let current = [];
  let chars = 0;
  for (const key of missing) {
    if (current.length >= BATCH_MAX_ITEMS || (chars + key.length > BATCH_MAX_CHARS && current.length)) {
      chunks.push(current);
      current = [];
      chars = 0;
    }
    current.push(key);
    chars += key.length;
  }
  if (current.length) chunks.push(current);

  for (const chunk of chunks) {
    const translations = await translateBatch(chunk, lang);
    chunk.forEach((key, i) => {
      const trans = translations[i];
      if (trans && norm(key) !== norm(trans)) map[key] = trans;
    });
    await sleep(1100); // politesse (volume + rate-limit par IP)
  }

  mkdirSync(MAPS_DIR, { recursive: true });
  writeFileSync(
    join(MAPS_DIR, `pages_fr_${lang}.json`),
    JSON.stringify({ lang, generatedAt: new Date().toISOString(), pages: GENERATED[lang], map }, null, 1)
  );
  console.log(`[collect:${lang}] map écrite (${Object.keys(map).length} entrées)`);
}

/* ---------- génération des pages ---------- */

function generate(lang) {
  const mapPath = join(MAPS_DIR, `pages_fr_${lang}.json`);
  if (!existsSync(mapPath)) {
    console.warn(`[build:${lang}] map absente (${mapPath}) → pages non générées`);
    return;
  }
  const { map } = JSON.parse(readFileSync(mapPath, 'utf8'));
  const siblings = new Set([...CORE, ...ADDITIONAL]);
  for (const page of GENERATED[lang]) {
    const frFile = join(DIST, page);
    if (!existsSync(frFile)) {
      console.warn(`[build:${lang}] ${page} absent de dist — ignoré`);
      continue;
    }
    let html = readFileSync(frFile, 'utf8');
    const localized = buildLocalized(html, { map, langMap: lang, siblings });
    // <html lang + mode statique (aucune traduction runtime sur la page).
    const head = localized.replace(/<html\s+lang="fr"/i, `<html lang="${lang}" data-static-i18n`);
    // Même source de vérité que LangLayout (i18n.js lit window.AP_I18N_PAGES) :
    // le sélecteur de langue navigue vers la variante si elle existe, sinon FR.
    // Tous les arbres contiennent finalement CORE + ADDITIONAL (EN = les 3
    // pages écrites à la main dans src/pages/en/).
    const knownLists = Object.fromEntries(LANGS.map((l) => [l, [...CORE, ...ADDITIONAL]]));
    // Canonical + hreflang : les 8 pages existent dans chaque arbre → alternates
    // complets (FR d'abord, x-default → FR).
    const alternates = LANGS
      .filter((l) => l !== 'fr')
      .map((l) => `<link rel="alternate" hreflang="${l}" href="${SITE_URL}/${l}/${page}" />`)
      .join('');
    const headLines =
      `    <link rel="canonical" href="${SITE_URL}/${lang}/${page}" />` +
      `    <link rel="alternate" hreflang="fr" href="${SITE_URL}/${page}" />` +
      `    <link rel="alternate" hreflang="x-default" href="${SITE_URL}/${page}" />` +
      alternates +
      `    <script>window.AP_I18N_PAGES = ${JSON.stringify(knownLists)};</script>`;
    const injected = head.replace('</head>', headLines + '</head>');
    const dir = join(DIST, lang);
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, page), injected);
    console.log(`[build:${lang}] ${page} ✓`);
  }
}

/**
 * Fusionne les overrides de l'accueil (locales/home/<lang>.json) dans une map
 * existante — priorité aux overrides, SANS appel réseau (les autres traductions
 * restent telles quelles). À relancer après avoir modifié les overrides.
 */
function primeOverrides(lang) {
  const overrides = loadHomeOverrides(lang);
  const mapFile = join(MAPS_DIR, `pages_fr_${lang}.json`);
  const existing = existsSync(mapFile)
    ? JSON.parse(readFileSync(mapFile, 'utf8'))
    : { lang, generatedAt: new Date().toISOString(), pages: GENERATED[lang], map: {} };
  const collectSet = new Set();
  for (const page of GENERATED[lang]) {
    const file = join(DIST, page);
    if (!existsSync(file)) continue;
    buildLocalized(readFileSync(file, 'utf8'), { collect: collectSet });
  }
  const unused = Object.keys(overrides).filter((k) => !collectSet.has(k) && !(k in existing.map));
  if (unused.length) {
    console.warn(`[prime:${lang}] ⚠️  ${unused.length} overrides sans entrée (clés à corriger) :`);
    for (const k of unused) console.warn('    - ' + JSON.stringify(k));
  }
  existing.map = { ...existing.map, ...overrides };
  writeFileSync(mapFile, JSON.stringify(existing, null, 1));
  console.log(`[prime:${lang}] map réamorcée avec ${Object.keys(overrides).length} overrides (${Object.keys(existing.map).length} entrées)`);
}

const arg = process.argv[2];
const FRESH = process.argv.includes('--fresh');
if (arg === '--collect') {
  console.log('# Collecte des traductions (API /translate)…');
  for (const lang of LANGS) await collect(lang, FRESH);
  console.log('# Terminé.');
} else if (arg === '--prime') {
  console.log('# Fusion des overrides dans les maps existantes…');
  for (const lang of LANGS) primeOverrides(lang);
  console.log('# Terminé.');
} else {
  console.log('# Génération des pages localisées…');
  for (const lang of LANGS) generate(lang);
  console.log('# Terminé.');
}