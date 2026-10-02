import threading
import time
import logging
from typing import Optional, Callable, Union
from lazybench.core.violations import RuleViolation, ValidityViolation
from lazybench.core.node import Registry
from lazybench.core.callable import CallableNode
from lazybench.app.ux.prompter import Prompter

logger = logging.getLogger(__name__)

class TaskNode(CallableNode):
    def __init__(self, fn: Optional[Callable] = None,
                 name: Optional[str] = None,
                 resources: Optional[Union[str, frozenset['DAGNode'], 'DAGNode']] = None,
                 period: Optional[float] = None,
                 resources_keyword: str = 'resources'):
        self._resources_keyword = resources_keyword
        super().__init__(fn=fn, name=name, resources=resources)
        self.period = period
        self.run_at_time: Optional[float] = None
        self.last_start = time.monotonic()
        self.last_stop = time.monotonic()

    def _bind_callable(self, fn):
        super()._bind_callable(fn)
        if self._resources_keyword in {p.name for p in self.fn.params}:
            self.fn.bind(**{self._resources_keyword: self.resources})

    def set_period(self, period: Optional[float]):
        if period is None:
            return
        self.period = period

    @property
    def is_alive(self) -> bool:
        return self.period is not None and super().is_alive

    def __call__(self, *args: object, **kwargs: object) -> object:
        if not self.is_active:
            return

        return super().__call__(*args, **kwargs)

    def _schedule_next_run(self, now: float) -> None:
        if self.is_active:
            self.run_at_time = now + self.period

    def start(self):
        now = time.monotonic()
        if not self.is_active:
            self.set_trying_to_be_active()

        if self.is_active:
            self._schedule_next_run(now)
            self.last_start = now
            return (now, now - self.last_stop, True)
        else:
            return (now, now - self.last_start, False)

    def stop(self):
        now = time.monotonic()
        if self.is_active:
            self.deactivate_node()
            self.last_stop = now
            return (now, now - self.last_start, True)
        else:
            return (now, now - self.last_stop, False)

class Scheduler(Registry):
    DEFAULT_SLEEP = 1
    def __init__(self, name: Optional[str] = 'scheduler'):
        super().__init__(name=name, resources=None)
        self._thread : Optional[threading.Thread] = None
        self._wake = threading.Event()
        self._spawn_thread()

    def install(self, node: TaskNode, default_activate=False):
        if node.fn.currently_unbound != {}:
            raise ValidityViolation(f'{node.dagnode_name} has bound {node.fn.signature}. Not fully bound.')
        if node.period is None:
            raise ValidityViolation(f'{node.dagnode_name} has no set period. Cannot be scheduled')
        
        logging.debug(default_activate)
        install_flag = super().install(node, default_activate=default_activate)

        if default_activate and install_flag:
            logging.debug(node.start())
            logging.debug(node.run_at_time)

        return install_flag


    def _on_successful_install(self):
        self.start()

    # ── run loop ──
    def _next_delay(self) -> float:
        times = [t.run_at_time for t in self.values() if t.run_at_time is not None]
        return self.DEFAULT_SLEEP if not times else max(0.0, min(times) - time.monotonic())

    @property
    def is_active(self):
        if self._thread is None:
            return False

        return self._thread.is_alive() and super().is_active

    def _spawn_thread(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            return

        if not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        if self.is_active:
            return

        self._spawn_thread()
        self.set_trying_to_be_active()
        self._thread.start()
        self._wake.set()

    def deactivate_node(self):
        super().deactivate_node()
        if self._thread is not None:
            self._wake.set()
            self._thread.join(timeout=0.2)
            self._wake.clear()
            self._thread = None

    def kill_node(self):
        try:
            super().kill_node()
        finally:
            self._thread = None

    def stop(self):
        self._wake.clear()
        self.deactivate_node()

    def _run(self) -> None:
        dT = self._next_delay()
        while self.is_active:
            logger.info(self.values())
            self._wake.wait(dT)
            self._wake.clear()
            if not self._trying_to_be_active:
                break
            now = time.monotonic()
            for task in list(self.values()):            # snapshot — tasks may self-remove
                logger.info(f'Run at {task.run_at_time}, Active: {task.is_active}')
                if task.run_at_time is None or not task.is_active or task.run_at_time > now:
                    continue
                try:
                    task()                      # aliveness-gated
                except RuleViolation as e:
                    Prompter.log(f'{task.dagnode_name} skipped: {e}')
                    continue
                except Exception as e:
                    Prompter.log(f'{task.dagnode_name} ran into exception. Deactivating.: {e}')
                    task.stop()
                    continue
                task._schedule_next_run(now)
            dT = self._next_delay()

        
