"""The Recordings tab: a table of recent recordings with action buttons.

The buttons' ids are app action names (play, open_folder, …), so pressing one
runs the same action as its keyboard shortcut.
"""

from datetime import datetime
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Static

from . import system
from .util import human_size, tilde


class RecordingsPane(Vertical):
    DEFAULT_CSS = """
    RecordingsPane { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Static("No recordings yet. Press F or S to make one.", id="empty")
        yield DataTable(id="recent", cursor_type="row", zebra_stripes=True)
        with Horizontal(id="rec-actions"):
            yield Button("▶ Play  [dim]P[/]", id="play")
            yield Button("Folder  [dim]O[/]", id="open_folder")
            yield Button("Copy path  [dim]C[/]", id="copy_path")
            yield Button("Rename  [dim]N[/]", id="rename")
            yield Button("Delete  [dim]D[/]", id="delete")

    def on_mount(self) -> None:
        self.length_column = self.table.add_columns("Name", "Folder", "Length", "Size", "Recorded")[2]

    @property
    def table(self) -> DataTable:
        return self.query_one("#recent", DataTable)

    def show(self, paths: list[Path], select: Path | None = None) -> None:
        table = self.table
        table.clear()
        for path in paths:
            stat = path.stat()
            table.add_row(
                path.name,
                tilde(path.parent),
                "…",  # filled in by fill_lengths
                human_size(stat.st_size),
                f"{datetime.fromtimestamp(stat.st_mtime):%d %b %H:%M}",
                key=str(path),
            )
        empty = not paths
        self.query_one("#empty").display = empty
        table.display = not empty
        for button in self.query("#rec-actions Button"):
            button.disabled = empty
        if select and str(select) in table.rows:
            table.move_cursor(row=table.get_row_index(str(select)))
        self.run_worker(self.fill_lengths(paths), group="lengths", exclusive=True)

    async def fill_lengths(self, paths: list[Path]) -> None:
        for path in paths:
            length = await system.video_length(path)
            if str(path) in self.table.rows:
                self.table.update_cell(str(path), self.length_column, length)

    def selected(self) -> Path | None:
        table = self.table
        if not table.row_count:
            return None
        return Path(table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value)
