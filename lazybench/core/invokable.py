from typing import Callable, Optional
from functools import wraps
import dataclasses
from dataclasses import field
import typing
import inspect
from lazybench.core.typewalker import prompt_for_type
from lazybench.core.violations import RuleViolation
from lazybench.app.ux.prompter import Prompter, OperatorCancelled

# Forward Declaration
class Invokable: pass
InvokableViolation = RuleViolation[Invokable]

@dataclasses.dataclass(eq=False)
class InvokableParam:
    name: str
    typehint: object
    param_kind: inspect._ParameterKind
    default: object = field(default=inspect.Parameter.empty)
    value: object = field(default=inspect.Parameter.empty)
    
    @property
    def populated(self, use_dict: bool = False):
        if self.value != inspect.Parameter.empty:
            used_value = self.value 
        else:
            used_value = self.default

        if use_dict:
            return {'name': self.name,
                    'typehint': self.typehint,
                    'value': used_value,
                    'kind': self.param_kind}
        else:
            return (self.name, self.typehint, used_value, self.param_kind)

    def bind(self, value: object):
        self.value = value

    def get_value(self, allow_user_prompt=True):
        if self.value != inspect.Parameter.empty:
            return self.value

        if self.default != inspect.Parameter.empty:
            return self.default
            
        if allow_user_prompt:
            try:
                return prompt_for_type(self.typehint)
            except OperatorCancelled:
                Prompter.log(f"Operator Cancelled")
                return inspect.Parameter.empty

        return inspect.Parameter.empty


