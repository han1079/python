import sqlalchemy
from sqlalchemy.ext.associationproxy import association_proxy
import pathlib
from sqlalchemy.orm import Mapped, mapped_column, relationship
from lazybench.database.db_inspector import SQLWriter
from lazybench.database.db_inspector import InstrumentConfigBase, RunHistoryBase
from lazybench.app.ux.prompter import Prompter

## ========================= Instrument Config Writer ====================================

class IdnMatch(InstrumentConfigBase):
    __tablename__ = 'idn_match'
    idx: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[str] = mapped_column(sqlalchemy.ForeignKey('instrument_config.model_id'))
    value: Mapped[str]
        
class InstrumentConfig(InstrumentConfigBase):
    __tablename__ = 'instrument_config'
    model_id: Mapped[str] = mapped_column(primary_key=True)
    module_path: Mapped[str]
    vendor_id: Mapped[int]
    product_id: Mapped[int]
    driver_class: Mapped[str]
    idn_match_relationship: Mapped[list[IdnMatch]] = relationship(
        cascade='all, delete-orphan', lazy='selectin',
    )
    idn_match = association_proxy('idn_match_relationship', 'value', creator=lambda value: IdnMatch(value=value))

def write_instrument_config(path: pathlib.Path, data):
    with SQLWriter(path) as sqlw:
        try:
            sqlw.add_table_type('instrument_config', InstrumentConfig)
            sqlw.add_table_type('idn_match', IdnMatch)
        except Exception:
            pass
        sqlw.get_table_type('instrument_config').create_all()
        instrument_table = sqlw.get_table_type('instrument_config').table('instrument_config')
        inst_data = InstrumentConfig(**data)
        instrument_table.insert(inst_data)

## ========================= Instrument Entry Writer ====================================
# InstrumentDBEntry is a per-session SNAPSHOT of an observed instrument, not a
# row shared across sessions: the same physical unit (same `serial`) gets a
# fresh row every session it's seen in, because everything but the serial
# itself (ip_addr, canonical_name/sticker) is genuinely mutable session to
# session. It's owned outright by its session -- composite PK
# (session_id, serial) -- rather than referenced through a link table.

class InstrumentAlias(RunHistoryBase):
    __tablename__ = 'instrument_alias'
    idx: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column()
    serial: Mapped[str] = mapped_column()
    alias: Mapped[str]
    __table_args__ = (
        sqlalchemy.ForeignKeyConstraint(
            ['session_id', 'serial'],
            ['instrument_db_entry.session_id', 'instrument_db_entry.serial'],
        ),
    )
    entry: Mapped['InstrumentDBEntry'] = relationship(
        back_populates='alias_relationship', lazy='selectin',
    )


class InstrumentDBEntry(RunHistoryBase):
    __tablename__ = 'instrument_db_entry'
    session_id: Mapped[str] = mapped_column(
        sqlalchemy.ForeignKey('run_history.session_id'), primary_key=True,
    )
    serial: Mapped[str] = mapped_column(primary_key=True)
    model_id: Mapped[str]
    vendor_id: Mapped[int]
    product_id: Mapped[int]
    ip_addr: Mapped[str]
    canonical_name: Mapped[str]
    alias_relationship: Mapped[list[InstrumentAlias]] = relationship(
        back_populates='entry', cascade='all, delete-orphan', lazy='selectin',
    )
    aliases = association_proxy('alias_relationship', 'alias', creator=lambda alias: InstrumentAlias(alias=alias))

    # Reverse side of RunHistory.instrument_entries -- string forward-reference,
    # resolved via the shared registry at configure_mappers() time. Must stay
    # a string: instrument_db.py cannot import run_history_db.py
    # (run_history_db.py already imports this module, so an import here would
    # be circular).
    session: Mapped['RunHistory'] = relationship(
        back_populates='instrument_entries', lazy='selectin',
    )

def write_instrument_entry(path: pathlib.Path, data):
    with SQLWriter(path) as sqlw:
        try:
            sqlw.add_table_type('instrument_db_entry', InstrumentDBEntry)
            sqlw.add_table_type('instrument_alias', InstrumentAlias)
        except Exception:
            pass
        sqlw.get_table_type('instrument_db_entry').create_all()
        instrument_table = sqlw.get_table_type('instrument_db_entry').table('instrument_db_entry')
        inst_data = InstrumentDBEntry(**data)
        instrument_table.insert(inst_data)
