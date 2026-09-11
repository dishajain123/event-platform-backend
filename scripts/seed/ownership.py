"""Persist seed ownership in the existing audit schema; never infer it from names."""
import json
import uuid
from pathlib import Path
from sqlalchemy import select, delete, update
from app.core.base_model import Base
from app.modules.audit_log.models import AuditLog

NAMESPACE = uuid.UUID('b0b9c320-e23b-4c9e-a689-743cab131885')
MANIFEST_ID = uuid.uuid5(NAMESPACE, 'manifest')


def seed_id(table, key):
    return uuid.uuid5(NAMESPACE, f'{table}:{key}')


async def load_manifest(db):
    row = await db.get(AuditLog, MANIFEST_ID)
    return row, (row.after_value or {}).get('records', {}) if row else {}


async def reset_owned(db):
    """Delete only exact registered IDs, protecting outside references transitively.

    Role definitions are shared infrastructure and never deleted. Nullable links
    wholly inside the deletion set are cleared to resolve cycles before deletion.
    No CASCADE, TRUNCATE, name-prefix or email-domain deletion is used.
    """
    manifest, registered = await load_manifest(db)
    legacy = json.loads((Path(__file__).parent / 'legacy_inventory.json').read_text())
    candidates = {}
    for name in set(registered) | set(legacy):
        table = Base.metadata.tables[name]
        ids = {uuid.UUID(v) for v in registered.get(name, []) + legacy.get(name, [])}
        if ids:
            candidates[name] = set((await db.execute(select(table.c.id).where(table.c.id.in_(ids)))).scalars())
    original = {name: set(ids) for name, ids in candidates.items()}
    changed = True
    while changed:
        changed = False
        # Audit references are UUID columns rather than declared foreign keys.
        audit = Base.metadata.tables['audit_logs']
        outside_audit = audit.c.id.not_in(candidates.get('audit_logs', set()) | {MANIFEST_ID})
        for target, column, extra in [('users', audit.c.actor_user_id, None),
                ('users', audit.c.entity_id, audit.c.entity_type == 'user'),
                ('events', audit.c.entity_id, audit.c.entity_type == 'event')]:
            ids = candidates.get(target, set())
            if ids:
                query = select(column).where(outside_audit, column.in_(ids))
                if extra is not None:
                    query = query.where(extra)
                protected = set((await db.execute(query)).scalars())
                if protected:
                    candidates[target] -= protected
                    changed = True
        for table in Base.metadata.tables.values():
            for fk in table.foreign_keys:
                target = fk.column.table.name
                ids = candidates.get(target, set())
                if not ids:
                    continue
                outside = select(fk.parent).where(fk.parent.in_(ids))
                if candidates.get(table.name):
                    outside = outside.where(table.c.id.not_in(candidates[table.name]))
                protected = set((await db.execute(outside)).scalars())
                if protected:
                    candidates[target] -= protected
                    changed = True
    for table in Base.metadata.tables.values():
        if not candidates.get(table.name):
            continue
        for fk in table.foreign_keys:
            if fk.parent.nullable and candidates.get(fk.column.table.name):
                await db.execute(update(table).where(table.c.id.in_(candidates[table.name]),
                    fk.parent.in_(candidates[fk.column.table.name])).values({fk.parent.name: None}))
    pending = {name: ids for name, ids in candidates.items() if ids}
    while pending:
        progress = False
        for name, ids in list(pending.items()):
            blocked = False
            for table in Base.metadata.tables.values():
                for fk in table.foreign_keys:
                    if fk.column.table.name == name and pending.get(table.name):
                        if await db.scalar(select(table.c.id).where(table.c.id.in_(pending[table.name]), fk.parent.in_(ids)).limit(1)):
                            blocked = True
            if not blocked:
                await db.execute(delete(Base.metadata.tables[name]).where(Base.metadata.tables[name].c.id.in_(ids)))
                del pending[name]
                progress = True
        if not progress:
            raise RuntimeError('Non-null seed reference cycle; transaction rolled back, no records deleted.')
    if manifest:
        await db.delete(manifest)
    await db.flush()
    db.expire_all()
    return {name: len(original[name] - candidates[name]) for name in original if original[name] - candidates[name]}


class SeedWriter:
    def __init__(self, db):
        self.db = db
        self.records = {}
        self.created = set()
        self.borrowed = {}

    async def add(self, model, key, **values):
        identity = seed_id(model.__tablename__, key)
        row = await self.db.get(model, identity)
        if row is None:
            row = model(id=identity, **values)
            self.db.add(row)
            await self.db.flush()
            self.created.add(identity)
        self.records.setdefault(model.__tablename__, []).append(str(identity))
        return row

    async def save(self):
        row, prior = await load_manifest(self.db)
        records = {name: sorted(set(prior.get(name, []) + self.records.get(name, []))) for name in set(prior) | set(self.records)}
        if row is None:
            row = AuditLog(id=MANIFEST_ID, entity_type='seed_dataset', entity_id=MANIFEST_ID, action='go360_seed')
            self.db.add(row)
        row.after_value = {'dataset': 'go360-screenshot-v1', 'records': records, 'borrowed': self.borrowed}
        await self.db.flush()
        return {name: len(ids) for name, ids in records.items()}


async def snapshot_unowned(db):
    """Keep an in-memory baseline so the transaction can prove it preserved other data."""
    _, owned = await load_manifest(db)
    legacy = json.loads((Path(__file__).parent / 'legacy_inventory.json').read_text())
    baseline = {}
    for table in Base.metadata.tables.values():
        ignored = {uuid.UUID(x) for x in owned.get(table.name, []) + legacy.get(table.name, [])}
        if table.name == 'audit_logs':
            ignored.add(MANIFEST_ID)
        query = select(table)
        if ignored:
            query = query.where(table.c.id.not_in(ignored))
        baseline[table.name] = {row['id']: dict(row) for row in (await db.execute(query)).mappings()}
    return baseline


async def assert_preserved(db, baseline, allow_taxonomy_labels=False):
    for name, rows in baseline.items():
        if not rows:
            continue
        table = Base.metadata.tables[name]
        current = {row['id']: dict(row) for row in (await db.execute(select(table).where(table.c.id.in_(rows)))).mappings()}
        for identity, before in rows.items():
            after = current.get(identity)
            if after is None:
                raise RuntimeError(f'Reset would delete non-seed {name}/{identity}; rolling back.')
            for column, value in before.items():
                if allow_taxonomy_labels and name in {'main_categories', 'sub_categories'} and column in {'name', 'updated_at'}:
                    continue
                if after[column] != value:
                    raise RuntimeError(f'Seed would change non-seed {name}/{identity}/{column}; rolling back.')
