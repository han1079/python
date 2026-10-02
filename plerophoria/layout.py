from prompt_toolkit.layout.container import Container, to_container, _window_too_small
from prompt_toolkit.layout.dimension import Dimension as Dim
from prompt_toolkit.layout.dimension import to_dimension, sum_layout_dimensions, max_layout_dimensions
from prompt_toolkit.cache import SimpleCache
from prompt_toolkit.key_binding.key_bindings import KeyBindingsBase
from typing import Sequence
from types import MappingProxyType
import dataclasses, enum
from functools import cached_property

class LayoutMode(enum.Enum):
    COLUMN_MAJOR = 'column_major'
    ROW_MAJOR = 'row_major'

@dataclasses.dataclass(frozen=True)
class GridSpec:
    containers: dict[tuple[int, int], Container]
    layout_mode: LayoutMode
    style: str

    def __post_init__(self):
        if not self.containers:
            raise ValueError('No objects to build grid')

        if any(r < 0, c < 0 for r,c in self.containers.keys()):
            raise ValueError('Negative Coordinates not allowed')

        object.__setattr__(self, "containers", MappingProxyType(dict(self.containers)))

        all_rows = {r for r,c in self.containers}
        all_columns = {c for r,c in self.containers}
        expected_rows = set(range(self.total_rows))
        expected_columns = set(range(self.total_columns))

        if not (expected_columns - all_columns) == set():
            raise ValueError(f'Missing Columns {expected_columns - all_columns}')

        if not (expected_rows - all_rows) == set():
            raise ValueError(f'Missing Rows {expected_rows - all_rows}')

    @cached_property
    def total_rows(self) -> int:
        return 1 + max(r for r, c in self.containers.keys())

    @cached_property
    def total_columns(self) -> int:
        return 1 + max(c for r, c in self.containers.keys())

    def get_grid(self):
        cells = [[None] * self.total_columns for _ in range(self.total_rows)]
        for k, v in self.containers.items():
            cells[k[0]][k[1]] = v
        return cells

    def get_row(self, row: int):
        if row < self.total_rows:
            return self.get_grid()[row]

    def get_column(self, col: int):
        if col < self.total_columns:
            return self.get_grid()[col]

    def get_flat(self):
        return [y for x in self.get_grid() for y in x if y is not None]


def to_gridspec(gridspec: dict | GridSpec):
    if isinstance(gridspec, GridSpec):
        return gridspec
    # Implement dict build later
    raise NotImplementedError

