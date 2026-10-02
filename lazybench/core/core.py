from functools import wraps
import datetime
from lazybench.app.ux.prompter import Prompter
from typing import TypeVar, Type, Optional, Callable
import inspect
import pdb
class MetaNode(type):
    """Metaclass for all DAGNodes. Forces each node to update a list of 'reserved names'.

        The aim of reserving names is so that each node can manipulate __getattr__
        __getattribute__ dunder methods so that nodes stored in dicts can look exactly 
        like normal class attributes WITHOUT overwriting or shadowing existing names.

        In conjunction with bespoke whitelists for specialized subclasses, this process
        eventually allows the user to easily create a new node, populate it with a 
        dictionary full of objects, callables, etc to create a namespace.

        The benefit is that such a namespace can respond to a dead node by removing it
        from the namespace - thus rendering the attribute LITERALLY inaccessible.
    """
    def __new__(mcs, name, bases, namespace):
        original_init = namespace.get('__init__')

        if original_init is None:
            if len(bases) == 0:
                raise AttributeError(f'{name} needs an __init__ function for metaclass consistency')

            # Set the init to the last parent that had one
            original_init = bases[0].__init__

        reserved_names = namespace.get('_reserved_attr_names')
        if reserved_names is None:
            if len(bases) == 0:
                namespace['_reserved_attr_names'] = set()
                reserved_names = namespace['_reserved_attr_names']
            else:
                reserved_names = set(bases[0]._reserved_attr_names)
                namespace['_reserved_attr_names'] = reserved_names

        if '_bootstrapped_meta' not in reserved_names:
            reserved_names.add('_bootstrapped_meta')

        def init_with_footer(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
                
            if hasattr(self, '_bootstrapped_meta') and self._bootstrapped_meta == True:
                return

            try:
                self._bootstrap_node()
                self._bootstrapped_meta = True
            except AttributeError as e:
                raise AttributeError(f'{type(self).__qualname__} may not be a valid DAGNode. Got: {e}')

        namespace['__init__'] = init_with_footer

        return super().__new__(mcs, name, bases, namespace)

def make_subclass(base, *, attr_name: str, default_factory: Optional[type], class_name):
    if not hasattr(base, '_reserved_attr_names'):
        raise AttributeError(f'{base.__name__} has no _reserved_attr_names')

    reserved = set()
    for cls in base.__mro__:
        reserved_attr_names = getattr(cls, '_reserved_attr_names', None)
        existing_class_vars = set(cls.__dict__.keys())
        reserved = reserved.union(existing_class_vars)
        if reserved_attr_names is not None:
            reserved = reserved.union(reserved_attr_names)

    if attr_name in reserved:
        raise AttributeError(f'Cannot override existing attribute {attr_name}')

    def new_init(self, *args, **kwargs):
        _kw_value_that_matches = kwargs.pop(attr_name, None)
        if _kw_value_that_matches is not None:
            setattr(self, attr_name, _kw_value_that_matches)
        else:
            if default_factory is None:
                setattr(self, attr_name, None)
            else:
                setattr(self, attr_name, default_factory())


        super(cls, self).__init__(*args, **kwargs)
    
    new_cls_namespace = {'__init__': new_init}
    cls = MetaNode(class_name, (base,), new_cls_namespace)
    cls._reserved_attr_names.add(attr_name)

    return cls
            
class MonitorMe:
    def __init__(self, fn=None, hook=None, verbose = True):

        if fn is None: 
            fn = lambda: None

        def wrapped(self, *args, **kwargs):
            result = fn(*args, **kwargs)
            exit_frame = inspect.currentframe().f_back
            self.exit_filename = exit_frame.f_code.co_filename
            self.exit_lineno = exit_frame.f_lineno
            if verbose:
                Prompter.log(self.exit_filename)
                Prompter.log(self.exit_lineno)
                Prompter.log(f'Hooked = {self.hook}')
            return result 

        self.hook = hook
        self.fn = wrapped(self)

    def __call__(self, *args, **kwargs):
        with self:
            res = self.fn(*args, *kwargs)

        return res

    def __enter__(self):
        self.start_time = datetime.datetime.now()
        entry_frame = inspect.currentframe().f_back
        self.lineno = entry_frame.f_lineno
        self.filename = entry_frame.f_code.co_filename

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.print_result()
        except Exception:
            pdb.post_mortem()

        if exc_type is not None:
            pdb.post_mortem()
            return

    def print_result(self):
        prefix = f'{self.filename}::{self.lineno}-{self.exit_lineno}  '
        timing = f'{datetime.datetime.now() - self.start_time}'
        Prompter.log(prefix + timing) 
