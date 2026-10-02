"""Generalized DB browser -- auto-detects every registered schema (a direct
DeclarativeBase subclass, e.g. RunHistoryBase/InstrumentConfigBase) instead
of hardcoding one browse_<schema> function per schema.
"""
import pathlib
from typing import Optional

import sqlalchemy
from sqlalchemy.orm import DeclarativeBase, Session

from lazybench.database import instrument_db  # noqa: F401
from lazybench.database import run_history_db  # noqa: F401
from lazybench.database.db_inspector import Row, SQLWriter
from lazybench.database.run_history_db import RunHistory
from lazybench.app.ux.prompter import Prompter
from lazybench.app.ux.prompter import InquirerPrompter
from lazybench.util import format_epoch


def _discover_roots() -> dict:
    """Every direct DeclarativeBase subclass currently registered -- one per
    schema group. Only sees schemas whose module has actually been imported
    (see the module-level imports above)."""
    return {cls.__name__: cls for cls in DeclarativeBase.__subclasses__()}


def _is_pure_link_table(mapper) -> bool:
    """True for a table that's nothing but foreign keys forming its primary
    key (e.g. a session<->instrument association) -- no content of its own,
    so it's not worth surfacing as a top-level browsable table. A table with
    even one non-FK column (e.g. instrument_alias.alias) is real content."""
    return bool(mapper.columns) and all(
        col.foreign_keys for col in mapper.columns
    )


def _content_table_names(root_cls) -> list:
    return [
        mapper.local_table.name
        for mapper in root_cls.registry.mappers
        if not _is_pure_link_table(mapper)
    ]


def browse(path: pathlib.Path, schema: Optional[str] = None):
    Prompter.set(InquirerPrompter())
    roots = _discover_roots()
    with SQLWriter(path) as sqlw:
        root_name = schema or Prompter.select('Schema:', list(roots.keys()))
        root_cls = roots[root_name]
        sqlw.add_schema('everything', root_cls)
        db_schema = sqlw.schema('everything')
        table_name = Prompter.select('Table:', _content_table_names(root_cls) + [root_name])
        if table_name == root_name:
            return db_schema
        table = db_schema.table(table_name)
        pk = Prompter.select('Row:', table.primary_keys())
        return table.row(pk)


## ========================= Session-scoped browser =========================
# Guided walk: session -> relationship -> row, filtered by session_id instead
# of enumerating the raw (globally-indexed) tables by hand. Discovers
# relationship_pks structurally off RunHistory's relationships, so a new
# child table appears with zero changes here.

class _AllAsDict:
    def __repr__(self) -> str:
        return '<< ALL as dict >>'


class _AllAsList:
    def __repr__(self) -> str:
        return '<< ALL as list >>'


_ALL_AS_DICT = _AllAsDict()
_ALL_AS_LIST = _AllAsList()


def _relationship_pks() -> dict:
    """{relationship_key: (child_class, fk_attr_name)} for every *-to-many
    relationship on RunHistory."""
    mapper = sqlalchemy.inspect(RunHistory)
    relationship_pks = {}
    for rel in mapper.relationships:
        if not rel.uselist:
            continue
        _, remote_col = rel.local_remote_pairs[0]
        relationship_pks[rel.key] = (rel.mapper.class_, remote_col.name)
    return relationship_pks


def _nestable_relationships(obj) -> dict:
    """One-level-only descend targets: collection relationships that don't
    point back at RunHistory (we already know the session)."""
    mapper = sqlalchemy.inspect(type(obj)).mapper
    return {
        rel.key: rel.key
        for rel in mapper.relationships
        if rel.uselist and rel.mapper.class_ is not RunHistory
    }


def _session_choices(engine) -> dict:
    relationship_pks = _relationship_pks()
    with Session(engine) as session:
        rows = session.execute(
            sqlalchemy.select(
                RunHistory.session_id,
                RunHistory.session_start_time,
                RunHistory.session_stop_time,
            ).order_by(RunHistory.session_id.desc()),
        ).all()
        counts = {}
        for key, (child_cls, fk_attr) in relationship_pks.items():
            fk_col = getattr(child_cls, fk_attr)
            counts[key] = dict(session.execute(
                sqlalchemy.select(fk_col, sqlalchemy.func.count()).group_by(fk_col),
            ).all())

    choices = {}
    for session_id, start, stop in rows:
        duration = f'{stop - start:.1f}s' if stop is not None else 'running'
        summary = ', '.join(
            f'{counts[key].get(session_id, 0)} {key}' for key in relationship_pks
        )
        choices[f'{session_id}  {duration}  {summary}'] = session_id
    return choices


