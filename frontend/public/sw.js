/* Service worker — cache des assets statiques (visites répétées instantanées).
 * Render ne permet pas d'override Cache-Control sur le CDN statique
 * (max-age=0 forcé) donc chaque visite revalidait tout. Ici :
 *  - assets (js/css/fonts/images) : cache-d'abord, contournement en arrière-plan
 *    (stale-while-revalidate) → l'affichage est immédiat, le fichier se met à jour
 *    tout seul même si Render force max-age=0 ;
 *  - HTML (navigation) : réseau d'abord pour garder le contenu frais.
 */
const CACHE = 'ap-static-v1';
const STATIC_RE = /\.(js|css|woff2?|ttf|webp|png|jpe?g|svg|ico|webmanifest)(\?.*)?$/;

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)));
      await self.clients.claim();
    })()
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/')) return;

  if (request.mode === 'navigate') {
    event.respondWith(
      (async () => {
        const cache = await caches.open(CACHE);
        try {
          const response = await fetch(request);
          if (response.ok) cache.put(request, response.clone());
          return response;
        } catch (err) {
          const fallback = await cache.match(request);
          if (fallback) return fallback;
          return cache.match('/index.html') || Response.error();
        }
      })()
    );
    return;
  }

  if (!STATIC_RE.test(url.pathname)) return;

  event.respondWith(
    (async () => {
      const cache = await caches.open(CACHE);
      const cached = await cache.match(request);
      const update = fetch(request)
        .then((response) => {
          if (response.ok) cache.put(request, response.clone());
          return response;
        })
        .catch(() => cached);
      return cached || update;
    })()
  );
});