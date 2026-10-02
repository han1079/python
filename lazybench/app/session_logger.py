"""session_logger -- logging.Handler that owns the RunHistory SQLWriter and
tracks one session end-to-end: session-row creation, filtered log capture,
and periodic DAG topology snapshots.

session_id is a timestamp string (not a uuid) -- deliberately: what matters
for debugging a run later is WHEN it happened, not a unique-but-opaque token.
"""
import json
import logging
import sys
import time
import coloredlogs
from typing import Optional

from lazybench.app.hardware.scanner import RunHistoryDBWriter
from lazybench.core.node import RootNode
from lazybench.database import run_history_db  # noqa: F401

_PROMPTER_LOGGER_NAME = 'lazybench.prompter'
_OWN_PACKAGE_PREFIX = 'lazybench'


def snapshot_tree(root) -> str:
    """Depth-first collection of every dagnode_path under root, as a stable
    JSON string -- the unit record_tree_if_changed diffs against."""
    paths = []

    def _walk(node):
        paths.append(list(node.dagnode_path))
        for child in node.dagnode_children:
            _walk(child)

    _walk(root)
    return json.dumps(sorted(paths))

## ========================= Periodic tree snapshot (TaskNode: dag_tree_logger) =========================

def log_tree_if_changed(resources):
    resources.session_logger.record_tree_if_changed(snapshot_tree(RootNode.get()))

class _LiveStdout:
    def write(self, s): sys.stdout.write(s)
    def flush(self): sys.stdout.flush()

class ConsoleLogger:
    def __init__(self, level: int = logging.INFO):
        self._handler = logging.StreamHandler(_LiveStdout())
        self._handler.setLevel(level)

        # Log Format: Time, Level, File Name, Line Number, Message
        fmt = '%(asctime)s.%(msecs)03d [%(levelname).1s] %(filename)s@%(lineno)d: %(message)s'

        # Log Style: Make sure Level Name is white and bold
        fmtr_cls = coloredlogs.ColoredFormatter
        field_styles = coloredlogs.DEFAULT_FIELD_STYLES.copy()
        field_styles['levelname'] = {'color': 'white', 'bold': True}
        field_styles['filename'] = {'color': 'white', 'bold': True}
        field_styles['lineno'] = {'color': 'white', 'bold': True}

        # Custom Level for Prompter: Make sure it's formatted as cyan
        level_styles = coloredlogs.DEFAULT_LEVEL_STYLES.copy()
        level_styles['prompt'] = {'color': 'cyan'}
        self._handler.setFormatter(fmtr_cls(fmt=fmt, 
                                            datefmt='%y_%m_%d %H:%M:%S', 
                                            field_styles=field_styles,
                                            level_styles=level_styles))
        logging.getLogger().addHandler(self._handler)

class SessionLogger(logging.Handler):
    def __init__(
        self,
        own_level: int = logging.DEBUG,
        dependency_level: int = logging.WARNING,
    ):
        super().__init__(level=logging.NOTSET)
        self.own_level = own_level
        self.dependency_level = dependency_level

        # Kept started for the whole session (not the usual per-op `with`
        # idiom) -- scan_and_sync holds onto instrument_entry_table() across
        # scheduler ticks, so the writer can't tear its engine down between
        # calls the way a short-lived one-shot writer would.
        self._writer = RunHistoryDBWriter().start()
        now = time.time()
        self.session_id = time.strftime('%Y%m%d-%H%M%S', time.localtime(now)) + f'.{int((now % 1) * 1000):03d}'

        self._writer.schema('run_history').create_all()
        self._writer.schema('run_history').table('run_history').insert(dict(
            session_id=self.session_id,
            session_start_time=time.time(),
            session_stop_time=None,
        ))

        self.last_tree_snapshot: Optional[str] = None
        self.record_tree_if_changed(snapshot_tree(RootNode.get()))

        logging.getLogger().addHandler(self)
        logging.getLogger().setLevel(logging.DEBUG)

    def emit(self, record: logging.LogRecord) -> None:
        if record.name != _PROMPTER_LOGGER_NAME:
            is_own = (
                record.name == _OWN_PACKAGE_PREFIX
                or record.name.startswith(f'{_OWN_PACKAGE_PREFIX}.')
            )
            threshold = self.own_level if is_own else self.dependency_level
            if record.levelno < threshold:
                return

        try:
            self._writer.schema('run_history').table('log_entry').insert(dict(
                session_id=self.session_id,
                timestamp=record.created,
                level=record.levelname,
                logger_name=record.name,
                message=self.format(record),
            ))
        except Exception:
            # A logging handler must never raise -- a DB hiccup here should
            # not take down whatever code triggered the log call.
            print(e, file=sys.stderr)
            pass

    def record_tree_if_changed(self, tree_json: str) -> bool:
        if tree_json == self.last_tree_snapshot:
            return False
        self._writer.schema('run_history').table('dag_tree_log').insert(dict(
            session_id=self.session_id,
            timestamp=time.time(),
            tree=tree_json,
        ))
        self.last_tree_snapshot = tree_json
        return True

    def previous_session_entries(self) -> list:
        """Every InstrumentDBEntry recorded by the most recent OTHER session,
        for bootstrap_from_previous_session's targeted recheck."""
        history_table = self._writer.schema('run_history').table('run_history')
        other_sessions = [
            sid for sid in history_table.primary_keys() if sid != self.session_id
        ]
        if not other_sessions:
            return []
        latest = max(
            other_sessions,
            key=lambda sid: history_table.row(sid).session_start_time,
        )
        return list(history_table.row(latest).instrument_entries)

    def instrument_entry_table(self):
        """Table handle for instrument_db_entry, scoped to this session's
        writer -- scan_and_sync's idempotent upsert reads/writes through
        this rather than reaching into the writer's internals directly."""
        return self._writer.schema('run_history').table('instrument_db_entry')

    def stop(self) -> None:
        # Idempotent -- session_logger's resource edge to connector_router
        # makes it a *dependent* of connector_router too (DAGNode.install
        # wires both directions), so DAGNode.kill_node's recursive dependent
        # walk invokes this node's kill_node -- and therefore this stop() --
        # via two separate incoming edges during root teardown. Matches
        # SQLWriter.stop()'s own already-stopped-is-a-no-op idiom.
        if not self._writer._started:
            return
        try:
            self._writer.schema('run_history').table('run_history').row(self.session_id).update(
                session_stop_time=time.time(),
            )
        finally:
            logging.getLogger().removeHandler(self)
            self._writer.stop()
