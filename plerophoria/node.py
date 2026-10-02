import dataclass
from typing import Optional, Union, NoneType

@dataclasses.dataclass
class Node:
    name: str
    tile: Tile
    children: Optional[set[Node], type(NotImplemented)] = None
    parent: Optional[Node] = None

    @property
    def path(self) -> tuple[str]:
        if self.name == 'root':
            return ('root',)

        if self.parent is None:
            return ('orphaned', name,)

        return parent.path + (name,)

    @property
    def is_configured(self) -> bool:
        return all(x is not None for x in (self.children, self.parent))

    @property
    def is_leaf(self) -> bool:
        return self.children is NotImplemented

    def set_as_leaf(self):
        self.children = NotImplemented

    def set_as_branch(self):
        self.children = set()

    def path_as_string(self) -> str:
        return '::'.join(p for p in path)


def make_sink(node: Node):
    name = node.path_as_string()
    control = UIControl(name, focusable=True)
    window = Window(control, height=Dimension.exact(0))
    return window

    

class Tile:
    def __init__(self, name: str):
        # Create a bijection between tile and node.
        self.node = Node(name=name, tile=self)

        self.sink = make_sink(self.node.path)
        self.container: Optional[Container] = None

        self._axis: Optional[str] = None
        self._style: Optional[str] = None

    @property
    def is_configured(self):
        return all(attr is not NotImplemented for attr in (
            self.node, self.children, self.parent
            ))

    def __pt_container__(self):


    # Construction
    def _configure_as_holder(self):
        assert all(x is NotImplemented for x in (self.children, ))

        if self.children is NotImplemented:
            self.children = []

    def _configure_as_leaf(self):
        if isinstance(self.children, list):
            raise RuntimeError(f'self.children is already configured as non-leaf')

        if self.children is NotImplemented:
            self.children = None

    def set_yaxis(self):
        self._axis = 'y'
        if self.children is NotImplemented:
            self.children = []

    def set_xaxis(self):
        self._axis = 'x'



