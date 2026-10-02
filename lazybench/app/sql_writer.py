import sqlalchemy
import pathlib
from sqlalchemy.orm import Session, DeclarativeBase, Mapped, mapped_column
from typing import Optional, Union


class Base(DeclarativeBase):
    def column_names(self):
        return sqlalchemy.inspect(self).mapper.columns.keys()

    def keys(self):
        return self.column_names()

    def get_primary_key(self):
        pk_cols = sqlalchemy.inspect(self).mapper.primary_key
        values = tuple(getattr(self, c.name) for c in pk_cols)
        return values[0] if len(values) == 1 else values

    def __getitem__(self, key):
        return getattr(self, key)

    def __repr__(self) -> str:
        return f'{type(self).__name__}({dict(self)})'




class Row:
    def __init__(self, engine, table_cls, primary_key):
        self.engine, self.table_cls, self.primary_key = engine, table_cls, primary_key

    def __repr__(self):
        return repr(self.read())

    def _get(self, session):
        return session.get(self.table_cls, self.primary_key)

    def read(self):
        with Session(self.engine) as session:
            return self._get(session)

    @property
    def column_names(self) -> list:
        return sqlalchemy.inspect(self.table_cls).columns.keys()

    def keys(self):
        return self.column_names

    def __getitem__(self, name):
        return getattr(self.read(), name)

    def __getattr__(self, name):
        return getattr(self.read(), name)

    def update(self, **fields):
        with Session(self.engine) as session:
            row = self._get(session)
            for k, v in fields.items():
                setattr(row, k, v)
            try:
                session.commit()
            except sqlalchemy.exc.IntegrityError as e:
                session.rollback()
                raise ValueError(f'Update failed: {e.orig}') from None
            return row

    def delete(self) -> None:
        with Session(self.engine) as session:
            row = self._get(session)
            session.delete(row)
            try:
                session.commit()
            except sqlalchemy.exc.IntegrityError as e:
                session.rollback()
                raise ValueError(f'Delete failed: {e.orig}') from None


class Column:
    def __init__(self, engine, table_cls, column):
        self.engine, self.table_cls, self.column = engine, table_cls, column
        self._sql_statement = sqlalchemy.select(column)

    def where(self, condition) -> 'Column':
        self._sql_statement = self._sql_statement.where(condition)
        return self

    def order_by(self, column_name) -> 'Column':
        self._sql_statement = self._sql_statement.order_by(column_name)
        return self

    def all(self) -> list:
        with Session(self.engine) as session:
            return session.scalars(self._sql_statement).all()

    def first(self):
        with Session(self.engine) as session:
            return session.scalars(self._sql_statement).first()

    def count(self) -> int:
        count_stmt = sqlalchemy.select(
            sqlalchemy.func.count(),
        ).select_from(self._sql_statement.subquery())
        with Session(self.engine) as session:
            return session.scalar(count_stmt)


class Table:
    def __init__(self, engine, table_cls: type):
        self.engine = engine
        self.table_cls = table_cls

    def row(self, primary_key) -> Row:
        return Row(self.engine, self.table_cls, primary_key)

    def column(self, column_name) -> Column:
        return Column(self.engine, self.table_cls, getattr(self.table_cls, column_name))

    def column_names(self) -> list:
        return sqlalchemy.inspect(self.table_cls).columns.keys()

    def primary_key_columns(self) -> list:
        return [c.name for c in sqlalchemy.inspect(self.table_cls).primary_key]

    def primary_keys(self) -> list:
        pk_cols = sqlalchemy.inspect(self.table_cls).primary_key
        with Session(self.engine) as session:
            return session.scalars(sqlalchemy.select(*pk_cols)).all()

    def rowids(self) -> list:
        with self.engine.connect() as conn:
            return conn.execute(
                sqlalchemy.text(f'SELECT rowid FROM {self.table_cls.__tablename__}'),
            ).scalars().all()

    def insert(self, row_data: Union[dict, object]) -> object:
        if isinstance(row_data, dict):
            row_data = self.table_cls(**row_data)
        with Session(self.engine) as session:
            session.add(row_data)
            try:
                session.commit()
            except sqlalchemy.exc.IntegrityError as e:
                session.rollback()
                raise ValueError(f'Insert failed: {e.orig}') from None
            return row_data


class Schema:
    def __init__(self, engine, root_cls: type[DeclarativeBase]):
        self.engine = engine
        self.root_cls = root_cls
        self._mappers_by_name = {
            mapper.local_table.name: mapper for mapper in root_cls.registry.mappers
        }

    def create_all(self) -> None:
        self.root_cls.metadata.create_all(self.engine)

    def create_table(self, name: str) -> Table:
        self.root_cls.metadata.tables[name].create(self.engine, checkfirst=True)
        return self.table(name)

    def table(self, name: str) -> Table:
        mapper = self._mappers_by_name.get(name)
        if mapper is None:
            raise KeyError(name)
        return Table(self.engine, mapper.class_)

    def table_names(self) -> list:
        return list(self._mappers_by_name.keys())

    def clear_table(self, name: str, *, confirm: bool = False) -> int:
        """Delete every row from `name`, leaving the table itself intact.

        Requires confirm=True so an accidental call can't silently wipe data.
        Returns the number of rows deleted.
        """
        if not confirm:
            raise ValueError(
                f'clear_table({name!r}) requires confirm=True to avoid '
                f'accidental data loss',
            )
        mapped_cls = self.table(name).table_cls
        with Session(self.engine) as session:
            deleted = session.query(mapped_cls).delete()
            session.commit()
            return deleted


class SQLWriter:
    def __init__(self, db_path: Optional[Union[str, pathlib.Path]]):
        self.db_path = pathlib.Path(db_path)
        self.engine = None
        self._started = False
        self._schemas = {}

    def start(self) -> 'SQLWriter':
        if self._started:
            return self
        self.engine = sqlalchemy.create_engine(f'sqlite:///{self.db_path}')
        self._started = True
        return self

    def stop(self) -> None:
        if not self._started:
            return

        if self.engine is not None:
            self.engine.dispose()
            self.engine = None

        self._started = False

    def __enter__(self) -> None:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    def add_schema(self, name, base):
        assert self._started, 'SQLWriter not started'
        self._schemas[name] = base
        return self

    def schema(self, name):
        assert self._started, 'SQLWriter not started'
        _schema = self._schemas.get(name)
        if _schema:
            return Schema(self.engine, _schema)

        raise KeyError(f'No schema named {name} registered')

    def schema_names(self) -> list:
        return list(self._schemas.keys())

    def add_table_type(self, name, base):
        return self.add_schema(name, base)
    def get_table_type(self, name):
        return self.schema(name)



