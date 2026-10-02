from __future__ import annotations
from typing import TypeVar, Generic, Callable, Optional, Union
from prompt_toolkit.application import Application
import dataclasses

@dataclasses.dataclass
class UIState:
    focused: Optional['Tile'] = None
    hovered: Optional['Tile'] = None
    dragged: Optional['HitBox'] = None

# Using custom global getter instead of builtin get_app() for unified coordinator access interface
class TerminalApp:
    _singleton: Optional[Application]

    def __init__(self, instance):
        if type(self)._singleton is None:
            type(self)._singleton = instance

    @classmethod
    def get(cls):
        return cls._singleton

    @classmethod
    def get_layout(cls):
        app = cls.get()
        if app is not None and hasattr(app, 'layout'):
            return app.layout
        else:
            raise AttributeError('Terminal Application not initialized property')
