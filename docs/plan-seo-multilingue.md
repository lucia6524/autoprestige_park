# Migration SEO multilingue — Astro i18n + descriptions pré-traduites en base

> Objectif : des URLs indexables par langue (`/en/vehicules.html`, `/de/vehicule.html?id=…`)
> servies en SSG avec un contenu traduit **au moment du build** — le traducteur
> runtime Google ne reste que pour les contenus imprévisibles (avis clients).
>
> Principe directeur : **zéro régression FR**. Le français reste servi exactement
> comme aujourd'hui (racine, URLs inchangées) ; les arbres localisés s'ajoutent
> sans toucher l'existant et peuvent être retirés indépendamment (rollback simple).

## État des lieux (audit)

| Sujet | État actuel | Impact migration |
|---|---|---|
| Build | Astro `output: static`, `format: 'file'` → `/vehicules.html` | L'arborescence `/en/…` doit produire `en/vehicules.html` |
| Pages | 22 pages `.astro`, dont 3 indépendantes du Layout (admin, vehicule, vehicules) | Les pages SEO = index, vehicules, vehicule, contact, financement, marques, vendre, faq, à-propos… |
| i18n runtime | `i18n.js` : phrasebook 620 entrées × 6 langues + `/translate(/html)` (Google gratuit) + cache localStorage | Devient le **repli** FR + avis dynamiques ; désactivé sur pages déjà localisées |
| Locales | `public/locales/{fr,en,de,it,es,pt,ro}.json` : 191 clés + `meta.title_*` déjà traduits | Réutilisées **au build** ; ajouter `meta.description_*` |
| Catalogue | Table `vehicles` (description `Text` FR), API `/vehicles`, repli local `vehicles-data.js` | Ajout de colonnes `description_<lang>` + backfill script |
| Énumérations | `body_category`, `fuel`, `transmission`, `type` : valeurs FR déjà dans les phrasebooks | Traduites au build via dictionnaire, **pas de colonnes DB** |
| SEO technique | ❌ pas de sitemap, ❌ pas de robots.txt, pas de hreflang/canonical | Phase dédiée |
| Liens | `header.js` map `PAGES` codée en dur FR ; liens `.html` relatifs codés dans les pages/JS | Helper de localisation d'URL |
| Déploiement | Render statique (`render.yaml` inchangé) + API Python | Le build grossit (22 → ~70+ pages) |

## Décisions à valider avant démarrage

1. **Structure d'URL** : sous-répertoires `/en/…` sur le domaine actuel (recommandé :
   autorité mutualisée, deploy unique) — pas de sous-domaines ni ccTLD.
2. **Langue par défaut** : `fr` **sans préfixe** (`/vehicules.html` reste FR) — les 6
   autres préfixées. `hreflang x-default` → FR.
