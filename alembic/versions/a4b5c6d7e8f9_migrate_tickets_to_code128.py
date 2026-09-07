"""rename QR ticket columns to the generic signed barcode contract"""

from typing import Sequence, Union

from alembic import op


revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, None] = "9d0e1f2a3b45"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing payloads are printable Code 128-compatible signed values.
    # Renaming preserves tickets issued before this migration.
    op.alter_column("tickets", "qr_payload", new_column_name="barcode_payload")
    op.alter_column("tickets", "qr_signature", new_column_name="barcode_signature")


def downgrade() -> None:
    op.alter_column("tickets", "barcode_signature", new_column_name="qr_signature")
    op.alter_column("tickets", "barcode_payload", new_column_name="qr_payload")
