import pathlib
import time
from typing import Optional


def find_root()-> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for parent in [*here.parents]:
        if 'lazybench' not in str(parent):
            return parent / 'lazybench'
    raise FileNotFoundError(f'Did not find monorepo. Last one {parent}')

_ROOT = find_root()
_CONFIG_DIR = _ROOT / 'config'

def check_attr_compatible(name):
    if name[0].isnumeric():
        return False
    if any(n.isalnum() for n in name):
        return False

def force_attr_compatible(name):
    name = name.strip('\x00')
    return ''.join(c if (c.isalnum() or c == '_') else '_' for c in name)

def format_epoch(value: Optional[float], fmt: str = '%Y%m%d-%H%M%S') -> str:
    """Epoch float -> human string, matching SessionLogger's session_id
    format family. None-safe (e.g. RunHistory.session_stop_time before
    SessionLogger.stop() runs)."""
    if value is None:
        return 'None'
    return time.strftime(fmt, time.localtime(value)) + f'.{int((value % 1) * 1000):03d}'

def make_db_browser(nodespec):
    from lazybench.database.browse import browse, browse_session
    from lazybench.core.node import RootNode
    from lazybench.core.callable import CallableNode
    if hasattr(make_db_browser, 'run_once_already'):
        return
    setattr(make_db_browser, 'run_once_already', True)
    parent_node = RootNode.find_node(nodespec.unique_path[:-1])

    def browse_history():
        return browse(_CONFIG_DIR / 'run_history.db', schema='RunHistoryBase')

    def browse_known_instruments():
        return browse(_CONFIG_DIR / 'known_instruments.db', schema='InstrumentConfigBase')

    def browse_session_node():
        return browse_session(_CONFIG_DIR / 'run_history.db')

    for fn, name in (
        (browse_history, 'browse_history'),
        (browse_known_instruments, 'browse_known_instruments'),
        (browse_session_node, 'browse_session'),
    ):
        parent_node.install(CallableNode(fn, name=name))



