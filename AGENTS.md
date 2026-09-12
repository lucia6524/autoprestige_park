# AGENTS.md — Règles pour les agents IA sur ce projet

> Ce fichier décrit la structure et les conventions du dépôt pour que les
> agents (Grok, opencode, etc.) travaillent efficacement.

## Vue d'ensemble

- **Site** : vente de véhicules d'occasion, vitrine multilingue (FR/EN/DE/IT/ES/PT/RO) + e-commerce complet.
- **Frontend** : Astro 5 (SSG statique) → `frontend/dist/` (déployé par Render). HTML générés, pas de SPA.
- **Backend** : FastAPI + SQLAlchemy 2 async, Python 3.13. Sans tests = CI interdite. Les pages statiques `.html` (index, vehicules, admin…) sont dans **`frontend/dist/`**, générées à partir de `frontend/src/`. Ne PAS éditer directement les `.html` du build.

## Structure

```
autoprestige/
├── frontend/               # Source Astro
│   ├── src/pages/          # 22 pages .astro (source des .html)
│   ├── src/layouts/, src/components/
│   ├── public/             # Servi tel quel : css/, js/, locales/, thumbs/ (WebP)
│   └── dist/               # Build (ne pas éditer ; voir npm run build)
├── backend/                # API FastAPI
│   ├── app/                # main.py, config.py, database.py, models/, routers/, services/, schemas.py, deps.py
│   ├── alembic/            # Migrations de schéma (baseline initiale incluse)
│   ├── tests/              # Suite pytest (nécessaire avant toute modif backend)
│   ├── run.py, requirements.txt, pyproject.toml (ruff + pytest), alembic.ini
├── render.yaml             # Déploiement Render (site statique + API + PostgreSQL)
├── AGENTS.md, README.md
```

## Règles

1. Préférer read_file / write_file ; écrire des fichiers complets.
2. Respecter le style existant (ruff configuré dans `backend/pyproject.toml`).
3. **Après toute modification backend : exécuter `python -m pytest` (depuis `backend/`) et `python -m ruff check app tests`.** Ne pas laisser de tests rouges.
4. Toujours vérifier les modèles SQLAlchemy avant de toucher le schéma ; les migrations vont dans `backend/alembic/versions/` (voir README § Maintenance), pas dans des ALTER inline.
5. Ne JAMAIS committer `.env` (les valeurs réelles ne sont que dans Render). Ne pas casser les gardes de prod dans `config.py` (SECRET_KEY, ADMIN_PASSWORD, CORS obligatoires).
6. Rester dans le workspace. Pas de secrets dans le code.
7. Ne pas utiliser de toolchain non présente dans le repo (pas de nouveau bundler/buildtool sans justification).

## Commandes utiles

```bash
cd backend
python -m pip install -r requirements.txt   # + pytest, alembic, ruff
python -m pytest                        # tests API
python -m ruff check app tests          # lint
python run.py                           # API locale http://127.0.0.1:8000
cd frontend && npm install && npm run build   # régénère dist/
```