# Autohaus — Site + Backend

## Contenu

- Site vitrine multilingue (FR, EN, DE, IT, ES, PT, RO)
- Catalogue 120 véhicules + pages détail
- Backend FastAPI (auth, panier, commandes, échéancier, livraison)
- Inscription multi-étapes + vérification email OTP

## Structure

```
autoprestige/
├── frontend/          # Site Astro (statique, génération de pages .html)
│   ├── src/pages/     # 22 pages .astro
│   ├── src/layouts/   # Layout, Header, Footer
│   ├── public/        # css/, js/, locales/, thumbs/ (assets servis tels quels)
│   └── dist/          # Sortie du build (déployée par Render)
├── backend/           # API FastAPI (auth, véhicules, panier, commandes)
├── render.yaml        # Déploiement Render (site statique + API + PostgreSQL)
└── README.md
```

## Démarrage rapide

### 1. Backend

```bash
cd backend
pip install -r requirements.txt

# Optionnel : envoi réel des emails
cp .env.example .env
# Édite .env avec tes identifiants (Brevo SMTP, DeepL, ADMIN_PASSWORD…)

python run.py
# API sur http://127.0.0.1:8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run build      # génère le site 100 % statique dans frontend/dist/
npm run dev        # (optionnel) serveur de dev Astro
```

## Pages importantes

| Page            | URL                |
| --------------- | ------------------ |
| Accueil         | index.html         |
| Catalogue       | vehicules.html     |
| Détail véhicule | vehicule.html?id=1 |
| Inscription     | inscription.html   |
| Connexion       | connexion.html     |
| Espace compte   | compte.html        |

## Auth

1. Inscription en 4 étapes (nom → email/tél → salaire → code email)
2. Le code OTP interne est affiché à l'écran puis saisi par l'utilisateur
3. Après validation → espace compte (panier, commandes, livraison)

## Déploiement (Render)

`render.yaml` définit :

- **autoprestige-site** : site statique ; `frontend/dist` est publié après
  `npm run build`. Le fichier `frontend/public/404.html` (copié dans dist)
  sert malgré lui de page 404.
- **autoprestige-api** : API Uvicorn sur le dossier `backend`.
- **progrest** : base PostgreSQL (le réglage `PYTHON_VERSION` et de nombreuses
  variables d'env sont à renseigner dans l'UI Render, avec `sync: false`).

## Maintenance

- Génération des vignettes locales WebP dans `frontend/public/thumbs/` +
  table `frontend/public/js/vehicles-thumbs.js` :
  ```bash
  cd backend && python optimize_catalog_images.py
  ```
- Import du catalogue local (`frontend/public/js/vehicles-data.js`) vers l'API :
  ```bash
  cd backend && python import_vehicles.py --email ... --password ...
  ```
- Tests + lint :
  ```bash
  cd backend
  python -m pytest                   # suite de tests API (10 tests)
  python -m ruff check app tests     # lint
  ```
- Migrations de schéma (`backend/alembic/`) :
  ```bash
  cd backend
  DATABASE_URL=... alembic upgrade head   # applique les migrations
  alembic revision --autogenerate -m "description"   # nouvelle migration
  ```
  À noter : `init_db` crée le schéma au démarrage (`create_all`) pour une base
  neuve. Pour une base existante, la migration initiale est une *baseline* :
  appliquez `alembic stamp head` UNE fois pour enregistrer le schéma courant,
  puis migrez ensuite avec `alembic upgrade head`.