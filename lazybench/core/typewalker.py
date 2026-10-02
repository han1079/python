from typing import get_origin, get_args
from typing import Union, Optional, Literal, Any
from types import UnionType, NoneType
from lazybench.app.ux.prompter import CannedPrompter
from lazybench.app.ux.prompter import InquirerPrompter
from lazybench.app.ux.prompter import Prompter, ConfirmType
from lazybench.core.core import MonitorMe
import enum
import dataclasses
from dataclasses import field
from collections.abc import Collection, Hashable
import builtins
import inspect

empty = inspect.Parameter.empty
iprompt = InquirerPrompter()
Prompter.set(iprompt)

@dataclasses.dataclass
class TypeHint:
    outer: object
    inner: tuple = field(default_factory=tuple)
    nested_args: tuple = field(default_factory=tuple)

class TypeTree:
    __hash__ = object.__hash__

    def _make_data_cb(self, typehint, prompt_detail='', check_hashable=False):
        if isinstance(typehint, type) and issubclass(typehint, enum.Enum):
            return lambda: Prompter.select(f'Select a valid Enum Entry:', list(typehint))

        if typehint == Ellipsis:
            if check_hashable:
                raise Exception(f"Needs hashable, but using Ellipsis!")
            return lambda: Prompter.log('Ellipses are skipped!')

        data = lambda: Prompter.text(f'{prompt_detail}- Enter a {typehint.__name__}', result_cast=typehint)
        return data

    def _make_cb(self, outer_typehint, leaves, check_hashable=False, prompt_detail=''):
        # Assert this so we have inputs normalized
        if outer_typehint == Any or outer_typehint == empty:
            # Should not have any nested_cbss here.
            if check_hashable:
                raise Exception(f"Needs hashable, but got wildcard!")
            assert(len(leaves) == 0), f'{leaves}'
            return self._make_data_cb(str, prompt_detail=f'{prompt_detail}' + 'Got no data type', check_hashable=check_hashable)

        if outer_typehint == NoneType:
            if check_hashable:
                raise Exception(f"Needs hashable, random NoneType!")
            return lambda: None

        if outer_typehint == dict:
            if check_hashable:
                raise Exception(f"Needs hashable, but dict is not hashable")
            # Dicts need 2 nested_cbss
            assert(len(leaves) == 2), f'{leaves}'
            key_leaf = leaves[0]
            val_leaf = leaves[1]
            key_cb = self._make_cb(key_leaf.label, key_leaf.children, check_hashable=True, prompt_detail=f'{prompt_detail}' + '[DictKey]')
            val_cb = self._make_cb(val_leaf.label, val_leaf.children, check_hashable=check_hashable, prompt_detail=f'{prompt_detail}' + '[DictVal]')
            def handle_dict():
                Prompter.log("Handling Dict")
                nelem = Prompter.text(f'Number of elements in {prompt_detail}{[outer_typehint.__name__]}?', result_cast=int)
                
                dict_rtn = {}
                for i in range(nelem):
                    k = key_cb()
                    v = val_cb()
                    dict_rtn[k] = v

                return dict_rtn

            return handle_dict

        if outer_typehint in (Union, UnionType):
            if NoneType in [leaf.label for leaf in leaves]:
                valid_leaves = [leaf for leaf in leaves if leaf.label != NoneType]
                cb = self._make_cb(Union, valid_leaves, check_hashable=check_hashable, prompt_detail=f'{prompt_detail}')
                def handle_optional():
                    if len(valid_leaves) == 1:
                        cont = Prompter.confirm(f'Type wanted is {valid_leaves[0].label.__name__}. Is Optional. Continue?', ConfirmType.CONTINUE, default=False)
                    else:
                        cont = Prompter.confirm(f'Types wanted are {[leaf.label.__name__ for leaf in valid_leaves]}. Is Optional.\n Continue?', ConfirmType.CONTINUE, default=False)
                    if cont:
                        return cb()
                    else:
                        return None
                return handle_optional
            else:
                nested_cbs_selectable = {leaf.label.__name__: self._make_cb(leaf.label, leaf.children, check_hashable=check_hashable, prompt_detail=f'{prompt_detail}') for leaf in leaves}
                def handle_union():
                    selected_cb = Prompter.select(f'Multiple Types available for {prompt_detail}. Choose:', nested_cbs_selectable)
                    if not callable(selected_cb):
                        raise Exception(f'Got {selected_cb}. Is type {type(selected_cb)}, but expected Callable.')
                    return selected_cb()
                return handle_union

        if outer_typehint in (tuple, frozenset):
            variadic_cbs = [self._make_cb(leaf.label, leaf.children, check_hashable=check_hashable, prompt_detail=f'{prompt_detail}' + f'{[outer_typehint.__name__]}') for leaf in leaves]
            def handle_tuple():
                nelem = Prompter.text(f'Number of elements in {prompt_detail}{[outer_typehint.__name__]}?', result_cast=int)
                
                tup_data = [] 
                for i in range(nelem):
                    tup_elem = ()
                    for idx, fn in enumerate(variadic_cbs):
                        if len(variadic_cbs) > 1:
                            Prompter.log(f'{prompt_detail}[{outer_typehint.__name__}] variadic: ({tuple([leaves[i].label.__name__ for i in range(len(variadic_cbs))])}).\n Populating slot {idx+1}/{len(variadic_cbs)}: {leaves[idx].label.__name__}')
                        else:
                            Prompter.log(f'{prompt_detail}[{outer_typehint.__name__}] not variadic. Uses {leaves[idx].label.__name__}')
                        tup_elem += (fn(),)
                    tup_data.append(tup_elem)

                return outer_typehint(tup_data)
            return handle_tuple

        if issubclass(outer_typehint, Collection) and outer_typehint != str:
            with MonitorMe(hook=outer_typehint):
                if check_hashable and not self._is_hashable(outer_typehint):
                    raise Exception(f'Needs hashable!')
            cbs = [self._make_cb(leaf.label, leaf.children, check_hashable=check_hashable, prompt_detail=f'{prompt_detail}' + f'[{outer_typehint.__name__}]') for leaf in leaves]
            assert len(cbs) == 1
            cb = cbs[0]
            def handle_list_like():
                nelem = Prompter.text(f'Number of elements in {prompt_detail}{[outer_typehint.__name__]}?', result_cast=int)
                
                listlike_data = []
                for i in range(nelem):
                    listlike_data.append(cb())

                return outer_typehint(listlike_data)
            return handle_list_like

        if hasattr(builtins, outer_typehint.__name__):
            with MonitorMe(hook=outer_typehint.__name__):
                return self._make_data_cb(outer_typehint, check_hashable=check_hashable, prompt_detail=f'{prompt_detail}')

        raise TypeError(f"Got O, A: {outer_typehint}, {leaves}. Slipped through")

    def _peel_once(self, typehint):
        _o = get_origin(typehint) 
        _a = get_args(typehint)

        if _o is None:
            return TypeHint(outer=typehint, inner=(), nested_args=())
        else:
            nest = [self._peel_once(arg) for arg in _a]

            return TypeHint(outer=_o, inner=tuple([tp.outer for tp in nest]), nested_args=_a)

    def __init__(self, typehint, parent='root'):
        self.parent = parent
        self.children = []
        self.label = None

        self.prompt_cb = None
        tp = self._peel_once(typehint)

        if tp.inner is None:
            # Should be impossible for args here to by_anything other than len < 1
            self.label = typehint
            assert(len(tp.outer) <= 1), f'{tp.outer}'
            self.prompt_cb = self._make_data_cb(typehint)

        else:
            self.label = tp.outer
            if self._is_collection_like(tp.outer) and tp.inner == ():
                # No type is given. Placeholder is to just defaulting to string.
                self.children = [(TypeTree(Any, parent=self))]
            else:
                self.children = [TypeTree(self._at_idx(tp.nested_args,i), parent=self) for i in range(len(tp.nested_args))]

            self.prompt_cb = self._make_cb(tp.outer, self.children)

        self.tp = tp

    def _is_collection_like(self, origin):
        try:
            return issubclass(origin, Collection)
        except Exception:
            return False
        
    def _at_idx(self, l: list, idx:int, default=empty):
        try:
            return l[idx]
        except IndexError:
            return default

    def _is_hashable(self, x):
        if isinstance(type(x), type):
            return issubclass(x, Hashable)

        try:
            hash(x)
        except TypeError:
            return False

def prompt_for_type(typehint):
    tree = TypeTree(typehint)
    return tree.prompt_cb()

