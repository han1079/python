from typing import Type
class Uniqueness: pass
class Validity: pass
class TypeCheck: pass

class RuleViolation(Exception):
    rule_type: Type = None
    def __class_getitem__(cls, node_or_rule):
        if isinstance(node_or_rule, type):
            # Handle the case where this is a CLASS and therefore reparameterizes
            if cls.rule_type is not None:
                raise AttributeError(f'Class {cls.__name__} already has rule type {cls.rule_type}')

            new_name = f'{node_or_rule.__name__}Violation'
            return type(new_name, (cls,), {'rule_type': node_or_rule})

        else:
            if not hasattr(node_or_rule, 'dagnode_path'):
                try:
                    holder = getattr(node_or_rule, '_holder_node')
                    upath = holder.dagnode_path
                except AttributeError:
                    upath = None 
            else:
                upath = node_or_rule.dagnode_path

            def wrapped_init(detail):
                return cls(detail, upath)
            return wrapped_init
        
    def __init__(self, detail: str, unique_path: tuple[str, ...] = ()) -> None:
        cls_rule_type = type(self).rule_type
        if cls_rule_type is None:
            assert type(self).__name__ == 'RuleViolation'
            rule_name = type(self).__name__
        else:
            rule_name = cls_rule_type.__name__

        if unique_path is not None:
            super().__init__(f'[{rule_name}] at {"::".join([p for p in unique_path])}: {detail}')
        else:
            super().__init__(f'[{rule_name}]: ([Not in Node]) {detail}')

UniquenessViolation = RuleViolation[Uniqueness]
ValidityViolation = RuleViolation[Validity]
TypeCheckViolation = RuleViolation[TypeCheck]