3. **Périmètre initial** : recommandé **EN + DE d'abord** (marchés prioritaires),
   puis IT/ES/PT/RO — le mécanisme est identique, seul le volume de pages change.
   (Les 6 d'un coup reste possible : le coût est surtout au build.)
4. **Pages traduites en priorité** (les autres restent FR et ne sont pas référencées
   hreflang tant qu'elles n'existent pas) :
   `index`, `vehicules`, `vehicule` (fiche), `contact`, `financement`, `marques`, `vendre`.

## Phase 1 — Socle Astro i18n (routing SSG)

1. `astro.config.mjs` :
   ```js
   i18n: {
     defaultLocale: 'fr',
     locales: ['fr', 'en', 'de', 'it', 'es', 'pt', 'ro'],
     routing: { prefixDefaultLocale: false },
   },
   ```
2. Refactor léger : extraire le contenu des pages cibles dans
   `src/components/pages/*.astro` paramétré par `lang` ; les pages localisées
   deviennent des stubs minces `src/pages/en/vehicules.astro` (etc.) qui
   appellent le composant avec `lang="en"` et les textes issus de
   `src/locales/<lang>.json` (import build, plus de fetch runtime).
   - Les pages FR restent **telles quelles** à la racine (aucune migration forcée).
3. Helper `localizedUrl(path, lang)` (utilitaire partagé) :
   `vehicules.html` + prefix si `lang !== 'fr'`.
4. `header.js` : `PAGES` devient une fonction résolue depuis
   `document.documentElement.lang` (ou un `data-lang` sur `<body>`) pour que la
   navigation pointe vers l'arbre localisé quand on s'y trouve.
5. `i18n.js` : sur page `lang !== 'fr'`, mode « navigation » —
   `setLanguage(lang)` redirige vers l'URL localisée équivalente au lieu de
   traduire le DOM ; le pipeline runtime (`translateSection`, passes,
   MutationObserver) est **court-circuité** (`data-static-i18n` sur `<html>`).

**Livrable** : `/en/index.html`, `/en/vehicules.html`, … pré-générés, nav cohérente,
FR intact. Build vérifié (nombre de pages, liens internes).

## Phase 2 — Contenu des pages traduit au build

1. Déplacer/étendre les locales : ajouter `meta.description_<page>` par langue
   (les `meta.title_*` existent déjà).
2. Les composants extraits rendent les textes depuis le JSON (clés existantes +
   phrasebook) : plus de `data-i18n` nécessaire sur les pages localisées
   (on le garde sans risque, il devient no-op car le texte correspond déjà).
3. Valeurs d'énumérations du catalogue rendues au build via un dictionnaire
   `enums.<lang>` (dérivé des phrasebooks) : carrosseries, carburants, boîtes, type.
4. `<html lang>`, `<title>`, meta description, OG/twitter par langue.

**Livrable** : pages localisées 100 % statiques (aucun appel traduction au chargement).

## Phase 3 — Catalogue : pré-traduction des descriptions en base

1. **Migration Alembic** (`backend/alembic/versions/`) :
   `ALTER TABLE vehicles ADD COLUMN description_en/de/it/es/pt/ro TEXT NOT NULL DEFAULT ''`
   (une migration unique ; vérifier `app/models/commerce.py` en amont — règle AGENTS.md).
2. **Script backfill** `backend/pretranslate_vehicles.py` :
   - idempotent et reprenable : ne traite que les véhicules/langues à colonne vide ;
   - traduit via la fonction interne `_translate_texts` (même endpoint Google,
     backoff déjà en place) **en direct (in-process), sans passer par HTTP** → pas
     de rate-limit interne ; politesse `sleep` entre lots ;
   - journal : nb traduits / échecs ; option `--lang en,de` et `--dry-run`.
3. **API** `/vehicles` + `/vehicles/{id}` : paramètre `?lang=en|de|…` (borné à la
   liste supportée) → `description` renvoyée = colonne localisée si non vide,
   sinon repli FR (jamais de description vide). `VehiclePublic` inchangé
   (le champ reste `description`) → **zéro breaking change frontend**.
   `Cache-Control` conservé.
4. **Repli local** `vehicles-data.js` : reste FR ; la fiche tente l'API avec
   `?lang=` et remplace la description si réponse (le re-rendu `renderLocalized`
   existe déjà) — sur site endormi, la fiche reste FR puis se traduit via le
   runtime existant (filet inchangé).
5. `import_vehicles.py` : flag `--translate` pour traduire à l'import.
6. Admin : édition FR inchangée ; après édition, relancer le backfill
   (une commande) — un bouton admin « régénérer les traductions » est une
   extension future, pas un prérequis.

**Livrable** : 120 descriptions × N langues en base, API servante par langue,
coût Google **une seule fois** (puis uniquement pour les véhicules nouveaux/modifiés).

## Phase 4 — SEO technique

1. `robots.txt` (`public/robots.txt`) : `Sitemap: https://autohaus-park.onrender.com/sitemap.xml`.
2. **Sitemap** : intégration officielle `@astrojs/sitemap` (justification règle
   AGENTS.md n°7 : package officiel Astro, aucun bundler nouveau) avec
   alternates par langue ; ou mini-script de build si on veut éviter la dépendance.
3. **hreflang + canonical** sur les pages localisées : un `<link rel="alternate"
   hreflang>` par variante **existante** + `x-default → FR` ; canonical absolu
   par page. (Ne jamais déclarer hreflang vers une page qui n'existe pas encore.)
4. JSON-LD (opportunité, phase suivante) : `AutoDealer` (index) + `Vehicle`/`Offer`
   (fiche) avec prix/monnaie/dispo.
5. `404.html` unique conservé (Render le sert automatiquement).

**Livrable** : sitemap soumis Search Console, hreflang validé (outil Google),
canoniques propres.

## Phase 5 — Déploiement & validation

1. `render.yaml` inchangé ; le build passe de 22 à ~60-100 pages (surveiller la
   durée, free tier OK).
2. Checklist de recette :
   - `/` et `/vehicules.html` FR **identiques** à aujourd'hui (diff de rendu) ;
   - `/en/vehicules.html` : filtres/badges/textes EN au build (view-source, pas de flash) ;
   - fiche `?id=…` : description localisée servie par l'API (`?lang=en`) ;
   - changement de langue via le drapeau = navigation vers l'URL localisée ;
   - hreflang/sitemap/canonical OK ; Lighthouse SEO ≥ 95 sur /en/.
3. Search Console : property unique, sitemap, suivi indexation `/en/` puis `/de/`.
4. Rollback : supprimer les arbres localisés (ou les retirer du sitemap/hreflang) —
   FR n'a jamais bougé.

## Estimation & risques

| Phase | Effort estimé | Risque principal | Mitigation |
|---|---|---|---|
| 1 Routing | ½ – 1 j | Liens codés en dur FR | Helper `localizedUrl` + grep exhaustif des `.html` |
| 2 Contenu build | 1 – 1,5 j | Oublis de clés de locale | Test build qui échoue si clé manquante |
| 3 Catalogue DB | 1 – 1,5 j | Quota/qualité Google sur backfill | Idempotent + repli FR + vocabulaire auto vérifié sur échantillon |
| 4 SEO technique | ½ j | hreflang incohérent | Génération depuis la même source de vérité que le build |
| 5 Recette | ½ j | — | Checklist ci-dessus |

**Total : ~4–5 jours de travail effectif**, découpable : la phase 1+2 sur
EN uniquement donne déjà un SEO anglais indexable ; les phases suivantes
s'additionnent sans refonte.

## Ce qui reste explicitement hors périmètre (pour l'instant)

- Traduction des **avis clients** : reste au traducteur runtime (contenu UGC imprévisible).
- Pages légales localisées (`mentions-legales`) : à confier à un juridique, pas à Google.
- Multi-régions (pt-BR vs pt-PT…) : un seul `pt` suffit aujourd'hui.
