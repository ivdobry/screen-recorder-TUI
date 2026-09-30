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
- Recordings are saved to `~/Videos/recording-YYYYMMDD-HHMMSS.mp4`

## Requirements

- Python 3.10+
- [`wf-recorder`](https://github.com/ammen99/wf-recorder)
- [`slurp`](https://github.com/emersion/slurp) (for region selection)
- `notify-send` (optional, from `libnotify`, for desktop notifications)

On Arch Linux:

```bash
sudo pacman -S wf-recorder slurp libnotify
```

## Installation

```bash
git clone https://github.com/ivdobry/screen-recorder-TUI.git
cd screen-recorder-TUI
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

```bash
./run.sh
```

| Key | Action       | Command it runs                                  |
|-----|--------------|--------------------------------------------------|
| `F` | Full screen  | `wf-recorder -o <focused output> -f <file>`      |
| `S` | Section      | `wf-recorder -g "$(slurp)" -f <file>`            |
| `X` | Stop         | sends `SIGINT` to wf-recorder                    |
| `A` | Toggle audio | adds `--audio`                                   |
| `Q` | Quit         | stops any active recording first, then exits     |

You can also click the buttons with the mouse.

### Tips

- A full-screen recording includes the terminal running the TUI. Switch to another workspace after starting, or use **Section** to leave it out.
- To stop a recording without going back to the terminal, bind this to a key in your compositor config:

  ```bash
  pkill -INT wf-recorder
  ```

  The TUI notices that the recording ended and still saves and reports the file.

## Configuration

To change the output directory, edit `OUTPUT_DIR` at the top of `recorder.py`.
