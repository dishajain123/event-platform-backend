"""phase 16 check-out timestamps for re-entry accounting"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "r3a4b5c6d7e8"
down_revision: Union[str, None] = "q2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("check_ins", sa.Column("exited_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("check_ins", "exited_at")