def _fetch_session_rows(engine, child_cls, fk_attr, session_id) -> list:
    fk_col = getattr(child_cls, fk_attr)
    stmt = sqlalchemy.select(child_cls).where(fk_col == session_id)
    mapper = sqlalchemy.inspect(child_cls).mapper
    if 'timestamp' in mapper.columns.keys():
        stmt = stmt.order_by(getattr(child_cls, 'timestamp'))
    else:
        stmt = stmt.order_by(*mapper.primary_key)
    with Session(engine) as session:
        return list(session.scalars(stmt).all())


def _row_label(obj) -> str:
    mapper = sqlalchemy.inspect(obj).mapper
    pk_cols = {c.name for c in mapper.primary_key}
    session_fk_cols = {
        col.name for col in mapper.columns
        for fk in col.foreign_keys
        if fk.target_fullname == f'{RunHistory.__tablename__}.session_id'
    }
    has_timestamp = 'timestamp' in mapper.columns.keys()
    key = format_epoch(obj.timestamp) if has_timestamp else str(obj.get_primary_key())
    excluded = pk_cols | session_fk_cols | ({'timestamp'} if has_timestamp else set())
    data = ', '.join(
        f'{c}={getattr(obj, c)!r}' for c in mapper.columns.keys() if c not in excluded
    )
    if len(data) > 100:
        data = data[:97] + '...'
    return f'{key}: {data}'


def _row_choices(objs: list) -> dict:
    choices = {}
    for obj in objs:
        label = _row_label(obj)
        if label in choices:
            label = f'{label} #{obj.get_primary_key()}'
        choices[label] = obj
    return choices


def _select_row(objs: list):
    row_choices = _row_choices(objs)
    full_choices = {
        '<< ALL as dict >>': _ALL_AS_DICT,
        '<< ALL as list >>': _ALL_AS_LIST,
        **row_choices,
    }
    return Prompter.select('Row:', full_choices), row_choices


def _finalize(engine, obj):
    nestable = _nestable_relationships(obj)
    if not nestable:
        return Row(engine, type(obj), obj.get_primary_key())

    descend_choices = {'<< this row >>': None, **{k: k for k in nestable}}
    choice = Prompter.select('Descend:', descend_choices)
    if choice is None:
        return Row(engine, type(obj), obj.get_primary_key())

    selection, row_choices = _select_row(list(getattr(obj, choice)))
    if selection is _ALL_AS_DICT:
        return row_choices
    if selection is _ALL_AS_LIST:
        return list(row_choices.values())
    return Row(engine, type(selection), selection.get_primary_key())


def browse_session(path: pathlib.Path):
    """Guided walk: session -> relationship -> row.

    Returns a live Row for a single selection (matches browse()'s Row
    return), or a detached snapshot -- dict keyed by row label, or a plain
    list -- for the '<< ALL >>' escape hatches. One level of relationship
    nesting past the chosen relationship (e.g. instrument_entries ->
    alias_relationship); no deeper.
    """
    Prompter.set(InquirerPrompter())
    with SQLWriter(path) as sqlw:
        session_id = Prompter.select('Session:', _session_choices(sqlw.engine))

        relationship_pks = _relationship_pks()
        relationship_key = Prompter.select('Relationship:', list(relationship_pks.keys()))
        child_cls, fk_attr = relationship_pks[relationship_key]

        objs = _fetch_session_rows(sqlw.engine, child_cls, fk_attr, session_id)
        selection, row_choices = _select_row(objs)
        if selection is _ALL_AS_DICT:
            return row_choices
        if selection is _ALL_AS_LIST:
            return list(row_choices.values())

        return _finalize(sqlw.engine, selection)
