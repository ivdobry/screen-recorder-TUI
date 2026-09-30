# screen-recorder-TUI

A small terminal UI for [wf-recorder](https://github.com/ammen99/wf-recorder) on Wayland (wlroots-based compositors such as niri, Hyprland, Sway). Start a full-screen or region recording and stop it from one screen, with no commands to remember.

Built with [Textual](https://textual.textualize.io/).

## Features

- **Full screen**: records the currently focused monitor (detected via `niri msg` or `hyprctl`; falls back to wf-recorder's default output)
- **Section**: pick an area with `slurp`, then record only that region
- **Stop**: sends `SIGINT` to wf-recorder (the same as Ctrl+C), so the file is closed properly
- Optional audio recording toggle
- Live timer while recording
- Desktop notification with the file path when a recording is saved
- Choose the folder (with folder-name suggestions) and file name for each recording, or keep the defaults: `~/Videos/recording-YYYYMMDD-HHMMSS.mp4`

## Requirements

- Python 3.10+
- [`wf-recorder`](https://github.com/ammen99/wf-recorder)
- [`slurp`](https://github.com/emersion/slurp) (for region selection)
- `notify-send` (optional, from `libnotify`, for desktop notifications)
- `zenity` (optional, for the graphical *Save as* dialog)

On Arch Linux:

```bash
sudo pacman -S wf-recorder slurp libnotify zenity
```

## Installation

```bash
git clone https://github.com/ivdobry/screen-recorder-TUI.git
cd screen-recorder-TUI
./install.sh
```

`install.sh` creates the virtualenv, installs the dependencies and links a `screen-recorder` command into `~/.local/bin`. The link points at your clone, so a `git pull` updates the command too; don't move or delete the folder afterwards.

- Use a different command name: `./install.sh srec`
- Install to another folder: `BIN_DIR=/some/dir ./install.sh`
- Uninstall: `rm ~/.local/bin/screen-recorder`

## Usage

```bash
screen-recorder
```

(or `./run.sh` from the project folder without installing)

| Key | Action       | Command it runs                                  |
|-----|--------------|--------------------------------------------------|
| `F` | Full screen  | `wf-recorder -o <focused output> -f <file>`      |
| `S` | Section      | `wf-recorder -g "$(slurp)" -f <file>`            |
| `X` | Stop         | sends `SIGINT` to wf-recorder                    |
| `A` | Toggle audio | adds `--audio`                                   |
| `B` | Browse       | opens a file dialog to choose folder and name    |
| `Q` | Quit         | stops any active recording first, then exits     |

You can also click the buttons with the mouse.

### Folder and name

- **Save to**: the folder to save into (default `~/Videos`). `~` works, missing folders are created, and a suggested folder name can be accepted with `→`.
- **Name**: the file name. Leave it empty to use `recording-YYYYMMDD-HHMMSS`. `.mp4` is added if you don't give an extension; give one (e.g. `demo.mkv`) to use a different format.
- **Browse [B]** opens your system's *Save as* dialog (via `zenity`) to choose the folder and name. Without zenity, it opens a folder browser inside the terminal instead. Run `./run.sh --no-zenity` to always use the terminal browser.
- If the file already exists, `-1`, `-2`, … is added to the name, so recordings are never overwritten.
- Press `Enter` or `Esc` to leave a text field and use the keyboard shortcuts again.

### Tips

- A full-screen recording includes the terminal running the TUI. Switch to another workspace after starting, or use **Section** to leave it out.
- To stop a recording without going back to the terminal, bind this to a key in your compositor config:

  ```bash
  pkill -INT wf-recorder
  ```

  The TUI notices that the recording ended and still saves and reports the file.

## Configuration

Your settings are saved to `~/.config/screen-recorder-tui/config.json` and restored the next time you start the app:

- **Theme**: press `Ctrl+P` → *Change theme*
- **Save to folder**: the last existing folder you typed or picked with Browse
- **Audio**: whether the audio toggle is on

The file name is not remembered, so each session starts with the timestamp default. To reset everything, delete the config file. The built-in default folder (`~/Videos`) is `OUTPUT_DIR` at the top of `recorder.py`.
