"""phase 15 indexes for competition-scoped stage and entry queries"""
from typing import Sequence, Union

from alembic import op

revision: str = "p1e2f3a4b5c6"
down_revision: Union[str, None] = "o0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_competition_stages_competition_id ON competition_stages (competition_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_entries_competition_id ON entries (competition_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_entries_competition_id")
    op.execute("DROP INDEX IF EXISTS ix_competition_stages_competition_id")
