"""callable — wrap a callable as a DAGNode, and walk an object's public
callables into a batch of them.

CallableNode brings a bound method (or any callable) into the graph by
wrapping it around 'Invokable', which performs metadata binding, executor,
prompt injection, and signature introspection.
"""
import functools
import inspect
import logging
from typing import Callable, Optional, Union

from lazybench.core.invokable import Invokable
from lazybench.core.node import DAGNode
from lazybench.core.violations import ValidityViolation

logger = logging.getLogger(__name__)


class CallableNode(DAGNode):
    _reserved_attr_names: set = set()

    def __init__(self, fn: Optional[Callable] = None,
                 name: Optional[str] = None,
                 resources: Optional[Union[str, frozenset['DAGNode'], 'DAGNode']] = None):
        self.fn: Optional[Invokable] = None
        self._bind_callable(fn)
        super().__init__(name=name or self.fn.name, resources=resources)

    def _bind_callable(self, fn: Optional[Callable]) -> None:
        if not callable(fn):
            raise ValidityViolation[self](f'{fn!r} is not callable. CallableNode needs a real callable.')
        self.fn = Invokable(fn)

    def __call__(self, *args: object, **kwargs: object) -> object:
        if not self.is_alive:
            raise ValidityViolation[self](
                f'{self._name} is not alive (never installed, or killed). Cannot invoke.'
            )
        if args or kwargs:
            return self.fn.execute_raw(*args, **kwargs)
        return self.fn.execute_bound()
    
    def _on_successful_install(self):
        return True