class Grid(Container):
    def __init__(self,
                 gridspec: GridSpec | dict,
                 window_too_small: Container | None = None,
                 padding: Dim = Dim.exact(0),
                 padding_char: str | None = None,
                 padding_style: str = ""
                 width: Dim = None,
                 height: Dim = None,
                 z_index: int | None = None,
                 modal: bool = False,
                 key_bindings: KeyBindingsBase | None = None,
                 style: str | Callable[[], str] = "",
                 ) -> None:
        self.gridspec = to_gridspec(gridspec)
        self.children = self.gridspec.get_flat()

        self.window_too_small = window_too_small or _window_too_small()
        self.padding = padding
        self.padding_char = padding_char
        self.padding_style = padding_style

        self.width = width
        self.height = height
        self.z_index = z_index

        self.modal = modal
        self.key_bindings = key_bindings
        self.style = style

    def is_modal(self) -> bool:
        return self.modal

    def get_key_bindings(self) -> KeyBindingsBase | None:
        return self.key_bindings

    def get_children(self) -> list[Container]:
        return self.children

    def _column_cells(self, col_idx): return [c for c in self.gridspec.get_column(col_idx) if c is not None]

    def _row_cells(self, row_idx): return [c for c in self.gridspec.get_row(row_idx) if c is not None]

    def _interleave_buffers(self, dims: list[Dim]) -> list[Dim]:
        buffer = Dim.exact(1)
        interleaved = [buffer] * (2 * len(dims) + 1)
        interleaved[1::2] = dims
        return interleaved

    # --- Constraint Calculations
    def _column_widths(self, max_width: int) -> list[Dim]:
        total_widths = []
        for col_idx in range(self.gridspec.total_columns):
            column_widths = []
            for cell in self._column_cells(col_idx):
                column_widths.append(cell.preferred_width(max_width))
            total_widths.append(max_layout_dimensions(column_widths))
        return total_widths

    def _row_widths_at_idx(self, max_width: int, row_idx) -> list[Dim]:
        cell_widths = []
        for cell in self._row_cells(row_idx):
            cell_widths.append(cell.preferred_width(max_width))
        return cell_widths

    def preferred_width(self, max_available_width: int) -> Dim:
        if self.width is not None:
            return to_dimension(self.width)
        _w = max_available_width

        if self.gridspec.layout_mode == LayoutMode.COLUMN_MAJOR:
            all_col_dims = self._column_widths(_w)
            buffered_cols = self._interleave_buffers(all_col_dims)
            return sum_layout_dimensions(buffered_cols)

        elif self.gridspec.layout_mode == LayoutMode.ROW_MAJOR:
            buffered_row_widths = []
            for row_idx in range(self.gridspec.total_rows):
                row_widths = self._row_widths_at_idx(max_available_width, row_idx)
                total_width = sum_layout_dimensions(self._interleave_buffers(row_widths))
                buffered_row_widths.append(total_width)
            return max_layout_dimensions(buffered_row_widths)

        else:
            raise KeyError(f'{self.gridspec.layout_mode} is not a valid mode')

    def distribute_space(dimensions: list[Dim], total_space: int) -> list[Dim]:
        from prompt_toolkit.utils import take_using_weights
        sizes = [d.min for d in dimensions]
        prefs = [d.preferred for d in dimensions]
        total_size = sum_layout_dimensions(sizes)
        if total_size.min > total_space:
            return None

        # The buffers should have weight zero so they aren't ever incremented
        weighted_dim_distribution = take_using_weights(items=list(range(len(dimensions))), weights=[d.weight for d in dimensions])
        i = next(weighted_dim_distribution)

        while sum(sizes) < min(total_space, total_size.preferred):
            if sizes[i] < prefs[i]:
                sizes[i] += 1
            i = next(weighted_dim_distribution)

        max_dims = [d.max for d in dimensions]

        while sum(sizes) < min(total_space, total_size.max):
            if sizes[i] < max_dims[i]:
                sizes[i] += 1
            i = next(weighted_dim_distribution)

        return sizes
        

    def preferred_height(self, width: int, max_available_height: int) -> Dim:
        if self.height is not None:
            return to_dimension(self.height)


        if self.gridspec.layout_mode == LayoutMode.COLUMN_MAJOR:
            all_col_widths = self.distribute_space(self._column_widths(width), 
                                                   width - self.gridspec.total_columns - 1) 
            total_column_heights = []
            for col_idx in range(self.gridspec.total_columns):
                w = all_col_widths[col_idx]
                col_heights = [c.preferred_height(w) for c in self.gridspec.get_column(col_idx)]
                total_column_heights.append(sum_layout_dimensions(self._interleave_buffers(col_heights)))
                            
            return max_layout_dimensions(total_column_heights)
        elif self.gridspec.layout_mode == LayoutMode.ROW_MAJOR:
            max_row_heights = []
            for row_idx in range(self.gridspec.total_rows):
                row_cells = self._row_cells(row_idx)
                row_pref_widths = [c.preferred_width(width) for c in row_cells]
                row_cell_widths = self.distribute_space(row_pref_widths,
                                                        width - self.gridspec.total_columns - 1)
                heights = [c.preferred_height(w) for c, w in zip(row_cells, row_cell_widths)]
                max_row_heights.append(max_layout_dimensions(heights))

            buffered_rows = self._interleave_buffers(max_row_heights)

            return sum_layout_dimensions(buffered_rows)
        else:
            raise KeyError(f'{self.gridspec.layout_mode} is not a valid mode')



    def _divide_widths(self, width: int) -> list[int] | None:
        
    
