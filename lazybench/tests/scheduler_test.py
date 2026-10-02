import time

import pytest
from lazybench.core.violations import RuleViolation, ValidityViolation
from lazybench.tasks.scheduler import Scheduler, TaskNode
from lazybench.core.callable import CallableNode
from lazybench.core.invokable import Invokable
from lazybench.app.ux.prompter import CannedPrompter, Prompter

def add_one(count: int):
    count += 1 
    return count

def make_counter():
    count = 0
    def _add_one():
        nonlocal count
        count += 1
        return count
    return _add_one
    
NAME_CLASSES = {'CallableNode': CallableNode, 'TaskNode': TaskNode}

@pytest.mark.parametrize('use_class', NAME_CLASSES.keys())
def test_callable_node_with_normal_function(root_node, restore_prompter, use_class):
    cb = NAME_CLASSES[use_class](add_one)
    if hasattr(cb, 'period'): cb.period = 0.5
    assert isinstance(cb.fn, Invokable)
    assert (cb.dagnode_name == 'add_one')

    cb1 = NAME_CLASSES[use_class](add_one, 'not_add_one')
    if hasattr(cb1, 'period'): cb1.period = 0.5
    assert isinstance(cb1.fn, Invokable)
    assert (cb1.dagnode_name == 'not_add_one')

    root_node.install(cb)
    root_node.install(cb1)

    cb.set_trying_to_be_active()
    cb1.set_trying_to_be_active()

    Prompter.log(cb.dependency_active_states)
    Prompter.log(cb._trying_to_be_active)
    
    canned = CannedPrompter(text=["1"])
    Prompter.set(canned)
    assert cb() == 2

    canned = CannedPrompter(text=["1"])
    Prompter.set(canned)
    assert cb1() == 2

def test_task_node_raises_if_no_period(root_node):
    cb = TaskNode(make_counter())
    with pytest.raises(ValidityViolation, match='not alive'):
        root_node.install(cb)

    # Installation goes through regardless
    assert cb.dagnode_path in root_node.keys()
    with pytest.raises(ValidityViolation, match='not alive'):
        cb.start()

    cb.set_period(0.5)
    cb.start()
    assert cb.is_active
    
def test_callable_node_with_nonlocal_var(root_node, restore_prompter):
    cb = CallableNode(make_counter())
    assert isinstance(cb.fn, Invokable)

    root_node.install(cb)
    
    assert cb() == 1
    assert cb() == 2 

class PollableCounter:
    """Unlike make_counter's closure, exposes .value for polling without
    incrementing it -- lets a test observe the scheduler's own ticks
    instead of driving them itself by calling the task directly."""
    def __init__(self):
        self.value = 0

    def tick(self):
        self.value += 1
        return self.value


def _wait_until(predicate, timeout=1.0, interval=0.04):
    """Poll instead of sleeping a fixed duration -- avoids tying a test's
    pass/fail to exact wall-clock timing against a real background thread."""
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(interval)
    return predicate()


def test_scheduler_ticks_task(root_node):
    state = PollableCounter()
    scheduler = Scheduler()
    root_node.install(scheduler)
    cb = TaskNode(state.tick, period=0.02)
    scheduler.install(cb)
    cb.start()

    assert _wait_until(lambda: state.value >= 3, timeout=0.5)


def test_scheduler_stop_prevents_further_ticks(root_node):
    state = PollableCounter()
    scheduler = Scheduler()
    root_node.install(scheduler)
    cb = TaskNode(state.tick, period=0.02)
    scheduler.install(cb)
    cb.start()

    assert _wait_until(lambda: state.value >= 2, timeout=0.5)

    scheduler.stop()
    assert not scheduler.is_active

    count_at_stop = state.value
    time.sleep(0.1)
    assert state.value == count_at_stop


def test_scheduler_resume_after_pause_resumes_ticking(root_node):
    state = PollableCounter()
    scheduler = Scheduler()
    root_node.install(scheduler)
    cb = TaskNode(state.tick, period=0.02)
    scheduler.install(cb)
    cb.start()

    assert _wait_until(lambda: state.value >= 2, timeout=1.0)

    scheduler.stop()
    paused_count = state.value

    assert scheduler._thread is None

    scheduler.start()
    assert scheduler._thread.is_alive()
    assert _wait_until(lambda: state.value > paused_count, timeout=1.0)


def test_scheduler_install_with_period_none_succeeds_but_task_never_activates(root_node):
    state = PollableCounter()
    scheduler = Scheduler()
    root_node.install(scheduler)
    cb = TaskNode(state.tick)

    with pytest.raises(ValidityViolation, match='no set period'):
        scheduler.install(cb)

    assert cb.dagnode_path not in scheduler.keys()
    assert not cb.is_alive

    with pytest.raises(ValidityViolation, match='not alive'):
        cb.start()

    cb.set_period(0.1)
    scheduler.install(cb)
    assert cb.dagnode_path in scheduler.keys()
    assert cb.is_alive
    cb.start()
    assert _wait_until(lambda: state.value >= 9, timeout=1.0)


def test_scheduler_installed_into_tree_autostarts_with_zero_tasks(root_node):
    scheduler = Scheduler()
    root_node.install(scheduler)

    assert scheduler.is_active
    assert list(scheduler.values()) == []


def test_scheduler_task_raising_non_rule_violation_kills_thread_silently(root_node):
    def broken():
        raise RuntimeError('boom')


    counter = PollableCounter()
    scheduler = Scheduler()
    root_node.install(scheduler)
    broken_cb = TaskNode(broken, period=0.02)
    ok_task = TaskNode(counter.tick, period=0.01)
    scheduler.install(broken_cb)
    scheduler.install(ok_task)
    ok_task.start()
    broken_cb.start()

    assert _wait_until(lambda: not broken_cb.is_active, timeout=1.0)
    assert _wait_until(lambda: counter.value > 9, timeout = 1.0)


def test_scheduler_task_raising_rule_violation_is_skipped_not_fatal(root_node):
    good = PollableCounter()

    def bad():
        raise RuleViolation('nope')

    scheduler = Scheduler()
    root_node.install(scheduler)
    bad_cb = TaskNode(bad, period=0.02)
    good_cb = TaskNode(good.tick, period=0.02)
    scheduler.install(bad_cb)
    scheduler.install(good_cb)
    bad_cb.start()
    good_cb.start()

    assert _wait_until(lambda: good.value >= 2, timeout=1.0)
    assert scheduler.is_active


def test_scheduler_runs_two_tasks_with_different_periods(root_node):
    fast = PollableCounter()
    slow = PollableCounter()

    scheduler = Scheduler()
    root_node.install(scheduler)
    # Explicit names: both .tick methods otherwise share __name__ == 'tick',
    # and TaskNode defaults its dagnode_name to that -- second install
    # collides on the sibling-uniqueness check.
    fast_cb = TaskNode(fast.tick, name='fast_tick', period=0.01)
    slow_cb = TaskNode(slow.tick, name='slow_tick', period=0.08)
    scheduler.install(fast_cb)
    scheduler.install(slow_cb)
    fast_cb.start()
    slow_cb.start()

    assert _wait_until(lambda: slow.value >= 2, timeout=1.5)
    # Fast task shares the same window on an 8x shorter period -- should be
    # well ahead, not just "also nonzero".
    assert fast.value > slow.value

    



    
