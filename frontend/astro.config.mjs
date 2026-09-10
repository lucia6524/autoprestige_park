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
});
