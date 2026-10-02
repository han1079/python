"""loader -- build a DAGNode tree from an app_config.json-shaped spec.

Uniform call structure: `node_class` is always resolved and either
instantiated directly ("the element is literally just the object being
generated wholesale") or, when `factory` is set, the factory's return value
flows into `node_class` (currently: wrapped as a FacadeNode instance -- the
only shape any real factory in this config produces today). `dependents`
recurses the same way, installed under the node just built.
"""
import importlib
import logging
import json
import pathlib
import dataclasses
from dataclasses import field
from typing import Optional, Callable

from lazybench.core.facade import FacadeNode
from lazybench.core.node import DAGNode, RootNode
from lazybench.tasks.scheduler import TaskNode

_PACKAGE_ROOT = 'lazybench'
logger = logging.getLogger(__file__)


def get_module_attr_from_path(path: str) -> object:
    """Expect lazybench.core.node.Registry
                                   ^^^^^^   ^^^^^
                                   module   class
    """
    module_path, sep, class_name = path.rpartition('.')
    if not sep:
        raise ValueError(f'{dotted_path!r} has no module component')
    m = importlib.import_module(f"{_PACKAGE_ROOT}.{module_path}")
    attr = getattr(m, class_name)
    return attr 

@dataclasses.dataclass
class NodeSpec:
    node_name: str = field(default = None)
    unique_path: tuple[str] = field(default_factory = tuple)
    node_class: type = field(default = None)
    factory: Optional[Callable] = field(default = None)
    nested_config: Optional[dict] = field(default=None)
    resources: list[str] = field(default = None)
    children: list['NodeSpec'] = field(default = None)
    node: Optional[DAGNode] = field(default = None)
    kwargs: Optional[dict] = field(default=None)
    node_autogen_path: Optional[str] = field(default=None)
    leaf_gen: Optional[Callable] = field(default=None)

    def make_node(self):
        logger.debug(f"making node: {self.node_class}")
        if self.kwargs is None:
            self.kwargs = {}

        if not self.node:
            if self.factory:
                if self.node_class is FacadeNode:
                    if isinstance(self.factory, type):
                        obj = self.factory()
                        self.node = self.node_class(instance=obj, name=self.node_name)

                    else:
                        self.node = self.factory(cls=self.node_class, name=self.node_name)
                elif self.node_class is TaskNode:
                    period = self.kwargs.get('period') or 5.0
                    self.node = self.node_class(fn = self.factory, name=self.node_name, period=period)

            else:
                if self.node_class is RootNode:
                    if self.node_class.get() is None:
                        self.node_class()
                        self.node = self.node_class.get()
                    else:
                        self.node = self.node_class.get()
                else:
                    self.node = self.node_class(name=self.node_name)

        return self.node

def get_local_spec(node, node_name, parent_path, all_nodes):
    node_class_path = node.get('node_class')
    factory_function_path = node.get('factory')
    resource_names = node.get('resources')
    _install = node.get('install')
    node_autogen_path = _install.get('by_factory')
    nested_config = _install.get('by_config')
    kwargs = node.get('kwargs')

    ls = NodeSpec()
    ls.node_name = node_name
    ls.unique_path = parent_path + (node_name,)
    all_nodes.add(ls.unique_path)
    ls.resources = resource_names
    ls.nested_config = nested_config
    ls.children = []
    ls.kwargs = kwargs
    ls.node_autogen_path = node_autogen_path

    ls.node_class = get_module_attr_from_path(node_class_path)
    
    if factory_function_path is None:
        ls.factory = None
    else:
        ls.factory = get_module_attr_from_path(factory_function_path)

    if node_autogen_path is None:
        ls.leaf_gen = lambda: None
    else:
        _leaf_gen = get_module_attr_from_path(node_autogen_path)
        def wrapped_gen():
            return _leaf_gen(ls)
        ls.leaf_gen = wrapped_gen

    return ls


def wire_tree(parent, nodespec, already_installed):
    """Breadth first to wire up everything with no non-tree deps"""
    logger.debug(f"Wiring tree for {nodespec.node_name}")
    logger.debug(f'Already Installed at start of call: {already_installed}')
    obj = nodespec.make_node()

    if nodespec.resources is not None\
        and set(nodespec.resources).issubset(already_installed)\
        and nodespec.unique_path not in already_installed:
        for resource_path in nodespec.resources:
            obj.set_resources(RootNode.find_node(resource_path))

    if obj.dagnode_name == 'root':
        successful_install = True
    else:
        if nodespec.unique_path not in already_installed:
            if 'default_activate' in nodespec.kwargs:
                successful_install = parent.install(obj, default_activate=nodespec.kwargs['default_activate'])
            else:
                successful_install = parent.install(obj)
        else:
            successful_install = True

    if successful_install:
        already_installed.add(obj.dagnode_path)
        if 'expose' in nodespec.kwargs:
            exposed_names = nodespec.kwargs.get('expose')
            if exposed_names:
                for n in exposed_names:
                    obj.expose_name(n)
        nodespec.leaf_gen()

        for ch in nodespec.children:
            wire_tree(obj, ch, already_installed)

    logger.debug(f'Already Installed at end of call: {already_installed}')
    return already_installed

def build_tree(root, name, unique_path, all_nodes):
    local_spec = get_local_spec(root, name, unique_path, all_nodes)
    if local_spec.nested_config is None:
        return local_spec
    for k,v in local_spec.nested_config.items():
        child_spec = build_tree(v, k, local_spec.unique_path, all_nodes)
        if child_spec:
            local_spec.children.append(child_spec)
    return local_spec

def locate_resource_paths(node, all_node_paths):
    resources = node.resources
    if resources is None: resources = []
    # Accumulate across every requested name -- reassigning node.resources
    # inside the loop (the previous shape) discarded all but the LAST
    # resource's matches, so any node with more than one resource silently
    # lost every earlier one (e.g. instruments' 3-name list resolved to just
    # the last of the three).
    resolved = []
    for res in resources:
        matches = []
        for node_path in all_node_paths:
            if res == node_path[-1]:
                matches.append(node_path)
        assert len(matches) == len(set(matches))
        resolved.extend(matches)
    node.resources = resolved

    for child in node.children:
        locate_resource_paths(child, all_node_paths)

def gather_all_configured_names(spec):
    all_resource_names = []
    for k,v in spec.items():
        all_resource_names.append(k)
        nested_config = v['install']['by_config']
        if nested_config:
            all_resource_names.extend(gather_all_configured_names(nested_config))
    return all_resource_names

def build_config(path: pathlib.Path) -> DAGNode:
    with open(path) as f:
        spec = json.load(f)

    if spec is None:
        raise Exception(f"Configuration not loaded properly")

    # No two names should be the same. This way, resource name can unambiguously
    # pick out a specific node in the configuration.
    all_names = gather_all_configured_names(spec)
    assert len(all_names) == len(set(all_names))

    all_nodes = set()
    tree_root = build_tree(spec['root'], 'root', (), all_nodes)
    locate_resource_paths(tree_root, all_nodes)
    logger.debug(all_nodes)
    already_installed = set()
    already_installed.add(('root',))
    while already_installed != all_nodes:
        already_installed = wire_tree(None, tree_root, already_installed)

    return tree_root.node

