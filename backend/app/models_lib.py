"""Point d'entrée unique du métadonnées SQLAlchemy.

`database.py` n'expose que la base + les importer ici, afin qu'Alembic
(env.py) puisse reconstruire le même `Base.metadata` SANS créer d'engine et
sans dépendre de `config.settings` (contournement des blocages de prod).
Importer `models_lib` enregistre TOUTES les tables.
"""
from app.database import Base
from app.models import commerce, reviews, site_settings, user  # noqa: F401

__all__ = ["Base"]
