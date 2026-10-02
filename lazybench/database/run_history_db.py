import sqlalchemy
import pathlib
from sqlalchemy.orm import Session, DeclarativeBase, Mapped, mapped_column, relationship
from typing import Optional, Union
from lazybench.database.db_inspector import FluentBase, RunHistoryBase
from lazybench.database.instrument_db import InstrumentDBEntry

class RunHistory(RunHistoryBase):
    __tablename__ = 'run_history'
    session_id: Mapped[str] = mapped_column(primary_key=True)
    session_start_time: Mapped[float]
    # None until SessionLogger.stop() runs -- the row is created at session
    # START (session_id, a timestamp, IS the thing worth recording early).
    session_stop_time: Mapped[Optional[float]]
    instrument_entries: Mapped[list[InstrumentDBEntry]] = relationship(
        back_populates='session', cascade='all, delete-orphan', lazy='selectin',
    )
    log_entries: Mapped[list['LogEntry']] = relationship(
        back_populates='session', cascade='all, delete-orphan', lazy='selectin',
    )
    tree_log: Mapped[list['DagTreeLog']] = relationship(
        back_populates='session', cascade='all, delete-orphan', lazy='selectin',
    )


class LogEntry(RunHistoryBase):
    __tablename__ = 'log_entry'
    idx: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(sqlalchemy.ForeignKey('run_history.session_id'))
    timestamp: Mapped[float]
    level: Mapped[str]
    logger_name: Mapped[str]
    message: Mapped[str]
    session: Mapped['RunHistory'] = relationship(back_populates='log_entries', lazy='selectin')


class DagTreeLog(RunHistoryBase):
    __tablename__ = 'dag_tree_log'
    idx: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(sqlalchemy.ForeignKey('run_history.session_id'))
    timestamp: Mapped[float]
    tree: Mapped[str]
    session: Mapped['RunHistory'] = relationship(back_populates='tree_log', lazy='selectin')
