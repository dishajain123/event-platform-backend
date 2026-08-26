# Intentionally minimal in Phase 1 — organizations/router.py queries directly
# via SQLAlchemy for this module's simple CRUD. A repository layer is added
# here if/when this module grows business rules worth separating out
# (e.g. once real multi-organizer support is built).