"""Pop-up dialogs: folder browser, rename and delete confirmation."""

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Input, Label


class FolderPicker(ModalScreen[Path | None]):
    """In-terminal folder browser, used when no graphical file dialog is available."""

    CSS = """
    FolderPicker { align: center middle; }
    #picker { width: 80%; height: 80%; border: round $accent; background: $surface; padding: 0 1; }
    #picker DirectoryTree { height: 1fr; }
    #picker Horizontal { height: auto; align-horizontal: right; }
    #picker Button { margin: 0 1; }
    """
    BINDINGS = [("escape", "dismiss(None)", "Cancel")]

    class FoldersOnly(DirectoryTree):
        def filter_paths(self, paths):
            return [p for p in paths if p.is_dir() and not p.name.startswith(".")]

    def __init__(self, start: Path) -> None:
        super().__init__()
        self.selected = start

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Label(f"Choose a folder: [cyan]{self.selected}[/]", id="current")
            yield self.FoldersOnly(Path.home(), id="tree")
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Select", id="select", variant="primary")

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        self.selected = event.path
        self.query_one("#current", Label).update(f"Choose a folder: [cyan]{event.path}[/]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(self.selected if event.button.id == "select" else None)


class RenameScreen(ModalScreen[str | None]):
    CSS = """
    RenameScreen { align: center middle; }
    #dialog { width: 60; height: auto; border: round $accent; background: $surface; padding: 1 2; }
    #dialog Input { margin: 1 0; }
    #dialog Horizontal { height: auto; align-horizontal: right; }
    #dialog Button { margin-left: 1; }
    """
    BINDINGS = [("escape", "dismiss(None)", "Cancel")]

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"Rename [b]{self.path.name}[/]")
            yield Input(self.path.stem, id="new-name")
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Rename", id="ok", variant="primary")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        value = self.query_one("#new-name", Input).value.strip()
        self.dismiss(value or None if event.button.id == "ok" else None)


class ConfirmDelete(ModalScreen[bool]):
    CSS = """
    ConfirmDelete { align: center middle; }
    #dialog { width: 60; height: auto; border: round $error; background: $surface; padding: 1 2; }
    #dialog Horizontal { height: auto; align-horizontal: right; margin-top: 1; }
    #dialog Button { margin-left: 1; }
    """
    BINDINGS = [("escape,n", "dismiss(False)", "Cancel"), ("y", "dismiss(True)", "Delete")]

    def __init__(self, path: Path, to_trash: bool) -> None:
        super().__init__()
        self.path, self.to_trash = path, to_trash

    def compose(self) -> ComposeResult:
        what = "Move to Trash" if self.to_trash else "Permanently delete"
        with Vertical(id="dialog"):
            yield Label(f"{what} [b]{self.path.name}[/]?")
            with Horizontal():
                yield Button("Cancel  [dim]N[/]", id="cancel")
                yield Button("Delete  [dim]Y[/]", id="ok", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "ok")
