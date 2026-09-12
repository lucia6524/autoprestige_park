"""vehicles: colonnes de description par langue (SEO multilingue, phase 3)

Revision ID: a1f2c3d4e5f6
Revises: 06d3313bd89f
Create Date: 2026-09-12 19:10:00.000000

Descriptions pré-traduites une fois par pretranslate_vehicles.py ; vide =
non traduite → l'API renvoie la description FR (repli garanti).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1f2c3d4e5f6'
down_revision: Union[str, None] = '06d3313bd89f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LANGS = ('en', 'de', 'it', 'es', 'pt', 'ro')


def upgrade() -> None:
    for lang in LANGS:
        op.add_column(
            'vehicles',
            sa.Column(f'description_{lang}', sa.Text(), nullable=False, server_default=''),
        )


def downgrade() -> None:
    for lang in LANGS:
        op.drop_column('vehicles', f'description_{lang}')
