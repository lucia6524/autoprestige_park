// i18n côté BUILD (SSG) — remplace la traduction runtime pour les pages
// localisées. Source de vérité unique : public/locales/<lang>.json (les mêmes
// fichiers que le mode runtime), lus au build via node:fs — ce module ne
// s'exécute jamais dans le navigateur (output: static).
//
// Voir docs/plan-seo-multilingue.md (phase 1 & 2).
import { readFileSync } from 'node:fs';

export const DEFAULT_LOCALE = 'fr';
export const LOCALES = ['fr', 'en', 'de', 'it', 'es', 'pt', 'ro'] as const;
export type Locale = (typeof LOCALES)[number];

/** Origine de production (canonicals + hreflang). */
export const SITE_URL = 'https://autohaus-park.onrender.com';

/**
 * POC phase 1 : pages réellement présentes dans CHAQUE arbre localisé.
 * Tant qu'une page n'y figure pas pour une langue : les liens depuis cet
 * arbre pointent vers sa version FR (../) et elle n'est JAMAIS déclarée en
 * hreflang pour cette langue (jamais de hreflang vers une page inexistante).
 * À étendre au fil des phases (voir docs/plan-seo-multilingue.md).
 */
export const LOCALIZED_PAGES: Partial<Record<Locale, Set<string>>> = {
  en: new Set(['contact.html', 'faq.html', 'a-propos.html']),
  // de/es/it/pt/ro : ajoutés en phase suivante
};

const _cache = new Map<string, Record<string, unknown>>();

/** Dictionnaire de locale (clés imbriquées + phrasebook) lu une seule fois. */
export function getDict(locale: Locale): Record<string, unknown> {
  const cached = _cache.get(locale);
  if (cached) return cached;
  const raw = readFileSync(
    new URL(`../../public/locales/${locale}.json`, import.meta.url),
    'utf-8',
  );
  const data = JSON.parse(raw) as Record<string, unknown>;
  _cache.set(locale, data);
  return data;
}

/** Résout une clé imbriquée ('nav.home') avec repli explicite. */
export function t(dict: Record<string, unknown>, key: string, fallback = ''): string {
  let value: unknown = dict;
  for (const part of key.split('.')) {
    if (value && typeof value === 'object' && part in value) {
      value = (value as Record<string, unknown>)[part];
    } else {
      return fallback;
    }
  }
  return typeof value === 'string' ? value : fallback;
}

/**
 * Lien interne DEPUIS une page de l'arbre localisé : vers la page localisée
 * si elle existe, sinon vers la page FR de la racine (repli assumé du POC —
 * mieux qu'un lien mort). Sur les pages FR (lang='fr'), href inchangé.
 */
export function linkFor(file: string, lang: Locale): string {
  if (lang === DEFAULT_LOCALE) return file;
  return LOCALIZED_PAGES[lang]?.has(file) ? file : `../${file}`;
}

/**
 * Chemins d'assets/communs depuis une page localisée (un niveau de dossier
 * de plus que la racine) : logo.png → ../logo.png, css/… → ../css/…
 */
export function assetFor(path: string, lang: Locale): string {
  return lang === DEFAULT_LOCALE ? path : `../${path}`;
}