class Invokable:
    def __init__(self, fcn: Callable):
        self.name: Optional[str] = None
        self.qualname: Optional[str] = None
        self.fcn: Optional[Callable] = fcn
        self.params: tuple[InvokableParam] = ()
        self.bound_kwargs: dict = {}
        self.bound_args: tuple = ()

        self._positional_slots: tuple = ()
        self._positional_only_names: tuple = ()
        self._keyword_addressable: dict = {}
        self._var_kw = None
        self._var_pos = None
        self.extract_params()

    @property
    def currently_unbound(self):
        return {p.name: p.typehint for p in self.params 
                if p.get_value(allow_user_prompt=False) == inspect.Parameter.empty and 
                p.param_kind not in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL)}

    def extract_params(self):
        self.name = getattr(self.fcn, '__name__')
        self.qualname = getattr(self.fcn, '__qualname__')

        try:
            type_hints = typing.get_type_hints(self.fcn)
        except Exception as e:
            type_hints = {}

        try:
            sig = inspect.signature(self.fcn)
        except (TypeError, ValueError):
            raise AttributeError(f"Not an inspectable function")

        for s in sig.parameters.values():
            typehint = type_hints.get(s.name)
            if typehint is None:
                if s.annotation is inspect.Parameter.empty:
                    typehint = inspect.Parameter.empty
                else:
                    typehint = s.annotation

            p = InvokableParam(name=s.name,
                         typehint=typehint,
                         default=s.default,
                         param_kind=s.kind)

            self.params += (p,)

        self._positional_slots = tuple((p for p in self.params if p.param_kind in
                                  (inspect.Parameter.POSITIONAL_ONLY,
                                   inspect.Parameter.POSITIONAL_OR_KEYWORD)))

        self._keyword_addressable = {p.name: p for p in self.params if p.param_kind in
                                  (inspect.Parameter.KEYWORD_ONLY,
                                   inspect.Parameter.POSITIONAL_OR_KEYWORD)}

        self._positional_only_names = tuple((p.name for p in self.params if p.param_kind == inspect.Parameter.POSITIONAL_ONLY))
        self._var_pos = next((p for p in self.params if p.param_kind == inspect.Parameter.VAR_POSITIONAL), None)
        self._var_kw = next((p for p in self.params if p.param_kind == inspect.Parameter.VAR_KEYWORD), None)

    def execute_raw(self, *args, **kwargs):
        if self.fcn is None:
            raise AttributeError(f'No function bound.')
        return self.fcn(*args, **kwargs)

    def _assemble(self):
        allowed_types = [inspect.Parameter.POSITIONAL_ONLY,
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        inspect.Parameter.VAR_POSITIONAL,
                        inspect.Parameter.KEYWORD_ONLY,
                        inspect.Parameter.VAR_KEYWORD]
        chopping_block = allowed_types[0]
        allowed_types = allowed_types[1:]
        forbidden_types = []
        positional_args = ()
        kw_args = {}
        #Prompter.log(", ".join([f'{p.name}' for p in self.params]))
        for i in range(len(self.params)):
            _kind = self.params[i].param_kind

            while _kind != chopping_block:
                if _kind in forbidden_types:
                    raise TypeError(f'Ordering of parameters disallowed.')
                forbidden_types.append(chopping_block)
                chopping_block = allowed_types[0]
                allowed_types = allowed_types[1:]
                if chopping_block is None:
                    raise IndexError(f"Out of types somehow")

            if _kind == chopping_block:
                if _kind == inspect.Parameter.POSITIONAL_ONLY:
                    positional_args += (self.params[i].get_value(),)

                elif _kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
                    positional_args += (self.params[i].get_value(),)

                elif _kind == inspect.Parameter.VAR_POSITIONAL:
                    positional_args += self.bound_args

                elif _kind == inspect.Parameter.KEYWORD_ONLY:
                    kw_args[self.params[i].name] = self.params[i].get_value()

                elif _kind == inspect.Parameter.VAR_KEYWORD:
                    for k, v in self.bound_kwargs.items():
                        if k not in kw_args:
                            kw_args[k] = v


        if any(a == inspect.Parameter.empty for a in positional_args + tuple(kw_args.values())):
                raise Exception(f"Arguments not filled. Cannot call.")
        return positional_args, kw_args

    def execute_bound(self):
        if self.fcn is None:
            raise AttributeError(f'No function bound.')

        args, kwargs = self._assemble()
        return self.fcn(*args, **kwargs)
            

    def _stage_bind(self, *args, **kwargs):
        positional_cache = {}
        positional_overflow = ()
        kw_cache = {}
        kw_overflow = {}

        for i in range(len(args)):
            if i < len(self._positional_slots):
                name_at_position = self._positional_slots[i].name
                positional_cache[name_at_position] = {'idx': i, 'value': args[i]}
            else:
                if self._var_pos is not None:
                    positional_overflow += (args[i],)
                else:
                    raise InvokableViolation[self](f"Tried to write index[{i}] position. No VARPOS and only {len(self._positional_slots)} slots available.")

        # If you didn't touch either overflow or normal args, just return the existing 
        # overflow, if it exists
        if len(positional_cache.keys()) == 0 and len(positional_overflow) == 0:
            positional_overflow = self.bound_args

        for k, v in kwargs.items():
            if k in self._positional_only_names: # Negative Check
                    raise InvokableViolation[self](f"Cannot fill keyword arg in {k}. Positional Only")

            if k in self._keyword_addressable: # Positive Check (exactly 'varkw' gets punted)
                if k in positional_cache.keys():
                    raise InvokableViolation[self](f"Cannot fill arg named {k}. {k} already filled with {positional_cache[k]['value']}")
                kw_cache[k] = v
            else:
                if self._var_kw is not None:
                    kw_overflow[k] = v
                else:
                    raise InvokableViolation[self](f"No VARKW and no argument matching keyword: {k}")

        return positional_cache, positional_overflow, kw_cache, kw_overflow

    def bind(self, *args, **kwargs):
        positional_cache, positional_overflow, kw_cache, kw_overflow = self._stage_bind(*args, **kwargs)

        for v in positional_cache.values():
            self._positional_slots[v['idx']].bind(v['value'])

        self.bound_args = positional_overflow

        for k,v in kw_cache.items():
            self._keyword_addressable[k].bind(v)

        for k,v in kw_overflow.items():
            self.bound_kwargs[k] = v

    def _signature(self):
        parts = []
        for p in self.params:
            _name, _tp, _val, _kind = p.populated
            if _kind == inspect.Parameter.VAR_KEYWORD:
                _name = "**" + _name
            elif _kind == inspect.Parameter.VAR_POSITIONAL:
                _name = '*' + _name

            if _tp == inspect.Parameter.empty:
                parts.append(f'{_name}')
            else:
                parts. append(f'{_name}: {str(_tp.__name__)}')

        body = ', '.join(parts)
        return f'({body})' 

    @property
    def signature(self):
        return self.name + self._signature()

    @property 
    def qualsignature(self):
        return self.qualname + self._signature()
