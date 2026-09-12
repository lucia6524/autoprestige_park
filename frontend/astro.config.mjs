// @ts-check
import { defineConfig } from 'astro/config';

// https://astro.build/config
export default defineConfig({
  // Static output (SSG) — all existing HTML pages are pre-built and served
  // from a CDN. No server runtime needed for the frontend.
  output: 'static',

  // Keep the same URLs as today (e.g. /vehicules.html) so no links break.
  build: {
    format: 'file',
  },

  // i18n SSG : le FR reste à la racine (URLs actuelles inchangées), les
  // arbres localisés (/en/...) s'ajoutent à côté (voir docs/plan-seo-multilingue.md).
  i18n: {
    defaultLocale: 'fr',
    locales: ['fr', 'en', 'de', 'it', 'es', 'pt', 'ro'],
    routing: { prefixDefaultLocale: false },
  },
});
